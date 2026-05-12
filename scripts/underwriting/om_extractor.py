"""
om_extractor.py — Extract a Deal YAML from an Offering Memorandum PDF.

Sends the OM PDF natively to Claude Sonnet 4.6, asks for JSON matching the
Deal schema, validates via Deal.model_validate, writes to YAML.

Fields not present in the OM are filled with `null` (and a TODO comment in the
output YAML) rather than hallucinated. Broker-stated numbers are preserved
verbatim; analyst assumptions (exit cap, growth, debt terms when not financed
deals, etc.) are flagged as TODO.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import anthropic
import yaml
from pydantic import ValidationError

from .commercial.models import CommercialDeal
from .models import Deal

MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """You are an institutional acquisitions analyst extracting an underwriting model input from an Offering Memorandum (OM).

OUTPUT CONTRACT
Return ONLY a single JSON object inside one ```json fence, matching the Deal schema below. No prose outside the fence.

EXTRACTION RULES
1. Use broker-stated numbers verbatim where given (rents, unit counts, SF, T-12 OpEx, price guidance).
2. For fields the OM does not state, use `null`. NEVER hallucinate. Common nulls in an OM: exit_cap, exit hold_yrs, rent_growth assumptions, debt rate/terms (unless assumable financing is offered), promote/pref structure.
3. If price is given as a guidance range, use the midpoint and add "_extraction_notes" listing the range.
4. For unit_mix: collapse the rent roll into floorplan groups (e.g., "1BR/1BA", "2BR/2BA"). `in_place_rent` = current avg in-place rent. `market_rent` = pro-forma / market rent. If only one is given, set the other to the same value and note it.
5. For OpEx: use T-12 actuals if shown, otherwise broker pro-forma. All per-unit fields are ANNUAL $ per unit.
6. close_date: use today (analyst assumption) if not stated.
7. deal_id: snake_case from property name (e.g., "lattice_apartments"). deal_name: title case.

DEAL JSON SCHEMA (Pydantic v2 — types are strict)

{
  "deal_id": "string (snake_case)",
  "deal_name": "string",
  "sponsor": "string (default 'Acquirer')",
  "property": {
    "name": "string",
    "address": "string",
    "submarket": "string (e.g., 'Phoenix Metro')",
    "year_built": "int",
    "asset_class": "multifamily",
    "unit_mix": [
      {"name": "1BR/1BA", "count": "int>0", "sf": "int>0", "in_place_rent": "float>0 (monthly $)", "market_rent": "float>0 (monthly $)"}
    ]
  },
  "acquisition": {
    "purchase_price": "float>0",
    "closing_costs_pct": "float 0-0.05 (decimal; default 0.015 = 1.5%)",
    "initial_capex": "float>=0 (day-1 capex separate from value-add)",
    "day_one_reserves": "float>=0",
    "close_date": "YYYY-MM-DD"
  },
  "revenue": {
    "other_income_per_unit_mo": "float>=0 (parking/storage/RUBS monthly $/unit)",
    "rent_growth": "list[float] of length >= hold_yrs+1 (e.g., [0.04, 0.035, 0.03, 0.03, 0.03, 0.03])",
    "other_income_growth": "float (default 0.03)",
    "vacancy": "float 0-0.5 (default 0.05)",
    "bad_debt": "float 0-0.05 (default 0.01)",
    "concessions_yr1": "float 0-0.10 (default 0)"
  },
  "opex": {
    "payroll_per_unit": "float>=0 ANNUAL $/unit",
    "rm_per_unit": "float>=0",
    "marketing_per_unit": "float>=0",
    "utilities_per_unit": "float>=0 (net of recoveries)",
    "insurance_per_unit": "float>=0",
    "other_per_unit": "float>=0",
    "re_tax": "float>=0 ANNUAL TOTAL $",
    "re_tax_growth": "float (default 0.03)",
    "growth": "float (default 0.03)",
    "mgmt_fee_pct": "float 0-0.10 (default 0.03)"
  },
  "capex": {
    "value_add_per_unit": "float>=0 (interior reno $/unit)",
    "units_renovated_pct": "list[float] summing to ~1.0, by year (e.g., [0.4, 0.4, 0.2])",
    "rent_premium_per_unit_mo": "float>=0 (monthly $ uplift on renovated units)",
    "common_area_capex": "float>=0 (one-time)",
    "recurring_reserve_per_unit": "float>=0 (default 300 $/unit/yr)"
  },
  "debt": {
    "rate": "float 0-0.30 decimal (0.065 = 6.5%)",
    "term_yrs": "int>0 (default 10)",
    "amort_yrs": "int>=0 (0 = full IO; default 30)",
    "io_period_yrs": "int>=0 (default 0)",
    "max_ltv": "float 0-0.85 (default 0.65)",
    "min_dscr": "float 1.0-2.0 (default 1.25)",
    "min_debt_yield": "float 0-0.20 (default 0.08)",
    "origination_fee_pct": "float 0-0.03 (default 0.01)",
    "lender_reserves": "float>=0"
  },
  "equity": {
    "pref_rate": "float 0-0.20 (default 0.08)",
    "promote_pct": "float 0-0.50 (default 0.20)",
    "gp_coinvest_pct": "float 0-1.0 (default 0.10)",
    "acq_fee_pct": "float 0-0.03 (default 0)"
  },
  "exit": {
    "hold_yrs": "int 1-15 (default 5)",
    "exit_cap": "float 0-0.20 decimal (e.g., 0.055 = 5.5%)",
    "cost_of_sale_pct": "float 0-0.05 (default 0.015)",
    "exit_noi_basis": "trailing | forward (default forward)"
  },
  "_extraction_notes": {
    "field_path": "what was missing/assumed/ranged",
    "...": "..."
  }
}

GUIDANCE FOR ANALYST-ASSUMED FIELDS (fill with reasonable institutional defaults if absent):
- exit.exit_cap: use going-in cap + 50bps as default; if no going-in cap shown, use null.
- revenue.rent_growth: if not in OM, use [0.04, 0.035, 0.03, 0.03, 0.03, 0.03] (6 years).
- debt: if no financing assumptions in OM, use the schema defaults but flag in _extraction_notes.
- exit.hold_yrs: default 5.
- equity: use defaults unless OM states otherwise.

Sum check: capex.units_renovated_pct MUST sum to exactly 1.0 (e.g., [0.5, 0.5] or [0.4, 0.4, 0.2]).
revenue.rent_growth MUST have at least exit.hold_yrs + 1 entries (forward exit NOI needs Year hold+1).
"""


_COMMERCIAL_SYSTEM_PROMPT = """You are an institutional acquisitions analyst extracting an underwriting model input from a commercial real estate Offering Memorandum (OM) -- office, industrial, or retail.

OUTPUT CONTRACT
Return ONLY a single JSON object inside one ```json fence, matching the CommercialDeal schema below. No prose outside the fence.

