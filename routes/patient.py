"""The waiting-area terminal.

One question per screen, large targets, every question answerable by speaking
or tapping. Nothing here assumes the patient owns a phone, can read, or has
used software before.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.utils import secure_filename

from models import (CaseEntry, ConsentRequest, Doctor, Patient,
                    PrescriptionUpload, db, log, utcnow)
from services import abdm, extraction, i18n, redflags, summary
from services import intake as engine
from services.clinical import suggest_codes

flash_key = i18n.flash_key

bp = Blueprint("patient", __name__, url_prefix="/patient")

LANGUAGES = [
    {"code": "hi", "label": "हिंदी", "english": "Hindi", "speech": "hi-IN"},
    {"code": "mr", "label": "मराठी", "english": "Marathi", "speech": "mr-IN"},
    {"code": "en", "label": "English", "english": "English", "speech": "en-IN"},
]
SPEECH_LOCALE = {l["code"]: l["speech"] for l in LANGUAGES}


def current_patient():
    pid = session.get("patient_id")
    return Patient.query.get(pid) if pid else None


def current_case():
    cid = session.get("case_id")
    return CaseEntry.query.get(cid) if cid else None


def patient_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_patient():
            return redirect(url_for("patient.start"))
        return view(*args, **kwargs)
    return wrapped


def case_required(view):
    @wraps(view)
    @patient_required
    def wrapped(*args, **kwargs):
        if not current_case():
            return redirect(url_for("patient.consent"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Step 1 - language and identity
# ---------------------------------------------------------------------------

@bp.route("/", methods=["GET", "POST"])
def start():
    if request.method == "POST":
        chosen = request.form.get("language", "hi")
        # Both session keys, always together. ui_lang is what
        # i18n.resolve_locale() reads (and so what the context processor's
        # t/lang are built from on every subsequent request, including the
        # very next one); language is the kiosk's own long-standing key,
        # read directly by a few patient-identity routes below. A patient who
        # opens the kiosk directly, skipping the marketing landing page, only
        # ever passes through here — if this route only set one of the two,
        # t() and the displayed language could permanently disagree for that
        # entire session.
        if chosen in i18n.SUPPORTED:
            session["ui_lang"] = chosen
        session["language"] = chosen
        return redirect(url_for("patient.identify"))
    return render_template("patient/start.html", languages=LANGUAGES)


@bp.route("/identify", methods=["GET", "POST"])
def identify():
    lang = session.get("language") or i18n.resolve_locale()
    if request.method == "POST":
        abha = abdm.normalise_abha(request.form.get("abha"))
        patient = Patient.query.filter_by(abha_address=abha).first()
        if not patient:
            flash(flash_key("flash_no_record"), "warn")
            return redirect(url_for("patient.identify"))
        session["pending_patient"] = patient.id
        abdm.issue_otp(abha)
        log("otp_issued", actor_type="system", target=abha)
        db.session.commit()
        return redirect(url_for("patient.verify"))

    return render_template("patient/identify.html", lang=lang,
                           demo=Patient.query.limit(4).all(),
                           mock=abdm.mock_mode())


@bp.route("/register", methods=["GET", "POST"])
def register():
    lang = session.get("language") or i18n.resolve_locale()
    if request.method == "POST":
        abha = abdm.normalise_abha(request.form.get("abha"))
        if Patient.query.filter_by(abha_address=abha).first():
            flash(flash_key("flash_already_registered"), "warn")
            return redirect(url_for("patient.identify"))
        patient = Patient(
            abha_address=abha,
            name=request.form.get("name", "").strip() or "Unnamed patient",
            age=_as_int(request.form.get("age")),
            sex=request.form.get("sex") or "unknown",
            phone_last4=(request.form.get("phone") or "")[-4:],
            preferred_language=lang,
        )
        db.session.add(patient)
        db.session.commit()
        log("patient_registered", actor_type="patient", actor_id=patient.id,
            actor_label=patient.name, target=abha)
        session["pending_patient"] = patient.id
        abdm.issue_otp(abha)
        db.session.commit()
        return redirect(url_for("patient.verify"))
    return render_template("patient/register.html", lang=lang)


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    pid = session.get("pending_patient")
    patient = Patient.query.get(pid) if pid else None
    if not patient:
        return redirect(url_for("patient.identify"))

    if request.method == "POST":
        if abdm.verify_otp(patient.abha_address, request.form.get("otp")):
            session["patient_id"] = patient.id
            session.pop("pending_patient", None)
            log("patient_signed_in", actor_type="patient", actor_id=patient.id,
                actor_label=patient.name)
            db.session.commit()
            return redirect(url_for("patient.home"))
        flash(flash_key("flash_otp_mismatch"), "error")

    return render_template("patient/verify.html", patient=patient,
                           hint=abdm.demo_otp_hint())


@bp.route("/home")
@patient_required
def home():
    """What the patient sees straight after signing in.

    Previously sign-in dropped the patient directly into a new intake, which
    meant a patient who came to the terminal only to approve a practitioner's
    request had no way to reach that screen. Pending requests now surface
    here, before anything else.
    """
    patient = current_patient()
    pending = ConsentRequest.query.filter_by(
        patient_id=patient.id, status="requested").order_by(
        ConsentRequest.requested_at.desc()).all()
    live = [r for r in ConsentRequest.query.filter_by(
        patient_id=patient.id, status="granted").all() if r.is_live]
    recent = CaseEntry.query.filter_by(patient_id=patient.id).order_by(
        CaseEntry.id.desc()).limit(3).all()
    return render_template("patient/home.html", patient=patient,
                           pending=pending, live=live, recent=recent,
                           lang=session.get("language") or patient.preferred_language or i18n.resolve_locale())


# ---------------------------------------------------------------------------
# Step 2 - consent, explained aloud
# ---------------------------------------------------------------------------

CONSENT_TEXT = {
    "en": ("This terminal will ask you about your health and read any papers "
           "you upload. Your answers go only to the doctor you see today. "
           "Nothing is shared with anyone else unless you approve it. You can "
           "stop at any time and still see the doctor."),
    "hi": ("यह मशीन आपसे आपकी सेहत के बारे में पूछेगी और आपके कागज़ पढ़ेगी। आपके जवाब "
           "सिर्फ़ आज के डॉक्टर तक जाएँगे। आपकी मंज़ूरी के बिना किसी और को नहीं दिए जाएँगे। "
           "आप कभी भी रोक सकते हैं, फिर भी डॉक्टर से मिल सकते हैं।"),
    "mr": ("हे यंत्र तुम्हाला तुमच्या तब्येतीबद्दल विचारेल आणि तुमचे कागद वाचेल. तुमची उत्तरे "
           "फक्त आजच्या डॉक्टरांपर्यंत जातील. तुमच्या परवानगीशिवाय इतर कोणालाही दिली जाणार "
           "नाहीत. तुम्ही कधीही थांबू शकता, तरीही डॉक्टरांना भेटू शकता."),
}


@bp.route("/consent", methods=["GET", "POST"])
@patient_required
def consent():
    patient = current_patient()
    lang = (session.get("language") or patient.preferred_language
            or i18n.resolve_locale())

    if request.method == "POST":
        if request.form.get("agree") != "yes":
            flash(flash_key("flash_consent_required"), "warn")
            return redirect(url_for("patient.consent"))
        case = CaseEntry(
            patient_id=patient.id,
            mode=request.form.get("mode", "ayush"),
            language=lang,
            consent_given=True,
            consent_purpose="Pre-consultation clinical history for today's OPD visit",
        )
        db.session.add(case)
        db.session.commit()
        session["case_id"] = case.id
        log("consent_recorded", actor_type="patient", actor_id=patient.id,
            actor_label=patient.name, target=f"case:{case.id}",
            detail=case.consent_purpose)
        db.session.commit()
        return redirect(url_for("patient.intake"))

    return render_template("patient/consent.html", patient=patient, lang=lang,
                           text=CONSENT_TEXT.get(lang, CONSENT_TEXT["en"]),
                           speech_locale=SPEECH_LOCALE.get(lang, "hi-IN"))


# ---------------------------------------------------------------------------
# Step 3 - the adaptive interview
# ---------------------------------------------------------------------------

@bp.route("/interview")
@case_required
def intake():
    case = current_case()
    lang = case.language
    node, answered, total = _next_for(case)

    if node is None:
        return redirect(url_for("patient.documents"))

    return render_template(
        "patient/question.html",
        node=node,
        prompt=_prompt(node, lang),
        options=_options(node, lang),
        answered=answered,
        total=total,
        percent=int((answered / total) * 100) if total else 0,
        lang=lang,
        speech_locale=SPEECH_LOCALE.get(lang, "hi-IN"),
        case=case,
        section_label=engine.SECTION_LABELS.get(node.section, node.section),
    )


def _next_for(case):
    return engine.next_node(case.answers or {}, case.chief_complaint, case.mode)


def _prompt(node, lang):
    return engine.localized_prompt(node, lang)


def _options(node, lang):
    return engine.localized_options(node, lang)


@bp.route("/answer", methods=["POST"])
@case_required
def answer():
    case = current_case()
    node_id = request.form.get("node_id")
    node = next((n for n in engine.build_plan(case.answers or {},
                                              case.chief_complaint, case.mode)
                 if n.node_id == node_id), None)
    if node is None:
        return redirect(url_for("patient.intake"))

    source = request.form.get("source", "touch")
    raw = request.form.get("raw_transcript", "")
    confidence = float(request.form.get("confidence") or (0.7 if source == "voice" else 1.0))

    if node.input_type == "multi":
        value = request.form.getlist("value")
        if not value:
            value = ["none"]
    else:
        value = request.form.get("value", "").strip()
        if not value and node.input_type == "text":
            value = raw.strip()

    answers = dict(case.answers or {})
    answers[node_id] = {
        "value": value,
        "label": engine.label_for(node, value) if node.options else value,
        "source": source,
        "confidence": round(confidence, 2),
        "raw": raw,
        "at": utcnow().isoformat(),
    }
    case.answers = answers

    if node_id == "cc_main":
        case.chief_complaint = value if isinstance(value, str) else (value or [None])[0]

    # Triage is re-evaluated on every single answer, not only at the end.
    level, flags = redflags.evaluate(case, current_patient())
    was = case.triage
    case.triage = level
    case.red_flags = flags
    db.session.commit()

    if level == "emergency" and was != "emergency":
        log("red_flag_raised", actor_type="system", target=f"case:{case.id}",
            detail="; ".join(f["label"] for f in flags if f["level"] == "emergency"))
        db.session.commit()
        return redirect(url_for("patient.red_flag"))

    return redirect(url_for("patient.intake"))


@bp.route("/back", methods=["POST"])
@case_required
def go_back():
    """Undo the last answer. Elderly users mis-tap; make it recoverable."""
    case = current_case()
    answers = dict(case.answers or {})
    if answers:
        last = max(answers.items(), key=lambda kv: kv[1].get("at", ""))
        answers.pop(last[0], None)
        case.answers = answers
        if last[0] == "cc_main":
            case.chief_complaint = None
        level, flags = redflags.evaluate(case, current_patient())
        case.triage, case.red_flags = level, flags
        db.session.commit()
    return redirect(url_for("patient.intake"))


@bp.route("/urgent")
@case_required
def red_flag():
    case = current_case()
    emergencies = [f for f in (case.red_flags or []) if f["level"] == "emergency"]
    return render_template("patient/red_flag.html", case=case,
                           flags=emergencies, lang=case.language)


# ---------------------------------------------------------------------------
# Step 4 - documents
# ---------------------------------------------------------------------------

@bp.route("/documents", methods=["GET", "POST"])
@case_required
def documents():
    case = current_case()
    patient = current_patient()

    if request.method == "POST":
        file = request.files.get("document")
        if not file or not file.filename:
            flash(flash_key("flash_choose_file"), "warn")
            return redirect(url_for("patient.documents"))

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
            flash(flash_key("flash_bad_filetype"), "error")
            return redirect(url_for("patient.documents"))

        folder = current_app.config["UPLOAD_FOLDER"]
        os.makedirs(folder, exist_ok=True)
        safe = secure_filename(f"{patient.id}_{utcnow().timestamp():.0f}_{file.filename}")
        path = os.path.join(folder, safe)
        file.save(path)

        payload, source, confidence = extraction.extract_document(path)
        upload = PrescriptionUpload(
            patient_id=patient.id,
            case_id=case.id,
            filename=safe,
            doc_type=payload.get("doc_type") or request.form.get("doc_type", "prescription"),
            document_date=_as_date(payload.get("document_date")),
            extracted=payload,
            extraction_source=source,
            confidence=confidence,
            status="pending_review",
        )
        db.session.add(upload)
        db.session.commit()
        log("document_digitized", actor_type="system", target=f"upload:{upload.id}",
            detail=f"source={source} confidence={confidence:.2f} "
                   f"meds={len(payload.get('medications', []))}")
        db.session.commit()
        flash(flash_key("flash_paper_received"), "ok")
        return redirect(url_for("patient.documents"))

    uploads = PrescriptionUpload.query.filter_by(case_id=case.id)\
        .order_by(PrescriptionUpload.uploaded_at).all()
    return render_template("patient/documents.html", case=case,
                           timeline=extraction.timeline(uploads),
                           lang=case.language)


def _as_int(raw, default=None):
    """A stray character in a number field must not 500 the registration."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if 0 < value <= 130 else default


