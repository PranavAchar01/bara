from iso import keyboard, svg, part
from base import page, eyes

K, OX, OY = 1.62, 175, 330
body_svg, A = keyboard(k=K, ox=OX, oy=OY, gap=40)
order = [("top", 1), ("keycaps", 2), ("switches", 3), ("mcu", 4), ("pcb", 5), ("case", 6)]
col = 760
extra = ""
lasty = -99
for key, n in order:
    ax, ay = A[key]
    by = max(ay, lasty + 44)
    lasty = by
    extra += f'<polyline points="{ax:.0f},{ay:.0f} {col-60:.0f},{by:.0f} {col-16},{by:.0f}" fill="none" stroke="#161616" stroke-width="0.9"/><circle cx="{ax:.0f}" cy="{ay:.0f}" r="2.5" fill="#161616"/>'
    extra += f'<circle cx="{col}" cy="{by:.0f}" r="16" fill="#fff" stroke="#161616" stroke-width="1.2"/><text x="{col}" y="{by+5:.0f}" text-anchor="middle" font-family="Atkinson Hyperlegible Mono" font-size="14">{n}</text>'
from iso import P
(x0, y0), (x1, y1) = P(0, 100, 0, K, OX, OY), P(290, 100, 0, K, OX, OY)
dx, dy = -12, 24
extra += f'<g stroke="#0a6cff" stroke-width="1"><line x1="{x0:.0f}" y1="{y0:.0f}" x2="{x0+dx:.0f}" y2="{y0+dy+6:.0f}"/><line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x1+dx:.0f}" y2="{y1+dy+6:.0f}"/><line x1="{x0+dx:.0f}" y1="{y0+dy:.0f}" x2="{x1+dx:.0f}" y2="{y1+dy:.0f}"/></g>'
mx, my = (x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy
extra += f'<text x="{mx-24:.0f}" y="{my+18:.0f}" fill="#0a6cff" font-family="Atkinson Hyperlegible Mono" font-size="13" transform="rotate(30 {mx:.0f} {my:.0f})">290 mm</text>'
drawing = svg(body_svg + extra, 800, 720)

rows = [("1", "1", "Case top", "generated", "CERN-OHL-S"), ("2", "61", "DSA keycap, 1u–6.25u", "sourced", "MIT"), ("3", "61", "Cherry MX2A Brown", "sourced", "CC-BY-SA-4.0"),
        ("4", "1", "nice!nano v2", "sourced", "CERN-OHL-P"), ("5", "1", "PCB, routed in KiCad", "generated", "CERN-OHL-S"), ("6", "1", "Case bottom", "generated", "CERN-OHL-S")]
bom = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td class='soft'>{d}</td><td class='mono'>{e}</td></tr>" for a, b, c, d, e in rows)

reg = [("A-014", "a keyboard", "Bakeneko60", "128", "24 OCT", "A"), ("A-013", "a wireless split keyboard with an OLED", "Corne", "96", "24 OCT", "C"),
       ("A-012", "something cool for my desk", "Desk clock", "14", "23 OCT", "A"), ("A-011", "a macropad with one big knob", "Macropad", "22", "23 OCT", "B"),
       ("A-010", "a 60% keyboard with Choc switches", "Choc 60", "120", "23 OCT", "—")]
thumb = lambda: svg(keyboard(k=0.22, ox=52, oy=8, gap=26, sw=0.5, keys=(6, 2))[0], 120, 70)
register = "".join(f"<tr><td class='mono'>{a}</td><td>{thumb()}</td><td class='serif t'>{b}</td><td class='soft'>{c}</td><td class='mono'>{d}</td><td class='mono'>{e}</td><td class='mono'>{f}</td></tr>" for a, b, c, d, e, f in reg)

zones_top = "".join(f"<span>{c}</span>" for c in "ABCDEFGH")
zones_side = "".join(f"<span>{n}</span>" for n in range(1, 6))

css = """
.sheet { position: relative; margin: 28px; border: 1.5px solid #161616; height: 1180px; }
.inner { position: absolute; inset: 14px; border: 0.75px solid #161616; }
.ztop { position: absolute; left: 14px; right: 14px; top: 0; height: 14px; display: flex; justify-content: space-around; font: 9px 'Atkinson Hyperlegible Mono'; line-height: 14px; }
.zside { position: absolute; top: 14px; bottom: 14px; left: 0; width: 14px; display: flex; flex-direction: column; justify-content: space-around; font: 9px 'Atkinson Hyperlegible Mono'; text-align: center; }
.brand { position: absolute; left: 44px; top: 40px; }
.brand h1 { font-size: 40px; line-height: 1; }
.brand p { margin-top: 6px; }
.drawing { position: absolute; left: 30px; top: 150px; }
.notes { position: absolute; left: 44px; bottom: 44px; width: 430px; font-size: 13px; }
.notes ol { margin-top: 8px; padding-left: 18px; }
.notes li { margin-bottom: 4px; }
.bom { position: absolute; right: 44px; top: 40px; width: 420px; border-collapse: collapse; font-size: 13px; }
.bom th { text-align: left; font: 10px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; text-transform: uppercase; color: #5e5e5e; border-bottom: 1px solid #161616; padding: 6px 6px; }
.bom td { border-bottom: 0.75px solid #dcdcdc; padding: 7px 6px; }
.bom caption { text-align: left; padding-bottom: 8px; }
.tb { position: absolute; right: 30px; bottom: 30px; width: 640px; display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; border: 1.5px solid #161616; }
.tb > div { border-right: 0.75px solid #161616; border-bottom: 0.75px solid #161616; padding: 8px 10px; }
.tb .l { font: 9px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; text-transform: uppercase; color: #5e5e5e; display: block; margin-bottom: 4px; }
.tb .title { grid-column: 1 / 4; grid-row: 1 / 3; background: #fff; padding: 12px 14px; }
.tb .title .v { font-size: 30px; line-height: 1.15; }
.tb .title .hint { margin-top: 8px; font-size: 12px; }
.tb .go { grid-column: 4; grid-row: 1 / 3; background: #161616; color: #fff; display: flex; flex-direction: column; justify-content: space-between; padding: 12px 14px; }
.tb .go b { font: 600 20px 'Atkinson Hyperlegible Next'; }
.tb .go .l { color: #b4b4b4; }
.v { font-size: 14px; }
.rev { position: absolute; right: 500px; top: 40px; width: 300px; border-collapse: collapse; font-size: 12px; }
.rev th { text-align: left; font: 9px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; color: #5e5e5e; border-bottom: 1px solid #161616; padding: 4px 6px; }
.rev td { padding: 4px 6px; border-bottom: 0.75px solid #dcdcdc; }
.eyes { position: absolute; right: 690px; bottom: 182px; width: 52px; height: 36px; }
.say { position: absolute; right: 752px; bottom: 186px; font-size: 13px; background: #fff; border: 0.75px solid #161616; padding: 6px 10px; }
.register { margin: 0 28px 60px; }
.register h2 { font-size: 34px; margin: 8px 0 14px; }
.register table { width: 100%; border-collapse: collapse; border-top: 1.5px solid #161616; }
.register th { text-align: left; font: 10px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; text-transform: uppercase; color: #5e5e5e; padding: 8px 10px; border-bottom: 1px solid #161616; }
.register td { padding: 8px 10px; border-bottom: 0.75px solid #dcdcdc; vertical-align: middle; }
.register .t { font-size: 22px; }
.reghead { display: flex; justify-content: space-between; align-items: flex-end; margin: 0 28px; }
"""
body = f"""
<div class="sheet">
  <div class="ztop">{zones_top}</div>
  <div class="zside">{zones_side}</div>
  <div class="inner"></div>
  <div class="brand"><h1 class="serif">Bara</h1><p class="cap">Open hardware, drawn to order</p></div>
  <table class="rev"><tr><th>REV</th><th>CHANGE</th><th>BY</th></tr><tr><td class="mono">A</td><td>First build</td><td>Bara</td></tr><tr><td class="mono">B</td><td>Swap to Silent Reds</td><td>you</td></tr><tr><td class="mono accent">C</td><td class="accent">Thinner case walls</td><td class="accent">you, by voice</td></tr></table>
  <div class="drawing">{drawing}</div>
  <table class="bom"><caption class="cap">Parts list · every part is real and open</caption><tr><th>Item</th><th>Qty</th><th>Description</th><th>Source</th><th>Licence</th></tr>{bom}</table>
  <div class="notes"><span class="cap">Notes</span><ol>
    <li>Reuses an open design when one fits; otherwise composes one from open parts.</li>
    <li>Board routed in KiCad, case generated to fit, firmware written for the pins.</li>
    <li>Every decision is on the drawing. Click a balloon to pull that part out and ask about it.</li></ol></div>
  <div class="say">Write what you want in the title block.</div>
  <div class="eyes">{eyes(52, (5, 4))}</div>
  <div class="tb">
    <div class="title"><span class="l">Title · describe the device</span><div class="v serif">a split keyboard with an OLED<span class="caret" style="height:30px"></span></div><div class="hint soft">Type it, or hold Space and say it.</div></div>
    <div class="go"><span class="l">Press ↵</span><b>Draw it →</b></div>
    <div><span class="l">Drawn by</span><span class="v">Bara</span></div><div><span class="l">Checked</span><span class="v">14 checks</span></div><div><span class="l">Scale</span><span class="v mono">1 : 2</span></div><div><span class="l">Sheet</span><span class="v mono">01 / 01</span></div>
    <div><span class="l">Catalog</span><span class="v">39,451 parts</span></div><div><span class="l">Designs</span><span class="v">129 open</span></div><div><span class="l">Exports</span><span class="v">KiCad · STEP · ZMK</span></div><div><span class="l">Rev</span><span class="v mono accent">C</span></div>
  </div>
</div>
<div class="reghead"><div><span class="cap">Drawing register · 14 sheets</span><h2 class="serif" style="font-size:34px;margin:6px 0 14px">Everything you've drawn</h2></div><span class="cap">Search the register ⌕</span></div>
<div class="register"><table><tr><th>Sheet</th><th></th><th>Title</th><th>Based on</th><th>Parts</th><th>Date</th><th>Rev</th></tr>{register}</table></div>
"""
open("c1_sheet.html", "w").write(page("Drawing sheet", css, body))
print("ok")
