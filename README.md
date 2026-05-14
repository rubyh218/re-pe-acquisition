# Real Estate PE Acquisition

Institutional-grade underwriting and deal-workflow toolkit for real estate private equity acquisitions. Covers sourcing through closing across **multifamily, office, industrial, retail, hospitality, datacenter, and energy infrastructure** asset classes, with a paired asset-management library vendored as a git submodule.

Outputs follow Wall Street modeling conventions: multi-tier IRR-hurdle waterfalls, three-basis ROC (untrended / trended / exit-FTM), institutional Excel formatting, and a docx Investment Committee memo generator.

## What's in the box

| Asset class | Engine | Example |
|---|---|---|
| Multifamily | `scripts/underwriting/pro_forma.py` | `examples/marina-apartments.yaml` |
| Office / Industrial / Retail | `scripts/underwriting/commercial/` (lease-by-lease) | `examples/example-office.yaml`, `example-industrial.yaml`, `example-retail.yaml` |
| Hospitality | `scripts/underwriting/hospitality/` (USALI) | `examples/example-hotel.yaml` |
| Datacenter — wholesale | `scripts/underwriting/datacenter/wholesale_pro_forma.py` | `examples/example-dc-wholesale.yaml` |
| Datacenter — colocation | `scripts/underwriting/datacenter/colo_pro_forma.py` | `examples/example-dc-colo.yaml` |
| Infrastructure (solar / wind / BESS) | `scripts/underwriting/infrastructure/pro_forma.py` | `examples/example-solar-ppa.yaml`, `example-wind.yaml`, `example-bess.yaml` |

Every engine emits an institutional Excel workbook (executive summary + per-engine detail tabs) and feeds the cross-engine **IC memo** generator (`scripts/underwriting/ic_memo.py`).

The datacenter package additionally ships a **negotiation playbook** (`datacenter/negotiation.py`) with structured acquisition and lease-tactic catalogs that surface in the IC memo.

The infrastructure engine handles any blend of three revenue streams — contracted PPA ($/MWh), capacity / availability payments ($/MW-mo), and merchant exposure (year-indexed price curve) — against a generation profile (nameplate MW, capacity factor, degradation, curtailment, availability). It models ITC as Yr-1 cash and PTC as a per-MWh credit over the term, sizes OpEx on nameplate (fixed) + net generation (variable), and handles lumpy augmentation capex (BESS swaps, inverter replacement, blade refurb). The IC memo's section 2a reports the contracted-vs-merchant revenue mix by hold year — the institutional headline for any energy asset.

## Install

Requires Python 3.11+ (developed on 3.14).

```bash
git clone --recurse-submodules https://github.com/rubyh218/re-pe-acquisition.git
cd re-pe-acquisition
pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY only if using OM extraction
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

The submodule at `vendor/asset-management/` provides shared helpers (`returns`, `waterfall`, `debt_metrics`, `excel_style`, `docx_style`) used by every engine. `scripts/__init__.py` adds the vendored `scripts/` directory to `sys.path`.

## Usage

All engines and tools take a YAML deal file.

### Underwriting → Excel

```bash
# Multifamily
python -m scripts.underwriting examples/marina-apartments.yaml -o outputs/marina.xlsx

# Commercial (office / industrial / retail)
python -m scripts.underwriting.commercial examples/example-office.yaml

# Hospitality
python -m scripts.underwriting.hospitality examples/example-hotel.yaml

# Datacenter (dispatches wholesale vs. colo from YAML shape)
python -m scripts.underwriting.datacenter examples/example-dc-wholesale.yaml
python -m scripts.underwriting.datacenter examples/example-dc-colo.yaml

