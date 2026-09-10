from io_assistant.models_domain import normalize_kind


def test_normalize_kind_slugifies():
    assert normalize_kind("Gym Session") == "gym_session"
    assert normalize_kind("  ") == "note"


def test_normalize_kind_aliases_todo_and_reminder_to_task():
    for raw in ("todo", "to-do", "to do", "reminder", "Reminders", "TASK_REMINDER"):
        assert normalize_kind(raw) == "task"
    assert normalize_kind("chores") == "chore"
    assert normalize_kind("watchlist") == "watchlist"  # unknown slug untouched
