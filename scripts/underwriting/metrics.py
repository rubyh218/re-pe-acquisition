"""
metrics.py — Shared institutional return metrics.

The "3-basis ROC" (return on cost / yield on cost) is the institutional
headline for development & value-add deals:

  - Untrended @ Stab: Stab NOI in Yr-1 dollars / all-in basis.
                      Strips inflation; isolates organic operating uplift.
  - Trended @ Stab:   Stab NOI as projected / all-in basis.
                      What we actually underwrite.
  - Exit FTM:         Forward-twelve-month NOI at exit / all-in basis.
                      Aligns with exit-cap convention.

Deflation factor: stab NOI / (1 + g) ** (stab_yr - 1), where g is the engine's
representative organic growth rate (rent_growth for MF, escalation avg for
commercial, ADR growth for hospitality).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReturnOnCost:
    """3-basis ROC for institutional headline display."""
    untrended_stab: float       # stab NOI deflated to Yr-1 dollars / all-in basis
    trended_stab:   float       # stab NOI as projected / all-in basis
    exit_ftm:       float       # forward-twelve-month NOI at exit / all-in basis
    stab_yr:        int         # which year is stabilized (1-indexed)
    all_in_basis:   float       # denominator (purchase + closing + capex + reserves)
    growth_rate:    float       # growth assumption used to deflate trended->untrended


def compute_roc(
    stab_noi:     float,
    exit_ftm_noi: float,
    all_in_basis: float,
    stab_yr:      int,
    growth_rate:  float,
) -> ReturnOnCost:
    """Compute 3-basis ROC.

    stab_noi: trended (as-projected) NOI in year `stab_yr` (1-indexed).
    exit_ftm_noi: forward-twelve-month NOI at sale (Year hold+1 if forward
                  exit basis, else trailing).
    growth_rate: representative organic growth rate (e.g. rent_growth or ADR
                 growth) used to back trended NOI into untrended dollars.
    """
    if all_in_basis <= 0:
        raise ValueError(f"all_in_basis must be > 0, got {all_in_basis}")
    # Guard against growth_rate <= -1 (would divide by zero or yield negative
    # deflator). At -100% growth the untrended-to-trended map is undefined;
    # fall back to no deflation.
    if growth_rate > -1:
        deflate = (1 + growth_rate) ** max(0, stab_yr - 1)
    else:
        deflate = 1.0
    untrended_stab_noi = stab_noi / deflate
    return ReturnOnCost(
        untrended_stab=untrended_stab_noi / all_in_basis,
        trended_stab=stab_noi / all_in_basis,
        exit_ftm=exit_ftm_noi / all_in_basis,
        stab_yr=stab_yr,
        all_in_basis=all_in_basis,
        growth_rate=growth_rate,
    )
