"""Commit and PR attribution helpers."""

from __future__ import annotations

from dataclasses import dataclass

KNIGHT_BOT_NAME = "knight[bot]"
KNIGHT_BOT_EMAIL = "knight@users.noreply.github.com"


@dataclass(frozen=True)
class CollaboratorIdentity:
    display_name: str
    commit_name: str
    commit_email: str


def make_identity(*, name: str, email: str) -> CollaboratorIdentity | None:
    """Build a CollaboratorIdentity from explicit name/email strings."""
    name = name.strip()
    email = email.strip()
    if not name or not email:
        return None
    return CollaboratorIdentity(display_name=name, commit_name=name, commit_email=email)


def add_coauthor_trailer(
    commit_message: str,
    identity: CollaboratorIdentity | None,
) -> str:
    """Append a Co-authored-by git trailer when an identity is available."""
    normalized = commit_message.rstrip()
    if not identity:
        return normalized
    trailer = f"Co-authored-by: {identity.commit_name} <{identity.commit_email}>"
    if trailer in normalized:
        return normalized
    return f"{normalized}\n\n{trailer}"


def add_pr_collaboration_note(
    pr_body: str,
    identity: CollaboratorIdentity | None,
) -> str:
    """Append a collaboration attribution note to a PR body.

    GitHub supports commit co-authors via trailers but not PR co-authors,
    so this note makes the collaboration visible in the PR description.
    """
    normalized = pr_body.rstrip()
    if not identity:
        return normalized
    note = f"_Opened collaboratively by {identity.display_name} and Knight._"
    if note in normalized:
        return normalized
    if not normalized:
        return note
    return f"{normalized}\n\n{note}"
