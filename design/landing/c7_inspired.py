from iso import keyboard, svg, fitted, part, P
from base import page, bot
from lego_parts import tray, pcb, switches, caps, top, INK

# hero: exploded build with manual cues (drop arrows between layers, part counts)
K, OX, OY = 1.55, 170, 312
body, A = keyboard(k=K, ox=OX, oy=OY, gap=42)
def drop(x, y, n=40):
    return (f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+n-10}" stroke="{INK}" stroke-width="1.6"/>'
            f'<polygon points="{x-5},{y+n-12} {x+5},{y+n-12} {x},{y+n}" fill="{INK}"/>')
def tag(x, y, t):
    return (f'<rect x="{x}" y="{y-15}" width="{len(t)*8+14}" height="22" fill="#fff" stroke="{INK}" stroke-width="1"/>'
            f'<text x="{x+7}" y="{y+1}" font-family="Atkinson Hyperlegible Next" font-weight="800" font-size="13">{t}</text>')
cues = ""
for key, t, dx in (("keycaps", "61×", 40), ("switches", "61×", 40), ("mcu", "1×", 120)):
    ax, ay = A[key]
    cues += f'<line x1="{ax:.0f}" y1="{ay:.0f}" x2="{ax+dx:.0f}" y2="{ay-6:.0f}" stroke="{INK}" stroke-width="0.8"/>' + tag(ax + dx, ay - 6, t)
# drop arrows beside the stack, one in each gap between layers (top -> caps -> switches -> board)
for z0, z1 in ((178, 146), (134, 104), (92, 62)):
    x0, y0 = P(-16, 70, z0, K, OX, OY)
    x1, y1 = P(-16, 70, z1, K, OX, OY)
    cues += f'<line x1="{x0:.0f}" y1="{y0:.0f}" x2="{x1:.0f}" y2="{y1-10:.0f}" stroke="{INK}" stroke-width="1.6"/><polygon points="{x1-5:.0f},{y1-12:.0f} {x1+5:.0f},{y1-12:.0f} {x1:.0f},{y1:.0f}" fill="{INK}"/>'
hero = svg(body + cues, 760, 630)

# how it builds: four steps in a row
def mini(b):
    return fitted(b, 270, 150, 12)
steps = [
    ("1", "You say what you want", "One line, typed or said out loud.", None, [("1×", "your idea")]),
    ("2", "Real parts are picked", "From 39,451 open parts, each with its licence; an open design first if one fits.", mini(tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0)), [("61×", "switch"), ("1×", "controller")]),
    ("3", "The board is routed", "A real KiCad board under the keys, ready to order.", mini(tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + caps(1, 0, 0)), [("1×", "PCB"), ("61×", "keycap")]),
    ("4", "Cased and flashed", "A case shaped to fit, firmware for the exact pins, fourteen checks.", mini(tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + top(1, 0, 0) + caps(1, 0, 0, z=24)), [("1×", "case"), ("1×", "firmware")]),
]
cells = ""
for n, t, d, drawing, need in steps:
    chips = "".join(f"<span class='need'><b>{q}</b> {w}</span>" for q, w in need)
    art = drawing or f"<div class='idea'><span class='serif'>“a keyboard quiet enough for a library”</span></div>"
    cells += f"<div class='step'><div class='sh'><span class='n'>{n}</span><div class='needs'>{chips}</div></div><div class='art'>{art}</div><b class='st'>{t}</b><p class='soft'>{d}</p></div>"

# your builds
lib = [("a keyboard", "Bakeneko60 · 128 parts", "2 min ago"), ("a wireless split keyboard with an OLED", "Corne · 96 parts", "yesterday"),
       ("something cool for my desk", "Desk clock · 14 parts", "yesterday"), ("a macropad with one big knob", "Macropad · 22 parts", "Fri 23 Oct")]
thumb = fitted(tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + top(1, 0, 0) + caps(1, 0, 0, z=24), 300, 170, 26)
cards = "".join(f"<div class='card'><div class='th'>{thumb}<span class='no mono'>No. {14-i:03d}</span></div><div class='cm'><span class='serif ct'>{t}</span><span class='soft cs'>{m} · {w}</span></div></div>" for i, (t, m, w) in enumerate(lib))

