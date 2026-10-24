from iso import svg, part, box, P, keyboard, fitted
from base import page, eyes
from lego_parts import tray, pcb, switches, caps, top, arrow_down, INK

PAGE = "#dde9f2"     # manual page blue
CALL = "#f3f8fb"     # parts callout
EDGE = "#8fa6b8"

# ---------------------------------------------------------------- cover (box art)
K, OX, OY = 2.05, 250, 230
hero = tray(K, OX, OY) + pcb(K, OX, OY) + switches(K, OX, OY) + top(K, OX, OY) + caps(K, OX, OY, z=24)
shadow = f'<ellipse cx="560" cy="560" rx="380" ry="60" fill="#000" opacity="0.10"/>'
shadow = '<ellipse cx="470" cy="520" rx="330" ry="52" fill="#000" opacity="0.10"/>'
hero_svg = svg(shadow + hero, 860, 600)
dims = fitted(tray(1, 0, 0) + top(1, 0, 0), 150, 90, 8)

# ---------------------------------------------------------------- steps
def callout(items):
    cells = "".join(f"<div class='pc'>{fitted(part(kd), w, h)}<span class='qty'>{q}×</span></div>" for kd, q, kk, w, h in items)
    return f"<div class='callout'>{cells}</div>"

k = 1.25
s1 = svg(tray(k, 120, 120, z=0) + pcb(k, 120, 120, z=46) + arrow_down(260, 40, 64), 560, 340)
s2 = svg(tray(k, 120, 120) + pcb(k, 120, 120) + switches(k, 120, 120, only=lambda c, r: not (c == 9 and r == 1))
         + switches(k, 120, 120, only=lambda c, r: c == 9 and r == 1, lift=38) + arrow_down(318, 40, 44, 12), 560, 340)
s3 = svg(tray(k, 120, 120) + pcb(k, 120, 120) + switches(k, 120, 120) + caps(k, 120, 120, only=lambda c, r: r < 3 or c < 6)
         + caps(k, 120, 120, only=lambda c, r: r >= 3 and c >= 6, lift=34) + arrow_down(360, 36, 46, 12), 560, 340)
xx, yy = P(290, 20, 8, k, 120, 120)
cable = f'<path d="M{xx:.0f},{yy:.0f} C {xx+50:.0f},{yy+10:.0f} {xx+30:.0f},{yy-70:.0f} {xx+80:.0f},{yy-86:.0f}" stroke="{INK}" stroke-width="3" fill="none"/><rect x="{xx+70:.0f}" y="{yy-140:.0f}" width="78" height="50" fill="#fff" stroke="{INK}" stroke-width="1.5"/><text x="{xx+109:.0f}" y="{yy-110:.0f}" text-anchor="middle" font-family="Atkinson Hyperlegible Mono" font-size="12">ZMK ✓</text>'
s4 = svg(tray(k, 120, 120) + pcb(k, 120, 120) + switches(k, 120, 120) + caps(k, 120, 120) + top(k, 120, 120, z=60) + arrow_down(200, 20, 50, 14) + cable, 560, 340)

# sub-assembly: the board being routed (top view traces)
traces = "".join(f'<path d="M{20+i*16},{20} v{30+(i%3)*12} h{14} v{40}" stroke="#0a6cff" stroke-width="1.6" fill="none"/>' for i in range(9))
pads = "".join(f'<rect x="{18+i*16}" y="16" width="5" height="5" fill="{INK}"/>' for i in range(9))
sub = svg(f'<rect x="8" y="8" width="164" height="104" fill="#e9ecef" stroke="{INK}"/>{traces}{pads}', 180, 120)
subarrow = '<svg width="70" height="60" viewBox="0 0 70 60"><path d="M66 4 C 40 6, 22 20, 16 44" fill="none" stroke="#161616" stroke-width="3"/><polygon points="6,40 16,58 26,40" fill="#161616"/></svg>'
rot = '<svg width="54" height="54" viewBox="0 0 54 54"><rect x="1" y="1" width="52" height="52" fill="#fff" stroke="#161616" stroke-width="1.5"/><path d="M14 30 a13 13 0 1 0 6 -15" fill="none" stroke="#161616" stroke-width="3"/><polygon points="20,8 26,16 16,18" fill="#161616"/></svg>'

