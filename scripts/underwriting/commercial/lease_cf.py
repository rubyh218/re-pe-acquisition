"""
lease_cf.py — Per-lease annual cash flow generator.

Produces, for each lease, year-by-year:
  - base_rent: contractual rent (escalated)
  - free_rent: negative (rent abatement)
  - recoveries: NNN/BYS pass-through reimbursement
  - ti: tenant improvements paid by landlord
  - lc: leasing commissions paid by landlord
  - downtime_loss: rent lost between leases (new-tenant rollover only)
  - occupancy_pct_of_year: fraction of the year this lease is rent-paying (0..1)

On lease expiration during the hold, we blend the renewal outcome
(prob = renewal_prob) and the new-tenant outcome (1 - renewal_prob) into a
single probability-weighted cash flow stream per institutional convention.

Periods are ANNUAL buckets anchored to close_date anniversaries. Partial-year
math uses months as 1/12 fractions of the bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .models import CommercialOpEx, Lease, Market


# ---------------------------------------------------------------------------
# Per-year output structure
# ---------------------------------------------------------------------------

@dataclass
class LeaseYear:
    year: int                       # 1-indexed hold year
    base_rent: float                # gross contractual rent (positive)
    free_rent: float                # negative (abatement during year)
    recoveries: float               # positive (reimbursement income)
    ti: float                       # positive expense
    lc: float                       # positive expense
    downtime_loss: float            # positive (rent forgone — already netted in base_rent but tracked for reporting)
    occupied_months: float          # 0..12 — for property-level occupancy roll-up


# ---------------------------------------------------------------------------
# Helpers — date math in months
# ---------------------------------------------------------------------------

def _months_between(d1: date, d2: date) -> float:
    """Approximate months between d1 and d2 (positive if d2 >= d1)."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) + (d2.day - d1.day) / 30.4375


def _add_months(d: date, months: float) -> date:
    """Add fractional months to d (rough — day-of-month preserved)."""
    total = d.month + int(months) - 1
    y = d.year + total // 12
    m = total % 12 + 1
    # Day-of-month preservation (clip to month-end if needed)
    from calendar import monthrange
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def _year_window(close_date: date, year: int) -> tuple[date, date]:
    """Start and end of annual bucket `year` (1-indexed, anchored to close_date)."""
    start = _add_months(close_date, 12 * (year - 1))
    end = _add_months(close_date, 12 * year)
    return start, end


def _overlap_months(window_start: date, window_end: date,
                    period_start: date, period_end: date) -> float:
    """Months of overlap between [window_start, window_end) and [period_start, period_end)."""
    lo = max(window_start, period_start)
    hi = min(window_end, period_end)
    if hi <= lo:
        return 0.0
    return _months_between(lo, hi)


# ---------------------------------------------------------------------------
# Single-segment rent stream
# ---------------------------------------------------------------------------

@dataclass
class _LeaseSegment:
    """A single uninterrupted lease segment with constant escalation cadence."""
    start: date
    end: date
    base_rent_psf_at_start: float
    escalation_pct: float
    sf: int
    free_rent_mo: int                  # free rent months at lease start (from segment.start)
    ti_total: float                    # paid at segment.start
    lc_total: float                    # paid at segment.start


