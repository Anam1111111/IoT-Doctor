from .base import Parser, ParseResult
from .registry import register, get, available

# lazily import parsers
from .regex_parser import RegexParser
from .logcat_parser import LogcatParser

# register default parsers
register('regex', lambda: RegexParser(r"^(?P<level>\w+)\s+(?P<message>.*)$"))
register('logcat', lambda: LogcatParser())
register('jsonl', lambda: None)
