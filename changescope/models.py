"""共通データモデルの定義。

業種ごとに専用の表は作らず、「要素（ノード）」と「依存関係（エッジ）」の2種類だけで
組織・業務・システムを表現する。ここでは、CSVの列と区分値（決められた選択肢）を定義する。
"""

# 要素の種類（キー＝CSVに書く値、値＝画面表示用の日本語）
ELEMENT_TYPES = {
    "process": "業務プロセス",
    "system": "情報システム",
    "department": "部門",
    "role": "担当者・役割",
    "data": "データ",
    "document": "帳票",
    "external_service": "外部サービス",
    "rule": "社内規程・ルール",
}

# 依存関係の種類。向きは常に「from が変わると to に影響しうる」
RELATION_TYPES = {
    "provides_data": "データを提供する",
    "uses": "利用する",
    "integrates_with": "システム連携する",
    "performs": "業務を担当する",
    "approves": "承認する",
    "governed_by": "規程に従う",
    "produces": "帳票を作成する",
    "depends_on": "その他の依存",
}

# 経路の表示用：「from → to（ここ）」の形で、to が from から見て何にあたるかを表す
RELATION_TARGET_LABELS = {
    "provides_data": "提供データ・提供先",
    "uses": "利用先",
    "integrates_with": "連携先",
    "performs": "担当",
    "approves": "承認者",
    "governed_by": "準拠する規程",
    "produces": "作成する帳票",
    "depends_on": "依存先",
}

# 影響の伝わり方
DIRECTIONS = {
    "one_way": "一方向",
    "both": "双方向",
}

# 依存関係の確認状態
STATUSES = {
    "confirmed": "確認済",
    "unconfirmed": "未確認",
    "assumed": "推定",
}

# 要素CSVの列
ELEMENT_REQUIRED_COLUMNS = ["element_id", "name", "element_type"]
ELEMENT_OPTIONAL_COLUMNS = ["description", "owner", "aliases"]

# 依存関係CSVの列
DEPENDENCY_REQUIRED_COLUMNS = [
    "dependency_id",
    "from_id",
    "to_id",
    "relation_type",
    "direction",
    "evidence",
    "status",
]
DEPENDENCY_OPTIONAL_COLUMNS = ["note"]

# Excelテンプレートで使う日本語の列名（CSVの列名 → Excelの見出し）
ELEMENT_HEADERS_JA = {
    "element_id": "要素ID",
    "name": "名前",
    "element_type": "種類",
    "description": "説明",
    "owner": "責任部門・担当（要素ID）",
    "aliases": "別名（;区切り）",
}
DEPENDENCY_HEADERS_JA = {
    "dependency_id": "依存関係ID",
    "from_id": "影響元の要素ID",
    "to_id": "影響先の要素ID",
    "relation_type": "関係の種類",
    "direction": "影響の向き",
    "evidence": "根拠（資料名・ヒアリング等）",
    "status": "確認状態",
    "note": "補足",
}

# 利用者が追加できる選択肢（種類・関係の種類）の最大文字数。追加した値は、日本語の名前のまま値として使う
MAX_CUSTOM_CHOICE_LENGTH = 20


def element_type_label(code: str) -> str:
    """種類の表示名。利用者が追加した種類は、その名前のまま表示する。"""
    return ELEMENT_TYPES.get(code, code)


def relation_type_label(code: str) -> str:
    """関係の種類の表示名。利用者が追加した関係は、その名前のまま表示する。"""
    return RELATION_TYPES.get(code, code)


# 区分値の列と、その選択肢（Excelでは日本語で選び、読み込み時にCSVの値へ変換する）
ELEMENT_CHOICE_COLUMNS = {"element_type": ELEMENT_TYPES}
DEPENDENCY_CHOICE_COLUMNS = {"relation_type": RELATION_TYPES, "direction": DIRECTIONS, "status": STATUSES}
