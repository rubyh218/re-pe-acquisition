# 05 — Investment Committee Memo

The decision document. Synthesizes everything for committee approval.

## Inputs
- All prior workflow outputs (01–04)

## Standard sections
1. **Executive summary** — one paragraph: what we're buying, why, expected returns, ask
2. **Transaction overview** — price, basis, structure, timing, broker, seller
3. **Investment thesis** — 3–5 bullets on why this deal wins
4. **Property description** — physical, operational, current performance
5. **Market & submarket** — pulled from workflow 02 brief
6. **Business plan** — what we'll do post-close (renovation scope, lease-up, refinance plan)
7. **Underwriting summary** — key assumptions table, returns table (unlevered/levered IRR, MOIC, EM)
8. **Sensitivity analysis** — 2–3 most relevant sensitivity tables
9. **Capital structure** — debt terms, equity raise, GP co-invest, fees
10. **Risks & mitigants** — table format, rank-ordered
11. **Comps support** — sales comps and rent comps summary tables
12. **Recommendation** — approve / approve with conditions / pass

## Deliverables
- `ic-memo.docx` — institutional-formatted document with embedded charts/tables from underwriting.xlsx
- Appendix: full pro forma PDF, market brief, comp grids

## Scripts
- `scripts/memos/ic_memo.py` — composes docx using shared `docx_style.py`, embeds Excel ranges as images

## Templates
- `templates/ic-memo.docx` — section headers, table styles, chart placeholders
