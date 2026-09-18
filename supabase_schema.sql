-- ===========================================================================
-- Swasthya Kosh — Supabase schema
--
-- You do NOT have to run this file. On first boot the application calls
-- SQLAlchemy's create_all() and builds every table itself. Run this only if
-- you want the indexes, the constraints and the row-level security policies
-- that create_all() does not generate.
--
-- How to run it:
--   Supabase dashboard -> SQL Editor -> New query -> paste -> Run
--
-- Read the RLS section at the bottom before you decide. It explains exactly
-- what these policies do and do not protect, which is the sort of thing a
-- judge will ask about.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. Tables
-- ---------------------------------------------------------------------------

create table if not exists doctor (
  id              bigserial primary key,
  hpr_id          varchar(64) unique not null,
  name            varchar(120) not null,
  system          varchar(32) default 'Ayurveda',
  department      varchar(80) default 'Kayachikitsa',
  password_hash   varchar(255) not null,
  created_at      timestamp default (now() at time zone 'utc')
);

create table if not exists patient (
  id                  bigserial primary key,
  abha_address        varchar(120) unique not null,
  abha_number         varchar(32),
  name                varchar(120) not null,
  age                 integer check (age is null or (age >= 0 and age <= 130)),
  sex                 varchar(16),
  phone_last4         varchar(4),          -- never the full number
  preferred_language  varchar(8) default 'hi',
  created_at          timestamp default (now() at time zone 'utc')
);

create table if not exists case_entry (
  id                 bigserial primary key,
  patient_id         bigint not null references patient(id) on delete cascade,
  doctor_id          bigint references doctor(id),
  mode               varchar(16) default 'ayush',
  language           varchar(8) default 'hi',
  chief_complaint    varchar(255),
  answers            jsonb default '{}'::jsonb,
  dashavidha         jsonb default '{}'::jsonb,
  triage             varchar(16) default 'routine'
                     check (triage in ('routine','priority','emergency')),
  red_flags          jsonb default '[]'::jsonb,
  summary_text       text,
  summary_source     varchar(32) default 'pending',
  namaste_code       varchar(32),
  namaste_term       varchar(160),
  icd11_tm2_code     varchar(32),
  icd11_biomed_code  varchar(32),
  status             varchar(24) default 'in_progress'
                     check (status in ('in_progress','awaiting_review','confirmed','rejected')),
  verified_by        bigint references doctor(id),
  verified_at        timestamp,
  consent_given      boolean default false,
  consent_purpose    varchar(255),
  started_at         timestamp default (now() at time zone 'utc'),
  submitted_at       timestamp
);

create table if not exists prescription_upload (
  id                 bigserial primary key,
  patient_id         bigint not null references patient(id) on delete cascade,
  case_id            bigint references case_entry(id) on delete cascade,
  filename           varchar(255),
  doc_type           varchar(32) default 'prescription',
  document_date      date,
  extracted          jsonb default '{}'::jsonb,
  extraction_source  varchar(32) default 'pending',
  confidence         double precision default 0.0
                     check (confidence >= 0 and confidence <= 1),
  status             varchar(24) default 'pending_review'
                     check (status in ('pending_review','confirmed','rejected')),
  verified_by        bigint references doctor(id),
  verified_at        timestamp,
  uploaded_at        timestamp default (now() at time zone 'utc')
);

-- The intake ontology. Questions are ROWS, not code. This is the table that
-- lets a new chief-complaint branch go live without a redeploy.
create table if not exists question_node (
  id                bigserial primary key,
  node_id           varchar(64) unique not null,
  section           varchar(48) not null,
  order_index       integer default 100,
  prompt_en         text not null,
  prompt_hi         text,
  prompt_mr         text,
  input_type        varchar(24) default 'choice',
  options           jsonb default '[]'::jsonb,
  parent_node       varchar(64),
  show_if_value     varchar(120),
  complaint_tag     varchar(64),
  socrates_slot     varchar(24),
  dashavidha_param  varchar(32),
  practitioner_only boolean default false,
  active            boolean default true
);

create table if not exists namaste_code (
  id                  bigserial primary key,
  code                varchar(32) unique not null,
  term                varchar(160) not null,
  term_diacritic      varchar(160),
  system              varchar(24) default 'Ayurveda',
  description         text,
  icd11_tm2_code      varchar(32),
  icd11_tm2_term      varchar(160),
  icd11_biomed_code   varchar(32),
  icd11_biomed_term   varchar(160),
  keywords            varchar(400)
);

