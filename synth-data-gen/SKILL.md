---
name: synth-data-gen
description: >
  Generate realistic synthetic data to replace production PII/PHI in development and testing
  environments. Use this skill ANY time a developer needs test data, sample data, mock data,
  fake data, or dummy data — especially when the underlying production data contains personally
  identifiable information (PII) or protected health information (PHI). Also trigger when a
  developer asks to copy, export, extract, or replicate production data for dev/test/staging,
  or when they mention needing data that "looks like production." This skill ensures HIPAA,
  FERPA, and institutional compliance by generating statistically plausible but entirely
  fictional data — never redacted or masked production data.
---

# Synthetic Data Generator

## Why This Skill Exists

Developers frequently request production data to test new systems. When that data contains
PII (names, SSNs, emails, addresses) or PHI (diagnoses, medications, lab results, MRNs),
using it in non-production environments violates HIPAA, FERPA, and institutional policy —
even if "just for testing." Masking or redacting real data is error-prone and still carries
residual risk of re-identification.

This skill generates **entirely fictional data** that preserves the statistical properties,
relationships, and edge cases developers need — with zero compliance risk.

## Core Principles

1. **Never copy production data.** Every value must be invented from scratch.
2. **Referential integrity matters.** If a patient has encounters, those encounters reference
   a valid fictional patient_id. Foreign keys work. Joins work.
3. **Statistical plausibility over perfection.** Distributions should feel realistic (e.g.,
   age distributions skew appropriately, diagnoses correlate with demographics) but need not
   match production exactly.
4. **Edge cases by design.** Always include a realistic mix of nulls, boundary values,
   special characters in names, hyphenated names, international characters, and format
   variations that break brittle parsers.
5. **Deterministic when requested.** Support seeded generation so developers can reproduce
   the same dataset for regression testing.

## Workflow

### Step 1 — Understand the Request

**First, check for a schema directory.** Look for schema files in the project before asking
questions. Common locations:

```
schema/          db/schema/        database/schema/
migrations/      ddl/              sql/
db/migrations/   prisma/schema/    *.sql (project root)
```

If schema files exist, **go directly to the Schema File Workflow below** — no need to ask
for schema details.

If no schema files exist, ask the developer:

- **Domain**: What system is this for? (clinical/EHR, student records, HR, identity/IAM,
  research, financial, or custom)
- **Unstructured text**: Do they need clinical notes or dictation transcripts with embedded
  PHI? If yes, use `scripts/clinical_notes.py` (below) — it includes ground-truth PHI spans
  for de-identification testing.
- **Schema**: Do they have a DDL, JSON schema, CSV headers, or sample (redacted) structure?
  If they provide a production sample, **do not echo it back** — extract only the schema.
- **Volume**: How many records? (default: 100 rows for primary tables, proportional for
  related tables)
- **Format**: CSV, JSON, SQL INSERT statements, FHIR bundles, HL7 segments, Parquet-via-Python,
  or raw Python/TypeScript generator script?
- **Relationships**: Are there parent/child or many-to-many relationships across tables?
- **Specific edge cases**: Any particular scenarios they need? (e.g., patients with 50+
  encounters, students enrolled in zero courses, employees with future start dates)

If the developer just says "I need test data for the patient table," that's enough to start.
Use sensible defaults and let them refine.

---

## Schema File Workflow

When a project has a `schema/` directory (or equivalent), use this workflow instead of the
manual generation steps below.

### Step A — Discover the Schema

```bash
python scripts/generate_from_schema.py <schema_dir_or_file> --list-tables
```

This prints every detected table, its primary key, and any foreign key relationships. Share
this list with the developer to confirm the scope before generating.

### Step B — Generate Synthetic Data

```bash
# Generate 100 rows per table, CSV output (default)
python scripts/generate_from_schema.py schema/

# Specify rows, seed, and output format
python scripts/generate_from_schema.py schema/ --rows 500 --seed 42 --format csv --output ./synthetic/

# JSON format for API mocking
python scripts/generate_from_schema.py schema/ --format json --output ./test_fixtures/

# SQL INSERT for seeding a database directly
python scripts/generate_from_schema.py schema/ --format sql --output ./seed_data/

# Only generate specific tables
python scripts/generate_from_schema.py schema/ --tables patients encounters --rows 200

# Generate and validate in one step
python scripts/generate_from_schema.py schema/ --rows 100 --validate
```

The script automatically:
- Parses all `CREATE TABLE` statements across one or multiple files
- Infers generators from column names (e.g., `first_name` → `fake.first_name()`,
  `email` → safe `@example.com` address, `ssn` → `987-65-xxxx`)
- Generates parent tables before child tables so foreign keys resolve correctly
- Outputs one file per table in the requested format
- Optionally validates output for accidental PII/PHI leakage

