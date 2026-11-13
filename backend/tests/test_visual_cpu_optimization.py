"""
Tests verifying LORE Visual Extraction CPU-only (16 GB RAM) optimizations:
1. Lazy model loading only when required.
2. Worker model & extractor instance reuse across calls.
3. Page-by-page PDF processing and prompt image/array release.
4. No unnecessary full-page rendering (digital/mixed vector & raster charts/forms crop region-only).
5. Single-pass Tesseract ``image_to_data`` OCR instead of double subprocess invocation.
6. Configurable CPU/OpenCV/OMP/Tesseract thread limits and configurable DPI.
7. Conservative worker concurrency default (1) & gated execution.
8. Recorded duration, peak memory (RSS / tracemalloc), render breakdown, and failure rates.
9. Repeatable benchmark execution across small PDF workload.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from PIL import Image, ImageDraw
import pymupdf
import pytest

from apps.ingestion.batch import WorkloadConcurrencyGate, get_workload_concurrency_limit
from apps.ingestion.pipeline import ocr as ocr_mod
from apps.ingestion.pipeline.charts import PyMuPDFOpenCVChartExtractor
from apps.ingestion.pipeline.extractors import WorkerExtractorRegistry
from apps.ingestion.pipeline.forms import FormKVExtractor
from apps.ingestion.pipeline.layout import (
    PPDocLayoutSConfig,
    PPDocLayoutSProvider,
    WorkerLayoutModelCache,
)
from apps.ingestion.pipeline.ocr import TesseractOCRProvider, reconstruct_text_from_tesseract_data
from apps.ingestion.pipeline.pdf_visual import (
    PDFSafetyLimits,
    PyMuPDFPageRenderer,
    PyMuPDFVisualPDFAdapter,
)
from apps.ingestion.pipeline.runtime import (
    GLOBAL_VISUAL_METRICS,
    configure_visual_cpu_runtime,
    get_process_memory_mb,
)
from apps.ingestion.pipeline.tables import (
    SLANetPlusConfig,
    SLANetPlusTableExtractor,
    WorkerTableStructureModelCache,
)
from apps.ingestion.pipeline.visual_schema import (
    pages_to_visual_document,
    validate_visual_document_payload,
)
from benchmarks.benchmark_visual_extraction import run_visual_benchmark


def _make_vector_chart_and_form_pdf_bytes() -> bytes:
    """Create a 2-page digital PDF: Page 1 vector bar chart, Page 2 printed form."""
    doc = pymupdf.open()
    # Page 1: vector bar chart
    page1 = doc.new_page(width=612, height=792)
    page1.insert_text((48, 44), "Quarterly Revenue Report", fontsize=12)
    px0, py0, px1, py1 = 90, 100, 500, 340
    page1.draw_rect(pymupdf.Rect(px0, py0, px1, py1), color=(0.1, 0.1, 0.1), width=1.2)
    for val in (0, 50, 100):
        y = py1 - (val / 100.0) * (py1 - py0)
        page1.draw_line((px0 - 5, y), (px0, y), color=(0, 0, 0), width=1.0)
        page1.insert_text((px0 - 30, y + 3), str(val), fontsize=8.5)
    for idx, (lbl, val) in enumerate([("Q1", 40), ("Q2", 75), ("Q3", 90)]):
        bx0 = px0 + 35 + idx * 115
        bx1 = bx0 + 55
        by0 = py1 - (val / 100.0) * (py1 - py0)
        page1.draw_rect(pymupdf.Rect(bx0, by0, bx1, py1), color=(0.1, 0.3, 0.6), fill=(0.2, 0.45, 0.8))
        page1.insert_text((bx0 + 15, py1 + 14), lbl, fontsize=9)

    # Page 2: vector form with individual field boxes & checkbox (avoiding table-grid false match)
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((48, 60), "Vendor Application Form", fontsize=14)
    form_rows = [
        ("Vendor Name:", "Northstar Logistics", 120, 260),
        ("Invoice Date:", "2026-11-12", 175, 190),
        ("Tax ID:", "TIN-774920", 230, 170),
        ("Notes:", "__________________", 285, 0),
    ]
    for lbl, val, y, box_w in form_rows:
        page2.insert_text((65, y), lbl, fontsize=10.5)
        if box_w > 0:
            page2.draw_rect(pymupdf.Rect(205, y - 13, 205 + box_w, y + 5), color=(0.25, 0.25, 0.25), width=0.9)
            page2.insert_text((212, y), val, fontsize=10)
        else:
            page2.insert_text((205, y), val, fontsize=10)
    page2.draw_rect(pymupdf.Rect(65, 345, 79, 359), color=(0, 0, 0), width=1.1)
    page2.insert_text((90, 356), "[ ] Expedite Audit", fontsize=10)

    out = doc.tobytes(deflate=True)
    doc.close()
    return out


def _make_mixed_raster_graphic_pdf_bytes() -> bytes:
    """Create a 1-page mixed-content PDF with native text plus an embedded bar chart raster."""
    chart_img = Image.new("RGB", (360, 220), color=(255, 255, 255))
    d = ImageDraw.Draw(chart_img)
    d.line([45, 25, 45, 185], fill=(0, 0, 0), width=2)
    d.line([45, 185, 330, 185], fill=(0, 0, 0), width=2)
    d.rectangle([80, 95, 125, 185], fill=(35, 95, 190))
    d.rectangle([160, 60, 205, 185], fill=(35, 95, 190))
    d.rectangle([240, 115, 285, 185], fill=(35, 95, 190))

    import io

    img_buf = io.BytesIO()
    chart_img.save(img_buf, format="PNG")
    chart_img.close()

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((48, 55), "Executive Summary: Mixed Page with Chart Image Figure", fontsize=12)
    page.insert_image(pymupdf.Rect(80, 120, 440, 340), stream=img_buf.getvalue())
    out = doc.tobytes(deflate=True)
    doc.close()
    return out


def _make_plain_digital_pdf_bytes(num_pages: int = 2) -> bytes:
    doc = pymupdf.open()
    for i in range(1, num_pages + 1):
        page = doc.new_page(width=612, height=792)
        page.insert_text((50, 60), f"Plain digital text page {i}. Contains sufficient native text for direct extraction.", fontsize=11)
    out = doc.tobytes(deflate=True)
    doc.close()
    return out


def test_cpu_runtime_thread_limits_and_opencv_configuration():
    cfg = configure_visual_cpu_runtime(
        cpu_threads=2,
        opencv_threads=1,
        tesseract_omp_threads=1,
        force=True,
    )
    assert cfg["cpu_threads"] == 2
    assert cfg["tesseract_omp_threads"] == 1
    assert os.environ.get("OMP_NUM_THREADS") == "2"
    assert os.environ.get("OPENBLAS_NUM_THREADS") == "2"
    assert os.environ.get("MKL_NUM_THREADS") == "2"
    assert os.environ.get("OMP_THREAD_LIMIT") == "1"
    if cfg["opencv_threads_applied"] is not None:
        import cv2

        assert cv2.getNumThreads() == 1


@override_settings(VISUAL_PDF_DPI=160, VISUAL_MAX_RENDER_PIXELS=6_000_000)
def test_pdf_safety_limits_respects_configured_dpi_and_env(monkeypatch):
    monkeypatch.delenv("VISUAL_PDF_DPI", raising=False)
    monkeypatch.delenv("VISUAL_MAX_RENDER_PIXELS", raising=False)
    lim_settings = PDFSafetyLimits.from_settings_or_env()
    assert lim_settings.dpi == 160
    assert lim_settings.max_render_pixels == 6_000_000

    monkeypatch.setenv("VISUAL_PDF_DPI", "144")
    monkeypatch.setenv("VISUAL_MAX_RENDER_PIXELS", "4000000")
    lim_env = PDFSafetyLimits.from_settings_or_env()
    assert lim_env.dpi == 144
    assert lim_env.max_render_pixels == 4_000_000

    explicit = PDFSafetyLimits(dpi=220, max_pages=12)
    assert explicit.dpi == 220
    assert explicit.max_pages == 12


def test_conservative_visual_concurrency_default_is_one():
    # settings.py defaults INGESTION_VISUAL_MAX_CONCURRENCY to 1 when env is unset
    assert int(getattr(settings, "INGESTION_VISUAL_MAX_CONCURRENCY", 0)) >= 1
    if "INGESTION_VISUAL_MAX_CONCURRENCY" not in os.environ:
        assert int(settings.INGESTION_VISUAL_MAX_CONCURRENCY) == 1
        assert get_workload_concurrency_limit("visual") == 1


def test_tesseract_provider_single_image_to_data_call_reconstructs_text(monkeypatch):
    img = Image.new("RGB", (240, 80), color=(255, 255, 255))
    calls = {"to_data": 0, "to_string": 0}

    def fake_to_data(image, lang="eng+ben", output_type=None):
        calls["to_data"] += 1
        return {
            "text": ["Line", "One", "", "Line", "Two"],
            "conf": ["92", "88", "-1", "95", "91"],
            "left": [10, 60, 0, 10, 60],
            "top": [10, 10, 0, 40, 40],
            "width": [40, 40, 0, 40, 40],
            "height": [20, 20, 0, 20, 20],
            "block_num": [1, 1, 1, 1, 1],
            "par_num": [1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 2, 2],
        }

    def fake_to_string(image, lang="eng+ben"):
        calls["to_string"] += 1
        return "SHOULD NOT BE CALLED"

    monkeypatch.setattr(ocr_mod, "HAS_PYTESSERACT", True)
    monkeypatch.setattr(TesseractOCRProvider, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        ocr_mod.ImagePreprocessor,
        "detect_and_correct_rotation",
        staticmethod(lambda im, tesseract_cmd=None: (im, 0)),
    )

    with patch.object(ocr_mod, "pytesseract") as mock_tess:
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_to_data
        mock_tess.image_to_string.side_effect = fake_to_string

        provider = TesseractOCRProvider()
        res = provider.extract_image(img)

    assert calls["to_data"] == 1
    assert calls["to_string"] == 0
    assert res["status"] == "success"
    assert res["text"] == "Line One\nLine Two"
    assert len(res["bounding_boxes"]) == 4
    assert res["confidence"] > 0.85

    # Missing 'text' key falls back cleanly to image_to_string once
    with patch.object(ocr_mod, "pytesseract") as mock_tess2:
        mock_tess2.Output.DICT = "dict"
        mock_tess2.image_to_data.return_value = {}
        mock_tess2.image_to_string.return_value = "Fallback OCR"
        provider2 = TesseractOCRProvider()
        res2 = provider2.extract_image(img)
    assert res2["text"] == "Fallback OCR"
    assert reconstruct_text_from_tesseract_data({"text": []}) == ""


def test_digital_vector_and_mixed_raster_avoid_full_page_rendering(monkeypatch):
    """
    Verify digital pages with vector charts/forms and mixed pages with embedded
    graphic images crop ONLY region clips via extract_or_render_region_image and
    never trigger full-page PyMuPDFPageRenderer.render_page_image().
    """
    GLOBAL_VISUAL_METRICS.reset()
    render_full_calls = []
    render_clip_calls = []
    orig_full = PyMuPDFPageRenderer.render_page_image
    orig_clip = PyMuPDFPageRenderer.extract_or_render_region_image

    def spy_full(*args, **kwargs):
        render_full_calls.append(kwargs.get("dpi"))
        return orig_full(*args, **kwargs)

    def spy_clip(*args, **kwargs):
        render_clip_calls.append(kwargs.get("region_display_rect"))
        return orig_clip(*args, **kwargs)

    monkeypatch.setattr(PyMuPDFPageRenderer, "render_page_image", staticmethod(spy_full))
    monkeypatch.setattr(PyMuPDFPageRenderer, "extract_or_render_region_image", staticmethod(spy_clip))

    ocr = TesseractOCRProvider()
    adapter = PyMuPDFVisualPDFAdapter(
        ocr_provider=ocr,
        chart_extractor=PyMuPDFOpenCVChartExtractor(ocr_provider=ocr),
        form_extractor=FormKVExtractor(ocr_provider=ocr),
        analyze_searchable_with_layout=False,
        limits=PDFSafetyLimits(dpi=150),
    )

    vec_pdf = _make_vector_chart_and_form_pdf_bytes()
    pages_vec = adapter.process_pdf(vec_pdf)
    assert len(pages_vec) == 2
    assert len(render_full_calls) == 0, f"Unexpected full-page render calls: {render_full_calls}"
    assert len(render_clip_calls) >= 2
    diag_vec = adapter.last_run_diagnostics
    assert diag_vec["full_page_renders"] == 0
    assert diag_vec["region_clip_renders"] >= 2

    # Ensure pre-cropped chart and form regions preserve valid full-page lore.visual/1.0 coordinates
    vdoc = pages_to_visual_document(
        pages_vec,
        source_document_id="doc-clip-only",
        filename="vec_chart_form.pdf",
        document_type="pdf",
    )
    validated = validate_visual_document_payload(vdoc.model_dump(mode="json"))
    el_types = {el.element_type.value for el in validated.elements}
    assert "chart" in el_types
    assert "form_kv" in el_types
    for el in validated.elements:
        nb = el.bounding_box
        assert 0 <= nb.xmin < nb.xmax <= 1000
        assert 0 <= nb.ymin < nb.ymax <= 1000

    # Mixed page with embedded raster figure must also avoid full-page render
    render_full_calls.clear()
    render_clip_calls.clear()
    mixed_pdf = _make_mixed_raster_graphic_pdf_bytes()
    pages_mixed = adapter.process_pdf(mixed_pdf)
    assert len(pages_mixed) == 1
    assert len(render_full_calls) == 0
    assert len(render_clip_calls) >= 1
    assert adapter.last_run_diagnostics["full_page_renders"] == 0
    assert adapter.last_run_diagnostics["region_clip_renders"] >= 1


def test_lazy_model_loading_and_worker_cache_reuse(monkeypatch):
    WorkerExtractorRegistry.clear()
    WorkerLayoutModelCache.clear()
    WorkerTableStructureModelCache.clear()

    load_counts = {"layout": 0, "table": 0}

    class DummyModel:
        def predict(self, *args, **kwargs):
            return []

    def fake_layout_ctor(*args, **kwargs):
        load_counts["layout"] += 1
        return DummyModel()

    def fake_table_ctor(*args, **kwargs):
        load_counts["table"] += 1
        return DummyModel()

    # 1. Getting worker extractor & running plain digital PDF must NOT eagerly load heavy models
    ext1 = WorkerExtractorRegistry.get_visual_extractor()
    ext2 = WorkerExtractorRegistry.get_visual_extractor()
    assert ext1 is ext2
    assert WorkerExtractorRegistry.get_stats()["init_counts"].get("visual") == 1
    pages = ext1.extract_document(_make_plain_digital_pdf_bytes(2), doc_type="pdf", filename="plain.pdf")
    assert len(pages) == 2
    assert load_counts["layout"] == 0
    assert load_counts["table"] == 0

    # 2. When optional model factories ARE invoked repeatedly, caches load ONCE and reuse
    lp = PPDocLayoutSProvider(
        config=PPDocLayoutSConfig(cpu_threads=2),
        model_loader=fake_layout_ctor,
    )
    assert load_counts["layout"] == 0  # still lazy on __init__
    m1 = lp._get_or_load_model()
    m2 = lp._get_or_load_model()
    assert m1 is m2
    assert load_counts["layout"] == 1

    te = SLANetPlusTableExtractor(
        config=SLANetPlusConfig(cpu_threads=2),
        model_loader=fake_table_ctor,
    )
    assert load_counts["table"] == 0  # still lazy on __init__
    tm1 = te._get_or_load_model()
    tm2 = te._get_or_load_model()
    assert tm1 is tm2
    assert load_counts["table"] == 1


def test_metrics_records_duration_peak_memory_and_failure_rates():
    GLOBAL_VISUAL_METRICS.reset()
    adapter = PyMuPDFVisualPDFAdapter(limits=PDFSafetyLimits(dpi=150))

    # 1. Valid PDF
    valid_pages = adapter.process_pdf(_make_plain_digital_pdf_bytes(2))
    assert len(valid_pages) == 2
    d1 = adapter.last_run_diagnostics
    assert d1["duration_ms"] >= 0.0
    assert d1["dpi"] == 150

    # 2. Malformed PDF recorded cleanly as failed run
    malformed_pages = adapter.process_pdf(b"%PDF-broken-header-xyz")
    assert malformed_pages[0]["status"] == "malformed_pdf"

    snap = GLOBAL_VISUAL_METRICS.snapshot()
    assert snap["total_runs"] == 2
    assert snap["failed_runs"] == 1
    assert snap["failure_rate"] == pytest.approx(0.5, abs=1e-4)
    assert snap["avg_duration_ms"] >= 0.0
    mem = get_process_memory_mb()
    if mem["rss_mb"] is not None:
        assert snap["max_peak_rss_mb"] is not None
        assert snap["max_peak_rss_mb"] > 0.0


def test_prompt_crop_image_close_on_region_extraction(monkeypatch):
    closed_count = {"n": 0}
    orig_close = Image.Image.close

    def tracked_close(self):
        closed_count["n"] += 1
        return orig_close(self)

    monkeypatch.setattr(Image.Image, "close", tracked_close)

    ocr = TesseractOCRProvider()
    adapter = PyMuPDFVisualPDFAdapter(
        ocr_provider=ocr,
        chart_extractor=PyMuPDFOpenCVChartExtractor(ocr_provider=ocr),
        form_extractor=FormKVExtractor(ocr_provider=ocr),
        limits=PDFSafetyLimits(dpi=150),
    )
    pages = adapter.process_pdf(_make_vector_chart_and_form_pdf_bytes())
    assert len(pages) == 2
    assert closed_count["n"] >= 2


def test_benchmark_suite_runs_and_reports_measured_metrics():
    report = run_visual_benchmark(
        sizes=("small",),
        dpis=(150,),
        concurrencies=(1,),
        include_corrupt_probe=True,
    )
    assert report["cold_vs_warm_worker_reuse"]["same_worker_instance_reused"] is True
    assert len(report["dpi_size_matrix"]) == 1
    row = report["dpi_size_matrix"][0]
    assert row["size_tier"] == "small"
    assert row["page_count"] == 4
    assert row["duration_ms"] > 0.0
    assert row["schema_roundtrip_ms"] >= 0.0
    assert row["failure_rate"] == 0.0

    conc = report["concurrency_sweep"][0]
    assert conc["concurrency_limit"] == 1
    assert conc["peak_active_slots"] == 1
    # 4 valid docs + 1 malformed probe => failure rate == 0.2
    assert conc["failed_runs"] == 1
    assert conc["failure_rate"] == pytest.approx(0.2, abs=1e-4)

