from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str
    request_id: str


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail


async def problem_response(request: Request, exc: ApiError) -> JSONResponse:
    value = Problem(
        type=f"urn:zoclip:problem:{exc.code}",
        title=exc.code.replace("_", " "),
        status=exc.status,
        code=exc.code,
        detail=exc.detail,
        instance=request.url.path,
        request_id=request.state.request_id,
    )
    headers = {"Retry-After": "60"} if exc.status == 429 else {}
    return JSONResponse(
        value.model_dump(),
        status_code=exc.status,
        media_type="application/problem+json",
        headers=headers,
    )
