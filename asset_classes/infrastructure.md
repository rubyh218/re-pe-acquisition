# Infrastructure — Underwriting Nuances

Real estate–adjacent infrastructure. Long-duration, contracted cash flows, often regulated. Underwriting looks closer to project finance than core real estate.

## Sub-types (very different — pick first)
- **Data centers** — colocation, hyperscale, edge; power-constrained; AI-driven demand surge
- **Cell towers / small cell** — multi-tenant antenna sites
- **Fiber networks** — dark fiber, lit services
- **Energy infrastructure** — solar farms, wind, battery storage, transmission
- **Logistics infrastructure** — intermodal yards, ports, IOS (industrial outdoor storage)
- **Self-storage** *(if treated as infrastructure rather than commercial RE)*
- **Healthcare-adjacent** — MOB/medical office, life science (sometimes treated separately)

## Revenue model — generally contracted, long-duration
- **Take-or-pay / capacity contracts** — customer pays for reserved capacity regardless of use (common in fiber, towers, data centers)
- **Power Purchase Agreements (PPAs)** — long-dated (10–25 yr) contracted off-take (energy)
- **Master lease structures** — single tenant, long term, NNN-style (some data centers, towers)
- **Escalators** — fixed (2–3%/yr) or CPI-linked

## Data center specifics (most active institutional play)
- **Power** is the gating constraint — measured in MW (megawatts) of critical IT load
- **PUE** (Power Usage Effectiveness) — total facility power / IT power; lower is better (1.1–1.5 typical)
- **Tier classification** (I–IV) — redundancy / uptime (Tier III = N+1, 99.982% uptime)
- **Customer mix** — hyperscale (Microsoft, Google, AWS, Meta) vs. enterprise vs. retail colo
- **Lease term** — hyperscale often 10–15 yrs with renewals
- **Power cost passthrough** — typically pass-through to customer, but mechanics vary
- **Cooling design** — air-cooled vs. liquid (liquid required for AI/GPU densification)
- **Site capacity expansion** — phased build-out; underwrite committed vs. contingent capacity

## Cell tower specifics
- **Multi-tenancy** drives returns — adding 2nd, 3rd carrier dramatically improves yield
- **Master Lease Agreements** with carriers (Verizon, AT&T, T-Mobile, DISH)
- **Ground lease** under tower — major cost; consolidate / extend critical to value
- **Co-location amendments** — additional revenue at low marginal cost

## Energy infrastructure specifics
- **PPA counterparty credit** — 20-yr cash flows only as good as the off-taker
- **ITC / PTC** — federal investment / production tax credits; significantly affect economics
- **Interconnection queue** — gating constraint for new development
- **Curtailment risk** — grid can't always take generation
- **Battery degradation** — augmentation CapEx schedule

## OpEx specifics (highly asset-specific)
- Data centers: power, cooling maintenance, security, network connectivity
- Towers: ground rent, utilities, R&M, insurance — generally light
- Energy: O&M contracts (often outsourced to OEM), inverter replacement, panel cleaning

## Asset-class-specific DD
- **Customer credit** — long-duration contracts only as good as counterparty
- **Technical due diligence** — engineering review of capacity, power, redundancy (data centers); structural engineering (towers); production data + degradation (energy)
- **Permits + entitlement** — interconnection, zoning, environmental
- **Land control** — fee vs. ground lease; if ground lease, residual term + extension rights
- **Revenue contract review** — escalators, termination rights, change-of-control, indemnification
- **Tax credit / regulatory regime** — confirm continued eligibility

## Risks to underwrite
- **Technology obsolescence** (data centers — cooling/density requirements changing fast with AI)
- **Counterparty concentration** (single hyperscale tenant = single point of failure)
- **Power availability** (data centers — many markets have multi-year power constraints)
- **Regulatory / tariff** changes (energy)
- **Ground lease renewal risk** (towers)

## Data sources
- **Data centers** — datacenterHawk, Cushman Global Data Center reports, CBRE Data Center reports
- **Towers** — public REIT 10-Ks (American Tower, Crown Castle, SBA) for benchmarks
- **Energy** — EIA (federal energy data), state PUC data, ISO/RTO market data (CAISO, ERCOT, PJM, etc.)
- **Self-storage** (if applicable here) — Yardi STORE, Radius+ for supply/demand by 3-mile radius

## Note
Infrastructure underwriting models diverge meaningfully from traditional RE pro forma. May warrant a dedicated `scripts/underwriting/infra_pro_forma.py` separate from the standard `pro_forma.py` once we get to a real infrastructure deal. Defer that decision until first live deal in this class.
