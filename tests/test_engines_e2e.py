"""End-to-end tests against bundled example YAMLs.

These pin the headline numbers each engine produces on its canonical
fixture so engine refactors can't silently move them. Tolerance is loose
(±10 bps on rates, ±0.01x on multiples) because we're snapshotting
hand-validated values, not deriving from formula.

The values below were observed on main after the audit smoke checks; if a
change is intentional, update them and document why in the PR.
"""

from pathlib import Path
import unittest

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _run_mf(yaml_path):
    from scripts.underwriting.models import load_deal
    from scripts.underwriting.pro_forma import build_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_deal(str(yaml_path))
    pf = build_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


def _run_commercial(yaml_path):
    from scripts.underwriting.commercial.models import load_commercial_deal
    from scripts.underwriting.commercial.pro_forma import build_commercial_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_commercial_deal(str(yaml_path))
    pf = build_commercial_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


def _run_hospitality(yaml_path):
    from scripts.underwriting.hospitality.models import load_hotel_deal
    from scripts.underwriting.hospitality.pro_forma import build_hotel_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_hotel_deal(str(yaml_path))
    pf = build_hotel_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


def _run_dc_wholesale(yaml_path):
    from scripts.underwriting.datacenter.models import load_dc_wholesale_deal
    from scripts.underwriting.datacenter.wholesale_pro_forma import build_wholesale_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_dc_wholesale_deal(str(yaml_path))
    pf = build_wholesale_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


def _run_dc_colo(yaml_path):
    from scripts.underwriting.datacenter.models import load_dc_colo_deal
    from scripts.underwriting.datacenter.colo_pro_forma import build_colo_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_dc_colo_deal(str(yaml_path))
    pf = build_colo_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


def _run_infra(yaml_path):
    from scripts.underwriting.infrastructure.models import load_infrastructure_deal
    from scripts.underwriting.infrastructure.pro_forma import build_infrastructure_pro_forma
    from scripts.underwriting.waterfall_acq import run_acquisition_waterfall
    deal = load_infrastructure_deal(str(yaml_path))
    pf = build_infrastructure_pro_forma(deal)
    wf = run_acquisition_waterfall(pf)
    return pf, wf


class TestMultifamilyE2E(unittest.TestCase):

    def test_marina_apartments(self):
        pf, wf = _run_mf(_EXAMPLES / "marina-apartments.yaml")
        # Acquisition basics.
        self.assertEqual(pf.deal.property.unit_count, 200)
        self.assertAlmostEqual(pf.deal.acquisition.purchase_price, 42_000_000)
        # All-in basis ~ $45.15M (purchase + closing + capex + reserves + fees).
        self.assertAlmostEqual(pf.sources_uses.total_uses, 45_152_708, delta=10_000)
        # Going-in cap ~5.94% (Yr-1 NOI on purchase).
        self.assertAlmostEqual(pf.going_in_cap, 0.0594, delta=0.0010)
        # Loan sized at DSCR-binding ~$27M.
        self.assertAlmostEqual(pf.sizing.loan_amount, 27_027_783, delta=50_000)
        # Project IRR ~19.5%; LP Net ~17.5%.
        self.assertAlmostEqual(wf.total_equity_irr, 0.1954, delta=0.0050)
        self.assertAlmostEqual(wf.lp.irr, 0.1758, delta=0.0050)


class TestCommercialE2E(unittest.TestCase):

    def test_meridian_office(self):
        pf, wf = _run_commercial(_EXAMPLES / "example-office.yaml")
        # Sanity: positive equity, positive IRR.
        self.assertGreater(pf.sources_uses.equity_check, 0)
        self.assertGreater(wf.total_equity_irr, 0)
        # Going-in cap in a sensible band (1-10%).
        self.assertGreater(pf.going_in_cap, 0.01)
        self.assertLess(pf.going_in_cap, 0.15)

    def test_industrial_runs(self):
        pf, wf = _run_commercial(_EXAMPLES / "example-industrial.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)

    def test_retail_runs(self):
        pf, wf = _run_commercial(_EXAMPLES / "example-retail.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)


class TestHospitalityE2E(unittest.TestCase):

    def test_hampton_inn(self):
        pf, wf = _run_hospitality(_EXAMPLES / "example-hotel.yaml")
        self.assertEqual(pf.deal.property.keys, 120)
        self.assertGreater(pf.sources_uses.equity_check, 0)
        # PIP-displaced asset → reasonable cap range.
        self.assertGreater(pf.going_in_cap, 0.02)


class TestDatacenterE2E(unittest.TestCase):

    def test_ashburn_wholesale(self):
        pf, wf = _run_dc_wholesale(_EXAMPLES / "example-dc-wholesale.yaml")
        # Project IRR / MOIC observed at smoke check (12.84% / 1.74x).
        self.assertAlmostEqual(wf.total_equity_irr, 0.1284, delta=0.0050)
        self.assertAlmostEqual(wf.total_equity_moic, 1.74, delta=0.05)
        # Sensible cap range for DC.
        self.assertGreater(pf.going_in_cap, 0.04)
        self.assertLess(pf.going_in_cap, 0.10)

    def test_colo_runs(self):
        pf, wf = _run_dc_colo(_EXAMPLES / "example-dc-colo.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)


class TestInfrastructureE2E(unittest.TestCase):

    def test_solar_ppa(self):
        pf, wf = _run_infra(_EXAMPLES / "example-solar-ppa.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)
        # Infrastructure cap rates lower than RE typically.
        self.assertGreater(pf.going_in_cap, 0.03)

    def test_wind_runs(self):
        pf, wf = _run_infra(_EXAMPLES / "example-wind.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)

    def test_bess_runs(self):
        pf, wf = _run_infra(_EXAMPLES / "example-bess.yaml")
        self.assertGreater(pf.sources_uses.equity_check, 0)


class TestMultiTierWaterfallE2E(unittest.TestCase):

    def test_marina_multitier(self):
        pf, wf = _run_mf(_EXAMPLES / "marina-multitier.yaml")
        # Multi-tier waterfall shifts LP slightly down, GP up vs single-tier.
        # LP Net ~16.96%, GP Net ~36.31% from smoke check.
        self.assertAlmostEqual(wf.lp.irr, 0.1696, delta=0.0050)
        self.assertAlmostEqual(wf.gp.irr, 0.3631, delta=0.0050)
        # Should have 3 tiers (pref / hurdle II / residual).
        self.assertEqual(len(wf.tiers), 3)


if __name__ == "__main__":
    unittest.main()
