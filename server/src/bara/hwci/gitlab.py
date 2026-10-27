"""The few GitLab REST calls the hardware gate makes. The token comes from the environment
(`TANGIBLE_GITLAB_TOKEN`, a project access token with `api` scope) and never from a file."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

MARKER = "<!-- tangible-hardware-gate -->"


class GitLab:
    def __init__(self, api: str, project: str, token: str) -> None:
        self.api = api.rstrip("/")
        self.project = urllib.parse.quote(project, safe="")
        self.token = token

    @classmethod
    def from_env(cls) -> GitLab | None:
        token = os.environ.get("TANGIBLE_GITLAB_TOKEN")
        api = os.environ.get("CI_API_V4_URL")
        project = os.environ.get("CI_PROJECT_ID")
        return cls(api, project, token) if token and api and project else None

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        req = urllib.request.Request(
            f"{self.api}/projects/{self.project}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def upsert_mr_note(self, mr_iid: str, body: str) -> str:
        """One gate note per MR, edited in place on every pipeline instead of piling up."""
        text = f"{MARKER}\n{body}"
        notes = self.call("GET", f"/merge_requests/{mr_iid}/notes?per_page=100&sort=desc")
        mine = next((n for n in notes if MARKER in (n.get("body") or "")), None)
        if mine:
            self.call("PUT", f"/merge_requests/{mr_iid}/notes/{mine['id']}", {"body": text})
            return f"updated note {mine['id']}"
        made = self.call("POST", f"/merge_requests/{mr_iid}/notes", {"body": text})
        return f"created note {made['id']}"

    def label_mr(self, mr_iid: str, passed: bool) -> None:
        add, remove = ("hardware::pass", "hardware::fail")[:: 1 if passed else -1]
        self.call("PUT", f"/merge_requests/{mr_iid}", {"add_labels": add, "remove_labels": remove})

    def open_issue(self, title: str, body: str, labels: str) -> str:
        """Open an issue unless an open one with the same title exists; return its URL."""
        q = urllib.parse.quote(title)
        found = self.call("GET", f"/issues?state=opened&search={q}&in=title")
        same = next((i for i in found if i["title"] == title), None)
        if same:
            self.call("POST", f"/issues/{same['iid']}/notes", {"body": body})
            return same["web_url"]
        return self.call("POST", "/issues", {"title": title, "description": body,
                                             "labels": labels})["web_url"]  # fmt: skip
