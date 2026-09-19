"""The consultation-room console.

The physician opens one screen and sees the whole case: triage banner, the
generated case sheet with its provenance, the document timeline, dual coding,
and drug safety. Everything is editable. Nothing is final until they say so.
"""
from __future__ import annotations

import io
import json
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, send_from_directory,
                   session, url_for)

from models import (AccessLog, CaseEntry, ConsentRequest, Doctor, NamasteCode,
                    Patient, PrescriptionUpload, QuestionNode, db, log, utcnow)
from services import (abdm, allopathy_translate, ayush_translate,
                      extraction, fhir, redflags, summary)
from services.clinical import (check_interactions, search_terminology,
                               suggest_codes)
from services.intake import SECTION_LABELS, practitioner_nodes, structured_history

bp = Blueprint("clinician", __name__, url_prefix="/clinician")

TRIAGE_RANK = {"emergency": 0, "priority": 1, "routine": 2}


def _safe_int(raw, default):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def current_doctor():
    did = session.get("doctor_id")
    return Doctor.query.get(did) if did else None


def doctor_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_doctor():
            return redirect(url_for("clinician.login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        doctor = Doctor.query.filter_by(
            hpr_id=request.form.get("hpr_id", "").strip()).first()
        if doctor and doctor.check_password(request.form.get("password", "")):
            session["doctor_id"] = doctor.id
            log("doctor_signed_in", actor_type="doctor", actor_id=doctor.id,
                actor_label=doctor.name)
            db.session.commit()
            return redirect(url_for("clinician.queue"))
        flash("HPR ID or password not recognised.", "error")
    return render_template("clinician/login.html",
                           demo=Doctor.query.limit(3).all())


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        hpr_id = (request.form.get("hpr_id") or "").strip().upper()
        name = (request.form.get("name") or "").strip()
        system = (request.form.get("system") or "Ayurveda").strip()
        department = (request.form.get("department") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not hpr_id or not name or not department:
            flash("Name, HPR ID and department are required.", "error")
            return render_template("clinician/signup.html")
        if len(password) < 8:
            flash("Use a password with at least 8 characters.", "error")
            return render_template("clinician/signup.html")
        if password != confirm:
            flash("The two passwords did not match.", "error")
            return render_template("clinician/signup.html")
        if Doctor.query.filter_by(hpr_id=hpr_id).first():
            flash("That HPR ID already has an account. Sign in instead.", "warn")
            return redirect(url_for("clinician.login"))

        doctor = Doctor(hpr_id=hpr_id, name=name, system=system,
                        department=department)
        doctor.set_password(password)
        db.session.add(doctor)
        db.session.flush()
        log("doctor_signed_up", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=doctor.hpr_id,
            detail=f"{doctor.system} / {doctor.department}")
        db.session.commit()
        session["doctor_id"] = doctor.id
        flash("Practitioner account created. You are signed in.", "ok")
        return redirect(url_for("clinician.queue"))

    return render_template("clinician/signup.html")


@bp.route("/logout")
def logout():
    session.pop("doctor_id", None)
    return redirect(url_for("main.landing"))


# ---------------------------------------------------------------------------

@bp.route("/queue")
@doctor_required
def queue():
    doctor = current_doctor()
    tab = request.args.get("tab", "waiting")
    if tab not in ("waiting", "attended"):
        tab = "waiting"

    all_cases = CaseEntry.query.filter(CaseEntry.status.in_(
        ["awaiting_review", "confirmed"])).all()

    # Scope the queue to patients who picked THIS doctor on the kiosk
    # (see CaseEntry.chosen_doctor_id / routes/patient.choose_doctor).
    # Three kinds of case are never filtered out, regardless of who they
    # picked:
    #   - emergencies: a red-flagged patient must be visible to every
    #     doctor, not siloed into one queue while everyone else's screen
    #     stays quiet about them.
    #   - chosen_doctor_id unset: a patient who used "Skip, any doctor"
    #     (or an older case from before this feature existed, which has
    #     no value here either) still needs to show up SOMEWHERE — every
    #     doctor sees these rather than no one.
    #   - already assigned to this doctor by the older doctor_id field
    #     (set when a doctor CONFIRMS a case sheet) or attended_by: if a
    #     doctor has already engaged with a case in either of those ways,
    #     it keeps showing on their queue even if chosen_doctor_id points
    #     elsewhere or was never set — that other doctor already has a
    #     stake in this patient's visit.
    my_cases = [c for c in all_cases if (
        c.triage == "emergency"
        or c.chosen_doctor_id is None
        or c.chosen_doctor_id == doctor.id
        or c.doctor_id == doctor.id
        or c.attended_by == doctor.id
    )]

    if tab == "attended":
        cases = [c for c in my_cases if c.attended_at]
        # Most recently attended first — that is what a doctor glancing
        # back at who they have already seen today wants at the top.
        cases.sort(key=lambda c: c.attended_at, reverse=True)
    else:
        cases = [c for c in my_cases if not c.attended_at]
        cases.sort(key=lambda c: (TRIAGE_RANK.get(c.triage, 3),
                                  c.submitted_at or utcnow()))

    rows = []
    for case in cases:
        rows.append({
            "case": case,
            "patient": case.patient,
            "granted": _has_access(doctor, case.patient_id),
            "pending": _pending_request(doctor, case.patient_id),
            "docs": PrescriptionUpload.query.filter_by(case_id=case.id).count(),
            "chosen_me": case.chosen_doctor_id == doctor.id,
        })

    # Counts (the three banner numbers and the two tab labels) are always
    # computed across THIS doctor's scoped queue (my_cases), not the
    # whole hospital's — a doctor's "2 emergency" banner means two
    # emergencies they can see, which given the emergency carve-out above
    # is every emergency in the building, same as before this feature.
    counts = {
        "emergency": sum(1 for c in my_cases if c.triage == "emergency"
                         and c.status == "awaiting_review"
                         and not c.attended_at),
        "priority": sum(1 for c in my_cases if c.triage == "priority"
                        and c.status == "awaiting_review"
                        and not c.attended_at),
        "waiting": sum(1 for c in my_cases if c.status == "awaiting_review"
                       and not c.attended_at),
        "waiting_total": sum(1 for c in my_cases if not c.attended_at),
        "attended_total": sum(1 for c in my_cases if c.attended_at),
    }
    return render_template("clinician/queue.html", rows=rows, doctor=doctor,
                           counts=counts, tab=tab)


@bp.route("/case/<int:case_id>/attended", methods=["POST"])
@doctor_required
def mark_attended(case_id):
    """Toggle whether the doctor has seen this patient today.

    Deliberately separate from verify_case()/confirming the case sheet —
    a doctor may tick this mid-consult before the case sheet is finished,
    or finish the case sheet before calling the patient in. See the
    attended_at/attended_by comment on CaseEntry in models.py.
    """
    doctor = current_doctor()
    case = CaseEntry.query.get_or_404(case_id)
    if not _has_access(doctor, case.patient_id):
        abort(403)

    if case.attended_at:
        case.attended_at = None
        case.attended_by = None
        log("case_unattended", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}")
        flash("Moved back to the waiting queue.", "ok")
    else:
        case.attended_at = utcnow()
        case.attended_by = doctor.id
        log("case_attended", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}")
        flash("Marked as attended.", "ok")

    db.session.commit()
    next_url = request.form.get("next") or url_for("clinician.queue")
    return redirect(next_url)


def _pending_request(doctor, patient_id):
    """The doctor's own most recent still-open request for this patient, if
    any — used to offer "enter the code" instead of "request access" once
    a request is already in flight, on the queue table and anywhere else
    that needs it."""
    return ConsentRequest.query.filter_by(
        doctor_id=doctor.id, patient_id=patient_id, status="requested")\
        .order_by(ConsentRequest.id.desc()).first()


def _has_access(doctor, patient_id):
    """Own submissions are open; anything else needs a live consent artefact."""
    req = ConsentRequest.query.filter_by(doctor_id=doctor.id,
                                         patient_id=patient_id,
                                         status="granted")\
        .order_by(ConsentRequest.id.desc()).first()
    return req if (req and req.is_live) else None


# ---------------------------------------------------------------------------

@bp.route("/case/<int:case_id>")
@doctor_required
def case_view(case_id):
    doctor = current_doctor()
    case = CaseEntry.query.get_or_404(case_id)
    patient = case.patient
    uploads = PrescriptionUpload.query.filter_by(case_id=case.id)\
        .order_by(PrescriptionUpload.uploaded_at).all()

    consent = _has_access(doctor, patient.id)
    open_request = ConsentRequest.query.filter_by(
        doctor_id=doctor.id, patient_id=patient.id, status="requested").first()

    if not consent:
        log("access_denied", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}",
            detail="no live consent artefact")
        db.session.commit()
        return render_template("clinician/locked.html", case=case,
                               patient=patient, doctor=doctor,
                               open_request=open_request)

    log("case_opened", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"case:{case.id}", consent_id=consent.id)
    db.session.commit()

    spoken_meds = (case.answers or {}).get("drug_current", {}).get("value", "")
    medicines = extraction.all_medications(uploads, spoken_meds)
    interactions = check_interactions(medicines)
    grouped = structured_history(case)

    # Ayurveda-taken intake (case.mode == "ayush") seen by a non-AYUSH
    # doctor: translate the Dashavidha Pariksha findings into plain
    # clinical notes so "Agni: Vishama" does not land in front of an
    # allopathic reader as unexplained jargon. See services/ayush_translate
    # for what this does and does not claim to translate.
    ayush_translation = None
    if ayush_translate.applies_to(case, doctor):
        ayush_translation = ayush_translate.translate(
            grouped.get("dashavidha", []), case.dashavidha)

    # The mirror direction: a general-medicine (SOCRATES) intake read by
    # an Ayurveda/Siddha/Unani doctor. See services/allopathy_translate
    # for what this covers and how it is calibrated.
    allopathy_translation = None
    if allopathy_translate.applies_to(case, doctor):
        allopathy_translation = allopathy_translate.translate(
            grouped.get("hpi", []))

    return render_template(
        "clinician/case.html",
        case=case, patient=patient, doctor=doctor, consent=consent,
        sections=summary.as_sections(case.summary_text),
        grouped=grouped,
        section_labels=SECTION_LABELS,
        timeline=extraction.timeline(uploads),
        medicines=medicines,
        interactions=interactions,
        suggestions=suggest_codes(case),
        practitioner_nodes=practitioner_nodes(),
        low_confidence=_low_confidence(case, uploads),
        ayush_translation=ayush_translation,
        allopathy_translation=allopathy_translation,
        missing_dashavidha_note=allopathy_translate.MISSING_DASHAVIDHA_NOTE,
    )


def _low_confidence(case, uploads):
    """Everything the physician should personally re-check before confirming."""
    threshold = current_app.config["LOW_CONFIDENCE_THRESHOLD"]
    items = []
    for node_id, entry in (case.answers or {}).items():
        if entry.get("confidence", 1.0) < threshold:
            items.append({"what": entry.get("label") or entry.get("value"),
                          "why": f"heard by voice at "
                                 f"{int(entry.get('confidence', 0) * 100)}% confidence",
                          "where": node_id})
    for up in uploads:
        if up.confidence < threshold:
            items.append({"what": f"{up.doc_type} ({up.filename[:28]})",
                          "why": f"document read at {int(up.confidence * 100)}% confidence",
                          "where": f"upload:{up.id}"})
    return items


# ---------------------------------------------------------------------------

@bp.route("/case/<int:case_id>/verify", methods=["POST"])
@doctor_required
def verify_case(case_id):
    doctor = current_doctor()
    case = CaseEntry.query.get_or_404(case_id)
    if not _has_access(doctor, case.patient_id):
        abort(403)

    action = request.form.get("action")

    if action == "reject":
        case.status = "rejected"
        case.verified_by = doctor.id
        case.verified_at = utcnow()
        log("case_rejected", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}",
            detail=request.form.get("reason", ""))
        db.session.commit()
        flash("Case sheet rejected. It will not enter the record.", "warn")
        return redirect(url_for("clinician.queue"))

    edited = request.form.get("summary_text", "").strip()
    if edited and edited != (case.summary_text or "").strip():
        case.summary_text = edited
        case.summary_source = "edited"

    code = request.form.get("namaste_code", "").strip()
    if code:
        row = NamasteCode.query.filter_by(code=code).first()
        if row:
            case.namaste_code = row.code
            case.namaste_term = row.term
            case.icd11_tm2_code = row.icd11_tm2_code
            case.icd11_biomed_code = row.icd11_biomed_code

    dv = dict(case.dashavidha or {})
    for node in practitioner_nodes():
        field = f"dv_{node.node_id}"
        if node.input_type == "multi":
            val = request.form.getlist(field)
        else:
            val = request.form.get(field, "").strip()
        if val:
            dv[node.dashavidha_param or node.node_id] = val
    case.dashavidha = dv

    if action == "confirm":
        case.status = "confirmed"
        case.doctor_id = doctor.id
        case.verified_by = doctor.id
        case.verified_at = utcnow()
        log("case_confirmed", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}",
            detail=f"namaste={case.namaste_code} tm2={case.icd11_tm2_code} "
                   f"summary_source={case.summary_source}")
        flash("Case sheet confirmed and written to the record.", "ok")
    else:
        log("case_edited", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"case:{case.id}")
        flash("Changes saved as a draft.", "ok")

    db.session.commit()
    return redirect(url_for("clinician.case_view", case_id=case.id))


