#!/usr/bin/env python3
"""
Schema-Driven Synthetic Data Generator (Streamlit UI)
======================================================
Paste or upload a SQL DDL schema and generate realistic synthetic data.
All data is entirely fictional — zero real PII/PHI.

Canonical generation logic lives in the ``synthgen`` package; this file is the
interactive layer only.

Run:
    streamlit run schema_app.py
"""

import io
import json
import random
import zipfile
from datetime import datetime
from typing import List

import pandas as pd
import streamlit as st
from faker import Faker

from synthgen.generators import (AUTO, GENERATOR_REGISTRY,  # noqa: F401
                                 describe_generator as _describe_generator)
from synthgen.schema import ColumnDef, TableDef, parse_ddl  # noqa: F401
from synthgen.tables import generate_all as generate_all_tables
from synthgen.tables import generate_table as generate_from_table
from synthgen.validators import validate as validate_text
from synthgen.formatters import to_csv as to_csv_string
from synthgen.formatters import to_json as to_json_string
from synthgen.formatters import to_sql as to_sql_string

EXAMPLE_DDL = """\
CREATE TABLE patients (
    patient_id    VARCHAR(20)  PRIMARY KEY,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    dob           DATE,
    gender        VARCHAR(20),
    ssn           CHAR(11),
    email         VARCHAR(255),
    phone         VARCHAR(20),
    address       VARCHAR(255),
    city          VARCHAR(100),
    state         CHAR(2),
    zip           CHAR(10),
    mrn           VARCHAR(20),
    created_at    TIMESTAMP,
    deceased_flag BOOLEAN
);

CREATE TABLE encounters (
    encounter_id       VARCHAR(20) PRIMARY KEY,
    patient_id         VARCHAR(20) REFERENCES patients(patient_id),
    encounter_type     VARCHAR(50) NOT NULL,
    admit_datetime     TIMESTAMP   NOT NULL,
    discharge_datetime TIMESTAMP,
    department         VARCHAR(100),
    attending_npi      VARCHAR(10)
);"""


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def _render_results(tbl_name: str, df: pd.DataFrame, output_format: str, seed: int) -> None:
    tab_preview, tab_raw, tab_validate, tab_stats = st.tabs(["Preview", "Raw Output", "Validation", "Statistics"])

    with tab_preview:
        st.dataframe(df, use_container_width=True, height=350)

    with tab_raw:
        if output_format == "Table Preview":
            st.info("Select CSV, JSON, or SQL INSERT from the sidebar to get downloadable output.")
            st.dataframe(df, use_container_width=True, height=350)
        elif output_format == "CSV":
            raw = to_csv_string(df)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="csv")
            st.download_button("Download CSV", raw, file_name=f"synthetic_{tbl_name}.csv",
                               mime="text/csv", key=f"dl_csv_{tbl_name}")
        elif output_format == "JSON":
            raw = to_json_string(df)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="json")
            st.download_button("Download JSON", raw, file_name=f"synthetic_{tbl_name}.json",
                               mime="application/json", key=f"dl_json_{tbl_name}")
        elif output_format == "SQL INSERT":
            raw = to_sql_string(df, tbl_name)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="sql")
            st.download_button("Download SQL", raw, file_name=f"synthetic_{tbl_name}.sql",
                               mime="text/sql", key=f"dl_sql_{tbl_name}")

    with tab_validate:
        vr = validate_text(to_csv_string(df))
        for msg in vr["critical"][:10]:
            st.error(f"CRITICAL: {msg}")
        for msg in vr["warnings"][:10]:
            st.warning(f"WARNING: {msg}")
        for msg in vr["info"][:10]:
            st.info(msg)
        if not vr["critical"] and not vr["warnings"]:
            st.success("All checks passed — no real PII/PHI detected.")
        elif vr["critical"]:
            st.error("Critical issues found. DO NOT use this data.")
        else:
            st.warning("Warnings found. Review before using.")

    with tab_stats:
        c1, c2, c3 = st.columns(3)
        c1.metric("Rows", len(df))
        c2.metric("Columns", len(df.columns))
        c3.metric("Seed", seed)
        st.markdown("#### NULL Distribution")
        null_pcts = (df.isnull().sum() / len(df) * 100).round(1)
        null_df = pd.DataFrame({"Column": null_pcts.index, "NULL %": null_pcts.values})
        null_df = null_df[null_df["NULL %"] > 0]
        if len(null_df):
            st.bar_chart(null_df.set_index("Column"))
        else:
            st.info("No NULL values in this dataset.")
        st.markdown("#### Column Details")
        st.dataframe(df.describe(include="all").T, use_container_width=True)


