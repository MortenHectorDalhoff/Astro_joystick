"""Utility helpers for coordinate handling."""

import math
from typing import Tuple


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ra_hours_to_deg(hours: float) -> float:
    return (hours % 24.0) * 15.0


def deg_to_ra_hours(deg: float) -> float:
    return (deg / 15.0) % 24.0


def parse_sexagesimal(value: str, *, hours: bool = False) -> float:
    """Parse sexagesimal strings like '12:30:00' or '-05 23 28'."""
    text = value.strip()
    if not text:
        raise ValueError("Empty value")
    sign = -1 if text.startswith("-") else 1
    cleaned = text.lstrip("+-")
    cleaned = (
        cleaned.replace("h", " ")
        .replace("d", " ")
        .replace("m", " ")
        .replace("s", " ")
        .replace("°", " ")
        .replace("'", " ")
        .replace('"', " ")
        .replace(":", " ")
    )
    parts = cleaned.split()
    numbers = [abs(float(p)) for p in parts]
    base = numbers[0] if numbers else 0.0
    minutes = numbers[1] / 60.0 if len(numbers) > 1 else 0.0
    seconds = numbers[2] / 3600.0 if len(numbers) > 2 else 0.0
    total = sign * (base + minutes + seconds)
    if hours:
        return total % 24.0
    return total


def format_ra(hours: float) -> str:
    hours = hours % 24.0
    h = int(hours)
    m_float = (hours - h) * 60
    m = int(m_float)
    s = (m_float - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def format_dec(deg: float) -> str:
    sign = "-" if deg < 0 else "+"
    deg_abs = abs(deg)
    d = int(deg_abs)
    m_float = (deg_abs - d) * 60
    m = int(m_float)
    s = (m_float - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:05.1f}"


def angular_distance(ra1_hours: float, dec1_deg: float, ra2_hours: float, dec2_deg: float) -> float:
    ra1 = math.radians(ra_hours_to_deg(ra1_hours))
    ra2 = math.radians(ra_hours_to_deg(ra2_hours))
    dec1 = math.radians(dec1_deg)
    dec2 = math.radians(dec2_deg)
    cos_d = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    cos_d = clamp(cos_d, -1.0, 1.0)
    return math.degrees(math.acos(cos_d))


def direction_hint(
    current_ra_hours: float, current_dec_deg: float, target_ra_hours: float, target_dec_deg: float
) -> Tuple[float, float]:
    delta_ra_deg = (ra_hours_to_deg(target_ra_hours) - ra_hours_to_deg(current_ra_hours))
    delta_ra_deg = (delta_ra_deg + 180) % 360 - 180  # normalize
    delta_dec_deg = target_dec_deg - current_dec_deg
    return delta_ra_deg, delta_dec_deg
