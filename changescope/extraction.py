"""資料から依存関係の候補を作るAI（3つの柱の①「依存関係を作る」）。

業務フロー説明書・システム一覧・会議メモなどの文章から、AIが要素とつながりの「候補」を作る。
登録するかどうかは人が決める（AIが作った候補は、そのまま登録しない）。

AIの回答はそのまま使わず、Pythonで次を確かめる。
- 根拠の文が、貼り付けた資料に本当に書いてあるか → なければ「根拠が見つからない」として、最初は選ばない
- すでに登録されている要素と同じ名前か → 同じなら新しく作らず、登録済みの要素につなぐ
- つながりの両端が、候補または登録済みの要素か → どちらでもなければ外す
- 確認状態 → AIが作ったつながりは必ず「推定」にする（人が確かめてから「確認済」に直す）
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from changescope import models
from changescope.ai_client import AIClient, wrap_user_input
from changescope.diagram import RELATION_HELP

FEATURE = "資料から作る"
MAX_QUOTE = 80  # 根拠として抜き出す文の最大文字数（Excelのセルに入れるため短くする）
EVIDENCE_PREFIX = "資料から抽出"

_TYPE_CODE = {label: code for code, label in models.ELEMENT_TYPES.items()}
_RELATION_CODE = {label: code for code, label in models.RELATION_TYPES.items()}


def _str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


SCHEMA = _object({
    "elements": _array(_object({
        "name": {"type": "string", "description": "要素の名前（資料の書き方に合わせ、短く）"},
        "element_type": {"type": "string", "enum": list(models.ELEMENT_TYPES.values())},
        "quote": {"type": "string", "description": f"根拠にした資料の文。資料から一字一句そのまま、{MAX_QUOTE}文字以内で抜き出す"},
    })),
    "links": _array(_object({
        "source": {"type": "string", "description": "影響元の要素の名前（elements か、登録済みの要素の名前）"},
        "target": {"type": "string", "description": "影響先の要素の名前（elements か、登録済みの要素の名前）"},
        "relation_type": {"type": "string", "enum": list(models.RELATION_TYPES.values())},
        "quote": {"type": "string", "description": f"根拠にした資料の文。資料から一字一句そのまま、{MAX_QUOTE}文字以内で抜き出す"},
    })),
    "unclear": _array(_object({
        "point": {"type": "string", "description": "資料からは分からず、確認が必要なこと"},
        "ask": {"type": "string", "description": "誰に確認するとよいか（資料に出てくる部門・担当者の名前を優先）"},
    })),
})

SYSTEM = (
    "役割：業務の資料から、変更の影響を調べるための「要素」と「つながり」の候補を作ること。\n"
    "- 要素は、業務プロセス・情報システム・部門・担当者・役割・データ・帳票・外部サービス・社内規程・ルールのどれか。"
    "資料に出てくるものだけを挙げ、資料にないものを作らない。\n"
    "- つながりの向きは「影響元が変わると、影響先に対応や確認が必要になる」向き。"
    "例：勤怠管理システム → 勤怠実績データ（データを提供する）、勤怠実績データ → 月次給与計算（利用される）、"
    "月次給与計算 → 人事部（担当される）。\n"
    "- 関係の種類の意味：" + "／".join(f"{models.RELATION_TYPES[c]}＝{h}" for c, h in RELATION_HELP.items()) + "\n"
    "- quote には、根拠にした資料の文を一字一句そのまま抜き出す（言い換えない。要約しない）。\n"
    "- 登録済みの要素と同じものは、登録済みの名前をそのまま使う。\n"
    "- 資料からは分からないが、影響の調査に必要なこと（連携の有無、担当部門、データの受け渡し方法など）は unclear に挙げる。\n"
    "- すべて日本語で書く。"
)


@dataclass
class ElementCandidate:
    name: str
    element_type: str  # 種類のコード（例：system）
    quote: str
    found: bool  # 根拠の文が資料に書いてあるか
    existing_id: str | None = None  # すでに登録されている要素なら、その要素ID


@dataclass
class LinkCandidate:
    source: str  # 要素の名前
    target: str
    relation_type: str  # 関係の種類のコード（例：uses）
    quote: str
    found: bool
    duplicate: bool = False  # すでに同じ向き・同じ種類で登録されている


@dataclass
class ExtractionResult:
    elements: list[ElementCandidate]
    links: list[LinkCandidate]
    unclear: list[dict]
    dropped_links: int = 0  # 両端が分からない・自分自身へのつながりなどで外した数
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _normalize(text: str) -> str:
    """照合のために、空白・改行・全角半角の空白を取り除く（資料の改行位置が違っても照合できるように）。"""
    return re.sub(r"\s+", "", text)


def quote_found(quote: str, document: str) -> bool:
    """根拠の文が、資料に本当に書いてあるか。"""
    q = _normalize(quote)
    return bool(q) and q in _normalize(document)


def build_prompt(document: str, source_name: str, existing: list[dict]) -> str:
    lines = [f"## 資料（{source_name or '名前なし'}）", wrap_user_input(document), "",
             "## 登録済みの要素（同じものは、この名前を使う）"]
    lines += [f"- {e['name']}（{models.element_type_label(e['element_type'])}）" for e in existing] or ["- なし"]
    return "\n".join(lines)


def validate(raw: dict, document: str, existing_elements: list[dict], existing_links: list[dict]) -> ExtractionResult:
    """AIの回答を確かめて、人が選べる候補の一覧にする。"""
    existing_by_name = {e["name"]: e["element_id"] for e in existing_elements}
    elements: list[ElementCandidate] = []
    seen: set[str] = set()
    for item in raw.get("elements", []):
        name = _str(item.get("name"))
        code = _TYPE_CODE.get(_str(item.get("element_type")))
        if not name or not code or name in seen:
            continue
        seen.add(name)
        quote = _str(item.get("quote"))[:MAX_QUOTE]
        elements.append(ElementCandidate(name, code, quote, quote_found(quote, document), existing_by_name.get(name)))

    known = seen | set(existing_by_name)
    id_to_name = {e["element_id"]: e["name"] for e in existing_elements}
    registered = {(id_to_name.get(l["from_id"]), id_to_name.get(l["to_id"]), l["relation_type"]) for l in existing_links}
    links: list[LinkCandidate] = []
    pairs: set[tuple[str, str, str]] = set()
    dropped = 0
    for item in raw.get("links", []):
        source, target = _str(item.get("source")), _str(item.get("target"))
        code = _RELATION_CODE.get(_str(item.get("relation_type")))
        key = (source, target, code)
        if source not in known or target not in known or source == target or not code or key in pairs:
            dropped += 1
            continue
        pairs.add(key)
        quote = _str(item.get("quote"))[:MAX_QUOTE]
        links.append(LinkCandidate(source, target, code, quote, quote_found(quote, document), key in registered))

    unclear = [{"point": _str(u.get("point")), "ask": _str(u.get("ask"))}
               for u in raw.get("unclear", []) if _str(u.get("point"))]
    return ExtractionResult(elements, links, unclear, dropped)


def extract(client: AIClient, document: str, source_name: str, existing_elements: list[dict],
            existing_links: list[dict], user_key: str | None) -> tuple[ExtractionResult | None, str]:
    """資料から候補を作る。失敗したときは (None, 利用者に見せる説明) を返す（例外は出さない）。"""
    prompt = build_prompt(document, source_name, existing_elements)
    answer = client.call_json(FEATURE, SYSTEM, prompt, SCHEMA, user_key, document,
                              max_chars=client.settings.max_document_chars)
    if not answer.ok:
        return None, answer.message
    result = validate(answer.data, document, existing_elements, existing_links)
    result.input_tokens, result.output_tokens, result.cost_usd = (
        answer.input_tokens, answer.output_tokens, answer.cost_usd)
    return result, ""


def apply_candidates(elements: list[dict], links: list[dict], chosen_elements: list[ElementCandidate],
                     chosen_links: list[LinkCandidate], source_name: str) -> tuple[list[dict], list[dict]]:
    """選ばれた候補を、要素・つながりの一覧に加えた新しい一覧を返す（もとの一覧は変えない）。

    - 登録済みの要素と同じ名前の候補は、新しく作らない
    - つながりの片方の端が、選ばれていない新しい要素なら、その要素も一緒に作る（つながりだけ浮かないように）
    - つながりの確認状態は「推定」。根拠は「資料から抽出（資料名）：抜き出した文」
    """
    new_elements = [dict(e) for e in elements]
    new_links = [dict(l) for l in links]
    name_to_id = {e["name"]: e["element_id"] for e in new_elements}
    candidates_by_name = {c.name: c for c in chosen_elements}

    def ensure(name: str, fallback_type: str = "process") -> str:
        if name not in name_to_id:
            element_type = candidates_by_name[name].element_type if name in candidates_by_name else fallback_type
            element_id = f"E-{uuid.uuid4().hex[:6].upper()}"
            new_elements.append({"element_id": element_id, "name": name, "element_type": element_type, "owner": ""})
            name_to_id[name] = element_id
        return name_to_id[name]

    for candidate in chosen_elements:
        ensure(candidate.name)
    label = f"{EVIDENCE_PREFIX}（{source_name}）" if source_name else EVIDENCE_PREFIX
    for candidate in chosen_links:
        if candidate.duplicate:
            continue
        new_links.append({
            "dependency_id": f"D-{uuid.uuid4().hex[:6].upper()}",
            "from_id": ensure(candidate.source), "to_id": ensure(candidate.target),
            "relation_type": candidate.relation_type, "direction": "one_way",
            "evidence": f"{label}：{candidate.quote}" if candidate.quote else label,
            "status": "assumed", "note": "",
        })
    return new_elements, new_links

