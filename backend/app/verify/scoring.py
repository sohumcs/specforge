"""Blueprint Quality Score (0-100).

    score = sum(weight_c * category_score_c) / sum(weights)

Category scores:
* traceability, completeness, conventions: 100 * (1 - weighted_violations / checks)
  where a violation weighs high=1.0, medium=0.6, low=0.3. Normalising by the
  number of checks keeps big blueprints from being punished for being big.
* consistency (contradictions): 100 - 25 per contradiction (floor 0). Even one
  real contradiction in a spec is serious.
* uniqueness (duplicates): 100 - 15 per duplicate - 5 per near-duplicate.
"""

from dataclasses import dataclass

from app.models.enums import IssueCategory, Severity
from app.verify.rules import Finding, RuleResult

WEIGHTS = {
    IssueCategory.traceability: 35,
    IssueCategory.completeness: 25,
    IssueCategory.consistency: 20,
    IssueCategory.uniqueness: 10,
    IssueCategory.conventions: 10,
}
SEVERITY_WEIGHT = {Severity.high: 1.0, Severity.medium: 0.6, Severity.low: 0.3}


@dataclass
class CategoryScore:
    category: IssueCategory
    score: int
    weight: int
    checks: int
    issues: int


def _ratio_score(results: list[RuleResult]) -> tuple[int, int, int]:
    checks = sum(r.checks for r in results)
    findings = [f for r in results for f in r.findings]
    if checks == 0:
        return 100, 0, len(findings)
    penalty = sum(SEVERITY_WEIGHT[f.severity] for f in findings)
    return max(0, round(100 * (1 - min(penalty, checks) / checks))), checks, len(findings)


def score(
    rule_results: list[RuleResult], ml_findings: list[Finding]
) -> tuple[int, list[CategoryScore]]:
    cats: list[CategoryScore] = []
    for cat in (IssueCategory.traceability, IssueCategory.completeness, IssueCategory.conventions):
        s, checks, issues = _ratio_score([r for r in rule_results if r.category == cat])
        cats.append(CategoryScore(cat, s, WEIGHTS[cat], checks, issues))

    contradictions = [f for f in ml_findings if f.category == IssueCategory.consistency]
    cats.append(
        CategoryScore(
            IssueCategory.consistency,
            max(0, 100 - 25 * len(contradictions)),
            WEIGHTS[IssueCategory.consistency],
            -1,
            len(contradictions),
        )
    )
    dups = [f for f in ml_findings if f.category == IssueCategory.uniqueness]
    hard = sum(1 for f in dups if f.rule_code == "DUP-001")
    near = len(dups) - hard
    cats.append(
        CategoryScore(
            IssueCategory.uniqueness,
            max(0, 100 - 15 * hard - 5 * near),
            WEIGHTS[IssueCategory.uniqueness],
            -1,
            len(dups),
        )
    )

    total_w = sum(c.weight for c in cats)
    overall = round(sum(c.score * c.weight for c in cats) / total_w)
    order = list(WEIGHTS)
    cats.sort(key=lambda c: order.index(c.category))
    return overall, cats
