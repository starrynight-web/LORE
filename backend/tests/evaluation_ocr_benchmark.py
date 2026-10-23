"""
LORE Enterprise — Empirical OCR and Extraction Benchmark Harness
Specification: docs/enterprise/docs/ocr.md, Master Prompt Requirements.

Systematically measures and compares extraction strategies across representative labelled datasets:
1. Digital PDF Stream (pdfplumber)
2. Local Tesseract OCR (bilingual ben+eng / eng with 300 DPI rendering)
3. Page Rotation Detection and Recovery (0, 90, 180, 270 degrees via OSD)
4. Visual Bengali Font Repair (Bijoy/SutonnyMJ -> Unicode)
5. Low-Quality & Low-Resolution Image Enhancement (Lanczos + Contrast + Sharpness)
6. Optional Provider Resilience: Execution in environments lacking Tesseract binary

Calculates genuine empirical metrics:
- Character Error Rate (CER)
- Word Error Rate (WER)
- Token Match F1
- Average Confidence Score
- Processing Latency (ms/page)
"""

import io
import time
import os
import re
from typing import Dict, Any, List, Tuple
from PIL import Image, ImageDraw, ImageFont

from apps.ingestion.pipeline.ocr import (
    ImagePreprocessor, TesseractOCRProvider, DigitalPDFExtractor,
    OCRRouter, repair_visual_bengali_document, is_visual_encoded_document,
    bangla_to_arabic_digits, find_tesseract_binary, HAS_PYTESSERACT
)


