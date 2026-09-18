"""Module C - the physician-ready case sheet.

Two paths produce the same shape of output:
  * the model writes the narrative  (source = gemini/groq/openrouter)
  * a deterministic template writes it from the same answers (source = rules)

The physician sees which one they are reading, always. The summary is a draft
to accept, amend or reject. It contains no diagnosis, no differential and no
treatment.
"""
from __future__ import annotations

from . import ai
from .intake import SECTION_LABELS, structured_history

SYSTEM = (
    "You are a clinical documentation assistant in an AYUSH outpatient "
    "department in India. You convert a patient's own answers into a concise, "
    "physician-readable history. You never diagnose, never suggest a "
    "differential, never recommend treatment or investigations. You write only "
    "what the patient reported. If a section has no data you write 'Not "
    "elicited'. Plain clinical English, no adjectives, no reassurance."
)

TEMPLATE = """Write the case sheet for this patient using only the data below.

Patient: {name}, {age} year old {sex}. Interview language: {language}.
Chief complaint tag: {complaint}

Answers given:
{answers}

Documents on file:
{documents}

Produce exactly these sections, each on its own line, in this order, with the
heading followed by a colon, then a line break, then the section's content as
short bullet points (each bullet starting with "- "):

Chief complaint
History of present illness
Past medical and surgical history
Drug and allergy history
Family history
Personal history
Review of systems
Prior investigations
Dashavidha Pariksha

Rules:
- Every section is bullet points, no exceptions — including History of
  present illness: break it into separate bullets (onset, severity, timing,
  character, associated features), not one paragraph of prose. A physician
  scanning this in ten seconds should be able to pick out each fact without
  reading full sentences.
- Each bullet is a short clinical fragment, not a full sentence — drop
  restating the question, just state the finding (e.g. "- Onset: a few
  weeks ago", not "- The patient reports the onset was a few weeks ago
  when asked how long they had this").
- Under Dashavidha Pariksha, one bullet per parameter present in the data;
  mark practitioner-assessed ones as 'to be assessed on examination'.
- A section with nothing recorded gets a single bullet: "- Not elicited."
- Do not add any section, disclaimer or commentary beyond these nine
  headings and their bullets.
"""

ORDER = ["chief_complaint", "hpi", "past", "drug_allergy", "family",
         "personal", "ros", "dashavidha"]


def generate(case, patient, uploads):
    grouped = structured_history(case)
    answer_lines = _answer_lines(grouped)
    doc_lines = _document_lines(uploads)

    result = ai.generate_text(SYSTEM, TEMPLATE.format(
        name=patient.name,
        age=patient.age or "unknown",
        sex=patient.sex or "unspecified",
        language=case.language,
        complaint=case.chief_complaint or "not selected",
        answers=answer_lines or "None recorded.",
        documents=doc_lines or "None uploaded.",
    ))

    if result.ok:
        return result.text.strip(), result.source
    return _fallback(case, patient, grouped, uploads), "rules"


def _answer_lines(grouped):
    lines = []
    for section in ORDER:
        for item in grouped.get(section, []):
            slot = f" [{item['socrates_slot']}]" if item["socrates_slot"] else ""
            param = f" [{item['dashavidha_param']}]" if item["dashavidha_param"] else ""
            src = "spoken" if item["source"] == "voice" else "tapped"
            lines.append(
                f"- ({SECTION_LABELS.get(section, section)}{slot}{param}) "
                f"{item['prompt']} -> {item['label']} ({src})"
            )
    return "\n".join(lines)


