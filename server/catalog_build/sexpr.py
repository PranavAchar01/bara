"""Minimal KiCad s-expression reader and writer.

A node is a Python list whose first element is the head symbol (str). Atoms are str
for symbols and quoted strings alike; `Quoted` marks the strings that were quoted so
they can be written back faithfully.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class Quoted(str):
    """A string atom that was quoted in the source."""


Node = list[Any]


def parse(text: str) -> Node:
    """Parse one top level s-expression."""
    stack: list[Node] = []
    root: Node | None = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            node: Node = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            i += 1
        elif c == ")":
            done = stack.pop()
            if not stack:
                root = done
                break
            i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            stack[-1].append(Quoted("".join(buf)))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if root is None:
        raise ValueError("unbalanced s-expression")
    return root


def dump(node: Any) -> str:
    if isinstance(node, list):
        return "(" + " ".join(dump(x) for x in node) + ")"
    if isinstance(node, Quoted):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return str(node)


def children(node: Node, head: str) -> Iterator[Node]:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == head:
            yield item


def child(node: Node, head: str) -> Node | None:
    return next(children(node, head), None)


def value(node: Node | None, index: int = 1, default: Any = None) -> Any:
    if node is None or len(node) <= index:
        return default
    return node[index]


def floats(node: Node | None, count: int) -> list[float] | None:
    if node is None:
        return None
    out: list[float] = []
    for item in node[1 : 1 + count]:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            return None
    return out if len(out) == count else None
