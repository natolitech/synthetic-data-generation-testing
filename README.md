# Synthetic Data Generation & Testing

Generate realistic but **completely fictional** data for development, testing, QA, and demos — without risking exposure of real PII or PHI.

## Overview

This project provides tools for generating synthetic data across six enterprise domains (Clinical/EHR, Student Records, HR, Identity & Access Management, Research, and Financial/Billing). Every generated identifier is drawn from **reserved/test ranges** so synthetic records can never collide with real people.

Use it to:
- Populate dev/test databases with realistic volumes
- Build demos and training environments
- Test ETL pipelines, reports, and dashboards
- Validate data-handling code without compliance risk

## Safety Guarantees

All generated identifiers use officially reserved or fictional ranges:

| Field | Safe Range | Standard |
|-------|-----------|----------|
| SSN | `987-65-xxxx` | IRS test range |
| Email | `@example.com`, `@example.org`, `@test.invalid` | RFC 2606 reserved domains |
| Phone | `555-01xx` | NANPA reserved for fiction |
| IP Address | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` | RFC 5737 documentation ranges |
| MRN | `MRN-224xxxx` | Synthetic prefix (no real system uses this) |
| Patient ID | `SYN-000001` | Synthetic prefix |
| Student ID | `SYN-100000` | Synthetic prefix |
| Employee ID | `EMP-200000` | Synthetic prefix |
| Credit Card | `4242424242424242` | Stripe test numbers |

The included validator (`validate_synthetic.py`) checks generated files and flags any value that falls outside these safe ranges.

## Supported Domains

| Domain | Tables |
|--------|--------|
| **Clinical / EHR** | Patients, Encounters, Diagnoses, Lab Results |
| **Student Records** | Students, Course Enrollment |
| **Human Resources** | Employees |
| **Identity & Access** | User Accounts, Entitlements |
| **Research** | Research Subjects, Studies |
| **Financial / Billing** | Claims |

Each domain generates data with realistic distributions, NULL patterns, edge cases, and referential integrity. See [data-domains.md](data-domains.md) for full field-level generation rules.

## Supported Output Formats

- **CSV** — UTF-8 with synthetic-data header comment
- **JSON** — Collection format with `_meta.synthetic` marker
- **SQL INSERT** — PostgreSQL-flavored with `ON CONFLICT` handling
- **FHIR R4** — US Core Patient/Encounter bundles
- **HL7 v2.x** — ADT^A01, ORU^R01 message templates
- **Parquet** — Via pandas + pyarrow

See [format-templates.md](format-templates.md) for format specifications and examples.

## Quick Start

### Install dependencies

```bash
pip install faker pandas streamlit
```

Or use the requirements file:

```bash
pip install -r requirements.txt
```

### Run the demo app

```bash
streamlit run demo_app.py
```

This launches an interactive web UI where you can select domains, table types, row counts, and output formats.

### Generate patient data from the CLI

```bash
# Generate 100 patients as CSV (default)
python example_patient_generator.py

# Generate 500 patients as JSON with validation
python example_patient_generator.py -n 500 -f json --validate

# Generate SQL output with a specific seed
python example_patient_generator.py -n 200 -f sql -s 123 -o patients.sql
```

### Validate a synthetic data file

```bash
python validate_synthetic.py synthetic_patients.csv
python validate_synthetic.py output_directory/ --format json
```

## Demo Application

The Streamlit app (`demo_app.py`) provides an interactive UI for generating and inspecting synthetic data.

**Sidebar controls:**
- Domain selector (all 6 domains)
- Table type selector (domain-specific)
- Row count slider (5–500)
- Random seed input (for reproducibility)
- Output format (Table Preview, CSV, JSON, SQL INSERT)

**After generation, four tabs are available:**
1. **Preview** — Interactive dataframe display
2. **Raw Output** — Formatted CSV/JSON/SQL with a download button
3. **Validation** — Inline PII/PHI checker with three severity tiers
4. **Statistics** — Row/column counts, NULL distribution chart, column descriptors

## CLI Usage

### example_patient_generator.py

Standalone generator for clinical patient records.

```
usage: example_patient_generator.py [-h] [--rows ROWS] [--seed SEED]
                                     [--format {csv,json,sql}]
                                     [--output OUTPUT] [--validate]

