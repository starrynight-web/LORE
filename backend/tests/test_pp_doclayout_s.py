"""
Comprehensive verification suite for LORE's optional CPU PP-DocLayout-S layout
detection provider (apps.ingestion.pipeline.layout) and its integration with
VisualDocumentExtractor, PyMuPDFVisualPDFAdapter, contracts, and Settlement.

Covers:
1. Verified model artifact constants & runtime availability checks (CPU/thread config).
2. 8-category classification (titles/headings, paragraphs, tables, charts,
   figures/images, forms, headers/footers, unknown) including all 23 PP-DocLayout-S labels.
3. Canonical [ymin, xmin, ymax, xmax] (0..1000) coordinate normalization & rotated pages.
4. Multi-column XY-cut reading-order preservation & overlap/duplicate suppression.
5. Per-region extractor routing & preservation of unknown regions.
6. Worker-level model reuse & thread-limit configuration.
7. Graceful fallback on unavailable library/missing model_dir/runtime error +
   strict non-interference with Governance/Settlement authority & evidence sufficiency.
8. Representative multi-region page fixtures (2-column report, form+seal, rotated PDF).
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Mapping, Tuple
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from apps.ingestion.pipeline import layout as layout_mod
from apps.ingestion.pipeline.contracts import VisualPipelineIntegrationAdapter
from apps.ingestion.pipeline.layout import (
    PP_DOCLAYOUT_S_ARTIFACT_METADATA,
    PP_DOCLAYOUT_S_BACKBONE,
    PP_DOCLAYOUT_S_BCEBOS_URL,
    PP_DOCLAYOUT_S_HF_REPO,
    PP_DOCLAYOUT_S_INFERENCE_ARCHIVE,
    PP_DOCLAYOUT_S_LABEL_LIST,
    PP_DOCLAYOUT_S_LICENSE,
    PP_DOCLAYOUT_S_MODEL_NAME,
    HAS_PADDLEOCR_LAYOUT,
    HAS_PADDLEPADDLE,
    LayoutCategory,
    LayoutExtractorRoute,
    PPDocLayoutSConfig,
    PPDocLayoutSProvider,
    WorkerLayoutModelCache,
    classify_layout_label,
    deduplicate_layout_regions,
    extract_form_kv_pairs,
    sort_regions_reading_order,
    transform_box_for_rotation,
)
from apps.ingestion.pipeline.ocr import BaseOCRProvider, TesseractOCRProvider
from apps.ingestion.pipeline.pdf_visual import HAS_PYMUPDF, PyMuPDFVisualPDFAdapter
from apps.ingestion.pipeline.visual import VisualDocumentExtractor, VisualRegionType

if HAS_PYMUPDF:
    import pymupdf  # type: ignore


# ==============================================================================
# DETERMINISTIC TEST DOUBLES & REPRESENTATIVE PAGE FIXTURES
# ==============================================================================
class _RegionAwareMockOCR(BaseOCRProvider):
    """
    Deterministic OCR double that maps cropped image content / caller region hints
    or luminance regions cleanly without external binaries.
    """

    engine_name = "tesseract"
    engine_version = "5.5.0-mock"

    def __init__(self, responses_by_hint: Optional[Dict[str, Tuple[str, List[Dict[str, Any]]]]] = None, lang: str = "ben+eng"):
        self.responses_by_hint = responses_by_hint or {}
        self.lang = lang
        self.calls: List[Tuple[int, int]] = []

    def is_available(self) -> bool:
        return True

    def _signature_color_hint(self, image: Image.Image) -> str:
        """Detects synthetic fixture strip/swatch markers painted cleanly in crops."""
        rgb = image.convert("RGB")
        w, h = rgb.size
        # Sample evenly spaced pixels and inspect dominant non-white RGB color tag
        r_acc, g_acc, b_acc, n = 0, 0, 0, 0
        for y in range(max(1, h // 10), h, max(1, h // 5)):
            for x in range(max(1, w // 10), w, max(1, w // 5)):
                r, g, b = rgb.getpixel((x, y))
                if r < 235 or g < 235 or b < 235:
                    r_acc += r
                    g_acc += g
                    b_acc += b
                    n += 1
        if n == 0:
            return "default"
        ar, ag, ab = r_acc / n, g_acc / n, b_acc / n
        if ar > 180 and ag < 110 and ab < 110:
            return "red"
        if ab > 180 and ar < 110 and ag < 110:
            return "blue"
        if ag > 160 and ar < 110 and ab < 110:
            return "green"
        if ar > 180 and ag > 150 and ab < 100:
            return "amber"
        if ar > 160 and ab > 160 and ag < 110:
            return "purple"
        return "default"

    def extract_image(self, image: Image.Image) -> Dict[str, Any]:
        self.calls.append(image.size)
        hint = self._signature_color_hint(image)
        if hint in self.responses_by_hint:
            text, raw_boxes = self.responses_by_hint[hint]
        else:
            text = f"Extracted OCR Text ({image.width}x{image.height})"
            raw_boxes = [
                {
                    "word": w,
                    "confidence": 0.91,
                    "x": 10 + i * 24,
                    "y": 10,
                    "w": 20,
                    "h": 14,
                    "normalized_box": [100, min(900, 50 + i * 120), 220, min(980, 150 + i * 120)],
                }
                for i, w in enumerate(text.split())
            ]
        return {
            "text": text,
            "confidence": 0.91,
            "words_count": len(text.split()),
            "width": float(image.width),
            "height": float(image.height),
            "engine": self.engine_name,
            "engine_version": self.engine_version,
            "status": "success",
            "language": self.lang,
            "needs_review": False,
            "bounding_boxes": raw_boxes,
        }


# Make Optional typing import available cleanly cleanly inside test signatures above
from typing import Optional  # noqa: E402


class _MockLayoutResult:
    """Mimics PaddleOCR 3.x LayoutDetection prediction result object (`res['boxes']` & `res.json`)."""

    def __init__(self, boxes: List[Dict[str, Any]], input_path: str = "page.png"):
        self._boxes = boxes
        self.json = {"res": {"input_path": input_path, "page_index": None, "boxes": boxes}}

    def __getitem__(self, key: str) -> Any:
        if key == "boxes":
            return self._boxes
        raise KeyError(key)


class _SpyPPDocLayoutModel:
    """Fake PaddleOCR LayoutDetection instance verifying BGR array inputs & call counts."""

    def __init__(self, config: PPDocLayoutSConfig, boxes_factory: Any):
        self.config = config
        self.boxes_factory = boxes_factory
        self.predict_calls: List[Dict[str, Any]] = []

    def predict(
        self,
        input: Any,
        batch_size: int = 1,
        threshold: Optional[float] = None,
        layout_nms: Optional[bool] = None,
        **kwargs,
    ) -> List[_MockLayoutResult]:
        shape = getattr(input, "shape", None)
        size = getattr(input, "size", None)
        self.predict_calls.append({
            "type": type(input).__name__,
            "shape": shape,
            "size": size,
            "batch_size": batch_size,
            "threshold": threshold,
            "layout_nms": layout_nms,
            "extra_kwargs": kwargs,
        })
        boxes = self.boxes_factory(input) if callable(self.boxes_factory) else list(self.boxes_factory)
        return [_MockLayoutResult(boxes)]


def _build_two_column_report_fixture() -> Tuple[Image.Image, List[Dict[str, Any]], _RegionAwareMockOCR]:
    """
    Representative 800x1000 2-column compliance report page containing all 8 categories:
    - Header & Footer
    - Document Title + Body Paragraphs (left & right columns)
    - Table (in left column)
    - Chart (in right column, color-tagged green)
    - Figure/Image (in right column)
    - Form (KV block, color-tagged blue)
    - Unknown custom callout region (color-tagged amber)
    """
    img = Image.new("RGB", (800, 1000), "white")
    draw = ImageDraw.Draw(img)
    # Paint faint color swatches inside regions so _RegionAwareMockOCR identifies each crop distinctly
    draw.rectangle((40, 20, 760, 65), fill=(245, 245, 245), outline=(40, 40, 40))       # header
    draw.rectangle((60, 85, 740, 145), fill=(240, 240, 240), outline=(10, 10, 10))      # doc_title
    draw.rectangle((50, 175, 380, 320), fill=(242, 242, 242), outline=(20, 20, 20))     # left paragraph (Bengali Bijoy + digits)
    draw.rectangle((50, 350, 380, 560), fill=(220, 70, 70), outline=(210, 30, 30))      # table (red tag)
    draw.rectangle((420, 175, 750, 315), fill=(70, 80, 225), outline=(25, 45, 210))     # right form KV (blue tag)
    draw.rectangle((420, 345, 750, 535), fill=(70, 200, 70), outline=(20, 180, 20))     # right chart (green tag)
    draw.rectangle((420, 555, 750, 720), fill=(238, 238, 238), outline=(50, 50, 50))    # right figure
    draw.rectangle((50, 595, 380, 735), fill=(230, 185, 60), outline=(210, 170, 20))    # unknown callout (amber tag)
    draw.rectangle((40, 935, 760, 975), fill=(245, 245, 245), outline=(40, 40, 40))      # footer

    # Deliberately supply raw detections in SCRAMBLED score order + one overlapping duplicate
    # so tests prove both deduplication AND reading-order sorting!
    raw_boxes = [
        {"cls_id": 15, "label": "footer", "score": 0.99, "coordinate": [40.0, 935.0, 760.0, 975.0]},
        {"cls_id": 18, "label": "chart", "score": 0.96, "coordinate": [420.0, 345.0, 750.0, 535.0]},
        {"cls_id": 2, "label": "text", "score": 0.95, "coordinate": [420.0, 175.0, 750.0, 315.0]},  # Form KV content!
        {"cls_id": 99, "label": "custom_callout", "score": 0.88, "coordinate": [50.0, 595.0, 380.0, 735.0]},  # Unknown!
        # Duplicate table overlapping the main table at high IoU -> MUST be suppressed!
        {"cls_id": 8, "label": "table", "score": 0.72, "coordinate": [55.0, 355.0, 375.0, 555.0]},
        # Nested paragraph fragment inside table container -> MUST be suppressed!
        {"cls_id": 2, "label": "text", "score": 0.65, "coordinate": [70.0, 370.0, 350.0, 520.0]},
        {"cls_id": 8, "label": "table", "score": 0.94, "coordinate": [50.0, 350.0, 380.0, 560.0]},
        {"cls_id": 1, "label": "image", "score": 0.91, "coordinate": [420.0, 555.0, 750.0, 720.0]},
        {"cls_id": 2, "label": "text", "score": 0.90, "coordinate": [50.0, 175.0, 380.0, 320.0]},
        {"cls_id": 11, "label": "doc_title", "score": 0.97, "coordinate": [60.0, 85.0, 740.0, 145.0]},
        {"cls_id": 13, "label": "header", "score": 0.98, "coordinate": [40.0, 20.0, 760.0, 65.0]},
    ]

    ocr = _RegionAwareMockOCR(
        responses_by_hint={
            "red": (
                "Metric Value Q1 42 Q2 58",
                [
                    {"word": "Metric", "x": 10, "y": 10, "w": 45, "h": 14, "confidence": 0.95},
                    {"word": "Value", "x": 120, "y": 10, "w": 45, "h": 14, "confidence": 0.95},
                    {"word": "Q1", "x": 10, "y": 40, "w": 25, "h": 14, "confidence": 0.95},
                    {"word": "42", "x": 120, "y": 40, "w": 25, "h": 14, "confidence": 0.95},
                ],
            ),
            "blue": (
                "Applicant Name: Tariq Hasan\nDepartment: Compliance\nForm ID: 2026-09",
                [],
            ),
            "green": ("Revenue Growth Chart Q1-Q4 +18%", []),
            "amber": ("Special Unknown Callout Note 99", []),
        }
    )
    return img, raw_boxes, ocr


# ==============================================================================
# 1. VERIFIED MODEL ARTIFACTS & AVAILABILITY TESTS
# ==============================================================================
class TestModelVerificationAndAvailability:
    def test_verified_artifact_metadata_and_23_official_classes(self):
        assert PP_DOCLAYOUT_S_MODEL_NAME == "PP-DocLayout-S"
        assert PP_DOCLAYOUT_S_BACKBONE == "PicoDet-S"
        assert PP_DOCLAYOUT_S_LICENSE == "Apache-2.0"
        assert PP_DOCLAYOUT_S_HF_REPO == "PaddlePaddle/PP-DocLayout-S"
        assert PP_DOCLAYOUT_S_INFERENCE_ARCHIVE == "PP-DocLayout-S_infer.tar"
        assert PP_DOCLAYOUT_S_BCEBOS_URL.endswith("PP-DocLayout-S_infer.tar")
        assert len(PP_DOCLAYOUT_S_LABEL_LIST) == 23
        assert PP_DOCLAYOUT_S_ARTIFACT_METADATA["num_classes"] == 23
        assert PP_DOCLAYOUT_S_ARTIFACT_METADATA["input_size"] == (480, 480)

        # Every one of the 23 official PP-DocLayout-S classes maps deterministically to a canonical category
        mapped = {lbl: classify_layout_label(lbl)[0] for lbl in PP_DOCLAYOUT_S_LABEL_LIST}
        assert len(mapped) == 23
        assert mapped["doc_title"] == LayoutCategory.TITLE_HEADING
        assert mapped["paragraph_title"] == LayoutCategory.TITLE_HEADING
        assert mapped["text"] == LayoutCategory.PARAGRAPH
        assert mapped["table"] == LayoutCategory.TABLE
        assert mapped["chart"] == LayoutCategory.CHART
        assert mapped["image"] == LayoutCategory.FIGURE_IMAGE
        assert mapped["seal"] == LayoutCategory.FORM
        assert mapped["header"] == LayoutCategory.HEADER_FOOTER
        assert mapped["footer"] == LayoutCategory.HEADER_FOOTER

        # Unrecognized labels cleanly become UNKNOWN rather than being discarded
        unk_cat, unk_raw = classify_layout_label("unexpected_custom_block")
        assert unk_cat == LayoutCategory.UNKNOWN
        assert unk_raw == "unexpected_custom_block"

    def test_availability_and_cpu_thread_configuration(self, tmp_path):
        # 1. Missing packages -> is_available() returns False gracefully without crashing
        with patch.object(layout_mod, "HAS_PADDLEOCR_LAYOUT", False), patch.object(layout_mod, "HAS_PADDLEPADDLE", False):
            unavail = PPDocLayoutSProvider(config=PPDocLayoutSConfig(cpu_threads=2))
            assert unavail.is_available() is False
            assert unavail.last_status_reason == "paddle_packages_missing"

        # 2. Missing local model_dir -> is_available() returns False cleanly
        missing_dir = str(tmp_path / "does_not_exist_pp_doclayout_s")
        prov_missing_dir = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(model_dir=missing_dir, cpu_threads=3),
            model_loader=lambda cfg: _SpyPPDocLayoutModel(cfg, []),
        )
        assert prov_missing_dir.is_available() is False
        assert prov_missing_dir.last_status_reason == "model_dir_missing"

        # 3. Valid model_dir + CPU clamping + thread config enforced
        valid_dir = tmp_path / "PP-DocLayout-S"
        valid_dir.mkdir()
        cfg = PPDocLayoutSConfig(model_dir=str(valid_dir), device="cuda:0", cpu_threads=6, enable_mkldnn=True)
        assert cfg.device == "cpu"  # Enforced CPU-only execution
        assert cfg.cpu_threads == 6

        cfg_min = PPDocLayoutSConfig(cpu_threads=0)
        assert cfg_min.cpu_threads == 1

        prov_ok = PPDocLayoutSProvider(config=cfg, model_loader=lambda c: _SpyPPDocLayoutModel(c, []))
        assert prov_ok.is_available() is True

        # 4. Live environment consistency check (succeeds whether PaddleOCR is installed or absent on Python 3.14)
        default_prov = PPDocLayoutSProvider()
        expected = HAS_PADDLEOCR_LAYOUT and HAS_PADDLEPADDLE
        assert default_prov.is_available() is expected


# ==============================================================================
# 2. GEOMETRY, ROTATION, READING ORDER & DEDUPLICATION TESTS
# ==============================================================================
class TestGeometryRotationReadingOrderAndDedup:
    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_rotation_coordinate_transformation_preserves_canonical_normalized_system(self, rotation: int):
        # Original unrotated box at top-left quadrant: x=[50..250], y=[100..220] on 600x800 page
        src_w, src_h = 600.0, 800.0
        unrot = (50.0, 100.0, 250.0, 220.0)
        rot_box, (disp_w, disp_h) = transform_box_for_rotation(*unrot, src_w, src_h, rotation)

        # Render unrotated black target block & rotate image CW cleanly via PIL (-rotation)
        canvas = Image.new("RGB", (600, 800), "white")
        ImageDraw.Draw(canvas).rectangle(unrot, fill="black")
        rot_img = canvas if rotation == 0 else canvas.rotate(-rotation, expand=True)
        assert rot_img.size == (int(disp_w), int(disp_h))

        # Sampling center of transformed box on rotated image MUST hit the black target rectangle!
        cx = int((rot_box[0] + rot_box[2]) / 2.0)
        cy = int((rot_box[1] + rot_box[3]) / 2.0)
        assert sum(rot_img.getpixel((cx, cy))) < 20

        # Wire unrotated raw model output through PPDocLayoutSProvider with coords_in_unrotated_space=True
        WorkerLayoutModelCache.clear()
        spy_ocr = _RegionAwareMockOCR()
        prov = PPDocLayoutSProvider(
            ocr_provider=spy_ocr,
            config=PPDocLayoutSConfig(auto_rotate=False, reuse_worker_model=False),
            model_loader=lambda c: _SpyPPDocLayoutModel(
                c,
                [{"cls_id": 11, "label": "doc_title", "score": 0.93, "coordinate": list(unrot)}],
            ),
        )
        res = prov.analyze_image(
            rot_img,
            context={
                "page_number": 1,
                "source_rotation": rotation,
                "coords_in_unrotated_space": True,
                "apply_auto_rotate": False,
            },
        )
        canvas.close()
        if rot_img is not canvas:
            rot_img.close()

        assert res["status"] == "success"
        assert res["rotated_degrees"] == rotation
        reg = res["regions"][0]
        nb = reg["normalized_box"]  # Canonical [ymin, xmin, ymax, xmax] in 0..1000
        assert len(nb) == 4 and all(0 <= v <= 1000 for v in nb)
        assert nb[0] < nb[2] and nb[1] < nb[3]

        # Expected center in normalized rotated display space
        exp_ymin = round((rot_box[1] / disp_h) * 1000)
        exp_xmin = round((rot_box[0] / disp_w) * 1000)
        assert abs(nb[0] - exp_ymin) <= 2
        assert abs(nb[1] - exp_xmin) <= 2

    def test_exif_auto_rotation_orients_portrait_output_coords_cleanly(self):
        # Paint black header bar on what SHOULD be top after 270deg CW EXIF correction
        img = Image.new("RGB", (600, 400), "white")
        ImageDraw.Draw(img).rectangle((20, 20, 580, 100), fill="black")
        exif = img.getexif()
        exif[274] = 6  # EXIF Orientation 6 -> 90 deg CW image that needs 270 deg rotation to upright

        WorkerLayoutModelCache.clear()
        model_boxes = [{"cls_id": 13, "label": "header", "score": 0.95, "coordinate": [20.0, 20.0, 380.0, 90.0]}]
        prov = PPDocLayoutSProvider(
            ocr_provider=_RegionAwareMockOCR(),
            config=PPDocLayoutSConfig(auto_rotate=True, reuse_worker_model=False),
            model_loader=lambda c: _SpyPPDocLayoutModel(c, model_boxes),
        )
        exif_buf = io.BytesIO()
        img.save(exif_buf, format="JPEG", exif=exif.tobytes())
        exif_buf.seek(0)
        img_with_exif = Image.open(exif_buf)
        img_with_exif.load()

        res = prov.analyze_image(img_with_exif)
        img.close()
        img_with_exif.close()
        exif_buf.close()
        assert res["status"] == "success"
        assert res["rotated_degrees"] == 270
        # EXIF transpose turned 600x400 into 400x600 upright dimensions
        assert res["width"] == 400.0 and res["height"] == 600.0
        assert res["regions"][0]["normalized_box"][0] < 100

    def test_deduplication_and_two_column_reading_order_preservation(self):
        dets = [
            # Scrambled order: footer, right-col, nested-text-inside-table, duplicate-table, left-col, header, doc_title
            {"layout_category": "footer", "raw_label": "footer", "score": 0.99, "normalized_box": [920, 40, 980, 960]},
            {"layout_category": "header_footer", "raw_label": "footer", "score": 0.99, "normalized_box": [920, 40, 980, 960]},
            {"layout_category": "paragraph", "raw_label": "text", "score": 0.92, "normalized_box": [200, 530, 450, 950]},
            {"layout_category": "chart", "raw_label": "chart", "score": 0.94, "normalized_box": [480, 530, 750, 950]},
            {"layout_category": "paragraph", "raw_label": "text", "score": 0.60, "normalized_box": [400, 60, 580, 440]},   # nested in table
            {"layout_category": "table", "raw_label": "table", "score": 0.70, "normalized_box": [390, 55, 595, 455]},       # dup table
            {"layout_category": "table", "raw_label": "table", "score": 0.96, "normalized_box": [380, 50, 600, 460]},       # main table
            {"layout_category": "paragraph", "raw_label": "text", "score": 0.95, "normalized_box": [200, 50, 350, 460]},
            {"layout_category": "title_heading", "raw_label": "doc_title", "score": 0.98, "normalized_box": [100, 60, 170, 940]},
            {"layout_category": "header_footer", "raw_label": "header", "score": 0.99, "normalized_box": [20, 40, 80, 960]},
        ]
        # Clean invalid first toy dict if present, use canonical 8 categories
        valid_dets = [d for d in dets if d["layout_category"] != "footer"]
        deduped = deduplicate_layout_regions(valid_dets)
        ordered = sort_regions_reading_order(deduped)

        # Duplicate table & nested paragraph inside table MUST be suppressed -> 7 distinct regions remain
        assert len(ordered) == 7
        cats_in_order = [r["layout_category"] for r in ordered]
        assert cats_in_order == [
            "header_footer",   # Top header
            "title_heading",   # Full-width doc title
            "paragraph",       # Left column paragraph
            "table",           # Left column table
            "paragraph",       # Right column paragraph
            "chart",           # Right column chart
            "header_footer",   # Bottom footer
        ]
        assert [r["reading_order"] for r in ordered] == [1, 2, 3, 4, 5, 6, 7]


# ==============================================================================
# 3. FULL FIXTURE ROUTING, WORKER MODEL REUSE, FALLBACK & GOVERNANCE SAFETY
# ==============================================================================
class TestRoutingReuseFallbackAndGovernanceSafety:
    def test_representative_two_column_fixture_routes_all_categories_and_preserves_unknown(self):
        WorkerLayoutModelCache.clear()
        img, raw_boxes, spy_ocr = _build_two_column_report_fixture()

        prov = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(cpu_threads=4, enable_mkldnn=True, auto_rotate=False),
            ocr_provider=spy_ocr,
            model_loader=lambda c: _SpyPPDocLayoutModel(c, raw_boxes),
        )
        res = prov.analyze_image(img, context={"page_number": 1, "source_asset_name": "report.png"})
        img.close()

        assert res["status"] == "success"
        assert res["engine"] == "pp_doclayout_s"
        assert res["engine_version"] == "PP-DocLayout-S"
        regions = res["regions"]
        # 11 raw boxes minus 2 duplicates (duplicate table + nested text inside table) = 9 unique regions!
        assert len(regions) == 9

        # Reading order verified: Header -> Doc Title -> Left Col (Para, Table, Unknown) -> Right Col (Form, Chart, Figure) -> Footer
        routes = [r["metadata"]["extraction_route"] for r in regions]
        cats = [r["metadata"]["layout_category"] for r in regions]
        assert cats == [
            "header_footer",
            "title_heading",
            "paragraph",
            "table",
            "unknown",
            "form",
            "chart",
            "figure_image",
            "header_footer",
        ]
        assert LayoutExtractorRoute.TABLE_EXTRACTOR.value in routes or "table_ocr_extractor" in routes
        assert LayoutExtractorRoute.FORM_KV_EXTRACTOR.value in routes
        assert LayoutExtractorRoute.UNKNOWN_FALLBACK_OCR.value in routes

        # Table region rendered as Markdown pipe table
        tbl_reg = next(r for r in regions if r["region_type"] == VisualRegionType.TABLE.value)
        assert "| Metric | Value |" in tbl_reg["text"]

        # Form KV region preserved structured form fields
        form_reg = next(r for r in regions if r["region_type"] == VisualRegionType.FORM_KV.value)
        assert len(form_reg["metadata"]["form_fields"]) == 3
        assert form_reg["metadata"]["form_fields"][0] == {"field": "Applicant Name", "value": "Tariq Hasan"}

        # Unknown region preserved with its extracted text & unknown classification
        unk_reg = next(r for r in regions if r["region_type"] == VisualRegionType.UNKNOWN.value)
        assert unk_reg["metadata"]["raw_label"] == "custom_callout"
        assert "Special Unknown Callout Note 99" in unk_reg["text"]

        # Every region + synthesized page passes strict LORE integration contract
        page = VisualPipelineIntegrationAdapter.merge_baseline_and_visual_page(
            baseline_page={
                "page_number": 1,
                "text": "",
                "confidence": 0.0,
                "words_count": 0,
                "width": res["width"],
                "height": res["height"],
                "extraction_type": "layout_pp_doclayout_s",
                "engine": "pp_doclayout_s",
                "engine_version": "PP-DocLayout-S",
                "is_repaired": False,
                "bounding_boxes": [],
            },
            visual_regions=regions,
        )
        VisualPipelineIntegrationAdapter.validate_page_payload(page, strict=True)

        # STRICT NON-INTERFERENCE INVARIANT: layout outputs NEVER emit governance/authority/evidence decisions
        forbidden_governance_keys = {
            "verdict",
            "directive",
            "authority_tier",
            "approval_status",
            "is_approved",
            "publication_status",
            "allowed_roles",
            "permissions",
            "evidence_status",
        }
        assert forbidden_governance_keys.isdisjoint(set(res.keys()))
        assert forbidden_governance_keys.isdisjoint(set(page.keys()))
        for r in regions:
            assert forbidden_governance_keys.isdisjoint(set(r.keys()))
            assert forbidden_governance_keys.isdisjoint(set(r["metadata"].keys()))

    def test_worker_model_reused_across_pages_and_keyed_by_thread_config(self):
        WorkerLayoutModelCache.clear()
        created_configs: List[Tuple[str, int, bool]] = []

        def _counting_loader(cfg: PPDocLayoutSConfig) -> _SpyPPDocLayoutModel:
            created_configs.append((cfg.device, cfg.cpu_threads, cfg.enable_mkldnn))
            return _SpyPPDocLayoutModel(
                cfg,
                [{"cls_id": 2, "label": "text", "score": 0.9, "coordinate": [20.0, 20.0, 380.0, 180.0]}],
            )

        img = Image.new("RGB", (400, 200), "white")
        prov_a = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(cpu_threads=2, enable_mkldnn=True, auto_rotate=False),
            ocr_provider=_RegionAwareMockOCR(),
            model_loader=_counting_loader,
        )
        prov_b = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(cpu_threads=2, enable_mkldnn=True, auto_rotate=False),
            ocr_provider=_RegionAwareMockOCR(),
            model_loader=_counting_loader,
        )

        # Three predictions across two provider instances in same worker -> 1 model load, 2 cache reuses!
        prov_a.analyze_image(img, context={"page_number": 1})
        prov_a.analyze_image(img, context={"page_number": 2})
        prov_b.analyze_image(img, context={"page_number": 3})

        stats = WorkerLayoutModelCache.stats()
        assert stats["load_count"] == 1
        assert stats["reuse_count"] == 2
        assert created_configs == [("cpu", 2, True)]

        # Different cpu_threads creates a distinct worker entry cleanly
        prov_4t = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(cpu_threads=4, enable_mkldnn=False, auto_rotate=False),
            ocr_provider=_RegionAwareMockOCR(),
            model_loader=_counting_loader,
        )
        prov_4t.analyze_image(img, context={"page_number": 1})
        img.close()
        assert WorkerLayoutModelCache.stats()["load_count"] == 2
        assert created_configs[-1] == ("cpu", 4, False)

    def test_graceful_fallback_on_unavailability_or_inference_crash(self):
        WorkerLayoutModelCache.clear()
        img = Image.new("RGB", (400, 300), "white")
        ImageDraw.Draw(img).rectangle((40, 40, 360, 220), fill="black")
        spy_ocr = _RegionAwareMockOCR()

        # 1. Unavailable runtime (packages missing) -> deterministic visual fallback preserves valid output
        with patch.object(layout_mod, "HAS_PADDLEOCR_LAYOUT", False), patch.object(layout_mod, "HAS_PADDLEPADDLE", False):
            unavail = PPDocLayoutSProvider(ocr_provider=spy_ocr)
            fb_res = unavail.analyze_image(img, context={"page_number": 1})
            assert fb_res["fallback_applied"] is True
            assert fb_res["is_optional_skipped"] is True
            assert fb_res["status"] == "fallback_deterministic"
            assert len(fb_res["regions"]) >= 1

        # 2. Runtime inference exception -> falls back cleanly with sanitized error reason (no crash!)
        def _broken_loader(cfg: PPDocLayoutSConfig) -> Any:
            class _ExplodingModel:
                def predict(self, *args, **kwargs):
                    raise RuntimeError("inference boom api_key=sk-secret-12345")
            return _ExplodingModel()

        broken_prov = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(reuse_worker_model=False, auto_rotate=False),
            ocr_provider=spy_ocr,
            model_loader=_broken_loader,
        )
        crash_fb = broken_prov.analyze_image(img, context={"page_number": 1})
        img.close()
        assert crash_fb["fallback_applied"] is True
        assert crash_fb["is_optional_skipped"] is True
        assert "sk-secret-12345" not in str(crash_fb)

    @pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for PDF layout+fallback fixture")
    def test_pdf_integration_dedup_native_tables_scanned_form_and_fallback_to_ocr(self):
        WorkerLayoutModelCache.clear()
        # Build 2-page PDF:
        # Page 1 (mixed_content): Native digital text + native grid table (must NOT be duplicated by layout!) + chart
        # Page 2 (scanned): Scanned form raster with Form KV + official seal + Bengali text
        doc = pymupdf.open()

        p1 = doc.new_page(width=612, height=792)
        p1.insert_text((60, 70), "Enterprise Financial Policy Compliance Section With Over Twenty Characters", fontsize=12)
        # Draw bordered native PDF table on p1 for find_tables()
        sh = p1.new_shape()
        for r in range(3):
            sh.draw_line((60, 140 + r * 28), (340, 140 + r * 28))
        for c in (60, 200, 340):
            sh.draw_line((c, 140), (c, 196))
        sh.finish(width=1.0)
        sh.commit()
        p1.insert_text((70, 158), "Quarter", fontsize=10)
        p1.insert_text((210, 158), "Revenue", fontsize=10)
        p1.insert_text((70, 186), "Q1", fontsize=10)
        p1.insert_text((210, 186), "120M", fontsize=10)
        # Visual chart block
        blk = Image.new("RGB", (180, 120), (20, 160, 20))
        buf = io.BytesIO()
        blk.save(buf, format="PNG")
        blk.close()
        p1.insert_image(pymupdf.Rect(380, 140, 560, 260), stream=buf.getvalue())

        # Page 2: pure scanned form + seal raster image
        p2 = doc.new_page(width=612, height=792)
        scan_img = Image.new("RGB", (612, 792), "white")
        sd = ImageDraw.Draw(scan_img)
        sd.rectangle((50, 80, 560, 240), fill=(70, 80, 225), outline=(20, 40, 200))
        sd.rectangle((400, 300, 540, 420), fill=(220, 70, 70), outline=(200, 30, 30))
        sbuf = io.BytesIO()
        scan_img.save(sbuf, format="PNG")
        scan_img.close()
        p2.insert_image(pymupdf.Rect(0, 0, 612, 792), stream=sbuf.getvalue())

        pdf_bytes = doc.tobytes()
        doc.close()

        # Map predictions relative to whatever pixel size PyMuPDF renders at 150 DPI
        def _page_boxes_factory(inp: Any) -> List[Dict[str, Any]]:
            h, w = inp.shape[:2] if hasattr(inp, "shape") else (inp.height, inp.width)
            # First page uses native table coords matching PyMuPDF (60..340, 140..196 on 612x792)
            # Second page returns Form KV + Seal
            if _page_boxes_factory.idx == 0:
                _page_boxes_factory.idx += 1
                sx, sy = w / 612.0, h / 792.0
                return [
                    {"cls_id": 11, "label": "doc_title", "score": 0.96, "coordinate": [55 * sx, 50 * sy, 550 * sx, 95 * sy]},
                    {"cls_id": 8, "label": "table", "score": 0.94, "coordinate": [58 * sx, 138 * sy, 342 * sx, 198 * sy]},
                    {"cls_id": 18, "label": "chart", "score": 0.92, "coordinate": [380 * sx, 140 * sy, 560 * sx, 260 * sy]},
                ]
            sx, sy = w / 612.0, h / 792.0
            return [
                {"cls_id": 2, "label": "form", "score": 0.95, "coordinate": [50 * sx, 80 * sy, 560 * sx, 240 * sy]},
                {"cls_id": 16, "label": "seal", "score": 0.89, "coordinate": [400 * sx, 300 * sy, 540 * sx, 420 * sy]},
            ]

        _page_boxes_factory.idx = 0

        spy_ocr = _RegionAwareMockOCR(
            responses_by_hint={
                "blue": ("License No: BD-901\nStatus: Active", []),
                "red": ("Approved Seal 2026", []),
                "green": ("Revenue Trend Chart", []),
            }
        )
        layout_prov = PPDocLayoutSProvider(
            config=PPDocLayoutSConfig(cpu_threads=3, auto_rotate=False),
            ocr_provider=spy_ocr,
            model_loader=lambda cfg: _SpyPPDocLayoutModel(cfg, _page_boxes_factory),
        )
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=spy_ocr, layout_provider=layout_prov)
        pages = adapter.process_pdf(pdf_bytes)

        assert len(pages) == 2
        # Page 1: native table NOT duplicated (only 1 table region + 1 chart region; layout table deduplicated!)
        p1_types = [r["region_type"] for r in pages[0]["visual_regions"]]
        assert p1_types.count(VisualRegionType.TABLE.value) == 1
        assert VisualRegionType.CHART.value in p1_types
        assert pages[0]["visual_metadata"]["layout_provider"] == "pp_doclayout_s"
        assert any(lr.get("deduplicated_against") for lr in pages[0]["visual_metadata"]["layout_regions"])
        assert "| Quarter |" in pages[0]["text"]
        assert "Revenue |" in pages[0]["text"]
        assert "120M" in pages[0]["text"]

        # Page 2 (scanned): Form + Seal extracted cleanly in order!
        p2_types = [r["region_type"] for r in pages[1]["visual_regions"]]
        assert p2_types == [VisualRegionType.FORM_KV.value, VisualRegionType.STAMP_OR_SEAL.value]
        assert "License No: BD-901" in pages[1]["text"]

        # Worker cache reused same loaded model across Page 1 & Page 2!
        stats = WorkerLayoutModelCache.stats()
        assert stats["load_count"] == 1
        assert stats["reuse_count"] == 1

        # Fallback test inside PyMuPDFVisualPDFAdapter: unavailable layout falls back cleanly to OCR pipeline!
        with patch.object(layout_mod, "HAS_PADDLEOCR_LAYOUT", False), patch.object(layout_mod, "HAS_PADDLEPADDLE", False):
            unavail_layout = PPDocLayoutSProvider(ocr_provider=spy_ocr)
            fb_adapter = PyMuPDFVisualPDFAdapter(ocr_provider=spy_ocr, layout_provider=unavail_layout)
            fb_pages = fb_adapter.process_pdf(pdf_bytes)
            assert len(fb_pages) == 2
            assert fb_pages[1]["extraction_type"] == "ocr_tesseract"
            assert fb_pages[1]["visual_metadata"]["fallback_applied"] is True

        # Live Tesseract smoke test when installed on host (does not fail if omitted)
        real_tess = TesseractOCRProvider()
        if real_tess.is_available():
            ext_factory = VisualDocumentExtractor.with_pp_doclayout_s(ocr_provider=real_tess, use_pymupdf=True)
            assert ext_factory.pdf_visual_adapter.ocr_provider.is_available() is True
