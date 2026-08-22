"""Fixtures partagées des tests AUREUS."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "user_data" / "strategies"

# Rend `aureus` et `AureusStrategy` importables sans installation,
# comme le fait Freqtrade avec le dossier strategies.
if str(STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGY_DIR))


@pytest.fixture
def valid_freqtrade_config() -> dict:
    """Config Freqtrade minimale mais valide pour AUREUS."""
    return {
        "dry_run": True,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "timeframe": "5m",
        "exchange": {
            "name": "okx",
            "pair_whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        },
        "aureus": {
            "risk_per_trade": "0.01",
            "max_leverage": "5",
            "daily_max_loss_r": "2",
            "daily_max_drawdown": "0.03",
            "cooldown_candles": 6,
            "unknown_funding_policy": "neutral",
        },
    }
