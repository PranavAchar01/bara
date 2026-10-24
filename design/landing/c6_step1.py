import re
from iso import svg, fitted, part, P
from base import page, eyes
from lego_parts import tray, pcb, switches, caps, top, INK

PAGE, CALL, EDGE = "#dde9f2", "#f3f8fb", "#8fa6b8"

def ghost(body):
    """The same drawing as a dashed outline: what will be built here."""
    body = re.sub(r'fill="[^"]+"', 'fill="none"', body)
    body = re.sub(r'stroke="#161616"', 'stroke="#7f95a6" stroke-dasharray="5 4"', body)
    return body

k, ox, oy = 1.75, 240, 210
outline = ghost(tray(k, ox, oy) + top(k, ox, oy) + caps(k, ox, oy, z=24, only=lambda c, r: (c + r) % 3 == 0))
arrow = '<path d="M200 40 C 300 30, 360 80, 380 150" fill="none" stroke="#161616" stroke-width="3.5"/><polygon points="368,146 384,170 394,142" fill="#161616"/>'
drawing = svg(outline + arrow, 900, 520)

def panel(n, body, cap):
    return f"<div class='mini'><span class='mn'>{n}</span>{fitted(body, 250, 130, 10)}<span class='mc'>{cap}</span></div>"
minis = (panel(2, tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0), "Bara picks and places the parts")
         + panel(3, tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + caps(1, 0, 0), "routes the board in KiCad")
         + panel(4, tray(1, 0, 0) + pcb(1, 0, 0) + switches(1, 0, 0) + top(1, 0, 0) + caps(1, 0, 0, z=24), "cases it and writes the firmware"))

css = f"""
body {{ background: {PAGE}; }}
.bar {{ display: flex; justify-content: space-between; align-items: center; padding: 28px 48px 0; }}
.bar .tag {{ background: #161616; color: #fff; padding: 8px 14px 10px; font-family: 'Averia Serif Libre'; font-size: 28px; line-height: 1; letter-spacing: -0.03em; }}
.bar nav {{ display: flex; gap: 0; border: 2px solid #161616; background: #fff; }}
.bar nav span {{ padding: 8px 14px; border-right: 2px solid #161616; font: 11px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.08em; text-transform: uppercase; }}
.bar nav span:last-child {{ border-right: 0; }}
.pagewrap {{ position: relative; height: 820px; margin: 22px 48px 0; }}
.big {{ position: absolute; left: 0; top: 0; font: 800 200px 'Atkinson Hyperlegible Next'; line-height: 0.8; letter-spacing: -0.06em; }}
.call {{ position: absolute; left: 190px; top: 6px; width: 560px; background: {CALL}; border: 2px solid {EDGE}; border-radius: 4px; padding: 14px 16px 16px; }}
.call .row {{ display: flex; align-items: flex-end; gap: 14px; }}
.call .q {{ font: 800 30px 'Atkinson Hyperlegible Next'; line-height: 1; }}
.call .idea {{ flex: 1; background: #fff; border: 2px solid #161616; padding: 12px 14px; }}
.call .idea .l {{ font: 10px 'Atkinson Hyperlegible Mono'; letter-spacing: 0.1em; color: #5e5e5e; }}
.call .idea .v {{ font-family: 'Averia Serif Libre'; font-size: 32px; line-height: 1.12; letter-spacing: -0.02em; margin-top: 4px; }}
.call .hint {{ margin-top: 10px; display: flex; justify-content: space-between; font-size: 13px; color: #3b4650; }}
.call .eyes {{ position: absolute; right: -30px; top: -26px; }}
.drawing {{ position: absolute; left: 120px; top: 170px; }}
.next {{ position: absolute; right: 0; bottom: 30px; display: flex; align-items: center; gap: 0; background: #161616; color: #fff; }}
.next b {{ font: 700 22px 'Atkinson Hyperlegible Next'; padding: 18px 24px; }}
.next span {{ font: 12px 'Atkinson Hyperlegible Mono'; color: #b4b4b4; padding-right: 24px; }}
.ahead {{ position: absolute; right: 0; top: 0; width: 290px; display: flex; flex-direction: column; gap: 10px; opacity: 0.72; }}
.ahead .cap {{ margin-bottom: 2px; }}
.mini {{ position: relative; background: {CALL}; border: 1.5px solid {EDGE}; border-radius: 4px; padding: 6px 10px 10px 34px; }}
.mn {{ position: absolute; left: 10px; top: 6px; font: 800 28px 'Atkinson Hyperlegible Next'; }}
.mc {{ display: block; font-size: 12px; color: #3b4650; }}
.pn {{ position: absolute; left: 0; bottom: 30px; font: 700 16px 'Atkinson Hyperlegible Next'; }}
.facts {{ position: absolute; left: 120px; bottom: 34px; display: flex; gap: 36px; font-size: 13px; color: #3b4650; }}
.facts b {{ display: block; color: #161616; font: 800 24px 'Atkinson Hyperlegible Next'; }}
"""
body = f"""
<div class="bar"><span class="tag">Bara</span><nav><span>Your sets</span><span>How it builds</span><span>Parts catalog</span><span>GitHub</span></nav></div>
<div class="pagewrap">
  <div class="big">1</div>
  <div class="call">
    <div class="row"><span class="q">1×</span><div class="idea"><span class="l">YOUR IDEA</span><div class="v">a keyboard quiet enough for a library<span class="caret" style="height:30px"></span></div></div></div>
    <div class="hint"><span>Type what you want, or hold Space and say it.</span><span class="mono">↵ next page</span></div>
    <span class="eyes">{eyes(60, (-10, 8))}</span>
  </div>
  <div class="drawing">{drawing}</div>
  <div class="ahead"><span class="cap">Then, in about twenty seconds</span>{minis}</div>
  <div class="facts"><span><b>39,451</b>real parts</span><span><b>129</b>open designs</span><span><b>14</b>checks per build</span></div>
  <div class="pn">1</div>
  <div class="next"><b>Build it →</b><span>↵</span></div>
</div>
"""
open("c6_step1.html", "w").write(page("Bara step one", css, body))
print("ok")
