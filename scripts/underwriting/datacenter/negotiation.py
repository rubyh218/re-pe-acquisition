"""
negotiation.py -- Data center deal negotiation playbook.

Two structured tactic catalogs surfaced in the IC memo for DC deals:

  ACQUISITION_TACTICS
      Buyer-side tactics for negotiating the LOI / PSA -- price discovery,
      DD carve-outs, R&W, escrow, environmental, financing contingency,
      power capacity transfer, contract assignment, holdbacks.

  LEASING_TACTICS
      Landlord-side tactics for negotiating wholesale lease terms (hyperscale
      tenant-of-credit deals) and colo MSAs -- TI/LC, free rent, escalation
      structure, expansion options, ROFR/ROFO, SLA/uptime credits, power
      capacity reservations, MSA pricing tiers, cross-connect ARPU.

Each Tactic has:
  - title           short imperative tag for the table row
  - category        bucket (Price / Risk / Terms / etc.)
  - lever           what the negotiator can move
  - typical_range   institutional convention range (string -- mixed units)
  - rationale       why it matters / where it shows up in the model
  - applies_to      "wholesale" | "colo" | "both" (leasing only)

The lists below encode the institutional playbook -- they are static defaults.
A future enhancement could pull deal-specific tactics from the YAML and merge
them with these baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Tactic:
    title: str
    category: str
    lever: str
    typical_range: str
    rationale: str
    applies_to: Literal["wholesale", "colo", "both"] = "both"


# ---------------------------------------------------------------------------
# ACQUISITION (buyer-side, LOI / PSA / closing)
# ---------------------------------------------------------------------------

ACQUISITION_TACTICS: list[Tactic] = [
    Tactic(
        title="Cap-rate-based price discovery",
        category="Price",
        lever="Establish a going-in cap floor anchored to a trailing-12 NOI net of below-the-line items (mgmt fee, reserves) rather than seller's pro-forma.",
        typical_range="50-100 bps wider than seller ask",
        rationale="Hyperscale wholesale traded inside 5% in 2023-24; current re-pricing is 75-150 bps wider. Anchor on cap, not headline price.",
    ),
    Tactic(
        title="Power capacity transfer assurance",
        category="Risk",
        lever="Require seller to deliver fully-executed utility power purchase agreement (PPA) assignment + interconnect agreement at close with no consent fees.",
        typical_range="Pre-close PUC consent letter required",
        rationale="A DC without unencumbered power capacity is unleasable. PPA assignment is non-negotiable in modern transactions; capture the risk in writing.",
    ),
    Tactic(
        title="Tenant estoppels at close",
        category="Risk",
        lever="100% tenant estoppels (no thresholding) confirming rent, commencement, defaults, ROFR exercise status, and any pass-through reconciliations.",
        typical_range="100% of MW under lease",
        rationale="DC leases are MW-denominated and credit-driven; one disputed lease can sink the going-in NOI. No estoppel = no closing.",
    ),
    Tactic(
        title="Environmental Phase II + battery/generator audit",
        category="Risk",
        lever="Phase II ESA + standalone audit on UPS battery age, generator runtime hours, and fuel tank integrity. Negotiate seller credit if remaining useful life < 50% of replacement reserve assumption.",
        typical_range="$5-15K/MW credit if RUL deficient",
        rationale="Battery / generator replacement is six-figure-per-MW. Wholesale leases often pass through capex via reserves; missing the diligence shifts cost to buyer.",
    ),
    Tactic(
        title="DD-period carve-out for hyperscale tenant interview",
        category="Diligence",
        lever="Direct interview with each anchor tenant's real-estate counterparty during DD, separate from estoppels. Probe expansion intent, renewal economics, contract usage.",
        typical_range="60-90 day DD with tenant interview clause",
        rationale="Renewal probability is the single biggest IRR driver in wholesale (~80% institutional default). Verify, don't assume.",
    ),
    Tactic(
        title="Financing contingency with rate-cap reset",
        category="Capital Markets",
        lever="LOI contingent on debt with stated max rate / min LTV; reset trigger if SOFR moves > 50 bps during DD.",
        typical_range="50-bp SOFR trigger; max LTV 55-60%",
        rationale="DC debt market is thin; lenders re-trade on macro moves. Lock the contingency or wear the risk.",
    ),
    Tactic(
        title="Rep & warranty insurance + reduced escrow",
        category="Risk Allocation",
        lever="RWI policy in lieu of large indemnity escrow; cap seller indemnity at retention amount.",
        typical_range="RWI premium ~3-4% of limit; retention 0.5-1.0% of EV",
        rationale="Hyperscale sellers (REITs, infrastructure funds) push back on long-tailed indemnity. RWI clears the cap table at close for both sides.",
    ),
    Tactic(
        title="Earn-out on lease-up / commissioning",
        category="Price Bridge",
        lever="Cash holdback released against MW commissioned and leased within 12-24 months post-close; tied to specific tenant credits and $/kW thresholds.",
        typical_range="5-15% of EV, 12-24 mo release",
        rationale="Bridges the bid-ask on unleased capacity. Seller keeps optionality on pricing; buyer underwrites only contracted capacity at close.",
    ),
    Tactic(
        title="Capex true-up at close",
        category="Working Capital",
        lever="Adjust price for actual vs. budgeted capex through close date; verify with independent engineer's report (IER).",
        typical_range="$ for $ adjustment vs. project budget",
        rationale="Greenfield / partially-commissioned DCs often have rolling capex. Anchor the true-up to the IER, not management's report.",
    ),
    Tactic(
        title="Reserve true-up on operating accounts",
        category="Working Capital",
        lever="Buyer assumes operating reserves at fair value with prorated adjustment for collected vs. earned tenant CAM / power reconciliations.",
        typical_range="Standard prorated adjustments",
        rationale="Power reconciliations can be 60-90 days behind actual usage. Net out without taking unintended P&L exposure.",
    ),
]


# ---------------------------------------------------------------------------
# LEASING (landlord-side, lease execution after close)
# ---------------------------------------------------------------------------

LEASING_TACTICS: list[Tactic] = [
    # --- Wholesale ---
    Tactic(
        title="Power-based pricing escalation",
        category="Rent Structure",
        lever="Negotiate fixed annual escalation on rent ($/kW/mo) separate from utility pass-through; resist CPI-based escalators in hyperscale leases.",
        typical_range="2.5-3.0% fixed annual",
        rationale="Hyperscale tenants prefer fixed escalators; CPI exposes landlord to inflation reset on rent but not on utility passthrough margin.",
        applies_to="wholesale",
    ),
    Tactic(
        title="Power pass-through structure",
        category="Power Economics",
        lever="Structure as full pass-through at cost + 5-10% landlord margin (partial), not bundled into base rent. Tenant bears utility-rate risk; landlord earns margin on metered draw.",
        typical_range="5-10% margin multiplier",
        rationale="Bundling power = landlord eats utility inflation. Pass-through with margin is the institutional default; preserves NOI durability and avoids re-trading on rate moves.",
        applies_to="wholesale",
    ),
    Tactic(
        title="Critical-MW reservation fees",
        category="Capacity",
        lever="Tenant pays reservation fee on committed-but-undrawn MW from lease signing through commissioning; fee converts to rent at commissioning date.",
        typical_range="60-80% of full rent on reserved MW pre-commissioning",
        rationale="Bridges the gap from signing to ready-for-service (RFS). Tenant locks capacity; landlord doesn't carry leasable MW unpriced.",
        applies_to="wholesale",
    ),
    Tactic(
        title="ROFR / ROFO on contiguous capacity",
        category="Expansion",
        lever="Grant ROFR on adjacent MW with 30-day decision window; require tenant to match third-party offer including escalators and term.",
        typical_range="30-60 day ROFR window",
        rationale="Hyperscale tenants pay for expansion certainty; landlord wins better economics from competitive third-party offers if tenant declines.",
        applies_to="wholesale",
    ),
    Tactic(
        title="Uptime / SLA credits",
        category="Service Level",
        lever="Concurrently-maintainable Tier III commitment (99.982% annual uptime); credits capped at one month's rent per incident with carve-outs for force majeure, scheduled maintenance, tenant equipment.",
        typical_range="99.982-99.995% uptime; 1-mo credit cap",
        rationale="Tenants negotiate hard on SLA; landlord caps liability at credits and excludes off-the-fence events. Carve-outs protect NOI from operational risk.",
        applies_to="both",
    ),
    Tactic(
        title="Renewal economics defined at signing",
        category="Renewal",
        lever="Embed renewal terms in initial lease: fair market rent with floor (no discount to in-place), term 7-10 yrs, escalation continuity.",
        typical_range="FMR with floor at last in-place rent + 5%",
        rationale="Renewal probability is the biggest IRR lever (default 80%). Lock the floor at signing or wear the negotiation later at maximum tenant leverage.",
        applies_to="wholesale",
    ),
    Tactic(
        title="Limited TI; no landlord-side fit-out",
        category="Capex",
        lever="Wholesale tenants self-fund servers, racks, cooling distribution at the rack level; landlord delivers shell + power + cooling backbone only.",
        typical_range="$0-25/kW landlord TI (de minimis)",
        rationale="Hyperscale tenant fit-out is bespoke; cleaner economics + faster signing if landlord stays out of TI negotiations.",
        applies_to="wholesale",
    ),
    Tactic(
        title="Lease term + early termination",
        category="Term",
        lever="10-15 yr initial term with no early termination right except landlord uncured default; survival of payment obligations to lease end.",
        typical_range="10-15 yrs initial; no ET right",
        rationale="Long-dated, no-out leases are why hyperscale DC trades at sub-6% caps. ET rights collapse value.",
        applies_to="wholesale",
    ),
    # --- Colo ---
    Tactic(
        title="Cross-connect pricing as separate SKU",
        category="Ancillary Revenue",
        lever="Price cross-connects separately from cabinet MRR; $250-500/mo per XC, escalated annually 3%.",
        typical_range="$250-500/mo per XC; 3% escalation",
        rationale="XC is the highest-margin revenue line in colo (90%+ margin). Decoupling lets landlord price-discriminate across customer tiers without cabinet-rate concessions.",
        applies_to="colo",
    ),
    Tactic(
        title="Power overage billing",
        category="Power Economics",
        lever="Contracted kW per cabinet plus metered overage at cost + 15-25% landlord margin; quarterly true-up.",
        typical_range="Overage billed at 1.15-1.25x utility cost",
        rationale="Colo tenants often draw above contracted kW. Margin on overage is pure upside; lacking it leaves landlord eating utility cost increases.",
        applies_to="colo",
    ),
    Tactic(
        title="MSA tier pricing + commit discounts",
        category="Rent Structure",
        lever="Tiered MRR by cabinet count: 1-9 / 10-49 / 50+ commits get progressive discount (e.g., 0% / 5% / 10%) in exchange for 3+ year terms.",
        typical_range="0% / 5% / 10% commit discount",
        rationale="Anchor accounts justify discount via stickier renewals and faster ramp. Single-cabinet customers churn at 3-4x the rate.",
        applies_to="colo",
    ),
    Tactic(
        title="Remote / smart hands ancillary",
        category="Ancillary Revenue",
        lever="Bundle X hours/month included; bill incremental hours at $150-300/hr.",
        typical_range="$150-300/hr incremental; 2-4 hrs included",
        rationale="Operating-leverage revenue with no cost to add. Surfaces as ~10-15% of total revenue at well-run colo facilities.",
        applies_to="colo",
    ),
    Tactic(
        title="Setup / NRC fees on new contracts",
        category="One-Time Revenue",
        lever="Non-recurring charge (NRC) for cabinet activation, power circuit installation, cross-connect setup, KVM provisioning.",
        typical_range="$500-2000 NRC per cabinet activation",
        rationale="Captures landlord's one-time cost + margin; signals tenant commitment vs. tire-kickers.",
        applies_to="colo",
    ),
    Tactic(
        title="Term commit with auto-renewal",
        category="Term",
        lever="36-mo initial term, 12-mo auto-renewal with 90-day notice; mid-term rate adjustment cap at CPI + 200 bps.",
        typical_range="3-yr initial + 1-yr evergreens",
        rationale="Shorter than wholesale but longer than MTM; balances tenant flex against landlord NOI durability. Auto-renewal reduces sales cost.",
        applies_to="colo",
    ),
    Tactic(
        title="SLA structure with measured credits",
        category="Service Level",
        lever="99.99% uptime, credits as % of monthly MRR per outage hour beyond first 5 minutes; total monthly credits capped at 50% of MRR.",
        typical_range="99.99% uptime; 50% MRR credit cap",
        rationale="Lower bar than wholesale (Tier III SLA), but explicit measurement and caps. Caps avoid free-rent outcomes from minor incidents.",
        applies_to="colo",
    ),
]


# ---------------------------------------------------------------------------
# Memo helpers
# ---------------------------------------------------------------------------

def acquisition_table_rows() -> list[list[str]]:
    """Return rows for the acquisition tactics table in the IC memo."""
    return [[t.title, t.category, t.lever, t.typical_range, t.rationale] for t in ACQUISITION_TACTICS]


def leasing_table_rows(kind: Literal["wholesale", "colo"]) -> list[list[str]]:
    """Return leasing rows filtered to the deal kind (wholesale or colo)."""
    return [
        [t.title, t.category, t.lever, t.typical_range, t.rationale]
        for t in LEASING_TACTICS
        if t.applies_to in (kind, "both")
    ]
