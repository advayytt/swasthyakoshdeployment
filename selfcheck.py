"""Walk the entire demo path and report what breaks.

    python selfcheck.py

Run this before every rehearsal and once more on the morning of the demo, on
the actual machine you will present from. It drives the real application
through Flask's test client — no browser, no clicking — and exercises every
route a judge could reach, including the ones you are least likely to rehearse
(PDF export, the consent lock screen, the ontology editor).

It finishes in a few seconds and prints a pass/fail line per step. Anything red
is a bug you would otherwise have discovered on stage.

Note: it signs in as a demo patient and completes a real intake, so it leaves
one extra case in the database. Clean up with:

    python seed.py --reset
"""
import re
import sys
import traceback

from app import app
from models import CaseEntry, ConsentRequest, Doctor, Patient, QuestionNode, db

PASS, FAIL, WARN = [], [], []
GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def check(label, fn):
    """Run one step. A failure is recorded and never stops the run."""
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        FAIL.append((label, f"{type(exc).__name__}: {exc}",
                     traceback.format_exc()))
        print(f"  {RED}FAIL{RESET}  {label}\n        {type(exc).__name__}: {exc}")
        return None

    if result is True or result is None:
        PASS.append(label)
        print(f"  {GREEN}ok{RESET}    {label}")
    elif isinstance(result, str) and result.startswith("warn:"):
        WARN.append((label, result[5:].strip()))
        print(f"  {YELLOW}warn{RESET}  {label}\n        {result[5:].strip()}")
    elif result is False:
        FAIL.append((label, "returned False", ""))
        print(f"  {RED}FAIL{RESET}  {label}")
    else:
        PASS.append(label)
        print(f"  {GREEN}ok{RESET}    {label}  {DIM}{result}{RESET}")
    return result


def expect(resp, label, codes=(200,)):
    if resp.status_code not in codes:
        raise AssertionError(
            f"{label} returned {resp.status_code}, expected one of {codes}")
    return True


def body(resp):
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------

