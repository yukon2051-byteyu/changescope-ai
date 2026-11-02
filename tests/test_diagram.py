"""図で入力する画面の計算部分のテスト（配置・データのまとめ・関係の自動選択・読み方・たどった順）。"""

import pytest

from changescope.datasets import load_sample
from changescope.diagram import (
    QUESTIONS, READING, RELATION_HELP, default_relation, direct_links_to_replace, is_answered, isolated, layout,
    reading, update_trail, view_links,
)
from changescope import models


def element(element_id, name, element_type):
    return {"element_id": element_id, "name": name, "element_type": element_type}


def link(dependency_id, source, target, relation_type="uses", status="confirmed"):
    return {"dependency_id": dependency_id, "from_id": source, "to_id": target, "relation_type": relation_type,
            "direction": "one_way", "status": status, "evidence": "ヒアリング"}


# 勤怠管理システム → 勤怠実績データ → 経理部、勤怠実績データ → 個人情報取扱規程
ELEMENTS = [element("SYS", "勤怠管理システム", "system"), element("DATA", "勤怠実績データ", "data"),
            element("ACC", "経理部", "department"), element("RULE", "個人情報取扱規程", "rule"),
            element("SOLO", "未接続の帳票", "document")]
LINKS = [link("D-1", "SYS", "DATA", "provides_data"), link("D-2", "DATA", "ACC", "uses", "assumed"),
         link("D-3", "DATA", "RULE", "governed_by")]


# ---------- 関係の種類の自動選択・読み方 ----------

@pytest.mark.parametrize("source, target, expected", [
    ("data", "department", "uses"),          # 勤怠実績データ → 経理部（以前は誤って「データを提供する」になった）
    ("data", "process", "uses"),
    ("system", "data", "provides_data"),
    ("system", "document", "produces"),
    ("system", "system", "integrates_with"),
    ("process", "department", "performs"),
    ("process", "rule", "governed_by"),
    ("department", "system", "depends_on"),  # どれにも当てはまらない
    ("設備", "process", "depends_on"),        # 利用者が追加した種類でもエラーにしない
])
def test_default_relation(source, target, expected):
    assert default_relation(source, target) == expected


def test_reading_and_help_cover_all_relations():
    assert set(READING) == set(models.RELATION_TYPES) == set(RELATION_HELP)
    assert reading("勤怠実績データ", "経理部", "uses") == "「勤怠実績データ」は、「経理部」に利用される（使われる・受け取られる）"
    assert "検査を受ける" in reading("製品", "品質保証部", "検査を受ける")  # 追加した関係の種類


def test_questions_use_known_types_and_relations():
    for element_type, questions in QUESTIONS.items():
        assert element_type in models.ELEMENT_TYPES
        for q in questions:
            assert q.side in ("in", "out")
            assert q.element_type in models.ELEMENT_TYPES and q.relation_type in models.RELATION_TYPES


def test_is_answered():
    data_users = next(q for q in QUESTIONS["data"] if q.relation_type == "uses")
    data_makers = next(q for q in QUESTIONS["data"] if q.relation_type == "provides_data")
    assert is_answered(data_users, "DATA", LINKS)        # DATA → 経理部（利用される）がある
    assert is_answered(data_makers, "DATA", LINKS)       # 勤怠管理システム → DATA（提供する）がある
    assert not is_answered(QUESTIONS["system"][1], "SYS", LINKS)  # システムを使う業務は未回答


# ---------- 配置 ----------

def test_layout_places_chain_left_to_right():
    result = layout(ELEMENTS, LINKS, "SYS")
    columns = {p.element_id: p.column for p in result.placements}
    assert columns == {"SYS": "center", "DATA": "first", "ACC": "second", "RULE": "second"}
    assert {l["dependency_id"] for l in result.edges} == {"D-1", "D-2", "D-3"}


def test_layout_left_side_and_uncertain_first():
    links = LINKS + [link("D-4", "DATA", "SOLO", "uses", "confirmed")]
    result = layout(ELEMENTS, links, "DATA")
    left = [p.element_id for p in result.placements if p.column == "left"]
    first = [p.element_id for p in result.placements if p.column == "first"]
    assert left == ["SYS"]
    assert first[0] == "ACC"  # 推定のつながりの相手が先頭（確認すべきものを上に）


