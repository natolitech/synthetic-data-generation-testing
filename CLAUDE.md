# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

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

- `demo_app.py` — Streamlit app with six hardcoded domain generators (Clinical, Student, HR, IAM, Research, Financial). All generation logic lives here as plain functions. Supports CSV, JSON, SQL INSERT, and Parquet output. Has four output tabs: Preview, Raw Output, Validation, Statistics.
- `schema_app.py` — Streamlit app that accepts any SQL DDL (paste or upload). Parses `CREATE TABLE` statements, maps column names to semantic generators, shows a preview of inferred generators before generation, and supports single-table or all-tables-with-FK-integrity mode. Same four output tabs.
- `example_patient_generator.py` — Minimal CLI generator for the clinical patient domain. Reference implementation showing the expected script structure.
- `validate_synthetic.py` — Multi-format PII/PHI validator. Checks SSN ranges, email domains, phone prefixes, IP ranges, NPI patterns, NULL distribution, and JSON synthetic markers.

**2. Claude Code skill** (`synth-data-gen/`)

- `SKILL.md` — Primary behavioral instructions for Claude. Describes the schema-file workflow (auto-detect `schema/` directory) and the manual domain-based workflow. Claude reads this when the skill is invoked.
- `references/data-domains.md` — Field-level generation rules for all 6 built-in domains. Claude reads this during generation to get realistic value pools and NULL rates.
- `references/format-templates.md` — Output format specs for FHIR R4, HL7 v2.x, SQL, CSV, JSON, and Parquet. Claude reads this when FHIR or HL7 output is requested.
- `scripts/generate_from_schema.py` — Standalone CLI script. Reads one or more DDL files, parses all `CREATE TABLE` statements, generates data in FK dependency order (parents before children), and writes one output file per table. Accepts `--rows`, `--seed`, `--format` (csv/json/sql), `--output`, `--tables`, `--validate`, `--list-tables`.
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
3. Update `synth-data-gen/references/data-domains.md` with field-level rules.
4. For new output formats, update `synth-data-gen/references/format-templates.md`.
5. Validate generated output with `validate_synthetic.py`.
