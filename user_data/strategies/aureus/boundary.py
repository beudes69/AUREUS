"""Frontière Decimal ⇄ float d'AUREUS.

Règles :
- Tout calcul monétaire (prix, stake, notionnel, stop, PnL, risque) se fait en
  ``Decimal``. Les ``float`` n'existent qu'aux frontières Freqtrade/CCXT et ne
  traversent que par ``to_decimal`` / ``to_float``.
- Les floats sont convertis via ``Decimal(str(x))`` (repr le plus court) ; les
  valeurs non finies (nan/inf) sont rejetées.
- Les quantizations d'exécution sont conservatrices : les quantités s'arrondissent
  vers le bas (jamais plus gros que prévu).

Ce module contient aussi les primitives pures du futur shadow accounting
(PnL, multiple de R, drawdown) — le moteur complet arrive avec le RiskEngine.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


class BoundaryError(ValueError):
    """Violation de la frontière Decimal ⇄ float."""


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def to_decimal(value: int | float | str | Decimal) -> Decimal:
    """Convertit une valeur de la frontière en Decimal exact.

    - ``Decimal`` : passe-plat (doit être fini)
    - ``int`` / ``str`` : conversion exacte
    - ``float`` : converti via ``str()`` (repr le plus court) ; nan/inf rejetés
    """
    if isinstance(value, bool):
        raise BoundaryError(f"to_decimal: booléen refusé ({value!r})")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BoundaryError(f"to_decimal: Decimal non fini refusé ({value!r})")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BoundaryError(f"to_decimal: float non fini refusé ({value!r})")
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except Exception as exc:
            raise BoundaryError(f"to_decimal: chaîne non numérique {value!r}") from exc
        if not result.is_finite():
            raise BoundaryError(f"to_decimal: valeur non finie {value!r}")
        return result
    raise BoundaryError(f"to_decimal: type non supporté {type(value).__name__!r}")


def to_float(value: Decimal) -> float:
    """Convertit un Decimal en float pour un callback Freqtrade/CCXT."""
    if not isinstance(value, Decimal):
        raise BoundaryError(f"to_float: Decimal attendu, reçu {type(value).__name__!r}")
    if not value.is_finite():
        raise BoundaryError(f"to_float: Decimal non fini refusé ({value!r})")
    return float(value)


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

def _check_step(step: Decimal) -> None:
    if not isinstance(step, Decimal) or not step.is_finite() or step <= 0:
        raise BoundaryError(f"quantization: step invalide ({step!r}), attendu Decimal > 0")


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Arrondit ``value`` vers le bas au multiple de ``step`` (conservateur pour
    les quantités : on ne prend jamais une position plus grosse que calculée)."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise BoundaryError(f"floor_to_step: valeur invalide ({value!r})")
    _check_step(step)
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Arrondit ``value`` vers le haut au multiple de ``step``."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise BoundaryError(f"ceil_to_step: valeur invalide ({value!r})")
    _check_step(step)
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


# ---------------------------------------------------------------------------
# Primitives du shadow accounting (moteur complet à l'étape RiskEngine)
# ---------------------------------------------------------------------------

def notional(price: Decimal, amount: Decimal) -> Decimal:
    """Notionnel = prix × quantité (base currency)."""
    if price <= 0:
        raise BoundaryError(f"notional: prix invalide ({price!r})")
    if amount < 0:
        raise BoundaryError(f"notional: quantité négative ({amount!r})")
    return price * amount


def position_pnl(
    entry_price: Decimal,
    exit_price: Decimal,
    amount: Decimal,
    *,
    is_short: bool,
) -> Decimal:
    """PnL brut (hors frais/funding) d'une position, signé."""
    if entry_price <= 0 or exit_price <= 0:
        raise BoundaryError("position_pnl: les prix doivent être > 0")
    if amount <= 0:
        raise BoundaryError(f"position_pnl: quantité invalide ({amount!r})")
    direction = Decimal(-1) if is_short else Decimal(1)
    return (exit_price - entry_price) * amount * direction


def r_multiple(pnl: Decimal, risk_amount: Decimal) -> Decimal:
    """Exprime un PnL en multiples de R (risque initial du trade)."""
    if risk_amount <= 0:
        raise BoundaryError(f"r_multiple: risk_amount invalide ({risk_amount!r}), attendu > 0")
    return pnl / risk_amount


def drawdown_fraction(anchor: Decimal, current: Decimal) -> Decimal:
    """Drawdown relatif à une ancre : (anchor - current) / anchor.

    Positif = perte par rapport à l'ancre ; négatif = equity au-dessus de l'ancre.
    """
    if anchor <= 0:
        raise BoundaryError(f"drawdown_fraction: ancre invalide ({anchor!r}), attendu > 0")
    return (anchor - current) / anchor
