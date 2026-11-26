"""End-to-end smoke test against a running stack (API + worker).

    python scripts/e2e_smoke.py [base_url]

demo login -> create blueprint -> generate (SSE) -> quality report -> fix one
issue -> edit a requirement -> impact -> regenerate subgraph -> re-check.
Exits non-zero on any failure. Reused later as the post-deploy smoke test.
"""

import json
import sys
import time
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/api/v1"
BRIEF = (
    "A gym membership app where members book fitness classes and pay monthly fees, "
    "trainers publish class schedules and track attendance, and managers see revenue "
    "reports and manage membership plans. Bookings must never exceed class capacity."
)


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        sys.exit(1)


def wait_job(c: httpx.Client, job_id: str, label: str, timeout: float = 240) -> dict:
    steps = []
    with c.stream("GET", f"/jobs/{job_id}/events", timeout=timeout) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if not steps or steps[-1] != ev["step"]:
                    steps.append(ev["step"])
                if ev["status"] in ("succeeded", "failed", "dead"):
                    print(f"  {label}: {' -> '.join(steps)} [{ev['status']}]", flush=True)
                    return ev
    raise SystemExit(f"{label}: stream ended without a terminal event")


def main() -> None:
    t0 = time.time()
    c = httpx.Client(base_url=BASE, timeout=30)
    tok = c.post("/auth/demo").json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    sandbox = c.get("/projects").json()["items"][0]["id"]
    bp = c.post(
        f"/projects/{sandbox}/blueprints",
        json={"title": f"Smoke {uuid.uuid4().hex[:6]}", "brief": BRIEF},
    ).json()["id"]

    job = c.post(f"/blueprints/{bp}/generate", headers={"Idempotency-Key": f"smoke-{bp}"}).json()
    ev = wait_job(c, job["job_id"], "generate")
    check(
        ev["status"] == "succeeded",
        f"generated via {ev['result']['provider']} ({ev['result']['nodes']} nodes)",
    )
    q = c.get(f"/blueprints/{bp}/quality").json()
    by_cat = {x["category"]: x["score"] for x in q["breakdown"]["categories"]}
    check(q["breakdown"]["ml"] == "ok", f"quality score {q['score']} {by_cat}")
    for i in q["issues"][:6]:
        print(f"     [{i['severity']}] {i['rule_code']} {i['message'][:90]}")

    fixable = [i for i in q["issues"] if i["fixable"] and not i["resolved"]]
    if fixable:
        issue = fixable[0]
        ev = wait_job(c, c.post(f"/issues/{issue['id']}/fix").json()["job_id"], "fix")
        check(
            ev["status"] == "succeeded",
            f"fixed {issue['rule_code']}: {ev['result']['action'][:80]} "
            f"(via {ev['result']['provider']}, score {ev['result']['score_before']} -> "
            f"{ev['result']['score_after']})",
        )

    graph = c.get(f"/blueprints/{bp}/graph").json()
    req = next(n for n in graph["nodes"] if n["type"] == "requirement")
    r = c.patch(f"/nodes/{req['id']}", json={"title": req["title"] + " with a waitlist when full"})
    impact = r.json()["impact"]
    check(
        r.status_code == 200 and impact["impacted"],
        f"edited {req['key']}: {len(impact['impacted'])} nodes impacted, "
        f"depths {sorted(int(d) for d in impact['by_depth'])}",
    )
    stale = c.get(f"/blueprints/{bp}/graph?stale=true").json()["nodes"]
    check(len(stale) == len(impact["impacted"]), f"{len(stale)} nodes marked stale")

    ev = wait_job(
        c,
        c.post(f"/blueprints/{bp}/regenerate-subgraph", json={"root_node_id": req["id"]}).json()[
            "job_id"
        ],
        "regenerate",
    )
    check(
        ev["status"] == "succeeded",
        f"regenerated via {ev['result']['provider']}: "
        f"{len(ev['result']['updated'])} updated, {len(ev['result']['reviewed'])} reviewed",
    )
    check(c.get(f"/blueprints/{bp}/graph?stale=true").json()["nodes"] == [], "no stale nodes left")
    sim = c.get(f"/nodes/{req['id']}/similar?k=3").json()
    shown = ", ".join(f"{s['key']} {s['similarity']}" for s in sim)
    check(len(sim) == 3, f"similar nodes: {shown}")
    print(f"SMOKE OK in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
