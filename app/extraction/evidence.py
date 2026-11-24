"""Whether the quote a provider gives really holds the value it proposes.

The quote also comes from the model, so this does not prove that the document says it: it only
keeps estimates and guesses from being applied without review (D-AI-3).
"""

import re

PAGE_REFERENCE = re.compile(r"\b(?:p[aá]g(?:ina|\.)?|page|p\.)\s*\d+\b", re.IGNORECASE)
COORDINATES = re.compile(r"-?\d{1,3}[.,]\d{3,}\s*[,;/ ]\s*-?\d{1,3}[.,]\d{3,}")
NUMBER = re.compile(r"-?\d+(?:(?:[.,]|[ '’´`‘](?=\d{3}(?!\d)))\d+)*")
BEFORE_A_NUMBER = re.compile(r"(?:[\w.,'’-]|\d\s{1,3}|-\s{1,3})\Z")
MAX_QUOTE = 500
NOT_A_READING = re.compile(
    r"\b(?:not stated|estimated|estimate|guess|assumed|inferred"
    r"|no indica|estimad[oa]|supuest[oa])\b",
    re.IGNORECASE,
)

LENGTH_UNIT = re.compile(
    r"\s*(?:metros?|met(?:er|re)s?|m)\b(?!\s*(?:\^|²|2\b|cuadrad|square))", re.IGNORECASE
)
UNITS = {
    "area_m2": re.compile(r"\s*(?:m2\b|m²|metros cuadrados|square met)", re.IGNORECASE),
    "width_m": LENGTH_UNIT,
    "length_m": LENGTH_UNIT,
    "depth_m": LENGTH_UNIT,
    "height_m": LENGTH_UNIT,
    "slope_percent": re.compile(r"\s*(?:%|por ciento|percent)", re.IGNORECASE),
}


def holds_coordinates(text: str) -> bool:
    return COORDINATES.search(text) is not None


def _readings(token: str) -> set[float]:
    """1.250,5 and 1 250,5 are the same number. 2.500 can be two numbers: it waits for review."""
    # Digits split by a space or an apostrophe can be one number or two: it waits for review.
    if re.search(r"[ '’´`‘]", token):
        return set()

    if re.fullmatch(r"-?[1-9]\d{0,2}[.,]\d{3}", token):
        return set()

    if "." in token and "," in token:
        decimal = "." if token.rfind(".") > token.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        candidates = [token.replace(thousands, "").replace(decimal, ".")]
    elif token.count(".") + token.count(",") > 1:
        candidates = [token.replace(".", "").replace(",", "")]
    else:
        candidates = [token.replace(",", ".")]

    found = set()

    for candidate in candidates:
        try:
            found.add(round(float(candidate), 2))
        except (ValueError, OverflowError):
            continue

    return found


def _normalised(text: str) -> str:
    text = re.sub("[\u2212\u2012\u2013\u2014\u2015]", "-", text)

    return re.sub("[\u00a0\u2007\u2009\u202f]", " ", text)


def is_within(quote: str, text: str) -> bool:
    """Whether the quote is really part of the text the user wrote."""
    return " ".join(_normalised(quote).casefold().split()) in " ".join(
        _normalised(text).casefold().split()
    )


def is_quoted(name: str, value: str | float, quote: str) -> bool:
    """Whether the quote holds the value, and a measure with its unit."""
    if len(quote) > MAX_QUOTE:
        return False

    quote = _normalised(quote)

    if NOT_A_READING.search(quote):
        return False

    quote = PAGE_REFERENCE.sub(" | ", quote)

    if isinstance(value, str):
        return " ".join(value.casefold().split()) in " ".join(quote.casefold().split())

    unit = UNITS.get(name)

    return unit is not None and any(
        value in _readings(match.group())
        and unit.match(quote, match.end())
        and not BEFORE_A_NUMBER.search(quote[max(0, match.start() - 6) : match.start()])
        for match in NUMBER.finditer(quote)
    )


# The words that name each kind of structural component, in the languages of the documents.
KIND_WORDS = {
    "column": ("columna", "pilar", "column"),
    "beam": ("viga", "beam"),
    "wall": ("muro", "pared", "wall"),
}


def names_kind(kind: str, quote: str) -> bool:
    """Whether the quote really names that kind of component."""
    if len(quote) > MAX_QUOTE or NOT_A_READING.search(_normalised(quote)):
        return False

    text = _normalised(quote).casefold()

    return any(re.search(rf"\b{re.escape(word)}", text) for word in KIND_WORDS.get(kind, ()))


def is_supported(name: str, value: str | float, source: str) -> bool:
    """A quote of a document has to say on which page it is."""
    if len(source) > MAX_QUOTE or not PAGE_REFERENCE.search(_normalised(source)):
        return False

    return is_quoted(name, value, source)
