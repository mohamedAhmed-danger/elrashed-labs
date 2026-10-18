import logging
import mimetypes
import os
import time
from typing import Optional, Union

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from config import Config
from utils.trace_logger import trace_logger

logger = logging.getLogger(__name__)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class TestItem(BaseModel):
    name: str = Field(description="Test name as written, e.g. CBC, FBS, TSH")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Legibility of this specific entry (0.0 to 1.0)",
    )


class OfferItem(BaseModel):
    name: str = Field(
        description="Offer/bundle title exactly as written, e.g. 'باقة اطمئن'"
    )
    price: Optional[str] = Field(
        description="Price exactly as written including currency, e.g. '499 جنيه'; null if no price is visible"
    )


class PrescriptionOCRResult(BaseModel):
    is_prescription: bool = Field(
        description="True if image is a medical prescription, doctor's order, lab request form, "
                    "OR a lab offer/package/bundle flyer. False only for unrelated images."
    )
    is_offer_or_bundle: bool = Field(
        description="True only if the image is a promotional lab offer, package, bundle, or discounted "
                    "test menu. Always false for prescriptions and request forms."
    )
    offers: list[OfferItem] = Field(
        description="Offers/bundles shown on the flyer (name + price only); empty if not an offer."
    )
    extracted_text: str = Field(
        description="Visible text as written; [illegible] for unreadable parts; empty if unrelated."
    )
    tests: list[TestItem] = Field(
        description="Requested tests for prescriptions only. MUST be empty for offers/bundles and unrelated images."
    )


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _detect_mime_type(image_bytes: bytes, file_path: str = None) -> str:
    """Detect image MIME type from magic header bytes or file extension."""
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return "image/webp"
    if file_path:
        guessed_type, _ = mimetypes.guess_type(file_path)
        if guessed_type:
            return guessed_type
    return "image/jpeg"


_shared_genai_client = None


def _get_genai_client() -> genai.Client:
    """Retrieve or instantiate a shared Google GenAI Client singleton."""
    global _shared_genai_client
    if _shared_genai_client is None:
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in configuration.")
        _shared_genai_client = genai.Client(api_key=api_key)
    return _shared_genai_client


# ── Layer 1 Public Interface ─────────────────────────────────────────────────

OCR_SYSTEM_PROMPT = """You are a medical document extraction assistant. Analyze the provided image and return structured data.

Instructions:
1. `is_prescription`: true if the image is a medical prescription, doctor's order, lab/investigation request form, OR a lab promotional offer / package / bundle flyer. false only if the image is unrelated (personal photos, memes, non-medical ads). If false, return `extracted_text` as "", `offers` as [] and `tests` as [].
2. `is_offer_or_bundle`: true only if the image is a lab promotional offer, package, bundle, or discounted tests menu. A prescription or request form is NEVER an offer. Otherwise false.
3. `offers`: if `is_offer_or_bundle` is true, list each offer shown with its `name` (exactly as written, do not translate) and its `price` (exactly as written with currency; null if no price is visible; never calculate or guess a price). If the flyer shows several offers, return one item per offer. Otherwise return [].
4. `extracted_text`: transcribe the visible text exactly as written. Use [illegible] for unreadable parts. Never guess. Text may be Arabic, English, or mixed: transcribe in the original language, do not translate.
5. `tests`: for prescriptions/request forms only, list every requested laboratory test or diagnostic investigation (including imaging/ECG). Keep names as written (abbreviations stay abbreviated, e.g. CBC, FBS). Do not list the same test twice. If `is_offer_or_bundle` is true, `tests` MUST be [] (do NOT list tests included in the bundle).
6. For each test provide `name` and an individual `confidence` score (0.0 to 1.0) reflecting how legible that specific entry is.
7. Include uncertain tests with LOW confidence instead of omitting them, so a human can review.
8. Do NOT extract patient info, doctor info, medications, notes, or instructions into `tests`.

CRITICAL HANDWRITING & NOISE-REDUCTION RULES:
- Ignore pre-printed paper branding: pad logos, drug brand names printed in the header/footer, table lines on the paper.
- Ignore decorative underlines, stray pen marks, background noise, and stains. Pay attention to marks ONLY if they cross out a test (exclude crossed-out tests) or tick/circle a specific item (on checkbox forms, include only ticked/circled items).
- For offers/bundles: extract only the offer name and price. Ignore clinic phone numbers, social media handles, slogans, and the list of included tests.
- Strict zero-hallucination: extract ONLY what is explicitly and visually present in the image. Do NOT infer or add complementary tests based on medical context (e.g., do NOT extract 'HbA1c' just because 'FBS' or 'RBS' is present unless 'HbA1c' is physically written).
- Confidence scale:
0.90-1.00: printed or clearly legible
0.70-0.89: legible handwriting, minor ambiguity
0.40-0.69: partially legible, plausible reading
0.00-0.39: mostly a guess or unreadable
If a test name is ambiguous, cropped, blurry, or requires medical guessing, use below 0.5.
"""


