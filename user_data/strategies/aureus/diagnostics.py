"""Diagnostics AUREUS — événements JSONL structurés.

Une ligne JSON par événement :
``{"ts": "<ISO 8601 UTC>", "event": "...", "pair": ..., "plan_id": ..., "payload": {...}}``

- ``pair`` et ``plan_id`` sont optionnels (omis si absents).
- Les Decimal du payload sont sérialisés en chaînes.
- Toute clé de payload ressemblant à un secret (key/secret/password/passphrase/
  token/credential) est caviardée récursivement : aucun secret dans les logs.

L'enum ``Event`` fixe dès maintenant le vocabulaire du funnel de diagnostics
(matière première du futur ZERO TRADE report) — seuls les événements de cycle
de vie sont émis à l'étape 1.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

REDACTED = "[REDACTED]"
_SECRET_KEY_PATTERN = re.compile(
    r"(key|secret|password|passphrase|token|credential)", re.IGNORECASE
)


class Event(StrEnum):
    """Stages du funnel AUREUS + événements de cycle de vie."""

    # Cycle de vie
    BOT_STARTED = "bot_started"
    CONFIG_VALIDATED = "config_validated"
    STATE_RECOVERED_CORRUPT = "state_recovered_corrupt"
    # Funnel signal -> sortie (émis à partir des étapes suivantes)
    SIGNAL_GENERATED = "signal_generated"
    PLAN_CREATED = "plan_created"
    PLAN_REJECTED = "plan_rejected"
    ENTRY_APPROVED = "entry_approved"
    ENTRY_REJECTED = "entry_rejected"
    ORDER_CREATED = "order_created"
    ORDER_FILLED = "order_filled"
    ENTRY_TIMEOUT = "entry_timeout"
    PARTIAL_ORDER_CREATED = "partial_order_created"
    PARTIAL_FILLED = "partial_filled"
    TRAILING_ARMED = "trailing_armed"
    EXITED = "exited"


def _scrub(value: object) -> object:
    """Caviarde récursivement les valeurs dont la clé évoque un secret."""
    if isinstance(value, Mapping):
        return {
            str(key): (REDACTED if _SECRET_KEY_PATTERN.search(str(key)) else _scrub(item))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _json_default(value: object) -> str:
    if isinstance(value, Decimal | datetime | date):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    return str(value)


class DiagnosticsWriter:
    """Écrit les événements en JSONL (append-only, une ligne par événement)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event: Event | str,
        *,
        pair: str | None = None,
        plan_id: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        record: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "event": str(event),
        }
        if pair is not None:
            record["pair"] = pair
        if plan_id is not None:
            record["plan_id"] = plan_id
        record["payload"] = _scrub(dict(payload) if payload else {})

        line = json.dumps(
            record, default=_json_default, ensure_ascii=False, separators=(",", ":")
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