@bp.route("/upload/<int:upload_id>/review", methods=["POST"])
@doctor_required
def review_upload(upload_id):
    doctor = current_doctor()
    up = PrescriptionUpload.query.get_or_404(upload_id)
    if not _has_access(doctor, up.patient_id):
        abort(403)

    action = request.form.get("action")
    payload = dict(up.extracted or {})

    names = request.form.getlist("med_name")
    doses = request.form.getlist("med_dose")
    if names:
        payload["medications"] = [
            {"name": n.strip(), "strength": (doses[i] if i < len(doses) else ""),
             "frequency": "", "duration": "", "confidence": 1.0}
            for i, n in enumerate(names) if n.strip()
        ]

    up.extracted = payload
    up.status = "confirmed" if action == "confirm" else "rejected"
    up.verified_by = doctor.id
    up.verified_at = utcnow()
    if action == "confirm":
        up.confidence = 1.0
        up.extraction_source = "doctor_verified"

    log(f"document_{up.status}", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"upload:{up.id}")
    db.session.commit()
    flash("Document reading confirmed." if action == "confirm"
          else "Document reading rejected.", "ok")
    return redirect(url_for("clinician.case_view", case_id=up.case_id))


@bp.route("/upload/<int:upload_id>/file")
@doctor_required
def view_upload(upload_id):
    """Serve the original uploaded document as-is.

    Exists so a doctor can look at the actual prescription or report
    whenever the automatic reading is wrong, low-confidence, or failed
    outright (see services/extraction.py's _empty_payload — a failed read
    still attaches the document and sets needs_manual_entry rather than
    losing it). The structured fields on screen are the model's reading;
    this route is the ground truth they were read from.

    Same consent gate as every other per-patient view in this file — a
    document is part of the record it belongs to, not a public asset, so
    it gets exactly the access check case_view() and review_upload() use.
    """
    doctor = current_doctor()
    up = PrescriptionUpload.query.get_or_404(upload_id)
    if not _has_access(doctor, up.patient_id):
        abort(403)
    if not up.filename:
        abort(404)

    log("document_viewed_raw", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"upload:{up.id}")
    db.session.commit()
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], up.filename,
        as_attachment=False)


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

