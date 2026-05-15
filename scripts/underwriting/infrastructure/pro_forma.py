"""
pro_forma.py -- Energy infrastructure cash-flow engine.

Annual periods. Net generation drives variable revenue (PPA + merchant) and
variable OpEx; nameplate MW drives fixed OpEx. Year buildup:

  1. Net generation = nameplate * 8760 * cf * (1-deg)^(y-1) * (1-curt) * avail
  2. Per-stream revenue (PPA / availability / merchant)
  3. Tax credit cash (ITC Yr 1 + PTC Yr 1..ptc_term)
  4. Gross revenue + credits
  5. OpEx (fixed_om + variable_om + insurance + tax + land + interconnect + AM%)
  6. NOI = revenue - opex
  7. Augmentation capex (lumpy by year) + recurring reserves
  8. Debt sizing on Yr 1 NOI, exit reversion on contracted NOI
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..debt_sizing import AmortYear, SizingResult, amortization_schedule, size_loan
from ..metrics import ReturnOnCost, compute_roc
from .models import (
    AvailabilityStream,
    InfrastructureDeal,
    MerchantStream,
    PPAStream,
)


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------

@dataclass
class StreamYear:
    """One revenue stream's contribution in a given hold year."""
    label: str
    kind: str                       # "ppa" / "availability" / "merchant"
    counterparty: str
    contracted_mwh: float           # 0 for availability
    price_mwh: float                # blended; 0 for availability
    capacity_mw: float              # 0 for ppa/merchant
    payment_mw_mo: float            # 0 for ppa/merchant
    revenue: float


@dataclass
class GenerationYear:
    year: int
    gross_mwh: float                # nameplate * 8760 * cf, no drags
    degradation_factor: float       # (1-deg)^(y-1)
    curtailed_mwh: float            # negative drag (positive number = lost gen)
    availability_loss_mwh: float    # negative drag
    net_mwh: float                  # after all drags
    cf_realized: float              # net_mwh / (nameplate * 8760)


@dataclass
class InfraYearLine:
    year: int
    period_end: date
    # Generation
    net_generation_mwh: float
    # Revenue
    ppa_revenue: float
    availability_revenue: float
    merchant_revenue: float
    ptc_revenue: float              # production tax credit cash
    gross_revenue: float            # = sum of streams + PTC (ITC handled separately as Yr-1 cash)
    # OpEx
    fixed_om: float
    variable_om: float
    insurance: float
    property_tax: float
    land_lease: float
    interconnection_om: float
    asset_mgmt_fee: float
    total_opex: float
    noi: float
    # CapEx
    augmentation: float
    recurring_reserve: float
    total_capex: float
    # CF
    itc_cash: float                 # Yr 1 only
    ncf_unlevered: float
    debt_service: float
    interest: float
    principal: float
    loan_balance_eop: float
    ncf_levered: float


@dataclass
class InfraSourcesUses:
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
class InfraExitSummary:
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
class ContractedShareYear:
    """Per-year share of revenue that is contracted vs. merchant -- IC memo headline."""
    year: int
    contracted_revenue: float       # PPA + availability
    merchant_revenue: float
    contracted_share: float         # contracted / total


@dataclass
class InfraProForma:
    deal: InfrastructureDeal
    years: list[InfraYearLine]
    generation_schedule: list[GenerationYear]
    per_stream_years: dict[str, list[StreamYear]]
    contracted_share_schedule: list[ContractedShareYear]
    sizing: SizingResult
    amort_schedule: list[AmortYear]
    sources_uses: InfraSourcesUses
    exit_summary: InfraExitSummary
    equity_flows_total: list[EquityFlow]
    going_in_cap: float
    stabilized_cap: float
    all_in_basis_per_mw: float
    roc: ReturnOnCost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year_window(close: date, year: int) -> tuple[date, date]:
    """[start, end) window for hold year `year` (1-indexed)."""
    start = date(close.year + (year - 1), close.month, min(close.day, 28))
    end = date(close.year + year, close.month, min(close.day, 28))
    return start, end


def _fraction_in_window(stream_start: date, stream_end: date, win_start: date, win_end: date) -> float:
    """Fraction of [win_start, win_end) overlapped by [stream_start, stream_end)."""
    lo = max(stream_start, win_start)
    hi = min(stream_end, win_end)
    if hi <= lo:
        return 0.0
    overlap_days = (hi - lo).days
    win_days = (win_end - win_start).days
    return overlap_days / win_days if win_days > 0 else 0.0


