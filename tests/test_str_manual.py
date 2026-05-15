"""Tests for the manual STR comp-set parser."""

from pathlib import Path
import unittest

from scripts.market_data.str_manual import (
    STRMonth,
    compute_indices,
    load_compset,
    summary,
    trailing_window,
)


_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "example-str-compset.csv"


class TestLoadCompset(unittest.TestCase):

    def test_loads_example_csv(self):
        rows = load_compset(_EXAMPLE)
        # 12 months in the bundled example.
        self.assertEqual(len(rows), 12)

    def test_rows_sorted_by_month_ascending(self):
        rows = load_compset(_EXAMPLE)
        months = [r.month for r in rows]
        self.assertEqual(months, sorted(months))

    def test_supply_pipeline_optional_present_in_example(self):
        rows = load_compset(_EXAMPLE)
        # All rows in the example have supply_pipeline.
        self.assertTrue(all(r.new_supply_pipeline_pct is not None for r in rows))

    def test_comment_lines_skipped(self, tmp_path=None):
        # Inline-write a tiny CSV with comments.
        import tempfile
        body = (
            "# Test header comment\n"
            "# Another comment\n"
            "month,property_revpar,property_adr,property_occ,"
            "compset_revpar,compset_adr,compset_occ\n"
            "2025-01,100,150,0.67,90,140,0.64\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(body)
            path = f.name
        rows = load_compset(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].property_revpar, 100)


class TestComputeIndices(unittest.TestCase):

    def test_rgi_at_parity_is_100(self):
        rows = [
            STRMonth(
                month=__import__("datetime").date(2025, 1, 1),
                property_revpar=100, property_adr=150, property_occ=0.67,
                compset_revpar=100, compset_adr=150, compset_occ=0.67,
                new_supply_pipeline_pct=None,
            )
        ]
        idx = compute_indices(rows)
        self.assertAlmostEqual(idx[0].rgi, 100.0)
        self.assertAlmostEqual(idx[0].ari, 100.0)
        self.assertAlmostEqual(idx[0].mpi, 100.0)

    def test_outperforming_above_100(self):
        rows = [
            STRMonth(
                month=__import__("datetime").date(2025, 1, 1),
                property_revpar=120, property_adr=160, property_occ=0.75,
                compset_revpar=100, compset_adr=150, compset_occ=0.67,
                new_supply_pipeline_pct=None,
            )
        ]
        idx = compute_indices(rows)
        self.assertGreater(idx[0].rgi, 100)
        self.assertGreater(idx[0].mpi, 100)

    def test_zero_compset_safe(self):
        rows = [
            STRMonth(
                month=__import__("datetime").date(2025, 1, 1),
                property_revpar=120, property_adr=160, property_occ=0.75,
                compset_revpar=0, compset_adr=0, compset_occ=0,
                new_supply_pipeline_pct=None,
            )
        ]
        idx = compute_indices(rows)
        # Should not raise / return 0 sentinels.
        self.assertEqual(idx[0].rgi, 0.0)


class TestTrailingWindow(unittest.TestCase):

    def test_t3_from_example(self):
        rows = load_compset(_EXAMPLE)
        w = trailing_window(rows, 3)
        self.assertIsNotNone(w)
        # T-3 window covers the last 3 months.
        self.assertEqual(w.n_months, 3)
        # The example outperforms — RGI should be above 100.
        self.assertGreater(w.rgi, 100)

    def test_t12_from_example_supply_avg_present(self):
        rows = load_compset(_EXAMPLE)
        w = trailing_window(rows, 12)
        self.assertIsNotNone(w)
        self.assertIsNotNone(w.supply_growth_avg)
        # All 12 months have supply data; average should be ~ 2-3%.
        self.assertGreater(w.supply_growth_avg, 0.01)
        self.assertLess(w.supply_growth_avg, 0.05)

    def test_insufficient_data_returns_none(self):
        rows = load_compset(_EXAMPLE)[:2]   # only 2 months
        w = trailing_window(rows, 12)
        self.assertIsNone(w)


class TestSummary(unittest.TestCase):

    def test_renders_section_headers(self):
        rows = load_compset(_EXAMPLE)
        out = summary(rows)
        self.assertIn("STR COMP SET SUMMARY", out)
        self.assertIn("RevPAR", out)
        self.assertIn("T-3", out)
        self.assertIn("T-12", out)

    def test_empty_rows_message(self):
        out = summary([])
        self.assertIn("no data", out)


if __name__ == "__main__":
    unittest.main()
