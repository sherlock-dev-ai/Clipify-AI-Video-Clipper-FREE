"""Static guard for the installer stylesheet.

The `.music-row` rule was silently dropped by the browser because a stray `}`
sat just above it: the parser closed a block early and discarded the rule, so
the music transport quietly stopped being a flex row and every button stacked
vertically. Nothing errored, the CSSOM simply did not contain the rule.

This checks the things that fail silently in CSS:
  1. brace balance, and no point where depth goes negative
  2. comment balance (an unterminated comment swallows the rest of the file)
  3. every selector a handful of critical rules are expected to define, so a
     dropped rule is caught here rather than by a user noticing stacked buttons

Run: python tools/check_css.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "renderer" / "style.css"
FOREST_CSS = CSS.with_name("forest-theme.css")

# selector -> substring that must appear inside the rule body
REQUIRED: dict[str, str] = {
    ".music-row": "display: flex",
    ".model-grid": "grid-template-columns",
    ".celestial": "z-index",
    ".activity-feed": "overflow-y",
    ".popup-card-warn": "background",
    ".model-desc": "-webkit-line-clamp",
    ".sky-hint": "opacity",
}

# The modal popup renders *below* .titlebar (z-index 90 vs 100) because the
# window controls have to stay clickable while it is open. The titlebar is a
# -webkit-app-region: drag strip, so it swallows any click landing in the top
# 44px of the window. The popup's top padding is therefore the only thing
# keeping the confirm button out of that band: with 24px it could overlap, the
# button stopped responding, and installation could never be started. This
# fails if the padding is ever reduced back towards the titlebar height.
MIN_POPUP_TOP_PADDING = 68


def parse_padding_top(body: str) -> int | None:
    match = re.search(r"(?<![\w-])padding\s*:\s*([^;]+);", body)
    if not match:
        return None
    parts = [p.strip() for p in match.group(1).split()]
    if not parts:
        return None
    top = parts[0]
    if top.endswith("px"):
        try:
            return int(float(top[:-2]))
        except ValueError:
            return None
    # A shorthand like "1rem 2rem" or only side values cannot be verified here.
    return None


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def main() -> int:
    raw = CSS.read_text(encoding="utf-8")
    problems: list[str] = []

    # ---- 1. comments -----------------------------------------------------
    if raw.count("/*") != raw.count("*/"):
        problems.append(
            f"comment markers unbalanced: {raw.count('/*')} '/*' vs {raw.count('*/')} '*/'"
        )

    # ---- 2. brace depth --------------------------------------------------
    text = strip_comments(raw)
    depth = 0
    line = 1
    first_negative: int | None = None
    for ch in text:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0 and first_negative is None:
                first_negative = line
                depth = 0
    if first_negative is not None:
        problems.append(
            f"brace depth goes negative at line {first_negative}: a stray '}}' makes the "
            f"browser discard the rule that follows it"
        )
    if depth != 0:
        problems.append(f"unclosed block: final brace depth is {depth}, expected 0")

    # ---- 3. required rules survived parsing ------------------------------
    for selector, needle in REQUIRED.items():
        pattern = re.compile(
            r"(?<![\w.-])" + re.escape(selector) + r"\s*\{(.*?)\}", re.S
        )
        match = pattern.search(text)
        if not match:
            problems.append(f"{selector}: rule not found")
        elif needle not in match.group(1):
            problems.append(f"{selector}: rule is missing '{needle}'")

    # ---- 4. modal must clear the titlebar drag region --------------------
    popup = re.search(r"(?<![\w.-])\.popup\s*\{(.*?)\}", text, re.S)
    if popup:
        top = parse_padding_top(popup.group(1))
        if top is None:
            problems.append(
                ".popup: top padding could not be verified; it must be an explicit "
                f"px value of at least {MIN_POPUP_TOP_PADDING} so modal buttons stay "
                "clear of the titlebar drag region"
            )
        elif top < MIN_POPUP_TOP_PADDING:
            problems.append(
                f".popup: top padding is {top}px but must be at least "
                f"{MIN_POPUP_TOP_PADDING}px; the titlebar is 44px tall and sits above "
                "the popup, so a shorter padding lets modal buttons fall into its "
                "drag region and become unclickable"
            )

    if problems:
        print(f"FAIL  {CSS}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    forest = FOREST_CSS.read_text(encoding="utf-8")
    forest_text = strip_comments(forest)
    forest_depth = 0
    for ch in forest_text:
        if ch == "{":
            forest_depth += 1
        elif ch == "}":
            forest_depth -= 1
            if forest_depth < 0:
                print(f"FAIL  {FOREST_CSS}: brace depth goes negative")
                return 1
    if forest_depth != 0 or forest.count("/*") != forest.count("*/"):
        print(f"FAIL  {FOREST_CSS}: unbalanced CSS braces or comments")
        return 1
    for selector, needle in {
        ".forest-backdrop": "position: fixed",
        ".steps ol": "repeat(5",
        ".builder": "transition:",
        "#forest-game": "display: block",
        ".failure-panel": "border:",
    }.items():
        matches = re.finditer(r"(?<![\w.-])" + re.escape(selector) + r"\s*\{(.*?)\}", forest_text, re.S)
        if not any(needle in match.group(1) for match in matches):
            print(f"FAIL  {FOREST_CSS}: {selector} missing required rule '{needle}'")
            return 1
    print(f"OK    {CSS.name}: braces balanced, {len(REQUIRED)} critical rules intact")
    print(f"OK    {FOREST_CSS.name}: braces balanced, five-stage forest rules intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
