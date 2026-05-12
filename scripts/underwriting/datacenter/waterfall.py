"""
waterfall.py -- Data center waterfall adapter (both wholesale + colo).

Delegates to the shared multi-tier IRR-hurdle engine via run_acquisition_waterfall.
Both pro_forma types expose .deal and .equity_flows_total -- the same contract
the multifamily/commercial/hospitality engines use.
"""

from __future__ import annotations

from ..waterfall_acq import WaterfallResult, run_acquisition_waterfall


def run_datacenter_waterfall(pf) -> WaterfallResult:
    """Run the standard acquisition waterfall on any DC pro_forma."""
    return run_acquisition_waterfall(pf)  # type: ignore[arg-type]
