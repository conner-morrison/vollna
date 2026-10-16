#!/usr/bin/env python3
"""Auto mode: watch a Vollna feed page and handle each job as it appears.

A job is handled once: decided by the rules in rules.md, then sent on if the decision is not skip.
What is sent follows the "Send to server" list in the sidebar.
"""
import json
import os
import threading
import time

import events
import notify
import reports
import rules
import scrape

HERE = os.path.dirname(os.path.abspath(__file__))
HANDLED_FILE = os.path.join(HERE, 'handled.json')
MAX_HANDLED = 200
CATCH_UP_DEPTH = 25        # how far down the page to look for the last job before giving up

state = {
    'running': False, 'url': '', 'session': '', 'interval': 120,
    'checked': None, 'error': None, 'seen': [], 'handled': [],
    # per page URL: the newest job on it when it was last checked, so a restart knows where it was
    'last': {},
    # set by start(): None once the first check is done, else whether to send what was missed
    'catchUp': None, 'note': None,
}
lock = threading.Lock()
stop_event = threading.Event()
worker = None


def load_handled():
    try:
        with open(HANDLED_FILE) as handle:
            saved = json.load(handle)
        state['handled'] = saved.get('handled', [])
        state['seen'] = saved.get('seen', [])
        state['last'] = saved.get('last', {})
    except (OSError, ValueError):
        pass


def save_handled():
    with open(HANDLED_FILE, 'w') as handle:
        json.dump({'handled': state['handled'][:MAX_HANDLED], 'seen': state['seen'][-500:],
                   'last': state['last']}, handle, indent=2, ensure_ascii=False)
    events.changed()


def extras(row, wanted):
    """Work history and the client's name, fetched only when the sidebar asks for them."""
    if not ({'Work history', 'Client name'} & set(wanted)) or not row['projectId']:
        return None, None, 0
    try:
        dom = scrape.chrome_dump(scrape.WORK_HISTORY_URL % row['projectId'], state['profile'], 20000,
                                 use_snapshot=True)
        content = json.loads(scrape.text_from_html(dom)).get('content') or ''
    except Exception:                       # noqa: BLE001 - a missing history must not stop the run
        return None, None, 0
    history = scrape.parse_work_history(content)
    if 'Client name' in wanted:
        name, mentions = scrape.client_name(history)
    else:
        name, mentions = None, 0
    return (history if 'Work history' in wanted else None), name, mentions


def job_text(row, decision, why, send_list):
    """The message as plain text: no JSON quoting, no escapes, one thing per line.

    Sending a dict would wrap every line of the description in quotes and turn the line breaks into
    "\\n", so the body is written out as text a person can read as it is.
    """
    block = ['Decision: %s' % decision, 'Reason: %s' % why, 'Project id: %s' % row['projectId'], '']
    if 'Job title' in send_list:
        block.append('Job title: %s' % (row.get('Job title') or '(not found)'))
    if 'Job link' in send_list:
        block.append('Job link: %s' % (row.get('Job link') or '(not found)'))
    if 'Client name' in send_list:
        found = row.get('clientName') or {}
        block.append('Client name: %s' % (
            '%s (named in %d feedback%s)' % (found['name'], found['mentions'],
                                             '' if found['mentions'] == 1 else 's')
            if found.get('name') else '(no name written in any feedback)'))
    if 'Job description' in send_list:
        block += ['', 'Job description:'] + scrape.text_lines(row.get('Job description') or '')
    if 'Screening Questions' in send_list:
        asked = row.get('Screening Questions') or []
        block += ['', 'Screening Questions:'] + (['  %d. %s' % (n, q) for n, q in enumerate(asked, 1)]
                                                 or ['  (none)'])
    for item, key, fields in (('Project info', 'project', scrape.PROJECT_CATEGORIES),
                              ('Client info', 'client', scrape.CLIENT_CATEGORIES)):
        if item in send_list:
            values = row.get(key) or {}
            block += ['', item + ':'] + ['  %s: %s' % (name, values.get(name) or '(not found)')
                                         for name in fields]
    if 'Work history' in send_list:
        history = row.get('history') or []
        block += ['', 'Work history (%d past contract%s):' % (len(history),
                                                             '' if len(history) == 1 else 's')]
        done = 0
        for entry in history:
            if entry.get('status') == 'in progress':
                mark = 'in progress'
            else:
                done += 1
                mark = '#%d' % done
            block.append('  %s %s' % (mark, entry.get('job title') or '(no title)'))
            if entry.get('payment type') == 'fixed':
                block.append('      %s | fixed price | billed %s' % (
                    entry.get('Project period') or '?', entry.get('total billed') or '?'))
            else:
                block.append('      %s | %s | %s | billed %s' % (
                    entry.get('Project period') or '?', entry.get('project time commitment') or '?',
                    entry.get('hourly rate') or '?', entry.get('total billed') or '?'))
            for score, text, who in (('feedback score to freelancer', 'written feedback to freelancer',
                                      'to freelancer'),
                                     ('feedback score to client', 'written feedback to client',
                                      'to client')):
                if entry.get(score):
                    block.append('      %s %s: %s' % (who, entry[score],
                                                      entry.get(text) or '(no text)'))
    return '\n'.join(block).strip()


