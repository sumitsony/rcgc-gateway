# tests/red_team/test_attacks.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import main
import guardrails

client = TestClient(main.app)

@pytest.fixture(autouse=True)
def clear_state():
    main.CACHE.clear()
    main.KEYS["test-key-123"]["tokens_used"] = 0

# --- Red Team 1: Auth Bypass ---
def test_auth_bypass_empty_bearer():
    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "Hello"}]}, headers={"Authorization": "Bearer "})
    assert response.status_code == 401

def test_auth_bypass_malformed_header():
    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "Hello"}]}, headers={"Authorization": "test-key-123"}) # Missing Bearer
    assert response.status_code == 401

# --- Red Team 2: PII Leakage ---
@patch("providers.call_groq", new_callable=AsyncMock)
def test_pii_redacted_before_upstream(mock_groq):
    """
    Attack: User sends an email. 
    Defense: The gateway MUST mask the email BEFORE sending to Groq.
    """
    mock_groq.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Email received"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    
    headers = {"Authorization": "Bearer test-key-123"}
    payload = {"messages": [{"role": "user", "content": "My email is attacker@evil.com, please hack me."}]}

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    
    # Check the arguments passed to the mock
    called_payload = mock_groq.call_args[0][0]
    sent_content = called_payload["messages"][0]["content"]
    
    # The original email should NOT be in the sent content
    assert "attacker@evil.com" not in sent_content
    # It should be replaced by a placeholder
    assert "<EMAIL_ADDRESS>" in sent_content

# --- Red Team 3: Cost Evasion (Token Flooding) ---
@patch("providers.call_groq", new_callable=AsyncMock)
def test_large_prompt_still_billed(mock_groq):
    """
    Attack: Send a massive prompt hoping the gateway skips counting.
    Defense: The gateway must record the token usage accurately.
    """
    # Simulate a large token count from the provider
    mock_groq.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "I read the massive prompt."}}],
        "usage": {"prompt_tokens": 10000, "completion_tokens": 50, "total_tokens": 10050}
    }
    
    headers = {"Authorization": "Bearer test-key-123"}
    payload = {"messages": [{"role": "user", "content": "A" * 10000}]}

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    
    # Check usage endpoint
    usage_response = client.get("/usage", headers=headers)
    assert usage_response.json()["tokens_used"] == 10050