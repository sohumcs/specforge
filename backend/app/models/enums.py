from enum import StrEnum


class Role(StrEnum):
    """Per-project roles, ordered by privilege (see ROLE_RANK)."""

    viewer = "viewer"
    editor = "editor"
    owner = "owner"


ROLE_RANK = {Role.viewer: 1, Role.editor: 2, Role.owner: 3}


class NodeType(StrEnum):
    requirement = "requirement"
    story = "story"
    module = "module"
    api = "api"
    entity = "entity"
    test = "test"
    risk = "risk"


NODE_KEY_PREFIX = {
    NodeType.requirement: "REQ",
    NodeType.story: "US",
    NodeType.module: "MOD",
    NodeType.api: "API",
    NodeType.entity: "ENT",
    NodeType.test: "TST",
    NodeType.risk: "RSK",
}


class EdgeType(StrEnum):
    refines = "refines"  # requirement -> story
    implemented_by = "implemented_by"  # story -> module
    exposes = "exposes"  # module -> api
    persists = "persists"  # api -> entity
    relates_to = "relates_to"  # entity -> entity
    verified_by = "verified_by"  # story | api -> test
    threatens = "threatens"  # risk -> requirement | module
    depends_on = "depends_on"  # module -> module


# Which (source type, target type) pairs each edge type allows.
EDGE_RULES: dict[EdgeType, set[tuple[NodeType, NodeType]]] = {
    EdgeType.refines: {(NodeType.requirement, NodeType.story)},
    EdgeType.implemented_by: {(NodeType.story, NodeType.module)},
    EdgeType.exposes: {(NodeType.module, NodeType.api)},
    EdgeType.persists: {(NodeType.api, NodeType.entity)},
    EdgeType.relates_to: {(NodeType.entity, NodeType.entity)},
    EdgeType.verified_by: {(NodeType.story, NodeType.test), (NodeType.api, NodeType.test)},
    EdgeType.threatens: {(NodeType.risk, NodeType.requirement), (NodeType.risk, NodeType.module)},
    EdgeType.depends_on: {(NodeType.module, NodeType.module)},
}


class NodeStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    in_review = "in_review"
    done = "done"


TRACKABLE_TYPES = {NodeType.story, NodeType.test}


class BlueprintStatus(StrEnum):
    draft = "draft"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class JobKind(StrEnum):
    generate = "generate"
    verify = "verify"
    regenerate_subgraph = "regenerate_subgraph"
    fix_issue = "fix_issue"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    dead = "dead"  # exhausted retries -> dead-letter


class IssueCategory(StrEnum):
    traceability = "traceability"
    completeness = "completeness"
    consistency = "consistency"
    uniqueness = "uniqueness"
    conventions = "conventions"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
