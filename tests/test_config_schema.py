"""Tests de la validation fail-fast de configuration."""

from decimal import Decimal

import pytest
from aureus.config_schema import AureusConfig, ConfigError, validate_config


def test_valid_config_passes(valid_freqtrade_config):
    result = validate_config(valid_freqtrade_config)
    assert isinstance(result, AureusConfig)
    assert result.risk_per_trade == Decimal("0.01")
    assert result.max_leverage == Decimal("5")
    assert result.daily_max_drawdown == Decimal("0.03")
    assert result.cooldown_candles == 6
    assert result.unknown_funding_policy == "neutral"
    assert result.allow_live is False


def test_financial_params_are_decimal(valid_freqtrade_config):
    result = validate_config(valid_freqtrade_config)
    assert isinstance(result.risk_per_trade, Decimal)
    assert isinstance(result.max_leverage, Decimal)
    assert isinstance(result.daily_max_loss_r, Decimal)
    assert isinstance(result.daily_max_drawdown, Decimal)


def test_missing_aureus_section_uses_safe_defaults(valid_freqtrade_config):
    del valid_freqtrade_config["aureus"]
    result = validate_config(valid_freqtrade_config)
    assert result.risk_per_trade == Decimal("0.01")
    assert result.max_leverage == Decimal("5")


@pytest.mark.parametrize("bad_risk", ["0", "-0.01", "0.03", "abc", None])
def test_risk_per_trade_out_of_bounds_rejected(valid_freqtrade_config, bad_risk):
    valid_freqtrade_config["aureus"]["risk_per_trade"] = bad_risk
    with pytest.raises(ConfigError, match="risk_per_trade"):
        validate_config(valid_freqtrade_config)


@pytest.mark.parametrize("bad_leverage", ["6", 6, "5.01", "0.5", "0"])
def test_leverage_above_5_or_below_1_rejected(valid_freqtrade_config, bad_leverage):
    valid_freqtrade_config["aureus"]["max_leverage"] = bad_leverage
    with pytest.raises(ConfigError, match="max_leverage"):
        validate_config(valid_freqtrade_config)


def test_dry_run_false_rejected_without_explicit_allow_live(valid_freqtrade_config):
    valid_freqtrade_config["dry_run"] = False
    with pytest.raises(ConfigError, match="dry_run"):
        validate_config(valid_freqtrade_config)


def test_dry_run_false_accepted_with_explicit_allow_live(valid_freqtrade_config):
    valid_freqtrade_config["dry_run"] = False
    valid_freqtrade_config["aureus"]["allow_live"] = True
    result = validate_config(valid_freqtrade_config)
    assert result.allow_live is True


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("trading_mode", "spot", "trading_mode"),
        ("margin_mode", "cross", "margin_mode"),
        ("max_open_trades", 2, "max_open_trades"),
        ("stake_currency", "BTC", "stake_currency"),
        ("timeframe", "1h", "timeframe"),
    ],
)
def test_freqtrade_invariants_rejected(valid_freqtrade_config, key, value, fragment):
    valid_freqtrade_config[key] = value
    with pytest.raises(ConfigError, match=fragment):
        validate_config(valid_freqtrade_config)


def test_spot_pair_format_rejected(valid_freqtrade_config):
    valid_freqtrade_config["exchange"]["pair_whitelist"] = ["BTC/USDT"]
    with pytest.raises(ConfigError, match="pair_whitelist"):
        validate_config(valid_freqtrade_config)


def test_empty_whitelist_rejected(valid_freqtrade_config):
    valid_freqtrade_config["exchange"]["pair_whitelist"] = []
    with pytest.raises(ConfigError, match="pair_whitelist"):
        validate_config(valid_freqtrade_config)


def test_unknown_aureus_key_rejected(valid_freqtrade_config):
    valid_freqtrade_config["aureus"]["risk_pertrade"] = "0.01"
    with pytest.raises(ConfigError, match="clés inconnues"):
        validate_config(valid_freqtrade_config)


@pytest.mark.parametrize("bad_cooldown", [True, -1, "6", 1.5])
def test_invalid_cooldown_rejected(valid_freqtrade_config, bad_cooldown):
    valid_freqtrade_config["aureus"]["cooldown_candles"] = bad_cooldown
    with pytest.raises(ConfigError, match="cooldown_candles"):
        validate_config(valid_freqtrade_config)


def test_invalid_funding_policy_rejected(valid_freqtrade_config):
    valid_freqtrade_config["aureus"]["unknown_funding_policy"] = "yolo"
    with pytest.raises(ConfigError, match="unknown_funding_policy"):
        validate_config(valid_freqtrade_config)


def test_all_errors_reported_at_once(valid_freqtrade_config):
    valid_freqtrade_config["max_open_trades"] = 3
    valid_freqtrade_config["aureus"]["max_leverage"] = "10"
    valid_freqtrade_config["aureus"]["risk_per_trade"] = "0.5"
    with pytest.raises(ConfigError) as excinfo:
        validate_config(valid_freqtrade_config)
    message = str(excinfo.value)
    assert "max_open_trades" in message
    assert "max_leverage" in message
    assert "risk_per_trade" in message
