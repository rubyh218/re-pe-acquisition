"""
waterfall_acq.py — LP / GP waterfall on PROJECTED acquisition cash flows.

Wraps vendor/asset-management/scripts/waterfall.py for the projected (forward-
looking) case. The vendor module assumes a single LP fund the entire equity;
acquisitions typically have a GP co-invest. We model:

  - Total equity flows (LP + GP combined) drive the waterfall.
  - Result is split: LP gets (1 - gp_coinvest) of the LP-tier distributions;
    GP gets gp_coinvest of LP-tier distributions PLUS the GP promote stream.

This is the standard institutional treatment — GP co-invest is pari-passu with
LP, and GP earns promote on top of that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import scripts  # noqa: F401  (sets sys.path so vendor scripts import)
from returns import moic, xirr
from waterfall import run_waterfall

from .models import Deal
from .pro_forma import EquityFlow, ProForma


@dataclass
class PartyReturn:
    irr: float
    moic: float
    contributed: float
    distributed: float


@dataclass
class WaterfallResult:
    pref_rate: float
    promote_pct: float
    total_equity_irr: float          # pre-waterfall ("project equity")
    total_equity_moic: float
    lp: PartyReturn                   # net of waterfall
    gp: PartyReturn                   # co-invest pari-passu + promote


def run_acquisition_waterfall(pf: ProForma) -> WaterfallResult:
    deal = pf.deal
    coinvest = deal.equity.gp_coinvest_pct
    pref = deal.equity.pref_rate
    promote = deal.equity.promote_pct

    flows_dated: list[tuple[date, float]] = [(ef.period, ef.amount) for ef in pf.equity_flows_total]

    # Pre-waterfall ("project equity") return on total equity
    project_irr = xirr(flows_dated)
    project_moic, project_contrib, project_dist = moic(flows_dated)

    # Run waterfall on total equity flows. The vendor treats this as 100% LP-funded.
    # We then re-attribute LP-tier distributions between LP fund (1-coinvest) and GP co-invest (coinvest).
    wf = run_waterfall(flows_dated, pref_rate=pref, promote_pct=promote)

    # LP fund's flows: pari-passu share of LP-tier distributions, contributions = (1-coinvest) of total contrib
    lp_fund_flows: list[tuple[date, float]] = []
    gp_flows: list[tuple[date, float]] = []
    for (d, lp_amt), (_, gp_promote_amt) in zip(wf["lp_flows"], wf["gp_flows"]):
        if lp_amt < 0:
            # contribution
            lp_fund_flows.append((d, lp_amt * (1 - coinvest)))
            gp_flows.append((d, lp_amt * coinvest))           # GP co-invest contribution (negative)
        else:
            # distribution from LP tiers
            lp_fund_flows.append((d, lp_amt * (1 - coinvest)))
            gp_pari = lp_amt * coinvest
            gp_flows.append((d, gp_pari + gp_promote_amt))

    lp_irr = xirr(lp_fund_flows)
    lp_moic_v, lp_contrib, lp_dist = moic(lp_fund_flows)
    gp_irr = xirr(gp_flows) if any(a < 0 for _, a in gp_flows) and any(a > 0 for _, a in gp_flows) else float("nan")
    gp_moic_v, gp_contrib, gp_dist = moic(gp_flows)

    return WaterfallResult(
        pref_rate=pref,
        promote_pct=promote,
        total_equity_irr=project_irr,
        total_equity_moic=project_moic,
        lp=PartyReturn(irr=lp_irr, moic=lp_moic_v, contributed=lp_contrib, distributed=lp_dist),
        gp=PartyReturn(irr=gp_irr, moic=gp_moic_v, contributed=gp_contrib, distributed=gp_dist),
    )