EXTRACTION RULES
1. Use broker-stated numbers verbatim where given (rent roll, T-12 OpEx, price guidance, market rent).
2. For fields the OM does not state, use `null`. NEVER hallucinate. Common nulls: exit_cap, hold_yrs, debt terms, market growth assumptions, percentage rent.
3. property.asset_class MUST be one of: office, industrial, retail.
4. rent_roll: extract EVERY tenant in the rent roll / stacking plan. Each row must have tenant, sf, base_rent_psf (ANNUAL $/SF), lease_type (NNN/BYS/gross), lease_start, lease_end, escalation_pct.
5. If escalations are unstated, use 0.025 for office, 0.035 for industrial, 0.02 for retail.
6. lease_type: triple-net -> "NNN"; modified gross / base-year stop -> "BYS"; full-service gross -> "gross".
7. close_date: use today (analyst assumption) if not stated.
8. Market re-leasing assumptions (renewal_prob, downtime, TI, LC, free rent, new lease term): if not in OM, use institutional defaults appropriate to asset class -- but flag in _extraction_notes.
9. deal_id: snake_case from property name. deal_name: title case.
10. percentage rent (retail): only populate pct_rent_rate and sales_psf if the OM explicitly references percentage rent terms.

COMMERCIAL DEAL JSON SCHEMA

