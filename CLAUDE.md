# VitaScore — правила проекта

## Стек
- Python 3.11+, Flask, SQLite через стандартный модуль sqlite3 (без ORM).
- Фронтенд: чистые HTML/CSS/JS, без фреймворков и сборки.
- Зависимости только: Flask, pytest (и gunicorn для деплоя). Новые библиотеки — только с моего согласия.

## Ограничения
- НЕ добавлять авторизацию, OAuth, сторонние API и новые внешние сервисы.
- Яндекс.Метрику и виджет aistudio.yandexcloud не менять, кроме одного: Метрика и собственный лог событий
  включаются только после согласия на аналитические cookie (cookie vs_consent=all, см. app/consent.py).
- Новые cookie, трекеры и поля с персональными данными — только вместе с обновлением app/templates/privacy.html
  и POLICY_VERSION в app/consent.py.
- Дизайн и тексты страницы не менять, кроме блока анкеты.

## Структура
- app/scoring.py — только логика скоринга, без импорта Flask.
- app/db.py — подключение к SQLite, создание таблиц и миграции (_migrate).
- app/consent.py — cookie согласия и версия политики.
- app/visitor.py — разбор User-Agent, примерная страна, источник перехода; без Flask и без сторонних библиотек.
- app/routes.py — страницы и API.
- app/templates/, app/static/css/, app/static/js/ — фронтенд.
- tests/ — pytest.
- index.html, 404.html в корне — только редирект со старого GitHub Pages на новый адрес, не часть приложения.

## Команды
- Запуск: python run.py  (http://localhost:5000)
- Тесты: pytest -q
- Отчёты: sqlite3 instance/vitascore.db < reports.sql
