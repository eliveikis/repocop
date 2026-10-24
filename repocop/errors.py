"""Domain errors: expected failures that carry a message a person can act on."""


class RepoCopError(Exception):
    """Base class for expected failures, each with a readable message."""


class ConfigError(RepoCopError):
    """Host configuration is missing, malformed, or unsafe."""


class DatabaseError(RepoCopError):
    """RepoCop's database can't be opened or has an unsupported schema version."""
