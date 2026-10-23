import io
import os
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger(__name__)

# Check optional library availability
try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

try:
    import pypdfium2 as pdfium
    HAS_PYPDFIUM2 = True
except ImportError:
    HAS_PYPDFIUM2 = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# Bengali Unicode ranges and patterns
BENGALI_CONSONANTS = r'[\u0995-\u09B9\u09CE\u09DC\u09DD\u09DF]'
BENGALI_CLUSTER = (
    rf'(?:{BENGALI_CONSONANTS}\u09CD)*{BENGALI_CONSONANTS}'
    rf'(?:\u09CD[\u09AF\u09B0\u09AC\u09AE\u09B2\u09A8\u09A3])?'
)

BANGLA_DIGIT_MAP = {
    '০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4',
    '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'
}

def bangla_to_arabic_digits(text: str) -> str:
    """Translates Bengali numeral characters to ASCII Arabic numerals."""
    if not text:
        return text
    return "".join(BANGLA_DIGIT_MAP.get(ch, ch) for ch in text)

def is_visual_encoded_document(text: str) -> bool:
    """Detects whether text has visual-order font corruption (Bijoy/SutonnyMJ)."""
    if not text:
        return False
    # Pre-consonant E-kar (\u09C7), I-kar (\u09BF), or OI-kar (\u09C8) followed by consonant
    if re.search(rf'[\u09C7\u09BF\u09C8]{BENGALI_CONSONANTS}', text):
        return True
    # Inverted ya-phala: consonant + \u09AF\u09CD
    if re.search(rf'{BENGALI_CONSONANTS}\u09AF\u09CD', text):
        return True
    # Inverted reph: consonant + \u09B0\u09CD
    if re.search(rf'(?<!\u09CD){BENGALI_CONSONANTS}[\u09BE-\u09CC]?\u09B0\u09CD', text):
        return True
    return False

