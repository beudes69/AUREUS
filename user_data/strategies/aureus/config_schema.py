"""Validation fail-fast de la configuration AUREUS.

Lit la section ``aureus`` de la config Freqtrade et vérifie les invariants
critiques de la config elle-même (dry-run, futures isolated, 1 position max…).
Toutes les erreurs sont collectées puis remontées en une seule ``ConfigError``
avec un message explicite par problème — le bot refuse de démarrer.

Politique Decimal : les paramètres financiers sont exposés en ``Decimal``.
Les nombres JSON (floats) sont convertis via ``Decimal(str(x))`` ; pour une
exactitude garantie, écrire les valeurs en chaînes dans la config
(ex. ``"risk_per_trade": "0.01"``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

CONFIG_SECTION = "aureus"

# Bornes dures — non configurables.
HARD_MAX_LEVERAGE = Decimal("5")
HARD_MAX_RISK_PER_TRADE = Decimal("0.02")
HARD_MAX_DAILY_DRAWDOWN = Decimal("0.10")

REQUIRED_TRADING_MODE = "futures"
REQUIRED_MARGIN_MODE = "isolated"
REQUIRED_STAKE_CURRENCY = "USDT"
REQUIRED_MAX_OPEN_TRADES = 1
REQUIRED_TIMEFRAME = "5m"

UNKNOWN_FUNDING_POLICIES = ("neutral", "block")

_PAIR_PATTERN = re.compile(r"^[A-Z0-9]+/USDT:USDT$")

# Valeurs par défaut de la section aureus (toutes surchargeables, dans les bornes).
_DEFAULTS: dict[str, Any] = {
    "risk_per_trade": "0.01",
    "max_leverage": "5",
    "daily_max_loss_r": "2",
    "daily_max_drawdown": "0.03",
    "cooldown_candles": 6,
    "unknown_funding_policy": "neutral",
    "allow_live": False,
}


class ConfigError(ValueError):
    """Configuration invalide — le bot ne doit pas démarrer."""


@dataclass(frozen=True)
class AureusConfig:
    """Paramètres AUREUS validés. Tous les montants/ratios sont des Decimal."""

    risk_per_trade: Decimal
    max_leverage: Decimal
    daily_max_loss_r: Decimal
    daily_max_drawdown: Decimal
    cooldown_candles: int
    unknown_funding_policy: str
    allow_live: bool


def _as_decimal(name: str, value: Any, errors: list[str]) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        errors.append(
            f"{CONFIG_SECTION}.{name}: type invalide {type(value).__name__!r} "
            f"(attendu chaîne, entier ou nombre — préférer une chaîne, ex. \"0.01\")"
        )
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        errors.append(f"{CONFIG_SECTION}.{name}: valeur non numérique {value!r}")
        return None
    if not result.is_finite():
        errors.append(f"{CONFIG_SECTION}.{name}: valeur non finie {value!r}")
        return None
    return result


def validate_config(config: Mapping[str, Any]) -> AureusConfig:
    """Valide la config Freqtrade complète et retourne les paramètres AUREUS.

    Lève ``ConfigError`` listant TOUTES les violations détectées.
    """
    errors: list[str] = []

    # ---- Section aureus : clés connues + défauts -------------------------------------
    section_raw = config.get(CONFIG_SECTION, {})
    if not isinstance(section_raw, Mapping):
        errors.append(
            f"{CONFIG_SECTION}: doit être un objet JSON, reçu {type(section_raw).__name__!r}"
        )
        section_raw = {}
    unknown_keys = sorted(set(section_raw) - set(_DEFAULTS))
    if unknown_keys:
        errors.append(
            f"{CONFIG_SECTION}: clés inconnues {unknown_keys} "
            f"(clés valides : {sorted(_DEFAULTS)})"
        )
    section: dict[str, Any] = {**_DEFAULTS, **dict(section_raw)}

    # ---- Invariants de la config Freqtrade -------------------------------------------
    allow_live = section["allow_live"]
    if not isinstance(allow_live, bool):
        errors.append(f"{CONFIG_SECTION}.allow_live: booléen attendu, reçu {allow_live!r}")
        allow_live = False
    if config.get("dry_run", True) is not True and allow_live is not True:
        errors.append(
            "dry_run: doit être true — le passage en live exige un "
            f"{CONFIG_SECTION}.allow_live=true explicite"
        )

    trading_mode = config.get("trading_mode")
    if trading_mode != REQUIRED_TRADING_MODE:
        errors.append(f"trading_mode: attendu {REQUIRED_TRADING_MODE!r}, reçu {trading_mode!r}")

    margin_mode = config.get("margin_mode")
    if margin_mode != REQUIRED_MARGIN_MODE:
        errors.append(f"margin_mode: attendu {REQUIRED_MARGIN_MODE!r}, reçu {margin_mode!r}")

    max_open_trades = config.get("max_open_trades")
    if max_open_trades != REQUIRED_MAX_OPEN_TRADES:
        errors.append(
            f"max_open_trades: attendu {REQUIRED_MAX_OPEN_TRADES}, reçu {max_open_trades!r}"
        )

    stake_currency = config.get("stake_currency")
    if stake_currency != REQUIRED_STAKE_CURRENCY:
        errors.append(
            f"stake_currency: attendu {REQUIRED_STAKE_CURRENCY!r}, reçu {stake_currency!r}"
        )

    timeframe = config.get("timeframe")
    if timeframe is not None and timeframe != REQUIRED_TIMEFRAME:
        errors.append(f"timeframe: attendu {REQUIRED_TIMEFRAME!r}, reçu {timeframe!r}")

    exchange = config.get("exchange") or {}
    whitelist = exchange.get("pair_whitelist") if isinstance(exchange, Mapping) else None
    if not whitelist:
        errors.append("exchange.pair_whitelist: au moins une paire perpetual requise")
    else:
        for pair in whitelist:
            if not isinstance(pair, str) or not _PAIR_PATTERN.match(pair):
                errors.append(
                    f"exchange.pair_whitelist: paire invalide {pair!r} "
                    f"(format perpetual attendu, ex. 'BTC/USDT:USDT')"
                )

    # ---- Paramètres financiers (Decimal + bornes) ------------------------------------
    risk_per_trade = _as_decimal("risk_per_trade", section["risk_per_trade"], errors)
    if risk_per_trade is not None and not (
        Decimal("0") < risk_per_trade <= HARD_MAX_RISK_PER_TRADE
    ):
        errors.append(
            f"{CONFIG_SECTION}.risk_per_trade: {risk_per_trade} hors bornes "
            f"(0 < r <= {HARD_MAX_RISK_PER_TRADE})"
        )

    max_leverage = _as_decimal("max_leverage", section["max_leverage"], errors)
    if max_leverage is not None and not (Decimal("1") <= max_leverage <= HARD_MAX_LEVERAGE):
        errors.append(
            f"{CONFIG_SECTION}.max_leverage: {max_leverage} hors bornes "
            f"(1 <= levier <= {HARD_MAX_LEVERAGE})"
        )

    daily_max_loss_r = _as_decimal("daily_max_loss_r", section["daily_max_loss_r"], errors)
    if daily_max_loss_r is not None and daily_max_loss_r <= 0:
        errors.append(
            f"{CONFIG_SECTION}.daily_max_loss_r: {daily_max_loss_r} invalide (doit être > 0)"
        )

    daily_max_drawdown = _as_decimal("daily_max_drawdown", section["daily_max_drawdown"], errors)
    if daily_max_drawdown is not None and not (
        Decimal("0") < daily_max_drawdown <= HARD_MAX_DAILY_DRAWDOWN
    ):
        errors.append(
            f"{CONFIG_SECTION}.daily_max_drawdown: {daily_max_drawdown} hors bornes "
            f"(0 < dd <= {HARD_MAX_DAILY_DRAWDOWN})"
        )

    cooldown_candles = section["cooldown_candles"]
    if isinstance(cooldown_candles, bool) or not isinstance(cooldown_candles, int):
        errors.append(
            f"{CONFIG_SECTION}.cooldown_candles: entier attendu, reçu {cooldown_candles!r}"
        )
        cooldown_candles = 0
    elif cooldown_candles < 0:
        errors.append(f"{CONFIG_SECTION}.cooldown_candles: {cooldown_candles} invalide (>= 0)")

    unknown_funding_policy = section["unknown_funding_policy"]
    if unknown_funding_policy not in UNKNOWN_FUNDING_POLICIES:
        errors.append(
            f"{CONFIG_SECTION}.unknown_funding_policy: {unknown_funding_policy!r} invalide "
            f"(valeurs possibles : {list(UNKNOWN_FUNDING_POLICIES)})"
        )

    if errors:
        raise ConfigError(
            "Configuration AUREUS invalide — démarrage refusé :\n- " + "\n- ".join(errors)
        )

    assert risk_per_trade is not None
    assert max_leverage is not None
    assert daily_max_loss_r is not None
    assert daily_max_drawdown is not None
    return AureusConfig(
        risk_per_trade=risk_per_trade,
        max_leverage=max_leverage,
        daily_max_loss_r=daily_max_loss_r,
        daily_max_drawdown=daily_max_drawdown,
        cooldown_candles=cooldown_candles,
        unknown_funding_policy=unknown_funding_policy,
        allow_live=allow_live,
    )
