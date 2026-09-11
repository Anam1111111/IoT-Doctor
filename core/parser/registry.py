from typing import Dict, Callable
from core.parser.base import Parser

_registry: Dict[str, Callable[[], Parser]] = {}


def register(name: str, factory: Callable[[], Parser]) -> None:
    _registry[name] = factory


def get(name: str) -> Parser | None:
    f = _registry.get(name)
    return f() if f else None


def available() -> list:
    return list(_registry.keys())
