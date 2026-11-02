"""図で入力する画面の計算部分（画面の部品には依存しない。テストできるよう、ここにまとめる）。

図は「いま見ている要素」を真ん中に置き、左に影響元（1段）、右に影響先（2段先まで）を並べる。
線は左から右へ流れるので、「システム → データ → 部門」のような流れをそのまま読める。

要素・依存関係は、読み込んだデータと同じ列名の辞書のリストで扱う。
- 要素：element_id, name, element_type, owner など
- 依存関係：dependency_id, from_id, to_id, relation_type, direction, evidence, status, note
"""

from __future__ import annotations

from dataclasses import dataclass, field

from changescope import models

DATA, RULE = "data", "rule"
PEOPLE = ("department", "role")
MAX_ROWS = 6  # 1列に並べる箱の上限（超えたら「ほか〇件」にまとめる）

# 確認状態の不確かさの順（大きいほど不確か）
STATUS_ORDER = {"confirmed": 0, "assumed": 1, "unconfirmed": 2}

# 関係の種類の意味（選ぶときの手がかり）
RELATION_HELP = {
    "provides_data": "左がデータを作り、右に渡す（例：勤怠管理システム → 勤怠実績データ）",
    "uses": "左を、右が使う・受け取る（例：勤怠実績データ → 経理部）",
    "integrates_with": "左のシステムから、右のシステムへデータが流れる",
    "performs": "左の業務を、右の部門・担当者が受け持つ",
    "approves": "左の業務は、右の人の承認が必要",
    "governed_by": "左は、右の規程・ルールに従う",
    "produces": "左のシステムが、右の帳票を作る",
    "depends_on": "左が、右の土台になっている（上のどれにも当てはまらないとき）",
}

# 選んだ関係を「左は、右に〜」の文章にして、登録する前に向きと意味を読んで確かめられるようにする
READING = {
    "provides_data": "「{a}」は、「{b}」を提供する（作る・渡す）",
    "uses": "「{a}」は、「{b}」に利用される（使われる・受け取られる）",
    "integrates_with": "「{a}」は、「{b}」とシステム連携する（「{a}」から「{b}」へデータが流れる）",
    "performs": "「{a}」は、「{b}」に担当される",
    "approves": "「{a}」は、「{b}」の承認を受ける",
    "governed_by": "「{a}」は、「{b}」に従う",
    "produces": "「{a}」は、「{b}」を作成する",
    "depends_on": "「{a}」は、「{b}」の土台になる",
}

STATUS_HELP = {
    "confirmed": "資料や担当者に確かめた",
    "assumed": "たぶんそうだが、まだ確かめていない",
    "unconfirmed": "あるかどうか分からない",
}


@dataclass(frozen=True)
class Question:
    """ヒアリングの質問。答えを「どちら側に」「どの種類で」「どの関係で」つなぐかを持つ。"""
    text: str
    side: str  # "in"＝影響元として追加、"out"＝影響先として追加
    element_type: str
    relation_type: str


# 見ている要素の種類ごとに、聞くべきこと（追加の画面に例として出す。答えていないものは聞き漏れの目印）
QUESTIONS = {
    "system": [Question("このシステムが作るデータは？", "out", DATA, "provides_data"),
               Question("このシステムを使う業務は？", "out", "process", "uses"),
               Question("連携しているシステムは？", "out", "system", "integrates_with"),
               Question("このシステムで作る帳票は？", "out", "document", "produces")],
    "external_service": [Question("このサービスを使う業務は？", "out", "process", "uses"),
                         Question("このサービスに渡すデータは？", "in", DATA, "uses")],
    DATA: [Question("このデータを使う業務・部門は？", "out", "process", "uses"),
           Question("このデータを作るシステムは？", "in", "system", "provides_data"),
           Question("このデータが従う規程は？", "out", RULE, "governed_by")],
    "document": [Question("この帳票を作るシステムは？", "in", "system", "produces"),
                 Question("この帳票を使う業務は？", "out", "process", "uses")],
    "process": [Question("この業務の担当は？", "out", "department", "performs"),
                Question("この業務の承認者は？", "out", "role", "approves"),
                Question("この業務で使うデータは？", "in", DATA, "uses"),
                Question("この業務が従う規程は？", "out", RULE, "governed_by")],
    "department": [Question("この部門が担当する業務は？", "in", "process", "performs")],
    "role": [Question("この担当者が担当する業務は？", "in", "process", "performs"),
             Question("この担当者が作るデータは？", "out", DATA, "provides_data")],
    RULE: [Question("この規程に従う業務は？", "in", "process", "governed_by")],
}

