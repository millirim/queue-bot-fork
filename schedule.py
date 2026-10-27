"""Расписание групп БГУИР: загрузка из API или xlsx и развёртка в конкретные занятия."""
import asyncio
import glob
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

import aiohttp

import config

log = logging.getLogger(__name__)

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass
class Lesson:
    """Строка расписания: повторяется по неделям цикла 1–4."""
    weekday: int                  # 0 = понедельник
    start: str                    # "08:30"
    end: str
    subject: str
    ltype: str                    # ЛК / ЛР / ПЗ
    subgroup: int                 # 0 — вся группа
    weeks: list[int]
    date_from: str | None = None  # ISO-даты, None — без ограничения
    date_to: str | None = None
    room: str = ""


@dataclass
class Occurrence:
    """Конкретное занятие в конкретный день."""
    group: str
    subject: str
    ltype: str
    subgroup: int
    starts_at: datetime           # локальное время без tzinfo
    ends_at: datetime
    room: str


@dataclass
class GroupSchedule:
    group: str
    semester_start: date
    semester_end: date
    lessons: list[Lesson]
    source: str

    def week_number(self, d: date) -> int:
        """Учебная неделя 1–4; неделя с 1 сентября — первая."""
        monday = self.semester_start - timedelta(days=self.semester_start.weekday())
        return (d - monday).days // 7 % 4 + 1

    def occurrences(self, since: date, until: date) -> list[Occurrence]:
        result = []
        d = max(since, self.semester_start)
        last = min(until, self.semester_end)
        while d <= last:
            week = self.week_number(d)
            for l in self.lessons:
                if l.weekday != d.weekday() or week not in l.weeks:
                    continue
                if l.date_from and d < date.fromisoformat(l.date_from):
                    continue
                if l.date_to and d > date.fromisoformat(l.date_to):
                    continue
                result.append(Occurrence(
                    group=self.group,
                    subject=l.subject,
                    ltype=l.ltype,
                    subgroup=l.subgroup,
                    starts_at=datetime.combine(d, _parse_time(l.start)),
                    ends_at=datetime.combine(d, _parse_time(l.end)),
                    room=l.room,
                ))
            d += timedelta(days=1)
        result.sort(key=lambda o: (o.starts_at, o.subject, o.subgroup))
        return result

    def to_json(self) -> dict:
        return {
            "group": self.group,
            "semester_start": self.semester_start.isoformat(),
            "semester_end": self.semester_end.isoformat(),
            "lessons": [asdict(l) for l in self.lessons],
        }

    @classmethod
    def from_json(cls, data: dict, source: str) -> "GroupSchedule":
        return cls(
            group=data["group"],
            semester_start=date.fromisoformat(data["semester_start"]),
            semester_end=date.fromisoformat(data["semester_end"]),
            lessons=[Lesson(**l) for l in data["lessons"]],
            source=source,
        )


def _parse_time(s: str):
    return datetime.strptime(s, "%H:%M").time()


def _ddmmyyyy(s: str | None) -> str | None:
    if not s:
        return None
    return datetime.strptime(s, "%d.%m.%Y").date().isoformat()


# ================= API БГУИР =================
def parse_api(data: dict, group: str) -> GroupSchedule:
    lessons = []
    for day_name, items in (data.get("schedules") or {}).items():
        if day_name not in WEEKDAYS:
            continue
        for it in items:
            if it.get("dateLesson"):  # разовое занятие на конкретную дату
                one = _ddmmyyyy(it["dateLesson"])
                date_from = date_to = one
                weeks = [1, 2, 3, 4]
            else:
                date_from = _ddmmyyyy(it.get("startLessonDate"))
                date_to = _ddmmyyyy(it.get("endLessonDate"))
                weeks = it.get("weekNumber") or []
            lessons.append(Lesson(
                weekday=WEEKDAYS.index(day_name),
                start=it["startLessonTime"],
                end=it["endLessonTime"],
                subject=it["subject"] or it.get("subjectFullName") or "?",
                ltype=it.get("lessonTypeAbbrev") or "",
                subgroup=int(it.get("numSubgroup") or 0),
                weeks=weeks,
                date_from=date_from,
                date_to=date_to,
                room=", ".join(it.get("auditories") or []),
            ))
    return GroupSchedule(
        group=group,
        semester_start=datetime.strptime(data["startDate"], "%d.%m.%Y").date(),
        semester_end=datetime.strptime(data["endDate"], "%d.%m.%Y").date(),
        lessons=lessons,
        source="api",
    )


async def fetch_api(group: str) -> GroupSchedule | None:
    """None — такой группы нет. Исключение — API недоступен."""
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(config.SCHEDULE_API, params={"studentGroup": group}) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            data = await resp.json()
    return parse_api(data, group)


# ================= xlsx (выгрузка с iis.bsuir.by) =================
LINE_RE = re.compile(r"^(\d)\)\s*(?:(\d)п\.\s*)?(.+?)\s*\(([А-ЯЁа-яё]+)\)\s*(.*)$")
ROOM_RE = re.compile(r"(\S+\s+к\.)")
FROM_RE = re.compile(r"\bс\s+(\d{1,2})\.(\d{1,2})\b")
TO_RE = re.compile(r"\bпо\s+(\d{1,2})\.(\d{1,2})\b")


def _semester_date(day: int, month: int) -> str:
    year = config.SEMESTER_START.year
    if month < config.SEMESTER_START.month:
        year += 1
    return date(year, month, day).isoformat()


