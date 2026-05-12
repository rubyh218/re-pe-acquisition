"""
debt_sizing.py — Constraint-based loan sizing + amortization schedule.

Wraps vendor/asset-management/scripts/debt_metrics.py for max-loan sizing
(min of LTV / DSCR / Debt Yield), then builds the annual amortization schedule
needed for the pro forma's debt-service line.
"""

from __future__ import annotations

from dataclasses import dataclass

import scripts  # noqa: F401  (sets sys.path so vendor scripts import)
from debt_metrics import (
    _annual_debt_service,
    debt_yield,
    dscr,
    ltv,
    size_max_loan,
)

from .models import Debt


@dataclass
class SizingResult:
    loan_amount: float
    constraints: dict[str, float]   # {"LTV": ..., "DSCR": ..., "Debt Yield": ...}
    binding: str                    # which constraint set the loan size
    implied_ltv: float
    implied_dscr: float
    implied_debt_yield: float


@dataclass
class AmortYear:
    year: int               # 1-indexed year of hold
    beginning_balance: float
    interest: float
    principal: float
    debt_service: float
    ending_balance: float
    is_io: bool             # interest-only year flag


def size_loan(
    sizing_noi: float,      # NOI used for sizing — typically Year 1 stabilized
    purchase_price: float,
    debt: Debt,
) -> SizingResult:
    """Solve for max loan proceeds given the three constraints."""
    if debt.fixed_loan_amount is not None:
        loan = debt.fixed_loan_amount
        return SizingResult(
            loan_amount=loan,
            constraints={
                "LTV":         debt.max_ltv * purchase_price,
                "DSCR":        float("inf"),
                "Debt Yield":  sizing_noi / debt.min_debt_yield,
            },
            binding="(fixed)",
            implied_ltv=ltv(loan, purchase_price),
            implied_dscr=dscr(sizing_noi, _annual_debt_service(loan, debt.rate, debt.amort_yrs)),
            implied_debt_yield=debt_yield(sizing_noi, loan),
        )

    result = size_max_loan(
        noi=sizing_noi,
        value=purchase_price,
        rate=debt.rate,
        amort_yrs=debt.amort_yrs,
        max_ltv=debt.max_ltv,
        min_dscr=debt.min_dscr,
        min_debt_yield=debt.min_debt_yield,
    )
    return SizingResult(
        loan_amount=result["max_loan"],
        constraints=result["constraints"],
        binding=result["binding"],
        implied_ltv=result["implied_ltv"],
        implied_dscr=result["implied_dscr"],
        implied_debt_yield=result["implied_debt_yield"],
    )


def amortization_schedule(
    loan_amount: float,
    debt: Debt,
    years: int,
) -> list[AmortYear]:
    """
    Build annual amort schedule.

    Honors io_period_yrs (interest-only first N years) then switches to amortizing
    on the remaining balance over the remaining amort_yrs. If amort_yrs == 0,
    fully interest-only for the whole term.
    """
    schedule: list[AmortYear] = []
    balance = loan_amount
    rate = debt.rate

    # Annual payment for the amortizing portion (post-IO)
    if debt.amort_yrs > 0:
        amort_annual = _annual_debt_service(loan_amount, rate, debt.amort_yrs)
    else:
        amort_annual = loan_amount * rate  # IO

    for yr in range(1, years + 1):
        is_io = yr <= debt.io_period_yrs or debt.amort_yrs == 0
        beginning = balance
        if is_io:
            interest = balance * rate
            principal = 0.0
            ds = interest
        else:
            # On the level-pay amortizing schedule, annual payment is constant; principal = ds - interest
            ds = amort_annual
            interest = balance * rate
            principal = max(0.0, ds - interest)
            # Cap principal at remaining balance
            if principal > balance:
                principal = balance
                ds = interest + principal
        ending = beginning - principal
        schedule.append(
            AmortYear(
                year=yr,
                beginning_balance=beginning,
                interest=interest,
                principal=principal,
                debt_service=ds,
                ending_balance=ending,
                is_io=is_io,
            )
        )
        balance = ending

    return schedule
