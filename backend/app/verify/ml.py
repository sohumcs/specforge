"""ML layer: embeddings (duplicates) and NLI (contradictions), CPU only.

Models (verified on Hugging Face, Apache-2.0):
* sentence-transformers/all-MiniLM-L6-v2   22.7M params, 384-d, normalised
* cross-encoder/nli-deberta-v3-xsmall      70.8M params, labels
                                           [contradiction, entailment, neutral]

Both load lazily ONCE per process (Celery threads share them) and are baked
into the worker image so pods never download at start-up.

Contradictions are a hybrid: NLI proposes, linguistics confirms
-----------------------------------------------------------------
Probing the NLI model (SNLI/MNLI-trained) showed "Patients can *book*
appointments" vs "Patients can *cancel* appointments" scored 0.99
contradiction: to an SNLI model two different events in one scene contradict.
Genuine requirement conflicts ("must be encrypted" vs "stored unencrypted",
"never editable" vs "editable at any time", "can cancel" vs "cannot cancel")
carry a polarity cue. So a pair is reported only if
  1. the requirements are about the same topic (cosine >= TOPIC_MIN),
  2. NLI P(contradiction) >= NLI_MIN in at least one direction, and
  3. a polarity cue differs between them: negation in exactly one, an antonym
     prefix (un-/non-/in-/dis-) pair, or conflicting numbers for the same unit.
"""

import logging
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

log = logging.getLogger("specforge.ml")

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NLI_MODEL = "cross-encoder/nli-deberta-v3-xsmall"
NLI_LABELS = ("contradiction", "entailment", "neutral")

DUPLICATE_MIN = 0.90
NEAR_DUPLICATE_MIN = 0.80
TOPIC_MIN = 0.45
NLI_MIN = 0.80

_lock = threading.Lock()


@lru_cache(maxsize=1)
def embedder() -> Any:
    with _lock:
        from sentence_transformers import SentenceTransformer

        log.info("loading %s", EMBED_MODEL)
        return SentenceTransformer(EMBED_MODEL, device="cpu")


@lru_cache(maxsize=1)
def nli_model() -> Any:
    with _lock:
        from sentence_transformers import CrossEncoder

        log.info("loading %s", NLI_MODEL)
        model = CrossEncoder(NLI_MODEL, device="cpu")
        labels = tuple(model.model.config.id2label[i].lower() for i in range(3))
        if labels != NLI_LABELS:  # guard against a model card / label-order change
            raise RuntimeError(f"unexpected NLI label order {labels}")
        return model


def models_loaded() -> bool:
    return embedder.cache_info().currsize == 1 and nli_model.cache_info().currsize == 1


def warm_up() -> None:
    embedder()
    nli_model()


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vecs = embedder().encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return np.asarray(vecs, dtype=np.float32)


def nli_contradiction(pairs: list[tuple[str, str]]) -> list[float]:
    """P(contradiction) for each (premise, hypothesis) pair."""
    if not pairs:
        return []
    probs = nli_model().predict(pairs, apply_softmax=True, batch_size=16, show_progress_bar=False)
    return [float(p[0]) for p in probs]


# ------------------------------------------------------------------ polarity cues

NEGATIONS = {
    "not",
    "no",
    "never",
    "cannot",
    "can't",
    "won't",
    "without",
    "none",
    "nobody",
    "nothing",
    "neither",
    "nor",
    "n't",
    "unable",
    "prohibited",
    "forbidden",
    "disallowed",
}
NEG_PREFIXES = ("un", "non", "in", "dis", "im", "ir")
UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|sec|seconds?|minutes?|mins?|hours?|hrs?|days?|"
    r"%|percent|mb|gb|users?|requests?|rps)\b",
    re.IGNORECASE,
)
_UNIT_ALIASES = {
    "millisecond": "ms",
    "milliseconds": "ms",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "minute": "min",
    "minutes": "min",
    "mins": "min",
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "hrs": "h",
    "day": "d",
    "days": "d",
    "percent": "%",
    "user": "users",
    "request": "requests",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _has_negation(words: list[str]) -> bool:
    return any(w in NEGATIONS or w.endswith("n't") for w in words)


def _antonym_prefix_pair(a: list[str], b: list[str]) -> str | None:
    sa, sb = set(a), set(b)
    for w in sa:
        for p in NEG_PREFIXES:
            if w.startswith(p) and len(w) > len(p) + 3 and w[len(p) :] in sb:
                return f"{w[len(p) :]} / {w}"
    for w in sb:
        for p in NEG_PREFIXES:
            if w.startswith(p) and len(w) > len(p) + 3 and w[len(p) :] in sa:
                return f"{w[len(p) :]} / {w}"
    return None


def _quantities(text: str) -> dict[str, set[float]]:
    out: dict[str, set[float]] = {}
    for value, unit in UNIT_RE.findall(text):
        u = _UNIT_ALIASES.get(unit.lower(), unit.lower())
        out.setdefault(u, set()).add(float(value))
    return out


def polarity_cue(a: str, b: str) -> str | None:
    """Why two statements could genuinely conflict, or None."""
    wa, wb = _words(a), _words(b)
    if _has_negation(wa) != _has_negation(wb):
        return "negation in one statement only"
    pair = _antonym_prefix_pair(wa, wb)
    if pair:
        return f"opposite terms ({pair})"
    qa, qb = _quantities(a), _quantities(b)
    for unit in qa.keys() & qb.keys():
        if qa[unit] != qb[unit]:
            return f"conflicting values for '{unit}'"
    return None


@dataclass
class Contradiction:
    a: int
    b: int
    score: float
    similarity: float
    cue: str


def find_contradictions(texts: list[str], vectors: np.ndarray) -> list[Contradiction]:
    """Return confirmed contradictions among `texts` (indices into the list)."""
    n = len(texts)
    if n < 2:
        return []
    sims = vectors @ vectors.T
    candidates: list[tuple[int, int, str]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] < TOPIC_MIN:
                continue
            cue = polarity_cue(texts[i], texts[j])
            if cue:  # cheap filter first: skip NLI for pairs with no possible conflict
                candidates.append((i, j, cue))
    if not candidates:
        return []
    pairs = [(texts[i], texts[j]) for i, j, _ in candidates]
    pairs += [(texts[j], texts[i]) for i, j, _ in candidates]
    probs = nli_contradiction(pairs)
    k = len(candidates)
    found = []
    for idx, (i, j, cue) in enumerate(candidates):
        score = max(probs[idx], probs[idx + k])
        if score >= NLI_MIN:
            found.append(Contradiction(i, j, round(score, 3), round(float(sims[i, j]), 3), cue))
    return found
