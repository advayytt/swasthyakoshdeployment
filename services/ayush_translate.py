"""Ayurveda -> allopathy translation for the case sheet.

The problem this solves: a patient's intake can run in Ayurveda mode
(CaseEntry.mode == "ayush"), which asks the ten Dashavidha Pariksha
questions (routes/patient.consent, data/question_ontology.json). If the
patient is then seen by an allopathic doctor (Doctor.system == "Allopathy"),
that doctor has no reason to know what "Agni" or "Koshtha" mean, or what a
"Vata" answer to a body-build question implies clinically. Handing them the
raw Ayurvedic terms is not useful history — it is unreadable jargon.

This module is the translator: for each Dashavidha parameter and each
possible patient answer, it gives a plain-language clinical note that
actually means something to a general-medicine reader. It never asserts a
diagnosis and is careful about how firmly it correlates a traditional
finding with a modern one — see the wording rules in NOTES below. It does
not replace the original Ayurvedic term; routes/clinician.py's case_view()
passes both to the template so the practitioner sees the source and the
translation side by side, never one without the other.

Coverage: this only concerns Dashavidha Pariksha. Every other section of
the case sheet (chief complaint, HPI/SOCRATES, past history, drug/allergy,
family, personal, ROS, investigations) is already system-agnostic — those
questions are the same regardless of mode (confirmed by inspecting
data/question_ontology.json: no non-dashavidha node is mode-gated) — so
they need no translation and this module does not touch them.
"""
from __future__ import annotations

