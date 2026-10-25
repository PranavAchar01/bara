"""Run the compiled firmware.

ChipSession executes the chip build (the same ELF that becomes the UF2) instruction by
instruction in Unicorn (QEMU's CPU core) with the peripherals the firmware touches modelled
in Python: GPIO, UART, the RTC or TIMER tick, the ADC, clocks and resets. Time is virtual: when
the firmware waits for the next tick the session jumps straight to it, so a simulated second
takes a fraction of a real one.

HostSession runs the host build of the same source over a pipe. It is the fallback for chips
with no emulator here (ESP32, AVR) and it is what the firmware unit tests drive.

Both expose the same calls: press, turn, set_axis, set_power, run_ms, snapshot.
"""

from __future__ import annotations

import base64
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import elf as elfmod
from .codegen import FwConfig, input_rows
from .mcu import BOARDS, Board, pin_number

MAX_EVENTS = 4000
SLICE_INSNS = 400_000  # instructions per run before the session forces time forward

FB_W, FB_H = 128, 64
_PLAIN = "abcdefghijklmnopqrstuvwxyz1234567890\n\x1b\b\t -=[]\\#;'`,./"
_SHIFT = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()\n\x1b\b\t _+{}|~:"~<>?'


def usage_char(usage: int, shift: bool) -> str | None:
    """The character a US keyboard types for a HID usage, or None for keys that type nothing."""
    i = usage - 0x04
    table = _SHIFT if shift else _PLAIN
    return table[i] if 0 <= i < len(table) and usage <= 0x38 else None


