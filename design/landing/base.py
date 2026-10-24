FONTS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1440px; background: #ffffff; color: #161616; font-family: 'Atkinson Hyperlegible Next', sans-serif; font-size: 15px; line-height: 1.5; letter-spacing: -0.01em; }
.serif { font-family: 'Averia Serif Libre', serif; letter-spacing: -0.03em; font-weight: 400; }
.mono { font-family: 'Atkinson Hyperlegible Mono', monospace; letter-spacing: 0.02em; }
.cap { font-family: 'Atkinson Hyperlegible Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #5e5e5e; }
.soft { color: #5e5e5e; } .faint { color: #b4b4b4; } .accent { color: #0a6cff; }
.caret { display: inline-block; width: 3px; background: #0a6cff; vertical-align: -0.12em; }
"""
def page(title, css, body):
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>{FONTS}{css}</style></head><body>{body}</body></html>"""

def eyes(w=44, look=(3, 0)):
    h = w * 0.7
    ex, ey = look
    return f"""<svg width="{w}" height="{h:.0f}" viewBox="0 0 88 62"><ellipse cx="44" cy="31" rx="44" ry="31" fill="#161616"/><ellipse cx="{30+ex}" cy="{31+ey}" rx="7" ry="11" fill="#fff"/><ellipse cx="{58+ex}" cy="{31+ey}" rx="7" ry="11" fill="#fff"/></svg>"""


def bot(w=44, ink="#161616", paper="#ffffff", look=(0, 0)):
    """Bara exactly as the site draws it (BaraBot idle): an 88x62 stadium with two 13x19 rounded eyes,
    25 apart. Coordinates are pre-scaled (no viewBox scaling, which html_to_figma drops)."""
    s = w / 88
    h = 62 * s
    ew, eh = 13 * s, 19 * s
    gx, gy = look[0] * 9 * s, look[1] * 6 * s
    eyes = "".join(
        f'<rect x="{w/2 + side*12.5*s - ew/2 + gx:.2f}" y="{h/2 - eh/2 + gy:.2f}" width="{ew:.2f}" height="{eh:.2f}" rx="{ew/2:.2f}" fill="{paper}"/>'
        for side in (-1, 1))
    return f'<svg width="{w:.0f}" height="{h:.0f}"><rect x="0" y="0" width="{w:.2f}" height="{h:.2f}" rx="{h/2:.2f}" fill="{ink}"/>{eyes}</svg>'
