"""Load reference data and four demo personas.

Run:  python seed.py     (or)  python app.py --seed

Everything created here is fictional. No real patient data is used anywhere in
this prototype, and the personas are labelled as synthetic in the UI.
"""
import json
from datetime import date, timedelta

from config import BASE_DIR
from models import (CaseEntry, ConsentRequest, Doctor, DrugInteraction,
                    NamasteCode, OtpToken, Patient, PrescriptionUpload,
                    QuestionNode, db, utcnow)

DATA = BASE_DIR / "data"


def _load(name):
    with open(DATA / name, encoding="utf-8") as fh:
        return json.load(fh)


def seed_ontology():
    existing = {n.node_id for n in QuestionNode.query.all()}
    added = 0
    for row in _load("question_ontology.json"):
        if row["node_id"] in existing:
            continue
        node = QuestionNode(
            order_index=row.get("order_index", 100),
            prompt_en=row["prompt_en"],
            prompt_hi=row.get("prompt_hi"),
            prompt_mr=row.get("prompt_mr"),
            input_type=row.get("input_type", "choice"),
            options=row.get("options", []),
            parent_node=row.get("parent_node"),
            show_if_value=row.get("show_if_value"),
            complaint_tag=row.get("complaint_tag"),
            socrates_slot=row.get("socrates_slot"),
            dashavidha_param=row.get("dashavidha_param"),
            practitioner_only=row.get("practitioner_only", False),
        )
        node.section = row["section"]
        setattr(node, "node_id", row["node_id"])
        db.session.add(node)
        added += 1
    db.session.commit()
    return added


def seed_terminology():
    existing = {c.code for c in NamasteCode.query.all()}
    added = 0
    for row in _load("namaste_codes.json"):
        if row["code"] in existing:
            continue
        db.session.add(NamasteCode(**row))
        added += 1
    db.session.commit()
    return added


def seed_interactions():
    if DrugInteraction.query.count():
        return 0
    rows = _load("drug_interactions.json")
    for row in rows:
        db.session.add(DrugInteraction(**row))
    db.session.commit()
    return len(rows)


def seed_doctors():
    specs = [
        ("HPR-AY-44821", "Dr Meenakshi Raut", "Ayurveda", "Kayachikitsa"),
        ("HPR-AY-77104", "Dr Sandeep Kulkarni", "Ayurveda", "Panchakarma"),
        ("HPR-MD-20933", "Dr Farhan Qureshi", "Allopathy", "General Medicine"),
    ]
    added = 0
    for hpr, name, system, dept in specs:
        if Doctor.query.filter_by(hpr_id=hpr).first():
            continue
        doc = Doctor(hpr_id=hpr, name=name, system=system, department=dept)
        doc.set_password("demo1234")
        db.session.add(doc)
        added += 1
    db.session.commit()
    return added