# Energy infrastructure (solar / wind / BESS)
python -m scripts.underwriting.infrastructure examples/example-solar-ppa.yaml
python -m scripts.underwriting.infrastructure examples/example-wind.yaml
python -m scripts.underwriting.infrastructure examples/example-bess.yaml
```

### IC memo → Word

The IC memo generator auto-dispatches by `property.asset_class` (with fallback inference from the YAML shape):

```bash
python -m scripts.underwriting.ic_memo examples/example-dc-colo.yaml -o outputs/colo-ic-memo.docx
```

Sections: cover page, transaction summary, sources & uses, capital structure, pro forma, returns, sensitivities, risk register. Datacenter memos add a tenancy/cabinet-mix section (2a) and a negotiation playbook (section 9). Infrastructure memos add a generation profile + revenue-stream roster + contracted-share-by-year section (2a) and a tax-credit summary.

### OM extraction (PDF → YAML)

Convert an Offering Memorandum PDF to a draft `deal.yaml` using Claude (Sonnet 4.6, native PDF, cached system prompt):

```bash
python -m scripts.underwriting.extract path/to/om.pdf --type multifamily
python -m scripts.underwriting.extract path/to/om.pdf --type commercial -o draft.yaml
```

If extraction validation fails the tool writes a PARTIAL YAML with TODO markers — the analyst fills the gaps before running an engine. Requires `ANTHROPIC_API_KEY` in `.env`.

## Repo layout

```
asset_classes/        Per-class underwriting notes (office, retail, ...)
examples/             Sample deal YAMLs (one per asset class) + reference Excel outputs
inbox/                Drop zone for analyst inputs (CoStar exports, OMs) — gitignored
outputs/              Generated workbooks + IC memos — gitignored
scripts/underwriting/
  models.py           Pydantic v2 Deal schema (frozen, extra=forbid)
  pro_forma.py        Multifamily cash flow engine
  commercial/         Office / industrial / retail (lease-by-lease)
  hospitality/        USALI hotel engine
  datacenter/         Wholesale + colo engines + negotiation playbook
  infrastructure/     Energy generation engine (PPA / availability / merchant + ITC/PTC)
  debt_sizing.py      Solves min of LTV / DSCR / DY constraints
  waterfall_acq.py    Single-tier acquisition waterfall
  waterfall_multi.py  Multi-tier IRR-hurdle waterfall
  metrics.py          IRR, MOIC, three-basis ROC
  sensitivity.py      2-axis tables
  excel_summary.py    Shared executive summary tab (engine-agnostic)
  excel_writer.py     Multifamily Excel builder
  om_extractor.py     OM PDF -> Deal (Claude Sonnet 4.6)
  extract.py          OM extraction CLI
  ic_memo.py          Cross-engine IC memo docx generator
vendor/asset-management/   Git submodule — shared scripts (returns, waterfall, ...)
workflows/            Stage-gated workflow notes (01-sourcing -> 08-handoff)
SKILL.md              Claude Code skill manifest (paired tooling)
```

## Tests

```bash
python -m unittest discover -s tests -v
```

56 tests covering ROC math, debt sizing + amortization invariants, the
multi-tier waterfall (hand-derived expected values), pydantic schema
validation, and one end-to-end fixture per asset-class engine. Tests pin
the headline numbers each example YAML produces; intentional engine
changes need the relevant assertion updated in the PR.

## Conventions

- **Returns**: levered IRR, MOIC, TVPI, three-basis ROC.
- **Waterfall**: multi-tier American with IRR hurdles. LP/GP re-attribution by `gp_coinvest_pct`.
- **Debt sizing**: most-binding of 65% LTV / 1.25x DSCR / 8% debt yield (defaults; override per deal).
- **Hold**: 5 years default. Exit cap = entry cap + 25 bps unless specified.
- **Currency**: USD, no abbreviations in models (write `1000000`, not `1MM`).
- **Excel formatting**: institutional only (no Unicode box chars; cp1252-safe CLI output).

## Market data

CoStar has no public API, so the toolkit uses a hybrid approach:

- **CoStar** (sanctioned manual exports): rent comps, sales comps, supply pipeline. Drop XLSX/PDF into `inbox/costar/{type}/`; adapters parse and cache.
- **Free APIs**: Census ACS (demographics), BLS QCEW/LAUS (employment), HUD (FMR), FRED (rates/macro).
- **STR** (hospitality): TBD pending subscription confirmation.

CoStar scraping is a TOS violation — never do it.

## License

MIT — see [LICENSE](LICENSE).
