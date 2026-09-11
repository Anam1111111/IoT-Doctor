from dataclasses import dataclass
from typing import Dict, List, Any


@dataclass
class ParseResult:
    fields: Dict[str, Any]
    raw_lines: List[str]
    format: str
    confidence: float  # 0.0-1.0
    is_multiline: bool = False


class Parser:
    """Parser interface: implement parse(lines: List[str] | str) -> ParseResult or None"""

    def parse(self, raw_lines: List[str] | str) -> ParseResult | None:
        raise NotImplementedError()