### Step C — Validate

```bash
python scripts/validate_synthetic.py <output_dir>
```

Exit codes: `0` = clean, `1` = warnings (review), `2` = critical (do not use).

### Step C+ — Clinical Notes / Dictations (when unstructured PHI is requested)

```bash
# Mix of 6 note types, ~35% rendered as raw dictation transcripts
python scripts/clinical_notes.py -n 50 --validate --ground-truth

# Only raw dictations, one .txt per note + PHI ground-truth sidecar
python scripts/clinical_notes.py -n 25 -t dictation_transcript -f txt --ground-truth

# Specific note type: progress_note | history_physical | discharge_summary |
#                     ed_note | telehealth_note | procedure_note
python scripts/clinical_notes.py -n 10 -t discharge_summary -f json
```

Notes embed safe-range PHI (names, MRN, DOB, SSN 987-65-xxxx, phones 555-01xx,
NPI, addresses) and ship with **ground-truth PHI spans** (type + character
offsets) so de-identification tools can be scored for recall/precision. Columns
named `note_text`, `dictation_text`, `progress_note`, `hpi`, `chief_complaint`,
etc. in a DDL schema are also populated automatically by
`generate_from_schema.py`.

### Step C++ — Linked clinical bundle (full EHR dataset, FHIR/HL7)

When the developer needs a *coherent multi-table dataset* (joys that actually
join, timelines that line up) or interoperability fixtures, use the bundle
generator instead of independent tables:

```bash
# 100 patients → encounters → diagnoses/labs/notes, CSV + manifest + zip
python scripts/clinical_bundle.py -n 100 --validate --zip

# FHIR R4 Bundle (Patient/Practitioner/Encounter/Condition/Observation/
# DocumentReference — all internal references resolve) + per-type bundles
python scripts/clinical_bundle.py -n 250 --format fhir

# HL7 v2.5.1 ADT^A01 admit + ORU^R01 lab messages
python scripts/clinical_bundle.py -n 50 --format hl7
```

Guarantees: encounters reference the same patient pool; diagnoses/meds/labs/notes
reference real encounters; medications correlate with the encounter's diagnoses
(start dates follow onset); labs are condition-biased; note narrative embeds the
actual patient identity and the encounter's principal diagnosis; DOB < admit <
discharge and note times fall inside the encounter window. Locale packs
(`--locale us|uk|ca|eu`) localize names/addresses/phones with region-appropriate
fictional ranges; dirty mode (`--dirty`) adds realistic data-quality problems
after integrity verification. Every run writes `manifest.json` (seed, row counts,
versions, locale, dirty flag) for reproducibility, plus
`clinical_notes_ground_truth.json`.

### Step D — Deliver

Tell the developer:
- What tables were generated and how many rows each contains
- The seed used (for reproducibility)
- Any columns where the generator fell back to a type-based default (not semantic)
  so they can verify those look right
- The output directory path

---

### Step 2 — Select a Domain Profile

Read the appropriate domain reference for field-level generation rules:

```
Read references/data-domains.md
```

This file contains field definitions, realistic value pools, and distribution guidance for
each supported domain. If the request spans multiple domains (e.g., a student health portal),
combine the relevant sections.

If no domain fits, build a custom profile from the schema provided.

### Step 3 — Generate the Data

Choose a generation strategy based on the request:

**For small datasets (≤500 rows, ≤5 tables):**
Generate data inline using Python with the `Faker` library as a foundation, enhanced with
domain-specific value pools from the reference file. Output directly in the requested format.

**For large datasets or complex schemas (>500 rows or >5 tables):**
Generate a **reusable Python script** the developer can run and modify. The script should:
- Accept CLI arguments for row count and random seed
- Use Faker + custom providers for domain-specific fields
- Maintain referential integrity across tables via shared ID pools
- Output to the requested format(s)
- Include a `--validate` flag that checks for referential integrity and null distributions

**For FHIR/HL7 output:**
Read the format-specific reference:
```
Read references/format-templates.md
```

### Step 4 — Validate the Output

Before delivering, run the validation script:

```bash
python scripts/validate_synthetic.py <output_file_or_directory>
```

This checks for:
- Accidental real-world data leakage (known real SSN prefixes, real hospital NPIs, etc.)
- Referential integrity violations
- Null/edge case coverage
- Format compliance

If validation flags issues, fix them before presenting results.

### Step 5 — Deliver with Context

When presenting the generated data or script:
- State clearly that **all data is synthetic and contains no real PII/PHI**
- Note the random seed used (if applicable) so the dataset is reproducible
- List any assumptions made about distributions or relationships
- If a generator script was created, include usage instructions

## Generation Rules — Quick Reference

These rules apply universally. Domain-specific rules are in `references/data-domains.md`.

