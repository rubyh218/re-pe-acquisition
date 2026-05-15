"""Tests for scripts/underwriting/metrics.py — 3-basis ROC.

Hand-derived expected values are computed inline so the assertion is
auditable from the test alone.
"""

import math
import unittest

from scripts.underwriting.metrics import compute_roc, ReturnOnCost


class TestComputeROC(unittest.TestCase):

    def test_yr1_stab_no_deflation(self):
        # stab_yr=1 → no deflation; untrended == trended.
        r = compute_roc(
            stab_noi=1_000_000,
            exit_ftm_noi=1_100_000,
            all_in_basis=20_000_000,
            stab_yr=1,
            growth_rate=0.03,
        )
        self.assertAlmostEqual(r.trended_stab, 0.05, places=6)
        self.assertAlmostEqual(r.untrended_stab, 0.05, places=6)
        self.assertAlmostEqual(r.exit_ftm, 1_100_000 / 20_000_000, places=6)

    def test_yr3_stab_with_3pct_growth(self):
        # stab_yr=3 with 3% growth: deflate factor = 1.03^2 = 1.0609.
        stab_noi = 1_060_900   # explicitly trended for 2 years at 3%
        r = compute_roc(
            stab_noi=stab_noi,
            exit_ftm_noi=1_200_000,
            all_in_basis=20_000_000,
            stab_yr=3,
            growth_rate=0.03,
        )
        # Untrended = stab / 1.0609 = 1,000,000 → 5.0% on $20M.
        self.assertAlmostEqual(r.untrended_stab, 0.05, places=4)
        # Trended = stab as-is.
        self.assertAlmostEqual(r.trended_stab, stab_noi / 20_000_000, places=6)

    def test_zero_growth_rate_no_deflation(self):
        # growth_rate=0 → deflate = 1.0^N = 1.0 → untrended == trended.
        r = compute_roc(
            stab_noi=1_000_000, exit_ftm_noi=1_000_000,
            all_in_basis=20_000_000, stab_yr=5, growth_rate=0.0,
        )
        self.assertAlmostEqual(r.untrended_stab, r.trended_stab, places=6)

    def test_zero_basis_raises(self):
        with self.assertRaises(ValueError):
            compute_roc(
                stab_noi=1, exit_ftm_noi=1,
                all_in_basis=0, stab_yr=1, growth_rate=0.03,
            )

    def test_negative_basis_raises(self):
        with self.assertRaises(ValueError):
            compute_roc(
                stab_noi=1, exit_ftm_noi=1,
                all_in_basis=-100, stab_yr=1, growth_rate=0.03,
            )

    def test_growth_rate_at_minus_one_doesnt_explode(self):
        # growth_rate = -1.0 would otherwise yield deflate=0. The guard falls
        # back to no deflation (deflate=1).
        r = compute_roc(
            stab_noi=1_000_000, exit_ftm_noi=1,
            all_in_basis=10_000_000, stab_yr=5, growth_rate=-1.0,
        )
        self.assertTrue(math.isfinite(r.untrended_stab))
        self.assertAlmostEqual(r.untrended_stab, r.trended_stab, places=6)

    def test_return_dataclass_carries_inputs(self):
        r = compute_roc(
            stab_noi=1_000_000, exit_ftm_noi=1_100_000,
            all_in_basis=20_000_000, stab_yr=3, growth_rate=0.025,
        )
        self.assertIsInstance(r, ReturnOnCost)
        self.assertEqual(r.stab_yr, 3)
        self.assertEqual(r.all_in_basis, 20_000_000)
        self.assertEqual(r.growth_rate, 0.025)

    def test_3pct_growth_5yr_deflation_factor(self):
        # Explicit math: stab_yr=5, growth=0.03 → deflate = 1.03^4 = 1.12551.
        # If stab NOI = 1,000,000, untrended = 1_000_000 / 1.12551 = 888,487.
        r = compute_roc(
            stab_noi=1_000_000, exit_ftm_noi=1,
            all_in_basis=10_000_000, stab_yr=5, growth_rate=0.03,
        )
        expected_untrended_noi = 1_000_000 / (1.03 ** 4)
        self.assertAlmostEqual(
            r.untrended_stab * r.all_in_basis,
            expected_untrended_noi,
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
