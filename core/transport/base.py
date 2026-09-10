class Transport:
    """
    Any transport (Serial, MQTT, TCP, etc.) must implement these
    three methods. The core engine only ever calls these — it
    never needs to know what kind of transport it's talking to.
    """

    def connect(self):
        raise NotImplementedError

    def read_line(self):
        raise NotImplementedError

    def is_connected(self):
        raise NotImplementedError
