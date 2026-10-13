"""Conservative title matching helpers.

Names and aliases help find candidates; only exact provider or external IDs merge records.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if character.isalnum() and not unicodedata.combining(character))


def close_name(query: str, candidate: str) -> bool:
    left, right = normalize_name(query), normalize_name(candidate)
    if not left or not right:
        return False
    if left == right:
        return True
    # Short partial queries are suggestions, not evidence that the title exists.
    if len(left) < 5:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.88
