"""Persistence de l'état global AUREUS — JSON atomique.

Garanties :
- Écriture atomique : fichier temporaire dans le même répertoire + flush +
  fsync + ``os.replace`` (+ fsync du répertoire). Aucun état partiel possible.
- Lecture conservatrice : fichier manquant = premier démarrage (état neuf) ;
  fichier corrompu ou schéma inattendu = quarantaine du fichier + état
  **conservateur** (``halted=True`` : aucune entrée jusqu'au reset UTC).
- Les Decimal sont sérialisés en chaînes.

Structure (v1) — prête pour le daily risk state et les cooldowns, sans aucune
logique de trading ici :
- ``daily_risk`` : date UTC, ``daily_equity_anchor`` (référence du drawdown
  quotidien, distincte de la current equity de sizing), R réalisé, flag HALT.
- ``cooldowns`` : pair -> timestamp ISO de fin de cooldown.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

STATE_VERSION = 1


class _CorruptState(ValueError):
    """Interne : contenu illisible ou schéma inattendu."""


@dataclass
class DailyRiskState:
    """État de risque journalier (kill switch). Aucune logique ici."""

    date_utc: str | None = None
    daily_equity_anchor: Decimal | None = None
    realized_r: Decimal = Decimal("0")
    halted: bool = False


@dataclass
class AureusState:
    daily_risk: DailyRiskState = field(default_factory=DailyRiskState)
    cooldowns: dict[str, str] = field(default_factory=dict)
    # Non persisté : signale qu'on a redémarré depuis un état corrompu.
    recovered_from_corruption: bool = False


def fresh_state() -> AureusState:
    """État d'un premier démarrage : rien à protéger, pas de HALT."""
    return AureusState()


def conservative_state() -> AureusState:
    """État le plus conservateur : HALT jusqu'au reset UTC.

    Utilisé quand l'état persisté est illisible : on ne peut pas prouver que le
    kill switch n'était pas armé, donc on le considère armé.
    """
    return AureusState(
        daily_risk=DailyRiskState(halted=True),
        recovered_from_corruption=True,
    )


# ---------------------------------------------------------------------------
# (Dé)sérialisation stricte
# ---------------------------------------------------------------------------

def _optional_decimal(value: object, name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _CorruptState(f"{name}: chaîne Decimal attendue, reçu {type(value).__name__}")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _CorruptState(f"{name}: valeur non numérique {value!r}") from exc
    if not result.is_finite():
        raise _CorruptState(f"{name}: valeur non finie {value!r}")
    return result


def _state_to_json(state: AureusState) -> dict:
    anchor = state.daily_risk.daily_equity_anchor
    return {
        "version": STATE_VERSION,
        "daily_risk": {
            "date_utc": state.daily_risk.date_utc,
            "daily_equity_anchor": None if anchor is None else str(anchor),
            "realized_r": str(state.daily_risk.realized_r),
            "halted": state.daily_risk.halted,
        },
        "cooldowns": dict(state.cooldowns),
    }


def _state_from_json(data: object) -> AureusState:
    if not isinstance(data, dict):
        raise _CorruptState("racine: objet JSON attendu")
    if data.get("version") != STATE_VERSION:
        raise _CorruptState(f"version: {data.get('version')!r} != {STATE_VERSION}")

    daily = data.get("daily_risk")
    if not isinstance(daily, dict):
        raise _CorruptState("daily_risk: objet attendu")
    date_utc = daily.get("date_utc")
    if date_utc is not None and not isinstance(date_utc, str):
        raise _CorruptState("daily_risk.date_utc: chaîne ou null attendu")
    halted = daily.get("halted")
    if not isinstance(halted, bool):
        raise _CorruptState("daily_risk.halted: booléen attendu")
    realized_r = _optional_decimal(daily.get("realized_r"), "daily_risk.realized_r")
    if realized_r is None:
        raise _CorruptState("daily_risk.realized_r: requis")
    anchor = _optional_decimal(
        daily.get("daily_equity_anchor"), "daily_risk.daily_equity_anchor"
    )

    cooldowns_raw = data.get("cooldowns")
    if not isinstance(cooldowns_raw, dict):
        raise _CorruptState("cooldowns: objet attendu")
    cooldowns: dict[str, str] = {}
    for pair, until in cooldowns_raw.items():
        if not isinstance(pair, str) or not isinstance(until, str):
            raise _CorruptState(f"cooldowns: entrée invalide {pair!r} -> {until!r}")
        cooldowns[pair] = until

    return AureusState(
        daily_risk=DailyRiskState(
            date_utc=date_utc,
            daily_equity_anchor=anchor,
            realized_r=realized_r,
            halted=halted,
        ),
        cooldowns=cooldowns,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class StateStore:
    """Lecture/écriture atomique de l'état AUREUS sur disque."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> AureusState:
        """Charge l'état.

        - fichier absent  -> état neuf (premier démarrage)
        - fichier corrompu -> quarantaine (.corrupt-<ts>) + état conservateur (HALT)
        """
        if not self.path.exists():
            return fresh_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return _state_from_json(data)
        except (_CorruptState, json.JSONDecodeError, UnicodeDecodeError):
            self._quarantine()
            return conservative_state()

    def save(self, state: AureusState) -> None:
        """Écrit l'état de façon atomique (tempfile + flush + fsync + replace)."""
        payload = json.dumps(_state_to_json(state), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            self._fsync_dir()
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_path)

    def _quarantine(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        with contextlib.suppress(OSError):
            os.replace(self.path, backup)

    def _fsync_dir(self) -> None:
        with contextlib.suppress(OSError):
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
