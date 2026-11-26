"""Rule engine + scoring: every rule's pass and fail paths, pure (no DB, no ML)."""

import pytest

from app.models.enums import EdgeType, IssueCategory, NodeType, Severity
from app.verify.ml import polarity_cue
from app.verify.rules import (
    ALL_RULES,
    RULE_CATALOG,
    ApiMapsToModuleAndEntity,
    ApiNaming,
    EntityCrudCoverage,
    EntityNaming,
    Finding,
    HighRiskMitigated,
    KeysWellFormed,
    ModuleImplementsStory,
    NfrCoverage,
    NoOrphans,
    RequirementHasStory,
    StoryHasAcceptanceCriteria,
    StoryHasTest,
    path_problems,
    run_rules,
)
from app.verify.scoring import WEIGHTS, score
from tests.graph_builder import AC, G, healthy

T, E = NodeType, EdgeType


def codes(g: G) -> dict[str, int]:
    return {r.code: len(r.findings) for r in run_rules(g.view()) if r.findings}


def test_healthy_graph_passes_every_rule():
    assert codes(healthy()) == {}
    overall, cats = score(run_rules(healthy().view()), [])
    assert overall == 100 and all(c.score == 100 for c in cats)


def test_catalog_covers_all_rules_with_unique_codes():
    assert len(RULE_CATALOG) == len(ALL_RULES) == 12
    assert {r.code[:2] for r in ALL_RULES} == {"TR", "CP", "CV"}


def test_tr001_requirement_without_story():
    g = healthy().add("R2", T.requirement, "Track rider", kind="functional")
    res = RequirementHasStory().check(g.view())
    assert res.checks == 5 and len(res.findings) == 1
    f = res.findings[0]
    assert f.node_ids == [g.id("R2")] and f.severity == Severity.high and "R2" not in f.message
    assert f.message.startswith("REQ-005")


def test_tr002_story_without_test():
    g = healthy().add("S9", T.story, "As a rider", acceptance_criteria=AC)
    res = StoryHasTest().check(g.view())
    assert [f.node_ids for f in res.findings] == [[g.id("S9")]]


def test_tr003_api_without_module_and_entity():
    g = healthy().add("A9", T.api, "GET /riders", method="GET", path="/riders")
    (f,) = ApiMapsToModuleAndEntity().check(g.view()).findings
    assert f.details["missing"] == ["module", "entity"]
    g.link("M1", "A9", E.exposes)
    (f,) = ApiMapsToModuleAndEntity().check(g.view()).findings
    assert f.details["missing"] == ["entity"]


def test_tr004_orphans_and_tr005_module_without_story():
    g = healthy().add("X", T.entity, "Rider").add("M2", T.module, "Dispatch")
    orphan_ids = {f.node_ids[0] for f in NoOrphans().check(g.view()).findings}
    assert orphan_ids == {g.id("X"), g.id("M2")}
    assert [f.node_ids for f in ModuleImplementsStory().check(g.view()).findings] == [[g.id("M2")]]


def test_cp001_missing_and_badly_formed_criteria():
    g = healthy().add("S8", T.story, "no ac", acceptance_criteria=[])
    g.add("S9", T.story, "bad ac", acceptance_criteria=["It should work"])
    found = {f.node_ids[0]: f for f in StoryHasAcceptanceCriteria().check(g.view()).findings}
    assert found[g.id("S8")].severity == Severity.high
    assert found[g.id("S9")].severity == Severity.low
    assert found[g.id("S9")].details["not_gwt"] == ["It should work"]


def test_cp002_crud_coverage_and_exemption():
    g = (
        healthy()
        .add("E2", T.entity, "Payment")
        .add("AP", T.api, "POST /payments", method="POST", path="/payments")
    )
    g.link("AP", "E2", E.persists)
    (f,) = EntityCrudCoverage().check(g.view()).findings
    assert f.details["missing"] == ["read", "update", "delete"]
    g2 = healthy().add("E2", T.entity, "AuditLog", crud_exempt=True)
    assert EntityCrudCoverage().check(g2.view()).findings == []


def test_cp003_nfr_coverage():
    g = G().add("R1", T.requirement, "r", kind="non_functional", nfr_category="security")
    res = NfrCoverage().check(g.view())
    assert res.checks == 3
    assert sorted(f.details["nfr"] for f in res.findings) == ["availability", "performance"]


