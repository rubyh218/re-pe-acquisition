"""
colo_pro_forma.py -- Retail-colocation DC cash-flow engine.

Pattern: multifamily ramp-up but with cabinets instead of units. Models per-
cabinet MRR (in-place vs. market), an occupancy ramp (lease-up), value-add
fit-out that lifts MRR on refitted cabinets, plus colo-specific income lines:

  - Cross-connect MRR (per occupied cabinet * avg xc/cabinet * $/xc/mo)
  - Other operated income (remote hands, smart hands, setup -- $/occupied cab/mo)

Power is a landlord cost line (not a pass-through, unlike wholesale).  Modeled
as utility_rate * total_kw * 8760 * PUE, sized on contracted kW * occupancy.

Year buildup:
  - Effective MRR per cabinet (in-place Yr1, market trended Yr2+) + value-add uplift
  - GPR_cabinets = effective MRR * total_cabinets * 12 * occupancy
  - Cross-connect MRR + other income (occupancy-scaled)
  - Less bad debt / concessions (% of gross rent, MF-style burn-off)
  - EGI
  - Less power (utility * total_kw * occupancy * 8760 * PUE)
  - Less other OpEx (per-cabinet operating costs on total inventory; building
    must run regardless of lease-up)
  - NOI, capex, NCF unlevered
  - Debt + exit + equity flows
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from ..metrics import ReturnOnCost, compute_roc
from .models import DCColoDeal


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------

@dataclass
class ColoYearLine:
    year: int
    period_end: date
    # Stats
    occupancy: float                # avg cabinet occupancy
    occupied_cabinets: float        # avg occupied
    avg_mrr_per_cabinet: float      # blended in-place / market / uplift, $/mo
    # Revenue
    cabinet_rent: float             # GPR_cabinets * occupancy (after lease-up)
    cross_connect_rev: float
    other_income: float
    gross_revenue: float
    concessions: float              # negative
    bad_debt: float                 # negative
    egi: float
    # OpEx
    power_cost: float
    payroll: float
    rm: float
    marketing: float
    insurance: float
    other_opex: float
    re_tax: float
    mgmt_fee: float
    total_opex: float
    noi: float
    # CapEx
    fit_out_capex: float
    common_capex: float
    recurring_reserve: float
    total_capex: float
    # CF
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float


@dataclass
class ColoSourcesUses:
    purchase_price: float
    closing_costs: float
    initial_capex: float
    day_one_reserves: float
    acq_fee: float
    origination_fee: float
    lender_reserves: float
    total_uses: float
    loan_amount: float
    equity_check: float


@dataclass
class ColoExitSummary:
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
class ColoProForma:
    deal: DCColoDeal
    years: list[ColoYearLine]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: ColoSourcesUses
    exit_summary: ColoExitSummary
    equity_flows_total: list[EquityFlow]
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_cabinet: float
    all_in_basis_per_mw: float
    roc: ReturnOnCost


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def build_colo_pro_forma(deal: DCColoDeal) -> ColoProForma:
    prop = deal.property
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)
    close = deal.acquisition.close_date

    total_cabinets = prop.total_cabinets
    contracted_kw = prop.total_contracted_kw

    # In-place vs. market MRR (weighted by cabinet count)
    in_place_mrr_avg = (
        prop.in_place_gross_rent / total_cabinets / 12 if total_cabinets else 0.0
    )
    market_mrr_avg = (
        prop.market_gross_rent / total_cabinets / 12 if total_cabinets else 0.0
    )

    pre_debt: list[ColoYearLine] = []
    cumulative_renovated = 0.0
    for y_idx in range(n_years):
        y = y_idx + 1
        occ = deal.revenue.occupancy[y_idx]

        # Effective per-cabinet MRR: Yr 1 in-place, Yr 2+ market trended
        if y == 1:
            base_mrr = in_place_mrr_avg
        else:
            base_mrr = market_mrr_avg * (1 + deal.revenue.mrr_growth) ** (y - 1)

        # Value-add fit-out uplift on refitted cabinets (cumulative)
        if deal.capex.cabinets_renovated_pct and y_idx < len(deal.capex.cabinets_renovated_pct):
            cumulative_renovated += deal.capex.cabinets_renovated_pct[y_idx]
        renov_pct = min(1.0, cumulative_renovated)
        uplift_escalator = (1 + deal.revenue.mrr_growth) ** max(0, y - 1)
        mrr_uplift = deal.capex.mrr_uplift_per_cabinet * renov_pct * uplift_escalator
        avg_mrr = base_mrr + mrr_uplift

        # Occupancy-scaled cabinet revenue
        occupied_cab = total_cabinets * occ
        cabinet_rent = avg_mrr * total_cabinets * 12 * occ

        # Cross-connect revenue (per occupied cabinet)
        xc_each = deal.revenue.xc_mrr_each * (1 + deal.revenue.xc_mrr_growth) ** (y - 1)
        xc_rev = occupied_cab * deal.revenue.xc_per_cabinet * xc_each * 12

        # Other operated income
        other_each_mo = deal.revenue.other_income_per_cabinet_mo * \
                        (1 + deal.revenue.other_income_growth) ** (y - 1)
        other_inc = occupied_cab * other_each_mo * 12

        gross_rev = cabinet_rent + xc_rev + other_inc

        # MF-style burn-off concessions
        if y == 1:
            concessions = -deal.revenue.concessions_yr1 * gross_rev
        elif y == 2:
            concessions = -deal.revenue.concessions_yr1 * gross_rev * 0.5
        else:
            concessions = 0.0
        bad_debt = -deal.revenue.bad_debt * gross_rev
        egi = gross_rev + concessions + bad_debt

        # --- OpEx ---
        # Power: utility * contracted kW * occupancy * 8760 * PUE
        util = deal.opex.utility_rate_kwh * (1 + deal.opex.utility_rate_growth) ** (y - 1)
        power_kwh = contracted_kw * occ * 8760 * deal.opex.pue_uplift
        power_cost = util * power_kwh

        # Per-cabinet operating costs scale on TOTAL inventory (building runs
        # regardless of lease-up)
        ctrl_g = (1 + deal.opex.controllable_growth) ** (y - 1)
        payroll = deal.opex.payroll_per_cabinet * total_cabinets * ctrl_g
        rm = deal.opex.rm_per_cabinet * total_cabinets * ctrl_g
        marketing = deal.opex.marketing_per_cabinet * total_cabinets * ctrl_g
        insurance = deal.opex.insurance_per_cabinet * total_cabinets * ctrl_g
        other_opex = deal.opex.other_per_cabinet * total_cabinets * ctrl_g
        re_tax = deal.opex.re_tax * (1 + deal.opex.re_tax_growth) ** (y - 1)
        mgmt_fee = max(0.0, egi) * deal.opex.mgmt_fee_pct
        total_opex = (power_cost + payroll + rm + marketing + insurance
                      + other_opex + re_tax + mgmt_fee)
        noi = egi - total_opex

        # --- CapEx ---
        if deal.capex.cabinets_renovated_pct and y_idx < len(deal.capex.cabinets_renovated_pct):
            fit_out = total_cabinets * deal.capex.fit_out_per_cabinet * \
                      deal.capex.cabinets_renovated_pct[y_idx]
        else:
            fit_out = 0.0
        common_cx = deal.capex.common_capex if y == 1 else 0.0
        recurring = deal.capex.recurring_reserve_per_cabinet * total_cabinets * ctrl_g
        total_capex = fit_out + common_cx + recurring

        ncf_unlev = noi - total_capex
        period_end = date(close.year + y, close.month, close.day)

        pre_debt.append(ColoYearLine(
            year=y, period_end=period_end,
            occupancy=occ, occupied_cabinets=occupied_cab,
            avg_mrr_per_cabinet=avg_mrr,
            cabinet_rent=cabinet_rent, cross_connect_rev=xc_rev,
            other_income=other_inc, gross_revenue=gross_rev,
            concessions=concessions, bad_debt=bad_debt, egi=egi,
            power_cost=power_cost, payroll=payroll, rm=rm, marketing=marketing,
            insurance=insurance, other_opex=other_opex, re_tax=re_tax,
            mgmt_fee=mgmt_fee, total_opex=total_opex, noi=noi,
            fit_out_capex=fit_out, common_capex=common_cx,
            recurring_reserve=recurring, total_capex=total_capex,
            ncf_unlevered=ncf_unlev,
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlev,
        ))

    # --- Debt sizing on Yr 1 NOI ---
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

    # --- S&U ---
    closing_costs = deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct
    acq_fee = deal.acquisition.purchase_price * deal.equity.acq_fee_pct
    origination_fee = sizing.loan_amount * deal.debt.origination_fee_pct
    total_uses = (
        deal.acquisition.purchase_price + closing_costs + deal.acquisition.initial_capex
        + deal.acquisition.day_one_reserves + acq_fee + origination_fee + deal.debt.lender_reserves
    )
    equity_check = total_uses - sizing.loan_amount
    sources_uses = ColoSourcesUses(
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
    exit_summary = ColoExitSummary(
        exit_year=hold, exit_noi=exit_noi, exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale, cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff, net_proceeds=net_proceeds,
    )

    # --- Metrics ---
    going_in_cap = pre_debt[0].noi / deal.acquisition.purchase_price
    if deal.exit.stab_yr is not None:
        stab_idx = min(deal.exit.stab_yr - 1, len(pre_debt) - 1)
    else:
        stab_idx = min(2, len(pre_debt) - 1)
    stabilized_cap = pre_debt[stab_idx].noi / deal.acquisition.purchase_price
    all_in_basis_per_cabinet = total_uses / total_cabinets
    all_in_basis_per_mw = total_uses / prop.mw_critical

    stab_yr = stab_idx + 1
    roc = compute_roc(
        stab_noi=pre_debt[stab_idx].noi,
        exit_ftm_noi=exit_noi,
        all_in_basis=total_uses,
        stab_yr=stab_yr,
        growth_rate=deal.revenue.mrr_growth,
    )

    # --- Equity flows ---
    equity_flows: list[EquityFlow] = [EquityFlow(period=close, amount=-equity_check)]
    for i in range(hold):
        yl = pre_debt[i]
        amount = yl.ncf_levered
        if i == hold - 1:
            amount += net_proceeds
        equity_flows.append(EquityFlow(period=yl.period_end, amount=amount))

    output_years = pre_debt[: hold + (1 if deal.exit.exit_noi_basis == "forward" else 0)]

    return ColoProForma(
        deal=deal, years=output_years,
        sizing=sizing, amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses, exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap, stabilized_cap=stabilized_cap,
        all_in_basis_per_cabinet=all_in_basis_per_cabinet,
        all_in_basis_per_mw=all_in_basis_per_mw,
        roc=roc,
    )
