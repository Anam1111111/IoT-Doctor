class Parser:
    """
    Any parser (regex, JSON, etc.) must implement parse(),
    which takes a raw line and returns (level, message, count)
    or None if it doesn't match.
    """

    def parse(self, line):
        raise NotImplementedError
