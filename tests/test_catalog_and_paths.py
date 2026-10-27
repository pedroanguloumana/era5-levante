from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from era5_levante import MissingCoverageError, get_parameter, open_data, resolve_files, search


class CatalogTests(unittest.TestCase):
    def test_humidity_is_not_conflated(self):
        found = {parameter.code: parameter for parameter in search("humidity")}
        self.assertEqual(set(found), {133, 157})
        self.assertEqual((found[133].short_name, found[133].units), ("q", "kg kg-1"))
        self.assertEqual((found[157].short_name, found[157].units), ("r", "%"))
        self.assertEqual(found[133].level_types, ("pl", "ml"))
        self.assertEqual(found[157].level_types, ("pl",))
        self.assertEqual(get_parameter("0133"), found[133])
        self.assertEqual(get_parameter("r"), found[157])
        self.assertTrue(all(a.hourly_representation == "instantaneous" for a in found[133].availability))

    def test_accumulation_and_new_archive_parameter(self):
        tp = get_parameter("total precipitation")
        self.assertEqual(tp.code, 228)
        self.assertEqual(tp.availability[0].kind, "fc")
        self.assertEqual(tp.availability[0].hourly_representation, "accumulated")
        self.assertEqual(get_parameter(527).short_name, "ptype")
        self.assertEqual(get_parameter(527).eccodes_param_id, 260015)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            get_parameter("precipitation")


class PathTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "E5"

    def touch(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_hourly_dates_and_missing_coverage(self):
        first = self.touch("pl/an/1H/133/E5pl00_1H_2000-01-01_133.grb")
        selected = resolve_files("q", "pl", "1H", "2000-01-01", "2000-01-03", root=self.root)
        self.assertEqual(selected.files, (first,))
        self.assertEqual(selected.missing, ("2000-01-02", "2000-01-03"))
        with self.assertRaises(MissingCoverageError):
            selected.require_complete()

    def test_monthly_and_yearly_file_stamps(self):
        jan = self.touch("sf/fc/1D/228/E5sf12_1D_2000-01_228.grb")
        feb = self.touch("sf/fc/1D/228/E5sf12_1D_2000-02_228.grb")
        daily = resolve_files("tp", "sf", "1D", "2000-01-15", "2000-02-03", root=self.root)
        self.assertEqual(daily.files, (jan, feb))
        self.assertTrue(daily.complete)
        year = self.touch("sf/fc/1M/228/E5sf12_1M_2000_228.grb")
        monthly = resolve_files(228, "sf", "1M", "2000-02-01", "2000-11-30", root=self.root)
        self.assertEqual(monthly.files, (year,))

    def test_iv_symlink_and_ambiguity(self):
        dated = self.touch("sf/an/IV/172/E5sf00_IV_2000-01-01_172.grb")
        canonical = dated.with_name("E5sf00_IV_INVARIANT_172.grb")
        canonical.symlink_to(dated)
        selected = resolve_files("lsm", "sf", "IV", kind="an", root=self.root)
        self.assertEqual(selected.files, (canonical,))
        with self.assertRaisesRegex(ValueError, "omit start and end"):
            resolve_files("lsm", "sf", "IV", "2000-01-01", kind="an", root=self.root)
        with self.assertRaisesRegex(ValueError, "both analysis and forecast"):
            resolve_files("sst", "sf", "1H", "2000-01-01", root=self.root)

    def test_unavailable_combination_and_invalid_range(self):
        with self.assertRaisesRegex(ValueError, "not cataloged"):
            resolve_files("r", "ml", "1H", "2000-01-01", root=self.root)
        with self.assertRaisesRegex(ValueError, "end precedes start"):
            resolve_files("q", "pl", "1H", "2000-01-02", "2000-01-01", root=self.root)

    def test_open_file_limit_is_checked_before_archive_scan(self):
        with self.assertRaisesRegex(ValueError, "32 files"):
            open_data("q", "pl", "1H", "2000-01-01", "2000-02-01", root=self.root)


if __name__ == "__main__":
    unittest.main()
