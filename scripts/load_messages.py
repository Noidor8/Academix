from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from academix.db.storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузить JSON с сообщениями в базу Academix")
    parser.add_argument("file", type=Path, help="JSON-файл со списком сообщений")
    parser.add_argument("--db", default=None, help="путь к базе (по умолчанию data/academix.db)")
    args = parser.parse_args()

    data = json.loads(args.file.read_text(encoding="utf-8"))
    messages = data["messages"] if isinstance(data, dict) else data
    print(Storage(args.db).save_messages(messages))


if __name__ == "__main__":
    main()