{
  "deal_id": "string (snake_case)",
  "deal_name": "string",
  "sponsor": "string (default 'Acquirer')",
  "property": {
    "name": "string",
    "address": "string",
    "submarket": "string",
    "year_built": "int",
    "asset_class": "office | industrial | retail",
    "total_rba": "int>0 (rentable building area, SF)",
    "general_vacancy_pct": "float 0-0.30 (default 0.05; 0.02-0.03 for credit-tenant industrial)",
    "rent_roll": [
      {
        "tenant": "string",
        "suite": "string or null",
        "sf": "int>0",
        "base_rent_psf": "float>0 (ANNUAL $/SF)",
        "lease_type": "NNN | BYS | gross",
        "lease_start": "YYYY-MM-DD",
        "lease_end": "YYYY-MM-DD",
        "escalation_pct": "float 0-0.15 (e.g., 0.025 = 2.5%/yr)",
        "free_rent_remaining_mo": "int>=0 (default 0)",
        "pct_rent_rate": "float 0-0.20 or null (retail only; e.g., 0.06)",
        "sales_psf": "float>=0 or null (retail only; projected sales $/SF)"
      }
    ]
  },
  "acquisition": {
    "purchase_price": "float>0",
    "closing_costs_pct": "float 0-0.05 (default 0.015)",
    "initial_capex": "float>=0",
    "day_one_reserves": "float>=0",
    "close_date": "YYYY-MM-DD"
  },
  "market": {
    "market_rent_psf": "float>0 (ANNUAL $/SF)",
    "market_rent_growth": "float (default 0.03)",
    "new_lease_term_yrs": "int 1-20 (default: office 7, industrial 10, retail 7)",
    "new_escalation_pct": "float 0-0.15",
    "new_free_rent_mo": "int 0-24",
    "new_ti_psf": "float>=0",
    "new_lc_pct": "float 0-0.15 (typically 0.05-0.06)",
    "downtime_mo": "int 0-36 (typical 6-12 months)",
    "renewal_lease_term_yrs": "int 1-20",
    "renewal_escalation_pct": "float 0-0.15",
    "renewal_free_rent_mo": "int 0-12",
    "renewal_ti_psf": "float>=0",
    "renewal_lc_pct": "float 0-0.10",
    "renewal_prob": "float 0-1 (default 0.65 office, 0.75 industrial credit, 0.70 retail)",
    "sales_growth": "float (default 0.025; retail only — escalator on tenant sales)"
  },
  "opex": {
    "cam_psf": "float>=0 (ANNUAL $/SF, recoverable)",
    "re_tax": "float>=0 (ANNUAL TOTAL $)",
    "insurance_psf": "float>=0",
    "utilities_psf": "float>=0 (common-area recoverable)",
    "non_recoverable_psf": "float>=0",
    "mgmt_fee_pct": "float 0-0.10 (default 0.03; retail 0.04)",
    "cam_growth": "float (default 0.03)",
    "re_tax_growth": "float (default 0.03)",
    "insurance_growth": "float (default 0.04)",
    "utilities_growth": "float (default 0.03)",
    "non_recoverable_growth": "float (default 0.03)"
  },
  "capex": {
    "initial_building_capex": "float>=0",
    "recurring_reserve_psf": "float>=0 (default 0.20; industrial 0.08)"
  },
  "debt": {
    "rate": "float 0-0.30",
    "term_yrs": "int>0 (default 10)",
    "amort_yrs": "int>=0 (0 = full IO; default 30)",
    "io_period_yrs": "int>=0",
    "max_ltv": "float 0-0.85 (default 0.60 commercial)",
    "min_dscr": "float 1.0-2.0 (default 1.30)",
    "min_debt_yield": "float 0-0.20 (default 0.08)",
    "origination_fee_pct": "float 0-0.03 (default 0.01)",
    "lender_reserves": "float>=0"
  },
  "equity": {
    "pref_rate": "float 0-0.20 (default 0.08)",
    "promote_pct": "float 0-0.50 (default 0.20)",
    "gp_coinvest_pct": "float 0-1.0 (default 0.10)",
    "acq_fee_pct": "float 0-0.03 (default 0)"
  },
  "exit": {
    "hold_yrs": "int 1-15 (default 5)",
    "exit_cap": "float 0-0.20 (going-in + 25-50 bps if unstated)",
    "cost_of_sale_pct": "float 0-0.05 (default 0.015)",
    "exit_noi_basis": "trailing | forward (default forward)"
  },
  "_extraction_notes": {"field_path": "what was missing/assumed"}
}
"""


def _encode_pdf(pdf_path: Path) -> str:
    with pdf_path.open("rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _strip_json_fence(text: str) -> str:
    """Extract JSON from a ```json ... ``` fenced block, falling back to first {...} block."""
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    if obj:
        return obj.group(0)
    raise ValueError("No JSON object found in model response")


def extract_om_raw(
    pdf_path: Path,
    client: anthropic.Anthropic | None = None,
    deal_type: str = "multifamily",
) -> tuple[dict, dict]:
    """
    Run extraction on a PDF and return the raw extracted dict + notes (no validation).

    deal_type: 'multifamily' or 'commercial'.
    Returns (raw_json_dict, extraction_notes).
    """
    if client is None:
        client = anthropic.Anthropic()

    pdf_b64 = _encode_pdf(pdf_path)
    prompt = _COMMERCIAL_SYSTEM_PROMPT if deal_type == "commercial" else _SYSTEM_PROMPT

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract the CommercialDeal JSON from this Offering Memorandum. Return ONLY the fenced JSON block."
                            if deal_type == "commercial"
                            else "Extract the Deal JSON from this Offering Memorandum. Return ONLY the fenced JSON block."
                        ),
                    },
                ],
            }
        ],
    )

    text = next(b.text for b in response.content if b.type == "text")
    raw_json = json.loads(_strip_json_fence(text))
    notes = raw_json.pop("_extraction_notes", None) or {}
    return raw_json, notes


def validate_deal(raw_json: dict, deal_type: str = "multifamily") -> Deal | CommercialDeal:
    """Validate an extracted JSON dict against the appropriate schema."""
    if deal_type == "commercial":
        return CommercialDeal.model_validate(raw_json)
    return Deal.model_validate(raw_json)


def extract_om(pdf_path: Path, client: anthropic.Anthropic | None = None,
               deal_type: str = "multifamily") -> tuple[Deal | CommercialDeal, dict, dict]:
    """Run extraction and validate. Raises ValidationError on bad schema."""
    raw, notes = extract_om_raw(pdf_path, client, deal_type=deal_type)
    return validate_deal(raw, deal_type), raw, notes


def deal_to_yaml(deal: Deal | CommercialDeal, notes: dict | None = None) -> str:
    """Serialize a validated Deal back to YAML, with extraction notes as a leading comment block."""
    body = yaml.safe_dump(
        deal.model_dump(mode="json"),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not notes:
        return body
    header = "# Extraction notes (analyst assumptions / OM gaps):\n"
    for k, v in notes.items():
        header += f"#   {k}: {v}\n"
    header += "#\n"
    return header + body
