from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from db import get_db
from deps import get_current_user
from schemas import UsageOut

router = APIRouter(prefix="/v1",tags=["gateway"])

@router.get("/usage",response_model=UsageOut)
def usage(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    rows = db.execute(text("""
SELECT
    COUNT(CASE WHEN created_at >= CURDATE() AND status='success' THEN 1 END) AS today_success,
    COUNT(CASE WHEN created_at >= CURDATE() AND status='failed' THEN 1 END) AS today_failed,
    COUNT(CASE WHEN created_at >= DATE_FORMAT(CURDATE(),'%Y-%m-01') AND status = 'success' THEN 1 END) AS month_success,
    COUNT(CASE WHEN created_at >= DATE_FORMAT(CURDATE(),'%Y-%m-01') AND status = 'failed' THEN 1 END) AS month_failed,
    COALESCE(SUM(prompt_tokens),0) AS total_prompt_tokens,
    COALESCE(SUM(completion_tokens),0) AS total_completion_tokens,
    COALESCE(SUM(cost),0) AS total_cost
FROM api_calls
WHERE user_id = :uid
"""),{"uid":current_user.id}).mappings().one()
    return dict(rows)