PERSONAS = [
    {
        "abha": "kamla.devi@abdm", "name": "Kamla Devi", "age": 68,
        "sex": "female", "lang": "hi", "phone": "4417",
        "complaint": "joint_pain", "mode": "ayush",
        "answers": {
            "cc_main": ("joint_pain", "Joint or back pain", "touch", 1.0, ""),
            "hpi_onset": ("years", "A year or more", "voice", 0.81,
                          "do saal se ghutno mein dard hai"),
            "hpi_severity": ("4", "Severe", "touch", 1.0, ""),
            "hpi_timing": ("morning", "Early morning", "voice", 0.68,
                           "subah subah zyada hota hai"),
            "joint_site": (["knee", "lower_back"], "Knees, Lower back", "touch", 1.0, ""),
            "joint_stiffness": ("under30", "Loosens within half an hour", "touch", 1.0, ""),
            "joint_swelling": ("no", "No", "touch", 1.0, ""),
            "red_general": (["none"], "None of these", "touch", 1.0, ""),
            "past_conditions": (["diabetes", "hypertension"],
                                "Diabetes, High blood pressure", "touch", 1.0, ""),
            "past_surgery": ("no", "No", "touch", 1.0, ""),
            "drug_current": ("Metformin 500 twice daily, Amlodipine 5mg, "
                             "Yashtimadhu churna", "Metformin 500 twice daily, "
                             "Amlodipine 5mg, Yashtimadhu churna", "voice", 0.64,
                             "metformin paanch sau do baar, amlodipine, "
                             "yashtimadhu churna"),
            "drug_allergy": ("no", "No", "touch", 1.0, ""),
            "family_history": (["arthritis"], "Joint disease", "touch", 1.0, ""),
            "personal_habits": (["none"], "None", "touch", 1.0, ""),
            "personal_sleep": ("broken", "Breaks often", "touch", 1.0, ""),
            "dv_vaya": ("vriddha", "Over 60 (Vriddha)", "touch", 1.0, ""),
            "dv_agni": ("manda", "Weak, little appetite (Manda)", "touch", 1.0, ""),
            "dv_koshtha": ("krura", "Hard, needs effort (Krura)", "touch", 1.0, ""),
            "dv_satmya": ("madhura", "Sweet (Madhura)", "touch", 1.0, ""),
            "dv_vyayama": ("avara", "Tire very quickly (Avara)", "touch", 1.0, ""),
            "dv_sattva": ("madhyama", "Shaken but recover (Madhyama)", "touch", 1.0, ""),
            "dv_prakriti_body": ("vata", "Thin, gain weight with difficulty",
                                 "touch", 1.0, ""),
            "dv_prakriti_climate": ("vata", "Cold and windy days", "touch", 1.0, ""),
        },
        "documents": [
            {
                "doc_type": "prescription", "days_ago": 95, "confidence": 0.71,
                "payload": {
                    "doc_type": "prescription",
                    "facility": "Civil Hospital, Sehore",
                    "prescriber": "Dr A. Sharma",
                    "diagnoses": [{"text": "Type 2 diabetes mellitus", "confidence": 0.88},
                                  {"text": "Hypertension", "confidence": 0.84}],
                    "medications": [
                        {"name": "Metformin", "strength": "500 mg",
                         "frequency": "twice daily", "duration": "3 months",
                         "confidence": 0.91},
                        {"name": "Amlodipine", "strength": "5 mg",
                         "frequency": "once daily", "duration": "3 months",
                         "confidence": 0.86},
                    ],
                    "investigations": [], "procedures": [],
                    "notes": "Third line partly illegible, possibly a statin.",
                    "overall_confidence": 0.71,
                },
            },
            {
                "doc_type": "lab_report", "days_ago": 21, "confidence": 0.93,
                "payload": {
                    "doc_type": "lab_report",
                    "facility": "Sehore Diagnostics",
                    "prescriber": None,
                    "diagnoses": [], "medications": [], "procedures": [],
                    "investigations": [
                        {"name": "HbA1c", "value": "8.4", "unit": "%",
                         "reference": "4.0-5.6 %", "status": "high", "confidence": 0.95},
                        {"name": "Fasting glucose", "value": "162", "unit": "mg/dL",
                         "reference": "70-100 mg/dL", "status": "high", "confidence": 0.94},
                        {"name": "Creatinine", "value": "1.1", "unit": "mg/dL",
                         "reference": "0.6-1.3 mg/dL", "status": "normal", "confidence": 0.93},
                        {"name": "ESR", "value": "34", "unit": "mm/hr",
                         "reference": "0-20 mm/hr", "status": "high", "confidence": 0.9},
                    ],
                    "notes": "", "overall_confidence": 0.93,
                },
            },
        ],
    },
    {
        "abha": "rukmini.patil@abdm", "name": "Rukmini Patil", "age": 54,
        "sex": "female", "lang": "mr", "phone": "9082",
        "complaint": "abdominal", "mode": "ayush",
        "answers": {
            "cc_main": ("abdominal", "Stomach problem", "voice", 0.77,
                        "potat jalte ani gas hoto"),
            "hpi_onset": ("months", "Months", "touch", 1.0, ""),
            "hpi_severity": ("3", "Troubling", "touch", 1.0, ""),
            "hpi_timing": ("night", "At night", "touch", 1.0, ""),
            "abd_character": (["acidity", "bloating"],
                              "Acidity or burning, Bloating and gas", "touch", 1.0, ""),
            "red_general": (["none"], "None of these", "touch", 1.0, ""),
            "past_conditions": (["thyroid"], "Thyroid problem", "touch", 1.0, ""),
            "past_surgery": ("no", "No", "touch", 1.0, ""),
            "drug_current": ("Thyroxine 50 mcg, Triphala churna at night",
                             "Thyroxine 50 mcg, Triphala churna at night",
                             "voice", 0.72, "thyroxine pannas, ratri triphala churna"),
            "drug_allergy": ("no", "No", "touch", 1.0, ""),
            "family_history": (["none"], "None known", "touch", 1.0, ""),
            "personal_habits": (["none"], "None", "touch", 1.0, ""),
            "personal_sleep": ("broken", "Breaks often", "touch", 1.0, ""),
            "dv_vaya": ("madhya", "16 to 60 (Madhya)", "touch", 1.0, ""),
            "dv_agni": ("tikshna", "Very strong, hungry soon again (Tikshna)",
                        "touch", 1.0, ""),
            "dv_koshtha": ("mridu", "Soft, easy, sometimes loose (Mridu)",
                           "touch", 1.0, ""),
            "dv_satmya": ("katu_tikta", "Pungent and bitter (Katu, Tikta)",
                          "touch", 1.0, ""),
            "dv_vyayama": ("madhyama", "Moderate work (Madhyama)", "touch", 1.0, ""),
            "dv_sattva": ("pravara", "Stay steady (Pravara)", "touch", 1.0, ""),
            "dv_prakriti_body": ("pitta", "Medium, warm-bodied", "touch", 1.0, ""),
            "dv_prakriti_climate": ("pitta", "Hot summer", "touch", 1.0, ""),
        },
        "documents": [],
    },
    {
        "abha": "ramesh.yadav@abdm", "name": "Ramesh Yadav", "age": 61,
        "sex": "male", "lang": "hi", "phone": "3310",
        "complaint": "chest_pain", "mode": "general",
        "answers": {
            "cc_main": ("chest_pain", "Chest pain or tightness", "touch", 1.0, ""),
            "hpi_onset": ("today", "Started today", "touch", 1.0, ""),
            "hpi_severity": ("5", "Worst I have felt", "touch", 1.0, ""),
            "hpi_timing": ("constant", "All the time", "touch", 1.0, ""),
            "chest_character": ("pressure", "Heavy pressure or squeezing",
                                "voice", 0.79, "chaati par bhaari pathar jaisa"),
            "chest_radiation": ("left_arm", "Yes, left arm", "touch", 1.0, ""),
            "chest_assoc": (["sweating", "breathless"],
                            "Cold sweating, Breathlessness", "touch", 1.0, ""),
        },
        "documents": [],
        "incomplete": True,
    },
    {
        "abha": "arjun.nair@abdm", "name": "Arjun Nair", "age": 34,
        "sex": "male", "lang": "en", "phone": "7756",
        "complaint": "skin", "mode": "ayush",
        "answers": {
            "cc_main": ("skin", "Skin complaint", "touch", 1.0, ""),
            "hpi_onset": ("weeks", "A few weeks", "touch", 1.0, ""),
            "hpi_severity": ("2", "Manageable", "touch", 1.0, ""),
            "hpi_timing": ("night", "At night", "touch", 1.0, ""),
            "skin_spread": ("limb", "A whole arm or leg", "touch", 1.0, ""),
            "red_general": (["none"], "None of these", "touch", 1.0, ""),
            "past_conditions": (["none"], "None", "touch", 1.0, ""),
            "past_surgery": ("no", "No", "touch", 1.0, ""),
            "drug_current": ("Nothing regular", "Nothing regular", "touch", 1.0, ""),
            "drug_allergy": ("unsure", "Not sure", "touch", 1.0, ""),
            "family_history": (["none"], "None known", "touch", 1.0, ""),
            "personal_habits": (["smoking"], "Smoking", "touch", 1.0, ""),
            "personal_sleep": ("good", "Sound sleep", "touch", 1.0, ""),
            "dv_vaya": ("madhya", "16 to 60 (Madhya)", "touch", 1.0, ""),
            "dv_agni": ("sama", "Regular, food digests well (Sama)", "touch", 1.0, ""),
            "dv_koshtha": ("madhyama", "Regular once a day (Madhyama)", "touch", 1.0, ""),
            "dv_satmya": ("mixed", "No particular preference", "touch", 1.0, ""),
            "dv_vyayama": ("pravara", "A full day's hard work (Pravara)", "touch", 1.0, ""),
            "dv_sattva": ("pravara", "Stay steady (Pravara)", "touch", 1.0, ""),
            "dv_prakriti_body": ("kapha", "Heavy, gain weight easily", "touch", 1.0, ""),
            "dv_prakriti_climate": ("kapha", "Damp and rainy weather", "touch", 1.0, ""),
        },
        "documents": [],
    },
]


