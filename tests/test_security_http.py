import io
from contextlib import redirect_stderr, redirect_stdout

import pytest
from starlette.testclient import TestClient

from core.server import app
from core.ingestion.file_analysis import FileAnalysisService


@pytest.mark.parametrize("filename", ["../../evil.log", "..\\..\\evil.log", "/absolute/path.log", "C:\\Windows\\evil.log"])
def test_upload_filename_is_not_used_as_a_filesystem_path(filename):
    client = TestClient(app)
    response = client.post("/analyze/file", files={"file": (filename, b"INFO safe message\n", "text/plain")})
    assert response.status_code in {200, 400, 415}
    assert not (response.status_code == 200 and "evil" in response.json().get("source", {}).get("filename", "") and ".." in response.json().get("source", {}).get("filename", ""))


def test_synthetic_secrets_do_not_appear_in_analysis_output(tmp_path):
    path = tmp_path / "secret.log"
    secret = "TEST_PASSWORD_123"
    path.write_text(f"INFO password={secret}\n", encoding="utf-8")
    service = FileAnalysisService(None, {"name": "Generic", "level_symbols": {}, "metrics": {}})
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = service.analyze(path)
    assert secret not in stdout.getvalue()
    assert secret not in stderr.getvalue()
    assert result["events"][0]["message"] == f"password={secret}"


def test_exception_response_does_not_include_uploaded_secret():
    client = TestClient(app)
    secret = "TEST_TOKEN_123"
    response = client.post("/analyze/file", files={"file": ("bad.csv", f"token={secret}".encode(), "text/plain")})
    assert response.status_code == 415
    assert secret not in response.text


def test_parser_exception_with_secret_does_not_reach_output(tmp_path):
    class FailingParser:
        def parse(self, _raw_lines):
            raise RuntimeError("parser failed for TEST_API_KEY_123")

    path = tmp_path / "failure.log"
    path.write_text("unstructured input\n", encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = FileAnalysisService(FailingParser(), {"name": "Generic", "level_symbols": {}, "metrics": {}}).analyze(path)
    assert "TEST_API_KEY_123" not in stdout.getvalue()
    assert "TEST_API_KEY_123" not in stderr.getvalue()
    assert "TEST_API_KEY_123" not in str(result)
