# Synthetic Data Generation & Testing

Generate realistic but **completely fictional** data for development, testing, QA, and demos — without risking exposure of real PII or PHI.

## Overview

This project provides four ways to generate synthetic data:

| Tool | What it does |
|------|-------------|
| `run.sh` | **Start here** — one command to run everything (apps, CLIs, validation) |
| `demo_app.py` | Interactive Streamlit UI — pick a built-in domain and generate data in your browser |
| `schema_app.py` | Interactive Streamlit UI — paste or upload your own SQL schema and generate matching data, with editable per-column generator overrides |
| `generate_from_schema.py` | CLI script — point it at a `schema/` directory and it generates data for every table automatically |
| `clinical_notes.py` | CLI — synthetic physician notes & dictation transcripts with embedded (safe-range) PHI and ground-truth PHI spans |
| `clinical_bundle.py` | CLI — **referentially-linked** clinical dataset (patients → encounters → diagnoses/meds/labs/notes) with FHIR R4 / HL7 v2.5.1 / CSV / JSON / SQL output, locale packs, dirty mode, zip + manifest |
| `synthgen deid` | CLI — score any de-identification scrubber against ground-truth PHI spans (recall / char-precision / F1 per type) |
| `synthgen fhir-check` | CLI — structural FHIR R4 conformance checks (required elements, enums, references, base64) |

All tools share the same safety guarantees and semantic column mapping. The Claude Code skill (`synth-data-gen/`) wraps these tools and invokes them automatically when you ask for test data in Claude Code. See [PLAN.md](PLAN.md) for the roadmap.

---

## Documentation

| Doc | What it covers |
|-----|----------------|
| [docs/USAGE.md](docs/USAGE.md) | **Start here** — task-oriented recipes: seed a database, test a de-identification pipeline, build FHIR/HL7 fixtures, generate linked QA datasets; app guides; troubleshooting |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Every acronym (PHI, HIPAA, MRN, NPI, ICD-10, FHIR, HL7, ADT, LOINC…) and synthetic-data concept (safe ranges, ground-truth spans, dirty mode, recall/precision) explained |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture and decision log: canonical package + generated skill copies, safety-by-construction, checksum-valid NPIs, character-level de-id precision, the validator invariant |
| [CLAUDE.md](CLAUDE.md) | Guidance for AI coding assistants working in this repo |
| [data-domains.md](data-domains.md) | Field-level generation rules for all domains |
| [format-templates.md](format-templates.md) | FHIR R4 / HL7 v2.x / SQL / CSV / JSON output specs |
| [PLAN.md](PLAN.md) | Roadmap — Phases 1–5 delivered, backlog |
| [INSTALL.md](INSTALL.md) | Installing the Claude Code skill |


---

## Safety Guarantees

Every generated identifier uses an officially reserved or fictional range — synthetic records can never collide with real people or systems.

| Field | Safe Range | Standard |
|-------|-----------|----------|
| SSN | `987-65-xxxx` | IRS test range |
| Email | `@example.com`, `@example.org`, `@test.invalid` | RFC 2606 reserved |
| Phone | `555-01xx` | NANPA reserved for fiction |
| IP Address | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` | RFC 5737 documentation ranges |
| MRN | `MRN-224xxxx` | Synthetic prefix |
| Patient ID | `SYN-000001` | Synthetic prefix |
| Student ID | `SYN-100000` | Synthetic prefix |
| Employee ID | `EMP-200000` | Synthetic prefix |
| Credit Card | `4242424242424242` | Stripe test number |

Run `validate_synthetic.py` on any generated file to confirm nothing leaked outside these ranges.

---

## Quick Start

### Install dependencies

```bash
pip install -r requirements.txt
# requirements: faker>=25, pandas>=2, streamlit>=1.30
```

### Option 0 — Use `run.sh` (recommended)

```bash
./run.sh demo      # domain-based Streamlit app  → http://localhost:8501
./run.sh schema    # schema-driven Streamlit app → http://localhost:8502
./run.sh notes -n 50 --validate --ground-truth   # clinical notes / dictations
./run.sh bundle -n 100 --zip --validate          # linked clinical dataset (6 tables)
./run.sh gen schema/ --rows 200 --validate       # schema-driven CLI
./run.sh validate synthetic_output/              # PII/PHI validation
./run.sh doctor     # environment check
```

`run.sh` auto-detects a Python interpreter with the required dependencies (override with `PYTHON=`), always runs from the repo root, and passes extra flags straight through to the underlying tool.

### Option 0b — Unified package CLI

```bash
python -m synthgen notes  -n 50 --validate
python -m synthgen bundle -n 100 --format fhir --zip
python -m synthgen schema schema/ --rows 100 --manifest
```

With `pip install -e ".[dev]"` you also get the `synthgen` console script and dev tools (pytest, ruff).

### Option 0c — Docker (zero local Python)

```bash
docker compose up    # demo app on :8501, schema app on :8502
```

### Option 1 — Use the domain-based demo app

```bash
streamlit run demo_app.py
```

Opens at `http://localhost:8501`. Pick a domain (Clinical, Student Records, HR, IAM, Research, Financial), configure rows and seed, click **Generate Data**.

