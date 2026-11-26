Stage 3 of 3: test scenarios.

PROJECT BRIEF
"""
{{brief}}
"""

STORIES (with acceptance criteria)
{{stories}}

API ENDPOINTS
{{apis}}

Produce {{test_min}}-{{test_max}} test scenarios:
- Every story must be covered by at least one test (`story_refs`).
- Cover the most important endpoints directly (`api_refs`), including at least one negative or error case.
- Mix kinds: mostly `integration` and `e2e`, plus at least one `performance` and one `security` test.
- Each test has 2-5 short, concrete steps.
