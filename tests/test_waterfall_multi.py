"""Tests for scripts/underwriting/waterfall_multi.py.

Hand-derived expected values are computed inline. The algorithm is an
IRR-hurdle multi-tier American waterfall; the canonical case is verified
by tracing tier balances through one full equity contribution + sale.
"""

from datetime import date
import unittest

from scripts.underwriting.waterfall_multi import (
    Tier,
    legacy_tiers,
    run_multi_tier_waterfall,
)


class TestSingleTierResidual(unittest.TestCase):
    """One residual tier — everything splits at promote_pct."""

    def test_single_residual_tier_splits_residual(self):
        tiers = [Tier(hurdle_irr=0.0, promote_pct=0.20, label="Residual")]
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2031, 1, 1),  2_000_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        # 100% of distribution flows to residual: LP gets 80%, GP gets 20%.
        self.assertAlmostEqual(r.lp.distributed, 1_600_000.0, places=0)
        self.assertAlmostEqual(r.gp.distributed, 400_000.0, places=0)


class TestPrefThenResidual(unittest.TestCase):
    """Standard 2-tier: 100%-to-LP pref then 80/20 residual."""

    def test_pref_at_8pct_exact(self):
        # Contribute $1M at Yr 0, sell at Yr 1 (365 days) for $1.20M.
        # Pref tier accrual: $1M * 1.08 = $1.08M (balance after Yr 1).
        # Distribution $1.2M: $1.08M to LP via Tier 0 (100%);
        #   remaining $0.12M to residual: $0.096M LP, $0.024M GP.
        # LP total = $1.176M; GP = $0.024M.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2027, 1, 1),  1_200_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        self.assertAlmostEqual(r.lp.distributed, 1_176_000.0, places=0)
        self.assertAlmostEqual(r.gp.distributed,    24_000.0, places=0)

    def test_distribution_below_pref_pays_zero_promote(self):
        # Distribution exactly equal to pref balance → all to LP, no carry.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2027, 1, 1),  1_080_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        self.assertAlmostEqual(r.lp.distributed, 1_080_000.0, places=0)
        self.assertAlmostEqual(r.gp.distributed,         0.0, places=0)

    def test_no_distribution_at_all_raises(self):
        # Only a contribution → project IRR can't be computed (the vendored
        # xirr requires both signs). The engine surfaces the underlying error.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [(date(2026, 1, 1), -1_000_000.0)]
        with self.assertRaises(ValueError):
            run_multi_tier_waterfall(flows, tiers)


class TestThreeTier(unittest.TestCase):
    """Three-tier: pref at 8%, hurdle II at 15%, residual at 30% promote."""

    def test_three_tier_hand_calc(self):
        # Setup: -$1M at Yr 0, +$3M at Yr 1.
        # After 1 year:
        #   balance[0] (pref @ 8%)    = $1,080,000
        #   balance[1] (hurdle @ 15%) = $1,150,000
        # Distribute $3M:
        #   Tier 0 (promote 0): gross_cap = $1,080,000 / 1.0 = $1,080,000.
        #     Pay $1.08M → LP $1.08M, GP $0. All balances drop by $1.08M.
        #     balance[0]=0, balance[1]=$70,000. Remaining = $1,920,000.
        #   Tier 1 (promote 0.20): gross_cap = $70,000 / 0.8 = $87,500.
        #     Pay $87,500 → LP $70,000, GP $17,500. All balances drop by $70k.
        #     balance[0]=0, balance[1]=0. Remaining = $1,832,500.
        #   Residual (promote 0.30): $1,832,500 splits 70/30
        #     → LP $1,282,750, GP $549,750.
        # Total LP = $1,080,000 + $70,000 + $1,282,750 = $2,432,750.
        # Total GP = $17,500 + $549,750 = $567,250.
        # Sum = $3,000,000 ✓.
        tiers = [
            Tier(hurdle_irr=0.08, promote_pct=0.0,  label="Pref"),
            Tier(hurdle_irr=0.15, promote_pct=0.20, label="Hurdle II"),
            Tier(hurdle_irr=0.0,  promote_pct=0.30, label="Residual"),
        ]
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2027, 1, 1),  3_000_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        self.assertAlmostEqual(r.lp.distributed, 2_432_750.0, places=0)
        self.assertAlmostEqual(r.gp.distributed,   567_250.0, places=0)

        # Per-tier breakdown should match.
        per = {t.label: t for t in r.per_tier}
        self.assertAlmostEqual(per["Pref"].lp_total,      1_080_000.0, places=0)
        self.assertAlmostEqual(per["Pref"].gp_total,              0.0, places=0)
        self.assertAlmostEqual(per["Hurdle II"].lp_total,    70_000.0, places=0)
        self.assertAlmostEqual(per["Hurdle II"].gp_total,    17_500.0, places=0)
        self.assertAlmostEqual(per["Residual"].lp_total,  1_282_750.0, places=0)
        self.assertAlmostEqual(per["Residual"].gp_total,    549_750.0, places=0)


