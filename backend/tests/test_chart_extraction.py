"""
Verification suite for LORE's deterministic chart extraction (PyMuPDF + OpenCV +
existing TesseractOCRProvider).

Covers:
1. Supported chart types: vertical bar, horizontal bar, grouped bar, stacked bar,
   line chart, pie chart, scatter plot, and unknown/ambiguous chart.
2. Vector PDF, raster PNG, and mixed-content PDF paths using real PyMuPDF,
   real OpenCV, and real TesseractOCRProvider (plus controlled OCR mocks for
   Bangla/low-confidence/unavailable edge cases).
3. Axis calibration without zero-origin or equal-interval assumptions: non-zero
   origins, negative zero-crossing values, log10 scale, and irregular-interval
   rejection (`unavailable` + `review_required=True`).
4. Dual Y axes (left Y1 + right Y2): unambiguous unit/color binding vs
   ambiguous dual-axis refusal (`unavailable` + `review_required=True`).
5. Units, legends, rotated Y titles, Bengali/English label repair & OCR metadata,
   crop reference & source coordinates, low-resolution & missing-label handling.
6. End-to-end integration with PyMuPDFVisualPDFAdapter, VisualDocumentExtractor,
   and PPDocLayoutSProvider, plus strict Settlement / Knowledge Store isolation.
"""

from __future__ import annotations

import io
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from unittest.mock import patch

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from apps.ingestion.pipeline import charts as charts_mod
from apps.ingestion.pipeline.charts import (
    ChartExtractorConfig,
    ChartSourceMode,
    ChartType,
    PyMuPDFOpenCVChartExtractor,
    ValuePrecisionStatus,
    calibrate_numeric_axis,
    detect_chart_candidates_in_pdf_page,
    detect_chart_regions_opencv,
    is_likely_chart_raster_opencv,
)
from apps.ingestion.pipeline.contracts import (
    VisualExtractionKind,
    VisualPipelineIntegrationAdapter,
    VisualRegionType,
)
from apps.ingestion.pipeline.layout import (
    PPDocLayoutSConfig,
    PPDocLayoutSProvider,
    WorkerLayoutModelCache,
)
from apps.ingestion.pipeline.ocr import BaseOCRProvider, TesseractOCRProvider
from apps.ingestion.pipeline.pdf_visual import PyMuPDFVisualPDFAdapter
from apps.ingestion.pipeline.visual import VisualDocumentExtractor


