import re
from core.parser.base import Parser

class RegexParser(Parser):
    def __init__(self, pattern):
        self.pattern = pattern

    def parse(self, line):
        match = re.match(self.pattern, line)
        if not match:
            return None
        return match.group(1), match.group(2), match.group(3)
