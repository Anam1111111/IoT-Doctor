import unittest
import tempfile
from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
from pathlib import Path

ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"]) 

class TimeoutRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def test_sensor_timeout_recommendation(self):
        content = (
            "[ERROR] Sensor response timeout\n"
            "[INFO] sensor acknowledged\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        reports = result.get('report') or []
        recs = [r.get('recommended_action','').lower() for r in reports]
        self.assertTrue(any('sensor' in r for r in recs), f"recs={recs}")

    def test_command_ack_timeout_recommendation(self):
        content = (
            "[ERROR] command acknowledgement timeout\n"
            "[INFO] command acknowledgement received\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        reports = result.get('report') or []
        recs = [r.get('recommended_action','').lower() for r in reports]
        self.assertTrue(any('acknowled' in r for r in recs), f"recs={recs}")

if __name__ == '__main__':
    unittest.main()
