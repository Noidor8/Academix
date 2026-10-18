from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import academix.db as db
from academix.db.storage import Storage
from load_messages import main as load_json_main
from tests.fake_data import generate




def make_message(**overrides: Any) -> dict[str, Any]:
    """Одно сообщение в формате контракта; любое поле можно переопределить."""
    message = {
        "chat_id": -1001, "chat_title": "Линал", "message_id": 1,
        "date": "2026-10-14T13:45:00Z", "author_id": "42", "author_name": "Ирина Сергеевна",
        "reply_to_message_id": None, "text": "ДЗ 3 до пятницы", "is_pinned": 0,
        "edit_date": None, "attachment_name": None,
    }
    return {**message, **overrides}

def raw_row(storage: Storage, message_id: int = 1) -> sqlite3.Row:
    """Служебные колонки (raw_json, inserted_at) наружу не отдаются — читаем их напрямую."""
    with storage._connect() as conn:
        return conn.execute("SELECT * FROM messages WHERE message_id = ?", [message_id]).fetchone()

@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test.db")


def test_init_db_creates_file_and_is_idempotent(storage: Storage) -> None:
    storage.init_db()
    assert storage.path.exists()
    assert storage.list_chats() == []


def test_round_trip_returns_the_same_dict(storage: Storage) -> None:
    message = make_message()
    assert storage.save_messages([message]).inserted == 1
    assert storage.get_messages() == [message]


def test_duplicate_is_updated_not_stored_twice(storage: Storage) -> None:
    storage.save_messages([make_message()])
    report = storage.save_messages([make_message()])
    assert (report.inserted, report.updated) == (0, 1)
    assert len(storage.get_messages()) == 1


def test_edit_replaces_text_and_edit_date(storage: Storage) -> None:
    storage.save_messages([make_message()])
    storage.save_messages([make_message(text="ДЗ 3 до субботы", edit_date="2026-10-15T09:00:00Z")])
    (stored,) = storage.get_messages()
    assert (stored["text"], stored["edit_date"]) == ("ДЗ 3 до субботы", "2026-10-15T09:00:00Z")


@pytest.mark.parametrize("bad_key", [None, "abc", "", 1.5])
def test_message_with_bad_key_is_skipped_but_rest_is_saved(storage: Storage, bad_key: Any) -> None:
    report = storage.save_messages([make_message(message_id=bad_key), make_message(message_id=2)])
    assert (report.skipped, report.inserted) == (1, 1)


def test_missing_optional_fields_become_empty(storage: Storage) -> None:
    storage.save_messages([{"chat_id": -1001, "message_id": 7, "date": "не дата"}])
    (stored,) = storage.get_messages()
    assert (stored["text"], stored["date"], stored["is_pinned"]) == (None, None, 0)


def test_unix_and_iso_dates_are_stored_the_same_way(storage: Storage) -> None:
    moment = datetime(2026, 10, 24, 10, 45, tzinfo=timezone.utc)
    storage.save_messages([
        make_message(message_id=1, date=int(moment.timestamp())),
        make_message(message_id=2, date=str(int(moment.timestamp()))),
        make_message(message_id=3, date="2026-10-24T13:45:00+03:00"),
        make_message(message_id=4, date="2026-10-24T10:45:00"),
        make_message(message_id=5, date=moment),
    ])
    assert {m["date"] for m in storage.get_messages()} == {"2026-10-24T10:45:00Z"}


def test_filters_and_newest_first_ordering(storage: Storage) -> None:
    storage.save_messages([
        make_message(message_id=1, date="2026-10-01T10:00:00Z", author_id="42"),
        make_message(message_id=2, date="2026-10-05T10:00:00Z", author_id="7"),
        make_message(message_id=3, date="2026-10-09T10:00:00Z", chat_id=-2002),
    ])
    ids = lambda **filters: [m["message_id"] for m in storage.get_messages(**filters)]
    assert ids() == [3, 2, 1]
    assert ids(chat_id=-1001) == [2, 1]
    assert ids(since="2026-10-04", until="2026-10-06") == [2]
    assert ids(since=datetime(2026, 10, 4, tzinfo=timezone.utc)) == [3, 2]
    assert ids(chat_id=-1001, author_id="42") == [1]
    assert ids(author_id=7) == [2]
    assert ids(limit=1) == [3]
    assert ids(limit=None) == [3, 2, 1]


