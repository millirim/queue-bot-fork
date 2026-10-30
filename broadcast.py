"""Рассылка старосты или админа всей группе — с форматированием оригинала.

Два источника:
- **из бота** — староста пишет сообщение (или присылает фото, видео, файл, альбом): бот не пересказывает текст,
  а копирует сообщение целиком (`copy_message` / `copy_messages`), поэтому сохраняются жирный, курсив, подчёркивание,
  зачёркивание, моноширинный, спойлеры, ссылки, цитаты, картинки и альбомы. Подпись «📢 Сообщение (…)» ставится в начало
  текста или подписи, а если там нет места (у стикера, кружка, альбома, длинного текста) — отдельным сообщением перед ним;
- **из веб-панели** — HTML из редактора (`clean_html` оставляет только то, что понимает Telegram) и до 10 картинок.

Черновик (`Draft`) хранится в состоянии FSM словарём, поэтому в нём только простые типы.
"""
import asyncio
import html
import logging
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message

from common import esc

log = logging.getLogger(__name__)

TEXT_LIMIT = 4096     # символов в сообщении Telegram (без разметки)
CAPTION_LIMIT = 1024  # символов в подписи к фото, видео, файлу
MAX_PHOTOS = 10       # картинок в одном альбоме
ALBUM_WAIT = 1.5      # секунд ждать остальные части альбома, прежде чем показать предпросмотр
CAPTIONED = ("photo", "video", "document", "animation", "audio", "voice")


def header(signature: str) -> str:
    return f"📢 <b>Сообщение ({esc(signature)})</b>"


@dataclass
class Draft:
    """Что разослать. kind: text — текст (html), copy — одно сообщение из чата старосты, album — несколько,
    web — текст из веб-панели и картинки (photos — байты при первой отправке, потом file_id)."""
    kind: str
    html: str = ""
    plain: str = ""             # без разметки — для журнала и подсчёта длины
    chat_id: int = 0            # откуда копировать
    ids: list[int] = field(default_factory=list)
    media: str = ""             # тип одного сообщения: photo, video, sticker…
    photos: list = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["photos"] = []  # байты картинок в FSM не кладём (веб отправляет сразу)
        return data


def from_message(msg: Message) -> Draft:
    """Черновик из одного сообщения старосты в боте."""
    plain = msg.text or msg.caption or ""
    if msg.text is not None:
        return Draft("text", html=msg.html_text, plain=plain, chat_id=msg.chat.id, ids=[msg.message_id])
    media = next((kind for kind in (*CAPTIONED, "sticker", "video_note", "location", "venue", "contact", "poll", "dice")
                  if getattr(msg, kind, None)), "other")
    return Draft("copy", html=msg.html_text if msg.caption else "", plain=plain, chat_id=msg.chat.id,
                 ids=[msg.message_id], media=media)


def album(chat_id: int, ids: list[int], caption: str = "") -> Draft:
    return Draft("album", plain=caption, chat_id=chat_id, ids=sorted(ids), media="album")


def describe(draft: Draft) -> str:
    """Коротко для журнала: начало текста и что приложено."""
    what = {"album": f"альбом ({len(draft.ids)})", "photo": "фото", "video": "видео", "document": "файл",
            "animation": "гифка", "audio": "аудио", "voice": "голосовое", "sticker": "стикер", "video_note": "кружок"}
    extra = what.get(draft.media, "вложение" if draft.kind == "copy" else "")
    if draft.kind == "web" and draft.photos:
        extra = f"картинок: {len(draft.photos)}"
    text = " ".join(draft.plain.split())[:80]
    return " · ".join(x for x in (text, extra) if x) or "без текста"


async def _call(make):
    """Запрос к Telegram с повтором после «подожди». None — не дошло (заблокировал бота, удалил чат…)."""
    for _ in range(3):
        try:
            return await make()
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return None
        except TelegramAPIError as e:
            log.warning("Рассылка: не доставлено: %s", e)
            return None
    return None


async def deliver(bot: Bot, chat_id: int, signature: str, draft: Draft) -> bool:
    """Одному человеку. True — дошло."""
    top = header(signature)
    top_len = len(html.unescape(re.sub(r"<[^>]+>", "", top))) + 2
    if draft.kind in ("text", "web") and not draft.photos:
        if len(draft.plain) + top_len <= TEXT_LIMIT:
            return await _call(lambda: bot.send_message(chat_id, f"{top}\n\n{draft.html}")) is not None
        if await _call(lambda: bot.send_message(chat_id, top)) is None:
            return False
        if draft.kind == "web":
            return await _call(lambda: bot.send_message(chat_id, draft.html)) is not None
        return await _call(lambda: bot.copy_message(chat_id, draft.chat_id, draft.ids[0])) is not None
    if draft.kind == "web":
        return await _deliver_photos(bot, chat_id, top, top_len, draft)
    if draft.kind == "copy" and draft.media in CAPTIONED and len(draft.plain) + top_len <= CAPTION_LIMIT:
        caption = f"{top}\n\n{draft.html}" if draft.html else top
        return await _call(lambda: bot.copy_message(chat_id, draft.chat_id, draft.ids[0], caption=caption)) is not None
    # Подпись не помещается или её не бывает (стикер, кружок, альбом): подпись — отдельно, оригинал — как есть.
    if await _call(lambda: bot.send_message(chat_id, top)) is None:
        return False
    if draft.kind == "album":
        return await _call(lambda: bot.copy_messages(chat_id, draft.chat_id, draft.ids)) is not None
    return await _call(lambda: bot.copy_message(chat_id, draft.chat_id, draft.ids[0])) is not None


