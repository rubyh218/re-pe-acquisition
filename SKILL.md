---
name: real-estate-pe-acquisition
description: Institutional-grade real estate private equity acquisition workflows — sourcing, underwriting, market analysis, comps, IC memos, due diligence, LOI/PSA, and handoff to asset management. Pairs with the real-estate-asset-management skill (vendored at vendor/asset-management/) for shared returns, debt, waterfall, and document-styling helpers.
---

# Real Estate PE Acquisition

End-to-end acquisitions workflow for institutional real estate investors. Covers deal sourcing through closing and handoff to asset management.

## Asset Classes

Mirrors the asset-management skill: **multifamily, office, industrial, retail, hospitality, infrastructure**. Per-class underwriting nuances live in `asset_classes/`.

## Workflows (stage-gated)

Each stage has a deliverable. Stages are sequential but can iterate.

1. `workflows/01-sourcing-screening.md` — OM intake, deal scoring, quick-screen pro forma
2. `workflows/02-market-analysis.md` — market & submarket brief
3. `workflows/03-comps.md` — sales and rent comp analysis
4. `workflows/04-underwriting.md` — full pro forma, debt sizing, sensitivities
5. `workflows/05-ic-memo.md` — investment committee memo
6. `workflows/06-due-diligence.md` — phase-gated DD checklist
7. `workflows/07-loi-psa.md` — LOI generation, PSA review checklist
8. `workflows/08-close-handoff.md` — closing reconciliation, handoff to AM skill

## Shared with asset-management skill

Imported from `vendor/asset-management/scripts/`:

| Script | Purpose | Acquisitions usage |
|---|---|---|
| `returns.py` | IRR, NPV, MOIC | Levered/unlevered returns on projected cash flows |
| `waterfall.py` | American waterfall distributions | Project promote/pref to LP/GP on hold-period cash flows |
| `debt_metrics.py` | DSCR, debt yield, LTV/LTC, sizing | Constraint-based loan sizing (min of LTV/DSCR/DY) |
| `excel_style.py` | Institutional Excel formatting | Pro forma exports, sensitivity tables |
| `docx_style.py` | Institutional Word formatting | IC memo, market brief, LOI |

## Acquisitions-only scripts (to be built)

Will live in `scripts/` once each workflow is designed:

- `underwriting/pro_forma.py` — 10-yr cash flow build
- `underwriting/debt_sizing.py` — solve max proceeds across LTV/DSCR/DY constraints
- `underwriting/sensitivity.py` — 2-axis sensitivity tables, tornado charts
- `comps/sales_comps.py`, `comps/rent_comps.py` — comp adjustment models
- `market_data/adapters/` — CoStar export parsers + Census/BLS/HUD/FRED API clients
- `market_data/market_brief.py` — composes 2-page brief
- `memos/ic_memo.py`, `memos/loi.py` — docx generators
- `screening.py` — OM scoring rubric

## Market data strategy

CoStar has no public API. Hybrid approach:

- **CoStar** (sanctioned manual exports): rent comps, sales comps, supply pipeline, tenant rosters. User exports XLSX/PDF from CoStar UI → drops into `inbox/costar/{type}/` → adapter parses and caches.
- **Free APIs** for everything CoStar resells from public sources: Census ACS (demographics), BLS QCEW/LAUS (employment), HUD (FMR), FRED (rates/macro).
- **STR data** (CoStar-owned, hospitality): subscription TBD. **Manual CSV fallback shipped**: analysts assemble a monthly comp-set CSV from the STR dashboard (or HVS / CBRE Hotels / JLL Hotels) and run `scripts/market_data/str_manual.py` for RGI / ARI / MPI + T-3/T-6/T-12 trailing windows. See `asset_classes/hospitality.md` for the CSV format and `examples/example-str-compset.csv` for a reference file.

Never scrape CoStar — TOS violation, account ban risk.

## Conventions

- All deliverables follow institutional investor formatting (Wall Street modeling aesthetics) — use shared `excel_style.py` / `docx_style.py`.
- Currency in USD, no abbreviations in models (write 1,000,000 not 1MM).
- Hold-period default: 5 years. Exit cap = entry cap + 25 bps unless overridden.
- Debt-sizing default: most-binding of 65% LTV / 1.25x DSCR / 8% debt yield.
