# main.py
import os
import time
import hashlib
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Dict, Optional

import guardrails
import providers

# ADR-001: In-Memory Stores for v0.1
CACHE: Dict[str, dict] = {}
CACHE_TTL_SECONDS = 3600

# ADR-011: Cost & Token Observability
KEYS: Dict[str, dict] = {
    "test-key-123": {"team": "dev-team", "tokens_used": 0, "cost_usd": 0.0}
}

# ADR-013: In-Memory Audit Log (capped at 100 entries)
AUDIT_LOG: List[dict] = []
MAX_LOG_ENTRIES = 100

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

# --- Helper: Log Audit Entry ---
def add_audit_log(entry: dict):
    """Appends to the audit log, keeping only the last MAX_LOG_ENTRIES."""
    AUDIT_LOG.append(entry)
    if len(AUDIT_LOG) > MAX_LOG_ENTRIES:
        AUDIT_LOG.pop(0)

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest, 
    authorization: Optional[str] = Header(None),
    x_force_provider: Optional[str] = Header(None)
):
    # 1. Auth
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    key = authorization.split(" ")[1]
    if key not in KEYS:
        raise HTTPException(status_code=401, detail="Invalid virtual key")

    # 2. Input Guardrails & PII Detection
    sanitized_messages = []
    pii_masked = False
    for msg in request.messages:
        clean_content = guardrails.mask_pii(msg.content)
        if clean_content != msg.content:
            pii_masked = True
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
            response = cached_entry["response"]
            
            # Extract tokens from cached response
            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = prompt_tokens + completion_tokens
            
            # Log cache hit (0 cost, but tokens still counted for user consumption)
            add_audit_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "key": key,
                "provider_used": "cache",
                "cache_hit": True,
                "pii_masked": pii_masked,
                "tokens": {"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
                "cost_usd": 0.0,
                "status": "success"
            })
            return response
        else:
            del CACHE[cache_key]

    print("--- CACHE MISS ---")

    # 4. Routing & Fallback
    response = None
    provider_used = None

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
            response = await providers.call_groq(payload)
            provider_used = "groq"
    except Exception as e:
        print(f"Primary provider failed: {e}. Falling back...")
        
        # Log failure of primary provider
        add_audit_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "key": key,
            "provider_used": force_provider or "groq",
            "cache_hit": False,
            "pii_masked": pii_masked,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "cost_usd": 0.0,
            "status": f"failed: {str(e)[:50]}" # Truncate error for UI
        })

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
                    add_audit_log({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "key": key, "provider_used": "all", "cache_hit": False,
                        "pii_masked": pii_masked, "tokens": {"prompt": 0, "completion": 0, "total": 0},
                        "cost_usd": 0.0, "status": "failed: all providers down"
                    })
                    raise HTTPException(status_code=502, detail="All providers failed")
        else:
             try:
                response = await providers.call_ollama(payload)
                provider_used = "ollama"
             except Exception as e3:
                add_audit_log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "key": key, "provider_used": "gemini/ollama", "cache_hit": False,
                    "pii_masked": pii_masked, "tokens": {"prompt": 0, "completion": 0, "total": 0},
                    "cost_usd": 0.0, "status": "failed: forced fallback down"
                })
                raise HTTPException(status_code=502, detail="Forced provider and fallback failed")

    # 5. Cost & Token Tracking (ADR-011)
    usage = response.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = prompt_tokens + completion_tokens
    
    pricing = PRICING.get(provider_used, {"input": 0, "output": 0})
    cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000
    
    # Update Global Key Usage
    KEYS[key]["tokens_used"] += total_tokens
    KEYS[key]["cost_usd"] += cost

    # Add to Audit Log
    add_audit_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "key": key,
        "provider_used": provider_used,
        "cache_hit": False,
        "pii_masked": pii_masked,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
        "cost_usd": cost,
        "status": "success"
    })

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
        "tokens_used": KEYS[key]["tokens_used"],
        "cost_usd": round(KEYS[key]["cost_usd"], 6)
    }

# --- Admin Endpoints for UI (v0.1.2) ---

@app.get("/admin/stats")
def get_admin_stats():
    """Aggregates token and cost flow for the dashboard."""
    total_tokens = 0
    total_cost = 0.0
    provider_split = {
        "groq": {"tokens": 0, "cost": 0.0},
        "gemini": {"tokens": 0, "cost": 0.0},
        "ollama": {"tokens": 0, "cost": 0.0},
        "cache": {"tokens": 0, "cost": 0.0}
    }

    for entry in AUDIT_LOG:
        if entry["status"] == "success":
            p = entry["provider_used"]
            t = entry["tokens"]["total"]
            c = entry["cost_usd"]
            
            total_tokens += t
            total_cost += c
            
            if p in provider_split:
                provider_split[p]["tokens"] += t
                provider_split[p]["cost"] += c

    return {
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "provider_split": provider_split
    }

@app.get("/admin/logs")
def get_admin_logs():
    """Returns the audit log, most recent first."""
    return list(reversed(AUDIT_LOG))