### Option 2 — Use your own SQL schema (interactive)

```bash
streamlit run schema_app.py
```

Paste a `CREATE TABLE` DDL or upload a `.sql` file. The app parses your schema, shows you what generator each column will use, then generates and validates data.

### Option 3 — Use your own SQL schema (CLI / automated)

```bash
# See what tables are in your schema directory
python synth-data-gen/scripts/generate_from_schema.py schema/ --list-tables

# Generate 100 rows per table as CSV (default)
python synth-data-gen/scripts/generate_from_schema.py schema/

# Generate 500 rows per table as SQL INSERT, with validation
python synth-data-gen/scripts/generate_from_schema.py schema/ \
  --rows 500 --format sql --validate --output ./seed_data/

# Specific tables only, seeded for reproducibility
python synth-data-gen/scripts/generate_from_schema.py schema/ \
  --tables patients encounters --rows 200 --seed 42
```

Output is written to `./synthetic_output/` (one file per table) unless `--output` is specified.

### Option 4 — Generate clinical notes & dictation transcripts (CLI)

```bash
# 25 notes — blend of 6 note types, ~35% rendered as raw dictation
python clinical_notes.py --validate

# 50 pure dictation transcripts, one .txt per note + PHI ground truth
python clinical_notes.py -n 50 -t dictation_transcript -f txt --ground-truth

# Specific note type, JSON with embedded PHI span annotations
python clinical_notes.py -n 10 -t discharge_summary -f json --ground-truth
```

Note types: `progress_note`, `history_physical`, `discharge_summary`, `ed_note`,
`telehealth_note`, `procedure_note`, `radiology_report`, `behavioral_health_note`
(42 CFR Part 2 banners), `patient_portal_message` (patient-written, with typos),
`phone_call_transcript` (identity-verification dialog) — or `mix`. Dictation
transcripts include realistic ASR artifacts — spoken punctuation ("period",
"comma", "colon"), "new paragraph" commands, disfluencies, `[inaudible]` markers,
mid-sentence corrections, and occasional Spanish interpreter quotes.

**Ground-truth PHI spans.** Every note can be annotated with the exact character
offsets of each PHI instance (`PATIENT`, `MRN`, `DOB`, `SSN`, `PHONE`, `ADDRESS`,
`PROVIDER`, `NPI`, `DATE`, `ENCOUNTER`, `CONTACT`, `ICD10`, `EMAIL`). Use them to score
de-identification pipelines for recall/precision — see
`clinical_notes_ground_truth.json` written by `--ground-truth`.

### Scoring a de-identification scrubber (deid harness)

Score **any** redaction technology — regex, NER, LLM, vendor product — against the
ground-truth spans. The harness diffs original vs. scrubbed text and reports
span recall, **character-level precision** (blunt whole-document redaction scores
low), F1, and per-PHI-type breakdowns:

```bash
# generate notes, then score the built-in regex baseline
python -m synthgen bundle -n 50 -o ./synthetic_output/
python -m synthgen deid --baseline ./synthetic_output/synthetic_clinical_notes.csv

# score YOUR scrubber (any str -> str callable) + HTML/JSON reports
python -m synthgen deid --scrubber mypkg:redact_text notes.csv \
    --html deid_report.html --json scores.json
```

The baseline demonstrates the classic profile: 100% recall on structured
identifiers (MRN/SSN/NPI/DOB/phones), 0% on names — the harness makes that
gap measurable instead of anecdotal.

### FHIR conformance checking

