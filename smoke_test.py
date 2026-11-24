# smoke_test.py
import httpx

BASE_URL = "http://127.0.0.1:8000"
HEADERS = {
    "Authorization": "Bearer test-key-123",
    "Content-Type": "application/json"
}

def print_separator():
    print("-" * 50)

def test_health():
    print("Testing /health...")
    try:
        resp = httpx.get(f"{BASE_URL}/health")
        assert resp.status_code == 200, f"Health check failed: {resp.text}"
        print("✅ Health check passed.")
    except httpx.ConnectError:
        print("❌ Could not connect to the gateway. Is uvicorn running on port 8000?")
        exit(1)

def test_provider(provider_name, model_name):
    print(f"Testing {provider_name.capitalize()} (Live)...")
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": f"Say 'I am {provider_name}' and nothing else."}]
    }
    headers = HEADERS.copy()
    headers["X-Force-Provider"] = provider_name

    try:
        resp = httpx.post(f"{BASE_URL}/v1/chat/completions", json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        print(f"✅ {provider_name.capitalize()} responded: {content.strip()}")
    except Exception as e:
        print(f"❌ {provider_name.capitalize()} failed: {e}")

if __name__ == "__main__":
    print("Starting RCGC Gateway Smoke Test...")
    print("Make sure `uvicorn main:app` is running in another terminal.")
    print("Make sure ALLOW_FORCE_PROVIDER=true is set in the server terminal.")
    print("Make sure GROQ_API_KEY and GEMINI_API_KEY are set.")
    print_separator()
    
    test_health()
    test_provider("groq", "openai/gpt-oss-120b")
    test_provider("gemini", "gemini-3.8-flash")
    # Ollama model name might differ (llama3.2, llama3, qwen2.5, etc.)
    # Change this to whatever model you have pulled locally.
    test_provider("ollama", "llama3.2") 
    print_separator()
    print("Smoke test complete.")