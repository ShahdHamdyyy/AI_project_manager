import json, re, sys
from difflib import SequenceMatcher

plan = json.load(open(sys.argv[1], encoding="utf-8"))
srs = open(sys.argv[2], encoding="utf-8").read()

issues = []


def add(level, msg):
    issues.append((level, msg))


tasks = plan["tasks"]
reqs = plan["requirements"]
sprint_of = {i: s["number"] for s in plan["sprints"] for i in s["task_ids"]}
owner_of = {a["task_id"]: a["member_id"] for a in plan["assignments"]}
member = {m["id"]: m for m in plan["team"]}


def text(t):
    return (t["title"] + " " + t["description"]).lower()


all_text = " ".join(text(t) for t in tasks)

# 1. requirements: every FR and NFR in the SRS must exist with its numbers and key terms
functional = [r for r in reqs if r["kind"] == "functional"]
frs = re.findall(r"\*\*FR-(\d+) ([^*]+?):\*\*\s*(.+)", srs)
if len(functional) < len(frs):
    add("ERROR", f"SRS has {len(frs)} functional requirements, plan has {len(functional)}")
key_terms = {1: ["rate"], 3: ["background"], 4: ["lock"], 6: ["store credit"], 9: ["override"]}
for num, title, body in frs:
    n = int(num)
    if n > len(functional):
        continue
    r = functional[n - 1]
    desc = r["description"].lower()
    for x in set(re.findall(r"\b\d+\b", body) + re.findall(r"USD|EUR|EGP", body)):
        if x.lower() not in desc:
            add("WARN", f"FR-{num} detail '{x}' is missing from {r['id']} description")
    for term in key_terms.get(n, []):
        if term not in desc:
            add("WARN", f"FR-{num} term '{term}' is missing from {r['id']} description")

nfr_section = srs.split("## 8.")[1].split("## 9.")[0]
nfr_plan = [r for r in reqs if r["kind"] == "non_functional"]
for title, body in re.findall(r"- \*\*([^:*]+):\*\*\s*(.+)", nfr_section):
    best = max(nfr_plan, key=lambda r: SequenceMatcher(None, title.lower(), r["title"].lower()).ratio(), default=None)
    if best is None or SequenceMatcher(None, title.lower(), best["title"].lower()).ratio() < 0.6:
        add("ERROR", f"NFR '{title}' is missing from the plan")
        continue
    for x in re.findall(r"\d[\d,]*", body):
        x = x.replace(",", "")
        if x not in best["description"].replace(",", ""):
            add("WARN", f"NFR '{title}' detail '{x}' is missing from {best['id']}")

# 2. epics: every non-constraint requirement is in an epic, and no epic is built from constraints only
covered = {r for e in plan["epics"] for r in e["requirement_ids"]}
kind = {r["id"]: r["kind"] for r in reqs}
for r in reqs:
    if r["kind"] != "constraint" and r["id"] not in covered:
        add("ERROR", f"{r['id']} {r['title']} is not in any epic")
for e in plan["epics"]:
    if e["requirement_ids"] and all(kind.get(i) == "constraint" for i in e["requirement_ids"]):
        add("ERROR", f"{e['id']} {e['name']} is built only from constraints (should not be an epic)")

# 3. tasks: must-have features, traceability, duplicates
for word in ["store credit", "fraud", "csv", "search", "redis", "argon", "rate limit", "main.py",
             "escalat", "wireframe", "load test", "state machine"]:
    if word not in all_text:
        add("ERROR", f'no task covers "{word}"')
referenced = set(re.findall(r"REQ-\d+", " ".join(t["description"] for t in tasks)))
if not referenced:
    add("WARN", "no task description references a REQ id (traceability missing)")
else:
    for r in functional:
        if r["id"] not in referenced:
            add("ERROR", f"{r['id']} {r['title']} has no task")
for i, a in enumerate(tasks):
    for b in tasks[i + 1:]:
        if SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio() > 0.8:
            add("WARN", f"possible duplicate tasks: {a['id']} '{a['title']}' and {b['id']} '{b['title']}'")

