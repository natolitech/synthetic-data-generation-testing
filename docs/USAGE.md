# Usage Guide

Task-oriented recipes for the four jobs this toolkit does. New to the
vocabulary (PHI, MRN, FHIR, ground-truth spans)? Read [GLOSSARY.md](GLOSSARY.md)
first. For architecture and rationale, see [DESIGN.md](DESIGN.md).

All commands assume you're in the repo root. `./run.sh doctor` checks your
environment first. Every generated identifier is in a reserved/fictional range —
see the safety table in the [GLOSSARY](GLOSSARY.md#reserved-ranges--why-each-safe-value-is-safe).

---

## Recipe 1 — Seed a test database from your schema

*You have a real schema (DDL) and want realistic rows that respect foreign keys.*

```bash
# 1. What tables will be detected?
python -m synthgen schema schema/ --list-tables

# 2. Generate — FK dependency order handled automatically (parents before children)
python -m synthgen schema schema/ --rows 500 --validate --manifest -o ./seed_data/

# 3. Load it (SQL INSERT format also available)
python -m synthgen schema schema/ --rows 500 --format sql -o ./seed_data/
psql mydb < seed_data/synthetic_patients.sql
```

Notes:
- Columns are mapped by name — `first_name`, `email`, `ssn`, `dob`, `zip`,
  `note_text`, `dictation_text` etc. get semantic generators; everything else
  falls back to SQL-type-appropriate values. Full mapping table in the README.
- `--manifest` writes `manifest.json` (seed, schema SHA-256, versions) so the
  dataset is exactly reproducible.
- A table with both `dob` and `age` gets them reconciled automatically.

**Interactive version:** `./run.sh schema` → paste DDL or upload a `.sql` file →
**override any column's generator** from the dropdown (PK/FK locked) →
Generate → download single tables or the all-tables zip.

## Recipe 2 — Test a de-identification pipeline

*You built a PHI scrubber (regex, NER, LLM, vendor) and need to prove it works.*

```bash
# 1. Generate notes WITH ground-truth PHI spans
python -m synthgen notes -n 200 --validate --ground-truth -o ./eval/

# 2a. Score the built-in regex baseline (see what "decent" looks like)
python -m synthgen deid --baseline ./eval/synthetic_clinical_notes.csv --html ./eval/report.html

# 2b. Score YOUR scrubber — any Python callable str -> str
python -m synthgen deid --scrubber my_scrubber:redact_text ./eval/synthetic_clinical_notes.csv \
    --json ./eval/scores.json --sample-misses 5
```

Reading the scorecard:
- **Recall** — share of true PHI spans touched. Low recall = leaked PHI.
- **Precision (character-level)** — share of redacted characters that were
  actually PHI. A scrubber that nukes the whole document hits 100% recall with
  terrible precision.
- **Per-type table** — the baseline scores ~100% on structured identifiers
  (MRN/SSN/NPI/DOB/phone) and 0% on names. That gap is exactly what the harness
  exists to measure.
- `--sample-misses` prints the actual missed spans (`MISS [PATIENT] NOTE-000007:
  'Maria Garcia'`) for quick debugging.

Tougher evaluation material: `python -m synthgen bundle -n 50 --dirty --zip`
adds OCR damage, and `-t dictation_transcript` gives you raw ASR-style text.

## Recipe 3 — FHIR / HL7 interoperability fixtures

*You're building against a FHIR API or a hospital HL7 interface and need mock payloads.*

```bash
# FHIR R4: combined Bundle (all resource types, every reference resolves)
python -m synthgen bundle -n 100 --format fhir -o ./fixtures/
python -m synthgen fhir-check ./fixtures/synthetic_fhir_bundle.json   # verify it

# HL7 v2.5.1: ADT^A01 admit messages + ORU^R01 lab messages
python -m synthgen bundle -n 50 --format hl7 -o ./fixtures/
```

What you get:
- FHIR: `Patient`, `Practitioner`, `Encounter`, `Condition`, `MedicationRequest`,
  `Observation`, `DocumentReference` (note text as base64) — plus one bundle per
  resource type for targeted endpoint mocks.
- HL7: delimiter-escaped, spec-shaped messages with consistent patient identity
  across ADT and ORU.
- `synthgen fhir-check` catches missing required elements, invalid status enums,
  malformed ids/references, non-ISO dates, bad base64, and dangling references —
  with precise error paths. (Install `fhir.resources` to also run official-schema
  validation.)

## Recipe 4 — Linked clinical dataset for QA / demos

*You need a full EHR-shaped dataset where the joins actually join.*

```bash
python -m synthgen bundle -n 200 --zip --validate -o ./dataset/
```

Six linked tables — patients → encounters → diagnoses / medications / labs /
notes — with guarantees checked on every run: FK integrity, note identity and
principal diagnosis match their encounter, `DOB < admit < discharge`, med start
dates follow their diagnosis onset, diabetic labs biased high, behavioral notes
only for BH/SUD encounters. The zip includes `manifest.json` and the PHI
ground truth.

Variants:
- `--locale uk|ca|eu` — localized names/addresses/phones (Ofcom drama range,
  ZZ99 postcodes, unassigned Canadian Z-FSAs; non-US patients get NULL SSN)
- `--dirty` — duplicate rows, mixed date formats, casing drift, OCR-ish damage
  (applied after integrity verification, so you can test your cleanup pipelines
  against realistically messy-but-safe data)
- `--dictation-ratio 0.8` — mostly raw dictation transcripts
- `--no-notes` — tabular data only

**Interactive version:** `./run.sh demo` → Clinical/EHR → *Full Dataset —
linked* → pick locale + dirty mode in the sidebar → per-table previews,
integrity badge, zip + FHIR downloads.

---

## The Streamlit apps

| App | Command | Use when |
|-----|---------|----------|
| **demo_app** (`:8501`) | `./run.sh demo` | You want standard-domain data fast — 6 domains, 5–5,000 rows, per-table tabs, one-click downloads |
| **schema_app** (`:8502`) | `./run.sh schema` | You have your own DDL — paste/upload it, review & **override** the inferred generators, generate with FK integrity |

Both apps show four tabs per table: Preview (full note text for notes tables),
Raw Output (CSV/JSON/SQL), Validation (inline PII/PHI check), Statistics (NULL
distribution, column details). Docker alternative: `docker compose up`.

## Validation & exit codes

```bash
./run.sh validate synthetic_output/            # files or directories
python validate_synthetic.py data/ --html compliance.html   # + HTML artifact
```

| Exit code | Meaning | Action |
|-----------|---------|--------|
| 0 | All checks passed | Safe to use |
| 1 | Warnings | Review (e.g., unrecognized email domain, invalid NPI checksum, MRN outside synthetic range) |
| 2 | Critical | **Do not use** — real-range SSN, real email domain, potential real NPI |
| 3 | Usage/schema error | Fix the command or DDL |

## Reproducibility

Same seed + same code version = identical dataset (tests enforce this with a
frozen clock). Every CLI run writes a manifest recording the seed, row counts,
tool versions, and (for schema runs) a SHA-256 of your DDL. When you hand data
to someone, hand them the manifest too.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No Python interpreter with faker + pandas + streamlit found` | `pip install -r requirements.txt`, or `PYTHON=/path/to/venv/bin/python ./run.sh ...` |
| `Unknown command: deid` | You're on an old checkout — `./run.sh update` |
| CI fails on `check-sync` | Skill copies drifted; run `make sync-skill` and commit |
| `transcription_status` column got a full dictation | By design? No — check column name; `dictation|transcript` columns get raw dictation, plain `note_text` gets transcribed notes |
| Notes generation slow at 5,000 rows | Narrative construction is per-note; use `-n` batches or `--no-notes` + separate notes run |
| My scrubber scores 0 precision | It's likely returning completely rewritten text; precision is character-level — see [DESIGN.md](DESIGN.md#d5) |