create table if not exists drug_interaction (
  id         bigserial primary key,
  drug_a     varchar(120) not null,
  drug_b     varchar(120) not null,
  severity   varchar(16) default 'moderate'
             check (severity in ('minor','moderate','major')),
  mechanism  text,
  advice     text,
  reference  varchar(255)
);

create table if not exists consent_request (
  id            bigserial primary key,
  patient_id    bigint not null references patient(id) on delete cascade,
  doctor_id     bigint not null references doctor(id) on delete cascade,
  purpose       varchar(255) not null,
  scope         jsonb default '[]'::jsonb,
  status        varchar(16) default 'requested'
                check (status in ('requested','granted','denied','revoked','expired')),
  otp           varchar(6),
  requested_at  timestamp default (now() at time zone 'utc'),
  decided_at    timestamp,
  expires_at    timestamp,
  revoked_at    timestamp
);

-- Append-only by policy (see section 4).
create table if not exists access_log (
  id           bigserial primary key,
  actor_type   varchar(16),
  actor_id     bigint,
  actor_label  varchar(120),
  action       varchar(64) not null,
  target       varchar(120),
  detail       text,
  consent_id   bigint references consent_request(id),
  at           timestamp default (now() at time zone 'utc')
);

create table if not exists otp_token (
  id          bigserial primary key,
  subject     varchar(120) not null,
  code        varchar(6) not null,
  created_at  timestamp default (now() at time zone 'utc'),
  used        boolean default false
);


-- ---------------------------------------------------------------------------
-- 2. Indexes
--
-- The queue query sorts by triage then arrival on every console page load, and
-- the consent check runs on every single record open. Those two are the hot
-- paths; index them.
-- ---------------------------------------------------------------------------

create index if not exists idx_case_queue
  on case_entry (status, triage, submitted_at);
create index if not exists idx_case_patient
  on case_entry (patient_id);
create index if not exists idx_consent_lookup
  on consent_request (doctor_id, patient_id, status, expires_at);
create index if not exists idx_upload_case
  on prescription_upload (case_id, status);
create index if not exists idx_node_walk
  on question_node (active, section, order_index);
create index if not exists idx_namaste_search
  on namaste_code (code, term);
create index if not exists idx_log_recent
  on access_log (at desc);
create index if not exists idx_otp_lookup
  on otp_token (subject, code, used);

-- Terminology autocomplete does substring search across four columns. This
-- makes it fast enough to run on every keystroke.
create extension if not exists pg_trgm;
create index if not exists idx_namaste_trgm
  on namaste_code using gin (
    (term || ' ' || coalesce(keywords,'') || ' ' || coalesce(icd11_biomed_term,''))
    gin_trgm_ops
  );


-- ---------------------------------------------------------------------------
-- 3. Row Level Security
--
-- READ THIS BEFORE YOU ENABLE IT.
--
-- How this app currently connects: DATABASE_URL is a direct Postgres
-- connection string, so SQLAlchemy authenticates as the database owner. The
-- owner BYPASSES row level security. Enabling RLS therefore does not change
-- the behaviour of the Flask app at all, and it will not break your demo.
--
-- So why is it here? Because the moment anything talks to Supabase through
-- the anon key — a patient-facing mobile app, a Supabase Edge Function, a
-- teammate poking at the REST endpoint — that connection is NOT the owner and
-- these policies become the only thing standing between an anon key and every
-- patient record in the table. Shipping the policies now means the boundary
-- exists before the client that needs it does.
--
-- Consent enforcement in THIS build lives in the application layer, in
-- clinician._has_access(), and it is real: the case view, the FHIR export and
-- the PDF export all refuse without a live consent artefact, and the refusal
-- is written to access_log. Say exactly that if you are asked. Claiming the
-- database enforces it today would be wrong.
-- ---------------------------------------------------------------------------

alter table patient             enable row level security;
alter table case_entry          enable row level security;
alter table prescription_upload enable row level security;
alter table consent_request     enable row level security;
alter table access_log          enable row level security;
alter table otp_token           enable row level security;

-- Reference data is readable by anyone. It is public terminology, not PHI.
alter table question_node    enable row level security;
alter table namaste_code     enable row level security;
alter table drug_interaction enable row level security;

drop policy if exists read_ontology on question_node;
create policy read_ontology on question_node
  for select using (true);

drop policy if exists read_terminology on namaste_code;
create policy read_terminology on namaste_code
  for select using (true);

drop policy if exists read_interactions on drug_interaction;
create policy read_interactions on drug_interaction
  for select using (true);

