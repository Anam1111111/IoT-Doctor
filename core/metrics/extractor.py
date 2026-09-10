import re

from core.models.metric import Metric


class MetricExtractor:
    """Extract configured metrics from normalized events."""

    def __init__(self, definitions=None):
        self.definitions = definitions or {}

    def extract(self, event):
        metrics = []
        for name, definition in self.definitions.items():
            if definition.get("source", "message") != "message":
                continue
            match = re.search(definition["pattern"], event.get("message", ""))
            if not match:
                continue
            value = match.groupdict().get("value")
            if value is None and match.groups():
                value = match.group(1)
            if value is None:
                continue
            metrics.append(
                Metric(
                    name=name,
                    value=self._coerce(value),
                    unit=definition.get("unit"),
                    timestamp=event.get("timestamp"),
                    device_id=event.get("device_id"),
                    source_event_id=event.get("id"),
                    metadata={
                        key: value
                        for key, value in definition.items()
                        if key not in {"source", "pattern", "unit"}
                    },
                )
            )
        return metrics

    @staticmethod
    def _coerce(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        return int(number) if number.is_integer() else number