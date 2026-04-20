"""GitHub App authentication helpers.

Generates short-lived installation access tokens from a GitHub App's
private key.  These tokens work identically to PATs for git clone,
git push, and GitHub REST API calls.

Usage:
    token = await get_installation_token(
        app_id="123456",
        private_key="-----BEGIN RSA PRIVATE KEY-----\\n...",
        installation_id=12345678,
    )
    # use token as: https://x-access-token:<token>@github.com/owner/repo.git
"""
from __future__ import annotations

import time

import httpx
import jwt

_GITHUB_API = "https://api.github.com"
# Clock-skew buffer recommended by GitHub docs
_IAT_BUFFER_SECONDS = 60
# JWT is valid for 10 minutes max; we use 9 to leave headroom
_JWT_LIFETIME_SECONDS = 9 * 60
# Installation tokens are valid for 1 hour
_INSTALLATION_TOKEN_LIFETIME_SECONDS = 60 * 60


def _make_jwt(app_id: str, private_key: str) -> str:
    """Return a signed JWT for authenticating as the GitHub App itself."""
    now = int(time.time())
    payload = {
        "iss": app_id,
        "iat": now - _IAT_BUFFER_SECONDS,
        "exp": now + _JWT_LIFETIME_SECONDS,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(
    *,
    app_id: str,
    private_key: str,
    installation_id: int | str,
) -> str:
    """Exchange App credentials for a short-lived installation access token.

    Args:
        app_id: GitHub App ID (numeric string or int, shown in App settings).
        private_key: PEM-encoded RSA private key (the .pem file contents).
        installation_id: Installation ID from the webhook payload
            (``payload["installation"]["id"]``).

    Returns:
        An installation access token string, valid for ~1 hour.

    Raises:
        httpx.HTTPStatusError: if GitHub returns a non-2xx response.
    """
    app_jwt = _make_jwt(app_id, private_key.replace("\\n", "\n"))
    url = f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        return response.json()["token"]
