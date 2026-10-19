"""Generate distinct demo logos for the SAMPLE startups and investors.

    python tools/generate_logos.py

Writes static/images/logos/<slug>.svg. The sample companies are fictional,
so they get original marks rather than any real company's branding.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

OUT = os.path.join(os.path.dirname(__file__), "..", "static", "images", "logos")

PALETTES = [
    ("#3b1fd9", "#7c5cff"), ("#0b5ed7", "#38bdf8"), ("#0f766e", "#2dd4bf"), ("#b91c1c", "#fb7185"),
    ("#c2410c", "#fbbf24"), ("#4d7c0f", "#a3e635"), ("#7e22ce", "#e879f9"), ("#0f172a", "#64748b"),
    ("#1e3a8a", "#60a5fa"), ("#065f46", "#34d399"), ("#9a3412", "#fb923c"), ("#312e81", "#a78bfa"),
]


def orbit(a, b):
    return f'''<circle cx="128" cy="128" r="44" fill="url(#g)"/>
<ellipse cx="128" cy="128" rx="96" ry="34" fill="none" stroke="{b}" stroke-width="12" transform="rotate(-28 128 128)"/>
<circle cx="206" cy="86" r="12" fill="{a}"/>'''


def launch(a, b):
    return f'''<path d="M128 30 L188 150 L128 122 L68 150 Z" fill="url(#g)"/>
<path d="M128 140 L176 226 L128 204 L80 226 Z" fill="{b}" opacity=".75"/>'''


def hexmark(a, b):
    return f'''<path d="M128 26 L216 77 L216 179 L128 230 L40 179 L40 77 Z" fill="url(#g)"/>
<path d="M128 78 L172 103 L172 153 L128 178 L84 153 L84 103 Z" fill="#fff"/>
<circle cx="128" cy="128" r="16" fill="{a}"/>'''


def leaf(a, b):
    return f'''<path d="M60 196 C 50 110 110 52 206 50 C 208 146 150 206 60 196 Z" fill="url(#g)"/>
<path d="M60 196 C 100 150 140 110 190 66" stroke="#fff" stroke-width="12" fill="none" stroke-linecap="round"/>'''


def spark(a, b):
    return f'''<path d="M128 24 C 136 96 160 120 232 128 C 160 136 136 160 128 232 C 120 160 96 136 24 128 C 96 120 120 96 128 24 Z" fill="url(#g)"/>
<circle cx="196" cy="60" r="14" fill="{b}"/>'''


def nodes(a, b):
    return f'''<path d="M128 56 L56 186 L200 186 Z" fill="none" stroke="{b}" stroke-width="14" stroke-linejoin="round"/>
<circle cx="128" cy="56" r="30" fill="url(#g)"/><circle cx="56" cy="186" r="30" fill="url(#g)"/>
<circle cx="200" cy="186" r="30" fill="url(#g)"/><circle cx="128" cy="144" r="18" fill="{a}"/>'''


def split(a, b):
    return f'''<circle cx="128" cy="128" r="96" fill="{b}"/>
<path d="M60 196 A 96 96 0 0 1 196 60 Z" fill="url(#g)"/>
<circle cx="128" cy="128" r="34" fill="#fff"/>'''


def bars(a, b):
    return f'''<rect x="40" y="140" width="40" height="76" rx="10" fill="{b}"/>
<rect x="108" y="96" width="40" height="120" rx="10" fill="url(#g)"/>
<rect x="176" y="40" width="40" height="176" rx="10" fill="{a}"/>'''


def wave(a, b):
    return f'''<rect x="28" y="28" width="200" height="200" rx="56" fill="url(#g)"/>
<path d="M52 140 L92 140 L112 86 L144 186 L166 118 L180 140 L204 140" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>'''


def rotor(a, b):
    return f'''<g fill="url(#g)"><circle cx="72" cy="72" r="42"/><circle cx="184" cy="72" r="42"/>
<circle cx="72" cy="184" r="42"/><circle cx="184" cy="184" r="42"/></g>
<rect x="100" y="100" width="56" height="56" rx="14" fill="#fff" stroke="{a}" stroke-width="12"/>'''


def bolt(a, b):
    return f'''<circle cx="128" cy="128" r="100" fill="url(#g)"/>
<path d="M142 44 L76 140 L122 140 L110 212 L182 112 L134 112 Z" fill="#fff"/>'''


def chip(a, b):
    pins = "".join(f'<rect x="{x}" y="22" width="14" height="30" rx="4" fill="{b}"/><rect x="{x}" y="204" width="14" height="30" rx="4" fill="{b}"/>'
                   f'<rect x="22" y="{x}" width="30" height="14" rx="4" fill="{b}"/><rect x="204" y="{x}" width="30" height="14" rx="4" fill="{b}"/>'
                   for x in (78, 121, 164))
    return f'''{pins}<rect x="52" y="52" width="152" height="152" rx="28" fill="url(#g)"/>
<rect x="96" y="96" width="64" height="64" rx="12" fill="#fff"/>'''


def helix(a, b):
    return f'''<path d="M84 30 C 84 90 172 90 172 128 C 172 166 84 166 84 226" fill="none" stroke="url(#g)" stroke-width="22" stroke-linecap="round"/>
<path d="M172 30 C 172 90 84 90 84 128 C 84 166 172 166 172 226" fill="none" stroke="{b}" stroke-width="22" stroke-linecap="round" opacity=".8"/>'''


def atom(a, b):
    return f'''<g fill="none" stroke="url(#g)" stroke-width="14"><ellipse cx="128" cy="128" rx="100" ry="38"/>
<ellipse cx="128" cy="128" rx="100" ry="38" transform="rotate(60 128 128)"/><ellipse cx="128" cy="128" rx="100" ry="38" transform="rotate(120 128 128)"/></g>
<circle cx="128" cy="128" r="22" fill="{a}"/>'''


def monogram(a, b, letter="A"):
    return f'''<rect x="24" y="24" width="208" height="208" rx="60" fill="url(#g)"/>
<text x="128" y="170" text-anchor="middle" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="128" font-weight="800" fill="#fff">{letter}</text>'''


CATEGORY_MARKS = {
    "spacetech": [launch, orbit, spark], "robotics": [nodes, hexmark], "ai": [spark, nodes],
    "biotech": [helix, split], "semiconductors": [chip, hexmark], "climatetech": [leaf, orbit],
    "clean-energy": [bolt, bars], "agritech": [leaf, split], "quantum": [atom], "medtech": [wave, split],
    "defence": [hexmark], "ev-mobility": [bolt, split], "advanced-materials": [hexmark],
    "iot": [nodes], "drones": [rotor],
}
INVESTOR_MARKS = [bars, monogram, split, orbit, monogram, hexmark]


def render(mark, palette, **kw):
    a, b = palette
    body = mark(a, b, **kw) if kw else mark(a, b)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
{body}
</svg>
'''


def slugify(name):
    return name.lower().replace(" ", "-").replace(".", "")


def main():
    from seed import INVESTORS, STARTUPS
    os.makedirs(OUT, exist_ok=True)
    used = {}
    for row in STARTUPS:
        name, cat = row[0], row[1]
        marks = CATEGORY_MARKS[cat]
        n = used.get(cat, 0)
        used[cat] = n + 1
        digest = int(hashlib.sha1(name.encode()).hexdigest(), 16)
        palette = PALETTES[digest % len(PALETTES)]
        with open(os.path.join(OUT, f"{slugify(name)}.svg"), "w", encoding="utf-8") as fh:
            fh.write(render(marks[n % len(marks)], palette))
    for i, row in enumerate(INVESTORS):
        firm = row[0]
        mark = INVESTOR_MARKS[i % len(INVESTOR_MARKS)]
        kw = {"letter": firm[0]} if mark is monogram else {}
        with open(os.path.join(OUT, f"investor-{slugify(firm)}.svg"), "w", encoding="utf-8") as fh:
            fh.write(render(mark, PALETTES[(i * 5 + 3) % len(PALETTES)], **kw))
    print(f"Wrote {len(STARTUPS) + len(INVESTORS)} logos to {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
