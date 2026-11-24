\# Architectural Decisions (RCGC Gateway)



\## ADR-001: In-Memory Dict for v0.1 Cache and Key Store

\*\*Decision:\*\* v0.1 uses a Python `dict` for exact-match cache and virtual key storage.

\*\*Why:\*\* Zero infrastructure dependencies. Tests run in under 1 second. The v0.1 goal is to verify \*logic\*, not \*persistence\*.

\*\*Tradeoff:\*\* Cache and keys die on restart. No TTL unless manually implemented.

\*\*Upgrade path:\*\* v0.2 introduces Redis via Docker Compose for semantic cache and persistent key storage. Postgres added when /usage needs to survive restarts.



\## ADR-002: Presidio with en\_core\_web\_sm (not default large model)

\*\*Decision:\*\* Use spaCy `en\_core\_web\_sm` (\~12MB) explicitly.

\*\*Why:\*\* Default `en\_core\_web\_lg` is \~560MB. Small model is sufficient for masking emails/phones/cards in a gateway input guardrail.

\*\*Tradeoff:\*\* Slightly lower recall on edge-case PII. Acceptable for v0.1.

\*\*Warm-up:\*\* FastAPI startup event triggers a dummy analyze() call to download the model on first boot.



\## ADR-003: OpenAI-Compatible Request Format

\*\*Decision:\*\* Gateway exposes `/v1/chat/completions` matching OpenAI's schema.

\*\*Why:\*\* Any client SDK (LangChain, openai-python) works without modification.

\*\*Adapter note:\*\* Groq and Ollama are OpenAI-compatible natively. Gemini requires a translation layer inside the router.



\## ADR-004: Zero-Cost Provider Matrix \& Shadow Cost Tracking

\*\*Decision:\*\* Supported providers are Groq, Gemini, and Ollama (local).

\*\*Why:\*\* User constraint: no paid API keys.

\*\*Shadow cost:\*\* /usage computes "equivalent USD cost" using public pricing tables for models like `llama-3.1-70b` or `gemini-1.5-flash`, so the cost-tracking logic is exercised without real spend.



\## ADR-005: Functional vs Red-Team Test Separation \& Mocking Strategy

\*\*Decision:\*\* Tests are split into `tests/functional/` and `tests/red\_team/`. Automated tests use `unittest.mock` to intercept `httpx` calls. A separate `smoke\_test.py` exists for live API verification.

\*\*Why:\*\* CI must be fast, free, and deterministic. Hitting real APIs in pytest makes tests flaky and dependent on network/rate limits. Mixing functional and adversarial tests hides which failures are regressions vs security findings.

\*\*Tradeoff:\*\* Automated tests do not catch upstream API breaking changes. The smoke test covers this gap.