-- A patient may read and write only their own row.
-- Mapping: the JWT carries the ABHA address in a custom claim.
drop policy if exists patient_self on patient;
create policy patient_self on patient
  for all
  using (abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address')
  with check (abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address');

-- A patient may read and write only their own case entries.
drop policy if exists case_owner on case_entry;
create policy case_owner on case_entry
  for all
  using (
    patient_id in (
      select id from patient
      where abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address'
    )
  );

-- A practitioner may read a case ONLY while a granted, unexpired, unrevoked
-- consent artefact exists for that patient. This is the database expressing
-- the same rule the application enforces.
drop policy if exists case_consented_practitioner on case_entry;
create policy case_consented_practitioner on case_entry
  for select
  using (
    exists (
      select 1
      from consent_request c
      join doctor d on d.id = c.doctor_id
      where c.patient_id = case_entry.patient_id
        and c.status = 'granted'
        and c.revoked_at is null
        and c.expires_at > (now() at time zone 'utc')
        and d.hpr_id = current_setting('request.jwt.claims', true)::json->>'hpr_id'
    )
  );

-- Uploaded documents inherit the same rule through their case.
drop policy if exists upload_follows_case on prescription_upload;
create policy upload_follows_case on prescription_upload
  for select
  using (
    patient_id in (
      select id from patient
      where abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address'
    )
    or exists (
      select 1
      from consent_request c
      join doctor d on d.id = c.doctor_id
      where c.patient_id = prescription_upload.patient_id
        and c.status = 'granted'
        and c.revoked_at is null
        and c.expires_at > (now() at time zone 'utc')
        and d.hpr_id = current_setting('request.jwt.claims', true)::json->>'hpr_id'
    )
  );

-- Consent requests are visible to the patient they concern and to the
-- practitioner who made them. The patient alone may change the decision.
drop policy if exists consent_visible on consent_request;
create policy consent_visible on consent_request
  for select
  using (
    patient_id in (
      select id from patient
      where abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address'
    )
    or doctor_id in (
      select id from doctor
      where hpr_id = current_setting('request.jwt.claims', true)::json->>'hpr_id'
    )
  );

drop policy if exists consent_patient_decides on consent_request;
create policy consent_patient_decides on consent_request
  for update
  using (
    patient_id in (
      select id from patient
      where abha_address = current_setting('request.jwt.claims', true)::json->>'abha_address'
    )
  );


-- ---------------------------------------------------------------------------
-- 4. Append-only audit log
--
-- An audit trail that can be edited is not an audit trail. Inserts are
-- allowed; updates and deletes are refused at the database level, so even a
-- compromised application credential cannot quietly erase an access record.
-- ---------------------------------------------------------------------------

drop policy if exists log_insert_only on access_log;
create policy log_insert_only on access_log
  for insert with check (true);

drop policy if exists log_read_own on access_log;
create policy log_read_own on access_log
  for select using (true);

create or replace function refuse_log_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'access_log is append-only: % is not permitted', tg_op;
end;
$$;

drop trigger if exists no_log_update on access_log;
create trigger no_log_update before update on access_log
  for each row execute function refuse_log_mutation();

drop trigger if exists no_log_delete on access_log;
create trigger no_log_delete before delete on access_log
  for each row execute function refuse_log_mutation();


-- ---------------------------------------------------------------------------
-- 5. Expire stale consent automatically
--
-- A grant that has passed its expiry should read as 'expired', not as
-- 'granted with a date in the past'. The application already checks the
-- timestamp, but the status column should not lie to anyone reading the table
-- directly.
-- ---------------------------------------------------------------------------

create or replace function expire_consents()
returns void language sql as $$
  update consent_request
     set status = 'expired'
   where status = 'granted'
     and expires_at < (now() at time zone 'utc');
$$;


-- ---------------------------------------------------------------------------
-- 6. Storage bucket for uploaded documents (optional)
--
-- This build writes uploads to ./uploads on the local disk, which is the right
-- choice for a laptop demo. If you want them in Supabase Storage instead:
--
--   Dashboard -> Storage -> New bucket
--     Name:   patient-documents
--     Public: NO. These are prescriptions.
--
-- Then set SUPABASE_URL and SUPABASE_ANON_KEY in .env. Keep the bucket
-- private and serve files through signed URLs with a short expiry — a public
-- bucket holding prescriptions is the single most common way a student health
-- project leaks real data.
-- ---------------------------------------------------------------------------
