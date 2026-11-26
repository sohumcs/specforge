from app.nlp.brief import analyze
from tests.llm_fakes import FOOD_BRIEF


def test_food_brief_signals():
    s = analyze(FOOD_BRIEF)
    assert {"customer", "rider", "restaurant"} <= set(s.actors)
    assert "Order" in s.entities or "Meal" in s.entities
    assert ("track", "rider", "customer") in s.actions
    assert s.sentences >= 2
    assert all(t == t.lower() for t in s.terms)


def test_deterministic_and_filler_free():
    brief = "The system lets the platform users manage things. Admins approve invoices."
    a, b = analyze(brief), analyze(brief)
    assert a == b
    assert "System" not in a.entities and "Platform" not in a.entities
    assert "admin" in a.actors
    assert ("approve", "invoice", "admin") in a.actions


def test_signals_serialise():
    d = analyze(FOOD_BRIEF).as_dict()
    assert set(d) == {"actors", "entities", "actions", "terms", "sentences"}