```bash
python -m synthgen fhir-check synthetic_fhir_bundle.json --json report.json
```

Structural FHIR R4 checks with zero dependencies: required elements per resource
type, status code enums, id/reference formats, ISO-8601 datetimes, base64
attachment payloads, and dangling-reference detection inside bundles. If the
optional `fhir.resources` package is installed, official-schema validation runs
additionally.

### Validation depth

NPIs are **Luhn-checksum valid** (CMS 80840 algorithm) but keep the safe 9-prefix,
so they exercise NPI validation logic without colliding with issued numbers. The
validator flags: valid-checksum NPIs in the real-range 1-prefix (critical),
invalid checksums (data quality), MRNs outside `MRN-224xxxx`, plus the existing
SSN/email/phone/IP range checks. `python validate_synthetic.py <path> --html report.html`
produces a self-contained HTML compliance artifact with per-check status and
statistics — suitable as a review deliverable.

Schema-driven tools also pick up note columns automatically: `note_text`,
`dictation_text`, `progress_note`, `hpi`, `chief_complaint`, `note_type`,
`author`, `transcription_status` are all mapped semantically in
`schema_app.py` and `generate_from_schema.py`.

### Option 5 — Generate a linked clinical dataset (bundle, CLI)

Single-table generators each invent their own ID pools — fine for fixtures, useless
for testing joins. The bundle generator produces a **referentially-linked** dataset:

```bash
# 100 patients → encounters → diagnoses/meds/labs/notes (CSV + manifest + zip)
python clinical_bundle.py -n 100 --validate --zip

# FHIR R4: combined Bundle (Patient/Practitioner/Encounter/Condition/
# MedicationRequest/Observation/DocumentReference) + one bundle per type
python clinical_bundle.py -n 250 --format fhir

# HL7 v2.5.1: ADT^A01 admit + ORU^R01 lab result messages
python clinical_bundle.py -n 50 --format hl7

# Locale pack (UK names/addresses, Ofcom drama phones, ZZ99 postcodes)
python clinical_bundle.py -n 80 --locale uk

# Dirty data mode: duplicates, mixed date formats, OCR-ish note damage
python clinical_bundle.py -n 60 --dirty
```

**Guarantees** (checked by `check_integrity()` on every run):

- every `encounter.patient_id` exists in patients; every diagnosis/med/lab/note references a real encounter
- note `patient_id` equals its encounter's patient; note narrative embeds the actual patient name/MRN/DOB and the encounter's principal diagnosis
- `DOB < admit < discharge`, note service times fall inside the encounter window, and med start dates follow their matching diagnosis onset
- **correlations**: medications come from the encounter's actual diagnoses; labs are condition-biased (diabetes → elevated HbA1c/glucose, pneumonia → elevated WBC); radiology findings match the indication; behavioral-health notes only appear for BH/SUD encounters

**Every run writes `manifest.json`** (seed, row counts, tool versions, timestamp) so
the dataset can be reproduced exactly; `--zip` bundles everything, including the PHI
ground truth, into one archive.

---

## The Two Streamlit Apps

### demo_app.py — Domain-based generator

Use when you want to generate data for a **standard enterprise domain** without providing a schema. The domains and their tables are built in.

**Sidebar controls:** domain, table type, row count (5–500), random seed, output format
**Tabs after generation:** Preview · Raw Output · Validation · Statistics

| Domain | Tables |
|--------|--------|
| Clinical / EHR | Patients, Encounters, Diagnoses, Lab Results, Clinical Notes / Dictations, **Full Dataset — linked (6 tables, incl. Medications)** |

Selecting **Full Dataset — linked** generates a referentially-linked cohort
(same guarantees as the bundle CLI) with per-table previews, an integrity badge,
a zip download (CSV + manifest + PHI ground truth), and a FHIR R4 bundle
download — plus **Locale** (us/uk/ca/eu) and **Dirty data mode** toggles in the
sidebar.
| Student Records | Students, Course Enrollment |
| Human Resources | Employees |
| Identity & Access | User Accounts, Entitlements |
| Research | Research Subjects, Studies |
| Financial / Billing | Claims |

### schema_app.py — Schema-driven generator

Use when you have your **own database schema** and want data that matches it exactly.

