# logic/frequency_importer.py
import csv
import io
import math
import re
from urllib.request import Request, urlopen

DEFAULT_UK_FREQUENCY_URL = "https://ucrel.lancs.ac.uk/bncfreq/lists/1_2_all_freq.txt"

_WORD_CLEAN_RE = re.compile(r"[^a-z'-]+")


def download_frequency_text(url: str = DEFAULT_UK_FREQUENCY_URL, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "StenoLab/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    text = data.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        # Replacement characters mean the response contained bytes that
        # weren't valid UTF-8.  This can indicate a network error or an
        # unexpected encoding.  We still return what we have so the caller
        # can decide whether the result is usable.
        print(
            f"[StenoEditor] Warning: frequency download from {url} contained "
            "invalid UTF-8 bytes (replaced with \ufffd). "
            "The parsed result may be incomplete."
        )
    return text


def parse_frequency_text(text: str) -> dict[str, int]:
    """Parse common frequency-list formats into {word: frequency}.

    Supports:
    - space/tab-delimited lines like: "word POS freq"
    - csv-like rows where frequency appears in a numeric column
    """
    out: dict[str, int] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("word ") or line.lower().startswith("word,"):
            continue

        row = _split_row(line)
        parsed = _parse_row(row)
        if not parsed:
            continue
        word, freq = parsed

        prev = out.get(word)
        if prev is None or freq > prev:
            out[word] = freq

    return out


def parse_frequency_file(path: str) -> dict[str, int]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse_frequency_text(f.read())


def _split_row(line: str) -> list[str]:
    if "," in line:
        try:
            return next(csv.reader(io.StringIO(line)))
        except Exception:
            pass
    if "	" in line:
        return line.split("	")
    return line.split()


def _parse_row(cells: list[str]) -> tuple[str, int] | None:
    cells = [c.strip() for c in cells if c is not None and c.strip()]
    if len(cells) < 2:
        return None

    nums = []
    for i, c in enumerate(cells):
        try:
            f = float(c)
        except ValueError:
            continue
        # float("inf") / float("nan") are valid Python floats but cannot be
        # converted to int — skip them so they don't cause an OverflowError.
        if not math.isfinite(f):
            continue
        nums.append((i, int(f)))
    if not nums:
        return None

    freq_idx, freq = nums[-1]

    word_idx = 0
    if _looks_numeric(cells[0]) and len(cells) > 1:
        word_idx = 1
    if word_idx == freq_idx and len(cells) > 2:
        word_idx = 1 if word_idx == 0 else 0

    word = _normalize_word(cells[word_idx])
    if not word:
        return None
    if freq < 0:
        return None
    return word, freq


def _normalize_word(word: str) -> str:
    word = word.lower().strip().strip('"')
    word = word.replace("*", "")
    word = _WORD_CLEAN_RE.sub("", word)
    return word


def _looks_numeric(s: str) -> bool:
    try:
        return math.isfinite(float(s))
    except ValueError:
        return False
