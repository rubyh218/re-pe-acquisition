"""
cli.py -- Data center underwriting CLI (single entry, auto-dispatches).

Usage:
    python -m scripts.underwriting.datacenter examples/example-dc-wholesale.yaml
    python -m scripts.underwriting.datacenter examples/example-dc-colo.yaml -o out.xlsx

Dispatch:
    property.contracts present     -> wholesale engine
    property.cabinet_mix present   -> colo engine
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .colo_pro_forma import build_colo_pro_forma
from .excel_writer import write_colo_workbook, write_wholesale_workbook
from .models import detect_dc_kind, load_dc_colo_deal, load_dc_wholesale_deal
from .waterfall import run_datacenter_waterfall
from .wholesale_pro_forma import build_wholesale_pro_forma


def _print_summary(deal, pf, wf, kind: str) -> None:
    bar = "-" * 72
    print(bar)
    print(f"  {deal.deal_name}  ({kind})")
    print(f"  {deal.property.address}")
    print(bar)
    if kind == "wholesale":
        prop = deal.property
        print(f"  {'Critical MW':<32} {prop.mw_critical:>16.2f}")
        print(f"  {'Commissioned MW':<32} {prop.mw_commissioned:>16.2f}")
        print(f"  {'Leased MW (in-place)':<32} {prop.leased_mw:>16.2f}")
        print(f"  {'Utilization':<32} {prop.utilization_pct*100:>15.1f}%")
        print(f"  {'Tier Rating':<32} {prop.tier_rating:>16}")
        print(f"  {'Price / MW':<32} ${deal.acquisition.purchase_price/prop.mw_critical:>15,.0f}")
        print(f"  {'All-In / MW':<32} ${pf.all_in_basis_per_mw:>15,.0f}")
    else:
        prop = deal.property
        print(f"  {'Critical MW':<32} {prop.mw_critical:>16.2f}")
        print(f"  {'Total Cabinets':<32} {prop.total_cabinets:>16,}")
        print(f"  {'Total Contracted kW':<32} {prop.total_contracted_kw:>16,.0f}")
        print(f"  {'Tier Rating':<32} {prop.tier_rating:>16}")
        print(f"  {'Price / Cabinet':<32} ${deal.acquisition.purchase_price/prop.total_cabinets:>15,.0f}")
        print(f"  {'All-In / Cabinet':<32} ${pf.all_in_basis_per_cabinet:>15,.0f}")
        print(f"  {'All-In / MW':<32} ${pf.all_in_basis_per_mw:>15,.0f}")
    print(bar)
    print(f"  {'Going-In Cap':<32} {pf.going_in_cap*100:>15.2f}%")
    print(f"  {'Stabilized Cap':<32} {pf.stabilized_cap*100:>15.2f}%")
    print(f"  {'Exit Cap':<32} {deal.exit.exit_cap*100:>15.2f}%")
    print(bar)
    s = pf.sizing
    print(f"  {'Loan Amount':<32} ${s.loan_amount:>15,.0f}  (binding: {s.binding})")
    print(f"  {'LTV / DSCR / DY':<32} {s.implied_ltv*100:.1f}% / {s.implied_dscr:.2f}x / {s.implied_debt_yield*100:.2f}%")
    print(f"  {'Equity Check':<32} ${pf.sources_uses.equity_check:>15,.0f}")
    print(bar)
    print(f"  {'Project IRR / MOIC':<32} {wf.total_equity_irr*100:>14.2f}% / {wf.total_equity_moic:.2f}x")
    print(f"  {'LP Net IRR / MOIC':<32} {wf.lp.irr*100:>14.2f}% / {wf.lp.moic:.2f}x")
    print(f"  {'GP IRR / MOIC':<32} {wf.gp.irr*100:>14.2f}% / {wf.gp.moic:.2f}x")
    print(bar)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Underwrite a data center (wholesale or colo).")
    ap.add_argument("deal", help="path to deal.yaml")
    ap.add_argument("-o", "--out", help="output XLSX path (default: outputs/<deal_id>.xlsx)")
    args = ap.parse_args(argv)

    kind = detect_dc_kind(args.deal)
    if kind == "wholesale":
        deal = load_dc_wholesale_deal(args.deal)
        pf = build_wholesale_pro_forma(deal)
        wf = run_datacenter_waterfall(pf)
        out_path = Path(args.out) if args.out else Path("outputs") / f"{deal.deal_id}.xlsx"
        written = write_wholesale_workbook(pf, wf, out_path)
    else:
        deal = load_dc_colo_deal(args.deal)
        pf = build_colo_pro_forma(deal)
        wf = run_datacenter_waterfall(pf)
        out_path = Path(args.out) if args.out else Path("outputs") / f"{deal.deal_id}.xlsx"
        written = write_colo_workbook(pf, wf, out_path)

    _print_summary(deal, pf, wf, kind)
    print(f"  Workbook written to: {written}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
