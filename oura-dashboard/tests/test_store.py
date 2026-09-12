"""History store: upserts, ordering, and surviving a corrupt file."""

from oura_dashboard.store import History


def test_merge_reports_new_documents():
    history = History()
    changes = history.merge({"daily_sleep": [{"id": "a", "score": 70}]})
    assert changes == {"daily_sleep": 1}
    assert history.total_documents == 1


def test_merge_is_idempotent():
    history = History()
    payload = {"daily_sleep": [{"id": "a", "score": 70}]}
    history.merge(payload)
    assert history.merge(payload) == {}
    assert history.total_documents == 1


def test_merge_updates_a_changed_document():
    """Oura revises a day's score after later syncs; the newer one must win."""
    history = History()
    history.merge({"daily_sleep": [{"id": "a", "score": 70}]})
    changes = history.merge({"daily_sleep": [{"id": "a", "score": 81}]})
    assert changes == {"daily_sleep": 1}
    assert history.documents("daily_sleep") == [{"id": "a", "score": 81}]


def test_documents_are_sorted_by_day():
    history = History()
    history.merge({"daily_sleep": [
        {"id": "c", "day": "2026-09-03"},
        {"id": "a", "day": "2026-09-01"},
        {"id": "b", "day": "2026-09-02"},
    ]})
    assert [d["id"] for d in history.documents("daily_sleep")] == ["a", "b", "c"]


def test_documents_without_an_id_fall_back_to_a_key():
    history = History()
    history.merge({"ring_battery_level": [{"timestamp": "2026-09-11T00:00:00Z"}]})
    assert history.total_documents == 1


def test_singleton_returns_the_latest():
    history = History()
    history.merge({"personal_info": [{"id": "me", "day": "2026-09-01"},
                                     {"id": "me2", "day": "2026-09-09"}]})
    assert history.singleton("personal_info")["id"] == "me2"


def test_round_trip_through_disk(tmp_path):
    path = tmp_path / "history.json"
    history = History()
    history.merge({"daily_sleep": [{"id": "a", "day": "2026-09-01", "score": 70}]})
    history.save(path)

    reloaded = History.load(path)
    assert reloaded.documents("daily_sleep")[0]["score"] == 70
    assert reloaded.updated_at is not None


def test_corrupt_file_starts_fresh_instead_of_crashing(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json at all")
    assert History.load(path).total_documents == 0


def test_missing_file_starts_empty(tmp_path):
    assert History.load(tmp_path / "nope.json").total_documents == 0


def test_save_is_atomic_leaving_no_temp_file(tmp_path):
    path = tmp_path / "history.json"
    History().save(path)
    assert path.is_file()
    assert not list(tmp_path.glob("*.tmp"))
