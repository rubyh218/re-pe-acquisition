"""Tests for the OM extractor's deal-type dispatch and schema scaffolding.

These tests DO NOT call the Anthropic API — they exercise the offline parts:
the deal-type registry, the schema-generation path, and the round-trip
validation that the extractor's validator accepts every bundled example YAML.

The actual PDF → JSON extraction is exercised in manual / integration tests
that require an ANTHROPIC_API_KEY.
"""

from pathlib import Path
import unittest

import yaml
from pydantic import ValidationError

from scripts.underwriting.om_extractor import (
    _build_system_prompt,
    _strip_json_fence,
    deal_to_yaml,
    supported_deal_types,
    validate_deal,
)


_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestSupportedDealTypes(unittest.TestCase):

    def test_all_engines_covered(self):
        types = supported_deal_types()
        # Five asset classes, with datacenter split into wholesale + colo.
        self.assertEqual(
            set(types),
            {
                "multifamily", "commercial", "hospitality",
                "datacenter_wholesale", "datacenter_colo", "infrastructure",
            },
        )


class TestSystemPromptBuilder(unittest.TestCase):

    def test_each_deal_type_builds_a_nonempty_prompt_with_schema(self):
        # Every supported deal_type should produce a system prompt containing
        # both the base rules and a JSON schema block.
        for dt in supported_deal_types():
            prompt = _build_system_prompt(dt)
            self.assertIn("UNIVERSAL EXTRACTION RULES", prompt, f"{dt}: missing rules section")
            self.assertIn("JSON SCHEMA", prompt, f"{dt}: missing schema section")
            # JSON Schema starts with a `{` and contains the title of the model.
            self.assertIn("\"properties\":", prompt, f"{dt}: schema body not embedded")

    def test_unknown_deal_type_raises(self):
        with self.assertRaises(ValueError):
            _build_system_prompt("brand_new_asset_class")


class TestValidateDeal(unittest.TestCase):
    """validate_deal should accept every bundled example YAML when given the
    right deal_type. This locks in the contract that extracted JSON, once it
    matches an example shape, validates cleanly."""

    def _round_trip(self, yaml_path: str, deal_type: str):
        with (_EXAMPLES / yaml_path).open() as f:
            raw = yaml.safe_load(f)
        deal = validate_deal(raw, deal_type=deal_type)
        # The validated deal serializes back to YAML without error.
        text = deal_to_yaml(deal)
        self.assertIn("deal_id:", text)
        return deal

    def test_multifamily_example_validates(self):
        d = self._round_trip("marina-apartments.yaml", "multifamily")
        self.assertEqual(d.property.unit_count, 200)

    def test_commercial_office_validates(self):
        d = self._round_trip("example-office.yaml", "commercial")
        self.assertEqual(d.property.asset_class, "office")

    def test_commercial_industrial_validates(self):
        d = self._round_trip("example-industrial.yaml", "commercial")
        self.assertEqual(d.property.asset_class, "industrial")

    def test_commercial_retail_validates(self):
        d = self._round_trip("example-retail.yaml", "commercial")
        self.assertEqual(d.property.asset_class, "retail")

    def test_hospitality_example_validates(self):
        d = self._round_trip("example-hotel.yaml", "hospitality")
        self.assertEqual(d.property.keys, 120)

    def test_datacenter_wholesale_example_validates(self):
        d = self._round_trip("example-dc-wholesale.yaml", "datacenter_wholesale")
        self.assertGreater(d.property.mw_critical, 0)

    def test_datacenter_colo_example_validates(self):
        d = self._round_trip("example-dc-colo.yaml", "datacenter_colo")
        self.assertGreater(len(d.property.cabinet_mix), 0)

    def test_infrastructure_solar_validates(self):
        d = self._round_trip("example-solar-ppa.yaml", "infrastructure")
        self.assertGreater(d.property.generation.nameplate_mw_ac, 0)

    def test_infrastructure_wind_validates(self):
        d = self._round_trip("example-wind.yaml", "infrastructure")
        self.assertGreater(d.property.generation.nameplate_mw_ac, 0)

    def test_infrastructure_bess_validates(self):
        d = self._round_trip("example-bess.yaml", "infrastructure")
        # BESS still uses the InfrastructureDeal schema; verify it loads.
        self.assertIsNotNone(d.deal_id)

    def test_wrong_deal_type_raises(self):
        # Loading a hotel YAML as 'multifamily' must fail validation
        # (no unit_mix, presence of `keys`, etc.).
        with (_EXAMPLES / "example-hotel.yaml").open() as f:
            raw = yaml.safe_load(f)
        with self.assertRaises(ValidationError):
            validate_deal(raw, deal_type="multifamily")


class TestStripJsonFence(unittest.TestCase):

    def test_fenced_json_extracted(self):
        text = "Here is the deal:\n```json\n{\"deal_id\": \"x\"}\n```\nThanks."
        self.assertEqual(_strip_json_fence(text), '{"deal_id": "x"}')

    def test_unfenced_object_fallback(self):
        text = "No fences here: {\"deal_id\": \"y\"}"
        # The regex is greedy ({.*}), so it grabs the bare object.
        self.assertIn("deal_id", _strip_json_fence(text))

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            _strip_json_fence("Sorry, I couldn't read the PDF.")


class TestDealToYaml(unittest.TestCase):

    def test_emits_clean_yaml(self):
        with (_EXAMPLES / "marina-apartments.yaml").open() as f:
            raw = yaml.safe_load(f)
        deal = validate_deal(raw, deal_type="multifamily")
        text = deal_to_yaml(deal)
        self.assertIn("deal_id:", text)
        self.assertIn("property:", text)

    def test_extraction_notes_emit_as_header_comment(self):
        with (_EXAMPLES / "marina-apartments.yaml").open() as f:
            raw = yaml.safe_load(f)
        deal = validate_deal(raw, deal_type="multifamily")
        text = deal_to_yaml(deal, notes={"exit.exit_cap": "guidance was 5.5-6.0%, took midpoint 5.75%"})
        self.assertTrue(text.startswith("# Extraction notes"))
        self.assertIn("exit.exit_cap", text)


if __name__ == "__main__":
    unittest.main()
