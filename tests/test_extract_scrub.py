from io_assistant.extract.scrub import scrub_roles
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedRecord)


def test_drops_role_noun_person_top_level_and_in_record():
    r = ExtractionResult(
        people=[ExtractedPerson(name="dentist", confidence=0.8),
                ExtractedPerson(name="Nafay", confidence=0.9)],
        records=[ExtractedRecord(kind="task", title="call the dentist",
                                 people=["dentist", "Nafay"], confidence=0.9)],
    )
    out = scrub_roles(r)
    assert [p.name for p in out.people] == ["Nafay"]
    assert out.records[0].people == ["Nafay"]


def test_keeps_named_people_and_leaves_untouched_when_clean():
    r = ExtractionResult(
        people=[ExtractedPerson(name="Sana", confidence=0.9)],
        records=[ExtractedRecord(kind="event", title="lunch", people=["Sana"],
                                 confidence=0.9)],
    )
    out = scrub_roles(r)
    assert [p.name for p in out.people] == ["Sana"]


def test_handles_the_my_prefixes():
    r = ExtractionResult(
        people=[ExtractedPerson(name="my boss", confidence=0.7)],
        records=[ExtractedRecord(kind="task", title="email the boss",
                                 assigned_by="my boss", people=["my boss"],
                                 confidence=0.8)],
    )
    out = scrub_roles(r)
    assert out.people == []
    assert out.records[0].people == []
    assert out.records[0].assigned_by is None
