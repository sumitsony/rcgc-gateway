# main.py
import os
import time
import hashlib
import json
import pathlib
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
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

app = FastAPI(title="Elint AI Services | RCGC Gateway v0.1", lifespan=lifespan)

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
            
            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = prompt_tokens + completion_tokens
            
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
        
        add_audit_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "key": key,
            "provider_used": force_provider or "groq",
            "cache_hit": False,
            "pii_masked": pii_masked,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "cost_usd": 0.0,
            "status": f"failed: {str(e)[:50]}"
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
    
    KEYS[key]["tokens_used"] += total_tokens
    KEYS[key]["cost_usd"] += cost

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

# --- Admin Endpoints (JSON) ---

@app.get("/admin/stats")
def get_admin_stats():
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
    return list(reversed(AUDIT_LOG))


# --- UI Endpoints for HTMX (v0.1.2) ---

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Serves the static HTMX dashboard UI."""
    html_path = pathlib.Path(__file__).parent / "templates" / "dashboard.html"
    return html_path.read_text(encoding="utf-8")

@app.get("/admin/ui/tokens", response_class=HTMLResponse)
def get_ui_tokens():
    total_tokens = sum(e["tokens"]["total"] for e in AUDIT_LOG if e["status"] == "success")
    total_cost = sum(e["cost_usd"] for e in AUDIT_LOG if e["status"] == "success")
    return f"""
    <div class="space-y-4">
        <div>
            <div class="text-sm text-gray-400">Total Tokens Processed</div>
            <div class="text-3xl font-mono text-white">{total_tokens:,}</div>
        </div>
        <div>
            <div class="text-sm text-gray-400">Shadow Cost (USD)</div>
            <div class="text-xl font-mono text-emerald-400">${total_cost:.6f}</div>
        </div>
    </div>
    """

@app.get("/admin/ui/providers", response_class=HTMLResponse)
def get_ui_providers():
    provider_split = {}
    total_tokens = 0
    for e in AUDIT_LOG:
        if e["status"] == "success":
            p = e["provider_used"]
            t = e["tokens"]["total"]
            provider_split[p] = provider_split.get(p, 0) + t
            total_tokens += t
    
    if total_tokens == 0:
        return "<div class='text-sm text-gray-500'>No traffic yet.</div>"

    html = "<div class='space-y-3'>"
    for name, tokens in provider_split.items():
        pct = (tokens / total_tokens) * 100
        color = {"groq": "bg-blue-500", "gemini": "bg-purple-500", "ollama": "bg-orange-500", "cache": "bg-emerald-500"}.get(name, "bg-gray-500")
        html += f"""
        <div>
            <div class="flex justify-between text-xs mb-1">
                <span class="uppercase font-semibold text-gray-300">{name}</span>
                <span class="text-gray-400">{tokens} tokens</span>
            </div>
            <div class="w-full bg-gray-700 rounded-full h-2">
                <div class="{color} h-2 rounded-full" style="width: {pct}%"></div>
            </div>
        </div>
        """
    html += "</div>"
    return html

@app.get("/admin/ui/logs", response_class=HTMLResponse)
def get_ui_logs():
    if not AUDIT_LOG:
        return "<div class='text-sm text-gray-500'>No activity yet.</div>"
    
    rows = ""
    for entry in reversed(AUDIT_LOG[-20:]):
        ts = entry["timestamp"].split("T")[1][:8]
        provider = entry["provider_used"]
        cache = "✅" if entry["cache_hit"] else "❌"
        pii = "🛡️" if entry["pii_masked"] else "-"
        tokens = entry["tokens"]["total"]
        cost = entry["cost_usd"]
        status = entry["status"]
        status_color = "text-green-400" if status == "success" else "text-red-400"
        
        rows += f"""
        <tr class="border-b border-gray-700 text-sm">
            <td class="py-2 text-gray-400 font-mono">{ts}</td>
            <td class="py-2 text-gray-300 uppercase text-xs">{provider}</td>
            <td class="py-2 text-center">{cache}</td>
            <td class="py-2 text-center">{pii}</td>
            <td class="py-2 text-right font-mono">{tokens}</td>
            <td class="py-2 text-right font-mono text-emerald-400">${cost:.6f}</td>
            <td class="py-2 text-right text-xs {status_color}">{status[:20]}</td>
        </tr>
        """
        
    return f"""
    <div class="overflow-y-auto max-h-96">
        <table class="w-full text-left">
            <thead class="sticky top-0 bg-gray-800 text-xs text-gray-500 uppercase">
                <tr>
                    <th class="pb-2">Time</th>
                    <th class="pb-2">Provider</th>
                    <th class="pb-2 text-center">Cache</th>
                    <th class="pb-2 text-center">PII</th>
                    <th class="pb-2 text-right">Tokens</th>
                    <th class="pb-2 text-right">Cost</th>
                    <th class="pb-2 text-right">Status</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """