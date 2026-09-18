# Swasthya Kosh

Pre-consultation clinical intake for AYUSH outpatient departments.
Built for Smart India Hackathon 2026, problem statement **SIH26047 — Patient
Case-Taking Software**, Ministry of Ayush.

A patient in a government OPD gets two to five minutes with a doctor. History
taking — the step that carries 70 to 80 percent of the diagnosis — gets
whatever is left of that. Swasthya Kosh moves history taking into the waiting area.
The patient answers in Hindi, Marathi or English by speaking or tapping,
photographs whatever old papers they carry, and the practitioner opens a
complete, coded, triage-sorted case sheet the moment they walk in.

---

## Table of contents

1. [Run it in five minutes](#1-run-it-in-five-minutes)
2. [Tech stack and why](#2-tech-stack-and-why)
3. [Project structure](#3-project-structure)
4. [Supabase setup](#4-supabase-setup)
5. [Free AI API keys](#5-free-ai-api-keys)
6. [Database schema](#6-database-schema)
7. [The demo script](#7-the-demo-script)
8. [MVP feature set](#8-mvp-feature-set)
9. [Architecture decisions worth defending](#9-architecture-decisions-worth-defending)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Run it in five minutes

You need Python 3.10 or newer and VS Code. Nothing else — not Supabase, not an
API key, not an internet connection.

### macOS

```bash
cd swasthya-kosh
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
python seed.py
python app.py
```

On a Mac, always use **`python3`** to create the venv. The bare `python`
command either does not exist or points at an old system Python. Once the venv
is active, plain `python` is correct — it resolves to the venv.

If macOS has no Python 3, install it with `brew install python@3.12`, or get
the installer from python.org.

### Windows (PowerShell)

```powershell
cd swasthya-kosh
python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

copy .env.example .env
python seed.py
python app.py
```

If activation is blocked by execution policy, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once, then retry.

### Then

The startup banner prints the URL. It is normally
**http://127.0.0.1:5002**. If 5002 is somehow taken, the app steps to 5000,
5001, 5050 or 8000 automatically and tells you. Read the banner rather than
assuming.

| Screen | Path | Credentials |
|---|---|---|
| Landing | `/` | — |
| Patient terminal | `/patient/` | `kamla.devi@abdm`, OTP `246813` |
| Practitioner console | `/clinician/login` | `HPR-AY-44821` / `demo1234` |
| System status | `/status` | shows which optional services are live |

Two more practitioners exist: `HPR-AY-77104` and `HPR-MD-20933`, same password.

**Use Chrome or Edge.** Safari does not implement speech recognition, so the
microphone will not work there. Everything else does.

> **VS Code:** `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows) →
> *Python: Select Interpreter* → pick the `.venv` one. Then `F5` runs `app.py`
> with breakpoints working.

### If the install fails

The one package that can refuse to install is `psycopg`, the Postgres driver.
It is only needed for Supabase — the app runs fully on local SQLite without it.
If you hit an error mentioning psycopg, use the cut-down file instead:

```bash
pip install -r requirements-core.txt
```

Everything in the demo still works. Add psycopg later when you wire up
Supabase:  `pip install "psycopg[binary]"`

Steps 4 and 5 below are upgrades, not requirements.

### Deploy to Vercel

The repo is ready for Vercel's Python runtime:

- `vercel.json` routes all requests to `app.py`.
- `runtime.txt` pins the serverless runtime to Python 3.12.
- `.vercelignore` keeps local-only files such as `.env`, `venv`, `instance`
  and uploaded documents out of the deployment bundle.

For a real deployment, set `DATABASE_URL` in the Vercel project settings to
the Supabase **Session pooler** URI. Without it, the app still boots on Vercel,
but it falls back to SQLite in `/tmp`, which is temporary and can be wiped
between serverless invocations. Local file uploads are also temporary on
Vercel; use Supabase Storage or another hosted object store before collecting
real documents.

**Commit, push, deploy:**

```bash
git add -A
git commit -m "Dark-green kiosk theme, practitioner signup, port 5002"
git push origin main
```

Then either:

- **Dashboard**: on [vercel.com](https://vercel.com), "Add New… → Project",
  import `advayytt/SwasthyaKoshPrototype` from GitHub, leave the build
  settings at their Python defaults (Vercel reads `vercel.json`), add
  `DATABASE_URL` (and any AI/ABDM/Bhashini keys you're using) under
  Project Settings → Environment Variables, then **Deploy**. Every future
  `git push` to the connected branch redeploys automatically.
- **CLI**: `npm i -g vercel` once, then from the project root:
  ```bash
  vercel login
  vercel          # first run: links the project, deploys a preview
  vercel --prod   # promotes to the production URL
  ```

Either way, set environment variables in Vercel's dashboard, not in a
committed `.env` — `.vercelignore` already excludes `.env` from the
uploaded bundle so it can't leak into the deployment by accident.

---

## 2. Tech stack and why

| Layer | Choice | Reason |
|---|---|---|
| Backend | Flask 3 | One process, no build step, readable by a rookie teammate on day one |
| ORM | Flask-SQLAlchemy 3 | Same code against Postgres and SQLite, so the offline fallback is free |
| Templates | Jinja2 | Server-rendered. No bundler, no `npm install`, nothing to break on stage |
| Database | Supabase Postgres, SQLite fallback | Hosted and shareable when online; a local file when not |
| Styling | Custom CSS, ~700 lines | See the note below |
| Voice | Web Speech API | Browser-native ASR and TTS. Free, no key, supports `hi-IN`, `mr-IN`, `en-IN` |
| AI | Gemini / Groq / OpenRouter | All free tier. Swappable through one env variable |
| PDF | ReportLab | Pure Python, no system dependencies to install |
| Identity | Mock ABDM, sandbox-ready | Same interface; flip `MOCK_ABDM=false` when credentials arrive |

**On Tailwind.** The brief called for Tailwind, and it is a reasonable default.
This build uses a hand-written token system instead, for two reasons worth
being explicit about. First, the Tailwind Play CDN fetches and compiles at page
load, so a dead venue network means an unstyled demo — and the whole point of
the SQLite and rules-engine fallbacks is that this app survives a dead network.
Second, the kiosk and the console are deliberately *different products*: 22px
type on dark vetiver green for a 70-year-old standing in a corridor, versus
13.5px on pale limewash for a clinician with 90 seconds. Utility classes make
two design systems in one codebase harder to keep honest, not easier.

Everything is driven by CSS custom properties at the top of `static/css/app.css`,
so migrating is mechanical if you want it:

```js
// tailwind.config.js — the same tokens, if you switch
module.exports = {
  content: ["./templates/**/*.html"],
  theme: { extend: {
    colors: {
      paper: "#EEF1E9", ink: "#101A2E", vetiver: "#1F3D33",
      haldi: "#C8912B", alert: "#C0362C",
    },
    fontFamily: {
      display: ['"Tiro Devanagari Hindi"', "serif"],
      sans: ['"IBM Plex Sans"', '"IBM Plex Sans Devanagari"', "sans-serif"],
    },
  }},
};
```

---

## 3. Project structure

```
swasthya-kosh/
├── app.py                     # application factory, error handlers, CLI
├── config.py                  # env-driven config, three run modes
├── models.py                  # 10 SQLAlchemy tables
├── seed.py                    # loads ontology, terminology, 4 demo personas
├── supabase_schema.sql        # optional: indexes, RLS policies, audit triggers
├── requirements.txt
├── .env.example               # copy to .env
│
├── data/
│   ├── question_ontology.json   # 38 question nodes, en/hi/mr
│   ├── namaste_codes.json       # 22 terms, dual-coded to ICD-11 TM2 + MMS
│   └── drug_interactions.json   # 28 Ayurveda x allopathy pairs
│
├── services/                  # all business logic, no Flask routing
│   ├── ai.py                    # provider abstraction + no-key fallback
│   ├── intake.py                # walks the ontology at runtime
│   ├── redflags.py              # 14 deterministic triage rules
│   ├── clinical.py              # terminology, drug matching, lab ranges
│   ├── extraction.py            # vision-LLM document reading
│   ├── summary.py               # case sheet, AI path + rules path
│   ├── fhir.py                  # FHIR R4 document Bundle
│   ├── pdf.py                   # printable case sheet
│   └── abdm.py                  # ABHA / HPR / OTP, mock and sandbox
│
├── routes/
│   ├── main.py                  # landing, status, healthz
│   ├── patient.py               # kiosk flow
│   └── clinician.py             # console, exports, ontology editor, audit
│
├── static/
│   ├── css/app.css              # the design system
│   └── js/kiosk.js, console.js  # Web Speech, terminology autocomplete
│
└── templates/
    ├── landing.html, status.html, error.html
    ├── patient/                 # 10 kiosk screens
    └── clinician/               # 6 console screens
```

---

## 4. Supabase setup

Optional. Skip it and the app writes to `instance/swasthya_kosh.sqlite3` instead.

1. Create a free project at **https://supabase.com/dashboard**. Pick a region
   close to you — `ap-south-1` (Mumbai) if you are in India.
2. Save the database password it shows you. It is not recoverable.
3. Click **Connect** at the top of the dashboard, choose the
   **Session pooler** tab, and copy the URI. It looks like:
   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
   Use the **Session pooler**, not Direct connection. Direct connection is
   IPv6-only on the free tier and most Indian college networks cannot reach it.
4. Replace `[YOUR-PASSWORD]` with your actual password and paste it into `.env`:
   ```env
   DATABASE_URL=postgresql://postgres.abcdefgh:yourpassword@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
5. Run `python seed.py` again. The tables are created automatically.
6. Optional: paste `supabase_schema.sql` into the SQL Editor and run it. That
   adds indexes, RLS policies and the append-only audit triggers. Read the
   comment block in section 3 of that file first — it explains precisely what
   the policies do and do not protect in this build, which is the honest answer
   if a judge asks.

Confirm it worked at **http://127.0.0.1:5002/status**.

---

## 5. Free AI API keys

Also optional. Section 8 lists exactly what changes without one.

### Google Gemini (recommended — does text *and* vision on one key)

1. Go to **https://aistudio.google.com/apikey**
2. Sign in with any Google account. Click **Create API key**.
3. Paste it into `.env`:
   ```env
   AI_PROVIDER=gemini
   GEMINI_API_KEY=[INSERT_API_KEY_HERE]
   GEMINI_MODEL=gemini-2.0-flash
   ```
4. Restart `python app.py`. `/status` should now read *key present*.

Free tier is rate-limited per minute, which is plenty for a demo. Prescription
reading needs vision, and Gemini Flash handles it on the same key — this is the
main reason it is the default.

### Groq (alternative — very fast)

1. **https://console.groq.com/keys** → sign in → **Create API Key**
2. ```env
   AI_PROVIDER=groq
   GROQ_API_KEY=[INSERT_API_KEY_HERE]
   GROQ_MODEL=openai/gpt-oss-120b
   GROQ_VISION_MODEL=qwen/qwen3.8-27b
   ```
   Text generation and document-image extraction use different Groq
   models — Groq's text models are not vision-capable and vice versa.
   qwen/qwen3.8-27b is currently Groq's only vision-capable model and is
   in their Preview tier, which Groq's own docs say may be discontinued
   at short notice. Groq retires models on a rolling schedule
   (https://console.groq.com/docs/deprecations); if either of these
   starts 404ing, that page plus https://console.groq.com/docs/vision
   will have the current names.

### OpenRouter (alternative — many free models)

1. **https://openrouter.ai/keys** → sign in → **Create Key**
2. ```env
   AI_PROVIDER=openrouter
   OPENROUTER_API_KEY=[INSERT_API_KEY_HERE]
   OPENROUTER_MODEL=google/gemini-2.0-flash-exp:free
   ```

### Speech needs no key at all

Voice input and the spoken prompts use the browser's own Web Speech API.
That is free, works offline for synthesis, and covers `hi-IN`, `mr-IN` and
`en-IN`. **Use Chrome or Edge** — Firefox and Safari do not ship the
recogniser, and the kiosk detects this and hides the microphone rather than
showing a dead button.

> `.env` is already in `.gitignore`. Before you push to a public repo, run
> `git status` and confirm `.env` is not listed. A leaked key on a public SIH
> repo gets scraped within hours.

---

## 6. Database schema

Ten tables. Full DDL with constraints, indexes and RLS is in
`supabase_schema.sql`.

| Table | Holds | Notable column |
|---|---|---|
| `patient` | Identity | `phone_last4` — we store four digits, never a full number, never Aadhaar |
| `doctor` | Practitioners | `hpr_id` — Healthcare Professional Registry |
| `case_entry` | One intake session | `answers` jsonb, `triage`, `red_flags`, and the three coding columns |
| `prescription_upload` | A digitized paper | `confidence`, `status` defaults to `pending_review` |
| `question_node` | **The intake ontology** | `parent_node` + `show_if_value` + `complaint_tag` drive branching |
| `namaste_code` | Terminology | `icd11_tm2_code` and `icd11_biomed_code` alongside `code` |
| `drug_interaction` | Safety reference | `mechanism`, `advice`, `reference` |
| `consent_request` | Consent artefact | `expires_at`, `revoked_at` — time-boxed and revocable |
| `access_log` | Audit trail | Append-only, enforced by trigger |
| `otp_token` | Phone verification | Mock now, ABDM sandbox later |

Two things in here are the design argument, not just storage:

**`question_node` is data.** There is no hardcoded question sequence anywhere
in the codebase. `services/intake.py` walks rows at runtime, filtering by chief
complaint and by earlier answers. Adding a branch is an `INSERT`.

**Every clinical value carries provenance.** Each answer stores its `source`
(voice or touch), a `confidence` score, and the raw utterance. Each document
stores what read it and how sure it was. The console surfaces everything below
75% confidence in a *check this* banner. Nothing enters the record without a
human confirming it.

---

## 7. The demo script

Six minutes. Two browser windows side by side — patient terminal on the left,
practitioner console on the right.

**1. The landing page (20s).** Read the opening line. Point at the five-step
strip. "All five steps happen before the patient reaches the doctor."

**2. A complete intake (90s).** Patient terminal → Hindi → sign in as
`kamla.devi@abdm` → OTP `246813`. Let the consent screen *read itself aloud* —
do not skip this, it is the accessibility argument in one moment. Then answer
questions. Tap the microphone and actually speak an answer so they see the
transcript and the option light up. Note the progress rail.

**3. The structural change (60s).** Console → **Question set**. Add
*"Has there been any bleeding since delivery?"*, section `hpi`, complaint
`abdominal`, three options: no bleeding / light spotting / heavy bleeding.
Submit. Switch to the patient terminal, start a fresh intake, choose a stomach
problem — the question is there. **The app was never restarted.** This is the
answer to "what happens when a new complaint type is needed", and it is the
single highest-leverage thing on the screen.

**4. The red flag (45s).** New intake → chest pain → heavy pressure → radiates
to left arm → cold sweating. The interview **stops**. The screen turns red and
tells the patient to show it to a nurse. Say the line: *"Those are 14
deterministic rules, not a model. If the API key expires mid-demo, triage still
works."*

**5. The case sheet (2 min).** Console → queue, sorted by triage with Ramesh
Yadav at the top in red. Open **Kamla Devi**:
- The case sheet, with its provenance line stating who wrote it
- *What the patient actually said*, with the Hindi she spoke and the confidence
- The document timeline — HbA1c 8.4 and ESR 34 flagged out of range, and the
  prescription read at 71% with one illegible line the reader admitted to
- **Yashtimadhu + Amlodipine, major.** Liquorice causes sodium retention and
  opposes her blood pressure medicine. She said it out loud; the doctor would
  never have asked.
- Dual coding: search `sandhivata`, watch NAMASTE `AAE-16`, ICD-11 TM2 and
  ICD-11 Biomedicine `FA01.0` attach together
- The four Dashavidha parameters left blank *because they require examination*
- **FHIR R4 bundle** — open it, show the Condition resource carrying all three
  codings in one array

**6. Consent (45s).** Queue → open **Arjun Nair** → lock screen. Then patient
terminal → sign in as `arjun.nair@abdm` → *Manage who can see my record* →
approve with `246813` → refresh the console, it opens. Revoke, refresh, it
locks again. Finish on **Audit trail**, which has been recording every step you
just performed, including the refused open.

**Closing line:** "Nothing here diagnoses. It is a complete history, coded to
two vocabularies, on the doctor's screen before the patient sits down."

---

## 8. MVP feature set

### Module A — intake
- Adaptive interview, 38 nodes, branching on chief complaint and prior answers
- SOCRATES follow-ups per complaint: joint, chest, abdominal, fever,
  breathlessness, headache, skin
- Hindi, Marathi, English — prompts, options and spoken audio
- Voice or touch on every question, with graceful degradation
- Dashavidha Pariksha: 8 patient-reported parameters, 4 reserved for
  examination
- Undo on every step, because elderly users mis-tap
- Live ontology editor — add a branch without a redeploy

### Module B — documents
- Vision-LLM reading of prescriptions, lab reports, discharge summaries
- Structured output: diagnoses, medicines, investigations, per-field confidence
- Chronological medical timeline
- Lab values checked against 28 reference ranges, abnormals flagged
- Everything held in `pending_review` until a practitioner confirms it
- Manual entry path when no key is configured

### Module C — case sheet
- Nine-section physician-ready history
- Two generators: model-written and deterministic, provenance always shown
- Low-confidence items surfaced for re-checking
- Fully editable, then confirm / draft / reject
- Print to PDF

### Practitioner signup workflow

`/clinician/signup` (`routes/clinician.py:signup`) is the self-service
onboarding path for the console. It's deliberately simple for a prototype —
no email loop, no admin approval queue — but every field maps to something
a real HPR-backed rollout would need:

1. **Form fields**: full name, HPR ID, system (Ayurveda / Siddha / Unani /
   Allopathy), department, password + confirmation. Rendered by
   `templates/clinician/signup.html`.
2. **Server-side checks** (in order): name/HPR ID/department non-empty →
   password ≥ 8 characters → password matches confirmation → HPR ID not
   already registered (`Doctor.query.filter_by(hpr_id=...)`). Each failure
   flashes a message and re-renders the form without losing the other
   fields' intent.
3. **Account creation**: a `Doctor` row is inserted (`models.py`) with the
   password hashed via Werkzeug's `generate_password_hash` — plaintext
   passwords are never stored or logged.
4. **Audit log**: a `doctor_signed_up` entry is written to the append-only
   `AccessLog` table (actor, HPR ID, system/department) before commit, so
   every account creation is traceable the same way record accesses are.
5. **Session + redirect**: the new doctor is logged in immediately
   (`session["doctor_id"] = doctor.id`) and sent to `/clinician/queue` —
   no separate login step required right after signup.

**What's intentionally out of scope for this build, and why:** the form
does not verify the HPR ID against the real Healthcare Professional
Registry (NHA's HPR API needs sandbox onboarding this prototype doesn't
have), and there's no email/OTP confirmation loop. Anyone who knows an HPR
ID format can create an account. For a production deployment, the fix is
to swap step 2 for an HPR API lookup (confirm the ID exists and pull the
name/system/department from it instead of trusting form input) and gate
`session["doctor_id"]` behind an OTP or magic-link step, the same pattern
already used for patient identity via ABDM (`services/abdm.py`).

**Database schema** (`models.py`, `Doctor`): `id`, `hpr_id` (unique),
`name`, `system`, `department`, `password_hash`, `created_at`. No schema
change is needed to ship this — it already exists in `supabase_schema.sql`
and is created automatically by `db.create_all()` on SQLite.

**Routing**: `GET /clinician/signup` renders the form; `POST` handles
submission. The chain from the dashboard is: landing page →
"Practitioner console" (masthead button and footer link, both
`url_for('clinician.login')`) → login page's "Create a practitioner
account" link → `/clinician/signup`.

### Module D — safety, coding, consent
- 14 deterministic red-flag rules → routine / priority / emergency
- Triage recomputed on **every answer**, not just at submission
- 28-pair Ayurveda × allopathy drug interaction screen with mechanism and
  reference
- NAMASTE × ICD-11 TM2 × ICD-11 Biomedicine triple coding in one FHIR Condition
- Purpose-scoped, time-boxed, OTP-approved, revocable consent
- Append-only audit trail covering opens, refused opens, edits and exports
- FHIR R4 document Bundle export, NRCeS profile

### Resilience
| Missing | What still works | What changes |
|---|---|---|
| No API key | Everything | Case sheets use the rules engine; documents need manual entry |
| No Supabase | Everything | Data goes to a local SQLite file |
| No internet | Everything | Web fonts fall back to system fonts; speech synthesis still works |
| No microphone | Everything | Microphone hides itself, every question is tappable |

---

## 9. Architecture decisions worth defending

These are the questions a judge is most likely to ask.

**"Add a new chief complaint with its own branch, right now."**
Console → Question set → fill the form → submit. `question_node` is a table and
`services/intake.py` walks it at runtime. No deploy, no restart. This is why
the ontology is data.

**"What if your AI is down when a cardiac patient walks in?"**
Triage never touches the model. `services/redflags.py` is 14 explicit rules
over stored answers. Each carries the reason it fired so the practitioner can
disagree. Escalation is additive — a flag moves a patient up the queue, so a
miss returns to baseline rather than causing harm.

**"How do you know the speech recognition understood a 68-year-old in Marathi?"**
We assume it often will not. Every answer stores its confidence and the raw
utterance; anything under 75% appears in a *check this* banner on the console
with the original Hindi shown. Unmatched speech falls back to tapping rather
than guessing. This matters — the IIT-KGP / NIMHANS audit
(arXiv:2512.10967) found substantial ASR degradation on exactly this population,
code-mixed vernacular clinical speech, with gaps by speaker role and gender.

**"Show me a non-literate patient completing this."**
Consent is read aloud before anything is recorded. Every prompt has a *repeat
question* button. Options carry icons and large text. No question requires
reading, typing or a smartphone. The fallback is not a simpler screen — it is
a staff member, and the flow is designed to be handed over mid-way.

**"A-HMIS already exists and has 5,386 facilities onboarded."**
It does, and it already does double coding and ABHA creation. Swasthya Kosh does not
replace it; it fills the slot *before* it. A-HMIS records the encounter. Swasthya Kosh
produces the history that encounter starts from, and exports FHIR R4 so it
lands in A-HMIS rather than competing with it.

**"Is the NAMASTE mapping real?"**
The 22 seeded codes with their TM2 and MMS mappings are curated for this
prototype and labelled as such. The production path is the NAMASTE portal's
published mapping set — 4,500+ ASU terms, of which roughly 1,941 national codes
are already mapped to TM2's 529 disorder categories and 196 pattern codes. The
architecture is the claim here, not the completeness of the dictionary.

**"Where does the patient's data actually go?"**
Nowhere outside the consultation it was collected for, unless the patient
grants it. Consent is an artefact with a purpose, a scope and an expiry. The
practitioner console refuses without one and logs the refusal. Revocation is
one tap and takes effect on the next request.

---

## 10. Troubleshooting

**`ModuleNotFoundError: No module named 'flask'`**
The virtual environment is not active. Re-run the activate command, confirm
your prompt shows `(.venv)`, then `pip install -r requirements.txt`.

**`psycopg.OperationalError` / cannot reach the database**
You used the Direct connection string. Switch to the **Session pooler** URI.
Also check you replaced `[YOUR-PASSWORD]` and that the password has no
unescaped `@` or `#` — if it does, percent-encode it (`@` → `%40`).

**The microphone button does nothing**
Use Chrome or Edge. Also, `127.0.0.1` is treated as a secure origin so the
microphone works locally without HTTPS — but if you are serving from another
machine's IP, the browser will block it until you use HTTPS.

**No patients in the queue**
Run `python seed.py`. Check `/status` shows non-zero question nodes.

**`/status` says *no key, using rules engine* after adding a key**
Restart `python app.py`. `.env` is read once at import.

**Port 5002 already in use**
Handled automatically: the app finds a free port (5002, then 5000, 5001, 5050,
8000) and prints it in the startup banner. To force one, set `PORT=5050` in
`.env`. On macOS, port 5000 is often held by AirPlay Receiver — turn it off in
System Settings → General → AirDrop & Handoff if you want that one back too.

**The microphone does nothing**
Use Chrome or Edge; Safari has no speech recognition. Chrome's recogniser also
uploads audio to Google, so it needs internet even though it needs no API key.
Grant microphone permission via the padlock icon in the address bar. On macOS
also check System Settings → Privacy & Security → Microphone.

**No Marathi voice for the read-aloud**
macOS ships Hindi TTS but usually not Marathi. The page falls back to a Hindi
voice (shared Devanagari script) and says so. To install more voices:
System Settings → Accessibility → Spoken Content → System Voice → Manage
Voices.

**Everything broke and I want to start over**
Delete `instance/swasthya_kosh.sqlite3` and re-run `python seed.py`. Postgres users:
drop the tables in the Supabase SQL editor first.

---

## Licence and disclaimer

Prototype for academic evaluation. **Not a medical device.** It does not
diagnose, does not suggest treatment and does not replace clinical triage.
Every AI-generated field is a draft held for practitioner confirmation.

All patients, prescriptions and laboratory values in this build are fictional
and generated for demonstration. No real patient data is used anywhere.
