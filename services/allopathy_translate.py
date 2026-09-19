"""Allopathy -> Ayurveda translation for the case sheet.

The mirror image of services/ayush_translate.py. That module handles an
Ayurveda-mode intake (Dashavidha Pariksha) being read by an allopathic
doctor; this one handles the reverse: a general-medicine intake, taken with
the SOCRATES-structured HPI questions and no Dashavidha Pariksha at all
(CaseEntry.mode == "general" never asks those — see services/intake.py's
_visible(), which gates the whole dashavidha section behind mode=="ayush"),
being read by an Ayurveda, Siddha or Unani doctor.

Unlike the Dashavidha direction, HPI/SOCRATES questions are NOT
Ayurveda-mode-only — they are asked in every intake, general or ayush alike
(confirmed against data/question_ontology.json: no hpi-section node is
mode-gated). So there is no missing data to translate here, only a
vocabulary and framing gap: a SOCRATES answer like "chest_character:
burning" is complete, useful clinical information, but it is phrased in
allopathic terms an Ayurveda-trained reader was not necessarily taught to
map onto dosha-level thinking. This module does that mapping, per node and
per answer value, the same way the Dashavidha direction does it per
parameter and per value.

Calibration, same rules as ayush_translate.py:
  - "classically associated with" / "worth correlating with" / "may
    reflect", never "means" or "confirms" — a modern symptom description
    is being offered as a data point for traditional interpretation, not
    translated into a diagnosis.
  - Where a SOCRATES answer is a genuine clinical red flag regardless of
    system (chest pain radiating with cardiac-sounding features, a
    thunderclap headache, blood in stool, orthopnea), the note says so
    plainly and does not let the dosha framing bury it — a red flag is a
    red flag in any system.
  - The classical dosha-dominant times of day (roughly: Kapha early
    morning/evening, Pitta midday/midnight, Vata late night/late
    afternoon) are standard textbook Ayurveda, not an invented
    correlation, so hpi_timing's notes state them directly rather than
    hedging as heavily as the more speculative per-symptom correlations.

Also surfaces, once per case, that Dashavidha Pariksha was never asked —
see MISSING_DASHAVIDHA_NOTE below — so the Ayurveda doctor knows to assess
constitution and current dosha state directly on examination rather than
assuming its absence from the case sheet means it was assessed and normal.
"""
from __future__ import annotations

MISSING_DASHAVIDHA_NOTE = (
    "This intake ran in general medicine mode, so the Dashavidha Pariksha "
    "questions were never asked — there is no Prakriti, Agni, Koshtha, "
    "Satmya or Sara/Samhanana/Vikriti data on file for this patient. "
    "The notes below are inferred from the SOCRATES-structured history "
    "alone; they are not a substitute for taking Dashavidha Pariksha "
    "directly on examination if it is relevant to your assessment."
)

