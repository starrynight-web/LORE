"""
PDF and OCR Integration Tests for LORE Visual Extraction.

Verifies PyMuPDF + TesseractOCRProvider integration, compatibility with
OCRRouter and UnifiedDocumentExtractor, page classification, native-text
preference, rotation/coordinate preservation, Bengali repair, single-page
memory release, safety guards, and unavailable-dependency fallbacks.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw
from django.conf import settings

from apps.ingestion.pipeline import pdf_visual as pdf_visual_mod
from apps.ingestion.pipeline.contracts import VisualPipelineIntegrationAdapter
from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
from apps.ingestion.pipeline.ocr import (
    HAS_PDFPLUMBER,
    BaseOCRProvider,
    OCRRouter,
    TesseractOCRProvider,
    is_visual_encoded_document,
    repair_visual_bengali_document,
)
from apps.ingestion.pipeline.pdf_visual import (
    HAS_PYMUPDF,
    PDFPageClassification,
    PDFSafetyLimits,
    PyMuPDFPageRenderer,
    PyMuPDFVisualPDFAdapter,
)
from apps.ingestion.pipeline.visual import VisualDocumentExtractor, VisualRegionType


if HAS_PYMUPDF:
    import pymupdf


def _load_dataset_pdf(prefix: str) -> bytes:
    zip_candidates = [
        os.path.join(str(settings.BASE_DIR), "..", "Lore_Dataset.zip"),
        os.path.join(str(settings.BASE_DIR), "Lore_Dataset.zip"),
    ]
    for zp in zip_candidates:
        if os.path.exists(zp):
            with zipfile.ZipFile(zp, "r") as zf:
                matches = [n for n in zf.namelist() if n.startswith(prefix) and n.lower().endswith(".pdf")]
                if matches:
                    return zf.read(matches[0])
    pytest.skip(f"Dataset PDF matching {prefix} not found in Lore_Dataset.zip")


def _make_text_png_bytes(lines: List[str], width: int = 500, height: int = 240, draw_box: bool = True) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    if draw_box:
        draw.rectangle((10, 10, width - 10, height - 10), outline="black", width=3)
    y = 30
    for line in lines:
        draw.text((28, y), line, fill="black")
        y += 38
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img.close()
    return buf.getvalue()


class _SpyOCRProvider(BaseOCRProvider):
    """Configurable OCR stub tracking invocations while matching TesseractOCRProvider schema."""

    def __init__(
        self,
        *,
        available: bool = True,
        lang: str = "ben+eng",
        text: str = "Diagram Axis Growth 42%",
        confidence: float = 0.87,
        status: str = "success",
        engine: str = "tesseract",
        engine_version: str = "5.5.0-spy",
        needs_review: bool = False,
        error_detail: str = "",
    ):
        self._available = available
        self.lang = lang
        self.text = text
        self.confidence = confidence
        self.status = status
        self.engine = engine
        self.engine_version = engine_version
        self.needs_review = needs_review
        self.error_detail = error_detail
        self.calls: int = 0
        self.observed_sizes: List[tuple[int, int]] = []

    def is_available(self) -> bool:
        return self._available

    def extract_image(self, image: Image.Image) -> Dict[str, Any]:
        self.calls += 1
        self.observed_sizes.append(image.size)
        if not self._available:
            return {
                "text": f"[OCR Engine Optional: Tesseract missing. Size: {image.width}x{image.height}]",
                "confidence": 0.0,
                "words_count": 0,
                "bounding_boxes": [],
                "engine": "none",
                "engine_version": "none",
                "language": self.lang,
                "status": "provider_unavailable",
                "is_optional_skipped": True,
                "needs_review": False,
                "width": float(image.width),
                "height": float(image.height),
            }

        clean_text = repair_visual_bengali_document(self.text) if self.text else ""
        words = clean_text.split()
        boxes = [
            {
                "word": w,
                "confidence": self.confidence,
                "x": 20 + (i * 35),
                "y": 40,
                "w": 28,
                "h": 16,
                "normalized_box": [120, min(900, 60 + i * 180), 220, min(990, 200 + i * 180)],
            }
            for i, w in enumerate(words)
        ]
        res: Dict[str, Any] = {
            "text": clean_text,
            "confidence": self.confidence,
            "words_count": len(words),
            "bounding_boxes": boxes,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "language": self.lang,
            "width": float(image.width),
            "height": float(image.height),
            "status": self.status,
            "needs_review": self.needs_review,
        }
        if self.error_detail:
            res["error_detail"] = self.error_detail
        return res


def _build_3page_representative_pdf() -> bytes:
    """
    Page 1: Pure searchable digital text (>20 chars, no images/drawings).
    Page 2: Pure scanned raster image page (0 digital chars).
    Page 3: Mixed-content page (digital text >20 chars + embedded visual diagram).
    """
    doc = pymupdf.open()

    # Page 1: Searchable
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text(
        (72, 90),
        "LORE Enterprise Policy Section 1: All financial approvals require dual signoff.",
        fontsize=12,
    )

    # Page 2: Scanned full-page image
    p2 = doc.new_page(width=612, height=792)
    scan_png = _make_text_png_bytes(["SCANNED DEED EXHIBIT A", "Plot 44 Approved"], width=600, height=780)
    p2.insert_image(pymupdf.Rect(18, 18, 594, 774), stream=scan_png)

    # Page 3: Mixed digital text + embedded visual diagram
    p3 = doc.new_page(width=612, height=792)
    p3.insert_text(
        (72, 80),
        "Quarterly Expenditure Overview: See embedded compliance flow figure below.",
        fontsize=12,
    )
    diag_png = _make_text_png_bytes(["Architecture Diagram", "Q3 Limit $900"], width=360, height=220)
    p3.insert_image(pymupdf.Rect(72, 160, 432, 380), stream=diag_png)

    raw = doc.tobytes()
    doc.close()
    return raw


# ==============================================================================
# 1. COMPARISON ON REPRESENTATIVE & REAL DATASET PDFs
# ==============================================================================
class TestOldVsNewPDFComparison:
    @pytest.mark.parametrize("doc_prefix", ["DOC-001", "DOC-002", "DOC-010"])
    def test_real_dataset_digital_pdfs_match_baseline_contract_without_ocr(self, doc_prefix: str):
        pdf_bytes = _load_dataset_pdf(doc_prefix)
        spy_ocr = _SpyOCRProvider()

        old_extractor = UnifiedDocumentExtractor(ocr_provider=spy_ocr)
        new_extractor = UnifiedDocumentExtractor.with_pymupdf_visual(
            ocr_provider=spy_ocr,
            append_visual_text=False,  # Strict baseline text parity mode
        )
        enriched_extractor = UnifiedDocumentExtractor.with_pymupdf_visual(
            ocr_provider=spy_ocr,
            append_visual_text=True,
        )

        old_pages = old_extractor.extract_document(pdf_bytes, doc_type="pdf", filename=f"{doc_prefix}.pdf")
        new_pages = new_extractor.extract_document(pdf_bytes, doc_type="pdf", filename=f"{doc_prefix}.pdf")
        enr_pages = enriched_extractor.extract_document(pdf_bytes, doc_type="pdf", filename=f"{doc_prefix}.pdf")

        # Searchable digital dataset PDFs must never trigger unnecessary OCR
        assert spy_ocr.calls == 0
        assert len(new_pages) == len(old_pages) >= 1

        for op, np, ep in zip(old_pages, new_pages, enr_pages):
            assert np["page_number"] == op["page_number"]
            assert np["text"] == op["text"]
            assert np["confidence"] == op["confidence"]
            assert np["extraction_type"] == op["extraction_type"] == "digital_pdf"
            assert np["engine"] == op["engine"] == "pdfplumber"
            assert np["engine_version"] == op["engine_version"]
            assert np["width"] == op["width"] and np["height"] == op["height"]
            assert np["bounding_boxes"] == op["bounding_boxes"]
            assert np["visual_metadata"]["ocr_triggered"] is False
            assert np["visual_metadata"]["render_count"] == 0
            VisualPipelineIntegrationAdapter.validate_page_payload(np, strict=True)
            VisualPipelineIntegrationAdapter.validate_page_payload(ep, strict=True)
            # Every native sentence remains preserved even when Markdown table evidence is appended
            assert op["text"][:80] in ep["text"]

    @pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for 3-page PDF synthesis")
    def test_searchable_scanned_mixed_comparison_between_old_router_and_new_adapter(self):
        pdf_bytes = _build_3page_representative_pdf()

        old_ocr = _SpyOCRProvider(text="Scanned Deed Plot 44", confidence=0.88)
        new_ocr = _SpyOCRProvider(text="Recovered Visual Region", confidence=0.88)

        old_pages = UnifiedDocumentExtractor(ocr_provider=old_ocr).extract_document(
            pdf_bytes, doc_type="pdf", filename="3page.pdf"
        )
        new_pages = UnifiedDocumentExtractor.with_pymupdf_visual(ocr_provider=new_ocr).extract_document(
            pdf_bytes, doc_type="pdf", filename="3page.pdf"
        )

        assert len(old_pages) == len(new_pages) == 3

        # Old OCRRouter OCR'd page 2 only (skipped page 1 & ignored page 3 image)
        assert old_ocr.calls == 1
        # New adapter: Page 1 -> 0 OCR calls; Page 2 -> 1 page OCR call; Page 3 -> 1 cropped region OCR call
        assert new_ocr.calls == 2

        # Page 1 (Searchable): identical native extraction & 0 renders
        assert new_pages[0]["page_classification"] == PDFPageClassification.SEARCHABLE.value
        assert new_pages[0]["text"] == old_pages[0]["text"]
        assert new_pages[0]["confidence"] == old_pages[0]["confidence"]
        assert new_pages[0]["bounding_boxes"] == old_pages[0]["bounding_boxes"]
        assert new_pages[0]["visual_metadata"]["render_count"] == 0
        assert new_pages[0]["visual_metadata"]["ocr_triggered"] is False

        # Page 2 (Scanned): OCR executed via TesseractOCRProvider schema
        assert new_pages[1]["page_classification"] == PDFPageClassification.SCANNED.value
        assert new_pages[1]["extraction_type"] == "ocr_tesseract"
        assert new_pages[1]["confidence"] == 0.88
        assert new_pages[1]["engine"] == "tesseract"
        assert new_pages[1]["engine_version"] == "5.5.0-spy"
        assert new_pages[1]["language"] == "ben+eng"
        assert new_pages[1]["visual_metadata"]["render_count"] == 1
        assert new_pages[1]["visual_metadata"]["ocr_triggered"] is True

        # Page 3 (Mixed): retains digital baseline text & word boxes AND adds cropped visual region
        assert new_pages[2]["page_classification"] == PDFPageClassification.MIXED_CONTENT.value
        assert new_pages[2]["extraction_type"] == "digital_pdf"
        assert new_pages[2]["confidence"] == old_pages[2]["confidence"]
        assert new_pages[2]["bounding_boxes"] == old_pages[2]["bounding_boxes"]
        assert "Quarterly Expenditure Overview" in new_pages[2]["text"]
        assert "Recovered Visual Region" in new_pages[2]["text"]
        assert new_pages[2]["visual_metadata"]["render_count"] == 1
        assert len(new_pages[2]["visual_regions"]) == 1
        reg = new_pages[2]["visual_regions"][0]
        assert reg["region_type"] == VisualRegionType.EMBEDDED_IMAGE.value
        # Region bbox should sit around y=[160..380]/792 -> normalized ymin ~200, ymax ~480
        ymin, xmin, ymax, xmax = reg["normalized_box"]
        assert 170 <= ymin <= 230 and 450 <= ymax <= 510
        assert 90 <= xmin <= 140 and 680 <= xmax <= 730
        # Remapped cropped word boxes must sit inside the parent region normalized bounds
        for wb in reg["word_boxes"]:
            wy0, wx0, wy1, wx1 = wb["normalized_box"]
            assert ymin <= wy0 <= wy1 <= ymax + 2
            assert xmin <= wx0 <= wx1 <= xmax + 2


# ==============================================================================
# 2. NATIVE FIRST, ROTATION & COORDINATE PRESERVATION
# ==============================================================================
@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for geometry and rotation tests")
class TestRotationGeometryAndNativeFirst:
    @pytest.mark.parametrize("rotation", [90, 180, 270])
    def test_rotation_and_coordinate_transforms_match_display_space(self, rotation: int):
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            (72, 100),
            "Rotated Compliance Clause Minimum Length Over Twenty Characters",
            fontsize=12,
        )
        # Solid black visual block at unrotated rect (100, 200, 220, 320)
        blk = Image.new("RGB", (120, 120), "black")
        blk_buf = io.BytesIO()
        blk.save(blk_buf, format="PNG")
        blk.close()
        page.insert_image(pymupdf.Rect(100, 200, 220, 320), stream=blk_buf.getvalue())
        page.set_rotation(rotation)
        pdf_bytes = doc.tobytes()
        doc.close()

        captured_crops: List[Image.Image] = []

        class _PixelCheckOCR(_SpyOCRProvider):
            def extract_image(self, image: Image.Image) -> Dict[str, Any]:
                # Sample center pixel before close: proves clip hit rotated black square, not white paper
                center = image.getpixel((image.width // 2, image.height // 2))
                captured_crops.append(center)
                return super().extract_image(image)

        spy_ocr = _PixelCheckOCR(text="Stamp Sealed", confidence=0.90)
        # Test PyMuPDF-native extraction directly (prefer_existing_native=False)
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=spy_ocr, prefer_existing_native=False)
        pages = adapter.process_pdf(pdf_bytes)

        assert len(pages) == 1
        p = pages[0]
        assert p["rotation"] == rotation
        assert p["page_classification"] == PDFPageClassification.MIXED_CONTENT.value
        if rotation in (90, 270):
            assert p["width"] == 792.0 and p["height"] == 612.0
        else:
            assert p["width"] == 612.0 and p["height"] == 792.0

        # Clipped region crop must have captured the black block pixels (near RGB (0,0,0)), NOT white background!
        assert len(captured_crops) == 1
        assert sum(captured_crops[0]) < 30

        # Compare rotated native word box alignment against pdfplumber's rotated word coordinates
        if HAS_PDFPLUMBER:
            old_page = OCRRouter(ocr_provider=spy_ocr).process_pdf(pdf_bytes)[0]
            assert old_page["width"] == p["width"] and old_page["height"] == p["height"]
            # At 180/270 deg pdfplumber reverses reading order & characters ("detatoR"); match corresponding words
            old_rot = next(
                b for b in old_page["bounding_boxes"] if b.get("word") in ("Rotated", "detatoR")
            )
            new_rot = next(b for b in p["bounding_boxes"] if b.get("word") == "Rotated")
            for o_coord, n_coord in zip(old_rot["normalized_box"], new_rot["normalized_box"]):
                assert abs(o_coord - n_coord) <= 15

            old_chr = next(
                b for b in old_page["bounding_boxes"] if b.get("word") in ("Characters", "sretcarahC")
            )
            new_chr = next(b for b in p["bounding_boxes"] if b.get("word") == "Characters")
            for o_coord, n_coord in zip(old_chr["normalized_box"], new_chr["normalized_box"]):
                assert abs(o_coord - n_coord) <= 15


# ==============================================================================
# 3. OCR PROVENANCE, BENGALI SUPPORT, MEMORY CLEANUP, SAFETY & FALLBACKS
# ==============================================================================
class TestProvenanceBengaliSafetyAndFallbacks:
    @pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for scanned PDF synthesis")
    def test_preserves_original_ocr_confidence_engine_version_lang_and_warnings(self):
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(
            pymupdf.Rect(20, 20, 592, 772),
            stream=_make_text_png_bytes(["Faint Scanned Text"], width=500, height=500),
        )
        pdf_bytes = doc.tobytes()
        doc.close()

        ocr_stub = _SpyOCRProvider(
            text="সফটওয়্যার",
            confidence=0.38,
            status="low_confidence",
            engine="tesseract",
            engine_version="5.5.0-custom",
            lang="ben+eng",
            needs_review=True,
            error_detail="Low contrast warning",
        )
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=ocr_stub)
        pages = adapter.process_pdf(pdf_bytes)

        p = pages[0]
        assert p["confidence"] == 0.38
        assert p["engine"] == "tesseract"
        assert p["engine_version"] == "5.5.0-custom"
        assert p["status"] == "low_confidence"
        assert p["language"] == "ben+eng"
        assert p["needs_review"] is True
        assert "Low contrast warning" in p["warnings"]

    @pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for Bengali PDF synthesis")
    def test_preserves_bengali_repair_and_bangla_digit_normalization(self):
        corrupted = "স্মার্ট ই গভনয্র্ ােন্সর ল্যান্ডটকে ১২ — পর্যাপ্ত দৈর্ঘ্যের পাঠ্য।"
        assert is_visual_encoded_document(corrupted) is True

        # 1. Native PDF Bengali repair + digit conversion when a Unicode Bengali TTF/TTC exists on host
        bengali_font = next(
            (
                path
                for path in (
                    r"C:\Windows\Fonts\Nirmala.ttc",
                    r"C:\Windows\Fonts\vrinda.ttf",
                    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
                    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
                )
                if os.path.exists(path)
            ),
            None,
        )
        if bengali_font is not None:
            doc = pymupdf.open()
            page = doc.new_page(width=612, height=792)
            page.insert_font(fontname="benfont", fontfile=bengali_font)
            page.insert_text((50, 100), corrupted, fontname="benfont", fontsize=11)
            native_pdf = doc.tobytes()
            doc.close()

            adapter = PyMuPDFVisualPDFAdapter(
                ocr_provider=_SpyOCRProvider(),
                prefer_existing_native=False,
                repair_bengali=True,
                convert_bangla_digits=True,
            )
            native_page = adapter.process_pdf(native_pdf)[0]
            assert native_page["is_repaired"] is True
            assert "স্মার্ট ই-গভর্ন্যান্সের ল্যান্ডটেক 12" in native_page["text"]

        # 2. Scanned PDF OCR path with Bengali visual repair + Bangla digit conversion + ben+eng lang metadata
        scanned_doc = pymupdf.open()
        sp = scanned_doc.new_page(width=612, height=792)
        sp.insert_image(
            pymupdf.Rect(20, 20, 592, 772),
            stream=_make_text_png_bytes(["Scanned Bengali Form"], width=500, height=500),
        )
        scanned_pdf = scanned_doc.tobytes()
        scanned_doc.close()

        ben_ocr = _SpyOCRProvider(text=corrupted, confidence=0.81, lang="ben+eng")
        scanned_adapter = PyMuPDFVisualPDFAdapter(
            ocr_provider=ben_ocr,
            repair_bengali=True,
            convert_bangla_digits=True,
        )
        scanned_page = scanned_adapter.process_pdf(scanned_pdf)[0]
        assert scanned_page["language"] == "ben+eng"
        assert scanned_page["is_repaired"] is True
        assert "স্মার্ট ই-গভর্ন্যান্সের ল্যান্ডটেক 12" in scanned_page["text"]

    @pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real raster Tesseract check")
    def test_real_tesseract_and_page_by_page_image_memory_release(self):
        # 3-page scanned PDF verifies single-page image lifecycle + optional real Tesseract execution
        doc = pymupdf.open()
        for idx in range(3):
            p = doc.new_page(width=400, height=200)
            p.insert_image(
                pymupdf.Rect(10, 10, 390, 190),
                stream=_make_text_png_bytes([f"LORE AUDIT PAGE {idx + 1}"], width=380, height=180, draw_box=False),
            )
        pdf_bytes = doc.tobytes()
        doc.close()

        real_ocr = TesseractOCRProvider()
        closed_events = []
        orig_close = Image.Image.close

        def spy_close(img_self):
            closed_events.append(img_self.size)
            return orig_close(img_self)

        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=real_ocr, limits=PDFSafetyLimits(dpi=150))
        with patch.object(Image.Image, "close", autospec=True, side_effect=spy_close):
            pages = adapter.process_pdf(pdf_bytes)

        assert len(pages) == 3
        # Each page's raster image must be closed after that page's processing
        assert len(closed_events) >= 3
        if real_ocr.is_available():
            assert all(p["engine"] == "tesseract" for p in pages)
            assert all(p["language"] == real_ocr.lang for p in pages)
        else:
            assert all(p["status"] == "provider_unavailable" for p in pages)

    def test_encrypted_malformed_empty_and_oversized_pdfs_handled_safely(self):
        adapter = PyMuPDFVisualPDFAdapter(
            ocr_provider=_SpyOCRProvider(),
            limits=PDFSafetyLimits(max_pages=2, max_file_bytes=200_000, max_render_pixels=2_000_000),
        )

        # 1. Empty 0-byte PDF -> [] safely
        assert adapter.process_pdf(b"") == []
        assert adapter.last_run_diagnostics["status"] == "empty_pdf"

        # 2. Malformed bytes -> diagnostic page with empty text & warning (fails Stage 3 safely)
        malformed = adapter.process_pdf(b"%PDF-1.4\nINVALID_CORRUPT_PAYLOAD")
        assert len(malformed) == 1
        assert malformed[0]["status"] == "malformed_pdf"
        assert malformed[0]["text"] == ""
        assert malformed[0]["needs_review"] is True
        VisualPipelineIntegrationAdapter.validate_page_payload(malformed[0], strict=True)

        # 3. Oversized stream -> rejected safely BEFORE buffering into memory
        oversized_stream = io.BytesIO(b"%PDF-1.4" + (b"0" * 205_000))
        oversized = adapter.process_pdf(oversized_stream)
        assert len(oversized) == 1
        assert oversized[0]["status"] == "oversized_pdf"
        assert oversized[0]["text"] == ""
        assert any("exceeds" in w.lower() for w in oversized[0]["warnings"])
        VisualPipelineIntegrationAdapter.validate_page_payload(oversized[0], strict=True)

        if HAS_PYMUPDF:
            # 4. Encrypted PDF without password -> halted safely; with password -> decrypted cleanly
            edoc = pymupdf.open()
            ep = edoc.new_page()
            ep.insert_text((72, 90), "Confidential Policy Clause Protected By User Password Over 20 Chars")
            enc_bytes = edoc.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="secret123"
            )
            edoc.close()

            locked = adapter.process_pdf(enc_bytes)
            assert len(locked) == 1
            assert locked[0]["status"] == "encrypted_pdf"
            assert locked[0]["text"] == ""
            assert locked[0]["needs_review"] is True

            unlocked = adapter.process_pdf(enc_bytes, password="secret123")
            assert len(unlocked) == 1
            assert "Confidential Policy Clause" in unlocked[0]["text"]

            # 5. Page limit truncation (4 pages > max_pages=2)
            pdoc = pymupdf.open()
            for i in range(4):
                pg = pdoc.new_page()
                pg.insert_text((72, 90), f"Page {i + 1} Long Enough To Be Digital Searchable Content")
            many_bytes = pdoc.tobytes()
            pdoc.close()

            capped = adapter.process_pdf(many_bytes)
            assert len(capped) == 2
            assert any("page limit" in w.lower() for w in capped[0]["warnings"])

            # 6. Oversized page geometry (7200 x 7200 pt) triggers adaptive DPI clamp without OOM
            dpi, warn = PyMuPDFPageRenderer.compute_safe_dpi(
                7200.0, 7200.0, target_dpi=300, max_render_pixels=2_000_000
            )
            assert dpi < 300
            assert warn is not None and "Adaptive DPI clamped" in warn

    def test_graceful_fallback_when_pymupdf_or_tesseract_unavailable(self):
        # 1. Unavailable Tesseract binary: digital PDFs succeed cleanly; scanned pages degrade safely
        missing_tess = TesseractOCRProvider(tesseract_cmd=r"C:\nonexistent_tess\tesseract.exe")
        assert missing_tess.is_available() is False

        if HAS_PYMUPDF:
            pdf_bytes = _build_3page_representative_pdf()
            adapter = PyMuPDFVisualPDFAdapter(ocr_provider=missing_tess)
            pages = adapter.process_pdf(pdf_bytes)
            assert pages[0]["extraction_type"] == "digital_pdf"
            assert pages[1]["status"] == "provider_unavailable"
            assert pages[1]["is_optional_skipped"] is True
            assert any("unavailable" in w.lower() for w in pages[1]["warnings"])
        else:
            pdf_bytes = _load_dataset_pdf("DOC-001")

        # 2. PyMuPDF unavailable -> falls back cleanly to OCRRouter inside adapter & UnifiedDocumentExtractor
        sample_pdf = _load_dataset_pdf("DOC-001")
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=_SpyOCRProvider())
        with patch.object(pdf_visual_mod, "HAS_PYMUPDF", False), patch.object(pdf_visual_mod, "pymupdf", None):
            extractor = UnifiedDocumentExtractor(pdf_visual_adapter=adapter)
            fb_pages = extractor.extract_document(sample_pdf, doc_type="pdf", filename="DOC-001.pdf")

        assert len(fb_pages) >= 1
        assert fb_pages[0]["extraction_type"] == "digital_pdf"
        assert fb_pages[0]["visual_metadata"]["fallback_applied"] is True
        assert any("pymupdf not installed" in w.lower() for w in fb_pages[0]["warnings"])
        VisualPipelineIntegrationAdapter.validate_page_payload(fb_pages[0], strict=True)

        # 3. VisualDocumentExtractor(use_pymupdf=True) compatibility check
        if HAS_PYMUPDF:
            vde = VisualDocumentExtractor(ocr_provider=_SpyOCRProvider(text="Chart Data"), use_pymupdf=True)
            v_pages = vde.extract_document(sample_pdf, doc_type="pdf", filename="DOC-001.pdf")
            assert len(v_pages) >= 1
            VisualPipelineIntegrationAdapter.validate_page_payload(v_pages[0], strict=True)

