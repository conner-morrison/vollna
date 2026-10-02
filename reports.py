#!/usr/bin/env python3
"""Instructions and requests exchanged with the relay server.

The Report page is a conversation, not a job feed: anything that looks like scraped job data is
ignored here. Threads live in reports.json so they survive restarts.
"""
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_FILE = os.path.join(HERE, 'reports.json')
ENV_FILES = (os.path.join(HERE, '.env'), os.path.join(os.path.dirname(HERE), '.env'))
JOB_TYPES = {'job', 'alert', 'invite', 'message', 'email', 'test'}


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


def poll():
    """Fetch anything new from the relay and file it into threads. Returns how many arrived."""
    check_tickets()                       # approval may be waiting under the ticket
    data = load()
    if not data.get('serverId'):
        return 0                          # nothing to authenticate with yet; registration comes first
    incoming = relay('/messages?wait=0&limit=50').get('messages') or []
    added = 0
    for message in incoming:
        body = message.get('body')
        channel, seq = message.get('channel'), message.get('seq')
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
    channel = found.get('channel') or load().get('channel') or env().get('RELAY_CHANNEL')
    if not channel:
        raise RuntimeError('No channel yet. The server has to put "%s" in a channel, or send an '
                           'instruction first so replies can go back to it.' % project_name())
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
    if done and registered():
        try:
            relay('/publish', 'POST', {
                'channel': found.get('channel') or load().get('channel') or env().get('RELAY_CHANNEL') or 'jobs',
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
    data = load()
    thread_id = 'local-%d' % int(time.time() * 1000)
    settings = env()
    data['threads'].insert(0, {'id': thread_id, 'title': title or text.strip().splitlines()[0][:70],
                               'channel': settings.get('RELAY_CHANNEL') or 'jobs', 'completed': False,
                               'created': time.strftime('%Y-%m-%d %H:%M'), 'messages': []})
    save(data)
    return send(thread_id, text)
