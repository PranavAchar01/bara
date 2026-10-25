"""A minimal 32-bit little-endian ELF reader: loadable segments, symbols, and UF2 packing."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class Elf:
    entry: int
    segments: list[tuple[int, int, bytes]]  # (paddr, vaddr, data with bss zero filled)
    symbols: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (addr, size)
    sections: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (addr, size)

    def image(self) -> tuple[int, bytes]:
        """The flat image to program, from the lowest load address (file bytes only)."""
        alloc = [(a, n) for a, n in self.sections.values() if a and n]
        segs = sorted(
            (p, d)
            for p, v, d in self.segments
            if d and any(a < v + len(d) and v < a + n for a, n in alloc)
        )
        base = segs[0][0]
        end = max(p + len(d) for p, d in segs)
        buf = bytearray(end - base)
        for p, d in segs:
            buf[p - base : p - base + len(d)] = d
        return base, bytes(buf)


def parse(data: bytes) -> Elf:
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF")
    (entry, phoff, shoff) = struct.unpack_from("<III", data, 24)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from("<HHHHH", data, 42)
    segments = []
    for i in range(phnum):
        p_type, off, vaddr, paddr, filesz, memsz, _flags, _align = struct.unpack_from(
            "<IIIIIIII", data, phoff + i * phentsize
        )
        if p_type == 1 and filesz:  # PT_LOAD with bytes in the file
            segments.append((paddr, vaddr, data[off : off + filesz]))
    sects = []
    for i in range(shnum):
        sects.append(struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize))
    names = sects[shstrndx] if shnum else None

    def name_at(table_off: int, idx: int) -> str:
        end = data.index(b"\0", table_off + idx)
        return data[table_off + idx : end].decode("ascii", "replace")

    sections: dict[str, tuple[int, int]] = {}
    symbols: dict[str, tuple[int, int]] = {}
    for s in sects:
        if names:
            sections[name_at(names[4], s[0])] = (s[3], s[5])
        if s[1] == 2:  # SHT_SYMTAB
            strtab = sects[s[6]]
            for k in range(s[5] // 16):
                st_name, value, size, _info, _other, _shndx = struct.unpack_from(
                    "<IIIBBH", data, s[4] + k * 16
                )
                if st_name:
                    symbols[name_at(strtab[4], st_name)] = (value, size)
    return Elf(entry=entry, segments=segments, symbols=symbols, sections=sections)


def uf2(base: int, image: bytes, family: int) -> bytes:
    """UF2 blocks (Microsoft UF2 spec): 256 payload bytes per 512-byte block, family id set."""
    blocks = [image[i : i + 256] for i in range(0, len(image), 256)]
    out = bytearray()
    for n, chunk in enumerate(blocks):
        head = struct.pack(
            "<IIIIIIII",
            0x0A324655,
            0x9E5D5157,
            0x00002000,  # familyID present
            base + n * 256,
            256,
            n,
            len(blocks),
            family,
        )
        payload = chunk.ljust(476, b"\0")
        out += head + payload + struct.pack("<I", 0x0AB16F30)
    return bytes(out)
