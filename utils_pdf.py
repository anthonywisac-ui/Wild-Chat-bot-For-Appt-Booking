# utils_pdf.py
#
# Generates a branded PDF appointment confirmation/receipt, mirroring the
# "PDF Export" feature from the reference Streamlit appointment agent.
# The file is written to a temp dir and the path is returned so the caller
# (bots/appointment/flow.py) can send it as a WhatsApp document.

from __future__ import annotations

import os
import tempfile

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

PDF_OUTPUT_DIR = os.getenv("PDF_OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "appointment_pdfs"))


def generate_appointment_pdf(appointment, bot, doctor=None, procedure=None) -> str:
    """
    appointment: db.Appointment instance
    bot: db.WhatsappBot instance
    doctor: optional db.Doctor instance (adds department/doctor name/fee rows)
    procedure: optional db.Procedure instance (adds a sessions-required row for packages)
    Returns the absolute file path of the generated PDF.
    """
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(PDF_OUTPUT_DIR, f"appointment_{appointment.id}.pdf")

    doc = SimpleDocTemplate(
        file_path, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"], textColor=colors.HexColor("#4B2E83"), fontSize=20,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"], textColor=colors.grey, fontSize=10, spaceAfter=12,
    )
    status_color = {
        "Confirmed": colors.HexColor("#1f9d55"),
        "Rescheduled": colors.HexColor("#d97706"),
        "Cancelled": colors.HexColor("#dc2626"),
    }.get(appointment.status, colors.black)

    business_name = bot.business_name or bot.name

    elements = [
        Paragraph(f"{business_name}", title_style),
        Paragraph("Appointment Confirmation", subtitle_style),
        Spacer(1, 8),
    ]

    rows = [
        ["Appointment ID", f"#{appointment.id}"],
        ["Status", appointment.status],
    ]
    if doctor is not None:
        rows.append(["Department", (appointment.department or doctor.department or "-").title()])
        rows.append(["Doctor", f"Dr. {doctor.name}"])
    elif appointment.department:
        rows.append(["Department", appointment.department.title()])

    rows.append(["Service", appointment.service or "-"])
    if procedure is not None and procedure.sessions_required and procedure.sessions_required > 1:
        rows.append(["Sessions", f"{procedure.sessions_required} sessions (package)"])
    rows.append(["Date", appointment.appointment_date or "-"])
    rows.append(["Time", appointment.appointment_time or "-"])

    if appointment.consultation_fee:
        fee_label = "Package Total" if (procedure is not None and procedure.sessions_required and procedure.sessions_required > 1) else "Consultation Fee"
        rows.append([fee_label, f"${appointment.consultation_fee:.0f}"])

    rows.append(["Customer", appointment.customer_name or appointment.customer_phone])
    rows.append(["Phone", appointment.customer_phone])
    rows.append(["Notes", appointment.notes or "-"])
    table = Table(rows, colWidths=[140, 320])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (1, 1), (1, 1), status_color),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9fafb")),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        "Please keep this document for your records. "
        "Reply to this WhatsApp chat if you need to cancel or reschedule.",
        styles["Normal"],
    ))

    doc.build(elements)
    return file_path
