"""Real models (CPU). Loaded once per test session; first run downloads ~100 MB."""

import numpy as np
import pytest

from app.verify import ml


@pytest.fixture(scope="module", autouse=True)
def models():
    ml.warm_up()
    assert ml.models_loaded()


def test_embeddings_are_normalised_384d():
    v = ml.embed(["Users sign in with email", "Riders deliver orders"])
    assert v.shape == (2, 384) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4)
    assert ml.embed([]).shape == (0, 384)


def test_paraphrase_vs_unrelated_similarity():
    v = ml.embed(
        [
            "Users sign in with email and password.",
            "Users authenticate using email and a password.",
            "Riders deliver food orders to customers.",
        ]
    )
    assert float(v[0] @ v[1]) >= ml.NEAR_DUPLICATE_MIN
    assert float(v[0] @ v[2]) < ml.TOPIC_MIN


def test_nli_label_order_guard():
    probs = ml.nli_contradiction(
        [
            ("All data must be encrypted.", "Data is never encrypted."),
            ("Users log in with email.", "Users sign in using email."),
        ]
    )
    assert probs[0] > 0.8 > probs[1]


def test_book_vs_cancel_is_not_reported_although_nli_alone_says_contradiction():
    a, b = "Patients can book appointments online.", "Patients can cancel appointments online."
    assert ml.nli_contradiction([(a, b)])[0] > 0.9  # raw NLI: false positive
    assert ml.find_contradictions([a, b], ml.embed([a, b])) == []  # hybrid: filtered


def test_real_contradictions_are_found_with_cue():
    texts = [
        "All customer data must be encrypted at rest.",
        "Customer data is stored unencrypted to speed up analytics queries.",
        "Riders can see delivery addresses.",
    ]
    found = ml.find_contradictions(texts, ml.embed(texts))
    assert [(c.a, c.b) for c in found] == [(0, 1)]
    assert "opposite" in found[0].cue and found[0].score >= ml.NLI_MIN


def test_unrelated_topics_skip_nli(monkeypatch):
    calls = []
    monkeypatch.setattr(ml, "nli_contradiction", lambda pairs: calls.append(pairs) or [])
    texts = ["Payments are never refunded.", "The homepage shows trending restaurants."]
    assert ml.find_contradictions(texts, ml.embed(texts)) == []
    assert calls == []  # pruned by topic similarity / cue filter before the model