def pack_2bpp(raw: bytes) -> bytes:
    """One byte per pixel (0..3) to four pixels per byte."""
    out = bytearray(len(raw) // 4)
    for i in range(0, len(out) * 4, 4):
        out[i // 4] = (
            (raw[i] & 3)
            | ((raw[i + 1] & 3) << 2)
            | ((raw[i + 2] & 3) << 4)
            | ((raw[i + 3] & 3) << 6)
        )
    return bytes(out)


class _Inputs:
    """Physical state of every input, and the pin levels it produces."""

    def __init__(self, io: dict[str, Any], cfg: FwConfig, board: Board) -> None:
        self.rows = input_rows(io, cfg)
        self.by_id = {r["id"]: r for r in self.rows}
        self.board = board
        self.closed: dict[str, bool] = {}  # button/key/switch contact closed
        self.enc: dict[str, tuple[bool, bool]] = {}  # encoder (A closed, B closed)
        self.axis: dict[str, int] = {}  # ADC value 0..4095
        self.adc_by_ch: dict[int, str] = {}
        for r in self.rows:
            if r["fw_kind"] == "axis":
                self.axis[r["id"]] = 2048
                self.adc_by_ch[int(r.get("adc") or 0)] = r["id"]
        self.matrix_rows = {
            pin_number(board, p) for p in ((io.get("matrix") or {}).get("row_pins") or []) if p
        }

    def pin(self, r: dict[str, Any], key: str = "pin") -> int:
        p = r.get(key)
        return pin_number(self.board, p) if p else 255

    def level(self, pin: int, out_levels: dict[int, int]) -> int:
        """Level the MCU reads on an input pin (pull-ups: an open contact reads 1)."""
        for r in self.rows:
            k = r["fw_kind"]
            if k in ("button", "key", "switch") and self.pin(r) == pin and self.closed.get(r["id"]):
                return 0
            if k == "mkey" and self.pin(r) == pin and self.closed.get(r["id"]):
                if out_levels.get(self.pin(r, "row_pin"), 1) == 0:
                    return 0
            if k == "encoder":
                a, b = self.enc.get(r["id"], (False, False))
                if self.pin(r) == pin and a:
                    return 0
                if self.pin(r, "pin_b") == pin and b:
                    return 0
        return 1

    def low_pins(self, out_levels: dict[int, int]) -> list[int]:
        """Input pins pulled low right now by a closed contact."""
        low = []
        for rid, closed in self.closed.items():
            if not closed:
                continue
            r = self.by_id[rid]
            if r["fw_kind"] in ("button", "key", "switch"):
                low.append(self.pin(r))
            elif r["fw_kind"] == "mkey" and out_levels.get(self.pin(r, "row_pin"), 1) == 0:
                low.append(self.pin(r))
        for rid, (a, b) in self.enc.items():
            r = self.by_id[rid]
            if a:
                low.append(self.pin(r))
            if b:
                low.append(self.pin(r, "pin_b"))
        return low

    def adc(self, ch: int) -> int:
        rid = self.adc_by_ch.get(ch)
        return self.axis.get(rid, 2048) if rid else 2048


class _Base:
    kind = "base"

    def __init__(self, io: dict[str, Any], cfg: FwConfig) -> None:
        self.io = io
        self.board = BOARDS.get(io["mcu"]["board_id"]) or BOARDS["nice_nano_v2"]
        self.inputs = _Inputs(io, cfg, self.board)
        self.events: list[dict[str, Any]] = []
        self.seq = 0
        self.serial_line = ""
        self.powered = True
        self.screen: list[str] = []
        self.hid: list[int] = [0] * 8
        self.fb: bytes | None = None  # display framebuffer, 2 bits per pixel, row-major
        self.bootloader = False
        self._last_keys: set[int] = set()
        self.led: dict[int, int] = {}
        self.lock = threading.RLock()
        self.watch_pins = self._watch_pins()
        self.tone_pins = {
            pin_number(self.board, o["pin"])
            for o in io["outputs"]
            if o["kind"] == "tone" and o.get("pin")
        }
        self.tone_last: dict[int, float] = {}
        self.wave: dict[int, list[tuple[float, int]]] = {}

    def _watch_pins(self) -> dict[int, str]:
        names: dict[int, str] = {}
        for o in self.io["outputs"]:
            if o.get("pin") and o["kind"] in ("led", "tone"):
                names[pin_number(self.board, o["pin"])] = o["label"]
        return names

    # ---- events ----
    def now_ms(self) -> float:
        raise NotImplementedError

    def _emit(self, ev: dict[str, Any]) -> None:
        self.seq += 1
        ev = {"seq": self.seq, "t_ms": round(self.now_ms(), 1), **ev}
        self.events.append(ev)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]

    def _serial_char(self, c: int) -> None:
        if c == 10:
            line = self.serial_line
            self.serial_line = ""
            self._emit({"type": "serial", "text": line})
            if line.startswith("HID ") or line.startswith("HIDC "):
                self._emit({"type": "hid", "report": line[4:].strip(), "kind": line.split()[0]})
            if line.startswith("HID kb "):
                self._typed(line.split()[2:])
        elif c != 13:
            self.serial_line += chr(c) if 32 <= c < 127 else "?"

    def _typed(self, report: list[str]) -> None:
        """What a USB keyboard would type for a new key in this report (text the host receives)."""
        try:
            raw = [int(x, 16) for x in report]
        except ValueError:
            return
        keys = {k for k in raw[2:8] if k}
        shift = bool(raw[0] & 0x22) if raw else False
        for k in sorted(keys - self._last_keys):
            ch = usage_char(k, shift)
            if ch is not None:
                self._emit({"type": "typed", "text": ch})
        self._last_keys = keys

    def reboot(self, bootloader: bool = False) -> None:
        raise NotImplementedError

    def _gpio(self, pin: int, level: int) -> None:
        if pin in self.inputs.matrix_rows:
            return
        if self.led.get(pin) == level:
            return
        self.led[pin] = level
        t = round(self.now_ms(), 2)
        wave = self.wave.setdefault(pin, [])
        wave.append((t, level))
        if len(wave) > 600:
            del wave[:-600]
        if pin in self.tone_pins:  # a square wave: report the burst, not every edge
            if t - self.tone_last.get(pin, -1e9) > 5:
                self._emit({"type": "tone", "pin": pin, "name": self.watch_pins[pin], "on": True})
            self.tone_last[pin] = t
            return
        self._emit(
            {"type": "gpio", "pin": pin, "level": level, "name": self.watch_pins.get(pin, "")}
        )

    # ---- inputs ----
    def press(self, input_id: str, down: bool, hold_ms: int = 0) -> None:
        with self.lock:
            r = self.inputs.by_id.get(input_id)
            if not r:
                raise KeyError(input_id)
            self.inputs.closed[input_id] = down
            self._emit({"type": "input", "id": input_id, "label": r["label"], "down": down})
            self._sync_inputs()
            if hold_ms:
                self.run_ms(hold_ms)

    def turn(self, input_id: str, steps: int) -> None:
        """Quadrature steps: clockwise A closes before B, anticlockwise B first."""
        with self.lock:
            r = self.inputs.by_id.get(input_id)
            if not r or r["fw_kind"] != "encoder":
                raise KeyError(input_id)
            cw = steps > 0
            self._emit({"type": "input", "id": input_id, "label": r["label"], "turn": steps})
            for _ in range(abs(steps)):
                seq = (
                    [(True, False), (True, True), (False, True), (False, False)]
                    if cw
                    else [(False, True), (True, True), (True, False), (False, False)]
                )
                for st in seq:
                    self.inputs.enc[input_id] = st
                    self._sync_inputs()
                    self.run_ms(3)

    def set_axis(self, input_id: str, value: float) -> None:
        with self.lock:
            r = self.inputs.by_id.get(input_id)
            if not r or r["fw_kind"] != "axis":
                raise KeyError(input_id)
            v = max(-1.0, min(1.0, float(value)))
            self.inputs.axis[input_id] = int(round(2048 + v * 2047))
            self._emit({"type": "input", "id": input_id, "label": r["label"], "value": v})
            self._sync_inputs()

    def _sync_inputs(self) -> None:
        pass

    def set_power(self, on: bool) -> None:
        raise NotImplementedError

    def run_ms(self, ms: float) -> None:
        raise NotImplementedError

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            leds = []
            for o in self.io["outputs"]:
                if o["kind"] in ("led", "tone") and o.get("pin"):
                    pin = pin_number(self.board, o["pin"])
                    lvl = self.led.get(pin, 0)
                    on = (not lvl) if o.get("active_low") else bool(lvl)
                    if pin in self.tone_pins:
                        on = self.now_ms() - self.tone_last.get(pin, -1e9) <= 3
                    leds.append({"id": o["id"], "label": o["label"], "on": on and self.powered})
            return {
                "mode": self.kind,
                "powered": self.powered,
                "t_ms": round(self.now_ms(), 1),
                "screen": self.screen if self.powered else [],
                "hid": " ".join(f"{b:02X}" for b in self.hid),
                "bootloader": self.bootloader,
                "fb": (
                    {"w": FB_W, "h": FB_H, "b64": base64.b64encode(self.fb).decode()}
                    if self.fb and self.powered and not self.bootloader
                    else None
                ),
                "leds": leds,
                "inputs": {
                    "closed": {k: v for k, v in self.inputs.closed.items() if v},
                    "axes": dict(self.inputs.axis),
                },
                "events": [e for e in self.events if e["seq"] > since],
                "wave": {
                    str(p): {"name": self.watch_pins.get(p, f"pin {p}"), "edges": w[-200:]}
                    for p, w in self.wave.items()
                },
                "seq": self.seq,
            }


