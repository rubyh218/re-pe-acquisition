"""
waterfall.py -- Infrastructure waterfall adapter.

Delegates to the shared multi-tier IRR-hurdle engine. The infra pro_forma
exposes the same .deal / .equity_flows_total contract every other engine uses.
"""

from __future__ import annotations

from ..waterfall_acq import WaterfallResult, run_acquisition_waterfall


def run_infrastructure_waterfall(pf) -> WaterfallResult:
    return run_acquisition_waterfall(pf)  # type: ignore[arg-type]