1. **Paste DDL** or upload a `.sql` file (or click "Load example schema" to try a sample)
2. **Review the parsed schema** — an editable grid shows each column, its SQL type, and the inferred generator. **Override any column** from the dropdown (~30 generators: names, safe SSN/phone/email, note text, dictation transcripts, NULL, …). PK/FK columns stay locked to preserve referential integrity.
3. **Choose single table or all tables** — multi-table mode resolves foreign keys in dependency order so joins work; a zip download (CSV + manifest) is offered for multi-table runs
4. **Generate** — same four tabs as the demo app

**Supported dialects:** PostgreSQL, MySQL, SQLite, SQL Server
**Supported constraints parsed:** `PRIMARY KEY`, `NOT NULL`, `REFERENCES` (FK), inline and table-level

**How column names map to generators:**

| Column name pattern | Generator used |
|--------------------|---------------|
| `first_name`, `fname` | `fake.first_name()` |
| `last_name`, `lname`, `surname` | `fake.last_name()` |
| `email`, `email_address` | `user@example.com` |
| `phone`, `mobile`, `telephone` | `555-01xx` |
| `ssn`, `social_security` | `987-65-xxxx` |
| `dob`, `birth_date`, `date_of_birth` | Random date (age distribution) |
| `gender`, `sex` | Female/Male/Non-binary (weighted) |
| `address`, `street_address` | `fake.street_address()` |
| `city`, `state`, `zip` | `fake.city/state_abbr/zipcode()` |
| `mrn`, `medical_record` | `MRN-224xxxx` |
| `npi`, `attending_npi` | `9xxxxxxxxx` (10-digit format) |
| `encounter_type` | Outpatient/ED/Inpatient/Telehealth (weighted) |
| `department`, `dept` | Department name pool |
| `salary`, `wage` | `randint(35000, 250000)` |
| `icd10`, `dx_code` | ICD-10 code from clinical pool |
| `cpt`, `cpt_code` | CPT code from pool |
| `username`, `login` | `flastname` pattern |
| `created_at`, `updated_at` | Recent datetime |
| Anything else | SQL type fallback (int→randint, date→random date, varchar→`fake.word()`) |

Nullable columns get ~7% NULL injection; soft-delete/end-date/notes columns get ~38%.

---

## CLI Reference

### generate_from_schema.py

Reads one or more SQL DDL files, generates synthetic data for every table, and writes output files.

```
python synth-data-gen/scripts/generate_from_schema.py <schema> [options]

Arguments:
  schema              Path to a .sql file or a directory of .sql/.ddl files

Options:
  -n, --rows N        Rows per table (default: 100)
  -s, --seed N        Random seed (default: 42)
  -f, --format        Output format: csv | json | sql  (default: csv)
  -o, --output DIR    Output directory (default: ./synthetic_output)
  -t, --tables T...   Only generate these tables (space-separated)
  --validate          Run PII/PHI validation after generation
  --manifest          Write manifest.json (seed, schema SHA-256, versions, row counts)
  --list-tables       Print detected tables and exit

Exit codes: 0=clean  1=warnings  2=critical issues  3=schema error
```

### example_patient_generator.py

Standalone generator for clinical patient records (17 fields).

```
python example_patient_generator.py [options]

  -n, --rows N     Number of records (default: 100)
  -s, --seed N     Random seed (default: 42)
  -f, --format     csv | json | sql  (default: csv)
  -o, --output     Output file path (default: stdout)
  --validate       Run validation after generation
```

### clinical_notes.py

Generates synthetic physician notes and dictation transcripts with embedded safe-range PHI.

```
python clinical_notes.py [options]

  -n, --rows N          Number of notes (default: 25)
  -s, --seed N          Random seed (default: 42)
  -f, --format          csv | json | sql | txt  (default: csv; txt = one file per note)
  -t, --type            mix | progress_note | history_physical | discharge_summary |
                        ed_note | telehealth_note | procedure_note | dictation_transcript
  --dictation-ratio F   Fraction rendered as raw dictation, 0.0-1.0 (default: 0.35)
  -o, --output          Output file or directory (default: ./synthetic_output)
  --ground-truth        Write clinical_notes_ground_truth.json with PHI spans
  --validate            Run PII/PHI validation after generation
  --list-types          Print note types and exit
```

### clinical_bundle.py

Generates a referentially-linked synthetic clinical dataset with integrity guarantees.

