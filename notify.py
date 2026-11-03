#!/usr/bin/env python3
"""Telegram alerts: a message to a chat through a bot, for things a person must hear about.

Needs a bot token (from @BotFather) and a chat id, saved on the panel's Profile tab (telegram.json)
or set as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env; the saved ones win. Every message starts
with this project's name in bold, so alerts from several projects in one chat can be told apart.
"""
import html
import json
import os
import urllib.error
import urllib.request

import reports

TELEGRAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telegram.json')


def saved():
    try:
        with open(TELEGRAM_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save(token, chat):
    with open(TELEGRAM_FILE, 'w') as handle:
        json.dump({'token': token, 'chat': chat}, handle, indent=2)


def settings():
    """(token, chat id, where they came from): the Profile tab's, else .env / the environment."""
    mine = saved()
    if mine.get('token') and mine.get('chat'):
        return mine['token'], mine['chat'], 'profile'
    found = reports.env()
    token, chat = found.get('TELEGRAM_BOT_TOKEN'), found.get('TELEGRAM_CHAT_ID')
    return token, chat, ('env' if token and chat else None)


def summary():
    """What the panel may show: never the whole token, which is the bot's password."""
    token, chat, source = settings()
    return {'chatId': chat or '', 'tokenEnd': (token or '')[-4:], 'source': source}


def telegram(text, error=False):
    """Send text to the configured chat. Returns 'sent' or why not; never raises.

    An error alert gets a red cross before the name, so it stands out in the chat at a glance.
    """
    token, chat, _ = settings()
    if not token or not chat:
        return 'not sent: save a Telegram bot token and chat id on the Profile tab'
    # the name in bold; everything is escaped, since an error may hold "<" or "&"
    message = '%s<b>%s</b>\n%s' % ('\u274c ' if error else '', html.escape(reports.project_name()),
                                   html.escape(text[:3900]))
    request = urllib.request.Request(
        'https://api.telegram.org/bot%s/sendMessage' % token, method='POST',
        data=json.dumps({'chat_id': chat, 'text': message, 'parse_mode': 'HTML',
                         'disable_web_page_preview': True}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            answer = json.loads(response.read().decode('utf-8', 'replace') or '{}')
    except urllib.error.HTTPError as problem:
        detail = problem.read().decode('utf-8', 'replace')
        try:
            detail = json.loads(detail).get('description') or detail
        except ValueError:
            pass
        return 'not sent: Telegram answered %s: %s' % (problem.code, str(detail)[:150])
    except (urllib.error.URLError, OSError) as problem:
        return 'not sent: Telegram unreachable: %s' % getattr(problem, 'reason', problem)
    return 'sent' if answer.get('ok') else 'not sent: %s' % str(answer)[:150]
