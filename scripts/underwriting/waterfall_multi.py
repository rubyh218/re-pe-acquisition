"""
waterfall_multi.py — Multi-tier IRR-hurdle waterfall (American-style, deal-level).

Replaces the vendor 4-tier (ROC + pref + GP catch-up + carry) with the pure
IRR-hurdle model used by most institutional RE PE sponsors (incl. the 3705
Haven model used as the v5 format template).

Tier mechanics:
  Each tier maintains a "balance" interpreted as the cumulative LP-owed
  amount at that tier's IRR rate. Balance:
    - grows at the tier's hurdle_irr between events,
    - increases by every total-equity contribution,
    - decreases by LP cash received (whether through this tier or any prior).
  When a balance reaches 0, LP has achieved that tier's IRR.

Distribution rule per event:
  Fill tiers in ascending hurdle order. For tier i with promote p_i:
    - Gross capacity to satisfy tier = balance_i / (1 - p_i).
    - Pay gross = min(remaining, capacity); LP receives gross x (1 - p_i),
      GP receives gross x p_i.
    - All tier balances drop by lp_paid (LP cash reduces FV at every rate).
  Residual cash (after all capped tiers exhausted) splits per the LAST tier's
  promote_pct.

Returns LP/GP cash flows + per-tier distribution detail (for institutional
display) + IRR/MOIC for each party.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import scripts  # noqa: F401  (vendor sys.path)
from returns import moic, xirr


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tier:
    """One waterfall tier."""
    hurdle_irr: float    # upper bound of this tier (LP IRR). Ignored for the residual (last) tier.
    promote_pct: float   # GP's share of cash flow distributed within this tier.
    label: str = ""      # display label (e.g., "Preferred", "Hurdle II")


@dataclass
class TierDistribution:
    """Total cash distributed through one tier across the full hold."""
    label: str
    hurdle_irr: float
    promote_pct: float
    lp_share_pct: float          # 1 - promote_pct
    lp_total: float              # sum LP receives via this tier
    gp_total: float              # sum GP receives via this tier (promote only; co-invest separate)
    gross_total: float           # LP + GP via this tier


@dataclass
class PartyReturn:
    irr: float
    moic: float
    contributed: float
    distributed: float


@dataclass
class MultiTierResult:
    tiers: list[Tier]
    project_irr: float                   # pre-waterfall, on total equity flows
    project_moic: float
    project_contributed: float
    project_distributed: float
    lp: PartyReturn                       # net of waterfall (LP fund only, ex-GP coinvest)
    gp: PartyReturn                       # GP coinvest pari-passu + promote
    per_tier: list[TierDistribution]
    lp_flows: list[tuple[date, float]]
    gp_flows: list[tuple[date, float]]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_multi_tier_waterfall(
    flows: list[tuple[date, float]],
    tiers: list[Tier],
    gp_coinvest_pct: float = 0.0,
) -> MultiTierResult:
    """
    Run a multi-tier IRR-hurdle waterfall on total-equity cash flows.

    flows: chronological [(date, amount)] for TOTAL equity (LP + GP combined).
           Contributions negative, distributions positive.
    tiers: ordered ascending by hurdle_irr; the LAST tier is the residual
           (its hurdle_irr is not used).
    gp_coinvest_pct: GP's pari-passu share of the equity check (0..1).
    """
    if not tiers:
        raise ValueError("tiers must be non-empty")
    if not flows:
        raise ValueError("flows must be non-empty")
    if not 0 <= gp_coinvest_pct <= 1:
        raise ValueError(f"gp_coinvest_pct out of range: {gp_coinvest_pct}")

    sorted_flows = sorted(flows, key=lambda x: x[0])

    # Capped tiers (with finite hurdle): all but the last.
    n_capped = len(tiers) - 1
    balances = [0.0] * n_capped

    lp_flows: list[tuple[date, float]] = []
    gp_flows: list[tuple[date, float]] = []
    per_tier_totals: list[TierDistribution] = []
    for t in tiers:
        per_tier_totals.append(TierDistribution(
            label=t.label, hurdle_irr=t.hurdle_irr, promote_pct=t.promote_pct,
            lp_share_pct=1 - t.promote_pct,
            lp_total=0.0, gp_total=0.0, gross_total=0.0,
        ))

    prev_date = sorted_flows[0][0]

    for current_date, amount in sorted_flows:
        # 1. Accrue balances at each tier's hurdle rate
        years = (current_date - prev_date).days / 365.0
        if years > 0:
            for i in range(n_capped):
                if balances[i] > 0:
                    balances[i] *= (1 + tiers[i].hurdle_irr) ** years

        if amount < 0:
            # Contribution: grows ALL tier balances by the full contribution amount
            for i in range(n_capped):
                balances[i] += -amount
            # Pari-passu LP/GP split
            lp_share = amount * (1 - gp_coinvest_pct)   # negative
            gp_share = amount * gp_coinvest_pct         # negative
            lp_flows.append((current_date, lp_share))
            gp_flows.append((current_date, gp_share))
        elif amount > 0:
            # Distribution: fill capped tiers, then residual
            remaining = amount
            lp_this_event = 0.0
            gp_promote_this_event = 0.0

            for i in range(n_capped):
                if remaining <= 1e-9 or balances[i] <= 1e-9:
                    continue
                tier = tiers[i]
                lp_pct = 1 - tier.promote_pct
                if lp_pct <= 0:
                    raise ValueError(f"tier {i} ({tier.label}): promote_pct >= 1 invalid")
                gross_capacity = balances[i] / lp_pct
                gross_paid = min(remaining, gross_capacity)
                lp_paid = gross_paid * lp_pct
                gp_paid = gross_paid * tier.promote_pct

                # Reduce all tier balances by LP paid (LP receiving reduces FV-balances at every rate)
                for j in range(n_capped):
                    balances[j] = max(0.0, balances[j] - lp_paid)

                lp_this_event += lp_paid
                gp_promote_this_event += gp_paid
                per_tier_totals[i].lp_total += lp_paid
                per_tier_totals[i].gp_total += gp_paid
                per_tier_totals[i].gross_total += gross_paid
                remaining -= gross_paid

            # Residual tier (last)
            if remaining > 1e-9:
                residual = tiers[-1]
                lp_paid = remaining * (1 - residual.promote_pct)
                gp_paid = remaining * residual.promote_pct
                lp_this_event += lp_paid
                gp_promote_this_event += gp_paid
                per_tier_totals[-1].lp_total += lp_paid
                per_tier_totals[-1].gp_total += gp_paid
                per_tier_totals[-1].gross_total += remaining

            # Split the LP-tier cash pari-passu between LP fund and GP coinvest
            lp_fund_amt = lp_this_event * (1 - gp_coinvest_pct)
            gp_coinv_amt = lp_this_event * gp_coinvest_pct
            lp_flows.append((current_date, lp_fund_amt))
            gp_flows.append((current_date, gp_coinv_amt + gp_promote_this_event))
        else:
            # amount == 0: record zero flows so dates align
            lp_flows.append((current_date, 0.0))
            gp_flows.append((current_date, 0.0))

        prev_date = current_date

    # Project-level (total equity, pre-waterfall) metrics
    project_irr = xirr(sorted_flows)
    project_moic, project_contrib, project_dist = moic(sorted_flows)

    # LP / GP party returns
    lp_irr = xirr(lp_flows) if _has_both_signs(lp_flows) else float("nan")
    lp_moic_v, lp_contrib, lp_dist = moic(lp_flows)
    gp_irr = xirr(gp_flows) if _has_both_signs(gp_flows) else float("nan")
    gp_moic_v, gp_contrib, gp_dist = moic(gp_flows)

    return MultiTierResult(
        tiers=list(tiers),
        project_irr=project_irr,
        project_moic=project_moic,
        project_contributed=project_contrib,
        project_distributed=project_dist,
        lp=PartyReturn(irr=lp_irr, moic=lp_moic_v, contributed=lp_contrib, distributed=lp_dist),
        gp=PartyReturn(irr=gp_irr, moic=gp_moic_v, contributed=gp_contrib, distributed=gp_dist),
        per_tier=per_tier_totals,
        lp_flows=lp_flows,
        gp_flows=gp_flows,
    )


def _has_both_signs(flows: list[tuple[date, float]]) -> bool:
    has_neg = any(a < 0 for _, a in flows)
    has_pos = any(a > 0 for _, a in flows)
    return has_neg and has_pos


# ---------------------------------------------------------------------------
# Legacy adapter — build tiers from single pref + promote
# ---------------------------------------------------------------------------

def legacy_tiers(pref_rate: float, promote_pct: float) -> list[Tier]:
    """Convert legacy single-tier (pref_rate + promote_pct) into a 2-tier list.

    Tier 0: pref tier (0% promote, LP gets all up to pref IRR).
    Tier 1: residual (promote_pct applies above pref).

    Note: this does NOT replicate the vendor "GP catch-up" tier. v5 uses pure
    IRR-hurdle (no catch-up), which is the 3705 Haven institutional convention.
    """
    return [
        Tier(hurdle_irr=pref_rate, promote_pct=0.0, label="Preferred Return"),
        Tier(hurdle_irr=0.0, promote_pct=promote_pct, label="Residual"),  # hurdle_irr ignored for residual
    ]
