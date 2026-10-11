#!/usr/bin/env python3
"""
De-identification scoring harness
==================================
Scores any scrubber (a ``str -> str`` callable) against the ground-truth PHI
spans shipped with synthgen notes, turning this repo into a de-identification
benchmarking tool:

- **recall** — share of true PHI spans the scrubber touched (detected/removed)
- **precision** — share of the scrubber's edits that landed on true PHI
  (the rest is over-redaction collateral)
- per-PHI-type breakdown (PATIENT, MRN, DOB, SSN, PHONE, PROVIDER, ...)

Edits are derived by diffing original vs. scrubbed text (difflib), so the
harness works with ANY redaction technology — regex, NER, LLM, vendor product.

Usage:
    # score the built-in regex baseline
    python -m synthgen deid --baseline synthetic_output/synthetic_clinical_notes.csv

    # score your own scrubber: module.path:function
    python -m synthgen deid --scrubber myscrubber:redact synthetic_output/synthetic_clinical_notes.csv

    # JSON or HTML report
    python -m synthgen deid --baseline notes.csv --json scores.json --html report.html
"""

import difflib
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List

import pandas as pd


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def changed_regions(original: str, scrubbed: str) -> List[tuple]:
    """Regions of the ORIGINAL text that the scrubber modified.

    Returns (start, end) tuples in original coordinates; pure insertions are
    recorded as zero-width (pos, pos) anchors.
    """
    sm = difflib.SequenceMatcher(None, original, scrubbed, autojunk=False)
    return [(i1, i2) for tag, i1, i2, _j1, _j2 in sm.get_opcodes() if tag != "equal"]


def _overlaps(a: tuple, b: dict) -> bool:
    return a[0] < b["end"] and b["start"] < a[1]


@dataclass
class DeidScore:
    notes_scored: int = 0
    spans_total: int = 0
    spans_detected: int = 0
    edits_total: int = 0
    edits_on_phi: int = 0
    changed_chars: int = 0
    changed_chars_on_phi: int = 0
    per_type: Dict[str, dict] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return self.spans_detected / self.spans_total if self.spans_total else 1.0

    @property
    def precision(self) -> float:
        """Character-level precision: of all characters the scrubber touched,
        the fraction that actually belonged to true PHI. Blunt whole-document
        redactions score low even when recall is high."""
        if self.changed_chars == 0:
            return 1.0
        return self.changed_chars_on_phi / self.changed_chars

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def collateral_chars(self) -> int:
        return self.changed_chars - self.changed_chars_on_phi

    def as_dict(self) -> dict:
        return {
            "notes_scored": self.notes_scored,
            "spans": {"total": self.spans_total, "detected": self.spans_detected},
            "edits": {"total": self.edits_total, "on_phi": self.edits_on_phi,
                      "collateral_chars": self.collateral_chars},
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "f1": round(self.f1, 4),
            "per_type": {
                t: {"detected": v["detected"], "total": v["total"],
                    "recall": round(v["detected"] / v["total"], 4) if v["total"] else 1.0}
                for t, v in sorted(self.per_type.items())
            },
        }


def _overlap_len(a: tuple, b: dict) -> int:
    return max(0, min(a[1], b["end"]) - max(a[0], b["start"]))


def score_note(original: str, scrubbed: str, spans: List[dict]) -> dict:
    """Score one note. Returns {'detected': [...], 'missed': [...],
    'collateral': [(start, end), ...], 'regions': [...]} in original coords."""
    regions = changed_regions(original, scrubbed)
    detected, missed = [], []
    for s in spans:
        (detected if any(_overlaps(r, s) for r in regions) else missed).append(s)
    collateral = [r for r in regions if not any(_overlaps(r, s) for s in spans)]
    return {"detected": detected, "missed": missed, "collateral": collateral,
            "regions": regions}


