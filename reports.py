#!/usr/bin/env python3
"""Instructions and requests exchanged with the relay server.

The Report page is a conversation, not a job feed: anything that looks like scraped job data is
ignored here. Threads live in reports.json so they survive restarts.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

import events

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_FILE = os.path.join(HERE, 'reports.json')
ENV_FILES = (os.path.join(HERE, '.env'), os.path.join(os.path.dirname(HERE), '.env'))
JOB_TYPES = {'job', 'alert', 'invite', 'message', 'email', 'test'}
poll_lock = threading.Lock()


def env():
    """RELAY_URL / RELAY_TOKEN / RELAY_CHANNEL, read from .env next to the project."""
    values = {}
    for path in ENV_FILES:
        if not os.path.exists(path):
            continue
        for line in open(path):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip())
    return values


def project_name():
    """What this project calls itself when registering with a server."""
    settings = env()
    return settings.get('PROJECT_NAME') or settings.get('RELAY_ID') or 'vollna-scraper'


def load():
    try:
        with open(REPORTS_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {'threads': [], 'cursor': {}}


def save(data):
    with open(REPORTS_FILE, 'w') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    events.changed()                      # threads, registration or channels may have moved


def relay(path, method='GET', payload=None, timeout=25):
    data = load()
    # the relay address is remembered from the registration; the id doubles as the bearer token
    base = (data.get('relayUrl') or env().get('RELAY_URL') or '').rstrip('/')
    token = data.get('serverId')
    if not base:
        raise RuntimeError('No server yet. Use New -> Register me with the server URL.')
    if not token:
        raise RuntimeError('This project is not registered yet, so it has no id to talk with.')
    request = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as problem:
        detail = problem.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError('Relay answered %s: %s' % (problem.code, detail))
    except urllib.error.URLError as problem:
        raise RuntimeError('Relay unreachable: %s' % problem.reason)
    return json.loads(body) if body.strip() else {}


def post_json(url, payload, timeout=25):
    """POST to any server (registration lives outside the relay)."""
    request = urllib.request.Request(url, method='POST', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            code = response.status
    except urllib.error.HTTPError as problem:
        raise RuntimeError('Server answered %s: %s' % (problem.code,
                                                       problem.read().decode('utf-8', 'replace')[:200]))
    except urllib.error.URLError as problem:
        raise RuntimeError('Server unreachable: %s' % problem.reason)
    try:
        return code, json.loads(raw) if raw.strip() else {}
    except ValueError:
        return code, {'raw': raw[:500]}


def attempt_register(url, name):
    """Try the plain registration call, then the relay's own /enrol, so either kind of server works."""
    base = url.rstrip('/')
    attempts = []
    if base.endswith(('/enrol', '/enroll', '/register')):
        attempts.append((base, {'name': name, 'label': 'Vollna scraper', 'type': 'register'}))
    else:
        attempts.append((base, {'type': 'register', 'name': name}))
        attempts.append((base + '/enrol', {'name': name, 'label': 'Vollna scraper'}))
    problems = []
    for endpoint, payload in attempts:
        try:
            code, answer = post_json(endpoint, payload)
        except RuntimeError as problem:
            problems.append('%s -> %s' % (endpoint, problem))
            continue
        if isinstance(answer, dict) and answer.get('raw', '').lstrip().startswith('<'):
            problems.append('%s -> answered HTML, not a registration endpoint' % endpoint)
            continue
        return endpoint, code, answer
    raise RuntimeError('Registration failed. ' + '; '.join(problems))


def verdict(answer):
    """(id, status) from whatever shape the server replied with."""
    if not isinstance(answer, dict):
        return None, 'waiting'
    given = (answer.get('id') or answer.get('worker_id') or answer.get('workerId')
             or answer.get('assignedId'))
    state = str(answer.get('status') or '').lower()
    if state in ('pending', 'waiting', 'queued'):
        return (str(given) if given else None), 'waiting'
    if state in ('registered', 'approved', 'active', 'ok'):
        return (str(given) if given else None), 'approved'
    if given:
        return str(given), 'approved'
    return None, 'waiting'


def get_json(url, timeout=25):
    request = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
            code = response.status
    except urllib.error.HTTPError as problem:
        raise RuntimeError('Server answered %s: %s' % (problem.code,
                                                       problem.read().decode('utf-8', 'replace')[:200]))
    except urllib.error.URLError as problem:
        raise RuntimeError('Server unreachable: %s' % problem.reason)
    try:
        return code, json.loads(raw) if raw.strip() else {}
    except ValueError:
        return code, {'raw': raw[:500]}


