import os


class FileReaderError(Exception):
    pass


class FileReader:
    """Read bounded UTF-8 LOG/TXT input without loading it all at once."""

    SUPPORTED_EXTENSIONS = {".log", ".txt"}

    def __init__(self, path, max_bytes=5 * 1024 * 1024):
        self.path = os.fspath(path)
        self.max_bytes = max_bytes

    def lines(self):
        extension = os.path.splitext(self.path)[1].lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise FileReaderError("Only .log and .txt files are supported")
        if not os.path.isfile(self.path):
            raise FileReaderError("Input file does not exist")
        if os.path.getsize(self.path) > self.max_bytes:
            raise FileReaderError("Input file exceeds the maximum allowed size")
        try:
            with open(self.path, "r", encoding="utf-8", errors="strict") as file:
                yield from file
        except UnicodeDecodeError as error:
            raise FileReaderError("Input file is not valid UTF-8") from error