def send_job(row, decision, why, send_list):
    """Publish the decision and the chosen fields as plain text. Returns a status for the panel.

    A skip is refused here, not only by the caller: nothing about a skipped job ever leaves the
    project, whoever asks for the send.

    A job's message id is always "job-<projectId>", so the relay's own duplicate check stops the same
    job being sent twice; the id is never varied to push a second copy through. The relay's answer is
    read, so a message it refused as a duplicate is not reported as sent.
    """
    if decision == rules.SKIP:
        return 'not sent (skip)'
    payload = job_text(row, decision, why, send_list)
    if not reports.registered():
        return 'not sent: this project is not registered yet'
    channel = reports.job_channel()
    if not channel:
        return 'not sent: the server has not allocated a channel to this project'
    message_id = 'job-%s' % row['projectId']
    try:
        answer = reports.relay('/publish', 'POST', {'channel': channel, 'id': message_id,
                                                    'body': payload})
    except RuntimeError as problem:
        return 'failed: %s' % str(problem)[:120]
    if answer.get('duplicate'):
        return 'not sent (duplicate): the server already holds this job'
    return 'sent'


def handle_once(extract_list, send_list):
    """One pass: read the page, handle jobs not seen before."""
    profile = state['profile']
    html = scrape.chrome_dump(state['url'], profile, 25000, use_snapshot=True)
    context = scrape.page_context(html)
    if context['accessDenied']:
        raise RuntimeError('session "%s" has no access to that page' % state['session'])
    # A logged-out session is handed the sign-in page, which parses as a feed with no jobs at all.
    # Saying so beats watching an empty page for days and reporting nothing wrong.
    if scrape.needs_login(html):
        raise RuntimeError('session "%s" is logged out of Vollna: open the session and log in '
                           'again, then start watching' % state['session'])

    rows = [r for r in scrape.parse_rows(html) if r['projectId']]
    seen = set(state['seen'])
    first_pass = state['catchUp'] is not None
    if first_pass:
        fresh = missed_jobs(rows, seen, state['catchUp'])
        seen.update(r['projectId'] for r in rows)      # the rest of the page counts as seen
        state['catchUp'] = None
    else:
        fresh = [r for r in rows if r['projectId'] not in seen]

    for row in fresh:
        seen.add(row['projectId'])
        history, name, mentions = extras(row, extract_list)
        row['history'] = history
        row['clientName'] = {'name': name, 'mentions': mentions} if name or 'Client name' in extract_list else None
        decision, why = rules.decide(row['client'])
        # skip means skip: nothing is sent about those jobs (send_job refuses them too)
        status = send_job(row, decision, why, send_list)
        state['handled'].insert(0, {
            'at': time.strftime('%Y-%m-%d %H:%M'), 'title': row['Job title'],
            'link': row['Job link'], 'decision': decision, 'why': why, 'status': status,
            'projectId': row['projectId'],
            'clientName': (row['clientName'] or {}).get('name') if row.get('clientName') else None,
            'historyCount': len(history or []) if history is not None else None,
        })
    state['seen'] = list(seen)
    state['checked'] = time.strftime('%Y-%m-%d %H:%M')
    if rows:
        # the newest job looked at on this page: where the next start picks up from
        state['last'][state['url']] = {'projectId': rows[0]['projectId'], 'title': rows[0]['Job title'],
                                       'at': state['checked']}
    save_handled()
    failed = [h for h in state['handled'][:len(fresh)] if h['status'].startswith('failed')]
    if failed:
        # a job the server never got is lost unless someone hears about it
        raise RuntimeError('%d job(s) could not be sent to the server: %s'
                           % (len(failed), failed[0]['status']))
    return len(fresh), first_pass


