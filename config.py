import os
from datetime import date
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID админов через запятую. Админ может всё; старост назначает админ в боте.
# Если список пустой, заявки на регистрацию принимаются автоматически.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Путь к SQLite (относительно папки бота или абсолютный).
DB_PATH = os.getenv("DB_PATH", "data/queue.db")

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Minsk"))

# --- расписание ---
# Основной источник — API БГУИР (подходит для любой группы). Если API недоступен,
# берётся последняя сохранённая копия, а затем файл schedules/<группа>.xlsx.
SCHEDULE_API = os.getenv("SCHEDULE_API", "https://iis.bsuir.by/api/v1/schedule")
SCHEDULE_DIR = os.getenv("SCHEDULE_DIR", "schedules")
SCHEDULE_CACHE_DIR = os.path.join(os.path.dirname(DB_PATH) or ".", "schedule_cache")
# Как часто перечитывать расписание из API.
SCHEDULE_REFRESH_HOURS = 6


def _default_semester() -> tuple[date, date]:
    """Осенний семестр текущего учебного года: с 1 сентября по 31 декабря."""
    today = date.today()
    year = today.year if today.month >= 7 else today.year - 1
    return date(year, 9, 1), date(year, 12, 31)


# Границы семестра нужны только для xlsx-файлов (в API они есть): от начала семестра
# считается номер учебной недели (1–4). Для весеннего семестра задай их в переменных.
_start, _end = _default_semester()
SEMESTER_START = date.fromisoformat(os.getenv("SEMESTER_START") or _start.isoformat())
SEMESTER_END = date.fromisoformat(os.getenv("SEMESTER_END") or _end.isoformat())

# --- правила очереди ---
# Запись на занятие открывается за столько часов до его начала.
UNLOCK_BEFORE_HOURS = int(os.getenv("UNLOCK_BEFORE_HOURS", "24"))
# За сколько минут до открытия записи предупреждать.
UNLOCK_WARN_MINUTES = int(os.getenv("UNLOCK_WARN_MINUTES", "30"))
# За сколько минут до начала пары очередь перемешивается случайно.
SHUFFLE_BEFORE_MINUTES = int(os.getenv("SHUFFLE_BEFORE_MINUTES", "60"))
# На сколько дней вперёд искать ближайшее занятие (цикл БГУИР — 4 недели).
LOOKAHEAD_DAYS = 28

# Типы работ. Ключ (lab/prac/course) используется в кнопках и не меняется.
KIND_TITLES = {
    "lab": "Лабораторная",
    "prac": "Практическая",
    "course": "Курсач",
}

# Типы занятий, на которых можно что-то сдавать (их предлагает админка).
QUEUE_LESSON_TYPES = ("ЛР", "ПЗ")

# Начальный список предметов — записывается в базу при первом запуске, дальше
# предметы меняются в админке (/admin → Предметы). Название — как в расписании БГУИР.
# Число — сколько всего номеров в этом типе работ; KIND_LESSON — на каком занятии сдаётся.
KIND_LESSON = {
    "lab": "ЛР",
    "prac": "ПЗ",
}

SUBJECTS: dict[str, dict[str, int]] = {
    "ПнаЯВУ": {"lab": 8},
    "БЖЧ": {"lab": 7, "prac": 6},
    "БД": {"lab": 6},
    "ЭП": {"lab": 99},
}

# Если номеров не больше этого значения, они показываются кнопками, иначе вводятся текстом.
MAX_NUMBER_BUTTONS = 12

# Как часто планировщик проверяет открытие записи и перемешивание (секунды).
TICK_SECONDS = 30
