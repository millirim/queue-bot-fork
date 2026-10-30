"""Игры для веб-панели. Работают в ОТДЕЛЬНОМ процессе (games/server.py), чтобы никакая игра не могла уронить бота и основную панель.

Правила пакета (проверяются tests/test_games_isolation.py):
- файлы с правилами игр (base, g2048, snake, checkers, chess, blackjack, poker) — чистый Python: только стандартная библиотека,
  без Telegram, без базы бота, без web/admin/handlers/common/config и без сети;
- сервер игр (server, rooms, store) не знает токена бота и не открывает основную базу: у него свой файл games.db и свой секрет.
Подробности: docs/GAMES.md.
"""
