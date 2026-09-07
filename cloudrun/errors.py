class ApiError(Exception):
    def __init__(self, status, code, message=None):
        self.status, self.code = status, code
        self.message = message or code.replace('_', ' ').capitalize()
        super().__init__(self.message)
