"""The root of every error the SDK raises (`aip.AipError`), in a module of its own so the client's
HTTP layer and the SDK can both build on it without importing each other."""


class AipError(Exception):
    """An AIP operation that could not be done. `kind` names what went wrong, in the same
    vocabulary as the CLI's error objects and the server's error envelope."""

    kind = "error"

    def __init__(self, message: str, kind: str | None = None):
        super().__init__(message)
        self.message = message
        if kind is not None:
            self.kind = kind


__all__ = ["AipError"]
