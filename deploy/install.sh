#!/usr/bin/env bash
# Установка бота на Debian (12/13) как службы systemd.
# Запуск из склонированного репозитория:  sudo bash deploy/install.sh
# Повторный запуск безопасен: настройки и база не трогаются.
set -euo pipefail

APP_DIR=/opt/queue-bot
APP_USER=queuebot
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_NAME=queue-bot   # ключ ~/.ssh/queue-bot — нужен, только если репозиторий приватный

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
as_bot() { runuser -u "$APP_USER" -- "$@"; }

[[ $EUID -eq 0 ]] || die "Запусти через sudo: sudo bash deploy/install.sh"

say "Ставлю пакеты (python3, venv, git, curl)"
apt-get update -q
apt-get install -y -q python3 python3-venv git curl ca-certificates
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "Нужен Python 3.11 или новее"

say "Проверяю доступ в интернет"
curl -sS -m 15 -o /dev/null https://api.telegram.org || die "Нет доступа к api.telegram.org — бот не сможет работать"
curl -sS -m 15 -o /dev/null https://iis.bsuir.by \
    || echo "⚠️  Нет доступа к iis.bsuir.by — расписание будет браться из сохранённой копии/xlsx"

say "Создаю пользователя $APP_USER (без root-прав и без входа в систему)"
id -u "$APP_USER" &>/dev/null \
    || useradd --system --no-create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

if [[ "$SRC_DIR" != "$APP_DIR" ]]; then
    if [[ -d "$APP_DIR/.git" ]]; then
        echo "$APP_DIR уже есть — оставляю как есть (для обновления: sudo bash $APP_DIR/deploy/update.sh)"
    else
        # Простое копирование: git от root отказывается работать с папкой другого пользователя.
        say "Копирую бота в $APP_DIR"
        install -d "$APP_DIR"
        cp -a "$SRC_DIR/." "$APP_DIR/"
        rm -rf "$APP_DIR/.venv"  # пути внутри venv привязаны к старой папке — создадим заново
    fi
fi

# Если репозиторий приватный: копия ключа того, кто запускает установку (для обновлений).
KEY_SRC="$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)/.ssh/$KEY_NAME"
if [[ -f "$KEY_SRC" && ! -f "$APP_DIR/.ssh/id_ed25519" ]]; then
    say "Настраиваю ключ доступа к GitHub для обновлений"
    install -d -m 700 "$APP_DIR/.ssh"
    install -m 600 "$KEY_SRC" "$APP_DIR/.ssh/id_ed25519"
fi

install -d "$APP_DIR/data" "$APP_DIR/backups"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
if [[ -f "$APP_DIR/.ssh/id_ed25519" ]]; then
    as_bot git -C "$APP_DIR" config core.sshCommand \
        "ssh -i $APP_DIR/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$APP_DIR/.ssh/known_hosts"
fi

say "Ставлю зависимости в отдельное окружение (.venv)"
[[ -x "$APP_DIR/.venv/bin/python" ]] || as_bot python3 -m venv "$APP_DIR/.venv"
as_bot "$APP_DIR/.venv/bin/pip" install -q --no-cache-dir --upgrade pip
as_bot "$APP_DIR/.venv/bin/pip" install -q --no-cache-dir -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
    say "Настройки бота"
    while true; do
        read -rsp "Токен бота от @BotFather (ввод скрыт): " token; echo
        if me=$(curl -sS -m 15 "https://api.telegram.org/bot${token}/getMe") && [[ $me == *'"ok":true'* ]]; then
            echo "✓ Бот: @$(sed -E 's/.*"username":"([^"]+)".*/\1/' <<<"$me")"
            break
        fi
        echo "✗ Telegram не принял токен, попробуй ещё раз"
    done
    while true; do
        read -rp "Твой Telegram ID (узнать у @userinfobot; несколько — через запятую): " admins
        [[ $admins =~ ^[0-9]+(,[0-9]+)*$ ]] && break
        echo "✗ Нужны только цифры, например 123456789"
    done
    umask 077
    cat > "$APP_DIR/.env" <<EOF
BOT_TOKEN=$token
ADMIN_IDS=$admins
DB_PATH=data/queue.db
TIMEZONE=Europe/Minsk
EOF
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
else
    echo "Файл $APP_DIR/.env уже есть — оставляю"
fi

say "Ставлю службы systemd"
install -m 644 "$APP_DIR"/deploy/queue-bot.service "$APP_DIR"/deploy/queue-bot-backup.service \
    "$APP_DIR"/deploy/queue-bot-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q queue-bot.service queue-bot-backup.timer
systemctl restart queue-bot.service
systemctl start queue-bot-backup.timer

sleep 5
if systemctl is-active -q queue-bot.service; then
    say "Готово, бот работает ✓"
    journalctl -u queue-bot -n 5 --no-pager
    cat <<EOF

Полезные команды:
  journalctl -u queue-bot -f           — логи в реальном времени (выход: Ctrl+C)
  systemctl status queue-bot           — состояние
  sudo systemctl restart queue-bot     — перезапуск
  sudo bash $APP_DIR/deploy/update.sh  — обновить бота из GitHub
  sudo nano $APP_DIR/.env              — настройки (после правки — перезапуск)
EOF
else
    journalctl -u queue-bot -n 30 --no-pager
    die "Бот не запустился — смотри лог выше"
fi
