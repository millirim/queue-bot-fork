# Общее для install.sh и команды queue-bot. Подключается через source.
CODE=/opt/queue-bot              # код — можно стереть и скачать заново
CONF_DIR=/etc/queue-bot          # настройки (токен, админы) — вводятся один раз
CONF="$CONF_DIR/env"
DATA=/var/lib/queue-bot          # база и бэкапы — переживают обновления
APP_USER=queuebot
UNITS=(queue-bot.service queue-bot-games.service queue-bot-maint.service queue-bot-backup.service queue-bot-backup.timer queue-bot-update.service queue-bot-update.path)

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
    # Кнопка «Обновить бота»: путь следит за файлом-запросом, который кладёт бот. Включение безопасно повторять.
    systemctl enable -q --now queue-bot-update.path || true
    # Дежурный ответчик включается на загрузку, но не запускается сейчас (бот работает; дежурный стартует при остановке бота).
    systemctl enable -q queue-bot-maint.service || true
    # Игры — отдельная служба со своим секретом (общий с веб-панелью бота только для подписи билетов входа).
    if [[ ! -f "$CONF_DIR/games.env" ]]; then
        install -d -m 700 "$CONF_DIR"
        (umask 077; printf 'GAMES_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > "$CONF_DIR/games.env")
        systemctl try-restart queue-bot.service || true  # бот прочитает секрет заново
    fi
    systemctl enable -q --now queue-bot-games.service || true
    # Папка данных нужна боту сразу (запросы на обновление, версия), systemd создаёт её только при старте службы.
    install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA"
    write_version
}

# Версия, которую показывает бот в Панели Админа (бот не может читать git: код принадлежит root).
write_version() {
    local tmp="$DATA/.version.tmp"
    git -C "$CODE" log -1 --format='%h от %cd' --date=format:'%d.%m.%Y %H:%M' > "$tmp"
    chown "$APP_USER:$APP_USER" "$tmp"
    mv -f "$tmp" "$DATA/version"
}

# Перезапуск и проверка, что бот поднялся. 0 — работает.
restart_and_check() {
    systemctl restart queue-bot.service
    sleep 5
    systemctl is-active -q queue-bot.service
}
