"""
sensitivity.py — 2-axis sensitivity tables.

Recomputes returns over a cartesian product of two driver values. Default tables:
  - Exit cap × rent growth (multiplier on the input series)
  - Purchase price × Max LTV
  - Exit cap × Hold years

Each cell of the output table is the LP IRR (or MOIC) under that scenario.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Deal
from .pro_forma import build_pro_forma
from .waterfall_acq import run_acquisition_waterfall


@dataclass
class SensitivityTable:
    title: str
    metric: str                       # "LP IRR", "LP MOIC", "Total Equity IRR"
    x_label: str
    y_label: str
    x_values: list[float]             # column headers (typically the more important driver)
    y_values: list[float]             # row headers
    cells: list[list[float]]          # cells[y][x]


def _rerun(deal: Deal) -> tuple[float, float, float, float]:
    """(total_equity_irr, total_equity_moic, lp_irr, lp_moic)"""
    pf = build_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return wf.total_equity_irr, wf.total_equity_moic, wf.lp.irr, wf.lp.moic


def _override(deal: Deal, **changes) -> Deal:
    """Return a copy of Deal with specified leaf overrides applied via model_copy."""
    return deal.model_copy(deep=True, update=changes)


def _override_nested(deal: Deal, section: str, **changes) -> Deal:
    """Override a nested section (e.g., exit, debt, acquisition)."""
    sec = getattr(deal, section).model_copy(update=changes)
    return deal.model_copy(update={section: sec})


def exit_cap_x_rent_growth(
    deal: Deal,
    exit_caps: list[float],
    rent_growth_multipliers: list[float],
    metric: str = "LP IRR",
) -> SensitivityTable:
    """
    Rows = rent growth multipliers (e.g., [0.5, 0.75, 1.0, 1.25, 1.5]).
    Cols = exit caps (e.g., [0.0525, 0.0550, 0.0575, 0.0600, 0.0625]).
    """
    cells: list[list[float]] = []
    for mult in rent_growth_multipliers:
        row: list[float] = []
        for ec in exit_caps:
            new_growth = [g * mult for g in deal.revenue.rent_growth]
            d = _override_nested(deal, "revenue", rent_growth=new_growth)
            d = _override_nested(d, "exit", exit_cap=ec)
            te_irr, te_moic, lp_irr, lp_moic = _rerun(d)
            row.append({"LP IRR": lp_irr, "LP MOIC": lp_moic, "Total Equity IRR": te_irr, "Total Equity MOIC": te_moic}[metric])
        cells.append(row)
    return SensitivityTable(
        title=f"{metric} — Exit Cap × Rent Growth Sensitivity",
        metric=metric,
        x_label="Exit Cap",
        y_label="Rent Growth (× base case)",
        x_values=exit_caps,
        y_values=rent_growth_multipliers,
        cells=cells,
    )


def price_x_ltv(
    deal: Deal,
    price_deltas_pct: list[float],   # e.g., [-0.05, -0.025, 0, 0.025, 0.05]
    max_ltvs: list[float],
    metric: str = "LP IRR",
) -> SensitivityTable:
    base_price = deal.acquisition.purchase_price
    cells: list[list[float]] = []
    for ltv in max_ltvs:
        row: list[float] = []
        for delta in price_deltas_pct:
            new_price = base_price * (1 + delta)
            d = _override_nested(deal, "acquisition", purchase_price=new_price)
            d = _override_nested(d, "debt", max_ltv=ltv)
            te_irr, te_moic, lp_irr, lp_moic = _rerun(d)
            row.append({"LP IRR": lp_irr, "LP MOIC": lp_moic, "Total Equity IRR": te_irr, "Total Equity MOIC": te_moic}[metric])
        cells.append(row)
    return SensitivityTable(
        title=f"{metric} — Price × Max LTV Sensitivity",
        metric=metric,
        x_label="Purchase Price (Δ vs. base)",
        y_label="Max LTV",
        x_values=price_deltas_pct,
        y_values=max_ltvs,
        cells=cells,
    )


def default_tables(deal: Deal) -> list[SensitivityTable]:
    """Standard sensitivity panel for IC memos."""
    base_cap = deal.exit.exit_cap
    cap_grid = [base_cap - 0.0050, base_cap - 0.0025, base_cap, base_cap + 0.0025, base_cap + 0.0050]
    rg_mult_grid = [0.5, 0.75, 1.0, 1.25, 1.5]
    price_delta_grid = [-0.05, -0.025, 0.0, 0.025, 0.05]
    ltv_grid = [0.55, 0.60, 0.65, 0.70]

    return [
        exit_cap_x_rent_growth(deal, cap_grid, rg_mult_grid, metric="LP IRR"),
        exit_cap_x_rent_growth(deal, cap_grid, rg_mult_grid, metric="LP MOIC"),
        price_x_ltv(deal, price_delta_grid, ltv_grid, metric="LP IRR"),
    ]
