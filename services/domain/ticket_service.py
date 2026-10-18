import functools
import io
import logging
import os
import unicodedata
from datetime import datetime, timezone
from typing import Any, List
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import arabic_reshaper
import fitz  # PyMuPDF
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

logger = logging.getLogger(__name__)

# ── colours (taken from the Sadara logo) ──────────────────────────────────────
BLUE = colors.HexColor("#2E7CC4")       # top of the flask square
INDIGO = colors.HexColor("#3F3F94")     # "صدارة" wordmark
PURPLE = colors.HexColor("#5B3F8F")     # tagline / bottom of the square
GREEN = colors.HexColor("#7DB63F")      # liquid inside the flask
LIGHT_ROW = colors.HexColor("#EEF2FA")  # very light blue-lavender tint
LIGHT_GREEN = colors.HexColor("#F1F8E9")
LINE = colors.HexColor("#D5DCEE")
WHITE = colors.white
MUTED = colors.HexColor("#5F6785")
DARK = colors.HexColor("#1F2340")

# Header text next to the logo
CLINIC_LINE_1 = "معمل صدارة"
CLINIC_LINE_2 = "للتحاليل الطبية الكيميائية"

# ── font & assets ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(os.path.dirname(_HERE))   

_FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "utils", "Cairo.ttf"),
    os.path.join(_BASE_DIR, "static", "fonts", "Cairo.ttf"),
    os.path.join(_HERE, "Cairo.ttf"),
]
_FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), _FONT_CANDIDATES[0])

_FONT_GLYPHS: set = set()


@functools.lru_cache(maxsize=1)
def _register_font() -> str:
    """
    Register the Cairo font once per process.
    Raises if the font is missing: the fallback font has no Arabic glyphs,
    so the customer would receive a ticket full of empty boxes.
    """
    global _FONT_GLYPHS
    if not os.path.exists(_FONT_PATH):
        logger.error("Cairo font not found at %s", _FONT_PATH)
        raise FileNotFoundError(f"Cairo font not found: {_FONT_PATH}")

    font = TTFont("Cairo", _FONT_PATH)
    pdfmetrics.registerFont(font)
    try:
        _FONT_GLYPHS = set(font.face.charToGlyph.keys())
    except Exception:
        logger.warning("Could not read Cairo glyph map", exc_info=True)
        _FONT_GLYPHS = set()
    return "Cairo"


@functools.lru_cache(maxsize=1)
def _find_logo() -> str | None:
    candidates = [
        os.path.join(_BASE_DIR, "static", "images", "sadara_logo.jpg"),
        os.path.join(_BASE_DIR, "utils", "logo.jpeg"),
        os.path.join(_BASE_DIR, "utils", "logo.jpg"),
        os.path.join(_BASE_DIR, "utils", "logo.png"),
        os.path.join(_HERE, "logo.jpeg"),
        os.path.join(_HERE, "logo.jpg"),
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


# ── Text helpers ──────────────────────────────────────────────────────────────
def _fix_missing_glyphs(text: str) -> str:
    if not _FONT_GLYPHS:
        return text
    result = []
    for ch in text:
        if ord(ch) in _FONT_GLYPHS or ch in (" ", "\u00A0"):
            result.append(ch)
            continue
        fallback = unicodedata.normalize("NFKC", ch)
        if fallback and all(ord(c) in _FONT_GLYPHS for c in fallback):
            result.append(fallback)
        else:
            result.append(ch)
    return "".join(result)


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in (text or ""))


def _ar(text) -> str:
    """
    Shape and reorder Arabic text for reportlab, then XML-escape it
    (Paragraph parses its input as markup, and this text comes from customers).
    """
    if not text:
        return ""
    str_text = str(text).strip()
    if not str_text:
        return ""
    try:
        displayed = get_display(arabic_reshaper.reshape(str_text))
        displayed = _fix_missing_glyphs(displayed)
    except Exception:
        displayed = str_text
    return "\u00A0" + escape(displayed) + "\u00A0"


def _wrap_text(text: str, font: str, size: int, max_width: float) -> List[str]:
    """
    Split logical-order text into lines that fit max_width.
    Arabic must be wrapped BEFORE bidi reordering: reordering a whole long string
    and letting Paragraph wrap it puts the end of the sentence on the first line.
    """
    lines: List[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and pdfmetrics.stringWidth(candidate, font, size) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _ps(name_: str, font: str, size: int, color=DARK, align: int = 0) -> ParagraphStyle:
    return ParagraphStyle(
        name_,
        fontName=font,
        fontSize=size,
        textColor=color,
        alignment=align,
        leading=size * 1.45,
    )


def _issued_now() -> str:
    """Issue time in Cairo local time (falls back to UTC if tz data is missing)."""
    try:
        return datetime.now(ZoneInfo("Africa/Cairo")).strftime("%B %d, %Y %H:%M")
    except Exception:
        return datetime.now(timezone.utc).strftime("%B %d, %Y %H:%M UTC")


# ── PDF Component Builders ────────────────────────────────────────────────────
def _build_brand_strip(usable_w: float) -> Table:
    strip = Table(
        [["", "", ""]],
        colWidths=[usable_w * 0.45, usable_w * 0.35, usable_w * 0.20],
        rowHeights=[3 * mm],
    )
    strip.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), BLUE),
            ("BACKGROUND", (1, 0), (1, 0), INDIGO),
            ("BACKGROUND", (2, 0), (2, 0), GREEN),
        ])
    )
    return strip


