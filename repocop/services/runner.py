"""Runner: each task's work, run in the background and keyed by task id.

Request handlers hand work to the runner and return at once; they never wait for it. For most
tasks the work is a Claude session. A running task has one live session, and an instruction goes
to that task's session only (invariant 5). The runner records the session's updates as task
events and moves the task through the status machine: a finished turn leaves it waiting_for_user
(ADR-009), an error fails it, and a cancel interrupts it. An instruction sent mid-turn is
answered as the next turn; one sent to a waiting task resumes its session.

A task that addresses a review is given that review with its first prompt.

A review task's work is one run of the reviewer instead (ADR-025). Its output becomes task
events, and it completes on its own with the commit it covered, or fails with the reason: the
reviewer's own, or that the review left the worktree changed. It takes no instructions.

The runner records each task's process, so a restart can stop one left behind. It lives on the
app's event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import (
    claude,
    codex,
    repositories,
    requirements,
    reviews,
    tasks,
    worktrees,
)
from repocop.services.tasks import Status, Task, TaskError

logger = logging.getLogger(__name__)

CANCEL_GRACE_S = 10.0
RESTART_REASON = "RepoCop restarted during this task."
CHANGED_WORKTREE = "the review left the worktree changed, which a review must never do"


@dataclass
class _Live:
    """A task's session, or its review, while its background job runs."""

    session: claude.Session | None = None
    review: codex.Review | None = None
    reviewing: bool = False  # the job is a review, which has no session to instruct
    job: asyncio.Task[None] | None = None
    backlog: list[str] = field(default_factory=list)  # sent before the session was open
    pending: int = 0  # instructions queued mid-turn, each answered as one more turn
    closing: bool = False  # the job has decided to stop: new instructions resume instead
    cancelling: bool = False