# 4. sprint placement from SRS section 11
rules = [("partial refund", {3}), ("multi-currency refund", {3}), ("store credit", {3}), ("fraud", {3}),
         ("ticket creation", {2}), ("deactivation", {2}), ("rbac", {1}), ("schema", {1, 2})]
for t in tasks:
    if t["type"] == "design":
        continue
    for word, ok in rules:
        if word in t["title"].lower() and sprint_of[t["id"]] not in ok:
            add("ERROR", f"{t['id']} '{t['title']}' is in sprint {sprint_of[t['id']]}, SRS says sprint {sorted(ok)}")

# 5. dependencies: SRS section 13 rules, order, cycles
dep = {}
for d in plan["dependencies"]:
    dep.setdefault(d["task_id"], set()).add(d["depends_on"])


def reach(a):
    seen, stack = set(), [a]
    while stack:
        x = stack.pop()
        for y in dep.get(x, ()):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return seen


for a, b in [("refund", "wallet"), ("fraud", "refund"), ("escalat", "schema"), ("escalat", "auth")]:
    src = [t["id"] for t in tasks if a in text(t)]
    dst = {t["id"] for t in tasks if b in text(t)}
    if src and dst and not any(reach(s) & dst for s in src):
        add("ERROR", f"SRS section 13: '{a}' tasks must depend on '{b}' tasks, no dependency path found")
for t in tasks:
    if t["id"] in reach(t["id"]):
        add("ERROR", f"{t['id']} is in a dependency cycle")
    for p in dep.get(t["id"], ()):
        if sprint_of[p] > sprint_of[t["id"]]:
            add("ERROR", f"{t['id']} (sprint {sprint_of[t['id']]}) depends on {p} (sprint {sprint_of[p]})")
tid_epic = {t["id"]: t["epic_id"] for t in tasks}
cross = [d for d in plan["dependencies"] if tid_epic[d["task_id"]] != tid_epic[d["depends_on"]]]
if not cross:
    add("WARN", "0 cross-epic dependencies, every dependency is the same-epic heuristic")

# 6. team, capacity, priorities, risks
allowed = {"project_manager", "backend_developer", "frontend_developer", "ui_ux_designer", "qa_engineer"}
for m in plan["team"]:
    if m["role"] not in allowed:
        add("WARN", f"{m['name']} ({m['role']}) is not in the SRS team")
    if "docker" in " ".join(m["skills"]).lower():
        add("ERROR", f"{m['name']} has a Docker skill, Docker is out of scope in the SRS")
total_cap = sum(s["capacity_hours"] for s in plan["sprints"])
total = sum(t["estimated_hours"] for t in tasks)
if total / total_cap < 0.6:
    add("WARN", f"only {100 * total / total_cap:.0f}% of capacity planned ({total:g}h of {total_cap:g}h), estimates look too low")
for m in plan["team"]:
    idle = []
    for s in plan["sprints"]:
        h = sum(t["estimated_hours"] for t in tasks if owner_of[t["id"]] == m["id"] and sprint_of[t["id"]] == s["number"])
        if h > m["capacity_hours_per_sprint"]:
            add("ERROR", f"{m['name']} has {h:g}h in sprint {s['number']}, capacity {m['capacity_hours_per_sprint']:g}h")
        if h == 0:
            idle.append(s["number"])
    if m["role"] != "project_manager" and len(idle) >= 2:
        add("WARN", f"{m['name']} is idle in sprints {idle}")
    if m["role"] == "qa_engineer" and 3 in idle:
        add("ERROR", f"{m['name']} has no work in sprint 3, SRS needs a regression suite running by M3")
high = sum(1 for t in tasks if t["priority"] == "high")
if high / len(tasks) > 0.5:
    add("WARN", f"{high}/{len(tasks)} tasks are high priority, priority is not informative")
for r in plan["risks"]:
    if re.search(r"add(ing)? more|extend", r["mitigation"].lower()):
        add("ERROR", f"{r['id']} mitigation conflicts with the fixed team/timeline: {r['mitigation']}")

for level, msg in issues:
    print(f"{level}: {msg}")
errors = sum(1 for l, _ in issues if l == "ERROR")
print(f"\n{errors} errors, {len(issues) - errors} warnings")
sys.exit(1 if errors else 0)
