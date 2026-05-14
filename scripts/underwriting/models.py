"""
models.py — Deal input schema (pydantic v2).

Multifamily-only for v1. The Deal object is the single contract between data
ingestion (manual YAML for now, OM extraction later) and the underwriting engine.

Defaults reflect institutional norms (see SKILL.md "Conventions").
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    """Immutable base — deal inputs should not mutate after load."""
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

class UnitType(_Frozen):
    """One floorplan in the rent roll."""
    name: str                  # "1BR/1BA", "2BR/2BA", etc.
    count: int = Field(gt=0)
    sf: int = Field(gt=0)      # avg SF per unit
    in_place_rent: float = Field(gt=0)   # avg in-place monthly rent
    market_rent: float = Field(gt=0)     # avg current market monthly rent

    @property
    def loss_to_lease(self) -> float:
        """Annualized loss-to-lease for this unit type."""
        return (self.market_rent - self.in_place_rent) * self.count * 12


class Property(_Frozen):
    name: str
    address: str
    submarket: str
    year_built: int
    asset_class: Literal["multifamily"] = "multifamily"
    unit_mix: list[UnitType] = Field(min_length=1)

    @property
    def unit_count(self) -> int:
        return sum(u.count for u in self.unit_mix)

    @property
    def total_sf(self) -> int:
        return sum(u.count * u.sf for u in self.unit_mix)

    @property
    def gpr_in_place(self) -> float:
        """Annual gross potential rent at in-place rents."""
        return sum(u.in_place_rent * u.count * 12 for u in self.unit_mix)

    @property
    def gpr_market(self) -> float:
        """Annual gross potential rent at market rents."""
        return sum(u.market_rent * u.count * 12 for u in self.unit_mix)


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------

class Acquisition(_Frozen):
    purchase_price: float = Field(gt=0)
    closing_costs_pct: float = Field(default=0.015, ge=0, le=0.05)
    initial_capex: float = Field(default=0, ge=0)        # day-1 CapEx (separate from value-add schedule below)
    day_one_reserves: float = Field(default=0, ge=0)     # working capital, lender-required reserves
    close_date: date


# ---------------------------------------------------------------------------
# Revenue assumptions
# ---------------------------------------------------------------------------

class Revenue(_Frozen):
    other_income_per_unit_mo: float = Field(default=0, ge=0)  # parking, storage, fees, RUBS
    rent_growth: list[float] = Field(min_length=1)            # by year, decimal (0.03 = 3%)
    other_income_growth: float = 0.03
    vacancy: float = Field(default=0.05, ge=0, le=0.5)        # physical vacancy (% of GPR)
    bad_debt: float = Field(default=0.01, ge=0, le=0.05)      # % of GPR
    concessions_yr1: float = Field(default=0.0, ge=0, le=0.10)  # Year 1 concessions (% of GPR), burns off by Yr 3

    # In-place → market mark-to-market roll convention.
    #
    # Multifamily leases are typically 12 months, so only ~50% of the rent
    # roll re-prices in any given year. mtm_roll_yrs=1 (the previous default
    # and the institutional value-add convention) assumes the engine
    # instantly captures the full LTL gap at the start of Year 2. That
    # overstates Year-2 revenue on any deal with material LTL.
    #
    # Set mtm_roll_yrs > 1 to spread the roll linearly over multiple years:
    #   mtm_roll_yrs=2 → 50% rolls at Year 2, 100% at Year 3.
    #   mtm_roll_yrs=3 → 33% / 67% / 100% at Years 2, 3, 4.
    #
    # In every case, the rolled portion trends with rent_growth from Yr 1.
    mtm_roll_yrs: int = Field(default=1, ge=1, le=10)


# ---------------------------------------------------------------------------
# OpEx assumptions
# ---------------------------------------------------------------------------

class OpEx(_Frozen):
    """Per-unit annual where noted; RE tax is total annual (property-specific)."""
    payroll_per_unit:   float = Field(ge=0)
    rm_per_unit:        float = Field(ge=0)
    marketing_per_unit: float = Field(ge=0)
    utilities_per_unit: float = Field(ge=0)   # net of recoveries
    insurance_per_unit: float = Field(ge=0)
    other_per_unit:     float = Field(default=0, ge=0)
    re_tax:             float = Field(ge=0)   # annual total (often re-assessed at sale; see re_tax_growth)
    re_tax_growth:      float = 0.03
    growth:             float = 0.03          # general OpEx growth (controllable)
    mgmt_fee_pct:       float = Field(default=0.03, ge=0, le=0.10)  # % of EGI


# ---------------------------------------------------------------------------
# CapEx (value-add schedule + recurring reserve)
# ---------------------------------------------------------------------------

class CapEx(_Frozen):
    value_add_per_unit:        float = Field(default=0, ge=0)   # interior reno cost per unit
    units_renovated_pct:       list[float] = Field(default_factory=list)  # by year, % of total units turned (e.g., [0.40, 0.40, 0.20])
    rent_premium_per_unit_mo:  float = Field(default=0, ge=0)   # uplift on renovated units
    common_area_capex:         float = Field(default=0, ge=0)   # one-time, year 1
    recurring_reserve_per_unit: float = Field(default=300, ge=0)  # $/unit/yr (typical: $250–$500 multifamily)

    @model_validator(mode="after")
    def _check_renovation_pct(self):
        if self.value_add_per_unit > 0 and not self.units_renovated_pct:
            raise ValueError("units_renovated_pct required when value_add_per_unit > 0")
        if self.units_renovated_pct and abs(sum(self.units_renovated_pct) - 1.0) > 0.01:
            raise ValueError(f"units_renovated_pct must sum to ~1.0, got {sum(self.units_renovated_pct):.3f}")
        return self


# ---------------------------------------------------------------------------
# Debt
# ---------------------------------------------------------------------------

class Debt(_Frozen):
    rate:              float = Field(gt=0, lt=0.30)   # decimal (0.065 = 6.5%)
    term_yrs:          int = Field(default=10, gt=0)
    amort_yrs:         int = Field(default=30, ge=0)  # 0 = interest-only
    io_period_yrs:     int = Field(default=0, ge=0)   # IO upfront period
    max_ltv:           float = Field(default=0.65, gt=0, le=0.85)
    min_dscr:          float = Field(default=1.25, gt=1.0, le=2.0)
    min_debt_yield:    float = Field(default=0.08, gt=0, le=0.20)
    origination_fee_pct: float = Field(default=0.01, ge=0, le=0.03)
    lender_reserves:   float = Field(default=0, ge=0)  # additional reserves required at close

    # Optional override: if set, sizes to this loan amount instead of solving for max
    fixed_loan_amount: float | None = None


# ---------------------------------------------------------------------------
# Equity / Waterfall
# ---------------------------------------------------------------------------

class WaterfallTier(_Frozen):
    """One tier in a multi-tier IRR-hurdle waterfall.

    Tiers are listed in ascending hurdle order. The LAST tier is the residual:
    its `hurdle_irr` is ignored — all cash beyond capped tiers splits at the
    residual's `promote_pct`.
    """
    hurdle_irr:  float = Field(ge=0, le=0.50)   # ignored for residual tier
    promote_pct: float = Field(ge=0, lt=0.80)
    label:       str = ""


class Equity(_Frozen):
    pref_rate:        float = Field(default=0.08, ge=0, le=0.20)
    promote_pct:      float = Field(default=0.20, ge=0, lt=0.50)
    gp_coinvest_pct:  float = Field(default=0.10, ge=0, le=1.0)  # GP's share of equity check
    acq_fee_pct:      float = Field(default=0.0, ge=0, le=0.03)  # GP acquisition fee (% of purchase price)

    # Optional multi-tier override. If provided, supersedes pref_rate + promote_pct.
    # Convention: tiers ascending by hurdle_irr; LAST tier is residual.
    tiers: list[WaterfallTier] | None = None

    @property
    def waterfall_tiers(self) -> list[WaterfallTier]:
        """Resolve the active tier list (explicit `tiers` or legacy 2-tier)."""
        if self.tiers:
            return list(self.tiers)
        return [
            WaterfallTier(hurdle_irr=self.pref_rate, promote_pct=0.0, label="Preferred Return"),
            WaterfallTier(hurdle_irr=0.0,            promote_pct=self.promote_pct, label="Residual"),
        ]


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------

class Exit(_Frozen):
    hold_yrs:           int = Field(default=5, gt=0, le=15)
    exit_cap:           float = Field(gt=0, lt=0.20)
    cost_of_sale_pct:   float = Field(default=0.015, ge=0, le=0.05)
    exit_noi_basis:     Literal["trailing", "forward"] = "forward"  # forward = NOI of year hold+1
    # Manual stabilization-year override (1-indexed). When set, the engine
    # reports the cap rate / 3-basis ROC at this year instead of its default.
    # Commercial engine auto-picks the first low-rollover year when unset;
    # other engines fall back to min(Yr 3, hold).
    stab_yr:            int | None = Field(default=None, ge=1, le=15)


# ---------------------------------------------------------------------------
# Top-level Deal
# ---------------------------------------------------------------------------

class Deal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: Property
    acquisition: Acquisition
    revenue: Revenue
    opex: OpEx
    capex: CapEx
    debt: Debt
    equity: Equity
    exit: Exit

    @model_validator(mode="after")
    def _check_rent_growth_length(self):
        # Need at least hold_yrs + 1 years of growth assumptions (for forward exit NOI)
        needed = self.exit.hold_yrs + (1 if self.exit.exit_noi_basis == "forward" else 0)
        if len(self.revenue.rent_growth) < needed:
            raise ValueError(
                f"revenue.rent_growth needs >= {needed} entries for hold_yrs={self.exit.hold_yrs} "
                f"with {self.exit.exit_noi_basis} exit basis; got {len(self.revenue.rent_growth)}"
            )
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_deal(path: str | "pathlib.Path") -> Deal:
    """Load a Deal from a YAML file."""
    import yaml
    from pathlib import Path

    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Deal.model_validate(raw)
