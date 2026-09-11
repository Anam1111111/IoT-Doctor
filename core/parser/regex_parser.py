import re
from core.parser.base import Parser, ParseResult


class RegexParser(Parser):
    def __init__(self, pattern):
        self.pattern = pattern

    def parse(self, raw_lines):
        # Backwards-compat: if called with a single string, return legacy dict
        if isinstance(raw_lines, str):
            line = raw_lines
            called_with_str = True
        else:
            line = raw_lines[0] if isinstance(raw_lines, list) else raw_lines
            called_with_str = False
        match = re.match(self.pattern, line)
        if not match:
            return None

        if match.groupdict():
            fields = {key: value for key, value in match.groupdict().items() if value is not None}
        else:
            field_names = ("level", "message", "count")
            fields = {name: value for name, value in zip(field_names, match.groups()) if value is not None}

        result = ParseResult(fields=fields, raw_lines=[line], format="regex", confidence=0.9, is_multiline=False)
        return fields if called_with_str else result
