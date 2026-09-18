"""Swasthya Kosh — pre-consultation clinical intake for AYUSH OPDs.

Run it:
    python app.py

The app boots even with no Supabase URL and no API key. It will tell you what
mode it is in on startup and on the /status page.
"""
import os
import sys
from pathlib import Path

from flask import Flask, render_template

from config import BASE_DIR, Config
from models import db
from routes.clinician import bp as clinician_bp
from routes.main import bp as main_bp
from routes.patient import bp as patient_bp
from routes.speech import bp as speech_bp
from services import ai, i18n


def create_app(config_object=Config):
    # Vercel's zero-config Python runtime promotes a top-level public/**
    # directory to its CDN and serves it without ever invoking this
    # function — faster than round-tripping every CSS/JS request through
    # a cold Python process, and free of charge against function compute.
    # Flask's OWN static_folder, by contrast, is explicitly ignored for
    # static files on Vercel (per Vercel's Flask deployment docs) — files
    # would 404 in production if left in the default ./static location.
    # Pointing static_folder at public/static, with static_url_path left
    # at the Flask default of "/static", keeps every existing
    # url_for('static', filename=...) call across every template
    # producing the exact same "/static/..." URL as before; only the
    # physical folder moved, nothing in the templates needed to change.
    # Locally (`python app.py`), Flask still serves these files itself
    # from the same folder, so local development is unaffected either way.
    app = Flask(__name__, static_folder=str(BASE_DIR / "public" / "static"),
               static_url_path="/static")
    app.config.from_object(config_object)

    # Vercel's Python runtime (and most serverless platforms) mounts
    # everything except /tmp read-only. Writing folders next to the code
    # — completely normal for a server you run yourself — crashes the
    # import here instead, before any route ever runs. Vercel sets the
    # VERCEL env var automatically, so this only changes behavior there;
    # local development is unaffected.
    #
    # /tmp is writable but wiped between invocations, so this makes the
    # import succeed without making file uploads or local SQLite actually
    # work in production — see the deployment note in README.md for what
    # still needs a real fix (Supabase for the database via DATABASE_URL,
    # and a real file-storage service instead of local disk for uploads).
    if os.getenv("VERCEL"):
        import tempfile
        instance_dir = Path(tempfile.gettempdir()) / "swasthya-kosh-instance"
        upload_dir = Path(tempfile.gettempdir()) / "swasthya-kosh-uploads"
        app.config["UPLOAD_FOLDER"] = upload_dir
    else:
        instance_dir = BASE_DIR / "instance"
        upload_dir = app.config["UPLOAD_FOLDER"]
    os.makedirs(instance_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)

    db.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(clinician_bp)
    app.register_blueprint(speech_bp)

    @app.context_processor
    def inject_globals():
        # Resolved once per request and handed to every template, including
        # error pages, without each route having to pass t/lang itself. A
        # route that wants to override the language (e.g. after the patient
        # explicitly switches) still can, by passing lang=... explicitly to
        # render_template — an explicit kwarg always wins over a context
        # processor value in Jinja.
        lang = i18n.resolve_locale()
        t = i18n.translator(lang)
        return {
            "ai_label": ai.status_label(),
            "ai_on": ai.available(),
            "db_label": "Supabase" if app.config["USING_POSTGRES"] else "SQLite",
            "abdm_mock": app.config["MOCK_ABDM"],
            "t": t,
            "th": i18n.translator_html(lang),
            "lang": lang,
            "speech_locale": i18n.speech_locale(lang),
            "languages": i18n.available_languages(),
            # Bound to this request's t so templates call resolve_flash(msg)
            # without also having to pass t through explicitly.
            "resolve_flash": lambda raw: i18n.resolve_flash(t, raw),
        }

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403,
                               title="No live consent for this record",
                               body="A practitioner can only open a record "
                                    "while the patient's consent is active. "
                                    "Request access, or ask the patient to "
                                    "approve it on the terminal."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               title="Nothing here",
                               body="That page does not exist. Head back to "
                                    "the start."), 404

    @app.errorhandler(500)
    def server_error(exc):
        # In debug mode Flask shows its own debugger and never reaches this.
        # Set DEBUG=false in .env before a demo so a crash shows this page
        # instead of a stack trace on a projector.
        app.logger.exception("Unhandled error: %s", exc)
        return render_template("error.html", code=500,
                               title="Something went wrong on our side",
                               body="The problem has been logged. Go back and "
                                    "try again — your saved answers are "
                                    "unaffected."), 500

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", code=413,
                               title="That file is too large",
                               body="Uploads are capped at 12 MB. Take the "
                                    "photo again at a lower resolution."), 413

    with app.app_context():
        try:
            db.create_all()
        except Exception as exc:  # noqa: BLE001
            # Almost always a wrong Supabase password or the Direct connection
            # string instead of the Session pooler. Say so, instead of dumping
            # a driver traceback on someone at 2am before submission.
            print("\n  Could not reach the database.")
            print(f"  {type(exc).__name__}: {str(exc)[:180]}")
            print("\n  Check DATABASE_URL in .env:")
            print("    - use the Session pooler URI, not Direct connection")
            print("    - replace [YOUR-PASSWORD] with your real password")
            print("    - percent-encode any @ or # in the password")
            print("  Or clear DATABASE_URL entirely to run on local SQLite.\n")
        else:
            try:
                _sync_schema()
            except Exception as exc:  # noqa: BLE001
                # Same reasoning as the seed try/except below: a schema-sync
                # problem should never take the whole app down. Worse to 500
                # every request than to boot with a stale column missing once
                # (which will now surface as a normal, catchable error on the
                # one route that touches it, instead of every route).
                print(f"\n  Schema sync skipped: {type(exc).__name__}: {str(exc)[:180]}\n")

            # Auto-seed demo data (practitioners, patients, ontology, etc.)
            # whenever the practitioners table is empty. This is what makes
            # the practitioner console log-in-able the moment the app boots,
            # with no separate `flask seed` step to remember — essential on
            # Vercel, where /tmp SQLite is wiped on every cold start and
            # nobody is sitting at a terminal to run a CLI command before a
            # judge opens the link. Guarded by a row-count check (not a
            # flag) so it is always safe to call: a warm instance with data
            # already in place just skips it.
            try:
                from models import Doctor
                if Doctor.query.count() == 0:
                    from seed import run_seed
                    run_seed()
            except Exception as exc:  # noqa: BLE001
                # Never let a seeding problem take the whole app down —
                # worse to 500 every request than to boot with an empty
                # practitioner table once.
                print(f"\n  Auto-seed skipped: {type(exc).__name__}: {str(exc)[:180]}\n")

    return app


