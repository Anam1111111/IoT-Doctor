import re
from core.parser.base import Parser

class RegexParser(Parser):
    def __init__(self, pattern):
        self.pattern = pattern

    def parse(self, raw_data):
        match = re.match(self.pattern, raw_data)
        if not match:
            return None

        if match.groupdict():
            return {
                key: value
                for key, value in match.groupdict().items()
                if value is not None
            }

        field_names = ("level", "message", "count")
        return {
            name: value
            for name, value in zip(field_names, match.groups())
            if value is not None
        }
