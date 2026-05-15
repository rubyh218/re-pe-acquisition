"""
extract.py — CLI to extract a deal.yaml from an OM PDF.

Usage:
    python -m scripts.underwriting.extract path/to/om.pdf [-o out.yaml]

The `--type` flag selects the engine schema to extract against:
    multifamily | commercial | hospitality |
    datacenter_wholesale | datacenter_colo | infrastructure

`commercial` covers office / industrial / retail; the asset_class within
the property block disambiguates them.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from .om_extractor import (
    deal_to_yaml,
    extract_om_raw,
    supported_deal_types,
    validate_deal,
)


def _write_partial_yaml(raw: dict, notes: dict, errors: list, out_path: Path) -> None:
    """Write the extracted (un-validated) dict as a draft YAML with TODO header."""
    header = "# PARTIAL EXTRACTION -- analyst must fill TODO fields before running engine.\n"
    header += "# Validation errors from extractor (these fields need analyst input):\n"
    for err in errors:
        loc = ".".join(str(p) for p in err["loc"])
        header += f"#   {loc}: {err['msg']}\n"
    if notes:
        header += "#\n# Extraction notes (broker gaps / assumptions):\n"
        for k, v in notes.items():
            header += f"#   {k}: {v}\n"
    header += "#\n"
    body = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    out_path.write_text(header + body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Create a .env file (see .env.example).", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Extract a deal YAML from an Offering Memorandum PDF.")
    parser.add_argument("pdf", type=Path, help="Path to the OM PDF.")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output YAML path (default: <pdf-stem>.yaml in same dir).",
    )
    parser.add_argument(
        "-t", "--type",
        choices=supported_deal_types(),
        default="multifamily",
        help=(
            "OM type / engine schema (default: multifamily). "
            "Choices: multifamily, commercial (office/industrial/retail), "
            "hospitality, datacenter_wholesale, datacenter_colo, infrastructure."
        ),
    )
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    out_path = args.output or args.pdf.with_suffix(".yaml")

    print(f"Extracting {args.pdf.name} ({args.type}) -> {out_path.name} via Claude Sonnet 4.6...")
    raw, notes = extract_om_raw(args.pdf, deal_type=args.type)

    try:
        deal = validate_deal(raw, deal_type=args.type)
    except ValidationError as e:
        _write_partial_yaml(raw, notes, e.errors(), out_path)
        print(f"PARTIAL: wrote {out_path} ({len(e.errors())} field(s) need analyst input)", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            print(f"  TODO {loc}: {err['msg']}", file=sys.stderr)
        return 1

    yaml_text = deal_to_yaml(deal, notes)
    out_path.write_text(yaml_text, encoding="utf-8")

    print(f"OK: wrote {out_path}")
    print(f"  deal_id:    {deal.deal_id}")
    print(f"  property:   {_property_summary(deal, args.type)}")
    print(f"  price:      ${deal.acquisition.purchase_price:,.0f}")
    if notes:
        print(f"  notes:      {len(notes)} extraction note(s) -- review YAML header")
    return 0


def _property_summary(deal, deal_type: str) -> str:
    """Engine-specific one-liner describing the extracted property."""
    p = deal.property
    name = p.name
    if deal_type == "commercial":
        return f"{name} ({p.total_rba:,} SF, {len(p.rent_roll)} leases)"
    if deal_type == "multifamily":
        return f"{name} ({p.unit_count} units)"
    if deal_type == "hospitality":
        return f"{name} ({p.keys} keys, {p.brand} {p.flag_type})"
    if deal_type == "datacenter_wholesale":
        return f"{name} ({p.mw_critical} MW critical, {len(p.contracts)} contracts)"
    if deal_type == "datacenter_colo":
        total_cabs = sum(c.count for c in p.cabinet_mix)
        return f"{name} ({total_cabs} cabinets, {len(p.cabinet_mix)} products)"
    if deal_type == "infrastructure":
        return f"{name} ({p.generation.nameplate_mw_ac} MW {p.generation.technology})"
    return f"{name}"


if __name__ == "__main__":
    raise SystemExit(main())
