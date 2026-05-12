"""
models.py -- Data center Deal schemas (wholesale + colo).

Two top-level Deal classes share a single subpackage:

  DCWholesaleDeal  -- MW-priced lease model (commercial-pattern).
  DCColoDeal       -- Cabinet-mix MRR model (multifamily-pattern).

The dispatch convention is: whichever revenue list is populated determines
the engine.

Acquisition / Debt / Equity / Exit are reused from the multifamily schemas.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import Acquisition, Debt, Equity, Exit


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ===========================================================================
# Shared: power capacity descriptors (apply to both wholesale and colo)
# ===========================================================================

TierRating = Literal["Tier I", "Tier II", "Tier III", "Tier IV"]
# Uptime Institute tier classification. Tier III ("concurrently maintainable")
# is the institutional minimum for hyperscale leases; Tier IV is fully
# fault-tolerant. Most modern wholesale stock is Tier III.


# ===========================================================================
# WHOLESALE (commercial-pattern)
# ===========================================================================

# ---------------------------------------------------------------------------
# Contract (one row of the lease roster) -- wholesale only
# ---------------------------------------------------------------------------

PassThrough = Literal["full", "partial", "none"]
# Power treatment:
#   full     -- tenant pays metered power directly to utility OR reimburses 100%
#               of metered power at cost; landlord neutral on power.
#   partial  -- landlord bills tenant for metered power + a margin (e.g., 1.05x);
#               margin is income to the landlord but small.
#   none     -- power is bundled into rent (rare in wholesale); landlord pays
#               utility and bears price/usage risk.


class Contract(_Frozen):
    """One executed wholesale lease, as of close_date.

    Wholesale leases are MW-denominated and priced in $/kW/month.  By
    institutional convention rents are quoted on the *contracted* (leased)
    capacity, not on actual draw.
    """
    tenant: str
    suite: str | None = None
    mw_leased: float = Field(gt=0)               # contracted critical IT load (MW)
    base_rent_kw_mo: float = Field(gt=0)         # $/kW/month on leased MW
    lease_start: date
    lease_end: date
    escalation_pct: float = Field(default=0.025, ge=0, le=0.10)   # annual
    free_rent_remaining_mo: int = Field(default=0, ge=0)
    power_pass_through: PassThrough = "full"

    # Optional per-contract overrides
    market_rent_kw_mo_override: float | None = Field(default=None, gt=0)
    renewal_prob_override: float | None = Field(default=None, ge=0, le=1.0)

    @model_validator(mode="after")
    def _check_dates(self):
        if self.lease_end <= self.lease_start:
            raise ValueError(f"{self.tenant}: lease_end must be after lease_start")
        return self

    @property
    def annual_base_rent(self) -> float:
        """Contracted annual base rent at current rate (12 * kW * $/kW/mo)."""
        return self.base_rent_kw_mo * (self.mw_leased * 1000) * 12


# ---------------------------------------------------------------------------
# Wholesale market (re-leasing assumptions on rollover)
# ---------------------------------------------------------------------------

class DCWholesaleMarket(_Frozen):
    """Market assumptions applied when a wholesale contract rolls."""
    market_rent_kw_mo: float = Field(gt=0)                 # current market $/kW/mo
    market_rent_growth: float = Field(default=0.03, ge=-0.05, le=0.15)

    # New contract terms
    new_lease_term_yrs: int = Field(default=10, gt=0, le=20)
    new_escalation_pct: float = Field(default=0.025, ge=0, le=0.10)
    new_free_rent_mo: int = Field(default=0, ge=0)
    new_ti_kw: float = Field(default=0, ge=0)              # $/kW one-time landlord fit-out (rare in wholesale)
    new_lc_pct: float = Field(default=0.04, ge=0, le=0.15) # of first-year rent (approx broker fee)
    downtime_mo: int = Field(default=3, ge=0, le=24)       # months vacant between contracts

    # Renewal terms
    renewal_lease_term_yrs: int = Field(default=7, gt=0, le=20)
    renewal_escalation_pct: float = Field(default=0.025, ge=0, le=0.10)
    renewal_free_rent_mo: int = Field(default=0, ge=0)
    renewal_ti_kw: float = Field(default=0, ge=0)
    renewal_lc_pct: float = Field(default=0.02, ge=0, le=0.10)

    renewal_prob: float = Field(default=0.80, ge=0, le=1.0)  # wholesale tenants stickier than office

    # Power margin on partial pass-through contracts (multiplier applied to
    # utility cost when billing tenant; e.g., 1.05 = 5% landlord margin).
    power_margin_multiplier: float = Field(default=1.05, ge=1.0, le=1.30)
    utility_rate_kwh: float = Field(default=0.08, ge=0)     # $/kWh blended utility rate
    utility_rate_growth: float = Field(default=0.03, ge=-0.05, le=0.15)


# ---------------------------------------------------------------------------
# Wholesale OpEx
# ---------------------------------------------------------------------------

class DCWholesaleOpEx(_Frozen):
    """Wholesale data center OpEx.

    Power for leased space is generally a pass-through; this OpEx structure
    captures the landlord's controllable cost base (security, mech/elec staff,
    insurance, RE tax, mgmt) plus property-level utilities (common areas,
    cooling for unleased capacity, etc.).
    """
    # Per-MW (critical) annual $
    security_per_mw: float = Field(default=15000, ge=0)
    mep_staffing_per_mw: float = Field(default=80000, ge=0)   # mechanical/electrical/plumbing technicians
    insurance_per_mw: float = Field(default=8000, ge=0)
    common_power_per_mw: float = Field(default=12000, ge=0)   # non-passed-through utility (common areas, cooling overhead)

    re_tax: float = Field(ge=0)                                # annual total $
    mgmt_fee_pct: float = Field(default=0.02, ge=0, le=0.10)   # % of EGI
    non_recoverable_per_mw: float = Field(default=5000, ge=0)  # G&A, legal, marketing

    # Growth rates
    controllable_growth: float = 0.03      # applied to security/staffing/common power/non-rec
    re_tax_growth:        float = 0.03
    insurance_growth:     float = 0.04


# ---------------------------------------------------------------------------
# Wholesale CapEx
# ---------------------------------------------------------------------------

class DCWholesaleCapEx(_Frozen):
    initial_building_capex: float = Field(default=0, ge=0)      # day-1 fit-out beyond purchase
    recurring_reserve_per_mw: float = Field(default=20000, ge=0)  # $/MW/yr replacement reserves (UPS, generators, chillers)


# ---------------------------------------------------------------------------
# Wholesale property
# ---------------------------------------------------------------------------

class DCWholesaleProperty(_Frozen):
    name: str
    address: str
    submarket: str
    year_built: int
    asset_class: Literal["datacenter_wholesale"] = "datacenter_wholesale"

    mw_critical: float = Field(gt=0)              # total designed critical IT MW
    mw_commissioned: float = Field(gt=0)          # MW currently powered and ready to lease
    pue: float = Field(default=1.40, gt=1.0, le=2.0)   # power usage effectiveness (total / IT load)
    tier_rating: TierRating = "Tier III"
    total_gross_sf: int | None = Field(default=None, gt=0)   # optional building footprint

    contracts: list[Contract] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_capacity(self):
        if self.mw_commissioned > self.mw_critical:
            raise ValueError(
                f"mw_commissioned ({self.mw_commissioned}) cannot exceed "
                f"mw_critical ({self.mw_critical})"
            )
        leased = sum(c.mw_leased for c in self.contracts)
        if leased > self.mw_commissioned + 1e-6:
            raise ValueError(
                f"contracted MW ({leased:.2f}) exceeds mw_commissioned "
                f"({self.mw_commissioned:.2f})"
            )
        return self

    @property
    def leased_mw(self) -> float:
        return sum(c.mw_leased for c in self.contracts)

    @property
    def available_mw(self) -> float:
        return self.mw_commissioned - self.leased_mw

    @property
    def utilization_pct(self) -> float:
        """Leased / commissioned MW."""
        return self.leased_mw / self.mw_commissioned if self.mw_commissioned else 0.0

    @property
    def in_place_annual_rent(self) -> float:
        return sum(c.annual_base_rent for c in self.contracts)


# ---------------------------------------------------------------------------
# Top-level wholesale Deal
# ---------------------------------------------------------------------------

class DCWholesaleDeal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: DCWholesaleProperty
    acquisition: Acquisition
    market: DCWholesaleMarket
    opex: DCWholesaleOpEx
    capex: DCWholesaleCapEx
    debt: Debt
    equity: Equity
    exit: Exit


# ===========================================================================
# COLO (multifamily-pattern)
# ===========================================================================

# ---------------------------------------------------------------------------
# Cabinet type (analog of UnitType)
# ---------------------------------------------------------------------------

class CabinetType(_Frozen):
    """One cabinet SKU in the colo inventory.

    Pricing is per-cabinet monthly recurring revenue (MRR), inclusive of a
    contracted power allotment (kW per cabinet).  Overage power is billed
    separately (see ColoMarket.overage_power_psf_per_kw).
    """
    name: str                                    # "Standard 5kW", "High-Density 10kW", "Half-Cabinet"
    count: int = Field(gt=0)                     # available inventory
    kw_per_cabinet: float = Field(gt=0)          # contracted power allotment
    in_place_mrr: float = Field(gt=0)            # current in-place MRR per cabinet ($/mo)
    market_mrr: float = Field(gt=0)              # current market MRR per cabinet ($/mo)

    @property
    def in_place_annual_rent(self) -> float:
        return self.in_place_mrr * self.count * 12

    @property
    def market_annual_rent(self) -> float:
        return self.market_mrr * self.count * 12

    @property
    def total_kw(self) -> float:
        return self.kw_per_cabinet * self.count

    @property
    def loss_to_lease(self) -> float:
        return (self.market_mrr - self.in_place_mrr) * self.count * 12


# ---------------------------------------------------------------------------
# Colo revenue assumptions
# ---------------------------------------------------------------------------

class ColoRevenue(_Frozen):
    """Revenue and lease-up assumptions for a colo property."""
    # Occupancy ramp -- fraction of cabinets occupied by year. Must have
    # >= hold_yrs (+1 for forward exit) entries.
    occupancy: list[float] = Field(min_length=1)

    # MRR growth applied annually to both in-place and market MRR.
    mrr_growth: float = Field(default=0.03, ge=-0.05, le=0.15)

    # Bad debt / credit loss (% of gross rent)
    bad_debt: float = Field(default=0.01, ge=0, le=0.05)

    # Concessions Yr 1 (% of gross rent, burns off by Yr 3)
    concessions_yr1: float = Field(default=0.0, ge=0, le=0.10)

    # Cross-connects: one-time install + monthly recurring per cross-connect.
    # We model cross-connects per occupied cabinet.
    xc_per_cabinet: float = Field(default=2.0, ge=0)           # avg cross-connects per occupied cabinet
    xc_mrr_each: float = Field(default=300, ge=0)              # monthly recurring revenue per cross-connect
    xc_mrr_growth: float = Field(default=0.03, ge=-0.05, le=0.15)

    # Other income (remote hands, smart hands, setup fees) -- $/occupied cabinet/mo
    other_income_per_cabinet_mo: float = Field(default=150, ge=0)
    other_income_growth: float = Field(default=0.03, ge=-0.05, le=0.15)


# ---------------------------------------------------------------------------
# Colo OpEx
# ---------------------------------------------------------------------------

class ColoOpEx(_Frozen):
    """Colo OpEx -- mirrors hospitality PAR convention but on a per-cabinet basis."""
    # Per-cabinet annual $
    payroll_per_cabinet: float = Field(default=600, ge=0)       # techs, security, NOC
    rm_per_cabinet: float = Field(default=400, ge=0)            # repairs & maintenance
    marketing_per_cabinet: float = Field(default=150, ge=0)
    insurance_per_cabinet: float = Field(default=100, ge=0)
    other_per_cabinet: float = Field(default=200, ge=0)

    # Power -- colo landlord is typically responsible for full power bill
    # and recovers via contracted allotment + overage charges.
    utility_rate_kwh: float = Field(default=0.09, ge=0)         # $/kWh blended
    utility_rate_growth: float = Field(default=0.03, ge=-0.05, le=0.15)
    pue_uplift: float = Field(default=1.40, gt=1.0, le=2.0)     # multiplier: total power / IT power

    re_tax: float = Field(ge=0)                                  # annual total $
    re_tax_growth: float = Field(default=0.03, ge=-0.05, le=0.15)

    mgmt_fee_pct: float = Field(default=0.04, ge=0, le=0.10)    # % of EGI
    controllable_growth: float = Field(default=0.03, ge=-0.05, le=0.15)


# ---------------------------------------------------------------------------
# Colo CapEx
# ---------------------------------------------------------------------------

class ColoCapEx(_Frozen):
    """Colo capex -- value-add fit-out + recurring reserves.

    Mirrors multifamily value-add: refit cabinets to high-density / Edge / AI
    standards, lift MRR.  Fit-out is fronted on a per-cabinet basis and the
    rollout schedule is a percentage-of-inventory list (must sum to ~1.0).
    """
    fit_out_per_cabinet: float = Field(default=0, ge=0)
    cabinets_renovated_pct: list[float] = Field(default_factory=list)   # by year, must sum ~1.0
    mrr_uplift_per_cabinet: float = Field(default=0, ge=0)              # $/mo MRR uplift on refitted cabinets
    common_capex: float = Field(default=0, ge=0)                         # one-time Yr 1 building/MEP
    recurring_reserve_per_cabinet: float = Field(default=400, ge=0)      # $/cabinet/yr

    @model_validator(mode="after")
    def _check_schedule(self):
        if self.fit_out_per_cabinet > 0 and not self.cabinets_renovated_pct:
            raise ValueError("cabinets_renovated_pct required when fit_out_per_cabinet > 0")
        if self.cabinets_renovated_pct and abs(sum(self.cabinets_renovated_pct) - 1.0) > 0.01:
            raise ValueError(
                f"cabinets_renovated_pct must sum to ~1.0, got "
                f"{sum(self.cabinets_renovated_pct):.3f}"
            )
        return self


# ---------------------------------------------------------------------------
# Colo property
# ---------------------------------------------------------------------------

class DCColoProperty(_Frozen):
    name: str
    address: str
    submarket: str
    year_built: int
    asset_class: Literal["datacenter_colo"] = "datacenter_colo"

    mw_critical: float = Field(gt=0)              # designed critical IT MW
    pue: float = Field(default=1.50, gt=1.0, le=2.0)
    tier_rating: TierRating = "Tier III"
    total_gross_sf: int | None = Field(default=None, gt=0)

    cabinet_mix: list[CabinetType] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_kw(self):
        total_kw = sum(c.total_kw for c in self.cabinet_mix)
        commissioned_kw = self.mw_critical * 1000
        if total_kw > commissioned_kw + 1e-3:
            raise ValueError(
                f"sum of cabinet kW ({total_kw:.1f}) exceeds critical kW "
                f"({commissioned_kw:.1f})"
            )
        return self

    @property
    def total_cabinets(self) -> int:
        return sum(c.count for c in self.cabinet_mix)

    @property
    def total_contracted_kw(self) -> float:
        return sum(c.total_kw for c in self.cabinet_mix)

    @property
    def in_place_gross_rent(self) -> float:
        return sum(c.in_place_annual_rent for c in self.cabinet_mix)

    @property
    def market_gross_rent(self) -> float:
        return sum(c.market_annual_rent for c in self.cabinet_mix)


# ---------------------------------------------------------------------------
# Top-level colo Deal
# ---------------------------------------------------------------------------

class DCColoDeal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: DCColoProperty
    acquisition: Acquisition
    revenue: ColoRevenue
    opex: ColoOpEx
    capex: ColoCapEx
    debt: Debt
    equity: Equity
    exit: Exit

    @model_validator(mode="after")
    def _check_occupancy_length(self):
        needed = self.exit.hold_yrs + (1 if self.exit.exit_noi_basis == "forward" else 0)
        if len(self.revenue.occupancy) < needed:
            raise ValueError(
                f"revenue.occupancy needs >= {needed} entries for "
                f"hold_yrs={self.exit.hold_yrs} with {self.exit.exit_noi_basis} "
                f"exit basis; got {len(self.revenue.occupancy)}"
            )
        return self


# ===========================================================================
# Loaders
# ===========================================================================

def load_dc_wholesale_deal(path: str) -> DCWholesaleDeal:
    """Load a DCWholesaleDeal from a YAML file."""
    import yaml
    from pathlib import Path
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DCWholesaleDeal.model_validate(raw)


def load_dc_colo_deal(path: str) -> DCColoDeal:
    """Load a DCColoDeal from a YAML file."""
    import yaml
    from pathlib import Path
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DCColoDeal.model_validate(raw)


def detect_dc_kind(path: str) -> Literal["wholesale", "colo"]:
    """Inspect a YAML file and decide which DC engine to use.

    Convention: presence of `property.contracts` -> wholesale; presence of
    `property.cabinet_mix` -> colo. Also honors explicit asset_class.
    """
    import yaml
    from pathlib import Path
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    prop = (raw or {}).get("property", {}) or {}
    ac = (prop.get("asset_class") or "").lower()
    if ac == "datacenter_wholesale":
        return "wholesale"
    if ac == "datacenter_colo":
        return "colo"
    if prop.get("contracts"):
        return "wholesale"
    if prop.get("cabinet_mix"):
        return "colo"
    raise ValueError(
        f"could not detect DC kind in {path}: missing property.contracts "
        f"(wholesale) or property.cabinet_mix (colo)"
    )
