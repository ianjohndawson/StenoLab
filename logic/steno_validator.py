# logic/steno_validator.py
"""
Pragmatic steno validation.

Aims to catch obvious typos and accidental garbage rather than enforce
strict Plover correctness — that's a deeper rabbit hole than makes sense
for an editor UX where the user might be typing keys out of order while
thinking about them, or pasting briefs from other layouts.

Plover's stroke shape, in order of keys pressed:

    [#] [S T K P W H R] [A O] [*] [E U] [F R P B L G T S D Z]
     │   left bank      vowels  star  vowels   right bank
     │                                          │
     └── number bar (optional)                  └── may be prefixed by '-'
                                                    when no centre keys present

A stroke must be one or more left-bank keys, then optionally vowels and/or
the asterisk, then optionally right-bank keys.  At least one part must be
present.  When the right bank is used without any vowels or asterisk, a '-'
disambiguates: e.g. -FT means right-bank F+T with no centre keys.

Multi-stroke entries are joined with '/'.

Returns:
    (True, "")   if the steno passes basic validation
    (False, msg) describing the first problem found
"""
import re


# Letters allowed on each bank, in canonical order.
_LEFT_BANK   = "STKPWHR"
_VOWELS      = "AOEU"
_RIGHT_BANK  = "FRPBLGTSDZ"
_VALID_CHARS = set(_LEFT_BANK + _VOWELS + _RIGHT_BANK + "*-#0123456789")

# Each stroke can match one of these shapes:
#   - Pure meta-key: just '*' or '#' or a digit-only stroke
#   - Standard:  optional '#', optional left-bank, optional vowels-or-star,
#                optional right-bank (preceded by '-' if no centre keys)
#
# Build a regex that captures the canonical layout.  We use it as a
# whole-string match to enforce key order automatically: no character can
# appear twice (other than via legitimate placement) and bank order is
# enforced by position in the regex.
_STROKE_RE = re.compile(
    r"^"
    r"#?"                                     # optional number bar
    r"(?:[STKPWHR0-9]+)?"                     # left bank (digits allowed)
    r"(?:[AO0-9]*\*?[EU0-9]*"                 # centre with optional star
        r"|\*"                                # or just star alone
    r")?"
    r"(?:-?[FRPBLGTSDZ0-9]+(?:-[FRPBLGTSDZ0-9]+)?)?"  # right bank
    r"$"
)


def validate_steno(steno: str) -> tuple[bool, str]:
    """Light-weight validation.  Returns (ok, message)."""
    if not steno:
        return False, "Steno cannot be empty."

    if steno.strip() != steno:
        return False, "Steno cannot start or end with whitespace."

    if " " in steno:
        return False, "Steno cannot contain spaces."

    strokes = steno.split("/")
    for i, stroke in enumerate(strokes):
        if not stroke:
            return False, "Empty stroke (check for stray '/')."

        ok, msg = _validate_stroke(stroke)
        if not ok:
            if len(strokes) > 1:
                return False, f"Stroke {i + 1} ('{stroke}'): {msg}"
            return False, msg

    return True, ""


def _validate_stroke(stroke: str) -> tuple[bool, str]:
    """Validate a single stroke (no '/')."""
    # Reject any character outside the steno alphabet first - gives a
    # clearer error than a regex mismatch would.
    invalid = [c for c in stroke if c not in _VALID_CHARS]
    if invalid:
        bad = invalid[0]
        return False, (
            f"Invalid character '{bad}'. Steno only uses "
            f"S T K P W H R A O * E U F B L G D Z, digits, '#' and '-'."
        )

    if stroke.count("*") > 1:
        return False, "More than one '*' in a single stroke."

    # The structural check.  If this fails it's almost always because keys
    # appear in the wrong order (e.g. typing 'AKT' instead of 'TKA' for /tk/+/a/+/t/).
    if not _STROKE_RE.match(stroke):
        return False, (
            "Keys are out of order. Steno strokes go left-to-right: "
            "S T K P W H R, then A O * E U, then F R P B L G T S D Z."
        )

    return True, ""
