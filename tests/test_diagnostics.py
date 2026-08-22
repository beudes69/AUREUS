"""Tests des diagnostics JSONL."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from aureus.diagnostics import REDACTED, DiagnosticsWriter, Event


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_emit_writes_valid_jsonl(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit(Event.BOT_STARTED, payload={"dry_run": True})
    writer.emit(Event.CONFIG_VALIDATED)

    records = _lines(writer.path)
    assert len(records) == 2
    assert records[0]["event"] == "bot_started"
    assert records[0]["payload"] == {"dry_run": True}
    assert records[1]["event"] == "config_validated"


def test_timestamp_is_utc_iso(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit(Event.BOT_STARTED)
    record = _lines(writer.path)[0]
    parsed = datetime.fromisoformat(record["ts"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60


def test_pair_and_plan_id_optional(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit(Event.SIGNAL_GENERATED)
    writer.emit(Event.PLAN_CREATED, pair="BTC/USDT:USDT", plan_id="abc-123")

    without, with_ids = _lines(writer.path)
    assert "pair" not in without
    assert "plan_id" not in without
    assert with_ids["pair"] == "BTC/USDT:USDT"
    assert with_ids["plan_id"] == "abc-123"


def test_decimal_payload_serialized_as_string(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit(Event.PLAN_CREATED, payload={"risk_amount": Decimal("10.55")})
    record = _lines(writer.path)[0]
    assert record["payload"]["risk_amount"] == "10.55"


def test_secrets_are_redacted(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit(
        Event.BOT_STARTED,
        payload={
            "api_key": "AKIA-visible",
            "exchange": {"secret": "s3cret", "password": "p4ss", "name": "okx"},
            # Clé évoquant un secret : la valeur ENTIÈRE est caviardée.
            "tokens": [{"access_token": "tok"}],
            # Clé anodine : récursion dans la liste, seule la clé secrète est caviardée.
            "items": [{"access_token": "tok2", "note": "ok"}],
            "risk_per_trade": "0.01",
        },
    )
    payload = _lines(writer.path)[0]["payload"]
    assert payload["api_key"] == REDACTED
    assert payload["exchange"]["secret"] == REDACTED
    assert payload["exchange"]["password"] == REDACTED
    assert payload["exchange"]["name"] == "okx"
    assert payload["tokens"] == REDACTED
    assert payload["items"][0]["access_token"] == REDACTED
    assert payload["items"][0]["note"] == "ok"
    assert payload["risk_per_trade"] == "0.01"

    # Aucun secret nulle part dans le fichier brut.
    raw = writer.path.read_text(encoding="utf-8")
    for secret in ("AKIA-visible", "s3cret", "p4ss", "tok2", '"tok"'):
        assert secret not in raw


def test_accepts_plain_string_event(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "diag.jsonl")
    writer.emit("custom_event")
    assert _lines(writer.path)[0]["event"] == "custom_event"


def test_creates_parent_directory(tmp_path):
    writer = DiagnosticsWriter(tmp_path / "logs" / "sub" / "diag.jsonl")
    writer.emit(Event.BOT_STARTED)
    assert writer.path.exists()
