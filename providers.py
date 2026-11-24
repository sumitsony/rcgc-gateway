# providers.py
import httpx
import os

TIMEOUT = 30.0

# ADR-003 (revised): All providers use the OpenAI-compatible chat completions endpoint.
# Gemini, Groq, and Ollama all expose this format, so we can use a single
# request/response shape. The only differences are base URL and model name.

PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.8-flash",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1/chat/completions",
        "api_key_env": None,
        "default_model": "llama3.2",
    },
}

async def _call_openai_compatible(provider: str, payload: dict) -> dict:
    cfg = PROVIDER_CONFIG[provider]

    # Set the model if the client didn't specify one (or used "default")
    if payload.get("model") in (None, "default"):
        payload["model"] = cfg["default_model"]

    headers = {"Content-Type": "application/json"}
    if cfg["api_key_env"]:
        key = os.getenv(cfg["api_key_env"])
        if not key:
            raise ValueError(f"Missing {cfg['api_key_env']} for provider '{provider}'")
        headers["Authorization"] = f"Bearer {key}"
    else:
        # Ollama ignores the key, but the OpenAI-compatible endpoint requires one
        headers["Authorization"] = "Bearer ollama"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(cfg["base_url"], headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

async def call_groq(payload: dict) -> dict:
    return await _call_openai_compatible("groq", payload)

async def call_gemini(payload: dict) -> dict:
    return await _call_openai_compatible("gemini", payload)

async def call_ollama(payload: dict) -> dict:
    return await _call_openai_compatible("ollama", payload)