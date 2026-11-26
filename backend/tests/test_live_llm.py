"""Opt-in checks against the real free-tier providers (spends a little quota).

SPECFORGE_LIVE_TESTS=1 pytest -m live
"""

import os

import pytest

from app.llm.breaker import MemoryBreaker
from app.llm.chain import generate_draft
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import cross_reference_errors
from app.nlp.brief import analyze

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("SPECFORGE_LIVE_TESTS") != "1",
        reason="set SPECFORGE_LIVE_TESTS=1 to call real providers",
    ),
]

BRIEF = (
    "A library app where members search the catalogue, borrow and renew books, and "
    "librarians manage inventory and overdue fines."
)


@pytest.mark.parametrize("provider_cls", [GeminiProvider, GroqProvider])
def test_provider_generates_valid_blueprint(provider_cls):
    provider = provider_cls()
    if not provider.configured():
        pytest.skip(f"{provider.name} key not configured")
    res = generate_draft(BRIEF, analyze(BRIEF), providers=[provider], breaker=MemoryBreaker())
    assert res.provider == provider.name, res.attempts
    d = res.draft
    assert cross_reference_errors(d.requirements, d.design, d.tests) == []
