import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID админов через запятую. Админ может всё; старост назначает админ в боте.
# Если список пустой, заявки на регистрацию принимаются автоматически.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Путь к SQLite (относительно папки бота или абсолютный).
DB_PATH = os.getenv("DB_PATH", "data/queue.db")

# Часовой пояс для времени в журнале.
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Minsk"))

# Начальный список предметов — записывается в базу при первом запуске, дальше
# предметы меняются в админке (/admin → Предметы). Число — сколько всего работ.
SUBJECTS: dict[str, int] = {
    "ПнаЯВУ": 8,
    "БЖЧ — лабы": 7,
    "БЖЧ — практики": 6,
    "БД": 6,
    "ЭП": 99,
}
