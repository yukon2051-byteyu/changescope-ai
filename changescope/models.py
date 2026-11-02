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

# 依存関係の種類。向きは常に「from が変わると to に影響しうる」（影響が伝わる向き）。
# 名前は、矢印に沿って「影響元は 影響先に（を）〜」と読めるようにする（例：データは業務に利用される）
RELATION_TYPES = {
    "provides_data": "データを提供する",
    "uses": "利用される",
    "integrates_with": "システム連携する",
    "performs": "担当される",
    "approves": "承認を受ける",
    "governed_by": "規程に従う",
    "produces": "帳票を作成する",
    "depends_on": "土台になる",
}
# 以前の名前（矢印と逆の意味に読めたため 2026-11-02 に変更）。古いExcelも読み込めるようにする
LEGACY_RELATION_LABELS = {
    "利用する": "uses",
    "業務を担当する": "performs",
    "承認する": "approves",
    "その他の依存": "depends_on",
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
# 要素IDは任意（空欄なら自動で付ける）。名前は重複できず、依存関係・責任部門は名前でもIDでも指定できる
ELEMENT_REQUIRED_COLUMNS = ["name", "element_type"]
ELEMENT_OPTIONAL_COLUMNS = ["element_id", "description", "owner", "aliases"]

# 依存関係CSVの列
# 依存関係IDは任意（空欄なら自動で付ける）。影響元・影響先は、要素の名前でもIDでも指定できる
DEPENDENCY_REQUIRED_COLUMNS = [
    "from_id",
    "to_id",
    "relation_type",
    "direction",
    "evidence",
    "status",
]
DEPENDENCY_OPTIONAL_COLUMNS = ["dependency_id", "note"]

# Excelテンプレートで使う日本語の列名（CSVの列名 → Excelの見出し）
ELEMENT_HEADERS_JA = {
    "element_id": "要素ID",
    "name": "名前",
    "element_type": "種類",
    "description": "説明",
    "owner": "責任部門・担当",
    "aliases": "別名（;区切り）",
}
DEPENDENCY_HEADERS_JA = {
    "dependency_id": "依存関係ID",
    "from_id": "影響元",
    "to_id": "影響先",
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


# 以前のテンプレートの見出し（古いExcelも読み込めるようにする）
LEGACY_HEADERS_JA = {
    "責任部門・担当（要素ID）": "owner",
    "影響元の要素ID": "from_id",
    "影響先の要素ID": "to_id",
}

# 区分値の列と、その選択肢（Excelでは日本語で選び、読み込み時にCSVの値へ変換する）
ELEMENT_CHOICE_COLUMNS = {"element_type": ELEMENT_TYPES}
DEPENDENCY_CHOICE_COLUMNS = {"relation_type": RELATION_TYPES, "direction": DIRECTIONS, "status": STATUSES}
