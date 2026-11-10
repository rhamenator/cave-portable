"""Display-unit choices for app-generated values; raw source messages stay intact."""

from __future__ import annotations

import math
import re

MODES = ("US", "Metric", "Hybrid")
DEFAULT = "Hybrid"


def validate(mode: str) -> str:
    if mode not in MODES:
        raise ValueError("Choose US, Metric, or Hybrid units")
    return mode


def temperature(celsius: float | None, mode: str, precision: int = 1) -> str:
    if celsius is None or not math.isfinite(celsius):
        return "—"
    value = celsius * 9 / 5 + 32 if mode == "US" else celsius
    return f"{value:.{precision}f} °{'F' if mode == 'US' else 'C'}"


def wind(knots_text: str, mode: str) -> str:
    """Convert the normalized METAR wind string, leaving unknown values visible."""
    match = re.fullmatch(r"(.+?) (\d+(?:\.\d+)?) kt", knots_text)
    if not match:
        return knots_text
    speed = float(match[2])
    if mode == "US":
        return f"{match[1]} {speed * 1.150779:.0f} mph"
    return f"{match[1]} {speed * 1.852:.0f} km/h"


def visibility(miles_text: str, mode: str) -> str:
    try:
        miles = float(miles_text)
    except (TypeError, ValueError):
        return miles_text
    return f"{miles * 1.609344:.1f}" if mode != "US" else f"{miles:g}"


def visibility_unit(mode: str) -> str:
    return "km" if mode != "US" else "mi"


def visibility_display(miles_text: str, mode: str) -> str:
    if miles_text == "—":
        return "—"
    value = visibility(miles_text, mode)
    if value == miles_text and mode != "US":
        try:
            float(miles_text)
        except (TypeError, ValueError):
            return f"{miles_text} mi (source)"
    return f"{value} {visibility_unit(mode)}"


def snow(mm: float, mode: str) -> str:
    return f"{mm / 25.4:.1f} in" if mode != "Metric" else f"{mm / 10:.1f} cm"


def ice(mm: float, mode: str) -> str:
    return f"{mm / 25.4:.1f} in" if mode != "Metric" else f"{mm:.1f} mm"


def speed_kmh(kmh: float, mode: str) -> str:
    return f"{kmh * 0.621371:.0f} mph" if mode == "US" else f"{kmh:.0f} km/h"
