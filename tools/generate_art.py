"""Generate the category cover illustrations in static/images/covers/.

Run:  python tools/generate_art.py

Each category gets three SVG variants (dark space backdrop, planet-curve
horizon, network constellation and a glowing line illustration) used as
fallback imagery for startup cards, products and galleries.
"""
import math
import os
import random

OUT = os.path.join(os.path.dirname(__file__), "..", "static", "images", "covers")
W, H = 800, 500

CATEGORIES = {
    "spacetech": "#7c5cff", "robotics": "#9b6bff", "ai": "#4f8bff", "biotech": "#22c58b",
    "semiconductors": "#22c3e6", "climatetech": "#3ddc84", "clean-energy": "#ffb020", "agritech": "#9ad23a",
    "quantum": "#b06bff", "medtech": "#ff5a7a", "defence": "#8fa3c0", "ev-mobility": "#38bdf8",
    "advanced-materials": "#f59e0b", "iot": "#2dd4bf", "drones": "#7d7bff",
}


def rocket():
    return """
    <path d="M0 -150 C 38 -110 46 -40 40 60 L -40 60 C -46 -40 -38 -110 0 -150 Z"/>
    <circle cx="0" cy="-60" r="16"/>
    <path d="M-40 10 L-80 80 L-40 60 M40 10 L80 80 L40 60"/>
    <path d="M-22 60 L-16 84 L16 84 L22 60"/>
    <path class="flame" d="M-14 90 C -18 130 0 170 0 190 C 0 170 18 130 14 90 Z"/>
    """


def bot():
    return """
    <rect x="-90" y="90" width="180" height="26" rx="8"/>
    <path d="M-40 90 L-40 60 L40 60 L40 90"/>
    <circle cx="0" cy="40" r="22"/>
    <path d="M14 22 L90 -60"/><circle cx="100" cy="-70" r="18"/>
    <path d="M112 -82 L40 -150"/><circle cx="34" cy="-156" r="12"/>
    <path d="M24 -166 L0 -186 M40 -168 L44 -196"/>
    """


def ai():
    layers = [(-150, [-90, -30, 30, 90]), (-50, [-120, -60, 0, 60, 120]), (50, [-120, -60, 0, 60, 120]),
              (150, [-60, 0, 60])]
    parts = []
    for (x1, ys1), (x2, ys2) in zip(layers, layers[1:]):
        for y1 in ys1:
            for y2 in ys2:
                parts.append(f'<path class="thin" d="M{x1} {y1} L{x2} {y2}"/>')
    for x, ys in layers:
        for y in ys:
            parts.append(f'<circle class="node" cx="{x}" cy="{y}" r="9"/>')
    return "\n".join(parts)


def dna():
    parts = []
    a = " ".join(f"{'M' if i == 0 else 'L'}{55 * math.sin(i / 6):.1f} {-170 + i * 8}" for i in range(43))
    b = " ".join(f"{'M' if i == 0 else 'L'}{-55 * math.sin(i / 6):.1f} {-170 + i * 8}" for i in range(43))
    parts.append(f'<path d="{a}"/><path d="{b}"/>')
    for i in range(2, 43, 3):
        x = 55 * math.sin(i / 6)
        parts.append(f'<path class="thin" d="M{x:.1f} {-170 + i * 8} L{-x:.1f} {-170 + i * 8}"/>')
    return "\n".join(parts)


def chip():
    pins = []
    for i in range(-3, 4):
        o = i * 26
        pins.append(f'<path d="M{o} -110 L{o} -140 M{o} 110 L{o} 140 M-110 {o} L-140 {o} M110 {o} L140 {o}"/>')
    return f"""
    <rect x="-110" y="-110" width="220" height="220" rx="18"/>
    <rect class="core" x="-55" y="-55" width="110" height="110" rx="8"/>
    <path class="thin" d="M-55 -20 L-110 -20 M55 20 L110 20 M-20 55 L-20 110 M20 -55 L20 -110"/>
    {''.join(pins)}
    """


def climate():
    return """
    <circle cx="0" cy="0" r="130"/>
    <ellipse class="thin" cx="0" cy="0" rx="55" ry="130"/>
    <path class="thin" d="M-130 0 L130 0 M-112 -65 L112 -65 M-112 65 L112 65"/>
    <path class="leaf" d="M30 120 C 30 30 100 -10 170 -20 C 170 60 120 120 30 120 Z"/>
    <path d="M30 120 C 70 70 110 30 150 0"/>
    """


