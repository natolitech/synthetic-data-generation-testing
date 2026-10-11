# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (runtime) + dev tools
pip install -r requirements.txt
pip install -e ".[dev]"          # pytest + ruff, plus the `synthgen` console script

# Preferred: use the run.sh entry point for everything
./run.sh demo                          # domain-based Streamlit app (:8501)
./run.sh schema                        # schema-driven Streamlit app (:8502)
./run.sh notes -n 50 --validate        # clinical notes / dictations CLI
./run.sh bundle -n 100 --zip --validate  # linked clinical dataset (6 tables)
./run.sh gen schema/ --rows 100 --manifest
./run.sh validate synthetic_output/
./run.sh doctor                        # environment check

# Unified package CLI (same subcommands)
python -m synthgen notes -n 50 --validate
python -m synthgen bundle -n 100 --format fhir
python -m synthgen schema schema/ --rows 100 --manifest

# Legacy entry points still work (thin shims over synthgen)
python clinical_notes.py -n 50 --validate --ground-truth
python clinical_bundle.py -n 100 --zip
python synth-data-gen/scripts/generate_from_schema.py schema/ --list-tables

# Development
make test        # pytest (76 tests: parser, generators, notes, bundle, interop, invariants)
make lint        # ruff over package + apps + tests
make sync-skill  # regenerate synth-data-gen/scripts from canonical sources
make check-sync  # drift gate used by CI
make ci          # lint + test + check-sync

# Docker (zero local Python)
docker compose up   # demo on :8501, schema app on :8502
```

## Architecture

**Canonical implementation: the `synthgen/` package.** Everything else is either a UI, a shim, or a *generated* copy.

| Module | Contents |
|--------|----------|
| `synthgen/schema.py` | DDL parser: `ColumnDef`, `TableDef`, `parse_ddl`, `load_schema` (PostgreSQL/MySQL/SQLite/SQL Server) |
| `synthgen/generators.py` | Semantic column mapping (`generate_value`), safe-range constants + helpers, `GENERATOR_REGISTRY` (~30 named generators for UI/CLI overrides), `null_rate`, `reconcile_age`, `describe_generator` |
| `synthgen/tables.py` | `generate_table` (single table, with overrides) and `generate_all` (FK dependency order), edge-case name injection |
| `synthgen/formatters.py` | CSV / JSON (with `_meta.synthetic` marker) / SQL INSERT serializers |
| `synthgen/validators.py` | Inline PII/PHI `validate()` — SSN/email/phone ranges; reserved-TLD + subdomain-aware safe-email logic |
| `synthgen/notes.py` | 10 clinical note types (progress, H&P, discharge, ED, telehealth, procedure, radiology, behavioral-health w/ 42 CFR Part 2, portal message, call transcript), transcribed or raw-dictation rendering, **ground-truth PHI spans**; `make_context()`/`build_note()` composition API |
| `synthgen/bundle.py` | Referentially-linked cohort (patients→encounters→diagnoses→medications→labs→notes), `check_integrity()`, condition-biased labs, locale packs (us/uk/ca/eu), `apply_dirty_mode()`, CLI |
| `synthgen/fhir.py` | FHIR R4 serializers (Patient/Practitioner/Encounter/Condition/MedicationRequest/Observation/DocumentReference); combined bundle has zero dangling references |
| `synthgen/hl7.py` | HL7 v2.5.1 ADT^A01 + ORU^R01 builders, delimiter-escaped |
| `synthgen/schema_cli.py` | `python -m synthgen schema` CLI |
| `synthgen/manifest.py` | Reproducibility manifests (seed, schema SHA-256, versions) |
| `synthgen/clock.py` | Injectable `clock.now()/today()` — tests freeze it for byte-determinism |

**UIs (root):**
- `demo_app.py` — six built-in domains + "Full Dataset — linked" mode (integrity badge, zip + FHIR downloads, locale/dirty toggles). Domain generators live inline; helpers/validators/formatters come from `synthgen`.
- `schema_app.py` — Streamlit layer ONLY (~300 lines): editable generator grid (`GENERATOR_REGISTRY`, PK/FK locked), multi-table zip download. All generation logic imported from `synthgen`.

**Compat shims (root):** `clinical_notes.py`, `clinical_bundle.py`, `fhir_export.py`, `hl7_export.py` re-export the package so historical entry points keep working. `validate_synthetic.py` and `example_patient_generator.py` remain intentionally standalone.

**Skill (`synth-data-gen/`) is GENERATED — never edit by hand.** `scripts/sync_skill.py` copies the package into `synth-data-gen/scripts/synthgen/`, writes CLI shims, and copies the standalone validators verbatim (plus removing stale files). CI runs `make check-sync`; any edit under `synth-data-gen/scripts/` made directly will fail the drift gate. `SKILL.md` and `references/` are hand-maintained.

**Tests (`tests/`)** — key invariant suite: `test_validator_invariant.py` proves *the validator never flags generator output* across every generator, format, locale, and dirty mode. Determinism tests freeze `synthgen.clock` and require identical output for identical seeds. `check_integrity` is exercised across multiple seeds.

## Semantic Column Mapping

`synthgen.generators.generate_value(col, fake, fk_pool, row_idx, override=None)` maps column names via `re.search`, first match wins. Priority: manual override → UUID → PK (sequential/prefixed: SYN/EMP/USR/CLM/ENC/NOTE) → FK pool → note metadata & narrative (`note_type`, `transcription_status`, `author`, `dictation|transcript` → raw dictation, `note_text|progress_note|hpi|chief_complaint|narrative` → transcribed note) → names/contact/identity/location/demographics/dates/financial/clinical/IAM pools → SQL type fallbacks. Narrative text is truncated to `VARCHAR(n)`.

When adding semantic rules: edit `synthgen/generators.py` ONCE, then `make sync-skill`.

## Safety Invariants

Every generated identifier stays in reserved/fictional ranges:

| Field | Safe Range |
|-------|-----------|
| SSN | `987-65-xxxx` |
| Email | `@example.com`, `@example.org`, `@test.invalid` + reserved TLDs/subdomains |
| Phone | `555-01xx` (US/CA), UK Ofcom `01632 960xxx`, EU synthetic `+49 30 5550-xxx` |
| IP | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` (RFC 5737) |
| Non-US national IDs | NULL (no universally safe range) |

`tests/test_validator_invariant.py` enforces this on every push; never weaken it.

## Adding a New Domain, Note Type, or Format

1. Implement in the `synthgen/` package (generators / notes / fhir / hl7 as appropriate).
2. Add tests under `tests/` — extend the invariant suite if new output can contain identifiers.
3. Run `make lint test sync-skill`.
4. Update UIs only if surfacing is needed (`demo_app.py` DOMAIN_TABLES, `schema_app.py` registry).
5. Update `synth-data-gen/references/data-domains.md` (root `data-domains.md` mirrors it) and README.
