"""Test doubles for the LLM layer."""

from typing import Any

from app.llm.providers.base import LLMRequest, LLMResponse
from app.llm.providers.demo import assemble
from app.llm.schemas import BlueprintDraft
from app.nlp.brief import BriefSignals

FOOD_BRIEF = (
    "A food delivery app where customers browse nearby restaurants, order meals and pay "
    "online. Riders pick up orders and deliver them while customers track the rider live. "
    "Restaurants manage menus and accept orders."
)


def valid_draft() -> BlueprintDraft:
    return assemble(
        BriefSignals(
            actors=["customer", "rider", "restaurant"],
            entities=["Order", "Menu", "Restaurant"],
            actions=[
                ("order", "meal", "customer"),
                ("track", "rider", "customer"),
                ("manage", "menu", "restaurant"),
            ],
        )
    )


def stage_payloads() -> dict[str, dict[str, Any]]:
    d = valid_draft()
    return {
        "requirements": d.requirements.model_dump(),
        "design": d.design.model_dump(),
        "tests": d.tests.model_dump(),
    }


class ScriptedProvider:
    """Returns scripted outcomes in order. An item may be:
    - a dict              -> returned as JSON data
    - "valid"             -> the correct payload for the requested stage
    - an Exception        -> raised
    """

    def __init__(
        self, name: str, script: list[Any] | None = None, *, configured: bool = True
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.script = list(script or [])
        self._configured = configured
        self.requests: list[LLMRequest] = []

    def configured(self) -> bool:
        return self._configured

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        item = self.script.pop(0) if self.script else "valid"
        if isinstance(item, Exception):
            raise item
        if item == "valid":
            item = stage_payloads()[request.stage]
        return LLMResponse(data=item, provider=self.name, model=self.model)
