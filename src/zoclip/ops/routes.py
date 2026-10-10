from datetime import datetime

from fastapi import APIRouter, Request

from zoclip.auth.dependencies import DB, AdminUser
from zoclip.core.errors import ApiError
from zoclip.credits.service import audit
from zoclip.ops.report import report
from zoclip.ops.schemas import OperationReport

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/operations", response_model=OperationReport)
def operations(
    request: Request, db: DB, user: AdminUser, start: datetime, end: datetime
) -> OperationReport:
    try:
        result = report(db, start, end, request.app.state.settings.media_root)
    except ValueError as exc:
        raise ApiError(
            422, "invalid_report", "Use a valid UTC monthly period/reporting policy."
        ) from exc
    audit(db, user.id, "operations.report_read", user.id)
    db.commit()
    return OperationReport.model_validate(result)
