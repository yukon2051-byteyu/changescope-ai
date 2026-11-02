"""確認漏れを見つけるAI（ChangeScope の中核）。

「変更によって何が起きるか」だけでなく、「変更前に何を確認していないか」を見つけ、
誰に・何を聞けばよいかまで具体的に示す。

AIには登録データそのものではなく、Pythonで分析した結果（影響・経路・確認状態・根拠・関係者・見落としチェック）を、
つながりの番号つきで渡す。AIの回答はそのまま使わず、Pythonで次を確かめる。
- 根拠に挙げたつながりの番号が実在するか → 実在すれば「登録情報にもとづく」、なければ「AIの推測」
- 確認先が登録された部門・担当者か → なければ「未登録の部門候補」
- 費用・期間の数字が入っていないか → 入っていれば「要見積もり」に置き換える（数字を作らせない）
- 文章にD番号が書かれていないか → 画面ではIDを見せないため、つながりの名前（「A → B」）に置き換える
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from changescope import models
from changescope.ai_client import AIClient, wrap_user_input
from changescope.gaps import Finding
from changescope.graph_engine import ImpactItem, ImpactResult, Step, step_label
from changescope.insights import department_of
from changescope.next_actions import find_uncertain_links
from changescope.stakeholders import PERSON_TYPES, Stakeholder

FEATURE = "確認漏れ"
VIEWPOINTS = ["コスト", "契約", "業務手順", "システム", "データ", "セキュリティ", "規程・ルール", "内部統制", "教育・周知", "スケジュール"]
IMPORTANCE = ["高", "中", "低"]
REGISTERED = "登録情報にもとづく"
GUESS = "AIの推測"
UNREGISTERED_CONTACT = "未登録の部門候補"
ESTIMATE = "要見積もり"
# 事前にAIで生成したサンプル結果（4シナリオ）。料金なしで見られる
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample" / "ai_results"

# 費用・期間の数字（AIに作らせない）。「3段階」のような、費用・期間でない数字は対象外
_MONEY_OR_PERIOD = re.compile(
    r"(約|およそ|最大|最低|少なくとも)?[0-9０-９][0-9０-９,，.．]*\s*"
    r"(億円|万円|千円|円|ドル|人日|人月|日間|週間|か月|ヶ月|カ月|ヵ月|箇月|年間|時間)"
)
# 文章中のつながりの番号。かっこの中が番号だけなら、かっこごと消す
_ID = r"D-\d+"
_SEP = r"\s*[、,，・]\s*"
_PAREN_IDS_ONLY = re.compile(rf"[（(]\s*{_ID}(?:{_SEP}{_ID})*\s*[）)]")
_PAREN_IDS_LEAD = re.compile(rf"(?<=[（(])\s*{_ID}(?:{_SEP}{_ID})*{_SEP}")
_BARE_ID = re.compile(_ID)


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


SCHEMA = _object({
    "findings": _array(_object({
        "title": {"type": "string", "description": "確認していないことを一言で（例：給与計算システムとの連携が未確認）"},
        "detail": {"type": "string", "description": "なぜ確認が必要か。確認しないと何が起きうるか"},
        "viewpoint": {"type": "string", "enum": VIEWPOINTS},
        "importance": {"type": "string", "enum": IMPORTANCE},
        "contact": {"type": "string", "description": "確認先の部門・担当者（登録されている名前を優先する）"},
        "question": {"type": "string", "description": "確認先にそのまま聞ける質問文"},
        "evidence_ids": _array({"type": "string", "description": "根拠にしたつながりの番号（例：D-006）。なければ空"}),
    })),
    "department_points": _array(_object({
        "department": {"type": "string"},
        "points": _array(_object({"viewpoint": {"type": "string", "enum": VIEWPOINTS}, "content": {"type": "string"}})),
    })),
    "risks": _array(_object({
        "scenario": {"type": "string", "description": "起こりうるトラブル"},
        "condition": {"type": "string", "description": "どんな条件で起きるか"},
        "spread_to": {"type": "string", "description": "どこに影響が広がるか"},
        "prevention": {"type": "string", "description": "予防策"},
    })),
    "hidden_costs": _array(_object({
        "item": {"type": "string"},
        "detail": {"type": "string", "description": "なぜ見落としやすいか。金額は書かない"},
    })),
    "approach": _array(_object({"step": {"type": "string"}, "detail": {"type": "string"}})),
    # 「必ず挙げる」と指示しても0件で返すことがあったため、1件以上を形で必須にする（APIが使える値は0か1だけ）
    "unregistered": {**_array(_object({
        "name": {"type": "string", "description": "登録データにないが、関係しそうな要素"},
        "element_type": {"type": "string", "enum": list(models.ELEMENT_TYPES.values())},
        "reason": {"type": "string"},
    })), "minItems": 1},
})

SYSTEM = (
    "役割：変更を実施する前に、まだ確認していないこと（確認漏れ）を見つけ、誰に何を聞けばよいかを具体的に示すこと。\n"
    "経験豊富なITコンサルタントがヒアリングで指摘するように、次の点に注意して回答してください。\n"
    "- findings（確認漏れ）を最も重視し、6〜10件挙げる。登録データの「推定」「未確認」のつながり、"
    "変更の種類から当然確認すべきなのにデータにないこと（データ移行、連携、権限、規程、契約、教育、切り戻しなど）を優先する。\n"
    "- 変更内容と関係が薄いつながり（経路の先にあるだけで、今回の変更で何も変わらないもの）は挙げない。\n"
    "- 確認先は、登録された部門・担当者の名前を使う。該当がなければ、部門の候補を書く。\n"
    "- question は、確認先にそのまま聞ける具体的な質問文にする（例：「新しい勤怠システムから給与計算システムへの連携は、"
    "今と同じCSV形式で可能ですか？」）。\n"
    "- 登録データのつながりを根拠にした指摘は、evidence_ids にそのつながりの番号（D-で始まる）を入れる。"
    "推測にもとづく指摘は evidence_ids を空にする。存在しない番号を書かない。"
    "番号は evidence_ids にだけ書き、文章（title・detail・question など）には書かない。\n"
    "- department_points は関係する部門ごとに、risks は3〜5件、hidden_costs は3〜5件（金額は書かない）、"
    "approach は3〜5段階、unregistered は必ず2件以上（最大5件）挙げる。登録データにない業務・システム・外部サービス・規程・担当者を、変更の種類から推測する。\n"
    "- すべて日本語で、簡潔に書く。"
)


@dataclass
class OversightFinding:
    title: str
    detail: str
    viewpoint: str
    importance: str
    contact: str
    contact_registered: bool
    question: str
    basis: str  # REGISTERED または GUESS
    evidence: list[str] = field(default_factory=list)  # 根拠のつながりの説明（実在したもの）


@dataclass
class OversightReport:
    findings: list[OversightFinding]
    department_points: list[dict]
    risks: list[dict]
    hidden_costs: list[dict]
    approach: list[dict]
    unregistered: list[dict]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _step_text(graph: nx.MultiDiGraph, step: Step) -> str:
    text = (f"{step.dependency_id}: {graph.nodes[step.from_id]['name']} → {graph.nodes[step.to_id]['name']}"
            f"（{step_label(step)}／{models.STATUSES.get(step.status, step.status)}")
    if step.evidence:
        text += f"／根拠：{step.evidence}"
    if step.note:
        text += f"／補足：{step.note}"
    return text + "）"


def collect_steps(result: ImpactResult) -> dict[str, Step]:
    """影響の経路に含まれるつながりを、番号ごとに集める（AIが根拠として挙げてよい番号の一覧）。"""
    steps: dict[str, Step] = {}
    for item in result.impacts:
        for step in item.path:
            steps.setdefault(step.dependency_id, step)
    return steps


def build_prompt(graph: nx.MultiDiGraph, result: ImpactResult, change_text: str,
                 stakeholders: list[Stakeholder], gaps: list[Finding], hidden: list[ImpactItem]) -> str:
    """AIに渡す材料。登録データそのものではなく、分析結果を番号つきで渡す。"""
    targets = "、".join(f"{graph.nodes[t]['name']}（{models.element_type_label(graph.nodes[t]['element_type'])}）"
                       for t in result.targets if t in graph)
    lines = ["## 変更内容（利用者の入力）", wrap_user_input(change_text), "", f"## 変更対象\n{targets}", "",
             "## 影響が伝わるつながり（番号つき。根拠として挙げてよいのはこの番号だけ）"]
    lines += [f"- {_step_text(graph, s)}" for s in collect_steps(result).values()]
    lines += ["", "## 影響を受ける要素（影響の大きい順）"]
    for item in result.impacts[:30]:
        department = department_of(graph, item.element_id)
        owner = graph.nodes[department]["name"] if department else "未登録"
        lines.append(f"- {item.name}（{models.element_type_label(item.element_type)}／{item.level == 'direct' and '直接' or '間接'}"
                     f"／確認状態：{models.STATUSES.get(item.path_status, item.path_status)}／所属部門：{owner}）")
    lines += ["", "## 登録されている部門・担当者（確認先の候補）"]
    people = [n for n, d in graph.nodes(data=True) if d["element_type"] in PERSON_TYPES]
    lines += [f"- {graph.nodes[p]['name']}" for p in people] or ["- （登録なし）"]
    lines += ["", "## 影響を受ける関係者（プログラムが判定）"]
    lines += [f"- {s.name}：" + "／".join(r.text for r in s.reasons[:3]) for s in stakeholders] or ["- なし"]
    links = find_uncertain_links(graph, result)
    lines += ["", "## まだ確認されていないつながり（推定・未確認）"]
    lines += [f"- {l.dependency_id}: {l.text}（{models.STATUSES[l.status]}）" for l in links] or ["- なし"]
    lines += ["", "## 見落としやすい影響（別の部門に、2段以上先で伝わる）"]
    lines += [f"- {i.name}" for i in hidden] or ["- なし"]
    lines += ["", "## プログラムが見つけた確認すべき観点"]
    lines += [f"- {g.title}：{'、'.join(g.items) if g.items else ''}" for g in gaps] or ["- なし"]
    return "\n".join(lines)


def scrub_numbers(text: str) -> str:
    """費用・期間の数字を「要見積もり」に置き換える（AIに数値を作らせない）。"""
    return _MONEY_OR_PERIOD.sub(ESTIMATE, text)


def link_names(graph: nx.MultiDiGraph) -> dict[str, str]:
    """つながりの番号 → 「影響元 → 影響先」（逆向きに追加した線は除く）。"""
    return {d["dependency_id"]: f"「{graph.nodes[u]['name']} → {graph.nodes[v]['name']}」"
            for u, v, d in graph.edges(data=True) if not d.get("reversed")}


def replace_ids(text: str, names: dict[str, str]) -> str:
    """文章中のD番号を、つながりの名前に置き換える（存在しない番号は消す）。"""
    text = _PAREN_IDS_LEAD.sub("", _PAREN_IDS_ONLY.sub("", text))
    return _BARE_ID.sub(lambda m: names.get(m.group(), ""), text)


def validate(raw: dict, graph: nx.MultiDiGraph, result: ImpactResult) -> OversightReport:
    """AIの回答を確かめて、表示できる形にする。"""
    steps = collect_steps(result)
    names = link_names(graph)

    def clean(text) -> str:
        return scrub_numbers(replace_ids(_str(text), names))

    person_names = {d["name"] for _, d in graph.nodes(data=True) if d["element_type"] in PERSON_TYPES}
    element_names = {d["name"] for _, d in graph.nodes(data=True)}

    findings = []
    for f in raw.get("findings", []):
        cited = [i for i in f.get("evidence_ids", []) if i in steps]  # 実在する番号だけ残す
        contact = _str(f.get("contact")).strip()
        findings.append(OversightFinding(
            title=clean(f.get("title")),
            detail=clean(f.get("detail")),
            viewpoint=f.get("viewpoint") if f.get("viewpoint") in VIEWPOINTS else "業務手順",
            importance=f.get("importance") if f.get("importance") in IMPORTANCE else "中",
            contact=contact,
            contact_registered=any(name in contact for name in person_names),
            question=clean(f.get("question")),
            basis=REGISTERED if cited else GUESS,
            evidence=[_step_text(graph, steps[i]) for i in cited],
        ))
    order = {v: i for i, v in enumerate(IMPORTANCE)}
    findings.sort(key=lambda f: (order[f.importance], f.basis != REGISTERED))

    def scrub_all(items: list[dict]) -> list[dict]:
        return [{k: clean(v) if isinstance(v, str) else v for k, v in item.items()} for item in items]

    department_points = [
        {"department": _str(d.get("department")),
         "registered": _str(d.get("department")) in person_names,
         "points": scrub_all(d.get("points", []))}
        for d in raw.get("department_points", [])
    ]
    # すでに登録されている要素は「未登録の影響」から外す
    unregistered = [u for u in scrub_all(raw.get("unregistered", [])) if u.get("name") not in element_names]
    return OversightReport(
        findings=findings,
        department_points=department_points,
        risks=scrub_all(raw.get("risks", [])),
        hidden_costs=scrub_all(raw.get("hidden_costs", [])),
        approach=scrub_all(raw.get("approach", [])),
        unregistered=unregistered,
    )


def find_oversights(client: AIClient, graph: nx.MultiDiGraph, result: ImpactResult, change_text: str,
                    stakeholders: list[Stakeholder], gaps: list[Finding], hidden: list[ImpactItem],
                    user_key: str | None) -> tuple[OversightReport | None, str]:
    """AIで確認漏れを調べる。失敗したときは (None, 利用者に見せる説明) を返す（例外は出さない）。"""
    prompt = build_prompt(graph, result, change_text, stakeholders, gaps, hidden)
    answer = client.call_json(FEATURE, SYSTEM, prompt, SCHEMA, user_key, change_text)
    if not answer.ok:
        return None, answer.message
    report = validate(answer.data, graph, result)
    report.input_tokens, report.output_tokens, report.cost_usd = (
        answer.input_tokens, answer.output_tokens, answer.cost_usd)
    return report, ""


@dataclass
class SampleReport:
    report: OversightReport
    model: str
    generated_on: str


def load_sample_report(scenario_id: str) -> SampleReport | None:
    """事前に生成したサンプル結果を読み込む。なければ None。"""
    path = SAMPLE_DIR / f"oversight_{scenario_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = dict(data["report"])
    raw["findings"] = [OversightFinding(**f) for f in raw["findings"]]
    return SampleReport(OversightReport(**raw), data["model"], data["generated_on"])