def score_scrubber(notes: List[dict], scrubber: Callable[[str], str]) -> DeidScore:
    """Score a scrubber over notes: [{note_id?, text, phi_spans: [...]}]."""
    score = DeidScore()
    for note in notes:
        scrubbed = scrubber(note["text"])
        result = score_note(note["text"], scrubbed, note["phi_spans"])
        score.notes_scored += 1
        score.spans_total += len(note["phi_spans"])
        score.spans_detected += len(result["detected"])
        score.edits_total += len(result["regions"])
        score.edits_on_phi += len(result["regions"]) - len(result["collateral"])
        # character-level accounting: original-side chars touched, and how many
        # of those actually belonged to true PHI spans
        for r in result["regions"]:
            region_len = max(1, r[1] - r[0])
            on_phi = min(region_len, sum(_overlap_len(r, s) for s in note["phi_spans"]))
            score.changed_chars += region_len
            score.changed_chars_on_phi += on_phi
        for s in note["phi_spans"]:
            bucket = score.per_type.setdefault(s["type"], {"detected": 0, "total": 0})
            bucket["total"] += 1
            if s in result["detected"]:
                bucket["detected"] += 1
    return score


# ---------------------------------------------------------------------------
# Built-in baseline scrubber (regex redaction — the thing to beat)
# ---------------------------------------------------------------------------

