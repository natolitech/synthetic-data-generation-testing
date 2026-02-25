# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the interactive Streamlit demo
streamlit run demo_app.py

# Generate patient data (CLI)
python example_patient_generator.py -n 100 -f csv
python example_patient_generator.py -n 500 -f json --validate
python example_patient_generator.py -n 200 -f sql -s 123 -o patients.sql

# Validate a synthetic output file
python validate_synthetic.py <file_or_directory>
# Exit codes: 0=pass, 1=warnings, 2=critical issues
```

## Architecture

This project has two layers:

**1. Standalone tools** (root directory)
- `demo_app.py` — Streamlit web UI; all generation logic lives here as functions. Supports all 6 domains, 4 output formats (CSV, JSON, SQL, Parquet), and inline validation.
- `example_patient_generator.py` — CLI script for clinical/patient data only; pattern for how generator scripts should be structured.
- `validate_synthetic.py` — Multi-format validator that checks SSN ranges, email domains, phone prefixes, IP ranges, NPI patterns, NULL distribution, and JSON synthetic markers.

**2. Claude Code skill** (`synth-data-gen/`)
- `SKILL.md` — Skill definition and the primary behavioral instructions for generating data via Claude.
- `references/data-domains.md` — Field-level generation rules for all 6 domains.
- `references/format-templates.md` — Format specifications for FHIR R4, HL7 v2.x, SQL, CSV, JSON, and Parquet.
- `scripts/` — Copies of the validator and patient generator for in-skill use.

## Safety Invariants

Every generated identifier must stay in reserved/fictional ranges. The core ones:

| Field | Safe Range |
|-------|-----------|
| SSN | `987-65-xxxx` |
| Email | `@example.com`, `@example.org`, `@test.invalid` |
| Phone | `555-01xx` |
| IP | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` (RFC 5737) |

Always run `validate_synthetic.py` against generated output before delivery.

## Adding a New Domain or Format

1. Add generator functions in `demo_app.py` following the existing pattern (weighted random choices, NULL injection, edge-case names).
2. Update `synth-data-gen/references/data-domains.md` or `format-templates.md` with field-level rules.
3. Keep `synth-data-gen/scripts/` in sync with the root-level standalone scripts.
4. Validate generated output with `validate_synthetic.py`.
