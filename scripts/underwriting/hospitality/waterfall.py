"""
waterfall.py — Acquisition waterfall for hospitality deals.

Thin shim that adapts the multifamily waterfall (../waterfall_acq) to a
HotelProForma. The vendor waterfall only consumes equity_flows_total +
deal.equity.{pref_rate, promote_pct, gp_coinvest_pct}, so the same logic
works unchanged here.
"""

from __future__ import annotations

from datetime import date

import scripts  # noqa: F401  (sets sys.path so vendor scripts import)
from returns import moic, xirr
from waterfall import run_waterfall as _vendor_waterfall

from ..waterfall_acq import PartyReturn, WaterfallResult
from .pro_forma import HotelProForma


def run_hotel_waterfall(pf: HotelProForma) -> WaterfallResult:
    deal = pf.deal
    coinvest = deal.equity.gp_coinvest_pct
    pref = deal.equity.pref_rate
    promote = deal.equity.promote_pct

    flows_dated: list[tuple[date, float]] = [(ef.period, ef.amount) for ef in pf.equity_flows_total]

    project_irr = xirr(flows_dated)
    project_moic, _, _ = moic(flows_dated)

    wf = _vendor_waterfall(flows_dated, pref_rate=pref, promote_pct=promote)

    lp_fund_flows: list[tuple[date, float]] = []
    gp_flows: list[tuple[date, float]] = []
    for (d, lp_amt), (_, gp_promote_amt) in zip(wf["lp_flows"], wf["gp_flows"]):
        if lp_amt < 0:
            lp_fund_flows.append((d, lp_amt * (1 - coinvest)))
            gp_flows.append((d, lp_amt * coinvest))
        else:
            lp_fund_flows.append((d, lp_amt * (1 - coinvest)))
            gp_pari = lp_amt * coinvest
            gp_flows.append((d, gp_pari + gp_promote_amt))

    lp_irr = xirr(lp_fund_flows)
    lp_moic_v, lp_contrib, lp_dist = moic(lp_fund_flows)
    gp_irr = xirr(gp_flows) if any(a < 0 for _, a in gp_flows) and any(a > 0 for _, a in gp_flows) else float("nan")
    gp_moic_v, gp_contrib, gp_dist = moic(gp_flows)

    return WaterfallResult(
        pref_rate=pref, promote_pct=promote,
        total_equity_irr=project_irr, total_equity_moic=project_moic,
        lp=PartyReturn(irr=lp_irr, moic=lp_moic_v, contributed=lp_contrib, distributed=lp_dist),
        gp=PartyReturn(irr=gp_irr, moic=gp_moic_v, contributed=gp_contrib, distributed=gp_dist),
    )