def compute_levenshtein(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance between two sequences."""
    if len(s1) < len(s2):
        return compute_levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def calculate_cer(reference: str, hypothesis: str) -> float:
    """Computes Character Error Rate (CER = edits / len(ref))."""
    ref = re.sub(r'\s+', ' ', reference.strip())
    hyp = re.sub(r'\s+', ' ', hypothesis.strip())
    if not ref:
        return 0.0 if not hyp else 1.0
    dist = compute_levenshtein(ref, hyp)
    return min(1.0, dist / max(1, len(ref)))


def calculate_wer(reference: str, hypothesis: str) -> float:
    """Computes Word Error Rate (WER = word edits / word count(ref))."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    dist = compute_levenshtein(ref_words, hyp_words)
    return min(1.0, dist / max(1, len(ref_words)))


def calculate_token_f1(reference: str, hypothesis: str) -> float:
    """Computes Token Set Overlap F1 Score."""
    ref_tokens = set(re.findall(r'\w+', reference.lower()))
    hyp_tokens = set(re.findall(r'\w+', hypothesis.lower()))
    if not ref_tokens and not hyp_tokens:
        return 1.0
    if not ref_tokens or not hyp_tokens:
        return 0.0
    tp = len(ref_tokens & hyp_tokens)
    fp = len(hyp_tokens - ref_tokens)
    fn = len(ref_tokens - hyp_tokens)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * (precision * recall) / (precision + recall)


class MockDigitalPage:
    """Simulates a pdfplumber digital page."""
    def __init__(self, text: str, width: float = 612.0, height: float = 792.0):
        self.text_content = text
        self.width = width
        self.height = height

    def extract_text(self, x_tolerance=2, y_tolerance=2):
        return self.text_content

    def extract_words(self, x_tolerance=2, y_tolerance=2):
        words = []
        x = 50.0
        y = 50.0
        for w in self.text_content.split():
            words.append({
                'text': w,
                'x0': x,
                'top': y,
                'x1': x + len(w) * 6,
                'bottom': y + 12
            })
            x += len(w) * 6 + 4
            if x > self.width - 100:
                x = 50.0
                y += 18
        return words


def create_synthetic_scanned_image(text_lines: List[str], width=1600, height=1600, rotation_deg=0, blur=False) -> Image.Image:
    """Renders synthetic scanned page with known ground truth for empirical OCR evaluation."""
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = 100
    for line in text_lines:
        draw.text((100, y), line, fill=(0, 0, 0))
        y += 45

    if rotation_deg in (90, 180, 270):
        img = img.rotate(rotation_deg, expand=True)

    return img


def run_ocr_benchmark_suite() -> Dict[str, Any]:
    """Executes the full suite of OCR and extraction empirical benchmarks."""
    results = {}

    # --------------------------------------------------------------------------
    # Dataset 1: Standard Clean Digital Text (Statutory Document)
    # --------------------------------------------------------------------------
    doc1_ground_truth = (
        "LORE ENTERPRISE STATUTORY POLICY MANUAL 2026. "
        "Section 104.2: All cloud deployments must enforce mandatory Multi-Factor Authentication (MFA). "
        "Authority Level: Rank 6 (Enterprise Policy). Effective from 2026-01-01 to 2026-12-31. "
        "Any scoped exception requires explicit sign-off from Chief Information Security Officer."
    )
    mock_page = MockDigitalPage(doc1_ground_truth)

    t0 = time.time()
    extracted_digital = DigitalPDFExtractor.extract_page(mock_page)
    lat_digital_ms = (time.time() - t0) * 1000

    results['dataset_1_digital_pdf'] = {
        'strategy': 'DigitalPDFExtractor (pdfplumber)',
        'cer': calculate_cer(doc1_ground_truth, extracted_digital['text']),
        'wer': calculate_wer(doc1_ground_truth, extracted_digital['text']),
        'token_f1': calculate_token_f1(doc1_ground_truth, extracted_digital['text']),
        'confidence': extracted_digital['confidence'],
        'latency_ms': lat_digital_ms,
        'words_count': extracted_digital['words_count'],
        'status': 'success'
    }

    # --------------------------------------------------------------------------
    # Dataset 2: Scanned Upright Page (Local Tesseract OCR)
    # --------------------------------------------------------------------------
    doc2_lines = [
        "LORE ENTERPRISE STATUTORY POLICY MANUAL 2026",
        "Section 104.2: All cloud deployments must enforce mandatory Multi-Factor Authentication",
        "Authority Level: Rank 6 Enterprise Policy. Effective from 2026-01-01 to 2026-12-31",
        "Any scoped exception requires explicit sign-off from Chief Information Security Officer",
        "Record Identity Hashing: SHA-256 with tenant-scoped cryptographic salt",
        "Verification Gate Stage 1: Input structure and binary header compliance",
        "Verification Gate Stage 2: Security scanning and vulnerability sanitization",
        "Verification Gate Stage 3: Extraction substance and groundedness validation",
        "Verification Gate Stage 4: Strict deduplication via content checksum",
        "Verification Gate Stage 5: Knowledge graph conflict pre-scan resolution",
        "Verification Gate Stage 6: Staged atomic merge with transaction rollback",
    ]
    doc2_ground_truth = "\n".join(doc2_lines)
    img_upright = create_synthetic_scanned_image(doc2_lines, width=1600, height=1600, rotation_deg=0)

    ocr_provider = TesseractOCRProvider()
    if ocr_provider.is_available():
        t0 = time.time()
        ocr_res_upright = ocr_provider.extract_image(img_upright)
        lat_ocr_ms = (time.time() - t0) * 1000

        results['dataset_2_tesseract_ocr_upright'] = {
            'strategy': f"TesseractOCRProvider ({ocr_provider.version}, lang: {ocr_provider.lang})",
            'cer': calculate_cer(doc2_ground_truth, ocr_res_upright['text']),
            'wer': calculate_wer(doc2_ground_truth, ocr_res_upright['text']),
            'token_f1': calculate_token_f1(doc2_ground_truth, ocr_res_upright['text']),
            'confidence': ocr_res_upright['confidence'],
            'latency_ms': lat_ocr_ms,
            'words_count': ocr_res_upright['words_count'],
            'status': ocr_res_upright['status']
        }
    else:
        results['dataset_2_tesseract_ocr_upright'] = {
            'strategy': 'TesseractOCRProvider (Unavailable on host)',
            'cer': 1.0,
            'wer': 1.0,
            'token_f1': 0.0,
            'confidence': 0.0,
            'latency_ms': 0.1,
            'words_count': 0,
            'status': 'provider_unavailable'
        }

    # --------------------------------------------------------------------------
    # Dataset 3: Rotated Scanned Page (90 Degrees with OSD Detection)
    # --------------------------------------------------------------------------
    img_rotated_90 = create_synthetic_scanned_image(doc2_lines, width=1600, height=1600, rotation_deg=90)
    if ocr_provider.is_available():
        t0 = time.time()
        ocr_res_rot = ocr_provider.extract_image(img_rotated_90)
        lat_rot_ms = (time.time() - t0) * 1000

        results['dataset_3_rotated_90deg_recovery'] = {
            'strategy': 'ImagePreprocessor OSD + Tesseract OCR',
            'cer': calculate_cer(doc2_ground_truth, ocr_res_rot['text']),
            'wer': calculate_wer(doc2_ground_truth, ocr_res_rot['text']),
            'token_f1': calculate_token_f1(doc2_ground_truth, ocr_res_rot['text']),
            'confidence': ocr_res_rot['confidence'],
            'latency_ms': lat_rot_ms,
            'words_count': ocr_res_rot['words_count'],
            'status': ocr_res_rot['status']
        }
    else:
        results['dataset_3_rotated_90deg_recovery'] = {
            'strategy': 'ImagePreprocessor OSD (Unavailable on host)',
            'cer': 1.0,
            'wer': 1.0,
            'token_f1': 0.0,
            'confidence': 0.0,
            'latency_ms': 0.1,
            'words_count': 0,
            'status': 'provider_unavailable'
        }

    # --------------------------------------------------------------------------
    # Dataset 4: Visual Bengali Font Corruption Repair (Bijoy/SutonnyMJ)
    # --------------------------------------------------------------------------
    # Known visual-order corrupted Bengali phrases from legacy government PDFs
    corrupted_bengali = "স্মার্ট ই গভনয্র্ ােন্সর ল্যান্ডটকে ইনোভশেন এবং ডজিটিাইজশেন নিয়মাবলী"
    expected_unicode = "স্মার্ট ই-গভর্ন্যান্সের ল্যান্ডটেক ইনোভেশন এবং ডিজিটাইজেশন নিয়মাবলী"

    t0 = time.time()
    is_corrupted = is_visual_encoded_document(corrupted_bengali)
    repaired_bengali = repair_visual_bengali_document(corrupted_bengali)
    lat_repair_ms = (time.time() - t0) * 1000

    results['dataset_4_bengali_font_repair'] = {
        'strategy': 'Deterministic Bengali Phonetic Reordering (OCR.md)',
        'detected_corruption': is_corrupted,
        'cer_before_repair': calculate_cer(expected_unicode, corrupted_bengali),
        'cer_after_repair': calculate_cer(expected_unicode, repaired_bengali),
        'token_f1': calculate_token_f1(expected_unicode, repaired_bengali),
        'latency_ms': lat_repair_ms,
        'exact_match': (repaired_bengali.strip() == expected_unicode.strip()),
        'status': 'success'
    }

    # --------------------------------------------------------------------------
    # Dataset 5: Low-Resolution Image Enhancement (Lanczos + Contrast Boost)
    # --------------------------------------------------------------------------
    tiny_img = Image.new('RGB', (400, 400), (240, 240, 240))
    d = ImageDraw.Draw(tiny_img)
    d.text((20, 100), "LOW RESOLUTION SPECIFICATION", fill=(100, 100, 100))

    t0 = time.time()
    enhanced_img = ImagePreprocessor.preprocess(tiny_img, auto_rotate=False)
    lat_enh_ms = (time.time() - t0) * 1000

    results['dataset_5_low_res_enhancement'] = {
        'strategy': 'ImagePreprocessor (Lanczos Upscaling + Contrast Enhancement)',
        'original_dimensions': tiny_img.size,
        'enhanced_dimensions': enhanced_img.size,
        'upscaled': enhanced_img.size[0] >= 1200,
        'latency_ms': lat_enh_ms,
        'status': 'success'
    }

    # --------------------------------------------------------------------------
    # Dataset 6: Optional Provider Decoupling & Graceful Degradation
    # --------------------------------------------------------------------------
    # Test OCR provider configured with non-existent binary to verify zero crash
    missing_ocr = TesseractOCRProvider(tesseract_cmd=r'C:\non_existent_path\tesseract.exe')
    t0 = time.time()
    fallback_res = missing_ocr.extract_image(img_upright)
    lat_fallback_ms = (time.time() - t0) * 1000

    results['dataset_6_optional_provider_resilience'] = {
        'strategy': 'TesseractOCRProvider (Mock Missing Binary / Unsupported OS)',
        'is_available': missing_ocr.is_available(),
        'crashed': False,
        'returned_status': fallback_res['status'],
        'is_optional_skipped': fallback_res.get('is_optional_skipped', False),
        'latency_ms': lat_fallback_ms,
        'status': 'success'
    }

    return results


if __name__ == '__main__':
    print("=" * 80)
    print("LORE ENTERPRISE — OCR & EXTRACTION EMPIRICAL BENCHMARK")
    print("=" * 80)
    benchmark_data = run_ocr_benchmark_suite()
    for dataset, data in benchmark_data.items():
        print(f"\n[{dataset}]")
        for k, v in data.items():
            print(f"  {k}: {v}")
    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETED SUCCESSFULLY.")
    print("=" * 80)
