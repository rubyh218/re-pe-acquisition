"""
ic_memo.py — Institutional IC memo docx generator.

Produces a standard acquisition IC memo from any engine's underwriting output
(multifamily / commercial / hospitality). Uses the shared docx_style helpers
(vendor/asset-management) for consistent institutional appearance.

CLI:
    python -m scripts.underwriting.ic_memo deal.yaml [-o memo.docx]

Auto-detects asset class via `property.asset_class` in the YAML and dispatches
to the correct engine. Section order:

    Cover page
    1. Executive Summary
    2. Property Overview
    3. Transaction Structure
    4. Operating Pro Forma
    5. Debt
    6. Returns & Waterfall
    7. Exit
    8. Risks (analyst-fill stubs)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import scripts  # noqa: F401
from docx import Document
from docx_style import (
    add_bullets,
    add_cover_page,
    add_heading,
    add_para,
    add_source,
    add_table,
    apply_memo_styles,
)

from .excel_summary import SummaryPayload, build_payload


# ---------------------------------------------------------------------------
# Memo-specific payload extension
# ---------------------------------------------------------------------------

@dataclass
class MemoYearLine:
    year: int
    revenue: float
    opex: float
    noi: float
    ncf_unlevered: float
    ncf_levered: float


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_dollar(v: float) -> str:
    return f"${v:,.0f}"


def _fmt_dollar_m(v: float) -> str:
    return f"${v / 1_000_000:,.2f}M"


def _fmt_pct(v: float, digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%"


def _fmt_multiple(v: float) -> str:
    return f"{v:.2f}x"


def _fmt_per_denom(v: float, label: str) -> str:
    return f"${v:,.0f} {label}"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_ic_memo(
    p: SummaryPayload,
    year_lines: list[MemoYearLine],
    out_path: Path,
    revenue_label: str = "Revenue",
    preparer: str = "Acquisitions",
) -> Path:
    """Render the IC memo as a docx at `out_path`."""
    doc = Document()
    apply_memo_styles(doc, theme="modern")

    add_cover_page(
        doc,
        title=f"Acquisition Memorandum  —  {p.deal_name}",
        recipient="Investment Committee",
        preparer=preparer,
        date_str=p.close_date.strftime("%B %d, %Y"),
        confidentiality=True,
    )

    # ---- 1. Executive Summary ----
    add_heading(doc, "1. Executive Summary", level=1)
    add_para(
        doc,
        f"{p.sponsor} proposes the acquisition of {p.property_name}, a "
        f"{p.asset_class.lower()} asset located in {p.submarket} "
        f"({p.address}), for a purchase price of {_fmt_dollar(p.purchase_price)} "
        f"({_fmt_per_denom(p.purchase_price / p.denom_value, p.per_denom_label)}). "
        f"Total all-in basis of {_fmt_dollar(p.all_in_basis)} "
        f"({_fmt_per_denom(p.all_in_basis / p.denom_value, p.per_denom_label)}) "
        f"underwrites to {_fmt_pct(p.going_in_cap)} going-in / "
        f"{_fmt_pct(p.stabilized_cap)} stabilized cap on a "
        f"{p.hold_yrs}-year hold."
    )
    add_para(
        doc,
        f"Projected returns: project IRR {_fmt_pct(p.project_irr)} / MOIC "
        f"{_fmt_multiple(p.project_moic)}; LP net IRR "
        f"{_fmt_pct(p.lp_irr)} / MOIC {_fmt_multiple(p.lp_moic)}; "
        f"GP IRR {_fmt_pct(p.gp_irr)} / MOIC {_fmt_multiple(p.gp_moic)} "
        f"(inclusive of {_fmt_pct(p.gp_coinvest_pct, 0)} co-invest)."
    )

    add_table(
        doc,
        headers=["Metric", "Value"],
        rows=[
            ["Purchase Price",       _fmt_dollar(p.purchase_price)],
            [f"Price {p.per_denom_label}", _fmt_dollar(p.purchase_price / p.denom_value)],
            ["All-In Basis",         _fmt_dollar(p.all_in_basis)],
            ["Going-In Cap",         _fmt_pct(p.going_in_cap)],
            [f"Stab Cap (Yr {p.stab_yr})", _fmt_pct(p.stabilized_cap)],
            ["Exit Cap",             _fmt_pct(p.exit_cap)],
            ["Untrended YOC @ Stab", _fmt_pct(p.roc_untrended)],
            ["Trended YOC @ Stab",   _fmt_pct(p.roc_trended)],
            ["YOC @ Exit (FTM)",     _fmt_pct(p.roc_exit_ftm)],
            ["LTV",                  _fmt_pct(p.ltv, 1)],
            ["Yr 1 DSCR",            _fmt_multiple(p.dscr)],
            ["Project IRR",          _fmt_pct(p.project_irr)],
            ["LP Net IRR",           _fmt_pct(p.lp_irr)],
            ["GP IRR",               _fmt_pct(p.gp_irr)],
        ],
        numeric_cols=[1],
    )

    # ---- 2. Property Overview ----
    add_heading(doc, "2. Property Overview", level=1)
    add_table(
        doc,
        headers=["Attribute", "Detail"],
        rows=[
            ["Property",        p.property_name],
            ["Address",         p.address],
            ["Submarket",       p.submarket],
            ["Asset Class",     p.asset_class],
            [p.denom_label,     f"{p.denom_value:,.0f}"],
            ["Close Date",      p.close_date.isoformat()],
            ["Hold (yrs)",      str(p.hold_yrs)],
        ],
        numeric_cols=[],
    )

    # ---- 3. Transaction Structure ----
    add_heading(doc, "3. Transaction Structure", level=1)
    add_para(doc, "Sources & uses:")
    uses = [
        ["Purchase Price",        _fmt_dollar(p.purchase_price)],
        ["Closing Costs",         _fmt_dollar(p.closing_costs)],
        ["Initial CapEx",         _fmt_dollar(p.initial_capex)],
        ["Value-Add / PIP",       _fmt_dollar(p.value_add_capex_total)],
        ["Day-One Reserves",      _fmt_dollar(p.day_one_reserves)],
        ["All-In Basis",          _fmt_dollar(p.all_in_basis)],
    ]
    add_table(doc, headers=["Use", "Amount"], rows=uses, numeric_cols=[1], total_row=True)
    add_para(doc, "Capitalization:")
    add_table(
        doc,
        headers=["Source", "Amount", "% of Capitalization"],
        rows=[
            ["Senior Debt",     _fmt_dollar(p.loan_amount),
             _fmt_pct(p.loan_amount / p.all_in_basis, 1)],
            ["LP Equity",       _fmt_dollar(p.lp_contributed),
             _fmt_pct(p.lp_contributed / p.all_in_basis, 1)],
            ["GP Co-Invest",    _fmt_dollar(p.gp_contributed),
             _fmt_pct(p.gp_contributed / p.all_in_basis, 1)],
        ],
        numeric_cols=[1, 2],
    )

    # ---- 4. Operating Pro Forma ----
    add_heading(doc, "4. Operating Pro Forma", level=1)
    rows = [
        [
            f"Yr {yl.year}",
            _fmt_dollar(yl.revenue),
            _fmt_dollar(-yl.opex),
            _fmt_dollar(yl.noi),
            _fmt_dollar(yl.ncf_unlevered),
            _fmt_dollar(yl.ncf_levered),
        ]
        for yl in year_lines
    ]
    add_table(
        doc,
        headers=["Period", revenue_label, "OpEx", "NOI", "Unlevered NCF", "Levered NCF"],
        rows=rows,
        numeric_cols=[1, 2, 3, 4, 5],
    )

    # ---- 5. Debt ----
    add_heading(doc, "5. Debt", level=1)
    add_table(
        doc,
        headers=["Term", "Value"],
        rows=[
            ["Loan Amount",        _fmt_dollar(p.loan_amount)],
            ["Binding Constraint", p.binding_constraint],
            ["LTV",                _fmt_pct(p.ltv, 1)],
            ["Yr 1 DSCR",          _fmt_multiple(p.dscr)],
            ["Yr 1 Debt Yield",    _fmt_pct(p.debt_yield)],
            ["All-In Rate",        _fmt_pct(p.rate)],
            ["Term",               f"{p.term_yrs} years"],
            ["Amortization",       f"{p.amort_yrs} years"],
            ["IO Period",          f"{p.io_period_yrs} years"],
        ],
        numeric_cols=[1],
    )

    # ---- 6. Returns & Waterfall ----
    add_heading(doc, "6. Returns & Waterfall", level=1)
    add_para(doc, "Projected returns:")
    add_table(
        doc,
        headers=["Party", "IRR", "MOIC", "Contributed", "Distributed"],
        rows=[
            ["Project (Total Equity)",
             _fmt_pct(p.project_irr), _fmt_multiple(p.project_moic),
             _fmt_dollar(p.lp_contributed + p.gp_contributed),
             _fmt_dollar(p.lp_distributed + p.gp_distributed)],
            ["LP (net of waterfall)",
             _fmt_pct(p.lp_irr), _fmt_multiple(p.lp_moic),
             _fmt_dollar(p.lp_contributed), _fmt_dollar(p.lp_distributed)],
            [f"GP (co-invest {_fmt_pct(p.gp_coinvest_pct, 0)} + promote)",
             _fmt_pct(p.gp_irr), _fmt_multiple(p.gp_moic),
             _fmt_dollar(p.gp_contributed), _fmt_dollar(p.gp_distributed)],
        ],
        numeric_cols=[1, 2, 3, 4],
    )

    add_para(doc, "Promote structure (multi-tier IRR hurdle):")
    tier_rows = []
    for i, t in enumerate(p.tiers):
        is_residual = (i == len(p.tiers) - 1)
        tier_rows.append([
            t.label or f"Tier {i+1}",
            "Residual" if is_residual else _fmt_pct(t.hurdle_irr, 1),
            _fmt_pct(t.promote_pct, 1),
            _fmt_dollar(t.lp_total),
            _fmt_dollar(t.gp_total),
        ])
    add_table(
        doc,
        headers=["Tier", "Hurdle IRR", "GP Promote", "LP Cash", "GP Promote $"],
        rows=tier_rows,
        numeric_cols=[1, 2, 3, 4],
    )

    # ---- 7. Exit ----
    add_heading(doc, "7. Exit", level=1)
    add_table(
        doc,
        headers=["Item", "Value"],
        rows=[
            ["Exit Year",                  f"Yr {p.exit_year}"],
            ["Exit NOI Basis",             p.exit_noi_basis],
            ["Exit NOI",                   _fmt_dollar(p.exit_noi)],
            ["Exit Cap",                   _fmt_pct(p.exit_cap)],
            ["Gross Sale Price",           _fmt_dollar(p.gross_sale)],
            ["Cost of Sale",               _fmt_dollar(p.cost_of_sale)],
            ["Loan Payoff",                _fmt_dollar(p.loan_payoff)],
            ["Net Proceeds to Equity",     _fmt_dollar(p.net_proceeds)],
        ],
        numeric_cols=[1],
        total_row=True,
    )

    # ---- 8. Risks ----
    add_heading(doc, "8. Risks & Mitigants", level=1)
    add_para(doc, "Analyst-fill section. Standard risk categories:")
    add_bullets(doc, [
        "Market risk — submarket rent / occupancy / cap rate sensitivity.",
        "Execution risk — value-add or PIP delivery, lease-up pace, downtime.",
        "Capital markets risk — refinance / take-out availability at exit.",
        "Operating risk — expense inflation, tax reassessment, insurance hardening.",
        "Sponsor / counterparty risk — operator quality, GP track record.",
    ])

    add_source(
        doc,
        "Note: Figures generated by the underwriting engine on "
        f"{p.close_date.isoformat()}; refer to the accompanying workbook for "
        "full assumptions and year-by-year detail."
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Engine adapters
# ---------------------------------------------------------------------------

def _build_mf(deal_path: str) -> tuple[SummaryPayload, list[MemoYearLine]]:
    from .models import load_deal
    from .pro_forma import build_pro_forma
    from .waterfall_acq import run_acquisition_waterfall
    deal = load_deal(deal_path)
    pf = build_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    value_add_total = (
        deal.capex.value_add_per_unit * deal.property.unit_count
        if deal.capex.value_add_per_unit > 0 else 0.0
    )
    payload = build_payload(
        pf=pf, wf=wf,
        asset_class="Multifamily",
        denom_label="Units",
        denom_value=deal.property.unit_count,
        per_denom_label="/Unit",
        per_denom_fmt="per_unit",
        value_add_capex_total=value_add_total,
    )
    years = [
        MemoYearLine(
            year=yl.year, revenue=yl.egi, opex=yl.total_opex,
            noi=yl.noi, ncf_unlevered=yl.ncf_unlevered, ncf_levered=yl.ncf_levered,
        )
        for yl in pf.years
    ]
    return payload, years


def _build_commercial(deal_path: str) -> tuple[SummaryPayload, list[MemoYearLine]]:
    from .commercial.models import load_commercial_deal
    from .commercial.pro_forma import build_commercial_pro_forma
    from .waterfall_acq import run_acquisition_waterfall
    deal = load_commercial_deal(deal_path)
    pf = build_commercial_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    payload = build_payload(
        pf=pf, wf=wf,
        asset_class=deal.property.asset_class.title(),
        denom_label="RBA (SF)",
        denom_value=deal.property.total_rba,
        per_denom_label="/SF",
        per_denom_fmt="per_sf",
        value_add_capex_total=0.0,
    )
    years = [
        MemoYearLine(
            year=yl.year, revenue=yl.egi, opex=yl.total_opex,
            noi=yl.noi, ncf_unlevered=yl.ncf_unlevered, ncf_levered=yl.ncf_levered,
        )
        for yl in pf.years
    ]
    return payload, years


def _build_hospitality(deal_path: str) -> tuple[SummaryPayload, list[MemoYearLine]]:
    from .hospitality.models import load_hotel_deal
    from .hospitality.pro_forma import build_hotel_pro_forma
    from .waterfall_acq import run_acquisition_waterfall
    deal = load_hotel_deal(deal_path)
    pf = build_hotel_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    payload = build_payload(
        pf=pf, wf=wf,
        asset_class="Hospitality",
        denom_label="Keys",
        denom_value=deal.property.keys,
        per_denom_label="/Key",
        per_denom_fmt="per_unit",
        value_add_capex_total=deal.capex.pip_total,
    )
    years = [
        MemoYearLine(
            year=yl.year,
            revenue=yl.total_revenue,
            opex=yl.total_revenue - yl.noi,   # all costs incl. reserve
            noi=yl.noi,
            ncf_unlevered=yl.ncf_unlevered,
            ncf_levered=yl.ncf_levered,
        )
        for yl in pf.years
    ]
    return payload, years


def _dispatch(deal_path: str) -> tuple[SummaryPayload, list[MemoYearLine], str]:
    """Detect asset class from YAML, dispatch to correct engine.

    Returns (payload, year_lines, revenue_label).
    """
    import yaml
    with open(deal_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    prop = raw.get("property", {}) or {}
    asset_class = (prop.get("asset_class") or "").lower()
    # Fallbacks: infer from distinctive fields when asset_class is omitted.
    if not asset_class:
        if "keys" in prop or "service_level" in prop or "brand" in prop:
            asset_class = "hospitality"
        elif "unit_mix" in prop:
            asset_class = "multifamily"
        elif "rent_roll" in raw or "leases" in raw:
            asset_class = "office"

    if asset_class == "multifamily":
        payload, years = _build_mf(deal_path)
        return payload, years, "EGI"
    if asset_class in {"office", "industrial", "retail"}:
        payload, years = _build_commercial(deal_path)
        return payload, years, "EGI"
    if asset_class == "hospitality":
        payload, years = _build_hospitality(deal_path)
        return payload, years, "Total Revenue"
    raise ValueError(
        f"unknown asset_class '{asset_class}' in {deal_path}. "
        f"Expected: multifamily / office / industrial / retail / hospitality."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_status(payload: SummaryPayload, out: Path) -> None:
    bar = "-" * 72
    print(bar)
    print(f"  {payload.deal_name}  -  IC Memo")
    print(bar)
    print(f"  Asset class:     {payload.asset_class}")
    print(f"  Purchase Price:  {_fmt_dollar(payload.purchase_price)}")
    print(f"  All-In Basis:    {_fmt_dollar(payload.all_in_basis)}")
    print(f"  LP Net IRR:      {_fmt_pct(payload.lp_irr)}")
    print(f"  GP IRR:          {_fmt_pct(payload.gp_irr)}")
    print(bar)
    print(f"  Memo written to: {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.underwriting.ic_memo",
        description="Generate an institutional IC memo (docx) from a deal YAML.",
    )
    parser.add_argument("deal", help="Path to deal YAML.")
    parser.add_argument(
        "-o", "--output",
        help="Output path (default: outputs/<deal_id>-ic-memo.docx).",
    )
    parser.add_argument(
        "--preparer",
        default="Acquisitions",
        help="Preparer name printed on cover page (default: Acquisitions).",
    )
    args = parser.parse_args(argv)

    payload, years, revenue_label = _dispatch(args.deal)
    out = Path(args.output) if args.output else Path("outputs") / f"{payload.deal_id}-ic-memo.docx"
    write_ic_memo(payload, years, out, revenue_label=revenue_label, preparer=args.preparer)
    _print_status(payload, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
