from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

START = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

CHATS = {
    -1001000000001: ("Линейная алгебра 2026", "Ирина Сергеевна"),
    -1001000000002: ("Матан — организационный", "Пётр Алексеевич"),
    -1001000000003: ("Дискретка, 2 курс", "Олег Николаевич"),
}
STUDENTS = ["Аня", "Борис", "Вика", "Глеб", "Даша"]

ANNOUNCEMENTS = [
    "ДЗ {n} выложено в LMS. Сдать до {due} 23:59, формат — PDF.",
    "Напоминаю: дедлайн по ДЗ {n} — {due}, 23:59. За каждый день опоздания −1 балл.",
    "Контрольная по темам 1–{n} будет {due} на семинаре. Калькуляторы можно.",
    "Семинар {due} переносится с 14:40 на 18:10, аудитория та же.",
    "Коллоквиум {due}. Список вопросов — в закрепе, 20 вопросов, готовьтесь.",
]
QUESTIONS = [
    "А до скольки сдавать?",
    "Можно в группах по двое?",
    "Где потом смотреть оценки?",
    "Это задание обязательное?",
    "Это по новой программе или по старой?",
]
ANSWERS = [
    "До 23:59, как и написано выше.",
    "Да, можно, подпишите обоих.",
    "В LMS, раздел «Оценки», через неделю после дедлайна.",
    "Да, все задания обязательные.",
    "По новой, старые условия больше не действуют.",
]


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_chat(chat_id: int, title: str, teacher: str, rng: random.Random) -> list[dict[str, Any]]:
    """Один чат: серия объявлений преподавателя, под каждым — вопросы студентов и ответы."""
    messages: list[dict[str, Any]] = []
    teacher_id = str(1000 + abs(chat_id) % 100)

    def add(author_id: str, author_name: str, text: str, moment: datetime, **extra: Any) -> dict[str, Any]:
        message: dict[str, Any] = {
            "chat_id": chat_id, "chat_title": title, "message_id": len(messages) + 1,
            "date": _iso(moment), "author_id": author_id, "author_name": author_name,
            "reply_to_message_id": None, "text": text, "is_pinned": False,
            "edit_date": None, "attachment_name": None, **extra,
        }
        messages.append(message)
        return message

    moment = START + timedelta(days=rng.randint(0, 3))
    for n, template in enumerate(ANNOUNCEMENTS, start=1):
        due = (moment + timedelta(days=rng.randint(5, 10))).strftime("%d.%m")
        announcement = add(
            teacher_id, teacher, template.format(n=n, due=due), moment,
            is_pinned=(n == 1), attachment_name=f"hw{n}.pdf" if template.startswith("ДЗ") else None,
        )
        for _ in range(rng.randint(1, 3)):
            moment += timedelta(minutes=rng.randint(3, 180))
            idx = rng.randrange(len(QUESTIONS))
            student = rng.choice(STUDENTS)
            question = add(str(2000 + STUDENTS.index(student)), student, QUESTIONS[idx], moment,
                           reply_to_message_id=announcement["message_id"])
            moment += timedelta(minutes=rng.randint(5, 240))
            add(teacher_id, teacher, ANSWERS[idx], moment, reply_to_message_id=question["message_id"])
        moment += timedelta(days=rng.randint(4, 8))

    messages[0]["text"] += " UPD: срок продлён на два дня."
    messages[0]["edit_date"] = _iso(moment)
    return messages


def generate(seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [m for chat_id, (title, teacher) in CHATS.items() for m in make_chat(chat_id, title, teacher, rng)]
