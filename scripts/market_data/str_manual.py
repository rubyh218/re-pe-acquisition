"""
str_manual.py — Parse an analyst-supplied STR-style hotel comp-set CSV.

WHY THIS EXISTS
---------------
STR (Smith Travel Research, CoStar-owned) is the canonical source for hotel
comp-set RevPAR / ADR / occupancy data, but there is no public API and
the firm hasn't confirmed subscription yet. To unblock hospitality
underwriting in the meantime, this module reads a SIMPLE CSV that an
analyst can manually export from STR's web interface (or assemble from
HVS / CBRE Hotels / JLL Hotels published reports).

CSV FORMAT (wide, monthly)
--------------------------
The CSV is one row per month covering both the subject property and the
competitive set. Columns (case-insensitive, extra columns ignored):

    month                       YYYY-MM or YYYY-MM-DD
    property_revpar             $ (room revenue / available room-nights)
    property_adr                $
    property_occ                decimal 0..1 (0.80 = 80%)
    compset_revpar              $
    compset_adr                 $
    compset_occ                 decimal 0..1
    new_supply_pipeline_pct     decimal (annualized supply growth in submarket)
                                — OPTIONAL; useful for risk callouts

Example:
    month,property_revpar,property_adr,property_occ,compset_revpar,compset_adr,compset_occ,new_supply_pipeline_pct
    2025-01,142.50,178.00,0.801,135.20,170.50,0.793,0.025
    2025-02,138.75,175.00,0.793,131.40,168.00,0.782,0.025
    ...

COMPUTED OUTPUTS
----------------
The three institutional STR indices:
    RGI (RevPAR Index) = property_revpar / compset_revpar * 100
    ARI (ADR Index)    = property_adr    / compset_adr    * 100
    MPI (Occ Index)    = property_occ    / compset_occ    * 100
A value of 100 = parity with comp set. 105 = outperforming by 5%.

Plus trailing windows:
    T-3 / T-6 / T-12 averages on property and comp-set RevPAR/ADR/Occ
    and on each of the three indices.

Usage:
    from scripts.market_data.str_manual import load_compset, compute_indices, summary

    rows = load_compset("inbox/str/example-property-compset.csv")
    indices = compute_indices(rows)
    print(summary(rows, indices))
"""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class STRMonth:
    month: date                          # first day of the month
    property_revpar: float
    property_adr: float
    property_occ: float                  # 0..1
    compset_revpar: float
    compset_adr: float
    compset_occ: float                   # 0..1
    new_supply_pipeline_pct: float | None  # decimal; None if not provided


@dataclass(frozen=True)
class STRIndices:
    """STR's three indices for a single month (or averaged over a window)."""
    month: date | None       # None for averaged windows
    rgi: float               # RevPAR Index — property / comp * 100
    ari: float               # ADR Index
    mpi: float               # MPI (Occ Index)


