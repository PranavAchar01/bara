import base64, io
from PIL import Image
from base import page, bot

SHOTS = "/Users/NithinAwasome/Downloads/CODE/bara-figma-ui/web/screenshots/"
BLUE, INK, OK = "#0a6cff", "#161616", "#2e9e5b"

def crop(name, box, width):
    im = Image.open(SHOTS + name).convert("RGB").crop(box)
    h = round(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), h

CROP = (0, 210, 920, 830)            # macropad hero, canvas area without HUD and dock
CW = 808                              # canvas width in the hero window
canvas_src, CH = crop("render-v4-c3-macropad-hero.png", CROP, CW)
K = CW / 920                          # crop px -> canvas px

def R(x, y, w, h, k=K):
    return dict(x=x * k, y=y * k, w=w * k, h=h * k)

cursor_svg = f'<svg width="16" height="20" viewBox="0 0 16 20"><path d="M1.5 1.5v15.2l4.1-3.9 2.7 6.1 2.6-1.1-2.7-6h5.7z" fill="{INK}" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></svg>'

def sel(r, label, color=BLUE, extra="", chip_below=False):
    """The agent's Figma-like selection: frame, four handles, label chip."""
    x, y, w, h = r["x"], r["y"], r["w"], r["h"]
    hs = "".join(f'<i class="hd" style="left:{hx-4:.0f}px;top:{hy-4:.0f}px;border-color:{color}"></i>' for hx, hy in ((0, 0), (w, 0), (0, h), (w, h)))
    chip_top = h + 6 if chip_below else -24
    return (f'<div class="sel" style="left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;border-color:{color};background:{color}0d">{hs}'
            f'<span class="chip" style="top:{chip_top:.0f}px;background:{color}">{label}</span>{extra}</div>')

# ---------------------------------------------------------------- hero window
oled = R(532, 238, 228, 130)
done_marks = "".join(f'<span class="okmark" style="left:{x*K:.0f}px;top:{y*K:.0f}px">✓</span>' for x, y in ((300, 150), (420, 210), (330, 330)))
agent = (sel(oled, "Placing SSD1306 OLED")
         + f'<span class="cur" style="left:{oled["x"]+26:.0f}px;top:{oled["y"]+40:.0f}px">{cursor_svg}</span>'
         + f'<span class="stagebot" style="left:{oled["x"]-64:.0f}px;top:{oled["y"]-46:.0f}px">{bot(44)}</span>'
         + done_marks)
trail = (f'<svg class="trail" width="1328" height="620"><path d="M 200 236 C 320 236, 380 120, {220+oled["x"]-50:.0f} {oled["y"]+20:.0f}" fill="none" stroke="{BLUE}" stroke-width="1.5" stroke-dasharray="3 5"/></svg>')

layers = [("Switches", [("Gateron Yellow (MX)", "×9", "done")]), ("Keycaps", [("DSA 1u keycap", "×9", "done")]), ("Controller", [("RP2040 Zero", "×1", "done")]),
          ("Display", [("SSD1306 OLED 0.91″", "×1", "now")]), ("Input", [("EC11 encoder + knob", "×1", "done")]), ("Board", [("PCB, routing next", "×1", "wait")]), ("Case", [("Case, after the board", "×1", "wait")])]
lrows = ""
for g, items in layers:
    lrows += f"<div class='lg'>{g}</div>"
    for n, q, st in items:
        lrows += f"<div class='lr {st}'><i class='dot'></i><span class='ln'>{n}</span><span class='lq mono'>{q}</span></div>"
pipe = [("Understand", "3.1 s", "ok"), ("Find design", "0.4 s", "ok"), ("Choose parts", "7.4 s", "ok"), ("Place", "", "now"), ("Case", "", "wait"), ("Board", "", "wait"), ("Firmware", "", "wait"), ("Check", "", "wait")]
prows = "".join(f"<div class='pr {st}'><i class='dot'></i><span>{n}</span><span class='mono pt'>{t}</span>{'<span class=bar><i></i></span>' if st=='now' else ''}</div>" for n, t, st in pipe)

