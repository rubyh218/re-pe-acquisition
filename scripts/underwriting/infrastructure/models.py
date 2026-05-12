"""
models.py -- Energy infrastructure Deal schema.

One Deal class supports any blend of three revenue stream types against a
generation profile. Stream discrimination is by `kind`:

  PPAStream            kind="ppa"
  AvailabilityStream   kind="availability"
  MerchantStream       kind="merchant"

Allotments (% of generation) across PPA + Merchant streams should sum to <= 1.0
in any given year; Availability streams are independent of generation and are
priced on contracted MW capacity.

Acquisition / Debt / Equity / Exit are reused from the multifamily schemas.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import Acquisition, Debt, Equity, Exit


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


Technology = Literal["solar", "wind", "bess", "gas_peaker", "hydro"]
# Technology drives default capacity-factor / degradation conventions in the
# engine and shapes IC-memo presentation. BESS is treated as a "generator"
# where dispatchable energy = power_mw * duration_hrs * cycles_per_year *
# round_trip_efficiency.

CounterpartyRating = Literal["IG", "Sub-IG", "Unrated", "Public Utility", "Hyperscaler"]
# Used to flag credit concentration in the IC memo.

Market = Literal["CAISO", "ERCOT", "PJM", "MISO", "NYISO", "ISO-NE", "SPP", "WECC", "Other"]


# ===========================================================================
# Generation profile
# ===========================================================================

class GenerationProfile(_Frozen):
    """Asset-level generation drivers.

    Annual gross generation (MWh) = nameplate_mw_ac * 8760 * capacity_factor.
    Net generation applies degradation, curtailment, and forced-outage drags
    in that order. For BESS, capacity_factor = (cycles_per_year * duration_hrs
    * round_trip_efficiency) / 8760 -- the engine accepts this as-is.
    """
    technology: Technology
    nameplate_mw_ac: float = Field(gt=0)              # AC interconnection capacity
    nameplate_mw_dc: float | None = Field(default=None, gt=0)  # solar/wind only (DC>AC overbuild)
    capacity_factor: float = Field(gt=0, le=0.98)     # annual avg, decimal
    degradation_pct: float = Field(default=0.005, ge=0, le=0.10)   # /yr, applied to net generation
    curtailment_pct: float = Field(default=0.00, ge=0, le=0.30)    # ISO-driven curtailment, % of gross
    availability_pct: float = Field(default=0.98, ge=0.50, le=1.0) # mechanical availability

    # BESS-specific (ignored by other technologies)
    bess_duration_hrs: float | None = Field(default=None, gt=0, le=12)
    bess_cycles_per_year: float | None = Field(default=None, gt=0, le=730)
    bess_round_trip_eff: float | None = Field(default=None, gt=0, le=1.0)

    @property
    def gross_annual_generation_mwh_yr1(self) -> float:
        """Yr-1 gross generation before degradation and curtailment."""
        return self.nameplate_mw_ac * 8760 * self.capacity_factor

    @model_validator(mode="after")
    def _check_bess(self):
        if self.technology == "bess":
            missing = [
                f for f, v in [
                    ("bess_duration_hrs", self.bess_duration_hrs),
                    ("bess_cycles_per_year", self.bess_cycles_per_year),
                    ("bess_round_trip_eff", self.bess_round_trip_eff),
                ] if v is None
            ]
            if missing:
                raise ValueError(f"BESS requires {missing}")
        return self


# ===========================================================================
# Revenue streams (discriminated union)
# ===========================================================================

class _StreamBase(_Frozen):
    label: str                            # display label (e.g., "PPA - SoCal Edison")
    counterparty: str                     # offtaker name
    counterparty_rating: CounterpartyRating = "Unrated"


class PPAStream(_StreamBase):
    """Power purchase agreement -- $/MWh on a contracted % of generation."""
    kind: Literal["ppa"] = "ppa"
    price_mwh: float = Field(gt=0)                     # $/MWh at start
    escalation_pct: float = Field(default=0.02, ge=0, le=0.10)   # annual
    allotment_pct: float = Field(default=1.0, gt=0, le=1.0)      # share of generation
    start_date: date
    end_date: date
    floor_price_mwh: float | None = Field(default=None, ge=0)    # optional contracted floor
    cap_price_mwh: float | None = Field(default=None, gt=0)      # optional ceiling

    @model_validator(mode="after")
    def _check_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError(f"{self.label}: end_date must be after start_date")
        return self


class AvailabilityStream(_StreamBase):
    """Capacity payment -- $/MW-month on contracted MW, paid regardless of dispatch.

    Common for: BESS capacity contracts (e.g., RA in CAISO), tolling agreements,
    capacity-only generation (peakers under capacity market), reliability-must-run.
    """
    kind: Literal["availability"] = "availability"
    capacity_mw: float = Field(gt=0)                   # contracted MW
    payment_mw_mo: float = Field(gt=0)                 # $/MW/month
    escalation_pct: float = Field(default=0.02, ge=0, le=0.10)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError(f"{self.label}: end_date must be after start_date")
        return self

    @property
    def annual_payment(self) -> float:
        return self.capacity_mw * self.payment_mw_mo * 12


class MerchantStream(_StreamBase):
    """Merchant exposure -- spot market $/MWh on a share of generation.

    `price_curve_mwh` is a year-indexed list of $/MWh prices (decimal). Engine
    extrapolates by `terminal_growth` past the final entry. For BESS arbitrage,
    encode the *spread* between charge and discharge prices as the price.
    """
    kind: Literal["merchant"] = "merchant"
    market: Market = "Other"
    price_curve_mwh: list[float] = Field(min_length=1)            # by hold year
    terminal_growth: float = Field(default=0.02, ge=-0.05, le=0.10)
    allotment_pct: float = Field(default=1.0, gt=0, le=1.0)        # share of generation


RevenueStream = PPAStream | AvailabilityStream | MerchantStream


# ===========================================================================
# Tax credits (ITC / PTC)
# ===========================================================================

class TaxCredits(_Frozen):
    """Federal tax credits monetized as cash (direct pay or tax-equity sale).

    Convention: ITC is a one-time Yr-1 inflow equal to itc_pct * itc_basis.
    PTC is a per-MWh cash credit applied to *net* generation for ptc_term_yrs,
    inflated annually. Both are pre-tax cash to the equity (we don't model the
    tax-equity flip explicitly here).
    """
    itc_pct: float = Field(default=0.0, ge=0, le=0.70)       # IRA bonus structure can reach 70%
    itc_basis: float = Field(default=0.0, ge=0)              # eligible basis ($); usually = construction cost
    ptc_per_mwh: float = Field(default=0.0, ge=0)            # $/MWh, inflated
    ptc_term_yrs: int = Field(default=10, ge=0, le=15)
    ptc_inflation: float = Field(default=0.025, ge=0, le=0.08)


# ===========================================================================
# OpEx
# ===========================================================================

class InfrastructureOpEx(_Frozen):
    """Energy-asset operating cost structure.

    Two-piece: fixed (sized on nameplate MW) + variable (sized on net generation).
    Land lease + property tax are property-level annual totals. Asset management
    is % of revenue (sponsor / OpCo fee, akin to mgmt_fee_pct in real estate).
    """
    fixed_om_per_mw_yr: float = Field(ge=0)                  # O&M contract (often OEM): towers, panels, BESS racks
    variable_om_per_mwh: float = Field(default=0.0, ge=0)    # wind especially -- wear-and-tear $/MWh

    insurance_per_mw_yr: float = Field(default=3500, ge=0)
    property_tax: float = Field(ge=0)                        # annual total $
    land_lease: float = Field(default=0, ge=0)               # annual total $ (ground rent)
    interconnection_om: float = Field(default=0, ge=0)       # transmission/interconnect $/yr
    asset_mgmt_pct: float = Field(default=0.02, ge=0, le=0.08)   # % of gross revenue

    # Growth rates
    om_growth: float = Field(default=0.025, ge=-0.05, le=0.10)
    property_tax_growth: float = Field(default=0.02, ge=-0.05, le=0.10)
    land_lease_growth: float = Field(default=0.025, ge=-0.05, le=0.10)
    insurance_growth: float = Field(default=0.03, ge=-0.05, le=0.10)


# ===========================================================================
# CapEx (augmentation, inverter replacement, recurring reserves)
# ===========================================================================

class AugmentationEvent(_Frozen):
    """Lumpy capex (BESS augmentation, inverter swap, blade refurb)."""
    year: int = Field(ge=1)
    amount: float = Field(ge=0)
    label: str = ""


class InfrastructureCapEx(_Frozen):
    initial_capex: float = Field(default=0, ge=0)            # day-1 construction completion / commissioning
    augmentation_schedule: list[AugmentationEvent] = Field(default_factory=list)
    recurring_reserve_per_mw_yr: float = Field(default=2000, ge=0)


# ===========================================================================
# Property
# ===========================================================================

class InfrastructureProperty(_Frozen):
    name: str
    address: str
    submarket: str                                            # county / city / state for siting
    market: Market = "Other"                                  # ISO/RTO
    cod_date: date                                            # commercial operation date
    year_built: int

    asset_class: Literal["infrastructure"] = "infrastructure"
    generation: GenerationProfile

    site_acres: float | None = Field(default=None, gt=0)
    interconnect_voltage_kv: float | None = Field(default=None, gt=0)
    queue_position: str | None = None                         # ISO interconnection queue ID

    revenue_streams: list[RevenueStream] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_streams(self):
        # Allotments across PPA + Merchant should sum to <= 1.0 at any point.
        # Loose check: just validate by stream (per-year overlap is enforced
        # in the engine via clamping).
        gen_share = sum(
            s.allotment_pct for s in self.revenue_streams
            if isinstance(s, (PPAStream, MerchantStream))
        )
        # We allow over-allocation in the schema (a deal might layer multiple
        # PPAs across non-overlapping date windows summing > 100% of one year's
        # generation). The engine clamps per-year allotment to 100%.
        if gen_share <= 0 and not any(isinstance(s, AvailabilityStream) for s in self.revenue_streams):
            raise ValueError("Property has zero contracted/merchant generation share and no availability streams")
        return self


# ===========================================================================
# Top-level deal
# ===========================================================================

class InfrastructureDeal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: InfrastructureProperty
    acquisition: Acquisition
    opex: InfrastructureOpEx
    capex: InfrastructureCapEx
    tax_credits: TaxCredits = Field(default_factory=TaxCredits)
    debt: Debt
    equity: Equity
    exit: Exit


# ===========================================================================
# Loader
# ===========================================================================

def load_infrastructure_deal(path: str) -> InfrastructureDeal:
    """Load an InfrastructureDeal from a YAML file."""
    import yaml
    from pathlib import Path
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return InfrastructureDeal.model_validate(raw)
