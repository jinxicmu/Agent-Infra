from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, http_code: int, code: str, message: str):
        super().__init__(
            status_code=http_code,
            detail={
                "type": "error",
                "error": {
                    "type": "bad_request_error" if http_code < 500 else "internal_error",
                    "message": message,
                    "http_code": str(http_code),
                    "code": code,
                },
            },
        )