_BASELINE_RULES = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("MRN", re.compile(r"\bMRN-\d{4,10}\b")),
    ("PHONE", re.compile(r"\b(?:\d{3}-\d{4}|\d{3} \d{3} \d{4}|\(\d{3}\) \d{3}-\d{4})\b")),
    ("NPI", re.compile(r"\b\d{10}\b")),
    ("DATE", re.compile(r"\b\d{2}/\d{2}/\d{4}\b")),
    ("ID", re.compile(r"\b(?:ENC|NOTE|SYN|PRV|ACC)-[0-9A-Za-z]{3,12}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
]


def regex_baseline(text: str) -> str:
    """Redact structured identifiers (SSN/MRN/phone/NPI/dates/IDs/emails).
    Deliberately does NOT attempt names or addresses — that gap is the point:
    it shows up as low recall for PATIENT/PROVIDER/ADDRESS in the score."""
    for label, pattern in _BASELINE_RULES:
        text = pattern.sub(f"[REDACTED-{label}]", text)
    return text


# ---------------------------------------------------------------------------
# Loading notes + scrubbers
# ---------------------------------------------------------------------------

def load_notes(path: Path) -> List[dict]:
    """Load notes from the bundle/notes CSV (note_id, note_text, phi_spans)."""
    df = pd.read_csv(path, comment="#")
    if not {"note_text", "phi_spans"} <= set(df.columns):
        raise SystemExit(f"{path}: expected note_text and phi_spans columns")
    return [
        {"note_id": row.get("note_id", str(i)), "text": row["note_text"],
         "phi_spans": json.loads(row["phi_spans"])}
        for i, row in df.to_dict(orient="index").items()
    ]


def load_scrubber(spec: str) -> Callable[[str], str]:
    """Load a scrubber from 'module.sub:callable'."""
    module_name, _, fn_name = spec.partition(":")
    if not fn_name:
        raise SystemExit(f"Scrubber spec must be 'module:function', got: {spec}")
    module = importlib.import_module(module_name)
    fn = getattr(module, fn_name)
    if not callable(fn):
        raise SystemExit(f"{spec} is not callable")
    return fn


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>De-identification Score Report</title>
<style>
 body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 2rem; color: #1a1a2e; }}
 h1 {{ border-bottom: 3px solid #4361ee; padding-bottom: .3rem; }}
 .metrics {{ display: flex; gap: 1.5rem; margin: 1.5rem 0; }}
 .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem 2rem; text-align: center; }}
 .card .value {{ font-size: 2rem; font-weight: 700; }}
 .good {{ color: #2a9d8f; }} .warn {{ color: #e9c46a; }} .bad {{ color: #e76f51; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
 th, td {{ border: 1px solid #ddd; padding: .5rem .8rem; text-align: left; }}
 th {{ background: #f0f2ff; }}
 footer {{ margin-top: 2rem; color: #777; font-size: .85rem; }}
</style></head><body>
<h1>De-identification Score Report</h1>
<p class="meta">{scrubber_desc} · {n} note(s) · {spans} ground-truth PHI span(s)</p>
<div class="metrics">
  <div class="card"><div class="value {r_cls}">{recall:.1%}</div>Recall</div>
  <div class="card"><div class="value {p_cls}">{precision:.1%}</div>Precision</div>
  <div class="card"><div class="value {f_cls}">{f1:.1%}</div>F1</div>
  <div class="card"><div class="value">{collateral:,}</div>Collateral chars</div>
</div>
<h2>Recall by PHI type</h2>
<table><tr><th>PHI type</th><th>Detected</th><th>Total</th><th>Recall</th></tr>
{rows}
</table>
<footer>Generated by synthgen deid · all data synthetic · {timestamp}</footer>
</body></html>"""


def html_report(score: DeidScore, scrubber_desc: str) -> str:
    from datetime import datetime
    rows = "".join(
        f'<tr><td>{t}</td><td>{v["detected"]}</td><td>{v["total"]}</td>'
        f'<td class="{_cls(v["detected"], v["total"])}">{v["detected"]/v["total"]:.1%}</td></tr>'
        if v["total"] else ""
        for t, v in sorted(score.per_type.items()))
    return _HTML_TEMPLATE.format(
        scrubber_desc=scrubber_desc, n=score.notes_scored, spans=score.spans_total,
        recall=score.recall, precision=score.precision, f1=score.f1,
        r_cls=_cls_ratio(score.recall), p_cls=_cls_ratio(score.precision),
        f_cls=_cls_ratio(score.f1),
        collateral=score.collateral_chars, rows=rows,
        timestamp=datetime.now().isoformat(timespec="seconds"))


def _cls(detected: int, total: int) -> str:
    return _cls_ratio(detected / total if total else 1.0)


def _cls_ratio(r: float) -> str:
    return "good" if r >= 0.9 else ("warn" if r >= 0.7 else "bad")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Score a de-identification scrubber against ground-truth PHI spans.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    scrub = parser.add_mutually_exclusive_group(required=True)
    scrub.add_argument("--scrubber", metavar="MODULE:FUNCTION",
                       help="your scrubber, e.g. mypkg:redact_text")
    scrub.add_argument("--baseline", action="store_true",
                       help="use the built-in regex baseline scrubber")
    parser.add_argument("notes", help="notes CSV with note_text + phi_spans columns")
    parser.add_argument("--json", metavar="PATH", help="write JSON scores")
    parser.add_argument("--html", metavar="PATH", help="write HTML report")
    parser.add_argument("--sample-misses", type=int, default=0,
                        help="print N missed spans per report for eyeballing")
    args = parser.parse_args(argv)

    notes = load_notes(Path(args.notes))
    scrubber = regex_baseline if args.baseline else load_scrubber(args.scrubber)
    desc = "built-in regex baseline" if args.baseline else f"scrubber: {args.scrubber}"

    score = score_scrubber(notes, scrubber)
    d = score.as_dict()

    print(f"\nDe-identification score — {desc}")
    print(f"  notes: {d['notes_scored']}   spans: {d['spans']['total']}"
          f"   edits: {d['edits']['total']} (collateral chars: {d['edits']['collateral_chars']:,})")
    print(f"  RECALL {d['recall']:.1%}   PRECISION {d['precision']:.1%}   F1 {d['f1']:.1%}\n")
    print(f"  {'PHI type':<12} {'detected':>8} {'total':>6} {'recall':>8}")
    for t, v in d["per_type"].items():
        print(f"  {t:<12} {v['detected']:>8} {v['total']:>6} {v['recall']:>8.1%}")

    if args.sample_misses:
        print()
        for note in notes[: max(1, args.sample_misses)]:
            scrubbed = scrubber(note["text"])
            r = score_note(note["text"], scrubbed, note["phi_spans"])
            for s in r["missed"][:3]:
                print(f"  MISS [{s['type']}] {note['note_id']}: {s['text']!r}")

    if args.json:
        Path(args.json).write_text(json.dumps(d, indent=2), encoding="utf-8")
        print(f"\nWrote JSON → {args.json}")
    if args.html:
        Path(args.html).write_text(html_report(score, desc), encoding="utf-8")
        print(f"Wrote HTML → {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