def _as_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Step 5 - submit
# ---------------------------------------------------------------------------

@bp.route("/submit", methods=["POST"])
@case_required
def submit():
    case = current_case()
    patient = current_patient()
    uploads = PrescriptionUpload.query.filter_by(case_id=case.id).all()

    text, source = summary.generate(case, patient, uploads)
    case.summary_text = text
    case.summary_source = source
    case.status = "awaiting_review"
    case.submitted_at = utcnow()

    suggestions = suggest_codes(case)
    if suggestions:
        top = suggestions[0]
        case.namaste_code = top["code"]
        case.namaste_term = top["term"]
        case.icd11_tm2_code = top["icd11_tm2_code"]
        case.icd11_biomed_code = top["icd11_biomed_code"]

    db.session.commit()
    log("case_submitted", actor_type="patient", actor_id=patient.id,
        actor_label=patient.name, target=f"case:{case.id}",
        detail=f"summary_source={source} triage={case.triage}")
    db.session.commit()

    session["last_case"] = case.id
    session.pop("case_id", None)

    # Emergency cases skip doctor selection entirely — they already went
    # through /urgent, which tells the patient to show staff immediately;
    # a browse-the-doctors screen would only slow that down. Every other
    # case (routine/priority) gets the picker.
    if case.triage == "emergency":
        return redirect(url_for("patient.done", case_id=case.id))
    return redirect(url_for("patient.choose_doctor", case_id=case.id))


