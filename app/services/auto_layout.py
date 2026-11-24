"""Deterministic geometry completion and a small text-only construction fallback."""

import math
import re
import unicodedata
from collections.abc import Iterable

from app.extraction.proposal import ProposedField
from app.extraction.schemas import (
    MAX_COMPONENTS,
    MAX_LEVELS,
    MAX_ROOMS,
    BuildProposal,
    Fields,
    ProposedLevel,
)

GRID_M = 0.15
DEFAULT_HEIGHT_M = 2.7

_NUMBER = r"\d+(?:[.,]\d+)?"
_ROOMS: tuple[tuple[str, tuple[str, ...], tuple[float, float]], ...] = (
    ("sala-comedor", ("sala-comedor", "sala comedor"), (6.0, 3.6)),
    (
        "dormitorio",
        (
            "dormitorio",
            "dormitorios",
            "habitación",
            "habitaciones",
            "habitacion",
            "bedroom",
            "bedrooms",
        ),
        (3.6, 3.3),
    ),
    ("sala", ("sala", "salas", "salón", "salones", "salon", "living"), (4.5, 3.6)),
    ("cocina", ("cocina", "cocinas", "kitchen", "kitchens"), (3.0, 2.7)),
    ("baño", ("baño", "baños", "bano", "banos", "bathroom", "bathrooms"), (2.1, 1.8)),
    ("comedor", ("comedor", "comedores", "dining room"), (3.0, 3.0)),
    ("estudio", ("estudio", "estudios", "study", "office"), (3.0, 2.7)),
    ("garaje", ("garaje", "garajes", "garage", "garages"), (5.4, 5.4)),
    ("lavandería", ("lavandería", "lavanderías", "lavanderia", "laundry"), (2.4, 2.1)),
    ("patio", ("patio", "patios"), (4.5, 3.0)),
)
_ROOM_PATTERN = re.compile(
    r"\b("
    + "|".join(
        re.escape(word)
        for word in sorted(
            {word for _, words, _ in _ROOMS for word in words},
            key=len,
            reverse=True,
        )
    )
    + r")\b",
    re.IGNORECASE,
)
_COMPONENTS = (
    ("column", re.compile(r"\b(?:columnas?|pilares?|columns?)\b", re.IGNORECASE), "Columna"),
    ("beam", re.compile(r"\b(?:vigas?|beams?)\b", re.IGNORECASE), "Viga"),
    ("wall", re.compile(r"\b(?:muros?|paredes?|walls?)\b", re.IGNORECASE), "Muro"),
)
_FLOORS = (
    ("planta baja", re.compile(r"\bplanta\s+baja\b", re.IGNORECASE)),
    ("planta alta", re.compile(r"\bplanta\s+alta\b", re.IGNORECASE)),
    ("primer piso", re.compile(r"\bprimer(?:a)?\s+piso\b", re.IGNORECASE)),
    ("segundo piso", re.compile(r"\bsegund[oa]\s+piso\b", re.IGNORECASE)),
    ("tercer piso", re.compile(r"\btercer(?:a)?\s+piso\b", re.IGNORECASE)),
    ("sótano", re.compile(r"\bsótano\b|\bsotano\b", re.IGNORECASE)),
)
_NUMBER_WORDS = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


def _grid(value: float) -> float:
    if value <= 0:
        return 0.0

    return round(math.ceil((value - 1e-8) / GRID_M) * GRID_M, 2)


def _fit_to_lot(value: float, lot_dimension: float | None) -> float:
    if lot_dimension is None or not math.isfinite(lot_dimension) or lot_dimension <= 0:
        return value

    return max(GRID_M, math.floor((lot_dimension + 1e-8) / GRID_M) * GRID_M)


def _number(value: str) -> float | None:
    try:
        result = float(value.replace(",", "."))
    except ValueError:
        return None

    return result if math.isfinite(result) and result > 0 else None


def _field(
    value: str | float,
    source: str,
    origin: str | None = None,
) -> ProposedField:
    return ProposedField(
        value=value,
        confidence=0.0 if origin == "ai_generated" else 1.0,
        source=source,
        origin=origin,
    )


def _generated(fields: Fields, key: str, value: str | float) -> None:
    if key not in fields:
        fields[key] = _field(value, "", "ai_generated")


def _value(fields: Fields, key: str) -> float | None:
    field = fields.get(key)

    if field is None or isinstance(field.value, bool):
        return None

    try:
        value = float(field.value)
    except (ValueError, TypeError):
        return None

    return value if math.isfinite(value) and value > 0 else None