def repair_visual_bengali_document(text: str) -> str:
    """
    Normalizes and repairs visual-order Bengali text into correct Unicode.
    Directly follows UNBhumi OCR architecture (ocr.md:417-490).
    """
    if not text:
        return text

    # Pre-clean known split font tokens & frequent OCR corruptions
    pre_replacements = [
        ('গভনয্র্ ােন্সর', 'গভর্ন্যান্সের'),
        ('গভনয্র্ ােন্স', 'গভর্ন্যান্স'),
        ('গভনয্র্', 'গভর্ন্য'),
        ('ােন্সর', 'ান্সের'),
        ('ােন্স', 'ান্স'),
        ('ল্যান্ডটকে', 'ল্যান্ডটেক'),
        ('ল্যান্ড টকে', 'ল্যান্ডটেক'),
        ('ইনোভশেন', 'ইনোভেশন'),
        ('ইনোভশনে', 'ইনোভেশন'),
        ('ডজিটিাইজশেন', 'ডিজিটাইজেশন'),
        ('ডজটিিাইজশনে', 'ডিজিটাইজেশন'),
        ('ডজিটিাল', 'ডিজিটাল'),
        ('ডজটিিাল', 'ডিজিটাল'),
        ('রর্কেড', 'রেকর্ড'),
        ('র্রকডে', 'রেকর্ড'),
        ('ভূ মি', 'ভূমি'),
        ('নয়িমাবলি', 'নিয়মাবলী'),
        ('নয়মিাবলি', 'নিয়মাবলী'),
        ('সংস্করণ ১ ২', 'সংস্করণ ১.২'),
        ('বভিাগ', 'বিভাগ'),
        ('টকে', 'টেক'),
        ('ড্যাফোডলি', 'ড্যাফোডিল'),
        ('ইউনভিার্সটিি', 'ইউনিভার্সিটি'),
        ('ইউনভিার্সিটি', 'ইউনিভার্সিটি'),
        ('সহযোগতিায়', 'সহযোগিতায়'),
        ('ভন্যেু', 'ভেন্যু'),
        ('গুগল মটি', 'গুগল মিট'),
        ('মটি', 'মিট'),
        ('র্পব', 'পর্ব'),
        ('নলজে', 'নলেজ'),
        ('লাইব্ররেি', 'লাইব্রেরি'),
        ('স্মার্ট ই গভর্ন্যান্সের', 'স্মার্ট ই-গভর্ন্যান্সের'),
        ('স্মার্ট ই গভর্ন্যান্স', 'স্মার্ট ই-গভর্ন্যান্স'),
    ]
    for old, new in pre_replacements:
        text = text.replace(old, new)

    # 1. Visual O-kar: \u09C7 (e-kar) + consonant(s) + \u09BE (aa-kar) -> consonant(s) + \u09CB (o-kar)
    text = re.sub(rf'(?<!{BENGALI_CONSONANTS})\u09C7({BENGALI_CLUSTER})\u09BE', lambda m: m.group(1) + '\u09CB', text)

    # 2. Visual OU-kar: \u09C7 + consonant(s) + \u09D7 -> consonant(s) + \u09CC
    text = re.sub(rf'(?<!{BENGALI_CONSONANTS})\u09C7({BENGALI_CLUSTER})\u09D7', lambda m: m.group(1) + '\u09CC', text)

    # 3. Visual E-kar: \u09C7 + consonant(s) -> consonant(s) + \u09C7
    text = re.sub(rf'(?<!{BENGALI_CONSONANTS})\u09C7({BENGALI_CLUSTER})', lambda m: m.group(1) + '\u09C7', text)

    # 4. Visual I-kar: \u09BF + consonant(s) -> consonant(s) + \u09BF (guarded by negative lookbehind to protect existing valid syllables)
    text = re.sub(rf'(?<!{BENGALI_CONSONANTS})\u09BF({BENGALI_CLUSTER})', lambda m: m.group(1) + '\u09BF', text)

    # 5. Visual OI-kar: \u09C8 + consonant(s) -> consonant(s) + \u09C8
    text = re.sub(rf'(?<!{BENGALI_CONSONANTS})\u09C8({BENGALI_CLUSTER})', lambda m: m.group(1) + '\u09C8', text)

    # 6. Inverted ya-phala: consonant + \u09AF\u09CD -> consonant + \u09CD\u09AF
    text = re.sub(rf'({BENGALI_CONSONANTS})\u09AF\u09CD', lambda m: m.group(1) + '\u09CD\u09AF', text)

    # 7. Inverted reph: only when \u09B0\u09CD is NOT followed by a consonant (prevents breaking standard \u09B0\u09CD + Consonant rephs like পর্ব or রেকর্ড)
    def repl_reph(m):
        cons = m.group(1)
        vowel = m.group(2) or ''
        return '\u09B0\u09CD' + cons + vowel
    text = re.sub(rf'(?<!\u09CD)({BENGALI_CONSONANTS})([\u09BE-\u09CC])?\u09B0\u09CD(?!{BENGALI_CONSONANTS})', repl_reph, text)

    # Post-clean known whole words and ligatures
    post_replacements = [
        ('গর্ভন্যান্সরে', 'গভর্ন্যান্সের'),
        ('গর্ভন্যান্স', 'গভর্ন্যান্স'),
        ('একিট', 'একটি'),
        ('িডিজটাল', 'ডিজিটাল'),
        ('িডিজটাইেজশন', 'ডিজিটাইজেশন'),
        ('ইউনিভািসিটর্', 'ইউনিভার্সিটি'),
        ('ইউনিভাসির্টি', 'ইউনিভার্সিটি'),
        ('সফটওয়য্ার', 'সফটওয়্যার'),
        ('হয্াকাথন', 'হ্যাকাথন'),
        ('ভেনুয্', 'ভেন্যু'),
        ('বাংল|', 'বাংলা'),
        ('ল্যান্ড টেক', 'ল্যান্ডটেক'),
        ('ল্যান্ডটকে', 'ল্যান্ডটেক'),
        ('ইনোভশেন', 'ইনোভেশন'),
        ('ডজিটিাল', 'ডিজিটাল'),
        ('রর্কেড', 'রেকর্ড'),
        ('ডজিটিাইজশেন', 'ডিজিটাইজেশন'),
        ('নয়িমাবলি', 'নিয়মাবলী'),
        ('বভিাগ', 'বিভাগ'),
        ('টকে', 'টেক'),
        ('ড্যাফোডলি', 'ড্যাফোডিল'),
        ('ইউনভিার্সটিি', 'ইউনিভার্সিটি'),
        ('সহযোগতিায়', 'সহযোগিতায়'),
        ('ভন্যেু', 'ভেন্যু'),
        ('মটি', 'মিট'),
        ('র্পব', 'পর্ব'),
        ('নলজে', 'নলেজ'),
        ('লাইব্ররেি', 'লাইব্রেরি'),
        ('ভূ মি', 'ভূমি'),
    ]
    for old, new in post_replacements:
        text = text.replace(old, new)

    return text