Options:
  -n, --rows     Number of patient records (default: 100)
  -s, --seed     Random seed for reproducibility (default: 42)
  -f, --format   Output format: csv, json, sql (default: csv)
  -o, --output   Output file path (default: stdout)
  --validate     Run validation after generation
```

Generated records include 17 fields: patient_id, mrn, first_name, last_name, dob, gender, race, ethnicity, ssn, email, phone, address_line1, address_city, address_state, address_zip, preferred_language, and deceased_flag.

### validate_synthetic.py

Multi-format validator that checks for PII/PHI leakage and data quality.

```bash
python validate_synthetic.py <file_or_directory> [--format csv|json|sql]
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `1` | Warnings found (review recommended) |
| `2` | Critical issues found (do not use) |

## Using as a Claude Code Skill

The `synth-data-gen/` directory is a self-contained Claude Code skill. To install it:

```bash
cp -r synth-data-gen/ /path/to/your/project/.claude/skills/synth-data-gen/
```

Once installed, you can invoke it with natural language in Claude Code:

- *"Generate 200 synthetic patient records as CSV"*
- *"Create test data for a student enrollment system"*
- *"Build me a fake HR employee table with 500 rows"*
- *"Generate FHIR R4 Patient bundles for testing"*
- *"Validate this synthetic data file for PII leakage"*

The skill includes reference documents (`data-domains.md`, `format-templates.md`) that guide Claude on field-level generation rules and output format specifications.

## Project Structure

```
synthetic-data-generation-testing/
├── demo_app.py                          # Streamlit interactive web UI
├── example_patient_generator.py         # Standalone CLI patient generator
├── validate_synthetic.py                # Multi-format PII/PHI validator
├── requirements.txt                     # Python dependencies
├── SKILL.md                             # Skill installation guide
├── INSTALL.md                           # Setup instructions
├── data-domains.md                      # Domain generation rules (reference)
├── format-templates.md                  # Output format specs (reference)
├── .gitignore
├── synth-data-gen/                      # Claude Code skill (self-contained)
│   ├── SKILL.md                         # Skill definition
│   ├── references/
│   │   ├── data-domains.md              # Domain generation rules
│   │   └── format-templates.md          # Output format specifications
│   └── scripts/
│       ├── example_patient_generator.py # Generator script
│       └── validate_synthetic.py        # Validator script
└── .claude/
    └── settings.local.json              # Local Claude Code settings
```

## Validation

The validator (`validate_synthetic.py`) performs the following checks:

| Check | What it flags |
|-------|--------------|
| **SSN** | Area codes 001–899 (real IRS assignments) |
| **Email** | Real domains (gmail.com, yahoo.com, outlook.com, etc.) |
| **Phone** | Numbers outside the 555-01xx fictional range |
| **IP Address** | IPs outside RFC 5737 documentation and private ranges |
| **NPI** | 10-digit numbers starting with 1 (potential real provider IDs) |
| **NULL distribution** | Warns if no NULLs found (real data always has gaps) |
| **CSV quality** | Column diversity checks |
| **JSON quality** | Checks for `_meta.synthetic` marker |

Results are grouped into three severity tiers:
- **CRITICAL** — Potentially real PII detected; do not use the data
- **WARNING** — Values that could match real data; review recommended
- **INFO** — Informational notes and statistics

## Data Domain Reference

Each domain has detailed field-level generation rules covering data types, value distributions, NULL rates, and edge cases. Key highlights:

- **Realistic distributions** — Age, race, ethnicity, and language follow approximate US Census weights
- **Edge-case names** — International characters, hyphens, apostrophes, CJK characters
- **NULL patterns** — Required fields 0%, important fields 2–5%, optional 10–20%, rarely-populated 30–50%
- **Temporal realism** — Timezone-aware timestamps, business-hours clustering, multi-day encounter spans
- **Referential integrity** — Encounters link to patients, diagnoses link to encounters, etc.

Full details: [data-domains.md](data-domains.md)

## Contributing

Contributions are welcome. To add a new data domain or output format:

1. Add generator functions following the patterns in `demo_app.py`
2. Update `data-domains.md` or `format-templates.md` with field-level rules
3. Ensure all identifiers use safe/reserved ranges
4. Run `validate_synthetic.py` against your generated output
5. Test the Streamlit demo to verify the new domain appears correctly

## License

This project is not yet licensed. Contact the maintainer before redistributing.
