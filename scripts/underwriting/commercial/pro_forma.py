"""
pro_forma.py — Commercial property-level cash-flow engine.

Builds Yr 1..hold[+1]:
  - Aggregates per-lease CFs (rent / free rent / recoveries / TI / LC)
  - General-vacancy reserve (credit loss + unmodeled downtime)
  - Property OpEx (recoverable pool + non-recoverable + mgmt fee on EGI)
  - NOI, capex, NCF unlevered
  - Debt sizing (reuses ../debt_sizing) on Yr 1 NOI
  - Exit reversion on Yr hold (trailing) or Yr hold+1 (forward) NOI
  - Equity flows ready for the shared waterfall

Convention notes:
  - Year 1 = first 12 months from close_date.
  - Recoveries are income (reduce EGI deduction). Lease's pro-rata × recoverable pool.
  - Mgmt fee = pct of EGI (institutional default 3%).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from ..metrics import ReturnOnCost, compute_roc
from .lease_cf import LeaseYear, lease_cash_flow, recoverable_pool_total
from .models import CommercialDeal


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------

@dataclass
class CommercialYearLine:
    year: int
    period_end: date
    # Revenue
    gross_rent: float           # sum of lease base_rent (after free rent burn)
    free_rent: float            # negative
    recoveries: float           # tenant reimbursements
    pct_rent: float             # retail overage rent (positive)
    general_vacancy: float      # negative (credit/downtime reserve on gross rent)
    egi: float
    # OpEx
    recoverable_opex: float     # total recoverable pool (positive)
    non_recoverable_opex: float
    mgmt_fee: float
    total_opex: float
    noi: float
    # CapEx
    ti: float
    lc: float
    building_capex: float       # initial building capex (Yr 1) + recurring reserves
    total_capex: float
    # CF
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float
    # Occupancy metrics
    avg_occupancy_pct: float


@dataclass
class CommercialSourcesUses:
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
class CommercialExitSummary:
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
class RolloverYear:
    year: int
    sf_rolling: int
    in_place_rent_rolling: float    # annual $ rolling at in-place rate
    market_rent_at_roll: float      # annual $ on rolling SF at market
    mtm_spread_pct: float           # (market - in_place) / in_place; 0 if no roll


@dataclass
class CommercialProForma:
    deal: CommercialDeal
    years: list[CommercialYearLine]
    per_lease_years: dict[str, list[LeaseYear]]   # keyed by tenant (suite-disambiguated if needed)
    rollover_schedule: list[RolloverYear]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: CommercialSourcesUses
    exit_summary: CommercialExitSummary
    equity_flows_total: list[EquityFlow]
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_sf: float
    roc: ReturnOnCost


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def build_commercial_pro_forma(deal: CommercialDeal) -> CommercialProForma:
    prop = deal.property
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)
    close = deal.acquisition.close_date

    # --- 1. Per-lease CFs ---
    per_lease: dict[str, list[LeaseYear]] = {}
    for lease in prop.rent_roll:
        key = f"{lease.tenant}" + (f" / {lease.suite}" if lease.suite else "")
        # Disambiguate duplicates
        if key in per_lease:
            n = sum(1 for k in per_lease if k.startswith(key))
            key = f"{key} #{n + 1}"
        per_lease[key] = lease_cash_flow(
            lease=lease, market=deal.market, opex=deal.opex,
            total_rba=prop.total_rba, close_date=close, n_years=n_years,
        )

    # --- 2. Pre-debt year-by-year build ---
    # Reserves are treated as below-the-line capex (matches multifamily engine).
    pre_debt: list[CommercialYearLine] = []
    for y_idx in range(n_years):
        y = y_idx + 1
        gross_rent = sum(lys[y_idx].base_rent for lys in per_lease.values())
        free_rent = sum(lys[y_idx].free_rent for lys in per_lease.values())
        recoveries = sum(lys[y_idx].recoveries for lys in per_lease.values())
        pct_rent = sum(lys[y_idx].pct_rent for lys in per_lease.values())
        ti = sum(lys[y_idx].ti for lys in per_lease.values())
        lc = sum(lys[y_idx].lc for lys in per_lease.values())
        avg_occ_sf = sum(
            lease.sf * lys[y_idx].occupied_months / 12
            for lease, lys in zip(prop.rent_roll, per_lease.values())
        )
        avg_occupancy_pct = avg_occ_sf / prop.total_rba

        general_vacancy = -prop.general_vacancy_pct * gross_rent
        egi = gross_rent + free_rent + recoveries + pct_rent + general_vacancy

        recoverable = recoverable_pool_total(deal.opex, prop.total_rba, y)
        non_rec_growth = (1 + deal.opex.non_recoverable_growth) ** (y - 1)
        non_recoverable = deal.opex.non_recoverable_psf * prop.total_rba * non_rec_growth
        mgmt_fee = max(0.0, egi) * deal.opex.mgmt_fee_pct
        total_opex = recoverable + non_recoverable + mgmt_fee
        noi = egi - total_opex

        building_capex = deal.capex.initial_building_capex if y == 1 else 0.0
        recurring_reserve = deal.capex.recurring_reserve_psf * prop.total_rba * non_rec_growth
        total_capex = ti + lc + building_capex + recurring_reserve

        ncf_unlevered = noi - total_capex
        period_end = date(close.year + y, close.month, close.day)

        pre_debt.append(CommercialYearLine(
            year=y, period_end=period_end,
            gross_rent=gross_rent, free_rent=free_rent, recoveries=recoveries,
            pct_rent=pct_rent,
            general_vacancy=general_vacancy, egi=egi,
            recoverable_opex=recoverable, non_recoverable_opex=non_recoverable,
            mgmt_fee=mgmt_fee, total_opex=total_opex, noi=noi,
            ti=ti, lc=lc, building_capex=building_capex + recurring_reserve,
            total_capex=total_capex,
            ncf_unlevered=ncf_unlevered,
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlevered,
            avg_occupancy_pct=avg_occupancy_pct,
        ))

    # --- 3. Debt sizing on Yr 1 NOI ---
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

    # --- 4. Sources & uses ---
    closing_costs = deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct
    acq_fee = deal.acquisition.purchase_price * deal.equity.acq_fee_pct
    origination_fee = sizing.loan_amount * deal.debt.origination_fee_pct
    total_uses = (
        deal.acquisition.purchase_price + closing_costs + deal.acquisition.initial_capex
        + deal.acquisition.day_one_reserves + acq_fee + origination_fee + deal.debt.lender_reserves
    )
    equity_check = total_uses - sizing.loan_amount
    sources_uses = CommercialSourcesUses(
        purchase_price=deal.acquisition.purchase_price, closing_costs=closing_costs,
        initial_capex=deal.acquisition.initial_capex, day_one_reserves=deal.acquisition.day_one_reserves,
        acq_fee=acq_fee, origination_fee=origination_fee, lender_reserves=deal.debt.lender_reserves,
        total_uses=total_uses, loan_amount=sizing.loan_amount, equity_check=equity_check,
    )

    # --- 5. Exit reversion ---
    hold = deal.exit.hold_yrs
    if deal.exit.exit_noi_basis == "forward":
        exit_noi = pre_debt[hold].noi
    else:
        exit_noi = pre_debt[hold - 1].noi
    gross_sale = exit_noi / deal.exit.exit_cap
    cost_of_sale = gross_sale * deal.exit.cost_of_sale_pct
    loan_payoff = pre_debt[hold - 1].loan_balance_eop
    net_proceeds = gross_sale - cost_of_sale - loan_payoff
    exit_summary = CommercialExitSummary(
        exit_year=hold, exit_noi=exit_noi, exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale, cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff, net_proceeds=net_proceeds,
    )

    # --- 6. Metrics ---
    going_in_cap = pre_debt[0].noi / deal.acquisition.purchase_price

    # Pick stabilization year:
    #   1) Honor explicit Exit.stab_yr if set.
    #   2) Else auto-pick first year (within hold) with rollover_sf / RBA < 5%
    #      AND year >= 2 (Yr 1 is in-place, never "stabilized" yet).
    #   3) Else fall back to min(Yr 3, hold).
    rba = prop.total_rba
    rolling_sf_by_yr = [
        sum(lys[y_idx].rolling_sf for lys in per_lease.values())
        for y_idx in range(len(pre_debt))
    ]
    if deal.exit.stab_yr is not None:
        stabilized_idx = min(deal.exit.stab_yr - 1, len(pre_debt) - 1)
    else:
        low_rollover_idx = next(
            (i for i in range(1, min(hold, len(pre_debt)))
             if rba > 0 and (rolling_sf_by_yr[i] / rba) < 0.05),
            None,
        )
        if low_rollover_idx is not None:
            stabilized_idx = low_rollover_idx
        else:
            stabilized_idx = min(2, len(pre_debt) - 1)
    stabilized_cap = pre_debt[stabilized_idx].noi / deal.acquisition.purchase_price
    all_in_basis_per_sf = total_uses / prop.total_rba

    # --- 3-basis ROC (use market.escalation as proxy for organic growth) ---
    stab_yr = stabilized_idx + 1
    growth_rate = getattr(deal.market, "new_escalation_pct", 0.03)
    roc = compute_roc(
        stab_noi=pre_debt[stabilized_idx].noi,
        exit_ftm_noi=exit_noi,
        all_in_basis=total_uses,
        stab_yr=stab_yr,
        growth_rate=growth_rate,
    )

    # --- 7. Equity flows ---
    equity_flows: list[EquityFlow] = [EquityFlow(period=close, amount=-equity_check)]
    for i in range(hold):
        yl = pre_debt[i]
        amount = yl.ncf_levered
        if i == hold - 1:
            amount += net_proceeds
        equity_flows.append(EquityFlow(period=yl.period_end, amount=amount))

    output_years = pre_debt[: hold + (1 if deal.exit.exit_noi_basis == "forward" else 0)]

    # --- 8. Rollover schedule (aggregated per hold year) ---
    rollover: list[RolloverYear] = []
    for y_idx in range(len(output_years)):
        sf = sum(lys[y_idx].rolling_sf for lys in per_lease.values())
        in_place = sum(lys[y_idx].rolling_in_place_rent for lys in per_lease.values())
        mkt = sum(lys[y_idx].market_rent_at_roll for lys in per_lease.values())
        spread = (mkt - in_place) / in_place if in_place > 0 else 0.0
        rollover.append(RolloverYear(
            year=y_idx + 1, sf_rolling=sf,
            in_place_rent_rolling=in_place,
            market_rent_at_roll=mkt,
            mtm_spread_pct=spread,
        ))

    return CommercialProForma(
        deal=deal, years=output_years, per_lease_years=per_lease,
        rollover_schedule=rollover,
        sizing=sizing, amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses, exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap, stabilized_cap=stabilized_cap,
        all_in_basis_per_sf=all_in_basis_per_sf,
        roc=roc,
    )
