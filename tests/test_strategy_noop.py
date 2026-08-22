"""Tests de la stratégie minimale : chargeable, mais aucun trade possible.

Nécessite Freqtrade (skippé sinon) : `pip install -e ".[dev,freqtrade]"`.
"""

from datetime import UTC, datetime

import pytest

freqtrade = pytest.importorskip("freqtrade")
pd = pytest.importorskip("pandas")

from AureusStrategy import AureusStrategy  # noqa: E402


@pytest.fixture
def strategy(valid_freqtrade_config, tmp_path):
    valid_freqtrade_config["user_data_dir"] = str(tmp_path)
    return AureusStrategy(config=valid_freqtrade_config)


@pytest.fixture
def ohlcv_dataframe():
    index = pd.date_range("2026-01-01", periods=50, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "date": index,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        }
    )


def test_strategy_attributes():
    assert AureusStrategy.INTERFACE_VERSION == 3
    assert AureusStrategy.timeframe == "5m"
    assert AureusStrategy.can_short is True
    assert AureusStrategy.process_only_new_candles is True


def test_populate_indicators_is_passthrough(strategy, ohlcv_dataframe):
    result = strategy.populate_indicators(ohlcv_dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    assert list(result.columns) == list(ohlcv_dataframe.columns)
    assert len(result) == len(ohlcv_dataframe)


def test_no_entry_signal_ever(strategy, ohlcv_dataframe):
    df = strategy.populate_indicators(ohlcv_dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    df = strategy.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
    assert (df["enter_long"] == 0).all()
    assert (df["enter_short"] == 0).all()


def test_no_exit_signal(strategy, ohlcv_dataframe):
    df = strategy.populate_indicators(ohlcv_dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    df = strategy.populate_exit_trend(df, {"pair": "BTC/USDT:USDT"})
    assert (df["exit_long"] == 0).all()
    assert (df["exit_short"] == 0).all()


def test_confirm_trade_entry_always_false(strategy):
    confirmed = strategy.confirm_trade_entry(
        pair="BTC/USDT:USDT",
        order_type="limit",
        amount=1.0,
        rate=100.0,
        time_in_force="GTC",
        current_time=datetime.now(UTC),
        entry_tag=None,
        side="long",
    )
    assert confirmed is False


def test_bot_start_validates_and_initializes(strategy, tmp_path):
    strategy.bot_start()
    # État persisté et diagnostics créés.
    assert (tmp_path / "aureus_state.json").exists()
    diag = tmp_path / "logs" / "aureus_diagnostics.jsonl"
    assert diag.exists()
    content = diag.read_text(encoding="utf-8")
    assert "bot_started" in content
    assert "config_validated" in content


def test_bot_start_fails_fast_on_invalid_config(valid_freqtrade_config, tmp_path):
    from aureus.config_schema import ConfigError

    valid_freqtrade_config["user_data_dir"] = str(tmp_path)
    valid_freqtrade_config["max_open_trades"] = 3
    strategy = AureusStrategy(config=valid_freqtrade_config)
    with pytest.raises(ConfigError):
        strategy.bot_start()
