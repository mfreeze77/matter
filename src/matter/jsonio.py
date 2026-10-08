"""Strict JSON loading shared by repository tooling."""

import json
import math
from pathlib import Path
from typing import Any


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite JSON number: {value}")
    return result


def loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)


def read(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
