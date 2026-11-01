"""M2-06: product labels map to families across the 2017 and 2023 revisions; credit card
issues map onto the current issue list. Checked on real rows from every era."""

import duckdb


def _q(wh, sql):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql).fetchall()


def test_every_complaint_has_a_product_family(eras_warehouse):
    unmapped = "SELECT count(*) FROM int_complaints WHERE product_family IS NULL"
    assert _q(eras_warehouse, unmapped) == [(0,)]
    families = _q(eras_warehouse, "SELECT count(DISTINCT product_family) FROM int_complaints")
    assert families == [(11,)]


def test_split_labels_follow_the_sub_product(eras_warehouse):
    rows = dict(
        _q(
            eras_warehouse,
            """SELECT product || ' / ' || coalesce(sub_product, '-'), any_value(product_family)
               FROM int_complaints GROUP BY 1""",
        )
    )
    assert rows["Credit card or prepaid card / General-purpose credit card or charge card"] == (
        "credit_card"
    )
    assert rows["Credit card or prepaid card / Gift card"] == "prepaid_card"
    assert rows["Consumer Loan / Vehicle loan"] == "vehicle_loan_lease"
    assert rows["Consumer Loan / Installment loan"] == "payday_personal_loan"
    assert rows["Credit card / -"] == "credit_card"  # pre-2017: no sub-product (structural)


def test_credit_card_issues_map_onto_the_current_list(eras_warehouse):
    assert _q(
        eras_warehouse,
        """SELECT count(*) FROM int_complaints WHERE product_family = 'credit_card'
           AND issue IS NOT NULL AND credit_card_issue IS NULL""",
    ) == [(0,)]
    old = dict(
        _q(
            eras_warehouse,
            """SELECT DISTINCT issue, credit_card_issue FROM int_complaints
               WHERE product = 'Credit card' AND date_received < '2017-04-24'""",
        )
    )
    assert old["Billing disputes"] == "Problem with a purchase shown on your statement"
    assert old["Late fee"] == "Fees or interest"
    # reviewed: fraud has no single current home, so it keeps its own legacy value
    assert (
        old["Identity theft / Fraud / Embezzlement"] == "Fraud or identity theft (pre-2017 label)"
    )
    assert old["Billing statement"] == "Problem when making payments"
    assert _q(
        eras_warehouse,
        "SELECT count(*) FROM int_complaints WHERE product_family <> 'credit_card' "
        "AND credit_card_issue IS NOT NULL",
    ) == [(0,)]