class TaskRunner:
    def __init__(
        self, settings: Settings, factory: claude.ClientFactory = claude.sdk_client
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._live: dict[int, _Live] = {}

    def recover(self) -> list[Task]:
        """Settle tasks whose sessions a stopped RepoCop left behind (ADR-010).

        A process a task left running is stopped first, and for a review everything it started,
        since a review runs in a process group of its own. Each task then records where it
        stopped (commits and uncommitted files in its worktree). A running task with a session
        waits for the user, who can resume it; any other fails as app_restarted.
        """
        settled = []
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?) ORDER BY id",
                (Status.RUNNING.value, Status.QUEUED.value),
            ).fetchall()
            for task in (Task.from_row(row) for row in rows):
                details = {"interrupted": self._interruption(conn, task)}
                if task.status is Status.RUNNING and task.claude_session_id:
                    settled.append(
                        tasks.transition(conn, task.id, Status.WAITING_FOR_USER, details=details)
                    )
                else:
                    settled.append(
                        tasks.transition(
                            conn, task.id, Status.FAILED, error=tasks.RESTARTED, details=details
                        )
                    )
                tasks.set_process(conn, task.id, None, None)
        return settled

    def run(self, task_id: int) -> None:
        """Start a queued task: it becomes running now, and its work starts in the background."""
        with self._db() as conn:
            task = tasks.transition(conn, task_id, Status.RUNNING)
            prompt = None if reviews.is_review(task) else self._first_prompt(conn, task)
            if prompt is not None and (handed := reviews.handover(conn, task)) is not None:
                tasks.record(conn, task_id, "user_instruction", {"text": handed})
                prompt = f"{prompt}\n\n{handed}"
        if prompt is None:
            live = _Live(reviewing=True)
            self._live[task_id] = live
            live.job = asyncio.get_running_loop().create_task(self._review(task_id, live))
        else:
            self._launch(task_id, prompt, resume=None)

    async def send(self, task_id: int, text: str) -> None:
        """Deliver an instruction to this task's session and no other."""
        text = text.strip()
        if not text:
            raise TaskError("the instruction is empty")
        live = self._live.get(task_id)
        if live is not None and live.reviewing:
            raise TaskError(f"task #{task_id} is a review, which takes no instructions")
        if live is not None and not live.closing and not live.cancelling:
            live.pending += 1
            self._record(task_id, "user_instruction", {"text": text})
            if live.session is None:
                live.backlog.append(text)
            else:
                await live.session.send(text)
            return
        if live is not None and live.job is not None:
            await live.job  # the previous turn is finishing; resume only once it has closed
        with self._db() as conn:
            task = _get(conn, task_id)
            if task.status is not Status.WAITING_FOR_USER or not task.claude_session_id:
                raise TaskError(
                    f"task #{task_id} is {task.status}; instructions go to a running task or "
                    "one waiting for you"
                )
            tasks.record(conn, task_id, "user_instruction", {"text": text})
            tasks.transition(conn, task_id, Status.RUNNING)
        self._launch(task_id, text, resume=task.claude_session_id)

    async def cancel(self, task_id: int) -> None:
        """Interrupt a running task's session or stop its review, or cancel a task with neither."""
        live = self._live.get(task_id)
        if live is not None and not live.closing and live.job is not None:
            live.cancelling = True
            if live.session is not None:
                await live.session.interrupt()
            if live.review is not None:
                await live.review.stop()
            try:
                await asyncio.wait_for(asyncio.shield(live.job), timeout=CANCEL_GRACE_S)
            except TimeoutError:
                live.job.cancel()
                self._finish(task_id, Status.CANCELLED)
            return
        with self._db() as conn:
            tasks.cancel(conn, _get(conn, task_id))

    async def shutdown(self) -> None:
        """Stop every live session. Their tasks keep their status for restart recovery."""
        jobs = [live.job for live in self._live.values() if live.job is not None]
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    def _launch(self, task_id: int, prompt: str, resume: str | None) -> None:
        live = _Live()
        self._live[task_id] = live
        live.job = asyncio.get_running_loop().create_task(
            self._drive(task_id, live, prompt, resume)
        )

    async def _drive(self, task_id: int, live: _Live, prompt: str, resume: str | None) -> None:
        try:
            with self._db() as conn:
                task = _get(conn, task_id)
                repository = repositories.get(conn, task.repository_id)
            if repository is None or task.worktree_path is None:
                raise TaskError(f"task #{task_id} has no repository or worktree to run in")
            live.session = await claude.Session.open(
                self._settings, repository, task.worktree_path, resume=resume, factory=self._factory
            )
            if live.session.process is not None:
                with self._db() as conn:
                    tasks.set_process(
                        conn, task_id, live.session.process.pid, live.session.process.start
                    )
            if live.cancelling:
                self._finish(task_id, Status.CANCELLED)
                return
            await live.session.send(prompt)
            for text in live.backlog:
                await live.session.send(text)
            async for update in live.session.updates():
                if self._apply(task_id, live, update):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a session that can't run fails its task rather than vanishing
            logger.exception("Task #%d's session failed", task_id)
            self._finish(task_id, Status.FAILED, error=str(exc))
        finally:
            if self._live.get(task_id) is live:
                del self._live[task_id]
            if live.session is not None:
                with contextlib.suppress(Exception):
                    await live.session.close()
                if live.session.process is not None:
                    with self._db() as conn:
                        tasks.set_process(conn, task_id, None, None)

    async def _review(self, task_id: int, live: _Live) -> None:
        """One review of the task's worktree, from the checks that refuse it to how it ended."""
        try:
            with self._db() as conn:
                task = _get(conn, task_id)
                repository = repositories.get(conn, task.repository_id)
            worktree = task.worktree_path
            if repository is None or worktree is None:
                raise TaskError(f"task #{task_id} has no repository or worktree to run in")
            subject = await asyncio.to_thread(reviews.subject, self._settings, repository, worktree)
            before = await asyncio.to_thread(reviews.state, worktree)
            live.review = await codex.Review.start(
                self._settings, repository, worktree, base=subject.base
            )
            if (process := claude.process_ref(live.review.pid)) is not None:
                with self._db() as conn:
                    tasks.set_process(conn, task_id, process.pid, process.start)
            if _cancelled(live):
                self._finish(task_id, Status.CANCELLED)
                return
            async for update in live.review.updates():
                if isinstance(update, codex.Output):
                    self._record(task_id, "command_output", {"text": update.text})
                    continue
                live.closing = True
                changed = await asyncio.to_thread(reviews.state, worktree) != before
                if _cancelled(live):
                    self._finish(task_id, Status.CANCELLED)
                elif update.review is None or changed:
                    error = update.error or CHANGED_WORKTREE
                    self._record(task_id, "error", {"error": error})
                    self._finish(task_id, Status.FAILED, error=error)
                else:
                    self._record(
                        task_id, "assistant_text", {"text": update.review, "who": codex.NAME}
                    )
                    covered: dict[str, object] = {"review": {"commit": subject.head}}
                    self._finish(task_id, Status.COMPLETED, details=covered)
        except asyncio.CancelledError:
            raise
        except RepoCopError as exc:  # a review that can't run says why
            self._record(task_id, "error", {"error": str(exc)})
            self._finish(task_id, Status.FAILED, error=str(exc))
        except Exception as exc:
            logger.exception("Task #%d's review failed", task_id)
            self._finish(task_id, Status.FAILED, error=str(exc))
        finally:
            if self._live.get(task_id) is live:
                del self._live[task_id]
            if live.review is not None:
                with contextlib.suppress(Exception):
                    await live.review.stop()
                with self._db() as conn:
                    tasks.set_process(conn, task_id, None, None)

    def _apply(self, task_id: int, live: _Live, update: claude.Update) -> bool:
        """Record one update; True when the job should stop."""
        match update:
            case claude.SessionStarted(session_id=session_id):
                with self._db() as conn:
                    tasks.set_session(conn, task_id, session_id)
            case claude.Event(kind=kind, payload=payload):
                self._record(task_id, kind, payload)
            case claude.TurnEnded(ok=ok, error=error):
                if live.cancelling:
                    live.closing = True
                    self._finish(task_id, Status.CANCELLED)
                    return True
                if not ok:
                    live.closing = True
                    self._record(task_id, "error", {"error": error})
                    self._finish(task_id, Status.FAILED, error=error)
                    return True
                if live.pending:
                    live.pending -= 1
                    return False
                live.closing = True
                self._finish(task_id, Status.WAITING_FOR_USER)
                return True
        return False

    def _interruption(self, conn: sqlite3.Connection, task: Task) -> dict[str, object]:
        """Stop the task's leftover process, if any, then note where its worktree stands."""
        stopped = None
        if task.session_pid is not None and task.session_pid_start is not None:
            process = claude.ProcessRef(task.session_pid, task.session_pid_start)
            if claude.stop(process, group=reviews.is_review(task)):
                stopped = process.pid
                logger.warning("Stopped task #%d's leftover process %d", task.id, process.pid)
        snapshot = None
        repository = repositories.get(conn, task.repository_id)
        if repository and task.worktree_path and task.base_commit:
            try:
                snapshot = worktrees.snapshot(
                    repository, self._settings, task.worktree_path, task.base_commit
                )
            except RepoCopError:
                logger.warning("Couldn't read task #%d's worktree", task.id)
        return {
            "reason": RESTART_REASON,
            "commits": snapshot.commits if snapshot else None,
            "uncommitted": list(snapshot.uncommitted) if snapshot else None,
            "stopped_process": stopped,
        }

    def _first_prompt(self, conn: sqlite3.Connection, task: Task) -> str:
        """`/<workflow> <requirement path>`: the repo's skill does the rest."""
        requirement = requirements.get(conn, task.requirement_id) if task.requirement_id else None
        if requirement is None:
            return f"/{task.workflow}"
        return f"/{task.workflow} {requirement.path}"

    def _record(self, task_id: int, kind: str, payload: dict[str, object]) -> None:
        with self._db() as conn:
            tasks.record(conn, task_id, kind, dict(payload))

    def _finish(
        self,
        task_id: int,
        status: Status,
        error: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        with self._db() as conn:
            try:
                tasks.transition(conn, task_id, status, error=error, details=details)
            except TaskError:
                logger.warning("Task #%d couldn't move to %s", task_id, status)

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with contextlib.closing(db.connect(self._settings.database_path)) as conn:
            yield conn


def _cancelled(live: _Live) -> bool:
    """Whether a cancel has come in. Asked each time, since it can while the job waits."""
    return live.cancelling


def _get(conn: sqlite3.Connection, task_id: int) -> Task:
    task = tasks.get(conn, task_id)
    if task is None:
        raise TaskError(f"task #{task_id} doesn't exist")
    return task