def _photo(item, i: int):
    """Первый раз — файл, дальше — file_id, который вернул Telegram (картинка не загружается заново)."""
    return item if isinstance(item, str) else BufferedInputFile(item, filename=f"photo{i + 1}.jpg")


async def _deliver_photos(bot: Bot, chat_id: int, top: str, top_len: int, draft: Draft) -> bool:
    fits = len(draft.plain) + top_len <= CAPTION_LIMIT
    caption = (f"{top}\n\n{draft.html}" if draft.plain else top) if fits else None
    if not fits:  # длинный текст — сначала он, потом картинки без подписи
        text = f"{top}\n\n{draft.html}" if len(draft.plain) + top_len <= TEXT_LIMIT else top
        if await _call(lambda: bot.send_message(chat_id, text)) is None:
            return False
        if text == top and draft.plain:
            await _call(lambda: bot.send_message(chat_id, draft.html))
    if len(draft.photos) == 1:
        sent = await _call(lambda: bot.send_photo(chat_id, _photo(draft.photos[0], 0), caption=caption))
        if sent is not None:
            draft.photos[0] = sent.photo[-1].file_id
        return sent is not None
    media = [InputMediaPhoto(media=_photo(p, i), caption=caption if i == 0 else None) for i, p in enumerate(draft.photos)]
    sent = await _call(lambda: bot.send_media_group(chat_id, media))
    if sent:
        draft.photos[:] = [m.photo[-1].file_id for m in sent]
    return bool(sent)


async def deliver_all(bot: Bot, chat_ids: list[int], signature: str, draft: Draft) -> int:
    """Всем по очереди, с паузой (лимит Telegram ~30 сообщений в секунду). Возвращает, скольким дошло."""
    sent = 0
    for chat_id in chat_ids:
        sent += await deliver(bot, chat_id, signature, draft)
        await asyncio.sleep(0.05)
    return sent


# ================= HTML из веб-редактора =================
# Что понимает Telegram (parse_mode=HTML). Всё остальное выкидывается, текст остаётся.
INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u", "ins": "u", "s": "s", "strike": "s", "del": "s",
          "code": "code", "tg-spoiler": "tg-spoiler"}
BLOCK = {"pre": "pre", "blockquote": "blockquote"}
LINK_SCHEMES = ("http://", "https://", "tg://", "mailto:")
NEWLINE_AFTER = {"div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.plain: list[str] = []
        self.stack: list[str | None] = []  # что открыто: тег Telegram или None (тег выкинут)

    @property
    def in_code(self) -> bool:
        return any(t in ("code", "pre") for t in self.stack)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "br":
            self.handle_data("\n")
            return
        if tag == "span" and "tg-spoiler" in (attrs.get("class") or "").split():
            tag = "tg-spoiler"
        name = INLINE.get(tag) or BLOCK.get(tag)
        if tag == "a":
            href = (attrs.get("href") or "").strip()
            name = "a" if href.lower().startswith(LINK_SCHEMES) else None
        if name and (self.in_code or name in self.stack):  # внутри кода разметки нет; одно и то же дважды не вкладываем
            name = None
        if name and name in BLOCK.values() and self.plain and not "".join(self.plain).endswith("\n"):
            self.handle_data("\n")
        self.stack.append(name)
        if name == "a":
            self.out.append(f'<a href="{html.escape(href, quote=True)}">')
        elif name:
            self.out.append(f"<{name}>")

    def handle_endtag(self, tag):
        if tag in NEWLINE_AFTER and self.plain and not "".join(self.plain).endswith("\n"):
            self.handle_data("\n")
        if tag == "br" or not self.stack:
            return
        name = self.stack.pop()
        if name:
            self.out.append(f"</{name}>")

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))
        self.plain.append(data)


def clean_html(raw: str) -> tuple[str, str]:
    """(html для Telegram, тот же текст без разметки). Лишние пустые строки по краям убираются."""
    parser = _Cleaner()
    parser.feed(raw or "")
    parser.close()
    while parser.stack:
        if name := parser.stack.pop():
            parser.out.append(f"</{name}>")
    out = re.sub(r"\n{3,}", "\n\n", "".join(parser.out)).strip("\n")
    plain = re.sub(r"\n{3,}", "\n\n", "".join(parser.plain)).strip()
    return out.strip(), plain
