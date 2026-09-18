"""Terminology, drug safety and lab interpretation.

Three jobs:
  1. NAMASTE search with automatic ICD-11 TM2 + Biomedicine dual coding
  2. Drug interaction screening across the Ayurveda / allopathy boundary
  3. Reference-range checking on extracted lab values
"""
from __future__ import annotations

import re

from sqlalchemy import or_

from models import DrugInteraction, NamasteCode

# Complaint -> likely NAMASTE codes, used to pre-rank the autocomplete.
COMPLAINT_HINTS = {
    "joint_pain": ["AAE-16", "AAE-18", "AAE-04"],
    "chest_pain": ["AAI-02", "AAB-09"],
    "abdominal": ["AAB-09", "AAB-14", "AAB-21"],
    "fever": ["AAF-05", "AAF-12"],
    "breathless": ["AAC-02", "AAC-07"],
    "headache": ["AAG-08", "AAG-15"],
    "skin": ["AAH-06", "AAH-11"],
}

# Reference ranges for the lab values our extractor commonly sees.
REFERENCE_RANGES = {
    "hba1c": (4.0, 5.6, "%"),
    "fasting glucose": (70, 100, "mg/dL"),
    "fbs": (70, 100, "mg/dL"),
    "post prandial glucose": (70, 140, "mg/dL"),
    "ppbs": (70, 140, "mg/dL"),
    "random glucose": (70, 140, "mg/dL"),
    "haemoglobin": (12.0, 16.0, "g/dL"),
    "hemoglobin": (12.0, 16.0, "g/dL"),
    "hb": (12.0, 16.0, "g/dL"),
    "creatinine": (0.6, 1.3, "mg/dL"),
    "urea": (15, 45, "mg/dL"),
    "esr": (0, 20, "mm/hr"),
    "crp": (0, 5, "mg/L"),
    "tsh": (0.4, 4.0, "uIU/mL"),
    "total cholesterol": (0, 200, "mg/dL"),
    "ldl": (0, 100, "mg/dL"),
    "hdl": (40, 80, "mg/dL"),
    "triglycerides": (0, 150, "mg/dL"),
    "uric acid": (3.5, 7.2, "mg/dL"),
    "rheumatoid factor": (0, 14, "IU/mL"),
    "vitamin d": (30, 100, "ng/mL"),
    "vitamin b12": (200, 900, "pg/mL"),
    "platelet count": (150, 410, "x10^3/uL"),
    "wbc": (4.0, 11.0, "x10^3/uL"),
    "potassium": (3.5, 5.1, "mmol/L"),
    "sodium": (135, 145, "mmol/L"),
    "sgpt": (0, 45, "U/L"),
    "alt": (0, 45, "U/L"),
    "sgot": (0, 40, "U/L"),
}


# ---------------------------------------------------------------------------
# Terminology
# ---------------------------------------------------------------------------

def search_terminology(query: str, limit: int = 8, complaint: str | None = None):
    query = (query or "").strip()
    results = []

    if query:
        like = f"%{query.lower()}%"
        rows = NamasteCode.query.filter(
            or_(NamasteCode.term.ilike(like),
                NamasteCode.code.ilike(like),
                NamasteCode.keywords.ilike(like),
                NamasteCode.icd11_biomed_term.ilike(like))
        ).limit(limit).all()
    else:
        codes = COMPLAINT_HINTS.get(complaint or "", [])
        rows = NamasteCode.query.filter(NamasteCode.code.in_(codes)).all() \
            if codes else NamasteCode.query.limit(limit).all()

    for row in rows:
        results.append(serialize_code(row))
    return results


def serialize_code(row: NamasteCode):
    return {
        "code": row.code,
        "term": row.term,
        "term_diacritic": row.term_diacritic,
        "system": row.system,
        "description": row.description,
        "icd11_tm2_code": row.icd11_tm2_code,
        "icd11_tm2_term": row.icd11_tm2_term,
        "icd11_biomed_code": row.icd11_biomed_code,
        "icd11_biomed_term": row.icd11_biomed_term,
    }


def suggest_codes(case, limit=4):
    """Rank likely diagnoses from the chief complaint and key HPI answers.

    This is a SUGGESTION for the autocomplete. It never writes a diagnosis.
    """
    answers = case.answers or {}
    codes = list(COMPLAINT_HINTS.get(case.chief_complaint or "", []))

    def _val(node_id):
        return (answers.get(node_id) or {}).get("value")

    if case.chief_complaint == "joint_pain":
        if _val("joint_stiffness") == "over30" or _val("joint_swelling") != "no":
            codes = ["AAE-18"] + [c for c in codes if c != "AAE-18"]
        elif _val("joint_site") and "lower_back" in (_val("joint_site") or []):
            codes = ["AAE-04"] + [c for c in codes if c != "AAE-04"]
    if case.chief_complaint == "fever" and _val("fever_pattern") == "with_chills":
        codes = ["AAF-12"] + [c for c in codes if c != "AAF-12"]
    if "diabetes" in (_val("past_conditions") or []):
        codes.append("AAD-03")

    seen, ordered = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    rows = {r.code: r for r in
            NamasteCode.query.filter(NamasteCode.code.in_(ordered)).all()}
    return [serialize_code(rows[c]) for c in ordered if c in rows][:limit]


