# Design Document

Architecture, safety model, and the reasoning behind every major decision in
this toolkit. For how-to-use material see [USAGE.md](USAGE.md); for terminology
see [GLOSSARY.md](GLOSSARY.md).

---

## Goals & non-goals

**Goals**
1. Realistic synthetic PII/PHI for dev/test/QA/demo environments — realistic
   enough to exercise *de-identification, transcription, interoperability, and
   data-pipeline* code, not just to fill tables.
2. **Provably safe**: every identifier lives in a reserved/fictional range; a
   validator can certify each output file; CI enforces that the validator never
   flags our own generators.
3. Reproducible: same seed + same version ⇒ byte-identical datasets.
4. Usable at three altitudes: Streamlit UI, one-line CLI, importable Python API.

**Non-goals**
- Statistically faithful clones of a specific production dataset (no model
  fitting). We model *plausibility* (census-weighted demographics, clinically
  correlated dx/meds/labs), not your hospital's actual distributions.
- Anonymization/pseudonymization of real data. This project *generates* fiction;
   it never transforms production data.
- Full FHIR schema validation out of the box (optional via `fhir.resources`).

## Layered architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Interfaces                                                     │
│   run.sh · python -m synthgen · Streamlit apps · Docker         │
├────────────────────────────────────────────────────────────────┤
│  synthgen package  (THE canonical implementation)               │
│   schema.py   parse DDL → ColumnDef/TableDef                    │
│   generators.py   name→generator mapping + registry + safety    │
│   tables.py   single-table + FK-ordered multi-table generation  │
│   notes.py   10 narrative types · PHI segment builder           │
│   bundle.py   linked cohort · locales · dirty mode · integrity  │
│   fhir.py / hl7.py   interoperability serializers               │
│   validators.py / deid.py / fhir_validate.py   assurance layer  │
│   clock.py   injectable time (determinism)                      │
├────────────────────────────────────────────────────────────────┤
│  Generated consumers                                            │
│   synth-data-gen/scripts/  ← make sync-skill (drift-gated)      │
│   root shims (clinical_notes.py, …)  ← thin re-exports          │
└────────────────────────────────────────────────────────────────┘
```

## Decision log

### D1 — One canonical package; skill copies are generated
**Decision:** all logic lives in `synthgen/`; the Claude Code skill's scripts
are *generated* by `scripts/sync_skill.py` (shims + a package copy), and CI
fails on drift (`make check-sync`).
**Why:** the skill must run standalone (no repo import path), which previously
meant 2–3 hand-synced copies of the parser/generators/validators. Those copies
had already accumulated latent bugs (missing `uuid`/`json` imports — found by
ruff the day the package was extracted). Generation + a drift gate makes
divergence structurally impossible instead of conventionally forbidden.
**Trade-off:** skill payload is bigger (ships the package). Accepted.

### D2 — Safety by construction, not by scrubbing
**Decision:** identifiers are *born* in reserved ranges (see the
[ranges table](GLOSSARY.md#reserved-ranges--why-each-safe-value-is-safe));
nothing is redacted after the fact.
**Why:** post-hoc scrubbing can miss; reserved ranges can't collide. The
validator becomes a *verifier* of an invariant, not a best-effort filter.

### D3 — Checksum-valid NPIs in a safe prefix
**Decision:** generated NPIs pass the CMS Luhn check (prefix `80840`) but start
with `9`; the validator flags valid-checksum NPIs starting with `1` as critical.
**Why:** an NPI that fails its check digit can't exercise downstream NPI
validation logic; a *valid* one starting with `1` might be real. `9`-prefix +
valid checksum is simultaneously structurally plausible and un-issued.
**Trade-off:** `9`-prefix NPIs are less "realistic-looking" than `1`-prefix;
safety wins.

### D4 — Ground-truth PHI spans from construction
**Decision:** notes are assembled from labeled segments (`NoteBuilder`), so each
note ships with exact `{type, text, start, end}` offsets for every PHI instance.
**Why:** real de-id evaluation requires annotations, which are expensive to
produce and error-prone to hand-label. Building text *from* labels makes
annotations free and exact. This single decision turned the project from a data
generator into a **de-identification benchmark**.

### D5 — Character-level precision in the de-id harness
**Decision:** precision = (characters redacted that were true PHI) / (all
characters redacted), not region- or finding-level.
**Why:** a test initially used region-level precision and scored a
whole-document nuke as 1.0 because its single merged edit region overlapped one
span. Character weighting makes over-redaction *visible* — the clinically
relevant failure mode where "safe" output destroys meaning.
**Trade-off:** diff-derived regions attribute small boundary chars (e.g., a
space between two adjacent spans) to the scrubber; documented, negligible.

### D6 — Dirty mode runs strictly after integrity verification
**Decision:** `--dirty` is a post-pass; `check_integrity()` always certifies the
*clean* cohort first, and the manifest records `dirty_mode: true`.
**Why:** dirty data must degrade formats (dates, casing, duplicates), never
referential safety — otherwise users can't tell whether a broken join is their
pipeline's problem or ours.

### D7 — Injectable clock (`synthgen.clock`)
**Decision:** generation code reads `clock.now()/today()`, never `datetime.now()`
directly; tests freeze the clock.
**Why:** seeded RNG determinism is worthless if wall-clock time leaks into
output. Freezing time in tests proves same-seed runs are byte-identical.

### D8 — The invariant suite is the release gate
**Decision:** `test_validator_invariant.py` asserts the validator produces zero
criticals/warnings across every generator, format, locale, and dirty mode.
**Why:** it converts the project's core promise ("validator never flags
generator output") from documentation into a machine-checked contract. Any new
generator/range must extend it or fail CI.

### D9 — Locale packs use each region's *official* fiction ranges
**Decision:** UK → Ofcom drama numbers `01632 960xxx` + `ZZ99` postcodes;
Canada → NANP phones + unassigned `Z`-prefix FSAs; EU → a documented synthetic
`+49` pattern; non-US patients get **NULL** national IDs.
**Why:** there is no universally reserved SSN-equivalent outside the US;
inventing one would violate D2. NULLs are both realistic (foreign patients) and
safe.

### D10 — Email safety includes reserved TLDs and subdomains
**Decision:** `clinic.example.com`, `anything.test`, `x.invalid` are all safe;
the check is suffix-aware.
**Why:** strict domain equality flagged our own portal-message `To:` line as a
warning — a false positive that would have broken D8.

### D11 — Dictation is a rendering mode, not a note type
**Decision:** `dictation_transcript` is a pseudo-type; every narrative type
(except portal messages and call transcripts — `NON_DICTATABLE`) can be rendered
either transcribed or as raw ASR-style dictation via `--dictation-ratio`.
**Why:** modeling dictation as an orthogonal rendering doubles coverage (any
note × 2 forms) without duplicating templates.

### D12 — Correlation over independence
**Decision:** diagnoses drive medications (with temporal ordering), lab value
bias, note narrative, and radiology findings; behavioral-health notes are gated
to BH/SUD encounters; `check_integrity()` verifies all of it.
**Why:** independent random columns are fine for volume testing but useless for
testing clinical logic. Correlation is what makes the data *exercise* code.
The trade-off (hard-coded condition model in `CONDITIONS`) is deliberate: it
keeps guarantees checkable.

## Safety model summary

1. **Construction** (D2/D3/D9/D10): ranges chosen at generation time.
2. **Verification**: `validate()` (inline, every CLI `--validate` run) and
   `validate_synthetic.py` (standalone, file/directory, HTML artifact, exit
   codes 0/1/2) — SSN areas, email domains/TLDs, phone ranges, IPs, NPI
   checksums + prefixes, MRN range, NULL distribution, JSON markers.
3. **Continuous enforcement** (D8): CI proves generators and validators agree,
   on three Python versions, on every push.

## Testing philosophy

Four tiers, all in `tests/`:
- **Unit** — parser dialects, semantic mapping, span-offset exactness
  (`text[start:end] == span.text`), NPI math, FHIR/HL7 structure.
- **Property** — integrity across seeds; med↔dx correlation; lab bias;
  locale behavior; dirty-mode invariants.
- **Determinism** — frozen clock + seed ⇒ identical DataFrames.
- **Contract** (D8) — the invariant suite.

Negative testing is mandatory for validators and checkers: each must catch
crafted violations (tampered checksums, dangling references, missing required
elements), or the test fails.

## Extending

Short version (full version in CLAUDE.md): implement in `synthgen/`, add tests
(extending the invariant suite for anything emitting identifiers), run
`make lint test sync-skill`, update `references/data-domains.md` and the docs
in this folder. Never edit `synth-data-gen/scripts/` by hand.
