import unittest
import tempfile
from pathlib import Path

from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser

ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"])


class MalformedTimestampTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def test_invalid_timestamp_not_accepted_but_line_preserved(self):
        content = (
            "2026-09-10 12:00:00 [INFO] Good line\n"
            "2026-99-99 25:61:61 [WARN] Bad timestamp line\n"
            "[INFO] Another good line\n"
        )
        with tempfile.NamedTemporaryFile(suffix='.log', mode='w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            result = self.service.analyze(f.name)
        # First valid event has timestamp
        evs = result['events']
        self.assertTrue(any(e.get('timestamp') == '2026-09-10 12:00:00' for e in evs))
        # Malformed timestamp should NOT be present as a timestamp value
        self.assertFalse(any(e.get('timestamp') == '2026-99-99 25:61:61' for e in evs))
        # But the raw line must be preserved in raw_lines
        self.assertTrue(any('Bad timestamp line' in (l or '') for l in result['raw_lines']))
        # Other valid events still analyzed
        self.assertTrue(any(((e.get('message') or '').lower().find('good line')>=0) for e in evs))


if __name__ == '__main__':
    unittest.main()
