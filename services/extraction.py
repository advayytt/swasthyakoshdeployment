"""Prescription and report digitization.

Everything this module produces lands in status `pending_review`. A doctor
must confirm or edit before a single value enters the patient's record. That
is not a limitation of the prototype, it is the design.

OCR/vision provider: this goes through services.ai.generate_from_image,
which routes to whichever of Gemini / Groq / OpenRouter is configured as
AI_PROVIDER (see config.py and services/ai.py's provider() selection).
Bhashini (services/bhashini.py) is NOT used here and has no document/image
capability at all — it is MeitY's speech (ASR/TTS) and text-translation
(NMT) service only, with no OCR or vision endpoint in its API. A document
read failing is therefore either the configured vision provider's own key
being invalid/missing, or a genuinely illegible document — never a
Bhashini issue, whatever BHASHINI_ENABLED is set to.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime

from . import ai
from .clinical import annotate_labs

SYSTEM = (
    "You read Indian medical documents: handwritten and printed prescriptions, "
    "laboratory reports and discharge summaries, in English, Hindi, Marathi or "
    "a mix. You extract only what is legibly present. You never infer a "
    "diagnosis, never complete a partial drug name by guessing, and never "
    "invent a value. If something is unclear, you say so in the notes and give "
    "it a low confidence score. You reply with JSON only."
)

PROMPT = """Extract the clinical content of this document.

Reply with JSON in exactly this shape:

{
  "doc_type": "prescription" | "lab_report" | "discharge_summary",
  "document_date": "YYYY-MM-DD or null",
  "facility": "clinic or hospital name or null",
  "prescriber": "doctor name or null",
  "diagnoses": [{"text": "...", "confidence": 0.0}],
  "medications": [
    {"name": "...", "strength": "...", "frequency": "...",
     "duration": "...", "confidence": 0.0}
  ],
  "investigations": [
    {"name": "...", "value": "...", "unit": "...",
     "reference": "...", "confidence": 0.0}
  ],
  "procedures": [{"text": "...", "confidence": 0.0}],
  "notes": "anything illegible or uncertain, in one line",
  "overall_confidence": 0.0
}

Rules:
- confidence is 0.0 to 1.0 and must reflect legibility, not your fluency.
- If the document is a lab report, investigations must carry numeric values.
- Transliterate Devanagari drug names to Latin script but keep the original
  spelling in the notes field if you are unsure.
- Return nothing except the JSON object.
"""


def extract_document(image_path: str):
    """Returns (payload_dict, source_label, confidence_float)."""
    result = ai.generate_from_image(SYSTEM, PROMPT, image_path)

    if result.ok:
        data = ai.parse_json(result.text)
        if isinstance(data, dict):
            data = _normalise(data)
            confidence = float(data.get("overall_confidence") or result.confidence)
            return data, result.source, min(max(confidence, 0.0), 1.0)

    # No key, no network, or unparsable reply. The workflow continues.
    return _empty_payload(result.error or "unparsable_response"), "manual", 0.0


def _empty_payload(reason: str):
    return {
        "doc_type": "prescription",
        "document_date": None,
        "facility": None,
        "prescriber": None,
        "diagnoses": [],
        "medications": [],
        "investigations": [],
        "procedures": [],
        "notes": (
            "Automatic reading unavailable ("
            f"{reason}). Enter the fields by hand below — the document is "
            "attached and the review workflow is unchanged."
        ),
        "overall_confidence": 0.0,
        "needs_manual_entry": True,
    }


def _normalise(data: dict):
    data.setdefault("diagnoses", [])
    data.setdefault("medications", [])
    data.setdefault("investigations", [])
    data.setdefault("procedures", [])
    data.setdefault("notes", "")

    for key in ("diagnoses", "procedures"):
        fixed = []
        for item in data.get(key) or []:
            if isinstance(item, str):
                fixed.append({"text": item, "confidence": 0.5})
            elif isinstance(item, dict):
                item.setdefault("confidence", 0.5)
                fixed.append(item)
        data[key] = fixed

    meds = []
    for item in data.get("medications") or []:
        if isinstance(item, str):
            meds.append({"name": item, "strength": "", "frequency": "",
                         "duration": "", "confidence": 0.5})
        elif isinstance(item, dict):
            item.setdefault("name", "")
            item.setdefault("confidence", 0.5)
            if item["name"]:
                meds.append(item)
    data["medications"] = meds

    data["investigations"] = annotate_labs(data.get("investigations"))

    date_raw = data.get("document_date")
    data["document_date"] = _parse_date(date_raw)
    return data


def _parse_date(raw):
    if not raw or str(raw).lower() in {"null", "none", ""}:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def timeline(uploads):
    """Chronological medical timeline. Undated documents sort to the end."""
    items = []
    for up in uploads:
        payload = up.extracted or {}
        items.append({
            "id": up.id,
            "filename": up.filename,
            "doc_type": up.doc_type,
            "date": up.document_date,
            "date_label": up.document_date.strftime("%d %b %Y")
            if up.document_date else "Date not legible",
            "status": up.status,
            "confidence": up.confidence,
            "facility": payload.get("facility"),
            "prescriber": payload.get("prescriber"),
            "diagnoses": payload.get("diagnoses", []),
            "medications": payload.get("medications", []),
            "investigations": payload.get("investigations", []),
            "notes": payload.get("notes", ""),
            "abnormal": [i for i in payload.get("investigations", [])
                         if i.get("status") in {"high", "low"}],
        })
    # Undated documents sort to the end rather than to 1 AD.
    items.sort(key=lambda x: (x["date"] is None, x["date"] or _date.min))
    return items


def all_medications(uploads, spoken_text=""):
    """Every medicine we know about: confirmed documents plus what was said."""
    from .clinical import parse_medicines

    names = []
    for up in uploads:
        if up.status == "rejected":
            continue
        for med in (up.extracted or {}).get("medications", []):
            if med.get("name"):
                names.append(med["name"])
    names.extend(parse_medicines(spoken_text))

    seen, out = set(), []
    for n in names:
        key = n.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n.strip())
    return out
