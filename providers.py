# providers.py
import httpx
import os

# We use a standard timeout for all providers
TIMEOUT = 10.0

async def call_groq(payload: dict) -> dict:
    """Groq is OpenAI-compatible, so we just pass the payload."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set")
        
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload
        )
        response.raise_for_status()
        return response.json()

async def call_gemini(payload: dict) -> dict:
    """
    Gemini requires a translation layer. 
    We assume the input payload is OpenAI format (messages: [{role, content}]).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    # Translation: OpenAI -> Gemini
    messages = payload.get("messages", [])
    # Gemini separates system prompt from contents
    system_instruction = None
    contents = []
    
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": [{"text": msg["content"]}]}
        elif msg["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

    gemini_payload = {"contents": contents}
    if system_instruction:
        gemini_payload["system_instruction"] = system_instruction

    # Default to gemini-1.5-flash for zero-cost tier
    model = payload.get("model", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(url, json=gemini_payload)
        response.raise_for_status()
        data = response.json()

    # Translation: Gemini -> OpenAI (so the gateway always returns OpenAI format)
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        text = "Error: Could not parse Gemini response."

    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {
            # Gemini provides token counts in usageMetadata
            "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount", 0),
            "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0),
            "total_tokens": data.get("usageMetadata", {}).get("totalTokenCount", 0)
        }
    }

async def call_ollama(payload: dict) -> dict:
    """Ollama is OpenAI-compatible natively."""
    # Default to a local model if none specified
    if "model" not in payload:
        payload["model"] = "llama3.2"
        
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "http://localhost:11434/v1/chat/completions",
            json=payload
        )
        response.raise_for_status()
        return response.json()