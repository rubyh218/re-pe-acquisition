# 02 — Market & Submarket Analysis

Build the market thesis: is the location attractive, is rent/value growth defensible, what's the supply risk?

## Inputs
- Property address & submarket designation
- (Optional) CoStar market/submarket export — XLSX/PDF
- (Optional) CoStar supply pipeline export — XLSX

## Data sources
- **Census ACS** — population, household income, age distribution, owner/renter mix (free API)
- **BLS QCEW** — employment by NAICS sector, wage growth (free API)
- **BLS LAUS** — unemployment rate (free API)
- **HUD** — Fair Market Rents, CHAS housing affordability (free API)
- **FRED** — 10-yr treasury, SOFR, regional cap rate spreads (free API)
- **CoStar** — rent trends, vacancy, absorption, supply pipeline, tenant rosters (manual export)

## Process
1. **Macro context** — MSA-level demographics, employment trend, top employers, diversification.
2. **Submarket fundamentals** — rent/SF or rent/unit trend (5-yr), vacancy trend, absorption, concession environment.
3. **Supply pipeline** — under-construction + planned as % of standing inventory; expected delivery timing vs. our hold period.
4. **Demand drivers** — employment growth in relevant sectors (e.g., logistics for industrial, healthcare/tech for office), household formation, migration.
5. **Rent growth thesis** — defensible base-case growth rate with comp evidence.

## Deliverables
- `market-brief.docx` — 2 pages: macro snapshot, submarket fundamentals, supply pipeline chart, rent growth thesis, key risks
- Cached parquet of all source data in `scripts/market_data/cache/` keyed by submarket + as-of date

## Scripts
- `scripts/market_data/adapters/` — one adapter per source
- `scripts/market_data/market_brief.py` — composes the brief

## Templates
- `templates/market-brief.docx`
