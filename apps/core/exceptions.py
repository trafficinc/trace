class EditConflict(Exception):
    """The submitted version no longer matches saved state in an authorized scope."""

    def __init__(self, message='This record changed.', *, current=None):
        super().__init__(message)
        self.current = current
