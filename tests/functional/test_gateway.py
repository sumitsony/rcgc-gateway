# tests/functional/test_gateway.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import main

client = TestClient(main.app)

# --- Test Setup ---
# We use a fixture to clear in-memory state before every test
@pytest.fixture(autouse=True)
def clear_state():
    main.CACHE.clear()
    main.KEYS["test-key-123"]["tokens_used"] = 0

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@patch("providers.call_groq", new_callable=AsyncMock)
def test_auth_missing_key(mock_groq):
    # Redundant with red_team, but proves the happy path requires auth
    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 401
    mock_groq.assert_not_called()

@patch("providers.call_groq", new_callable=AsyncMock)
def test_cache_miss_then_hit(mock_groq):
    # Setup mock response
    mock_groq.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    
    headers = {"Authorization": "Bearer test-key-123"}
    payload = {"messages": [{"role": "user", "content": "Say hi"}]}

    # 1. First call (Cache Miss) - Should hit Groq
    response1 = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response1.status_code == 200
    assert response1.json()["choices"][0]["message"]["content"] == "Hi there!"
    assert mock_groq.call_count == 1
    
    # Verify usage updated
    usage_response = client.get("/usage", headers=headers)
    assert usage_response.json()["tokens_used"] == 15

    # 2. Second call (Cache Hit) - Should NOT hit Groq again
    response2 = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["choices"][0]["message"]["content"] == "Hi there!"
    assert mock_groq.call_count == 1 # Still 1, proving cache was used
    
    # Verify usage did NOT increase on cache hit (v0.1 design choice: cache hits are free)
    usage_response_2 = client.get("/usage", headers=headers)
    assert usage_response_2.json()["tokens_used"] == 15 

@patch("providers.call_groq", new_callable=AsyncMock)
@patch("providers.call_gemini", new_callable=AsyncMock)
def test_routing_fallback_to_gemini(mock_gemini, mock_groq):
    # Make Groq fail, Gemini succeed
    mock_groq.side_effect = Exception("Groq is down")
    mock_gemini.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Gemini here!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    
    headers = {"Authorization": "Bearer test-key-123"}
    payload = {"messages": [{"role": "user", "content": "Say hi"}]}

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Gemini here!"
    assert mock_groq.call_count == 1
    assert mock_gemini.call_count == 1