# チュートリアルの2つ目の要素の例（1つ目の種類ごと）：(考えるきっかけ, 例, 種類)
NEXT_EXAMPLE = {
    "system": ("このシステムが作るデータ", "勤怠実績データ", DATA),
    "external_service": ("このサービスを使う業務", "給与振込業務", "process"),
    DATA: ("このデータを使う業務", "月次給与計算", "process"),
    "document": ("この帳票を使う業務", "月次報告", "process"),
    "process": ("この業務を担当する部門", "人事部", "department"),
    "department": ("この部門が使うデータ", "勤怠実績データ", DATA),
    "role": ("この担当者が作るデータ", "勤怠修正申請データ", DATA),
    RULE: ("この規程に従う業務", "勤怠管理業務", "process"),
}


def default_relation(source_type: str, target_type: str) -> str:
    """関係の種類を自動で選ぶとき、2つの要素の種類から、いちばんありそうなものを返す。"""
    if target_type == RULE:
        return "governed_by"
    if source_type == "process" and target_type in PEOPLE:
        return "performs"
    if source_type in ("system", "external_service", "role") and target_type == DATA:
        return "provides_data"
    if source_type == "system" and target_type == "document":
        return "produces"
    if source_type in ("system", "external_service") and target_type in ("system", "external_service"):
        return "integrates_with"
    # データ・帳票・システムを、業務・部門・担当者が使う（例：勤怠実績データ → 経理部）
    if source_type in (DATA, "document", "system", "external_service") and target_type in ("process", *PEOPLE):
        return "uses"
    return "depends_on"  # どれにも当てはまらないとき


def reading(source_name: str, target_name: str, relation_type: str) -> str:
    """選んだ関係を文章にする（例：「勤怠実績データ」は、「経理部」に利用される）。"""
    template = READING.get(relation_type)
    if template is None:  # 利用者が追加した関係の種類
        return f"「{source_name}」→「{target_name}」（{models.relation_type_label(relation_type)}）"
    return template.format(a=source_name, b=target_name)


def relation_option(relation_type: str) -> str:
    """選択肢の表示：関係の名前と意味を並べる。"""
    label = models.relation_type_label(relation_type)
    help_text = RELATION_HELP.get(relation_type)
    return f"{label}　…　{help_text}" if help_text else label


def weakest(*statuses: str) -> str:
    """いちばん不確かな確認状態（経路の確認状態と同じ考え方）。"""
    return max(statuses, key=lambda s: STATUS_ORDER.get(s, 2))


def view_links(elements: list[dict], links: list[dict], center: str, collapse_data: bool) -> list[dict]:
    """図に描くつながり。collapse_data なら、データの箱を線の上の名前にまとめる。

    登録の内容は変えず、描き方だけを変える。例：
    勤怠管理システム → 勤怠実績データ → 経理部  を  勤怠管理システム ─勤怠実績データ→ 経理部  と描く。
    - まとめるのは、作る側と使う側の両方があるデータだけ（片方しかないデータは箱のまま）
    - いま見ている要素がデータのときは、そのデータはまとめない
    - データと規程のつながりは、まとめた表示では描かない（線にすると「システムが規程に従う」と誤って読めるため）
    まとめた線は via にデータの要素IDを持ち、確認状態は2本のうち不確かな方にする。
    """
    if not collapse_data:
        return list(links)
    types = {e["element_id"]: e["element_type"] for e in elements}

    def ins(d):
        return [l for l in links if l["to_id"] == d and types.get(l["from_id"]) != RULE]

    def outs(d):
        return [l for l in links if l["from_id"] == d and types.get(l["to_id"]) != RULE]

    collapsible = {e for e, t in types.items() if t == DATA and e != center and ins(e) and outs(e)}
    result = [l for l in links if l["from_id"] not in collapsible and l["to_id"] not in collapsible]
    names = {e["element_id"]: e["name"] for e in elements}
    for d in sorted(collapsible):
        for a in ins(d):
            for b in outs(d):
                if a["from_id"] == b["to_id"]:
                    continue
                result.append({
                    "dependency_id": f"via:{d}:{a['dependency_id']}:{b['dependency_id']}",
                    "from_id": a["from_id"], "to_id": b["to_id"], "relation_type": names[d],
                    "direction": "one_way", "status": weakest(a["status"], b["status"]), "via": d,
                })
    return result


