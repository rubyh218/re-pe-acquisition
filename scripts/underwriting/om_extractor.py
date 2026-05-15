"""
om_extractor.py — Extract a Deal YAML from an Offering Memorandum PDF.

Sends the OM PDF natively to Claude Sonnet 4.6, asks for JSON matching the
target Deal schema (chosen by asset class), validates via pydantic's
model_validate, writes to YAML.

Fields not present in the OM are filled with `null` (and a TODO comment in
the output YAML) rather than hallucinated. Broker-stated numbers are
preserved verbatim; analyst assumptions (exit cap, growth, debt terms when
not financed deals, etc.) are flagged as TODO.

DEAL TYPE DISPATCH
------------------
The `deal_type` parameter selects:
  - The pydantic schema used for validation
  - The asset-class extraction guidance baked into the system prompt
  - Which JSON Schema is injected for the model to follow

Supported deal_type values:
  multifamily               -> Deal              (top-level Deal)
  commercial                -> CommercialDeal    (office/industrial/retail)
  hospitality               -> HotelDeal
  datacenter_wholesale      -> DCWholesaleDeal
  datacenter_colo           -> DCColoDeal
  infrastructure            -> InfrastructureDeal

The schema is generated from the pydantic model via `model_json_schema()`
so prompt content never drifts from the actual Deal class fields.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import anthropic
import yaml

from .commercial.models import CommercialDeal
from .datacenter.models import DCColoDeal, DCWholesaleDeal
from .hospitality.models import HotelDeal
from .infrastructure.models import InfrastructureDeal
from .models import Deal

MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Deal-type registry
# ---------------------------------------------------------------------------

# Maps the CLI / API deal_type string to the pydantic Deal class.
_DEAL_TYPES: dict[str, type] = {
    "multifamily":          Deal,
    "commercial":           CommercialDeal,
    "hospitality":          HotelDeal,
    "datacenter_wholesale": DCWholesaleDeal,
    "datacenter_colo":      DCColoDeal,
    "infrastructure":       InfrastructureDeal,
}


def supported_deal_types() -> list[str]:
    """Return the deal types the extractor supports."""
    return list(_DEAL_TYPES.keys())


def _deal_class(deal_type: str) -> type:
    if deal_type not in _DEAL_TYPES:
        raise ValueError(
            f"unsupported deal_type {deal_type!r}; "
            f"choose from {sorted(_DEAL_TYPES)}"
        )
    return _DEAL_TYPES[deal_type]


# ---------------------------------------------------------------------------
# Asset-class-specific extraction guidance
# ---------------------------------------------------------------------------
# These are short paragraphs giving the LLM domain-specific conventions for
# each engine. The bulk of the schema content comes from `model_json_schema()`
# (see _build_system_prompt below).

_ASSET_CLASS_GUIDANCE: dict[str, str] = {
    "multifamily": """\
MULTIFAMILY GUIDANCE
- unit_mix: collapse the rent roll into floorplan groups (e.g., "1BR/1BA"). `in_place_rent` = current
  avg in-place; `market_rent` = pro-forma / market. If only one is given, set the other equal and note.
- OpEx per-unit fields are ANNUAL $ per unit.
- revenue.rent_growth: if not in OM, use [0.04, 0.035, 0.03, 0.03, 0.03, 0.03] (6 years).
- exit.exit_cap: going-in + 25-50 bps if unstated.
- capex.units_renovated_pct MUST sum to ~1.0. revenue.rent_growth MUST have >= exit.hold_yrs + 1 entries.
""",
    "commercial": """\
COMMERCIAL (office / industrial / retail) GUIDANCE
- property.asset_class MUST be one of: office, industrial, retail.
- rent_roll: extract EVERY tenant. Each row: tenant, sf, base_rent_psf (ANNUAL $/SF), lease_type
  (NNN/BYS/gross), lease_start, lease_end, escalation_pct.
