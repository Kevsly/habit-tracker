"""Webhook notifications for streaks and goals.

Standard library only (:mod:`urllib.request`), so this costs no new dependency.
Two payload shapes are supported because they are the two that matter in
practice: a Slack-style ``{"text": ...}`` and a Discord-style ``{"content": ...}``.

Privacy note: the session *note* is excluded unless explicitly requested. A
webhook endpoint is usually a shared third-party URL, and habit notes tend to
be personal, so numbers are sent by default and prose only on request.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from urllib import error as urlerror
from urllib import request as urlrequest

from . import tracker

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0
USER_AGENT = "habit-tracker/notify"


class NotificationError(RuntimeError):
    """Raised when a notification cannot be prepared or delivered."""


@dataclass(frozen=True)
class Report:
    """A prepared notification, ready to send."""

    message: str
    habit: str
    current_streak: int
    week_done: int
    goal: int

    def payload(self) -> dict:
        """Slack-style body, with a Discord fallback key included."""
        return {"text": self.message, "content": self.message}


def build_report(
    view: dict,
    today: date,
    habit: str = "your habit",
    include_note: bool = False,
    note: str = "",
) -> Report:
    """Compose the message text from a single-habit view.

    Pure, so the wording can be asserted in tests without any network.
    """
    done, goal = tracker.week_progress(view, today)
    streak = tracker.current_streak(view, today)
    longest = tracker.longest_streak(view)
    total = len(tracker.session_notes(view))

    if goal:
        weekly = f"{done}/{goal} this week"
    else:
        weekly = f"{done} this week (no goal set)"
    text = f"{habit}: {streak}-day streak, {weekly}."

    if total == 0:
        text += " Nothing logged yet - today is a good day to start."
    elif streak == 0:
        text += " Streak has lapsed - today is a good day to start again."
    elif longest > streak:
        text += f" Best so far: {longest}."

    if goal and done >= goal:
        text += " Goal reached."

    if include_note and note:
        text += f' Note: "{note}"'

    return Report(
        message=text,
        habit=habit,
        current_streak=streak,
        week_done=done,
        goal=goal,
    )


def send(url: str, report: Report, timeout: float = DEFAULT_TIMEOUT) -> None:
    """POST ``report`` as JSON to ``url``.

    Raises :class:`NotificationError` with a human-readable message on any
    failure, so a scheduled job fails loudly instead of silently doing nothing.
    """
    if not url or not url.strip():
        raise NotificationError("No webhook URL configured.")

    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in ("http", "https"):
        raise NotificationError(f"Webhook URL must be http or https, got {scheme or 'no'} scheme.")

    body = json.dumps(report.payload()).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise NotificationError(f"Webhook returned HTTP {status}.")
    except urlerror.HTTPError as exc:
        raise NotificationError(f"Webhook returned HTTP {exc.code}.") from exc
    except urlerror.URLError as exc:
        raise NotificationError(f"Could not reach the webhook: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise NotificationError("Webhook timed out.") from exc
    except OSError as exc:
        raise NotificationError(f"Could not send the webhook: {exc}.") from exc
