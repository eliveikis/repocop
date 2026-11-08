"""Requirement reviews: the review a requirement's review workflow saved, and whether the
requirement is ready to implement ("A requirement's review" in `specs/architecture.md`).

The workflow ends by saving its review as `<git common dir>/repocop/reviews/<file name>`,
replacing the requirement's last one: a header with its verdict, how many blocking questions it
asks, the SHA-256 of the requirement's file as reviewed and when it was saved, then the review.
A requirement is ready when its latest review says so of the text its file has now. Any local
process can write a review, so one is read only as a regular file inside the folder, never
through a link, at most MAX_BYTES of it, and shown escaped.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from stat import S_ISREG

from repocop.config import Settings
from repocop.services import backlog, requirements, sessions
from repocop.services.repositories import Repository

FORMAT = 1  # the version of the saved review's header read here
FOLDER = PurePosixPath("repocop", "reviews")  # in the repository's git common folder
WORKFLOW = "review-requirement"  # the workflow whose run ends by saving a review here
MAX_BYTES = 256 * 1024  # the most of a saved review that is read
SHA256 = re.compile(r"[0-9a-f]{64}")


class Verdict(StrEnum):
    YES = "yes"
    WITH_ASSUMPTIONS = "yes-with-assumptions"
    NO = "no"


class Standing(StrEnum):
    """Where a requirement stands for implementing, by its reviews."""

    NOT_REVIEWED = "Not reviewed"
    UNFINISHED = "Review unfinished"
    CHANGED = "Changed since review"
    NOT_READY = "Not ready"
    WITH_ASSUMPTIONS = "Ready with assumptions"
    READY = "Ready"

    @property
    def slug(self) -> str:
        return self.value.lower().replace(" ", "-")


@dataclass(frozen=True)
class Review:
    """A saved review of a requirement."""

    requirement: str  # the requirement's path, relative to the checkout
    verdict: Verdict
    blocking: int  # how many blocking questions it asks
    sha256: str  # of the requirement's file as reviewed
    at: datetime  # when it was saved
    text: str  # the review itself


@dataclass(frozen=True)
class Readiness:
    standing: Standing
    review: Review | None  # the latest saved
    started: datetime | None  # when a review was last started on it, if that is known


_OF_VERDICT = {
    Verdict.YES: Standing.READY,
    Verdict.WITH_ASSUMPTIONS: Standing.WITH_ASSUMPTIONS,
    Verdict.NO: Standing.NOT_READY,
}


def readiness(review: Review | None, started: datetime | None, text: bytes | None) -> Readiness:
    """Where a requirement whose file holds `text` stands, by its latest saved review and when a
    review was last started on it. A review started after the last one saved hasn't finished:
    it still runs, was stopped, or ran before reviews were saved. A file that differs from the
    one reviewed has changed since. Else the review's verdict tells, also when the file can't be
    read."""
    if started is not None and (review is None or review.at < started):
        return Readiness(Standing.UNFINISHED, review, started)
    if review is None:
        return Readiness(Standing.NOT_REVIEWED, None, started)
    if text is not None and hashlib.sha256(text).hexdigest() != review.sha256:
        return Readiness(Standing.CHANGED, review, started)
    return Readiness(_OF_VERDICT[review.verdict], review, started)


def of(repository: Repository, settings: Settings, file_names: list[str]) -> dict[str, Readiness]:
    """Where each requirement in the repository's folder called one of `file_names` stands, by
    file name."""
    started = sessions.last_started(repository, settings, WORKFLOW)
    return {
        file_name: of_one(repository, settings, file_name, started.get(backlog.name_of(file_name)))
        for file_name in file_names
    }


def of_one(
    repository: Repository, settings: Settings, file_name: str, started: datetime | None
) -> Readiness:
    """Where the requirement `file_name` in the repository's folder stands, given when a review
    was last started on it."""
    return readiness(
        saved(repository, settings, file_name),
        started,
        requirements.bytes_of(settings, repository, file_name),
    )


def saved(repository: Repository, settings: Settings, file_name: str) -> Review | None:
    """The latest review saved of the requirement `file_name` in the repository's folder. None
    when there is none, or it can't be read as one."""
    common = sessions.common_dir(repository, settings)
    if common is None or PurePosixPath(file_name).name != file_name:
        return None
    folder = common / FOLDER
    if folder.is_symlink() or not folder.resolve().is_relative_to(common.resolve()):
        return None
    data = _read(folder / file_name)
    if data is None:
        return None
    review = _parsed(data.decode("utf-8", "replace"))
    if review is None or review.requirement != f"{requirements.todo_dir(repository)}/{file_name}":
        return None
    return review


def _read(file: Path) -> bytes | None:
    """Up to MAX_BYTES of `file`, opened only as a regular file and never through a link."""
    try:
        descriptor = os.open(file, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as opened:
        if not S_ISREG(os.fstat(opened.fileno()).st_mode):
            return None
        return opened.read(MAX_BYTES)


def _parsed(content: str) -> Review | None:
    """The review `content` holds: its header between `---` lines, then the review."""
    if not content.startswith("---\n"):
        return None
    header, separator, text = content[4:].partition("\n---\n")
    if not separator:
        return None
    fields = dict(line.partition(": ")[::2] for line in header.split("\n"))
    try:
        review = Review(
            requirement=fields["requirement"],
            verdict=Verdict(fields["verdict"]),
            blocking=int(fields["blocking"]),
            sha256=fields["sha256"],
            at=datetime.fromisoformat(fields["at"]),
            text=text,
        )
    except (KeyError, ValueError):
        return None
    if (
        fields.get("v") != str(FORMAT)
        or review.at.tzinfo is None
        or review.blocking < 0
        or not fields["blocking"].isdigit()
        or not SHA256.fullmatch(review.sha256)
    ):
        return None
    return review