class ChipSession(_Base):
    """The chip build in Unicorn with modelled peripherals."""

    kind = "emulated"

    def __init__(self, io: dict[str, Any], cfg: FwConfig, elf_path: Path) -> None:
        super().__init__(io, cfg)
        self.elf = elfmod.parse(elf_path.read_bytes())
        self.t_us = 0.0
        self.insns = 0
        self.out: dict[int, int] = {}
        self._boot()

    # ---- machine ----
    def _boot(self) -> None:
        import unicorn as uc
        from unicorn import arm_const as a

        b = self.board
        u = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        u.ctl_set_cpu_model(
            a.UC_CPU_ARM_CORTEX_M4 if b.family == "nrf52840" else a.UC_CPU_ARM_CORTEX_M0
        )
        if b.family == "nrf52840":
            u.mem_map(0x0, 0x100000)  # flash
            u.mem_map(0x20000000, 0x40000)  # RAM
            u.mmio_map(0x40000000, 0x40000, self._rd, 0x40000000, self._wr, 0x40000000)  # APB
            u.mmio_map(0x50000000, 0x1000, self._rd, 0x50000000, self._wr, 0x50000000)  # GPIO
        else:
            u.mem_map(0x0, 0x4000)  # boot ROM (unused: the image runs from SRAM)
            u.mem_map(0x20000000, 0x43000)  # SRAM
            u.mmio_map(0x40000000, 0x70000, self._rd, 0x40000000, self._wr, 0x40000000)  # APB
            u.mmio_map(0xD0000000, 0x1000, self._rd, 0xD0000000, self._wr, 0xD0000000)  # SIO
        u.mem_map(0xE0000000, 0x100000)  # private peripheral bus (VTOR and friends)
        for paddr, _v, data in self.elf.segments:
            if any(a_ <= paddr < a_ + n for a_, n in self.elf.sections.values() if a_ and n):
                u.mem_write(paddr, data)
        self.u = u
        self.state: dict[str, Any] = {
            "tick_pending": False,
            "rtc_running": False,
            "alarm": None,
            "alarm_rel": 0,
            "intr": 0,
            "adc_ch": 0,
            "adc_ptr": 0,
            "saadc_end": 0,
            "idle": False,
        }
        self.out = {}
        self.boot_us = self.t_us
        sp = self.elf.symbols.get("__stack_top", (b.ram_origin + b.ram_size, 0))[0]
        u.reg_write(a.UC_ARM_REG_SP, sp)
        self.pc = self.elf.entry | 1
        self._emit({"type": "power", "on": True, "text": "power on: reset"})

    def now_ms(self) -> float:
        return self.t_us / 1000.0

    def _rtc_counter(self) -> int:
        return int((self.t_us - self.boot_us) * 32768 / 33 / 1e6) & 0xFFFFFF

    def _next_tick_us(self) -> float:
        if self.board.family == "nrf52840":
            period = 33 / 32768 * 1e6
            n = int((self.t_us - self.boot_us) / period) + 1
            return self.boot_us + n * period
        return float(self.state["alarm"] if self.state["alarm"] is not None else self.t_us + 1000)

    def _idle(self) -> None:
        self.state["idle"] = True
        self.u.emu_stop()

    # ---- MMIO ----
    def _set_out(self, pin: int, level: int) -> None:
        if self.out.get(pin) != level:
            self.out[pin] = level
            self._gpio(pin, level)

    def _in_word(self, base_pin: int) -> int:
        word = 0xFFFFFFFF  # pull-ups: open inputs read high
        for pin in self.inputs.low_pins(self.out):
            if base_pin <= pin < base_pin + 32:
                word &= ~(1 << (pin - base_pin))
        for pin, lvl in self.out.items():
            if base_pin <= pin < base_pin + 32:
                k = pin - base_pin
                word = (word & ~(1 << k)) | ((lvl & 1) << k)
        return word & 0xFFFFFFFF

    # mmio callbacks get the offset inside the mapped region; user data is the region base
    def _rd(self, u: Any, off: int, size: int, base: int) -> int:
        return self._read(base + off, size) & 0xFFFFFFFF

    def _wr(self, u: Any, off: int, size: int, value: int, base: int) -> None:
        self._write(base + off, size, value & 0xFFFFFFFF)

    def _read(self, off: int, size: int) -> int:
        raise NotImplementedError

    def _write(self, off: int, size: int, value: int) -> None:
        raise NotImplementedError

    # ---- run ----
    def run_ms(self, ms: float) -> None:
        with self.lock:
            end = self.t_us + ms * 1000.0
            while self.t_us < end:
                if not self.powered or self.bootloader:
                    self.t_us = end
                    break
                self.state["idle"] = False
                try:
                    self.u.emu_start(self.pc, 0xFFFFFFFF, count=SLICE_INSNS)
                except Exception as e:  # unicorn raises UcError on a CPU fault
                    self._emit({"type": "fault", "text": f"CPU fault: {e}"})
                    self.powered = False
                    break
                from unicorn import arm_const as a

                self.pc = self.u.reg_read(a.UC_ARM_REG_PC) | 1
                if self.state["idle"]:
                    nxt = self._next_tick_us()
                    if nxt > end:
                        self.t_us = end
                    else:
                        self.t_us = max(nxt, self.t_us)
                        self.state["tick_pending"] = True
                else:
                    self.t_us += 1000.0  # a busy slice: let time pass
            if self.powered:
                self._read_ram()

    def _read_ram(self) -> None:
        sym = self.elf.symbols
        if "bara_screen" in sym:
            addr, size = sym["bara_screen"]
            raw = bytes(self.u.mem_read(addr, size))
            screen = _cfg_int(self.io, "rows")
            cols = size // max(1, screen) - 1
            self.screen = [
                raw[r * (cols + 1) : r * (cols + 1) + cols]
                .split(b"\0")[0]
                .decode("ascii", "replace")
                for r in range(screen)
            ]
        if "bara_fb" in sym:
            addr, size = sym["bara_fb"]
            self.fb = pack_2bpp(bytes(self.u.mem_read(addr, size)))
        if "bara_hid" in sym:
            addr, _ = sym["bara_hid"]
            self.hid = list(bytes(self.u.mem_read(addr, 8)))

    def reboot(self, bootloader: bool = False) -> None:
        """The reset button: restart the chip. With the boot button held, enter the bootloader."""
        with self.lock:
            if not self.powered:
                return
            self.screen, self.fb, self.hid = [], None, [0] * 8
            self._last_keys = set()
            for pin in list(self.out):
                self._set_out(pin, 0)
            self.bootloader = bootloader
            if bootloader:
                self._emit({"type": "power", "on": True, "text": "reset: bootloader (USB drive)"})
                return
            self._boot()
            self.run_ms(5)

    def set_power(self, on: bool) -> None:
        with self.lock:
            if on == self.powered:
                return
            if not on:
                self.powered = False
                for pin in list(self.out):
                    self._set_out(pin, 0)
                self._emit({"type": "power", "on": False, "text": "power off: rail cut"})
                self.screen = []
            else:
                self.powered = True
                self.bootloader = False
                self._boot()
                self.run_ms(5)