@bp.route("/consent/request/<int:patient_id>", methods=["POST"])
@doctor_required
def request_consent(patient_id):
    doctor = current_doctor()
    patient = Patient.query.get_or_404(patient_id)
    req = ConsentRequest(
        patient_id=patient.id, doctor_id=doctor.id,
        purpose=request.form.get("purpose") or "Today's OPD consultation",
        scope=["case_history", "documents"],
    )
    db.session.add(req)
    db.session.commit()
    code = abdm.issue_otp(f"consent:{req.id}")
    req.otp = code
    log("consent_requested", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"patient:{patient.id}",
        consent_id=req.id, detail=req.purpose)
    db.session.commit()
    flash(f"Request sent to {patient.name}. Ask them for the code and enter "
          f"it below to unlock access, or they can approve it themselves on "
          f"the terminal or their phone.", "ok")
    return redirect(request.referrer or url_for("clinician.queue"))


@bp.route("/consent/<int:req_id>/verify", methods=["POST"])
@doctor_required
def verify_consent_otp(req_id):
    """Grant consent from the practitioner side, using the code the patient
    reads out loud rather than the patient logging into the kiosk again.

    This exists because the patient-side approval screen
    (patient/requests.html, routes/patient.decide_request) requires an
    active kiosk session — @patient_required redirects to the login screen
    otherwise. A patient with no smartphone has no way back into that
    session once they leave the terminal for the consult room: they
    finished their intake, the doctor clicks "Request access" at that
    point, and there is no device left in the patient's hands to approve
    it on. The OTP itself already exists independent of any session (see
    services/abdm.verify_otp, which checks the OtpToken table by subject
    string, not by who is logged in) — this route is the missing second
    way to redeem it: the patient reads the code off whatever they saw it
    on (the kiosk screen before they left, or an SMS in a real deployment)
    and tells it to the doctor, who types it in here.

    This does not replace the patient's own self-serve approval — that
    still works exactly as before for anyone who does have a device in
    hand. It only adds the second path for everyone else.
    """
    doctor = current_doctor()
    req = ConsentRequest.query.get_or_404(req_id)
    if req.doctor_id != doctor.id:
        abort(403)
    if req.status != "requested":
        flash("This request has already been decided.", "warn")
        return redirect(request.referrer or url_for("clinician.queue"))

    code = (request.form.get("otp") or "").strip()
    if not abdm.verify_otp(f"consent:{req.id}", code):
        log("consent_verify_failed", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"patient:{req.patient_id}",
            consent_id=req.id)
        db.session.commit()
        flash("That code did not match. Ask the patient to read it out "
              "again, or send a new code.", "error")
        return redirect(request.referrer or url_for("clinician.queue"))

    req.grant(current_app.config["CONSENT_DEFAULT_HOURS"])
    log("consent_granted", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"patient:{req.patient_id}",
        consent_id=req.id, detail=f"{req.purpose} (verified by practitioner, "
                                   f"patient read the code aloud)")
    db.session.commit()
    flash(f"Access granted until {req.expires_at.strftime('%d %b, %H:%M')}.", "ok")
    return redirect(request.referrer or url_for("clinician.queue"))


