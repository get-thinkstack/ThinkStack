"""How an author list survives a store that only holds strings.

Chunk metadata values are scalars (str, int, float, bool), so a list of
authors is flattened to write and rebuilt to read. Never with commas: in
BibTeX the comma is syntax (`Vaswani, Ashish and Shazeer, Noam` is two
people), so re-splitting on commas turns eight authors into sixteen
half-names. JSON keeps the boundaries.

`decode` still reads the old comma form, because papers ingested before the
switch are stored that way and a library is not re-ingested to fix a codec.
"""

import json


def encode_authors(authors) -> str:
    """A list of names as one metadata string. `[]` becomes `""`."""
    names = [str(a).strip() for a in (authors or []) if str(a).strip()]
    return json.dumps(names, ensure_ascii=False) if names else ""


def decode_authors(value) -> list[str]:
    """Names back out, whichever way they were written.

    Legacy rows split on commas and are wrong wherever a name was stored
    surname-first. That is not repairable from the string -- `Vaswani, Ashish`
    and `Vaswani, Shazeer` are indistinguishable -- so the old form is read as
    written rather than guessed at.
    """
    if isinstance(value, list):
        return [str(a).strip() for a in value if str(a).strip()]

    text = str(value or "").strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(a).strip() for a in parsed if str(a).strip()]

    return [part.strip() for part in text.split(",") if part.strip()]


def authors_display(value) -> str:
    """The names as one line, for a UI that wants a sentence not a list."""
    return ", ".join(decode_authors(value))