window = f"""
<div class="win">
  <aside class="wl">
    <div class="fh"><span class="serif fb">Bara</span><span class="sep">/</span><span class="fp">a macropad with one big knob and a little screen</span></div>
    <div class="fm mono"><span>b_k7Q2…</span><span class="pill run">RUNNING</span></div>
    <div class="sp"><span class="dots">{"<i class='d ok'></i>"*3}<i class='d now'></i>{"<i class='d'></i>"*4}</span><span class="cap">Place</span></div>
    <div class="lh"><span class="cap">Layers</span><span class="mono lc">7 lines · 23 pcs</span></div>
    {lrows}
  </aside>
  <div class="wc">
    <img src="{canvas_src}" width="{CW}" height="{CH}">
    {agent}
    <div class="dock"><span class="home-slot"></span><span class="ph">Bara is building. Ask about anything you see…</span><span class="dbtn">Stop</span></div>
  </div>
  <aside class="wr">
    <div class="tabs"><span>Design</span><span class="on">Build</span><span>Code</span></div>
    <div class="cap ph2">Pipeline</div>
    {prows}
    <div class="dec"><span class="cap">Decision · Display</span><b>SSD1306 OLED 0.91″</b><span class="soft">Fits beside the knob; I²C, two pins left on the controller.</span></div>
  </aside>
  {trail}
</div>
"""

# ---------------------------------------------------------------- what the agent does (real render, one beat each)
SW = 300
step_src, SH = crop("render-v4-c3-macropad-hero.png", (120, 300, 820, 760), SW)
k2 = SW / 700
def R2(x, y, w, h):  # coordinates in the hero crop space (0,210 origin) -> step crop
    return dict(x=(x + 0 - 120) * k2, y=(y + 210 - 300) * k2, w=w * k2, h=h * k2)
code = '<span class="code mono">Wire.begin(6, 7);<i class="caret2"></i></span>'
trace = f'<svg class="tr" viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M5 70 H35 V25 H70 V60 H95" fill="none" stroke="{BLUE}" stroke-width="2.5" stroke-dasharray="6 4" vector-effect="non-scaling-stroke"/></svg>'
scan = f'<span class="scan" style="background:{BLUE}"></span>'
tick = f'<span class="tick" style="background:{OK}">✓</span>'
beats = [
    ("Reads what you want", "It turns one line into a spec and asks one question if it must.", "look", sel(R2(190, 125, 590, 395), "Reading “one big knob”", extra=scan, chip_below=True)),
    ("Picks each part", "Flies to a part, picks it from 39,451 real ones, and drops it in place.", "pick", sel(R2(225, 200, 345, 300), "Picking Gateron Yellow ×9") + f'<span class="cur" style="left:{R2(330,250,0,0)["x"]:.0f}px;top:{R2(330,250,0,0)["y"]:.0f}px">{cursor_svg}</span><span class="ripple" style="left:{R2(330,250,0,0)["x"]-10:.0f}px;top:{R2(330,250,0,0)["y"]-10:.0f}px"></span>'),
    ("Routes the board", "Draws the traces across the board in KiCad, live.", "trace", sel(R2(320, 160, 230, 110), "Routing PCB", extra=trace, chip_below=True)),
    ("Writes the firmware", "Types the firmware for the exact pins it chose.", "type", sel(R2(380, 165, 100, 70), "Writing firmware", extra=code, chip_below=True)),
    ("Checks everything", "Fourteen checks. A green tick, or a red box where it needs you.", "check", sel(R2(532, 238, 228, 130), "Fits the case", color=OK, extra=tick)),
]
beat_cells = "".join(f"<div class='beat'><div class='shot'><img src='{step_src}' width='{SW}' height='{SH}'>{ov}</div><div class='bh'><span class='bn'>{i+1}</span><b>{t}</b></div><p class='soft'>{d}</p></div>" for i, (t, d, a, ov) in enumerate(beats))

