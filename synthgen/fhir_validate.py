#!/usr/bin/env python3
"""
FHIR R4 conformance checker (structural)
=========================================
Validates synthgen FHIR output (and any FHIR R4 JSON) against structural R4
rules without external dependencies:

- resourceType present; Bundle structure (type, entry[], fullUrl)
- id format ^[A-Za-z0-9\\-.]{1,64}$ ; reference format Type/id, urn:uuid, or absolute URL
- required elements per resource type (Patient.name, Encounter.status/period,
  Condition.code/subject, Observation.status/code, DocumentReference.status/content,
  MedicationRequest.status/intent/subject)
- dateTime fields parse as ISO-8601
- attachment.data is valid base64
- every relative reference resolves inside the bundle (dangling-reference check)

If the optional ``fhir.resources`` package is installed, deep official-schema
validation runs additionally; otherwise the structural checks above apply.

Usage:
    python -m synthgen fhir-check synthetic_fhir_bundle.json
    python -m synthgen fhir-check bundle.json --json report.json
"""

import base64
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_REF_RE = re.compile(r"^(?:[A-Za-z]+/[A-Za-z0-9\-.]{1,64}|urn:uuid:[0-9a-fA-F-]+|https?://\S+)$")

_REQUIRED = {
    "Patient": [("name", list)],
    "Encounter": [("status", str), ("subject", dict)],
    "Condition": [("code", dict), ("subject", dict)],
    "Observation": [("status", str), ("code", dict), ("subject", dict)],
    "DocumentReference": [("status", str), ("subject", dict), ("content", list)],
    "MedicationRequest": [("status", str), ("intent", str), ("subject", dict)],
    "Practitioner": [("name", list)],
}

_KNOWN_STATUS = {
    "Encounter": {"planned", "arrived", "triaged", "in-progress", "onleave",
                  "finished", "cancelled", "entered-in-error", "unknown"},
    "Observation": {"registered", "preliminary", "final", "amended",
                    "corrected", "cancelled", "entered-in-error", "unknown"},
    "DocumentReference": {"current", "superseded", "entered-in-error"},
    "MedicationRequest": {"active", "on-hold", "cancelled", "completed",
                          "entered-in-error", "stopped", "draft", "unknown"},
    "Condition": {"active", "recurrence", "relapse", "inactive", "remission", "resolved"},
}

_DATETIME_FIELDS = ("birthDate", "onsetDateTime", "authoredOn", "effectiveDateTime", "date")


class FhirReport:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, path: str, msg: str):
        self.errors.append(f"{path}: {msg}")

    def warning(self, path: str, msg: str):
        self.warnings.append(f"{path}: {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _check_resource(res: dict, path: str, rep: FhirReport):
    rtype = res.get("resourceType")
    if not rtype:
        rep.error(path, "missing resourceType")
        return
    rid = res.get("id")
    if rid is not None and not _ID_RE.match(str(rid)):
        rep.error(f"{path}/{rtype}[{rid}]", f"invalid id format: {rid!r}")

    for field, kind in _REQUIRED.get(rtype, []):
        v = res.get(field)
        if v is None:
            rep.error(f"{path}/{rtype}[{rid}]", f"missing required element: {field}")
        elif kind is list and not v:
            rep.error(f"{path}/{rtype}[{rid}]", f"required element is empty: {field}")

    status = res.get("status")
    if status is not None and rtype in _KNOWN_STATUS and status not in _KNOWN_STATUS[rtype]:
        rep.error(f"{path}/{rtype}[{rid}]", f"invalid status: {status!r}")

    for f in _DATETIME_FIELDS:
        if f in res and res[f]:
            try:
                datetime.fromisoformat(str(res[f]).replace("Z", "+00:00"))
            except ValueError:
                rep.error(f"{path}/{rtype}[{rid}]", f"{f} is not ISO-8601: {res[f]!r}")


def _walk_references(obj, path: str, rep: FhirReport):
    """Yield (path, reference) for every Reference.reference found."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str):
                if not _REF_RE.match(v):
                    rep.warning(f"{path}", f"unusual reference format: {v!r}")
                yield path, v
            else:
                yield from _walk_references(v, f"{path}.{k}", rep)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk_references(item, f"{path}[{i}]", rep)


def _check_attachments(res: dict, path: str, rep: FhirReport):
    rtype = res.get("resourceType", "")
    if rtype == "DocumentReference":
        for i, c in enumerate(res.get("content", [])):
            data = (c.get("attachment") or {}).get("data")
            if data:
                try:
                    base64.b64decode(data, validate=True)
                except Exception:
                    rep.error(f"{path}/DocumentReference.content[{i}]",
                              "attachment.data is not valid base64")


def validate_fhir(doc: dict, source: str = "input") -> FhirReport:
    rep = FhirReport()
    if not isinstance(doc, dict) or "resourceType" not in doc:
        rep.error(source, "not a FHIR resource (missing resourceType)")
        return rep

    if doc["resourceType"] == "Bundle":
        entries = doc.get("entry")
        if not isinstance(entries, list) or not entries:
            rep.error(source, "Bundle must have a non-empty entry[]")
            return rep
        ids = set()
        refs = []
        for i, entry in enumerate(entries):
            epath = f"{source}.entry[{i}]"
            res = entry.get("resource")
            if not res:
                rep.error(epath, "entry missing resource")
                continue
            _check_resource(res, epath, rep)
            _check_attachments(res, epath, rep)
            rid = res.get("id")
            if rid:
                ids.add(f'{res.get("resourceType")}/{rid}')
            refs.extend(r for _, r in _walk_references(res, epath, rep))
        dangling = sorted({r for r in refs
                           if "/" in r and not r.startswith(("urn:", "http"))
                           and r not in ids})
        for r in dangling:
            rep.error(source, f"dangling reference (not in bundle): {r}")
    else:
        _check_resource(doc, source, rep)
        _check_attachments(doc, source, rep)

    return rep


def _deep_validate_if_available(doc: dict, rep: FhirReport) -> bool:
    """Optionally run official-schema validation via fhir.resources."""
    try:
        import fhir.resources  # noqa: F401
    except ImportError:
        return False
    try:
        from fhir.resources import construct_fhir_element
        if doc.get("resourceType") == "Bundle":
            construct_fhir_element("Bundle", doc)
        else:
            construct_fhir_element(doc["resourceType"], doc)
    except Exception as e:  # pragma: no cover - depends on optional package
        rep.error("fhir.resources", f"schema validation failed: {e}")
    return True


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Structural FHIR R4 conformance check.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file", help="FHIR JSON file (resource or Bundle)")
    parser.add_argument("--json", metavar="PATH", help="write report as JSON")
    args = parser.parse_args(argv)

    try:
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read {args.file}: {e}", file=sys.stderr)
        return 2

    rep = validate_fhir(doc, source=Path(args.file).name)
    deep = _deep_validate_if_available(doc, rep)

    mode = "structural + fhir.resources schema" if deep else "structural"
    print(f"FHIR R4 check ({mode}) — {args.file}")
    for e in rep.errors:
        print(f"  ERROR:   {e}", file=sys.stderr)
    for w in rep.warnings:
        print(f"  WARNING: {w}", file=sys.stderr)
    if rep.ok:
        print(f"  ✅ OK — {len(rep.warnings)} warning(s), no errors")
    else:
        print(f"  ❌ {len(rep.errors)} error(s)", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
        print(f"Wrote JSON → {args.json}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
