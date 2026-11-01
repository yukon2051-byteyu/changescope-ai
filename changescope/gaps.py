"""見落としチェック：登録されていないもの・忘れやすい確認事項を指摘する（AIを使わない）。

業種ごとの専用ルールは作らず、要素の種類とつながりの種類だけで判定する。
- 登録の不足    ：分析の範囲で、責任部門や担当が登録されていない
- 確認すべき観点：影響範囲に含まれる要素の種類から、変更時に忘れやすい確認事項を、具体的な対象つきで示す
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from changescope.graph_engine import ImpactResult
from changescope.insights import department_of
from changescope.stakeholders import PERSON_TYPES

REGISTRATION = "登録の不足"
PERSPECTIVE = "確認すべき観点"

# データ移行・切り戻しの観点を出す変更対象の種類（仕組みそのものを入れ替える可能性があるもの）
_REPLACEABLE_TYPES = {"system", "external_service", "process"}


@dataclass
class Finding:
    kind: str  # REGISTRATION または PERSPECTIVE
    title: str
    detail: str
    items: list[str] = field(default_factory=list)


def _names(graph: nx.MultiDiGraph, element_ids) -> list[str]:
    return [graph.nodes[e]["name"] for e in dict.fromkeys(element_ids)]


def find_gaps(graph: nx.MultiDiGraph, result: ImpactResult) -> list[Finding]:
    targets = [t for t in result.targets if t in graph]
    in_range = targets + [i.element_id for i in result.impacts]
    by_type: dict[str, list[str]] = {}
    for element_id in in_range:
        by_type.setdefault(graph.nodes[element_id]["element_type"], []).append(element_id)
    # 各影響に最後にどの関係で届いたか（影響の大きい順）
    reached_by = [(i.path[-1].relation_type, i.element_id) for i in result.impacts]

    findings: list[Finding] = []

    # ---------- 登録の不足 ----------
    no_department = [e for e in in_range
                     if graph.nodes[e]["element_type"] not in PERSON_TYPES and department_of(graph, e) is None]
    if no_department:
        findings.append(Finding(
            REGISTRATION, "責任部門が登録されていない要素",
            "誰に確認すればよいかが分かりません。「要素」シートの「責任部門・担当」を登録してください。",
            _names(graph, no_department),
        ))

    no_performer = [
        p for p in by_type.get("process", [])
        if not any(d["relation_type"] == "performs" and graph.nodes[v]["element_type"] in PERSON_TYPES
                   for _, v, d in graph.out_edges(p, data=True))
    ]
    if no_performer:
        findings.append(Finding(
            REGISTRATION, "担当が登録されていない業務",
            "この業務を誰が行っているかが分からないため、影響を受ける人を見落とすおそれがあります。"
            "「依存関係」シートに、業務 → 部門・役割（業務を担当する）を登録してください。",
            _names(graph, no_performer),
        ))

    # ---------- 確認すべき観点 ----------
    provided_data = [v for t in targets for _, v, d in graph.out_edges(t, data=True)
                     if d["relation_type"] == "provides_data" and graph.nodes[v]["element_type"] == "data"]
    if provided_data and any(graph.nodes[t]["element_type"] in _REPLACEABLE_TYPES for t in targets):
        findings.append(Finding(
            PERSPECTIVE, "データの移行・引き継ぎ",
            "変更対象が扱っているデータです。新しい仕組みへの移行方法、移行後にデータが一致しているかの確認方法、"
            "過去データの保管方法を決めます。",
            _names(graph, provided_data),
        ))

    # 連携先：変更対象から出る連携と、変更対象へ入る連携の両方の相手
    partners = []
    for t in targets:
        for _, other, d in graph.out_edges(t, data=True):
            if d["relation_type"] == "integrates_with":
                partners.append(other)
        for other, _, d in graph.in_edges(t, data=True):
            if d["relation_type"] == "integrates_with":
                partners.append(other)
    partners = [p for p in partners if p not in targets]
    if partners:
        findings.append(Finding(
            PERSPECTIVE, "システム連携の動作確認",
            "連携しているシステムとの間で、データの形式・受け渡しのタイミングが変わらないかを、テストで確認します。",
            _names(graph, partners),
        ))

    approvers = [e for rel, e in reached_by if rel == "approves"]
    if approvers:
        findings.append(Finding(
            PERSPECTIVE, "承認者・権限の設定",
            "承認の流れや権限の設定を、変更後も同じように（または新しいルールどおりに）設定できるか確認します。",
            _names(graph, approvers),
        ))

    performers = [e for rel, e in reached_by
                  if rel == "performs" and graph.nodes[e]["element_type"] in PERSON_TYPES]
    if performers:
        findings.append(Finding(
            PERSPECTIVE, "利用者への周知・教育",
            "業務の手順や操作方法が変わる可能性がある部門・役割です。変更の時期と内容の周知、必要に応じた説明会・マニュアルを計画します。",
            _names(graph, performers),
        ))

    if by_type.get("document"):
        findings.append(Finding(
            PERSPECTIVE, "帳票の出力確認",
            "帳票のレイアウト・出力方法・配布方法が変わらないかを確認します。",
            _names(graph, by_type["document"]),
        ))

    if by_type.get("rule"):
        findings.append(Finding(
            PERSPECTIVE, "社内規程との整合性",
            "変更後の運用が規程に合っているか、規程の改定が必要かを確認します。改定する場合は、承認手続きの期間も計画に含めます。",
            _names(graph, by_type["rule"]),
        ))

    if by_type.get("external_service"):
        findings.append(Finding(
            PERSPECTIVE, "外部サービスとの接続・契約",
            "外部サービスとの接続方法や契約条件に影響がないかを確認します。",
            _names(graph, by_type["external_service"]),
        ))

    if any(graph.nodes[t]["element_type"] in _REPLACEABLE_TYPES for t in targets):
        findings.append(Finding(
            PERSPECTIVE, "切り戻し（元に戻す）計画",
            "変更がうまくいかなかったときに元の状態に戻す手順と、戻すかどうかを判断する基準・期限を用意します。"
            "この情報は登録データに含まれないため、すべての変更で確認が必要です。",
        ))
    return findings
