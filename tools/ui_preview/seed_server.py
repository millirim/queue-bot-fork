"""Стенд для разработки интерфейса: веб-панель на вымышленных данных (14 человек, прогресс, предложения). Запуск:
    python tools/ui_preview/seed_server.py <папка> [секунд]
В <папке> появятся токены входа (ta.txt, tb.txt, tc.txt, td.txt, te.txt), shots.txt и файлы для tools/ui_preview/shots.js.
Панель слушает 127.0.0.1:8099. Настоящих людей и токенов здесь нет. Проверка игр с настоящей службой — tests/test_games_integration.py."""
import asyncio
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("BOT_TOKEN", "123:TEST")

import config  # noqa: E402

config.CREATOR_IDS = {1}
config.WEB_PORT, config.WEB_ROLES = 8099, {"admin", "starosta", "user"}
config.WEB_URL, config.GROUP_NO, config.GAMES_PORT = "http://127.0.0.1:8099", "123456", 0

import metrics  # noqa: E402
import web  # noqa: E402
from db import Database  # noqa: E402
from harness import Harness  # noqa: E402

NAMES = ["Андреев Артём Николаевич", "Беляев Степан Олегович", "Буров Матвей Алексеевич", "Тихонов Глеб Андреевич", "Хромов Тарас Максимович",
         "Орлова Дарья Игоревна", "Смирнова Алина Сергеевна", "Козлов Никита Олегович", "Фёдоров Кирилл Андреевич", "Лебедева Полина Дмитриевна",
         "Волков Егор Павлович", "Зайцева Ксения Романовна", "Морозов Илья Степанович", "Никитина Вера Алексеевна"]
# chat_id -> кто: 1 создатель (Андреев), 2 админ (Беляев), 6 староста (Орлова), 8 обычный студент (Козлов)
LINKED = {NAMES[0]: 1, NAMES[1]: 2, NAMES[2]: 3, NAMES[5]: 6, NAMES[6]: 7, NAMES[7]: 8, NAMES[9]: 10, NAMES[10]: 11}


async def main(out: Path, seconds: int) -> None:
    db = Database(tempfile.mkdtemp() + "/q.db")
    await db.connect()
    await db.add_students(NAMES)
    ids = {s.name: s.id for s in await db.students()}
    rnd = random.Random(5)
    for name, chat in LINKED.items():
        await db.link(chat, f"u{chat}", ids[name])
    await db.set_role(ids[NAMES[1]], "admin")
    await db.set_role(ids[NAMES[5]], "starosta")
    for i, name in enumerate(NAMES):
        await db.set_subgroup(ids[name], 1 + i % 2)
    subjects = await db.subjects()
    for subject in subjects:
        for name in NAMES:
            for _ in range(rnd.randint(0, min(4, subject.total))):
                await db.change_done(ids[name], subject.id, 1)
        for name in rnd.sample(NAMES, 4):
            await db.set_want(ids[name], subject.id, True)
    await db.add_suggestion(ids[NAMES[6]], "Добавить в очередь отметку «сдаю онлайн»", True)
    await db.add_suggestion(None, "Сделать тёмную тему по умолчанию", True)
    await db.add_suggestion(ids[NAMES[7]], "Уведомлять, когда до тебя осталось три человека", True)
    poll = await db.create_poll("Где сдаём в пятницу?", ["Ауд. 101", "Ауд. 205", "Онлайн"], "админ Беляев Степан")
    out.mkdir(parents=True, exist_ok=True)
    (out / "shots.txt").write_text(f"{ids[NAMES[7]]} {subjects[0].id}")
    for name, chat in (("ta", 1), ("tb", 1), ("tc", 1), ("td", 8), ("te", 8), ("tf", 6), ("tg", 2)):
        (out / f"{name}.txt").write_text(await db.web_token(chat, "login", 3000))
    metrics.install_log_feed()
    asyncio.create_task(metrics.collector(db))
    await web.start(db, Harness().bot)
    print(f"Панель: http://127.0.0.1:8099  (poll #{poll}); токены входа лежат в {out}: ta/tb/tc — создатель, tf — староста, tg — админ, td/te — студент", flush=True)
    await asyncio.sleep(seconds)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 600))