def register(url):
    """Ask a server to register this project. The server approves later and sends back an id."""
    data = load()
    name = project_name()
    endpoint, code, answer = attempt_register(url, name)
    url = endpoint
    thread_id = 'register-%d' % int(time.time() * 1000)
    thread = {'id': thread_id, 'title': 'Register me: %s' % name, 'kind': 'register',
              'url': url, 'status': 'waiting', 'serverId': None, 'completed': False,
              'created': time.strftime('%Y-%m-%d %H:%M'),
              'messages': [{'from': 'me', 'text': 'Registration request sent to %s as "%s".' % (url, name),
                            'at': time.strftime('%Y-%m-%d %H:%M')}]}
    note = (answer.get('message') if isinstance(answer, dict) and answer.get('message')
            else json.dumps(answer, ensure_ascii=False)[:400])
    thread['messages'].append({'from': 'server', 'text': 'Answered %s: %s' % (code, note),
                               'at': time.strftime('%Y-%m-%d %H:%M')})
    given, state = verdict(answer)
    thread['ticket'] = answer.get('ticket') if isinstance(answer, dict) else None
    workspace = endpoint.rstrip('/')
    data['relayUrl'] = workspace[:-len('/enrol')] if workspace.endswith('/enrol') else workspace
    thread['serverId'] = given
    thread['status'] = 'registered' if (state == 'approved' and given) else state
    if thread['ticket']:
        thread['messages'].append({'from': 'me', 'text': 'Ticket: %s — use Request again to ask what came of it.'
                                   % thread['ticket'], 'at': time.strftime('%Y-%m-%d %H:%M')})
    if state == 'approved' and given:
        data['serverId'] = given
    data['threads'].insert(0, thread)
    save(data)
    return thread


def request_again(thread_id):
    """Ask once more, for a registration still waiting for approval."""
    data = load()
    found = next((t for t in data['threads'] if t['id'] == thread_id), None)
    if found is None or found.get('kind') != 'register':
        raise RuntimeError('That is not a registration request.')
    if found.get('ticket'):
        # the relay keeps the answer under the ticket: ask about that, do not register again
        base = found['url'].rstrip('/')
        base = base[:-len('/enrol')] if base.endswith('/enrol') else base
        code, answer = get_json('%s/enrol/%s' % (base, found['ticket']))
        endpoint = found['url']
    else:
        endpoint, code, answer = attempt_register(found['url'], project_name())
    found['url'] = endpoint
    if isinstance(answer, dict) and answer.get('ticket'):
        found['ticket'] = answer['ticket']
    note = (answer.get('message') if isinstance(answer, dict) and answer.get('message')
            else json.dumps(answer, ensure_ascii=False)[:400])
    found['messages'].append({'from': 'me', 'text': 'Asked again.', 'at': time.strftime('%Y-%m-%d %H:%M')})
    found['messages'].append({'from': 'server', 'text': 'Answered %s: %s' % (code, note),
                              'at': time.strftime('%Y-%m-%d %H:%M')})
    given, state = verdict(answer)
    if given:
        found['serverId'] = given
    found['status'] = 'registered' if (state == 'approved' and given) else state
    if state == 'approved' and given:
        found['messages'].append({'from': 'server', 'text': 'Registered. Your id is %s.' % given,
                                  'at': time.strftime('%Y-%m-%d %H:%M')})
        data['serverId'] = given
    save(data)
    return found


def is_job(body):
    """Job data belongs on the Workplace page, not in this conversation."""
    if not isinstance(body, dict):
        return False
    return body.get('type') in JOB_TYPES or body.get('source') in ('vollna', 'upwork')


def text_of(body):
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        for key in ('text', 'message', 'instruction', 'body', 'content'):
            if isinstance(body.get(key), str):
                return body[key]
    return json.dumps(body, ensure_ascii=False)


def pending_ticket():
    """Whether a registration is waiting for approval with a ticket to ask about."""
    return any(t.get('kind') == 'register' and t.get('status') != 'registered' and t.get('ticket')
               for t in load()['threads'])


def check_tickets():
    """Ask the server what came of any registration still waiting.

    This needs no id, which matters: before approval the project has nothing to authenticate with,
    so the ticket is the only way the answer can reach us.
    """
    data = load()
    changed = 0
    for thread in data['threads']:
        if thread.get('kind') != 'register' or thread.get('status') == 'registered' or not thread.get('ticket'):
            continue
        base = thread['url'].rstrip('/')
        base = base[:-len('/enrol')] if base.endswith('/enrol') else base
        try:
            code, answer = get_json('%s/enrol/%s' % (base, thread['ticket']))
        except RuntimeError:
            continue                        # server down: try again next time
        given, state = verdict(answer)
        if not given or state != 'approved':
            continue
        detail = (answer.get('message') if isinstance(answer, dict) and answer.get('message')
                  else json.dumps(answer, ensure_ascii=False)[:400])
        thread['serverId'] = given
        thread['status'] = 'registered'
        thread['messages'].append({'from': 'server',
                                   'text': 'Registered. Your id is %s.\n%s' % (given, detail),
                                   'at': time.strftime('%Y-%m-%d %H:%M')})
        data['serverId'] = given
        data['relayUrl'] = data.get('relayUrl') or base
        changed += 1
    if changed:
        save(data)
    return changed


