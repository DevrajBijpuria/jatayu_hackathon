CREATE TABLE IF NOT EXISTS documents (
  doc_id          TEXT PRIMARY KEY,      -- e.g. 'RBI-2024-17', 'ACME-EXP-V1'
  title           TEXT,
  source_path     TEXT,
  doc_type        TEXT,                  -- policy | amendment | circular | faq | memo | notice
  language        TEXT,                  -- en | hi | mixed
  origin          TEXT DEFAULT 'upload', -- upload | email | sharepoint
  origin_ref      TEXT,                  -- message id / SharePoint item id + version, for dedupe
  content_hash    TEXT,                  -- sha256 of the file, for dedupe
  issuer          TEXT,                  -- as written in the document; NULL if unknown
  issued_date     DATE,                  -- NULL if unknown
  access_level    TEXT DEFAULT 'all',    -- all | compliance | board
  injection_flag  BOOLEAN DEFAULT FALSE,
  translation_of  TEXT,                  -- doc_id of the partner translation (for bilingual docs)
  ingested_at     TIMESTAMP DEFAULT current_timestamp
);

-- Migration: add column to existing databases (no-op for new ones)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS translation_of TEXT;

CREATE TABLE IF NOT EXISTS clauses (
  clause_id       TEXT PRIMARY KEY,      -- '<doc_id>#<section or n>', e.g. 'ACME-EXP-V1#4.2'
  doc_id          TEXT REFERENCES documents(doc_id),
  section         TEXT,                  -- '4.2' if present
  source_text     TEXT NOT NULL,         -- exact sentence(s) in the original language; never rewritten
  language        TEXT,                  -- en | hi | mixed
  text_en         TEXT,                  -- English translation for Hindi clauses (display + LLM aid only; never used for grounding)
  concept_id      TEXT,                  -- from the concept vocabulary, e.g. 'approval_limit'
  subject         TEXT,                  -- who/what the rule is about, e.g. 'manager'
  clause_type     TEXT,                  -- quantitative | conditional | qualitative
  value_num       DOUBLE,                -- normalised number, NULL for qualitative
  value_unit      TEXT,                  -- 'INR', 'USD', 'days', 'percent', ...
  value_text      TEXT,                  -- value as written, e.g. '$3,000'
  condition_text  TEXT,                  -- e.g. 'except travel expenses'; NULL if none
  scope           TEXT DEFAULT '*',      -- '*' = everyone; otherwise tags joined by ';' e.g. 'location=mumbai;category=travel'
  issuer          TEXT,
  authority_rank  INTEGER,               -- looked up from authority_config; NULL if issuer unknown
  effective_date  DATE,                  -- NULL if unknown
  supersedes      TEXT,                  -- clause_id this clause replaces; NULL if none
  supersedes_conf DOUBLE,                -- confidence of the supersedes link (0-1)
  access_level    TEXT DEFAULT 'all',
  extract_conf    DOUBLE,                -- 1.0 if both extractions agree and grounding passed
  status          TEXT DEFAULT 'active'  -- active | needs_review | rejected
);

CREATE TABLE IF NOT EXISTS concepts (
  concept_id      TEXT PRIMARY KEY,      -- snake_case
  label           TEXT,                  -- 'Expense approval limit'
  synonyms        TEXT                   -- ';'-separated phrases that map to it, English AND Hindi (e.g. 'approval limit;अनुमोदन सीमा')
);

CREATE TABLE IF NOT EXISTS connector_state (
  connector       TEXT PRIMARY KEY,      -- 'sharepoint' | 'email'
  cursor          TEXT,                  -- Graph delta link or last IMAP UID
  last_run_at     TIMESTAMP,
  last_status     TEXT                   -- ok | error: <message>
);

CREATE TABLE IF NOT EXISTS authority_config (
  issuer          TEXT PRIMARY KEY,
  authority_rank  INTEGER                -- higher wins; configured per client
);

CREATE TABLE IF NOT EXISTS conflicts (
  conflict_id     TEXT PRIMARY KEY,
  clause_a        TEXT REFERENCES clauses(clause_id),
  clause_b        TEXT REFERENCES clauses(clause_id),
  kind            TEXT,                  -- value_mismatch | nli_contradiction
  score           DOUBLE,                -- 1.0 for value_mismatch, NLI prob otherwise
  detected_at     TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS review_queue (
  item_id         TEXT PRIMARY KEY,
  clause_id       TEXT,
  reason          TEXT,                  -- missing_date | missing_issuer | grounding_failed | extraction_disagreement | uncertain_supersedes | injection_flag | unresolved_conflict
  missing_fields  TEXT,                  -- ';'-separated
  created_at      TIMESTAMP DEFAULT current_timestamp,
  resolved_at     TIMESTAMP,
  resolved_by     TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  log_id          TEXT PRIMARY KEY,
  asked_at        TIMESTAMP DEFAULT current_timestamp,
  user_id         TEXT,
  question        TEXT,
  as_of           DATE,
  status          TEXT,
  answer          TEXT,
  trace_json      TEXT                   -- full serialized TGState (see 5.2)
);