@bp.route("/choose-doctor/<int:case_id>", methods=["GET", "POST"])
@patient_required
def choose_doctor(case_id):
    """Let the patient pick which doctor's queue to join.

    Reached right after intake is submitted (see submit() above) and
    before the final done() screen. Sets CaseEntry.chosen_doctor_id, which
    is what scopes a practitioner's queue to "patients who picked me" (see
    routes/clinician.queue) — a separate field from doctor_id (set only
    when a doctor later CONFIRMS the case sheet) and attended_by (set when
    a doctor marks the patient as seen); see the comment on
    CaseEntry.chosen_doctor_id in models.py for why these three doctor
    references on a case are deliberately not the same field.

    Picking a doctor is optional — a "Skip, any doctor" link goes straight
    to done() with chosen_doctor_id left unset, and every existing queue/
    consent/attended workflow already handles that case today (a case
    with no chosen doctor just doesn't show up filtered into anyone's
    "my patients" view; any doctor can still find and request access to
    it via Find patient, exactly as before this feature existed).
    """
    case = CaseEntry.query.get_or_404(case_id)
    if case.patient_id != session.get("patient_id"):
        abort(403)
    # Already decided (page refreshed, back-button, etc.) — nothing left
    # to choose, move on rather than let the pick be changed after the
    # fact from this screen.
    if case.chosen_doctor_id or case.triage == "emergency":
        return redirect(url_for("patient.done", case_id=case.id))

    if request.method == "POST":
        if request.form.get("action") == "skip":
            return redirect(url_for("patient.done", case_id=case.id))
        doctor_id = _safe_int_patient(request.form.get("doctor_id"))
        doctor = Doctor.query.get(doctor_id) if doctor_id else None
        if not doctor:
            flash(flash_key("flash_choose_doctor_required"), "warn")
            return redirect(url_for("patient.choose_doctor", case_id=case.id))
        case.chosen_doctor_id = doctor.id
        db.session.commit()
        log("doctor_chosen_by_patient", actor_type="patient",
            actor_id=case.patient_id, target=f"case:{case.id}",
            detail=f"doctor:{doctor.id}")
        db.session.commit()
        return redirect(url_for("patient.done", case_id=case.id))

    doctors = Doctor.query.order_by(Doctor.name).all()
    waiting_counts = _doctor_waiting_counts()
    rows = [{"doctor": d, "waiting": waiting_counts.get(d.id, 0)}
            for d in doctors]
    return render_template("patient/choose_doctor.html", case=case,
                           patient=current_patient(), rows=rows,
                           lang=case.language)