JOIN_WORDS = ('join', 'added', 'add', 'member', 'allocat', 'assign', 'grant', 'subscrib', 'invite')
LEAVE_WORDS = ('left', 'leave', 'remov', 'revok', 'unsubscrib', 'kick', 'delet')


def notice_change(notice):
    """('join' | 'leave' | None, [channel names]) read out of one server notice.

    The relay does not document its notice shape, so this accepts the plain forms: a dict naming
    "channel" or "channels" with a type/event/action word, or a sentence mentioning "#channel".
    """
    import re as regex

    if isinstance(notice, dict):
        names = notice.get('channels') or notice.get('channel') or []
        names = [names] if isinstance(names, str) else list(names)
        names = [n.get('name') if isinstance(n, dict) else n for n in names]
        words = ' '.join(str(notice.get(k) or '') for k in ('type', 'kind', 'event', 'action',
                                                             'text', 'message'))
        if not names:
            names = regex.findall(r'#([\w.-]+)', words)
    else:
        words = str(notice)
        names = regex.findall(r'#([\w.-]+)', words)
    names = [str(n).lstrip('#') for n in names if n]
    lowered = words.lower()
    if any(w in lowered for w in LEAVE_WORDS):
        return 'leave', names
    if any(w in lowered for w in JOIN_WORDS) or names:
        return 'join', names
    return None, names


def notice_key(notice):
    if isinstance(notice, dict):
        for key in ('id', 'seq', 'notice_id'):
            if notice.get(key) is not None:
                return '%s:%s' % (key, notice[key])
    return json.dumps(notice, sort_keys=True, ensure_ascii=False)


def file_notices(data, notices):
    """Record server notices, update the allocated channels from them, and show them in a thread."""
    seen = set(data.setdefault('noticeKeys', []))
    channels = set(data.get('channels') or [])
    fresh = 0
    for notice in notices:
        key = notice_key(notice)
        if key in seen:
            continue                      # a notice the relay repeats is still one notice
        seen.add(key)
        data['noticeKeys'].append(key)
        action, names = notice_change(notice)
        if action == 'join':
            channels.update(names)
        elif action == 'leave':
            channels.difference_update(names)
        thread = next((t for t in data['threads'] if t['id'] == 'notices'), None)
        if thread is None:
            thread = {'id': 'notices', 'title': 'Server notices', 'kind': 'notices', 'completed': False,
                      'created': time.strftime('%Y-%m-%d %H:%M'), 'messages': []}
            data['threads'].insert(0, thread)
        thread['messages'].append({'from': 'server', 'text': text_of(notice),
                                   'at': time.strftime('%Y-%m-%d %H:%M')})
        fresh += 1
    data['noticeKeys'] = data['noticeKeys'][-200:]
    data['channels'] = sorted(channels)
    return fresh


def channels():
    """Channels the server has put this project in. Without one, nothing can be sent."""
    return list(load().get('channels') or [])


def job_channel():
    """Where to post: the configured channel if the server allocated it, else the first allocated."""
    allocated = channels()
    if not allocated:
        return None
    wanted = env().get('RELAY_CHANNEL') or load().get('channel')
    return wanted if wanted in allocated else allocated[0]


def require_channel():
    channel = job_channel()
    if not channel:
        raise RuntimeError('No channel allocated. The server has to add "%s" to a channel before '
                           'anything can be sent; this updates by itself when it does.' % project_name())
    return channel


def poll(wait=0):
    """Fetch anything new from the relay and file it into threads. Returns how many arrived.

    With wait > 0 the relay holds the request open until it has something to say (or the wait runs
    out), so a caller looping on this hears about notices and messages as soon as they are sent.
    """
    with poll_lock:                       # one poll at a time: two would race to ack and save
        return _poll(wait)


