#!/usr/bin/env bash
# Установка бота на Debian 12/13 как службы systemd:  sudo bash deploy/install.sh
# Повторный запуск безопасен: настройки и база не трогаются, код обновляется до последнего.
# Потом всё делается командой queue-bot (справка: queue-bot help).
set -euo pipefail

main() {
    local src_dir repo
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    source "$src_dir/deploy/common.sh"
    need_root bash deploy/install.sh

    # Откуда скачан этот код — оттуда и будут приходить обновления.
    repo=$(git config --file "$src_dir/.git/config" remote.origin.url 2>/dev/null \
        || echo https://github.com/millirim/queue-bot-fork.git)

    say "Ставлю пакеты (python3, venv, git, curl)"
    apt-get update -q
    apt-get install -y -q python3 python3-venv git curl ca-certificates
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "Нужен Python 3.11 или новее"

    say "Проверяю доступ к Telegram"
    curl -sS -m 15 -o /dev/null https://api.telegram.org || die "Нет доступа к api.telegram.org — бот не сможет работать"

    say "Пользователь $APP_USER (без root-прав и без входа в систему)"
    if id -u "$APP_USER" &>/dev/null; then
        usermod -d "$DATA" "$APP_USER"
    else
        useradd --system --no-create-home --home-dir "$DATA" --shell /usr/sbin/nologin "$APP_USER"
    fi

    migrate_old_layout

    say "Код → $CODE"
    if [[ -d "$CODE/.git" ]]; then
        chown -R root:root "$CODE"
        # Старая копия может смотреть в другой репозиторий или ветку — переключаем на основную ветку $repo.
        local branch
        git -C "$CODE" remote set-url origin "$repo"
        git -C "$CODE" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
        git -C "$CODE" fetch -q --prune origin
        git -C "$CODE" remote set-head origin -a >/dev/null
        branch=$(git -C "$CODE" rev-parse --abbrev-ref origin/HEAD)
        git -C "$CODE" checkout -q -f -B "${branch#origin/}" "$branch"
        git -C "$CODE" clean -q -fdx -e .venv  # остатки старых версий (данные теперь лежат не здесь)
    else
        rm -rf "$CODE"
        git clone -q "$repo" "$CODE"
    fi
    apply_code

    configure

    say "Запускаю"
    systemctl enable -q queue-bot.service queue-bot-backup.timer
    systemctl start queue-bot-backup.timer
    if restart_and_check; then
        say "Готово, бот работает ✓  Версия: $(version)"
        journalctl -u queue-bot -n 3 -o cat --no-pager || true
        echo
        "$CODE/deploy/queue-bot" help
    else
        journalctl -u queue-bot -n 30 --no-pager || true
        die "Бот не запустился — смотри лог выше"
    fi
}

# Прошлая версия установки хранила настройки и базу внутри папки с кодом.
migrate_old_layout() {
    [[ -f "$CODE/.env" && ! -f "$CONF" ]] || return 0
    say "Переношу настройки из старой установки в $CONF"
    install -d -m 700 "$CONF_DIR"
    grep -E '^(BOT_TOKEN|ADMIN_IDS|TIMEZONE)=' "$CODE/.env" > "$CONF" || true
    chmod 600 "$CONF"
    systemctl stop queue-bot.service 2>/dev/null || true
    rm -rf "$CODE"  # база старой версии несовместима, код скачаем заново
}

configure() {
    if [[ -f "$CONF" ]] && grep -q '^BOT_TOKEN=.' "$CONF"; then
        echo "Настройки уже есть в $CONF — оставляю (изменить: sudo queue-bot config)"
        return
    fi
    say "Настройки бота (вводятся один раз)"
    local token me admins
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
        admins=${admins// /}
        [[ $admins =~ ^[0-9]+(,[0-9]+)*$ ]] && break
        echo "✗ Нужны только цифры, например 123456789"
    done
    install -d -m 700 "$CONF_DIR"
    (umask 077; printf 'BOT_TOKEN=%s\nADMIN_IDS=%s\nTIMEZONE=Europe/Minsk\n' "$token" "$admins" > "$CONF")
}

main "$@"
exit
