"""FHIR R4 export.

The Condition resource is the interesting one: a single code element carrying
three codings side by side — NAMASTE, ICD-11 TM2 and ICD-11 Biomedicine. That
is what the Ministry means by double coding, and it is what lets an AYUSH
encounter appear in national morbidity reporting and in an ABDM record without
losing either vocabulary.
"""
from __future__ import annotations

import uuid
from datetime import timezone

NAMASTE_SYSTEM = "https://ayush.gov.in/fhir/CodeSystem/namaste"
TM2_SYSTEM = "http://id.who.int/icd/release/11/mms/tm2"
MMS_SYSTEM = "http://id.who.int/icd/release/11/mms"
ABHA_SYSTEM = "https://healthid.abdm.gov.in/ns/abha-address"
HPR_SYSTEM = "https://hpr.abdm.gov.in/ns/hpr-id"


def _iso(dt):
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _uid():
    return str(uuid.uuid4())


def build_bundle(case, patient, doctor, uploads, summary_text, consent=None):
    patient_id, encounter_id = _uid(), _uid()
    entries = []

    def add(resource):
        entries.append({"fullUrl": f"urn:uuid:{resource['id']}",
                        "resource": resource})

    add({
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [{"system": ABHA_SYSTEM, "value": patient.abha_address}],
        "name": [{"text": patient.name}],
        "gender": (patient.sex or "unknown").lower(),
        "extension": [{
            "url": "https://ayush.gov.in/fhir/StructureDefinition/age-years",
            "valueInteger": patient.age or 0,
        }],
    })

    practitioner_id = None
    if doctor:
        practitioner_id = _uid()
        add({
            "resourceType": "Practitioner",
            "id": practitioner_id,
            "identifier": [{"system": HPR_SYSTEM, "value": doctor.hpr_id}],
            "name": [{"text": doctor.name}],
        })

    add({
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "finished" if case.status == "confirmed" else "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": "AMB", "display": "ambulatory"},
        "subject": {"reference": f"urn:uuid:{patient_id}"},
        "period": {"start": _iso(case.started_at), "end": _iso(case.submitted_at)},
        "serviceType": {"text": f"{(doctor.system if doctor else 'Ayurveda')} OPD"},
        "priority": {"text": case.triage},
    })

    # --- The dual-coded Condition -----------------------------------------
    if case.namaste_code:
        codings = [{
            "system": NAMASTE_SYSTEM,
            "code": case.namaste_code,
            "display": case.namaste_term or "",
        }]
        if case.icd11_tm2_code:
            codings.append({"system": TM2_SYSTEM, "code": case.icd11_tm2_code})
        if case.icd11_biomed_code:
            codings.append({"system": MMS_SYSTEM, "code": case.icd11_biomed_code})
        add({
            "resourceType": "Condition",
            "id": _uid(),
            "clinicalStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code": "active"}]},
            "verificationStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                "code": "confirmed" if case.status == "confirmed" else "provisional"}]},
            "code": {"coding": codings, "text": case.namaste_term},
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "encounter": {"reference": f"urn:uuid:{encounter_id}"},
            "recordedDate": _iso(case.verified_at or case.submitted_at),
        })

    # --- Red flags as clinical impressions ---------------------------------
    for flag in (case.red_flags or []):
        add({
            "resourceType": "Flag",
            "id": _uid(),
            "status": "active",
            "category": [{"text": "Triage"}],
            "code": {"text": flag.get("label")},
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "encounter": {"reference": f"urn:uuid:{encounter_id}"},
        })

    # --- Prior documents ---------------------------------------------------
    for up in uploads:
        if up.status == "rejected":
            continue
        payload = up.extracted or {}
        for med in payload.get("medications", []):
            add({
                "resourceType": "MedicationStatement",
                "id": _uid(),
                "status": "active",
                "medicationCodeableConcept": {"text": med.get("name", "")},
                "subject": {"reference": f"urn:uuid:{patient_id}"},
                "dosage": [{"text": " ".join(filter(None, [
                    med.get("strength"), med.get("frequency"),
                    med.get("duration")]))}],
                "note": [{"text": f"Digitized from {up.doc_type}; "
                                  f"{'verified' if up.status == 'confirmed' else 'unverified'}"}],
            })
        for inv in payload.get("investigations", []):
            add({
                "resourceType": "Observation",
                "id": _uid(),
                "status": "final" if up.status == "confirmed" else "preliminary",
                "code": {"text": inv.get("name", "")},
                "subject": {"reference": f"urn:uuid:{patient_id}"},
                "valueString": f"{inv.get('value', '')} {inv.get('unit', '')}".strip(),
                "referenceRange": [{"text": inv.get("reference", "")}]
                if inv.get("reference") else [],
                "interpretation": [{"text": inv.get("status", "unknown")}],
            })

    # --- Consent artefact --------------------------------------------------
    if consent:
        add({
            "resourceType": "Consent",
            "id": _uid(),
            "status": "active" if consent.is_live else "inactive",
            "scope": {"text": "patient-privacy"},
            "category": [{"text": "Pre-consultation intake"}],
            "patient": {"reference": f"urn:uuid:{patient_id}"},
            "dateTime": _iso(consent.decided_at or consent.requested_at),
            "provision": {
                "type": "permit",
                "period": {"start": _iso(consent.decided_at),
                           "end": _iso(consent.expires_at)},
                "purpose": [{"display": consent.purpose}],
            },
        })

    # --- The case sheet itself --------------------------------------------
    add({
        "resourceType": "Composition",
        "id": _uid(),
        "status": "final" if case.status == "confirmed" else "preliminary",
        "type": {"text": "Pre-consultation clinical history"},
        "subject": {"reference": f"urn:uuid:{patient_id}"},
        "encounter": {"reference": f"urn:uuid:{encounter_id}"},
        "date": _iso(case.submitted_at or case.started_at),
        "author": [{"reference": f"urn:uuid:{practitioner_id}"}]
        if practitioner_id else [{"display": "Swasthya Kosh intake terminal"}],
        "title": "Pre-consultation clinical history",
        "section": [{"title": "Case sheet",
                     "text": {"status": "generated",
                              "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">"
                                     f"<pre>{_escape(summary_text or '')}</pre></div>"}}],
    })

    return {
        "resourceType": "Bundle",
        "id": _uid(),
        "type": "document",
        "timestamp": _iso(case.submitted_at or case.started_at),
        "meta": {"profile": [
            "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"]},
        "entry": entries,
    }


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