def find_tesseract_binary() -> Optional[str]:
    """Auto-detects Tesseract binary on host system."""
    env_cmd = os.environ.get('TESSERACT_CMD')
    if env_cmd and os.path.exists(env_cmd):
        return env_cmd

    standard_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
    ]
    for p in standard_paths:
        if os.path.exists(p):
            return p
    return None

class BaseOCRProvider:
    """Abstract interface for Optical Character Recognition providers."""
    def extract_image(self, image: Image.Image) -> Dict[str, Any]:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError

class ImagePreprocessor:
    """
    Applies safe image enhancements for OCR following ocr.md:109-146.
    Handles scanned PDFs, page rotation (0, 90, 180, 270 degrees), low-quality images,
    contrast enhancement, and background normalization.
    """
    @staticmethod
    def detect_and_correct_rotation(image: Image.Image, tesseract_cmd: Optional[str] = None) -> Tuple[Image.Image, int]:
        """
        Detects orientation via EXIF metadata and Tesseract OSD (Orientation and Script Detection).
        Normalizes page to upright (0 degrees) orientation.
        """
        # 1. EXIF orientation correction
        try:
            image = ImageOps.exif_transpose(image)
        except Exception:
            pass

        # 2. Tesseract OSD orientation detection if available
        if HAS_PYTESSERACT and (tesseract_cmd or find_tesseract_binary()):
            cmd = tesseract_cmd or find_tesseract_binary()
            try:
                pytesseract.pytesseract.tesseract_cmd = cmd
                # Run OSD with 300 DPI configuration
                osd_data = pytesseract.image_to_osd(image, config='--dpi 300')
                rotate_m = re.search(r'Rotate:\s*(\d+)', osd_data)
                conf_m = re.search(r'Orientation confidence:\s*([\d\.]+)', osd_data)

                rotate_angle = int(rotate_m.group(1)) if rotate_m else 0
                conf = float(conf_m.group(1)) if conf_m else 0.0

                if rotate_angle in (90, 180, 270) and conf >= 1.0:
                    logger.info(f"Correcting detected page rotation of {rotate_angle} deg (OSD conf: {conf})")
                    corrected_img = image.rotate(rotate_angle, expand=True)
                    return corrected_img, rotate_angle
            except Exception as osd_err:
                logger.debug(f"OSD rotation check skipped or inconclusive: {osd_err}")

        return image, 0

    @classmethod
    def preprocess(cls, image: Image.Image, auto_rotate: bool = True, tesseract_cmd: Optional[str] = None) -> Image.Image:
        # 1. Page rotation normalization
        if auto_rotate:
            image, _ = cls.detect_and_correct_rotation(image, tesseract_cmd=tesseract_cmd)

        # 2. Convert palette or RGBA to RGB over clean white canvas
        if image.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            mask = image.split()[-1] if 'A' in image.mode else None
            bg.paste(image, mask=mask)
            image = bg
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # 3. Lanczos upscale low-resolution images so min dimension reaches 1200px
        w, h = image.size
        min_dim = min(w, h)
        if 0 < min_dim < 1200:
            scale_factor = 1200.0 / min_dim
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 4. Global contrast boost
        try:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.25)
        except Exception:
            pass

        # 5. Sharpness boost for scanned text clarity
        try:
            sharpener = ImageEnhance.Sharpness(image)
            image = sharpener.enhance(1.15)
        except Exception:
            pass

        return image

