# VitaScore — правила проекта

## Стек
- Python 3.11+, Flask, SQLite через стандартный модуль sqlite3 (без ORM).
- Фронтенд: чистые HTML/CSS/JS, без фреймворков и сборки.
- Зависимости только: Flask, pytest (и gunicorn для деплоя). Новые библиотеки — только с моего согласия.

## Ограничения
- НЕ добавлять авторизацию, OAuth, сторонние API и новые внешние сервисы.
- Яндекс.Метрику и виджет aistudio.yandexcloud оставить как есть.
- Дизайн и тексты страницы не менять, кроме блока анкеты.

## Структура
- app/scoring.py — только логика скоринга, без импорта Flask.
- app/db.py — подключение к SQLite и создание таблиц.
- app/routes.py — страницы и API.
- app/templates/, app/static/css/, app/static/js/ — фронтенд.
- tests/ — pytest.

## Команды
- Запуск: python run.py  (http://localhost:5000)
- Тесты: pytest -q
