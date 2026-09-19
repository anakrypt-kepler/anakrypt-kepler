import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile", ROOT / "scripts/render_profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ProfileTests(unittest.TestCase):
    def test_calendar_joins_tooltips_to_dates(self):
        html = '''<td id="day-a" data-date="2026-09-18" data-level="4"></td>
        <td id="day-b" data-date="2026-09-19" data-level="0"></td>
        <tool-tip for="day-b">No contributions on September 19th.</tool-tip>
        <tool-tip for="day-a">1,234 contributions on September 18th.</tool-tip>'''
        days = profile.parse_calendar(html)
        self.assertEqual([d["count"] for d in days], [1234, 0])
        self.assertEqual(days[0]["date"], "2026-09-18")

    def test_missing_calendar_data_is_not_a_fake_zero(self):
        for html in ["<html>rate limited</html>", '<td id="a" data-date="2026-09-19" data-level="1"></td>']:
            with self.assertRaises(ValueError):
                profile.parse_calendar(html)

    def test_streak_allows_today_to_be_incomplete(self):
        days = [{"date": f"2026-09-{day:02}", "count": count} for day, count in enumerate([1, 1, 0, 2, 3, 0], 14)]
        self.assertEqual(profile.streaks(days), (2, 2))
        self.assertEqual(profile.streaks([]), (0, 0))

    def test_language_shares_include_small_languages(self):
        values = {f"language-{i}": 10 + i for i in range(12)}
        shares = profile.language_shares(values)
        self.assertEqual(len(shares), 8)
        self.assertEqual(shares[-1][0], "Other")
        self.assertAlmostEqual(sum(fraction for _, fraction in shares), 1)
        self.assertEqual(profile.language_shares({}), [])

    def test_refresh_only_searches_public_upstream_work(self):
        today = profile.datetime.now(profile.timezone.utc).date()
        days = [{"date": str(today - profile.timedelta(days=364 - i)), "count": 0, "level": 0} for i in range(365)]
        responses = [{"created_at": "2026-01-01T00:00:00Z", "public_repos": 0, "followers": 0}, [], {"total_count": 0, "items": []}]
        with patch.object(profile, "api", side_effect=responses) as api, patch.object(profile, "download", return_value=b"calendar") as download, patch.object(profile, "parse_calendar", return_value=days):
            result = profile.fetch_data()
        self.assertEqual(len(result["days"]), 365)
        self.assertIn("is:public", unquote(api.call_args_list[-1].args[0]))
        self.assertEqual(download.call_args.args[0], f"https://github.com/users/{profile.LOGIN}/contributions")

    def test_tokens_are_not_sent_to_other_hosts(self):
        with patch.dict(profile.os.environ, {"GH_TOKEN": "not-a-real-token"}):
            with self.assertRaises(ValueError):
                profile.download("https://example.com/public.svg", authenticated=True)

    def test_svg_text_is_escaped(self):
        svg = profile.SVG(120, "dark", 'A < B & "C"')
        svg.text(22, 30, '<script> & "quotes"')
        root = ET.fromstring(svg.finish())
        self.assertEqual(len(root.findall('.//{http://www.w3.org/2000/svg}script')), 0)
        self.assertIn('&lt;script&gt;', svg.finish())

    def test_all_published_svgs_are_safe_and_valid(self):
        files = list((ROOT / "assets").glob("*-dark.svg")) + list((ROOT / "assets").glob("*-light.svg"))
        self.assertTrue(files, "Render the real snapshot before running asset checks")
        for path in files:
            root = ET.fromstring(path.read_text())
            self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
            for element in root.iter():
                self.assertNotIn(element.tag.rsplit('}', 1)[-1], ['script', 'foreignObject'])
                self.assertFalse(any(key.lower().startswith('on') for key in element.attrib))
            self.assertNotIn('@Rxflex', path.read_text())
        mesh = (ROOT / 'assets/net-dark.svg').read_text()
        self.assertIn('animateMotion', mesh)
        self.assertIn('prefers-reduced-motion', mesh)
        self.assertIn('data:image/jpeg;base64,', (ROOT / 'assets/kepler-dark.svg').read_text())


if __name__ == "__main__":
    unittest.main()
