"""Schema parser tests: dialects, constraints, comments."""

from synthgen.schema import load_schema, parse_ddl


def test_basic_postgres():
    tables = parse_ddl("""
        CREATE TABLE patients (
            patient_id VARCHAR(20) PRIMARY KEY,
            first_name VARCHAR(100) NOT NULL,
            dob DATE,
            created_at TIMESTAMP
        );
    """)
    assert len(tables) == 1
    t = tables[0]
    assert t.name == "patients"
    assert [c.name for c in t.columns] == ["patient_id", "first_name", "dob", "created_at"]
    pk = t.columns[0]
    assert pk.is_pk and not pk.nullable
    assert t.columns[1].nullable is False
    assert t.columns[2].nullable is True


def test_table_level_primary_key():
    tables = parse_ddl("""
        CREATE TABLE orders (
            id INT,
            sku VARCHAR(20),
            PRIMARY KEY (id)
        );
    """)
    assert tables[0].columns[0].is_pk


def test_inline_fk():
    tables = parse_ddl("""
        CREATE TABLE encounters (
            encounter_id VARCHAR(20) PRIMARY KEY,
            patient_id VARCHAR(20) REFERENCES patients(patient_id)
        );
    """)
    col = tables[0].columns[1]
    assert col.fk_table == "patients"
    assert col.fk_col == "patient_id"


def test_quoted_identifiers_mysql():
    tables = parse_ddl("""
        CREATE TABLE `patient_demo` (
            `first_name` VARCHAR(50),
            `age` INT
        );
    """)
    assert tables[0].name == "patient_demo"
    assert tables[0].columns[0].name == "first_name"


def test_comments_and_multiple_tables():
    ddl = """
    -- leading comment
    CREATE TABLE a (x INT); /* block
    comment */ CREATE TABLE b (y INT);
    """
    tables = parse_ddl(ddl)
    assert [t.name for t in tables] == ["a", "b"]


def test_if_not_exists_and_schema_qualified():
    tables = parse_ddl("CREATE TABLE IF NOT EXISTS public.users (id INT PRIMARY KEY);")
    assert tables[0].name == "users"


def test_load_schema_directory(tmp_path):
    (tmp_path / "one.sql").write_text("CREATE TABLE a (x INT);")
    (tmp_path / "two.sql").write_text("CREATE TABLE b (y INT);")
    (tmp_path / "ignore.txt").write_text("not sql")
    tables = load_schema(tmp_path)
    assert {t.name for t in tables} == {"a", "b"}


def test_nested_parens_not_split_as_columns():
    tables = parse_ddl("""
        CREATE TABLE t (
            amount DECIMAL(10, 2),
            note VARCHAR(50)
        );
    """)
    assert len(tables[0].columns) == 2
    assert tables[0].columns[0].sql_type == "DECIMAL(10, 2)"