def _cfg_int(io: dict[str, Any], key: str) -> int:
    screen = next((o for o in io["outputs"] if o["kind"] == "display"), None)
    v = (screen or {}).get(key) or (4 if key == "rows" else 21)
    return max(1, min(int(v), 8)) if key == "rows" else max(8, min(int(v), 32))


class Nrf52840(ChipSession):
    """nRF52840 registers (Product Specification v1.7) that the HAL uses."""

    def _read(self, addr: int, size: int) -> int:
        st = self.state
        if addr == 0x40000104:  # CLOCK EVENTS_LFCLKSTARTED
            return 1
        if addr == 0x40000100:  # EVENTS_HFCLKSTARTED
            return 1
        if addr == 0x4000211C:  # UART0 EVENTS_TXDRDY
            return 1
        if addr == 0x4000B100:  # RTC0 EVENTS_TICK
            if st["tick_pending"]:
                return 1
            self._idle()
            return 0
        if addr == 0x4000B504:  # RTC0 COUNTER
            return self._rtc_counter()
        if addr == 0x40007104:  # SAADC EVENTS_END
            return st["saadc_end"]
        if addr == 0x50000510:  # P0.IN
            return self._in_word(0)
        if addr == 0x50000810:  # P1.IN
            return self._in_word(32)
        if addr in (0x50000504, 0x50000804):  # OUT
            base = 0 if addr == 0x50000504 else 32
            return sum((self.out.get(base + k, 0) & 1) << k for k in range(32))
        return 0

    def _write(self, addr: int, size: int, value: int) -> None:
        st = self.state
        if addr == 0x4000251C:  # UART0 TXD
            self._serial_char(value & 0xFF)
        elif addr == 0x4000B100:  # EVENTS_TICK cleared
            st["tick_pending"] = bool(value)
        elif addr == 0x4000762C:
            st["adc_ptr"] = value
        elif addr == 0x40007510:
            st["adc_ch"] = max(0, value - 1)
        elif addr == 0x40007104:
            st["saadc_end"] = value
        elif addr == 0x40007004:  # TASKS_SAMPLE: write the 16-bit result through EasyDMA
            v = self.inputs.adc(st["adc_ch"])
            self.u.mem_write(st["adc_ptr"], int(v).to_bytes(2, "little"))
            st["saadc_end"] = 1
        elif 0x50000508 <= addr <= 0x5000050C or 0x50000808 <= addr <= 0x5000080C:
            base = 0 if addr < 0x50000800 else 32
            level = 1 if addr & 0xF == 0x8 else 0  # OUTSET / OUTCLR
            for k in range(32):
                if value >> k & 1:
                    self._set_out(base + k, level)
        elif 0x50000700 <= addr < 0x50000780 or 0x50000A00 <= addr < 0x50000A80:
            base = 0 if addr < 0x50000800 else 32
            pin = base + ((addr & 0x7F) >> 2)
            if value & 1 and pin not in self.out:  # DIR = output, starts low
                self._set_out(pin, 0)
            elif not value & 1:
                self.out.pop(pin, None)