def seed_personas():
    from services import redflags
    from services.clinical import suggest_codes
    from services.summary import _fallback  # deterministic, no API key needed
    from services.intake import structured_history

    created = 0
    for spec in PERSONAS:
        if Patient.query.filter_by(abha_address=spec["abha"]).first():
            continue
        patient = Patient(
            abha_address=spec["abha"], name=spec["name"], age=spec["age"],
            sex=spec["sex"], phone_last4=spec["phone"],
            preferred_language=spec["lang"],
            abha_number=f"91-{4000 + created}-{7700 + created}-{1100 + created}",
        )
        db.session.add(patient)
        db.session.flush()

        answers = {}
        for node_id, (value, label, source, conf, raw) in spec["answers"].items():
            answers[node_id] = {"value": value, "label": label, "source": source,
                                "confidence": conf, "raw": raw,
                                "at": utcnow().isoformat()}

        case = CaseEntry(
            patient_id=patient.id, mode=spec["mode"], language=spec["lang"],
            chief_complaint=spec["complaint"], answers=answers,
            consent_given=True,
            consent_purpose="Pre-consultation clinical history for today's OPD visit",
            started_at=utcnow() - timedelta(minutes=9),
        )
        db.session.add(case)
        db.session.flush()

        for doc in spec["documents"]:
            db.session.add(PrescriptionUpload(
                patient_id=patient.id, case_id=case.id,
                filename=f"{patient.name.split()[0].lower()}_{doc['doc_type']}.jpg",
                doc_type=doc["doc_type"],
                document_date=date.today() - timedelta(days=doc["days_ago"]),
                extracted=doc["payload"], extraction_source="vision_llm",
                confidence=doc["confidence"], status="pending_review",
            ))

        level, flags = redflags.evaluate(case, patient)
        case.triage, case.red_flags = level, flags

        if not spec.get("incomplete"):
            uploads = PrescriptionUpload.query.filter_by(case_id=case.id).all()
            case.summary_text = _fallback(case, patient,
                                          structured_history(case), uploads)
            case.summary_source = "rules"
            case.status = "awaiting_review"
            case.submitted_at = utcnow() - timedelta(minutes=3)
            picks = suggest_codes(case)
            if picks:
                top = picks[0]
                case.namaste_code = top["code"]
                case.namaste_term = top["term"]
                case.icd11_tm2_code = top["icd11_tm2_code"]
                case.icd11_biomed_code = top["icd11_biomed_code"]
        else:
            case.status = "awaiting_review"
            case.submitted_at = utcnow() - timedelta(minutes=1)
            case.summary_text = ("Chief complaint: Chest pain or tightness.\n"
                                 "History of present illness: Intake was "
                                 "interrupted when triage escalated this "
                                 "patient to emergency. Remaining sections were "
                                 "not asked.\n"
                                 "Review of systems: Cold sweating, "
                                 "breathlessness, radiation to left arm.")
            case.summary_source = "rules"

        created += 1

    db.session.commit()
    return created