def parse_xlsx(path: str) -> GroupSchedule:
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    title = str(rows[0][0] or "") if rows else ""
    m = re.search(r"\d{6}", title)
    group = m.group(0) if m else os.path.splitext(os.path.basename(path))[0]

    header = next(i for i, r in enumerate(rows) if "Понедельник" in [str(c).strip() for c in r if c])
    day_cols = {
        col: WEEKDAYS.index(str(name).strip())
        for col, name in enumerate(rows[header])
        if name and str(name).strip() in WEEKDAYS
    }

    # Каждая пара занимает 4 строки: в первой время начала, в третьей — конца,
    # строки внутри — недели 1–4 (номер недели ещё и в префиксе «N)»).
    grouped: dict[tuple, set[int]] = {}
    r = header + 1
    while r + 2 < len(rows) and rows[r][0]:
        start, end = str(rows[r][0]).strip(), str(rows[r + 2][0] or "").strip()
        for rr in range(r, min(r + 4, len(rows))):
            for col, wd in day_cols.items():
                cell = rows[rr][col] if col < len(rows[rr]) else None
                for line in str(cell or "").splitlines():
                    lm = LINE_RE.match(line.strip())
                    if not lm:
                        continue
                    week, sub, subject, ltype, rest = lm.groups()
                    room = ROOM_RE.search(rest)
                    fm, tm = FROM_RE.search(rest), TO_RE.search(rest)
                    key = (
                        wd, start, end, subject.strip(), ltype, int(sub or 0),
                        _semester_date(int(fm[1]), int(fm[2])) if fm else None,
                        _semester_date(int(tm[1]), int(tm[2])) if tm else None,
                        room.group(1) if room else "",
                    )
                    grouped.setdefault(key, set()).add(int(week))
        r += 4

    lessons = [
        Lesson(weekday=k[0], start=k[1], end=k[2], subject=k[3], ltype=k[4], subgroup=k[5],
               weeks=sorted(w), date_from=k[6], date_to=k[7], room=k[8])
        for k, w in grouped.items()
    ]
    return GroupSchedule(group, config.SEMESTER_START, config.SEMESTER_END, lessons, "xlsx")


def load_xlsx_schedules(folder: str) -> dict[str, GroupSchedule]:
    result = {}
    for path in glob.glob(os.path.join(folder, "*.xlsx")):
        try:
            s = parse_xlsx(path)
            result[s.group] = s
            log.info("Расписание группы %s из %s: %d строк", s.group, path, len(s.lessons))
        except Exception:
            log.exception("Не удалось разобрать %s", path)
    return result


# ================= хранилище =================
class ScheduleStore:
    def __init__(self):
        self._mem: dict[str, tuple[float, GroupSchedule]] = {}
        self._xlsx = load_xlsx_schedules(config.SCHEDULE_DIR)
        self._lock = asyncio.Lock()
        os.makedirs(config.SCHEDULE_CACHE_DIR, exist_ok=True)

    def _cache_path(self, group: str) -> str:
        return os.path.join(config.SCHEDULE_CACHE_DIR, f"{group}.json")

    def _load_cache(self, group: str) -> GroupSchedule | None:
        try:
            with open(self._cache_path(group), encoding="utf-8") as f:
                return GroupSchedule.from_json(json.load(f), "cache")
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def get(self, group: str) -> GroupSchedule | None:
        """Расписание группы или None, если группа не найдена нигде."""
        async with self._lock:
            cached = self._mem.get(group)
            if cached and time.monotonic() - cached[0] < config.SCHEDULE_REFRESH_HOURS * 3600:
                return cached[1]

            schedule = None
            try:
                schedule = await fetch_api(group)
                if schedule is None and group not in self._xlsx:
                    return None
                if schedule is not None:
                    with open(self._cache_path(group), "w", encoding="utf-8") as f:
                        json.dump(schedule.to_json(), f, ensure_ascii=False)
            except Exception as e:
                log.warning("API расписания недоступен для %s: %s", group, e)
                if cached:  # оставляем то, что уже было в памяти, и попробуем позже
                    self._mem[group] = (time.monotonic(), cached[1])
                    return cached[1]
                schedule = self._load_cache(group)

            schedule = schedule or self._xlsx.get(group)
            if schedule is not None:
                self._mem[group] = (time.monotonic(), schedule)
            return schedule


# ================= что где сдают =================
@dataclass
class Work:
    """Тип работ по предмету: сколько номеров и на каком занятии (ЛР/ПЗ) сдаётся."""
    id: int
    subject: str
    kind: str                     # ключ из config.KIND_TITLES
    count: int
    ltype: str


# Заполняется из базы (Database.reload_works); меняется в админке без перезапуска.
WORKS: list[Work] = []


def set_works(items: list[Work]) -> None:
    WORKS[:] = items


def kinds_for(subject: str, ltype: str) -> list[str]:
    return [w.kind for w in WORKS if w.subject == subject and w.ltype == ltype]


def work_count(subject: str, kind: str) -> int:
    """Сколько номеров у типа работ; 0 — такого типа у предмета нет."""
    return next((w.count for w in WORKS if w.subject == subject and w.kind == kind), 0)


def is_queue_lesson(o) -> bool:
    """Занятие, на котором что-то сдают (есть в списке предметов)."""
    return bool(kinds_for(o.subject, o.ltype))
