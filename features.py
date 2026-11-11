"""Дополнительные функции (не очередь), которые админ может включать и выключать для каждой роли отдельно.

Реестр здесь, настройки — таблица feature_flags (db.py). Нет строки — берётся значение по умолчанию отсюда.
Создатель видит всё всегда (чтобы нельзя было потерять доступ к настройкам). Новая функция = запись в FEATURES
и проверка `common.feature_allowed` в боте и `web.need_feature` в вебе (проверять нужно на сервере, не только прятать кнопки).
Очередь (смотреть, 🙋, «Сдал», −1) отключить нельзя: это не «дополнение».
"""
from dataclasses import dataclass

import config

ROLES = ("user", "starosta", "admin")
ROLE_TITLES = {"user": "Студенты", "starosta": "Старосты", "admin": "Админы"}


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    hint: str
    roles: tuple[str, ...] = ROLES  # у каких ролей включено по умолчанию

    def default(self, role: str) -> bool:
        """Значение, пока админ ничего не менял. Для веб-панели — из WEB_ROLES в настройках сервера."""
        return role in config.WEB_ROLES if self.key == "web" else role in self.roles


FEATURES: dict[str, Feature] = {f.key: f for f in (
    Feature("web", "🌐 Веб-панель", "Вход в панель из бота: команда /web и кнопка «Панель». Создатель входит всегда."),
    Feature("swap", "🔁 Обмен местами", "Двое меняются местами в очереди, если оба согласны."),
    Feature("polls", "🗳 Голосования", "Опросы группы. У кого выключено, тем опросы не приходят."),
    Feature("presence", "🟢 Кто онлайн", "Зелёная точка у тех, кто сейчас в панели, и когда человек был в сети.", roles=("starosta", "admin")),
    Feature("games", "🎮 Игры", "Весь раздел «Игры» в панели. Выключено — игр нет совсем."),
    Feature("game_2048", "🧩 2048", "Для одного, с рекордами группы."),
    Feature("game_snake", "🐍 Змейка", "Для одного, с рекордами группы."),
    Feature("game_checkers", "⚪ Шашки", "Русские шашки на двоих."),
    Feature("game_chess", "♟ Шахматы", "На двоих, можно с часами."),
    Feature("game_blackjack", "🃏 «21»", "Против крупье, на игровые фишки."),
    Feature("game_poker", "♠ Покер", "Холдем на игровые фишки, до шести человек."),
    Feature("suggestions", "💡 Идеи", "Написать, что улучшить, и поддержать чужие идеи."),
)}


# Включена ли веб-панель ролям — копия строк feature_flags для "web" (db.connect и db.set_feature держат её свежей).
# Нужна, потому что вход проверяется и в синхронном коде (кнопка меню Telegram); нет строки — берётся WEB_ROLES.
WEB_OVERRIDE: dict[str, bool] = {}


GAME_KINDS = ("2048", "snake", "checkers", "chess", "blackjack", "poker")  # ключи игр; у каждой своя функция game_<ключ>
