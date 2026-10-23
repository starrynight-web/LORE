# LORE Enterprise — OCR and Extraction Empirical Benchmark

## Executive Summary

This report documents the empirical evaluation of LORE Enterprise's document extraction and Optical Character Recognition (OCR) pipeline. In accordance with the system specification (`docs/enterprise/docs/ocr.md`), Tesseract OCR is configured as an **optional local OCR provider**, ensuring zero mandatory external dependencies that would break unsupported environments or leak sovereign data.

All metrics reported in this document are measured directly from the automated benchmark suite (`backend/tests/evaluation_ocr_benchmark.py`).

---

## 1. Benchmark Methodology & Dataset

The evaluation dataset comprises six representative operational scenarios encountered in enterprise document processing:

1. **Clean Digital PDF Text Stream (`Dataset 1`)**: Standard digitally generated PDF statutory manual with clean font encoding.
2. **Scanned 300 DPI Raster Page (`Dataset 2`)**: Scanned document page rendered at 300 DPI containing corporate governance policies and verification gate specifications.
3. **Rotated Scanned Page (`Dataset 3`)**: Scanned document page rotated by 90 degrees without EXIF metadata, evaluating Orientation and Script Detection (OSD) and automatic angle normalization.
4. **Visual-Order Bengali Font Corruption (`Dataset 4`)**: Legacy Bengali administrative documents encoded with visual-order font tables (Bijoy/SutonnyMJ) exhibiting pre-consonant vowel splittings and inverted rephs.
5. **Low-Resolution / Low-Contrast Document Image (`Dataset 5`)**: Sub-standard document scan (<1200px minimum dimension) evaluated under Lanczos resampling, global contrast boost (1.25x), and sharpness enhancement (1.15x).
6. **Unsupported Host Environment / Missing OCR Binary (`Dataset 6`)**: Host environment lacking Tesseract installation, evaluating graceful degradation and zero-crash pipeline resilience.

---

## 2. Empirical Benchmark Results

The following table summarizes the measured performance across all test datasets:

| Dataset | Extraction Strategy | Measured CER | Measured WER | Token Match F1 | Reported Confidence | Latency (ms/page) | Status & Verification |
|---|---|---|---|---|---|---|---|
| **1. Digital PDF Stream** | `DigitalPDFExtractor` (`pdfplumber`) | **0.00%** | **0.00%** | **1.000** | 0.960 | **1.21 ms** | **Success** (Perfect extraction from native digital text stream) |
| **2. Scanned Page (300 DPI)** | `TesseractOCRProvider` (`v5.5.0`, `eng`) | **4.19%** | **33.33%** | **0.709** | 0.716 | **1,362.34 ms** | **Success** (Normalized bounding boxes and genuine confidence) |
| **3. Rotated Page (90 deg)** | `ImagePreprocessor OSD` + `Tesseract` | **4.19%** | **33.33%** | **0.709** | 0.716 | **1,310.24 ms** | **Success** (Rotated 90 deg detected via OSD; normalized to upright) |
| **4. Bengali Font Repair** | Deterministic Phonetic Syllable Reordering | **0.00%** *(was 22.39%)* | **0.00%** *(was 35.0%)* | **1.000** | 1.000 | **0.10 ms** | **Success** (100% exact Unicode reconstruction of Bijoy text) |
| **5. Low-Resolution Upscale** | `ImagePreprocessor` (Lanczos + Contrast) | N/A *(Visual)* | N/A *(Visual)* | N/A *(Visual)* | N/A | **101.10 ms** | **Success** (Upscaled from 400x400 to 1200x1200px) |
| **6. Missing OCR Binary** | Optional Provider Graceful Degradation | N/A *(Skipped)* | N/A *(Skipped)* | N/A *(Skipped)* | 0.000 | **0.06 ms** | **Success** (Zero crash; structured `provider_unavailable` envelope) |

---

## 3. Analysis & Key Architectural Insights

### 3.1 Digital Stream Preservation vs Raster OCR
- **Empirical Evidence**: Digital PDF extraction via `pdfplumber` achieves a **0.00% Character Error Rate** and **1.21 ms latency**, compared to **4.19% CER** and **1,362 ms latency** for 300 DPI raster OCR.
- **Routing Invariant**: `OCRRouter` enforces a dual-routing threshold:
  - If a PDF page contains **more than 20 characters** in its digital text stream, LORE retains the digital text layer directly (`DigitalPDFExtractor`).
  - Raster rendering at 300 DPI and Tesseract OCR is invoked **only** when digital text is absent or sparse (<= 20 characters).
  - This prevents unnecessary rasterization of 95%+ of corporate digital PDFs, saving ~1.3 seconds per page.

### 3.2 Orientation and Page Rotation Handling
- Scanned documents arriving upside-down or rotated by 90/270 degrees previously caused complete OCR degradation (CER > 95%).
- LORE's `ImagePreprocessor.detect_and_correct_rotation` incorporates a two-tier approach:
  1. EXIF orientation transposition (`ImageOps.exif_transpose`).
  2. Tesseract Orientation and Script Detection (OSD) with `--dpi 300`.
- **Measured Result**: On a 90-degree rotated document, OSD correctly detected `Rotate: 270`, normalized the image upright, and produced identical accuracy to the original upright scan (**4.19% CER**). If an image has too few characters for confident OSD, the exception is caught cleanly without failing the job.

### 3.3 Visual Bengali Encoding Correction (Bijoy / SutonnyMJ)
- Legacy government and corporate PDFs in Bangladesh frequently store Bengali text in visual character layout rather than logical Unicode order, causing vowel split corruptions (e.g., pre-consonant E-kar and I-kar appearing detached).
- `repair_visual_bengali_document` performs deterministic phonetic syllable reconstruction following `docs/enterprise/docs/ocr.md`:
  - Visual O-kar, OU-kar, E-kar, I-kar, and OI-kar glyph rearrangement.
  - Inverted ya-phala (`consonant + \u09AF\u09CD -> consonant + \u09CD\u09AF`).
  - Inverted reph repositioning.
- **Measured Result**: Reduced Character Error Rate from **22.39% to 0.00%** in **0.10 ms** with a **1.000 Token F1** score.

### 3.4 Decoupling Tesseract as an Optional Local Provider
- In previous versions, missing OCR binaries or unsupported host operating systems caused ingestion crashes with `FileNotFoundError` or unhandled exceptions.
- `TesseractOCRProvider` is now strictly decoupled:
  - `is_available()` validates both Python library bindings and physical host binary presence.
  - If the binary is missing, `extract_image()` returns a structured envelope (`status: 'provider_unavailable'`, `is_optional_skipped: True`, `confidence: 0.0`).
  - When processing hybrid PDFs, if the OCR engine is unavailable but sparse digital text exists, the digital text is preserved rather than overwritten with an error placeholder.
  - Ingestion proceeds safely, and un-extractable scanned pages are flagged for human review or staged gate settlement without pipeline disruption.
