import argparse
import base64
import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import textwrap
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
LOGIN = "anakrypt-kepler"
ACCENT = "#FF4D0D"
THEMES = {
    "dark": {"text": "#F4F4F5", "muted": "#A1A1AA", "dim": "#71717A", "edge": "#24242A", "card": "#101013", "grid": "#151518"},
    "light": {"text": "#18181B", "muted": "#52525B", "dim": "#71717A", "edge": "#E4E4E7", "card": "#FAFAFA", "grid": "#F4F4F5"},
}
COLORS = {"C++": "#F34B7D", "C": "#555555", "Python": "#3572A5", "Rust": "#DEA584", "TypeScript": "#3178C6", "JavaScript": "#F1E05A", "Svelte": "#FF3E00", "Shell": "#89E051", "CMake": "#DA3434", "HTML": "#E34C26", "CSS": "#563D7C", "Other": "#71717A"}


def download(url, authenticated=False):
    headers = {"User-Agent": "Mozilla/5.0 (Kepler GitHub profile renderer)", "Accept": "application/json" if authenticated else "*/*"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if authenticated and token:
        if not url.startswith("https://api.github.com/"):
            raise ValueError("Authentication is restricted to the GitHub API")
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return response.read()


def api(path):
    return json.loads(download("https://api.github.com" + path, authenticated=True))


class ContributionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.tooltips = {}
        self.current = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td" and "data-date" in attrs:
            self.cells[attrs["id"]] = {"date": attrs["data-date"], "level": int(attrs["data-level"])}
        if tag == "tool-tip" and "for" in attrs:
            self.current = attrs["for"]
            self.text = []

    def handle_data(self, value):
        if self.current is not None:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.current is not None:
            self.tooltips[self.current] = "".join(self.text).strip()
            self.current = None


def parse_calendar(html):
    parser = ContributionParser()
    parser.feed(html)
    if not parser.cells:
        raise ValueError("GitHub did not return a contribution calendar")
    days = []
    for key, cell in parser.cells.items():
        match = re.match(r"(No|[\d,]+) contributions?\b", parser.tooltips.get(key, ""))
        if not match:
            raise ValueError("Missing contribution count for " + cell["date"])
        if not 0 <= cell["level"] <= 4:
            raise ValueError("Invalid contribution intensity")
        days.append({**cell, "count": 0 if match[1] == "No" else int(match[1].replace(",", ""))})
    return sorted(days, key=lambda day: day["date"])


def fetch_data():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    user = api("/users/" + LOGIN)
    repos = []
    for page in range(1, 101):
        batch = api(f"/users/{LOGIN}/repos?type=owner&per_page=100&page={page}")
        repos.extend(repo for repo in batch if not repo["private"])
        if len(batch) < 100:
            break
    else:
        raise ValueError("Repository pagination exceeded the supported limit")
    languages = Counter()
    for repo in repos:
        if not repo["fork"]:
            languages.update(api(f"/repos/{LOGIN}/{quote(repo['name'], safe='')}/languages"))
    query = urlencode({"q": f"is:pr is:merged is:public author:{LOGIN} -user:{LOGIN}", "per_page": 3, "sort": "updated"})
    upstream = api("/search/issues?" + query)
    if upstream.get("incomplete_results"):
        raise ValueError("GitHub returned incomplete upstream statistics")
    html = download(f"https://github.com/users/{LOGIN}/contributions").decode()
    days = [day for day in parse_calendar(html) if str(start) <= day["date"] <= str(today)]
    expected = [str(start + timedelta(days=i)) for i in range(365)]
    if [day["date"] for day in days] != expected:
        raise ValueError("Contribution calendar is incomplete; keeping the previous snapshot")
    return {
        "login": LOGIN,
        "as_of": str(today),
        "created_at": user["created_at"],
        "public_repos": user["public_repos"],
        "followers": user["followers"],
        "stars": sum(repo["stargazers_count"] for repo in repos if not repo["fork"]),
        "upstream_count": upstream["total_count"],
        "upstream": [{"title": row["title"], "url": row["html_url"], "repo": row["repository_url"].removeprefix("https://api.github.com/repos/")} for row in upstream["items"]],
        "repos": [{key: repo[key] for key in ["name", "description", "html_url", "language", "stargazers_count", "pushed_at", "fork"]} for repo in repos],
        "languages": dict(languages),
        "days": days,
    }


def streaks(days):
    longest = run = 0
    previous = None
    for day in days:
        current_date = date.fromisoformat(day["date"])
        if previous is not None and current_date != previous + timedelta(days=1):
            run = 0
        run = run + 1 if day["count"] else 0
        longest = max(longest, run)
        previous = current_date
    tail = days[:-1] if days and not days[-1]["count"] else days
    current = 0
    for day in reversed(tail):
        if not day["count"]:
            break
        current += 1
    return current, longest


def language_shares(languages):
    items = sorted(((name, value) for name, value in languages.items() if value > 0), key=lambda item: (-item[1], item[0]))
    total = sum(value for _, value in items)
    if not total:
        return []
    if len(items) > 8:
        items = items[:7] + [("Other", sum(value for _, value in items[7:]))]
    return [(name, value / total) for name, value in items]


def import_reference():
    svg = download("https://gfx.redstone.md/net").decode()
    match = re.search(r"data:font/woff2;base64,([A-Za-z0-9+/=]+)", svg)
    if not match:
        raise ValueError("The reference no longer includes its JetBrains Mono font")
    license_text = download("https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/OFL.txt")
    (ASSETS / "JetBrainsMono.woff2").write_bytes(base64.b64decode(match[1], validate=True))
    (ASSETS / "JetBrainsMono-OFL.txt").write_text("\n".join(line.rstrip() for line in license_text.decode().splitlines()) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def font_style():
    path = ASSETS / "JetBrainsMono.woff2"
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode()
    return "@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:100 800;src:url(data:font/woff2;base64," + encoded + ") format('woff2')}"


def mesh_nodes():
    return (
        ("Synapsenetai", 459, 247, True),
        (LOGIN, 571, 134, True),
        ("NAAN", 253, 225, False),
        ("PoE", 338, 318, False),
        ("Tor", 386, 130, False),
        ("Knowledge", 629, 264, False),
        ("Desktop", 573, 352, False),
        ("Wallet", 218, 357, False),
        ("P2P", 703, 187, False),
        ("C++ engine", 426, 395, False),
        ("Local GGUF", 174, 150, False),
        ("Rust FFI", 118, 280, False),
    )


def node_briefs():
    return {
        "Synapsenetai": {"title": "Synapsenetai", "blurb": "SynapseNet desktop and engine", "files": ("src/ide/synapsed_engine.cpp", "tauri-app/src/app/App.svelte", "src-tauri/src/commands.rs")},
        LOGIN: {"title": "Profile", "blurb": "This public GitHub profile", "files": ("scripts/render_profile.py", "assets/net-dark.svg", "README.md")},
        "NAAN": {"title": "NAAN", "blurb": "Local harvest agents", "files": ("src/ide/synapsed_engine.cpp", "routes/NaanAgent.svelte", "lib/naanCrew.ts")},
        "PoE": {"title": "Proof of Emergence", "blurb": "Peer knowledge consensus", "files": ("src/core/poe_v1.cpp", "include/core/poe_v1.h", "src/node/poe_runtime.cpp")},
        "Tor": {"title": "Tor", "blurb": "Fail-closed peer transport", "files": ("src/web/tor_fetch.cpp", "src/core/tor_route_policy.cpp", "src/core/tor_process_guard.cpp")},
        "Knowledge": {"title": "Knowledge", "blurb": "Shared knowledge store", "files": ("src/core/knowledge.cpp", "include/core/knowledge.h", "routes/Knowledge.svelte")},
        "Desktop": {"title": "Desktop", "blurb": "Tauri pixel cell", "files": ("tauri-app/src/app/App.svelte", "sprites/NaanStation.svelte", "src-tauri/src/lib.rs")},
        "Wallet": {"title": "Wallet", "blurb": "Local wallet and claims", "files": ("src/core/wallet.cpp", "include/core/wallet.h", "routes/Wallet.svelte")},
        "P2P": {"title": "P2P", "blurb": "Peer identity and mesh", "files": ("src/core/tor_peer_identity.cpp", "src/node/poe_runtime.cpp", "src/cli/synapsed_poe_mesh.cpp")},
        "C++ engine": {"title": "C++ engine", "blurb": "Native synapsed runtime", "files": ("src/ide/synapsed_engine.cpp", "src/ide/synapsed_engine.h", "src/core/naan_task_share.cpp")},
        "Local GGUF": {"title": "Local GGUF", "blurb": "On-disk model weights", "files": ("components/ModelCatalog.svelte", "src/ide/synapsed_engine.cpp", "third_party/llama.cpp")},
        "Rust FFI": {"title": "Rust FFI", "blurb": "Desktop engine bridge", "files": ("src-tauri/src/commands.rs", "tauri-app/src/lib/rpc.ts", "src-tauri/src/lib.rs")},
    }


def node_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", slug):
        raise ValueError("Unsafe mesh node name: " + name)
    return slug


def card_box(x, y, width=252, height=102):
    left = x + 18
    top = y - height / 2
    if left + width > 824:
        left = x - width - 18
    left = min(max(16.0, left), float(840 - width - 16))
    top = min(max(82.0, top), float(424 - height))
    return (round(left, 1), round(top, 1), width, height)


def ticker_line(info):
    return info["title"] + "   " + "   ".join(info["files"][:2])


def ticker_animation(index, count, period=3.2):
    if count < 1:
        raise ValueError("Ticker needs at least one node")
    cycle = round(count * period, 1)
    fade = 0.012
    start = index / count
    end = (index + 1) / count
    if index == 0:
        times = [0.0, round(end - fade, 4), round(end, 4), 1.0]
        values = ["1", "1", "0", "0"]
    elif index == count - 1:
        times = [0.0, round(start, 4), round(min(1.0, start + fade), 4), round(1.0 - fade, 4), 1.0]
        values = ["0", "0", "1", "1", "0"]
    else:
        times = [0.0, round(start, 4), round(min(1.0, start + fade), 4), round(max(start + fade, end - fade), 4), round(end, 4), 1.0]
        values = ["0", "0", "1", "1", "0", "0"]
    cleaned_times = []
    cleaned_values = []
    for time, value in zip(times, values):
        time = min(max(time, 0.0), 1.0)
        if cleaned_times and time <= cleaned_times[-1]:
            time = min(1.0, round(cleaned_times[-1] + 0.0001, 4))
        cleaned_times.append(time)
        cleaned_values.append(value)
    cleaned_times[-1] = 1.0
    return cycle, cleaned_times, cleaned_values


def mesh_hover_style(slugs):
    rules = [".card{opacity:0}", ".static-legend{display:none}"]
    for slug in slugs:
        rules.append(f"#{slug}:hover~#card-{slug},#{slug}:focus-within~#card-{slug}{{opacity:1}}")
    rules.append("@media(prefers-reduced-motion:reduce){.static-legend{display:block}}")
    return "".join(rules)


class SVG:
    def __init__(self, height, theme, title, width=840, extra_style=""):
        self.height, self.width, self.title = height, width, title
        self.colors = THEMES[theme]
        self.extra_style = extra_style
        self.parts = []

    def raw(self, value):
        self.parts.append(value)

    def rect(self, x, y, width, height, fill, **attrs):
        extra = " ".join(f'{key.rstrip("_").replace("_", "-")}="{escape(str(value), quote=True)}"' for key, value in attrs.items())
        self.raw(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" {extra}/>')

    def text(self, x, y, value, size=12, color="muted", **attrs):
        color = self.colors.get(color, color)
        extra = " ".join(f'{key.rstrip("_").replace("_", "-")}="{escape(str(value), quote=True)}"' for key, value in attrs.items())
        self.raw(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" {extra}>{escape(str(value))}</text>')

    def section(self, title, note=""):
        self.text(22, 28, title.upper(), 16, "text", font_weight=600, letter_spacing=1.5)
        self.text(self.width - 22, 28, note, 11, "dim", text_anchor="end")
        self.raw(f'<defs><linearGradient id="rule"><stop stop-color="{ACCENT}" stop-opacity=".9"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient></defs>')
        self.rect(0, 40, self.width, 1, "url(#rule)")

    def finish(self):
        title = escape(self.title, quote=True)
        style = font_style() + "text{font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre}.reveal{animation:reveal .8s ease both}@keyframes reveal{from{opacity:0}to{opacity:1}}@media(prefers-reduced-motion:reduce){.motion{display:none}.reveal{animation:none!important}}" + self.extra_style
        return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{title}">\n<title>{title}</title>\n<style>{style}</style>\n' + "\n".join(self.parts) + "\n</svg>\n"


def net(data, theme):
    names = mesh_nodes()
    briefs = node_briefs()
    if set(briefs) != {name for name, *_ in names}:
        raise ValueError("Mesh node briefs must cover every node and only those nodes")
    slugs = [node_slug(name) for name, *_ in names]
    svg = SVG(460, theme, "Kepler — SynapseNet repositories and components, animated mesh", extra_style=mesh_hover_style(slugs))
    svg.raw(f'<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="{svg.colors["grid"]}"/></pattern></defs>')
    svg.rect(0, 0, 840, 460, "url(#grid)")
    for path in ["M14 30V14H30", "M826 30V14h-16", "M14 430v16h16", "M826 430v16h-16"]:
        svg.raw(f'<path d="{path}" fill="none" stroke="{ACCENT}" stroke-width="2"/>')
    svg.text(22, 40, "Kepler", 19, "text", font_weight=600, letter_spacing=1)
    svg.text(104, 40, "@" + LOGIN, 13, ACCENT)
    svg.text(22, 62, "local intelligence, shared knowledge, connected systems", 12)
    svg.rect(0, 76, 840, 1, svg.colors["edge"])
    edges = set()
    for i, (_, x, y, _) in enumerate(names):
        nearest = sorted((j for j in range(len(names)) if j != i), key=lambda j: math.hypot(names[j][1] - x, names[j][2] - y))[:2]
        edges.update(tuple(sorted((i, j))) for j in nearest)
    edges.add((0, 2))
    for index, (a, b) in enumerate(sorted(edges)):
        _, x1, y1, _ = names[a]
        _, x2, y2, _ = names[b]
        svg.raw(f'<path id="edge{index}" d="M{x1},{y1}L{x2},{y2}" fill="none" stroke="{svg.colors["edge"]}"/>')
        duration, begin = 3.5 + index % 7 * .19, -(index * .37 % 4)
        svg.raw(f'<circle class="motion" r="2" fill="{ACCENT}" opacity="0"><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.88;1" dur="{duration:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite"/><animateMotion dur="{duration:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite"><mpath href="#edge{index}" xlink:href="#edge{index}"/></animateMotion></circle>')
    repositories = {repo["name"]: repo for repo in data["repos"]}
    for name, x, y, repository in names:
        repo = repositories.get(name)
        radius = 14 + min(8, math.sqrt(repo["stargazers_count"])) if repo else 6
        stroke = ACCENT if repository else svg.colors["dim"]
        fill = ACCENT if repository else svg.colors["card"]
        slug = node_slug(name)
        info = briefs[name]
        hit = max(radius + 10, 20)
        svg.raw(f'<g id="{slug}" class="node" tabindex="0">')
        svg.raw(f'<title>{escape(info["title"])}: {escape(info["blurb"])}. Files: {escape(", ".join(info["files"]))}</title>')
        svg.raw(f'<circle class="hit" cx="{x}" cy="{y}" r="{hit}" fill="#000" fill-opacity="0"/>')
        if repository:
            svg.raw(f'<circle class="motion" cx="{x}" cy="{y}" r="{radius}" fill="none" stroke="{ACCENT}"><animate attributeName="r" values="{radius};{radius + 12}" dur="2.8s" repeatCount="indefinite"/><animate attributeName="opacity" values=".6;0" dur="2.8s" repeatCount="indefinite"/></circle>')
        svg.raw(f'<circle class="core" cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        label = name + (f' / {repo["stargazers_count"]} stars' if repo else "")
        if name == LOGIN:
            svg.text(x, y - 26, "Profile", 12, "text", text_anchor="middle")
        else:
            svg.text(x + radius + 10 if x < 500 else x - radius - 10, y + 4, label, 12, "text" if repository else "muted", text_anchor="start" if x < 500 else "end")
        svg.raw("</g>")
    for index, (name, *_) in enumerate(names):
        line = ticker_line(briefs[name])
        cycle, key_times, values = ticker_animation(index, len(names))
        svg.raw(f'<g class="motion" opacity="0"><text x="22" y="432" fill="{svg.colors["dim"]}" font-size="10">{escape(line)}</text><animate attributeName="opacity" values="{",".join(values)}" keyTimes="{";".join(f"{time:.4f}" for time in key_times)}" dur="{cycle}s" begin="0s" repeatCount="indefinite"/></g>')
    svg.raw(f'<text class="static-legend" x="22" y="432" fill="{svg.colors["dim"]}" font-size="10">filled: repositories / outlined: project components</text>')
    svg.text(818, 432, f'{data["public_repos"]} public repos / {data["stars"]} stars', 10, "dim", text_anchor="end")
    for name, x, y, _ in names:
        info = briefs[name]
        slug = node_slug(name)
        left, top, width, height = card_box(x, y)
        svg.raw(f'<g id="card-{slug}" class="card">')
        svg.rect(left, top, width, height, svg.colors["card"], rx=6, stroke=ACCENT)
        svg.rect(left, top, 3, height, ACCENT)
        svg.text(left + 14, top + 22, info["title"], 12, "text", font_weight=600)
        svg.text(left + 14, top + 40, info["blurb"], 10, "muted")
        for index, path in enumerate(info["files"][:3]):
            svg.text(left + 14, top + 62 + index * 14, path, 10, "dim")
        svg.raw("</g>")
    return svg


def tiles(data, theme):
    svg = SVG(92, theme, "Public GitHub account statistics for " + LOGIN)
    today, created = date.fromisoformat(data["as_of"]), date.fromisoformat(data["created_at"][:10])
    months = max(0, (today.year - created.year) * 12 + today.month - created.month - (today.day < created.day))
    age = f"{months // 12}y" if months >= 12 else f"{months}mo"
    values = [(data["public_repos"], "PUBLIC REPOSITORIES"), (data["stars"], "STARS EARNED"), (data["followers"], "FOLLOWERS"), (data["upstream_count"], "MERGED UPSTREAM"), (age, "ON GITHUB")]
    for index, (value, name) in enumerate(values):
        x = round(index * 169.6, 1)
        color = ACCENT if index in (1, 3) else svg.colors["edge"]
        svg.rect(x, .5, 161.6, 91, svg.colors["card"], rx=6, stroke=svg.colors["edge"])
        svg.rect(x, .5, 3, 91, color)
        svg.text(x + 80.8, 46, value, 24, ACCENT if index in (1, 3) else "text", text_anchor="middle", font_weight=600)
        svg.text(x + 80.8, 68, name, 9, "dim", text_anchor="middle", letter_spacing=.7)
    return svg


def heat(data, theme):
    days = data["days"]
    total = sum(day["count"] for day in days)
    svg = SVG(235, theme, f"{total:,} public profile contributions over the last 365 days")
    svg.section("Contributions", "last 12 months / public profile")
    first = date.fromisoformat(days[0]["date"])
    origin = first - timedelta(days=(first.weekday() + 1) % 7)
    last = date.fromisoformat(days[-1]["date"])
    columns = (last - origin).days // 7 + 1
    step = min(14, 764 / columns)
    colors = [svg.colors["edge"], "#4B2114", "#853417", "#C74311", ACCENT] if theme == "dark" else ["#E4E4E7", "#FFDBC9", "#FFB48A", "#FF8050", ACCENT]
    month = None
    for column in range(columns):
        sunday = origin + timedelta(days=column * 7)
        if sunday.month != month:
            svg.text(48 + column * step, 67, calendar.month_abbr[sunday.month], 10, "dim")
            month = sunday.month
    for row, name in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        svg.text(22, 86 + row * 14, name, 9, "dim")
    for day in days:
        offset = (date.fromisoformat(day["date"]) - origin).days
        col, row = divmod(offset, 7)
        svg.raw(f'<g class="reveal" style="animation-delay:{col * .014:.3f}s"><title>{day["date"]}: {day["count"]} contributions</title>')
        svg.rect(round(48 + col * step, 2), 76 + row * 14, round(step - 3, 2), 11, colors[day["level"]], rx=1)
        svg.raw('</g>')
    current, longest = streaks(days)
    svg.text(22, 196, f"{total:,} contributions / {current}d current streak / {longest}d longest", 10, "dim")
    svg.text(22, 220, f'Snapshot {data["as_of"]} UTC', 10, "dim")
    svg.text(685, 220, "less", 9, "dim")
    for i, color in enumerate(colors):
        svg.rect(715 + i * 14, 211, 10, 10, color, rx=1)
    svg.text(790, 220, "more", 9, "dim")
    return svg


def langs(data, theme):
    svg = SVG(168, theme, "Language distribution by code bytes in public, non-fork repositories")
    svg.section("Languages", "public non-fork repositories / by code bytes")
    shares = language_shares(data["languages"])
    if not shares:
        svg.text(22, 82, "No public language data available yet.")
        return svg
    svg.raw('<defs><clipPath id="reveal"><rect x="0" y="64" width="840" height="26" rx="3"/></clipPath></defs><g clip-path="url(#reveal)">')
    x = 0
    for index, (name, fraction) in enumerate(shares):
        width = fraction * 840
        svg.rect(round(x, 2), 64, max(.1, round(width - 1, 2)), 26, COLORS.get(name, "#A78BFA"), class_="reveal", style=f"animation-delay:{index * .08}s")
        x += width
    svg.raw('</g>')
    for i, (name, fraction) in enumerate(shares):
        x, y = 22 + (i % 4) * 205, 116 + (i // 4) * 27
        svg.raw(f'<circle cx="{x}" cy="{y - 4}" r="3" fill="{COLORS.get(name, "#A78BFA")}"/>')
        percent = f"{fraction * 100:.1f}%" if fraction >= .001 else "<0.1%"
        svg.text(x + 9, y, f"{name} {percent}", 11)
    return svg


def strip(theme):
    svg = SVG(54, theme, "Selected work")
    svg.section("Selected work", "public repositories / real GitHub data")
    return svg


def card(repo, data, theme):
    svg = SVG(180, theme, f'{repo["name"]} — {repo["stargazers_count"]} stars', width=410)
    svg.rect(.5, .5, 409, 179, svg.colors["card"], rx=6, stroke=svg.colors["edge"])
    svg.rect(.5, .5, 3, 179, ACCENT)
    svg.raw(f'<g fill="none" stroke="{ACCENT}" stroke-width="2" opacity=".15"><path d="M317 65l34 -20 34 20v40l-34 20-34-20ZM317 65l34 20 34-20M351 85v40"/><circle cx="351" cy="85" r="12"/></g>')
    svg.text(22, 34, repo["name"], 16, "text", font_weight=600)
    language = repo["language"] or "Profile"
    svg.text(388, 56, language, 11, COLORS.get(language, "muted"), text_anchor="end")
    description = "Decentralized intelligence. Local GGUF models, Tor peers, and Proof of Emergence." if repo["name"] == "Synapsenetai" else "Kepler's profile. Animated project mesh, contribution history, and public GitHub statistics."
    for index, line in enumerate(textwrap.wrap(description, 43)[:3]):
        svg.text(22, 80 + index * 19, line, 12.5)
    svg.rect(22, 141, 366, 1, svg.colors["edge"])
    svg.text(22, 163, f'{repo["stargazers_count"]} stars', 11, ACCENT)
    days = max(0, (date.fromisoformat(data["as_of"]) - date.fromisoformat(repo["pushed_at"][:10])).days)
    svg.text(388, 163, "pushed today" if not days else f"pushed {days}d ago", 11, "dim", text_anchor="end")
    return svg


def portrait_data():
    gif = ASSETS / "kepler.gif"
    if not gif.is_file():
        raise FileNotFoundError("assets/kepler.gif is required")
    return base64.b64encode(gif.read_bytes()).decode()


def kepler(theme):
    svg = SVG(325, theme, "Kepler — independent builder of SynapseNet")
    svg.section("Kepler / SynapseNet", "independent builder")
    svg.rect(22, 58, 206, 250, svg.colors["card"], rx=6, stroke=svg.colors["edge"])
    svg.raw(f'<image x="25" y="72" width="200" height="220" href="data:image/gif;base64,{portrait_data()}" preserveAspectRatio="xMidYMid meet"/>')
    rows = [("SynapseNet", "Decentralized intelligence, built in the open."), ("Local AI + NAAN", "Local models and knowledge contributions."), ("Tor + Proof of Emergence", "Peer communication and knowledge validation."), ("C++ / Rust / Tauri / Svelte", "From the native engine to the desktop cell.")]
    for index, (title, subtitle) in enumerate(rows):
        y = 88 + index * 51
        svg.rect(246, y - 12, 2, 14, ACCENT)
        svg.text(260, y, title, 13, "text", font_weight=600)
        svg.text(260, y + 19, subtitle, 11.5)
    svg.text(260, 298, "Intelligence belongs to everyone. / Alpha development.", 11, "dim")
    return svg


def upstream(data, theme):
    rows = data["upstream"]
    svg = SVG(90 + len(rows) * 44, theme, "Public pull requests merged into other people's repositories")
    svg.section("Merged upstream", "other people's repositories")
    if not rows:
        svg.text(22, 73, "No public upstream pull requests merged yet.", 12)
    for index, row in enumerate(rows):
        y = 70 + index * 44
        svg.text(22, y, row["repo"], 12, "text")
        svg.text(22, y + 18, textwrap.shorten(row["title"], width=100, placeholder="..."), 11, ACCENT)
    return svg


def footer(data, theme):
    svg = SVG(150, theme, "Kepler — local models, shared knowledge, open infrastructure")
    svg.section("Elsewhere", "@" + LOGIN)
    for x, width, value in [(140, 160, "SynapseNet"), (314, 196, "GitHub profile"), (524, 176, "Issues + ideas")]:
        svg.rect(x, 59, width, 30, svg.colors["card"], rx=15, stroke=svg.colors["edge"])
        svg.text(x + width / 2, 79, value, 11, ACCENT, text_anchor="middle")
    svg.text(420, 116, "Local models. Shared knowledge. Open infrastructure.", 11, "dim", text_anchor="middle")
    svg.text(420, 138, f'Public data snapshot / {data["as_of"]} UTC / refreshed daily', 10, "dim", text_anchor="middle")
    return svg


def render(data):
    repos = {repo["name"]: repo for repo in data["repos"]}
    for theme in THEMES:
        graphics = {"net": net(data, theme), "tiles": tiles(data, theme), "heat": heat(data, theme), "langs": langs(data, theme), "selected": strip(theme), "portrait": kepler(theme), "upstream": upstream(data, theme), "footer": footer(data, theme)}
        for name in ["Synapsenetai", LOGIN]:
            graphics["card-" + name.lower()] = card(repos[name], data, theme)
        for name, graphic in graphics.items():
            (ASSETS / f"{name}-{theme}.svg").write_text(graphic.finish(), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate animated GitHub profile SVGs from a public-data snapshot.")
    parser.add_argument("--refresh", action="store_true", help="Refresh public GitHub statistics before rendering.")
    parser.add_argument("--import-reference", action="store_true", help="Import the embedded JetBrains Mono font from the reference SVG, with its OFL license.")
    args = parser.parse_args()
    if args.import_reference:
        import_reference()
    snapshot = ASSETS / "github-data.json"
    data = fetch_data() if args.refresh else json.loads(snapshot.read_text())
    render(data)
    if args.refresh:
        snapshot.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f'Rendered dark and light SVGs from the {data["as_of"]} public-data snapshot.')


if __name__ == "__main__":
    main()