def _sync_schema():
    """Add any model columns missing from an already-existing table.

    This project has no Alembic/migration framework (see README) — the
    whole story until now was db.create_all(), which only creates tables
    that don't exist yet and never touches one that's already there. That
    is fine the first time anyone runs the app, and silently wrong forever
    after: add a column to a model (attended_at/attended_by on CaseEntry,
    say) and every existing SQLite file or Supabase database on a
    teammate's machine keeps the old shape until someone remembers to run
    an ALTER TABLE by hand — which is exactly how "no such column:
    case_entry.attended_at" reaches a browser instead of a terminal.

    This walks every mapped model, compares its columns against what the
    live database actually has (via SQLAlchemy's inspector, which speaks
    both SQLite and Postgres), and issues a plain ADD COLUMN for anything
    missing. It never drops or alters an existing column and never touches
    a table that matches already, so it is safe to run on every boot — a
    database that's already up to date does nothing here. It is not a
    substitute for a real migration tool if this project ever needs to
    rename or remove a column, only for the additive case, which is the
    only kind of change this codebase has made so far.

    Must be called inside an app context — reads db.engine, which needs
    the app's config (the database URL) to exist.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    added = []

    # Use the model metadata directly; Flask-SQLAlchemy's Model type does
    # not expose ``registry`` to static type checkers.
    for table in db.Model.metadata.tables.values():
        if table.name not in existing_tables:
            continue  # a brand-new table: create_all() already made it whole
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            coltype = column.type.compile(dialect=db.engine.dialect)
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {coltype}"
            with db.engine.begin() as conn:
                conn.execute(text(ddl))
            added.append(f"{table.name}.{column.name}")

    if added:
        print(f"\n  Schema sync: added column(s) {', '.join(added)}\n")


app = create_app()


@app.cli.command("seed")
def seed_command():
    """Load the ontology, terminology, interactions and demo personas."""
    from seed import run_seed
    run_seed()


def _free_port(preferred=5002):
    """Find a port we can actually bind.

    The kiosk defaults to 5002 (macOS runs AirPlay Receiver on 5000, and
    5001 is a common conflict too). Rather than failing with "address
    already in use", step to the next free port and print where we landed.
    """
    import socket
    candidates = [preferred, 5000, 5001, 5050, 8000]
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def _banner(port):
    with app.app_context():
        mode_db = "Supabase Postgres" if app.config["USING_POSTGRES"] \
            else "SQLite (offline fallback)"
        mode_ai = ai.status_label()
    base = f"http://127.0.0.1:{port}"
    print("\n" + "=" * 62)
    print("  Swasthya Kosh - pre-consultation clinical intake")
    print("=" * 62)
    print(f"  Database : {mode_db}")
    print(f"  AI       : {mode_ai}")
    print(f"  ABDM     : {'mock identity service' if app.config['MOCK_ABDM'] else 'sandbox'}")
    if port != 5000:
        print(f"  Note     : port 5000 was busy (AirPlay on macOS?), using {port}")
    print(f"  Landing  : {base}/")
    print(f"  Kiosk    : {base}/patient/")
    print(f"  Console  : {base}/clinician/login")
    print("=" * 62)
    print("  Use Chrome or Edge. Safari has no speech recognition.")
    print("  Practitioner: HPR-AY-44821 / demo1234")
    print("  Patient OTP : 246813")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    if "--seed" in sys.argv:
        from seed import run_seed
        with app.app_context():
            run_seed()
        sys.exit(0)
    # Werkzeug's reloader binds the socket in the PARENT process and passes
    # the file descriptor to the child. The child then re-executes this file.
    # If we probed for a free port again there, we would see our own inherited
    # socket holding 5000, pick 5001, and print a URL nothing is listening on
    # while the server carried on serving 5000. So the first process decides
    # the port and puts it in the environment; the child reads it back.
    chosen = int(os.environ.get("PORT") or _free_port())
    os.environ["PORT"] = str(chosen)

    # Only the process that actually serves should print the banner. The
    # reloader sets this variable in the child it spawns.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if is_reloader_child or not os.environ.get("FLASK_BANNER_SHOWN"):
        os.environ["FLASK_BANNER_SHOWN"] = "1"
        _banner(chosen)

    # Demo day: put DEBUG=false in .env. You lose auto-reload and gain a
    # friendly error page instead of a traceback in front of judges.
    debug = (os.getenv("DEBUG", "true").strip().lower()
             not in {"0", "false", "no", "off"})
    if not debug:
        print("  DEBUG is off: auto-reload disabled, friendly error pages on.\n")
    # services/i18n.py caches data/i18n_landing.json in memory for the whole
    # process (@lru_cache) — editing translation keys has no effect until the
    # process restarts. Werkzeug's reloader only watches .py files by
    # default, so a JSON-only edit would otherwise go unnoticed and the app
    # would keep serving the old bundle (a missing key falls back to printing
    # the key name itself — including out loud, if it's a key TTS reads).
    # Watching the file explicitly means saving it restarts the server like
    # any other source change.
    # Same reasoning as the i18n bundle above: config.py's load_dotenv() only
    # runs once at import time, so editing .env (flipping BHASHINI_ENABLED,
    # say) has no effect until the process restarts. Watching it too means
    # saving .env restarts the server automatically instead of leaving you
    # staring at a flag that looks set but isn't taking effect.
    env_path = str(BASE_DIR / ".env")
    i18n_path = str(BASE_DIR / "data" / "i18n_landing.json")
    watch_files = [i18n_path]
    if os.path.exists(env_path):
        watch_files.append(env_path)
    app.run(debug=debug, host="127.0.0.1", port=chosen,
            extra_files=watch_files if debug else None)