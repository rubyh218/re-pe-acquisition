"""
pro_forma.py — Multifamily cash-flow engine.

Builds Years 1..hold+1 of revenue, OpEx, NOI, CapEx, and computes:
  - Unlevered net cash flow
  - Sources & uses
  - Equity check sized by debt
  - Levered cash flows
  - Exit reversion (sale at exit cap, less cost of sale, less loan payoff)
  - Equity cash flows (LP/GP perspective for waterfall input)

Conventions:
  - Year 1 = first full operating year post-close (close_date + ~6 mo to year-end is ignored;
    we model annual periods starting at close_date for IRR purposes).
  - Forward exit basis: exit cap applied to Year hold+1 NOI (so we model hold+1 years).
  - Trailing exit basis: exit cap applied to Year hold NOI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from .models import Deal


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

@dataclass
class YearLine:
    year: int
    period_end: date
    # Revenue
    avg_monthly_rent: float       # blended in-place vs. market vs. premium
    gpr: float
    vacancy: float                # negative (loss)
    concessions: float            # negative
    bad_debt: float               # negative
    other_income: float
    egi: float
    # OpEx (each is a positive number; total subtracted from EGI for NOI)
    payroll: float
    rm: float
    marketing: float
    utilities: float
    insurance: float
    re_tax: float
    other_opex: float
    mgmt_fee: float
    total_opex: float
    noi: float
    # CapEx
    value_add_capex: float
    common_area_capex: float
    recurring_reserve: float
    total_capex: float
    # Cash flow
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float


@dataclass
class SourcesUses:
    # Uses
    purchase_price: float
    closing_costs: float
    initial_capex: float
    day_one_reserves: float
    acq_fee: float
    origination_fee: float
    lender_reserves: float
    total_uses: float
    # Sources
    loan_amount: float
    equity_check: float


@dataclass
class ExitSummary:
    exit_year: int
    exit_noi: float
    exit_cap: float
    gross_sale: float
    cost_of_sale: float
    loan_payoff: float
    net_proceeds: float          # to total equity (LP + GP combined)


@dataclass
class EquityFlow:
    period: date
    amount: float                # signed: contribution negative, distribution positive


@dataclass
class ProForma:
    deal: Deal
    years: list[YearLine]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: SourcesUses
    exit_summary: ExitSummary
    # Total-equity (LP+GP combined) cash flows for IRR / MOIC computation
    equity_flows_total: list[EquityFlow]
    # Going-in metrics
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_unit: float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def build_pro_forma(deal: Deal) -> ProForma:
    """Build the full pro forma + sizing + sources/uses + exit + equity flows."""
    units = deal.property.unit_count
    avg_in_place = deal.property.gpr_in_place / units / 12
    avg_market = deal.property.gpr_market / units / 12
    rg = deal.revenue.rent_growth                       # annual decimals
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)

    # --- Revenue/OpEx/NOI/CapEx pre-debt build ---
    pre_debt: list[YearLine] = []
    cumulative_renovated = 0.0
    for y_idx in range(n_years):
        y = y_idx + 1
        # Effective rent: Yr 1 = in-place; Yr 2+ = market trended forward
        if y == 1:
            avg_rent_base = avg_in_place
        else:
            growth_factor = 1.0
            for g in rg[: y - 1]:
                growth_factor *= (1 + g)
            avg_rent_base = avg_market * growth_factor

        # Renovation premium adds to whatever rent applies to the renovated share.
        if deal.capex.units_renovated_pct and y_idx < len(deal.capex.units_renovated_pct):
            cumulative_renovated += deal.capex.units_renovated_pct[y_idx]
        cumulative_renovated_capped = min(1.0, cumulative_renovated)
        # Premium escalates with rent growth too (approx — institutional convention)
        premium_escalator = 1.0
        for g in rg[: max(0, y - 1)]:
            premium_escalator *= (1 + g)
        renovation_premium_per_unit_mo = (
            deal.capex.rent_premium_per_unit_mo * cumulative_renovated_capped * premium_escalator
        )
        avg_monthly_rent = avg_rent_base + renovation_premium_per_unit_mo

        gpr = avg_monthly_rent * units * 12
        vacancy = -deal.revenue.vacancy * gpr
        bad_debt = -deal.revenue.bad_debt * gpr
        # Concessions: full Yr 1, half Yr 2, zero thereafter (institutional burn-off pattern)
        if y == 1:
            concessions = -deal.revenue.concessions_yr1 * gpr
        elif y == 2:
            concessions = -deal.revenue.concessions_yr1 * gpr * 0.5
        else:
            concessions = 0.0

        other_income = (
            deal.revenue.other_income_per_unit_mo
            * units
            * 12
            * ((1 + deal.revenue.other_income_growth) ** (y - 1))
        )
        egi = gpr + vacancy + concessions + bad_debt + other_income

        # --- OpEx (per-unit lines escalate by opex.growth) ---
        opex_growth = (1 + deal.opex.growth) ** (y - 1)
        payroll = deal.opex.payroll_per_unit * units * opex_growth
        rm = deal.opex.rm_per_unit * units * opex_growth
        marketing = deal.opex.marketing_per_unit * units * opex_growth
        utilities = deal.opex.utilities_per_unit * units * opex_growth
        insurance = deal.opex.insurance_per_unit * units * opex_growth
        other_opex = deal.opex.other_per_unit * units * opex_growth
        re_tax = deal.opex.re_tax * ((1 + deal.opex.re_tax_growth) ** (y - 1))
        mgmt_fee = egi * deal.opex.mgmt_fee_pct
        total_opex = payroll + rm + marketing + utilities + insurance + other_opex + re_tax + mgmt_fee

        noi = egi - total_opex

        # --- CapEx ---
        if deal.capex.units_renovated_pct and y_idx < len(deal.capex.units_renovated_pct):
            value_add_capex = (
                units
                * deal.capex.value_add_per_unit
                * deal.capex.units_renovated_pct[y_idx]
            )
        else:
            value_add_capex = 0.0
        common_area_capex = deal.capex.common_area_capex if y == 1 else 0.0
        recurring_reserve = (
            deal.capex.recurring_reserve_per_unit * units * opex_growth
        )
        total_capex = value_add_capex + common_area_capex + recurring_reserve

        ncf_unlevered = noi - total_capex

        period_end = date(deal.acquisition.close_date.year + y, deal.acquisition.close_date.month, deal.acquisition.close_date.day)

        pre_debt.append(YearLine(
            year=y, period_end=period_end,
            avg_monthly_rent=avg_monthly_rent,
            gpr=gpr, vacancy=vacancy, concessions=concessions, bad_debt=bad_debt,
            other_income=other_income, egi=egi,
            payroll=payroll, rm=rm, marketing=marketing, utilities=utilities,
            insurance=insurance, re_tax=re_tax, other_opex=other_opex,
            mgmt_fee=mgmt_fee, total_opex=total_opex, noi=noi,
            value_add_capex=value_add_capex, common_area_capex=common_area_capex,
            recurring_reserve=recurring_reserve, total_capex=total_capex,
            ncf_unlevered=ncf_unlevered,
            # debt fields filled below
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlevered,
        ))

    # --- Debt sizing (uses Year 1 NOI per lender convention) ---
    sizing = size_loan(
        sizing_noi=pre_debt[0].noi,
        purchase_price=deal.acquisition.purchase_price,
        debt=deal.debt,
    )
    amort = amortization_schedule(
        loan_amount=sizing.loan_amount,
        debt=deal.debt,
        years=n_years,
    )

    # --- Apply debt service to each year ---
    years_with_debt: list[YearLine] = []
    for yl, am in zip(pre_debt, amort):
        yl.debt_service = am.debt_service
        yl.interest = am.interest
        yl.principal = am.principal
        yl.loan_balance_eop = am.ending_balance
        yl.ncf_levered = yl.ncf_unlevered - am.debt_service
        years_with_debt.append(yl)

    # --- Sources & uses ---
    closing_costs = deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct
    acq_fee = deal.acquisition.purchase_price * deal.equity.acq_fee_pct
    origination_fee = sizing.loan_amount * deal.debt.origination_fee_pct

    total_uses = (
        deal.acquisition.purchase_price
        + closing_costs
        + deal.acquisition.initial_capex
        + deal.acquisition.day_one_reserves
        + acq_fee
        + origination_fee
        + deal.debt.lender_reserves
    )
    equity_check = total_uses - sizing.loan_amount
    sources_uses = SourcesUses(
        purchase_price=deal.acquisition.purchase_price,
        closing_costs=closing_costs,
        initial_capex=deal.acquisition.initial_capex,
        day_one_reserves=deal.acquisition.day_one_reserves,
        acq_fee=acq_fee,
        origination_fee=origination_fee,
        lender_reserves=deal.debt.lender_reserves,
        total_uses=total_uses,
        loan_amount=sizing.loan_amount,
        equity_check=equity_check,
    )

    # --- Exit reversion ---
    hold = deal.exit.hold_yrs
    if deal.exit.exit_noi_basis == "forward":
        exit_noi = years_with_debt[hold].noi    # Year hold+1 (0-indexed = hold)
    else:
        exit_noi = years_with_debt[hold - 1].noi
    gross_sale = exit_noi / deal.exit.exit_cap
    cost_of_sale = gross_sale * deal.exit.cost_of_sale_pct
    loan_payoff = years_with_debt[hold - 1].loan_balance_eop
    net_proceeds = gross_sale - cost_of_sale - loan_payoff
    exit_summary = ExitSummary(
        exit_year=hold,
        exit_noi=exit_noi,
        exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale,
        cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff,
        net_proceeds=net_proceeds,
    )

    # --- Going-in / stabilized metrics ---
    going_in_cap = years_with_debt[0].noi / deal.acquisition.purchase_price
    stabilized_idx = min(2, len(years_with_debt) - 1)  # Year 3 stabilized, or last if shorter
    stabilized_cap = years_with_debt[stabilized_idx].noi / deal.acquisition.purchase_price
    all_in_basis = total_uses
    all_in_basis_per_unit = all_in_basis / units

    # --- Equity cash flows (total equity = LP + GP combined) ---
    equity_flows: list[EquityFlow] = [
        EquityFlow(period=deal.acquisition.close_date, amount=-equity_check),
    ]
    for i in range(hold):
        yl = years_with_debt[i]
        amount = yl.ncf_levered
        if i == hold - 1:
            amount += net_proceeds
        equity_flows.append(EquityFlow(period=yl.period_end, amount=amount))

    # Truncate years to hold+1 (for forward) or hold (for trailing) for output clarity
    output_years = years_with_debt[: hold + (1 if deal.exit.exit_noi_basis == "forward" else 0)]

    return ProForma(
        deal=deal,
        years=output_years,
        sizing=sizing,
        amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses,
        exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap,
        stabilized_cap=stabilized_cap,
        all_in_basis_per_unit=all_in_basis_per_unit,
    )