@bp.route("/consent/<int:req_id>/resend", methods=["POST"])
@doctor_required
def resend_consent_otp(req_id):
    """Reissue the code on an existing, still-pending request rather than
    creating a second ConsentRequest for the same visit (which is what
    calling request_consent() again would do). The patient-side terminal
    has its own equivalent of this (routes/patient.resend_consent_otp) for
    anyone still logged into their kiosk session; this is the same action
    for a doctor whose patient is not."""
    doctor = current_doctor()
    req = ConsentRequest.query.get_or_404(req_id)
    if req.doctor_id != doctor.id:
        abort(403)
    if req.status != "requested":
        flash("This request has already been decided.", "warn")
        return redirect(request.referrer or url_for("clinician.queue"))

    code = abdm.issue_otp(f"consent:{req.id}")
    req.otp = code
    log("consent_otp_resent", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"patient:{req.patient_id}",
        consent_id=req.id)
    db.session.commit()
    hint = abdm.demo_otp_hint()
    flash("New code issued." + (f" Mock service: the code is {hint}." if hint else ""), "ok")
    return redirect(request.referrer or url_for("clinician.queue"))


@bp.route("/patients", methods=["GET", "POST"])
@doctor_required
def patients():
    """Look up a patient by the ABHA address they give at the desk.

    This is the real front-desk workflow. A patient arrives, reads out their
    ABHA address, and the practitioner needs to either find them or enrol them
    and then ask for access. Without this the console could only ever see
    patients who had already completed an intake at the terminal.
    """
    doctor = current_doctor()
    query = (request.args.get("q") or "").strip().lower()

    if request.method == "POST" and request.form.get("action") == "register":
        abha = abdm.normalise_abha(request.form.get("abha"))
        if not abha:
            flash("An ABHA address is needed to create a record.", "error")
            return redirect(url_for("clinician.patients"))
        if Patient.query.filter_by(abha_address=abha).first():
            flash("That ABHA address already has a record. It is shown below.",
                  "warn")
            return redirect(url_for("clinician.patients", q=abha))

        patient = Patient(
            abha_address=abha,
            name=(request.form.get("name") or "").strip() or "Unnamed patient",
            age=_safe_int(request.form.get("age"), None),
            sex=request.form.get("sex") or "unknown",
            phone_last4=(request.form.get("phone") or "")[-4:],
            preferred_language=request.form.get("language") or "hi",
        )
        db.session.add(patient)
        db.session.commit()
        log("patient_enrolled_at_desk", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=f"patient:{patient.id}",
            detail=abha)
        db.session.commit()
        flash(f"{patient.name} enrolled. Request access below, then send them "
              f"to the terminal to approve it and complete their intake.", "ok")
        return redirect(url_for("clinician.patients", q=abha))

    results = []
    if query:
        like = f"%{query}%"
        found = Patient.query.filter(
            db.or_(Patient.abha_address.ilike(like),
                   Patient.name.ilike(like))).limit(20).all()
        for patient in found:
            consent = _has_access(doctor, patient.id)
            open_req = ConsentRequest.query.filter_by(
                doctor_id=doctor.id, patient_id=patient.id,
                status="requested").first()
            latest = CaseEntry.query.filter_by(patient_id=patient.id)\
                .order_by(CaseEntry.id.desc()).first()
            results.append({"patient": patient, "consent": consent,
                            "open_request": open_req, "case": latest})

    return render_template("clinician/patients.html", doctor=doctor,
                           query=request.args.get("q", ""), results=results,
                           searched=bool(query))


