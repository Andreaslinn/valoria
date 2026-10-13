"""Strict source coordinates; never apply currency/thousands normalization."""
import math
import re
from decimal import Decimal
from typing import Any


def coordinate_pair(latitude: Any, longitude: Any) -> tuple[float | None, float | None]:
    values = []
    for value, limit in ((latitude, 90), (longitude, 180)):
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            return None, None
        if isinstance(value, str) and not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", value.strip()):
            return None, None
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None, None
        if not math.isfinite(number) or not -limit <= number <= limit:
            return None, None
        values.append(number)
    return values[0], values[1]