# Keyed by node_id (not by socrates_slot) because, unlike the Dashavidha
# side, each option set here is specific to one chief-complaint branch —
# "site" means something different for joint_pain than it would for any
# other complaint, and there is no shared vocabulary to key on above the
# individual question. See data/question_ontology.json for the exact
# node_id / value pairs this mirrors.
HPI_TRANSLATIONS = {
    # Universal — asked for every chief complaint, complaint_tag is None.
    "hpi_onset": {
        "today": "Acute onset, started today — in classical framing this "
                "kind of rapid-aggravation onset is more often Vata or "
                "Pitta in character than a slow-building Kapha process; "
                "correlate with the character/quality reported elsewhere.",
        "days": "Sub-acute onset over a few days.",
        "weeks": "Onset over a few weeks — a more gradual course; worth "
                "considering whether a slower, accumulating Kapha-type "
                "process fits the rest of the picture.",
        "months": "Onset over months — a chronic, gradually developing "
                  "course.",
        "years": "Longstanding, a year or more — often reflects an "
                 "established constitutional (Prakriti) tendency or a "
                 "chronic Dhatu-level (tissue) process rather than a "
                 "fresh aggravation. Dashavidha Pariksha, if taken on "
                 "examination, may be informative here.",
    },
    "hpi_severity": {
        "1": "Mild severity as reported by the patient.",
        "2": "Manageable severity.",
        "3": "Troubling severity — the patient finds this significant.",
        "4": "Severe — may warrant a closer look at the affected dosha "
             "and dhatu on examination.",
        "5": "Patient describes this as the worst they have felt — a "
             "significant symptom burden regardless of framework.",
    },
    "hpi_timing": {
        "morning": "Worst in early morning — classically a Kapha-dominant "
                  "period of the day.",
        "day": "Worst during the day — midday is classically a "
              "Pitta-dominant period.",
        "evening": "Worst in the evening — evening is classically a "
                  "Kapha-dominant period (along with early morning).",
        "night": "Worst at night — late night is classically a "
                 "Vata-dominant period; also worth correlating with sleep "
                 "quality and general Vata signs.",
        "constant": "Constant, unremitting — a continuous pattern that "
                   "does not point to any one dosha's characteristic "
                   "timing on its own.",
    },
    # joint_pain
    "joint_site": {
        "knee": "Knee involvement — a weight-bearing joint; worth "
               "checking for Vata signs (dryness, crepitus) given the "
               "mechanical loading.",
        "lower_back": "Lower back involvement — the lower back is a "
                     "classical Vata-predominant region.",
        "shoulder": "Shoulder involvement.",
        "fingers": "Small joints of the fingers and wrists involved — if "
                  "symmetrical and multiple, worth correlating with Ama "
                  "(undigested metabolic residue) or a systemic "
                  "Vata-Kapha picture.",
        "neck": "Neck involvement.",
        "ankle": "Ankle and foot involvement — a lower, weight-bearing "
                "region, again classically Vata-predominant.",
    },
    "joint_stiffness": {
        "none": "No morning stiffness reported.",
        "under30": "Stiffness resolves within half an hour — a milder "
                  "pattern.",
        "over30": "Stiffness lasting more than half an hour — worth "
                 "correlating with Ama or a Kapha-type joint picture, "
                 "given the prolonged, heavy quality.",
    },
    "joint_swelling": {
        "no": "No swelling, warmth or redness reported.",
        "swelling": "Swelling without warmth or redness — a heavier, "
                   "more Kapha-type picture (fluid accumulation) rather "
                   "than an actively inflamed one.",
        "hot_red": "Swollen, warm and red — a Pitta-type inflammatory "
                  "picture; also worth examining for active "
                  "inflammation regardless of framework.",
    },
    # chest_pain
    "chest_character": {
        "pressure": "Heavy pressure or squeezing — a heavier, Kapha-type "
                   "pain quality; the classical anginal description, so "
                   "correlate with cardiac risk factors regardless of "
                   "framework.",
        "burning": "Burning quality — classically a Pitta-type pain "
                  "quality.",
        "sharp": "Sharp, stabbing quality — classically a Vata-type pain "
                "quality (sharp, moving pain).",
        "unsure": "Patient finds the character hard to describe.",
    },
    "chest_radiation": {
        "no": "No radiation reported.",
        "left_arm": "Radiates to the left arm — a classical cardiac red "
                   "flag regardless of framework.",
        "jaw": "Radiates to the jaw or neck — a classical cardiac red "
              "flag regardless of framework.",
        "back": "Radiates to the back.",
    },
    "chest_assoc": {
        "sweating": "Cold sweating alongside the pain — a significant "
                   "associated feature regardless of framework.",
        "breathless": "Breathlessness alongside the pain — a significant "
                     "associated feature regardless of framework.",
        "vomiting": "Nausea or vomiting alongside the pain — a notable "
                   "systemic accompanying feature to weigh alongside "
                   "the cardiac picture.",
        "fainting": "Fainting or blackout alongside the pain — a "
                   "significant red-flag feature regardless of "
                   "framework.",
        "none": "No associated features reported.",
    },
    # abdominal
    "abd_character": {
        "pain": "Pain as the main complaint.",
        "bloating": "Bloating and gas — classically associated with "
                   "aggravated Vata affecting Apana Vata and the "
                   "digestive (Pachaka) fire.",
        "acidity": "Acidity or burning — classically associated with "
                  "aggravated Pitta (specifically Pachaka Pitta) "
                  "affecting digestion.",
        "loose": "Loose motions — could reflect weak Agni or a "
                "Pitta-type aggravation depending on associated "
                "features; worth correlating with Koshtha type on "
                "further history or examination.",
        "constipation": "Constipation — classically associated with "
                        "aggravated Vata affecting Apana Vata and "
                        "Purishavaha srotas (the channel governing "
                        "stool).",
        "blood_stool": "Blood in stool — a significant finding "
                       "regardless of framework; warrants prompt "
                       "further assessment.",
    },
    # fever
    "fever_pattern": {
        "continuous": "Continuous fever, present all day — classically "
                     "described as Santata Jwara.",
        "intermittent": "Intermittent fever, comes and goes — classically "
                        "a form of intermittent Jwara; worth "
                        "establishing the exact interval on further "
                        "history.",
        "with_chills": "Fever with rigors or shivering — classically "
                       "suggests a Vata-Kapha component to the "
                       "presentation.",
        "evening": "Fever rising in the evening — an evening-predominant "
                  "pattern is a recognized feature in classical fever "
                  "description worth noting.",
    },
    # breathless
    "breathless_exertion": {
        "exertion": "Breathless on exertion — movement provoking the "
                   "symptom is a Vata-type pattern in classical framing, "
                   "and also the standard cardiopulmonary red flag "
                   "regardless of system.",
        "rest": "Breathless even at rest — a more severe pattern; "
               "significant regardless of framework and warrants "
               "prompt assessment.",
        "night": "Breathless at night, waking the patient — worth "
                "correlating with a Kapha-type (congestive) pattern "
                "or cardiac causes regardless of framework.",
        "dust": "Triggered by dust or cold air — a classical "
               "Vata-Kapha aggravation pattern (cold, dry or irritant "
               "exposure provoking the airway).",
    },
    "breathless_exacerbating": {
        "yes": "Worse lying flat (orthopnea) — a significant finding "
              "regardless of framework; correlate with cardiac and "
              "Kapha (congestive) causes.",
        "no": "No positional difference reported.",
    },
    # headache
    "headache_features": {
        "thunderclap": "Sudden, severe onset described as 'like a blow' "
                       "— a red-flag feature regardless of framework; "
                       "warrants urgent assessment.",
        "weakness": "One-sided weakness alongside the headache — a "
                    "red-flag neurological feature regardless of "
                    "framework.",
        "speech": "Speech difficulty alongside the headache — a "
                 "red-flag neurological feature regardless of "
                 "framework.",
        "vision": "Blurred or double vision alongside the headache — "
                 "worth correlating with Pitta involvement (the eyes "
                 "are classically associated with Pitta) alongside "
                 "standard neurological assessment.",
        "none": "No associated red-flag features reported.",
    },
    "headache_exacerbating": {
        "light": "Worse with light (photophobia) — classically a "
                "Pitta-aggravation feature (Pitta governs light and "
                "heat sensitivity).",
        "noise": "Worse with noise (phonophobia).",
        "movement": "Worse with movement — a Vata-type aggravation "
                   "pattern.",
        "none": "No clear aggravating pattern reported.",
    },
    # skin
    "skin_spread": {
        "patch": "Localized to one or two patches.",
        "limb": "Spread across a whole limb — a more Kapha-type "
               "(spreading, heavier) pattern if accompanied by itching "
               "or heaviness.",
        "body": "Widespread across most of the body — worth correlating "
               "with a Pitta picture (if hot, red, burning) or a Kapha "
               "picture (if damp, itchy) depending on the character "
               "reported elsewhere.",
    },
    "skin_exacerbating": {
        "heat_worse": "Worse with heat or sweat — classically a "
                     "Pitta-aggravation pattern.",
        "specific_trigger": "Worse after a specific food, soap or "
                            "fabric — worth correlating with Agni/Ama "
                            "if food-triggered, or an external "
                            "Vata-Pitta irritant if contact-triggered.",
        "none": "No clear trigger identified.",
    },
    # exacerbating/relieving, per complaint
    "joint_exacerbating": {
        "movement_worse": "Worse with movement — a classical Vata-type "
                          "pattern (mobile aggravation).",
        "rest_better": "Better with rest — consistent with a Vata-type "
                      "pattern responding to stillness.",
        "weight_worse": "Worse bearing weight — a mechanical loading "
                        "pattern; worth assessing joint structure "
                        "directly regardless of framework.",
        "none": "No clear aggravating or relieving pattern reported.",
    },
    "chest_exacerbating": {
        "exertion_worse": "Worse on exertion — the classical anginal "
                          "pattern; treat as a cardiac red flag "
                          "regardless of framework.",
        "rest_better": "Eases with rest.",
        "breathing_worse": "Worse on deep breathing — suggests a "
                           "pleuritic or musculoskeletal component "
                           "rather than a purely cardiac one; worth "
                           "noting regardless of framework.",
        "none": "No clear aggravating or relieving pattern reported.",
    },
    "abd_exacerbating": {
        "food_worse": "Worse after eating — worth correlating with weak "
                      "Agni or a Pitta-type biliary process.",
        "empty_worse": "Worse on an empty stomach — a classical pattern "
                       "associated with Pitta-type Agni (hyperacidity "
                       "worsening when the stomach is empty).",
        "food_better": "Better after eating.",
        "none": "No clear aggravating or relieving pattern reported.",
    },
}


