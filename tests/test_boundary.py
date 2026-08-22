"""Tests de la frontière Decimal ⇄ float et des quantizations."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aureus.boundary import (
    BoundaryError,
    ceil_to_step,
    drawdown_fraction,
    floor_to_step,
    notional,
    position_pnl,
    r_multiple,
    to_decimal,
    to_float,
)

# ---------------------------------------------------------------------------
# to_decimal / to_float
# ---------------------------------------------------------------------------


def test_to_decimal_from_str_is_exact():
    assert to_decimal("0.1") == Decimal("0.1")
    assert to_decimal(" 42.5 ") == Decimal("42.5")


def test_to_decimal_from_int():
    assert to_decimal(7) == Decimal(7)


def test_to_decimal_from_float_uses_shortest_repr():
    # 0.1 float n'est pas exactement 1/10, mais str(0.1) == "0.1".
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(1234.56) == Decimal("1234.56")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_to_decimal_rejects_non_finite_floats(bad):
    with pytest.raises(BoundaryError):
        to_decimal(bad)


@pytest.mark.parametrize("bad", [True, False, None, [], {}, "abc", ""])
def test_to_decimal_rejects_invalid_inputs(bad):
    with pytest.raises(BoundaryError):
        to_decimal(bad)


def test_to_float_roundtrip():
    assert to_float(Decimal("1.5")) == 1.5


def test_to_float_rejects_non_decimal():
    with pytest.raises(BoundaryError):
        to_float(1.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------


def test_floor_to_step_rounds_down():
    assert floor_to_step(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")
    # Conservateur : 0.019 avec step 0.01 -> 0.01, jamais 0.02.
    assert floor_to_step(Decimal("0.019"), Decimal("0.01")) == Decimal("0.01")


def test_ceil_to_step_rounds_up():
    assert ceil_to_step(Decimal("1.231"), Decimal("0.01")) == Decimal("1.24")


def test_quantize_exact_multiple_unchanged():
    assert floor_to_step(Decimal("1.23"), Decimal("0.01")) == Decimal("1.23")
    assert ceil_to_step(Decimal("1.23"), Decimal("0.01")) == Decimal("1.23")


@pytest.mark.parametrize("bad_step", [Decimal("0"), Decimal("-0.01")])
def test_quantize_rejects_non_positive_step(bad_step):
    with pytest.raises(BoundaryError):
        floor_to_step(Decimal("1"), bad_step)
    with pytest.raises(BoundaryError):
        ceil_to_step(Decimal("1"), bad_step)


_steps = st.sampled_from(
    [Decimal("0.0001"), Decimal("0.001"), Decimal("0.01"), Decimal("0.1"), Decimal("1")]
)
_values = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1000000"), allow_nan=False, allow_infinity=False
)


@given(value=_values, step=_steps)
def test_floor_to_step_invariants(value: Decimal, step: Decimal):
    result = floor_to_step(value, step)
    # Jamais au-dessus de la valeur demandée (conservateur pour une quantité).
    assert result <= value
    # À moins d'un step de la valeur.
    assert value - result < step
    # Multiple exact du step.
    assert result % step == 0


@given(value=_values, step=_steps)
def test_ceil_to_step_invariants(value: Decimal, step: Decimal):
    result = ceil_to_step(value, step)
    assert result >= value
    assert result - value < step
    assert result % step == 0


# ---------------------------------------------------------------------------
# Primitives shadow accounting
# ---------------------------------------------------------------------------


def test_notional():
    assert notional(Decimal("50000"), Decimal("0.02")) == Decimal("1000.00")


def test_position_pnl_long():
    pnl = position_pnl(Decimal("100"), Decimal("110"), Decimal("2"), is_short=False)
    assert pnl == Decimal("20")


def test_position_pnl_long_loss():
    pnl = position_pnl(Decimal("100"), Decimal("95"), Decimal("2"), is_short=False)
    assert pnl == Decimal("-10")


def test_position_pnl_short():
    pnl = position_pnl(Decimal("100"), Decimal("90"), Decimal("1"), is_short=True)
    assert pnl == Decimal("10")


def test_position_pnl_short_loss():
    pnl = position_pnl(Decimal("100"), Decimal("110"), Decimal("1"), is_short=True)
    assert pnl == Decimal("-10")


def test_r_multiple():
    assert r_multiple(Decimal("-50"), Decimal("100")) == Decimal("-0.5")
    assert r_multiple(Decimal("200"), Decimal("100")) == Decimal("2")


def test_r_multiple_rejects_non_positive_risk():
    with pytest.raises(BoundaryError):
        r_multiple(Decimal("10"), Decimal("0"))


def test_drawdown_fraction():
    assert drawdown_fraction(Decimal("1000"), Decimal("970")) == Decimal("0.03")
    # Equity au-dessus de l'ancre -> drawdown négatif.
    assert drawdown_fraction(Decimal("1000"), Decimal("1010")) == Decimal("-0.01")


def test_drawdown_fraction_rejects_bad_anchor():
    with pytest.raises(BoundaryError):
        drawdown_fraction(Decimal("0"), Decimal("100"))
