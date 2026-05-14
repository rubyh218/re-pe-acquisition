"""
cli.py -- Infrastructure underwriting CLI.

Usage:
    python -m scripts.underwriting.infrastructure examples/example-solar-ppa.yaml
    python -m scripts.underwriting.infrastructure deal.yaml -o out.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .excel_writer import write_infrastructure_workbook
from .models import load_infrastructure_deal
from .pro_forma import build_infrastructure_pro_forma
from .waterfall import run_infrastructure_waterfall


def _print_summary(deal, pf, wf) -> None:
    bar = "-" * 72
    prop = deal.property
    gen = prop.generation
    print(bar)
    print(f"  {deal.deal_name}  ({gen.technology.title()})")
    print(f"  {prop.address}")
    print(bar)
    print(f"  {'Technology':<32} {gen.technology:>16}")
    print(f"  {'Market / ISO':<32} {prop.market:>16}")
    print(f"  {'Nameplate (MW AC)':<32} {gen.nameplate_mw_ac:>16.2f}")
    print(f"  {'Capacity Factor':<32} {gen.capacity_factor*100:>15.1f}%")
    print(f"  {'Yr-1 Net Generation (MWh)':<32} {pf.years[0].net_generation_mwh:>16,.0f}")
    print(f"  {'Price / MW':<32} ${deal.acquisition.purchase_price/gen.nameplate_mw_ac:>15,.0f}")
    print(f"  {'All-In / MW':<32} ${pf.all_in_basis_per_mw:>15,.0f}")
    cs0 = pf.contracted_share_schedule[0]
    print(f"  {'Yr-1 Contracted Share':<32} {cs0.contracted_share*100:>15.1f}%")
    print(bar)
    print(f"  {'Going-In Cap':<32} {pf.going_in_cap*100:>15.2f}%")
    print(f"  {'Yr ' + str(pf.roc.stab_yr) + ' Cap (on price)':<32} {pf.stabilized_cap*100:>15.2f}%")
    print(f"  {'Yr ' + str(pf.roc.stab_yr) + ' YoC (all-in)':<32} {pf.roc.trended_stab*100:>15.2f}%")
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
    ap = argparse.ArgumentParser(description="Underwrite an infrastructure asset.")
    ap.add_argument("deal", help="path to deal.yaml")
    ap.add_argument("-o", "--out", help="output XLSX path (default: outputs/<deal_id>.xlsx)")
    args = ap.parse_args(argv)

    deal = load_infrastructure_deal(args.deal)
    pf = build_infrastructure_pro_forma(deal)
    wf = run_infrastructure_waterfall(pf)
    out_path = Path(args.out) if args.out else Path("outputs") / f"{deal.deal_id}.xlsx"
    written = write_infrastructure_workbook(pf, wf, out_path)

    _print_summary(deal, pf, wf)
    print(f"  Workbook written to: {written}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