def _default_room_size(name: str) -> tuple[float, float]:
    lowered = name.casefold()

    for canonical, words, size in _ROOMS:
        if lowered == canonical or any(word in lowered for word in words):
            return size

    return 3.6, 3.0


def _room_kind(name: str) -> str:
    lowered = name.casefold()

    for canonical, words, _ in _ROOMS:
        if lowered in words:
            return canonical

    return lowered


def _quantity_before(text: str, position: int) -> int:
    prefix = text[:position]
    match = re.search(
        r"\b(?P<count>\d+|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
        r"\s+(?:de\s+)?$",
        prefix,
        re.IGNORECASE,
    )

    if match is None:
        return 1

    token = match.group("count").casefold()
    return min(MAX_ROOMS, int(token) if token.isdigit() else _NUMBER_WORDS[token])


def _bounds(items: Iterable[Fields]) -> tuple[float, float]:
    right = bottom = 0.0

    for fields in items:
        x, y = _value(fields, "x_m") or 0, _value(fields, "y_m") or 0
        right = max(right, x + (_value(fields, "width_m") or 0))
        bottom = max(bottom, y + (_value(fields, "depth_m") or 0))

    return right, bottom


def complete_geometry(
    proposal: BuildProposal, lot_width_m: float | None = None, lot_length_m: float | None = None
) -> BuildProposal:
    """Fill absent dimensions and positions without replacing documented values."""
    completed: list[ProposedLevel] = []

    for level_index, level in enumerate(proposal.levels):
        level_fields = dict(level.fields)
        default_title = "Planta baja" if level_index == 0 else f"Nivel {level_index + 1}"
        _generated(level_fields, "title", default_title)
        rooms = [dict(room) for room in level.rooms]
        components = [dict(component) for component in level.components]

        for room in rooms:
            name_field = room.get("name")
            name = "room" if name_field is None else str(name_field.value)
            default_width, default_depth = _default_room_size(name)
            default_width = _fit_to_lot(default_width, lot_width_m)
            default_depth = _fit_to_lot(default_depth, lot_length_m)
            _generated(room, "width_m", default_width)
            _generated(room, "depth_m", default_depth)
            _generated(room, "height_m", DEFAULT_HEIGHT_M)

        for component in components:
            kind_field = component.get("kind")
            kind = "wall" if kind_field is None else str(kind_field.value)
            if kind == "column":
                default_width, default_depth = 0.30, 0.30
            elif kind == "beam":
                default_width, default_depth = 3.0, 0.30
            else:
                default_width, default_depth = 3.0, 0.15

            default_width = _fit_to_lot(default_width, lot_width_m)
            default_depth = _fit_to_lot(default_depth, lot_length_m)
            _generated(component, "width_m", default_width)
            _generated(component, "depth_m", default_depth)
            _generated(component, "height_m", DEFAULT_HEIGHT_M)

        # A compact shelf layout keeps the rooms on a shared 15 cm grid.
        total_area = sum(
            (_value(room, "width_m") or 0) * (_value(room, "depth_m") or 0) for room in rooms
        )
        component_area = sum(
            (_value(item, "width_m") or 0) * (_value(item, "depth_m") or 0) for item in components
        )
        if lot_width_m and math.isfinite(lot_width_m) and lot_width_m > 0:
            shelf_width = lot_width_m
        elif lot_length_m and math.isfinite(lot_length_m) and lot_length_m > 0:
            shelf_width = max(
                (_value(room, "width_m") or 0 for room in rooms),
                default=max((_value(item, "width_m") or 0 for item in components), default=GRID_M),
            )
            if len(rooms) > 1:
                shelf_width = max(shelf_width, _grid(total_area / lot_length_m))
            elif not rooms and len(components) > 1:
                shelf_width = max(shelf_width, _grid(component_area / lot_length_m))
        else:
            shelf_width = max(
                (_value(room, "width_m") or 0 for room in rooms),
                default=max((_value(item, "width_m") or 0 for item in components), default=GRID_M),
            )
            if len(rooms) > 1:
                shelf_width = max(shelf_width, _grid(math.sqrt(total_area)))
            elif not rooms and len(components) > 1:
                shelf_width = max(shelf_width, _grid(math.sqrt(component_area)))

        cursor_x = cursor_y = row_depth = 0.0
        for room in rooms:
            width, depth = _value(room, "width_m") or GRID_M, _value(room, "depth_m") or GRID_M
            width, depth = round(width, 2), round(depth, 2)

            if cursor_x > 0 and cursor_x + width > shelf_width + 1e-8:
                cursor_y = _grid(cursor_y + row_depth)
                cursor_x = row_depth = 0.0

            _generated(room, "x_m", _grid(cursor_x))
            _generated(room, "y_m", _grid(cursor_y))
            x = _value(room, "x_m") or 0
            cursor_x = _grid(max(cursor_x, x) + width + GRID_M)
            row_depth = max(row_depth, depth + GRID_M)

        # Components use the next aligned band outside the room footprint. This keeps
        # them from colliding with room rectangles while preserving a shared facade line.
        _, room_bottom = _bounds(rooms)
        cursor_x = 0.0
        component_depth = 0.0
        component_band_y = _grid(room_bottom + GRID_M)

        for component in components:
            width, depth = (
                _value(component, "width_m") or GRID_M,
                _value(component, "depth_m") or GRID_M,
            )

            if cursor_x > 0 and cursor_x + width > shelf_width + 1e-8:
                component_band_y = _grid(component_band_y + component_depth + GRID_M)
                cursor_x = component_depth = 0.0

            _generated(component, "x_m", _grid(cursor_x))
            _generated(component, "y_m", component_band_y)
            x = _value(component, "x_m") or 0
            cursor_x = _grid(max(cursor_x, x) + width + GRID_M)
            component_depth = max(component_depth, depth)

        completed.append(ProposedLevel(fields=level_fields, rooms=rooms, components=components))

    return proposal.model_copy(update={"levels": completed})


