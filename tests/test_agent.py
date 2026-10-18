"""Проверки агента без настоящих запросов к модели и API-ключей."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from academix_agent import AgentError, Message, OpenRouterClient, SummaryRequest, Summarizer


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = SummaryRequest(
            "-1001", "2026-10-14T00:00:00Z", "2026-10-15T00:00:00Z",
            "Выдели домашние задания",
        )
        self.messages = [
            Message("101", "2026-10-14T10:00:00Z", "Преподаватель", "ДЗ: задачи 1–5."),
            Message("102", "2026-10-14T10:05:00Z", "Преподаватель", "Сдать до пятницы."),
        ]
        self.response = {
            "overview": "Обсудили домашнее задание.",
            "homework": [{
                "title": "Домашняя работа",
                "description": "Решить задачи 1–5",
                "deadline": "до пятницы",
                "source_message_ids": ["101", "102"],
            }],
            "deadlines": [], "key_points": [], "uncertainties": [],
        }
        self.client = Mock()
        self.client.complete.return_value = json.dumps(self.response, ensure_ascii=False)
        self.agent = Summarizer(self.client)

    def test_summary_preserves_contract_and_sends_sorted_context(self) -> None:
        result = self.agent.summarize(self.request, list(reversed(self.messages)))

        self.assertEqual(result.to_dict(), self.response)
        self.assertEqual(json.loads(result.to_json()), self.response)
        self.client.complete.assert_called_once()
        context = json.loads(self.client.complete.call_args.kwargs["user_prompt"])
        self.assertEqual(context["chat_id"], self.request.chat_id)
        self.assertEqual(context["student_request"], self.request.user_request)
        self.assertEqual(context["period"], {
            "start": self.request.period_start, "end": self.request.period_end,
        })
        self.assertEqual([m["id"] for m in context["messages"]], ["101", "102"])
        self.assertEqual(context["messages"][0]["text"], self.messages[0].text)

    def test_empty_selection_skips_model_and_returns_empty_sections(self) -> None:
        result = self.agent.summarize(self.request, []).to_dict()

        self.assertTrue(result["overview"])
        for section in ("homework", "deadlines", "key_points", "uncertainties"):
            self.assertEqual(result[section], [])
        self.client.complete.assert_not_called()

    def test_invalid_json_reports_error_without_exposing_response(self) -> None:
        self.client.complete.return_value = '{"overview": "private model text",}'

        with self.assertRaisesRegex(AgentError, "LLM returned invalid JSON") as caught:
            self.agent.summarize(self.request, self.messages)

        self.assertNotIn("private model text", str(caught.exception))

    def test_invented_source_message_is_rejected(self) -> None:
        self.response["homework"][0]["source_message_ids"] = ["999"]
        self.client.complete.return_value = json.dumps(self.response)

        with self.assertRaisesRegex(AgentError, "unknown message IDs"):
            self.agent.summarize(self.request, self.messages)

    def test_period_includes_start_and_excludes_end(self) -> None:
        at_start = Message("101", self.request.period_start, "Автор", "Задание")
        # В этом ответе нужна только ссылка на единственное переданное сообщение.
        self.response["homework"][0]["source_message_ids"] = ["101"]
        self.client.complete.return_value = json.dumps(self.response)
        self.agent.summarize(self.request, [at_start])
        self.client.complete.assert_called_once()
        self.client.reset_mock()

        for timestamp in ("2026-10-13T23:59:59Z", self.request.period_end):
            with self.subTest(timestamp=timestamp):
                message = Message("101", timestamp, "Автор", "Задание")
                with self.assertRaisesRegex(AgentError, "outside the requested period"):
                    self.agent.summarize(self.request, [message])
        self.client.complete.assert_not_called()

    def test_connection_failure_becomes_agent_error(self) -> None:
        client = OpenRouterClient("test-key", "test-model")
        with patch("academix_agent.agent.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(AgentError, "connection failed or timed out"):
                client.complete(system_prompt="Инструкции", user_prompt="Сообщения")


if __name__ == "__main__":
    unittest.main()
