#!/usr/bin/env bash
# Обновление бота из GitHub:  sudo bash /opt/queue-bot/deploy/update.sh
# Перед обновлением делает бэкап базы; если бот после обновления не запустился — откатывает код.
set -euo pipefail

APP_DIR=/opt/queue-bot
APP_USER=queuebot

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
as_bot() { runuser -u "$APP_USER" -- "$@"; }

[[ $EUID -eq 0 ]] || die "Запусти через sudo: sudo bash $APP_DIR/deploy/update.sh"
cd "$APP_DIR"

say "Проверяю обновления"
as_bot git fetch -q origin
old=$(as_bot git rev-parse HEAD)
new=$(as_bot git rev-parse '@{u}')
if [[ $old == "$new" ]]; then
    echo "Обновлений нет, версия $(as_bot git log -1 --format='%h от %cd' --date=format:'%d.%m.%Y')"
    exit 0
fi
echo "Что нового:"
as_bot git log --format='  • %s' "$old..$new"

say "Бэкап базы"
as_bot bash deploy/backup.sh

say "Обновляю код и зависимости"
as_bot git merge -q --ff-only "$new"
as_bot .venv/bin/pip install -q --no-cache-dir -r requirements.txt
install -m 644 deploy/queue-bot.service deploy/queue-bot-backup.service deploy/queue-bot-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart queue-bot.service

sleep 5
if systemctl is-active -q queue-bot.service; then
    say "Готово, бот обновлён и работает ✓"
else
    journalctl -u queue-bot -n 30 --no-pager
    say "Бот не запустился — откатываю на прошлую версию"
    as_bot git reset -q --hard "$old"
    as_bot .venv/bin/pip install -q --no-cache-dir -r requirements.txt
    systemctl restart queue-bot.service
    die "Обновление отменено, работает прошлая версия. Пришли лог выше разработчику."
fi