steps = f"""
<div class="pg">
  <div class="step"><div class="sn">1</div>{callout([("case", 1, 0.9, 128, 70), ("pcb", 1, 0.9, 128, 70)])}
    <div class="draw">{s1}</div><p class="does"><b>Bara picks the parts.</b> Your words become a spec, an open design if one fits, and real parts from 39,451.</p></div>
  <div class="step"><div class="sn">2</div>{callout([("switch", 61, 1.7, 84, 76)])}
    <div class="draw">{s2}</div><p class="does"><b>Places every one.</b> Where a hand would: keys on a grid, the controller where the cable can reach.</p></div>
  <div class="pn">2</div>
</div>
<div class="pg">
  <div class="step"><div class="sn">3</div>{callout([("keycap", 61, 1.5, 84, 76), ("stab", 5, 1.2, 100, 76)])}
    <div class="sub"><span class="subn">1</span>{sub}<span class="subcap mono">routed in KiCad</span><span class="subarrow">{subarrow}</span></div>
    <div class="draw">{s3}</div><p class="does"><b>Routes the board.</b> A real KiCad board, traces and all, under the caps.</p></div>
  <div class="step"><div class="sn">4</div>{callout([("case", 1, 0.9, 128, 70), ("mcu", 1, 1.3, 84, 76)])}<div class="rot">{rot}<span class="mono">turn it over to plug in</span></div>
    <div class="draw">{s4}</div><p class="does"><b>Cases and flashes it.</b> A case shaped to fit, firmware for the exact pins, fourteen checks.</p></div>
  <div class="pn">3</div>
</div>
"""

# ---------------------------------------------------------------- inventory
inv = [("keycap", "61", "DSA keycap 1u–6.25u", "MIT", 1.5), ("switch", "61", "Cherry MX2A Brown", "CC-BY-SA-4.0", 1.7), ("stab", "5", "MX stabilizer 2u", "CC-BY-SA-4.0", 1.2),
       ("mcu", "1", "nice!nano v2", "CERN-OHL-P", 1.3), ("pcb", "1", "PCB, routed in KiCad", "generated · OHL-S", 0.9), ("case", "1", "Case top", "generated · OHL-S", 0.9),
       ("case", "1", "Case bottom", "generated · OHL-S", 0.9), ("oled", "0", "SSD1306 OLED", "not in this set", 1.6)]
tiles = "".join(f"<div class='tile{' off' if q == '0' else ''}'>{fitted(part(kd), 130, 80, 10)}<span class='tq'>{q}×</span><span class='tn'>{n}</span><span class='tl mono'>{l}</span></div>" for kd, q, n, l, kk in inv)

# ---------------------------------------------------------------- your sets
sets = [("014", "a keyboard", 128, "#161616"), ("013", "a wireless split keyboard with an OLED", 96, "#0a6cff"), ("012", "something cool for my desk", 14, "#5b5f66"),
        ("011", "a macropad with one big knob", 22, "#161616"), ("010", "a 60% keyboard with Choc switches", 120, "#5b5f66")]
mini = lambda: fitted(tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + top(1, 0, 0) + caps(1, 0, 0, z=24), 230, 120, 14)
boxes = "".join(f"<div class='setbox'><div class='band' style='background:{c}'><span class='sb'>Bara</span><span class='num'>{n}</span></div><div class='art'>{mini()}</div><div class='meta'><span class='serif st'>{t}</span><span class='mono pcs'>{p} pcs</span></div></div>" for n, t, p, c in sets)

