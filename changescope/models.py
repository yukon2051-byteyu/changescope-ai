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

# 影響の伝わり方
DIRECTIONS = {
    "one_way": "一方向（from→to）",
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