# ---------------------------------------------------------------------------
# Live ontology editor - the on-stage structural change
# ---------------------------------------------------------------------------

@bp.route("/ontology", methods=["GET", "POST"])
@doctor_required
def ontology():
    doctor = current_doctor()

    if request.method == "POST":
        options = []
        for label in request.form.getlist("option_label"):
            label = label.strip()
            if label:
                options.append({
                    "value": label.lower().replace(" ", "_")[:40],
                    "label_en": label, "label_hi": label, "label_mr": label,
                })
        node = QuestionNode(
            node_id=request.form.get("node_id", "").strip()
            or f"custom_{int(utcnow().timestamp())}",
            section=request.form.get("section", "hpi"),
            order_index=_safe_int(request.form.get("order_index"), 95),
            prompt_en=request.form.get("prompt_en", "").strip(),
            prompt_hi=request.form.get("prompt_hi", "").strip() or None,
            prompt_mr=request.form.get("prompt_mr", "").strip() or None,
            input_type=request.form.get("input_type", "choice"),
            options=options,
            complaint_tag=request.form.get("complaint_tag", "").strip() or None,
            socrates_slot=request.form.get("socrates_slot", "").strip() or None,
            parent_node=request.form.get("parent_node", "").strip() or None,
            show_if_value=request.form.get("show_if_value", "").strip() or None,
            active=True,
        )
        if not node.prompt_en:
            flash("A question needs text before it can go live.", "error")
            return redirect(url_for("clinician.ontology"))
        db.session.add(node)
        db.session.commit()
        log("ontology_node_added", actor_type="doctor", actor_id=doctor.id,
            actor_label=doctor.name, target=node.node_id,
            detail=f"section={node.section} complaint={node.complaint_tag}")
        db.session.commit()
        flash(f"'{node.prompt_en}' is live. The next patient who selects "
              f"{node.complaint_tag or 'any complaint'} will be asked it.", "ok")
        return redirect(url_for("clinician.ontology"))

    nodes = QuestionNode.query.order_by(QuestionNode.section,
                                        QuestionNode.order_index).all()
    grouped = {}
    for node in nodes:
        grouped.setdefault(node.section, []).append(node)
    return render_template("clinician/ontology.html", grouped=grouped,
                           labels=SECTION_LABELS, doctor=doctor,
                           total=len(nodes))


