"""Tests for the A-share adapter's offline logic.

Nothing here touches the network. The parts worth testing are the
ownership classifier and the record assembly, both of which are pure.
"""

from succession_radar.adapters.ashare import (
    AShareAdapter,
    classify_ownership,
    em_code,
)
from succession_radar.adapters.base import Company, Person


def test_exchange_prefixes():
    assert em_code("002714") == "SZ002714"
    assert em_code("600519") == "SH600519"
    assert em_code("688001") == "SH688001"
    assert em_code("830799") == "BJ830799"


def test_classify_person_controlled():
    assert classify_ownership("秦英林,钱瑛") == "民营"
    assert classify_ownership("朱保国") == "民营"


def test_classify_state_controlled():
    assert classify_ownership("国务院国有资产监督管理委员会") == "国企"
    assert classify_ownership("中国石油天然气集团有限公司") == "国企"
    assert classify_ownership("深圳市人民政府国有资产监督管理委员会") == "国企"


def test_classify_edge_cases():
    assert classify_ownership("") == "无实际控制人"
    assert classify_ownership("无实际控制人") == "无实际控制人"
    # A company name that is not a person and carries no state marker
    # lands in the catch-all rather than being guessed either way.
    assert classify_ownership("某某投资控股有限公司") == "集体或其他法人"


def test_controller_prefers_named_actual_controller():
    """A big institutional holder must not be mistaken for the owner."""
    company = Company(
        name="测试",
        shareholders=[
            Person("某基金管理有限公司", "十大股东", 30.0, is_company=True),
            Person("李明", "十大股东", 12.0),
            Person("王建国", "实际控制人", 8.0),
        ],
    )
    owner = company.controller()
    assert owner is not None and owner.name == "王建国"


def test_build_maps_disclosed_age_and_tenure():
    adapter = AShareAdapter(private_only=True, progress=False)
    company = adapter._build(
        code="000001",
        uni={"SECURITY_NAME_ABBR": "测试股份", "INDUSTRY": "医药",
             "LISTING_DATE": "1993-01-01"},
        org={"REGIONBK": "广东", "FOUND_DATE": "1985-06-01"},
        fin={"TOTAL_OPERATE_INCOME": 5.0e9, "PARENT_NETPROFIT": 4.0e8},
        pledge_ratio=0.03,
        detail={
            "controller": "朱保国",
            "controller_pct": 25.0,
            "top10": [{"name": "某某资管计划", "pct": 5.0}],
            "executives": [
                {"name": "朱保国", "position": "董事长", "age": 64,
                 "birth_year": 1962, "since": "2002-05-01"},
                {"name": "李伟", "position": "总经理", "age": 45,
                 "birth_year": None, "since": "2015-01-01"},
            ],
        },
    )
    assert company is not None
    assert company.is_private
    assert company.legal_rep == "朱保国"
    assert company.legal_rep_since == 2002
    assert company.revenue_m == 5000.0
    assert company.net_profit_m == 400.0
    owner = company.controller()
    assert owner.name == "朱保国" and owner.age == 64


def test_universe_pagination_uses_count_not_pages():
    """The screener reports a total in `count` and returns no `pages`
    field. Paging on `pages` silently stops after the first 500 rows,
    which is how an earlier full-market scan quietly covered less than
    a tenth of the market."""
    import succession_radar.adapters.ashare as mod

    calls = []

    class FakeClient:
        def get_json(self, url, params=None, retries=3):
            page = int(params["p"])
            calls.append(page)
            start = (page - 1) * 500
            rows = [{"SECURITY_CODE": f"{i:06d}"}
                    for i in range(start, min(start + 500, 1200))]
            return {"success": True, "result": {"data": rows, "count": 1200}}

    adapter = mod.AShareAdapter(progress=False)
    adapter.client = FakeClient()
    rows = adapter.universe()
    assert len(rows) == 1200
    assert calls == [1, 2, 3]


def test_build_skips_state_owned_when_private_only():
    adapter = AShareAdapter(private_only=True, progress=False)
    assert adapter._build(
        code="601857", uni={}, org={}, fin={}, pledge_ratio=0.0,
        detail={"controller": "国务院国有资产监督管理委员会"},
    ) is None