# ---------------------------------------------------------------- your builds (real renders)
cards_src = [("render-v4-d1-keyboard-hero.png", "a keyboard", "Bakeneko60 · 128 parts · 2 min ago"), ("render-v4-b2-split-hero.png", "a wireless split keyboard with an OLED", "Corne · 96 parts · yesterday"),
             ("render-v4-d1-smartwatch-hero.png", "a little smartwatch", "Watch · 19 parts · yesterday"), ("render-v4-c3-macropad-hero.png", "a macropad with one big knob", "Macropad · 23 parts · Fri 23 Oct")]
cards = ""
for i, (f, t, m) in enumerate(cards_src):
    src, _ = crop(f, (60, 260, 900, 800), 320)
    cards += f"<div class='card'><div class='th'><img src='{src}' width='320'><span class='no mono'>No. {14-i:03d}</span></div><div class='cm'><span class='serif ct'>{t}</span><span class='soft cs'>{m}</span></div></div>"

css = f"""
.nav {{ display: flex; justify-content: space-between; align-items: center; padding: 24px 56px; }}
.nav .brand {{ font-size: 28px; }}
.nav nav {{ display: flex; gap: 28px; }}
.head {{ display: grid; grid-template-columns: 1fr 600px; gap: 48px; padding: 26px 56px 30px; align-items: end; }}
.head h1 {{ font-size: 66px; line-height: 0.96; letter-spacing: -0.04em; }}
.head .sub {{ margin-top: 14px; font-size: 17px; color: #5e5e5e; max-width: 560px; }}
.ask {{ display: grid; grid-template-columns: 54px 1fr; gap: 12px; align-items: start; }}
.ask .one {{ font: 800 66px 'Atkinson Hyperlegible Next'; line-height: 0.8; letter-spacing: -0.05em; }}
.field {{ border: 1.5px solid {INK}; border-radius: 2px; background: #fff; }}
.field .row {{ display: flex; align-items: center; gap: 12px; padding: 10px 10px 10px 12px; }}
.field .v {{ flex: 1; font-family: 'Averia Serif Libre'; font-size: 22px; letter-spacing: -0.02em; line-height: 1.2; }}
.field .go {{ background: {INK}; color: #fff; padding: 10px 16px; font-weight: 600; white-space: nowrap; }}
.field .foot {{ display: flex; justify-content: space-between; border-top: 1px solid #dcdcdc; padding: 6px 12px; font-size: 12px; color: #5e5e5e; }}
.try {{ margin-top: 10px; padding-left: 66px; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; }}
.try span {{ border-bottom: 1px solid #b4b4b4; }}
/* the product window */
.win {{ position: relative; margin: 0 56px; height: 600px; display: grid; grid-template-columns: 220px {CW}px 1fr; border: 1px solid #c9c9c6; box-shadow: 0 30px 60px -40px rgba(0,0,0,0.35); background: #fff; overflow: hidden; }}
.wl {{ border-right: 1px solid #dddddd; font-size: 12.5px; }}
.fh {{ display: flex; gap: 6px; align-items: baseline; padding: 12px 14px 4px; white-space: nowrap; overflow: hidden; }}
.fb {{ font-size: 18px; }} .sep {{ color: #b4b4b4; }} .fp {{ color: #5e5e5e; overflow: hidden; text-overflow: ellipsis; }}
.fm {{ display: flex; gap: 8px; align-items: center; padding: 2px 14px 10px; font-size: 11px; color: #5e5e5e; }}
.pill {{ font-size: 10px; padding: 1px 6px; border-radius: 3px; }} .pill.run {{ background: #e6f0ff; color: {BLUE}; }}
.sp {{ display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid #dddddd; border-bottom: 1px solid #dddddd; }}
.dots {{ display: inline-flex; gap: 4px; align-items: center; }}
.d {{ width: 5px; height: 5px; border-radius: 3px; border: 1px solid #b4b4b4; display: inline-block; }}
.d.ok {{ background: {INK}; border-color: {INK}; }} .d.now {{ width: 24px; background: #ececea; border-color: transparent; box-shadow: inset 14px 0 0 {INK}; }}
.lh {{ display: flex; justify-content: space-between; align-items: baseline; padding: 10px 14px 4px; }}
.lc {{ font-size: 10px; color: #5e5e5e; }}
.lg {{ padding: 6px 14px 1px; font-weight: 600; font-size: 12.5px; }}
.lr {{ display: flex; align-items: center; gap: 7px; padding: 3px 10px 3px 14px; margin: 0 4px; }}
.lr .dot, .pr .dot {{ width: 6px; height: 6px; border-radius: 3px; background: {OK}; display: inline-block; flex: none; }}
.lr.wait .dot, .pr.wait .dot {{ background: transparent; border: 1px solid #b4b4b4; }}
.lr.now {{ background: #e6f0ff; outline: 1px solid {BLUE}; }} .lr.now .dot, .pr.now .dot {{ background: {BLUE}; }}
.lr .ln {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }} .lr .lq {{ font-size: 11px; color: #5e5e5e; }}
.lr.wait {{ color: #8c8c8c; }}
.wc {{ position: relative; background: #ececec; overflow: hidden; }}
.wc img {{ display: block; }}
.sel {{ position: absolute; border: 1.5px solid; border-radius: 1px; }}
.hd {{ position: absolute; width: 8px; height: 8px; background: #fff; border: 1.5px solid; box-sizing: border-box; }}
.chip {{ position: absolute; left: -1px; padding: 2px 7px; border-radius: 3px; color: #fff; font: 600 11px 'Atkinson Hyperlegible Next'; white-space: nowrap; }}
.cur {{ position: absolute; }}
.stagebot {{ position: absolute; filter: drop-shadow(0 6px 10px rgba(0,0,0,0.18)); }}
.okmark {{ position: absolute; width: 18px; height: 18px; border-radius: 9px; background: {OK}; color: #fff; font-size: 11px; line-height: 18px; text-align: center; font-weight: 700; opacity: 0.9; }}
.dock {{ position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); width: 470px; display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid #dddddd; border-radius: 22px; padding: 5px 5px 5px 6px; box-shadow: 0 8px 18px -10px rgba(0,0,0,0.25); }}
.home-slot {{ width: 36px; height: 25px; border-radius: 13px; border: 1.5px dashed #b4b4b4; flex: none; }}
.ph {{ flex: 1; font-size: 13px; color: #8c8c8c; }}
.dbtn {{ font-size: 12px; font-weight: 600; padding: 7px 12px; border-radius: 16px; background: #f6f6f5; }}
.wr {{ border-left: 1px solid #dddddd; font-size: 12.5px; }}
.tabs {{ display: flex; gap: 14px; padding: 0 14px; height: 38px; align-items: stretch; border-bottom: 1px solid #dddddd; font: 11px 'Atkinson Hyperlegible Mono'; text-transform: uppercase; letter-spacing: 0.08em; color: #5e5e5e; }}
.tabs span {{ display: flex; align-items: center; }} .tabs .on {{ color: {INK}; border-bottom: 1.5px solid {INK}; }}
.ph2 {{ padding: 12px 14px 6px; }}
.pr {{ display: grid; grid-template-columns: 10px 1fr auto; gap: 8px; align-items: center; padding: 4px 14px; }}
.pr .pt {{ font-size: 11px; color: #5e5e5e; }}
.pr.wait {{ color: #8c8c8c; }}
.pr .bar {{ grid-column: 2 / 4; height: 3px; background: #ececea; border-radius: 2px; overflow: hidden; }} .pr .bar i {{ display: block; width: 55%; height: 100%; background: {BLUE}; }}
.dec {{ margin: 14px; padding: 10px 12px; border: 1px solid #dddddd; display: flex; flex-direction: column; gap: 3px; }}
.dec b {{ font-weight: 600; }}
.trail {{ position: absolute; left: 0; top: 0; pointer-events: none; }}
.caption {{ margin: 12px 56px 0; display: flex; justify-content: space-between; font-size: 13px; color: #5e5e5e; }}
/* what the agent does */
.what {{ margin: 64px 56px 0; border-top: 1.5px solid {INK}; padding-top: 16px; }}
.what .h, .lib .h {{ display: flex; justify-content: space-between; align-items: baseline; }}
.what h2, .lib h2 {{ font-size: 44px; letter-spacing: -0.035em; }}
.beats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; margin-top: 20px; }}
.beats .beat:nth-child(5) {{ display: none; }}
.shot {{ position: relative; overflow: hidden; background: #ececec; }}
.shot img {{ display: block; width: 100%; height: auto; }}
.bh {{ display: flex; align-items: baseline; gap: 10px; margin-top: 12px; }}
.bn {{ font: 800 34px 'Atkinson Hyperlegible Next'; line-height: 0.8; letter-spacing: -0.05em; }}
.bh b {{ font-size: 17px; font-weight: 600; }}
.beat p {{ font-size: 14px; margin-top: 4px; }}
.scan {{ position: absolute; left: 0; right: 0; top: 46%; height: 1.5px; }}
.ripple {{ position: absolute; width: 20px; height: 20px; border-radius: 10px; border: 2px solid {BLUE}; }}
.tr {{ position: absolute; inset: 6px; width: calc(100% - 12px); height: calc(100% - 12px); }}
.code {{ position: absolute; left: calc(100% + 8px); top: 10px; background: {INK}; color: #fff; font-size: 11px; padding: 5px 8px; border-radius: 4px; white-space: nowrap; }}
.caret2 {{ display: inline-block; width: 6px; height: 12px; background: {BLUE}; margin-left: 2px; vertical-align: -2px; }}
.tick {{ position: absolute; right: -9px; top: -9px; width: 18px; height: 18px; border-radius: 9px; color: #fff; font-size: 11px; line-height: 18px; text-align: center; font-weight: 700; }}
.lib {{ margin: 64px 56px 90px; border-top: 1.5px solid {INK}; padding-top: 16px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-top: 20px; }}
.card {{ border: 1px solid #dcdcdc; }}
.th {{ position: relative; background: #ececec; border-bottom: 1px solid #dcdcdc; overflow: hidden; height: 190px; }}
.th img {{ display: block; width: 100%; height: auto; }}
.th .no {{ position: absolute; left: 10px; top: 8px; font-size: 11px; color: #5e5e5e; }}
.cm {{ padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 6px; }}
.ct {{ font-size: 21px; line-height: 1.12; letter-spacing: -0.02em; }}
.cs {{ font-size: 13px; }}
"""
body_html = f"""
<div class="nav"><span class="serif brand">Bara</span><nav class="cap"><span>Your builds</span><span>How it builds</span><span>Parts</span><span>GitHub ↗</span></nav></div>
<section class="head">
  <div><h1 class="serif">Describe a device. Watch Bara build it from real parts.</h1><p class="sub">It picks open parts, routes the board, shapes the case and writes the firmware, out on the canvas where you can see every move.</p></div>
  <div><div class="ask"><span class="one">1</span><div class="field"><div class="row">{bot(44)}<span class="v">a macropad with one big knob and a little screen<span class="caret" style="height:22px"></span></span><span class="go">Build ↵</span></div><div class="foot"><span>Type it, or hold Space and say it</span><span class="mono">then watch</span></div></div></div>
  <div class="try"><span>a split keyboard with an OLED</span><span>a little smartwatch</span><span>something cool for my desk</span></div></div>
</section>
{window}
<div class="caption"><span>A real build, mid-way: Bara has placed the switches, caps, controller and knob, and is setting the screen in beside the knob.</span><span class="mono">13.6 s in</span></div>
<section class="what"><div class="h"><h2 class="serif">Bara works where you can see it</h2><span class="cap">Every step is an action on the canvas</span></div><div class="beats">{beat_cells}</div></section>
<section class="lib"><div class="h"><h2 class="serif">Your builds</h2><span class="cap">Search ⌕ · saved in this browser</span></div><div class="cards">{cards}</div></section>
"""
open("c8_product.html", "w").write(page("Bara", css, body_html))
print("ok", CH)
