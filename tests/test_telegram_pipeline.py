from __future__ import annotations

import sqlite3
import tempfile
import sys
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence
from unittest.mock import Mock, patch
from urllib.error import URLError

# Support both ``python tests/test_telegram_pipeline.py`` and unittest discovery
# without requiring an editable install of the src-layout package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from academix.telegram.access import AccessDecision, TelegramAccessChecker
from academix.telegram.contracts import SaveReport, TelegramMessageV1
from academix.telegram.dispatch import dispatch_pending_updates
from academix.telegram.inbox import RawTelegramUpdate, SqliteUpdateInbox
from academix.telegram.normalize import normalize_update
from academix.telegram.receiver import (
    TelegramApiError,
    TelegramBotApi,
    TelegramLongPollingReceiver,
)


def group_message(**overrides: Any) -> dict[str, Any]:
    message = {
        "message_id": 42,
        "date": 1792051200,
        "chat": {"id": -100123, "type": "supergroup", "title": "Study group"},
        "from": {"id": 1234, "first_name": "Irina", "last_name": "Ivanova"},
        "text": "Assignment posted",
    }
    message.update(overrides)
    return message


def raw_update(update_id: int = 7, message: dict[str, Any] | None = None) -> RawTelegramUpdate:
    return RawTelegramUpdate(
        update_id=update_id,
        kind="message",
        payload={"update_id": update_id, "message": message or group_message()},
        received_at_utc="2026-10-16T10:00:00Z",
    )


class TelegramContractTests(unittest.TestCase):
    def test_message_serializes_all_contract_fields_and_normalizes_utc(self) -> None:
        message = TelegramMessageV1(
            chat_id=-100123,
            chat_title="Study group",
            message_id=42,
            date="2026-10-16T10:00:00+00:00",
            author_id="1234",
            author_name="Irina Ivanova",
            reply_to_message_id=None,
            text="Hello",
            is_pinned=False,
            edit_date=None,
            attachment_name=None,
        )

        self.assertEqual(message.date, "2026-10-16T10:00:00Z")
        self.assertEqual(
            set(message.to_record()),
            {
                "chat_id",
                "chat_title",
                "message_id",
                "date",
                "author_id",
                "author_name",
                "reply_to_message_id",
                "text",
                "is_pinned",
                "edit_date",
                "attachment_name",
            },
        )

    def test_message_rejects_naive_and_non_utc_timestamps(self) -> None:
        for timestamp in ("2026-10-16T10:00:00", "2026-10-16T13:00:00+03:00"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ValueError):
                    TelegramMessageV1(
                        chat_id=1,
                        chat_title="Study group",
                        message_id=1,
                        date=timestamp,
                        author_id=None,
                        author_name=None,
                        reply_to_message_id=None,
                        text="",
                        is_pinned=False,
                        edit_date=None,
                        attachment_name=None,
                    )


class TelegramNormalizeTests(unittest.TestCase):
    def test_normalizes_text_author_reply_and_timestamp(self) -> None:
        message = group_message(reply_to_message={"message_id": 40})

        record = normalize_update({"message": message})

        self.assertIsNotNone(record)
        self.assertEqual(record.chat_id, -100123)
        self.assertEqual(record.message_id, 42)
        self.assertEqual(record.author_id, "1234")
        self.assertEqual(record.author_name, "Irina Ivanova")
        self.assertEqual(record.reply_to_message_id, 40)
        self.assertEqual(record.text, "Assignment posted")
        self.assertTrue(record.date.endswith("Z"))

    def test_uses_caption_and_supported_attachment_name(self) -> None:
        message = group_message(
            text=None,
            caption="Read this file",
            document={"file_name": "lecture.pdf"},
        )

        record = normalize_update({"message": message})

        self.assertEqual(record.text, "Read this file")
        self.assertEqual(record.attachment_name, "lecture.pdf")

    def test_handles_anonymous_sender_chat_without_fake_user_id(self) -> None:
        message = group_message(
            **{
                "from": {"id": 108796882, "first_name": "Group", "is_bot": True},
                "sender_chat": {"id": -100999, "title": "Course Admins"},
            }
        )

        record = normalize_update({"message": message})

        self.assertIsNone(record.author_id)
        self.assertEqual(record.author_name, "Course Admins")

    def test_ignores_private_chat(self) -> None:
        message = group_message(chat={"id": 1234, "type": "private"})

        self.assertIsNone(normalize_update({"message": message}))


class SqliteInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "updates.sqlite3"
        self.inbox = SqliteUpdateInbox(self.database_path)
        self.inbox.open()

    def tearDown(self) -> None:
        self.inbox.close()
        self.temp_dir.cleanup()

    def test_poll_persists_raw_update_and_offset(self) -> None:
        self.inbox.store_poll(
            [raw_update()],
            next_offset=8,
            succeeded_at_utc="2026-10-16T10:00:00Z",
        )

        self.assertEqual(self.inbox.get_state().next_offset, 8)
        pending = self.inbox.pending_updates()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].payload["message"]["message_id"], 42)

    def test_duplicate_poll_does_not_create_duplicate_update(self) -> None:
        first = raw_update()
        duplicate = raw_update(message=group_message(text="changed duplicate"))
        self.inbox.store_poll(
            [first], next_offset=8, succeeded_at_utc="2026-10-16T10:00:00Z"
        )
        self.inbox.store_poll(
            [duplicate], next_offset=8, succeeded_at_utc="2026-10-16T10:01:00Z"
        )

        pending = self.inbox.pending_updates()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].payload["message"]["text"], "Assignment posted")

    def test_source_catalog_tracks_membership_removal(self) -> None:
        joined = RawTelegramUpdate(
            update_id=7,
            kind="my_chat_member",
            payload={
                "my_chat_member": {
                    "chat": {"id": -100123, "type": "supergroup", "title": "Study group"},
                    "new_chat_member": {"status": "member"},
                }
            },
            received_at_utc="2026-10-16T10:00:00Z",
        )
        removed = RawTelegramUpdate(
            update_id=8,
            kind="my_chat_member",
            payload={
                "my_chat_member": {
                    "chat": {"id": -100123, "type": "supergroup", "title": "Study group"},
                    "new_chat_member": {"status": "left"},
                }
            },
            received_at_utc="2026-10-16T11:00:00Z",
        )
        self.inbox.store_poll(
            [joined, removed], next_offset=9, succeeded_at_utc="2026-10-16T11:00:00Z"
        )

        self.assertIsNone(self.inbox.active_source(-100123))
        self.assertFalse(self.inbox.sources()[0].active)


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.inbox = SqliteUpdateInbox(Path(self.temp_dir.name) / "updates.sqlite3")
        self.inbox.open()
        self.inbox.store_poll(
            [raw_update()], next_offset=8, succeeded_at_utc="2026-10-16T10:00:00Z"
        )

    def tearDown(self) -> None:
        self.inbox.close()
        self.temp_dir.cleanup()

    def test_dispatch_sends_normalized_batch_then_marks_updates_processed(self) -> None:
        class Store:
            received: Sequence[Mapping[str, Any]] = ()

            def save_messages(self, messages: Sequence[Mapping[str, Any]]) -> SaveReport:
                self.received = list(messages)
                return SaveReport(inserted=1, updated=0, skipped=0)

        store = Store()
        report = dispatch_pending_updates(self.inbox, store)

        self.assertEqual(report.received, 1)
        self.assertEqual(report.normalized, 1)
        self.assertEqual(report.saved.inserted, 1)
        self.assertEqual(store.received[0]["chat_id"], -100123)
        self.assertEqual(store.received[0]["author_name"], "Irina Ivanova")
        self.assertEqual(self.inbox.pending_updates(), [])

    def test_db_exception_leaves_update_pending_for_retry(self) -> None:
        class FailingStore:
            def save_messages(self, messages: Sequence[Mapping[str, Any]]) -> SaveReport:
                raise RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            dispatch_pending_updates(self.inbox, FailingStore())

        self.assertEqual(len(self.inbox.pending_updates()), 1)

    def test_private_update_is_not_saved_in_buffer(self) -> None:
        private = raw_update(8, group_message(chat={"id": 1234, "type": "private"}))
        self.inbox.store_poll([private], next_offset=9, succeeded_at_utc=private.received_at_utc)
        self.assertEqual([update.update_id for update in self.inbox.pending_updates()], [7])
        self.assertEqual(self.inbox.get_state().next_offset, 9)
        store = Mock()
        store.save_messages.return_value = SaveReport(1, 0, 0)

        report = dispatch_pending_updates(self.inbox, store)

        self.assertEqual(report.received, 1)
        self.assertEqual(self.inbox.pending_updates(), [])


class AccessTests(unittest.TestCase):
    class FakeBot:
        member: dict[str, Any] = {"status": "member"}
        error = False

        def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
            if self.error:
                raise TelegramApiError("API unavailable")
            return self.member

    def test_member_and_restricted_member_are_allowed(self) -> None:
        bot = self.FakeBot()
        checker = TelegramAccessChecker(bot)

        for member in (
            {"status": "creator"},
            {"status": "administrator"},
            {"status": "member"},
            {"status": "restricted", "is_member": True},
        ):
            with self.subTest(member=member):
                bot.member = member
                self.assertTrue(checker.check(-100123, 1234).allowed)

    def test_non_member_and_api_error_are_denied(self) -> None:
        bot = self.FakeBot()
        checker = TelegramAccessChecker(bot)
        bot.member = {"status": "left"}
        self.assertEqual(
            checker.check(-100123, 1234),
            AccessDecision(False, "membership_not_confirmed"),
        )
        bot.error = True
        self.assertEqual(
            checker.check(-100123, 1234),
            AccessDecision(False, "membership_check_failed"),
        )


class ReceiverTests(unittest.TestCase):
    def test_persists_batch_before_advancing_offset_for_next_poll(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox = SqliteUpdateInbox(Path(temp_dir) / "updates.sqlite3")
            inbox.open()

            class FakeBot:
                offsets: list[int] = []

                def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
                    self.offsets.append(offset)
                    if len(self.offsets) <= 2:
                        return [{"update_id": 7, "message": group_message()}]
                    raise KeyboardInterrupt

            bot = FakeBot()
            save_poll = inbox.store_poll
            failures = [sqlite3.OperationalError("buffer unavailable")]

            def store_poll(*args, **kwargs):
                if failures:
                    raise failures.pop()
                return save_poll(*args, **kwargs)

            try:
                with patch.object(inbox, "store_poll", side_effect=store_poll), \
                        patch("academix.telegram.receiver.time.sleep"), \
                        self.assertLogs("academix.telegram.receiver", level="ERROR"), \
                        self.assertRaises(KeyboardInterrupt):
                    TelegramLongPollingReceiver(bot, inbox, polling_timeout=1).run()

                self.assertEqual(bot.offsets, [0, 0, 8])
                self.assertEqual(inbox.get_state().next_offset, 8)
                self.assertEqual(len(inbox.pending_updates()), 1)
            finally:
                inbox.close()

    def test_api_error_does_not_expose_token(self) -> None:
        api = TelegramBotApi("secret-test-token")

        with patch("urllib.request.urlopen", side_effect=URLError("connection failed")):
            with self.assertRaises(TelegramApiError) as error:
                api.get_updates(offset=0, timeout=1)

        self.assertNotIn("secret-test-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()