def energy():
    return """
    <path d="M-6 -60 L-14 170 L14 170 L6 -60"/>
    <circle cx="0" cy="-70" r="12"/>
    <path d="M0 -82 C 10 -140 6 -180 -4 -200 C -14 -170 -12 -120 0 -82"/>
    <path d="M10 -64 C 60 -40 100 -10 120 10 C 90 14 50 0 10 -64"/>
    <path d="M-10 -64 C -60 -40 -100 -10 -120 10 C -90 14 -50 0 -10 -64"/>
    <circle class="sun" cx="140" cy="-140" r="34"/>
    """


def sprout():
    return """
    <path d="M-160 120 L160 120"/>
    <path d="M0 120 C 0 60 -4 10 0 -40"/>
    <path class="leaf" d="M0 -10 C -20 -70 -80 -90 -130 -80 C -110 -30 -60 -10 0 -10 Z"/>
    <path class="leaf" d="M0 -40 C 20 -110 80 -130 130 -120 C 110 -70 60 -40 0 -40 Z"/>
    <path class="thin" d="M60 70 a 40 40 0 0 1 0 50 M80 55 a 60 60 0 0 1 0 80 M100 40 a 80 80 0 0 1 0 110"/>
    """


def atom():
    return """
    <ellipse cx="0" cy="0" rx="170" ry="60"/>
    <ellipse cx="0" cy="0" rx="170" ry="60" transform="rotate(60)"/>
    <ellipse cx="0" cy="0" rx="170" ry="60" transform="rotate(120)"/>
    <circle class="core" cx="0" cy="0" r="22"/>
    <circle class="node" cx="170" cy="0" r="9"/><circle class="node" cx="-85" cy="-147" r="9"/>
    """


def heart():
    return """
    <path d="M0 140 C -150 40 -170 -40 -120 -100 C -80 -140 -20 -120 0 -80 C 20 -120 80 -140 120 -100 C 170 -40 150 40 0 140 Z"/>
    <path class="pulse" d="M-200 10 L-70 10 L-40 -50 L0 80 L40 -20 L60 10 L200 10"/>
    """


def shield():
    return """
    <path d="M0 -160 L130 -110 L130 10 C 130 90 60 140 0 170 C -60 140 -130 90 -130 10 L-130 -110 Z"/>
    <circle class="thin" cx="0" cy="0" r="40"/><circle class="thin" cx="0" cy="0" r="80"/>
    <path class="sweep" d="M0 0 L80 -20 A 82 82 0 0 0 40 -70 Z"/>
    <circle class="node" cx="44" cy="-40" r="7"/>
    """


def ev():
    return """
    <rect x="-150" y="-70" width="270" height="140" rx="20"/>
    <rect x="120" y="-28" width="26" height="56" rx="6"/>
    <path class="bolt" d="M10 -60 L-50 10 L-5 10 L-20 60 L45 -15 L0 -15 Z"/>
    <path class="thin" d="M-200 120 L200 120"/>
    """


def materials():
    parts = []
    r = 40
    for row in range(-2, 3):
        for col in range(-3, 4):
            cx = col * r * 1.5
            cy = row * r * math.sqrt(3) + (r * math.sqrt(3) / 2 if col % 2 else 0)
            if abs(cx) > 160 or abs(cy) > 160:
                continue
            pts = " ".join(f"{cx + r * math.cos(math.pi / 3 * k):.1f},{cy + r * math.sin(math.pi / 3 * k):.1f}"
                           for k in range(6))
            parts.append(f'<polygon points="{pts}"/>')
            parts.append(f'<circle class="node" cx="{cx + r:.1f}" cy="{cy:.1f}" r="5"/>')
    return "\n".join(parts)


def iot():
    return """
    <circle class="core" cx="0" cy="40" r="18"/>
    <path d="M-60 -20 A 85 85 0 0 1 60 -20"/>
    <path d="M-100 -60 A 140 140 0 0 1 100 -60"/>
    <path d="M-140 -100 A 195 195 0 0 1 140 -100"/>
    <path d="M0 58 L0 150 M-50 150 L50 150"/>
    <circle class="node" cx="-150" cy="110" r="10"/><circle class="node" cx="150" cy="110" r="10"/>
    <path class="thin" d="M-150 110 L0 40 L150 110"/>
    """


def drone():
    return """
    <rect x="-40" y="-26" width="80" height="52" rx="12"/>
    <path d="M-40 -20 L-120 -80 M40 -20 L120 -80 M-40 20 L-120 80 M40 20 L120 80"/>
    <ellipse cx="-120" cy="-80" rx="60" ry="12"/><ellipse cx="120" cy="-80" rx="60" ry="12"/>
    <ellipse cx="-120" cy="80" rx="60" ry="12"/><ellipse cx="120" cy="80" rx="60" ry="12"/>
    <circle class="core" cx="0" cy="40" r="10"/>
    <path class="thin" d="M-60 140 L60 140 M-30 170 L30 170"/>
    """