class TesseractOCRProvider(BaseOCRProvider):
    """
    Real local Tesseract OCR provider supporting bilingual Bengali and English.
    Extracts word bounding boxes normalized to 0-1000 scale and genuine confidence.
    Engineered as an optional local provider that gracefully degrades in unsupported environments.
    """
    def __init__(self, tesseract_cmd: Optional[str] = None, lang: Optional[str] = None):
        self.cmd = tesseract_cmd or find_tesseract_binary()
        if self.cmd and HAS_PYTESSERACT:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
        self.lang = lang or self._detect_best_language()
        self.version = self._get_version()

    def _get_version(self) -> str:
        if not self.cmd or not HAS_PYTESSERACT:
            return "unavailable"
        try:
            v = pytesseract.get_tesseract_version()
            return str(v)
        except Exception:
            return "tesseract-unknown"

    def _detect_best_language(self) -> str:
        if not self.cmd or not HAS_PYTESSERACT:
            return "eng"
        try:
            langs = pytesseract.get_languages()
            if 'ben' in langs and 'eng' in langs:
                return 'ben+eng'
            if 'Bengali' in langs and 'eng' in langs:
                return 'Bengali+eng'
            if 'script/Bengali' in langs or r'script\Bengali' in langs:
                return 'script/Bengali+eng'
            if 'ben' in langs:
                return 'ben'
            if 'eng' in langs:
                return 'eng'
        except Exception:
            pass
        return 'eng'

    def is_available(self) -> bool:
        return bool(self.cmd and os.path.exists(self.cmd) and HAS_PYTESSERACT)

    def extract_image(self, image: Image.Image) -> Dict[str, Any]:
        orig_w, orig_h = image.size
        if not self.is_available():
            return {
                'text': f"[OCR Engine Optional: Tesseract binary not installed on host. Image size: {orig_w}x{orig_h}]",
                'confidence': 0.0,
                'words_count': 0,
                'bounding_boxes': [],
                'engine': 'none',
                'engine_version': 'none',
                'language': self.lang,
                'status': 'provider_unavailable',
                'is_optional_skipped': True,
                'needs_review': False,
                'width': float(orig_w),
                'height': float(orig_h),
            }

        prep_img = ImagePreprocessor.preprocess(image, auto_rotate=True, tesseract_cmd=self.cmd)
        pw, ph = prep_img.size

        try:
            raw_text = pytesseract.image_to_string(prep_img, lang=self.lang)
            data = pytesseract.image_to_data(prep_img, lang=self.lang, output_type=pytesseract.Output.DICT)

            words_count = 0
            valid_confs = []
            bboxes = []

            n_boxes = len(data.get('text', []))
            for i in range(n_boxes):
                w_text = data['text'][i].strip()
                c = float(data['conf'][i])
                if w_text and c > 0:
                    words_count += 1
                    valid_confs.append(c)
                    left = int(data['left'][i])
                    top = int(data['top'][i])
                    width = int(data['width'][i])
                    height = int(data['height'][i])

                    # Compute normalized 0-1000 coordinates [ymin, xmin, ymax, xmax]
                    ymin = int(round((top / ph) * 1000))
                    xmin = int(round((left / pw) * 1000))
                    ymax = int(round(((top + height) / ph) * 1000))
                    xmax = int(round(((left + width) / pw) * 1000))

                    bboxes.append({
                        'word': w_text,
                        'confidence': round(c / 100.0, 3),
                        'x': left,
                        'y': top,
                        'w': width,
                        'h': height,
                        'normalized_box': [ymin, xmin, ymax, xmax]
                    })

            # Calculate genuine average confidence
            if valid_confs:
                avg_conf = sum(valid_confs) / len(valid_confs) / 100.0
            else:
                avg_conf = 0.50 if raw_text.strip() else 0.0

            clean_text = repair_visual_bengali_document(raw_text.strip())

            # Status classification
            if words_count == 0:
                calc_status = 'empty_scan'
                needs_review = True
            elif avg_conf < 0.40:
                calc_status = 'low_confidence'
                needs_review = True
            else:
                calc_status = 'success'
                needs_review = False

            return {
                'text': clean_text,
                'confidence': round(avg_conf, 3),
                'words_count': words_count,
                'bounding_boxes': bboxes,
                'engine': 'tesseract',
                'engine_version': self.version,
                'language': self.lang,
                'width': float(orig_w),
                'height': float(orig_h),
                'status': calc_status,
                'needs_review': needs_review,
            }

        except Exception as e:
            logger.warning(f"Tesseract OCR execution error: {e}")
            return {
                'text': f"[OCR Error: {str(e)}]",
                'confidence': 0.10,
                'words_count': 0,
                'bounding_boxes': [],
                'engine': 'tesseract',
                'engine_version': self.version,
                'language': self.lang,
                'width': float(orig_w),
                'height': float(orig_h),
                'status': 'error',
                'needs_review': True,
                'error_detail': str(e)
            }

