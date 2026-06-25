# utils_pdf.py
#
# Generates a branded PDF appointment confirmation/receipt — an elegant,
# editorial-style layout (cream background, gold accents, serif typography)
# matching the clinic's reference design. The file is written to a temp dir
# and the path is returned so the caller
# (bots/appointment/services/conversation_engine.py) can send it as a
# WhatsApp document.

from __future__ import annotations

import os
import tempfile
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.graphics.shapes import Drawing, Circle, String

PDF_OUTPUT_DIR = os.getenv("PDF_OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "appointment_pdfs"))

_CREAM = colors.HexColor("#FBF9F5")
_GOLD = colors.HexColor("#B8935A")
_INK = colors.HexColor("#2B2B28")
_MUTED = colors.HexColor("#9C968F")
_LINE = colors.HexColor("#E3DDD2")
_BOX_BG = colors.HexColor("#F0EDE6")

_STATUS_THEME = {
    "Confirmed": (colors.HexColor("#DCE8DC"), colors.HexColor("#3F6B4A")),
    "Scheduled": (colors.HexColor("#DCE5EF"), colors.HexColor("#3A5A80")),
    "Rescheduled": (colors.HexColor("#F2E6D3"), colors.HexColor("#9C6B1F")),
    "Cancelled": (colors.HexColor("#F2DCDC"), colors.HexColor("#8A3A3A")),
}


def _spaced(text: str) -> str:
    """Approximates letter-tracked small caps for short eyebrow/section labels.
    Uses non-breaking spaces since plain spaces get collapsed by reportlab's
    Paragraph text layout and the tracking effect disappears entirely."""
    nbsp = chr(160)
    words = text.upper().split()
    tracked_words = [nbsp.join(w) for w in words]
    return (nbsp * 3).join(tracked_words)


def _pretty_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except Exception:
        return date_str or "-"


def _pretty_time(time_str: str) -> str:
    try:
        return datetime.strptime(time_str, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str or "-"


def _monogram(letter: str, size: float = 30) -> Drawing:
    d = Drawing(size, size)
    d.add(Circle(size / 2, size / 2, size / 2 - 1.5, strokeColor=_GOLD, fillColor=None, strokeWidth=1))
    d.add(String(size / 2, size / 2 - size * 0.16, letter.upper(), fontName="Times-Roman",
                  fontSize=size * 0.42, fillColor=_GOLD, textAnchor="middle"))
    return d


def _status_pill(status: str) -> Table:
    bg, fg = _STATUS_THEME.get(status, (_BOX_BG, _INK))
    style = ParagraphStyle("Pill", fontName="Helvetica-Bold", fontSize=8, textColor=fg, alignment=TA_CENTER)
    pill = Table([[Paragraph(f"●  {status.upper()}", style)]], colWidths=[28 * mm])
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return pill


def _draw_page_frame(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(_CREAM)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    margin = 6 * mm
    canvas.setStrokeColor(_GOLD)
    canvas.setLineWidth(1.1)
    canvas.rect(margin, margin, width - 2 * margin, height - 2 * margin, fill=0, stroke=1)
    canvas.restoreState()


def generate_appointment_pdf(appointment, bot, doctor=None, procedure=None, sessions=None) -> str:
    """
    appointment: db.Appointment instance (the confirmed/first-session record)
    bot: db.WhatsappBot instance
    doctor: optional db.Doctor instance
    procedure: optional db.Procedure instance — when sessions_required > 1 the
               PDF adds a Treatment Schedule table below the main details
    sessions: optional full list of db.Appointment rows (parent + auto-projected
              future sessions, from db.get_treatment_schedule)
    Returns the absolute file path of the generated PDF.
    """
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(PDF_OUTPUT_DIR, f"appointment_{appointment.id}.pdf")
    is_package = bool(procedure is not None and procedure.sessions_required and procedure.sessions_required > 1)
    business_name = bot.business_name or bot.name

    doc = SimpleDocTemplate(
        file_path, pagesize=A4,
        topMargin=16 * mm, bottomMargin=16 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
    )

    name_style = ParagraphStyle("Name", fontName="Times-Bold", fontSize=15, textColor=_INK, leading=18)
    tagline_style = ParagraphStyle("Tagline", fontName="Helvetica", fontSize=7, textColor=_MUTED, leading=10)
    contact_style = ParagraphStyle("Contact", fontName="Helvetica", fontSize=8, textColor=_MUTED, leading=11, spaceBefore=2)
    meta_label_style = ParagraphStyle("MetaLabel", fontName="Helvetica", fontSize=7, textColor=_MUTED, alignment=TA_RIGHT, leading=9)
    meta_value_style = ParagraphStyle("MetaValue", fontName="Helvetica-Bold", fontSize=9.5, textColor=_INK, alignment=TA_RIGHT, leading=12, spaceAfter=4)
    eyebrow_style = ParagraphStyle("Eyebrow", fontName="Helvetica", fontSize=8, textColor=_GOLD, leading=11)
    heading_style = ParagraphStyle("Heading", fontName="Times-Roman", fontSize=26, textColor=_INK, leading=30)
    section_style = ParagraphStyle("Section", fontName="Helvetica", fontSize=8, textColor=_MUTED, spaceBefore=14, spaceAfter=8, leading=11)
    label_style = ParagraphStyle("Label", fontName="Helvetica", fontSize=7, textColor=_MUTED, leading=10)
    value_style = ParagraphStyle("Value", fontName="Times-Roman", fontSize=12, textColor=_INK, leading=16, spaceAfter=6)
    box_label_style = ParagraphStyle("BoxLabel", fontName="Helvetica", fontSize=7, textColor=_MUTED, leading=10)
    box_value_style = ParagraphStyle("BoxValue", fontName="Times-Bold", fontSize=15, textColor=_INK, leading=18)
    italic_style = ParagraphStyle("Italic", fontName="Times-Italic", fontSize=9.5, textColor=_MUTED, leading=13)
    footer_style = ParagraphStyle("Footer", fontName="Helvetica", fontSize=7.5, textColor=_MUTED, alignment=TA_CENTER, leading=11)

    elements = []

    # ── Header: monogram + clinic name + contact, date/doc-id right-aligned ──
    monogram = _monogram(business_name[:1] or "C")
    left_block = Table(
        [[monogram, Paragraph(business_name, name_style)],
         ["", Paragraph(_spaced("Esthetic & Dental Studio"), tagline_style)]],
        colWidths=[12 * mm, 90 * mm],
    )
    left_block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (1, 0), (1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("SPAN", (0, 0), (0, 1)),
    ]))

    contact_line = "For any questions, simply reply to this WhatsApp conversation."
    right_block_data = [
        [Paragraph(_spaced("Date of Issue"), meta_label_style)],
        [Paragraph(datetime.utcnow().strftime("%d %B %Y"), meta_value_style)],
        [Paragraph(_spaced("Document ID"), meta_label_style)],
        [Paragraph(f"APT-{datetime.utcnow().year}-{appointment.id:04d}", meta_value_style)],
    ]
    right_block = Table(right_block_data, colWidths=[55 * mm])
    right_block.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
    ]))

    header = Table([[left_block, right_block]], colWidths=[120 * mm, 58 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(header)
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(contact_line, contact_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", color=_LINE, thickness=0.8))
    elements.append(Spacer(1, 12))

    # ── Title row: eyebrow + "Confirmation" heading, status pill on the right ─
    title_left = [
        Paragraph(_spaced("Appointment"), eyebrow_style),
        Paragraph("Treatment Package Confirmation" if is_package else "Confirmation", heading_style),
    ]
    title_table = Table([[title_left, _status_pill(appointment.status)]], colWidths=[140 * mm, 38 * mm])
    title_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    elements.append(title_table)
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width="100%", color=_LINE, thickness=0.8))
    elements.append(Spacer(1, 4))

    def two_col(label_l, value_l, label_r, value_r):
        data = [[Paragraph(_spaced(label_l), label_style), Paragraph(_spaced(label_r), label_style)],
                [Paragraph(str(value_l), value_style), Paragraph(str(value_r), value_style)]]
        t = Table(data, colWidths=[89 * mm, 89 * mm])
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        return t

    elements.append(Paragraph(_spaced("Client Information"), section_style))
    elements.append(two_col("Client Name", appointment.customer_name or "-", "Contact", appointment.customer_phone))

    elements.append(Paragraph(_spaced("Treatment Details"), section_style))
    department = (appointment.department or (doctor.department if doctor else "") or "-").title()
    elements.append(two_col("Department", department, "Service", appointment.service or "-"))
    if not is_package:
        elements.append(two_col("Date", _pretty_date(appointment.appointment_date), "Time", _pretty_time(appointment.appointment_time)))
    else:
        elements.append(two_col("First Session", _pretty_date(appointment.appointment_date), "Sessions", f"{procedure.sessions_required} total"))
    if doctor is not None:
        elements.append(two_col("Doctor", f"Dr. {doctor.name}", "", ""))

    elements.append(Spacer(1, 8))

    # ── Highlight box: fee | appointment number ─────────────────────────────
    fee = appointment.consultation_fee or 0.0
    fee_label = "Package Total" if is_package else "Consultation Fee"
    box_data = [[
        Table([[Paragraph(_spaced(fee_label), box_label_style)], [Paragraph(f"${fee:,.0f}", box_value_style)]],
              style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)])),
        "",
        Table([[Paragraph(_spaced("Appointment"), box_label_style)], [Paragraph(f"No. {appointment.id}", box_value_style)]],
              style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)])),
    ]]
    box = Table(box_data, colWidths=[85 * mm, 8 * mm, 85 * mm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BOX_BG),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("LINEAFTER", (0, 0), (0, 0), 0.75, _LINE),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("LEFTPADDING", (2, 0), (2, 0), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(box)

    # ── Treatment Schedule (package bookings) ───────────────────────────────
    if is_package and sessions:
        elements.append(Paragraph(_spaced("Treatment Schedule"), section_style))
        schedule_header_style = ParagraphStyle("SchedHead", fontName="Helvetica", fontSize=7, textColor=_MUTED, leading=10)
        schedule_cell_style = ParagraphStyle("SchedCell", fontName="Helvetica", fontSize=9.5, textColor=_INK, leading=13)
        sched_rows = [[Paragraph(_spaced(h), schedule_header_style) for h in ("Session", "Date", "Time", "Status")]]
        for s in sessions:
            sched_rows.append([
                Paragraph(str(s.session_number), schedule_cell_style),
                Paragraph(_pretty_date(s.appointment_date), schedule_cell_style),
                Paragraph(_pretty_time(s.appointment_time), schedule_cell_style),
                Paragraph(s.status, schedule_cell_style),
            ])
        sched_table = Table(sched_rows, colWidths=[20 * mm, 55 * mm, 35 * mm, 68 * mm])
        sched_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, _GOLD),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, _LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(sched_table)
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            "Future sessions are auto-scheduled — our team will confirm or adjust each one closer to the date.",
            italic_style,
        ))

    # ── Notes ────────────────────────────────────────────────────────────────
    elements.append(Paragraph(_spaced("Notes"), section_style))
    elements.append(Paragraph(appointment.notes or "No additional notes for this appointment.", italic_style))

    elements.append(Spacer(1, 18))
    elements.append(HRFlowable(width="100%", color=_LINE, thickness=0.8))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        "Please retain this document for your records. To cancel or reschedule, kindly notify us "
        "at least 24 hours in advance via your WhatsApp conversation.",
        footer_style,
    ))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(f"care@{(business_name or 'clinic').lower().replace(' ', '')}.com", footer_style))

    doc.build(elements, onFirstPage=_draw_page_frame, onLaterPages=_draw_page_frame)
    return file_path
