from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Metric:
    name: str
    value: Any
    unit: str | None = None
    timestamp: str | None = None
    device_id: str | None = None
    source_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)