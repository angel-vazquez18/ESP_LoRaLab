"""Status reconciliation rules; no GitHub writes or physical ports."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "github_project", Path(__file__).resolve().parents[1] / "github_project.py"
)
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)


def issue(state="open", reason=None, labels=(), body=""):
    return {
        "state": state,
        "state_reason": reason,
        "labels": [{"name": name} for name in labels],
        "body": body,
    }


def item(status):
    return {"fieldValueByName": {"name": status}}


def test_board_status_wins_and_only_status_labels_are_removed():
    row = issue(
        labels=("status:todo", "status:completed", "area:firmware", "needs-hardware")
    )
    assert project.desired_state(row, item("Testing"), {}) == (
        "Testing",
        ["status:testing"],
        ["status:completed", "status:todo"],
    )


def test_closed_completed_moves_card_but_not_planned_never_completes():
    assert (
        project.desired_state(issue("closed", "completed"), item("Testing"), {})[0]
        == "Completed"
    )
    assert (
        project.desired_state(issue("closed", "not_planned"), item("Completed"), {})[0]
        == "To do"
    )


def test_missing_status_defaults_to_todo_and_unknown_status_is_rejected():
    assert project.desired_state(issue(), None, {}) == ("To do", ["status:todo"], [])
    try:
        project.desired_state(issue(), item("Invented"), {})
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown state must not be guessed")


def test_dependencies_require_completed_closure_and_manual_blockers_are_preserved():
    row = issue(
        labels=("status:todo", "blocked"),
        body="- Blocked by #3: fixture\n- Blocked by #4: hardware",
    )
    assert (
        "blocked"
        not in project.desired_state(
            row, item("To do"), {3: issue("closed", "completed")}
        )[2]
    )
    done = {3: issue("closed", "completed"), 4: issue("closed", "completed")}
    assert project.desired_state(row, item("To do"), done)[2] == ["blocked"]
    done[4] = issue("closed", "not_planned")
    assert "blocked" not in project.desired_state(row, item("To do"), done)[2]
    assert project.desired_state(issue(labels=("blocked",)), item("To do"), {})[2] == []


def test_project_item_pagination_and_redacted_items(monkeypatch):
    pages = iter(
        [
            {
                "nodes": [
                    {"id": "a", "content": {"id": "issue-a"}},
                    {"id": "redacted", "content": None},
                ],
                "pageInfo": {"hasNextPage": True, "endCursor": "next"},
            },
            {
                "nodes": [{"id": "b", "content": {"id": "issue-b"}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "end"},
            },
        ]
    )
    seen = []

    def gql(query, **variables):
        seen.append(variables["after"])
        return {"node": {"items": next(pages)}}

    monkeypatch.setattr(project, "graphql", gql)
    assert set(project.read_items("project")) == {"issue-a", "issue-b"}
    assert seen == [None, "next"]


def test_issue_pagination_excludes_pull_requests(monkeypatch):
    first = [{"number": n} for n in range(99)] + [{"number": 999, "pull_request": {}}]
    second = [{"number": 100}]
    seen = []

    def read(path):
        seen.append(path)
        return first if path.endswith("&page=1") else second

    monkeypatch.setattr(project, "api", read)
    assert len(project.read_issues("owner/repo")) == 100
    assert seen[-1].endswith("page=2")


def test_dry_run_never_adds_cards_or_changes_labels(monkeypatch, capsys):
    row = issue(labels=("status:testing",))
    row.update(number=1, node_id="issue")
    monkeypatch.setattr(project, "read_issues", lambda repo: [row])
    monkeypatch.setattr(project, "read_items", lambda project_id: {})

    def reject_write(*args, **kwargs):
        raise AssertionError("Dry run attempted a write")

    monkeypatch.setattr(project, "api", reject_write)
    monkeypatch.setattr(project, "graphql", reject_write)
    project.sync({"repository": "owner/repo", "project_id": "project"}, False)
    assert "1 changes planned" in capsys.readouterr().out
