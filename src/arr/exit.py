from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    NO_RESULTS = 3
    DEPENDENCY_UNAVAILABLE = 4
