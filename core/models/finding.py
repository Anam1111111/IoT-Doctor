from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class Finding:
    severity: str
    title: str
    category: str
    description: str
    evidence: str
    confidence: float
    recommended_action: str
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S")
    )
    status: str = "ACTIVE"
    created_at: str | None = None
    resolved_at: str | None = None
    resolution_reason: str | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = self.timestamp

    def to_dict(self):
        return asdict(self)