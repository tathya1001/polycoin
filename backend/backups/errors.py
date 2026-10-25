class BackupError(Exception):
    """A backup file the server refuses to make or read. `code` is stable and machine-readable;
    `detail` is safe to show and to log: it never contains the user's data."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
