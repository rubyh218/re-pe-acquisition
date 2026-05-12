"""
cli.py — Hospitality underwriting CLI.

Usage:
    python -m scripts.underwriting.hospitality examples/example-hotel.yaml
    python -m scripts.underwriting.hospitality deal.yaml -o outputs/asset.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .excel_writer import write_hotel_workbook
from .models import load_hotel_deal
from .pro_forma import build_hotel_pro_forma
from .waterfall import run_hotel_waterfall


def _print_summary(pf, wf):
    deal = pf.deal
    bar = "-" * 72
    print(bar)
    print(f"  {deal.deal_name}")
    print(f"  {deal.property.address}")
    print(bar)
    print(f"  {'Brand / Service Level':<32} {deal.property.brand} ({deal.property.service_level})")
    print(f"  {'Keys':<32} {deal.property.keys:>16,}")
    print(f"  {'Yr 1 ADR / Occ / RevPAR':<32} ${pf.years[0].adr:>7,.2f} / {pf.years[0].occupancy*100:>5.1f}% / ${pf.years[0].revpar:>7,.2f}")
    print(f"  {'Purchase Price':<32} ${deal.acquisition.purchase_price:>16,.0f}")
    print(f"  {'  per Key':<32} ${deal.acquisition.purchase_price/deal.property.keys:>16,.0f}")
    print(f"  {'All-In Basis':<32} ${pf.sources_uses.total_uses:>16,.0f}")
    print(f"  {'  per Key':<32} ${pf.all_in_basis_per_key:>16,.0f}")
    print(bar)
    print(f"  {'Going-In Cap (post-reserve)':<32} {pf.going_in_cap*100:>16.2f}%")
    print(f"  {'Yr 3 Stabilized Cap':<32} {pf.stabilized_cap*100:>16.2f}%")
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
    ap = argparse.ArgumentParser(description="Underwrite a hospitality deal (hotel, USALI structure).")
    ap.add_argument("deal", help="path to deal.yaml")
    ap.add_argument("-o", "--out", help="output XLSX path (default: outputs/<deal_id>.xlsx)")
    args = ap.parse_args()

    deal = load_hotel_deal(args.deal)
    pf = build_hotel_pro_forma(deal)
    wf = run_hotel_waterfall(pf)

    out_path = Path(args.out) if args.out else Path("outputs") / f"{deal.deal_id}.xlsx"
    written = write_hotel_workbook(pf, wf, out_path)

    _print_summary(pf, wf)
    print(f"  Workbook written to: {written}")
    print()


if __name__ == "__main__":
    main()
