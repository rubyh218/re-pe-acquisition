"""
excel_summary.py — Shared institutional Executive Summary writer.

Produces a single-page deal snapshot used by MF / commercial / hospitality
engines. The Executive Summary becomes the FIRST tab in every workbook, with
the engine-specific detail tabs following.

Layout (sections):
  1. Property summary (name, address, asset class, denominator)
  2. Pricing & basis (purchase price, closing, capex, reserves, all-in basis)
  3. Cap rates & 3-basis ROC (going-in / stabilized / exit; untrended/trended/exit-ftm)
  4. Debt summary (loan, LTV/DSCR/DY, rate, term)
  5. Equity returns (project / LP / GP — IRR + MOIC)
  6. Multi-tier waterfall (per-tier LP/GP totals)
  7. Exit (year, NOI, cap, gross, net proceeds)

Engine-agnostic — caller passes a `SummaryPayload` with the cross-engine fields
already extracted. Each engine has a tiny adapter (`build_payload`) that
projects its pro_forma + waterfall result onto the payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import scripts  # noqa: F401
from excel_style import (
    set_sheet_defaults,
    write_formula,
    write_header,
    write_input,
    write_label,
    write_section,
    write_subtotal,
    write_units,
)
from openpyxl import Workbook


@dataclass
class TierLine:
    label: str
    hurdle_irr: float
    promote_pct: float
    lp_total: float
    gp_total: float
    gross_total: float


@dataclass
class SummaryPayload:
    """Cross-engine snapshot for the Executive Summary tab."""
    # Header
    deal_id: str
    deal_name: str
    sponsor: str
    asset_class: str            # "Multifamily" / "Office" / "Hospitality"
    property_name: str
    address: str
    submarket: str
    close_date: date
    hold_yrs: int

    # Denominator
    denom_label: str            # "Units" / "RBA (SF)" / "Keys"
    denom_value: float          # 200 / 200,000 / 120
    per_denom_label: str        # "per Unit" / "per SF" / "per Key"
    per_denom_fmt: str          # "per_unit" / "per_sf" / "per_unit"

    # Pricing & basis
    purchase_price: float
    closing_costs: float
    initial_capex: float        # day-1 (excludes value-add schedule for MF; PIP for hotel)
    value_add_capex_total: float  # full schedule cost over hold (0 if none)
    day_one_reserves: float
    all_in_basis: float

    # Cap rates / ROC
    going_in_cap: float
    stabilized_cap: float
    stab_yr: int
    exit_cap: float
    roc_untrended: float
    roc_trended: float
    roc_exit_ftm: float

    # Debt
    loan_amount: float
    ltv: float
    dscr: float
    debt_yield: float
    rate: float
    term_yrs: int
    amort_yrs: int
    io_period_yrs: int
    binding_constraint: str

    # Equity returns
    project_irr: float
    project_moic: float
    lp_irr: float
    lp_moic: float
    lp_contributed: float
    lp_distributed: float
    gp_irr: float
    gp_moic: float
    gp_contributed: float
    gp_distributed: float

    # Waterfall structure
    gp_coinvest_pct: float
    tiers: list[TierLine]

    # Exit
    exit_year: int
    exit_noi: float
    gross_sale: float
    cost_of_sale: float
    loan_payoff: float
    net_proceeds: float
    exit_noi_basis: str         # "forward" / "trailing"


def write_executive_summary(wb: Workbook, p: SummaryPayload) -> None:
    """Insert the Executive Summary as the first tab of `wb`.

    Single-column stacked layout: 1-page snapshot, clean to print.
    `apply_institutional_styles(wb)` must be called by the engine before
    invoking this function.
    """
    ws = wb.create_sheet("Executive Summary", 0)
    set_sheet_defaults(ws, title=f"{p.deal_name} — Executive Summary")
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 2
    ws.column_dimensions["D"].width = 22
    ws.column_dimensions["E"].width = 2
    ws.column_dimensions["F"].width = 18
    ws.column_dimensions["G"].width = 2
    ws.column_dimensions["H"].width = 18

    r = 1
    write_header(ws, r, f"{p.deal_name}  —  Investment Summary", span_cols=10)
    r += 2

    # --- Property ---
    write_section(ws, r, "Property", span_cols=10); r += 1
    rows = [
        ("Deal ID",        p.deal_id,              "general"),
        ("Sponsor",        p.sponsor,              "general"),
        ("Asset Class",    p.asset_class,          "general"),
        ("Property",       p.property_name,        "general"),
        ("Address",        p.address,              "general"),
        ("Submarket",      p.submarket,            "general"),
        ("Close Date",     p.close_date,           "date"),
        ("Hold (yrs)",     p.hold_yrs,             "general"),
        (p.denom_label,    p.denom_value,          "general"),
    ]
    for label, val, fmt in rows:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt=fmt)
        r += 1
    r += 1

    # --- Pricing & Basis ---
    write_section(ws, r, "Pricing & Basis", span_cols=10); r += 1
    write_label(ws, (r, 2), "Purchase Price")
    write_input(ws, (r, 4), p.purchase_price, fmt="dollar")
    write_input(ws, (r, 6), p.purchase_price / p.denom_value, fmt=p.per_denom_fmt)
    write_units(ws, (r, 7), p.per_denom_label)
    r += 1
    for label, val in [
        ("Closing Costs",     p.closing_costs),
        ("Initial CapEx",     p.initial_capex),
        ("Value-Add / PIP",   p.value_add_capex_total),
        ("Day-One Reserves",  p.day_one_reserves),
    ]:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt="dollar")
        if p.denom_value > 0:
            write_input(ws, (r, 6), val / p.denom_value, fmt=p.per_denom_fmt)
            write_units(ws, (r, 7), p.per_denom_label)
        r += 1
    write_label(ws, (r, 2), "All-In Basis", bold=True)
    write_subtotal(ws, (r, 4), p.all_in_basis, fmt="dollar")
    write_input(ws, (r, 6), p.all_in_basis / p.denom_value, fmt=p.per_denom_fmt)
    write_units(ws, (r, 7), p.per_denom_label)
    r += 2

    # --- Cap Rates & 3-Basis ROC ---
    write_section(ws, r, "Cap Rates & Return on Cost", span_cols=10); r += 1
    cap_rows = [
        ("Going-In Cap (Yr 1 NOI / Price)",       p.going_in_cap),
        (f"Stabilized Cap (Yr {p.stab_yr} NOI)",  p.stabilized_cap),
        ("Exit Cap",                              p.exit_cap),
    ]
    for label, val in cap_rows:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt="pct2")
        r += 1
    r += 1
    roc_rows = [
        ("Untrended Yield-on-Cost @ Stab",        p.roc_untrended),
        ("Trended Yield-on-Cost @ Stab",          p.roc_trended),
        ("Yield-on-Cost @ Exit (FTM)",            p.roc_exit_ftm),
    ]
    for label, val in roc_rows:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt="pct2")
        r += 1
    r += 1

    # --- Debt ---
    write_section(ws, r, "Debt", span_cols=10); r += 1
    debt_rows = [
        ("Loan Amount",                p.loan_amount,    "dollar"),
        ("Binding Constraint",         p.binding_constraint, "general"),
        ("LTV",                        p.ltv,            "pct1"),
        ("Yr 1 DSCR",                  p.dscr,           "multiple"),
        ("Yr 1 Debt Yield",            p.debt_yield,     "pct2"),
        ("All-In Rate",                p.rate,           "pct2"),
        ("Term (yrs)",                 p.term_yrs,       "general"),
        ("Amort (yrs)",                p.amort_yrs,      "general"),
        ("IO Period (yrs)",            p.io_period_yrs,  "general"),
    ]
    for label, val, fmt in debt_rows:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt=fmt)
        r += 1
    r += 1

    # --- Equity Returns ---
    write_section(ws, r, "Equity Returns", span_cols=10); r += 1
    write_label(ws, (r, 2), "Party", bold=True)
    write_label(ws, (r, 4), "IRR", bold=True)
    write_label(ws, (r, 6), "MOIC", bold=True)
    write_label(ws, (r, 8), "Distributed", bold=True)
    r += 1
    for label, irr, m, contrib, dist in [
        ("Project (Total Equity, pre-WF)", p.project_irr, p.project_moic, p.lp_contributed + p.gp_contributed, p.lp_distributed + p.gp_distributed),
        ("LP (net of waterfall)",          p.lp_irr,      p.lp_moic,      p.lp_contributed,                    p.lp_distributed),
        (f"GP (coinvest {p.gp_coinvest_pct:.0%} + promote)", p.gp_irr, p.gp_moic, p.gp_contributed,                    p.gp_distributed),
    ]:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), irr, fmt="pct2")
        write_input(ws, (r, 6), m, fmt="multiple")
        write_input(ws, (r, 8), dist, fmt="dollar")
        r += 1
    r += 1

    # --- Multi-Tier Waterfall ---
    write_section(ws, r, "Promote Structure (Multi-Tier IRR Hurdle)", span_cols=10); r += 1
    write_label(ws, (r, 2), "Tier", bold=True)
    write_label(ws, (r, 4), "Hurdle IRR", bold=True)
    write_label(ws, (r, 6), "Promote", bold=True)
    write_label(ws, (r, 8), "LP / GP Total", bold=True)
    r += 1
    for i, t in enumerate(p.tiers):
        is_residual = (i == len(p.tiers) - 1)
        write_label(ws, (r, 2), t.label or f"Tier {i+1}")
        if is_residual:
            write_label(ws, (r, 4), "Residual")
        else:
            write_input(ws, (r, 4), t.hurdle_irr, fmt="pct1")
        write_input(ws, (r, 6), t.promote_pct, fmt="pct1")
        write_input(ws, (r, 8), t.lp_total, fmt="dollar")
        r += 1
    r += 1

    # --- Exit ---
    write_section(ws, r, "Exit", span_cols=10); r += 1
    exit_rows = [
        (f"Exit Year ({p.exit_noi_basis} NOI basis)", p.exit_year, "general"),
        ("Exit NOI",                                  p.exit_noi, "dollar"),
        ("Exit Cap",                                  p.exit_cap, "pct2"),
        ("Gross Sale Price",                          p.gross_sale, "dollar"),
        ("Cost of Sale",                              p.cost_of_sale, "dollar"),
        ("Loan Payoff",                               p.loan_payoff, "dollar"),
    ]
    for label, val, fmt in exit_rows:
        write_label(ws, (r, 2), label)
        write_input(ws, (r, 4), val, fmt=fmt)
        r += 1
    write_label(ws, (r, 2), "Net Proceeds to Equity", bold=True)
    write_subtotal(ws, (r, 4), p.net_proceeds, fmt="dollar")
    r += 1


# ---------------------------------------------------------------------------
# Adapter helper — convert engine outputs to a SummaryPayload
# ---------------------------------------------------------------------------

def build_payload(
    *,
    pf,                                  # any engine ProForma (duck-typed)
    wf,                                  # WaterfallResult from waterfall_acq
    asset_class: str,
    denom_label: str,
    denom_value: float,
    per_denom_label: str,
    per_denom_fmt: str,
    value_add_capex_total: float = 0.0,
) -> SummaryPayload:
    """Build a SummaryPayload by extracting fields from a pro_forma + waterfall result."""
    deal = pf.deal
    su = pf.sources_uses
    ex = pf.exit_summary
    sz = pf.sizing
    roc = pf.roc

    return SummaryPayload(
        deal_id=deal.deal_id,
        deal_name=deal.deal_name,
        sponsor=deal.sponsor,
        asset_class=asset_class,
        property_name=deal.property.name,
        address=deal.property.address,
        submarket=deal.property.submarket,
        close_date=deal.acquisition.close_date,
        hold_yrs=deal.exit.hold_yrs,

        denom_label=denom_label,
        denom_value=denom_value,
        per_denom_label=per_denom_label,
        per_denom_fmt=per_denom_fmt,

        purchase_price=deal.acquisition.purchase_price,
        closing_costs=getattr(su, "closing_costs", deal.acquisition.purchase_price * deal.acquisition.closing_costs_pct),
        initial_capex=deal.acquisition.initial_capex,
        value_add_capex_total=value_add_capex_total,
        day_one_reserves=deal.acquisition.day_one_reserves,
        all_in_basis=roc.all_in_basis,

        going_in_cap=pf.going_in_cap,
        stabilized_cap=pf.stabilized_cap,
        stab_yr=roc.stab_yr,
        exit_cap=deal.exit.exit_cap,
        roc_untrended=roc.untrended_stab,
        roc_trended=roc.trended_stab,
        roc_exit_ftm=roc.exit_ftm,

        loan_amount=sz.loan_amount,
        ltv=getattr(sz, "implied_ltv", getattr(sz, "ltv", 0.0)),
        dscr=getattr(sz, "implied_dscr", getattr(sz, "dscr", 0.0)),
        debt_yield=getattr(sz, "implied_debt_yield", getattr(sz, "debt_yield", 0.0)),
        rate=deal.debt.rate,
        term_yrs=deal.debt.term_yrs,
        amort_yrs=deal.debt.amort_yrs,
        io_period_yrs=deal.debt.io_period_yrs,
        binding_constraint=getattr(sz, "binding", "—"),

        project_irr=wf.total_equity_irr,
        project_moic=wf.total_equity_moic,
        lp_irr=wf.lp.irr,
        lp_moic=wf.lp.moic,
        lp_contributed=wf.lp.contributed,
        lp_distributed=wf.lp.distributed,
        gp_irr=wf.gp.irr,
        gp_moic=wf.gp.moic,
        gp_contributed=wf.gp.contributed,
        gp_distributed=wf.gp.distributed,

        gp_coinvest_pct=deal.equity.gp_coinvest_pct,
        tiers=[
            TierLine(
                label=t.label,
                hurdle_irr=t.hurdle_irr,
                promote_pct=t.promote_pct,
                lp_total=t.lp_total,
                gp_total=t.gp_total,
                gross_total=t.gross_total,
            )
            for t in wf.per_tier
        ],

        exit_year=ex.exit_year,
        exit_noi=ex.exit_noi,
        gross_sale=ex.gross_sale,
        cost_of_sale=ex.cost_of_sale,
        loan_payoff=ex.loan_payoff,
        net_proceeds=ex.net_proceeds,
        exit_noi_basis=deal.exit.exit_noi_basis,
    )