class TestBalanceAccrual(unittest.TestCase):

    def test_multi_year_accrual_compounds_at_tier_rate(self):
        # No distribution for 5 years → balance compounds at 8%.
        # Then distribute exactly the accrued balance: LP gets all, GP zero.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2031, 1, 1),  1_000_000.0 * (1.08 ** 5)),   # = $1,469,328.08
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        # Within rounding: LP gets the full distribution; GP gets nothing.
        self.assertAlmostEqual(r.lp.distributed,
                               1_000_000.0 * (1.08 ** 5), places=0)
        self.assertAlmostEqual(r.gp.distributed, 0.0, delta=1.0)

    def test_contribution_in_middle_grows_all_balances(self):
        # -$1M at Yr 0, -$0.5M at Yr 1, +$3M at Yr 5.
        # Tier 0 (pref 8%) balance evolution:
        #   Yr 0: $1.0M
        #   Yr 1: $1.08M + $0.5M = $1.58M
        #   Yr 5: $1.58M * 1.08^4 = $2,149,486
        # Total LP should at minimum receive ≥ that balance.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2027, 1, 1),   -500_000.0),
            (date(2031, 1, 1),  3_000_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers)
        # Pref tier alone should be ~$2.149M; LP gets that + 80% of residual.
        per = {t.label: t for t in r.per_tier}
        self.assertGreater(per["Preferred Return"].lp_total, 2_140_000)
        self.assertLess(   per["Preferred Return"].lp_total, 2_160_000)


class TestGPCoinvest(unittest.TestCase):

    def test_coinvest_splits_contribution_pari_passu(self):
        # 10% GP coinvest → GP funds 10% of equity check.
        tiers = legacy_tiers(pref_rate=0.08, promote_pct=0.20)
        flows = [
            (date(2026, 1, 1), -1_000_000.0),
            (date(2027, 1, 1),  1_200_000.0),
        ]
        r = run_multi_tier_waterfall(flows, tiers, gp_coinvest_pct=0.10)

        # GP contributes 10% → $100k negative flow.
        self.assertAlmostEqual(r.gp.contributed, 100_000.0, places=0)
        self.assertAlmostEqual(r.lp.contributed, 900_000.0, places=0)

        # LP-tier cash ($1,176k total LP from prior single-LP test) splits pari-passu:
        # LP fund gets 90% = $1,058,400; GP coinvest gets 10% = $117,600.
        # GP also gets its $24k promote → total GP = $141,600.
        self.assertAlmostEqual(r.lp.distributed, 1_058_400.0, places=0)
        self.assertAlmostEqual(r.gp.distributed,   141_600.0, places=0)


class TestValidation(unittest.TestCase):

    def test_empty_tiers_raises(self):
        with self.assertRaises(ValueError):
            run_multi_tier_waterfall([(date(2026, 1, 1), -1.0)], tiers=[])

    def test_empty_flows_raises(self):
        with self.assertRaises(ValueError):
            run_multi_tier_waterfall([], tiers=legacy_tiers(0.08, 0.20))

    def test_gp_coinvest_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            run_multi_tier_waterfall(
                [(date(2026, 1, 1), -1.0), (date(2027, 1, 1), 2.0)],
                tiers=legacy_tiers(0.08, 0.20),
                gp_coinvest_pct=1.5,
            )


class TestLegacyTiers(unittest.TestCase):

    def test_legacy_tiers_produces_two_tier_list(self):
        tiers = legacy_tiers(pref_rate=0.07, promote_pct=0.25)
        self.assertEqual(len(tiers), 2)
        self.assertEqual(tiers[0].hurdle_irr, 0.07)
        self.assertEqual(tiers[0].promote_pct, 0.0)
        self.assertEqual(tiers[1].promote_pct, 0.25)


if __name__ == "__main__":
    unittest.main()
