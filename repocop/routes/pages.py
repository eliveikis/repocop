"""The template environment every page renders with: what the shell's sidebar lists, read only
when a page shows it; the `ago` filter, which shows a time relative to now, with the exact time
on hover; and the `sessions_id` filter, the element id of a session list."""

import hashlib
from contextlib import closing
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from repocop import db
from repocop.config import Settings
from repocop.services import navigation
from repocop.services.repositories import Repository


def templates(directory: Path) -> Jinja2Templates:
    """The page templates in `directory`, each given the sidebar and the filters."""
    environment = Jinja2Templates(directory=directory, context_processors=[_shell])
    environment.env.filters["ago"] = ago
    environment.env.filters["sessions_id"] = sessions_id
    return environment


class LazySidebar:
    """What the sidebar lists, read the first time a page shows it, so a fragment, which
    doesn't, reads nothing for it: the repositories, and the sessions that need input."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def repositories(self) -> list[Repository]:
        with closing(db.connect(self._settings.database_path)) as conn:
            return navigation.sidebar(conn)

    @cached_property
    def needs_input(self) -> list[navigation.SessionEntry]:
        with closing(db.connect(self._settings.database_path)) as conn:
            return navigation.needs_input(conn, self._settings)


def _shell(request: Request) -> dict[str, Any]:
    return {"sidebar": LazySidebar(request.app.state.settings)}


def sessions_id(key: str) -> str:
    """The element id of the session list named `key`: the same for the same key, on any page."""
    return "sessions-" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]


def ago(when: str | datetime | None) -> Markup:
    """`when` (a stored timestamp, or a datetime) as a `<time>` that reads relative to now,
    such as "3 min ago", with the exact UTC time on hover. Nothing for None."""
    if when is None:
        return Markup("")
    moment = datetime.fromisoformat(when) if isinstance(when, str) else when
    moment = moment.astimezone(UTC).replace(microsecond=0)
    elapsed = (datetime.now(UTC) - moment).total_seconds()
    return Markup('<time datetime="{}" title="{}">{}</time>').format(
        moment.isoformat(), moment.strftime("%Y-%m-%d %H:%M:%S UTC"), _relative(int(elapsed))
    )


def _relative(seconds: int) -> str:
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if minutes < 1:
        return "just now"
    if hours < 1:
        return f"{minutes} min ago"
    if days < 1:
        return _count(hours, "hour")
    if days < 30:
        return "yesterday" if days == 1 else _count(days, "day")
    if days < 365:
        return _count(days // 30, "month")
    return _count(days // 365, "year")


def _count(number: int, unit: str) -> str:
    return f"{number} {unit}{'' if number == 1 else 's'} ago"