@dataclass(frozen=True)
class STRTrailingWindow:
    """Trailing-N-month aggregates."""
    n_months: int                   # 3, 6, or 12
    end_month: date
    property_revpar: float
    compset_revpar: float
    rgi: float                      # property_revpar_avg / compset_revpar_avg * 100
    ari: float
    mpi: float
    supply_growth_avg: float | None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_month(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m", "%Y-%m-%d", "%m/%Y", "%b-%y", "%B %Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return date(d.year, d.month, 1)
        except ValueError:
            continue
    raise ValueError(f"unrecognized month format: {s!r}")


def _parse_float(s: str) -> float:
    s = (s or "").strip().replace(",", "").replace("$", "").replace("%", "")
    return float(s) if s else 0.0


def load_compset(path: str | Path) -> list[STRMonth]:
    """Parse the STR comp-set CSV and return rows sorted by month ascending.

    Comment lines starting with `#` are ignored, so analysts can annotate
    the file. The first non-comment, non-blank line is treated as the header.
    """
    rows: list[STRMonth] = []
    with Path(path).open(encoding="utf-8-sig") as f:
        cleaned = (line for line in f if line.strip() and not line.lstrip().startswith("#"))
        reader = csv.DictReader(cleaned)
        for raw in reader:
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not row.get("month"):
                continue
            supply_raw = row.get("new_supply_pipeline_pct", "")
            supply = _parse_float(supply_raw) if supply_raw else None
            rows.append(STRMonth(
                month=_parse_month(row["month"]),
                property_revpar=_parse_float(row["property_revpar"]),
                property_adr=_parse_float(row["property_adr"]),
                property_occ=_parse_float(row["property_occ"]),
                compset_revpar=_parse_float(row["compset_revpar"]),
                compset_adr=_parse_float(row["compset_adr"]),
                compset_occ=_parse_float(row["compset_occ"]),
                new_supply_pipeline_pct=supply,
            ))
    rows.sort(key=lambda r: r.month)
    return rows


# ---------------------------------------------------------------------------
# Indices
# ---------------------------------------------------------------------------

def _safe_index(num: float, denom: float) -> float:
    """Index = num/denom * 100. Zero denom returns 0 (caller checks)."""
    if denom <= 0:
        return 0.0
    return num / denom * 100.0


def compute_indices(rows: list[STRMonth]) -> list[STRIndices]:
    """Per-month RGI / ARI / MPI."""
    return [
        STRIndices(
            month=r.month,
            rgi=_safe_index(r.property_revpar, r.compset_revpar),
            ari=_safe_index(r.property_adr, r.compset_adr),
            mpi=_safe_index(r.property_occ, r.compset_occ),
        )
        for r in rows
    ]


def trailing_window(rows: list[STRMonth], n_months: int) -> STRTrailingWindow | None:
    """Compute the T-N trailing-month window ending at the latest month.

    Returns None if there are fewer than n_months of data.
    Indices are computed as property_avg / compset_avg (the institutional
    convention — averaging then dividing, not the other way round).
    """
    if len(rows) < n_months:
        return None
    window = rows[-n_months:]
    p_rev = statistics.fmean(r.property_revpar for r in window)
    c_rev = statistics.fmean(r.compset_revpar for r in window)
    p_adr = statistics.fmean(r.property_adr for r in window)
    c_adr = statistics.fmean(r.compset_adr for r in window)
    p_occ = statistics.fmean(r.property_occ for r in window)
    c_occ = statistics.fmean(r.compset_occ for r in window)
    supply_vals = [r.new_supply_pipeline_pct for r in window if r.new_supply_pipeline_pct is not None]
    supply_avg = statistics.fmean(supply_vals) if supply_vals else None
    return STRTrailingWindow(
        n_months=n_months,
        end_month=window[-1].month,
        property_revpar=p_rev,
        compset_revpar=c_rev,
        rgi=_safe_index(p_rev, c_rev),
        ari=_safe_index(p_adr, c_adr),
        mpi=_safe_index(p_occ, c_occ),
        supply_growth_avg=supply_avg,
    )


def summary(rows: list[STRMonth], indices: list[STRIndices] | None = None) -> str:
    """Pretty-print a comp-set snapshot with T-3 / T-6 / T-12 indices."""
    if not rows:
        return "STR COMP SET: no data."
    if indices is None:
        indices = compute_indices(rows)
    latest = rows[-1]
    latest_idx = indices[-1]

    out: list[str] = []
    bar = "=" * 64
    out.append(bar)
    out.append(f"STR COMP SET SUMMARY  (latest: {latest.month})")
    out.append(bar)
    out.append(
        f"  {'':<22} {'Property':>10} {'Comp Set':>10} {'Index':>8}"
    )
    out.append(
        f"  {'RevPAR':<22} ${latest.property_revpar:>9,.2f} "
        f"${latest.compset_revpar:>9,.2f} {latest_idx.rgi:>7.1f}"
    )
    out.append(
        f"  {'ADR':<22} ${latest.property_adr:>9,.2f} "
        f"${latest.compset_adr:>9,.2f} {latest_idx.ari:>7.1f}"
    )
    out.append(
        f"  {'Occupancy':<22} {latest.property_occ*100:>9.1f}% "
        f"{latest.compset_occ*100:>9.1f}% {latest_idx.mpi:>7.1f}"
    )

    out.append("")
    out.append(f"  {'Trailing window':<22} {'RGI':>8} {'ARI':>8} {'MPI':>8} {'Supply':>10}")
    for n in (3, 6, 12):
        w = trailing_window(rows, n)
        if w is None:
            out.append(f"  T-{n:<2} (insufficient data)")
            continue
        supply = (
            f"{w.supply_growth_avg*100:>9.2f}%"
            if w.supply_growth_avg is not None else "       n/a"
        )
        out.append(
            f"  T-{n:<2} (to {w.end_month}) "
            f"{w.rgi:>8.1f} {w.ari:>8.1f} {w.mpi:>8.1f} {supply}"
        )
    out.append(bar)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--csv", required=True, help="Path to STR-style comp-set CSV")
    args = p.parse_args(argv)

    rows = load_compset(args.csv)
    if not rows:
        print("ERROR: no rows parsed from CSV. Check the format.")
        return 1
    print(summary(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