def _document_lines(uploads):
    lines = []
    for up in uploads:
        if up.status == "rejected":
            continue
        payload = up.extracted or {}
        date = up.document_date.strftime("%d %b %Y") if up.document_date else "undated"
        meds = ", ".join(m.get("name", "") for m in payload.get("medications", []))
        labs = ", ".join(
            f"{i.get('name')} {i.get('value')}{i.get('unit', '')}"
            f"{' [ABNORMAL]' if i.get('status') in ('high', 'low') else ''}"
            for i in payload.get("investigations", []))
        dx = ", ".join(d.get("text", "") for d in payload.get("diagnoses", []))
        lines.append(f"- {up.doc_type} ({date}) status={up.status}; "
                     f"diagnoses: {dx or 'none'}; medicines: {meds or 'none'}; "
                     f"results: {labs or 'none'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic fallback - runs with no key, no network, no model
# ---------------------------------------------------------------------------

def _fallback(case, patient, grouped, uploads):
    """Deterministic, no-model case sheet — same bullet format the AI
    template above asks for (see TEMPLATE's "Rules"), so the console
    renders both paths identically and a demo running with no API key
    still reads exactly like one running with a working key."""
    def bullets(section):
        items = grouped.get(section, [])
        if not items:
            return ["- Not elicited."]
        return [f"- {i['prompt'].rstrip('?')}: {i['label']}" for i in items]

    hpi_items = grouped.get("hpi", [])
    if hpi_items:
        hpi_lines = [f"- {i['prompt'].rstrip('?')}: {i['label']}" for i in hpi_items]
    else:
        hpi_lines = ["- Not elicited."]

    dv = grouped.get("dashavidha", [])
    if dv:
        dv_lines = [f"- {i['dashavidha_param'] or i['prompt']}: {i['label']}"
                    for i in dv]
        dv_lines.append("- Sara, Samhanana, Pramana and Vikriti to be "
                        "assessed on examination.")
    else:
        dv_lines = ["- Not elicited."]

    inv_lines = []
    for up in uploads:
        for i in (up.extracted or {}).get("investigations", []):
            mark = " (outside reference range)" if i.get("status") in ("high", "low") else ""
            inv_lines.append(f"- {i.get('name')} {i.get('value')}"
                             f"{i.get('unit', '')}{mark}")
    if not inv_lines:
        inv_lines = ["- None on file."]

    sections = [
        ("Chief complaint", bullets("chief_complaint")),
        ("History of present illness", hpi_lines),
        ("Past medical and surgical history", bullets("past")),
        ("Drug and allergy history", bullets("drug_allergy")),
        ("Family history", bullets("family")),
        ("Personal history", bullets("personal")),
        ("Review of systems", bullets("ros")),
        ("Prior investigations", inv_lines),
        ("Dashavidha Pariksha", dv_lines),
    ]
    out = []
    for heading, lines in sections:
        out.append(f"{heading}:")
        out.extend(lines)
    return "\n".join(out)


def as_sections(summary_text):
    """Split the flat summary into heading/bullets pairs for the console.

    Each section becomes {"heading": ..., "bullets": [...]}. Lines under a
    heading that already start with "- " (the format the model and the
    rules fallback both now produce, see TEMPLATE and _fallback above)
    become one bullet each. A section whose body arrived as plain prose —
    an older summary saved before this format existed, or a doctor's own
    free-text edit that does not use bullets — becomes a single bullet
    holding that whole line, so the console never loses text just because
    it is not bulleted; it simply is not broken into multiple lines.
    """
    sections, current = [], None
    for line in (summary_text or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        stripped = raw.lstrip("#").strip()
        is_bullet = stripped.startswith("- ") or stripped.startswith("* ")
        if not is_bullet and ":" in stripped and len(stripped.split(":", 1)[0]) < 60:
            heading, rest = stripped.split(":", 1)
            current = {"heading": heading.strip().lstrip("*- ").strip(),
                       "bullets": []}
            sections.append(current)
            rest = rest.strip()
            if rest:
                current["bullets"].append(rest)
            continue
        if current is None:
            continue
        if is_bullet:
            current["bullets"].append(stripped[2:].strip())
        else:
            # Continuation of the previous bullet (a model reply wrapped a
            # bullet across two lines), or, if there is no bullet yet in
            # this section, the start of one.
            if current["bullets"]:
                current["bullets"][-1] += " " + stripped
            else:
                current["bullets"].append(stripped)
    return sections