def _segment_year_cf(seg: _LeaseSegment, close_date: date, year: int) -> dict:
    """Compute one annual bucket's contribution from a lease segment."""
    win_start, win_end = _year_window(close_date, year)
    overlap_mo = _overlap_months(win_start, win_end, seg.start, seg.end)
    if overlap_mo <= 0:
        return {"base_rent": 0.0, "free_rent": 0.0, "ti": 0.0, "lc": 0.0,
                "occupied_months": 0.0, "downtime_loss": 0.0}

    # Annual rent at start: base_rent_psf_at_start × sf. Escalates on each
    # anniversary of seg.start.
    months_into_seg_at_window_start = max(0.0, _months_between(seg.start, max(win_start, seg.start)))
    months_into_seg_at_window_end = months_into_seg_at_window_start + overlap_mo

    # Integrate rent over the overlap, applying the escalator on each anniversary.
    # Approximation: compute month-by-month rent within the overlap.
    base_rent = 0.0
    # Iterate in monthly steps for accuracy with mid-year escalations.
    cursor = max(win_start, seg.start)
    months_remaining = overlap_mo
    while months_remaining > 1e-6:
        # How many months until next escalation anniversary?
        months_since_seg_start = _months_between(seg.start, cursor)
        completed_years = int(months_since_seg_start // 12)
        next_anniv_mo = (completed_years + 1) * 12
        months_to_anniv = next_anniv_mo - months_since_seg_start
        chunk = min(months_remaining, months_to_anniv, _months_between(cursor, min(seg.end, win_end)))
        if chunk <= 0:
            break
        annual_rent = seg.base_rent_psf_at_start * seg.sf * (1 + seg.escalation_pct) ** completed_years
        base_rent += annual_rent * (chunk / 12)
        cursor = _add_months(cursor, chunk)
        months_remaining -= chunk

    # Free rent: applied to the first free_rent_mo months of the segment.
    free_rent = 0.0
    if seg.free_rent_mo > 0:
        free_period_end = _add_months(seg.start, seg.free_rent_mo)
        free_overlap = _overlap_months(win_start, win_end, seg.start, free_period_end)
        if free_overlap > 0:
            # Free rent equals (rent that would have been paid) × (free_overlap / overlap_during_free_period)
            # Approximation: free rent abates at the year-1 rate of the segment.
            annual_rent_yr1 = seg.base_rent_psf_at_start * seg.sf
            free_rent = -annual_rent_yr1 * (free_overlap / 12)

    # TI / LC paid in lump at segment start if start falls in this window.
    ti = seg.ti_total if (win_start <= seg.start < win_end) else 0.0
    lc = seg.lc_total if (win_start <= seg.start < win_end) else 0.0

    return {
        "base_rent": base_rent,
        "free_rent": free_rent,
        "ti": ti,
        "lc": lc,
        "occupied_months": overlap_mo,
        "downtime_loss": 0.0,
    }


# ---------------------------------------------------------------------------
# Build the segments that represent a lease through the hold
# ---------------------------------------------------------------------------

def _build_segments(
    lease: Lease,
    market: Market,
    close_date: date,
    hold_end: date,
    outcome: Literal["renewal", "new"],
) -> tuple[list[_LeaseSegment], list[tuple[date, date]]]:
    """
    Return (segments, downtime_windows) for one outcome path.

    Segment 1 = existing lease as-is through lease.lease_end.
    Subsequent segments = rollovers under the chosen outcome (renewal or new).
    Continue chaining rollovers until we cover the hold_end.
    """
    segments: list[_LeaseSegment] = []
    downtimes: list[tuple[date, date]] = []

    # Segment 1: in-place lease.
    segments.append(_LeaseSegment(
        start=close_date,                # rent already in-place at close
        end=lease.lease_end,
        base_rent_psf_at_start=lease.base_rent_psf,
        escalation_pct=lease.escalation_pct,
        sf=lease.sf,
        free_rent_mo=lease.free_rent_remaining_mo,
        ti_total=0.0,                    # in-place lease — TI already funded by prior landlord
        lc_total=0.0,
    ))

    # Special case: in-place rent IS escalated relative to true lease_start.
    # Adjust: rent at close = base_rent_psf, but the escalator should compound
    # from close_date anniversaries, not from original lease_start. Above we
    # already set seg.start=close_date so escalations anniversary from close. OK.

    cursor_start = lease.lease_end
    while cursor_start < hold_end:
        # Downtime applies only on NEW outcome.
        if outcome == "new":
            new_start = _add_months(cursor_start, market.downtime_mo)
            downtimes.append((cursor_start, new_start))
            term_yrs = market.new_lease_term_yrs
            escal = market.new_escalation_pct
            free = market.new_free_rent_mo
            ti_psf = market.new_ti_psf
            lc_pct = market.new_lc_pct
        else:
            new_start = cursor_start
            term_yrs = market.renewal_lease_term_yrs
            escal = market.renewal_escalation_pct
            free = market.renewal_free_rent_mo
            ti_psf = market.renewal_ti_psf
            lc_pct = market.renewal_lc_pct

        if new_start >= hold_end:
            break

        # Market rent escalated from close_date to new_start
        yrs_from_close = _months_between(close_date, new_start) / 12
        mkt_rent_psf = (lease.market_rent_psf_override or market.market_rent_psf) * \
                       (1 + market.market_rent_growth) ** yrs_from_close

        new_end = _add_months(new_start, term_yrs * 12)

        ti_total = ti_psf * lease.sf
        # LC convention: % of base-rent NPV approximation = lc_pct × first-year rent × term_yrs
        first_yr_rent = mkt_rent_psf * lease.sf
        lc_total = lc_pct * first_yr_rent * term_yrs

        segments.append(_LeaseSegment(
            start=new_start,
            end=new_end,
            base_rent_psf_at_start=mkt_rent_psf,
            escalation_pct=escal,
            sf=lease.sf,
            free_rent_mo=free,
            ti_total=ti_total,
            lc_total=lc_total,
        ))
        cursor_start = new_end

    return segments, downtimes


def _outcome_year_cf(segments: list[_LeaseSegment], downtimes: list[tuple[date, date]],
                     close_date: date, year: int) -> dict:
    """Sum CF contributions from all segments for one outcome path."""
    totals = {"base_rent": 0.0, "free_rent": 0.0, "ti": 0.0, "lc": 0.0,
              "occupied_months": 0.0, "downtime_loss": 0.0}
    for seg in segments:
        c = _segment_year_cf(seg, close_date, year)
        for k in totals:
            totals[k] += c[k]
    # Downtime loss: track months of downtime within this year (for reporting; rent is already 0 in those months)
    win_start, win_end = _year_window(close_date, year)
    for (dt_start, dt_end) in downtimes:
        totals["downtime_loss"] += _overlap_months(win_start, win_end, dt_start, dt_end)
    return totals


# ---------------------------------------------------------------------------
# Recoveries
# ---------------------------------------------------------------------------

def recoverable_pool_total(opex: CommercialOpEx, total_rba: int, year: int) -> float:
    """Total recoverable opex in year N (1-indexed)."""
    g_cam = (1 + opex.cam_growth) ** (year - 1)
    g_tax = (1 + opex.re_tax_growth) ** (year - 1)
    g_ins = (1 + opex.insurance_growth) ** (year - 1)
    g_util = (1 + opex.utilities_growth) ** (year - 1)
    cam = opex.cam_psf * total_rba * g_cam
    re_tax = opex.re_tax * g_tax
    ins = opex.insurance_psf * total_rba * g_ins
    util = opex.utilities_psf * total_rba * g_util
    return cam + re_tax + ins + util


def _compute_recoveries(
    lease: Lease,
    total_rba: int,
    opex: CommercialOpEx,
    year: int,
    occupied_fraction: float,    # 0..1 of year that pro-rata SF is occupied by a paying tenant in this outcome
    base_year_pool: float,
) -> float:
    """
    Compute recoveries for this lease in year N.

    NNN  → pro_rata × full recoverable pool × occupied_fraction
    BYS  → pro_rata × max(0, pool - base_year_pool) × occupied_fraction
    gross → 0
    """
    if lease.lease_type == "gross":
        return 0.0
    pro_rata = lease.pro_rata_share if lease.pro_rata_share is not None else (lease.sf / total_rba)
    pool = recoverable_pool_total(opex, total_rba, year)
    if lease.lease_type == "NNN":
        return pro_rata * pool * occupied_fraction
    # BYS
    increase = max(0.0, pool - base_year_pool)
    return pro_rata * increase * occupied_fraction


# ---------------------------------------------------------------------------
# Top-level: lease cash flow over hold (probability-blended)
# ---------------------------------------------------------------------------

def lease_cash_flow(
    lease: Lease,
    market: Market,
    opex: CommercialOpEx,
    total_rba: int,
    close_date: date,
    n_years: int,
) -> list[LeaseYear]:
    """
    Build probability-blended annual cash flows for one lease over n_years.

    If the lease expires during the hold, the two rollover outcomes (renewal /
    new-tenant) are computed independently and blended by renewal_prob.
    """
    hold_end = _add_months(close_date, n_years * 12)
    p_renewal = lease.renewal_prob_override if lease.renewal_prob_override is not None else market.renewal_prob

    renewal_segs, renewal_dts = _build_segments(lease, market, close_date, hold_end, "renewal")
    new_segs, new_dts = _build_segments(lease, market, close_date, hold_end, "new")

    # Base-year recoverables for BYS: default to Yr 1 pool × pro_rata if not stated.
    if lease.lease_type == "BYS":
        if lease.base_year_recoverables is not None:
            base_year_pool = lease.base_year_recoverables / (
                lease.pro_rata_share if lease.pro_rata_share is not None else (lease.sf / total_rba)
            )
        else:
            base_year_pool = recoverable_pool_total(opex, total_rba, 1)
    else:
        base_year_pool = 0.0

    out: list[LeaseYear] = []
    for y in range(1, n_years + 1):
        renew_cf = _outcome_year_cf(renewal_segs, renewal_dts, close_date, y)
        new_cf = _outcome_year_cf(new_segs, new_dts, close_date, y)

        blend = lambda key: p_renewal * renew_cf[key] + (1 - p_renewal) * new_cf[key]
        base_rent = blend("base_rent")
        free_rent = blend("free_rent")
        ti = blend("ti")
        lc = blend("lc")
        occupied_months = blend("occupied_months")
        downtime_loss = blend("downtime_loss")

        # Recoveries scale by occupancy fraction within the year.
        occ_frac = min(1.0, occupied_months / 12)
        recoveries = _compute_recoveries(lease, total_rba, opex, y, occ_frac, base_year_pool)

        out.append(LeaseYear(
            year=y, base_rent=base_rent, free_rent=free_rent, recoveries=recoveries,
            ti=ti, lc=lc, downtime_loss=downtime_loss, occupied_months=occupied_months,
        ))
    return out
