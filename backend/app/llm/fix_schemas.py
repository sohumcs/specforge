"""Small structured-output schemas for targeted fixes and subgraph regeneration.
Same rules as app/llm/schemas.py: no Optional fields, "" / [] mean "none"."""

from pydantic import BaseModel, Field

from app.llm.schemas import TestKind


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class NewTest(_Strict):
    __test__ = False
    title: str = Field(min_length=3, max_length=200)
    kind: TestKind
    steps: list[str] = Field(min_length=1, max_length=6)


class NewStory(_Strict):
    title: str = Field(min_length=10, max_length=300)
    acceptance_criteria: list[str] = Field(min_length=2, max_length=4)
    test: NewTest


class StoriesFix(_Strict):
    stories: list[NewStory] = Field(min_length=1, max_length=2)


class TestsFix(_Strict):
    __test__ = False
    tests: list[NewTest] = Field(min_length=1, max_length=2)


class CriteriaFix(_Strict):
    acceptance_criteria: list[str] = Field(min_length=2, max_length=4)


class NfrFix(_Strict):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=600)
    story: NewStory


class MitigationFix(_Strict):
    mitigation: str = Field(min_length=15, max_length=800)


class RewriteFix(_Strict):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=800)
    rationale: str = Field(max_length=400)


class NodeUpdate(_Strict):
    key: str
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(max_length=800, description="new description/summary; '' = keep")
    acceptance_criteria: list[str] = Field(max_length=5, description="stories only; [] = keep")
    steps: list[str] = Field(max_length=6, description="tests only; [] = keep")


class SubgraphUpdate(_Strict):
    updates: list[NodeUpdate] = Field(max_length=40)
