"""Команды для почты: проверка настройки, тестовое письмо и «всё одной командой» для планировщика.

`flask --app run mail-check` — проверить Brevo без отправки писем;
`flask --app run mail-test --to you@example.com` — отправить тестовое письмо;
`flask --app run send-all` — напоминания Plus, недельное письмо и отчёт месяца одной командой (на PythonAnywhere
бесплатный тариф даёт одну запланированную задачу, поэтому все рассылки запускаются вместе раз в сутки).
"""
import os

import click
from flask.cli import with_appcontext
from flask import current_app

from . import mailer, monthly, plus
from .engage import send_weekly


@click.command("mail-check")
def mail_check_command():
    """Проверить настройку почты (Brevo) без отправки писем."""
    failed = False
    for status, text in mailer.check():
        click.echo({"ok": "[ok]   ", "fail": "[FAIL] ", "warn": "[warn] "}[status] + text)
        failed = failed or status == "fail"
    site = os.environ.get("SITE_URL", "").strip()
    click.echo(("[ok]   SITE_URL задан (" + site + ")") if site else "[FAIL] SITE_URL не задан: ссылки в письмах будут неверными")
    raise SystemExit(1 if failed or not site else 0)


@click.command("mail-test")
@click.option("--to", "to", required=True, help="Куда отправить тестовое письмо.")
def mail_test_command(to):
    """Отправить тестовое письмо через Brevo."""
    ok, info = mailer.send_email(to, "", "Проверка почты Del Health",
                                 "<p>Если вы видите это письмо, отправка из Del Health настроена.</p>",
                                 "Если вы видите это письмо, отправка из Del Health настроена.")
    click.echo(("Отправлено, id: " + str(info)) if ok else ("Не отправлено: " + str(info)))
    raise SystemExit(0 if ok else 1)


@click.command("send-all")
@with_appcontext
@click.option("--dry-run", is_flag=True, help="Только посчитать, письма не отправлять.")
def send_all_command(dry_run):
    """Все рассылки одной командой: напоминания Plus, недельное письмо, отчёт месяца."""
    site = os.environ.get("SITE_URL", "").strip()
    if not site:
        raise click.ClickException("Задайте SITE_URL (например https://example.pythonanywhere.com).")
    if not dry_run and not mailer.configured():
        raise click.ClickException("Не заданы BREVO_API_KEY и BREVO_SENDER_EMAIL. Проверьте: flask --app run mail-check")
    with current_app.test_request_context(base_url=site):
        for name, fn in (("напоминания", plus.send_due_reminders), ("недельное письмо", send_weekly),
                         ("отчёт месяца", monthly.send_monthly)):
            ok, bad, dry = fn(site, dry_run=dry_run)
            click.echo(f"{name}: отправлено {ok}, ошибок {bad}" + (f", к отправке {dry}" if dry_run else ""))
