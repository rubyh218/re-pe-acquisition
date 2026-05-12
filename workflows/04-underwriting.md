# 04 — Underwriting

The full pro forma. Ties together market thesis, comps, business plan, debt structure, and waterfall to produce the return profile presented to IC.

## Inputs
- Quick-screen output (workflow 01)
- Market brief (workflow 02) — rent growth, vacancy assumptions
- Comps conclusions (workflow 03) — stabilized market rent, exit cap
- Business plan — value-add CapEx scope, lease-up timing, OpEx initiatives
- Debt term sheet (or assumed terms) — rate, term, IO period, amortization, covenants
- Equity structure — LP/GP split, pref, promote tiers, GP co-invest %

## Process
1. **Revenue build (Year 1 → Year 10)**
   - Rent roll roll-forward (multifamily) or lease-by-lease (commercial)
   - Market rent growth schedule (from market brief)
   - Vacancy & credit loss
   - Other income (parking, RUBS, fees) for multifamily; expense recoveries (NNN) for commercial
2. **OpEx build** — line-item with growth rates (typically 3% controllable, RE tax per local rules, insurance per market)
3. **CapEx schedule** — value-add scope timed by year, recurring CapEx reserve ($/unit or $/SF)
4. **Debt sizing** — solve max proceeds = `min(LTV × purchase price, NOI / DSCR / debt service constant, NOI / debt yield)`. Use shared `debt_metrics.py`.
5. **Cash flows** — unlevered (NOI − CapEx) and levered (− debt service)
6. **Waterfall** — apply pref + promote tiers to levered cash flows. Use shared `waterfall.py` with acquisitions wrapper.
7. **Returns** — unlevered and levered IRR, MOIC, equity multiple at LP and GP level. Use shared `returns.py`.
8. **Sensitivities** — 2-axis tables: exit cap × rent growth, purchase price × LTV, IRR × hold period. Tornado for full driver set.

## Deliverables
- `underwriting.xlsx` — institutional-style model: assumptions tab, revenue/OpEx/CapEx tabs, debt tab, waterfall tab, returns summary, sensitivity tabs
- Returns summary table for IC memo

## Scripts
- `scripts/underwriting/pro_forma.py` — cash flow build orchestrator
- `scripts/underwriting/debt_sizing.py` — constraint-based sizing wrapper
- `scripts/underwriting/sensitivity.py` — 2-axis tables, tornado
- `scripts/underwriting/waterfall_acq.py` — wrapper around shared waterfall.py for projected cash flows

## Templates
- `templates/underwriting.xlsx`
