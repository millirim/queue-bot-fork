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

# Номер группы — только для названия файла с копией базы (bd-513802-28-10-2026-1250.zip).
GROUP_NO = os.getenv("GROUP_NO", "513802").strip() or "group"

# Часовой пояс для времени в журнале.
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Minsk"))

# Начальный список предметов — записывается в базу при первом запуске, дальше
# предметы меняются в панели админа (Предметы). Название → (сколько всего работ, эмодзи).
SUBJECTS: dict[str, tuple[int, str]] = {
    "ПнаЯВУ": (8, "🔥"),
    "БЖЧ-ПЗ": (6, "🏞"),
    "БЖЧ-ЛР": (7, "🌄"),
    "ЭП": (99, "📱"),
    "БД": (6, "💅"),
}

# Разовое переименование предметов, заведённых прежними версиями (выполняется один раз на базу).
LEGACY_SUBJECT_NAMES = {"БЖЧ — лабы": "БЖЧ-ЛР", "БЖЧ — практики": "БЖЧ-ПЗ"}
