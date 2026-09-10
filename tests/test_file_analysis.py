import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
from core.server import analyze_file


ROOT = Path(__file__).parent
PROFILE = ProfileLoader(".").load()
PARSER = RegexParser(PROFILE["log_pattern"])


class FakeUpload:
    def __init__(self, filename, content):
        self.filename = filename
        self.content = content
        self.position = 0
        self.closed = False

    async def read(self, size):
        if self.position >= len(self.content):
            return b""
        chunk = self.content[self.position : self.position + size]
        self.position += size
        return chunk

    async def close(self):
        self.closed = True


class FileAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.service = FileAnalysisService(PARSER, PROFILE)

    def analyze_fixture(self, name):
        return self.service.analyze(ROOT / "fixtures" / name)

    def test_valid_log_file_parses_events(self):
        result = self.analyze_fixture("healthy.log")
        self.assertEqual(result["source"]["type"], "file")
        self.assertEqual(result["statistics"]["events_parsed"], 3)
        self.assertEqual(result["statistics"]["unrecognized_lines"], 0)

    def test_valid_txt_file_parses_events(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8") as file:
            file.write("[INFO] Uptime=48s, FreeRAM=1778b, count=48\n")
            file.flush()
            result = self.service.analyze(file.name)
        self.assertEqual(result["statistics"]["events_parsed"], 1)

    def test_empty_file_returns_clear_empty_result(self):
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", encoding="utf-8") as file:
            result = self.service.analyze(file.name)
        self.assertEqual(result["statistics"], {
            "lines_total": 0,
            "events_parsed": 0,
            "unrecognized_lines": 0,
        })

    def test_unsupported_extension_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", encoding="utf-8") as file:
            with self.assertRaisesRegex(Exception, "Only .log and .txt"):
                self.service.analyze(file.name)

    def test_invalid_utf8_is_reported(self):
        with tempfile.NamedTemporaryFile(suffix=".log") as file:
            file.write(b"[INFO] valid\xff\n")
            file.flush()
            with self.assertRaisesRegex(Exception, "not valid UTF-8"):
                self.service.analyze(file.name)

    def test_partially_malformed_file_keeps_valid_events(self):
        result = self.analyze_fixture("malformed.log")
        self.assertEqual(result["statistics"]["lines_total"], 4)
        self.assertEqual(result["statistics"]["events_parsed"], 2)
        self.assertEqual(result["statistics"]["unrecognized_lines"], 2)

    def test_imported_metrics_reach_diagnostics(self):
        result = self.analyze_fixture("memory_degradation.log")
        self.assertEqual(len(result["metrics"]), 20)
        self.assertTrue(any(f["category"] == "memory" for f in result["findings"]))
        self.assertEqual(result["health"]["status"], "WARNING")

    def test_imported_reboot_is_detected(self):
        result = self.analyze_fixture("reboot.log")
        reboot_findings = [f for f in result["findings"] if f["category"] == "reboot"]
        self.assertEqual(len(reboot_findings), 1)
        self.assertIn("reset from 41 seconds to 0 seconds", reboot_findings[0]["evidence"])

    def test_imported_error_spike_is_detected(self):
        content = "".join(f"[ERROR] timeout, count={index}\n" for index in range(5))
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            result = self.service.analyze(file.name)
        self.assertTrue(any(f["category"] == "errors" for f in result["findings"]))

    def test_imported_connection_instability_is_detected(self):
        content = "".join(
            f"[ERROR] Device disconnected - retrying..., count={index}\n"
            for index in range(3)
        )
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            result = self.service.analyze(file.name)
        self.assertTrue(any(f["category"] == "connectivity" for f in result["findings"]))

    def test_file_order_is_preserved(self):
        result = self.analyze_fixture("healthy.log")
        self.assertEqual(
            [event["count"] for event in result["events"]],
            ["40", "41", "42"],
        )

    def test_file_analysis_does_not_replace_live_session_globals(self):
        from core import server
        original_session = server.session
        result = self.analyze_fixture("healthy.log")
        self.assertIs(server.session, original_session)
        self.assertEqual(result["source"]["type"], "file")

    def test_upload_endpoint_returns_structured_result(self):
        upload = FakeUpload(
            "sample.log",
            b"[INFO] Uptime=48s, FreeRAM=1778b, count=48\n",
        )
        result = asyncio.run(analyze_file(upload))
        self.assertEqual(result["source"]["filename"], "sample.log")
        self.assertEqual(result["statistics"]["events_parsed"], 1)
        self.assertTrue(upload.closed)

    def test_upload_endpoint_rejects_unsupported_extension(self):
        upload = FakeUpload("sample.csv", b"not csv support")
        with self.assertRaises(HTTPException) as error:
            asyncio.run(analyze_file(upload))
        self.assertEqual(error.exception.status_code, 415)
        self.assertTrue(upload.closed)


if __name__ == "__main__":
    unittest.main()