@dataclass
class Placement:
    element_id: str
    column: str  # "left"（影響元）, "center", "first"（1段目の影響先）, "second"（2段目）
    row: int
    link: dict | None  # この箱を置く理由になったつながり（真ん中は None）


@dataclass
class Layout:
    placements: list[Placement]
    edges: list[dict]  # 図に出ている箱どうしのつながり（すべて線で描く）
    hidden: dict[str, int] = field(default_factory=dict)  # 列ごとの「ほか〇件」の件数
    rows: int = 1  # いちばん多い列の行数（「ほか〇件」の箱を含む）


def layout(elements: list[dict], links: list[dict], center: str, collapse_data: bool = False,
           max_rows: int = MAX_ROWS) -> Layout:
    """いま見ている要素を中心にした図の配置を計算する。

    - 右の1段目：真ん中から出るつながりの相手。2段目：1段目の相手から出るつながりの相手
    - 左：真ん中に入るつながりの相手（右に出ている要素は除く）
    - 各列では、推定・未確認のつながりの相手を先に並べる（確認すべきものを上に）
    - 1列が max_rows を超えたら、最後の1行を「ほか〇件」にまとめる
    """
    drawn = view_links(elements, links, center, collapse_data)
    first: dict[str, dict] = {}
    for link in drawn:
        if link["from_id"] == center:
            first.setdefault(link["to_id"], link)
    second: dict[str, dict] = {}
    for element_id in first:
        for link in drawn:
            target = link["to_id"]
            if link["from_id"] == element_id and target != center and target not in first:
                second.setdefault(target, link)
    left: dict[str, dict] = {}
    for link in drawn:
        source = link["from_id"]
        if link["to_id"] == center and source not in first and source not in second:
            left.setdefault(source, link)

    placements = [Placement(center, "center", 0, None)]
    hidden: dict[str, int] = {}
    rows = 1
    for column, items in (("left", left), ("first", first), ("second", second)):
        ordered = sorted(items.items(), key=lambda kv: -STATUS_ORDER.get(kv[1]["status"], 2))
        if len(ordered) > max_rows:
            hidden[column] = len(ordered) - (max_rows - 1)
            ordered = ordered[:max_rows - 1]
        placements += [Placement(e, column, i, link) for i, (e, link) in enumerate(ordered)]
        rows = max(rows, len(ordered) + (1 if column in hidden else 0))
    placed = {p.element_id for p in placements}
    edges = [l for l in drawn if l["from_id"] in placed and l["to_id"] in placed]
    return Layout(placements, edges, hidden, rows)


def update_trail(trail: list[str], element_id: str) -> list[str]:
    """たどった順。すでに通った要素に戻ったときは、そこまでに切り詰める（行き来で長くならないように）。"""
    if element_id in trail:
        return trail[:trail.index(element_id) + 1]
    return [*trail, element_id]


def isolated(elements: list[dict], links: list[dict]) -> list[str]:
    """線が1本もつながっていない要素（登録漏れの目印）。"""
    connected = {l["from_id"] for l in links} | {l["to_id"] for l in links}
    return [e["element_id"] for e in elements if e["element_id"] not in connected]


def is_answered(question: Question, center: str, links: list[dict]) -> bool:
    """ヒアリングの質問に、すでに答えたか（同じ側に、同じ関係の種類のつながりがあるか）。"""
    if question.side == "out":
        return any(l["from_id"] == center and l["relation_type"] == question.relation_type for l in links)
    return any(l["to_id"] == center and l["relation_type"] == question.relation_type for l in links)


def direct_links_to_replace(links: list[dict], center: str, source: str, target: str) -> list[dict]:
    """source を経由する線（source → target）を引いたとき、置き換え候補になる直接の線（center → target）。"""
    if source == center:
        return []
    return [l for l in links if l["from_id"] == center and l["to_id"] == target]