@bp.route("/ontology/<int:node_id>/toggle", methods=["POST"])
@doctor_required
def toggle_node(node_id):
    node = QuestionNode.query.get_or_404(node_id)
    node.active = not node.active
    log("ontology_node_toggled", actor_type="doctor",
        actor_id=current_doctor().id, actor_label=current_doctor().name,
        target=node.node_id, detail=f"active={node.active}")
    db.session.commit()
    return redirect(url_for("clinician.ontology"))


# ---------------------------------------------------------------------------
# Exports and audit
# ---------------------------------------------------------------------------

@bp.route("/case/<int:case_id>/fhir")
@doctor_required
def fhir_export(case_id):
    doctor = current_doctor()
    case = CaseEntry.query.get_or_404(case_id)
    consent = _has_access(doctor, case.patient_id)
    if not consent:
        abort(403)
    uploads = PrescriptionUpload.query.filter_by(case_id=case.id).all()
    bundle = fhir.build_bundle(case, case.patient, doctor, uploads,
                               case.summary_text, consent)
    log("fhir_exported", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"case:{case.id}", consent_id=consent.id)
    db.session.commit()
    return Response(json.dumps(bundle, indent=2),
                    mimetype="application/fhir+json",
                    headers={"Content-Disposition":
                             f'attachment; filename="case-{case.id}-fhir.json"'})


