from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db, ApiCall
from deps import get_current_user
from schemas import ChatIn, ChatOut
from llm_client import chat_completion,PRICE

router = APIRouter(prefix="/v1", tags=["gateway"])

@router.post("/chat", response_model=ChatOut)
def chat(
        body: ChatIn,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user),
):
    if body.model not in PRICE:
        raise HTTPException(422,"不支持你的模型")
    try:
        result = chat_completion(body.prompt,body.model,body.temperature)
    except Exception:
        u = ApiCall(user_id = current_user.id,
                    model = body.model,
                    status = "failed"
                    )
        db.add(u)
        db.commit()
        raise HTTPException(502,"出错了")
    u = ApiCall(user_id = current_user.id,
                model = result["model"],
                prompt_tokens = result["prompt_tokens"],
                completion_tokens = result["completion_tokens"],
                cost = result["cost"],
                )
    db.add(u)
    db.commit()
    return {"reply": result["reply"],
            "model": result["model"],
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"], 
            "cost": result["cost"],}
    
    