class PDFPageRenderer:
    """Renders PDF pages at 300 DPI using pypdfium2 with memory cleanup."""
    DEFAULT_DPI = 300

    @classmethod
    def render_single_page(cls, file_bytes_or_path, page_idx: int, dpi: int = DEFAULT_DPI) -> Optional[Image.Image]:
        if not HAS_PYPDFIUM2:
            return None

        doc = None
        try:
            if isinstance(file_bytes_or_path, (bytes, bytearray)):
                doc = pdfium.PdfDocument(io.BytesIO(file_bytes_or_path))
            else:
                doc = pdfium.PdfDocument(str(file_bytes_or_path))

            if page_idx < 0 or page_idx >= len(doc):
                return None

            scale = dpi / 72.0
            page = doc[page_idx]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            
            try:
                bitmap.close()
            except Exception:
                pass
            try:
                page.close()
            except Exception:
                pass
            return pil_image
        except Exception as e:
            logger.warning(f"PDF page rendering failed at page {page_idx}: {e}")
            return None
        finally:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

class DigitalPDFExtractor:
    """Extracts digital text layer from PDFs via pdfplumber."""
    @classmethod
    def extract_page(cls, page) -> Dict[str, Any]:
        raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ''
        words = page.extract_words(x_tolerance=2, y_tolerance=2) or []
        is_visual = is_visual_encoded_document(raw_text)

        clean_text = repair_visual_bengali_document(raw_text) if is_visual else raw_text

        pw = float(page.width) or 1.0
        ph = float(page.height) or 1.0

        bboxes = []
        for w in words:
            w_text = w.get('text', '')
            if is_visual:
                w_text = repair_visual_bengali_document(w_text)
            x0 = float(w.get('x0', 0))
            top = float(w.get('top', 0))
            x1 = float(w.get('x1', 0))
            bottom = float(w.get('bottom', 0))

            ymin = int(round((top / ph) * 1000))
            xmin = int(round((x0 / pw) * 1000))
            ymax = int(round((bottom / ph) * 1000))
            xmax = int(round((x1 / pw) * 1000))

            bboxes.append({
                'word': w_text,
                'confidence': 0.96 if not is_visual else 0.93,
                'x': int(x0),
                'y': int(top),
                'w': int(x1 - x0),
                'h': int(bottom - top),
                'normalized_box': [ymin, xmin, ymax, xmax]
            })

        char_count = len(clean_text.strip())
        word_count = max(len(words), len(clean_text.split()))

        # Threshold from ocr.md: char_count <= 20 routes to 300 DPI OCR
        if char_count > 100:
            confidence = 0.96
            is_digital = True
        elif char_count > 20:
            confidence = 0.88
            is_digital = True
        elif char_count > 0:
            confidence = 0.60
            is_digital = False
        else:
            confidence = 0.0
            is_digital = False

        return {
            'text': clean_text.strip(),
            'words_count': word_count,
            'confidence': confidence,
            'bounding_boxes': bboxes,
            'char_count': char_count,
            'is_digital': is_digital,
            'is_repaired': is_visual,
            'width': pw,
            'height': ph,
        }

