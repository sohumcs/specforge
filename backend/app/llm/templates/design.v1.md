Stage 2 of 3: modules, data entities and REST API.

PROJECT BRIEF
"""
{{brief}}
"""

STAGE 1 RESULT (requirements and stories you must design for)
{{stage_a}}

Produce:
- {{mod_min}}-{{mod_max}} modules (cohesive components). Each lists the story refs it implements; every story must be implemented by at least one module. Use `depends_on` for module-to-module dependencies (no self-dependency, no cycles).
- {{ent_min}}-{{ent_max}} entities. Names in PascalCase singular (e.g. `Order`). Fields in snake_case; exactly one `primary_key` field named `id`. Use `relations` for links between entities.
- {{api_min}}-{{api_max}} REST endpoints. Paths are lowercase, kebab-case, plural nouns, versionless (e.g. `/orders/{id}/items`). Use the HTTP method that matches the action; never put verbs in paths. Each endpoint belongs to exactly one module (`module_ref`) and lists the entities it reads or writes. Give every entity create, read, update and delete coverage unless that makes no sense for the domain.