ART = {
    "spacetech": rocket, "robotics": bot, "ai": ai, "biotech": dna, "semiconductors": chip,
    "climatetech": climate, "clean-energy": energy, "agritech": sprout, "quantum": atom, "medtech": heart,
    "defence": shield, "ev-mobility": ev, "advanced-materials": materials, "iot": iot, "drones": drone,
}


def svg(slug, color, variant):
    rnd = random.Random(f"{slug}-{variant}")
    stars = "".join(
        f'<circle cx="{rnd.uniform(0, W):.0f}" cy="{rnd.uniform(0, H * 0.75):.0f}" r="{rnd.uniform(0.5, 1.8):.1f}" '
        f'fill="#fff" opacity="{rnd.uniform(0.25, 0.9):.2f}"/>' for _ in range(70))
    nodes = [(rnd.uniform(40, W - 40), rnd.uniform(H * 0.55, H - 30)) for _ in range(14)]
    links = []
    for i, (x1, y1) in enumerate(nodes):
        for x2, y2 in nodes[i + 1:]:
            if math.hypot(x2 - x1, y2 - y1) < 170:
                links.append(f'<path d="M{x1:.0f} {y1:.0f} L{x2:.0f} {y2:.0f}"/>')
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.uniform(2, 4):.1f}"/>' for x, y in nodes)

    cx = {1: 400, 2: 560, 3: 250}[variant]
    cy = {1: 220, 2: 230, 3: 215}[variant]
    scale = {1: 0.95, 2: 0.8, 3: 0.85}[variant]
    rot = {1: 0, 2: -8, 3: 6}[variant]
    tint = {1: "#0b1033", 2: "#0d0a2e", 3: "#06142e"}[variant]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#03051a"/><stop offset="0.55" stop-color="{tint}"/><stop offset="1" stop-color="#140a3d"/>
  </linearGradient>
  <radialGradient id="glow" cx="{cx / W:.2f}" cy="{cy / H:.2f}" r="0.5">
    <stop offset="0" stop-color="{color}" stop-opacity="0.55"/><stop offset="1" stop-color="{color}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="horizon" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#2b6cff" stop-opacity="0"/><stop offset="0.5" stop-color="#5aa0ff"/>
    <stop offset="1" stop-color="#2b6cff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="flame" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff3c4"/><stop offset="0.5" stop-color="#ff9a3c"/><stop offset="1" stop-color="#ff4d4d" stop-opacity="0"/>
  </linearGradient>
  <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect width="{W}" height="{H}" fill="url(#glow)"/>
<g>{stars}</g>
<ellipse cx="{W / 2}" cy="{H + 520}" rx="{W * 1.1:.0f}" ry="640" fill="#060b2a" stroke="url(#horizon)" stroke-width="3"/>
<g stroke="{color}" stroke-opacity="0.35" stroke-width="1">{''.join(links)}</g>
<g fill="{color}" opacity="0.9">{dots}</g>
<g transform="translate({cx} {cy}) rotate({rot}) scale({scale})" fill="none" stroke="#e8edff" stroke-width="5"
   stroke-linecap="round" stroke-linejoin="round" filter="url(#soft)">
  <style>
    .thin {{ stroke-width: 2; stroke-opacity: .55; stroke: {color}; }}
    .node {{ fill: {color}; stroke: #fff; stroke-width: 2; }}
    .core {{ fill: {color}; fill-opacity: .35; stroke: {color}; }}
    .leaf {{ fill: {color}; fill-opacity: .3; stroke: {color}; }}
    .flame {{ fill: url(#flame); stroke: none; }}
    .sun {{ fill: #ffcf4a; fill-opacity: .25; stroke: #ffcf4a; }}
    .pulse {{ stroke: {color}; stroke-width: 6; }}
    .sweep {{ fill: {color}; fill-opacity: .35; stroke: none; }}
    .bolt {{ fill: {color}; fill-opacity: .5; stroke: {color}; }}
  </style>
  {ART[slug]()}
</g>
</svg>
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    for slug, color in CATEGORIES.items():
        for variant in (1, 2, 3):
            name = f"{slug}.svg" if variant == 1 else f"{slug}-{variant}.svg"
            with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
                fh.write(svg(slug, color, variant))
    print(f"Wrote {len(CATEGORIES) * 3} covers to {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
