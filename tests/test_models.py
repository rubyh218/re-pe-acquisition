"""Tests for scripts/underwriting/models.py — the multifamily Deal schema.

The pydantic schema is the contract between data ingestion and the engine.
These tests pin the validators (rent_growth length, units_renovated sum,
asset_class literal, ranges).
"""

from datetime import date
import unittest

from pydantic import ValidationError

from scripts.underwriting.models import (
    Acquisition, CapEx, Debt, Deal, Equity, Exit, OpEx, Property, Revenue, UnitType,
    WaterfallTier,
)


def _minimal_deal(**overrides):
    base = dict(
        deal_id="t-1", deal_name="Test", sponsor="Test",
        property=Property(
            name="X", address="1 X St", submarket="Test", year_built=2020,
            unit_mix=[UnitType(name="1BR", count=100, sf=700,
                               in_place_rent=1500, market_rent=1600)],
        ),
        acquisition=Acquisition(purchase_price=10_000_000, close_date=date(2026, 1, 1)),
        revenue=Revenue(rent_growth=[0.03, 0.03, 0.03, 0.03, 0.03, 0.03]),
        opex=OpEx(payroll_per_unit=500, rm_per_unit=300, marketing_per_unit=100,
                  utilities_per_unit=400, insurance_per_unit=300, re_tax=200_000),
        capex=CapEx(),
        debt=Debt(rate=0.065),
        equity=Equity(),
        exit=Exit(exit_cap=0.06),
    )
    base.update(overrides)
    return Deal(**base)


class TestPropertyDerivedProperties(unittest.TestCase):

    def test_unit_count_sums_unit_mix(self):
        p = Property(
            name="X", address="1 X St", submarket="Test", year_built=2020,
            unit_mix=[
                UnitType(name="1BR", count=80, sf=700, in_place_rent=1500, market_rent=1600),
                UnitType(name="2BR", count=20, sf=1000, in_place_rent=2000, market_rent=2200),
            ],
        )
        self.assertEqual(p.unit_count, 100)
        self.assertEqual(p.total_sf, 80 * 700 + 20 * 1000)

    def test_gpr_in_place_vs_market(self):
        p = Property(
            name="X", address="1 X St", submarket="Test", year_built=2020,
            unit_mix=[UnitType(name="1BR", count=100, sf=700,
                               in_place_rent=1500, market_rent=1600)],
        )
        # GPR annualized: rent * count * 12.
        self.assertEqual(p.gpr_in_place, 1500 * 100 * 12)
        self.assertEqual(p.gpr_market,   1600 * 100 * 12)


class TestRentGrowthLengthValidator(unittest.TestCase):

    def test_rent_growth_must_cover_hold_plus_forward_year(self):
        # 5-yr hold with forward exit → needs 6 rent_growth entries.
        with self.assertRaises(ValidationError):
            _minimal_deal(
                revenue=Revenue(rent_growth=[0.03] * 5),  # only 5; need 6
                exit=Exit(exit_cap=0.06, hold_yrs=5, exit_noi_basis="forward"),
            )

    def test_rent_growth_exact_length_passes(self):
        d = _minimal_deal(
            revenue=Revenue(rent_growth=[0.03] * 6),
            exit=Exit(exit_cap=0.06, hold_yrs=5, exit_noi_basis="forward"),
        )
        self.assertEqual(len(d.revenue.rent_growth), 6)

    def test_trailing_exit_basis_needs_one_fewer_year(self):
        # Trailing exit on 5-yr hold → only 5 rent_growth entries needed.
        d = _minimal_deal(
            revenue=Revenue(rent_growth=[0.03] * 5),
            exit=Exit(exit_cap=0.06, hold_yrs=5, exit_noi_basis="trailing"),
        )
        self.assertEqual(d.exit.exit_noi_basis, "trailing")


class TestCapExValidators(unittest.TestCase):

    def test_units_renovated_pct_must_sum_to_one(self):
        with self.assertRaises(ValidationError):
            CapEx(value_add_per_unit=10000,
                  units_renovated_pct=[0.40, 0.30, 0.20])   # sums to 0.90

    def test_units_renovated_required_when_value_add_per_unit_positive(self):
        with self.assertRaises(ValidationError):
            CapEx(value_add_per_unit=10000)   # missing units_renovated_pct

    def test_units_renovated_pct_within_tolerance(self):
        # Sum 0.999 within 1% tolerance.
        c = CapEx(value_add_per_unit=10000, units_renovated_pct=[0.40, 0.40, 0.199])
        self.assertIsNotNone(c)


class TestDebtRanges(unittest.TestCase):

    def test_rate_must_be_positive_and_below_30pct(self):
        with self.assertRaises(ValidationError):
            Debt(rate=0)
        with self.assertRaises(ValidationError):
            Debt(rate=0.30)

    def test_max_ltv_caps_at_85pct(self):
        # 86% should fail.
        with self.assertRaises(ValidationError):
            Debt(rate=0.065, max_ltv=0.86)

    def test_min_dscr_caps_at_2x(self):
        with self.assertRaises(ValidationError):
            Debt(rate=0.065, min_dscr=2.1)


class TestEquityWaterfallResolution(unittest.TestCase):

    def test_legacy_pref_promote_resolves_to_2_tier_list(self):
        e = Equity(pref_rate=0.08, promote_pct=0.20)
        tiers = e.waterfall_tiers
        self.assertEqual(len(tiers), 2)
        self.assertEqual(tiers[0].hurdle_irr, 0.08)
        self.assertEqual(tiers[0].promote_pct, 0.0)
        self.assertEqual(tiers[1].promote_pct, 0.20)

    def test_explicit_tiers_override_legacy_fields(self):
        e = Equity(
            pref_rate=0.08, promote_pct=0.20,
            tiers=[
                WaterfallTier(hurdle_irr=0.10, promote_pct=0.0, label="Pref10"),
                WaterfallTier(hurdle_irr=0.20, promote_pct=0.20, label="II"),
                WaterfallTier(hurdle_irr=0.0,  promote_pct=0.40, label="Residual"),
            ],
        )
        tiers = e.waterfall_tiers
        self.assertEqual(len(tiers), 3)
        self.assertEqual(tiers[0].label, "Pref10")


class TestImmutability(unittest.TestCase):

    def test_deal_is_frozen(self):
        d = _minimal_deal()
        with self.assertRaises(ValidationError):
            d.deal_name = "Mutated"  # type: ignore


if __name__ == "__main__":
    unittest.main()
