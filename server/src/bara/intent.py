"""What a prompt typed over an open build asks for: a second device beside it, or a change to it.

"add a mouse to the keyboard" names a thing and relates it to what is on screen. When that thing
is something a build is made of (a speaker, an LED, a key matrix) it is a change to the build;
otherwise it is a device of its own, built on a new canvas next to the first one.
"""

from __future__ import annotations

import re
from typing import Any

from bara.catalog import Catalog
from bara.router import normalize

# "<verb> <thing> <link> <the build>", or "<thing> <link> <the build>"
_VERB = r"(?:add|connect|pair|attach|hook up|plug in|plug|make|build|give|design|create)"
_LINK = (
    r"(?:to go with|that goes with|that pairs with|paired with|next to|beside|alongside"
    r"|to|with|for)"
)
_REF = r"(?:the|this|my|it|that|our)"
_RELATION = re.compile(
    rf"^(?:{_VERB}\s+(?:me\s+)?)?(?:an?\s+|another\s+|matching\s+|some\s+)*"
    rf"(?P<thing>[a-z0-9-]+(?:\s+[a-z0-9-]+){{0,3}}?)\s+(?P<link>{_LINK})\s+{_REF}\b"
)
# Links that put the thing beside the build, never inside it: "a trackball to go with it" is its own device.
_BESIDE = {"to go with", "that goes with", "that pairs with", "paired with", "next to", "beside", "alongside"}


def part_words(catalog: Catalog, function_words: dict[str, Any]) -> set[str]:
    """Nouns that name what a build is made of: router function words and vocab labels."""
    words = {w for k in function_words for w in k.split()}
    for f in catalog.vocab.get("functions", []):
        for text in (f.get("id", "").split(".")[-1].replace("_", " "), f.get("label", "")):
            words |= {w for w in normalize(str(text)).split() if len(w) > 2}
    return words


def classify(prompt: str, has_build: bool, parts: set[str]) -> dict[str, Any]:
    """{"kind": "new" | "companion" | "modify", "thing": str | None, "prompt": str}."""
    text = re.sub(r"\s+", " ", prompt.lower()).strip()
    plain = re.sub(r"[^a-z0-9\s-]", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not has_build:
        return {"kind": "new", "thing": None, "prompt": prompt.strip()}
    m = _RELATION.match(plain)
    if not m:
        return {"kind": "new", "thing": None, "prompt": prompt.strip()}
    thing = m.group("thing").strip()
    head = thing.split()[-1]
    singular = head[:-1] if head.endswith("s") and len(head) > 3 else head
    if (head in parts or singular in parts) and m.group("link") not in _BESIDE:
        return {"kind": "modify", "thing": thing, "prompt": prompt.strip()}
    return {"kind": "companion", "thing": thing, "prompt": f"a {thing}"}