```
python clinical_bundle.py [options]

  -n, --rows N          Number of patients (default: 100). Encounters, diagnoses,
                        medications, labs, and notes scale from the patient pool.
  -s, --seed N          Random seed (default: 42)
  -f, --format          csv | json | sql | fhir | hl7  (default: csv)
  -o, --output DIR      Output directory (default: ./synthetic_output)
  --no-notes            Skip note generation
  --dictation-ratio F   Fraction of notes as raw dictation (default: 0.35)
  --locale LOCALE       us | uk | ca | eu — localized names/addresses/phones with
                        region-appropriate fictional ranges (default: us)
  --dirty               Realistic data-quality problems (duplicates, mixed date
                        formats, whitespace/casing drift, OCR-ish note damage)
  --zip                 Also write synthetic_clinical_bundle.zip
  --validate            Run PII/PHI validation after generation
```

Every run writes `manifest.json`; `fhir` writes a combined Bundle plus per-resource-type
bundles; `hl7` writes ADT^A01 and ORU^R01 message files.

### validate_synthetic.py

Checks generated files for PII/PHI leakage and data quality.

```
python validate_synthetic.py <file_or_directory> [--format csv|json|sql]
```

| Exit code | Meaning |
|-----------|---------|
| `0` | All checks passed |
| `1` | Warnings found — review recommended |
| `2` | Critical issues — do not use this data |

Checks performed: SSN area codes, email domains, phone ranges, IP ranges, **NPI Luhn checksums** (valid-checksum + real-range prefix = critical), MRN synthetic-range, NULL distribution, JSON `_meta.synthetic` marker. Add `--html report.html` for a self-contained compliance artifact.

---

## Using as a Claude Code Skill

The `synth-data-gen/` directory is a self-contained Claude Code skill. Install it once and Claude Code will automatically generate synthetic data whenever you ask.

### Install

```bash
# Project-level (recommended — skill travels with the repo)
cp -r synth-data-gen/ /path/to/your/project/.claude/skills/synth-data-gen/

# User-level (available in all projects)
cp -r synth-data-gen/ ~/.claude/skills/synth-data-gen/
```

### How it works

When the skill is installed, Claude Code intercepts requests like:

> *"I need test data for the patient table"*
> *"Generate 500 synthetic encounters as CSV"*
> *"Create fake HR employee records for our staging database"*
> *"Populate our database from the schema/ directory"*

**If your project has a `schema/` directory**, the skill detects it automatically and runs `generate_from_schema.py` — no need to describe the schema manually. It looks in these locations:

```
schema/       db/schema/     database/schema/
migrations/   ddl/           sql/
```

**If no schema directory exists**, the skill asks about domain, volume, and format, then generates data inline or produces a reusable generator script.

Either way, the skill validates all output before delivering it and states clearly that the data is synthetic.

### Example invocations

```
# Schema auto-detection
> Populate our test database with synthetic data

# Domain-based (no schema needed)
> Generate 200 synthetic patient records as CSV
> Create test data for a student enrollment system with 1000 students
> Build me a fake HR employee table with 500 rows, seeded at 99
> Generate FHIR R4 Patient bundles for our API mock server

# Validation
> Validate this synthetic data file for PII leakage
```

---

## Project Structure

