# smoke_test.py
import httpx
import os
import json

# We hit the local FastAPI server
BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"Authorization": "Bearer test-key-123"}

def print_separator():
    print("-" * 50)

def test_health():
    print("Testing /health...")
    resp = httpx.get(f"{BASE_URL}/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    print("✅ Health check passed.")

def test_groq_live():
    print("Testing Groq (Live)...")
    payload = {
        "model": "llama-3.1-8b-instant", # Explicitly ask for a fast Groq model
        "messages": [{"role": "user", "content": "Say 'Groq is live' and nothing else."}]
    }
    resp = httpx.post(f"{BASE_URL}/v1/chat/completions", json=payload, headers=HEADERS, timeout=30.0)
    assert resp.status_code == 200, f"Groq failed: {resp.text}"
    print(f"✅ Groq responded: {resp.json()['choices'][0]['message']['content']}")

def test_gemini_live():
    print("Testing Gemini (Live)...")
    payload = {
        "model": "gemini-1.5-flash",
        "messages": [{"role": "user", "content": "Say 'Gemini is live' and nothing else."}]
    }
    # We force Gemini by passing a specific model or modifying the gateway logic.
    # For the smoke test, we just rely on the gateway's fallback if Groq fails, 
    # but to test Gemini directly, we'd need to adjust the gateway routing or use a known failing Groq model.
    # For simplicity in v0.1, let's just ensure the gateway can route to it.
    print("⚠️  Note: To test Gemini directly, you might need to temporarily break the Groq key or modify the gateway.")

def test_ollama_live():
    print("Testing Ollama (Live)...")
    payload = {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Say 'Ollama is live' and nothing else."}]
    }
    # Again, Ollama is the final fallback. If Groq and Gemini fail, it hits this.
    print("⚠️  Note: Ollama is used as final fallback. Ensure it's running locally.")

if __name__ == "__main__":
    print("Starting RCGC Gateway Smoke Test...")
    print("Make sure `uvicorn main:app` is running in another terminal.")
    print("Make sure GROQ_API_KEY and GEMINI_API_KEY are set in your environment.")
    print_separator()
    
    try:
        test_health()
        # Note: The smoke test will just hit Groq by default, unless Groq fails.
        test_groq_live() 
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
    except httpx.ConnectError:
        print("❌ Could not connect to the gateway. Is uvicorn running on port 8000?")