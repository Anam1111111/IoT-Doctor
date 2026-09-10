class Transport:
    """
    Generic transport boundary for raw device data.
    """

    def connect(self):
        raise NotImplementedError

    def receive(self):
        raise NotImplementedError

    def is_connected(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def metadata(self):
        raise NotImplementedError
