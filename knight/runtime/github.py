"""GitHub API utilities for PR creation and repository inspection."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_HTTP_CREATED = 201
_HTTP_OK = 200
_HTTP_UNPROCESSABLE = 422


def _auth_headers(token: str) -> dict[str, str]:
    return {**_GITHUB_HEADERS, "Authorization": f"Bearer {token}"}


def create_github_pr(
    *,
    repo_owner: str,
    repo_name: str,
    github_token: str,
    title: str,
    head_branch: str,
    base_branch: str,
    body: str,
) -> tuple[str | None, int | None, bool]:
    """Create a draft GitHub pull request, or return the URL of an existing one.

    Returns:
        (pr_url, pr_number, pr_existing) — pr_existing is True when an open PR
        for the head branch already existed and was returned instead of created.
    """
    payload = {
        "title": title,
        "head": head_branch,
        "base": base_branch,
        "body": body,
        "draft": True,
    }
    logger.info(
        "creating PR: repo=%s/%s head=%s base=%s",
        repo_owner,
        repo_name,
        head_branch,
        base_branch,
    )
    try:
        response = requests.post(
            f"{_GITHUB_API}/repos/{repo_owner}/{repo_name}/pulls",
            headers=_auth_headers(github_token),
            json=payload,
            timeout=30,
        )
        data = response.json()

        if response.status_code == _HTTP_CREATED:
            pr_url = data.get("html_url")
            pr_number = data.get("number")
            logger.info("PR created: %s", pr_url)
            return pr_url, pr_number, False

        if response.status_code == _HTTP_UNPROCESSABLE:
            # PR may already exist for this branch
            logger.warning(
                "GitHub API 422 creating PR (%s), searching for existing",
                data.get("message"),
            )
            existing = _find_existing_pr(
                repo_owner=repo_owner,
                repo_name=repo_name,
                github_token=github_token,
                head_branch=head_branch,
            )
            if existing:
                return existing[0], existing[1], True

        logger.error(
            "GitHub API error %s creating PR: %s",
            response.status_code,
            data.get("message"),
        )
        return None, None, False

    except requests.RequestException:
        logger.exception("HTTP error creating GitHub PR")
        return None, None, False


def _find_existing_pr(
    *,
    repo_owner: str,
    repo_name: str,
    github_token: str,
    head_branch: str,
) -> tuple[str | None, int | None]:
    head_ref = f"{repo_owner}:{head_branch}"
    for state in ("open", "all"):
        try:
            response = requests.get(
                f"{_GITHUB_API}/repos/{repo_owner}/{repo_name}/pulls",
                headers=_auth_headers(github_token),
                params={"head": head_ref, "state": state, "per_page": 1},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if response.status_code != _HTTP_OK:
            continue
        prs = response.json()
        if prs:
            pr = prs[0]
            return pr.get("html_url"), pr.get("number")
    return None, None


def get_github_default_branch(
    *,
    repo_owner: str,
    repo_name: str,
    github_token: str,
) -> str:
    """Return the default branch of a GitHub repository, falling back to 'main'."""
    try:
        response = requests.get(
            f"{_GITHUB_API}/repos/{repo_owner}/{repo_name}",
            headers=_auth_headers(github_token),
            timeout=15,
        )
        if response.status_code == _HTTP_OK:
            branch = response.json().get("default_branch", "main")
            logger.debug("default branch for %s/%s: %s", repo_owner, repo_name, branch)
            return branch
        logger.warning(
            "could not fetch repo info (%s), falling back to 'main'",
            response.status_code,
        )
    except requests.RequestException:
        logger.exception("HTTP error fetching default branch, falling back to 'main'")
    return "main"
