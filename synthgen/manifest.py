"""Generation manifests for reproducibility."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def schema_hash(schema_path: Path) -> str:
    """SHA-256 over a schema file (or directory of .sql files)."""
    if schema_path.is_dir():
        blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in sorted(schema_path.rglob("*.sql")) if p.is_file())
    else:
        blob = schema_path.read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_manifest(generated_by: str, seed: int, tables: dict, **extra) -> dict:
    import importlib.metadata as md
    versions = {"pandas": pd.__version__, "faker": md.version("faker"),
                "python-synthgen": md.version("synthgen") if _installed("synthgen") else "dev"}
    meta = {"generated_by": generated_by, "synthetic": True,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "seed": seed, "versions": versions}
    meta.update(extra)
    return {"_meta": meta, "tables": {k: len(v) for k, v in tables.items()}}


def _installed(name: str) -> bool:
    try:
        import importlib.metadata as md
        md.version(name)
        return True
    except Exception:
        return False


def write_manifest(path: Path, manifest: dict) -> Path:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