class Rp2040(ChipSession):
    """RP2040 registers (datasheet) that the HAL uses."""

    def _read(self, addr: int, size: int) -> int:
        st = self.state
        if addr == 0x40024004:  # XOSC STATUS: stable
            return 1 << 31
        if addr == 0x4000C008:  # RESETS RESET_DONE
            return 0xFFFFFFFF
        if addr == 0x40034018:  # UART0 FR: TX FIFO never full
            return 0
        if addr == 0x40054028:  # TIMER TIMERAWL
            return int(self.t_us - self.boot_us) & 0xFFFFFFFF
        if addr == 0x40054034:  # TIMER INTR
            if st["alarm"] is not None and self.t_us - self.boot_us >= st["alarm_rel"]:
                st["intr"] |= 1
            if st["intr"] & 1:
                return 1
            self._idle()
            return 0
        if addr == 0x4004C000:  # ADC CS: always READY
            return 1 << 8 | st["adc_ch"] << 12 | 1
        if addr == 0x4004C004:
            return self.inputs.adc(st["adc_ch"])
        if addr == 0xD0000004:  # SIO GPIO_IN
            return self._in_word(0) & 0x3FFFFFFF
        return 0

    def _write(self, addr: int, size: int, value: int) -> None:
        st = self.state
        if addr == 0x40034000:  # UART0 DR
            self._serial_char(value & 0xFF)
        elif addr == 0x40054010:  # ALARM0 (armed on write)
            st["alarm_rel"] = value
            st["alarm"] = self.boot_us + value
            st["intr"] &= ~1
        elif addr == 0x40054034:  # INTR write-1-to-clear
            st["intr"] &= ~value
        elif addr == 0x4004C000:
            st["adc_ch"] = value >> 12 & 7
        elif addr in (0xD0000014, 0xD0000018, 0xD000001C):
            for k in range(30):
                if value >> k & 1:
                    cur = self.out.get(k, 0)
                    lvl = {0xD0000014: 1, 0xD0000018: 0, 0xD000001C: cur ^ 1}[addr]
                    self._set_out(k, lvl)
        elif addr == 0xD0000024:  # GPIO_OE_SET
            for k in range(30):
                if value >> k & 1 and k not in self.out:
                    self._set_out(k, 0)


