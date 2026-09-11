import tempfile
import unittest
from pathlib import Path

from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
from core.diagnostics import DiagnosticEngine
from core.models.metric import Metric

ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"])


class FindingsRecommendationsTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def analyze_fixture(self, name):
        return self.service.analyze(ROOT / "fixtures" / name)

    def test_memory_finding_visible_when_no_incidents(self):
        result = self.analyze_fixture("memory_degradation.log")
        self.assertTrue(len(result["findings"]) >= 1)
        # report should be empty (no correlated incidents) but findings present
        self.assertEqual(result.get("report"), [])

    def test_recommendations_vary_by_finding_type(self):
        engine = DiagnosticEngine()
        # unexpected reboot
        all_findings = []
        for value in (120, 121, 122, 0):
            all_findings.extend(engine.process({"id":"a","message":"m","level":"INFO","event_type":"log","timestamp":"12:00:00"}, [Metric("uptime", value, "seconds")]))
        reboot = [f for f in all_findings if getattr(f, "category", None) == "reboot"]
        self.assertTrue(reboot and "watchdog" in reboot[0].recommended_action.lower())

        # memory degradation
        engine = DiagnosticEngine()
        all_findings = []
        for value in (2000, 1900, 1800, 1700, 1600, 1500, 1400):
            all_findings.extend(engine.process({"id":"a","message":"m","level":"INFO","event_type":"log","timestamp":"12:00:00"}, [Metric("free_memory", value, "bytes")]))
        mem = [f for f in all_findings if getattr(f, "category", None) == "memory"]
        self.assertTrue(mem and "memory" in mem[0].recommended_action.lower())

        # connection instability
        engine = DiagnosticEngine()
        for _ in range(4):
            findings = engine.process({"id":"a","message":"Device disconnected - retrying...","level":"ERROR","event_type":"connection","timestamp":"12:00:00"})
        conn = engine.active_findings()
        conn = [f for f in conn if getattr(f, "category", None) == "connectivity"]
        self.assertTrue(conn and "connection" in conn[0].recommended_action.lower())

    def test_healthy_no_failure_recommendation(self):
        engine = DiagnosticEngine()
        findings = engine.process({"id":"a","message":"telemetry ok","level":"INFO","event_type":"log","timestamp":"12:00:00"})
        # no findings
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
