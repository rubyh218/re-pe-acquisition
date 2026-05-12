"""
models.py — Hospitality Deal schema (USALI departmental structure).

The HotelDeal object is the single contract between data ingestion
(manual YAML for now, OM extractor later) and the hospitality engine.

Key differences vs. commercial / multifamily:
  - Revenue driven by ADR x Occupancy x keys x 365 (rooms) plus F&B + Other
    departments as % of rooms revenue.
  - Expenses split USALI-style: departmental, undistributed, mgmt, fixed.
  - FF&E reserve (% of total revenue) deducted ABOVE the cap-rate NOI line
    per institutional convention.
  - PIP capex schedule with key displacement (rooms out of service during
    renovation) reducing sold room-nights during execution years.

Acquisition / Debt / Equity / Exit reuse the multifamily schemas verbatim
(institutional conventions are asset-class agnostic).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import Acquisition, Debt, Equity, Exit


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

ServiceLevel = Literal["economy", "midscale", "upper_midscale", "upscale",
                       "upper_upscale", "luxury"]


class HotelProperty(_Frozen):
    name: str
    address: str
    submarket: str
    year_built: int
    asset_class: Literal["hospitality"] = "hospitality"
    brand: str                                        # e.g. "Hampton Inn", "Westin"
    flag_type: Literal["franchised", "managed", "independent"] = "franchised"
    service_level: ServiceLevel
    keys: int = Field(gt=0)                           # total available rooms

    @property
    def available_room_nights(self) -> int:
        """Annual available room-nights at full inventory."""
        return self.keys * 365


# ---------------------------------------------------------------------------
# Operating assumptions (top-line + departmental)
# ---------------------------------------------------------------------------

class OperatingAssumptions(_Frozen):
    """
    Year-by-year operating drivers. Rooms revenue = sold_room_nights x ADR.
    F&B and Other are sized as % of rooms revenue with their own margins.
    """
    # Rooms
    adr_yr1: float = Field(gt=0)                      # Year 1 ADR ($)
    adr_growth: float = Field(default=0.03, ge=-0.05, le=0.15)
    occupancy: list[float] = Field(min_length=1)      # by year, decimal (0.72 = 72%)
    rooms_expense_pct: float = Field(default=0.27, ge=0, le=0.60)  # % of rooms revenue

    # F&B department
    fb_revenue_pct_of_rooms: float = Field(default=0.10, ge=0, le=1.50)
    fb_margin: float = Field(default=0.18, ge=-0.20, le=0.50)     # F&B profit / F&B revenue

    # Other operated departments (parking, spa, retail, telecom, etc.)
    other_revenue_pct_of_rooms: float = Field(default=0.05, ge=0, le=0.50)
    other_margin: float = Field(default=0.40, ge=-0.20, le=0.80)

    @model_validator(mode="after")
    def _check_occ_bounds(self):
        for o in self.occupancy:
            if not 0 <= o <= 1.0:
                raise ValueError(f"occupancy values must be in [0, 1.0]; got {o}")
        return self


# ---------------------------------------------------------------------------
# OpEx (USALI undistributed + fixed + mgmt + FF&E reserve)
# ---------------------------------------------------------------------------

class HotelOpEx(_Frozen):
    """
    PAR = "per available room" $/key/year. Standard hotel UW convention.
    All PAR amounts grow at their respective growth rates.
    """
    # Undistributed (PAR / yr)
    ga_par:        float = Field(ge=0)                # general & administrative
    sm_par:        float = Field(ge=0)                # sales & marketing
    rm_par:        float = Field(ge=0)                # repairs & maintenance
    utilities_par: float = Field(ge=0)                # utilities

    # Franchise fee (royalty + marketing + reservation) — % of rooms revenue
    franchise_fee_pct: float = Field(default=0.10, ge=0, le=0.20)

    # Management fee — % of total revenue (base; incentive fees ignored in v1)
    mgmt_fee_pct: float = Field(default=0.03, ge=0, le=0.07)

    # FF&E reserve — % of total revenue (4% institutional standard)
    ffe_reserve_pct: float = Field(default=0.04, ge=0, le=0.08)

    # Fixed charges
    re_tax:        float = Field(ge=0)                # annual total $
    insurance_par: float = Field(ge=0)                # PAR / yr

    # Growth rates
    undistributed_growth: float = 0.03                # applied to G&A, S&M, R&M, utilities, insurance
    re_tax_growth:        float = 0.03


# ---------------------------------------------------------------------------
# CapEx (PIP schedule with key displacement)
# ---------------------------------------------------------------------------

class HotelCapEx(_Frozen):
    """
    PIP = Property Improvement Plan capex required by brand at acquisition.
    Modeled as a multi-year spend with proportional key displacement
    (rooms out of inventory) during execution years.
    """
    pip_total: float = Field(default=0, ge=0)
    pip_schedule_pct: list[float] = Field(default_factory=list)   # by year, sums to ~1.0 if pip_total > 0
    pip_displacement_keys: list[int] = Field(default_factory=list)  # avg keys out by year (parallel to schedule)

    @model_validator(mode="after")
    def _check_pip(self):
        if self.pip_total > 0:
            if not self.pip_schedule_pct:
                raise ValueError("pip_schedule_pct required when pip_total > 0")
            total = sum(self.pip_schedule_pct)
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"pip_schedule_pct must sum to ~1.0, got {total:.3f}")
            if self.pip_displacement_keys and len(self.pip_displacement_keys) != len(self.pip_schedule_pct):
                raise ValueError("pip_displacement_keys must have same length as pip_schedule_pct")
        return self


# ---------------------------------------------------------------------------
# Top-level Deal
# ---------------------------------------------------------------------------

class HotelDeal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: HotelProperty
    acquisition: Acquisition
    operating: OperatingAssumptions
    opex: HotelOpEx
    capex: HotelCapEx
    debt: Debt
    equity: Equity
    exit: Exit

    @model_validator(mode="after")
    def _check_occupancy_length(self):
        needed = self.exit.hold_yrs + (1 if self.exit.exit_noi_basis == "forward" else 0)
        if len(self.operating.occupancy) < needed:
            raise ValueError(
                f"operating.occupancy needs >= {needed} entries for hold_yrs={self.exit.hold_yrs} "
                f"with {self.exit.exit_noi_basis} exit basis; got {len(self.operating.occupancy)}"
            )
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_hotel_deal(path: str) -> HotelDeal:
    """Load a HotelDeal from a YAML file."""
    import yaml
    from pathlib import Path

    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return HotelDeal.model_validate(raw)
