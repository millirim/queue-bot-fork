"""Настройки ролей: создатель (CREATOR_IDS, старая ADMIN_IDS читается тоже)."""
import importlib

import config


def reload_config(monkeypatch, **env):
    for name in ("CREATOR_IDS", "ADMIN_IDS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(config)


def test_creator_ids_and_legacy_admin_ids(monkeypatch):
    try:
        assert reload_config(monkeypatch, CREATOR_IDS="5, 6").CREATOR_IDS == {5, 6}
        assert reload_config(monkeypatch, ADMIN_IDS="7").CREATOR_IDS == {7}, "старая переменная продолжает работать"
        assert reload_config(monkeypatch, CREATOR_IDS="1", ADMIN_IDS="2").CREATOR_IDS == {1, 2}, "обе складываются"
        assert reload_config(monkeypatch).CREATOR_IDS == set()
    finally:
        monkeypatch.undo()
        importlib.reload(config)
