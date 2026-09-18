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

    # These four counts are decoration for the landing page (a few stat
    # numbers), not anything the page structurally needs. A database that
    # is unreachable — a cold Supabase instance waking up, a misconfigured
    # DATABASE_URL, a network blip on the platform — must never turn the
    # front door of the whole site into a 500. Every query here is
    # independently guarded so one failing does not take the others down
    # with it, and the page renders with whatever numbers it managed to
    # get, zero for the rest.
    def _safe_count(query_fn):
        try:
            return query_fn()
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning("Landing stat query failed: %s", exc)
            return 0

    stats = {
        "questions": _safe_count(
            lambda: QuestionNode.query.filter_by(active=True).count()),
        "codes": _safe_count(lambda: NamasteCode.query.count()),
        "rules": _safe_count(rule_count),
        "cases": _safe_count(lambda: CaseEntry.query.count()),
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

    # A diagnostic page's entire purpose is to say what is wrong — it must
    # be the one page that survives whatever it is reporting on. If the
    # database is down, db_ok above already caught that; the three counts
    # below query it again and would otherwise raise a second, unhandled
    # exception right past the point of this function, turning /status and
    # /healthz into 500s exactly when someone most needs them to load.
    def _safe_count(query_fn):
        try:
            return query_fn()
        except Exception:  # noqa: BLE001
            return None

    return {
        "database": "Supabase Postgres" if cfg["USING_POSTGRES"] else "SQLite (offline fallback)",
        "database_reachable": db_ok,
        "ai_provider": ai.status_label(),
        "ai_available": ai.available(),
        "speech_provider": bhashini.status_label(),
        "bhashini_enabled": bhashini.available(),
        "abdm": "Mock identity service" if cfg["MOCK_ABDM"] else "ABDM sandbox",
        "question_nodes": _safe_count(
            lambda: QuestionNode.query.filter_by(active=True).count()),
        "namaste_codes": _safe_count(lambda: NamasteCode.query.count()),
        "triage_rules": _safe_count(rule_count),
    }