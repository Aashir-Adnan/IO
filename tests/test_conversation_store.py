from tests.conftest import requires_db
from io_assistant.conversation.store import ConversationStore


@requires_db
def test_conversation_lifecycle(db):
    store = ConversationStore(lambda: db)
    cid = store.ensure_active()
    assert store.active_id() == cid

    store.append(cid, "user", "what work do I have today?")
    store.append(cid, "assistant", "Two tasks are open.", kind="answer", intent="query")
    store.append(cid, "user", "and Sana?")

    turns = store.recent_turns(cid, n=6)
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "what work do I have today?"

    hist = store.history(cid)
    assert hist[0]["text"] == "and Sana?"  # newest first
    assert len(hist) == 3

    convs = store.list_conversations()
    assert convs[0]["id"] == cid
    assert convs[0]["title"] == "what work do I have today?"
    assert convs[0]["message_count"] == 3
