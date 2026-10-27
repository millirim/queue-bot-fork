# Общее для install.sh и команды queue-bot. Подключается через source.
CODE=/opt/queue-bot              # код — можно стереть и скачать заново
CONF_DIR=/etc/queue-bot          # настройки (токен, админы) — вводятся один раз
CONF="$CONF_DIR/env"
DATA=/var/lib/queue-bot          # база и бэкапы — переживают обновления
APP_USER=queuebot
UNITS=(queue-bot.service queue-bot-backup.service queue-bot-backup.timer)

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
need_root() { [[ $EUID -eq 0 ]] || die "Нужно через sudo: sudo $*"; }

version() { git -C "$CODE" log -1 --format='%h от %cd' --date=format:'%d.%m.%Y %H:%M'; }

# Зависимости, службы systemd и команда queue-bot — по текущему коду в $CODE.
apply_code() {
    [[ -x "$CODE/.venv/bin/python" ]] || python3 -m venv "$CODE/.venv"
    "$CODE/.venv/bin/pip" install -q --no-cache-dir --disable-pip-version-check -r "$CODE/requirements.txt"
    for unit in "${UNITS[@]}"; do
        install -m 644 "$CODE/deploy/$unit" /etc/systemd/system/
    done
    ln -sfn "$CODE/deploy/queue-bot" /usr/local/bin/queue-bot
    chmod +x "$CODE/deploy/queue-bot"
    systemctl daemon-reload
}

# Перезапуск и проверка, что бот поднялся. 0 — работает.
restart_and_check() {
    systemctl restart queue-bot.service
    sleep 5
    systemctl is-active -q queue-bot.service
}