def seed_consents():
    """Give the first doctor live access to two patients so the queue opens."""
    doctor = Doctor.query.filter_by(hpr_id="HPR-AY-44821").first()
    if not doctor:
        return 0
    added = 0
    for abha in ("kamla.devi@abdm", "rukmini.patil@abdm", "ramesh.yadav@abdm"):
        patient = Patient.query.filter_by(abha_address=abha).first()
        if not patient:
            continue
        exists = ConsentRequest.query.filter_by(
            doctor_id=doctor.id, patient_id=patient.id).first()
        if exists:
            continue
        req = ConsentRequest(
            patient_id=patient.id, doctor_id=doctor.id,
            purpose="Today's OPD consultation",
            scope=["case_history", "documents"],
        )
        req.grant(24)
        db.session.add(req)
        added += 1

    # One patient deliberately left un-consented so the lock screen can be shown
    arjun = Patient.query.filter_by(abha_address="arjun.nair@abdm").first()
    if arjun and not ConsentRequest.query.filter_by(
            doctor_id=doctor.id, patient_id=arjun.id).first():
        req = ConsentRequest(
            patient_id=arjun.id, doctor_id=doctor.id,
            purpose="Today's OPD consultation",
            scope=["case_history", "documents"], status="requested", otp="246813")
        db.session.add(req)
        db.session.flush()
        # The approval screen verifies against an OtpToken row, not against
        # this column. Without the token the seeded request can be seen but
        # never approved, which is exactly the sort of thing you discover on
        # stage. Issue a real one.
        db.session.add(OtpToken(code="246813"))
        added += 1

    db.session.commit()
    return added


def reset_all():
    """Wipe everything and rebuild. Use between rehearsals so judges never see
    the leftovers of your last run."""
    db.drop_all()
    db.create_all()
    print("  database cleared")


def run_seed(reset=False):
    if reset:
        reset_all()
    db.create_all()
    print(f"  question nodes   : +{seed_ontology()}")
    print(f"  NAMASTE codes    : +{seed_terminology()}")
    print(f"  drug interactions: +{seed_interactions()}")
    print(f"  practitioners    : +{seed_doctors()}")
    print(f"  demo personas    : +{seed_personas()}")
    print(f"  consent artefacts: +{seed_consents()}")
    print("\n  Practitioner login  HPR-AY-44821 / demo1234")
    print("  Patient OTP (mock)  246813\n")


if __name__ == "__main__":
    import sys

    from app import app
    wipe = "--reset" in sys.argv
    with app.app_context():
        if wipe:
            print("\n  Resetting all demo data...")
        run_seed(reset=wipe)