def _load_font(size: int = 16) -> ImageFont.ImageFont:
    for candidate in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_rotated_text(
    img: Image.Image,
    xy_center: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int] = (20, 20, 20),
    angle: int = 90,
) -> None:
    tmp = Image.new("RGBA", (360, 80), (255, 255, 255, 0))
    td = ImageDraw.Draw(tmp)
    td.text((10, 10), text, font=font, fill=(*fill, 255))
    bbox = tmp.getbbox()
    if bbox:
        tmp = tmp.crop(bbox)
    rot = tmp.rotate(angle, expand=True)
    px = max(0, int(xy_center[0] - rot.width // 2))
    py = max(0, int(xy_center[1] - rot.height // 2))
    img.paste(rot.convert("RGB"), (px, py), rot.split()[3])


class _StaticOrTagMockOCR(BaseOCRProvider):
    """Deterministic OCR provider stub for controlled Bengali, low-confidence, and error cases."""

    def __init__(
        self,
        *,
        available: bool = True,
        lang: str = "ben+eng",
        confidence: float = 0.88,
        status: str = "success",
        warnings: Optional[List[str]] = None,
        tokens: Optional[List[Dict[str, Any]]] = None,
        full_text: str = "",
    ):
        self._available = available
        self.lang = lang
        self._confidence = confidence
        self._status = status
        self._warnings = list(warnings or [])
        self._tokens = list(tokens or [])
        self._full_text = full_text
        self.calls: List[Tuple[int, int]] = []

    def is_available(self) -> bool:
        return self._available

    def get_version(self) -> str:
        return "5.5.0-mock" if self._available else "unavailable"

    def extract_image(self, image: Image.Image, *args, **kwargs) -> Dict[str, Any]:
        self.calls.append((image.width, image.height))
        if not self._available:
            return {
                "text": "",
                "confidence": 0.0,
                "status": "provider_unavailable",
                "engine": "tesseract",
                "engine_version": "unavailable",
                "language": self.lang,
                "warnings": ["Tesseract unavailable in mock"],
                "needs_review": True,
                "bounding_boxes": [],
            }
        # Map tokens roughly to image dimensions on full-crop call; skip small tick band repeats cleanly
        if image.height > 120 and image.width > 180 and self._tokens:
            boxes = []
            for tk in self._tokens:
                bx, by, bw, bh = tk["bbox"]
                boxes.append({
                    "word": tk["text"],
                    "confidence": float(tk.get("confidence", self._confidence)),
                    "x": bx,
                    "y": by,
                    "w": bw,
                    "h": bh,
                    "normalized_box": [
                        int(round(by * 1000.0 / max(1, image.height))),
                        int(round(bx * 1000.0 / max(1, image.width))),
                        int(round((by + bh) * 1000.0 / max(1, image.height))),
                        int(round((bx + bw) * 1000.0 / max(1, image.width))),
                    ],
                })
            return {
                "text": self._full_text or " ".join(tk["text"] for tk in self._tokens),
                "confidence": self._confidence,
                "status": self._status,
                "engine": "tesseract",
                "engine_version": self.get_version(),
                "language": self.lang,
                "warnings": list(self._warnings),
                "needs_review": self._confidence < 0.65,
                "bounding_boxes": boxes,
            }
        return {
            "text": "",
            "confidence": self._confidence,
            "status": "empty_scan",
            "engine": "tesseract",
            "engine_version": self.get_version(),
            "language": self.lang,
            "warnings": list(self._warnings),
            "needs_review": False,
            "bounding_boxes": [],
        }


class _SpyLayoutModel:
    def __init__(self, detections: List[Dict[str, Any]]):
        self.detections = detections
        self.predict_calls = 0

    def predict(self, img_bgr: Any, **kwargs) -> List[Dict[str, Any]]:
        self.predict_calls += 1
        return [{"boxes": list(self.detections)}]


def _render_pdf_page_pil(page: pymupdf.Page, dpi: int = 150) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    try:
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        pix = None


def _draw_vector_axes(
    page: pymupdf.Page,
    *,
    px0: float,
    py0: float,
    px1: float,
    py1: float,
    y_ticks: Sequence[Tuple[float, str]],
    x_ticks_or_cats: Sequence[Tuple[float, str]] = (),
    title: str = "",
    y_title: str = "",
    x_title: str = "",
    y2_ticks: Sequence[Tuple[float, str]] = (),
    y2_title: str = "",
) -> None:
    shape = page.new_shape()
    # Left Y axis + bottom X axis
    shape.draw_line((px0, py0), (px0, py1))
    shape.draw_line((px0, py1), (px1, py1))
    if y2_ticks:
        shape.draw_line((px1, py0), (px1, py1))
    # Ticks
    for ty, _ in y_ticks:
        shape.draw_line((px0 - 5, ty), (px0, ty))
    for ty, _ in y2_ticks:
        shape.draw_line((px1, ty), (px1 + 5, ty))
    shape.finish(color=(0.15, 0.15, 0.15), width=1.2)
    shape.commit()

    if title:
        page.insert_text((px0 + 40, py0 - 16), title, fontsize=11, color=(0.1, 0.1, 0.1))
    if y_title:
        page.insert_text((max(8.0, px0 - 65), py0 + (py1 - py0) * 0.55), y_title, fontsize=9, rotate=90, color=(0.1, 0.1, 0.1))
    if y2_title:
        page.insert_text((px1 + 48, py0 + (py1 - py0) * 0.55), y2_title, fontsize=9, rotate=90, color=(0.8, 0.15, 0.15))
    if x_title:
        page.insert_text((px0 + (px1 - px0) * 0.40, py1 + 32), x_title, fontsize=9, color=(0.1, 0.1, 0.1))

    for ty, lbl in y_ticks:
        page.insert_text((px0 - 38, ty + 3), lbl, fontsize=9, color=(0.1, 0.1, 0.1))
    for ty, lbl in y2_ticks:
        page.insert_text((px1 + 8, ty + 3), lbl, fontsize=9, color=(0.75, 0.1, 0.1))
    for tx, lbl in x_ticks_or_cats:
        page.insert_text((tx - 10, py1 + 14), lbl, fontsize=9, color=(0.1, 0.1, 0.1))


class TestChartTypesVectorAndRaster:
    def test_vector_vertical_bar_chart_nonzero_origin_and_units(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=612, height=792)
            px0, py0, px1, py1 = 110.0, 140.0, 480.0, 380.0
            # Non-zero Y axis: 100 at bottom (py1=380), 160 at top (py0=140) => 4 pt per unit
            y_ticks = [
                (380.0, "100"),
                (300.0, "120"),
                (220.0, "140"),
                (140.0, "160"),
            ]
            cats = [(185.0, "Q1"), (295.0, "Q2"), (405.0, "Q3")]
            _draw_vector_axes(
                page,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=y_ticks,
                x_ticks_or_cats=cats,
                title="Quarterly Output",
                y_title="Revenue ($M)",
            )
            # Bars representing 115, 142 (explicit data label!), and 155
            bars = [
                (165.0, 380.0 - (115.0 - 100.0) * 4.0, 205.0, 380.0, (0.2, 0.45, 0.85)),
                (275.0, 380.0 - (142.0 - 100.0) * 4.0, 315.0, 380.0, (0.2, 0.45, 0.85)),
                (385.0, 380.0 - (155.0 - 100.0) * 4.0, 425.0, 380.0, (0.2, 0.45, 0.85)),
            ]
            shape = page.new_shape()
            for x0, y0, x1, y1, col in bars:
                shape.draw_rect(pymupdf.Rect(x0, y0, x1, y1))
                shape.finish(fill=col, color=col)
            shape.commit()
            # Explicit native data label on Q2 only
            page.insert_text((285.0, bars[1][1] - 6), "142", fontsize=9, color=(0.1, 0.1, 0.1))

            img = _render_pdf_page_pil(page, dpi=150)
            try:
                extractor = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                cands = detect_chart_candidates_in_pdf_page(pymupdf_page=page, page_number=1)
                assert len(cands) == 1

                reg = extractor.extract_chart_region(
                    page_image=img,
                    chart_box=cands[0]["bbox_display"],
                    bbox_format="display",
                    page_number=1,
                    page_width=612.0,
                    page_height=792.0,
                    pymupdf_page=page,
                )
            finally:
                img.close()
        finally:
            doc.close()

        meta = reg["metadata"]
        chart = meta["chart"]
        assert reg["region_type"] == VisualRegionType.CHART.value
        assert reg["extraction_kind"] == VisualExtractionKind.CHART_SERIES.value
        assert chart["chart_type"] == ChartType.VERTICAL_BAR.value
        assert chart["source_mode"] == ChartSourceMode.VECTOR.value

        y_cal = chart["axes"]["y_primary"]
        assert y_cal["is_valid"] is True
        assert y_cal["origin_value"] == pytest.approx(100.0, abs=0.5)
        assert "$M" in y_cal["unit"]

        pts = chart["series"][0]["data_points"]
        assert len(pts) == 3
        by_cat = {p["category"]: p for p in pts}
        # Never assumes origin=0: Q1 ~ 115 (not 15), Q3 ~ 155 (not 55)
        assert by_cat["Q1"]["precision"] == ValuePrecisionStatus.ESTIMATED.value
        assert by_cat["Q1"]["value"] == pytest.approx(115.0, abs=2.5)
        assert by_cat["Q2"]["precision"] == ValuePrecisionStatus.EXACT.value
        assert by_cat["Q2"]["value"] == pytest.approx(142.0, abs=0.5)
        assert by_cat["Q3"]["precision"] == ValuePrecisionStatus.ESTIMATED.value
        assert by_cat["Q3"]["value"] == pytest.approx(155.0, abs=2.5)

        assert meta["chart_crop_reference"]["crop_ref"].startswith("lore://charts/crops/")
        assert meta["source_coordinates"]["display_bbox_xywh"] == reg["bbox"]
        assert meta["source_coordinates"]["normalized_box"] == reg["normalized_box"]
        assert meta["review_required"] is False

    def test_raster_vertical_bar_chart_with_real_opencv_and_tesseract(self):
        img = Image.new("RGB", (680, 440), "white")
        try:
            draw = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_lbl = _load_font(16)
            px0, py0, px1, py1 = 125, 70, 620, 355

            # Dark axes + ticks
            draw.line((px0, py0, px0, py1), fill=(15, 15, 15), width=3)
            draw.line((px0, py1, px1, py1), fill=(15, 15, 15), width=3)
            draw.text((220, 18), "Regional Units", font=f_title, fill=(10, 10, 10))
            _draw_rotated_text(img, (28, 210), "Units Sold", font=f_lbl, angle=90)

            for val in (0, 25, 50, 75, 100):
                ty = int(round(py1 - (val / 100.0) * (py1 - py0)))
                draw.line((px0 - 7, ty, px0, ty), fill=(15, 15, 15), width=2)
                draw.text((px0 - 48, ty - 10), str(val), font=f_lbl, fill=(10, 10, 10))

            specs = [("East", 40, 200), ("West", 80, 370), ("North", 60, 540)]
            for cat, val, cx in specs:
                top = int(round(py1 - (val / 100.0) * (py1 - py0)))
                draw.rectangle((cx - 32, top, cx + 32, py1 - 2), fill=(40, 110, 205))
                draw.text((cx - 22, py1 + 14), cat, font=f_lbl, fill=(10, 10, 10))

            assert is_likely_chart_raster_opencv(img) is True
            boxes = detect_chart_regions_opencv(img)
            assert len(boxes) == 1

            extractor = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = extractor.extract_chart_region(
                page_image=img,
                chart_box=boxes[0],
                bbox_format="pixel",
                page_number=1,
                page_width=680.0,
                page_height=440.0,
            )
        finally:
            img.close()

        meta = reg["metadata"]
        chart = meta["chart"]
        assert chart["chart_type"] == ChartType.VERTICAL_BAR.value
        assert chart["source_mode"] == ChartSourceMode.RASTER.value
        assert meta["ocr_metadata"]["ocr_triggered"] is True
        assert meta["ocr_metadata"]["engine"] == "tesseract"
        assert chart["axes"]["y_primary"]["is_valid"] is True

        pts = chart["series"][0]["data_points"]
        assert len(pts) == 3
        # Strictly NEVER mark pixel geometry estimates as 'exact'
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in pts)
        vals = [p["value"] for p in pts]
        assert vals[0] == pytest.approx(40.0, abs=7.0)
        assert vals[1] == pytest.approx(80.0, abs=7.0)
        assert vals[2] == pytest.approx(60.0, abs=7.0)
        assert any("East" in str(p["category"]) for p in pts)

    def test_vector_horizontal_bar_chart(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=600, height=450)
            px0, py0, px1, py1 = 120.0, 90.0, 480.0, 330.0
            shape = page.new_shape()
            shape.draw_line((px0, py0), (px0, py1))
            shape.draw_line((px0, py1), (px1, py1))
            # X ticks: 0..60 across 360 pt (6 pt per unit)
            x_ticks = [(120.0, "0"), (240.0, "20"), (360.0, "40"), (480.0, "60")]
            for tx, _ in x_ticks:
                shape.draw_line((tx, py1), (tx, py1 + 5))
            shape.finish(color=(0.15, 0.15, 0.15), width=1.2)
            shape.commit()

            for tx, lbl in x_ticks:
                page.insert_text((tx - 6, py1 + 18), lbl, fontsize=9, color=(0.1, 0.1, 0.1))

            rows = [("Alpha", 130.0, 25.0), ("Beta", 205.0, 45.0), ("Gamma", 280.0, 15.0)]
            shape = page.new_shape()
            for _, ry, val in rows:
                shape.draw_rect(pymupdf.Rect(px0, ry - 14, px0 + val * 6.0, ry + 14))
                shape.finish(fill=(0.15, 0.62, 0.45), color=(0.15, 0.62, 0.45))
            shape.commit()
            for cat, ry, _ in rows:
                page.insert_text((52.0, ry + 4), cat, fontsize=10, color=(0.1, 0.1, 0.1))

            img = _render_pdf_page_pil(page, dpi=150)
            try:
                extractor = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg = extractor.extract_chart_region(
                    page_image=img,
                    chart_box=[30.0, 60.0, 520.0, 370.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=600.0,
                    page_height=450.0,
                    pymupdf_page=page,
                )
            finally:
                img.close()
        finally:
            doc.close()

        chart = reg["metadata"]["chart"]
        assert chart["chart_type"] == ChartType.HORIZONTAL_BAR.value
        assert chart["axes"]["x"]["is_valid"] is True
        pts = chart["series"][0]["data_points"]
        by_cat = {p["category"]: p for p in pts}
        assert by_cat["Alpha"]["value"] == pytest.approx(25.0, abs=2.5)
        assert by_cat["Beta"]["value"] == pytest.approx(45.0, abs=2.5)
        assert by_cat["Gamma"]["value"] == pytest.approx(15.0, abs=2.5)
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in pts)

    def test_grouped_and_stacked_bar_charts(self):
        doc = pymupdf.open()
        try:
            # Page 1: Grouped Bar Chart
            p1 = doc.new_page(width=620, height=500)
            px0, py0, px1, py1 = 100.0, 90.0, 480.0, 350.0
            _draw_vector_axes(
                p1,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(350.0, "0"), (220.0, "50"), (90.0, "100")],
                x_ticks_or_cats=[(190.0, "East"), (360.0, "West")],
            )
            # 2024 (blue) vs 2025 (orange) side-by-side + legend boxes in top-right
            s1 = p1.new_shape()
            # Legend swatches outside/upper plot
            s1.draw_rect(pymupdf.Rect(380.0, 98.0, 394.0, 112.0))
            s1.finish(fill=(0.15, 0.42, 0.85), color=(0.15, 0.42, 0.85))
            s1.draw_rect(pymupdf.Rect(380.0, 118.0, 394.0, 132.0))
            s1.finish(fill=(0.92, 0.50, 0.12), color=(0.92, 0.50, 0.12))
            # Grouped bars (East: 40 vs 70; West: 60 vs 90) -> 2.6 pt per unit
            g_bars = [
                (160.0, 350.0 - 40.0 * 2.6, 186.0, 350.0, (0.15, 0.42, 0.85)),
                (192.0, 350.0 - 70.0 * 2.6, 218.0, 350.0, (0.92, 0.50, 0.12)),
                (330.0, 350.0 - 60.0 * 2.6, 356.0, 350.0, (0.15, 0.42, 0.85)),
                (362.0, 350.0 - 90.0 * 2.6, 388.0, 350.0, (0.92, 0.50, 0.12)),
            ]
            for bx0, by0, bx1, by1, col in g_bars:
                s1.draw_rect(pymupdf.Rect(bx0, by0, bx1, by1))
                s1.finish(fill=col, color=col)
            s1.commit()
            p1.insert_text((400.0, 108.0), "2024", fontsize=9, color=(0.1, 0.1, 0.1))
            p1.insert_text((400.0, 128.0), "2025", fontsize=9, color=(0.1, 0.1, 0.1))

            # Page 2: Stacked Bar Chart
            p2 = doc.new_page(width=620, height=500)
            _draw_vector_axes(
                p2,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(350.0, "0"), (220.0, "50"), (90.0, "100")],
                x_ticks_or_cats=[(200.0, "Jan"), (360.0, "Feb")],
            )
            s2 = p2.new_shape()
            s2.draw_rect(pymupdf.Rect(380.0, 98.0, 394.0, 112.0))
            s2.finish(fill=(0.15, 0.42, 0.85), color=(0.15, 0.42, 0.85))
            s2.draw_rect(pymupdf.Rect(380.0, 118.0, 394.0, 132.0))
            s2.finish(fill=(0.15, 0.68, 0.38), color=(0.15, 0.68, 0.38))
            # Jan: Core=30 (272..350), Addon=25 (207..272)
            # Feb: Core=50 (220..350), Addon=35 (129..220)
            stk_bars = [
                (175.0, 272.0, 225.0, 350.0, (0.15, 0.42, 0.85)),
                (175.0, 207.0, 225.0, 272.0, (0.15, 0.68, 0.38)),
                (335.0, 220.0, 385.0, 350.0, (0.15, 0.42, 0.85)),
                (335.0, 129.0, 385.0, 220.0, (0.15, 0.68, 0.38)),
            ]
            for bx0, by0, bx1, by1, col in stk_bars:
                s2.draw_rect(pymupdf.Rect(bx0, by0, bx1, by1))
                s2.finish(fill=col, color=col)
            s2.commit()
            p2.insert_text((400.0, 108.0), "Core", fontsize=9, color=(0.1, 0.1, 0.1))
            p2.insert_text((400.0, 128.0), "Addon", fontsize=9, color=(0.1, 0.1, 0.1))

            pdf_bytes_bs = doc.tobytes()
        finally:
            doc.close()

        with pymupdf.open(stream=pdf_bytes_bs, filetype="pdf") as reloaded_bs:
            p1_r = reloaded_bs[0]
            p2_r = reloaded_bs[1]
            img1 = _render_pdf_page_pil(p1_r, dpi=150)
            img2 = _render_pdf_page_pil(p2_r, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg_grp = ext.extract_chart_region(
                    page_image=img1,
                    chart_box=[40.0, 60.0, 510.0, 390.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=620.0,
                    page_height=500.0,
                    pymupdf_page=p1_r,
                )
                reg_stk = ext.extract_chart_region(
                    page_image=img2,
                    chart_box=[40.0, 60.0, 510.0, 390.0],
                    bbox_format="display",
                    page_number=2,
                    page_width=620.0,
                    page_height=500.0,
                    pymupdf_page=p2_r,
                )
            finally:
                img1.close()
                img2.close()

        c_grp = reg_grp["metadata"]["chart"]
        assert c_grp["chart_type"] == ChartType.GROUPED_BAR.value
        assert len(c_grp["series"]) == 2
        grp_by_name = {s["name"]: {p["category"]: p["value"] for p in s["data_points"]} for s in c_grp["series"]}
        assert grp_by_name["2024"]["East"] == pytest.approx(40.0, abs=3.0)
        assert grp_by_name["2025"]["West"] == pytest.approx(90.0, abs=3.0)

        c_stk = reg_stk["metadata"]["chart"]
        assert c_stk["chart_type"] == ChartType.STACKED_BAR.value
        assert len(c_stk["series"]) == 2
        stk_by_name = {s["name"]: {p["category"]: p for p in s["data_points"]} for s in c_stk["series"]}
        assert stk_by_name["Core"]["Jan"]["value"] == pytest.approx(30.0, abs=3.0)
        assert stk_by_name["Addon"]["Jan"]["value"] == pytest.approx(25.0, abs=3.0)
        assert stk_by_name["Addon"]["Feb"]["value"] == pytest.approx(35.0, abs=3.0)
        assert stk_by_name["Addon"]["Feb"]["cumulative_value"] == pytest.approx(85.0, abs=4.0)

    def test_vector_and_raster_line_charts(self):
        # 1. Vector multi-series line chart crossing zero
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=620, height=460)
            px0, py0, px1, py1 = 110.0, 80.0, 490.0, 350.0
            # Y ticks [-20, 0, 20, 40] -> py1=350 (-20), py0=80 (+40) => 4.5 pt per unit
            _draw_vector_axes(
                page,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(350.0, "-20"), (260.0, "0"), (170.0, "20"), (80.0, "40")],
                x_ticks_or_cats=[(150.0, "Jan"), (260.0, "Feb"), (370.0, "Mar"), (460.0, "Apr")],
            )
            # Zero baseline
            z_sh = page.new_shape()
            z_sh.draw_line((px0, 260.0), (px1, 260.0))
            z_sh.finish(color=(0.75, 0.75, 0.75), width=0.8)
            z_sh.commit()

            # Blue series: [-10, 10, 25, 35] -> y = [305, 215, 147.5, 102.5]
            pts_blue = [(150.0, 305.0), (260.0, 215.0), (370.0, 147.5), (460.0, 102.5)]
            lsh = page.new_shape()
            for a, b in zip(pts_blue, pts_blue[1:]):
                lsh.draw_line(a, b)
            lsh.finish(color=(0.12, 0.42, 0.85), width=2.2)
            lsh.commit()

            img_vec = _render_pdf_page_pil(page, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg_vec = ext.extract_chart_region(
                    page_image=img_vec,
                    chart_box=[50.0, 55.0, 520.0, 390.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=620.0,
                    page_height=460.0,
                    pymupdf_page=page,
                )
            finally:
                img_vec.close()
        finally:
            doc.close()

        c_vec = reg_vec["metadata"]["chart"]
        assert c_vec["chart_type"] == ChartType.LINE.value
        assert c_vec["axes"]["y_primary"]["zero_coord"] is not None
        vals_v = [p["value"] for p in c_vec["series"][0]["data_points"]]
        assert min(vals_v) == pytest.approx(-10.0, abs=3.0)
        assert max(vals_v) == pytest.approx(35.0, abs=3.0)
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in c_vec["series"][0]["data_points"])

        # 2. Raster OpenCV + Tesseract line chart
        img_ras = Image.new("RGB", (660, 420), "white")
        try:
            draw = ImageDraw.Draw(img_ras)
            font = _load_font(16)
            rx0, ry0, rx1, ry1 = 120, 60, 590, 340
            draw.line((rx0, ry0, rx0, ry1), fill=(20, 20, 20), width=3)
            draw.line((rx0, ry1, rx1, ry1), fill=(20, 20, 20), width=3)
            for v in (0, 50, 100):
                ty = int(round(ry1 - (v / 100.0) * (ry1 - ry0)))
                draw.line((rx0 - 6, ty, rx0, ty), fill=(20, 20, 20), width=2)
                draw.text((rx0 - 45, ty - 10), str(v), font=font, fill=(15, 15, 15))
            x_pts = [("M1", 170, 25), ("M2", 310, 75), ("M3", 450, 50), ("M4", 550, 90)]
            poly = []
            for lbl, cx, v in x_pts:
                py_pt = int(round(ry1 - (v / 100.0) * (ry1 - ry0)))
                poly.append((cx, py_pt))
                draw.text((cx - 12, ry1 + 12), lbl, font=font, fill=(15, 15, 15))
            draw.line(poly, fill=(215, 45, 45), width=5)

            ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg_ras = ext.extract_chart_region(
                page_image=img_ras,
                chart_box=None,
                page_number=1,
                page_width=660.0,
                page_height=420.0,
            )
        finally:
            img_ras.close()

        c_ras = reg_ras["metadata"]["chart"]
        assert c_ras["chart_type"] == ChartType.LINE.value
        assert c_ras["source_mode"] == ChartSourceMode.RASTER.value
        pts_r = c_ras["series"][0]["data_points"]
        assert len(pts_r) >= 4
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in pts_r)

    def test_pie_chart_vector_and_raster_no_fabricated_absolute_values(self):
        # 1. Vector PDF pie sectors: 50% (180 deg, labeled "50%"), 30% (108 deg, category only), 20% (72 deg, category only)
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=550, height=420)
            cx, cy, rad = 250.0, 210.0, 100.0
            sh = page.new_shape()
            # Slice 1: 180 deg upper semicircle
            sh.draw_sector((cx, cy), (cx + rad, cy), 180.0, fullSector=True)
            sh.finish(fill=(0.15, 0.45, 0.85), color=(1, 1, 1), width=1.2)
            # Slice 2: 108 deg from (cx - rad, cy) CCW to (288 deg standard Cartesian = +cos, -sin in Y-down)
            sh.draw_sector((cx, cy), (cx - rad, cy), 108.0, fullSector=True)
            sh.finish(fill=(0.90, 0.48, 0.12), color=(1, 1, 1), width=1.2)
            p_start3 = (cx + rad * math.cos(math.radians(288.0)), cy - rad * math.sin(math.radians(288.0)))
            sh.draw_sector((cx, cy), p_start3, 72.0, fullSector=True)
            sh.finish(fill=(0.18, 0.68, 0.38), color=(1, 1, 1), width=1.2)
            sh.commit()
            # Labels inside / near sectors
            page.insert_text((cx - 22, cy - 46), "Cloud 50%", fontsize=9, color=(1, 1, 1))
            page.insert_text((cx - 52, cy + 52), "OnPrem", fontsize=9, color=(0.1, 0.1, 0.1))
            page.insert_text((cx + 32, cy + 32), "Edge", fontsize=9, color=(0.1, 0.1, 0.1))

            img_v = _render_pdf_page_pil(page, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg_v = ext.extract_chart_region(
                    page_image=img_v,
                    chart_box=[110.0, 80.0, 410.0, 340.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=550.0,
                    page_height=420.0,
                    pymupdf_page=page,
                )
            finally:
                img_v.close()
        finally:
            doc.close()

        c_v = reg_v["metadata"]["chart"]
        assert c_v["chart_type"] == ChartType.PIE.value
        pts = c_v["series"][0]["data_points"]
        assert len(pts) == 3
        shares = sorted([p["estimated_angle_share_pct"] for p in pts], reverse=True)
        assert shares[0] == pytest.approx(50.0, abs=3.0)
        assert shares[1] == pytest.approx(30.0, abs=3.0)
        assert shares[2] == pytest.approx(20.0, abs=3.0)
        exact_pts = [p for p in pts if p["precision"] == ValuePrecisionStatus.EXACT.value]
        est_pts = [p for p in pts if p["precision"] == ValuePrecisionStatus.ESTIMATED.value]
        assert len(exact_pts) == 1 and exact_pts[0]["value"] == pytest.approx(50.0, abs=0.5)
        assert len(est_pts) == 2

        # 2. Raster OpenCV Pie Chart with legend swatches & zero fabricated absolute quantities
        img_p = Image.new("RGB", (600, 400), "white")
        try:
            d = ImageDraw.Draw(img_p)
            f = _load_font(16)
            box = (80, 70, 340, 330)
            d.pieslice(box, start=0, end=180, fill=(35, 110, 215))
            d.pieslice(box, start=180, end=270, fill=(230, 120, 30))
            d.pieslice(box, start=270, end=360, fill=(45, 175, 95))
            # Legend
            d.rectangle((390, 120, 414, 144), fill=(35, 110, 215))
            d.text((425, 122), "Core", font=f, fill=(10, 10, 10))
            d.rectangle((390, 165, 414, 189), fill=(230, 120, 30))
            d.text((425, 167), "Services", font=f, fill=(10, 10, 10))
            d.rectangle((390, 210, 414, 234), fill=(45, 175, 95))
            d.text((425, 212), "Support", font=f, fill=(10, 10, 10))

            assert is_likely_chart_raster_opencv(img_p) is True
            ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg_r = ext.extract_chart_region(
                page_image=img_p,
                chart_box=None,
                page_number=1,
                page_width=600.0,
                page_height=400.0,
            )
        finally:
            img_p.close()

        c_r = reg_r["metadata"]["chart"]
        assert c_r["chart_type"] == ChartType.PIE.value
        pts_r = c_r["series"][0]["data_points"]
        assert len(pts_r) == 3
        shares_r = sorted([p["estimated_angle_share_pct"] for p in pts_r], reverse=True)
        assert shares_r[0] == pytest.approx(50.0, abs=6.0)
        assert shares_r[1] == pytest.approx(25.0, abs=6.0)
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in pts_r)
        assert all(p["unit"] == "%" for p in pts_r)

    def test_scatter_plot_vector_and_raster_xy_calibration(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=600, height=450)
            px0, py0, px1, py1 = 110.0, 80.0, 470.0, 350.0
            # X ticks: 10..40 (12 pt/unit), Y ticks: 200..500 (0.9 pt/unit)
            _draw_vector_axes(
                page,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(350.0, "200"), (260.0, "300"), (170.0, "400"), (80.0, "500")],
                x_ticks_or_cats=[(110.0, "10"), (230.0, "20"), (350.0, "30"), (470.0, "40")],
            )
            pts_spec = [(15.0, 250.0), (25.0, 350.0), (35.0, 450.0)]
            sh = page.new_shape()
            for xv, yv in pts_spec:
                cx = px0 + (xv - 10.0) * 12.0
                cy = py1 - (yv - 200.0) * 0.9
                sh.draw_circle((cx, cy), 4.5)
                sh.finish(fill=(0.15, 0.45, 0.85), color=(0.15, 0.45, 0.85))
            sh.commit()

            img = _render_pdf_page_pil(page, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg = ext.extract_chart_region(
                    page_image=img,
                    chart_box=[50.0, 50.0, 510.0, 390.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=600.0,
                    page_height=450.0,
                    pymupdf_page=page,
                )
            finally:
                img.close()
        finally:
            doc.close()

        chart = reg["metadata"]["chart"]
        assert chart["chart_type"] == ChartType.SCATTER.value
        pts = sorted(chart["series"][0]["data_points"], key=lambda p: p["x"] or 0.0)
        assert len(pts) == 3
        assert pts[0]["x"] == pytest.approx(15.0, abs=1.5)
        assert pts[0]["value"] == pytest.approx(250.0, abs=8.0)
        assert pts[2]["x"] == pytest.approx(35.0, abs=1.5)
        assert pts[2]["value"] == pytest.approx(450.0, abs=8.0)
        assert all(p["precision"] == ValuePrecisionStatus.ESTIMATED.value for p in pts)


class TestAxisGuardsDualAxesAndReviewStates:
    def test_negative_values_and_irregular_scale_vs_log10(self):
        # 1. Irregular unequal tick labels -> MUST reject rather than extrapolate!
        cal_bad = calibrate_numeric_axis(
            axis_name="y_primary",
            orientation="vertical",
            tick_candidates=[
                {"text": "0", "coord": 400.0},
                {"text": "10", "coord": 300.0},
                {"text": "50", "coord": 200.0},
                {"text": "500", "coord": 100.0},
            ],
        )
        assert cal_bad["is_valid"] is False
        assert cal_bad["scale_type"] == "irregular_non_uniform"
        assert cal_bad["reason"] == "non_uniform_or_nonlinear_intervals"

        # 2. Logarithmic base-10 scale [1, 10, 100, 1000] at equal intervals
        cal_log = calibrate_numeric_axis(
            axis_name="y_primary",
            orientation="vertical",
            tick_candidates=[
                {"text": "1", "coord": 400.0},
                {"text": "10", "coord": 300.0},
                {"text": "100", "coord": 200.0},
                {"text": "1000", "coord": 100.0},
            ],
        )
        assert cal_log["is_valid"] is True
        assert cal_log["scale_type"] == "logarithmic"

        # 3. Full extraction on irregular-axis PDF produces 'unavailable' values + review_required=True
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=550, height=420)
            px0, py0, px1, py1 = 100.0, 90.0, 420.0, 330.0
            _draw_vector_axes(
                page,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(330.0, "0"), (250.0, "10"), (170.0, "50"), (90.0, "500")],
                x_ticks_or_cats=[(180.0, "A"), (300.0, "B")],
            )
            sh = page.new_shape()
            sh.draw_rect(pymupdf.Rect(160.0, 210.0, 200.0, 330.0))
            sh.finish(fill=(0.2, 0.4, 0.8), color=(0.2, 0.4, 0.8))
            sh.draw_rect(pymupdf.Rect(280.0, 140.0, 320.0, 330.0))
            sh.finish(fill=(0.2, 0.4, 0.8), color=(0.2, 0.4, 0.8))
            sh.commit()

            img = _render_pdf_page_pil(page, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg = ext.extract_chart_region(
                    page_image=img,
                    chart_box=[40.0, 60.0, 450.0, 370.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=550.0,
                    page_height=420.0,
                    pymupdf_page=page,
                )
            finally:
                img.close()
        finally:
            doc.close()

        pts = reg["metadata"]["chart"]["series"][0]["data_points"]
        assert all(p["value"] is None and p["precision"] == ValuePrecisionStatus.UNAVAILABLE.value for p in pts)
        assert reg["metadata"]["review_required"] is True
        assert "y_axis_non_uniform_or_nonlinear_intervals" in reg["metadata"]["chart_validation"]["issue_codes"]

    def test_negative_bar_chart_crosses_zero_axis(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=550, height=420)
            px0, py0, px1, py1 = 100.0, 80.0, 440.0, 320.0
            # [-40, -20, 0, 20, 40] -> 3 pt per unit, zero line at y=200
            _draw_vector_axes(
                page,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(320.0, "-40"), (260.0, "-20"), (200.0, "0"), (140.0, "20"), (80.0, "40")],
                x_ticks_or_cats=[(190.0, "Gain"), (330.0, "Loss")],
            )
            sh = page.new_shape()
            sh.draw_line((px0, 200.0), (px1, 200.0))
            sh.finish(color=(0.5, 0.5, 0.5), width=1.0)
            sh = page.new_shape()
            # +30 bar (y=110..200) and -25 bar (y=200..275)
            sh.draw_rect(pymupdf.Rect(168.0, 110.0, 212.0, 200.0))
            sh.finish(fill=(0.15, 0.65, 0.35), color=(0.15, 0.65, 0.35))
            sh.draw_rect(pymupdf.Rect(308.0, 200.0, 352.0, 275.0))
            sh.finish(fill=(0.82, 0.22, 0.22), color=(0.82, 0.22, 0.22))
            sh.commit()

            img = _render_pdf_page_pil(page, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg = ext.extract_chart_region(
                    page_image=img,
                    chart_box=[40.0, 50.0, 470.0, 360.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=550.0,
                    page_height=420.0,
                    pymupdf_page=page,
                )
            finally:
                img.close()
        finally:
            doc.close()

        pts = {
            p["category"]: p["value"]
            for s in reg["metadata"]["chart"]["series"]
            for p in s["data_points"]
        }
        assert pts["Gain"] == pytest.approx(30.0, abs=3.0)
        assert pts["Loss"] == pytest.approx(-25.0, abs=3.0)

    def test_dual_axis_disambiguated_vs_ambiguous_refusal(self):
        # Case A: Dual Y1 ($M) & Y2 (%) disambiguated via series unit/title & legend
        doc = pymupdf.open()
        try:
            p_ok = doc.new_page(width=620, height=450)
            px0, py0, px1, py1 = 100.0, 80.0, 450.0, 340.0
            _draw_vector_axes(
                p_ok,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(340.0, "0"), (210.0, "50"), (80.0, "100")],
                y2_ticks=[(340.0, "0%"), (210.0, "25%"), (80.0, "50%")],
                x_ticks_or_cats=[(190.0, "Q1"), (340.0, "Q2")],
                y_title="Revenue ($M)",
                y2_title="Margin (%)",
            )
            sh = p_ok.new_shape()
            sh.draw_rect(pymupdf.Rect(140.0, 92.0, 154.0, 106.0))
            sh.finish(fill=(0.15, 0.42, 0.85), color=(0.15, 0.42, 0.85))
            sh.draw_rect(pymupdf.Rect(270.0, 92.0, 284.0, 106.0))
            sh.finish(fill=(0.82, 0.18, 0.18), color=(0.82, 0.18, 0.18))
            # Q1: Rev=60 (y=184), Margin=20% (y=236); Q2: Rev=80 (y=132), Margin=40% (y=132)
            for bx0, by0, bx1, by1, col in [
                (165.0, 184.0, 190.0, 340.0, (0.15, 0.42, 0.85)),
                (195.0, 236.0, 220.0, 340.0, (0.82, 0.18, 0.18)),
                (315.0, 132.0, 340.0, 340.0, (0.15, 0.42, 0.85)),
                (345.0, 132.0, 370.0, 340.0, (0.82, 0.18, 0.18)),
            ]:
                sh.draw_rect(pymupdf.Rect(bx0, by0, bx1, by1))
                sh.finish(fill=col, color=col)
            sh.commit()
            p_ok.insert_text((160.0, 102.0), "Sales ($M)", fontsize=9, color=(0.1, 0.1, 0.1))
            p_ok.insert_text((290.0, 102.0), "Margin (%)", fontsize=9, color=(0.1, 0.1, 0.1))

            # Case B: Ambiguous dual-axis (generic Y1 & Y2 with conflicting scales and NO unit/color hint)
            p_amb = doc.new_page(width=620, height=450)
            _draw_vector_axes(
                p_amb,
                px0=px0,
                py0=py0,
                px1=px1,
                py1=py1,
                y_ticks=[(340.0, "0"), (210.0, "50"), (80.0, "100")],
                y2_ticks=[(340.0, "0"), (210.0, "200"), (80.0, "400")],
                x_ticks_or_cats=[(220.0, "2024"), (340.0, "2025")],
            )
            sh2 = p_amb.new_shape()
            sh2.draw_rect(pymupdf.Rect(195.0, 180.0, 245.0, 340.0))
            sh2.finish(fill=(0.15, 0.55, 0.55), color=(0.15, 0.55, 0.55))
            sh2.draw_rect(pymupdf.Rect(315.0, 130.0, 365.0, 340.0))
            sh2.finish(fill=(0.15, 0.55, 0.55), color=(0.15, 0.55, 0.55))
            sh2.commit()

            pdf_bytes_dual = doc.tobytes()
        finally:
            doc.close()

        with pymupdf.open(stream=pdf_bytes_dual, filetype="pdf") as reloaded_dual:
            p_ok_r = reloaded_dual[0]
            p_amb_r = reloaded_dual[1]
            img_ok = _render_pdf_page_pil(p_ok_r, dpi=150)
            img_amb = _render_pdf_page_pil(p_amb_r, dpi=150)
            try:
                ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
                reg_ok = ext.extract_chart_region(
                    page_image=img_ok,
                    chart_box=[20.0, 50.0, 550.0, 390.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=620.0,
                    page_height=450.0,
                    pymupdf_page=p_ok_r,
                )
                reg_amb = ext.extract_chart_region(
                    page_image=img_amb,
                    chart_box=[50.0, 50.0, 520.0, 390.0],
                    bbox_format="display",
                    page_number=2,
                    page_width=620.0,
                    page_height=450.0,
                    pymupdf_page=p_amb_r,
                )
            finally:
                img_ok.close()
                img_amb.close()

        c_ok = reg_ok["metadata"]["chart"]
        assert c_ok["axes"]["y_secondary"]["present"] is True
        assert c_ok["axes"]["y_secondary"]["is_valid"] is True
        by_axis = {s["axis"]: {p["category"]: p for p in s["data_points"]} for s in c_ok["series"]}
        assert by_axis["y1"]["Q1"]["value"] == pytest.approx(60.0, abs=3.0)
        assert by_axis["y2"]["Q1"]["value"] == pytest.approx(20.0, abs=2.0)
        assert "%" in by_axis["y2"]["Q1"]["unit"]

        # Ambiguous dual axis MUST refuse to guess and mark review_required
        c_amb = reg_amb["metadata"]["chart"]
        assert reg_amb["metadata"]["review_required"] is True
        assert "ambiguous_dual_axis_binding" in reg_amb["metadata"]["chart_validation"]["issue_codes"]
        for s in c_amb["series"]:
            for dp in s["data_points"]:
                assert dp["value"] is None
                assert dp["precision"] == ValuePrecisionStatus.UNAVAILABLE.value

    def test_missing_labels_low_res_unknown_bengali_and_ocr_unavailable(self):
        ext = PyMuPDFOpenCVChartExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))

        # 1. Low resolution crop -> crop reference preserved + review_required=True
        tiny = Image.new("RGB", (90, 60), "white")
        try:
            ImageDraw.Draw(tiny).rectangle((10, 10, 80, 50), outline=(0, 0, 0), width=1)
            reg_low = ext.extract_chart_region(
                page_image=tiny,
                chart_box=None,
                page_number=1,
                page_width=90.0,
                page_height=60.0,
                source_asset_name="scan:tiny_chart.png",
            )
        finally:
            tiny.close()

        assert reg_low["metadata"]["review_required"] is True
        assert "low_resolution_chart" in reg_low["metadata"]["chart_validation"]["issue_codes"]
        assert reg_low["metadata"]["chart_crop_reference"]["byte_size"] > 0
        assert "crop_image_base64" in reg_low["metadata"]["chart_crop_reference"]
        assert reg_low["metadata"]["source_coordinates"]["pixel_rect_xyxy"] == [0.0, 0.0, 90.0, 60.0]

        # 2. Unknown / ambiguous graphic -> unknown chart type + zero fabricated points + review_required=True
        ambig = Image.new("RGB", (360, 260), "white")
        try:
            d = ImageDraw.Draw(ambig)
            d.text((70, 110), "Unstructured diagram", fill=(30, 30, 30))
            reg_unk = ext.extract_chart_region(
                page_image=ambig,
                chart_box=None,
                page_number=1,
                page_width=360.0,
                page_height=260.0,
            )
        finally:
            ambig.close()

        assert reg_unk["metadata"]["chart"]["chart_type"] == ChartType.UNKNOWN.value
        assert reg_unk["metadata"]["chart"]["series"] == []
        assert reg_unk["metadata"]["review_required"] is True
        assert "crop_image_base64" in reg_unk["metadata"]["chart_crop_reference"]

        # 3. Missing category labels on PDF bar chart -> review_required=True + bars not discarded
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=500, height=400)
            _draw_vector_axes(
                page,
                px0=100.0,
                py0=80.0,
                px1=420.0,
                py1=300.0,
                y_ticks=[(300.0, "0"), (190.0, "50"), (80.0, "100")],
                x_ticks_or_cats=[],
            )
            sh = page.new_shape()
            sh.draw_rect(pymupdf.Rect(160.0, 190.0, 210.0, 300.0))
            sh.finish(fill=(0.2, 0.45, 0.85), color=(0.2, 0.45, 0.85))
            sh.commit()
            img_nl = _render_pdf_page_pil(page, dpi=150)
            try:
                reg_nl = ext.extract_chart_region(
                    page_image=img_nl,
                    chart_box=[40.0, 50.0, 450.0, 340.0],
                    bbox_format="display",
                    page_number=1,
                    page_width=500.0,
                    page_height=400.0,
                    pymupdf_page=page,
                )
            finally:
                img_nl.close()
        finally:
            doc.close()

        assert reg_nl["metadata"]["review_required"] is True
        assert "missing_category_or_slice_labels" in reg_nl["metadata"]["chart_validation"]["issue_codes"]
        assert reg_nl["metadata"]["chart"]["series"][0]["data_points"][0]["value"] == pytest.approx(50.0, abs=3.0)

        # 4. Bengali + English chart labels via TesseractOCRProvider config + Bangla digits + OCR metadata preservation
        bn_img = Image.new("RGB", (540, 380), "white")
        try:
            bd = ImageDraw.Draw(bn_img)
            # Plot axes [80, 50] -> [480, 300] and two blue bars (height 100px out of 250px -> value ~ 12 when ticks are 0, 10, 20, 30)
            bd.line((90, 50, 90, 300), fill=(0, 0, 0), width=3)
            bd.line((90, 300, 480, 300), fill=(0, 0, 0), width=3)
            bd.rectangle((180, 200, 240, 298), fill=(35, 110, 215))
            bd.rectangle((320, 133, 380, 298), fill=(35, 110, 215))
            mock_bn = _StaticOrTagMockOCR(
                available=True,
                lang="ben+eng",
                confidence=0.84,
                status="success",
                warnings=["Minor skewer deskew applied"],
                tokens=[
                    {"text": "০", "bbox": (45, 292, 24, 16)},
                    {"text": "১০", "bbox": (45, 210, 24, 16)},
                    {"text": "২০", "bbox": (45, 127, 24, 16)},
                    {"text": "৩০", "bbox": (45, 44, 24, 16)},
                    {"text": "ঢাকা", "bbox": (185, 315, 48, 20)},
                    {"text": "Revenue", "bbox": (320, 315, 70, 20)},
                ],
            )
            ext_bn = PyMuPDFOpenCVChartExtractor(ocr_provider=mock_bn, repair_bengali=True)
            reg_bn = ext_bn.extract_chart_region(
                page_image=bn_img,
                chart_box=None,
                page_number=1,
                page_width=540.0,
                page_height=380.0,
            )
        finally:
            bn_img.close()

        bn_meta = reg_bn["metadata"]
        assert bn_meta["ocr_metadata"]["language"] == "ben+eng"
        assert bn_meta["ocr_metadata"]["engine"] == "tesseract"
        assert bn_meta["ocr_metadata"]["engine_version"] == "5.5.0-mock"
        assert "Minor skewer deskew applied" in bn_meta["ocr_metadata"]["warnings"]
        assert bn_meta["chart"]["chart_type"] == ChartType.VERTICAL_BAR.value
        assert bn_meta["chart"]["axes"]["y_primary"]["is_valid"] is True

        # 5. OCR unavailable on raster chart -> graceful fallback & review_required=True
        ext_off = PyMuPDFOpenCVChartExtractor(ocr_provider=_StaticOrTagMockOCR(available=False, lang="ben+eng"))
        ras = Image.new("RGB", (400, 300), "white")
        try:
            rd = ImageDraw.Draw(ras)
            rd.line((80, 40, 80, 240), fill=(0, 0, 0), width=3)
            rd.line((80, 240, 360, 240), fill=(0, 0, 0), width=3)
            rd.rectangle((140, 110, 200, 238), fill=(40, 100, 200))
            reg_off = ext_off.extract_chart_region(page_image=ras, chart_box=None, page_number=1, page_width=400.0, page_height=300.0)
        finally:
            ras.close()

        assert reg_off["metadata"]["review_required"] is True
        assert "ocr_unavailable" in reg_off["metadata"]["chart_validation"]["issue_codes"]
        assert reg_off["metadata"]["chart_crop_reference"]["crop_ref"].startswith("lore://charts/crops/")
        assert "crop_image_base64" in reg_off["metadata"]["chart_crop_reference"]