def analyze_prescription_image(
    image_path_or_bytes: Union[str, bytes, os.PathLike],
) -> tuple[PrescriptionOCRResult, dict[str, int]]:
    """
    Layer 1 OCR: Takes an image path or raw bytes, sends it to Gemini multimodally,
    and returns a validated PrescriptionOCRResult along with token usage.

    Zero database operations, zero business logic, zero threshold evaluation.
    """
    file_path = None
    if isinstance(image_path_or_bytes, (str, os.PathLike)):
        file_path = str(image_path_or_bytes)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Prescription image not found at: {file_path}")
        with open(file_path, "rb") as f:
            image_bytes = f.read()
    elif isinstance(image_path_or_bytes, (bytes, bytearray)):
        image_bytes = bytes(image_path_or_bytes)
    else:
        raise TypeError(f"Expected str, PathLike, or bytes, got {type(image_path_or_bytes)}")

    if not image_bytes:
        raise ValueError("Prescription image content is empty.")

    mime_type = _detect_mime_type(image_bytes, file_path)
    client = _get_genai_client()
    model_name = Config.OCR_MODEl

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    logger.info(
        "🔬 [OCR] Calling Gemini model=%s | mime_type=%s | bytes_len=%d",
        model_name, mime_type, len(image_bytes),
    )

    trace_logger.start_pipeline("OCR PIPELINE")
    try:
        trace_logger.step(
            "Gemini Multimodal OCR Call",
            input_data={
                "model": model_name,
                "mime_type": mime_type,
                "image_bytes_len": len(image_bytes),
                "source": file_path or "bytes",
            },
        )

        ocr_start = time.time()
        response = client.models.generate_content(
            model=model_name,
            contents=[image_part, "Extract the data from this image."],
            config=types.GenerateContentConfig(
                system_instruction=OCR_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=PrescriptionOCRResult,
                temperature=0.0,
            ),
        )
        ocr_duration = time.time() - ocr_start

        ocr_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            ocr_usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            ocr_usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            ocr_usage["total_tokens"] = getattr(response.usage_metadata, "total_token_count", 0) or 0

        if hasattr(response, "parsed") and isinstance(response.parsed, PrescriptionOCRResult):
            result = response.parsed
        elif response.text:
            result = PrescriptionOCRResult.model_validate_json(response.text)
        else:
            raise ValueError("Gemini returned an empty response for prescription OCR.")

        logger.info(
            "🔬 [OCR] Completed: is_prescription=%s | is_offer=%s | offers_count=%d | tests_count=%d | total_tokens=%d",
            result.is_prescription, result.is_offer_or_bundle, len(result.offers),
            len(result.tests), ocr_usage["total_tokens"],
        )

        trace_logger.log_llm_call(
            model=model_name,
            duration=ocr_duration,
            input_tokens=ocr_usage["input_tokens"],
            output_tokens=ocr_usage["output_tokens"],
            call_type="ocr_multimodal",
        )
        trace_logger.log_output({
            "is_prescription": result.is_prescription,
            "is_offer_or_bundle": result.is_offer_or_bundle,
            "offers": [f"{o.name} - {o.price}" for o in result.offers],
            "tests_found": len(result.tests),
            "tests": [f"{t.name} ({t.confidence:.2f})" for t in result.tests],
            "total_tokens": ocr_usage["total_tokens"],
        })

        return result, ocr_usage
    finally:
        trace_logger.end_pipeline("OCR PIPELINE")