def test_layout_limits_rows_and_counts_hidden():
    many = [element(f"P{i}", f"業務{i}", "process") for i in range(10)]
    links = [link(f"L{i}", "SYS", f"P{i}") for i in range(10)]
    result = layout(ELEMENTS + many, links, "SYS", max_rows=6)
    shown = [p for p in result.placements if p.column == "first"]
    assert len(shown) == 5 and result.hidden == {"first": 5} and result.rows == 6


# ---------- データをまとめて表示 ----------

def test_collapse_data_into_line_name():
    drawn = view_links(ELEMENTS, LINKS, "SYS", collapse_data=True)
    assert len(drawn) == 1
    via = drawn[0]
    assert (via["from_id"], via["to_id"], via["relation_type"], via["via"]) == ("SYS", "ACC", "勤怠実績データ", "DATA")
    assert via["status"] == "assumed"  # 2本のうち不確かな方
    # 規程とのつながりは、まとめた表示では描かない。登録の内容は変わらない
    assert all(l["to_id"] != "RULE" for l in drawn) and len(LINKS) == 3


def test_collapse_keeps_center_data_and_one_sided_data():
    assert view_links(ELEMENTS, LINKS, "DATA", collapse_data=True) == LINKS  # 見ている要素がデータ
    only_maker = [link("D-1", "SYS", "DATA", "provides_data")]
    assert view_links(ELEMENTS, only_maker, "SYS", collapse_data=True) == only_maker  # 使う側がない


def test_collapse_with_sample_data_reduces_boxes():
    ds = load_sample()
    elements = ds.elements.to_dict("records")
    links = ds.dependencies.to_dict("records")
    plain = layout(elements, links, "SYS-ATT")
    collapsed = layout(elements, links, "SYS-ATT", collapse_data=True)
    plain_types = {ds.graph.nodes[p.element_id]["element_type"] for p in plain.placements}
    collapsed_types = {ds.graph.nodes[p.element_id]["element_type"] for p in collapsed.placements}
    assert "data" in plain_types and "data" not in collapsed_types


# ---------- たどった順・未接続・直接の線の置き換え ----------

def test_update_trail_appends_and_truncates():
    trail = update_trail(update_trail(update_trail([], "A"), "B"), "C")
    assert trail == ["A", "B", "C"]
    assert update_trail(trail, "A") == ["A"]  # 戻ったら、そこから先を消す
    assert update_trail(trail, "C") == ["A", "B", "C"]


def test_isolated():
    assert isolated(ELEMENTS, LINKS) == ["SOLO"]


def test_direct_links_to_replace():
    links = LINKS + [link("D-9", "SYS", "ACC")]  # 勤怠管理システム → 経理部 の直接の線
    assert [l["dependency_id"] for l in direct_links_to_replace(links, "SYS", "DATA", "ACC")] == ["D-9"]
    assert direct_links_to_replace(links, "SYS", "SYS", "ACC") == []  # 真ん中から引いた線は置き換えない


# ---------- 図で編集したデータを、分析用のデータにする ----------

def test_records_round_trip_keeps_sample():
    from changescope.datasets import load_from_records, to_records
    ds = load_sample()
    result = load_from_records(*to_records(ds))
    assert not result.errors and result.dataset.source == "diagram"
    assert len(result.dataset.elements) == 57 and len(result.dataset.dependencies) == 75
    assert result.dataset.graph.number_of_edges() == ds.graph.number_of_edges()


def test_records_use_the_same_checks_as_excel():
    from changescope.datasets import load_from_records
    duplicated = ELEMENTS + [element("SYS2", "勤怠管理システム", "system")]
    result = load_from_records(duplicated, LINKS)
    assert result.dataset is None and any("勤怠管理システム" in e for e in result.errors)  # 同じ名前はエラー
    missing = LINKS + [link("D-8", "SYS", "NOWHERE")]
    assert load_from_records(ELEMENTS, missing).dataset is None  # 存在しない参照先はエラー


def test_records_accept_custom_types():
    from changescope.datasets import load_from_records
    custom = ELEMENTS + [element("EQ", "製造ライン1", "設備")]
    result = load_from_records(custom, LINKS + [link("D-7", "SYS", "EQ", "監視する")])
    assert result.dataset is not None  # 利用者が追加した種類・関係の種類も使える