class TestEndToEndPDFAndLayoutIntegration:
    def test_mixed_and_scanned_pdf_and_rotated_page_without_duplication(self):
        doc = pymupdf.open()
        try:
            # Page 1: Searchable/Mixed PDF with native heading + vector bar chart
            p1 = doc.new_page(width=612, height=792)
            p1.insert_text((72, 60), "Executive Summary: 2025 Performance", fontsize=12)
            _draw_vector_axes(
                p1,
                px0=120.0,
                py0=160.0,
                px1=460.0,
                py1=360.0,
                y_ticks=[(360.0, "0"), (260.0, "50"), (160.0, "100")],
                x_ticks_or_cats=[(200.0, "North"), (350.0, "South")],
            )
            sh1 = p1.new_shape()
            sh1.draw_rect(pymupdf.Rect(180.0, 210.0, 220.0, 360.0))  # 75
            sh1.finish(fill=(0.15, 0.45, 0.85), color=(0.15, 0.45, 0.85))
            sh1.draw_rect(pymupdf.Rect(330.0, 310.0, 370.0, 360.0))  # 25
            sh1.finish(fill=(0.15, 0.45, 0.85), color=(0.15, 0.45, 0.85))
            sh1.commit()

            # Page 2: Scanned PDF page containing embedded raster chart image (zero native text)
            p2 = doc.new_page(width=600, height=450)
            sc_img = Image.new("RGB", (600, 420), "white")
            try:
                sd = ImageDraw.Draw(sc_img)
                f = _load_font(16)
                sd.line((110, 60, 110, 320), fill=(10, 10, 10), width=3)
                sd.line((110, 320, 520, 320), fill=(10, 10, 10), width=3)
                for tv in (0, 50, 100):
                    ty = int(round(320 - (tv / 100.0) * 260))
                    sd.line((103, ty, 110, ty), fill=(10, 10, 10), width=2)
                    sd.text((62, ty - 10), str(tv), font=f, fill=(10, 10, 10))
                sd.rectangle((200, 190, 260, 318), fill=(40, 110, 210))
                sd.text((210, 330), "A1", font=f, fill=(10, 10, 10))
                sd.rectangle((360, 125, 420, 318), fill=(40, 110, 210))
                sd.text((370, 330), "B2", font=f, fill=(10, 10, 10))
                buf_img = io.BytesIO()
                sc_img.save(buf_img, format="PNG")
                p2.insert_image(pymupdf.Rect(30, 20, 570, 410), stream=buf_img.getvalue())
            finally:
                sc_img.close()

            # Page 3: Rotated 90-degree PDF page with vector chart
            p3 = doc.new_page(width=792, height=612)
            _draw_vector_axes(
                p3,
                px0=120.0,
                py0=140.0,
                px1=420.0,
                py1=340.0,
                y_ticks=[(340.0, "0"), (240.0, "50"), (140.0, "100")],
                x_ticks_or_cats=[(210.0, "P1"), (330.0, "P2")],
            )
            sh3 = p3.new_shape()
            sh3.draw_rect(pymupdf.Rect(190.0, 240.0, 230.0, 340.0))
            sh3.finish(fill=(0.15, 0.45, 0.85), color=(0.15, 0.45, 0.85))
            sh3.draw_rect(pymupdf.Rect(310.0, 180.0, 350.0, 340.0))
            sh3.finish(fill=(0.15, 0.45, 0.85), color=(0.15, 0.45, 0.85))
            sh3.commit()
            p3.set_rotation(90)

            pdf_bytes = doc.tobytes()
        finally:
            doc.close()

        ext = VisualDocumentExtractor.with_chart_extractor(
            ocr_provider=TesseractOCRProvider(lang="eng"),
            use_pymupdf=True,
        )
        pages = ext.extract_document(pdf_bytes, doc_type="pdf", filename="multi_charts.pdf")
        assert len(pages) == 3

        for p in pages:
            VisualPipelineIntegrationAdapter.validate_page_payload(p, strict=True)

        # Page 1: native heading kept, single non-duplicated chart region
        assert "Executive Summary" in pages[0]["text"]
        p1_charts = [r for r in pages[0]["visual_regions"] if r["region_type"] == VisualRegionType.CHART.value]
        assert len(p1_charts) == 1
        assert p1_charts[0]["metadata"]["chart"]["chart_type"] == ChartType.VERTICAL_BAR.value

        # Page 2: scanned page -> OpenCV + Tesseract chart extracted
        assert pages[1]["page_classification"] == "scanned"
        p2_charts = [r for r in pages[1]["visual_regions"] if r["region_type"] == VisualRegionType.CHART.value]
        assert len(p2_charts) == 1
        assert p2_charts[0]["metadata"]["chart"]["chart_type"] == ChartType.VERTICAL_BAR.value
        assert p2_charts[0]["metadata"]["ocr_metadata"]["ocr_triggered"] is True

        # Page 3: rotated 90 deg -> coordinates remain valid inside [0..1000]
        assert pages[2]["rotation"] == 90
        p3_charts = [r for r in pages[2]["visual_regions"] if r["region_type"] == VisualRegionType.CHART.value]
        assert len(p3_charts) == 1
        assert p3_charts[0]["metadata"]["source_coordinates"]["source_rotation"] == 90

    @pytest.mark.django_db
    def test_pp_doclayout_s_routing_and_strict_settlement_kb_isolation(self):
        from apps.knowledge.models import DocumentChunk, KnowledgeItem
        from apps.sources.models import DocumentPage, SourceDocument

        assert SourceDocument.objects.count() == 0
        assert DocumentPage.objects.count() == 0
        assert DocumentChunk.objects.count() == 0
        assert KnowledgeItem.objects.count() == 0

        WorkerLayoutModelCache.clear()

        # Render standalone ambiguous chart image so PP-DocLayout-S routes chart -> chart extractor
        # while chart_title supplies adjacent layout title, and uncalibrated axes force review_required=True.
        img = Image.new("RGB", (600, 420), "white")
        try:
            d = ImageDraw.Draw(img)
            f = _load_font(18)
            d.text((160, 20), "Q3 Capacity Utilization", font=f, fill=(10, 10, 10))
            d.line((100, 80, 100, 340), fill=(10, 10, 10), width=3)
            d.line((100, 340, 520, 340), fill=(10, 10, 10), width=3)
            d.rectangle((180, 180, 240, 338), fill=(40, 110, 210))
            d.rectangle((320, 130, 380, 338), fill=(40, 110, 210))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        finally:
            img.close()

        ext = VisualDocumentExtractor.with_pp_doclayout_s_and_slanet_plus(
            ocr_provider=TesseractOCRProvider(lang="eng"),
            enable_charts=True,
            use_pymupdf=False,
        )
        ext.visual_provider._model_loader = lambda _cfg: _SpyLayoutModel([
            {"cls_id": 2, "label": "chart_title", "score": 0.94, "coordinate": [150.0, 15.0, 420.0, 50.0]},
            {"cls_id": 10, "label": "chart", "score": 0.96, "coordinate": [75.0, 65.0, 540.0, 370.0]},
        ])

        pages = ext.extract_document(img_bytes, doc_type="image", filename="chart_layout.png")
        assert len(pages) == 1
        page = pages[0]
        VisualPipelineIntegrationAdapter.validate_page_payload(page, strict=True)

        charts_found = [r for r in page["visual_regions"] if r["region_type"] == VisualRegionType.CHART.value]
        assert len(charts_found) == 1
        cm = charts_found[0]["metadata"]
        assert "Q3 Capacity Utilization" in (cm["chart"]["title"] or "")
        # Because Y ticks were intentionally omitted on the chart image, review_required propagates to page!
        assert cm["review_required"] is True
        assert page["needs_review"] is True
        assert page.get("review_required") is True

        # Strict isolation guarantee: zero writes to Settlement or Knowledge Store DB tables
        assert SourceDocument.objects.count() == 0
        assert DocumentPage.objects.count() == 0
        assert DocumentChunk.objects.count() == 0
        assert KnowledgeItem.objects.count() == 0