def _build_header(usable_w: float, font: str) -> Table:
    logo_path = _find_logo()
    logo_h = 32 * mm
    logo_w = 40 * mm
    if logo_path:
        logo = Image(logo_path, width=logo_w, height=logo_h, kind="proportional")
        logo.hAlign = "LEFT"
    else:
        logo = Paragraph("", _ps("empty", font, 1))

    title_table = Table(
        [
            [Paragraph(_ar(CLINIC_LINE_1), _ps("clinic1", font, 24, INDIGO, align=2))],
            [Paragraph(_ar(CLINIC_LINE_2), _ps("clinic2", font, 12, PURPLE, align=2))],
        ],
        colWidths=[usable_w - logo_w - 5 * mm],
    )
    title_table.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ])
    )

    header = Table(
        [[logo, title_table]], colWidths=[logo_w + 5 * mm, usable_w - logo_w - 5 * mm]
    )
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return header


def _build_title_and_reference(usable_w: float, reference_id: str, font: str) -> List[Any]:
    ttl = Table(
        [[
            Paragraph("Booking Confirmation", _ps("en", font, 11, WHITE, align=0)),
            Paragraph(_ar("تأكيد حجز موعد التحليل"), _ps("ar", font, 12, WHITE, align=2)),
        ]],
        colWidths=[usable_w / 2, usable_w / 2],
    )
    ttl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), INDIGO),
            ("LINEBELOW", (0, 0), (-1, -1), 2.5, GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )

    ref = Table(
        [[
            Paragraph(
                f"Reference: {escape(str(reference_id))}",
                _ps("ref", font, 10, INDIGO, align=1),
            )
        ]],
        colWidths=[usable_w],
    )
    ref.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    return [ttl, ref]


def _build_info_table(usable_w: float, fields: list, font: str) -> Table:
    label_col_w = 78 * mm
    val_col_w = usable_w - label_col_w
    val_text_w = val_col_w - 14  # minus left (8) and right (6) cell padding

    rows = []
    for i, (en_lbl, ar_lbl, val) in enumerate(fields):
        lbl_cell = Paragraph(
            f"{en_lbl} / {_ar(ar_lbl)}", _ps(f"l_{i}", font, 9, MUTED, align=0)
        )

        val_str = str(val or "—")
        if _is_arabic(val_str):
            lines = _wrap_text(val_str, font, 10, val_text_w)
            val_text = "<br/>".join(_ar(line) for line in lines)
            val_align = 2
        else:
            val_text = escape(val_str).replace("\n", "<br/>")
            val_align = 0

        val_cell = Paragraph(val_text, _ps(f"v_{i}", font, 10, DARK, align=val_align))
        rows.append([lbl_cell, val_cell])

    info = Table(rows, colWidths=[label_col_w, val_col_w])
    info.setStyle(
        TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT_ROW, WHITE]),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
            ("LINEBELOW", (0, -1), (-1, -1), 1.5, BLUE),
            ("LINEBEFORE", (0, 0), (0, -1), 3, GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    return info


def _build_footer(usable_w: float, font: str) -> List[Any]:
    footer_table = Table(
        [[
            Paragraph(f"Issued: {_issued_now()}", _ps("fl", font, 8, MUTED, align=0)),
            Paragraph(_ar("احتفظ بهذه البطاقة للمراجعة"), _ps("fr", font, 8, PURPLE, align=2)),
        ]],
        colWidths=[usable_w / 2, usable_w / 2],
    )
    footer_table.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    return [
        HRFlowable(width="100%", thickness=1, color=GREEN),
        Spacer(1, 3 * mm),
        footer_table,
    ]


# ── PDF Generation ────────────────────────────────────────────────────────────
def generate_booking_pdf(
    name: str,
    phone: str,
    date: str,
    details: str,
    reference_id: str,
    time: str,
    address: str,
) -> bytes:
    """Generates a styled A4 PDF confirmation ticket for a patient lab booking."""
    font = _register_font()
    buffer = io.BytesIO()

    margin = 15 * mm
    usable_w = A4[0] - (margin * 2)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    fields = [
        ("Patient Name", "اسم المريض", name),
        ("Phone", "رقم الهاتف", phone),
        ("Appointment Date", "تاريخ الموعد", date),
        ("Required Analysis", "التحاليل المطلوبة", details),
        ("Address", "العنوان", address),
        ("Time", "الوقت", time),
    ]

    title_bar, reference_badge = _build_title_and_reference(usable_w, reference_id, font)

    story = [
        _build_brand_strip(usable_w),
        Spacer(1, 4 * mm),
        _build_header(usable_w, font),
        Spacer(1, 4 * mm),
        title_bar,
        reference_badge,
        Spacer(1, 6 * mm),
        _build_info_table(usable_w, fields, font),
        Spacer(1, 8 * mm),
        *_build_footer(usable_w, font),
    ]

    doc.build(story)
    return buffer.getvalue()


def generate_booking_img(
    name: str,
    phone: str,
    date: str,
    details: str,
    reference_id: str,
    time: str,
    address: str,
    dpi: int = 200,
) -> bytes:
    """Generates the booking card directly as a PNG image byte string."""
    try:
        pdf_bytes = generate_booking_pdf(
            name=name, phone=phone, date=date, details=details,
            reference_id=reference_id, time=time, address=address,
        )

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            zoom = dpi / 72
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return pix.tobytes("png")

    except Exception:
        logger.exception("[generate_booking_img] Failed")
        raise