css = """
.nav { display: flex; justify-content: space-between; align-items: center; padding: 26px 56px; }
.nav .brand { font-size: 28px; }
.nav nav { display: flex; gap: 28px; }
.hero { display: grid; grid-template-columns: 560px 1fr; gap: 20px; padding: 40px 56px 30px; align-items: start; }
.hero h1 { font-size: 78px; line-height: 0.95; letter-spacing: -0.04em; margin-top: 40px; }
.hero .sub { margin-top: 20px; font-size: 17px; color: #5e5e5e; max-width: 470px; }
.ask { margin-top: 40px; display: grid; grid-template-columns: 64px 1fr; gap: 14px; align-items: start; }
.ask .one { font: 800 74px 'Atkinson Hyperlegible Next'; line-height: 0.8; letter-spacing: -0.05em; }
.field { border: 1.5px solid #161616; border-radius: 2px; background: #fff; }
.field .row { display: flex; align-items: center; gap: 12px; padding: 12px 12px 12px 14px; }
.field .v { flex: 1; font-family: 'Averia Serif Libre'; font-size: 24px; letter-spacing: -0.02em; line-height: 1.2; }
.field .go { background: #161616; color: #fff; padding: 10px 16px; font-weight: 600; white-space: nowrap; }
.field .foot { display: flex; justify-content: space-between; border-top: 1px solid #dcdcdc; padding: 7px 14px; font-size: 12px; color: #5e5e5e; }
.try { margin-top: 16px; padding-left: 78px; display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 14px; }
.try span { border-bottom: 1px solid #b4b4b4; }
.facts { margin-top: 34px; padding-left: 78px; display: flex; gap: 34px; }
.facts b { display: block; font: 800 26px 'Atkinson Hyperlegible Next'; letter-spacing: -0.02em; }
.facts span { font-size: 13px; color: #5e5e5e; }
.how { margin: 30px 56px 0; border-top: 1.5px solid #161616; padding-top: 16px; }
.how .h { display: flex; justify-content: space-between; align-items: baseline; }
.how h2 { font-size: 44px; letter-spacing: -0.035em; }
.steps { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 20px; }
.step { padding: 0 22px 10px; border-left: 1px solid #dcdcdc; }
.step:first-child { padding-left: 0; border-left: 0; }
.sh { display: flex; align-items: flex-start; gap: 12px; }
.sh .n { font: 800 54px 'Atkinson Hyperlegible Next'; line-height: 0.85; letter-spacing: -0.05em; }
.needs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.need { border: 1px solid #161616; padding: 2px 8px; font-size: 12px; }
.need b { font-weight: 800; }
.art { height: 160px; display: flex; align-items: center; margin: 10px 0 8px; }
.idea { border: 1px dashed #8fa6b8; padding: 16px; width: 100%; height: 130px; display: flex; align-items: center; }
.idea .serif { font-size: 22px; line-height: 1.2; }
.st { display: block; font-size: 17px; font-weight: 600; }
.step p { font-size: 14px; margin-top: 4px; line-height: 1.4; }
.lib { margin: 60px 56px 90px; border-top: 1.5px solid #161616; padding-top: 16px; }
.lib .h { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px; }
.lib h2 { font-size: 44px; letter-spacing: -0.035em; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.card { border: 1px solid #dcdcdc; }
.th { position: relative; background: #f6f6f5; border-bottom: 1px solid #dcdcdc; }
.th .no { position: absolute; left: 10px; top: 8px; font-size: 11px; color: #5e5e5e; }
.cm { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 6px; }
.ct { font-size: 21px; line-height: 1.12; letter-spacing: -0.02em; }
.cs { font-size: 13px; }
"""
body_html = f"""
<div class="nav"><span class="serif brand">Bara</span><nav class="cap"><span>Your builds</span><span>How it builds</span><span>Parts</span><span>GitHub ↗</span></nav></div>
<section class="hero">
  <div>
    <h1 class="serif">Describe a device. Get it built from real parts.</h1>
    <p class="sub">Bara picks open parts, routes the board, shapes the case and writes the firmware, and shows every step.</p>
    <div class="ask"><span class="one">1</span>
      <div class="field"><div class="row">{bot(46)}<span class="v">a keyboard quiet enough for a library<span class="caret" style="height:24px"></span></span><span class="go">Build ↵</span></div>
      <div class="foot"><span>Type it, or hold Space and say it</span><span class="mono">step 1 of 4</span></div></div></div>
    <div class="try"><span>a split keyboard with an OLED</span><span>a macropad with one big knob</span><span>something cool for my desk</span></div>
    <div class="facts"><div><b>39,451</b><span>real parts</span></div><div><b>129</b><span>open designs</span></div><div><b>~20 s</b><span>to a full build</span></div></div>
  </div>
  <div>{hero}</div>
</section>
<section class="how"><div class="h"><h2 class="serif">How it builds</h2><span class="cap">Four steps, every one shown as it happens</span></div><div class="steps">{cells}</div></section>
<section class="lib"><div class="h"><h2 class="serif">Your builds</h2><span class="cap">Search ⌕ · 14 saved in this browser</span></div><div class="cards">{cards}</div></section>
"""
open("c7_inspired.html", "w").write(page("Bara", css, body_html))
print("ok")