def run():
    print(f"\n{'=' * 64}\n  Swasthya Kosh self-check\n{'=' * 64}")

    with app.app_context():
        nodes = QuestionNode.query.filter_by(active=True).count()
        patients = Patient.query.count()
        doctors = Doctor.query.count()

    print(f"{DIM}  database: {app.config['SQLALCHEMY_DATABASE_URI'].split('://')[0]}"
          f"  |  nodes: {nodes}  patients: {patients}  doctors: {doctors}{RESET}\n")

    if not nodes or not patients:
        print(f"  {RED}Nothing seeded. Run: python seed.py{RESET}\n")
        return 1

    client = app.test_client()

    # ---- public pages ----------------------------------------------------
    print("Public pages")
    for lang in ("en", "hi", "mr"):
        check(f"landing renders in {lang}",
              lambda l=lang: expect(client.get(f"/?lang={l}"), "landing"))

    check("landing shows translated copy",
          lambda: "स्वास्थ्य कोश" in body(client.get("/?lang=hi"))
                  or "परामर्श" in body(client.get("/?lang=hi"))
                  or "warn: Hindi text not found on the landing page")
    check("language switch endpoint",
          lambda: expect(client.get("/language/mr"), "switch", (302, 200)))
    check("status page", lambda: expect(client.get("/status"), "status"))
    check("healthz json", lambda: expect(client.get("/healthz"), "healthz"))
    check("404 handler",
          lambda: expect(client.get("/no-such-page"), "404", (404,)))

    # ---- patient intake --------------------------------------------------
    print("\nPatient terminal")
    check("kiosk start", lambda: expect(client.get("/patient/"), "start"))
    check("language selection",
          lambda: expect(client.post("/patient/", data={"language": "hi"}),
                         "lang", (302,)))
    check("identify screen",
          lambda: expect(client.get("/patient/identify"), "identify"))
    check("sign in as demo patient",
          lambda: expect(client.post("/patient/identify",
                                     data={"abha": "kamla.devi@abdm"}),
                         "identify", (302,)))
    check("OTP verification (mock 246813)",
          lambda: expect(client.post("/patient/verify", data={"otp": "246813"},
                                     follow_redirects=True), "verify"))

    def consent_screen():
        resp = client.get("/patient/consent")
        expect(resp, "consent")
        if "agree" not in body(resp).lower():
            return "warn: consent screen rendered but no agree control found"
        return True
    check("consent screen", consent_screen)

    check("record consent",
          lambda: expect(client.post("/patient/consent",
                                     data={"agree": "yes", "mode": "ayush"}),
                         "consent", (302,)))

    # ---- the interview loop ---------------------------------------------
    node_re = re.compile(r'name="node_id"\s+value="([^"]+)"')
    opt_re = re.compile(r'data-value="([^"]+)"')

    def walk_interview():
        answered, escalated = 0, False
        for _ in range(80):
            resp = client.get("/patient/interview", follow_redirects=False)

            if resp.status_code == 302:
                target = resp.headers.get("Location", "")
                if "urgent" in target:
                    escalated = True
                    break
                if "documents" in target:
                    break
                resp = client.get(target, follow_redirects=True)
                break

            html = body(resp)
            node = node_re.search(html)
            if not node:
                break

            options = opt_re.findall(html)
            payload = {"node_id": node.group(1), "source": "touch",
                       "confidence": "1.0", "raw_transcript": ""}
            payload["value"] = options[0] if options else "self-check answer"

            post = client.post("/patient/answer", data=payload)
            if post.status_code not in (302, 200):
                raise AssertionError(
                    f"answering {node.group(1)} returned {post.status_code}")
            answered += 1

            if post.status_code == 302 and "urgent" in post.headers.get("Location", ""):
                escalated = True
                break

        if answered == 0:
            raise AssertionError("no questions were served")
        return f"{answered} questions answered" + (" (escalated)" if escalated else "")

    check("adaptive interview walks to the end", walk_interview)
    check("documents step",
          lambda: expect(client.get("/patient/documents"), "documents"))

    def submit():
        resp = client.post("/patient/submit", follow_redirects=True)
        expect(resp, "submit")
        return True
    check("submit and generate case sheet", submit)

    def sheet_written():
        with app.app_context():
            case = CaseEntry.query.order_by(CaseEntry.id.desc()).first()
            if not case or not case.summary_text:
                raise AssertionError("no case sheet text was produced")
            return f"source={case.summary_source} triage={case.triage}"
    check("case sheet has content", sheet_written)

    check("patient hub after sign-in",
          lambda: expect(client.get("/patient/home"), "home"))
    check("consent manager screen",
          lambda: expect(client.get("/patient/requests"), "requests"))

    def approve_consent():
        """The un-consented patient must be able to approve from the terminal."""
        with app.app_context():
            arjun = Patient.query.filter_by(abha_address="arjun.nair@abdm").first()
            req = ConsentRequest.query.filter_by(
                patient_id=arjun.id, status="requested").first()
            if not req:
                return "warn: no pending request seeded to approve"
            req_id = req.id

        c2 = app.test_client()
        c2.post("/patient/", data={"language": "en"})
        c2.post("/patient/identify", data={"abha": "arjun.nair@abdm"})
        c2.post("/patient/verify", data={"otp": "246813"}, follow_redirects=True)
        c2.post(f"/patient/requests/{req_id}/otp", follow_redirects=True)
        resp = c2.post(f"/patient/requests/{req_id}/decide",
                       data={"decision": "grant", "otp": "246813"},
                       follow_redirects=True)
        expect(resp, "approve")
        with app.app_context():
            again = ConsentRequest.query.get(req_id)
            if again.status != "granted":
                raise AssertionError(
                    f"approval left status as '{again.status}', expected 'granted'")
        return "request approved from the terminal"
    check("patient can approve a doctor's request", approve_consent)

    # ---- triage ----------------------------------------------------------
    print("\nTriage rules")

    def triage_fires():
        from services import redflags

        class P:
            age = 61

        class C:
            answers = {k: {"value": v} for k, v in {
                "cc_main": "chest_pain", "chest_character": "pressure",
                "chest_radiation": "left_arm",
                "chest_assoc": ["sweating", "breathless"]}.items()}

        level, flags = redflags.evaluate(C(), P())
        if level != "emergency":
            raise AssertionError(f"chest pain pattern gave '{level}', "
                                 f"expected 'emergency'")
        return f"{len(flags)} flags raised"
    check("cardiac pattern escalates to emergency", triage_fires)

    def triage_quiet():
        from services import redflags

        class P:
            age = 30

        class C:
            answers = {}
        level, _ = redflags.evaluate(C(), P())
        if level != "routine":
            raise AssertionError(f"empty intake gave '{level}'")
        return True
    check("empty intake stays routine", triage_quiet)

    def interactions():
        from services.clinical import check_interactions, parse_medicines
        # check_interactions reads the DrugInteraction table, so it needs an
        # application context. The app itself always has one; this test did not.
        with app.app_context():
            meds = parse_medicines("Metformin 500 twice daily, Amlodipine 5mg, "
                                   "Yashtimadhu churna")
            hits = check_interactions(meds)
            if not hits:
                raise AssertionError("Yashtimadhu + Amlodipine was not detected")
            false_pos = check_interactions(
                parse_medicines("Amalaki churna, Amlodipine 10mg"))
            if false_pos:
                raise AssertionError("Amalaki wrongly matched Amlodipine")
        return f"{len(hits)} interaction(s), no false positive"
    check("drug interaction screening", interactions)

    # ---- clinician console ----------------------------------------------
    print("\nPractitioner console")
    doc_client = app.test_client()

    check("login page", lambda: expect(doc_client.get("/clinician/login"), "login"))
    check("sign in",
          lambda: expect(doc_client.post("/clinician/login",
                                         data={"hpr_id": "HPR-AY-44821",
                                               "password": "demo1234"}),
                         "login", (302,)))
    check("queue loads",
          lambda: expect(doc_client.get("/clinician/queue"), "queue"))

    with app.app_context():
        doctor = Doctor.query.filter_by(hpr_id="HPR-AY-44821").first()
        granted = ConsentRequest.query.filter_by(
            doctor_id=doctor.id, status="granted").first()
        open_case_id = None
        locked_case_id = None
        if granted:
            case = CaseEntry.query.filter_by(patient_id=granted.patient_id)\
                .order_by(CaseEntry.id).first()
            open_case_id = case.id if case else None
        arjun = Patient.query.filter_by(abha_address="arjun.nair@abdm").first()
        if arjun:
            lc = CaseEntry.query.filter_by(patient_id=arjun.id).first()
            locked_case_id = lc.id if lc else None

    if open_case_id:
        check("open a consented case",
              lambda: expect(doc_client.get(f"/clinician/case/{open_case_id}"), "case"))
        check("FHIR R4 export",
              lambda: expect(doc_client.get(f"/clinician/case/{open_case_id}/fhir"), "fhir"))

        def fhir_shape():
            import json
            data = json.loads(body(doc_client.get(f"/clinician/case/{open_case_id}/fhir")))
            kinds = {e["resource"]["resourceType"] for e in data.get("entry", [])}
            missing = {"Patient", "Encounter", "Composition"} - kinds
            if missing:
                raise AssertionError(f"bundle missing {missing}")
            return f"{len(data.get('entry', []))} resources"
        check("FHIR bundle is well formed", fhir_shape)

        def pdf_export():
            resp = doc_client.get(f"/clinician/case/{open_case_id}/pdf")
            expect(resp, "pdf")
            data = resp.get_data()
            if not data.startswith(b"%PDF"):
                raise AssertionError("response was not a PDF")
            return f"{len(data) // 1024} KB"
        check("PDF case sheet renders", pdf_export)
    else:
        WARN.append(("consented case", "no granted consent found; run seed.py"))
        print(f"  {YELLOW}warn{RESET}  no consented case to open — run python seed.py")

    if locked_case_id:
        def locked():
            resp = doc_client.get(f"/clinician/case/{locked_case_id}")
            html = body(resp)
            if resp.status_code == 200 and "lock" not in html.lower() \
                    and "consent" not in html.lower():
                raise AssertionError("un-consented case did not show a lock screen")
            return True
        check("un-consented case is locked", locked)

    check("terminology autocomplete",
          lambda: expect(doc_client.get("/clinician/api/terminology?q=sandhi"),
                         "terminology"))
    check("triage rules endpoint",
          lambda: expect(doc_client.get("/clinician/api/triage-rules"), "rules"))
    check("patient lookup page",
          lambda: expect(doc_client.get("/clinician/patients"), "patients"))
    check("lookup finds a patient by ABHA address",
          lambda: "Kamla" in body(doc_client.get(
              "/clinician/patients?q=kamla.devi@abdm"))
              or "warn: search returned no match for a seeded patient")

    def enrol_at_desk():
        abha = "selfcheck.walkin@abdm"
        resp = doc_client.post("/clinician/patients", data={
            "action": "register", "abha": abha, "name": "Self Check Walkin",
            "age": "44", "sex": "male", "phone": "9999", "language": "hi",
        }, follow_redirects=True)
        expect(resp, "enrol")
        with app.app_context():
            created = Patient.query.filter_by(abha_address=abha).first()
            if not created:
                raise AssertionError("desk enrolment did not create the patient")
            db.session.delete(created)
            db.session.commit()
        return "enrolled and cleaned up"
    check("enrol a walk-in patient by ABHA", enrol_at_desk)

    check("ontology editor loads",
          lambda: expect(doc_client.get("/clinician/ontology"), "ontology"))

    def add_question():
        with app.app_context():
            before = QuestionNode.query.count()
        resp = doc_client.post("/clinician/ontology", data={
            "prompt_en": "Self-check: does this question go live?",
            "section": "hpi", "input_type": "choice",
            "complaint_tag": "abdominal", "order_index": "96",
            "node_id": "selfcheck_probe",
            "option_label": ["Yes", "No"],
        }, follow_redirects=True)
        expect(resp, "add node")
        with app.app_context():
            node = QuestionNode.query.filter_by(node_id="selfcheck_probe").first()
            if not node:
                raise AssertionError("the new question was not saved")
            db.session.delete(node)
            db.session.commit()
            after = QuestionNode.query.count()
        return f"added and removed cleanly ({before} -> {after})"
    check("adding a question live works", add_question)

    check("audit trail loads",
          lambda: expect(doc_client.get("/clinician/audit"), "audit"))

    # ---- configuration ---------------------------------------------------
    print("\nConfiguration")

    def ai_state():
        from services import ai
        with app.app_context():
            if ai.available():
                return f"{ai.status_label()} key present"
            return ("warn: no AI key. Case sheets use the rules engine and "
                    "uploaded documents need manual entry. Fine for a demo, "
                    "but set GEMINI_API_KEY to show the AI path.")
    check("language model", ai_state)

    def db_state():
        if app.config["USING_POSTGRES"]:
            return "Supabase Postgres"
        return ("warn: running on local SQLite. Fine, and it cannot fail on "
                "stage. Set DATABASE_URL to use Supabase.")
    check("database", db_state)

    def debug_state():
        import os
        if os.getenv("DEBUG", "true").lower() in {"0", "false", "no", "off"}:
            return "DEBUG off, friendly error pages active"
        return ("warn: DEBUG is on. A crash shows judges a stack trace. "
                "Set DEBUG=false in .env before presenting.")
    check("debug mode", debug_state)

    def secret_state():
        if app.config["SECRET_KEY"] == "swasthya-kosh-dev-secret-change-me":
            return "warn: SECRET_KEY is still the default. Set one in .env."
        return True
    check("secret key", secret_state)

    # ---- summary ---------------------------------------------------------
    print(f"\n{'=' * 64}")
    print(f"  {GREEN}{len(PASS)} passed{RESET}   "
          f"{YELLOW}{len(WARN)} warnings{RESET}   "
          f"{RED}{len(FAIL)} failed{RESET}")
    print("=" * 64)

    if WARN:
        print("\nWarnings (not blocking, worth knowing):")
        for label, msg in WARN:
            print(f"  {YELLOW}·{RESET} {label}: {msg}")

    if FAIL:
        print(f"\n{RED}Failures — fix these before you present:{RESET}")
        for label, msg, tb in FAIL:
            print(f"\n  {RED}{label}{RESET}\n    {msg}")
            if tb:
                for line in tb.strip().splitlines()[-6:]:
                    print(f"    {DIM}{line}{RESET}")
        print()
        return 1

    print(f"\n  Demo path is clear. Clean the test data with: "
          f"python seed.py --reset\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