def _ppa_price_for_year(s: PPAStream, year: int) -> float:
    """Escalated PPA price for hold year `year`, with optional floor/ceiling."""
    raw = s.price_mwh * (1 + s.escalation_pct) ** (year - 1)
    if s.floor_price_mwh is not None:
        raw = max(raw, s.floor_price_mwh)
    if s.cap_price_mwh is not None:
        raw = min(raw, s.cap_price_mwh)
    return raw


def _merchant_price_for_year(s: MerchantStream, year: int) -> float:
    """Merchant price for hold year `year`. Extrapolates past curve by terminal_growth."""
    if year <= len(s.price_curve_mwh):
        return s.price_curve_mwh[year - 1]
    extra = year - len(s.price_curve_mwh)
    return s.price_curve_mwh[-1] * (1 + s.terminal_growth) ** extra


def _avail_payment_for_year(s: AvailabilityStream, year: int, close: date) -> float:
    """Escalated availability payment for hold year `year` * months in window."""
    win_start, win_end = _year_window(close, year)
    frac = _fraction_in_window(s.start_date, s.end_date, win_start, win_end)
    if frac <= 0:
        return 0.0
    escal = (1 + s.escalation_pct) ** (year - 1)
    return s.annual_payment * escal * frac


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def build_infrastructure_pro_forma(deal: InfrastructureDeal) -> InfraProForma:
    prop = deal.property
    gen = prop.generation
    n_years = deal.exit.hold_yrs + (1 if deal.exit.exit_noi_basis == "forward" else 0)
    close = deal.acquisition.close_date

    # --- 1. Generation schedule -------------------------------------------
    gen_schedule: list[GenerationYear] = []
    for y in range(1, n_years + 1):
        gross = gen.gross_annual_generation_mwh_yr1
        deg = (1 - gen.degradation_pct) ** (y - 1)
        gross_after_deg = gross * deg
        curtailed = gross_after_deg * gen.curtailment_pct
        after_curt = gross_after_deg - curtailed
        avail_loss = after_curt * (1 - gen.availability_pct)
        net = after_curt - avail_loss
        cf_real = net / (gen.nameplate_mw_ac * 8760) if gen.nameplate_mw_ac > 0 else 0.0
        gen_schedule.append(GenerationYear(
            year=y, gross_mwh=gross, degradation_factor=deg,
            curtailed_mwh=curtailed, availability_loss_mwh=avail_loss,
            net_mwh=net, cf_realized=cf_real,
        ))

    # --- 2. Per-stream revenue --------------------------------------------
    per_stream: dict[str, list[StreamYear]] = {}
    for stream in prop.revenue_streams:
        key = stream.label
        if key in per_stream:
            n = sum(1 for k in per_stream if k.startswith(key))
            key = f"{key} #{n+1}"
        years_out: list[StreamYear] = []
        for y in range(1, n_years + 1):
            net_mwh = gen_schedule[y - 1].net_mwh
            if isinstance(stream, PPAStream):
                win_start, win_end = _year_window(close, y)
                frac = _fraction_in_window(stream.start_date, stream.end_date, win_start, win_end)
                contracted_mwh = net_mwh * stream.allotment_pct * frac
                price = _ppa_price_for_year(stream, y)
                rev = contracted_mwh * price
                years_out.append(StreamYear(
                    label=stream.label, kind="ppa", counterparty=stream.counterparty,
                    contracted_mwh=contracted_mwh, price_mwh=price,
                    capacity_mw=0.0, payment_mw_mo=0.0, revenue=rev,
                ))
            elif isinstance(stream, AvailabilityStream):
                rev = _avail_payment_for_year(stream, y, close)
                years_out.append(StreamYear(
                    label=stream.label, kind="availability", counterparty=stream.counterparty,
                    contracted_mwh=0.0, price_mwh=0.0,
                    capacity_mw=stream.capacity_mw, payment_mw_mo=stream.payment_mw_mo,
                    revenue=rev,
                ))
            elif isinstance(stream, MerchantStream):
                mwh = net_mwh * stream.allotment_pct
                price = _merchant_price_for_year(stream, y)
                rev = mwh * price
                years_out.append(StreamYear(
                    label=stream.label, kind="merchant", counterparty=stream.counterparty,
                    contracted_mwh=mwh, price_mwh=price,
                    capacity_mw=0.0, payment_mw_mo=0.0, revenue=rev,
                ))
        per_stream[key] = years_out

    # --- 3. Year build (revenue + opex + capex) ----------------------------
    pre_debt: list[InfraYearLine] = []
    nameplate = gen.nameplate_mw_ac
    aug_by_year = {ev.year: ev.amount for ev in deal.capex.augmentation_schedule}

    for y_idx in range(n_years):
        y = y_idx + 1
        net_mwh = gen_schedule[y_idx].net_mwh

        ppa_rev = sum(s[y_idx].revenue for s in per_stream.values() if s[y_idx].kind == "ppa")
        avail_rev = sum(s[y_idx].revenue for s in per_stream.values() if s[y_idx].kind == "availability")
        merch_rev = sum(s[y_idx].revenue for s in per_stream.values() if s[y_idx].kind == "merchant")

        # PTC cash
        ptc_rev = 0.0
        if y <= deal.tax_credits.ptc_term_yrs and deal.tax_credits.ptc_per_mwh > 0:
            ptc_per_mwh_y = deal.tax_credits.ptc_per_mwh * \
                            (1 + deal.tax_credits.ptc_inflation) ** (y - 1)
            ptc_rev = net_mwh * ptc_per_mwh_y

        gross_rev = ppa_rev + avail_rev + merch_rev + ptc_rev

        # --- OpEx ---
        om_g = (1 + deal.opex.om_growth) ** (y - 1)
        tax_g = (1 + deal.opex.property_tax_growth) ** (y - 1)
        land_g = (1 + deal.opex.land_lease_growth) ** (y - 1)
        ins_g = (1 + deal.opex.insurance_growth) ** (y - 1)

        fixed_om = deal.opex.fixed_om_per_mw_yr * nameplate * om_g
        variable_om = deal.opex.variable_om_per_mwh * net_mwh * om_g
        insurance = deal.opex.insurance_per_mw_yr * nameplate * ins_g
        property_tax = deal.opex.property_tax * tax_g
        land_lease = deal.opex.land_lease * land_g
        interconn = deal.opex.interconnection_om * om_g
        asset_mgmt = max(0.0, gross_rev) * deal.opex.asset_mgmt_pct
        total_opex = (fixed_om + variable_om + insurance + property_tax
                      + land_lease + interconn + asset_mgmt)
        noi = gross_rev - total_opex

        # --- CapEx ---
        augmentation = aug_by_year.get(y, 0.0)
        recurring = deal.capex.recurring_reserve_per_mw_yr * nameplate * om_g
        total_capex = augmentation + recurring

        # ITC cash (Yr 1 only)
        itc_cash = (deal.tax_credits.itc_pct * deal.tax_credits.itc_basis) if y == 1 else 0.0

        ncf_unlev = noi - total_capex + itc_cash
        period_end = date(close.year + y, close.month, min(close.day, 28))

        pre_debt.append(InfraYearLine(
            year=y, period_end=period_end,
            net_generation_mwh=net_mwh,
            ppa_revenue=ppa_rev, availability_revenue=avail_rev,
            merchant_revenue=merch_rev, ptc_revenue=ptc_rev,
            gross_revenue=gross_rev,
            fixed_om=fixed_om, variable_om=variable_om,
            insurance=insurance, property_tax=property_tax,
            land_lease=land_lease, interconnection_om=interconn,
            asset_mgmt_fee=asset_mgmt, total_opex=total_opex, noi=noi,
            augmentation=augmentation, recurring_reserve=recurring,
            total_capex=total_capex,
            itc_cash=itc_cash,
            ncf_unlevered=ncf_unlev,
            debt_service=0.0, interest=0.0, principal=0.0,
            loan_balance_eop=0.0, ncf_levered=ncf_unlev,
        ))

    # --- 4. Debt sizing on Yr 1 NOI ---
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

    # --- 5. Sources & uses ---
    closing_costs = deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct
    acq_fee = deal.acquisition.purchase_price * deal.equity.acq_fee_pct
    origination_fee = sizing.loan_amount * deal.debt.origination_fee_pct
    total_uses = (
        deal.acquisition.purchase_price + closing_costs + deal.acquisition.initial_capex
        + deal.acquisition.day_one_reserves + acq_fee + origination_fee + deal.debt.lender_reserves
    )
    equity_check = total_uses - sizing.loan_amount
    sources_uses = InfraSourcesUses(
        purchase_price=deal.acquisition.purchase_price, closing_costs=closing_costs,
        initial_capex=deal.acquisition.initial_capex, day_one_reserves=deal.acquisition.day_one_reserves,
        acq_fee=acq_fee, origination_fee=origination_fee, lender_reserves=deal.debt.lender_reserves,
        total_uses=total_uses, loan_amount=sizing.loan_amount, equity_check=equity_check,
    )

    # --- 6. Exit ---
    hold = deal.exit.hold_yrs
    if deal.exit.exit_noi_basis == "forward":
        exit_noi = pre_debt[hold].noi
    else:
        exit_noi = pre_debt[hold - 1].noi
    gross_sale = exit_noi / deal.exit.exit_cap
    cost_of_sale = gross_sale * deal.exit.cost_of_sale_pct
    loan_payoff = pre_debt[hold - 1].loan_balance_eop
    net_proceeds = gross_sale - cost_of_sale - loan_payoff
    exit_summary = InfraExitSummary(
        exit_year=hold, exit_noi=exit_noi, exit_cap=deal.exit.exit_cap,
        gross_sale=gross_sale, cost_of_sale=cost_of_sale,
        loan_payoff=loan_payoff, net_proceeds=net_proceeds,
    )

    # --- 7. Metrics ---
    going_in_cap = pre_debt[0].noi / deal.acquisition.purchase_price
    if deal.exit.stab_yr is not None:
        stab_idx = min(deal.exit.stab_yr - 1, len(pre_debt) - 1)
    else:
        stab_idx = min(2, len(pre_debt) - 1)
    stabilized_cap = pre_debt[stab_idx].noi / deal.acquisition.purchase_price
    all_in_basis_per_mw = total_uses / nameplate

    # Pick a representative growth rate for ROC deflation: avg PPA escalation
    # (fallback to merchant terminal growth, then 0.02).
    ppa_escal = [
        s.escalation_pct for s in prop.revenue_streams if isinstance(s, PPAStream)
    ]
    merch_growth = [
        s.terminal_growth for s in prop.revenue_streams if isinstance(s, MerchantStream)
    ]
    if ppa_escal:
        growth_rate = sum(ppa_escal) / len(ppa_escal)
    elif merch_growth:
        growth_rate = sum(merch_growth) / len(merch_growth)
    else:
        growth_rate = 0.02

    stab_yr = stab_idx + 1
    roc = compute_roc(
        stab_noi=pre_debt[stab_idx].noi,
        exit_ftm_noi=exit_noi,
        all_in_basis=total_uses,
        stab_yr=stab_yr,
        growth_rate=growth_rate,
    )

    # --- 8. Equity flows ---
    equity_flows: list[EquityFlow] = [EquityFlow(period=close, amount=-equity_check)]
    for i in range(hold):
        yl = pre_debt[i]
        amount = yl.ncf_levered
        if i == hold - 1:
            amount += net_proceeds
        equity_flows.append(EquityFlow(period=yl.period_end, amount=amount))

    output_years = pre_debt[: hold + (1 if deal.exit.exit_noi_basis == "forward" else 0)]

    # --- 9. Contracted vs. merchant share (institutional headline) ---
    contracted_share: list[ContractedShareYear] = []
    for y_idx in range(len(output_years)):
        contracted = sum(s[y_idx].revenue for s in per_stream.values()
                         if s[y_idx].kind in ("ppa", "availability"))
        merchant = sum(s[y_idx].revenue for s in per_stream.values()
                       if s[y_idx].kind == "merchant")
        total = contracted + merchant
        share = (contracted / total) if total > 0 else 0.0
        contracted_share.append(ContractedShareYear(
            year=y_idx + 1, contracted_revenue=contracted,
            merchant_revenue=merchant, contracted_share=share,
        ))

    return InfraProForma(
        deal=deal, years=output_years,
        generation_schedule=gen_schedule[: len(output_years)],
        per_stream_years=per_stream,
        contracted_share_schedule=contracted_share,
        sizing=sizing, amort_schedule=amort[: len(output_years)],
        sources_uses=sources_uses, exit_summary=exit_summary,
        equity_flows_total=equity_flows,
        going_in_cap=going_in_cap, stabilized_cap=stabilized_cap,
        all_in_basis_per_mw=all_in_basis_per_mw,
        roc=roc,
    )
