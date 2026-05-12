"""
waterfall_acq.py — LP / GP multi-tier IRR-hurdle waterfall on projected flows.

Thin adapter over `waterfall_multi.run_multi_tier_waterfall` that:
  - Resolves the tier list from `Deal.equity` (explicit tiers or legacy
    pref_rate + promote_pct via the auto-generated 2-tier list).
  - Maps multi-tier engine output to the historical `WaterfallResult` shape so
    existing call sites (cli.py, excel_writer.py) keep working.
  - Preserves the full multi-tier detail via `per_tier` and `tiers` fields,
    which the v5 institutional writer consumes.

GP co-invest is pari-passu with LP; promote stacks on top. The pari-passu split
is performed inside the multi-tier engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import Deal
from .pro_forma import ProForma
from .waterfall_multi import (
    MultiTierResult,
    PartyReturn,
    Tier,
    TierDistribution,
    run_multi_tier_waterfall,
)


@dataclass
class WaterfallResult:
    # Legacy fields (kept for CLI / existing Excel writer)
    pref_rate: float
    promote_pct: float
    total_equity_irr: float
    total_equity_moic: float
    lp: PartyReturn
    gp: PartyReturn
    # v5 multi-tier fields
    tiers: list[Tier]
    per_tier: list[TierDistribution]
    lp_flows: list[tuple[date, float]]
    gp_flows: list[tuple[date, float]]


def _deal_tiers(deal: Deal) -> list[Tier]:
    """Translate Deal.equity.waterfall_tiers (pydantic) into engine Tiers (frozen dc)."""
    return [
        Tier(hurdle_irr=t.hurdle_irr, promote_pct=t.promote_pct, label=t.label)
        for t in deal.equity.waterfall_tiers
    ]


def run_acquisition_waterfall(pf: ProForma) -> WaterfallResult:
    deal = pf.deal
    tiers = _deal_tiers(deal)
    flows: list[tuple[date, float]] = [(ef.period, ef.amount) for ef in pf.equity_flows_total]

    res: MultiTierResult = run_multi_tier_waterfall(
        flows=flows,
        tiers=tiers,
        gp_coinvest_pct=deal.equity.gp_coinvest_pct,
    )

    return WaterfallResult(
        pref_rate=deal.equity.pref_rate,
        promote_pct=deal.equity.promote_pct,
        total_equity_irr=res.project_irr,
        total_equity_moic=res.project_moic,
        lp=res.lp,
        gp=res.gp,
        tiers=res.tiers,
        per_tier=res.per_tier,
        lp_flows=res.lp_flows,
        gp_flows=res.gp_flows,
    )
