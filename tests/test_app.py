from streamlit.testing.v1 import AppTest

from core.warehouse import REPO_ROOT


def test_app_renders_chart_for_selected_company(warehouse, monkeypatch):
    monkeypatch.setenv("CFPB_WAREHOUSE_ROOT", str(warehouse.root))
    at = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=120)
    at.run()
    assert not at.exception

    picker = at.selectbox[0]
    assert sorted(picker.options) == [
        "CAPITAL ONE FINANCIAL CORPORATION",
        "CITIBANK, N.A.",
        "SYNCHRONY FINANCIAL",
    ]
    picker.select("SYNCHRONY FINANCIAL").run()
    assert not at.exception
    assert at.subheader[0].value == "Complaints per month: SYNCHRONY FINANCIAL"
    caption = at.caption[0].value
    assert "complaint_count" in caption and "Data snapshot: 2026-10-31" in caption
