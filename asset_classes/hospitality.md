# Hospitality — Underwriting Nuances

Hotels are operating businesses, not real estate. Underwrite both the real estate and the operation.

## Revenue model
- **RevPAR = ADR × Occupancy** — the master metric
  - **ADR** (Average Daily Rate) — daily room revenue / rooms sold
  - **Occupancy** — rooms sold / rooms available
- **Departmental revenue** — rooms (60–80% of total), F&B, banquets, parking, spa
- **Group vs. transient mix** — affects rate volatility and forward visibility
- **Booking channels** — direct, OTA (with commission), GDS, brand.com — channel mix affects net realized rate
- **Rate by day-of-week** — leisure (weekend-heavy) vs. business (weekday-heavy) markets

## Brand vs. independent
- **Branded (Marriott, Hilton, Hyatt, IHG, Accor)** — franchise fee (5–7% of rooms revenue) + reservation/marketing (3–5%) + program fees; in exchange: distribution, loyalty, brand standards
- **Brand PIP (Property Improvement Plan)** — required CapEx for brand compliance; typical at acquisition (new owner) and franchise renewal (every 10–20 yrs); $20K–$80K/key
- **Independent / soft brand** — more flexibility, higher risk, requires marketing investment

## OpEx structure (per Uniform System of Accounts for Lodging — USALI)
- Departmental expenses (rooms, F&B, etc.) — variable with occupancy
- Undistributed expenses (admin, marketing, R&M, utilities) — semi-fixed
- Fixed expenses (RE tax, insurance, ground rent if any)
- Management fee (typically 2–4% of total revenue + incentive fee)
- Franchise fees (if branded)
- **GOP (Gross Operating Profit)** — pre-management-fee, pre-fixed
- **NOI** = GOP − management fee − fixed − FF&E reserve
- **FF&E reserve** — 3–5% of total revenue, cash-funded for furniture/fixtures replacement

## Sub-types (very different)
- **Luxury / upper-upscale** — Marriott, Ritz, Four Seasons; high ADR, F&B-heavy
- **Upscale / select-service** — Marriott Courtyard, Hilton Garden Inn; balanced ops
- **Limited-service / extended stay** — Hampton, Holiday Inn Express, Residence Inn; high margins, low CapEx
- **Resort** — destination-driven; seasonal; F&B + activities significant
- **Urban full-service** — group/business mix; high CapEx

## Asset-class-specific DD
- STR (Smith Travel Research / CoStar-owned) competitive set report — your hotel's RevPAR vs. comp set, "RGI" (RevPAR Index = your RevPAR / market RevPAR; >100 = outperforming)
- Brand inspection scores + standards compliance
- Existing PIP letter or anticipated PIP at acquisition
- Franchise agreement remaining term + renewal terms
- Management agreement (if owner doesn't operate)
- Group booking pace (forward bookings on books)
- Liquor license + transferability
- ADA compliance
- Recent CapEx history + deferred maintenance

## Submarket data points
- STR comp set RevPAR, ADR, Occ trend (3-yr)
- Pipeline (new supply) — STR provides; major risk to existing assets
- Demand drivers — major employers, convention center calendar, leisure attractions, airport traffic
- Seasonality patterns

## Data sources
- **STR (Smith Travel Research)** — comp set RevPAR data; CoStar-owned; **subscription required, no public API** — TBD if user has access
- **HVS, CBRE Hotels, JLL Hotels** — market reports (often free)
- **Hotel News Now** — industry trends
- Convention/visitor bureau data — group business pace

## Note for v1 launch
Without confirmed STR access, hospitality comps will lean on HVS/CBRE/JLL public reports, brand-published data, and triangulation from booking platforms. Returns confidence will be lower than other asset classes until STR pipeline is established.

## Manual STR comp-set CSV (fallback while subscription is TBD)

In the absence of a sanctioned STR API hookup, analysts can manually
assemble a monthly comp-set CSV from the STR web dashboard (or HVS / CBRE
Hotels / JLL Hotels published tables) and run it through
`scripts/market_data/str_manual.py`. The parser computes the three
institutional indices (RGI / ARI / MPI) plus T-3 / T-6 / T-12 trailing
windows.

### File location

Drop the file under `inbox/str/<property-id>-compset.csv` (gitignored —
`inbox/` is a per-deal drop zone).

### CSV format

Wide-format, one row per month. Columns (case-insensitive):

| Column | Type | Notes |
|---|---|---|
| `month` | `YYYY-MM` or `YYYY-MM-DD` | First-of-month is fine |
| `property_revpar` | $ | Subject hotel RevPAR |
| `property_adr` | $ | Subject hotel ADR |
| `property_occ` | decimal 0..1 | 0.80 = 80% |
| `compset_revpar` | $ | Comp set average |
| `compset_adr` | $ | Comp set average |
| `compset_occ` | decimal 0..1 | Comp set average |
| `new_supply_pipeline_pct` | decimal (optional) | Annualized submarket supply growth |

Comment lines starting with `#` are skipped, so analysts can annotate.

### Run

```bash
python -m scripts.market_data.str_manual \
    --csv inbox/str/hampton-sunbelt-compset.csv
```

Or from Python:

```python
from scripts.market_data.str_manual import load_compset, summary
print(summary(load_compset("inbox/str/hampton-sunbelt-compset.csv")))
```

Sample output:

```
STR COMP SET SUMMARY  (latest: 2026-03-01)
                           Property   Comp Set    Index
  RevPAR                 $   135.90 $   129.70   104.8
  ADR                    $   170.00 $   167.50   101.5
  Occupancy                   79.9%      77.4%   103.2

  Trailing window             RGI      ARI      MPI     Supply
  T-3  (to 2026-03-01)    104.2    101.4    102.7      3.13%
  T-6  (to 2026-03-01)    104.5    102.1    102.4      3.00%
  T-12 (to 2026-03-01)    104.8    102.0    102.7      2.73%
```

A reference example is bundled at `examples/example-str-compset.csv`. When
the STR subscription is in place this manual workflow gets replaced by
a proper adapter under `scripts/market_data/adapters/`; the index
formulas are the same, so the downstream IC memo / comp-set section
stays unchanged.
