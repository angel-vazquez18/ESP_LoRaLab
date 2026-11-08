"""Reconcile this repository's Project status labels; dry-run unless --apply."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
STATUS_LABELS = {
    "To do": "status:todo",
    "In progress": "status:in-progress",
    "Testing": "status:testing",
    "Completed": "status:completed",
}


def api(path: str, method: str = "GET", payload: dict | None = None) -> object:
    env = os.environ.copy()
    if path == "graphql" and env.get("GH_PROJECT_TOKEN"):
        env["GH_TOKEN"] = env["GH_PROJECT_TOKEN"]
    args = ["gh", "api", path, "--method", method]
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(
        args,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    value = json.loads(result.stdout) if result.stdout.strip() else None
    if isinstance(value, dict) and value.get("errors"):
        raise RuntimeError(str(value["errors"]))
    return value


def graphql(query: str, **variables: object) -> dict:
    return api("graphql", "POST", {"query": query, "variables": variables})["data"]


def read_issues(repo: str) -> list[dict]:
    issues = []
    page = 1
    while True:
        rows = api(f"repos/{repo}/issues?state=all&per_page=100&page={page}")
        issues.extend(row for row in rows if "pull_request" not in row)
        if len(rows) < 100:
            return issues
        page += 1


def read_items(project: str) -> dict[str, dict]:
    items = {}
    after = None
    while True:
        connection = graphql(
            """query($project:ID!,$after:String){node(id:$project){... on ProjectV2{
              items(first:100,after:$after){nodes{id content{... on Issue{id}}
                fieldValueByName(name:"Status"){
                  ... on ProjectV2ItemFieldSingleSelectValue{name}}}
                pageInfo{hasNextPage endCursor}}}}}""",
            project=project,
            after=after,
        )["node"]["items"]
        for item in connection["nodes"]:
            if (item.get("content") or {}).get("id"):
                items[item["content"]["id"]] = item
        if not connection["pageInfo"]["hasNextPage"]:
            return items
        after = connection["pageInfo"]["endCursor"]


def desired_state(issue: dict, item: dict | None, issues: dict[int, dict]) -> tuple:
    """Keep unrelated labels and manually declared non-issue blockers intact."""
    current = ((item or {}).get("fieldValueByName") or {}).get("name")
    if current and current not in STATUS_LABELS:
        raise ValueError(f"Unknown Project status {current!r}; refusing to guess")
    status = current or "To do"
    if issue["state"] == "closed" and issue.get("state_reason") == "completed":
        status = "Completed"
    elif issue["state"] == "closed" and status == "Completed":
        status = "To do"  # not-planned is never a successful completion
    labels = {label["name"] for label in issue["labels"]}
    desired = STATUS_LABELS[status]
    add = {desired} - labels
    remove = {label for label in labels if label.startswith("status:")} - {desired}
    deps = {
        int(number)
        for number in re.findall(
            r"(?im)^\s*-?\s*Blocked by\s+#(\d+)", issue.get("body") or ""
        )
    }
    if deps:
        blocked = any(
            n not in issues
            or issues[n]["state"] != "closed"
            or issues[n].get("state_reason") != "completed"
            for n in deps
        )
        if blocked and "blocked" not in labels:
            add.add("blocked")
        elif not blocked and "blocked" in labels:
            remove.add("blocked")
    return status, sorted(add), sorted(remove)


def sync(config: dict, apply: bool) -> None:
    repo = config["repository"]
    issues = read_issues(repo)
    by_number = {row["number"]: row for row in issues}
    items = read_items(config["project_id"])
    changes = 0
    for issue in issues:
        item = items.get(issue["node_id"])
        status, add, remove = desired_state(issue, item, by_number)
        current = ((item or {}).get("fieldValueByName") or {}).get("name")
        if not item or current != status or add or remove:
            changes += 1
            print(
                f"#{issue['number']}: project={status}; add={add}; remove={remove}"
                + (" [new card]" if not item else ""),
                flush=True,
            )
            if not apply:
                continue
            if not item:
                item = graphql(
                    """mutation($project:ID!,$issue:ID!){addProjectV2ItemById(
                    input:{projectId:$project,contentId:$issue}){item{id}}}""",
                    project=config["project_id"],
                    issue=issue["node_id"],
                )["addProjectV2ItemById"]["item"]
                time.sleep(1)
            if current != status:
                graphql(
                    """mutation($project:ID!,$item:ID!,$field:ID!,$option:String!){
                    updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,
                    fieldId:$field,value:{singleSelectOptionId:$option}}){projectV2Item{id}}}""",
                    project=config["project_id"],
                    item=item["id"],
                    field=config["status_field_id"],
                    option=config["status_options"][status],
                )
                time.sleep(1)
            if add:
                api(
                    f"repos/{repo}/issues/{issue['number']}/labels",
                    "POST",
                    {"labels": add},
                )
                time.sleep(1)
            for label in remove:
                api(
                    f"repos/{repo}/issues/{issue['number']}/labels/{quote(label, safe='')}",
                    "DELETE",
                )
                time.sleep(1)
    print(
        f"{len(issues)} issues inspected; {changes} changes {'applied' if apply else 'planned'}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sync"])
    parser.add_argument(
        "--apply", action="store_true", help="Write changes; otherwise read-only"
    )
    args = parser.parse_args()
    config = json.loads((ROOT / ".github/project.json").read_text())
    sync(config, args.apply)


if __name__ == "__main__":
    main()
