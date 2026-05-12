"""
extract.py — CLI to extract a deal.yaml from an OM PDF.

Usage:
    python -m scripts.underwriting.extract path/to/om.pdf [-o out.yaml]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from .om_extractor import deal_to_yaml, extract_om_raw, validate_deal


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
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    out_path = args.output or args.pdf.with_suffix(".yaml")

    print(f"Extracting {args.pdf.name} -> {out_path.name} via Claude Sonnet 4.6...")
    raw, notes = extract_om_raw(args.pdf)

    try:
        deal = validate_deal(raw)
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
    print(f"  property:   {deal.property.name} ({deal.property.unit_count} units)")
    print(f"  price:      ${deal.acquisition.purchase_price:,.0f}")
    if notes:
        print(f"  notes:      {len(notes)} extraction note(s) -- review YAML header")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
