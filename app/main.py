"""Walking-skeleton dashboard: pick a company, see complaint_count by month.

Every number comes from query_metric (governed MetricFlow metrics); the app does no math.
Run: uv run streamlit run app/main.py   (CFPB_WAREHOUSE_ROOT / CFPB_DBT_PROJECT_DIR override)
"""

import sys
from pathlib import Path

# `streamlit run` puts only app/ on sys.path; the project packages live at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from agent.tools.query_metric import MetricResult, query_metric, read_snapshot_stamp  # noqa: E402
from core.warehouse import Warehouse  # noqa: E402

METRIC = "complaint_count"


# Cached functions take the warehouse build stamp as an argument, so a rebuilt warehouse
# (new snapshot or new build) never serves numbers cached from the previous one.
@st.cache_data(show_spinner=False)
def companies(root: str, project: str, build: str) -> list[str]:
    wh = Warehouse(Path(root), Path(project))
    result = query_metric([METRIC], group_by=["complaint__company"], warehouse=wh)
    ranked = sorted(result.rows, key=lambda r: r[METRIC] or 0, reverse=True)
    return [str(r["complaint__company"]) for r in ranked]


@st.cache_data(show_spinner=False)
def monthly(root: str, project: str, build: str, company: str) -> MetricResult:
    return query_metric(
        [METRIC],
        group_by=["metric_time__month"],
        filters={"complaint__company": company},
        warehouse=Warehouse(Path(root), Path(project)),
    )


def main() -> None:
    st.set_page_config(page_title="CFPB Complaint Intelligence", layout="wide")
    st.title("CFPB Complaint Intelligence")
    wh = Warehouse.from_env()
    stamp = read_snapshot_stamp(wh)
    build = f"{stamp['source_sha256']}@{stamp['built_at']}"
    root, project = str(wh.root), str(wh.project_dir)

    company = st.selectbox("Company", companies(root, project, build))
    result = monthly(root, project, build, company)
    st.subheader(f"Complaints per month: {company}")
    st.line_chart(result.rows, x="metric_time__month", y=METRIC)

    p = result.provenance
    months = [str(r["metric_time__month"])[:7] for r in result.rows]
    span = f"{months[0]} to {months[-1]}" if months else "no data"
    st.caption(
        f"Metric: {', '.join(p.metrics)} · Filters: {p.filters} · Time range: {span} "
        f"(months with no complaints show 0) · Data snapshot: {p.snapshot_date}. "
        "Complaints are unverified allegations; counts are not rates."
    )


main()
