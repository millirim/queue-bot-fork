"""Документация не должна отставать от кода: всё, что есть в коде, должно быть упомянуто в docs/ARCHITECTURE.md и AGENTS.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_every_table_is_described():
    import db
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.SCHEMA)
    assert len(tables) >= 10
    missing = [t for t in tables if f"**`{t}`**" not in ARCH]
    assert not missing, f"таблицы без описания в docs/ARCHITECTURE.md: {missing}"


def test_every_column_is_mentioned():
    import db
    for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", db.SCHEMA, re.S):
        section = ARCH[ARCH.index(f"**`{table}`**"):]
        section = section[: section.find("\n**`", 5) if "\n**`" in section[5:] else len(section)]
        for column in re.findall(r"^\s{4}(?!PRIMARY|UNIQUE|FOREIGN)(\w+)\s", body, re.M):
            assert f"`{column}`" in section or f"`{column}" in section, f"колонка {table}.{column} не описана"


def test_every_env_variable_is_documented():
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    for name in re.findall(r'os\.getenv\("(\w+)"', config):
        assert name in ARCH, f"переменная {name} не описана в docs/ARCHITECTURE.md"


def test_every_code_file_is_in_the_agents_map():
    for path in ROOT.glob("*.py"):
        assert f"`{path.name}`" in AGENTS, f"{path.name} нет в карте файлов AGENTS.md"
        assert f"`{path.name}`" in ARCH, f"{path.name} нет в карте файлов docs/ARCHITECTURE.md"


def callback_prefixes() -> set[str]:
    prefixes = set()
    for name in ("handlers.py", "admin.py"):
        code = (ROOT / name).read_text(encoding="utf-8")
        for m in re.finditer(r'F\.data(?:\.regexp\(r"\^([^"]*)"\)| == "([^"]*)"|\.in_\(\{([^}]*)\}\))', code):
            regexp, equal, values = m.groups()
            if regexp is not None:
                head = re.split(r"[:$]", regexp)[0]
                prefixes |= set(re.findall(r"\w+", head))  # «(auxok|auv)» → auxok, auv
            elif equal is not None:
                prefixes.add(equal.split(":")[0])
            else:
                prefixes |= {v.strip().strip('"').split(":")[0] for v in values.split(",")}
    return prefixes


def test_every_callback_prefix_is_in_the_buttons_table():
    prefixes = callback_prefixes()
    assert len(prefixes) > 40, prefixes
    missing = sorted(p for p in prefixes if f"`{p}" not in ARCH)
    assert not missing, f"кнопки без описания в разделе 8 docs/ARCHITECTURE.md: {missing}"


def test_agents_file_is_short_and_linked():
    assert len(AGENTS.splitlines()) < 90, "AGENTS.md должен оставаться быстрым вводным файлом"
    assert "docs/ARCHITECTURE.md" in AGENTS
    assert "AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def test_every_games_file_is_documented():
    games_doc = (ROOT / "docs" / "GAMES.md").read_text(encoding="utf-8")
    for path in (ROOT / "games").glob("*.py"):
        if path.name != "__init__.py" and path.name != "__main__.py":
            assert f"games/{path.name}" in games_doc or f"`{path.name}`" in games_doc, f"games/{path.name} нет в таблице docs/GAMES.md"
