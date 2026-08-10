"""BOOSTOPT Action — GitHub posting (#18, step 3, the network half).

Posts/updates the summary comment and (in suggest mode) inline review suggestions,
using only the standard library (`urllib`) so the Docker image stays minimal.

Everything here is BEST-EFFORT and self-guarding: with no token or no pull-request
context it simply logs and returns, and any HTTP failure is caught — posting must
never change the build result (that's `--fail-on`'s job, already decided upstream).

This half needs a real repo + token to exercise end-to-end, so it is deliberately
thin and side-effect-isolated; the rendering it posts is unit-tested in `comment.py`.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _log(msg: str) -> None:
    sys.stderr.write(f"boostopt-action: {msg}\n")


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    return ""


def _token() -> str:
    return _env("GITHUB_TOKEN", "INPUT_GITHUB-TOKEN", "INPUT_GITHUB_TOKEN")


def _api() -> str:
    return _env("GITHUB_API_URL") or "https://api.github.com"


def pr_context() -> tuple[int, str] | None:
    """(pr_number, head_sha) from the event payload, or None when not a PR run."""
    path = _env("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        ev = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    pr = ev.get("pull_request") or {}
    num = pr.get("number") or ev.get("number")
    sha = (pr.get("head") or {}).get("sha", "")
    return (int(num), sha) if num else None


def _request(method: str, url: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw else {})


def _ready() -> tuple[str, int, str] | None:
    """Common preconditions for any post: token + repo + PR. Returns (repo, pr, sha)."""
    repo = _env("GITHUB_REPOSITORY")
    ctx = pr_context()
    if not _token() or not repo or not ctx:
        _log("skipping post — no token / repository / pull-request context "
             "(this is expected off a PR event).")
        return None
    return repo, ctx[0], ctx[1]


def post_or_update_summary(body: str, marker: str) -> bool:
    """Create the summary comment, or edit the existing one carrying `marker`
    (so each push updates one comment instead of spamming). Returns True on success."""
    ready = _ready()
    if not ready:
        return False
    repo, pr, _ = ready
    base = f"{_api()}/repos/{repo}"
    try:
        _, comments = _request("GET", f"{base}/issues/{pr}/comments?per_page=100")
        existing = next((c for c in comments if marker in (c.get("body") or "")), None)
        if existing:
            _request("PATCH", f"{base}/issues/comments/{existing['id']}", {"body": body})
            _log(f"updated summary comment on PR #{pr}.")
        else:
            _request("POST", f"{base}/issues/{pr}/comments", {"body": body})
            _log(f"posted summary comment on PR #{pr}.")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
        _log(f"could not post summary comment: {e}")
        return False


def post_suggestions(suggestions: list[dict]) -> int:
    """Post one inline review suggestion per finding hunk. Best-effort per item —
    GitHub only allows a comment on a line that's part of the PR's own diff, so some
    may be rejected; we skip those and report the count. Returns number posted."""
    ready = _ready()
    if not ready or not suggestions:
        return 0
    repo, pr, sha = ready
    if not sha:
        _log("no head SHA in the event payload — cannot anchor suggestions.")
        return 0
    url = f"{_api()}/repos/{repo}/pulls/{pr}/comments"
    posted = 0
    for s in suggestions:
        payload = {"body": s["body"], "commit_id": sha, "path": s["path"],
                   "line": s["line"], "side": "RIGHT"}
        if s.get("start_line") and s["start_line"] < s["line"]:
            payload["start_line"] = s["start_line"]
            payload["start_side"] = "RIGHT"
        try:
            _request("POST", url, payload)
            posted += 1
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
            _log(f"suggestion on {s['path']}:{s['line']} not posted "
                 f"(likely outside the PR diff): {e}")
    _log(f"posted {posted}/{len(suggestions)} inline suggestion(s) on PR #{pr}.")
    return posted
