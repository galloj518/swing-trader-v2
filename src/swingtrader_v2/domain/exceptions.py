"""Domain and configuration exceptions."""


class SwingTraderError(Exception):
    """Base exception for repository-owned errors."""


class ConfigError(SwingTraderError):
    """Base configuration error."""


class ConfigLoadError(ConfigError):
    """Raised when configuration cannot be loaded."""


class ConfigValidationError(ConfigError):
    """Raised when configuration violates structural or architectural rules."""


class SchemaContractError(SwingTraderError):
    """Raised when a machine-readable contract is invalid."""


class DeterministicIdError(SwingTraderError):
    """Raised when deterministic IDs cannot be constructed safely."""
