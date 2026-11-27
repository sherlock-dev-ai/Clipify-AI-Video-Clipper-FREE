"""Zero-dependency Devanagari-to-Hinglish (Romanized Hindi) transliterator.

Converts Hindi Devanagari script into natural English-alphabet Hinglish
(e.g. "नमस्ते दोस्तों" -> "namaste doston") so captions for Hindi streams
and videos are always readable in Latin script.
"""

from __future__ import annotations

import re

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

_INDEPENDENT_VOWELS = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "ऑ": "o",
    "ऍ": "e",
}

_CONSONANTS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "ळ": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "क़": "q",
    "ख़": "kh",
    "ग़": "gh",
    "ज़": "z",
    "ड़": "r",
    "ढ़": "rh",
    "फ़": "f",
    "य़": "y",
}

_MATRAS = {
    "ा": "a",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "ॉ": "o",
    "ॅ": "e",
}

_MODIFIERS = {
    "ं": "n",
    "ँ": "n",
    "ः": "h",
}

_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
    "।": ".", "॥": ".",
}

_HALANT = "्"
_NUKTA = "़"


def has_devanagari(text: str) -> bool:
    return bool(text and _DEVANAGARI_RE.search(text))


def _transliterate_word(word: str) -> str:
    if not has_devanagari(word):
        return word

    out: list[str] = []
    i = 0
    n = len(word)

    while i < n:
        ch = word[i]

        # Check nukta combination (consonant + nukta)
        if i + 1 < n and word[i + 1] == _NUKTA and (ch + _NUKTA) in _CONSONANTS:
            cons = _CONSONANTS[ch + _NUKTA]
            i += 2
        elif ch in _CONSONANTS:
            cons = _CONSONANTS[ch]
            i += 1
        elif ch in _INDEPENDENT_VOWELS:
            out.append(_INDEPENDENT_VOWELS[ch])
            i += 1
            continue
        elif ch in _MODIFIERS:
            out.append(_MODIFIERS[ch])
            i += 1
            continue
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
            i += 1
            continue
        elif ch in _MATRAS or ch == _HALANT or ch == _NUKTA:
            i += 1
            continue
        else:
            out.append(ch)
            i += 1
            continue

        # We matched a consonant; inspect what follows
        if i < n and word[i] == _HALANT:
            # Suppress inherent 'a'
            out.append(cons)
            i += 1
        elif i < n and word[i] in _MATRAS:
            out.append(cons + _MATRAS[word[i]])
            i += 1
        else:
            # Inherent schwa 'a', deleted at the very end of a multi-char Devanagari word
            is_word_end = (i >= n) or (not _DEVANAGARI_RE.match(word[i]) and word[i] not in _MODIFIERS)
            has_preceding = len(out) > 0
            if is_word_end and has_preceding:
                out.append(cons)
            else:
                out.append(cons + "a")

    return "".join(out)


def transliterate_devanagari_to_hinglish(text: str) -> str:
    """Convert any Devanagari spans in `text` to Romanized Hinglish."""
    if not text or not has_devanagari(text):
        return text
    tokens = re.split(r"(\s+)", text)
    return "".join(_transliterate_word(tok) if not tok.isspace() else tok for tok in tokens)