# One entry per Dashavidha parameter, keyed exactly as
# QuestionNode.dashavidha_param stores it (see data/question_ontology.json).
# Each parameter has a short "what_it_asks" gloss (context for a reader who
# has never seen the term) and a per-answer-value clinical note.
#
# Wording rules, followed throughout:
#   - "correlate with" / "consider" / "may suggest", never "means" or
#     "indicates" — a traditional finding is a data point for a modern
#     reader to weigh, not a diagnosis translated 1:1.
#   - Where a finding has no meaningful modern equivalent (Satmya's taste
#     preference, Vikriti's dosha judgement), the note says so honestly
#     rather than inventing a false correlation. A doctor who is told
#     "no direct allopathic equivalent" can decide for themselves whether
#     to use it; a doctor who is quietly given a made-up equivalence
#     cannot.
DASHAVIDHA_TRANSLATIONS = {
    "Vaya": {
        "what_it_asks": "Life stage (a coarser bracket than exact age)",
        "values": {
            "bala": "Paediatric/younger age bracket (under 16).",
            "madhya": "Adult age bracket (16 to 60) — no specific correlate needed.",
            "vriddha": "Older adult / geriatric age bracket (over 60) — "
                      "consider the usual geriatric-history considerations "
                      "(polypharmacy, falls risk, frailty) if relevant.",
        },
    },
    "Ahara Shakti / Agni": {
        "what_it_asks": "Appetite and digestive strength",
        "values": {
            "sama": "Regular appetite, food digests without difficulty — "
                    "unremarkable.",
            "vishama": "Irregular digestion, alternating between normal and "
                      "sluggish. Consider correlating with a functional GI "
                      "picture (e.g. IBS-type symptoms) if the chief "
                      "complaint is abdominal.",
            "tikshna": "Strong, fast appetite, hungry again soon after "
                      "eating. Consider correlating with hyperthyroidism or "
                      "diabetes if other supporting features are present.",
            "manda": "Weak appetite, sluggish digestion. Consider "
                    "correlating with hypothyroidism, chronic GI disease, "
                    "or a depressive picture if other features support it.",
        },
    },
    "Koshtha": {
        "what_it_asks": "Usual bowel habit",
        "values": {
            "mridu": "Soft stools, occasionally loose — analogous to an "
                    "IBS-diarrhoea-predominant—type bowel pattern.",
            "madhyama": "Regular bowel habit, once daily — unremarkable.",
            "krura": "Hard stools needing effort to pass — analogous to a "
                    "constipation-predominant bowel pattern.",
        },
    },
    "Satmya": {
        "what_it_asks": "Which taste the patient naturally prefers in food",
        "values": {
            "madhura": "Prefers sweet foods. No direct allopathic "
                      "equivalent; may be worth a passing note if diet or "
                      "metabolic risk is otherwise relevant.",
            "amla_lavana": "Prefers sour and salty foods. No direct "
                          "allopathic equivalent; worth a passing note if "
                          "sodium intake is relevant (e.g. hypertension).",
            "katu_tikta": "Prefers spicy and bitter foods. No direct "
                         "allopathic equivalent.",
            "mixed": "No particular taste preference. No allopathic "
                    "correlate to note.",
        },
    },
    "Vyayama Shakti": {
        "what_it_asks": "Physical exertion tolerated before tiring",
        "values": {
            "pravara": "High exercise tolerance — sustains a full day of "
                      "hard physical work.",
            "madhyama": "Moderate exercise tolerance — unremarkable.",
            "avara": "Low exercise tolerance, tires quickly. Worth "
                    "correlating with cardiopulmonary functional status "
                    "(the closest modern analogue is a functional class "
                    "assessment) if the chief complaint is cardiac or "
                    "respiratory.",
        },
    },
    "Sattva": {
        "what_it_asks": "How the patient copes with stress or bad news",
        "values": {
            "pravara": "Stays psychologically steady under stress — "
                      "unremarkable.",
            "madhyama": "Shaken by stress or bad news but recovers — "
                       "unremarkable.",
            "avara": "Prolonged distress after stress or bad news. Worth "
                    "a screening question for anxiety or mood symptoms "
                    "if clinically indicated, not a diagnosis on its own.",
        },
    },
    "Prakriti (screening)": {
        "what_it_asks": "Constitutional body build, or which weather the "
                        "patient tolerates poorly (this parameter is asked "
                        "as two separate questions, body build and "
                        "climate, both under the same traditional label)",
        "values": {
            # Body-build screening
            "vata": "Thin build, gains weight with difficulty — the "
                   "closest modern description is an ectomorphic build.",
            "pitta": "Medium build, tends to run warm — the closest "
                    "modern description is a mesomorphic build.",
            "kapha": "Heavier build, gains weight easily — the closest "
                    "modern description is an endomorphic build; worth a "
                    "passing note on metabolic risk if otherwise relevant.",
        },
    },
    "Sara": {
        "what_it_asks": "Tissue excellence (a practitioner-assessed exam "
                        "finding, not patient-reported)",
        "values": {
            "pravara": "Good tissue quality and vigour on examination.",
            "madhyama": "Average tissue quality on examination.",
            "avara": "Poor tissue quality on examination — worth "
                    "correlating with nutritional status.",
        },
    },
    "Samhanana": {
        "what_it_asks": "Compactness of body build (a practitioner-"
                        "assessed exam finding)",
        "values": {
            "pravara": "Well-knit, compact body frame on examination.",
            "madhyama": "Average body frame on examination.",
            "avara": "Loosely-knit body frame on examination.",
        },
    },
    "Vikriti": {
        "what_it_asks": "The examining Ayurvedic practitioner's judgement "
                        "of which dosha is currently imbalanced",
        "values": {
            "vata": "Recorded as a Vata imbalance by the Ayurvedic "
                   "practitioner. This is an Ayurveda-specific clinical "
                   "judgement with no direct allopathic equivalent — "
                   "included here for continuity of the referral, not as "
                   "an independent finding to interpret allopathically.",
            "pitta": "Recorded as a Pitta imbalance by the Ayurvedic "
                    "practitioner. No direct allopathic equivalent; "
                    "included for referral continuity only.",
            "kapha": "Recorded as a Kapha imbalance by the Ayurvedic "
                    "practitioner. No direct allopathic equivalent; "
                    "included for referral continuity only.",
            "sannipata": "Recorded as a combined (Sannipata) imbalance by "
                        "the Ayurvedic practitioner. No direct allopathic "
                        "equivalent; included for referral continuity only.",
        },
    },
}

