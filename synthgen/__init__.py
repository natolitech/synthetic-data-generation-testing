"""synthgen — synthetic data generation toolkit.

Single canonical implementation of the schema parser, semantic column
generators, validators, formatters, clinical notes/dictation generator, linked
clinical bundles, and FHIR R4 / HL7 v2.5.1 exporters.

CLI:
    python -m synthgen notes  -n 50 --validate
    python -m synthgen bundle -n 100 --zip
    python -m synthgen schema schema/ --rows 100 --manifest
    python -m synthgen validate <path>
"""

__version__ = "0.4.0"

from .clock import clock
from .formatters import to_csv, to_json, to_sql
from .generators import (GENERATOR_REGISTRY, generate_value, null_rate,
                         safe_email, safe_phone, safe_ssn)
from .schema import ColumnDef, TableDef, load_schema, parse_ddl
from .tables import generate_all, generate_table, reconcile_age
from .validators import validate

__all__ = [
    "__version__", "clock",
    "ColumnDef", "TableDef", "parse_ddl", "load_schema",
    "generate_value", "generate_table", "generate_all",
    "GENERATOR_REGISTRY", "null_rate", "reconcile_age",
    "safe_email", "safe_phone", "safe_ssn",
    "to_csv", "to_json", "to_sql", "validate",
]