- lease_type: triple-net -> "NNN"; modified gross / base-year stop -> "BYS"; full-service gross -> "gross".
- Default escalations if unstated: office 2.5%, industrial 3.5%, retail 2.0%.
- percentage rent (retail): only populate pct_rent_rate and sales_psf when the OM explicitly references them.
""",
    "hospitality": """\
HOSPITALITY (HOTEL) GUIDANCE
- property.keys: total inventory of room keys.
- brand / flag_type: e.g., "Hampton Inn" / "franchised". service_level one of: economy / midscale /
  upper_midscale / upscale / upper_upscale / luxury.
- operating.adr_yr1: Year-1 ADR in dollars. operating.occupancy: list of decimals (e.g., [0.65, 0.70, ...]),
  length >= hold_yrs+1.
- USALI structure: rooms_expense_pct of rooms revenue, fb_margin / other_margin as decimal margins.
- pip_total + pip_displacement_keys + pip_schedule_pct describe the brand-mandated capex program.
- opex.ffe_reserve_pct: typically 0.04-0.05 of total revenue.
""",
    "datacenter_wholesale": """\
DATACENTER (WHOLESALE) GUIDANCE
- property.mw_critical + mw_commissioned: total designed and currently-powered MW.
- property.tier_rating: "Tier I" / "Tier II" / "Tier III" / "Tier IV" (Uptime Institute).
- contracts: extract EVERY executed wholesale lease. base_rent_kw_mo is $/kW/month on contracted MW.
- power_pass_through: "full" / "partial" / "none". OpEx per-MW fields scale on mw_critical.
- pue: power usage effectiveness (1.3-1.6 typical, default 1.40).
""",
    "datacenter_colo": """\
DATACENTER (COLOCATION) GUIDANCE
- property.cabinet_mix: rows of named cabinet products (count, kw_per_cabinet, in_place_mrr,
  market_mrr — monthly $/cabinet).
- xc_per_cabinet: cross-connect count per occupied cabinet. xc_mrr_each: monthly $/xc.
- contracted_kw: aggregate utility-billed kW basis for power cost.
- opex.pue_uplift: typically 1.3-1.6.
""",
    "infrastructure": """\
INFRASTRUCTURE (SOLAR / WIND / BESS) GUIDANCE
- property.generation: nameplate_mw_ac, capacity_factor (0-1), degradation_pct/yr, curtailment_pct,
  availability_pct, gross_annual_generation_mwh_yr1.
- revenue_streams: list of PPA / availability / merchant streams. Each carries counterparty (rating
  optional), term dates, escalation, and stream-specific fields (PPA: price_mwh; availability:
  annual_payment + capacity_mw + capacity_payment_mw_mo; merchant: price_curve_mwh + terminal_growth).
- tax_credits: itc_pct of qualified basis (Yr 1 cash) AND/OR ptc_per_mwh + ptc_term_yrs (annual credit on
  net generation). Most projects use ONE — flag if both are claimed.
- OpEx is fixed-on-nameplate (fixed_om, insurance, prop_tax, land_lease) + variable on net generation
  (variable_om).
- Augmentation capex (BESS swaps, inverter replacement, blade refurb) is LUMPY by year.
""",
}


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

_BASE_RULES = """You are an institutional acquisitions analyst extracting an underwriting model input from an Offering Memorandum (OM).

