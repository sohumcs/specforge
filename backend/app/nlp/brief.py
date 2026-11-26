"""Extract structure from a free-text brief with spaCy (en_core_web_sm).

Output (`BriefSignals`) is used two ways:
1. as hints inside the stage-1 prompt (actors, entities, key terms), which keeps
   LLM output anchored to the user's own vocabulary;
2. as the raw material for the offline DemoProvider when no LLM is reachable.

Heuristics, all on spaCy's dependency parse:
* actors   - person-like nouns: a lexicon of common roles, plus nominal subjects
             with agentive suffixes (-er, -or, -ist, -ian, -ant, -ent)
* entities - nouns used as objects / compounds that aren't actors or filler words
* actions  - (verb, object, actor) triples such as ("track", "rider", "customer");
             actor is the verb's grammatical subject when it is an actor, else ""
* terms    - most frequent noun chunks
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

import spacy
from spacy.language import Language
from spacy.tokens import Token

MODEL = "en_core_web_sm"

ACTOR_LEXICON = {
    "user",
    "customer",
    "admin",
    "administrator",
    "manager",
    "student",
    "teacher",
    "faculty",
    "doctor",
    "patient",
    "nurse",
    "receptionist",
    "staff",
    "employee",
    "driver",
    "rider",
    "courier",
    "merchant",
    "vendor",
    "seller",
    "buyer",
    "owner",
    "guest",
    "member",
    "client",
    "agent",
    "operator",
    "auditor",
    "parent",
    "professor",
    "instructor",
    "clerk",
    "accountant",
    "restaurant",
    "partner",
    "visitor",
    "subscriber",
    "developer",
    "tenant",
    "landlord",
}
FILLER = {
    "system",
    "app",
    "application",
    "platform",
    "website",
    "site",
    "way",
    "thing",
    "feature",
    "ability",
    "time",
    "number",
    "lot",
    "kind",
    "type",
    "part",
    "need",
    "solution",
    "tool",
    "process",
    "service",
    "data",
    "information",
    "people",
    "everyone",
    "anyone",
    "product",
    "mvp",
    "version",
    "phase",
    "support",
    "experience",
    "use",
    "access",
    "ease",
    "real",
}
AGENTIVE_SUFFIXES = ("er", "or", "ist", "ian", "ant", "ent")
NON_AGENTIVE = ("ment", "ter", "order", "center", "error")


@dataclass
class BriefSignals:
    actors: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    actions: list[tuple[str, str, str]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    sentences: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def get_nlp() -> Language:
    """Loaded once per process (API never calls this; workers warm it at start)."""
    return spacy.load(MODEL, disable=["ner"])


def _pascal(word: str) -> str:
    return "".join(part.capitalize() for part in word.replace("-", " ").split())


def _subject_actor(verb: Token) -> str:
    """The actor doing `verb`: its nsubj, or the nsubj of the verb it's conjoined to
    ("customers browse restaurants and order meals" -> order's subject is customers)."""
    for v in (verb, verb.head if verb.dep_ in ("conj", "xcomp", "advcl") else None):
        if v is None:
            continue
        for child in v.children:
            if child.dep_ in ("nsubj", "nsubjpass"):
                lemma = child.lemma_.lower()
                agentive = lemma.endswith(AGENTIVE_SUFFIXES) and not lemma.endswith(NON_AGENTIVE)
                return lemma if lemma in ACTOR_LEXICON or agentive else ""
    return ""


def analyze(brief: str, *, max_items: int = 8) -> BriefSignals:
    doc = get_nlp()(brief)
    actors: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    actions: Counter[tuple[str, str, str]] = Counter()

    for tok in doc:
        if tok.pos_ not in ("NOUN", "PROPN") or tok.is_stop or len(tok.lemma_) < 3:
            continue
        lemma = tok.lemma_.lower()
        if lemma in FILLER:
            continue
        is_actor = lemma in ACTOR_LEXICON or (
            tok.dep_ in ("nsubj", "nsubjpass")
            and lemma.endswith(AGENTIVE_SUFFIXES)
            and not lemma.endswith(NON_AGENTIVE)
        )
        if is_actor:
            actors[lemma] += 1
        elif tok.dep_ in ("dobj", "pobj", "compound", "conj", "attr", "nsubjpass", "appos"):
            entities[lemma] += 1
        if tok.dep_ == "dobj" and tok.head.pos_ == "VERB":
            actions[(tok.head.lemma_.lower(), lemma, _subject_actor(tok.head))] += 1

    terms: Counter[str] = Counter()
    for chunk in doc.noun_chunks:
        words = [t.lemma_.lower() for t in chunk if not t.is_stop and t.is_alpha]
        if words and not all(w in FILLER for w in words):
            terms[" ".join(words)] += 1

    def top(c: Counter[Any]) -> list[Any]:
        # Ties broken alphabetically so output is deterministic.
        return [k for k, _ in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))][:max_items]

    return BriefSignals(
        actors=top(actors),
        entities=[_pascal(e) for e in top(entities)],
        actions=top(actions),
        terms=top(terms),
        sentences=len(list(doc.sents)),
    )
