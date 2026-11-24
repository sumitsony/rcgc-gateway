# main.py
import os
import time
import hashlib
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Dict, Optional

import guardrails
import providers

# ADR-001: In-Memory Stores for v0.1
CACHE: Dict[str, dict] = {}
CACHE_TTL_SECONDS = 3600

KEYS: Dict[str, dict] = {
    "test-key-123": {"team": "dev-team", "tokens_used": 0}
}

# ADR-004: Shadow Cost pricing (equivalent USD per 1M tokens)
PRICING = {
    "groq": {"input": 0.50, "output": 0.50},
    "gemini": {"input": 0.35, "output": 1.05},
    "ollama": {"input": 0.0, "output": 0.0}
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    guardrails.warm_up()
    yield

app = FastAPI(title="RCGC Gateway v0.1", lifespan=lifespan)

# --- Pydantic Models ---
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = "default"
    messages: List[Message]
    temperature: Optional[float] = 0.7

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest, 
    authorization: Optional[str] = Header(None),
    x_force_provider: Optional[str] = Header(None)  # ADR-008: Testing-only
):
    # 1. Auth
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    key = authorization.split(" ")[1]
    if key not in KEYS:
        raise HTTPException(status_code=401, detail="Invalid virtual key")

    # 2. Input Guardrails
    sanitized_messages = []
    for msg in request.messages:
        clean_content = guardrails.mask_pii(msg.content)
        sanitized_messages.append(Message(role=msg.role, content=clean_content))
    
    payload = {
        "model": request.model,
        "messages": [m.model_dump() for m in sanitized_messages],
        "temperature": request.temperature
    }

    # 3. Cache Check
    cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    
    if cache_key in CACHE:
        cached_entry = CACHE[cache_key]
        if cached_entry["expires_at"] > time.time():
            print("--- CACHE HIT ---")
            return cached_entry["response"]
        else:
            del CACHE[cache_key]

    print("--- CACHE MISS ---")

    # 4. Routing & Fallback
    response = None
    provider_used = None

    # ADR-008: Gated testing override
    force_provider = None
    if os.getenv("ALLOW_FORCE_PROVIDER", "false").lower() == "true":
        force_provider = x_force_provider

    try:
        if force_provider == "gemini":
            response = await providers.call_gemini(payload)
            provider_used = "gemini"
        elif force_provider == "ollama":
            response = await providers.call_ollama(payload)
            provider_used = "ollama"
        else:
            # Default path: Groq first
            response = await providers.call_groq(payload)
            provider_used = "groq"
    except Exception as e:
        print(f"Primary provider failed: {e}. Falling back...")
        # Fallback chain (only applies if not forced, or if forced provider failed)
        if force_provider != "gemini":
            try:
                response = await providers.call_gemini(payload)
                provider_used = "gemini"
            except Exception as e2:
                print(f"Gemini failed: {e2}. Falling back to Ollama.")
                try:
                    response = await providers.call_ollama(payload)
                    provider_used = "ollama"
                except Exception as e3:
                    raise HTTPException(status_code=502, detail="All providers failed")
        else:
             # If Gemini was forced and failed, try Ollama as last resort
             try:
                response = await providers.call_ollama(payload)
                provider_used = "ollama"
             except Exception:
                raise HTTPException(status_code=502, detail="Forced Gemini and fallback Ollama failed")

    # 5. Cost Tracking
    usage = response.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    
    pricing = PRICING.get(provider_used, {"input": 0, "output": 0})
    cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000
    
    KEYS[key]["tokens_used"] += (prompt_tokens + completion_tokens)

    # 6. Store in Cache
    CACHE[cache_key] = {
        "response": response,
        "expires_at": time.time() + CACHE_TTL_SECONDS
    }

    return response

@app.get("/usage")
def get_usage(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    key = authorization.split(" ")[1]
    if key not in KEYS:
        raise HTTPException(status_code=401, detail="Invalid virtual key")
    
    return {
        "team": KEYS[key]["team"],
        "tokens_used": KEYS[key]["tokens_used"]
    }