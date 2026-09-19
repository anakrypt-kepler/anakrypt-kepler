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
        self.assertIn('.card{opacity:0}', mesh)
        self.assertIn('#naan:hover~#card-naan', mesh)
        self.assertIn('NaanAgent.svelte', mesh)
        self.assertIn('data:image/jpeg;base64,', (ROOT / 'assets/portrait-dark.svg').read_text())


    def sample_mesh_data(self):
        return {
            "public_repos": 2,
            "stars": 3,
            "repos": [
                {"name": "Synapsenetai", "stargazers_count": 3},
                {"name": profile.LOGIN, "stargazers_count": 0},
            ],
        }

    def test_node_briefs_cover_the_mesh(self):
        names = {name for name, *_ in profile.mesh_nodes()}
        self.assertEqual(set(profile.node_briefs()), names)
        for name, info in profile.node_briefs().items():
            self.assertTrue(info["title"])
            self.assertTrue(info["blurb"])
            self.assertEqual(len(info["files"]), 3)
            for path in info["files"]:
                self.assertNotIn("<", path)
                self.assertNotIn("javascript:", path.lower())
            self.assertRegex(profile.node_slug(name), r"^[a-z][a-z0-9-]*$")

    def test_node_slug_rejects_unsafe_names(self):
        with self.assertRaises(ValueError):
            profile.node_slug("123bad")
        with self.assertRaises(ValueError):
            profile.node_slug("")

    def test_card_box_stays_inside_the_mesh(self):
        for x, y in [(0, 0), (459, 247), (830, 450), (118, 280), (703, 187)]:
            left, top, width, height = profile.card_box(x, y)
            self.assertGreaterEqual(left, 16)
            self.assertGreaterEqual(top, 82)
            self.assertLessEqual(left + width, 824)
            self.assertLessEqual(top + height, 424)

    def test_ticker_animation_uses_one_full_cycle(self):
        count = len(profile.mesh_nodes())
        seen_ones = []
        for index in range(count):
            cycle, times, values = profile.ticker_animation(index, count)
            self.assertEqual(cycle, round(count * 3.2, 1))
            self.assertEqual(times[0], 0)
            self.assertEqual(times[-1], 1)
            self.assertEqual(len(times), len(values))
            self.assertEqual(times, sorted(times))
            self.assertTrue(any(value == "1" for value in values))
            for left, right in zip(times, times[1:]):
                self.assertLess(left, right)
            seen_ones.append(values)
        self.assertEqual(seen_ones[0][0], "1")
        self.assertEqual(seen_ones[1][0], "0")

    def test_mesh_hover_cards_and_ticker_are_safe(self):
        svg = profile.net(self.sample_mesh_data(), "dark").finish()
        root = ET.fromstring(svg)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}script")), 0)
        for element in root.iter():
            self.assertFalse(any(key.lower().startswith("on") for key in element.attrib))
        slugs = [profile.node_slug(name) for name, *_ in profile.mesh_nodes()]
        for slug in slugs:
            node = root.find(f'.//svg:g[@id="{slug}"]', ns)
            card = root.find(f'.//svg:g[@id="card-{slug}"]', ns)
            self.assertIsNotNone(node, slug)
            self.assertIsNotNone(card, slug)
            self.assertIn(f"#{slug}:hover~#card-{slug}", svg)
            self.assertLess(list(root).index(node), list(root).index(card))
            title = node.find("{http://www.w3.org/2000/svg}title")
            self.assertIsNotNone(title)
            self.assertIn("Files:", title.text)
        self.assertIn("src/ide/synapsed_engine.cpp", svg)
        self.assertIn('class="motion"', svg)
        self.assertIn("static-legend", svg)
        self.assertNotIn("<script", svg)


if __name__ == "__main__":
    unittest.main()
