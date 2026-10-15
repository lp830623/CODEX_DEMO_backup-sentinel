"""Expected failures raised by the CLI and library."""


class BackupSentinelError(Exception):
    """Base class for errors the CLI reports without a traceback."""


class ConfigError(BackupSentinelError):
    """The configuration file or its environment is invalid."""


class UnrecognizedReportError(BackupSentinelError):
    """The text did not match a known backup report."""


class ParseError(BackupSentinelError):
    """A known report was missing fields required to build an event."""