```
synthetic-data-generation-testing/
│
├── run.sh                          # Single entry point for all tools
├── Makefile                        # Dev tasks: test / lint / sync-skill / ci
├── pyproject.toml                  # Package metadata, synthgen console script, ruff+pytest config
├── Dockerfile / compose.yaml       # Zero-local-Python demos of both Streamlit apps
│
├── synthgen/                       # ★ CANONICAL PACKAGE — all generation logic
│   ├── schema.py                   #   SQL DDL parser (ColumnDef/TableDef/parse_ddl)
│   ├── generators.py               #   Semantic column mapping + GENERATOR_REGISTRY + safe ranges
│   ├── tables.py                   #   Single-table + FK-ordered multi-table generation
│   ├── notes.py                    #   10 note types, dictation rendering, PHI ground-truth spans
│   ├── bundle.py                   #   Linked cohort, integrity checks, locales, dirty mode
│   ├── fhir.py / hl7.py            #   FHIR R4 + HL7 v2.5.1 exporters
│   ├── formatters.py / validators.py / manifest.py
│   ├── schema_cli.py / cli.py      #   python -m synthgen schema|notes|bundle|validate
│   └── clock.py                    #   Injectable clock (test determinism)
│
├── demo_app.py                     # Streamlit UI — domains + linked-bundle mode
├── schema_app.py                   # Streamlit UI — schema-driven, editable generator overrides
├── clinical_notes.py               # Compat shims over synthgen (historical entry points)
├── clinical_bundle.py              # "
├── fhir_export.py / hl7_export.py  # "
├── validate_synthetic.py           # Standalone PII/PHI validator CLI (file/dir, report)
├── example_patient_generator.py    # Minimal reference generator
├── requirements.txt                # faker, pandas, streamlit
├── PLAN.md                         # Improvement roadmap
│
├── tests/                          # 76 pytest tests incl. validator-never-flags invariants
├── scripts/sync_skill.py           # Generates the skill scripts (make sync-skill)
├── .github/workflows/ci.yml        # lint + tests + drift gate + CLI smoke (py3.11–3.14)
│
├── docs/                           # USAGE (recipes) · GLOSSARY (acronyms & terms) · DESIGN (decisions)
├── schema/example.sql              # Sample DDL (patients + encounters FK)
├── data-domains.md                 # Field-level rules for all domains + notes
├── format-templates.md             # FHIR R4 / HL7 v2.x / SQL / CSV / JSON specs
├── INSTALL.md                      # Skill installation guide
│
└── synth-data-gen/                 # Claude Code skill — scripts/ are GENERATED (make sync-skill)
    ├── SKILL.md
    ├── references/                 # data-domains.md, format-templates.md
    └── scripts/                    # CLI shims + synthgen/ package copy + standalone validators
```

---

## Validation Details

| Check | What it flags |
|-------|--------------|
| **SSN** | Area codes 001–899 (real IRS assignments) |
| **Email** | Known real domains (gmail.com, yahoo.com, outlook.com, etc.); unrecognized non-reserved domains warn; reserved TLDs/subdomains (`*.example.com`, `.test`, `.invalid`) are safe |
| **Phone** | Numbers outside the 555-01xx fictional range (region-aware for locale packs) |
| **IP Address** | IPs outside RFC 5737 documentation and private ranges |
| **NPI** | **Luhn checksum** (CMS 80840 algorithm): valid checksum + real-range 1-prefix → critical (potential real provider ID); invalid checksum → data-quality warning |
| **MRN** | Values outside the synthetic `MRN-224xxxx` range |
| **NULL distribution** | Warns if no NULLs found (real data always has gaps) |
| **JSON quality** | Checks for `_meta.synthetic` marker |

Results are grouped into three tiers: **CRITICAL** (do not use), **WARNING** (review), **INFO** (statistics). Add `--html report.html` for a self-contained compliance artifact.

---

## Data Domain Reference

Field-level rules for all six built-in domains — data types, value pools, NULL rates, edge cases, and referential integrity rules. See [data-domains.md](data-domains.md).

Key properties across all domains:
- **Realistic distributions** — age, race, ethnicity, and language follow approximate US Census weights
- **Edge-case names** — ~8% of records use international characters, hyphens, apostrophes, CJK characters
- **NULL patterns** — required fields 0%, optional fields 7–12%, soft-delete/end-date fields 30–38%
- **Referential integrity** — child tables always generated after parents; FK values drawn from parent PK pool

---

## Development

```bash
pip install -e ".[dev]"

make test         # 76 tests: parser, generators, notes spans, bundle integrity,
                  # FHIR/HL7 well-formedness, determinism, validator invariants
make lint         # ruff (configured in pyproject.toml)
make sync-skill   # regenerate synth-data-gen/scripts from synthgen/ — REQUIRED
                  # after any package change (CI fails on drift via check-sync)
```

The core invariant enforced by CI: **the validator never flags generator output**
across every generator, format, locale, and dirty-data mode.

## Contributing

To add a new data domain or output format:

1. Add generator functions to `demo_app.py` following the existing pattern
2. Add semantic column-name rules to `schema_app.py` and `synth-data-gen/scripts/generate_from_schema.py`
3. Update `data-domains.md` or `format-templates.md` with field-level rules
4. Ensure all identifiers use safe/reserved ranges
5. Run `validate_synthetic.py` against generated output

## License

This project is not yet licensed. Contact the maintainer before redistributing.
