"""
wholesale_pro_forma.py -- Wholesale DC property-level cash-flow engine.

Pattern: lease-by-lease (like commercial) but the denominator is critical MW
and rents are $/kW/month. Annual periods (no mid-year escalation drift --
wholesale operators bill on lease anniversaries with simple compounding).

Year buildup:
  - Per-contract base rent (annual, escalated)
  - Free rent abatement
  - Power margin income (partial pass-through contracts only; landlord earns
    a small margin on tenant-billed utility)
  - General vacancy / credit reserve (% of gross rent)
  - Property OpEx (controllable + RE tax + common power + non-recoverable + mgmt)
  - NOI, capex, NCF unlevered
  - Debt sizing on Yr 1 NOI, exit reversion, equity flows
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from ..metrics import ReturnOnCost, compute_roc
from .models import (
    Contract,
    DCWholesaleDeal,
    DCWholesaleMarket,
    DCWholesaleOpEx,
)


# ---------------------------------------------------------------------------
# Per-contract output
# ---------------------------------------------------------------------------

@dataclass
class ContractYear:
    year: int                       # 1-indexed hold year
    base_rent: float                # gross contractual rent (positive)
    free_rent: float                # negative
    power_margin: float             # positive (landlord margin on partial pass-through)
    ti: float                       # positive expense
    lc: float                       # positive expense
    occupied_months: float          # 0..12
    rolling_mw: float               # MW rolling this year
    rolling_in_place_rent: float    # annual $ on rolling MW at in-place rate
    market_rent_at_roll: float      # annual $ on rolling MW at market


@dataclass
class WholesaleYearLine:
    year: int
    period_end: date
    # Revenue
    gross_rent: float
    free_rent: float
    power_margin: float
    general_vacancy: float
    egi: float
    # OpEx
    security: float
    mep_staffing: float
    insurance: float
    common_power: float
    re_tax: float
    non_recoverable: float
    mgmt_fee: float
    total_opex: float
    noi: float
    # CapEx
    ti: float
    lc: float
    building_capex: float       # initial + recurring reserves
    total_capex: float
    # CF
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float
    # MW metrics
    leased_mw_avg: float
    utilization_pct: float          # leased_mw_avg / mw_commissioned


@dataclass
class WholesaleSourcesUses:
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
class WholesaleExitSummary:
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
class WholesaleRolloverYear:
    year: int
    mw_rolling: float
    in_place_rent_rolling: float
    market_rent_at_roll: float
    mtm_spread_pct: float


@dataclass
class WholesaleProForma:
    deal: DCWholesaleDeal
    years: list[WholesaleYearLine]
    per_contract_years: dict[str, list[ContractYear]]
    rollover_schedule: list[WholesaleRolloverYear]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: WholesaleSourcesUses
    exit_summary: WholesaleExitSummary
    equity_flows_total: list[EquityFlow]
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_mw: float
    roc: ReturnOnCost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    total = d.month + months - 1
    y = d.year + total // 12
    m = total % 12 + 1
    from calendar import monthrange
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def _months_between(d1: date, d2: date) -> float:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) + (d2.day - d1.day) / 30.4375


def _year_window(close: date, year: int) -> tuple[date, date]:
    return _add_months(close, 12 * (year - 1)), _add_months(close, 12 * year)


def _overlap_months(a_start: date, a_end: date, b_start: date, b_end: date) -> float:
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if hi <= lo:
        return 0.0
    return _months_between(lo, hi)


# ---------------------------------------------------------------------------
# Per-contract CF
# ---------------------------------------------------------------------------

@dataclass
class _ContractSegment:
    start: date
    end: date
    rent_kw_mo_at_start: float       # $/kW/mo
    escalation_pct: float
    mw: float
    free_rent_mo: int
    ti_total: float                  # one-time at segment start
    lc_total: float                  # one-time at segment start
    power_pass_through: str          # carried forward from contract; renewal/new inherits


def _segment_year_cf(seg: _ContractSegment, close: date, year: int) -> dict:
    win_start, win_end = _year_window(close, year)
    overlap_mo = _overlap_months(win_start, win_end, seg.start, seg.end)
    if overlap_mo <= 0:
        return {
            "base_rent": 0.0, "free_rent": 0.0, "ti": 0.0, "lc": 0.0,
            "occupied_months": 0.0, "mw_occupied_months": 0.0,
            "pass_through": seg.power_pass_through,
        }

    # Annual rent: rent_kw_mo * mw * 1000 * 12. Escalates on each anniversary
    # of seg.start. Wholesale convention: annual step on contract anniversary.
    # We split the overlap into pre-anniversary + post-anniversary chunks.
    base_rent = 0.0
    cursor = max(win_start, seg.start)
    seg_end_in_window = min(seg.end, win_end)
    while cursor < seg_end_in_window:
        months_since_start = _months_between(seg.start, cursor)
        completed_years = int(months_since_start // 12 + 1e-9)
        next_anniv = _add_months(seg.start, (completed_years + 1) * 12)
        chunk_end = min(next_anniv, seg_end_in_window)
        chunk_mo = _months_between(cursor, chunk_end)
        if chunk_mo <= 0:
            break
        annual_rent = seg.rent_kw_mo_at_start * seg.mw * 1000 * 12 * \
                      (1 + seg.escalation_pct) ** completed_years
        base_rent += annual_rent * (chunk_mo / 12)
        cursor = chunk_end

    # Free rent abates at year-1 rate over the first free_rent_mo months
    free_rent = 0.0
    if seg.free_rent_mo > 0:
        free_end = _add_months(seg.start, seg.free_rent_mo)
        free_mo = _overlap_months(win_start, win_end, seg.start, free_end)
        if free_mo > 0:
            annual_rent_yr1 = seg.rent_kw_mo_at_start * seg.mw * 1000 * 12
            free_rent = -annual_rent_yr1 * (free_mo / 12)

    ti = seg.ti_total if (win_start <= seg.start < win_end) else 0.0
    lc = seg.lc_total if (win_start <= seg.start < win_end) else 0.0

    return {
        "base_rent": base_rent,
        "free_rent": free_rent,
        "ti": ti,
        "lc": lc,
        "occupied_months": overlap_mo,
        "mw_occupied_months": overlap_mo * seg.mw,
        "pass_through": seg.power_pass_through,
    }


def _build_contract_segments(
    contract: Contract,
    market: DCWholesaleMarket,
    close: date,
    hold_end: date,
    outcome: str,                    # "renewal" or "new"
) -> tuple[list[_ContractSegment], list[tuple[date, date]]]:
    """Build the segment chain for one outcome path through the hold."""
    segments: list[_ContractSegment] = []
    downtimes: list[tuple[date, date]] = []

    # In-place segment
    segments.append(_ContractSegment(
        start=close, end=contract.lease_end,
        rent_kw_mo_at_start=contract.base_rent_kw_mo,
        escalation_pct=contract.escalation_pct,
        mw=contract.mw_leased,
        free_rent_mo=contract.free_rent_remaining_mo,
        ti_total=0.0, lc_total=0.0,
        power_pass_through=contract.power_pass_through,
    ))

    cursor = contract.lease_end
    while cursor < hold_end:
        if outcome == "new":
            new_start = _add_months(cursor, market.downtime_mo)
            downtimes.append((cursor, new_start))
            term_yrs = market.new_lease_term_yrs
            escal = market.new_escalation_pct
            free = market.new_free_rent_mo
            ti_kw = market.new_ti_kw
            lc_pct = market.new_lc_pct
        else:
            new_start = cursor
            term_yrs = market.renewal_lease_term_yrs
            escal = market.renewal_escalation_pct
            free = market.renewal_free_rent_mo
            ti_kw = market.renewal_ti_kw
            lc_pct = market.renewal_lc_pct

        if new_start >= hold_end:
            break

        yrs_from_close = _months_between(close, new_start) / 12
        mkt_rent_kw_mo = (contract.market_rent_kw_mo_override or market.market_rent_kw_mo) * \
                         (1 + market.market_rent_growth) ** yrs_from_close
        new_end = _add_months(new_start, term_yrs * 12)
        kw_total = contract.mw_leased * 1000
        ti_total = ti_kw * kw_total
        first_yr_rent = mkt_rent_kw_mo * kw_total * 12
        lc_total = lc_pct * first_yr_rent * term_yrs

        segments.append(_ContractSegment(
            start=new_start, end=new_end,
            rent_kw_mo_at_start=mkt_rent_kw_mo,
            escalation_pct=escal, mw=contract.mw_leased,
            free_rent_mo=free, ti_total=ti_total, lc_total=lc_total,
            power_pass_through=contract.power_pass_through,
        ))
        cursor = new_end

    return segments, downtimes


def _power_margin_year(
    contract: Contract,
    segments: list[_ContractSegment],
    market: DCWholesaleMarket,
    close: date,
    year: int,
) -> float:
    """Landlord margin on partial-pass-through power.

    For partial pass-through: landlord bills tenant at
    utility_rate * margin_multiplier and earns the (margin - 1) spread.
    Sized on leased MW at IT load, grossed up by PUE.

    For full pass-through: 0 margin.
    For none (rare): 0 margin (and tenant pays no power -> separately captured
    in common_power line as landlord bears full cost).
    """
    if contract.power_pass_through != "partial":
        return 0.0
    if market.power_margin_multiplier <= 1.0:
        return 0.0
    # Average MW occupied this year across the segments (each segment is for
    # this contract; same MW size, gated by occupied months).
    win_start, win_end = _year_window(close, year)
    occupied_mw_months = 0.0
    for seg in segments:
        ov = _overlap_months(win_start, win_end, seg.start, seg.end)
        occupied_mw_months += ov * seg.mw
    avg_mw = occupied_mw_months / 12

    # Margin is on IT-only kWh (NOT total facility kWh including cooling).
    # Convention: under partial pass-through, the tenant is metered on their
    # IT consumption and pays utility_rate * (1 + margin) on that. Cooling
    # overhead (PUE > 1.0) is the landlord's cost and is captured in
    # DCWholesaleOpEx.common_power_per_mw, not here. So we deliberately
    # size on IT MW only (i.e., effective PUE factor of 1.0 in this calc).
    util_rate = market.utility_rate_kwh * (1 + market.utility_rate_growth) ** (year - 1)
    annual_it_kwh = avg_mw * 1000 * 8760
    return (market.power_margin_multiplier - 1.0) * util_rate * annual_it_kwh


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def build_wholesale_pro_forma(deal: DCWholesaleDeal) -> WholesaleProForma:
    prop = deal.property
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)
    close = deal.acquisition.close_date
    hold_end = _add_months(close, n_years * 12)

    # --- 1. Per-contract CFs (probability-blended renewal vs new) ---
    per_contract: dict[str, list[ContractYear]] = {}
    contract_segments_renew: dict[str, list[_ContractSegment]] = {}
    contract_segments_new: dict[str, list[_ContractSegment]] = {}

    for c in prop.contracts:
        key = f"{c.tenant}" + (f" / {c.suite}" if c.suite else "")
        if key in per_contract:
            n = sum(1 for k in per_contract if k.startswith(key))
            key = f"{key} #{n+1}"

        renew_segs, renew_dts = _build_contract_segments(c, deal.market, close, hold_end, "renewal")
        new_segs, new_dts = _build_contract_segments(c, deal.market, close, hold_end, "new")
        contract_segments_renew[key] = renew_segs
        contract_segments_new[key] = new_segs

        p_renew = c.renewal_prob_override if c.renewal_prob_override is not None else deal.market.renewal_prob

        years_out: list[ContractYear] = []
        for y in range(1, n_years + 1):
            r_cf = {"base_rent": 0.0, "free_rent": 0.0, "ti": 0.0, "lc": 0.0,
                    "occupied_months": 0.0, "mw_occupied_months": 0.0}
            for seg in renew_segs:
                sc = _segment_year_cf(seg, close, y)
                for k in r_cf:
                    r_cf[k] += sc[k]
            n_cf = {"base_rent": 0.0, "free_rent": 0.0, "ti": 0.0, "lc": 0.0,
                    "occupied_months": 0.0, "mw_occupied_months": 0.0}
            for seg in new_segs:
                sc = _segment_year_cf(seg, close, y)
                for k in n_cf:
                    n_cf[k] += sc[k]

            blend = lambda k: p_renew * r_cf[k] + (1 - p_renew) * n_cf[k]
            base_rent = blend("base_rent")
            free_rent = blend("free_rent")
            ti = blend("ti")
            lc = blend("lc")
            occ_mo = blend("occupied_months")

            # Power margin: compute against blended segments (use renew for
            # simplicity since both outcomes carry the same pass-through type)
            pm_r = _power_margin_year(c, renew_segs, deal.market, close, y)
            pm_n = _power_margin_year(c, new_segs, deal.market, close, y)
            pm = p_renew * pm_r + (1 - p_renew) * pm_n

            # Rollover detection
            win_start, win_end = _year_window(close, y)
            rolling_mw = 0.0
            rolling_in_place_rent = 0.0
            market_rent_at_roll = 0.0
            if win_start <= c.lease_end < win_end:
                rolling_mw = c.mw_leased
                yrs_in_place = max(0.0, _months_between(close, c.lease_end) / 12)
                rolling_in_place_rent = c.base_rent_kw_mo * c.mw_leased * 1000 * 12 * \
                                        (1 + c.escalation_pct) ** yrs_in_place
                yrs_from_close = _months_between(close, c.lease_end) / 12
                mkt_kw_mo = (c.market_rent_kw_mo_override or deal.market.market_rent_kw_mo) * \
                            (1 + deal.market.market_rent_growth) ** yrs_from_close
                market_rent_at_roll = mkt_kw_mo * c.mw_leased * 1000 * 12

            years_out.append(ContractYear(
                year=y, base_rent=base_rent, free_rent=free_rent,
                power_margin=pm, ti=ti, lc=lc, occupied_months=occ_mo,
                rolling_mw=rolling_mw,
                rolling_in_place_rent=rolling_in_place_rent,
                market_rent_at_roll=market_rent_at_roll,
            ))

        per_contract[key] = years_out

    # --- 2. Pre-debt year-by-year build ---
    pre_debt: list[WholesaleYearLine] = []
    for y_idx in range(n_years):
        y = y_idx + 1
        gross_rent = sum(cys[y_idx].base_rent for cys in per_contract.values())
        free_rent = sum(cys[y_idx].free_rent for cys in per_contract.values())
        power_margin = sum(cys[y_idx].power_margin for cys in per_contract.values())
        ti = sum(cys[y_idx].ti for cys in per_contract.values())
        lc = sum(cys[y_idx].lc for cys in per_contract.values())

        # Average leased MW this year (used for utilization metric + OpEx
        # sizing on leased MW). For OpEx we use mw_critical so that operating
        # costs do not collapse with vacancy (institutional convention -- the
        # building must run regardless of lease-up).
        leased_mw_months = 0.0
        for c, cys in zip(prop.contracts, per_contract.values()):
            leased_mw_months += cys[y_idx].occupied_months * c.mw_leased
        leased_mw_avg = leased_mw_months / 12
        utilization = leased_mw_avg / prop.mw_commissioned if prop.mw_commissioned else 0.0

        # General vacancy / credit loss reserve (configurable on
        # DCWholesaleMarket; default 1% for hyperscale-grade tenants).
        general_vacancy = -deal.market.general_vacancy_pct * gross_rent
        egi = gross_rent + free_rent + power_margin + general_vacancy

        # --- OpEx (sized on mw_critical) ---
        ctrl_g = (1 + deal.opex.controllable_growth) ** (y - 1)
        ins_g = (1 + deal.opex.insurance_growth) ** (y - 1)
        tax_g = (1 + deal.opex.re_tax_growth) ** (y - 1)
        mw = prop.mw_critical
        security = deal.opex.security_per_mw * mw * ctrl_g
        mep = deal.opex.mep_staffing_per_mw * mw * ctrl_g
        insurance = deal.opex.insurance_per_mw * mw * ins_g
        common_power = deal.opex.common_power_per_mw * mw * ctrl_g
        re_tax = deal.opex.re_tax * tax_g
        non_rec = deal.opex.non_recoverable_per_mw * mw * ctrl_g
        mgmt_fee = max(0.0, egi) * deal.opex.mgmt_fee_pct
        total_opex = security + mep + insurance + common_power + re_tax + non_rec + mgmt_fee
        noi = egi - total_opex

        # --- CapEx ---
        building_capex = deal.capex.initial_building_capex if y == 1 else 0.0
        recurring = deal.capex.recurring_reserve_per_mw * mw * ctrl_g
        total_capex = ti + lc + building_capex + recurring
        ncf_unlevered = noi - total_capex
        period_end = date(close.year + y, close.month, close.day)

        pre_debt.append(WholesaleYearLine(
            year=y, period_end=period_end,
            gross_rent=gross_rent, free_rent=free_rent,
            power_margin=power_margin, general_vacancy=general_vacancy, egi=egi,
            security=security, mep_staffing=mep, insurance=insurance,
            common_power=common_power, re_tax=re_tax, non_recoverable=non_rec,
            mgmt_fee=mgmt_fee, total_opex=total_opex, noi=noi,
            ti=ti, lc=lc, building_capex=building_capex + recurring,
            total_capex=total_capex,
            ncf_unlevered=ncf_unlevered,
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlevered,
            leased_mw_avg=leased_mw_avg, utilization_pct=utilization,
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
    sources_uses = WholesaleSourcesUses(
        purchase_price=deal.acquisition.purchase_price, closing_costs=closing_costs,
        initial_capex=deal.acquisition.initial_capex, day_one_reserves=deal.acquisition.day_one_reserves,
        acq_fee=acq_fee, origination_fee=origination_fee, lender_reserves=deal.debt.lender_reserves,
        total_uses=total_uses, loan_amount=sizing.loan_amount, equity_check=equity_check,
    )

    # --- 5. Exit ---
    hold = deal.exit.hold_yrs
    if deal.exit.exit_noi_basis == "forward":
        exit_noi = pre_debt[hold].noi
    else:
        exit_noi = pre_debt[hold - 1].noi
    gross_sale = exit_noi / deal.exit.exit_cap
    cost_of_sale = gross_sale * deal.exit.cost_of_sale_pct
    loan_payoff = pre_debt[hold - 1].loan_balance_eop
    net_proceeds = gross_sale - cost_of_sale - loan_payoff
    exit_summary = WholesaleExitSummary(
        exit_year=hold, exit_noi=exit_noi, exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale, cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff, net_proceeds=net_proceeds,
    )

    # --- 6. Metrics ---
    going_in_cap = pre_debt[0].noi / deal.acquisition.purchase_price
    if deal.exit.stab_yr is not None:
        stab_idx = min(deal.exit.stab_yr - 1, len(pre_debt) - 1)
    else:
        stab_idx = min(2, len(pre_debt) - 1)
    stabilized_cap = pre_debt[stab_idx].noi / deal.acquisition.purchase_price
    all_in_basis_per_mw = total_uses / prop.mw_critical

    stab_yr = stab_idx + 1
    growth_rate = deal.market.market_rent_growth
    roc = compute_roc(
        yr1_noi=pre_debt[0].noi,
        stab_noi=pre_debt[stab_idx].noi,
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

    # --- 8. Rollover schedule ---
    rollover: list[WholesaleRolloverYear] = []
    for y_idx in range(len(output_years)):
        mw = sum(cys[y_idx].rolling_mw for cys in per_contract.values())
        in_place = sum(cys[y_idx].rolling_in_place_rent for cys in per_contract.values())
        mkt = sum(cys[y_idx].market_rent_at_roll for cys in per_contract.values())
        spread = (mkt - in_place) / in_place if in_place > 0 else 0.0
        rollover.append(WholesaleRolloverYear(
            year=y_idx + 1, mw_rolling=mw,
            in_place_rent_rolling=in_place,
            market_rent_at_roll=mkt,
            mtm_spread_pct=spread,
        ))

    return WholesaleProForma(
        deal=deal, years=output_years, per_contract_years=per_contract,
        rollover_schedule=rollover,
        sizing=sizing, amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses, exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap, stabilized_cap=stabilized_cap,
        all_in_basis_per_mw=all_in_basis_per_mw,
        roc=roc,
    )
