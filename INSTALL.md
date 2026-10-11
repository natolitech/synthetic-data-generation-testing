# Synthetic Data Generator — Claude Code Skill

The `synth-data-gen/` directory is a self-contained Claude Code skill: install
it once and Claude Code can generate synthetic test data whenever you ask.

> **Note:** the scripts inside `synth-data-gen/scripts/` are **generated** from
> the canonical `synthgen/` package by `make sync-skill`. Never edit them by
> hand — CI fails on drift.

## Install the skill

```bash
# Project-level (recommended — skill travels with the repo)
cp -r synth-data-gen/ /path/to/your/project/.claude/skills/synth-data-gen/

# Or user-level (available in all projects)
cp -r synth-data-gen/ ~/.claude/skills/synth-data-gen/

# Or from the repo root
./run.sh install-skill
```

## Python dependencies

The skill's scripts need `faker` and `pandas` in the target environment:

```bash
pip install faker pandas
```

## How developers use it

Once installed, invoke naturally in Claude Code:

```
> I need test data for the patient demographics table
> Generate 500 synthetic encounters with related diagnoses, meds, and labs in CSV
> Create a FHIR Patient bundle with 50 records for our API mock server
> Populate our test database from the schema/ directory
> Generate 200 doctor's notes as raw dictation transcripts with PHI annotations
> Score our de-identification service against annotated synthetic notes
```

The skill will:
1. Auto-detect a `schema/` directory (`schema/`, `db/schema/`, `migrations/`, `ddl/`, `sql/`) and run schema-driven generation if present
2. Otherwise ask about domain, volume, format — or generate clinical notes / linked bundles for unstructured-PHI needs
3. Generate data with every identifier in reserved/fictional ranges (SSN `987-65-xxxx`, phones `555-01xx`, RFC 2606 emails, Luhn-valid 9-prefix NPIs)
4. Run PII/PHI validation before delivery (`0=pass 1=warnings 2=critical`)
5. Deliver with a clear "all data is synthetic" attestation, plus `manifest.json` for reproducibility

## What's included

```
synth-data-gen/
├── SKILL.md                          # Behavioral instructions for Claude
├── references/
│   ├── data-domains.md               # Field-level rules for all domains + notes
│   └── format-templates.md           # FHIR R4 / HL7 v2.x / SQL / CSV / JSON specs
└── scripts/                          # GENERATED — do not edit (make sync-skill)
    ├── synthgen/                     # The full package copy (self-contained)
    ├── generate_from_schema.py       # Schema-driven CLI (shim → synthgen.schema_cli)
    ├── clinical_notes.py             # Notes & dictations CLI (shim → synthgen.notes)
    ├── clinical_bundle.py            # Linked cohort CLI (shim → synthgen.bundle)
    ├── validate_synthetic.py         # Standalone PII/PHI validator
    └── example_patient_generator.py  # Minimal reference generator
```

Because the package ships inside the skill, every CLI works from any directory
with no repo checkout — including `python -m synthgen deid` (de-id scoring) and
`python -m synthgen fhir-check` (FHIR conformance).

## Validation

```bash
python scripts/validate_synthetic.py output_dir/
```

It checks SSN ranges, real email domains, phone ranges, RFC 5737 IP ranges,
**NPI Luhn checksums** (valid checksum + real-range prefix = critical), MRN
synthetic range, NULL distribution, and JSON synthetic markers. Add
`--html report.html` for a self-contained compliance artifact.

Exit codes: `0` pass · `1` warnings · `2` critical — do not use.

## Further reading

- [../docs/USAGE.md](docs/USAGE.md) — task-oriented recipes (seeding, de-id scoring, FHIR fixtures)
- [../docs/GLOSSARY.md](docs/GLOSSARY.md) — every acronym and synthetic-data term explained
- [../docs/DESIGN.md](docs/DESIGN.md) — architecture and decision rationale
- [../README.md](README.md) — full project documentation
