# Synthetic Data Generation & Testing

Generate realistic but **completely fictional** data for development, testing, QA, and demos — without risking exposure of real PII or PHI.

## Overview

This project provides four ways to generate synthetic data:

| Tool | What it does |
|------|-------------|
| `run.sh` | **Start here** — one command to run everything (apps, CLIs, validation) |
| `demo_app.py` | Interactive Streamlit UI — pick a built-in domain and generate data in your browser |
| `schema_app.py` | Interactive Streamlit UI — paste or upload your own SQL schema and generate matching data |
| `generate_from_schema.py` | CLI script — point it at a `schema/` directory and it generates data for every table automatically |
| `clinical_notes.py` | CLI — synthetic physician notes & dictation transcripts with embedded (safe-range) PHI and ground-truth PHI spans |

All tools share the same safety guarantees and semantic column mapping. The Claude Code skill (`synth-data-gen/`) wraps these tools and invokes them automatically when you ask for test data in Claude Code. See [PLAN.md](PLAN.md) for the roadmap.

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
./run.sh gen schema/ --rows 200 --validate       # schema-driven CLI
./run.sh validate synthetic_output/              # PII/PHI validation
./run.sh doctor     # environment check
```

`run.sh` auto-detects a Python interpreter with the required dependencies (override with `PYTHON=`), always runs from the repo root, and passes extra flags straight through to the underlying tool.

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
`telehealth_note`, `procedure_note` (or `mix`). Dictation transcripts include
realistic ASR artifacts — spoken punctuation ("period", "comma", "colon"),
"new paragraph" commands, disfluencies, `[inaudible]` markers, and
mid-sentence corrections.

**Ground-truth PHI spans.** Every note can be annotated with the exact character
offsets of each PHI instance (`PATIENT`, `MRN`, `DOB`, `SSN`, `PHONE`, `ADDRESS`,
`PROVIDER`, `NPI`, `DATE`, `ENCOUNTER`, `CONTACT`, `ICD10`). Use them to score
de-identification pipelines for recall/precision — see
`clinical_notes_ground_truth.json` written by `--ground-truth`.

Schema-driven tools also pick up note columns automatically: `note_text`,
`dictation_text`, `progress_note`, `hpi`, `chief_complaint`, `note_type`,
`author`, `transcription_status` are all mapped semantically in
`schema_app.py` and `generate_from_schema.py`.

---

## The Two Streamlit Apps

### demo_app.py — Domain-based generator

Use when you want to generate data for a **standard enterprise domain** without providing a schema. The domains and their tables are built in.

**Sidebar controls:** domain, table type, row count (5–500), random seed, output format
**Tabs after generation:** Preview · Raw Output · Validation · Statistics

| Domain | Tables |
|--------|--------|
| Clinical / EHR | Patients, Encounters, Diagnoses, Lab Results, Clinical Notes / Dictations |
| Student Records | Students, Course Enrollment |
| Human Resources | Employees |
| Identity & Access | User Accounts, Entitlements |
| Research | Research Subjects, Studies |
| Financial / Billing | Claims |

### schema_app.py — Schema-driven generator

Use when you have your **own database schema** and want data that matches it exactly.

1. **Paste DDL** or upload a `.sql` file (or click "Load example schema" to try a sample)
2. **Review the parsed schema** — a table shows each column, its SQL type, and the inferred generator so you can verify the mapping before generating
3. **Choose single table or all tables** — multi-table mode resolves foreign keys in dependency order so joins work
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

Checks performed: SSN area codes, email domains, phone ranges, IP ranges, NPI format, NULL distribution, JSON `_meta.synthetic` marker.

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
├── demo_app.py                     # Streamlit UI — domain-based generation (6 built-in domains)
├── schema_app.py                   # Streamlit UI — schema-driven generation (paste/upload DDL)
├── clinical_notes.py               # CLI — clinical notes & dictation transcripts with PHI spans
├── example_patient_generator.py    # CLI — standalone patient record generator (17 fields)
├── validate_synthetic.py           # CLI — PII/PHI validator for generated files
├── requirements.txt                # faker, pandas, streamlit
├── PLAN.md                         # Improvement roadmap
│
├── schema/                         # Example SQL schemas for testing
│   └── example.sql                 # patients + encounters with FK relationship
│
├── data-domains.md                 # Field-level generation rules for all 6 domains + notes
├── format-templates.md             # Output format specs: FHIR R4, HL7 v2.x, SQL, CSV, JSON, Parquet
├── INSTALL.md                      # Skill installation and deployment guide
│
└── synth-data-gen/                 # Self-contained Claude Code skill (copy to .claude/skills/)
    ├── SKILL.md                    # Skill definition and behavioral instructions for Claude
    ├── references/
    │   ├── data-domains.md         # Domain generation rules (read by Claude during generation)
    │   └── format-templates.md     # Format specifications (read by Claude for FHIR/HL7 output)
    └── scripts/
        ├── generate_from_schema.py # Schema-driven generator — reads DDL, outputs synthetic data
        ├── clinical_notes.py       # Clinical notes & dictation generator
        ├── validate_synthetic.py   # PII/PHI validator
        └── example_patient_generator.py  # Example generator script
```

---

## Validation Details

| Check | What it flags |
|-------|--------------|
| **SSN** | Area codes 001–899 (real IRS assignments) |
| **Email** | Known real domains (gmail.com, yahoo.com, outlook.com, etc.) |
| **Phone** | Numbers outside the 555-01xx fictional range |
| **IP Address** | IPs outside RFC 5737 documentation and private ranges |
| **NPI** | 10-digit numbers starting with 1 (potential real provider IDs) |
| **NULL distribution** | Warns if no NULLs found (real data always has gaps) |
| **JSON quality** | Checks for `_meta.synthetic` marker |

Results are grouped into three tiers: **CRITICAL** (do not use), **WARNING** (review), **INFO** (statistics).

---

## Data Domain Reference

Field-level rules for all six built-in domains — data types, value pools, NULL rates, edge cases, and referential integrity rules. See [data-domains.md](data-domains.md).

Key properties across all domains:
- **Realistic distributions** — age, race, ethnicity, and language follow approximate US Census weights
- **Edge-case names** — ~8% of records use international characters, hyphens, apostrophes, CJK characters
- **NULL patterns** — required fields 0%, optional fields 7–12%, soft-delete/end-date fields 30–38%
- **Referential integrity** — child tables always generated after parents; FK values drawn from parent PK pool

---

## Contributing

To add a new data domain or output format:

1. Add generator functions to `demo_app.py` following the existing pattern
2. Add semantic column-name rules to `schema_app.py` and `synth-data-gen/scripts/generate_from_schema.py`
3. Update `data-domains.md` or `format-templates.md` with field-level rules
4. Ensure all identifiers use safe/reserved ranges
5. Run `validate_synthetic.py` against generated output

## License

This project is not yet licensed. Contact the maintainer before redistributing.
