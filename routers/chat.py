from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ratelimit import allow
from db import get_db, ApiCall
from deps import get_current_user
from schemas import ChatIn, ChatOut
from llm_client import chat_completion,PRICE
from ratelimit import r
import hashlib, json
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["gateway"])

def _cache_key(prompt: str,model: str) -> str:
    raw = json.dumps({"prompt": prompt, "model": model}, ensure_ascii=False, sort_keys=True)
    return "cache:" + hashlib.sha256(raw.encode()).hexdigest()

@router.post("/chat", response_model=ChatOut)
def chat(
        body: ChatIn,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user),
):
    if body.model not in PRICE:
        raise HTTPException(422,"不支持你的模型")
    # 限流
    ok,used = allow(current_user.id,limit=10,window=60)
    if not ok:
        raise HTTPException(429,f"请求太频繁 (已用{used}次, 上限 10 次/分钟 )")
    ck = None
    if body.temperature == 0:
        ck = _cache_key(body.prompt,body.model)
        hit = r.get(ck)
        if hit:
            logger.info("cache hit key=%s user=%s", ck,current_user.id)
            data = json.loads(hit)
            return{"reply": data["reply"],
                   "model": body.model,
                   "prompt_tokens": 0,
                   "completion_tokens": 0,
                   "cost": Decimal("0"),
                   "cached": True}
    try:
        result = chat_completion(body.prompt,body.model,body.temperature)
    except Exception:
        logger.exception("LLM 调用失败 user_id=%s model=%s",
                          current_user.id,body.model)
        u = ApiCall(user_id = current_user.id,
                    model = body.model,
                    status = "failed"
                    )
        db.add(u)
        db.commit()
        raise HTTPException(502,"上游服务暂不可用")
    u = ApiCall(user_id = current_user.id,
                model = result["model"],
                prompt_tokens = result["prompt_tokens"],
                completion_tokens = result["completion_tokens"],
                cost = result["cost"],
                )
    db.add(u)
    db.commit()
    db.refresh(u)
    if ck is not None:
        r.set(ck, json.dumps({"reply": result["reply"]}, ensure_ascii=False), ex=3600)
    return {"reply": result["reply"],
            "model": u.model,
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens, 
            "cost": u.cost,
            "cached": False}
    
    