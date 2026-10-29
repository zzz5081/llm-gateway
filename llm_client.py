import os
from decimal import Decimal

LLM_MODE = os.environ.get("LLM_MODE","mock")

PRICE = {
    "gpt-4o-mini": {
        "prompt": Decimal("0.15"),
        "completion": Decimal("0.60"),
    },
}
DEFAULT_MODEL = "gpt-4o-mini"

def calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    p = PRICE[model]
    return (
        prompt_tokens * p["prompt"]
        + completion_tokens * p["completion"]
    ) / Decimal("1000000")

def chat_completion(prompt: str,model: str = DEFAULT_MODEL,
                    temperature: float = 0.0) -> dict:
    if LLM_MODE == "mock":
        result = _mock_call(prompt)
    else:
        result = _real_call(prompt, model, temperature)

    result["model"] = model
    result["cost"] = calc_cost(model,
                               result["prompt_tokens"],
                               result["completion_tokens"])
    return result

def _mock_call(prompt: str) -> dict:
    return {
        "reply": f"[mock] 你说的是: {prompt}",
        "prompt_tokens": len(prompt),
        "completion_tokens": 20,
    }

def _real_call(prompt: str, model: str, temperature: float) -> dict:
    raise NotImplementedError("真调用留到W9")