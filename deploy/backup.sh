#!/usr/bin/env bash
# Копия базы в backups/ (хранятся 14 дней). Запускается таймером раз в сутки и перед обновлением.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

[[ -f data/queue.db ]] || { echo "Базы ещё нет — пропускаю"; exit 0; }
mkdir -p backups
target="backups/queue-$(date +%F_%H%M%S).db"
# Встроенный бэкап SQLite: корректная копия даже пока бот работает с базой.
.venv/bin/python - "$target" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect("data/queue.db"), sqlite3.connect(sys.argv[1])
with dst:
    src.backup(dst)
src.close(); dst.close()
EOF
find backups -name 'queue-*.db' -mtime +14 -delete
echo "Бэкап: $target"
