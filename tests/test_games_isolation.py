"""Изоляция игр: файлы с правилами — чистый Python без бота, базы, сети и конфигурации."""
import ast
from pathlib import Path

GAMES = Path(__file__).resolve().parent.parent / "games"
RULE_FILES = ("base", "g2048", "snake", "checkers", "chess", "blackjack", "poker")
FORBIDDEN = {"db", "web", "admin", "handlers", "common", "config", "main", "bottom", "metrics", "features", "ranking", "replication",
             "aiogram", "aiohttp", "aiosqlite", "requests", "urllib", "socket", "http", "subprocess", "os", "sqlite3", "asyncio", "threading",
             "multiprocessing", "logsink", "updater", "broadcast", "games"}


def imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            names.add("games")  # относительные импорты внутри пакета: разрешены только base (проверяем ниже)
    return names


def test_rule_files_do_not_import_the_bot_or_io():
    for name in RULE_FILES:
        path = GAMES / f"{name}.py"
        if not path.exists():
            continue
        bad = (imported(path) - {"games"}) & FORBIDDEN
        assert not bad, f"games/{name}.py тянет лишнее: {sorted(bad)} — правила игр должны быть чистыми"
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from games", "import games", "from .")) :
                assert stripped.startswith(("from games.base import", "from .base import")), f"games/{name}.py: из пакета можно брать только base ({stripped})"
        assert "open(" not in text and "__import__" not in text and "eval(" not in text and "exec(" not in text, f"games/{name}.py: ввод-вывод и динамика запрещены"