def _poll(wait):
    if not load().get('serverId'):
        return 0                          # nothing to authenticate with yet; registration comes first
    answer = relay('/messages?wait=%d&limit=50' % wait, timeout=wait + 20)
    # loaded after the wait, not before: anything saved while the request was open must survive
    data = load()
    incoming = answer.get('messages') or []
    added = file_notices(data, answer.get('notices') or [])
    if isinstance(answer.get('channels'), list):
        # the relay listing our channels outright is the final word
        data['channels'] = sorted(str(c.get('name') if isinstance(c, dict) else c)
                                  for c in answer['channels'])
    data['lastPoll'] = time.strftime('%Y-%m-%d %H:%M:%S')
    for message in incoming:
        body = message.get('body')
        channel, seq = message.get('channel'), message.get('seq')
        if channel and channel not in data['channels']:
            data['channels'] = sorted(data['channels'] + [channel])   # only members receive
        given = (body.get('id') or body.get('workerId') or body.get('assignedId')) if isinstance(body, dict) else None
        kind = body.get('type') if isinstance(body, dict) else None
        if given and (kind in ('register-approved', 'registered', 'approval') or 'register' in str(kind or '')):
            waiting = next((t for t in data['threads']
                            if t.get('kind') == 'register' and t.get('status') != 'approved'), None)
            if waiting:
                waiting['serverId'] = str(given)
                waiting['status'] = 'registered'
                waiting['messages'].append({'from': 'server', 'text': 'Approved. Your id is %s.' % given,
                                            'at': time.strftime('%Y-%m-%d %H:%M'), 'seq': seq})
                data['serverId'] = str(given)
                added += 1
        elif not is_job(body):
            thread_id = (body.get('threadId') if isinstance(body, dict) else None) or 'relay-%s-%s' % (channel, seq)
            thread = next((t for t in data['threads'] if t['id'] == thread_id), None)
            if thread is None:
                title = (body.get('title') if isinstance(body, dict) else None) or text_of(body).strip().splitlines()[0][:70]
                thread = {'id': thread_id, 'title': title or 'Message from server', 'channel': channel,
                          'completed': False, 'created': time.strftime('%Y-%m-%d %H:%M'), 'messages': []}
                data['threads'].insert(0, thread)
            data['channel'] = data.get('channel') or channel
            thread['messages'].append({'from': 'server', 'text': text_of(body),
                                       'at': time.strftime('%Y-%m-%d %H:%M'), 'seq': seq})
            added += 1
        if channel is not None and seq is not None:
            try:
                relay('/ack', 'POST', {'channel': channel, 'seq': seq})   # so it is not delivered again
            except RuntimeError:
                pass
    save(data)
    return added


def registered():
    """Until the server approves us and gives an id, nothing but registration may be sent."""
    return bool(load().get('serverId'))


def require_registration():
    if not registered():
        raise RuntimeError('Not registered yet. Until the server approves this project and sends an id, '
                           'only the registration request and asking again are allowed.')


def threads():
    data = load()
    return [{'id': t['id'], 'title': t['title'], 'completed': t['completed'],
             'kind': t.get('kind', 'general'), 'status': t.get('status'), 'serverId': t.get('serverId'),
             'created': t['created'], 'count': len(t['messages']),
             'last': t['messages'][-1]['text'][:80] if t['messages'] else ''}
            for t in data['threads']]


def thread(thread_id):
    return next((t for t in load()['threads'] if t['id'] == thread_id), None)


def send(thread_id, text):
    data = load()
    found = next((t for t in data['threads'] if t['id'] == thread_id), None)
    if found is None:
        raise RuntimeError('No such conversation.')
    if found['completed']:
        raise RuntimeError('This conversation is completed; reopen it to write.')
    require_registration()
    channel = found.get('channel') if found.get('channel') in channels() else require_channel()
    relay('/publish', 'POST', {
        'channel': channel,
        'id': 'report-%s-%d' % (thread_id, int(time.time() * 1000)),
        'body': {'type': 'report', 'threadId': thread_id, 'text': text,
                 'from': data.get('serverId') or project_name()},
    })
    found['messages'].append({'from': 'me', 'text': text, 'at': time.strftime('%Y-%m-%d %H:%M')})
    save(data)
    return found


def set_completed(thread_id, done=True):
    data = load()
    found = next((t for t in data['threads'] if t['id'] == thread_id), None)
    if found is None:
        raise RuntimeError('No such conversation.')
    found['completed'] = bool(done)
    channel = found.get('channel') if found.get('channel') in channels() else job_channel()
    if done and registered() and channel:
        try:
            relay('/publish', 'POST', {
                'channel': channel,
                'id': 'report-done-%s-%d' % (thread_id, int(time.time() * 1000)),
                'body': {'type': 'report-complete', 'threadId': thread_id},
            })
            found['messages'].append({'from': 'me', 'text': '(marked completed)',
                                      'at': time.strftime('%Y-%m-%d %H:%M')})
        except RuntimeError:
            pass        # completing locally must work even when the relay is down
    save(data)
    return found


def start(title, text):
    """Begin a new request to the server from this side."""
    require_registration()
    channel = require_channel()
    data = load()
    thread_id = 'local-%d' % int(time.time() * 1000)
    data['threads'].insert(0, {'id': thread_id, 'title': title or text.strip().splitlines()[0][:70],
                               'channel': channel, 'completed': False,
                               'created': time.strftime('%Y-%m-%d %H:%M'), 'messages': []})
    save(data)
    return send(thread_id, text)
