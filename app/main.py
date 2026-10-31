"""Walking-skeleton dashboard: pick a company, see complaint_count by month.

Every number comes from query_metric (governed MetricFlow metrics); the app does no math.
Run: uv run streamlit run app/main.py   (CFPB_WAREHOUSE_ROOT overrides data/warehouse)
"""

import os
import sys
from pathlib import Path

# `streamlit run` puts only app/ on sys.path; the project packages live at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from agent.tools.query_metric import MetricResult, query_metric  # noqa: E402
from core.warehouse import Warehouse  # noqa: E402

METRIC = "complaint_count"


def warehouse() -> Warehouse:
    root = os.environ.get("CFPB_WAREHOUSE_ROOT")
    return Warehouse(Path(root)) if root else Warehouse()


@st.cache_data(show_spinner=False)
def companies(root: str) -> list[str]:
    result = query_metric(
        [METRIC], group_by=["complaint__company"], warehouse=Warehouse(Path(root))
    )
    ranked = sorted(result.rows, key=lambda r: r[METRIC] or 0, reverse=True)
    return [str(r["complaint__company"]) for r in ranked]


@st.cache_data(show_spinner=False)
def monthly(root: str, company: str) -> MetricResult:
    return query_metric(
        [METRIC],
        group_by=["metric_time__month"],
        filters={"complaint__company": company},
        warehouse=Warehouse(Path(root)),
    )


def main() -> None:
    st.set_page_config(page_title="CFPB Complaint Intelligence", layout="wide")
    st.title("CFPB Complaint Intelligence")
    root = str(warehouse().root)
    company = st.selectbox("Company", companies(root))
    result = monthly(root, company)
    st.subheader(f"Complaints per month: {company}")
    st.line_chart(result.rows, x="metric_time__month", y=METRIC)
    p = result.provenance
    st.caption(
        f"Metric: {', '.join(p.metrics)} · Filters: {p.filters} · "
        f"Data snapshot: {p.snapshot_date}. Complaints are unverified allegations; "
        "counts are not rates."
    )


main()
