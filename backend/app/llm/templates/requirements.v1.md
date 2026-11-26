Stage 1 of 3: requirements, user stories and risks.

PROJECT BRIEF
"""
{{brief}}
"""

SIGNALS EXTRACTED FROM THE BRIEF (spaCy)
- Likely actors: {{actors}}
- Likely domain entities: {{entities}}
- Key terms: {{terms}}

Produce:
- {{req_min}}-{{req_max}} requirements. Most are `functional`. Include at least one `non_functional` requirement each for performance, security and availability (set `nfr_category` accordingly; functional ones use "none").
- {{story_min}}-{{story_max}} user stories in the form "As a <actor>, I want <goal> so that <benefit>". Every requirement, including non-functional ones, needs at least one story. Each story has 2-4 acceptance criteria written as "Given ..., when ..., then ...".
- 3-5 risks, each with likelihood, impact, a concrete mitigation, and the requirement refs it threatens.