def _doctor_waiting_counts():
    """{doctor_id: count} of cases currently in each doctor's queue — same
    definition of "waiting" as routes/clinician.queue's default tab
    (status in awaiting_review/confirmed, not yet attended), so the number
    a patient sees here always matches what the doctor's own queue shows."""
    waiting = CaseEntry.query.filter(
        CaseEntry.status.in_(["awaiting_review", "confirmed"]),
        CaseEntry.attended_at.is_(None),
        CaseEntry.chosen_doctor_id.isnot(None),
    ).all()
    counts = {}
    for c in waiting:
        counts[c.chosen_doctor_id] = counts.get(c.chosen_doctor_id, 0) + 1
    return counts


def _safe_int_patient(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@bp.route("/done/<int:case_id>")
@patient_required
def done(case_id):
    case = CaseEntry.query.get_or_404(case_id)
    if case.patient_id != session.get("patient_id"):
        abort(403)
    token = 100 + case.id
    chosen_doctor = (Doctor.query.get(case.chosen_doctor_id)
                     if case.chosen_doctor_id else None)
    return render_template("patient/done.html", case=case, token=token,
                           patient=current_patient(), lang=case.language,
                           chosen_doctor=chosen_doctor)


# ---------------------------------------------------------------------------
# Consent manager - the patient's own control panel
# ---------------------------------------------------------------------------

@bp.route("/requests")
@patient_required
def requests_list():
    patient = current_patient()
    items = ConsentRequest.query.filter_by(patient_id=patient.id)\
        .order_by(ConsentRequest.requested_at.desc()).all()
    return render_template("patient/requests.html", requests=items,
                           patient=patient, hint=abdm.demo_otp_hint())


@bp.route("/requests/<int:req_id>/decide", methods=["POST"])
@patient_required
def decide_request(req_id):
    patient = current_patient()
    req = ConsentRequest.query.get_or_404(req_id)
    if req.patient_id != patient.id:
        abort(403)

    decision = request.form.get("decision")
    if decision == "grant":
        if not abdm.verify_otp(f"consent:{req.id}", request.form.get("otp")):
            flash(flash_key("flash_consent_otp_mismatch"), "error")
            return redirect(url_for("patient.requests_list"))
        req.grant(current_app.config["CONSENT_DEFAULT_HOURS"])
        log("consent_granted", actor_type="patient", actor_id=patient.id,
            actor_label=patient.name, target=f"doctor:{req.doctor_id}",
            consent_id=req.id, detail=req.purpose)
        flash(flash_key("flash_access_granted", doctor=req.doctor.name,
                        until=req.expires_at.strftime('%d %b, %H:%M')), "ok")
    elif decision == "deny":
        req.status = "denied"
        req.decided_at = utcnow()
        log("consent_denied", actor_type="patient", actor_id=patient.id,
            actor_label=patient.name, target=f"doctor:{req.doctor_id}",
            consent_id=req.id)
        flash(flash_key("flash_request_declined"), "ok")
    elif decision == "revoke":
        req.status = "revoked"
        req.revoked_at = utcnow()
        log("consent_revoked", actor_type="patient", actor_id=patient.id,
            actor_label=patient.name, target=f"doctor:{req.doctor_id}",
            consent_id=req.id)
        flash(flash_key("flash_access_withdrawn"), "ok")

    db.session.commit()
    return redirect(url_for("patient.requests_list"))


@bp.route("/requests/<int:req_id>/otp", methods=["POST"])
@patient_required
def resend_consent_otp(req_id):
    req = ConsentRequest.query.get_or_404(req_id)
    if req.patient_id != session.get("patient_id"):
        abort(403)
    code = abdm.issue_otp(f"consent:{req.id}")
    req.otp = code
    db.session.commit()
    hint = abdm.demo_otp_hint()
    last4 = req.patient.phone_last4 or "****"
    msg = flash_key("flash_code_sent", last4=last4)
    if hint:
        # Two translated fragments concatenated, rather than one key with a
        # conditional clause baked into three languages of prose — simpler to
        # keep both pieces independently correct.
        msg = msg + "\x1f" + flash_key("flash_code_sent_mock", code=hint)
    flash(msg, "ok")
    return redirect(url_for("patient.requests_list"))


@bp.route("/leave")
def leave():
    session.clear()
    return redirect(url_for("main.landing"))