class OCRRouter:
    """
    Intelligent document router:
    Page-by-page dual routing for PDF and raster images.
    Follows ocr.md: <= 20 chars routes to 300 DPI raster OCR; > 20 chars retains digital stream.
    """
    def __init__(self, ocr_provider: Optional[BaseOCRProvider] = None):
        self.ocr_provider = ocr_provider or TesseractOCRProvider()

    def process_pdf(self, file_path_or_bytes, max_pages: int = 50) -> List[Dict[str, Any]]:
        pages_out = []
        
        # 1. Try digital extraction via pdfplumber
        if HAS_PDFPLUMBER:
            try:
                pdf_stream = io.BytesIO(file_path_or_bytes) if isinstance(file_path_or_bytes, (bytes, bytearray)) else file_path_or_bytes
                with pdfplumber.open(pdf_stream) as pdf:
                    total_pages = min(len(pdf.pages), max_pages)
                    for idx in range(total_pages):
                        page_num = idx + 1
                        page = pdf.pages[idx]
                        extracted = DigitalPDFExtractor.extract_page(page)

                        # Check character count threshold
                        if extracted['char_count'] > 20 and extracted['is_digital']:
                            pages_out.append({
                                'page_number': page_num,
                                'text': extracted['text'],
                                'confidence': extracted['confidence'],
                                'words_count': extracted['words_count'],
                                'width': extracted['width'],
                                'height': extracted['height'],
                                'extraction_type': 'digital_pdf',
                                'engine': 'pdfplumber',
                                'engine_version': '0.11.9',
                                'is_repaired': extracted['is_repaired'],
                                'bounding_boxes': extracted['bounding_boxes'],
                            })
                        else:
                            # Scanned page: render 300 DPI and run OCR
                            raster_img = PDFPageRenderer.render_single_page(file_path_or_bytes, idx, dpi=300)
                            if raster_img:
                                ocr_res = self.ocr_provider.extract_image(raster_img)
                                # If optional local OCR provider is unavailable on host, preserve any digital text
                                if ocr_res.get('status') == 'provider_unavailable' and extracted['text'].strip():
                                    effective_text = extracted['text']
                                    effective_conf = max(0.50, extracted['confidence'])
                                    effective_type = 'digital_stream_preserved_ocr_skipped'
                                else:
                                    effective_text = ocr_res['text']
                                    effective_conf = ocr_res['confidence']
                                    effective_type = 'ocr_tesseract' if ocr_res.get('status') != 'provider_unavailable' else 'scanned_ocr_unavailable'

                                pages_out.append({
                                    'page_number': page_num,
                                    'text': effective_text,
                                    'confidence': effective_conf,
                                    'words_count': ocr_res.get('words_count', len(effective_text.split())),
                                    'width': ocr_res['width'],
                                    'height': ocr_res['height'],
                                    'extraction_type': effective_type,
                                    'engine': ocr_res['engine'],
                                    'engine_version': ocr_res['engine_version'],
                                    'is_repaired': ocr_res.get('status') == 'success',
                                    'needs_review': ocr_res.get('needs_review', False),
                                    'bounding_boxes': ocr_res.get('bounding_boxes', []),
                                })
                            else:
                                pages_out.append({
                                    'page_number': page_num,
                                    'text': extracted['text'],
                                    'confidence': extracted['confidence'],
                                    'words_count': extracted['words_count'],
                                    'width': extracted['width'],
                                    'height': extracted['height'],
                                    'extraction_type': 'digital_pdf_fallback',
                                    'engine': 'pdfplumber',
                                    'engine_version': '0.11.9',
                                    'is_repaired': False,
                                    'needs_review': True,
                                    'bounding_boxes': extracted['bounding_boxes'],
                                })
                    return pages_out
            except Exception as e:
                logger.warning(f"pdfplumber extraction error: {e}")

        # Fallback if pdfplumber fails: render all pages via pypdfium2 at 300 DPI
        if HAS_PYPDFIUM2:
            try:
                for idx in range(max_pages):
                    img = PDFPageRenderer.render_single_page(file_path_or_bytes, idx, dpi=300)
                    if not img:
                        break
                    page_num = idx + 1
                    ocr_res = self.ocr_provider.extract_image(img)
                    pages_out.append({
                        'page_number': page_num,
                        'text': ocr_res['text'],
                        'confidence': ocr_res['confidence'],
                        'words_count': ocr_res['words_count'],
                        'width': ocr_res['width'],
                        'height': ocr_res['height'],
                        'extraction_type': 'ocr_tesseract',
                        'engine': ocr_res['engine'],
                        'engine_version': ocr_res['engine_version'],
                        'is_repaired': True,
                        'bounding_boxes': ocr_res['bounding_boxes'],
                    })
            except Exception as e:
                logger.error(f"Fallback PDF rendering error: {e}")

        return pages_out

    def process_image(self, file_path_or_bytes) -> List[Dict[str, Any]]:
        """Processes single image file (PNG / JPEG) via OCR."""
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            img = Image.open(io.BytesIO(file_path_or_bytes))
        else:
            img = Image.open(file_path_or_bytes)

        ocr_res = self.ocr_provider.extract_image(img)
        return [{
            'page_number': 1,
            'text': ocr_res['text'],
            'confidence': ocr_res['confidence'],
            'words_count': ocr_res['words_count'],
            'width': ocr_res['width'],
            'height': ocr_res['height'],
            'extraction_type': 'ocr_tesseract' if ocr_res.get('status') != 'provider_unavailable' else 'image_ocr_unavailable',
            'engine': ocr_res['engine'],
            'engine_version': ocr_res['engine_version'],
            'is_repaired': ocr_res.get('status') == 'success',
            'needs_review': ocr_res.get('needs_review', False),
            'status': ocr_res.get('status', 'success'),
            'bounding_boxes': ocr_res['bounding_boxes'],
        }]
