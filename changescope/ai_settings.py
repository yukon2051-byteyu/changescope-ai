"""AI分析の設定（ai_settings.toml）を読み込む。モデル名・単価・為替・上限は設定ファイルで変えられる。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "ai_settings.toml"


@dataclass(frozen=True)
class AISettings:
    model: str
    price_input_per_mtok_usd: float
    price_output_per_mtok_usd: float
    effort: str
    yen_per_usd: float
    max_input_chars: int
    max_document_chars: int
    max_output_tokens: int
    timeout_seconds: float
    monthly_budget_usd: float
    stop_ratio: float
    monthly_call_limit: int
    per_user_monthly_limit: int
    usage_db: str

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """トークン数から費用（ドル）を計算する。"""
        return (input_tokens * self.price_input_per_mtok_usd
                + output_tokens * self.price_output_per_mtok_usd) / 1_000_000

    def to_yen(self, usd: float) -> float:
        return usd * self.yen_per_usd


def model_label(model: str) -> str:
    """画面に出すモデル名（例：claude-sonnet-5-5 → Claude Sonnet 5.5）。"""
    parts = model.split("-")
    if len(parts) >= 3 and parts[0] == "claude":
        return f"Claude {parts[1].capitalize()} {'.'.join(parts[2:])}"
    return model


def load_settings(path: Path = SETTINGS_PATH) -> AISettings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    model, limits, storage = data["model"], data["limits"], data["storage"]
    return AISettings(
        model=model["name"],
        price_input_per_mtok_usd=float(model["price_input_per_mtok_usd"]),
        price_output_per_mtok_usd=float(model["price_output_per_mtok_usd"]),
        effort=model["effort"],
        yen_per_usd=float(model["yen_per_usd"]),
        max_input_chars=int(limits["max_input_chars"]),
        max_document_chars=int(limits["max_document_chars"]),
        max_output_tokens=int(limits["max_output_tokens"]),
        timeout_seconds=float(limits["timeout_seconds"]),
        monthly_budget_usd=float(limits["monthly_budget_usd"]),
        stop_ratio=float(limits["stop_ratio"]),
        monthly_call_limit=int(limits["monthly_call_limit"]),
        per_user_monthly_limit=int(limits["per_user_monthly_limit"]),
        usage_db=storage["usage_db"],
    )
