import unittest
from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
from pathlib import Path

ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"]) 

class RecommendationMappingTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def test_memory_finding_recommendation_used_for_ui(self):
        result = self.service.analyze(ROOT / 'fixtures' / 'memory_degradation.log')
        # report is empty (no correlated incidents) but findings include memory finding
        self.assertEqual(result.get('report'), [])
        findings = result.get('findings') or []
        self.assertTrue(findings)
        finding_rec = findings[0].get('recommended_action')
        self.assertTrue(finding_rec and 'memory' in finding_rec.lower())
        # Simulate UI selection logic: prefer report[0].recommended_action, then findings[0]
        def ui_pick(rec_result):
            if rec_result.get('report') and len(rec_result.get('report')) and rec_result['report'][0].get('recommended_action'):
                return rec_result['report'][0]['recommended_action']
            if rec_result.get('findings') and len(rec_result.get('findings')) and rec_result['findings'][0].get('recommended_action'):
                return rec_result['findings'][0]['recommended_action']
            if rec_result.get('recommended_action'):
                return rec_result['recommended_action']
            return None
        picked = ui_pick(result)
        self.assertEqual(picked, finding_rec)

if __name__ == '__main__':
    unittest.main()