def test_list_chats_counts_messages_per_chat(storage: Storage) -> None:
    storage.save_messages([
        make_message(message_id=1), make_message(message_id=2),
        make_message(message_id=1, chat_id=-2002, chat_title="Матан"),
    ])
    chats = {c["chat_id"]: c for c in storage.list_chats()}
    assert (chats[-1001]["n_messages"], chats[-1001]["chat_title"]) == (2, "Линал")
    assert chats[-2002]["n_messages"] == 1


def test_fake_data_loads_without_errors(storage: Storage) -> None:
    messages = generate()
    report = storage.save_messages(messages)
    assert (report.inserted, report.skipped) == (len(messages), 0)
    assert len(storage.list_chats()) == 3


def test_module_functions_use_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACADEMIX_DB", str(tmp_path / "env.db"))
    db.save_messages([make_message()])
    assert len(db.get_messages()) == 1
    assert len(db.list_chats()) == 1
    assert (tmp_path / "env.db").exists()


def test_init_db_creates_missing_parent_dirs(tmp_path: Path) -> None:
    deep = Storage(tmp_path / "a" / "b" / "c.db")
    assert deep.path.exists()


def test_skipped_messages_are_returned_for_inspection(storage: Storage) -> None:
    bad = make_message(message_id=None)
    report = storage.save_messages([bad, make_message(message_id=2)])
    assert report.skipped_messages == [bad]
    assert report.skipped == len(report.skipped_messages)
    assert "skipped_messages" not in repr(report)


def test_empty_batch_is_a_noop(storage: Storage) -> None:
    report = storage.save_messages([])
    assert (report.inserted, report.updated, report.skipped) == (0, 0, 0)
    assert storage.get_messages() == []


def test_update_keeps_original_inserted_at(storage: Storage) -> None:
    storage.save_messages([make_message()])
    first = raw_row(storage)["inserted_at"]
    storage.save_messages([make_message(text="правка")])
    assert raw_row(storage)["inserted_at"] == first


def test_same_message_id_in_different_chats_are_different_messages(storage: Storage) -> None:
    storage.save_messages([make_message(chat_id=-1001), make_message(chat_id=-2002)])
    assert len(storage.get_messages()) == 2


def test_missing_key_field_is_skipped(storage: Storage) -> None:
    message = make_message()
    del message["chat_id"]
    assert storage.save_messages([message]).skipped == 1


def test_string_keys_from_json_export_are_accepted(storage: Storage) -> None:
    storage.save_messages([make_message(chat_id="-1001", message_id="7")])
    (stored,) = storage.get_messages()
    assert (stored["chat_id"], stored["message_id"]) == (-1001, 7)


def test_extra_fields_are_not_returned_but_kept_in_raw_json(storage: Storage) -> None:
    storage.save_messages([make_message(views=150, forwarded_from="Деканат")])
    (stored,) = storage.get_messages()
    assert "views" not in stored
    raw = json.loads(raw_row(storage)["raw_json"])
    assert (raw["views"], raw["forwarded_from"]) == (150, "Деканат")


def test_raw_json_survives_update(storage: Storage) -> None:
    storage.save_messages([make_message(text="первая версия")])
    storage.save_messages([make_message(text="вторая версия")])
    assert json.loads(raw_row(storage)["raw_json"])["text"] == "вторая версия"


@pytest.mark.parametrize("value, expected", [(True, 1), (False, 0), (1, 1), (0, 0), (None, 0), ("да", 1)])
def test_is_pinned_is_normalized_to_0_or_1(storage: Storage, value: Any, expected: int) -> None:
    storage.save_messages([make_message(is_pinned=value)])
    assert storage.get_messages()[0]["is_pinned"] == expected


def test_author_id_is_stored_as_string(storage: Storage) -> None:
    storage.save_messages([make_message(author_id=42)])
    assert storage.get_messages()[0]["author_id"] == "42"


def test_sql_injection_in_values_is_stored_as_plain_text(storage: Storage) -> None:
    evil = "'); DROP TABLE messages; --"
    storage.save_messages([make_message(text=evil, chat_title='x" OR 1=1 --')])
    assert storage.get_messages()[0]["text"] == evil
    assert storage.get_messages(author_id="' OR 1=1 --") == []


