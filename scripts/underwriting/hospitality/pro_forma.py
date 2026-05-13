"""
pro_forma.py — Hospitality property-level USALI cash-flow engine.

Builds Yr 1..hold[+1]:
  - Operating stats: ADR, Occ, sold room-nights (less displaced rooms during PIP)
  - Departmental P&L: Rooms / F&B / Other (revenue, expense, profit)
  - Undistributed: G&A, S&M, R&M, utilities (PAR-based) + franchise fee
  - GOP = total departmental profit - undistributed
  - Less mgmt fee (% of total revenue) -> IBFC
  - Less fixed charges (RE tax + insurance) -> NOI (pre-reserve)
  - Less FF&E reserve (% of total revenue) -> NOI (cap-rate basis)
  - PIP capex below NOI (NCF unlevered)
  - Debt sizing on Yr 1 NOI (post-reserve), exit reversion, equity flows

Convention notes:
  - Cap rate NOI is AFTER FF&E reserve (institutional standard).
  - Displacement = avg keys out x 365 x Occ revenue lost during PIP years
    (modeled by reducing inventory: sold_rn = (keys - displaced) x 365 x Occ).
  - Mgmt fee is % of total revenue (base only; incentive fees ignored).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from ..metrics import ReturnOnCost, compute_roc
from .models import HotelDeal


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------

@dataclass
class HotelYearLine:
    year: int
    period_end: date
    # Operating stats
    adr: float
    occupancy: float
    avg_keys_available: float       # keys less displacement (avg over year)
    sold_room_nights: float
    revpar: float                   # rooms revenue / available room-nights (full inventory)
    # Revenue
    rooms_revenue: float
    fb_revenue: float
    other_revenue: float
    total_revenue: float
    # Departmental expense
    rooms_expense: float
    fb_expense: float
    other_expense: float
    total_dept_expense: float
    total_dept_profit: float
    # Undistributed
    ga: float
    sm: float
    rm: float
    utilities: float
    franchise_fee: float
    total_undistributed: float
    gop: float
    # Mgmt + fixed
    mgmt_fee: float
    ibfc: float                     # income before fixed charges
    re_tax: float
    insurance: float
    total_fixed: float
    noi_pre_reserve: float
    # Reserve + NOI for cap
    ffe_reserve: float
    noi: float                      # post-reserve, cap-rate basis
    # CapEx (PIP) + cash flow
    pip_capex: float
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float


@dataclass
class HotelSourcesUses:
    purchase_price: float
    closing_costs: float
    initial_capex: float            # day-one capex (separate from PIP schedule)
    day_one_reserves: float
    acq_fee: float
    origination_fee: float
    lender_reserves: float
    total_uses: float
    loan_amount: float
    equity_check: float


@dataclass
class HotelExitSummary:
    exit_year: int
    exit_noi: float
    exit_cap: float
    gross_sale: float
    cost_of_sale: float
    loan_payoff: float
    net_proceeds: float


@dataclass
class EquityFlow:
    period: date
    amount: float


@dataclass
class HotelProForma:
    deal: HotelDeal
    years: list[HotelYearLine]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: HotelSourcesUses
    exit_summary: HotelExitSummary
    equity_flows_total: list[EquityFlow]
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_key: float
    roc: ReturnOnCost


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _displaced_keys(deal: HotelDeal, year_idx: int) -> float:
    """Avg keys out of inventory for year y (0-indexed). 0 if no PIP that year."""
    if deal.capex.pip_total <= 0 or not deal.capex.pip_displacement_keys:
        return 0.0
    if year_idx >= len(deal.capex.pip_displacement_keys):
        return 0.0
    return float(deal.capex.pip_displacement_keys[year_idx])


def _pip_spend(deal: HotelDeal, year_idx: int) -> float:
    if deal.capex.pip_total <= 0 or not deal.capex.pip_schedule_pct:
        return 0.0
    if year_idx >= len(deal.capex.pip_schedule_pct):
        return 0.0
    return deal.capex.pip_total * deal.capex.pip_schedule_pct[year_idx]


def build_hotel_pro_forma(deal: HotelDeal) -> HotelProForma:
    prop = deal.property
    op = deal.operating
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)
    close = deal.acquisition.close_date
    available_rn_full = prop.keys * 365

    pre_debt: list[HotelYearLine] = []
    for y_idx in range(n_years):
        y = y_idx + 1

        # --- Operating stats ---
        adr = op.adr_yr1 * (1 + op.adr_growth) ** (y - 1)
        occ = op.occupancy[y_idx]
        displaced = _displaced_keys(deal, y_idx)
        avg_keys = prop.keys - displaced
        sold_rn = avg_keys * 365 * occ
        revpar = (sold_rn * adr) / available_rn_full if available_rn_full else 0.0

        # --- Revenue ---
        rooms_rev = sold_rn * adr
        fb_rev = rooms_rev * op.fb_revenue_pct_of_rooms
        other_rev = rooms_rev * op.other_revenue_pct_of_rooms
        total_rev = rooms_rev + fb_rev + other_rev

        # --- Departmental expense ---
        rooms_exp = rooms_rev * op.rooms_expense_pct
        fb_exp = fb_rev * (1 - op.fb_margin)
        other_exp = other_rev * (1 - op.other_margin)
        total_dept_exp = rooms_exp + fb_exp + other_exp
        total_dept_profit = total_rev - total_dept_exp

        # --- Undistributed (PAR-based; growth on PAR) ---
        und_growth = (1 + deal.opex.undistributed_growth) ** (y - 1)
        ga = deal.opex.ga_par * prop.keys * und_growth
        sm = deal.opex.sm_par * prop.keys * und_growth
        rm = deal.opex.rm_par * prop.keys * und_growth
        utilities = deal.opex.utilities_par * prop.keys * und_growth
        franchise = rooms_rev * deal.opex.franchise_fee_pct
        total_und = ga + sm + rm + utilities + franchise
        gop = total_dept_profit - total_und

        # --- Mgmt + fixed ---
        mgmt = total_rev * deal.opex.mgmt_fee_pct
        ibfc = gop - mgmt
        re_tax = deal.opex.re_tax * (1 + deal.opex.re_tax_growth) ** (y - 1)
        insurance = deal.opex.insurance_par * prop.keys * und_growth
        total_fixed = re_tax + insurance
        noi_pre = ibfc - total_fixed

        # --- Reserve + cap-rate NOI ---
        reserve = total_rev * deal.opex.ffe_reserve_pct
        noi = noi_pre - reserve

        # --- CapEx (PIP only; reserve already deducted above) ---
        pip = _pip_spend(deal, y_idx)
        ncf_unlev = noi - pip
        period_end = date(close.year + y, close.month, close.day)

        pre_debt.append(HotelYearLine(
            year=y, period_end=period_end,
            adr=adr, occupancy=occ, avg_keys_available=avg_keys,
            sold_room_nights=sold_rn, revpar=revpar,
            rooms_revenue=rooms_rev, fb_revenue=fb_rev, other_revenue=other_rev,
            total_revenue=total_rev,
            rooms_expense=rooms_exp, fb_expense=fb_exp, other_expense=other_exp,
            total_dept_expense=total_dept_exp, total_dept_profit=total_dept_profit,
            ga=ga, sm=sm, rm=rm, utilities=utilities, franchise_fee=franchise,
            total_undistributed=total_und, gop=gop,
            mgmt_fee=mgmt, ibfc=ibfc,
            re_tax=re_tax, insurance=insurance, total_fixed=total_fixed,
            noi_pre_reserve=noi_pre, ffe_reserve=reserve, noi=noi,
            pip_capex=pip, ncf_unlevered=ncf_unlev,
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlev,
        ))

    # --- Debt sizing on Yr 1 NOI (post-reserve) ---
    sizing = size_loan(
        sizing_noi=pre_debt[0].noi,
        purchase_price=deal.acquisition.purchase_price,
        debt=deal.debt,
    )
    amort = amortization_schedule(loan_amount=sizing.loan_amount, debt=deal.debt, years=n_years)

    for yl, am in zip(pre_debt, amort):
        yl.debt_service = am.debt_service
        yl.interest = am.interest
        yl.principal = am.principal
        yl.loan_balance_eop = am.ending_balance
        yl.ncf_levered = yl.ncf_unlevered - am.debt_service

    # --- Sources & uses ---
    closing_costs = deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct
    acq_fee = deal.acquisition.purchase_price * deal.equity.acq_fee_pct
    origination_fee = sizing.loan_amount * deal.debt.origination_fee_pct
    total_uses = (
        deal.acquisition.purchase_price + closing_costs + deal.acquisition.initial_capex
        + deal.acquisition.day_one_reserves + acq_fee + origination_fee + deal.debt.lender_reserves
    )
    equity_check = total_uses - sizing.loan_amount
    sources_uses = HotelSourcesUses(
        purchase_price=deal.acquisition.purchase_price, closing_costs=closing_costs,
        initial_capex=deal.acquisition.initial_capex, day_one_reserves=deal.acquisition.day_one_reserves,
        acq_fee=acq_fee, origination_fee=origination_fee, lender_reserves=deal.debt.lender_reserves,
        total_uses=total_uses, loan_amount=sizing.loan_amount, equity_check=equity_check,
    )

    # --- Exit ---
    hold = deal.exit.hold_yrs
    if deal.exit.exit_noi_basis == "forward":
        exit_noi = pre_debt[hold].noi
    else:
        exit_noi = pre_debt[hold - 1].noi
    gross_sale = exit_noi / deal.exit.exit_cap
    cost_of_sale = gross_sale * deal.exit.cost_of_sale_pct
    loan_payoff = pre_debt[hold - 1].loan_balance_eop
    net_proceeds = gross_sale - cost_of_sale - loan_payoff
    exit_summary = HotelExitSummary(
        exit_year=hold, exit_noi=exit_noi, exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale, cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff, net_proceeds=net_proceeds,
    )

    # --- Metrics ---
    going_in_cap = pre_debt[0].noi / deal.acquisition.purchase_price
    if deal.exit.stab_yr is not None:
        stabilized_idx = min(deal.exit.stab_yr - 1, len(pre_debt) - 1)
    else:
        stabilized_idx = min(2, len(pre_debt) - 1)
    stabilized_cap = pre_debt[stabilized_idx].noi / deal.acquisition.purchase_price
    all_in_basis_per_key = total_uses / prop.keys

    # --- 3-basis ROC (ADR growth proxies operating growth) ---
    stab_yr = stabilized_idx + 1
    roc = compute_roc(
        yr1_noi=pre_debt[0].noi,
        stab_noi=pre_debt[stabilized_idx].noi,
        exit_ftm_noi=exit_noi,
        all_in_basis=total_uses,
        stab_yr=stab_yr,
        growth_rate=deal.operating.adr_growth,
    )

    # --- Equity flows (Day 0 contribution, then NCF levered; exit added to last hold year) ---
    equity_flows: list[EquityFlow] = [EquityFlow(period=close, amount=-equity_check)]
    for i in range(hold):
        yl = pre_debt[i]
        amount = yl.ncf_levered
        if i == hold - 1:
            amount += net_proceeds
        equity_flows.append(EquityFlow(period=yl.period_end, amount=amount))

    output_years = pre_debt[: hold + (1 if deal.exit.exit_noi_basis == "forward" else 0)]

    return HotelProForma(
        deal=deal, years=output_years,
        sizing=sizing, amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses, exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap, stabilized_cap=stabilized_cap,
        all_in_basis_per_key=all_in_basis_per_key,
        roc=roc,
    )