def _floor_count(text: str) -> int:
    match = re.search(
        r"\b(?:de\s+)?(?P<count>\d+|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
        r"\s+(?:pisos?|plantas?|niveles?)\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return 0

    token = match.group("count").casefold()
    return min(MAX_LEVELS, int(token) if token.isdigit() else _NUMBER_WORDS[token])


def _floor_sections(text: str) -> list[tuple[str, int, int]]:
    markers: list[tuple[int, int, str]] = []

    for _title, pattern in _FLOORS:
        markers.extend(
            (match.start(), match.end(), match.group()) for match in pattern.finditer(text)
        )

    markers.sort()
    unique: list[tuple[int, int, str]] = []
    for marker in markers:
        if not unique or marker[0] >= unique[-1][1]:
            unique.append(marker)

    return [
        (title, start, unique[index + 1][0] if index + 1 < len(unique) else len(text))
        for index, (start, _, found) in enumerate(unique)
        for title in [found.strip()]
    ]


def _extract_measure(text: str, names: tuple[str, ...]) -> tuple[float, str] | None:
    cue = "|".join(names)
    patterns = (
        rf"(?P<n>{_NUMBER})\s*(?:m|metros?)\s*(?:de\s+)?(?:{cue})\b",
        rf"(?:{cue})\s*(?:de\s+)?(?P<n>{_NUMBER})\s*(?:m|metros?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _number(match.group("n"))
            if value is not None:
                return value, match.group()

    return None


def _room_fields(text: str, match: re.Match[str]) -> Fields:
    found = match.group()
    end = len(text)
    later_room = _ROOM_PATTERN.search(text, match.end())
    later_component = min(
        (
            found_component.start()
            for _, pattern, _ in _COMPONENTS
            if (found_component := pattern.search(text, match.end())) is not None
        ),
        default=len(text),
    )
    end = min(end, later_room.start() if later_room else end, later_component)
    segment = text[match.start() : end].split(";")[0].split(".")[0]
    fields: Fields = {"name": _field(_room_kind(found)[:160], found)}

    for key, cues in (
        ("width_m", ("ancho", "anchura", "wide", "width")),
        ("depth_m", ("fondo", "profundidad", "deep", "depth", "length")),
        ("height_m", ("altura", "alto", "height", "tall")),
    ):
        measure = _extract_measure(segment, cues)
        if measure is not None and measure[0] < 1000:
            fields[key] = _field(measure[0], measure[1])

    return fields


def _component_fields(text: str, match: re.Match[str], kind: str) -> Fields:
    end = len(text)
    later_room = _ROOM_PATTERN.search(text, match.end())
    later_component = min(
        (
            found_component.start()
            for _, pattern, _ in _COMPONENTS
            if (found_component := pattern.search(text, match.end())) is not None
        ),
        default=len(text),
    )
    end = min(end, later_room.start() if later_room else end, later_component)
    segment = text[match.start() : end].split(";")[0].split(".")[0]
    name = match.group()[:160]
    fields: Fields = {
        "kind": _field(kind, match.group()),
        "name": _field(name, match.group()),
    }

    thickness = _extract_measure(segment, ("espesor", "thickness"))
    if thickness is not None and thickness[0] < 1000:
        fields["depth_m"] = _field(thickness[0], thickness[1])

    return fields


def _section_items(text: str) -> tuple[list[Fields], list[Fields], bool]:
    rooms: list[Fields] = []
    for match in _ROOM_PATTERN.finditer(text):
        quantity = _quantity_before(text, match.start())

        for index in range(quantity):
            room = _room_fields(text, match)
            if quantity > 1:
                label = _room_kind(match.group()).replace("-", " ").title()
                room["name"] = _field(f"{label} {index + 1}", "", "ai_generated")
            rooms.append(room)

    components = [
        _component_fields(text, match, kind)
        for kind, pattern, _ in _COMPONENTS
        for match in pattern.finditer(text)
    ]

    return (
        rooms[:MAX_ROOMS],
        components[:MAX_COMPONENTS],
        (len(rooms) > MAX_ROOMS or len(components) > MAX_COMPONENTS),
    )


def _title_field(title: str, source: str | None) -> Fields:
    if source is not None:
        return {"title": ProposedField(value=title, confidence=1.0, source=source[:200])}

    return {"title": _field(title, "", "ai_generated")}


def from_description(
    text: str, lot_width_m: float | None = None, lot_length_m: float | None = None
) -> BuildProposal:
    """Create a conservative proposal from explicit room/floor words in user text."""
    sections = _floor_sections(text)
    requested_levels = max(len(sections), _floor_count(text), 1)
    count = min(requested_levels, MAX_LEVELS)
    levels: list[ProposedLevel] = []
    truncated = requested_levels > MAX_LEVELS
    if len(sections) > MAX_LEVELS:
        truncated = True

    if sections:
        for title, start, end in sections[:MAX_LEVELS]:
            source = text[start : start + len(title)]
            rooms, components, more_items = _section_items(text[start:end])
            truncated = truncated or more_items
            fields = _title_field(title, source)
            if rooms or components or len(sections) > 1 or _floor_count(text):
                levels.append(ProposedLevel(fields=fields, rooms=rooms, components=components))
    else:
        rooms, components, more_items = _section_items(text)
        truncated = truncated or more_items
        private_rooms = [
            room
            for room in rooms
            if any(
                word in str(room["name"].value).casefold()
                for word in ("dormitorio", "habitación", "bedroom")
            )
        ]
        for index in range(count):
            title = "Planta baja" if index == 0 else f"Nivel {index + 1}"
            levels.append(
                ProposedLevel(
                    fields=_title_field(title, None),
                    rooms=(
                        [room for room in rooms if room not in private_rooms]
                        if index == 0
                        else private_rooms
                        if index == count - 1
                        else []
                    ),
                    components=components if index == 0 else [],
                )
            )

    # A description may name only the number of floors; retain them as editable level proposals.
    while len(levels) < count:
        index = len(levels)
        title = "Planta baja" if index == 0 else f"Nivel {index + 1}"
        levels.append(ProposedLevel(fields=_title_field(title, None)))

    proposal = BuildProposal(
        origin="description",
        fallback=True,
        levels=levels[:MAX_LEVELS],
        truncated=truncated or len(levels) > MAX_LEVELS,
    )
    return complete_geometry(proposal, lot_width_m, lot_length_m)


def _normalised(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def lot_dimensions(text: str) -> tuple[float | None, float | None]:
    """Read an explicit `width x length m` lot size from description text."""
    normalized = _normalised(text)
    match = re.search(
        rf"\b(?:lote|terreno|lot)\b[^.;]{{0,80}}?({_NUMBER})\s*(?:m|metros?)?\s*"
        rf"(?:[x×]|\bpor\b|\bby\b)\s*"
        rf"({_NUMBER})\s*(?:m|metros?)\b",
        normalized,
    )
    if match is not None:
        return _number(match.group(1)), _number(match.group(2))

    width = re.search(
        rf"\b(?:ancho|anchura|width)\b(?:\s+(?:(?:del?\s+)?(?:lote|terreno)))?"
        rf"\s*(?:de|es|:)?\s*({_NUMBER})\s*(?:m|metros?)\b",
        normalized,
    ) or re.search(
        rf"({_NUMBER})\s*(?:m|metros?)\s*(?:de\s+)?\b(?:ancho|anchura|width)\b",
        normalized,
    )
    length = re.search(
        rf"\b(?:largo|longitud|fondo|length|depth)\b"
        rf"(?:\s+(?:(?:del?\s+)?(?:lote|terreno)))?"
        rf"\s*(?:de|es|:)?\s*({_NUMBER})\s*(?:m|metros?)\b",
        normalized,
    ) or re.search(
        rf"({_NUMBER})\s*(?:m|metros?)\s*(?:de\s+)?\b"
        rf"(?:largo|longitud|fondo|length|depth)\b",
        normalized,
    )
    return (
        _number(width.group(1)) if width else None,
        _number(length.group(1)) if length else None,
    )
