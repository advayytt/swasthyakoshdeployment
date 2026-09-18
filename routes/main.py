from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, session, url_for)

from models import CaseEntry, NamasteCode, QuestionNode, db
from services import ai, i18n
from services.redflags import rule_count

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    # t, lang, speech_locale and languages arrive from the app-level context
    # processor (see app.py), which resolves the same way i18n.resolve_locale
    # always has: ?lang= wins, then session, then Accept-Language, then
    # English. We still persist the choice here so a kiosk visit later in the
    # same session does not re-ask.
    session["ui_lang"] = i18n.resolve_locale()
    session.setdefault("language", session["ui_lang"])

    stats = {
        "questions": QuestionNode.query.filter_by(active=True).count(),
        "codes": NamasteCode.query.count(),
        "rules": rule_count(),
        "cases": CaseEntry.query.count(),
    }
    return render_template("landing.html", stats=stats)


@bp.route("/language/<code>")
def set_language(code):
    """Switch the interface language and return to wherever the user was."""
    if code in i18n.SUPPORTED:
        session["ui_lang"] = code
        session["language"] = code
    target = request.referrer or url_for("main.landing")
    # Never follow a referrer off this host.
    if not target.startswith(request.host_url):
        target = url_for("main.landing")
    return redirect(target)


@bp.route("/status")
def status():
    return render_template("status.html", info=_system_info())


@bp.route("/healthz")
def healthz():
    return jsonify(_system_info())


def _system_info():
    from services import bhashini
    cfg = current_app.config
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "database": "Supabase Postgres" if cfg["USING_POSTGRES"] else "SQLite (offline fallback)",
        "database_reachable": db_ok,
        "ai_provider": ai.status_label(),
        "ai_available": ai.available(),
        "speech_provider": bhashini.status_label(),
        "bhashini_enabled": bhashini.available(),
        "abdm": "Mock identity service" if cfg["MOCK_ABDM"] else "ABDM sandbox",
        "question_nodes": QuestionNode.query.filter_by(active=True).count(),
        "namaste_codes": NamasteCode.query.count(),
        "triage_rules": rule_count(),
    }