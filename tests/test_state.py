"""Tests de la persistence JSON atomique et de la récupération conservatrice."""

import json
from decimal import Decimal

from aureus.state import AureusState, DailyRiskState, StateStore


def _store(tmp_path):
    return StateStore(tmp_path / "aureus_state.json")


def test_missing_file_returns_fresh_state(tmp_path):
    state = _store(tmp_path).load()
    assert state.daily_risk.halted is False
    assert state.daily_risk.daily_equity_anchor is None
    assert state.recovered_from_corruption is False
    assert state.cooldowns == {}


def test_write_read_roundtrip(tmp_path):
    store = _store(tmp_path)
    state = AureusState(
        daily_risk=DailyRiskState(
            date_utc="2026-08-22",
            daily_equity_anchor=Decimal("1000.55"),
            realized_r=Decimal("-1.5"),
            halted=False,
        ),
        cooldowns={"BTC/USDT:USDT": "2026-08-22T10:00:00+00:00"},
    )
    store.save(state)
    loaded = store.load()
    assert loaded.daily_risk.date_utc == "2026-08-22"
    assert loaded.daily_risk.daily_equity_anchor == Decimal("1000.55")
    assert isinstance(loaded.daily_risk.daily_equity_anchor, Decimal)
    assert loaded.daily_risk.realized_r == Decimal("-1.5")
    assert loaded.daily_risk.halted is False
    assert loaded.cooldowns == {"BTC/USDT:USDT": "2026-08-22T10:00:00+00:00"}
    assert loaded.recovered_from_corruption is False


def test_persistence_across_simulated_restart(tmp_path):
    path = tmp_path / "aureus_state.json"
    first = StateStore(path)
    state = first.load()
    state.daily_risk.halted = True
    state.daily_risk.realized_r = Decimal("-2")
    first.save(state)

    # "Restart" : nouvelle instance sur le même chemin.
    second = StateStore(path)
    reloaded = second.load()
    assert reloaded.daily_risk.halted is True
    assert reloaded.daily_risk.realized_r == Decimal("-2")


def test_corrupt_json_recovers_conservatively(tmp_path):
    path = tmp_path / "aureus_state.json"
    path.write_text("{ceci n'est pas du JSON", encoding="utf-8")

    state = StateStore(path).load()
    # Conservateur : HALT jusqu'au reset UTC.
    assert state.daily_risk.halted is True
    assert state.recovered_from_corruption is True
    # Le fichier corrompu est mis en quarantaine, pas silencieusement écrasé.
    quarantined = list(tmp_path.glob("aureus_state.json.corrupt-*"))
    assert len(quarantined) == 1
    assert not path.exists()


def test_wrong_version_treated_as_corrupt(tmp_path):
    path = tmp_path / "aureus_state.json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    state = StateStore(path).load()
    assert state.daily_risk.halted is True
    assert state.recovered_from_corruption is True


def test_wrong_types_treated_as_corrupt(tmp_path):
    path = tmp_path / "aureus_state.json"
    payload = {
        "version": 1,
        "daily_risk": {
            "date_utc": None,
            "daily_equity_anchor": None,
            "realized_r": "0",
            "halted": "non",  # doit être un booléen
        },
        "cooldowns": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    state = StateStore(path).load()
    assert state.daily_risk.halted is True
    assert state.recovered_from_corruption is True


def test_atomic_save_leaves_no_temp_files(tmp_path):
    store = _store(tmp_path)
    for _ in range(3):
        store.save(AureusState())
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    assert (tmp_path / "aureus_state.json").exists()


def test_save_creates_parent_directory(tmp_path):
    store = StateStore(tmp_path / "nested" / "dir" / "state.json")
    store.save(AureusState())
    assert store.load().daily_risk.halted is False


def test_decimals_serialized_as_strings(tmp_path):
    store = _store(tmp_path)
    state = AureusState(
        daily_risk=DailyRiskState(daily_equity_anchor=Decimal("123.45"), realized_r=Decimal("0.5"))
    )
    store.save(state)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["daily_risk"]["daily_equity_anchor"] == "123.45"
    assert raw["daily_risk"]["realized_r"] == "0.5"