def applies_to(case, doctor) -> bool:
    """True when this translation is worth showing: the intake did NOT
    run in Ayurveda mode (so it is SOCRATES-structured with no Dashavidha
    data) and the doctor looking at it practices Ayurveda, Siddha or
    Unani — the mirror image of ayush_translate.applies_to()."""
    if not case or not doctor:
        return False
    if case.mode == "ayush":
        return False
    return (doctor.system or "").strip() in ("Ayurveda", "Siddha", "Unani")


def translate(hpi_grouped_items):
    """hpi_grouped_items: the list under grouped['hpi'] from
    services.intake.structured_history() — patient-reported SOCRATES
    answers for THIS case, each with node_id/socrates_slot/value/label.

    Returns a list of {node_id, socrates_slot, patient_answer, note}
    dicts, in the original order. A node_id or value not yet in the
    table above still gets a general fallback rather than being silently
    dropped — an unrecognised value looks like data loss to whoever is
    reading the case sheet otherwise, and this table will lag behind new
    question_ontology.json entries from time to time.
    """
    out = []
    for item in (hpi_grouped_items or []):
        node_id = item.get("node_id")
        value = item.get("value")
        table = HPI_TRANSLATIONS.get(node_id)
        if not table:
            continue
        if isinstance(value, list):
            # A multi-select answer (e.g. headache_features): translate
            # each ticked value and join them, rather than only handling
            # the single-value case and silently dropping the rest.
            notes = [table.get(v) for v in value if table.get(v)]
            note = " ".join(notes) if notes else (
                "Reported, but these answer values are not yet in the "
                "translation table — shown as originally recorded.")
        else:
            note = table.get(
                value, "Reported, but this answer value is not yet in "
                      "the translation table — shown as originally "
                      "recorded.")
        out.append({
            "node_id": node_id, "socrates_slot": item.get("socrates_slot"),
            "patient_answer": item.get("label"), "note": note,
        })
    return out