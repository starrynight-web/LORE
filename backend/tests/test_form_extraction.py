"""
Verification suite for LORE's deterministic form extraction (TesseractOCRProvider +
OpenCV + PyMuPDF + deterministic spatial key-value mapping).

Covers:
1. Printed forms, invoices, expense claims, and application forms (vector PDF + raster PNG).
2. Date, numeric, currency, percentage, ID, and free-text field parsing without false coercion.
3. Checkboxes (`checked`, `unchecked`, `unknown`) and circular radio buttons (single + ambiguous multi-select).
4. Incomplete forms & blank field preservation (boxes, underlines, colon labels, signatures) with zero fabrication.
5. Multi-column layout separation without cross-column value stealing.
6. Ambiguous field mappings, low-quality scans, low resolution, handwritten/low-confidence ink, and Bengali repair.
7. Signature regions (`signer_identified=False`) & approval fields (`approval_inferred=False`, `is_authoritative_decision=False`).
8. End-to-end integration with PyMuPDFVisualPDFAdapter, VisualDocumentExtractor, PPDocLayoutSProvider,
   plus strict Settlement / Governance / Knowledge Store isolation.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from apps.ingestion.pipeline.contracts import (
    VisualExtractionKind,
    VisualPipelineIntegrationAdapter,
    VisualRegionType,
)
from apps.ingestion.pipeline.forms import (
    CheckboxState,
    FormDocumentSubtype,
    FormExtractorConfig,
    FormFieldDataType,
    FormFieldStatus,
    FormKVExtractor,
    detect_form_candidates_in_pdf_page,
    detect_form_regions_opencv,
    is_approval_related_label,
    is_likely_form_raster_opencv,
    is_signature_label,
    parse_form_field_value,
)
from apps.ingestion.pipeline.layout import PPDocLayoutSProvider, WorkerLayoutModelCache
from apps.ingestion.pipeline.ocr import BaseOCRProvider, TesseractOCRProvider
from apps.ingestion.pipeline.visual import VisualDocumentExtractor


def _load_font(size: int = 18) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
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


class _FakeOCRProvider(BaseOCRProvider):
    """Controlled OCR provider for deterministic Bengali, low-confidence, and unavailable tests."""

    engine_name = "tesseract"
    engine_version = "5.3.0-mock"

    def __init__(
        self,
        *,
        available: bool = True,
        text: str = "",
        confidence: float = 0.85,
        boxes: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[str]] = None,
        language: str = "ben+eng",
        is_repaired: bool = False,
    ):
        self._available = available
        self._text = text
        self._confidence = confidence
        self._boxes = list(boxes or [])
        self._warnings = list(warnings or [])
        self._language = language
        self._is_repaired = is_repaired
        self.calls: int = 0

    def is_available(self) -> bool:
        return self._available

    def get_version(self) -> str:
        return self.engine_version

    def extract_image(self, image: Image.Image, **kwargs) -> Dict[str, Any]:
        self.calls += 1
        if not self._available:
            return {
                "text": "",
                "confidence": 0.0,
                "engine": self.engine_name,
                "engine_version": self.engine_version,
                "language": self._language,
                "bounding_boxes": [],
                "warnings": ["Tesseract binary unavailable"],
                "is_repaired": False,
                "needs_review": True,
                "status": "provider_unavailable",
            }
        # Targeted sub-crop OCR calls (small strips/boxes) return unreadable/empty text in this mock
        if image.width < 420 or image.height < 120:
            return {
                "text": "",
                "confidence": 0.0,
                "engine": self.engine_name,
                "engine_version": self.engine_version,
                "language": self._language,
                "bounding_boxes": [],
                "warnings": [],
                "is_repaired": False,
                "needs_review": True,
                "status": "empty_scan",
            }
        return {
            "text": self._text,
            "confidence": self._confidence,
            "engine": self.engine_name,
            "engine_version": self.engine_version,
            "language": self._language,
            "bounding_boxes": [dict(b) for b in self._boxes],
            "warnings": list(self._warnings),
            "is_repaired": self._is_repaired,
            "needs_review": self._confidence < 0.65,
            "status": "success",
        }


class _SpyLayoutModel:
    """Minimal PaddleOCR LayoutDetection duck-type returning pre-supplied region dicts."""

    def __init__(self, boxes: List[Dict[str, Any]]):
        self._boxes = boxes

    def predict(self, _img_arr, batch_size: int = 1):
        return [{"boxes": list(self._boxes)}]


def _draw_checkbox(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int = 24,
    mode: str = "unchecked",
) -> None:
    d.rectangle((x, y, x + size, y + size), outline=(15, 15, 15), width=2)
    if mode == "checked":
        d.line((x + 4, y + 4, x + size - 4, y + size - 4), fill=(10, 10, 10), width=3)
        d.line((x + size - 4, y + 4, x + 4, y + size - 4), fill=(10, 10, 10), width=3)
    elif mode == "checkmark":
        d.line((x + 4, y + size // 2 + 2, x + size // 2 - 1, y + size - 5), fill=(10, 10, 10), width=3)
        d.line((x + size // 2 - 1, y + size - 5, x + size - 4, y + 5), fill=(10, 10, 10), width=3)
    elif mode == "unknown":
        # Ambiguous light smudge inside center that does not span cleanly like a full X/check
        d.rectangle((x + 8, y + 8, x + size - 8, y + size - 8), fill=(175, 175, 175))


def _draw_radio(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int = 24,
    selected: bool = False,
) -> None:
    d.ellipse((x, y, x + size, y + size), outline=(15, 15, 15), width=2)
    if selected:
        pad = max(5, size // 4)
        d.ellipse((x + pad, y + pad, x + size - pad, y + size - pad), fill=(10, 10, 10))


def _find_field(fields: List[Dict[str, Any]], label_substr: str) -> Dict[str, Any]:
    low = label_substr.lower()
    for f in fields:
        if low in str(f.get("label") or "").lower():
            return f
    raise AssertionError(f"Expected field containing '{label_substr}', got {[f.get('label') for f in fields]}")


# ==============================================================================
# 1. UNIT TESTS: DATA TYPE PARSING & GOVERNANCE HELPERS
# ==============================================================================
class TestFormPrimitivesAndParsing:
    def test_parse_form_field_values_without_id_coercion(self):
        d = parse_form_field_value("2026-10-15")
        assert d["field_type"] == FormFieldDataType.DATE.value
        assert d["raw_value"] == "2026-10-15"
        assert d["numeric_value"] is None

        c = parse_form_field_value("$1,250.50")
        assert c["field_type"] == FormFieldDataType.CURRENCY.value
        assert c["numeric_value"] == pytest.approx(1250.50)
        assert c["currency"] == "$"

        pct = parse_form_field_value("15.5%")
        assert pct["field_type"] == FormFieldDataType.PERCENTAGE.value
        assert pct["numeric_value"] == pytest.approx(15.5)
        assert pct["unit"] == "%"

        # IDs / invoice numbers / postal hyphenated strings remain TEXT (not numeric/date)
        inv = parse_form_field_value("INV-2026-0412")
        assert inv["field_type"] == FormFieldDataType.TEXT.value
        assert inv["numeric_value"] is None

        zip_like = parse_form_field_value("12345-6789")
        assert zip_like["field_type"] == FormFieldDataType.TEXT.value

    def test_governance_label_helpers(self):
        assert is_approval_related_label("Approved By") is True
        assert is_approval_related_label("Manager Approval") is True
        assert is_approval_related_label("Authorized Status") is True
        assert is_approval_related_label("Invoice Number") is False

        assert is_signature_label("Applicant Signature") is True
        assert is_signature_label("Signed By") is True
        assert is_signature_label("Billing Address") is False


# ==============================================================================
# 2. COMPLETED INVOICE & EXPENSE CLAIM (PDF VECTOR + RASTER OCR)
# ==============================================================================
class TestCompletedInvoicesAndExpenseClaims:
    def test_completed_vector_pdf_invoice_preserves_native_values_and_provenance(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=612, height=792)
            page.insert_text((50, 52), "TAX INVOICE", fontsize=18)
            page.insert_text((50, 95), "Invoice No: INV-2026-0412", fontsize=12)
            page.insert_text((50, 125), "Invoice Date: 2026-10-15", fontsize=12)
            page.insert_text((50, 155), "Customer: Northstar Logistics", fontsize=12)
            page.insert_text((50, 185), "Tax Rate: 15%", fontsize=12)
            page.insert_text((50, 215), "Total Amount: $1,250.50", fontsize=12)
            pdf_bytes = doc.tobytes()
        finally:
            doc.close()

        ext = VisualDocumentExtractor.with_form_extractor(
            ocr_provider=TesseractOCRProvider(lang="eng"),
            use_pymupdf=True,
        )
        pages = ext.extract_document(pdf_bytes, doc_type="pdf", filename="completed_invoice.pdf")
        assert len(pages) == 1
        p = pages[0]
        VisualPipelineIntegrationAdapter.validate_page_payload(p, strict=True)

        form_regs = [r for r in p["visual_regions"] if r["region_type"] == VisualRegionType.FORM_KV.value]
        assert len(form_regs) == 1
        reg = form_regs[0]
        meta = reg["metadata"]
        form = meta["form"]

        assert form["form_subtype"] == FormDocumentSubtype.INVOICE.value
        assert form["source_mode"] == "native_pdf"
        assert form["is_complete"] is True
        assert meta["form_crop_reference"]["crop_ref"].startswith("lore://forms/crops/")
        assert "-crop-" in meta["form_crop_reference"]["crop_id"]
        assert meta["source_coordinates"]["page_number"] == 1

        fields = form["fields"]
        f_inv = _find_field(fields, "Invoice No")
        assert f_inv["raw_value"] == "INV-2026-0412"
        assert f_inv["status"] == FormFieldStatus.POPULATED.value

        f_date = _find_field(fields, "Invoice Date")
        assert f_date["field_type"] == FormFieldDataType.DATE.value
        assert f_date["raw_value"] == "2026-10-15"

        f_tax = _find_field(fields, "Tax Rate")
        assert f_tax["field_type"] == FormFieldDataType.PERCENTAGE.value
        assert f_tax["numeric_value"] == pytest.approx(15.0)
        assert f_tax["unit"] == "%"

        f_tot = _find_field(fields, "Total Amount")
        assert f_tot["field_type"] == FormFieldDataType.CURRENCY.value
        assert f_tot["numeric_value"] == pytest.approx(1250.50)
        assert f_tot["currency"] == "$"

    def test_completed_raster_expense_claim_real_opencv_and_tesseract(self):
        img = Image.new("RGB", (820, 520), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(22)
            f_body = _load_font(18)
            d.rectangle((25, 20, 795, 495), outline=(30, 30, 30), width=2)
            d.text((45, 36), "EMPLOYEE EXPENSE CLAIM", font=f_title, fill=(10, 10, 10))
            d.text((45, 95), "Claimant: Sara Khan", font=f_body, fill=(10, 10, 10))
            d.text((45, 140), "Claim Date: 2026-11-02", font=f_body, fill=(10, 10, 10))
            d.text((45, 185), "Reimbursement Total: $420.00", font=f_body, fill=(10, 10, 10))
            d.text((45, 235), "Receipts Attached:", font=f_body, fill=(10, 10, 10))
            _draw_checkbox(d, 250, 234, size=24, mode="checkmark")
            d.text((285, 235), "Yes", font=f_body, fill=(10, 10, 10))
            _draw_checkbox(d, 355, 234, size=24, mode="unchecked")
            d.text((390, 235), "No", font=f_body, fill=(10, 10, 10))

            assert is_likely_form_raster_opencv(img) is True
            ext = FormKVExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = ext.extract_form_region(
                page_image=img,
                form_box=None,
                page_number=1,
                page_width=820.0,
                page_height=520.0,
            )
        finally:
            img.close()

        form = reg["metadata"]["form"]
        assert form["form_subtype"] == FormDocumentSubtype.EXPENSE_CLAIM.value
        assert reg["metadata"]["ocr_metadata"]["ocr_triggered"] is True
        assert reg["metadata"]["ocr_metadata"]["engine"] == "tesseract"

        f_claimant = _find_field(form["fields"], "Claimant")
        assert "Sara" in f_claimant["raw_value"]
        f_amt = _find_field(form["fields"], "Reimbursement Total")
        assert f_amt["field_type"] == FormFieldDataType.CURRENCY.value
        assert f_amt["numeric_value"] == pytest.approx(420.0)

        cbs = form["checkboxes"]
        assert len(cbs) >= 2
        checked_cbs = [c for c in cbs if c["state"] == CheckboxState.CHECKED.value]
        unchecked_cbs = [c for c in cbs if c["state"] == CheckboxState.UNCHECKED.value]
        assert len(checked_cbs) >= 1
        assert len(unchecked_cbs) >= 1


# ==============================================================================
# 3. CHECKBOXES & RADIO BUTTONS (CHECKED / UNCHECKED / UNKNOWN / AMBIGUOUS)
# ==============================================================================
class TestCheckboxesAndRadioSelections:
    def test_checkbox_states_and_radio_buttons_with_ambiguity_detection(self):
        img = Image.new("RGB", (860, 560), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_body = _load_font(18)
            d.text((40, 30), "ACCOUNT APPLICATION FORM", font=f_title, fill=(10, 10, 10))
            d.text((40, 75), "Applicant Name: David Lin", font=f_body, fill=(10, 10, 10))

            # Checkboxes: Checked (X), Unchecked (empty), Unknown (partial center smudge)
            _draw_checkbox(d, 48, 130, size=26, mode="checked")
            d.text((88, 132), "Accept Terms", font=f_body, fill=(10, 10, 10))

            _draw_checkbox(d, 48, 178, size=26, mode="unchecked")
            d.text((88, 180), "Opt In Newsletter", font=f_body, fill=(10, 10, 10))

            _draw_checkbox(d, 48, 226, size=26, mode="unknown")
            d.text((88, 228), "Rush Processing", font=f_body, fill=(10, 10, 10))

            # Clean single-select Radio Group 1
            d.text((45, 290), "Delivery Option:", font=f_body, fill=(10, 10, 10))
            _draw_radio(d, 50, 330, size=24, selected=True)
            d.text((86, 332), "Courier", font=f_body, fill=(10, 10, 10))
            _draw_radio(d, 220, 330, size=24, selected=False)
            d.text((256, 332), "Pickup", font=f_body, fill=(10, 10, 10))

            # Ambiguous multi-selected Radio Group 2 (both dots selected!)
            d.text((45, 395), "Account Tier:", font=f_body, fill=(10, 10, 10))
            _draw_radio(d, 50, 435, size=24, selected=True)
            d.text((86, 437), "Standard", font=f_body, fill=(10, 10, 10))
            _draw_radio(d, 220, 435, size=24, selected=True)
            d.text((256, 437), "Priority", font=f_body, fill=(10, 10, 10))

            ext = FormKVExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = ext.extract_form_region(
                page_image=img,
                form_box=None,
                page_number=1,
                page_width=860.0,
                page_height=560.0,
            )
        finally:
            img.close()

        form = reg["metadata"]["form"]
        val = reg["metadata"]["form_validation"]
        assert form["form_subtype"] == FormDocumentSubtype.APPLICATION_FORM.value

        cbs = form["checkboxes"]
        states_found = {c["state"] for c in cbs}
        assert CheckboxState.CHECKED.value in states_found
        assert CheckboxState.UNCHECKED.value in states_found
        assert CheckboxState.UNKNOWN.value in states_found

        # Verify coordinates preserved inside [0..1000]
        for cb in cbs:
            nb = cb["checkbox_coordinates"]["normalized_box"]
            assert len(nb) == 4 and 0 <= nb[0] < nb[2] <= 1000 and 0 <= nb[1] < nb[3] <= 1000

        # Verify radio groups parsed & ambiguous group flagged
        rgs = form["radio_groups"]
        assert len(rgs) >= 2
        assert any(rg["is_ambiguous"] is False and len(rg["selected_options"]) == 1 for rg in rgs)
        assert any(rg["is_ambiguous"] is True and len(rg["selected_options"]) >= 2 for rg in rgs)
        assert val["review_required"] is True
        assert "ambiguous_checkbox_or_signature_mark" in val["issue_codes"]
        assert "ambiguous_field_mapping" in val["issue_codes"]


# ==============================================================================
# 4. INCOMPLETE FORMS & MULTI-COLUMN FORMS
# ==============================================================================
class TestIncompleteAndMultiColumnForms:
    def test_incomplete_form_preserves_blank_fields_and_never_infers(self):
        img = Image.new("RGB", (820, 520), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_body = _load_font(18)
            d.text((40, 28), "GRANT APPLICATION FORM", font=f_title, fill=(10, 10, 10))

            # Populated colon field
            d.text((40, 82), "Applicant Name: Priya Das", font=f_body, fill=(10, 10, 10))

            # Empty underline slot (label on left)
            d.text((40, 145), "Organization:", font=f_body, fill=(10, 10, 10))
            d.line((185, 168, 470, 168), fill=(15, 15, 15), width=2)

            # Empty bordered input box (label on left)
            d.text((40, 208), "Tax ID:", font=f_body, fill=(10, 10, 10))
            d.rectangle((185, 198, 460, 238), outline=(15, 15, 15), width=2)

            # Empty colon label with nothing to the right
            d.text((40, 272), "Project Code:", font=f_body, fill=(10, 10, 10))

            # Blank signature box
            d.text((40, 340), "Applicant Signature:", font=f_body, fill=(10, 10, 10))
            d.rectangle((240, 330, 520, 390), outline=(15, 15, 15), width=2)

            ext = FormKVExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = ext.extract_form_region(
                page_image=img,
                form_box=None,
                page_number=1,
                page_width=820.0,
                page_height=520.0,
            )
        finally:
            img.close()

        form = reg["metadata"]["form"]
        val = reg["metadata"]["form_validation"]
        assert form["is_complete"] is False
        assert form["governance_notices"]["missing_values_inferred"] is False
        assert val["needs_review"] is True
        assert "incomplete_form_fields" in val["issue_codes"]

        f_app = _find_field(form["fields"], "Applicant Name")
        assert f_app["is_blank"] is False and "Priya" in f_app["raw_value"]

        for blank_lbl in ("Organization", "Tax ID", "Project Code"):
            fb = _find_field(form["fields"], blank_lbl)
            assert fb["is_blank"] is True
            assert fb["status"] == FormFieldStatus.BLANK.value
            assert fb["raw_value"] == ""
            assert fb["numeric_value"] is None

        assert len(form["blank_fields"]) >= 3
        sigs = form["signature_regions"]
        assert len(sigs) >= 1
        assert sigs[0]["status"] == FormFieldStatus.SIGNATURE_BLANK.value
        assert sigs[0]["signer_identified"] is False
        assert sigs[0]["signer_identity"] is None

    def test_two_column_form_prevents_cross_column_stealing(self):
        img = Image.new("RGB", (980, 480), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_body = _load_font(17)
            d.text((40, 26), "TRAVEL EXPENSE CLAIM", font=f_title, fill=(10, 10, 10))
            # Clear vertical column divider between x=480 left and right columns
            d.line((490, 75, 490, 420), fill=(40, 40, 40), width=2)

            # Left column
            d.text((40, 95), "Full Name: Alice Brown", font=f_body, fill=(10, 10, 10))
            d.text((40, 155), "Department: Finance", font=f_body, fill=(10, 10, 10))
            # Deliberately BLANK field in left column opposite a populated field in right column!
            d.text((40, 215), "Manager Ext:", font=f_body, fill=(10, 10, 10))

            # Right column
            d.text((520, 95), "Employee ID: E-408", font=f_body, fill=(10, 10, 10))
            d.text((520, 155), "Claim Date: 2026-09-21", font=f_body, fill=(10, 10, 10))
            d.text((520, 215), "Office: Dhaka", font=f_body, fill=(10, 10, 10))
            d.text((520, 275), "Total Claim: $480.00", font=f_body, fill=(10, 10, 10))

            ext = FormKVExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = ext.extract_form_region(
                page_image=img,
                form_box=None,
                page_number=1,
                page_width=980.0,
                page_height=480.0,
            )
        finally:
            img.close()

        form = reg["metadata"]["form"]
        assert form["column_count"] >= 2
        fields = form["fields"]

        f_name = _find_field(fields, "Full Name")
        f_emp = _find_field(fields, "Employee ID")
        f_mgr = _find_field(fields, "Manager Ext")
        f_off = _find_field(fields, "Office")
        f_tot = _find_field(fields, "Total Claim")

        assert "Alice" in f_name["raw_value"]
        assert "E-408" in f_emp["raw_value"]
        assert "Dhaka" in f_off["raw_value"]
        assert f_tot["numeric_value"] == pytest.approx(480.0)

        # Critical cross-column check: blank left field must NOT steal "Office: Dhaka" from col 2!
        assert f_mgr["is_blank"] is True
        assert f_mgr["raw_value"] == ""
        assert f_mgr["column_index"] != f_off["column_index"]


# ==============================================================================
# 5. AMBIGUITY, SIGNATURES, APPROVAL ISOLATION & LOW-QUALITY / BENGALI SCANS
# ==============================================================================
class TestGovernanceGuardsAndLowQualityScans:
    def test_approval_field_and_signature_ink_never_infer_authority_or_signer(self):
        img = Image.new("RGB", (820, 480), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_body = _load_font(18)
            d.text((40, 28), "EXPENSE APPROVAL FORM", font=f_title, fill=(10, 10, 10))
            d.text((40, 88), "Approved: Yes", font=f_body, fill=(10, 10, 10))
            d.text((40, 138), "Approved By: M. Rahman", font=f_body, fill=(10, 10, 10))

            # Unlabeled checkbox (ambiguous unlabeled control!)
            _draw_checkbox(d, 640, 135, size=24, mode="checked")

            # Populated signature box containing realistic handwritten scribble ink
            d.text((40, 220), "Authorized Signature:", font=f_body, fill=(10, 10, 10))
            d.rectangle((260, 210, 560, 295), outline=(15, 15, 15), width=2)
            pts = [(280, 268), (305, 232), (330, 272), (360, 228), (395, 270), (435, 240), (485, 260), (520, 245)]
            d.line(pts, fill=(12, 12, 12), width=3)

            ext = FormKVExtractor(ocr_provider=TesseractOCRProvider(lang="eng"))
            reg = ext.extract_form_region(
                page_image=img,
                form_box=None,
                page_number=1,
                page_width=820.0,
                page_height=480.0,
            )
        finally:
            img.close()

        form = reg["metadata"]["form"]
        val = reg["metadata"]["form_validation"]

        # Never infer approval
        assert form["governance_notices"]["approval_inferred"] is False
        assert form["governance_notices"]["signer_identified"] is False
        assert form["governance_notices"]["settlement_delegated"] is True

        f_app = _find_field(form["fields"], "Approved")
        assert f_app["raw_value"].lower() == "yes"
        assert f_app["is_approval_field"] is True
        assert f_app["approval_inferred"] is False
        assert f_app["is_authoritative_decision"] is False

        # Signature present visually, but signer identity is NEVER guessed
        sigs = form["signature_regions"]
        assert len(sigs) >= 1
        assert sigs[0]["status"] == "signature_present"
        assert sigs[0]["signer_identified"] is False
        assert sigs[0]["signer_identity"] is None

        # Unlabeled checkbox flagged ambiguous -> review_required
        assert val["review_required"] is True
        assert any("unlabeled" in str(a.get("reason") or "") for a in form["ambiguous_fields"])

    def test_low_quality_blurry_scan_handwritten_ink_low_res_and_unavailable_ocr(self):
        # 1. Blurry/noisy scan + bordered input box filled only with unparsed handwritten strokes
        img = Image.new("RGB", (820, 440), "white")
        try:
            d = ImageDraw.Draw(img)
            f_body = _load_font(17)
            d.text((40, 40), "Patient Name:", font=f_body, fill=(85, 85, 85))
            d.rectangle((200, 32, 520, 76), outline=(60, 60, 60), width=2)
            # Scrawled illegible ink marks inside input box
            d.line([(220, 62), (240, 42), (255, 65), (275, 45), (310, 62), (345, 46), (380, 60)], fill=(45, 45, 45), width=2)
            d.text((40, 120), "Reference: REF-9901", font=f_body, fill=(95, 95, 95))
            blurry = img.filter(ImageFilter.GaussianBlur(radius=1.1))
        finally:
            img.close()

        try:
            fake_ocr = _FakeOCRProvider(
                available=True,
                text="Reference: REF-9901\nPatient Name:",
                confidence=0.41,
                boxes=[
                    {"word": "Patient", "confidence": 0.45, "normalized_box": [90, 48, 130, 130]},
                    {"word": "Name:", "confidence": 0.44, "normalized_box": [90, 136, 130, 195]},
                    {"word": "Reference:", "confidence": 0.42, "normalized_box": [272, 48, 312, 165]},
                    {"word": "REF-9901", "confidence": 0.39, "normalized_box": [272, 175, 312, 290]},
                ],
                warnings=["Low OCR contrast detected"],
                language="eng",
            )
            ext = FormKVExtractor(ocr_provider=fake_ocr)
            reg = ext.extract_form_region(
                page_image=blurry,
                form_box=None,
                page_number=1,
                page_width=820.0,
                page_height=440.0,
            )
        finally:
            blurry.close()

        form = reg["metadata"]["form"]
        val = reg["metadata"]["form_validation"]
        assert reg["metadata"]["ocr_metadata"]["confidence"] == pytest.approx(0.41)
        assert "Low OCR contrast detected" in reg["metadata"]["ocr_metadata"]["warnings"]
        assert val["review_required"] is True
        assert "low_confidence_or_handwritten_values" in val["issue_codes"]
        assert "unreadable_handwritten_or_inked_field" in val["issue_codes"]

        f_pat = _find_field(form["fields"], "Patient Name")
        assert f_pat["possibly_handwritten"] is True
        assert f_pat["status"] == FormFieldStatus.UNREADABLE.value

        f_ref = _find_field(form["fields"], "Reference")
        assert f_ref["raw_value"] == "REF-9901"
        assert f_ref["is_low_confidence"] is True
        assert f_ref["status"] == FormFieldStatus.LOW_CONFIDENCE.value

        # 2. Low-resolution form crop (<160x120) preserves crop image and flags review_required
        tiny = Image.new("RGB", (110, 80), "white")
        try:
            td = ImageDraw.Draw(tiny)
            td.text((8, 12), "ID: 12", fill=(20, 20, 20))
            reg_tiny = ext.extract_form_region(
                page_image=tiny,
                form_box=None,
                page_number=1,
                page_width=110.0,
                page_height=80.0,
            )
        finally:
            tiny.close()

        assert reg_tiny["metadata"]["form_validation"]["review_required"] is True
        assert "low_resolution_form_crop" in reg_tiny["metadata"]["form_validation"]["issue_codes"]
        assert reg_tiny["metadata"]["form_crop_reference"]["width_px"] == 110

        # 3. Graceful unavailable Tesseract fallback & Bengali label support
        unavail_ext = FormKVExtractor(ocr_provider=_FakeOCRProvider(available=False))
        blank_img = Image.new("RGB", (320, 220), "white")
        try:
            reg_unavail = unavail_ext.extract_form_region(page_image=blank_img, page_number=1, page_width=320.0, page_height=220.0)
        finally:
            blank_img.close()
        assert reg_unavail["metadata"]["ocr_metadata"]["ocr_available"] is False
        assert reg_unavail["metadata"]["form_validation"]["review_required"] is True

        ben_ocr = _FakeOCRProvider(
            available=True,
            text="নাম: রহিম উদ্দিন\nতারিখ: 2026-10-15",
            confidence=0.88,
            boxes=[
                {"word": "নাম:", "confidence": 0.90, "normalized_box": [120, 60, 175, 160]},
                {"word": "রহিম", "confidence": 0.87, "normalized_box": [120, 190, 175, 310]},
                {"word": "উদ্দিন", "confidence": 0.86, "normalized_box": [120, 320, 175, 450]},
                {"word": "তারিখ:", "confidence": 0.90, "normalized_box": [240, 60, 295, 170]},
                {"word": "2026-10-15", "confidence": 0.92, "normalized_box": [240, 190, 295, 420]},
            ],
            language="ben+eng",
            is_repaired=True,
        )
        ben_img = Image.new("RGB", (500, 320), "white")
        try:
            reg_ben = FormKVExtractor(ocr_provider=ben_ocr, repair_bengali=True).extract_form_region(
                page_image=ben_img, page_number=1, page_width=500.0, page_height=320.0
            )
        finally:
            ben_img.close()
        assert reg_ben["metadata"]["ocr_metadata"]["language"] == "ben+eng"
        f_ben = _find_field(reg_ben["metadata"]["form"]["fields"], "নাম")
        assert "রহিম উদ্দিন" in f_ben["raw_value"]


# ==============================================================================
# 6. MULTI-PAGE PDF + LAYOUT ROUTING + SETTLEMENT/GOVERNANCE ISOLATION
# ==============================================================================
class TestPDFIntegrationAndGovernanceIsolation:
    def test_multipage_pdf_digital_scanned_and_rotated_90_deg(self):
        doc = pymupdf.open()
        try:
            # Page 1: Searchable/Digital vector PDF form
            p1 = doc.new_page(width=612, height=792)
            p1.insert_text((50, 55), "APPLICATION FORM", fontsize=16)
            p1.insert_text((50, 100), "Applicant: Nadia Karim", fontsize=12)
            p1.insert_text((50, 130), "Request Date: 2026-11-05", fontsize=12)
            sh = p1.new_shape()
            sh.draw_rect(pymupdf.Rect(50, 160, 68, 178))
            sh.draw_line((53, 163), (65, 175))
            sh.draw_line((65, 163), (53, 175))
            sh.finish(color=(0, 0, 0), width=1.5)
            sh.commit()
            p1.insert_text((76, 173), "Expedite Review", fontsize=12)

            # Page 2: Scanned PDF page containing embedded raster form image (zero native text)
            p2 = doc.new_page(width=640, height=480)
            sc_img = Image.new("RGB", (620, 440), "white")
            try:
                sd = ImageDraw.Draw(sc_img)
                f = _load_font(18)
                sd.text((40, 35), "EXPENSE CLAIM SHEET", font=f, fill=(10, 10, 10))
                sd.text((40, 90), "Employee:Tariq Hasan", font=f, fill=(10, 10, 10))
                sd.text((40, 140), "Amount: $95.00", font=f, fill=(10, 10, 10))
                _draw_checkbox(sd, 42, 195, size=24, mode="checked")
                sd.text((80, 196), "Mileage", font=f, fill=(10, 10, 10))
                buf_img = io.BytesIO()
                sc_img.save(buf_img, format="PNG")
                p2.insert_image(pymupdf.Rect(10, 20, 630, 460), stream=buf_img.getvalue())
            finally:
                sc_img.close()

            # Page 3: Rotated 90-degree PDF form page
            p3 = doc.new_page(width=792, height=612)
            p3.insert_text((70, 80), "INVOICE RECORD", fontsize=16)
            p3.insert_text((70, 125), "Vendor: Apex Supplies", fontsize=12)
            p3.insert_text((70, 155), "Due Date: 2026-12-01", fontsize=12)
            p3.insert_text((70, 185), "Invoice Total: $310.25", fontsize=12)
            p3.set_rotation(90)

            pdf_bytes = doc.tobytes()
        finally:
            doc.close()

        ext = VisualDocumentExtractor.with_form_extractor(
            ocr_provider=TesseractOCRProvider(lang="eng"),
            use_pymupdf=True,
        )
        pages = ext.extract_document(pdf_bytes, doc_type="pdf", filename="multi_forms.pdf")
        assert len(pages) == 3

        for p in pages:
            VisualPipelineIntegrationAdapter.validate_page_payload(p, strict=True)

        # Page 1: native PDF form without extra duplication
        p1_forms = [r for r in pages[0]["visual_regions"] if r["region_type"] == VisualRegionType.FORM_KV.value]
        assert len(p1_forms) == 1
        assert p1_forms[0]["metadata"]["form"]["source_mode"] in ("native_pdf", "mixed")
        assert p1_forms[0]["metadata"]["ocr_metadata"]["ocr_triggered"] is False
        assert _find_field(p1_forms[0]["metadata"]["form"]["fields"], "Applicant")["raw_value"] == "Nadia Karim"

        # Page 2: scanned page -> OCR triggered and form extracted
        assert pages[1]["page_classification"] == "scanned"
        p2_forms = [r for r in pages[1]["visual_regions"] if r["region_type"] == VisualRegionType.FORM_KV.value]
        assert len(p2_forms) == 1
        assert p2_forms[0]["metadata"]["ocr_metadata"]["ocr_triggered"] is True
        assert _find_field(p2_forms[0]["metadata"]["form"]["fields"], "Amount")["numeric_value"] == pytest.approx(95.0)

        # Page 3: rotated 90 deg -> coordinates preserved inside [0..1000]
        assert pages[2]["rotation"] == 90
        p3_forms = [r for r in pages[2]["visual_regions"] if r["region_type"] == VisualRegionType.FORM_KV.value]
        assert len(p3_forms) == 1
        assert p3_forms[0]["metadata"]["source_coordinates"]["source_rotation"] == 90
        nb3 = p3_forms[0]["normalized_box"]
        assert 0 <= nb3[0] < nb3[2] <= 1000 and 0 <= nb3[1] < nb3[3] <= 1000

    @pytest.mark.django_db
    def test_pp_doclayout_s_form_routing_and_strict_governance_settlement_isolation(self):
        from apps.knowledge.models import DocumentChunk, KnowledgeItem
        from apps.sources.models import DocumentPage, SourceDocument

        assert SourceDocument.objects.count() == 0
        assert DocumentPage.objects.count() == 0
        assert DocumentChunk.objects.count() == 0
        assert KnowledgeItem.objects.count() == 0

        WorkerLayoutModelCache.clear()

        img = Image.new("RGB", (760, 480), "white")
        try:
            d = ImageDraw.Draw(img)
            f_title = _load_font(20)
            f_body = _load_font(17)
            d.text((40, 24), "VENDOR APPLICATION", font=f_title, fill=(10, 10, 10))
            d.text((40, 82), "Company: GreenLine Ltd", font=f_body, fill=(10, 10, 10))
            d.text((40, 128), "Approved: Yes", font=f_body, fill=(10, 10, 10))
            d.text((40, 175), "Contact Email:", font=f_body, fill=(10, 10, 10))
            _draw_checkbox(d, 48, 228, size=24, mode="checked")
            d.text((84, 230), "W-9 Included", font=f_body, fill=(10, 10, 10))

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        finally:
            img.close()

        ext = VisualDocumentExtractor.with_pp_doclayout_s_and_slanet_plus(
            ocr_provider=TesseractOCRProvider(lang="eng"),
            enable_forms=True,
            use_pymupdf=False,
        )
        # "text" region upgrades deterministically to FormKVExtractor via is_form_kv_text
        assert isinstance(ext.visual_provider, PPDocLayoutSProvider)
        ext.visual_provider._model_loader = lambda _cfg: _SpyLayoutModel([
            {"cls_id": 11, "label": "doc_title", "score": 0.95, "coordinate": [30.0, 15.0, 360.0, 56.0]},
            {"cls_id": 2, "label": "text", "score": 0.93, "coordinate": [25.0, 65.0, 560.0, 290.0]},
        ])

        pages = ext.extract_document(img_bytes, doc_type="image", filename="layout_form.png")
        assert len(pages) == 1
        page = pages[0]
        VisualPipelineIntegrationAdapter.validate_page_payload(page, strict=True)

        form_regs = [r for r in page["visual_regions"] if r["region_type"] == VisualRegionType.FORM_KV.value]
        assert len(form_regs) == 1
        fmeta = form_regs[0]["metadata"]
        form = fmeta["form"]
        assert _find_field(form["fields"], "Company")["raw_value"] == "GreenLine Ltd"
        assert _find_field(form["fields"], "Contact Email")["is_blank"] is True
        assert form["governance_notices"]["approval_inferred"] is False
        # Incomplete field triggers page-level review flag cleanly
        assert page["needs_review"] is True

        # Strict isolation guarantee: zero writes to Settlement or Knowledge Store DB tables
        assert SourceDocument.objects.count() == 0
        assert DocumentPage.objects.count() == 0
        assert DocumentChunk.objects.count() == 0
        assert KnowledgeItem.objects.count() == 0

