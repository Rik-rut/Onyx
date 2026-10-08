class TransmissionError(Exception):
    hint: str = ""


class DependencyUnavailable(TransmissionError):
    def __init__(self, msg: str = "transmission-daemon/transmission-remote not found"):
        super().__init__(msg)
        self.hint = (
            "Install Transmission (https://transmissionbt.com) so `transmission-daemon` "
            "and `transmission-remote` are on PATH, or set transmission_remote in config."
        )


class RpcError(TransmissionError):
    pass


class AuthError(RpcError):
    def __init__(self, msg: str = "RPC authentication failed"):
        super().__init__(msg)
        self.hint = "Check transmission_rpc_user/transmission_rpc_pass in config.toml."


class PortInUseError(TransmissionError):
    def __init__(self, port: int):
        super().__init__(f"Port {port} already in use")
        self.hint = (
            f"Another service is listening on {port}. Stop it or change "
            "transmission_rpc_port in config.toml."
        )


class StaleLockError(TransmissionError):
    def __init__(self, msg: str = "Stale transmission-daemon lock file detected"):
        super().__init__(msg)
        self.hint = (
            "Delete the stale `transmission-daemon` lock file (in the config dir) and retry."
        )
