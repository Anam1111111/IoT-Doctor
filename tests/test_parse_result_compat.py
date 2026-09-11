from core.parser.base import ParseResult
from core.parser.regex_parser import RegexParser
from core.parser.logcat_parser import LogcatParser
from core.normalization.normalizer import EventNormalizer


def test_regex_parseresult_compat_with_normalizer():
    parser = RegexParser(r"^(?P<level>INFO|WARN|ERROR) (?P<message>.+)$")
    pr = parser.parse(["WARN Low battery"])  # ParseResult
    assert isinstance(pr, ParseResult)
    normalizer = EventNormalizer()
    evt = normalizer.normalize(pr, raw="WARN Low battery", transport_metadata={})
    assert evt["level"] == "WARN"
    assert "Low battery" in evt["message"]


def test_regex_legacy_dict_still_works():
    parser = RegexParser(r"^(?P<level>INFO|WARN|ERROR) (?P<message>.+)$")
    d = parser.parse("ERROR Crash")  # legacy dict
    assert isinstance(d, dict)
    normalizer = EventNormalizer()
    evt = normalizer.normalize(d, raw="ERROR Crash", transport_metadata={"transport": "file"})
    assert evt["level"] == "ERROR"
    assert evt["raw_line"] == "ERROR Crash"


def test_logcat_parseresult_fields_preserved():
    lp = LogcatParser()
    line = "09-11 12:00:00.123 1234 5678 I Tag: Hello world"
    pr = lp.parse([line])
    assert isinstance(pr, ParseResult)
    normalizer = EventNormalizer()
    evt = normalizer.normalize(pr, raw=line, transport_metadata={"transport": "file"})
    assert evt.get("parse_format") == "logcat"
    assert evt.get("parse_confidence") is not None
    assert evt.get("raw_line") == line