css = f"""
body {{ background: #c9d8e4; }}
.cover {{ position: relative; height: 900px; background: linear-gradient(180deg, #e9f1f7 0%, #d4e3ee 100%); overflow: hidden; border-bottom: 10px solid #161616; }}
.cover .tag {{ position: absolute; left: 48px; top: 40px; background: #161616; color: #fff; padding: 10px 16px 12px; font-family: 'Averia Serif Libre'; font-size: 34px; letter-spacing: -0.03em; line-height: 1; }}
.cover .setno {{ position: absolute; right: 48px; top: 40px; display: flex; border: 2px solid #161616; background: #fff; }}
.cover .setno > div {{ padding: 8px 16px; border-right: 2px solid #161616; display: flex; flex-direction: column; justify-content: center; }}
.cover .setno > div:last-child {{ border-right: 0; }}
.cover .setno b {{ font: 800 40px 'Atkinson Hyperlegible Next'; line-height: 1; }}
.cover .setno span {{ font: 10px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.1em; color: #5e5e5e; text-transform: uppercase; }}
.cover .hero {{ position: absolute; right: 40px; top: 150px; }}
.cover .ask {{ position: absolute; left: 48px; top: 190px; width: 470px; }}
.cover .ask h1 {{ font-size: 76px; line-height: 0.93; letter-spacing: -0.04em; }}
.cover .label {{ margin-top: 34px; background: #fff; border: 2px solid #161616; padding: 14px 18px 16px; }}
.cover .label .l {{ font: 10px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.1em; color: #5e5e5e; }}
.cover .label .v {{ font-family: 'Averia Serif Libre'; font-size: 30px; line-height: 1.15; letter-spacing: -0.02em; margin-top: 6px; }}
.cover .open {{ display: flex; justify-content: space-between; align-items: center; margin-top: 10px; background: #161616; color: #fff; padding: 16px 18px; font: 700 20px 'Atkinson Hyperlegible Next'; }}
.cover .open span {{ font: 12px 'Atkinson Hyperlegible Mono'; color: #b4b4b4; }}
.cover .hint {{ margin-top: 10px; font-size: 13px; color: #5e5e5e; }}
.cover .dims {{ position: absolute; right: 48px; bottom: 40px; background: #fff; border: 2px solid #161616; padding: 8px 14px 10px; display: flex; gap: 12px; align-items: center; }}
.cover .dims b {{ font: 700 18px 'Atkinson Hyperlegible Next'; display: block; }}
.cover .side {{ position: absolute; left: 48px; bottom: 40px; display: flex; gap: 0; border: 2px solid #161616; background: #fff; }}
.cover .side span {{ padding: 8px 14px; border-right: 2px solid #161616; font: 11px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; text-transform: uppercase; }}
.cover .side span:last-child {{ border-right: 0; }}
.cover .peek {{ position: absolute; left: 520px; bottom: 110px; display: flex; align-items: center; gap: 10px; }}
.cover .peek .say {{ background: #fff; border: 2px solid #161616; padding: 6px 10px; font-size: 13px; }}
.bagbar {{ display: flex; align-items: baseline; gap: 18px; padding: 46px 56px 18px; }}
.bagbar h2 {{ font-size: 48px; letter-spacing: -0.035em; }}
.spread {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin: 0 56px; }}
.pg {{ position: relative; background: {PAGE}; padding: 26px 26px 54px; display: flex; flex-direction: column; gap: 22px; }}
.step {{ position: relative; background: transparent; min-height: 470px; }}
.sn {{ font: 800 86px 'Atkinson Hyperlegible Next'; line-height: 0.85; letter-spacing: -0.04em; }}
.callout {{ position: absolute; left: 96px; top: 0; display: flex; gap: 6px; background: {CALL}; border: 1.5px solid {EDGE}; border-radius: 4px; padding: 6px 10px; }}
.pc {{ position: relative; }}
.pc {{ display: flex; flex-direction: column; align-items: flex-start; }}
.qty {{ font: 800 16px 'Atkinson Hyperlegible Next'; margin-top: -4px; }}
.draw {{ margin-top: 6px; }}
.does {{ font-size: 14px; color: #3b4650; max-width: 520px; }}
.does b {{ color: #161616; }}
.sub {{ position: absolute; right: 8px; top: 96px; background: {CALL}; border: 1.5px solid {EDGE}; border-radius: 4px; padding: 8px 10px 8px; z-index: 2; }}
.sub .subn {{ font: 800 26px 'Atkinson Hyperlegible Next'; position: absolute; left: 8px; top: 2px; }}
.sub .subcap {{ display: block; font-size: 11px; text-align: right; color: #3b4650; }}
.sub .subarrow {{ position: absolute; left: -58px; bottom: -48px; }}
.rot {{ position: absolute; right: 10px; top: 100px; display: flex; align-items: center; gap: 8px; font-size: 11px; color: #3b4650; }}
.pn {{ position: absolute; bottom: 16px; right: 22px; font: 700 15px 'Atkinson Hyperlegible Next'; }}
.pg:first-child .pn {{ right: auto; left: 22px; }}
.inv {{ margin: 6px 56px 0; background: {PAGE}; padding: 26px 26px 54px; position: relative; }}
.inv h3 {{ font: 700 16px 'Atkinson Hyperlegible Next'; margin-bottom: 14px; }}
.tiles {{ display: grid; grid-template-columns: repeat(8, 1fr); gap: 6px; }}
.tile {{ background: {CALL}; border: 1.5px solid {EDGE}; border-radius: 4px; padding: 6px 8px 10px; display: flex; flex-direction: column; }}
.tile.off {{ opacity: 0.45; }}
.tq {{ font: 800 22px 'Atkinson Hyperlegible Next'; }}
.tn {{ font-size: 13px; line-height: 1.25; }}
.tl {{ font-size: 10px; color: #3b4650; margin-top: 4px; }}
.sets {{ padding: 60px 56px 90px; }}
.sets h2 {{ font-size: 48px; letter-spacing: -0.035em; margin: 6px 0 24px; }}
.shelf {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 18px; }}
.setbox {{ background: #fff; border: 2px solid #161616; display: flex; flex-direction: column; }}
.setbox .band {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; color: #fff; }}
.setbox .sb {{ font-family: 'Averia Serif Libre'; font-size: 18px; }}
.setbox .num {{ font: 800 22px 'Atkinson Hyperlegible Next'; }}
.setbox .art {{ background: linear-gradient(180deg, #e9f1f7, #d4e3ee); border-bottom: 2px solid #161616; }}
.setbox .meta {{ padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 6px; min-height: 92px; justify-content: space-between; }}
.setbox .st {{ font-size: 19px; line-height: 1.12; letter-spacing: -0.02em; }}
.setbox .pcs {{ font-size: 12px; color: #5e5e5e; }}
.setshead {{ display: flex; justify-content: space-between; align-items: flex-end; }}
"""
body = f"""
<section class="cover">
  <div class="tag">Bara</div>
  <div class="setno"><div><span>Set</span><b>015</b></div><div><span>Pieces</span><b>128</b></div><div><span>Ages</span><b>you+</b></div></div>
  <div class="ask">
    <h1 class="serif">Any device, built from real parts.</h1>
    <div class="label"><span class="l">WHAT'S IN THE BOX?</span><div class="v">a keyboard, sixty percent, with brown switches<span class="caret" style="height:28px"></span></div></div>
    <div class="open">Open the box <span>↵</span></div>
    <p class="hint">Type it, or hold Space and say it. Bara writes the instructions as it builds.</p>
  </div>
  <div class="hero">{hero_svg}</div>
  <div class="peek">{eyes(54, (-10, 6))}<span class="say">I'll start with the parts.</span></div>
  <div class="side"><span>Real parts</span><span>Open source</span><span>KiCad board</span><span>Fitted case</span><span>Firmware</span></div>
  <div class="dims">{dims}<div><b>29 × 10 × 3 cm</b><span class="mono" style="font-size:11px;color:#5e5e5e">built to fit, 1:1</span></div></div>
</section>
<div class="bagbar"><span class="cap">Inside every box</span><h2 class="serif">How Bara builds it</h2></div>
<section class="spread">{steps}</section>
<section class="inv"><h3>Every piece in this set, with its licence</h3><div class="tiles">{tiles}</div><div class="pn">4</div></section>
<section class="sets"><div class="setshead"><div><span class="cap">Your sets · 14</span><h2 class="serif">Back on the shelf</h2></div><span class="cap">Search your sets ⌕</span></div><div class="shelf">{boxes}</div></section>
"""
open("c5_manual.html", "w").write(page("Bara manual", css, body))
print("ok")
