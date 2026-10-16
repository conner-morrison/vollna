#!/usr/bin/env python3
"""Telegram alerts: a message to a chat through a bot, for things a person must hear about.

Needs TELEGRAM_BOT_TOKEN (from @BotFather) and TELEGRAM_CHAT_ID in .env. Every message starts with
this project's name in bold, so alerts from several projects in one chat can be told apart.
"""
import html
import json
import urllib.error
import urllib.request

import reports


def telegram(text, error=False):
    """Send text to the configured chat. Returns 'sent' or why not; never raises.

    An error alert gets a red cross before the name, so it stands out in the chat at a glance.
    """
    settings = reports.env()
    token, chat = settings.get('TELEGRAM_BOT_TOKEN'), settings.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return 'not sent: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env'
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
