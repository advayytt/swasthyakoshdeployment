"""Printable case sheet.

Government OPDs still run on paper at the point of handover. This produces the
sheet the practitioner can sign and clip to the file, with the provenance line
printed on it so the paper copy carries the same honesty as the screen.
"""
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .summary import as_sections

INK = colors.HexColor("#101A2E")
VETIVER = colors.HexColor("#1F3D33")
HALDI = colors.HexColor("#8A6314")
ALERT = colors.HexColor("#C0362C")
MUTED = colors.HexColor("#5A6B64")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=16,
                                textColor=INK, alignment=TA_LEFT,
                                spaceAfter=2, fontName="Helvetica-Bold"),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=8.5,
                              textColor=MUTED, spaceAfter=8),
        "h": ParagraphStyle("h", parent=base["Normal"], fontSize=9.5,
                            textColor=VETIVER, fontName="Helvetica-Bold",
                            spaceBefore=8, spaceAfter=2),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=10,
                               leading=14, textColor=INK),
        "flag": ParagraphStyle("f", parent=base["Normal"], fontSize=10,
                               leading=14, textColor=ALERT,
                               fontName="Helvetica-Bold"),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=8,
                                textColor=MUTED, leading=11),
    }


def build_case_pdf(buffer, case, patient, doctor, uploads):
    st = _styles()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm,
                            title=f"Case sheet {case.id}")
    story = []

    story.append(Paragraph("Pre-consultation case sheet", st["title"]))
    story.append(Paragraph(
        f"Swasthya Kosh &nbsp;|&nbsp; intake completed "
        f"{case.submitted_at.strftime('%d %b %Y, %H:%M') if case.submitted_at else 'in progress'}"
        f" &nbsp;|&nbsp; {case.duration_minutes or '-'} minutes"
        f" &nbsp;|&nbsp; language: {case.language}", st["sub"]))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CBD4C8")))
    story.append(Spacer(1, 6))

    meta = [
        ["Patient", patient.name, "ABHA address", patient.abha_address],
        ["Age / sex", f"{patient.age or '-'} / {patient.sex or '-'}",
         "Practitioner", f"{doctor.name} ({doctor.hpr_id})" if doctor else "-"],
    ]
    table = Table(meta, colWidths=[24 * mm, 55 * mm, 26 * mm, 55 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))

    if case.red_flags:
        story.append(Paragraph("Triage flags", st["h"]))
        for flag in case.red_flags:
            style = st["flag"] if flag["level"] == "emergency" else st["body"]
            story.append(Paragraph(
                f"[{flag['level'].upper()}] {flag['label']} — {flag['reason']}. "
                f"{flag['action']}", style))
        story.append(Spacer(1, 4))

    if case.namaste_code:
        story.append(Paragraph("Coding", st["h"]))
        story.append(Paragraph(
            f"NAMASTE {case.namaste_code} — {case.namaste_term} &nbsp;|&nbsp; "
            f"ICD-11 TM2 {case.icd11_tm2_code or '-'} &nbsp;|&nbsp; "
            f"ICD-11 Biomedicine {case.icd11_biomed_code or '-'}", st["body"]))

    for section in as_sections(case.summary_text):
        story.append(Paragraph(section["heading"], st["h"]))
        bullets = section.get("bullets") or []
        if bullets:
            for bullet in bullets:
                story.append(Paragraph(f"&#8226;&nbsp; {bullet}", st["body"]))
        else:
            story.append(Paragraph("Not elicited.", st["body"]))

    if case.dashavidha:
        story.append(Paragraph("Practitioner assessment", st["h"]))
        for key, val in case.dashavidha.items():
            shown = ", ".join(val) if isinstance(val, list) else val
            story.append(Paragraph(f"{key}: {shown}", st["body"]))

    docs = [u for u in uploads if u.status != "rejected"]
    if docs:
        story.append(Paragraph("Documents on file", st["h"]))
        rows = [["Date", "Type", "Contents", "Verified"]]
        for up in docs:
            payload = up.extracted or {}
            contents = "; ".join(filter(None, [
                ", ".join(d.get("text", "") for d in payload.get("diagnoses", [])),
                ", ".join(m.get("name", "") for m in payload.get("medications", [])),
                ", ".join(f"{i.get('name')} {i.get('value')}"
                          for i in payload.get("investigations", [])),
            ])) or "nothing legible"
            rows.append([
                up.document_date.strftime("%d %b %Y") if up.document_date else "undated",
                up.doc_type.replace("_", " "),
                Paragraph(contents[:240], st["small"]),
                "yes" if up.status == "confirmed" else "pending",
            ])
        t = Table(rows, colWidths=[22 * mm, 26 * mm, 96 * mm, 18 * mm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#CBD4C8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CBD4C8")))
    provenance = {
        "ai": "drafted by a language model from the patient's own answers",
        "gemini": "drafted by a language model from the patient's own answers",
        "groq": "drafted by a language model from the patient's own answers",
        "openrouter": "drafted by a language model from the patient's own answers",
        "rules": "assembled by the offline rules engine from the patient's answers",
        "edited": "edited by the practitioner",
    }.get(case.summary_source, case.summary_source)
    story.append(Paragraph(
        f"This history was {provenance}. It is a record of what the patient "
        f"reported. It contains no diagnosis, differential or treatment advice. "
        f"Status: {case.status.replace('_', ' ')}"
        + (f", confirmed by {doctor.name} on "
           f"{case.verified_at.strftime('%d %b %Y, %H:%M')}"
           if case.verified_at and doctor else "") + ".", st["small"]))

    doc.build(story)
    return buffer
