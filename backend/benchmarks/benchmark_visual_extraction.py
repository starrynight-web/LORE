"""
Repeatable CPU-Only (16 GB RAM) Benchmark Suite for LORE Visual Extraction.

Generates deterministic synthetic PDFs at three sizes — ``small``, ``medium``,
and ``large`` — each containing:
  1. Scanned raster pages (no native PDF text layer)
  2. Vector/structured tables
  3. Vector & raster charts (bar / line)
  4. Printed forms with label-value pairs & checkboxes

Measures:
  - Cold vs. warm worker initialization & extractor/model reuse
  - Wall-clock duration & throughput across configurable DPIs (e.g. 150, 200, 300)
  - Full-page vs. clipped region renders & OCR call counts
  - Peak RSS memory (OS WorkingSet/PeakWorkingSetSize / rusage) & tracemalloc peak MB
  - End-to-end Pydantic ``lore.visual/1.0`` validation & canonical conversion time
  - Conservative worker concurrency (``concurrency=1`` vs ``concurrency=2``+) via
    ``WorkloadConcurrencyGate`` before increasing concurrency limits
  - Failure & partial-page error rates (including optional malformed PDF probe)

Usage (from ``e:\\LORE\\backend``):
    python benchmarks/benchmark_visual_extraction.py
    python benchmarks/benchmark_visual_extraction.py --dpis 150 200 300 --concurrencies 1 2 --json-out benchmarks/latest_cpu_benchmark.json
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import gc
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Ensure backend root is importable when invoked as a standalone script
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lore_enterprise.settings")

try:
    import django

    django.setup()
except Exception:
    pass

from PIL import Image, ImageDraw
import pymupdf

from apps.ingestion.batch import WorkloadConcurrencyGate
from apps.ingestion.pipeline.charts import PyMuPDFOpenCVChartExtractor
from apps.ingestion.pipeline.extractors import WorkerExtractorRegistry
from apps.ingestion.pipeline.forms import FormKVExtractor
from apps.ingestion.pipeline.ocr import TesseractOCRProvider
from apps.ingestion.pipeline.pdf_visual import PDFSafetyLimits, PyMuPDFVisualPDFAdapter
from apps.ingestion.pipeline.runtime import (
    VisualExtractionMetrics,
    configure_visual_cpu_runtime,
    get_process_memory_mb,
    measure_memory_and_duration,
)
from apps.ingestion.pipeline.tables import SLANetPlusTableExtractor
from apps.ingestion.pipeline.layout import PPDocLayoutSProvider
from apps.ingestion.pipeline.visual_schema import (
    pages_to_visual_document,
    visual_document_to_canonical_pages,
)


def _get_host_hardware_summary() -> Dict[str, Any]:
    total_gb: Optional[float] = None
    avail_gb: Optional[float] = None
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = round(stat.ullTotalPhys / (1024.0 ** 3), 2)
                avail_gb = round(stat.ullAvailPhys / (1024.0 ** 3), 2)
        except Exception:
            pass
    return {
        "platform": sys.platform,
        "python_version": sys.version.split()[0],
        "cpu_cores_logical": os.cpu_count() or 1,
        "total_ram_gb": total_gb,
        "available_ram_gb_at_start": avail_gb,
    }


def _render_scanned_page_png_bytes(page_index: int) -> bytes:
    """Create a deterministic rasterized scanned page containing text, lines, and checkbox shapes."""
    img = Image.new("RGB", (1100, 1400), color=(250, 250, 248))
    draw = ImageDraw.Draw(img)
    draw.rectangle([45, 45, 1055, 1340], outline=(40, 40, 40), width=3)
    draw.text((80, 80), f"LORE SCANNED ARCHIVE PAGE {page_index}", fill=(10, 10, 10))
    draw.text((80, 130), "Applicant: Acme Infrastructure Ltd.", fill=(20, 20, 20))
    draw.text((80, 170), "Invoice Number: INV-2026-0094", fill=(20, 20, 20))
    draw.text((80, 210), "Audit Date: 2026-11-12", fill=(20, 20, 20))
    draw.text((80, 250), "Approved Budget: $148,500.00", fill=(20, 20, 20))
    # Table-like grid inside scanned bitmap
    for r in range(5):
        y = 330 + r * 55
        draw.rectangle([80, y, 1000, y + 55], outline=(60, 60, 60), width=2)
        draw.text((95, y + 16), f"Item {r + 1} | Region {page_index}", fill=(15, 15, 15))
        draw.text((620, y + 16), f"{120 + r * 35} units", fill=(15, 15, 15))
    # Checkbox inside scanned bitmap
    draw.rectangle([80, 670, 110, 700], outline=(10, 10, 10), width=3)
    draw.line([84, 685, 95, 696, 107, 674], fill=(10, 10, 10), width=3)
    draw.text((130, 676), "Verified Physical Record", fill=(10, 10, 10))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img.close()
    return buf.getvalue()


def _draw_table_page(doc: pymupdf.Document, page_idx: int) -> None:
    page = doc.new_page(width=612, height=792)
    page.insert_text((48, 52), f"Quarterly Procurement Ledger - Page {page_idx}", fontsize=13)
    # Vector bordered table geometry
    x_cols = [48, 210, 340, 455, 560]
    y_rows = [90 + r * 36 for r in range(8)]
    for y in y_rows:
        page.draw_line((x_cols[0], y), (x_cols[-1], y), color=(0, 0, 0), width=1.0)
    for x in x_cols:
        page.draw_line((x, y_rows[0]), (x, y_rows[-1]), color=(0, 0, 0), width=1.0)
    headers = ["Category", "Q1 (USD)", "Q2 (USD)", "Status"]
    for ci, hdr in enumerate(headers):
        page.insert_text((x_cols[ci] + 8, y_rows[0] + 22), hdr, fontsize=10)
    for ri in range(1, 7):
        y_t = y_rows[ri] + 22
        page.insert_text((x_cols[0] + 8, y_t), f"Line Item {ri}", fontsize=9.5)
        page.insert_text((x_cols[1] + 8, y_t), f"{1200 + ri * 175}", fontsize=9.5)
        page.insert_text((x_cols[2] + 8, y_t), f"{1350 + ri * 190}", fontsize=9.5)
        page.insert_text((x_cols[3] + 8, y_t), "Settled", fontsize=9.5)


def _draw_chart_page(doc: pymupdf.Document, page_idx: int) -> None:
    page = doc.new_page(width=612, height=792)
    page.insert_text((48, 52), f"Regional Output Performance - Page {page_idx}", fontsize=13)
    # Vector bar chart inside plot frame (axes + ticks + bars + labels)
    px0, py0, px1, py1 = 110, 120, 520, 420
    page.draw_rect(pymupdf.Rect(px0, py0, px1, py1), color=(0.15, 0.15, 0.15), width=1.2)
    page.insert_text((210, 102), "Quarterly Throughput (Units)", fontsize=11)
    # Horizontal gridlines + Y ticks
    for idx, val in enumerate([0, 25, 50, 75, 100]):
        y = py1 - (val / 100.0) * (py1 - py0)
        page.draw_line((px0 - 5, y), (px0, y), color=(0, 0, 0), width=1.0)
        page.draw_line((px0, y), (px1, y), color=(0.82, 0.82, 0.82), width=0.5)
        page.insert_text((px0 - 34, y + 3), str(val), fontsize=9)
    bars = [("North", 42), ("South", 68), ("East", 85), ("West", 54)]
    bar_colors = [(0.18, 0.45, 0.78), (0.18, 0.45, 0.78), (0.18, 0.45, 0.78), (0.18, 0.45, 0.78)]
    slot_w = (px1 - px0) / len(bars)
    for bi, ((lbl, val), col) in enumerate(zip(bars, bar_colors)):
        bx0 = px0 + bi * slot_w + 22
        bx1 = bx0 + slot_w - 44
        by0 = py1 - (val / 100.0) * (py1 - py0)
        page.draw_rect(pymupdf.Rect(bx0, by0, bx1, py1), color=(0.05, 0.2, 0.4), fill=col, width=0.8)
        page.insert_text((bx0 + 8, py1 + 18), lbl, fontsize=9.5)


def _draw_form_page(doc: pymupdf.Document, page_idx: int) -> None:
    page = doc.new_page(width=612, height=792)
    page.insert_text((48, 52), f"Vendor Compliance & Expense Application Form - Page {page_idx}", fontsize=13)
    fields = [
        ("Vendor Name:", "Delta Civil Works", 115, 290),
        ("Tax ID:", "TIN-8841209", 165, 210),
        ("Claim Date:", "2026-11-05", 215, 175),
        ("Claim Amount:", "$4,820.50", 265, 195),
        ("Cost Center:", "OPS-CPU-04", 315, 225),
        ("Missing Reference:", "__________________", 365, 0),
    ]
    for lbl, val, y, box_w in fields:
        page.insert_text((60, y), lbl, fontsize=10.5)
        if box_w > 0:
            page.draw_rect(pymupdf.Rect(215, y - 13, 215 + box_w, y + 5), color=(0.3, 0.3, 0.3), width=0.9)
            page.insert_text((222, y), val, fontsize=10)
        else:
            page.insert_text((215, y), val, fontsize=10)
    # Checkboxes
    page.draw_rect(pymupdf.Rect(60, 415, 74, 429), color=(0, 0, 0), width=1.1)
    page.insert_text((84, 426), "Receipts Attached", fontsize=10)
    page.draw_rect(pymupdf.Rect(260, 415, 274, 429), color=(0, 0, 0), width=1.1)
    page.insert_text((284, 426), "Urgent Expedite", fontsize=10)
    # Signature field
    page.insert_text((60, 485), "Authorized Signature:", fontsize=10.5)
    page.insert_text((215, 485), "___________________________", fontsize=10)


def _draw_scanned_page(doc: pymupdf.Document, page_idx: int) -> None:
    page = doc.new_page(width=612, height=792)
    png_bytes = _render_scanned_page_png_bytes(page_idx)
    page.insert_image(pymupdf.Rect(0, 0, 612, 792), stream=png_bytes)


def build_synthetic_benchmark_pdf(size_tier: str) -> Tuple[bytes, Dict[str, Any]]:
    """
    Build deterministic small / medium / large synthetic PDFs exercising
    scanned pages, tables, charts, and forms.
    """
    tier = size_tier.lower().strip()
    if tier == "small":
        plan = ["scanned", "table", "chart", "form"]  # 4 balanced pages (1 of each visual workload)
    elif tier == "medium":
        plan = ["table", "chart", "form", "scanned"] * 2 + ["table", "form"]  # 10 pages
    elif tier == "large":
        plan = ["table", "chart", "form", "scanned"] * 6  # 24 pages
    else:
        raise ValueError(f"Unsupported benchmark size tier: {size_tier}")

    doc = pymupdf.open()
    try:
        for idx, kind in enumerate(plan, start=1):
            if kind == "scanned":
                _draw_scanned_page(doc, idx)
            elif kind == "table":
                _draw_table_page(doc, idx)
            elif kind == "chart":
                _draw_chart_page(doc, idx)
            elif kind == "form":
                _draw_form_page(doc, idx)
        pdf_bytes = doc.tobytes(deflate=True)
    finally:
        doc.close()

    manifest = {
        "size_tier": tier,
        "page_count": len(plan),
        "bytes": len(pdf_bytes),
        "page_mix": {k: plan.count(k) for k in ("scanned", "table", "chart", "form")},
    }
    return pdf_bytes, manifest


def _build_worker_adapter(dpi: int, max_render_pixels: int = 12_000_000) -> PyMuPDFVisualPDFAdapter:
    ocr = TesseractOCRProvider()
    return PyMuPDFVisualPDFAdapter(
        ocr_provider=ocr,
        layout_provider=PPDocLayoutSProvider(ocr_provider=ocr),
        table_extractor=SLANetPlusTableExtractor(ocr_provider=ocr),
        chart_extractor=PyMuPDFOpenCVChartExtractor(ocr_provider=ocr),
        form_extractor=FormKVExtractor(ocr_provider=ocr),
        analyze_searchable_with_layout=False,
        limits=PDFSafetyLimits(dpi=dpi, max_render_pixels=max_render_pixels),
    )


def run_visual_benchmark(
    *,
    sizes: Sequence[str] = ("small", "medium", "large"),
    dpis: Sequence[int] = (150, 200, 300),
    concurrencies: Sequence[int] = (1, 2),
    include_corrupt_probe: bool = True,
) -> Dict[str, Any]:
    """
    Execute repeatable CPU-only benchmarks covering small, medium, and large PDFs,
    cold vs. warm worker reuse, DPI sweeps, schema serialization, and concurrency.
    """
    runtime_cfg = configure_visual_cpu_runtime(force=True)
    hardware = _get_host_hardware_summary()

    # Probe optional dependency availability honestly
    ocr_probe = TesseractOCRProvider()
    layout_probe = PPDocLayoutSProvider(ocr_provider=ocr_probe)
    table_probe = SLANetPlusTableExtractor(ocr_provider=ocr_probe)
    capabilities = {
        "pymupdf": True,
        "tesseract_available": ocr_probe.is_available(),
        "pp_doclayout_s_available": layout_probe.is_available(),
        "slanet_plus_available": table_probe.is_available(),
        "opencv_available": PyMuPDFOpenCVChartExtractor.is_available(),
    }

    fixtures: Dict[str, Tuple[bytes, Dict[str, Any]]] = {
        sz: build_synthetic_benchmark_pdf(sz) for sz in sizes
    }

    # 1. Cold vs Warm WorkerExtractorRegistry reuse benchmark on smallest fixture
    WorkerExtractorRegistry.clear()
    with measure_memory_and_duration(enable_tracemalloc=True) as cold_stats:
        vis_cold = WorkerExtractorRegistry.get_visual_extractor()
    with measure_memory_and_duration(enable_tracemalloc=True) as warm_stats:
        vis_warm = WorkerExtractorRegistry.get_visual_extractor()
    reg_stats = WorkerExtractorRegistry.get_stats()

    cold_vs_warm = {
        "cold_init_ms": cold_stats["duration_ms"],
        "warm_lookup_ms": warm_stats["duration_ms"],
        "same_worker_instance_reused": vis_cold is vis_warm,
        "registry_init_counts": reg_stats.get("init_counts", {}),
    }

    # 2. Single-worker DPI x Size Matrix (also measuring Pydantic schema validation/dump)
    matrix_results: List[Dict[str, Any]] = []
    for dpi in dpis:
        adapter = _build_worker_adapter(dpi=dpi)
        for sz in sizes:
            pdf_bytes, manifest = fixtures[sz]
            run_metrics = VisualExtractionMetrics()
            gc.collect()
            with measure_memory_and_duration(enable_tracemalloc=True) as perf:
                pages = adapter.process_pdf(pdf_bytes)
                t_schema0 = time.perf_counter()
                vdoc = pages_to_visual_document(
                    pages,
                    source_document_id=f"bench-{sz}-dpi{dpi}",
                    filename=f"bench_{sz}.pdf",
                    document_type="pdf",
                )
                canonical = visual_document_to_canonical_pages(vdoc)
                schema_ms = round((time.perf_counter() - t_schema0) * 1000.0, 2)

            diag = dict(adapter.last_run_diagnostics or {})
            entry = run_metrics.record_run(
                duration_ms=perf["duration_ms"],
                pages_processed=len(pages),
                full_page_renders=int(diag.get("full_page_renders", 0) or 0),
                region_clip_renders=int(diag.get("region_clip_renders", 0) or 0),
                ocr_calls=int(diag.get("ocr_calls", 0) or 0),
                partial_failure_pages=int(diag.get("partial_failure_pages", 0) or 0),
                failed=(len(canonical) != manifest["page_count"]),
                rss_before_mb=perf["rss_before_mb"],
                rss_after_mb=perf["rss_after_mb"],
                peak_rss_mb=perf["peak_rss_mb"],
                tracemalloc_peak_mb=perf["tracemalloc_peak_mb"],
                dpi=dpi,
            )
            dur_s = max(1e-4, perf["duration_ms"] / 1000.0)
            matrix_results.append({
                "size_tier": sz,
                "dpi": dpi,
                "page_count": manifest["page_count"],
                "pdf_bytes": manifest["bytes"],
                "duration_ms": perf["duration_ms"],
                "schema_roundtrip_ms": schema_ms,
                "pages_per_sec": round(len(pages) / dur_s, 3),
                "visual_elements_extracted": len(vdoc.elements),
                "full_page_renders": entry["full_page_renders"],
                "region_clip_renders": entry["region_clip_renders"],
                "ocr_calls": entry["ocr_calls"],
                "rss_before_mb": perf["rss_before_mb"],
                "rss_after_mb": perf["rss_after_mb"],
                "peak_rss_mb": perf["peak_rss_mb"],
                "tracemalloc_peak_mb": perf["tracemalloc_peak_mb"],
                "partial_failure_pages": entry["partial_failure_pages"],
                "failure_rate": run_metrics.snapshot()["failure_rate"],
            })

    # 3. Conservative concurrency measurement (measure limit=1 first, then limit=2+)
    # Uses a realistic multi-document job mix at configured 200 DPI (or first configured DPI)
    conc_dpi = 200 if 200 in dpis else dpis[0]
    medium_bytes, medium_manifest = fixtures["medium" if "medium" in fixtures else sizes[0]]
    small_bytes, _ = fixtures["small" if "small" in fixtures else sizes[0]]
    batch_jobs: List[Tuple[str, bytes, bool]] = [
        ("small_1", small_bytes, False),
        ("medium_1", medium_bytes, False),
        ("small_2", small_bytes, False),
        ("medium_2", medium_bytes, False),
    ]
    if include_corrupt_probe:
        batch_jobs.append(("malformed_probe", b"%PDF-corrupted-benchmark-payload", True))

    concurrency_results: List[Dict[str, Any]] = []
    for conc_limit in concurrencies:
        WorkloadConcurrencyGate.reset_stats()
        conc_metrics = VisualExtractionMetrics()
        def _run_one(item: Tuple[str, bytes, bool]) -> None:
            job_name, payload, _ = item
            with WorkloadConcurrencyGate.acquire("visual", limit=conc_limit):
                # Per-thread adapter reusing process-wide worker model caches
                local_adapter = _build_worker_adapter(dpi=conc_dpi)
                with measure_memory_and_duration(enable_tracemalloc=False) as jp:
                    res_pages = local_adapter.process_pdf(payload)
                diag = dict(local_adapter.last_run_diagnostics or {})
                failed_doc = str(diag.get("status") or "") in {
                    "malformed_pdf",
                    "encrypted_pdf",
                    "oversized_pdf",
                    "empty_pdf",
                }
                conc_metrics.record_run(
                    duration_ms=jp["duration_ms"],
                    pages_processed=len(res_pages),
                    full_page_renders=int(diag.get("full_page_renders", 0) or 0),
                    region_clip_renders=int(diag.get("region_clip_renders", 0) or 0),
                    ocr_calls=int(diag.get("ocr_calls", 0) or 0),
                    partial_failure_pages=int(diag.get("partial_failure_pages", 0) or 0),
                    failed=failed_doc,
                    rss_before_mb=jp["rss_before_mb"],
                    rss_after_mb=jp["rss_after_mb"],
                    peak_rss_mb=jp["peak_rss_mb"],
                    dpi=conc_dpi,
                    error_reason=f"{job_name}:{diag.get('status')}" if failed_doc else None,
                )

        gc.collect()
        with measure_memory_and_duration(enable_tracemalloc=True) as batch_perf:
            with ThreadPoolExecutor(max_workers=max(1, conc_limit)) as pool:
                list(pool.map(_run_one, batch_jobs))

        snap = conc_metrics.snapshot()
        gate_stats = WorkloadConcurrencyGate.stats()
        total_pages_batch = snap["pages_processed"]
        concurrency_results.append({
            "concurrency_limit": conc_limit,
            "peak_active_slots": gate_stats["peak"].get("visual", 0),
            "dpi": conc_dpi,
            "jobs_count": len(batch_jobs),
            "pages_processed": total_pages_batch,
            "batch_wall_ms": batch_perf["duration_ms"],
            "batch_pages_per_sec": round(total_pages_batch / max(1e-4, batch_perf["duration_ms"] / 1000.0), 3),
            "job_avg_ms": snap["avg_duration_ms"],
            "job_p95_ms": snap["p95_duration_ms"],
            "peak_rss_mb": snap["max_peak_rss_mb"] or batch_perf["peak_rss_mb"],
            "tracemalloc_peak_mb": batch_perf["tracemalloc_peak_mb"],
            "full_page_renders": snap["total_full_page_renders"],
            "region_clip_renders": snap["total_region_clip_renders"],
            "failed_runs": snap["failed_runs"],
            "failure_rate": snap["failure_rate"],
        })

    return {
        "hardware": hardware,
        "runtime_cpu_config": runtime_cfg,
        "capabilities": capabilities,
        "fixtures": {k: v[1] for k, v in fixtures.items()},
        "cold_vs_warm_worker_reuse": cold_vs_warm,
        "dpi_size_matrix": matrix_results,
        "concurrency_sweep": concurrency_results,
        "process_memory_end_mb": get_process_memory_mb(),
    }


def format_markdown_report(report: Dict[str, Any]) -> str:
    hw = report["hardware"]
    rt = report["runtime_cpu_config"]
    cap = report["capabilities"]
    cw = report["cold_vs_warm_worker_reuse"]
    lines = [
        "# LORE Visual Extraction CPU Benchmark Report",
        "",
        "## Environment & Thread Config",
        f"- Hardware: {hw['cpu_cores_logical']} logical CPU cores, {hw['total_ram_gb']} GB total RAM "
        f"({hw['available_ram_gb_at_start']} GB free at start), OS `{hw['platform']}`, Python `{hw['python_version']}`",
        f"- CPU Thread Limits: `cpu_threads={rt['cpu_threads']}`, `opencv_threads={rt['opencv_threads_applied']}`, "
        f"`tesseract_omp_threads={rt['tesseract_omp_threads']}`, `visual_max_concurrency_default={rt['visual_max_concurrency']}`",
        f"- Optional Engines: Tesseract={cap['tesseract_available']}, PP-DocLayout-S={cap['pp_doclayout_s_available']}, "
        f"SLANet_plus={cap['slanet_plus_available']}, OpenCV={cap['opencv_available']}",
        f"- Worker Reuse: cold init `{cw['cold_init_ms']} ms`, warm lookup `{cw['warm_lookup_ms']} ms`, "
        f"reused=`{cw['same_worker_instance_reused']}`",
        "",
        "## Size x DPI Matrix",
        "| Tier | Pages | DPI | Wall (ms) | Schema (ms) | Pages/s | Full Renders | Clip Renders | OCR Calls | Peak RSS (MB) | Tracemalloc Peak (MB) | Failure Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in report["dpi_size_matrix"]:
        lines.append(
            f"| {r['size_tier']} | {r['page_count']} | {r['dpi']} | {r['duration_ms']} | {r['schema_roundtrip_ms']} | "
            f"{r['pages_per_sec']} | {r['full_page_renders']} | {r['region_clip_renders']} | {r['ocr_calls']} | "
            f"{r['peak_rss_mb']} | {r['tracemalloc_peak_mb']} | {r['failure_rate']} |"
        )
    lines.extend([
        "",
        "## Worker Concurrency Sweep (Measured Before Increasing Concurrency)",
        "| Concurrency Limit | Peak Active | DPI | Jobs | Pages | Batch Wall (ms) | Pages/s | Job Avg (ms) | Job p95 (ms) | Peak RSS (MB) | Failure Rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for c in report["concurrency_sweep"]:
        lines.append(
            f"| {c['concurrency_limit']} | {c['peak_active_slots']} | {c['dpi']} | {c['jobs_count']} | "
            f"{c['pages_processed']} | {c['batch_wall_ms']} | {c['batch_pages_per_sec']} | "
            f"{c['job_avg_ms']} | {c['job_p95_ms']} | {c['peak_rss_mb']} | {c['failure_rate']} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeatable CPU benchmark for LORE Visual Extraction")
    parser.add_argument("--sizes", nargs="+", default=["small", "medium", "large"], choices=["small", "medium", "large"])
    parser.add_argument("--dpis", nargs="+", type=int, default=[150, 200, 300])
    parser.add_argument("--concurrencies", nargs="+", type=int, default=[1, 2])
    parser.add_argument("--no-corrupt-probe", action="store_true")
    parser.add_argument("--json-out", type=str, default="")
    args = parser.parse_args()

    report = run_visual_benchmark(
        sizes=args.sizes,
        dpis=args.dpis,
        concurrencies=args.concurrencies,
        include_corrupt_probe=not args.no_corrupt_probe,
    )
    print(format_markdown_report(report))
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved raw JSON benchmark to: {out_path}")


if __name__ == "__main__":
    main()
