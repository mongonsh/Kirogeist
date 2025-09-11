import os, time
from openai import OpenAI

# Read API key from env
client = OpenAI()

# default model
DEFAULT_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

def chat(messages, model: str = None, temperature: float = 0.2, max_tokens: int = 2048) -> str:
    m = model or DEFAULT_MODEL
    resp = client.chat.completions.create(
        model=m,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()

def ai_health(model: str = None) -> dict:
    """Return {"ok", "model", "latency_ms", "error"}"""
    m = model or DEFAULT_MODEL
    t0 = time.time()
    try:
        client.chat.completions.create(
            model=m,
            messages=[{"role":"system","content":"healthcheck"},{"role":"user","content":"ping"}],
            temperature=0.0,
            max_tokens=1,
        )
        return {"ok": True, "model": m, "latency_ms": int((time.time()-t0)*1000), "error": None}
    except Exception as e:
        return {"ok": False, "model": m, "latency_ms": int((time.time()-t0)*1000), "error": f"{type(e).__name__}: {e}"}