# Prakriti's climate-preference question shares the label "Prakriti
# (screening)" with the body-build question above (see
# data/question_ontology.json: dv_prakriti_body and dv_prakriti_climate
# are two different nodes with the same dashavidha_param string), but the
# vata/pitta/kapha VALUES mean something different depending on which
# question was actually asked. structured_history() groups both under one
# key with no way to tell them apart from the value alone, so this second
# table exists purely to catch the climate-flavoured phrasing when the
# node_id tells us which question it actually was (see translate() below).
_CLIMATE_VALUES = {
    "vata": "Cold and windy weather troubles the patient most — a cold-"
           "intolerance pattern; worth a screening thought for thyroid "
           "status if otherwise relevant.",
    "pitta": "Hot weather troubles the patient most — a heat-intolerance "
            "pattern; worth a screening thought for thyroid status if "
            "otherwise relevant.",
    "kapha": "Damp, rainy weather troubles the patient most — often "
            "reported alongside joint or respiratory complaints.",
}


def applies_to(case, doctor) -> bool:
    """True when a translation is worth showing at all: the intake ran in
    Ayurveda mode (so Dashavidha data exists to translate) and the doctor
    looking at it is not themselves an Ayurveda/Siddha/Unani practitioner
    (who needs no translation of their own system's terms)."""
    if not case or not doctor:
        return False
    if case.mode != "ayush":
        return False
    return (doctor.system or "").strip() not in ("Ayurveda", "Siddha", "Unani")


def translate(dashavidha_grouped_items, case_dashavidha=None):
    """dashavidha_grouped_items: the list under grouped['dashavidha'] from
    services.intake.structured_history() — patient-reported answers, each
    with node_id/dashavidha_param/value/label. case_dashavidha: case.dashavidha,
    the dict practitioner-entered exam fields (Sara/Samhanana/Pramana/
    Vikriti) get written into on confirm (see routes/clinician.verify_case).

    Returns a list of {param, what_it_asks, patient_answer, note} dicts,
    patient-reported items first in their original order, then any
    practitioner-entered exam fields that have a value. A param whose
    value has no entry in the table above (should not happen with the
    current ontology, but a future new option value could outrun this
    file) still gets a general fallback rather than being silently
    dropped, since dropping a filled-in field looks like data loss to
    whoever is reading the case sheet.
    """
    out = []

    for item in (dashavidha_grouped_items or []):
        param = item.get("dashavidha_param")
        node_id = item.get("node_id")
        value = item.get("value")
        table = DASHAVIDHA_TRANSLATIONS.get(param)
        if not table:
            continue
        # Disambiguate the two Prakriti (screening) questions by node_id —
        # see the _CLIMATE_VALUES comment above for why value alone is not
        # enough here.
        if node_id == "dv_prakriti_climate":
            note = _CLIMATE_VALUES.get(
                value, "Reported, but this answer value is not yet in the "
                      "translation table — shown as originally recorded.")
            what_it_asks = "Which weather the patient tolerates poorly"
        else:
            note = table["values"].get(
                value, "Reported, but this answer value is not yet in the "
                      "translation table — shown as originally recorded.")
            what_it_asks = table["what_it_asks"]
        out.append({
            "param": param, "what_it_asks": what_it_asks,
            "patient_answer": item.get("label"), "note": note,
        })

    for param in ("Sara", "Samhanana", "Vikriti"):
        value = (case_dashavidha or {}).get(param)
        if not value:
            continue
        table = DASHAVIDHA_TRANSLATIONS.get(param, {})
        note = table.get("values", {}).get(
            value, "Recorded, but this answer value is not yet in the "
                  "translation table — shown as originally recorded.")
        out.append({
            "param": param, "what_it_asks": table.get("what_it_asks", ""),
            "patient_answer": value, "note": note,
        })

    return out