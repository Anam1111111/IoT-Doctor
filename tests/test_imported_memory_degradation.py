from core.config.profile_loader import ProfileLoader
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def _analyze(tmp_path, values):
    log_path = tmp_path / "memory.log"
    log_path.write_text(
        "\n".join(f"[INFO] FreeRAM={value}b, count={index}" for index, value in enumerate(values)),
        encoding="utf-8",
    )
    profile = ProfileLoader(".").load()
    service = FileAnalysisService(RegexParser(profile["log_pattern"]), profile)
    return service.analyze(log_path)


def test_imported_seven_sample_memory_trend_produces_warning(tmp_path):
    result = _analyze(tmp_path, (1820, 1788, 1770, 1752, 1730, 1712, 1690))

    findings = [f for f in result["findings"] if f.get("category") == "memory"]
    assert len(findings) == 1
    assert "Free memory decreased" in findings[0]["evidence"]
    assert result["health"]["status"] == "WARNING"


def test_imported_ten_sample_memory_trend_produces_warning_finding(tmp_path):
    result = _analyze(
        tmp_path,
        (1820, 1788, 1770, 1752, 1730, 1712, 1690, 1672, 1650, 1632),
    )

    findings = [finding for finding in result["findings"] if finding["category"] == "memory"]
    assert len(findings) == 1
    assert "Free memory decreased" in findings[0]["evidence"]
    assert result["health"]["status"] == "WARNING"