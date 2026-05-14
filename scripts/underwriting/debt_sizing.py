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
    Build annual amort schedule by summing 12 monthly steps per year.

    Real-world RE loans amortize monthly: each month interest accrues on the
    THEN-CURRENT balance, principal pays down, and next month's interest is
    on the now-smaller balance. Approximating with annual `balance * rate`
    overstates year-1 interest and under-states principal, drifting on long
    holds (~30bps on a 10-yr balloon for a 30-yr-amort loan).

    Convention:
      - amort_yrs is the amortization period, calibrating the monthly payment
        as `loan_amount` amortizing over `amort_yrs * 12` months. The same
        monthly payment applies after the IO period; in a balloon-at-term
        scenario (term < amort) the balance at maturity is the balloon.
      - io_period_yrs years pay interest only on the then-current balance
        (which equals loan_amount throughout the IO since no principal pays).
      - amort_yrs == 0 → interest-only for the whole term.
    """
    schedule: list[AmortYear] = []
    balance = loan_amount
    annual_rate = debt.rate
    monthly_rate = annual_rate / 12

    # Monthly amortizing payment, sized once on the original loan over the
    # full amortization period (institutional convention).
    if debt.amort_yrs > 0:
        n = debt.amort_yrs * 12
        if monthly_rate > 0:
            monthly_pmt = loan_amount * (
                monthly_rate * (1 + monthly_rate) ** n
            ) / ((1 + monthly_rate) ** n - 1)
        else:
            monthly_pmt = loan_amount / n
    else:
        monthly_pmt = 0.0  # IO-only; payment recomputed below from balance

    for yr in range(1, years + 1):
        is_io = yr <= debt.io_period_yrs or debt.amort_yrs == 0
        beginning = balance
        year_interest = 0.0
        year_principal = 0.0
        for _ in range(12):
            month_interest = balance * monthly_rate
            year_interest += month_interest
            if is_io:
                month_principal = 0.0
            else:
                month_principal = min(monthly_pmt - month_interest, balance)
                if month_principal < 0:
                    # Negative-amortization guard: in a steep enough rate move,
                    # interest could exceed the payment. We don't model neg-am;
                    # treat as IO for that month and let the schedule continue.
                    month_principal = 0.0
            balance -= month_principal
            year_principal += month_principal
        ds = year_interest + year_principal
        schedule.append(
            AmortYear(
                year=yr,
                beginning_balance=beginning,
                interest=year_interest,
                principal=year_principal,
                debt_service=ds,
                ending_balance=balance,
                is_io=is_io,
            )
        )

    return schedule
