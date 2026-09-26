# VitaScore

Сайт сервиса скоринга здоровья: лендинг, анкета из 4 вопросов с расчётом балла на сервере,
сбор e-mail и лог действий посетителей. Flask + SQLite, без сборки фронтенда.

> VitaScore не является медицинским сервисом и не заменяет консультацию врача.

## Структура

```
app/
  __init__.py      create_app(): конфиг, БД, анонимный visitor_id в cookie-сессии
  scoring.py       calculate_score() — логика скоринга, без Flask
  consent.py       cookie согласия vs_consent и версия политики
  db.py            SQLite: get_db(), init_db(), log_event()
  routes.py        GET /, /privacy; POST /api/score, /api/lead, /api/event, /api/consent
  templates/       base.html (head, Метрика, баннер cookie, футер, виджет), index.html, privacy.html
  static/css/      style.css
  static/js/       main.js — анкета, форма e-mail, track() → Метрика + /api/event
tests/             pytest: test_scoring.py, test_api.py
run.py             локальный запуск
```

### Скоринг

| Сфера | Вопрос | Вес |
|---|---|---|
| Сон | `sleep`: `lt5` / `5_6` / `7_8` / `gt8` | 0.30 |
| Движение | `activity`: `0` / `1_2` / `3_4` / `5plus` дней в неделю | 0.25 |
| Питание | `nutrition`: `0_1` / `2_3` / `4plus` порций | 0.20 |
| Восстановление | `stress`: 1–5 (1 — спокойно) | 0.25 |

Каждый ответ даёт 0–100 баллов по сфере, итог — взвешенная сумма. Таблицы баллов — в `app/scoring.py`.

## Cookie и согласие

- При первом визите показывается баннер: «Принять все» или «Только необходимые».
- **Пока нет согласия на аналитику**, Яндекс.Метрика не загружается, `/api/event` ничего не пишет,
  сервер не выдаёт `visitor_id` и не логирует события. Результаты анкеты сохраняются без привязки к посетителю.
- Выбор хранится в cookie `vs_consent` (`all` / `necessary`) и записывается в таблицу `cookie_consents`
  вместе с версией политики. Изменить выбор можно по ссылке «Настройки cookie» в футере.
- Форма e-mail требует отметки согласия на обработку персональных данных. Сервер проверяет `consent: true`
  и сохраняет версию политики в `leads.policy_version`.
- Текст политики — `app/templates/privacy.html` (адрес `/privacy`). **Перед публикацией заполните реквизиты
  оператора в начале файла.** При любой правке текста увеличьте `POLICY_VERSION` в `app/consent.py`.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                      # http://localhost:5000
```

На macOS порт 5000 часто занят AirPlay Receiver — тогда: `PORT=5050 python run.py`.

Переменные окружения:

- `SECRET_KEY` — ключ подписи cookie (в проде обязательно задать своё значение);
- `DATABASE_PATH` — путь к файлу SQLite, по умолчанию `instance/vitascore.db`;
- `PORT`, `FLASK_DEBUG=1` — для `run.py`.

## Тесты

```bash
pytest -q
```

## Данные в БД

Таблицы: `events` (просмотры, клики, переходы, события анкеты и диалога — только при согласии на аналитику),
`leads` (e-mail, тариф, версия политики), `score_results` (ответы и баллы), `cookie_consents` (выбор в баннере cookie).
Новые колонки в существующей базе добавляются автоматически при старте приложения.

```bash
sqlite3 instance/vitascore.db "select name, path, created_at from events order by id desc limit 20;"
sqlite3 instance/vitascore.db "select email, plan, created_at from leads;"
sqlite3 instance/vitascore.db "select total, breakdown, created_at from score_results;"
sqlite3 instance/vitascore.db "select choice, count(*) from cookie_consents group by choice;"
```

## Деплой

GitHub Pages отдаёт только статические файлы и не запускает Python, поэтому сайту нужен
хостинг с бэкендом (любой VPS или PaaS с Python). Команда запуска:

```bash
gunicorn "app:create_app()"
```

Не забудьте задать `SECRET_KEY` и `DATABASE_PATH` на постоянном диске.
