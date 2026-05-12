# 03 — Comps (Sales & Rent)

Triangulate value via comparable sales and stabilized rent via comparable leases.

## Inputs
- Subject property: address, asset class, vintage, size, condition
- CoStar sales comp export (filtered by user in CoStar UI to relevant comp set) — XLSX → `inbox/costar/comps/sales_*.xlsx`
- CoStar lease comp export — XLSX → `inbox/costar/comps/lease_*.xlsx`

## Process

### Sales comps
1. **Comp set selection** — user-driven in CoStar (typically 5–10 transactions, last 18–24 months, similar submarket/vintage/size).
2. **Adjustments** — standardize to subject:
   - Time (market trend since transaction)
   - Location (submarket tier)
   - Size (per-unit / per-SF)
   - Vintage
   - Condition (renovated / original / value-add basis)
3. **Conclusion** — adjusted $/unit, $/SF, and cap rate range. Implied subject value = midpoint × subject units/SF.

### Rent comps
1. **Comp set** — currently leasing properties in same submarket, similar product class.
2. **Effective rent** — face rent − concessions amortized over lease term.
3. **Adjustments** — unit mix, finishes, amenities, walkability, parking.
4. **Conclusion** — market rent / unit / month (multifamily) or NNN rent / SF / yr (commercial). Drives Year 3 stabilized rent in the pro forma.

## Deliverables
- `comps.xlsx` — two tabs (sales, rent) with adjustment grids
- Comp summary section in IC memo

## Scripts
- `scripts/comps/sales_comps.py` — adjustment model, weighted-average conclusion
- `scripts/comps/rent_comps.py` — effective rent calculation, adjustment model

## Templates
- `templates/comps.xlsx` (institutional adjustment grid format)