def missed_jobs(rows, seen, catch_up):
    """The jobs to handle on the first check after starting, and a note saying why.

    No catch-up: none, everything on the page is taken as seen. Catch-up: look for the last job
    checked last time within the top CATCH_UP_DEPTH; the jobs above it appeared while watching was
    off. Not found that far down: too much was missed to tell, so the top CATCH_UP_DEPTH stand in.
    """
    if not catch_up:
        state['note'] = 'Started without sending missed jobs: only jobs posted from now on are handled.'
        return []
    top = rows[:CATCH_UP_DEPTH]
    ids = [r['projectId'] for r in top]
    remembered = state['last'].get(state['url']) or {}
    last = remembered.get('projectId')
    if not last:
        # nothing remembered for this page (watched before this was kept): the newest job on it
        # that was already seen marks the same place
        last = next((i for i in ids if i in seen), None)
        remembered = next(({'title': r['Job title']} for r in top if r['projectId'] == last), {})
    if last and last in ids:
        missed = top[:ids.index(last)]
        state['note'] = ('Caught up: %d job(s) were posted above the last one checked (%s).'
                         % (len(missed), (remembered.get('title') or '')[:60]))
    else:
        missed = top
        state['note'] = ('The last job checked was not in the top %d%s, so the top %d were analysed.'
                         % (CATCH_UP_DEPTH, '' if last else ' (none remembered for this page)',
                            len(missed)))
    # one already handled (from this page or another filter that lists it too) is not sent twice
    return [r for r in missed if r['projectId'] not in seen]


def loop(extract_list, send_list):
    try:
        while not stop_event.is_set():
            try:
                handle_once(extract_list, send_list)
                state['error'] = None
            # scrape.py reports Chrome trouble (an empty render after the Mac slept, a locked
            # profile) with sys.exit, a SystemExit that "except Exception" lets through; it used to
            # end this thread silently while the panel still said "watching"
            except (Exception, SystemExit) as problem:      # noqa: BLE001 - stop, and tell someone
                # Watching on after an error only repeats it (a wrong URL, a logged-out session),
                # so stop and alert a person, who can fix it and start again.
                when = time.strftime('%Y-%m-%d %H:%M')
                stop_event.set()
                alert = notify.telegram('Stopped watching because of an error.\n\n'
                                        'Error: %s\nPage: %s\nSession: %s\nAt: %s'
                                        % (str(problem)[:500], state['url'], state['session'], when),
                                        error=True)
                state['error'] = '%s (%s) · Telegram alert %s' % (str(problem)[:200], when, alert)
                events.changed()
                break
            stop_event.wait(max(30, int(state['interval'])))
    finally:
        state['running'] = False
        events.changed()                # a watcher that stopped must not still look like it runs


def start(url, session, profile, interval, extract_list, send_list, catch_up=False):
    global worker
    with lock:
        if state['running']:
            raise RuntimeError('Already watching. Stop it first.')
        load_handled()          # pick up whatever is on disk, rather than stale memory
        state.update({'running': True, 'url': url, 'session': session, 'profile': profile,
                      'interval': int(interval), 'error': None, 'catchUp': bool(catch_up),
                      'note': None})
        stop_event.clear()
        state['extract'] = list(extract_list)
        state['send'] = list(send_list)
        worker = threading.Thread(target=loop, args=(extract_list, send_list), daemon=True)
        worker.start()
    events.changed()
    return status()


def stop():
    stop_event.set()
    state['running'] = False
    events.changed()
    return status()


def status():
    # trust the thread, not the flag: a watcher that died is not watching
    alive = state['running'] and worker is not None and worker.is_alive()
    return {'running': alive, 'url': state['url'], 'session': state['session'],
            'interval': state['interval'], 'checked': state['checked'], 'error': state['error'],
            'extract': state.get('extract', []), 'send': state.get('send', []),
            'watching': len(state['seen']), 'handled': state['handled'][:50],
            'note': state['note'], 'last': state['last']}


def forget():
    """Clear the handled list and what has been seen, so everything counts as new again."""
    state['handled'], state['seen'], state['last'] = [], [], {}
    save_handled()
    return status()


load_handled()
