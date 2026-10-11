"""SQL DDL schema parsing (PostgreSQL, MySQL, SQLite, SQL Server)."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

@dataclass
class ColumnDef:
    name: str
    sql_type: str
    base_type: str
    nullable: bool = True
    is_pk: bool = False
    fk_table: Optional[str] = None
    fk_col: Optional[str] = None


@dataclass
class TableDef:
    name: str
    source_file: str = ""
    columns: List[ColumnDef] = field(default_factory=list)


def _split_top_level(text: str) -> List[str]:
    depth, parts, current = 0, [], []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p.strip()]


def _parse_column_token(token: str) -> Optional[ColumnDef]:
    token = token.strip()
    if not token:
        return None
    upper = token.upper().lstrip()
    if re.match(r"^(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|INDEX|KEY\b|CONSTRAINT|CHECK\s*\(|FULLTEXT|SPATIAL)", upper):
        return None

    name_match = re.match(r'^[`"\[]?([\w]+)[`"\]]?\s+', token)
    if not name_match:
        return None
    name = name_match.group(1)
    rest = token[name_match.end():]

    type_match = re.match(r"([\w]+(?:\s*\([^)]*\))?(?:\s+(?:UNSIGNED|ZEROFILL))*)", rest, re.IGNORECASE)
    if not type_match:
        return None
    sql_type = type_match.group(1).strip()
    base_type = sql_type.split("(")[0].strip().lower()
    rest_upper = rest[type_match.end():].upper()

    is_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", rest_upper))
    nullable = "NOT NULL" not in rest_upper
    if is_pk:
        nullable = False

    fk_table = fk_col = None
    fk_match = re.search(r"REFERENCES\s+[`\"]?([\w]+)[`\"]?\s*\(\s*[`\"]?([\w]+)[`\"]?\s*\)", token, re.IGNORECASE)
    if fk_match:
        fk_table, fk_col = fk_match.group(1), fk_match.group(2)

    return ColumnDef(name=name, sql_type=sql_type, base_type=base_type,
                     nullable=nullable, is_pk=is_pk, fk_table=fk_table, fk_col=fk_col)


def parse_ddl(text: str, source_file: str = "") -> List[TableDef]:
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    tables = []
    create_re = re.compile(
        r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:[`\"\[]?[\w]+[`\"\]]?\s*\.\s*)?[`\"\[]?([\w]+)[`\"\]]?\s*\(",
        re.IGNORECASE,
    )
    for m in create_re.finditer(text):
        table_name = m.group(1)
        start, depth, i = m.end(), 1, m.end()
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        body = text[start:i - 1]

        columns, pk_cols = [], set()
        for token in _split_top_level(body):
            stripped_upper = token.strip().upper()
            pk_match = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", stripped_upper)
            if pk_match:
                for c in pk_match.group(1).split(","):
                    pk_cols.add(re.sub(r"[`\"\[\]]", "", c.strip()).lower())
                continue
            col = _parse_column_token(token)
            if col:
                columns.append(col)

        for col in columns:
            if col.name.lower() in pk_cols:
                col.is_pk = True
                col.nullable = False

        if columns:
            tables.append(TableDef(name=table_name, source_file=source_file, columns=columns))

    return tables


def load_schema(path: Path) -> List[TableDef]:
    """Load schema from a file or every .sql/.ddl file in a directory."""
    if path.is_file():
        return parse_ddl(path.read_text(encoding="utf-8", errors="replace"), source_file=path.name)

    tables = []
    for ext in ("*.sql", "*.ddl"):
        for f in sorted(path.glob(ext)):
            tables.extend(parse_ddl(f.read_text(encoding="utf-8", errors="replace"), source_file=f.name))
    return tables