def test_cp004_high_risk_needs_mitigation_and_link():
    g = healthy().add("K2", T.risk, "Fraud", likelihood="low", impact="high", mitigation="tbd")
    g.add("K3", T.risk, "Minor", likelihood="low", impact="low", mitigation="")
    res = HighRiskMitigated().check(g.view())
    assert res.checks == 2  # K1 and K2 are high; K3 isn't checked
    (f,) = res.findings
    assert f.node_ids == [g.id("K2")] and len(f.details["problems"]) == 2


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("/orders", True),
        ("/orders/{order_id}/line-items", True),
        ("/users/me", True),
        ("/getOrders", False),
        ("/orders/create", False),
        ("/Order_Items", False),
        ("/v1/orders", False),
        ("/orders/{orderId}", False),
        ("/delete-user", False),
    ],
)
def test_cv001_path_rules(path, ok):
    assert (path_problems(path) == []) is ok, path_problems(path)


def test_cv001_rule_reports_first_problem():
    g = healthy().add("BAD", T.api, "GET /getOrders", method="GET", path="/getOrders")
    (f,) = ApiNaming().check(g.view()).findings
    assert "verb" in f.message or "kebab" in f.message


@pytest.mark.parametrize(
    ("name", "fields", "n_problems"),
    [
        ("Order", [{"name": "id", "primary_key": True}], 0),
        ("Status", [{"name": "id", "primary_key": True}], 0),  # 'status' isn't plural
        ("Orders", [{"name": "id", "primary_key": True}], 1),
        ("order_item", [{"name": "id", "primary_key": True}], 1),
        ("Order", [{"name": "createdAt", "primary_key": True}], 1),
        ("Order", [{"name": "id", "primary_key": False}], 1),
        ("Order", [{"name": "id", "primary_key": True}, {"name": "code", "primary_key": True}], 1),
    ],
)
def test_cv002_entity_naming(name, fields, n_problems):
    g = G().add("E", T.entity, name, fields=fields)
    found = EntityNaming().check(g.view()).findings
    assert (len(found[0].details["problems"]) if found else 0) == n_problems


def test_cv003_key_format():
    g = G().add("A", T.requirement, "r", key="REQ-001").add("B", T.requirement, "r", key="req1")
    assert [f.node_ids for f in KeysWellFormed().check(g.view()).findings] == [[g.id("B")]]


# ------------------------------------------------------------------ scoring


def _finding(code, cat, sev=Severity.medium):
    return Finding(code, cat, sev, "m", [], "h")


def test_score_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_score_normalises_by_checks_and_severity():
    g = healthy()
    for i in range(6):
        g.add(f"X{i}", T.requirement, f"r{i}", kind="functional")  # 6 high TR-001 violations
    overall, cats = score(run_rules(g.view()), [])
    trace = next(c for c in cats if c.category == IssueCategory.traceability)
    assert trace.issues == 12  # each also an orphan (TR-004, medium)
    assert 0 < trace.score < 100
    assert overall < 100


def test_score_ml_penalties():
    rules = run_rules(healthy().view())
    ml = [
        _finding("CON-001", IssueCategory.consistency, Severity.high),
        _finding("DUP-001", IssueCategory.uniqueness),
        _finding("DUP-002", IssueCategory.uniqueness),
    ]
    overall, cats = score(rules, ml)
    by = {c.category: c.score for c in cats}
    assert by[IssueCategory.consistency] == 75
    assert by[IssueCategory.uniqueness] == 80
    assert overall == round((35 * 100 + 25 * 100 + 20 * 75 + 10 * 80 + 10 * 100) / 100)


def test_score_floors_at_zero_and_empty_graph_is_100():
    many = [_finding("CON-001", IssueCategory.consistency)] * 10
    _, cats = score([], many)
    assert next(c for c in cats if c.category == IssueCategory.consistency).score == 0
    assert score(run_rules(G().view()), [])[0] < 100  # empty graph: no NFRs -> CP-003


# ------------------------------------------------------------------ polarity cues


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (
            "Patients can cancel up to 24 hours before.",
            "Patients cannot cancel once booked.",
            "negation",
        ),
        ("All data must be encrypted at rest.", "Data is stored unencrypted.", "opposite"),
        ("Pages load within 300 ms.", "Pages load within 2000 ms.", "conflicting"),
        ("Sessions expire after 15 minutes.", "Sessions expire after 30 minutes.", "conflicting"),
        ("Patients can book appointments.", "Patients can cancel appointments.", None),
        ("Users sign in with email.", "Users authenticate with email.", None),
    ],
)
def test_polarity_cue(a, b, expected):
    cue = polarity_cue(a, b)
    if expected is None:
        assert cue is None
    else:
        assert cue is not None and expected in cue
