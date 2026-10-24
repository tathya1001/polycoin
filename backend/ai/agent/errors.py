class AgentError(Exception):
    """A request or model reply the panel builder refuses. `code` is stable and machine-readable;
    `detail` is safe to show and to log: it never repeats what the user or the model wrote."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