def main():
    st.set_page_config(page_title="Schema-Driven Synthetic Data Generator", page_icon="🗄️", layout="wide")
    st.title("Schema-Driven Synthetic Data Generator")
    st.caption("Paste a SQL `CREATE TABLE` schema and generate realistic synthetic data. All data is entirely fictional.")

    # Sidebar
    st.sidebar.header("Generation Settings")
    row_count = st.sidebar.slider("Rows per table", min_value=5, max_value=5000, value=50, step=5)
    seed = st.sidebar.number_input("Random Seed", min_value=0, max_value=999999, value=42)
    output_format = st.sidebar.selectbox("Output Format", ["Table Preview", "CSV", "JSON", "SQL INSERT"])

    # Session state for example loading
    if "ddl_input" not in st.session_state:
        st.session_state.ddl_input = ""

    # Schema input
    st.subheader("1. Paste your SQL schema")
    col_input, col_example = st.columns([3, 1])

    with col_input:
        ddl_text = st.text_area(
            "CREATE TABLE DDL",
            height=220,
            placeholder="CREATE TABLE my_table (\n    id INT PRIMARY KEY,\n    name VARCHAR(100) NOT NULL,\n    ...\n);",
            key="ddl_input",
            label_visibility="collapsed",
        )

    with col_example:
        uploaded = st.file_uploader("Upload .sql file", type=["sql", "txt"])
        if uploaded:
            st.session_state.ddl_input = uploaded.read().decode("utf-8", errors="replace")
            st.rerun()
        st.markdown("---")
        if st.button("Load example schema", use_container_width=True):
            st.session_state.ddl_input = EXAMPLE_DDL
            st.rerun()
        st.caption("Loads a sample patients + encounters schema")

    # Parse
    tables: List[TableDef] = []
    if ddl_text and ddl_text.strip():
        try:
            tables = parse_ddl(ddl_text)
        except Exception as e:
            st.error(f"Parse error: {e}")
        if not tables:
            st.warning("No `CREATE TABLE` statements found. Check your DDL syntax.")

    # Schema preview
    if tables:
        st.subheader("2. Parsed Schema")
        st.caption(f"Found {len(tables)} table(s). Review inferred generators — you can override any "
                   "column's generator from the dropdown before generating. PK/FK columns stay locked "
                   "to preserve referential integrity.")
        for t in tables:
            with st.expander(f"**{t.name}** — {len(t.columns)} columns", expanded=len(tables) <= 2):
                saved = st.session_state.get(f"overrides_{t.name}", {})
                col_data = []
                for c in t.columns:
                    flags = []
                    if c.is_pk:
                        flags.append("PK")
                    if c.fk_table:
                        flags.append(f"FK → {c.fk_table}")
                    if not c.nullable:
                        flags.append("NOT NULL")
                    locked = bool(c.is_pk or c.fk_table)
                    col_data.append({
                        "Column": c.name,
                        "SQL Type": c.sql_type,
                        "Flags": " | ".join(flags) if flags else "—",
                        "Inferred Generator": _describe_generator(c),
                        "Generator": "Auto (locked)" if locked else saved.get(c.name, AUTO),
                    })
                preview_df = pd.DataFrame(col_data)
                edited = st.data_editor(
                    preview_df,
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{t.name}",
                    disabled=["Column", "SQL Type", "Flags", "Inferred Generator"],
                    column_config={
                        "Generator": st.column_config.SelectboxColumn(
                            "Generator (editable)",
                            options=[AUTO] + list(GENERATOR_REGISTRY.keys()),
                            help="Override the inferred generator for this column",
                        ),
                    },
                )
                # persist overrides (skip locked columns rendered as Auto (locked))
                overrides = {
                    r["Column"]: r["Generator"]
                    for _, r in edited.iterrows()
                    if r["Generator"] not in (AUTO, "Auto (locked)")
                }
                st.session_state[f"overrides_{t.name}"] = overrides
                if overrides:
                    st.caption(f"{len(overrides)} column(s) overridden: "
                               + ", ".join(f"`{c}`" for c in list(overrides)[:6])
                               + (" …" if len(overrides) > 6 else ""))

    # Generation controls
    if tables:
        st.subheader("3. Generate")
        gen_mode = st.radio(
            "Mode",
            ["Single table", "All tables (with referential integrity)"],
            horizontal=True,
        )
        selected_table = None
        if gen_mode == "Single table":
            selected_table = st.selectbox("Table", [t.name for t in tables])

        if st.button("Generate Data", type="primary"):
            random.seed(seed)
            Faker.seed(seed)
            fake = Faker()

            if gen_mode == "All tables (with referential integrity)":
                overrides_all = {t.name: st.session_state.get(f"overrides_{t.name}", {})
                                 for t in tables}
            else:
                tbl = next(t for t in tables if t.name == selected_table)
                overrides_all = {tbl.name: st.session_state.get(f"overrides_{tbl.name}", {})}

            with st.spinner("Generating..."):
                if gen_mode == "All tables (with referential integrity)":
                    all_dfs = generate_all_tables(tables, row_count, fake, overrides_all)
                else:
                    all_dfs = {tbl.name: generate_from_table(tbl, row_count, fake,
                                                             overrides=overrides_all.get(tbl.name, {}))}

            total_rows = sum(len(df) for df in all_dfs.values())
            st.success(f"Generated {total_rows} row(s) across {len(all_dfs)} table(s) (seed={seed})")

            if len(all_dfs) > 1:
                manifest = {
                    "_meta": {"generated_by": "synth-data-gen schema_app", "synthetic": True,
                              "seed": seed, "rows_per_table": row_count,
                              "timestamp": datetime.now().isoformat(timespec="seconds")},
                    "tables": {k: len(v) for k, v in all_dfs.items()},
                }
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for tbl_name, df in all_dfs.items():
                        zf.writestr(f"synthetic_{tbl_name}.csv", to_csv_string(df))
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                st.download_button("📦 Download all tables (zip, CSV + manifest)",
                                   buf.getvalue(), file_name="synthetic_schema_bundle.zip",
                                   mime="application/zip")

            for tbl_name, df in all_dfs.items():
                st.markdown(f"#### `{tbl_name}`")
                _render_results(tbl_name, df, output_format, seed)

    elif not ddl_text or not ddl_text.strip():
        st.markdown("---")
        st.markdown(
            "**Supported inputs:** any standard `CREATE TABLE` DDL — PostgreSQL, MySQL, SQLite, SQL Server\n\n"
            "**Semantic mapping:** column names like `first_name`, `email`, `ssn`, `dob`, `zip`, `salary` "
            "automatically map to realistic generators. All other columns fall back to SQL type-based generation.\n\n"
            "**Safety:** SSNs use `987-65-xxxx`, emails use `@example.com`, phones use `555-01xx`. "
            "An inline validator checks every output before delivery."
        )


if __name__ == "__main__":
    main()
