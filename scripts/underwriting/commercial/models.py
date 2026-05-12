"""
models.py — Commercial Deal schema (office / industrial / retail).

The CommercialDeal object is the single contract between data ingestion
(manual YAML, OM extractor) and the commercial underwriting engine.

Key differences vs. multifamily:
  - rent_roll: list of Lease objects (vs. unit_mix UnitTypes)
  - Recoveries: NNN / BYS (base-year stop) / gross — per lease
  - Market: assumptions for re-leasing on rollover (renewal_prob, downtime, TI/LC)
  - OpEx split into recoverable pool vs. non-recoverable

Acquisition / Debt / Equity / Exit reuse the multifamily schemas verbatim
(institutional conventions are asset-class agnostic).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Reuse the multifamily Acquisition / Debt / Equity / Exit schemas — these
# concepts don't change by asset class.
from ..models import Acquisition, Debt, Equity, Exit


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Lease (one row of the rent roll)
# ---------------------------------------------------------------------------

LeaseType = Literal["NNN", "BYS", "gross"]
# NNN  — triple-net, tenant pays pro-rata share of full recoverable pool
# BYS  — base-year stop, tenant pays pro-rata share of recoverable increases over base year
# gross — landlord absorbs recoveries entirely


class Lease(_Frozen):
    """One executed lease in the rent roll, as of close_date."""
    tenant: str
    suite: str | None = None
    sf: int = Field(gt=0)
    base_rent_psf: float = Field(gt=0)              # current $/SF/yr
    lease_type: LeaseType
    lease_start: date                                # original lease commencement
    lease_end: date                                  # current expiration
    escalation_pct: float = Field(default=0.03, ge=0, le=0.15)
    free_rent_remaining_mo: int = Field(default=0, ge=0)
    pro_rata_share: float | None = Field(default=None, ge=0, le=1.0)  # if None, derived as sf / total_rba
    base_year_recoverables: float | None = Field(default=None, ge=0)  # BYS only; if None and BYS, set to Yr1 recoverable pool × pro_rata_share

    # Optional per-lease overrides of Market defaults (otherwise inherit)
    market_rent_psf_override: float | None = Field(default=None, gt=0)
    renewal_prob_override: float | None = Field(default=None, ge=0, le=1.0)

    # Percentage rent (retail). Overage rent above natural breakpoint.
    # Applied only over the in-place segment; rollover segments revert to base.
    pct_rent_rate: float | None = Field(default=None, ge=0, le=0.20)   # e.g., 0.06 = 6% of sales
    sales_psf: float | None = Field(default=None, ge=0)                # projected tenant sales $/SF/yr at close

    @model_validator(mode="after")
    def _check_dates(self):
        if self.lease_end <= self.lease_start:
            raise ValueError(f"{self.tenant}: lease_end must be after lease_start")
        return self


# ---------------------------------------------------------------------------
# Market (re-leasing assumptions on rollover)
# ---------------------------------------------------------------------------

class Market(_Frozen):
    """Market assumptions applied when a lease rolls over (or vacant space leases up)."""
    market_rent_psf: float = Field(gt=0)            # current market $/SF/yr
    market_rent_growth: float = 0.03                # annual % growth applied to market rent going forward

    # New lease terms (used when (1 - renewal_prob) outcome occurs)
    new_lease_term_yrs: int = Field(default=5, gt=0, le=20)
    new_escalation_pct: float = Field(default=0.03, ge=0, le=0.15)
    new_free_rent_mo: int = Field(default=0, ge=0)
    new_ti_psf: float = Field(default=0, ge=0)
    new_lc_pct: float = Field(default=0.06, ge=0, le=0.15)   # of base-rent NPV (proxy: × first-year rent × term)
    downtime_mo: int = Field(default=6, ge=0, le=36)         # months vacant between leases (new tenant case only)

    # Renewal lease terms (used when renewal_prob outcome occurs) — typically less generous
    renewal_lease_term_yrs: int = Field(default=5, gt=0, le=20)
    renewal_escalation_pct: float = Field(default=0.03, ge=0, le=0.15)
    renewal_free_rent_mo: int = Field(default=0, ge=0)
    renewal_ti_psf: float = Field(default=0, ge=0)
    renewal_lc_pct: float = Field(default=0.03, ge=0, le=0.10)

    # Blended renewal probability (per-lease override available on Lease)
    renewal_prob: float = Field(default=0.65, ge=0, le=1.0)

    # Retail tenant sales growth (used for percentage rent escalation)
    sales_growth: float = Field(default=0.025, ge=-0.05, le=0.15)


# ---------------------------------------------------------------------------
# OpEx (split into recoverable pool vs. non-recoverable)
# ---------------------------------------------------------------------------

class CommercialOpEx(_Frozen):
    """
    All per-SF fields are ANNUAL $/SF on total RBA. RE tax is total annual $.

    Recoverable pool = CAM + RE tax + insurance + recoverable utilities.
    Non-recoverable = mgmt fee + non_recoverable_psf items (G&A, legal, marketing).
    """
    # Recoverable pool components
    cam_psf:              float = Field(ge=0)           # common area maintenance
    re_tax:               float = Field(ge=0)           # annual total $ (often reassessed at sale)
    insurance_psf:        float = Field(ge=0)
    utilities_psf:        float = Field(default=0, ge=0)   # common-area utilities (recoverable)

    # Non-recoverable
    mgmt_fee_pct:         float = Field(default=0.03, ge=0, le=0.10)   # % of EGI
    non_recoverable_psf:  float = Field(default=0, ge=0)  # G&A, legal, etc.

    # Growth rates
    cam_growth:           float = 0.03
    re_tax_growth:        float = 0.03
    insurance_growth:     float = 0.04
    utilities_growth:     float = 0.03
    non_recoverable_growth: float = 0.03


# ---------------------------------------------------------------------------
# CapEx (property-level only; TI/LC handled per-lease in the engine)
# ---------------------------------------------------------------------------

class CommercialCapEx(_Frozen):
    initial_building_capex: float = Field(default=0, ge=0)    # one-time Yr 1 building improvements
    recurring_reserve_psf:  float = Field(default=0.20, ge=0) # $/SF/yr replacement reserves


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

class CommercialProperty(_Frozen):
    name: str
    address: str
    submarket: str
    year_built: int
    asset_class: Literal["office", "industrial", "retail"]
    total_rba: int = Field(gt=0)                              # rentable building area
    rent_roll: list[Lease] = Field(min_length=1)
    general_vacancy_pct: float = Field(default=0.05, ge=0, le=0.30)   # credit loss / unmodeled downtime, % of gross rent

    @model_validator(mode="after")
    def _check_leased_sf(self):
        leased = sum(l.sf for l in self.rent_roll)
        if leased > self.total_rba:
            raise ValueError(f"rent roll SF ({leased:,}) exceeds total_rba ({self.total_rba:,})")
        return self

    @property
    def leased_sf(self) -> int:
        return sum(l.sf for l in self.rent_roll)

    @property
    def vacant_sf(self) -> int:
        return self.total_rba - self.leased_sf

    @property
    def in_place_occupancy(self) -> float:
        return self.leased_sf / self.total_rba

    @property
    def in_place_gross_rent(self) -> float:
        """Annual gross potential rent at current in-place rates."""
        return sum(l.base_rent_psf * l.sf for l in self.rent_roll)


# ---------------------------------------------------------------------------
# Top-level Deal
# ---------------------------------------------------------------------------

class CommercialDeal(_Frozen):
    deal_id: str
    deal_name: str
    sponsor: str = "Acquirer"

    property: CommercialProperty
    acquisition: Acquisition
    market: Market
    opex: CommercialOpEx
    capex: CommercialCapEx
    debt: Debt
    equity: Equity
    exit: Exit


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_commercial_deal(path: str) -> CommercialDeal:
    """Load a CommercialDeal from a YAML file."""
    import yaml
    from pathlib import Path

    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return CommercialDeal.model_validate(raw)
