"""Public engine error contract; messages contain no input or credential values."""
class Invalid(ValueError):
    """Source, data, review or admission failed validation."""

class NotFound(LookupError):
    """No such resource within the supplied actor scope."""