### Names
- Use Faker's name generators, but inject diversity: international characters (é, ñ, ü),
  hyphenated surnames, suffixes (Jr., III), prefixes (Dr., Rev.)
- Include at least 5% of records with names that stress-test systems: O'Brien, García-López,
  Müller, names with apostrophes, spaces, and diacritics
- Never use names of real public figures

### Identifiers
- **SSNs**: Use the 987-65-xxxx range (IRS-designated test range) or 900-999 area numbers
  (never assigned to real people)
- **MRNs**: Generate in the format the target system uses, with realistic prefixes
- **Student IDs**: Use clearly fictional prefixes (e.g., SYN-xxxxxx)
- **Email addresses**: Use `@example.com`, `@example.org`, or `@test.invalid` domains
  (RFC 2606 reserved domains — guaranteed non-routable)
- **Phone numbers**: Use 555-01xx range (NANPA reserved for fiction)
- **IP addresses**: Use RFC 5737 documentation ranges (192.0.2.0/24, 198.51.100.0/24,
  203.0.113.0/24)

### Dates
- Shift all dates to plausible ranges but avoid exact current dates
- Birth dates should produce realistic age distributions for the domain
- Include edge cases: leap year births, century boundaries, future dates where appropriate

### Addresses
- Use Faker-generated addresses; verify they don't accidentally match real addresses of
  note (hospitals, government buildings)
- Include a mix of US formats, PO boxes, APO/FPO addresses, and international formats
  where the system is expected to handle them

### Financial
- Credit card numbers: Use Stripe/Braintree test card ranges (4242424242424242, etc.)
- Bank accounts: Generate random digits with valid check digit algorithms
- Never generate real routing numbers

### Clinical / PHI
- ICD-10 codes: Use real code formats but ensure clinical plausibility
  (don't assign pregnancy codes to 80-year-old males)
- Medications: Use real drug names but pair with plausible diagnoses
- Lab values: Generate within physiologically possible ranges, with ~10% abnormal
- Include realistic co-morbidity patterns

## Output Format Examples

### CSV (default for tabular data)
```csv
patient_id,first_name,last_name,dob,ssn,mrn,email,phone
SYN-000001,María,García-López,1956-03-12,987-65-0001,MRN-2240001,maria.garcia@example.com,555-0101
SYN-000002,James,O'Brien,1989-11-28,987-65-0002,MRN-2240002,james.obrien@example.org,555-0102
```

### SQL INSERT
```sql
INSERT INTO patients (patient_id, first_name, last_name, dob, ssn, mrn)
VALUES ('SYN-000001', 'María', 'García-López', '1956-03-12', '987-65-0001', 'MRN-2240001');
```

### JSON (for API mocking)
```json
{
  "patients": [
    {
      "patient_id": "SYN-000001",
      "name": {"given": "María", "family": "García-López"},
      "birthDate": "1956-03-12",
      "identifier": [
        {"system": "urn:oid:2.16.840.1.113883.4.1", "value": "987-65-0001"},
        {"system": "urn:example:mrn", "value": "MRN-2240001"}
      ]
    }
  ]
}
```

### Python Generator Script (for large/repeatable datasets)
When generating a script, follow this structure:
```python
#!/usr/bin/env python3
"""Synthetic data generator for [system name].
All data is fictional. No real PII/PHI is used or referenced.
Seed: {seed} | Generated: {timestamp}
"""
import argparse
from faker import Faker
# ... domain-specific generation logic
```

## Common Pitfalls to Avoid

- **Don't mask real data** — generate from scratch. Masking leaves patterns that can be
  reversed.
- **Don't use `@gmail.com` or `@yahoo.com`** for fake emails — these are real domains and
  messages could reach real people.
- **Don't hardcode a single gender/ethnicity/age** — realistic data has diversity.
- **Don't skip NULLs** — production data always has missing fields. Include ~5-15% nulls
  in optional columns.
- **Don't forget referential integrity** — orphan records or dangling foreign keys defeat
  the purpose of realistic test data.
- **Don't use sequential dates** — real data has temporal clustering, gaps, and patterns.

## When the Developer Pushes Back

If a developer insists they need "real" production data because synthetic won't work:

1. Ask what specific property of the data they need to preserve (distributions? edge cases?
   specific error patterns?)
2. Offer to generate synthetic data that matches those properties
3. If they need to reproduce a specific bug, offer to create a minimal synthetic reproduction
   case that exhibits the same behavior
4. Escalate to the security team if they insist — this is a policy matter, not a tooling
   limitation

## Dependencies

The generated scripts use these Python libraries (install as needed):
- `faker` — core synthetic data generation
- `pandas` — tabular data manipulation and output
- `pyarrow` — Parquet output (if requested)

Install: `pip install faker pandas pyarrow`