@bp.route("/case/<int:case_id>/pdf")
@doctor_required
def pdf_export(case_id):
    doctor = current_doctor()
    case = CaseEntry.query.get_or_404(case_id)
    consent = _has_access(doctor, case.patient_id)
    if not consent:
        abort(403)
    uploads = PrescriptionUpload.query.filter_by(case_id=case.id).all()

    from services.pdf import build_case_pdf
    buf = io.BytesIO()
    build_case_pdf(buf, case, case.patient, doctor, uploads)
    buf.seek(0)
    log("pdf_exported", actor_type="doctor", actor_id=doctor.id,
        actor_label=doctor.name, target=f"case:{case.id}", consent_id=consent.id)
    db.session.commit()
    return Response(buf.read(), mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="case-sheet-{case.id}.pdf"'})


@bp.route("/audit")
@doctor_required
def audit():
    entries = AccessLog.query.order_by(AccessLog.id.desc()).limit(200).all()
    return render_template("clinician/audit.html", entries=entries,
                           doctor=current_doctor())


@bp.route("/api/terminology")
@doctor_required
def terminology():
    return jsonify(search_terminology(request.args.get("q", ""),
                                      complaint=request.args.get("complaint")))


@bp.route("/api/triage-rules")
@doctor_required
def triage_rules():
    return jsonify([{k: r[k] for k in ("id", "level", "label", "reason", "action")}
                    for r in redflags.RULES])