import unittest
import tempfile
from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
from pathlib import Path

ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"])

class TimeoutLabelingTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def test_sensor_timeout_recovery_labels_sensor(self):
        content = (
            "[ERROR] Sensor response timeout\n"
            "[INFO] command acknowledgement received\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        # report should include an incident with sensor in the title
        reports = result.get('report') or []
        titles = [r.get('title','').lower() for r in reports]
        self.assertTrue(any('sensor' in t for t in titles), f"titles={titles}")

    def test_command_ack_timeout_recovery_labels_command(self):
        content = (
            "[ERROR] command acknowledgement timeout\n"
            "[INFO] command acknowledgement received\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        reports = result.get('report') or []
        titles = [r.get('title','').lower() for r in reports]
        self.assertTrue(any('command' in t for t in titles), f"titles={titles}")

    def test_both_timeouts_identified_correctly(self):
        content = (
            "[ERROR] Sensor response timeout\n"
            "[INFO] sensor acknowledged\n"
            "[ERROR] command acknowledgement timeout\n"
            "[INFO] command acknowledgement received\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        reports = result.get('report') or []
        titles = [r.get('title','').lower() for r in reports]
        self.assertTrue(any('sensor' in t for t in titles), f"titles={titles}")
        self.assertTrue(any('command' in t for t in titles), f"titles={titles}")

if __name__ == '__main__':
    unittest.main()
