# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Preferred: use the run.sh entry point for everything
./run.sh demo                          # domain-based Streamlit app (:8501)
./run.sh schema                        # schema-driven Streamlit app (:8502)
./run.sh notes -n 50 --validate        # clinical notes / dictations CLI
./run.sh bundle -n 100 --zip --validate  # linked clinical dataset (5 tables, FHIR/HL7 capable)
./run.sh gen schema/ --rows 100 --validate
./run.sh validate synthetic_output/
./run.sh doctor                        # environment check

# Run the domain-based demo app (6 built-in domains)
streamlit run demo_app.py

# Run the schema-driven app (paste/upload your own DDL)
streamlit run schema_app.py

# Schema-driven CLI — list tables detected in schema/
python synth-data-gen/scripts/generate_from_schema.py schema/ --list-tables

# Schema-driven CLI — generate all tables, CSV output
python synth-data-gen/scripts/generate_from_schema.py schema/ --rows 100 --validate

# Schema-driven CLI — SQL INSERT format for database seeding
python synth-data-gen/scripts/generate_from_schema.py schema/ --format sql --output ./seed_data/

# Clinical notes / dictation transcripts (6 note types, PHI ground-truth spans)
python clinical_notes.py -n 50 --validate --ground-truth
python clinical_notes.py -n 25 -t dictation_transcript -f txt

# Linked clinical dataset: patients → encounters → diagnoses/meds/labs/notes
python clinical_bundle.py -n 100 --validate --zip        # CSV + manifest
python clinical_bundle.py -n 250 --format fhir            # FHIR R4 bundles
python clinical_bundle.py -n 50 --format hl7              # HL7 v2.5.1 ADT/ORU
python clinical_bundle.py -n 80 --locale uk               # locale pack
python clinical_bundle.py -n 60 --dirty                   # dirty data mode

# Generate patient data (standalone CLI)
python example_patient_generator.py -n 100 -f csv
python example_patient_generator.py -n 500 -f json --validate

