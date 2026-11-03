"""変更影響の探索エンジン。

検証済みの要素・依存関係からグラフ（点と線の構造）を作り、変更対象から影響が伝わる要素を
幅優先探索（近い要素から順に広げていく探索）で抽出する。AIは使わず、結果には必ず
「どの依存関係をたどったか」という経路を付ける。

- 1段目の要素 = 直接影響、2段目以降 = 間接影響
- 一度たどった要素は再訪しないため、循環参照があっても無限ループしない
- 最大段数で探索を打ち切り、その先にも影響がありうる場合は記録する
- 同じ段数の経路が複数あるときは、確認済みの経路を優先して代表の経路にする（番号の順は最後の決め手だけ）
- 要素の確認状態は、段数の上限までのすべての経路のうち、いちばん確かな経路で決める
  （確認済みだけで届く経路が1本でもあれば、影響を受けることは確か）
- 経路に選ばれなかったつながりも、影響範囲の中にあるものは links_in_scope に残す
  （推定・未確認のつながりを、代表の経路に出てこないために見落とさないように。レビュー C06）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from changescope import models

DEFAULT_MAX_DEPTH = 3

# 影響度スコアの「近さ」の点数（段数 → 点）。表にない段数は1点
PROXIMITY_POINTS = {1: 6, 2: 4, 3: 2}

# 確認状態の確かさの順位（小さいほど不確か）。経路の中で最も不確かな状態をその影響の状態とする
_STATUS_RANK = {"unconfirmed": 0, "assumed": 1, "confirmed": 2}


@dataclass
class Step:
    """経路の1区間（ある依存関係を1本たどったこと）。"""

    dependency_id: str
    from_id: str
    to_id: str
    relation_type: str
    evidence: str
    status: str
    reversed: bool  # 双方向の関係を逆向きにたどった場合 True
    note: str = ""


@dataclass
class ImpactItem:
    """影響を受ける要素1件。"""

    element_id: str
    name: str
    element_type: str
    depth: int
    path: list[Step]
    spread: int = 0  # 波及数：この要素を経由して影響が伝わる要素の数
    extra_paths: int = 0  # 複数経路：最短経路以外にも影響を受けるつながりの数
    best_status: str = ""  # 段数の上限までのすべての経路のうち、いちばん確かな経路の確認状態
    other_links: list[Step] = field(default_factory=list)  # 代表の経路以外に、影響範囲からこの要素へ届くつながり

    @property
    def proximity(self) -> int:
        """近さの点数。変更対象に近いほど高い。"""
        return PROXIMITY_POINTS.get(self.depth, 1)

    @property
    def score(self) -> int:
        """影響度 ＝ 近さ ＋ 波及数 ＋ 複数経路。確からしさ（確認状態）は別の軸として含めない。"""
        return self.proximity + self.spread + self.extra_paths

    @property
    def level(self) -> str:
        return "direct" if self.depth == 1 else "indirect"

    @property
    def path_status(self) -> str:
        """この影響の確認状態。経路の中で最も不確かなつながりの状態だが、ほかにもっと確かな経路があればそちらを使う。

        例：確認済みだけで届く経路が1本でもあれば「確認済」（影響を受けることは確か）。
        """
        return self.best_status or _weakest(self.path)


@dataclass
class ImpactResult:
    targets: list[str]
    impacts: list[ImpactItem] = field(default_factory=list)
    unknown_targets: list[str] = field(default_factory=list)
    # 最大段数で打ち切った先に、まだ影響がありうる要素
    beyond_max_depth: list[str] = field(default_factory=list)
    # 影響範囲の中にあるつながり（代表の経路に選ばれなかったものも含む。番号の順）
    links_in_scope: list[Step] = field(default_factory=list)

    @property
    def direct(self) -> list[ImpactItem]:
        return [i for i in self.impacts if i.level == "direct"]

    @property
    def indirect(self) -> list[ImpactItem]:
        return [i for i in self.impacts if i.level == "indirect"]


def build_graph(elements: pd.DataFrame, dependencies: pd.DataFrame) -> nx.MultiDiGraph:
    """要素と依存関係からグラフを作る。

    同じ2要素の間に種類の違う関係が複数ありうるため、MultiDiGraph（向きあり・複数の線を許す）を使う。
    双方向（both）の関係は、逆向きの線も追加する。
    """
    graph = nx.MultiDiGraph()
    for _, row in elements.iterrows():
        owner = row.get("owner", "")
        graph.add_node(row["element_id"], name=row["name"], element_type=row["element_type"],
                       owner=owner if isinstance(owner, str) else "")

    # 検証済みデータが前提だが、念のため存在しない要素への線は追加しない
    for _, row in dependencies.sort_values("dependency_id").iterrows():
        if row["from_id"] not in graph or row["to_id"] not in graph:
            continue
        attrs = {
            "dependency_id": row["dependency_id"],
            "relation_type": row["relation_type"],
            "evidence": row["evidence"],
            "status": row["status"],
            "note": row.get("note", ""),
        }
        graph.add_edge(row["from_id"], row["to_id"], key=row["dependency_id"], reversed=False, **attrs)
        if row["direction"] == "both":
            graph.add_edge(row["to_id"], row["from_id"], key=row["dependency_id"] + "~r", reversed=True, **attrs)
    return graph


def _weakest(path: list[Step]) -> str:
    """経路の中で最も不確かな確認状態。"""
    return min((s.status for s in path), key=_STATUS_RANK.__getitem__)


def _path_key(path: list[Step]) -> tuple:
    """代表の経路の選び方：確かな経路を優先し、同じ確かさなら番号の若い順（結果を毎回同じにするため）。"""
    return (-_STATUS_RANK[_weakest(path)], [s.dependency_id for s in path])


def _step(current: str, neighbor: str, data: dict) -> Step:
    return Step(
        dependency_id=data["dependency_id"],
        from_id=current,
        to_id=neighbor,
        relation_type=data["relation_type"],
        evidence=data["evidence"],
        status=data["status"],
        reversed=data["reversed"],
        note=data["note"],
    )


def _shortest_paths(graph: nx.MultiDiGraph, starts: list[str], max_depth: int,
                    min_rank: int = 0) -> tuple[dict[str, list[Step]], set[str]]:
    """変更対象から1段ずつ広げて（幅優先探索）、各要素への代表の経路を1本ずつ決める。

    min_rank：これより不確かなつながりは通らない（2＝確認済みだけ、1＝推定まで、0＝すべて）。
    同じ段数の候補が複数あれば _path_key で選ぶ。
    戻り値は（要素ごとの経路, 段数の上限の先につながっている要素）。変更対象は空の経路で入る。
    """
    # 変更対象そのものは影響一覧に含めない（深さ0として訪問済みにする）
    paths: dict[str, list[Step]] = {t: [] for t in starts}
    frontier = list(starts)
    beyond: set[str] = set()
    depth = 0
    while frontier:
        candidates: dict[str, list[Step]] = {}
        for current in frontier:
            for _, neighbor, _, data in graph.out_edges(current, keys=True, data=True):
                if neighbor in paths or _STATUS_RANK[data["status"]] < min_rank:
                    continue  # 訪問済み（循環参照・合流）はたどらない
                if depth >= max_depth:
                    beyond.add(neighbor)
                    continue
                path = paths[current] + [_step(current, neighbor, data)]
                if neighbor not in candidates or _path_key(path) < _path_key(candidates[neighbor]):
                    candidates[neighbor] = path
        paths.update(candidates)
        frontier = sorted(candidates)
        depth += 1
    return paths, beyond


def analyze_impact(graph: nx.MultiDiGraph, target_ids: list[str], max_depth: int = DEFAULT_MAX_DEPTH) -> ImpactResult:
    """変更対象から影響が伝わる要素を探索する。各要素には代表の経路（最短で、いちばん確かなもの）を1本記録する。"""
    if max_depth < 1:
        raise ValueError("max_depth は1以上を指定してください。")

    result = ImpactResult(targets=list(target_ids))
    starts = [t for t in dict.fromkeys(target_ids) if t in graph]
    result.unknown_targets = [t for t in target_ids if t not in graph]

    paths, beyond = _shortest_paths(graph, starts, max_depth)
    # 確認状態：確認済みだけ・推定までのつながりで届くかを、同じ段数の上限で調べる
    reach_confirmed, _ = _shortest_paths(graph, starts, max_depth, min_rank=_STATUS_RANK["confirmed"])
    reach_assumed, _ = _shortest_paths(graph, starts, max_depth, min_rank=_STATUS_RANK["assumed"])

    def best_status(element_id: str) -> str:
        if element_id in reach_confirmed:
            return "confirmed"
        return "assumed" if element_id in reach_assumed else "unconfirmed"

    # 波及数：各影響の経路の途中にある要素ごとに、経由して影響が伝わった件数を数える
    spread = {element_id: 0 for element_id in paths}
    for path in paths.values():
        for step in path[:-1]:
            spread[step.to_id] += 1

    affected = set(paths)
    # 影響範囲の中のつながり：変更対象・影響範囲の要素から、影響範囲の要素へのつながり（変更対象へ戻るものは除く）
    in_scope: dict[str, Step] = {}
    for u, v, data in graph.edges(data=True):
        if u in affected and v in affected and v not in starts and u != v:
            in_scope.setdefault(data["dependency_id"], _step(u, v, data))
    result.links_in_scope = [in_scope[k] for k in sorted(in_scope)]

    for element_id, path in paths.items():
        if not path:
            continue
        node = graph.nodes[element_id]
        # 複数経路：変更対象・影響範囲の要素のうち、この要素へ線がつながっている要素の数（最短経路の1本を除く）
        sources = {u for u, _ in graph.in_edges(element_id) if u in affected and u != element_id}
        others = [s for s in result.links_in_scope
                  if s.to_id == element_id and s.dependency_id != path[-1].dependency_id]
        result.impacts.append(
            ImpactItem(element_id, node["name"], node["element_type"], len(path), path,
                       spread=spread[element_id], extra_paths=max(0, len(sources) - 1),
                       best_status=best_status(element_id), other_links=others)
        )
    # 影響の大きい順。同点なら近い順、種類、IDの順
    result.impacts.sort(key=lambda i: (-i.score, i.depth, i.element_type, i.element_id))
    result.beyond_max_depth = sorted(beyond - set(paths))
    return result


def step_label(step: Step) -> str:
    """経路1区間の関係名。双方向の関係を逆向きにたどった場合は、元の関係名に「双方向」と付ける。"""
    if step.reversed:
        return f"{models.RELATION_TYPES.get(step.relation_type, step.relation_type)}・双方向"
    return models.RELATION_TARGET_LABELS.get(step.relation_type, step.relation_type)


def describe_path(graph: nx.MultiDiGraph, item: ImpactItem) -> str:
    """影響の理由を人が読める文にする。例：勤怠管理業務 → 人事部（担当）"""
    parts = [graph.nodes[item.path[0].from_id]["name"]]
    for step in item.path:
        parts.append(f"{graph.nodes[step.to_id]['name']}（{step_label(step)}）")
    return " → ".join(parts)
