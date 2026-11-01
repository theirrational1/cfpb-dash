"""Review 4 #1, #2, #6: metrics combined with filters, peer dimensions and each other, through
the governed path. Each combination must run and agree with its single-metric answers."""

import pytest

from agent.tools.query_metric import query_metric

CITI = {"complaint__company": "CITIBANK, N.A."}
SHARE = "issue_share_fees_or_interest"


def test_growth_with_a_filter(warehouse):
    """#1: the filter-value check used the first metric, which mf cannot list for offsets."""
    filtered = query_metric(["complaint_growth_mom"], group_by=["metric_time__month"],
                            filters=CITI, warehouse=warehouse).rows  # fmt: skip
    grouped = query_metric(["complaint_growth_mom"],
                           group_by=["complaint__company", "metric_time__month"],
                           warehouse=warehouse).rows  # fmt: skip
    citi = {r["metric_time__month"]: r["complaint_growth_mom"] for r in grouped
            if r["complaint__company"] == CITI["complaint__company"]}  # fmt: skip
    assert {r["metric_time__month"]: r["complaint_growth_mom"] for r in filtered} == citi


@pytest.mark.parametrize(
    ("metrics", "group_by", "filters"),
    [
        ([SHARE, "complaint_count"], ["company_product__volume_tier"], {}),
        (["relief_rate", SHARE], ["complaint__company"], {"company_product__volume_tier": "high"}),
        ([SHARE], ["company_product__volume_tier"], {}),
    ],
)
def test_issue_share_combines_with_peer_dimensions(warehouse, metrics, group_by, filters):
    """#2: issue metrics lived in a second semantic model, two joins from the peer table."""
    rows = query_metric(metrics, group_by=group_by, filters=filters, warehouse=warehouse).rows
    assert rows and all(set(group_by) <= set(r) for r in rows)
    single = query_metric([SHARE], group_by=group_by, filters=filters, warehouse=warehouse).rows
    key = group_by[0]
    assert {r[key]: r[SHARE] for r in rows} == {r[key]: r[SHARE] for r in single}