def test_unparseable_date_is_logged_and_stored_as_none(storage: Storage, caplog: pytest.LogCaptureFixture) -> None:
    storage.save_messages([make_message(date="вчера", edit_date="позавчера")])
    (stored,) = storage.get_messages()
    assert (stored["date"], stored["edit_date"]) == (None, None)
    assert "Непонятная дата" in caplog.text


def test_messages_with_empty_date_do_not_break_ordering(storage: Storage) -> None:
    storage.save_messages([make_message(message_id=1, date=None), make_message(message_id=2)])
    assert [m["message_id"] for m in storage.get_messages()] == [2, 1]


def test_filters_with_no_match_return_empty_list(storage: Storage) -> None:
    storage.save_messages([make_message()])
    assert storage.get_messages(chat_id=-9999) == []
    assert storage.get_messages(since="2030-01-01") == []


def test_same_second_messages_are_ordered_by_message_id(storage: Storage) -> None:
    storage.save_messages([make_message(message_id=i) for i in (3, 1, 2)])
    assert [m["message_id"] for m in storage.get_messages()] == [3, 2, 1]


def test_list_chats_dates_and_order(storage: Storage) -> None:
    storage.save_messages([
        make_message(chat_id=-1, message_id=1, date="2026-09-01T10:00:00Z"),
        make_message(chat_id=-1, message_id=2, date="2026-09-20T10:00:00Z"),
        make_message(chat_id=-2, message_id=1, date="2026-10-01T10:00:00Z"),
    ])
    first, second = storage.list_chats()
    assert first["chat_id"] == -2
    assert (second["first_date"], second["last_date"]) == ("2026-09-01T10:00:00Z", "2026-09-20T10:00:00Z")


def test_failed_batch_leaves_database_unchanged(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """Если посреди пачки упало, в базе не остаётся половины: транзакция откатывается."""
    monkeypatch.setattr("academix.db.storage.UPDATE_SQL", "THIS IS NOT SQL")
    with pytest.raises(sqlite3.Error):
        storage.save_messages([make_message(message_id=1), make_message(message_id=1)])
    assert storage.get_messages() == []


def test_two_storage_objects_share_one_file(tmp_path: Path) -> None:
    writer, reader = Storage(tmp_path / "shared.db"), Storage(tmp_path / "shared.db")
    writer.save_messages([make_message()])
    assert len(reader.get_messages()) == 1


def test_public_api_is_exactly_the_contract() -> None:
    assert set(db.__all__) == {"SaveReport", "save_messages", "get_messages", "list_chats"}


def test_fake_data_is_deterministic_and_valid() -> None:
    first, second = generate(), generate()
    assert first == second
    assert len(first) > 50
    assert all(set(m) == set(make_message()) for m in first)
    assert any(m["is_pinned"] for m in first) and any(m["edit_date"] for m in first)


@pytest.mark.parametrize("wrap", [False, True])
def test_load_json_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wrap: bool) -> None:
    """Загрузчик принимает и голый список, и объект {"messages": [...]}."""
    messages = [make_message(message_id=i) for i in (1, 2, 3)]
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"messages": messages} if wrap else messages, ensure_ascii=False), encoding="utf-8")
    db_path = tmp_path / "cli.db"
    monkeypatch.setattr("sys.argv", ["load_json", str(src), "--db", str(db_path)])
    load_json_main()
    assert "inserted=3" in capsys.readouterr().out
    assert len(Storage(db_path).get_messages()) == 3


def test_retried_old_version_does_not_overwrite_newer_edit(storage: Storage) -> None:
    """Повтор старой пачки из буфера Р. не должен вернуть старый текст поверх правки."""
    original = make_message(text="ДЗ до пятницы")
    first_edit = make_message(text="ДЗ до понедельника", edit_date="2026-10-15T09:00:00Z")
    second_edit = make_message(text="ДЗ до вторника", edit_date="2026-10-15T10:00:00Z")
    storage.save_messages([second_edit])
    report = storage.save_messages([original, first_edit])
    assert report.updated == 0
    assert storage.get_messages()[0]["text"] == "ДЗ до вторника"