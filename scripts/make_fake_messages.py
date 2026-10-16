from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from academix.db.fake_data import CHATS, generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Сгенерировать выдуманные сообщения учебных чатов")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / ".local" / "fake_messages.json")
    args = parser.parse_args()

    messages = generate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(messages)} сообщений из {len(CHATS)} чатов → {args.out}")


if __name__ == "__main__":
    main()
