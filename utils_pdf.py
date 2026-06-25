# utils_pdf.py
#
# Generates a branded PDF appointment confirmation/receipt. The file is
# written to a temp dir and the path is returned so the caller
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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

PDF_OUTPUT_DIR = os.getenv("PDF_OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "appointment_pdfs"))

_BRAND = colors.HexColor("#4B2E83")
_BRAND_LIGHT = colors.HexColor("#F4F1FA")
_INK = colors.HexColor("#1F2937")
_MUTED = colors.HexColor("#6B7280")
_LINE = colors.HexColor("#E5E7EB")
_STATUS_COLORS = {
    "Confirmed": colors.HexColor("#15803D"),
    "Scheduled": colors.HexColor("#2563EB"),
    "Rescheduled": colors.HexColor("#B45309"),
    "Cancelled": colors.HexColor("#B91C1C"),
}


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


def generate_appointment_pdf(appointment, bot, doctor=None, procedure=None, sessions=None) -> str:
    """
    appointment: db.Appointment instance (the confirmed/first-session record)
    bot: db.WhatsappBot instance
    doctor: optional db.Doctor instance
    procedure: optional db.Procedure instance — when sessions_required > 1 the
               PDF switches to the package layout (session schedule + total)
    sessions: optional full list of db.Appointment rows (parent + auto-projected
              future sessions, from db.get_treatment_schedule) — when given,
              renders a Treatment Schedule table instead of a single date/time row
    Returns the absolute file path of the generated PDF.
    """
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(PDF_OUTPUT_DIR, f"appointment_{appointment.id}.pdf")
    is_package = bool(procedure is not None and procedure.sessions_required and procedure.sessions_required > 1)

    doc = SimpleDocTemplate(
        file_path, pagesize=A4,
        topMargin=0, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    business_name = bot.business_name or bot.name

    header_style = ParagraphStyle("Header", fontName="Helvetica-Bold", fontSize=22, textColor=colors.white, leading=26)
    header_sub_style = ParagraphStyle("HeaderSub", fontName="Helvetica", fontSize=11, textColor=colors.HexColor("#E5DEF5"), leading=14)
    section_style = ParagraphStyle("Section", fontName="Helvetica-Bold", fontSize=11, textColor=_BRAND, spaceBefore=14, spaceAfter=6)
    label_style = ParagraphStyle("Label", fontName="Helvetica", fontSize=9.5, textColor=_MUTED)
    value_style = ParagraphStyle("Value", fontName="Helvetica-Bold", fontSize=10.5, textColor=_INK)
    footer_style = ParagraphStyle("Footer", fontName="Helvetica", fontSize=8.5, textColor=_MUTED)
    status_color = _STATUS_COLORS.get(appointment.status, _INK)
    status_style = ParagraphStyle("Status", fontName="Helvetica-Bold", fontSize=10, textColor=status_color, alignment=TA_RIGHT)

    # ── Header band ──────────────────────────────────────────────────────
    header_table = Table(
        [[Paragraph(business_name, header_style)],
         [Paragraph("Appointment Confirmation" if not is_package else "Treatment Package Confirmation", header_sub_style)]],
        colWidths=[doc.width],
    )
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 20 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20 * mm),
        ("TOPPADDING", (0, 0), (0, 0), 16 * mm),
        ("BOTTOMPADDING", (0, -1), (0, -1), 14 * mm),
        ("TOPPADDING", (0, 1), (0, 1), 2),
    ]))

    elements = [header_table, Spacer(1, 16)]

    # ── At-a-glance info grid ────────────────────────────────────────────
    def info_pair(label, value):
        return [Paragraph(label, label_style), Paragraph(str(value), value_style)]

    left_rows = [info_pair("Appointment ID", f"#{appointment.id}")]
    if doctor is not None or appointment.department:
        left_rows.append(info_pair("Department", (appointment.department or (doctor.department if doctor else "") or "-").title()))
    if doctor is not None:
        left_rows.append(info_pair("Doctor", f"Dr. {doctor.name}"))
    left_rows.append(info_pair("Service", appointment.service or "-"))

    right_rows = [[Paragraph("Status", label_style), Paragraph(appointment.status, status_style)]]
    if not is_package:
        right_rows.append(info_pair("Date", _pretty_date(appointment.appointment_date)))
        right_rows.append(info_pair("Time", _pretty_time(appointment.appointment_time)))
    else:
        right_rows.append(info_pair("Sessions", f"{procedure.sessions_required} sessions"))
    if appointment.consultation_fee:
        fee_label = "Package Total" if is_package else "Consultation Fee"
        right_rows.append(info_pair(fee_label, f"${appointment.consultation_fee:,.0f}"))

    max_rows = max(len(left_rows), len(right_rows))
    while len(left_rows) < max_rows:
        left_rows.append(["", ""])
    while len(right_rows) < max_rows:
        right_rows.append(["", ""])

    grid_data = []
    for l, r in zip(left_rows, right_rows):
        grid_data.append([l[0], l[1], r[0], r[1]])
    grid = Table(grid_data, colWidths=[35 * mm, 55 * mm, 35 * mm, 45 * mm])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, _LINE),
    ]))
    elements.append(grid)

    # ── Treatment Schedule (package bookings) ───────────────────────────
    if is_package and sessions:
        elements.append(Paragraph("Treatment Schedule", section_style))
        schedule_rows = [["Session", "Date", "Time", "Status"]]
        for s in sessions:
            schedule_rows.append([
                str(s.session_number), _pretty_date(s.appointment_date), _pretty_time(s.appointment_time), s.status,
            ])
        schedule_table = Table(schedule_rows, colWidths=[25 * mm, 55 * mm, 35 * mm, 55 * mm])
        schedule_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _BRAND_LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.5, _LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ]))
        elements.append(schedule_table)
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            "Future sessions are auto-scheduled — our team will confirm or adjust each one closer to the date.",
            footer_style,
        ))

    # ── Patient details ──────────────────────────────────────────────────
    elements.append(Paragraph("Patient Details", section_style))
    patient_rows = [
        info_pair("Name", appointment.customer_name or "-"),
        info_pair("Phone", appointment.customer_phone),
    ]
    if appointment.notes:
        patient_rows.append(info_pair("Notes", appointment.notes))
    patient_table = Table(patient_rows, colWidths=[35 * mm, 135 * mm])
    patient_table.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(patient_table)

    elements.append(Spacer(1, 16))
    elements.append(HRFlowable(width="100%", color=_LINE, thickness=0.75))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        "Please keep this document for your records. "
        "Reply to this WhatsApp chat if you need to cancel or reschedule.",
        footer_style,
    ))

    doc.build(elements)
    return file_path
