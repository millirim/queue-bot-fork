import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID создателей через запятую (раньше — «главные админы», переменная ADMIN_IDS по-прежнему читается).
# Создатель может всё, как админ, и его нельзя снять из бота; админов и старост назначают в боте.
# Если список пустой, заявки на регистрацию принимаются автоматически.
CREATOR_IDS = {int(x) for name in ("CREATOR_IDS", "ADMIN_IDS") for x in os.getenv(name, "").replace(" ", "").split(",") if x}

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

# Веб-панель (web.py). WEB_PORT=0 — выключена. По умолчанию слушает только этот компьютер (127.0.0.1):
# наружу её выпускают через обратный прокси или туннель с HTTPS, адрес для ссылок из бота — WEB_URL.
WEB_PORT = int(os.getenv("WEB_PORT", "8080") or 0)
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_URL = (os.getenv("WEB_URL", "").strip() or f"http://{WEB_HOST}:{WEB_PORT}").rstrip("/")
# Кому можно входить: admin, starosta, user через запятую. По умолчанию — всем, кто есть в списке группы.
WEB_ROLES = {r for r in os.getenv("WEB_ROLES", "admin,starosta,user").replace(" ", "").split(",") if r} & {"admin", "starosta", "user"}

# Игры (games/) работают отдельной службой: веб-панель проксирует к ней WebSocket. GAMES_PORT=0 — игры выключены.
# GAMES_SECRET (общий с службой игр) создаёт deploy/common.sh в /etc/queue-bot/games.env.
GAMES_PORT = int(os.getenv("GAMES_PORT", "8081") or 0)
GAMES_SECRET = os.getenv("GAMES_SECRET", "")
