"""Tests for scripts/underwriting/debt_sizing.py — sizing and amort schedule.

Sizing math is wrapped from the vendor's `debt_metrics.size_max_loan` so the
ground truth is hand-derivable from the three constraints. The amort schedule
exercise checks the structure (balance reconciles, IO vs amortizing, totals
add up) without binding to a specific compounding convention — the
implementation evolves but invariants don't.
"""

import unittest

from scripts.underwriting.debt_sizing import (
    SizingResult,
    AmortYear,
    amortization_schedule,
    size_loan,
)
from scripts.underwriting.models import Debt


def _debt(rate=0.065, term_yrs=10, amort_yrs=30, io_period_yrs=0,
          max_ltv=0.65, min_dscr=1.25, min_debt_yield=0.08,
          fixed_loan_amount=None):
    return Debt(
        rate=rate, term_yrs=term_yrs, amort_yrs=amort_yrs,
        io_period_yrs=io_period_yrs, max_ltv=max_ltv, min_dscr=min_dscr,
        min_debt_yield=min_debt_yield,
        fixed_loan_amount=fixed_loan_amount,
    )


class TestSizeLoan(unittest.TestCase):

    def test_ltv_binding_when_value_is_low_relative_to_noi(self):
        # High NOI relative to value → LTV is the most restrictive.
        r = size_loan(sizing_noi=10_000_000, purchase_price=50_000_000, debt=_debt())
        self.assertEqual(r.binding, "LTV")
        self.assertAlmostEqual(r.loan_amount, 50_000_000 * 0.65, places=0)

    def test_dscr_binding_when_rate_is_high(self):
        # At 9% rate, DSCR pinches before LTV.
        r = size_loan(sizing_noi=2_000_000, purchase_price=40_000_000,
                     debt=_debt(rate=0.09))
        self.assertEqual(r.binding, "DSCR")
        # Implied DSCR sits at the minimum.
        self.assertAlmostEqual(r.implied_dscr, 1.25, places=2)

    def test_debt_yield_binding_when_rate_is_low(self):
        # Cheap debt → LTV would lend a lot, DSCR isn't tight, DY 8% binds.
        r = size_loan(sizing_noi=2_500_000, purchase_price=50_000_000,
                     debt=_debt(rate=0.035))
        self.assertEqual(r.binding, "Debt Yield")
        # Loan = NOI / 0.08 = 31.25M.
        self.assertAlmostEqual(r.loan_amount, 31_250_000, delta=1)

    def test_fixed_loan_overrides_constraints(self):
        r = size_loan(sizing_noi=1_000_000, purchase_price=20_000_000,
                     debt=_debt(fixed_loan_amount=8_000_000))
        self.assertEqual(r.loan_amount, 8_000_000)
        self.assertEqual(r.binding, "(fixed)")
        # Implied ratios computed against the fixed loan.
        self.assertAlmostEqual(r.implied_ltv, 8_000_000 / 20_000_000, places=6)


class TestAmortizationSchedule(unittest.TestCase):
    """Structural invariants — should hold regardless of monthly vs annual
    compounding convention."""

    def test_io_only_no_principal_paid(self):
        debt = _debt(amort_yrs=0)   # interest-only for full term
        sched = amortization_schedule(10_000_000, debt, years=10)
        for yr in sched:
            self.assertEqual(yr.principal, 0.0)
            self.assertTrue(yr.is_io)
            self.assertEqual(yr.ending_balance, 10_000_000)

    def test_io_period_then_amortizing(self):
        debt = _debt(amort_yrs=30, io_period_yrs=3)
        sched = amortization_schedule(10_000_000, debt, years=10)
        # Years 1-3 are IO.
        for yr in sched[:3]:
            self.assertTrue(yr.is_io)
            self.assertEqual(yr.principal, 0.0)
            self.assertEqual(yr.ending_balance, 10_000_000)
        # Year 4+ is amortizing.
        self.assertFalse(sched[3].is_io)
        self.assertGreater(sched[3].principal, 0.0)
        self.assertLess(sched[3].ending_balance, 10_000_000)

    def test_balance_reconciles_year_over_year(self):
        debt = _debt(amort_yrs=30)
        sched = amortization_schedule(30_000_000, debt, years=10)
        for i, yr in enumerate(sched):
            if i == 0:
                self.assertEqual(yr.beginning_balance, 30_000_000)
            else:
                self.assertAlmostEqual(yr.beginning_balance,
                                       sched[i - 1].ending_balance, places=2)
            # Ending = beginning − principal.
            self.assertAlmostEqual(yr.ending_balance,
                                   yr.beginning_balance - yr.principal,
                                   places=2)

    def test_debt_service_equals_interest_plus_principal(self):
        debt = _debt(amort_yrs=30)
        sched = amortization_schedule(20_000_000, debt, years=10)
        for yr in sched:
            self.assertAlmostEqual(yr.debt_service,
                                   yr.interest + yr.principal, places=2)

    def test_principal_strictly_positive_after_io(self):
        debt = _debt(amort_yrs=30, io_period_yrs=2)
        sched = amortization_schedule(15_000_000, debt, years=10)
        for yr in sched[2:]:
            self.assertGreater(yr.principal, 0)

    def test_balloon_exists_for_term_shorter_than_amort(self):
        # 10-year term on a 30-year amort → balloon at year 10.
        debt = _debt(amort_yrs=30)
        sched = amortization_schedule(30_000_000, debt, years=10)
        # Substantial balloon (most principal still owed).
        self.assertGreater(sched[-1].ending_balance, 20_000_000)

    def test_near_zero_rate_amortizes_close_to_par(self):
        # At a tiny rate the schedule should pay off ~all principal over the
        # full amort term. We loosen the tolerance because annual vs monthly
        # compounding produces small (~$50) drift on a $1M loan.
        debt = _debt(rate=0.0001, amort_yrs=10)   # near-zero (rate>0 schema constraint)
        sched = amortization_schedule(1_000_000, debt, years=10)
        total_principal = sum(yr.principal for yr in sched)
        self.assertAlmostEqual(total_principal, 1_000_000, delta=200.0)


if __name__ == "__main__":
    unittest.main()