OUTPUT CONTRACT
Return ONLY a single JSON object inside one ```json fence, matching the Deal schema provided below. No prose outside the fence.

UNIVERSAL EXTRACTION RULES
1. Use broker-stated numbers verbatim (rents, unit counts, SF, T-12 OpEx, price guidance, lease terms).
2. For fields the OM does not state, use `null`. NEVER hallucinate. Common nulls: exit_cap, hold_yrs,
   rent / market growth assumptions, debt rate / terms (unless assumable financing is offered),
   promote / pref structure.
3. If price is given as a guidance range, use the midpoint and add "_extraction_notes" listing the range.
4. close_date: use today's date if not stated in the OM.
5. deal_id: snake_case from property name (e.g., "lattice_apartments"). deal_name: title case.
6. Validation requirements (will fail Pydantic validation if violated):
   - All `count`, `sf`, `mw_*`, `keys`, `nameplate_mw_ac` fields must be > 0 where present.
   - Decimal percentage fields are in the range [0, 1] (e.g., 0.05 = 5%); rates are decimals.
   - List fields with `min_length` annotations must meet the minimum length.
7. Use the _extraction_notes object at the JSON root to document any analyst assumption, OM gap,
   or value-range that you collapsed. Keys are field paths (e.g., "exit.exit_cap"); values are
   short strings.

DEFAULTS FOR ANALYST-ASSUMED FIELDS
- exit.exit_cap: going-in + 25-50 bps if unstated; null if no going-in either.
- exit.hold_yrs: 5.
- exit.cost_of_sale_pct: 0.015.
- exit.exit_noi_basis: "forward".
- debt: use schema defaults if no financing in OM, but flag in _extraction_notes.
- equity: use schema defaults unless OM states otherwise.
"""


def _schema_summary(deal_class: type) -> str:
    """Return a compact, human-readable JSON Schema for the deal class.

    Strips noisy keys (`title`, `description` at top level) but keeps field
    types, defaults, and constraints — enough for the model to produce a
    valid instance.
    """
    schema = deal_class.model_json_schema()
    # Compact pretty-print so the model can parse the structure quickly.
    return json.dumps(schema, indent=2)


def _build_system_prompt(deal_type: str) -> str:
    """Assemble the full system prompt for a given deal type."""
    cls = _deal_class(deal_type)
    guidance = _ASSET_CLASS_GUIDANCE.get(deal_type, "")
    schema_json = _schema_summary(cls)
    return (
        _BASE_RULES
        + "\n"
        + guidance
        + "\nJSON SCHEMA (Pydantic v2 — types are strict)\n\n"
        + schema_json
    )


# ---------------------------------------------------------------------------
# PDF + JSON helpers
# ---------------------------------------------------------------------------

def _encode_pdf(pdf_path: Path) -> str:
    with pdf_path.open("rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _strip_json_fence(text: str) -> str:
    """Extract JSON from a ```json ... ``` fenced block, falling back to first {...}."""
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    if obj:
        return obj.group(0)
    raise ValueError("No JSON object found in model response")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_om_raw(
    pdf_path: Path,
    client: anthropic.Anthropic | None = None,
    deal_type: str = "multifamily",
) -> tuple[dict, dict]:
    """Run extraction on a PDF and return the raw extracted dict + notes (no validation).

    Returns (raw_json_dict, extraction_notes).
    """
    if client is None:
        client = anthropic.Anthropic()

    _deal_class(deal_type)   # raises on unknown deal_type
    pdf_b64 = _encode_pdf(pdf_path)
    prompt = _build_system_prompt(deal_type)

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
                            f"Extract the {deal_type} Deal JSON from this Offering Memorandum. "
                            "Return ONLY the fenced JSON block."
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


def validate_deal(raw_json: dict, deal_type: str = "multifamily") -> Any:
    """Validate an extracted JSON dict against the appropriate Deal schema.

    Returns an instance of the matching Deal class
    (Deal / CommercialDeal / HotelDeal / DCWholesaleDeal / DCColoDeal /
    InfrastructureDeal).
    """
    cls = _deal_class(deal_type)
    return cls.model_validate(raw_json)


def extract_om(
    pdf_path: Path,
    client: anthropic.Anthropic | None = None,
    deal_type: str = "multifamily",
) -> tuple[Any, dict, dict]:
    """Run extraction and validate. Raises ValidationError on bad schema."""
    raw, notes = extract_om_raw(pdf_path, client, deal_type=deal_type)
    return validate_deal(raw, deal_type), raw, notes


def deal_to_yaml(deal: Any, notes: dict | None = None) -> str:
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
