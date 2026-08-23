"""Conversation-window policy independent of transport and persistence."""

from datetime import datetime, timedelta, timezone


DONE_COMMANDS = {"done"}
NEW_REPORT_COMMANDS = {"new report", "newreport"}


def normalized_command(text: str | None) -> str | None:
    if not text:
        return None
    command = " ".join(text.casefold().strip().split())
    if command in DONE_COMMANDS:
        return "done"
    if command in NEW_REPORT_COMMANDS:
        return "new_report"
    return None


def utc_aware(value: datetime) -> datetime:
    """Normalize database and provider timestamps to aware UTC."""
    # SQLite does not preserve timezone metadata even for timezone=True
    # columns. Normalize at the domain boundary so local tests and Postgres
    # production behave identically.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def belongs_to_open_conversation(last_message_at: datetime, received_at: datetime, timeout_minutes: int) -> bool:
    """Exactly 30 inactive minutes starts a new conversation."""
    return utc_aware(received_at) < utc_aware(last_message_at) + timedelta(minutes=timeout_minutes)
