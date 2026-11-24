# guardrails.py
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

# ADR-002: Explicitly use the small spaCy model (~12MB) to save memory and startup time.
# We configure the NLP engine provider manually to avoid Presidio defaulting to the large model.
configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}
provider = NlpEngineProvider(nlp_configuration=configuration)
nlp_engine = provider.create_engine()

#analyzer = AnalyzerEngine(nlp_engine=nlp_engine, registry=RecognizerRegistry(nlp_engine=nlp_engine))
#After (correct)
analyzer = AnalyzerEngine(nlp_engine=nlp_engine, registry=RecognizerRegistry())

anonymizer = AnonymizerEngine()

def warm_up():
    """Call this on FastAPI startup to download the spaCy model if missing."""
    # A tiny dummy string to force model loading into memory.
    analyzer.analyze(text="warm up", language="en")

def mask_pii(text: str) -> str:
    """Scans text for PII and replaces it with placeholder tags."""
    # We only analyze English for v0.1.
    results = analyzer.analyze(text=text, language="en")
    
    if not results:
        return text
    
    # Anonymizer replaces the PII with tags like <EMAIL_ADDRESS>
    anonymized_result = anonymizer.anonymize(
        text=text,
        analyzer_results=results
    )
    return anonymized_result.text