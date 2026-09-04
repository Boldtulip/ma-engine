"""Offline tests for the label builder and the annual-report parser.

Nothing here touches the network. The parser is exercised on text in
the shape of both exchange layouts, and the label logic on invented
episodes.
"""

import datetime as dt

from ma_engine.adapters.ashare_annual import (
    controller_from_block,
    parse_annual_report,
)
from ma_engine.labels import control_changes as cc


SZSE_TEXT = """
第四节 董事、监事和高级管理人员情况
姓名 性别 年龄 职务 任职状态
王建国 男 62 董事长 现任
王磊 男 34 董事、总经理 现任
李四 女 45 独立董事 现任
赵六 男 58 监事会主席 离任
王建国先生：1963年 8月出生，中国国籍，无境外永久居留权。
(二) 实际控制人情况
实际控制人性质 境内自然人 实际控制人姓名 王建国 国籍 中国
"""

SSE_TEXT = """
姓名 职务 性别 年龄 任期起始日期 任期终止日期
李林 董事长 男 62 2005/6/20 2027/6/19
张三 总经理 男 50 2018/1/1 2027/6/19
实际控制人情况 实际控制人性质 自然人 姓名 李林 国籍 中国
"""


def test_parse_szse_layout():
    d = parse_annual_report(SZSE_TEXT)
    assert d["chairman"]["name"] == "王建国"
    assert d["chairman"]["age"] == 62
    assert d["chairman"]["birth_year"] == 1963
    names = {o["name"] for o in d["officers"]}
    assert {"王建国", "王磊", "李四", "赵六"} <= names
    assert "实际控制人" in d["actual_controller"]


def test_parse_sse_layout_keeps_appointment_year():
    d = parse_annual_report(SSE_TEXT)
    assert d["chairman"]["name"] == "李林"
    assert d["chairman"]["since"] == 2005


def test_controller_from_block_matches_board():
    d = parse_annual_report(SZSE_TEXT)
    names, kind = controller_from_block(d["actual_controller"], d["officers"],
                                        d["chairman"])
    assert names == ["王建国"] and kind == "民营"


def test_controller_from_block_state():
    names, kind = controller_from_block(
        "实际控制人性质 国有法人 实际控制人名称 深圳市人民政府国有资产监督管理委员会",
        [], None)
    assert kind == "国企" and names == []


def test_title_filter():
    assert cc.is_control_change_title("关于筹划公司控制权变更事项的停牌公告")
    assert cc.is_control_change_title("关于实际控制人发生变更的公告")
    assert not cc.is_control_change_title("关于变更公司名称的公告")
    assert not cc.is_control_change_title("关于子公司控股股东变更的公告")
    assert cc.is_control_change_title("关于部分公司股份转让暨控制权变更的公告")


def _ann(code, date, title):
    return {"code": code, "name": "x", "date": date, "title": title, "id": f"{code}{date}"}


def test_build_episodes_groups_by_gap():
    anns = [
        _ann("000001", "2025-02-01", "关于筹划控制权变更事项的停牌公告"),
        _ann("000001", "2025-03-15", "关于实际控制人发生变更的公告"),
        _ann("000001", "2026-05-01", "关于筹划控制权变更事项的停牌公告"),   # new episode
        _ann("000002", "2025-06-01", "关于终止控制权变更事项的公告"),
        _ann("000003", "2025-06-01", "关于变更公司名称的公告"),               # not a control change
    ]
    eps = cc.build_episodes(anns, gap_days=270)
    by = {(e.code, e.first_date.isoformat()): e for e in eps}
    assert len([e for e in eps if e.code == "000001"]) == 2
    first = by[("000001", "2025-02-01")]
    assert first.confirmed and not first.terminated and first.n_announcements == 2
    assert by[("000002", "2025-06-01")].terminated
    assert not any(e.code == "000003" for e in eps)


def test_make_labels_window_and_exclusions():
    eps = [
        cc.Episode("000001", "a", dt.date(2025, 6, 1), dt.date(2025, 8, 1), 3, "t", True, False),
        cc.Episode("000002", "b", dt.date(2025, 7, 1), dt.date(2025, 7, 1), 1, "t", False, True),
        cc.Episode("000003", "c", dt.date(2025, 1, 10), dt.date(2025, 4, 20), 4, "t", True, False),
        cc.Episode("000004", "d", dt.date(2023, 3, 1), dt.date(2023, 5, 1), 2, "t", True, False),
    ]
    ls = cc.make_labels(eps, ["000001", "000002", "000003", "000004", "000005"],
                        dt.date(2025, 5, 1), dt.date(2026, 9, 4))
    assert ls.labels["000001"] == 1                      # deal in window
    assert "000002" in ls.excluded                       # only a terminated deal
    assert "000003" in ls.excluded                       # in progress at scoring date
    assert ls.labels["000004"] == 0                      # old deal, long finished
    assert ls.labels["000005"] == 0                      # never any deal
    assert ls.positives == 1


def test_write_and_read_episodes_roundtrip(tmp_path):
    eps = [cc.Episode("000001", "a", dt.date(2025, 6, 1), dt.date(2025, 8, 1),
                      3, "关于筹划控制权变更事项的停牌公告", True, False)]
    path = cc.write_episodes(eps, tmp_path / "e.csv")
    back = cc.read_episodes(path)
    assert back[0].code == "000001" and back[0].confirmed and not back[0].terminated


def test_labels_file_uses_source_ids(tmp_path):
    ls = cc.LabelSet({"000001": 1, "000002": 0}, {}, dt.date(2025, 5, 1), dt.date(2026, 9, 4))
    path = cc.write_labels(ls, tmp_path / "labels.csv")
    text = path.read_text(encoding="utf-8-sig")
    assert "ashare:000001,1" in text and "ashare:000002,0" in text
