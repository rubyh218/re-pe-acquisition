"""
cli.py — Commercial underwriting CLI.

Usage:
    python -m scripts.underwriting.commercial examples/example-office.yaml
    python -m scripts.underwriting.commercial deal.yaml -o outputs/asset.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .excel_writer import write_commercial_workbook
from .models import load_commercial_deal
from .pro_forma import build_commercial_pro_forma
from .waterfall import run_commercial_waterfall


def _print_summary(pf, wf):
    deal = pf.deal
    bar = "-" * 72
    print(bar)
    print(f"  {deal.deal_name}")
    print(f"  {deal.property.address}")
    print(bar)
    print(f"  {'Asset Class':<32} {deal.property.asset_class}")
    print(f"  {'RBA (SF)':<32} {deal.property.total_rba:>16,}")
    print(f"  {'In-Place Occupancy':<32} {deal.property.in_place_occupancy*100:>15.1f}%")
    print(f"  {'# Leases':<32} {len(deal.property.rent_roll):>16}")
    print(f"  {'Purchase Price':<32} ${deal.acquisition.purchase_price:>16,.0f}")
    print(f"  {'  per SF':<32} ${deal.acquisition.purchase_price/deal.property.total_rba:>16,.2f}")
    print(f"  {'All-In Basis':<32} ${pf.sources_uses.total_uses:>16,.0f}")
    print(f"  {'  per SF':<32} ${pf.all_in_basis_per_sf:>16,.2f}")
    print(bar)
    print(f"  {'Going-In Cap':<32} {pf.going_in_cap*100:>16.2f}%")
    print(f"  {'Yr ' + str(pf.roc.stab_yr) + ' Stabilized Cap':<32} {pf.stabilized_cap*100:>16.2f}%")
    print(f"  {'Exit Cap':<32} {deal.exit.exit_cap*100:>16.2f}%")
    print(bar)
    s = pf.sizing
    print(f"  {'Loan Amount':<32} ${s.loan_amount:>16,.0f}  (binding: {s.binding})")
    print(f"  {'Implied LTV / DSCR / DY':<32} {s.implied_ltv*100:.1f}% / {s.implied_dscr:.2f}x / {s.implied_debt_yield*100:.2f}%")
    print(f"  {'Equity Check':<32} ${pf.sources_uses.equity_check:>16,.0f}")
    print(bar)
    print(f"  {'Total Equity IRR (project)':<32} {wf.total_equity_irr*100:>16.2f}%")
    print(f"  {'Total Equity MOIC':<32} {wf.total_equity_moic:>16.2f}x")
    print(f"  {'LP Net IRR':<32} {wf.lp.irr*100:>16.2f}%")
    print(f"  {'LP Net MOIC':<32} {wf.lp.moic:>16.2f}x")
    print(f"  {'GP Net IRR':<32} {wf.gp.irr*100:>16.2f}%")
    print(f"  {'GP Net MOIC':<32} {wf.gp.moic:>16.2f}x")
    print(bar)


def main():
    ap = argparse.ArgumentParser(description="Underwrite a commercial deal (office / industrial / retail).")
    ap.add_argument("deal", help="path to deal.yaml")
    ap.add_argument("-o", "--out", help="output XLSX path (default: outputs/<deal_id>.xlsx)")
    args = ap.parse_args()

    deal = load_commercial_deal(args.deal)
    pf = build_commercial_pro_forma(deal)
    wf = run_commercial_waterfall(pf)

    out_path = Path(args.out) if args.out else Path("outputs") / f"{deal.deal_id}.xlsx"
    written = write_commercial_workbook(pf, wf, out_path)

    _print_summary(pf, wf)
    print(f"  Workbook written to: {written}")
    print()


if __name__ == "__main__":
    main()
