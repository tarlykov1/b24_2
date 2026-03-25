from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIG_ERROR = 10
    VALIDATION_ERROR = 11
    DATABASE_CONNECTION_ERROR = 20
    RUNTIME_FAILURE = 30
    UNKNOWN_COMMAND = 31
