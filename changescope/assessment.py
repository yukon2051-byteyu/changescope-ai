"""分析結果の総合判定と結論（AIを使わず、ルールで決める）。

結果を見た人が「まず何をすればよいか」「何を意識すればよいか」をすぐ分かるよう、
影響範囲を 大・中・小 で判定し、判定ごとの進め方と最初の一歩を短く示す。

判定の基準は「影響を受ける部門の数」。変更の手間とリスクは、主に何部門と調整が必要かで決まるため。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from changescope.graph_engine import ImpactResult
from changescope.insights import department_of, hard_to_notice
from changescope.next_actions import find_uncertain_links
from changescope.stakeholders import Stakeholder

LARGE_DEPARTMENTS = 3  # この部門数以上で「大」
MEDIUM_DEPARTMENTS = 2  # この部門数で「中」
LOW_CERTAINTY_RATIO = 0.3  # 要確認の割合がこれ以上なら、確からしさが低いと注意する

# 判定ごとの意味と、意識すること（進め方）
_LEVELS = {
    "大": (
        "複数の部門にまたがる変更です。1部門の判断だけでは進められません。",
        [
            "部門横断のプロジェクトとして扱い、関係部門を集めて変更の目的と範囲を最初に共有する",
            "スケジュールに、関係部門との確認・調整の期間をあらかじめ確保する",
            "一度に切り替えず、段階的な移行や新旧の並行運用を検討し、切り戻し計画を必ず用意する",
        ],
    ),
    "中": (
        "変更対象の部門のほかに、1つの部門が関わる変更です。",
        [
            "関わる部門と個別に調整し、影響を受ける業務・データを一緒に確認する",
            "連携や帳票など、部門の間で受け渡すものをテスト計画に入れる",
            "切り戻し計画を用意する",
        ],
    ),
    "小": (
        "変更対象の部門の中で完結する変更です。",
        [
            "責任部門の中で計画を進められる",
            "要確認の事項と、見落としチェックの項目だけは確認する",
        ],
    ),
}


@dataclass
class Assessment:
    level: str  # 大・中・小
    headline: str  # 結論の1文
    meaning: str  # 判定の意味
    first_step: str  # まずやること
    stance: list[str] = field(default_factory=list)  # 意識すること
    basis: str = ""  # 判定の根拠
    caution: str = ""  # 確からしさが低い場合の注意


def assess(graph: nx.MultiDiGraph, result: ImpactResult, stakeholders: list[Stakeholder]) -> Assessment:
    in_range = [t for t in result.targets if t in graph] + [i.element_id for i in result.impacts]
    departments = {d for e in in_range if (d := department_of(graph, e))}
    n_departments = len(departments)
    if n_departments >= LARGE_DEPARTMENTS:
        level = "大"
    elif n_departments >= MEDIUM_DEPARTMENTS:
        level = "中"
    else:
        level = "小"
    meaning, stance = _LEVELS[level]

    n_impacts = len(result.impacts)
    uncertain = sum(i.path_status != "confirmed" for i in result.impacts)
    hidden = len(hard_to_notice(graph, result))

    headline = f"影響範囲は「{level}」です。{n_departments}部門・{n_impacts}件に影響が及ぶ可能性があります。"
    basis = (f"判定の根拠：影響を受ける部門 {n_departments}（3部門以上＝大、2部門＝中、1部門＝小）"
             f"／影響 {n_impacts}件／見落としやすい影響 {hidden}件／要確認 {uncertain}件")

    owners = [s.name for s in stakeholders if s.is_target_owner]
    share = f"{'・'.join(owners)}と変更の方針を共有し" if owners else "変更対象の責任部門を決めて方針を共有し"
    # 確かめる単位は「つながり」。「次にやること」の件数と合わせる
    n_links = len(find_uncertain_links(graph, result))
    if n_links:
        first_step = f"まず、{share}、要確認のつながり{n_links}件を確かめてください。"
    elif hidden:
        first_step = f"まず、{share}、見落としやすい影響{hidden}件をその部門に伝えてください。"
    else:
        first_step = f"まず、{share}、影響の大きい要素から確認してください。"

    caution = ""
    if n_impacts and uncertain / n_impacts >= LOW_CERTAINTY_RATIO:
        caution = (f"影響の{round(uncertain / n_impacts * 100)}%（{uncertain}件）に推定・未確認のつながりが含まれています。"
                   "この結果は確定ではありません。計画を固める前に、事実確認を優先してください。")

    return Assessment(level, headline, meaning, first_step, list(stance), basis, caution)