# Validate any generated file or directory
python validate_synthetic.py <file_or_directory>
# Exit codes: 0=pass, 1=warnings, 2=critical issues
```

## Architecture

The project has three layers:

**1. Standalone tools** (root directory)

- `demo_app.py` — Streamlit app with six hardcoded domain generators (Clinical, Student, HR, IAM, Research, Financial). All generation logic lives here as plain functions. Supports CSV, JSON, SQL INSERT, and Parquet output. Has four output tabs: Preview, Raw Output, Validation, Statistics. The Clinical domain includes notes/dictations via `clinical_notes.py` (tables with a `note_text` column get per-note expanders) and **Full Dataset — linked** mode (renders via `_render_bundle()`: linked cohort, integrity badge, zip + FHIR downloads). Row cap 5000.
- `schema_app.py` — Streamlit app that accepts any SQL DDL (paste or upload). Parses `CREATE TABLE` statements, maps column names to semantic generators, shows an **editable generator grid** (`st.data_editor` + `GENERATOR_REGISTRY`, ~30 generators; PK/FK locked) before generation, and supports single-table or all-tables-with-FK-integrity mode (multi-table runs get a zip download with manifest). Same four output tabs. `_generate_value(col, fake, fk_pool, row_idx, override=None)` applies manual overrides.
- `clinical_notes.py` — CLI + importable module generating synthetic physician notes in **10 types** (progress, H&P, discharge summary, ED, telehealth, procedure, radiology, behavioral health w/ 42 CFR Part 2 banners, patient portal messages, phone call transcripts) rendered as transcribed notes or raw dictation transcripts (spoken punctuation, disfluencies, `[inaudible]`, Spanish interpreter quotes). Embeds safe-range PHI and records **ground-truth PHI spans** (type + char offsets) for de-identification scoring. `NoteBuilder` assembles segments; `make_context(fake, i, **overrides)` + `build_note(ctx, note_type, dictation)` are the composition API used by `clinical_bundle.py`; `NON_DICTATABLE` types are never rendered as dictation; `BH_CONDITIONS` gates behavioral-health notes.
- `clinical_bundle.py` — Referentially-linked cohort generator + CLI. One shared patient/provider pool feeds encounters → diagnoses → **medications** → labs → notes. Correlations: meds from the encounter's actual dx (start ≥ dx onset), condition-biased labs, note identity/dx/timeline match their encounter, radiology findings match indication, BH notes gated to BH/SUD encounters. `check_integrity()` verifies every guarantee per run. **Locale packs** (`LOCALES`, `--locale us|uk|ca|eu`) and **dirty data mode** (`apply_dirty_mode`, `--dirty`, applied strictly after integrity verification). Outputs CSV/JSON/SQL/FHIR/HL7 + `manifest.json` + optional zip.
- `fhir_export.py` — FHIR R4 serializers (Patient, Practitioner, Encounter, Condition, MedicationRequest, Observation, DocumentReference with base64 note payloads) per `format-templates.md` conventions (urn:example: systems, relative references). `cohort_to_bundles()` yields a combined Bundle whose internal references all resolve, plus per-resource-type bundles.
- `hl7_export.py` — HL7 v2.5.1 builders: ADT^A01 (MSH/EVN/PID/PV1/IN1) and ORU^R01 (MSH/PID/OBR/OBX…). Content is delimiter-escaped so messages are always well-formed; `cohort_to_hl7_messages()` yields ADT + ORU files.
- `example_patient_generator.py` — Minimal CLI generator for the clinical patient domain. Reference implementation showing the expected script structure.
- `validate_synthetic.py` — Multi-format PII/PHI validator. Checks SSN ranges, email domains, phone prefixes, IP ranges, NPI patterns, NULL distribution, and JSON synthetic markers.
- `run.sh` — Entry point for all tools (`demo`, `schema`, `notes`, `gen`, `patient`, `validate`, `install-skill`, `doctor`, `update`). Auto-detects a Python with faker/pandas/streamlit (`PYTHON=` overrides).

**2. Claude Code skill** (`synth-data-gen/`)

- `SKILL.md` — Primary behavioral instructions for Claude. Describes the schema-file workflow (auto-detect `schema/` directory) and the manual domain-based workflow. Claude reads this when the skill is invoked.
- `references/data-domains.md` — Field-level generation rules for all 6 built-in domains. Claude reads this during generation to get realistic value pools and NULL rates.
- `references/format-templates.md` — Output format specs for FHIR R4, HL7 v2.x, SQL, CSV, JSON, and Parquet. Claude reads this when FHIR or HL7 output is requested.
- `scripts/generate_from_schema.py` — Standalone CLI script. Reads one or more DDL files, parses all `CREATE TABLE` statements, generates data in FK dependency order (parents before children), and writes one output file per table. Accepts `--rows`, `--seed`, `--format` (csv/json/sql), `--output`, `--tables`, `--validate`, `--list-tables`.
- `scripts/clinical_notes.py` — Copy of the root notes/dictation generator (keep in sync with the root copy).
- `scripts/clinical_bundle.py` — Copy of the root linked-bundle generator (+ `fhir_export.py`, `hl7_export.py` siblings; keep in sync).
- `scripts/validate_synthetic.py` — Copy of the root-level validator for in-skill use.
- `scripts/example_patient_generator.py` — Copy of the root-level patient generator.

**3. Reference schemas** (`schema/`)

- `schema/example.sql` — Sample DDL with `patients` and `encounters` tables (FK relationship) used for testing and as a starting point.

## Semantic Column Mapping

Both `schema_app.py` and `generate_from_schema.py` map column names to generators using `re.search` substring patterns. The priority order matters — first match wins. Key patterns:

- Name fields: `first_name/fname` → `fake.first_name()`, `last_name/lname/surname` → `fake.last_name()`
- Contact: `email` → `@example.com`, `phone/mobile/telephone` → `555-01xx`, `fax` → `555-01xx` (~38% NULL)
- Identity: `ssn/social_security` → `987-65-xxxx`, `mrn/medical_record` → `MRN-224xxxx`, any column containing `npi` → `9xxxxxxxxx`
- Location: `city` → `fake.city()`, `state` → `fake.state_abbr()`, `zip/postal_code` → `fake.zipcode()`
- Dates: `created_at` → recent datetime, `hire_date/start_date` → random past date, `end_date/termination_date` → ~60% NULL
- Clinical: `encounter_type` → weighted clinical values, `icd10/dx_code` → ICD-10 pool, `cpt_code` → CPT pool
- Clinical notes: `note_type` → note-type pool, `transcription_status` → status pool, `author/dictated_by/signed_by` → "Dr. First Last, MD", `dictation/transcript` → raw dictation transcript, `note_text/progress_note/discharge_summary/hpi/chief_complaint/narrative` → full transcribed note (truncated to `VARCHAR(n)` length; TEXT columns keep full note)
- Financial: `salary/wage` → randint(35000, 250000), `amount/charge/price` → uniform(10, 5000)
- Type fallback: `INT` → randint, `DECIMAL` → uniform, `DATE` → random date, `TIMESTAMP` → recent datetime, `VARCHAR` → `fake.word()`

When adding new semantic rules, add them to **both** `schema_app.py` and `synth-data-gen/scripts/generate_from_schema.py` — they contain parallel copies of `_generate_value()`.

## Safety Invariants

Every generated identifier must stay in reserved/fictional ranges:

| Field | Safe Range |
|-------|-----------|
| SSN | `987-65-xxxx` |
| Email | `@example.com`, `@example.org`, `@test.invalid` |
| Phone | `555-01xx` |
| IP | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` (RFC 5737) |

Always run `validate_synthetic.py` against generated output before delivery.

## Adding a New Domain or Format

1. Add generator functions to `demo_app.py` following the existing pattern (weighted random choices, NULL injection, edge-case name injection).
2. Add semantic column-name rules to `_generate_value()` in both `schema_app.py` and `synth-data-gen/scripts/generate_from_schema.py`.
3. If the generator lives in a shared module (like `clinical_notes.py`), copy it into `synth-data-gen/scripts/` so the skill stays self-contained — and keep the copies in sync.
4. Update `synth-data-gen/references/data-domains.md` (and the root `data-domains.md` copy) with field-level rules.
5. For new output formats, update `synth-data-gen/references/format-templates.md`.
6. Validate generated output with `validate_synthetic.py`.