def make_chip(io: dict[str, Any], cfg: FwConfig, elf_path: Path) -> ChipSession:
    board = BOARDS.get(io["mcu"]["board_id"]) or BOARDS["nice_nano_v2"]
    cls = Nrf52840 if board.family == "nrf52840" else Rp2040
    return cls(io, cfg, elf_path)


class HostSession(_Base):
    """The host build of the same firmware source, driven over stdin/stdout."""

    kind = "host"

    def __init__(self, io: dict[str, Any], cfg: FwConfig, binary: Path) -> None:
        super().__init__(io, cfg)
        self.binary = binary
        self.t = 0.0
        self.proc: subprocess.Popen[str] | None = None
        self._start()

    def _start(self) -> None:
        self.proc = subprocess.Popen(
            [str(self.binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.base_t = self.t
        self._emit({"type": "power", "on": True, "text": "power on: reset"})
        self._sent_levels: dict[str, Any] = {}
        self._cmd("s 1")

    def now_ms(self) -> float:
        return self.t

    def _cmd(self, line: str) -> None:
        assert self.proc and self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        if not line.startswith("s"):
            return
        rows: list[str] = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            out = self.proc.stdout.readline()
            if not out:
                self._emit({"type": "fault", "text": "host build exited"})
                self.powered = False
                return
            out = out.rstrip("\n")
            tag, _, rest = out.partition(" ")
            if tag == "U":
                for ch in rest:
                    self._serial_char(ord(ch))
                self._serial_char(10)
            elif tag == "G":
                ms, pin, lvl = rest.split()
                self.t = self.base_t + float(ms)  # the edge's own time inside the step
                self._gpio(int(pin), int(lvl))
            elif tag == "S":
                _, _, text = rest.partition(" ")
                rows.append(text.rstrip())
            elif tag == "F":
                self.fb = bytes.fromhex(rest)
            elif tag == "D":
                self.t = self.base_t + float(rest)
                self.screen = rows
                break

    def _sync_inputs(self) -> None:
        if not self.powered:
            return
        b = self.board
        for r in self.inputs.rows:
            k = r["fw_kind"]
            closed = bool(self.inputs.closed.get(r["id"]))
            if k in ("button", "key", "switch"):
                self._send_once(f"p{r['id']}", f"p {self.inputs.pin(r)} {0 if closed else 1}")
            elif k == "mkey":
                col, row = self.inputs.pin(r), self.inputs.pin(r, "row_pin")
                self._send_once(f"m{r['id']}", f"m {col} {row} {1 if closed else 0}")
            elif k == "encoder":
                a, bb = self.inputs.enc.get(r["id"], (False, False))
                self._send_once(f"a{r['id']}", f"p {self.inputs.pin(r)} {0 if a else 1}")
                self._send_once(f"b{r['id']}", f"p {self.inputs.pin(r, 'pin_b')} {0 if bb else 1}")
            elif k == "axis":
                ch = int(r.get("adc") or 0)
                self._send_once(f"x{r['id']}", f"a {ch} {self.inputs.axis[r['id']]}")
        del b

    def _send_once(self, key: str, line: str) -> None:
        if self._sent_levels.get(key) != line:
            self._sent_levels[key] = line
            self._cmd(line)

    def run_ms(self, ms: float) -> None:
        with self.lock:
            if not self.powered or self.bootloader:
                self.t += ms
                return
            self._cmd(f"s {max(1, int(round(ms)))}")
            self._hid_from_events()

    def _hid_from_events(self) -> None:
        for e in reversed(self.events):
            if e["type"] == "hid" and e["kind"] == "HID":
                parts = e["report"].split()[1:]
                self.hid = [int(x, 16) for x in parts] + [0] * (8 - len(parts))
                break

    def reboot(self, bootloader: bool = False) -> None:
        with self.lock:
            if not self.powered:
                return
            self.close()
            self.screen, self.fb, self.hid = [], None, [0] * 8
            self._last_keys = set()
            self.bootloader = bootloader
            if bootloader:
                self._emit({"type": "power", "on": True, "text": "reset: bootloader (USB drive)"})
                return
            self._start()
            self._sync_inputs()

    def set_power(self, on: bool) -> None:
        with self.lock:
            if on == self.powered:
                return
            if not on:
                self.close()
                self.powered = False
                for pin in list(self.led):
                    self._gpio(pin, 0)
                self.screen = []
                self._emit({"type": "power", "on": False, "text": "power off: rail cut"})
            else:
                self.powered = True
                self.bootloader = False
                self._start()
                self._sync_inputs()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("q\n")  # type: ignore[union-attr]
                self.proc.stdin.flush()  # type: ignore[union-attr]
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None
