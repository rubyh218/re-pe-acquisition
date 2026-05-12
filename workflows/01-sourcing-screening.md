# 01 — Sourcing & Screening

First-pass evaluation of broker-marketed deals to decide: pursue (full underwriting) or pass.

## Inputs
- Offering Memorandum (OM) — PDF
- T-12 (trailing 12 months operating statement) — PDF/XLSX
- Rent roll snapshot — PDF/XLSX
- Broker call notes (optional)

## Process
1. **OM intake** — extract: address, asset class, year built, units/SF, asking price, occupancy, in-place NOI, broker contact.
2. **Quick-screen pro forma** — 5-input model:
   - Purchase price (asking, then bid scenarios)
   - In-place NOI (from T-12, normalized for non-recurring)
   - Stabilized NOI (Year 3, with trend assumptions)
   - All-in basis (price + closing + initial CapEx)
   - Exit cap rate
3. **Score against fund criteria** — geography, deal size, return hurdles (target IRR / equity multiple), strategy fit (core / core+ / value-add / opportunistic).
4. **Pursue/pass decision** with one-page rationale.

## Deliverables
- `quick-screen.xlsx` — 5-input model with going-in cap, stabilized YoC, deal-level IRR estimate
- `screen-memo.md` — one page: thesis, key risks, recommended next step

## Scripts
- `scripts/screening.py` — OM parsing, scoring rubric, quick-screen calculator

## Templates
- `templates/quick-screen.md`
- `templates/screen-memo.md`