# ---------------------------------------------------------------------------
# Drug safety
# ---------------------------------------------------------------------------

# Words that describe a dose or a schedule, never a medicine.
NOISE = r"""tab|tablet|tabs|cap|capsule|caps|syrup|syp|churna|choorna|vati|gutika|
kwath|kadha|powder|drops|inj|injection|mg|mcg|ug|ml|gm|gms|g|iu|units|tsp|tbsp|
bd|od|tds|qid|hs|sos|prn|stat|twice|thrice|once|daily|day|days|week|weeks|month|
months|morning|noon|night|evening|before|after|with|without|food|meal|meals|
empty|stomach|at|in|on|the|a|an|for|and|per|times|time"""

# Spoken or brand forms that need to reach the generic name in the table.
SYNONYMS = {
    "thyronorm": "levothyroxine", "eltroxin": "levothyroxine",
    "thyroxine": "levothyroxine", "glycomet": "metformin",
    "amlong": "amlodipine", "amlokind": "amlodipine",
    "ecosprin": "aspirin", "disprin": "aspirin",
    "liquorice": "yashtimadhu", "mulethi": "yashtimadhu",
    "turmeric": "haridra", "haldi": "haridra",
    "garlic": "lashuna", "ashwagandha": "ashwagandha",
    "bittergourd": "karela", "fenugreek": "methi",
    "amla": "amalaki", "giloy": "guduchi",
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z ]", " ", (name or "").lower())).strip()


def _tokens(name: str):
    """Meaningful word tokens of a medicine name, synonyms resolved."""
    out = []
    for tok in _norm(name).split():
        tok = SYNONYMS.get(tok, tok)
        if len(tok) >= 4 and not re.fullmatch(NOISE, tok, flags=re.I | re.X):
            out.append(tok)
    return out


def parse_medicines(text: str):
    """Pull medicine names out of free text spoken or typed by the patient."""
    if not text:
        return []
    if _norm(text) in {"nothing regular", "nothing", "none", "no medicines",
                       "not taking anything", "nil"}:
        return []

    parts = re.split(r"[,\n;/]|\band\b|\bplus\b", text, flags=re.I)
    out = []
    for part in parts:
        cleaned = re.sub(r"\d+(\.\d+)?", " ", part)          # drop every number
        cleaned = re.sub(rf"\b({NOISE})\b", " ", cleaned, flags=re.I | re.X)
        cleaned = re.sub(r"[^A-Za-z ]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) >= 3:
            out.append(cleaned.title())
    return out


def _matches(drug: str, medicine: str) -> bool:
    """Does this medicine name refer to this drug?

    Token-level, so 'Thyroxine 50 mcg' reaches Levothyroxine and
    'Metformin 500' reaches Metformin, without 'Amla' matching 'Amlodipine'
    (that one is blocked by requiring the shorter token to be at least 5
    characters and a prefix or suffix, not a loose substring).
    """
    drug_tokens = _tokens(drug)
    med_tokens = _tokens(medicine)
    for d in drug_tokens:
        for m in med_tokens:
            if d == m:
                return True
            short, long_ = (d, m) if len(d) <= len(m) else (m, d)
            if len(short) >= 5 and (long_.startswith(short)
                                    or long_.endswith(short)):
                return True
    return False


def check_interactions(medicines):
    """Screen a medicine list against the seeded reference table."""
    names = [m for m in medicines if m and _tokens(m)]
    hits, seen = [], set()
    if len(names) < 2:
        return hits

    for row in DrugInteraction.query.all():
        match_a = next((m for m in names if _matches(row.drug_a, m)), None)
        match_b = next((m for m in names if _matches(row.drug_b, m)), None)
        if match_a and match_b and match_a != match_b:
            key = tuple(sorted([row.drug_a, row.drug_b]))
            if key in seen:
                continue
            seen.add(key)
            hits.append({
                "drug_a": row.drug_a, "drug_b": row.drug_b,
                "severity": row.severity, "mechanism": row.mechanism,
                "advice": row.advice, "reference": row.reference,
            })
    order = {"major": 0, "moderate": 1, "minor": 2}
    hits.sort(key=lambda h: order.get(h["severity"], 3))
    return hits


# ---------------------------------------------------------------------------
# Lab values
# ---------------------------------------------------------------------------

def check_lab_value(name: str, value):
    """Return (status, range_text). status is low | normal | high | unknown."""
    key = (name or "").strip().lower()
    ref = REFERENCE_RANGES.get(key)
    if not ref:
        for k, v in REFERENCE_RANGES.items():
            if k in key:
                ref = v
                break
    if not ref:
        return "unknown", ""
    try:
        num = float(re.sub(r"[^0-9.\-]", "", str(value)))
    except (TypeError, ValueError):
        return "unknown", ""
    low, high, unit = ref
    range_text = f"{low}-{high} {unit}"
    if num < low:
        return "low", range_text
    if num > high:
        return "high", range_text
    return "normal", range_text


def annotate_labs(investigations):
    out = []
    for inv in investigations or []:
        name = inv.get("name") or inv.get("test") or ""
        value = inv.get("value")
        status, ref = check_lab_value(name, value)
        row = dict(inv)
        row["name"] = name
        row["status"] = status
        row["reference"] = inv.get("reference") or ref
        out.append(row)
    return out
