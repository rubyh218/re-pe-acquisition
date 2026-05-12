"""
waterfall.py — Hospitality-deal adapter over the multi-tier IRR-hurdle engine.

Delegates to `..waterfall_acq.run_acquisition_waterfall`; both engines consume
the same equity_flows_total + Deal.equity contract.
"""

from __future__ import annotations

from ..waterfall_acq import WaterfallResult, run_acquisition_waterfall
from .pro_forma import HotelProForma


def run_hotel_waterfall(pf: HotelProForma) -> WaterfallResult:
    return run_acquisition_waterfall(pf)  # type: ignore[arg-type]
