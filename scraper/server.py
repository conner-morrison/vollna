#!/usr/bin/env python3
"""Local control panel for the scraper.

    python3 server.py            # then open http://127.0.0.1:8787

Sessions are Chrome profiles kept in profiles/<name>. "New" opens a normal Chrome window so you
can log in; clicking Done closes it and makes the session usable for scraping.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import auto
import reports
import scrape

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(HERE, 'profiles')
LEGACY_PROFILE = os.path.join(HERE, 'chrome-profile')
STATE_FILE = os.path.join(HERE, 'state.json')
VOLLNA_LOGIN = 'https://www.vollna.com/login'
VOLLNA_DASHBOARD = 'https://www.vollna.com/dashboard'
PORT = int(os.environ.get('SCRAPER_PORT', '8787'))

# What can be pulled off a page, what is pulled by default, and what is sent on by default.
ITEMS = ['Job title', 'Job link', 'Job description', 'Project info', 'Client info',
         'Work history', 'Client name']
DEFAULT_EXTRACT = ['Job title', 'Job link', 'Job description', 'Project info', 'Client info']
DEFAULT_SEND = ['Job title', 'Job link', 'Job description']

# name -> {"state": "ready" | "waiting", "proc": Popen or None, "url": str, "check": dict}
sessions = {}
lock = threading.Lock()


def profile_path(name):
    return LEGACY_PROFILE if name == 'default' else os.path.join(PROFILES_DIR, name)


def load_state():
    """Settings that outlive a page reload or a server restart, kept in state.json."""
    try:
        with open(STATE_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    state = load_state()
    state.update(changes)
    with open(STATE_FILE, 'w') as handle:
        json.dump(state, handle, indent=2)
    return state


def save_check(name, check):
    checks = load_state().get('checks', {})
    checks[name] = check
    save_state(checks=checks)


def load_checks():
    return load_state().get('checks', {})


def preferences():
    state = load_state()
    extract = [i for i in state.get('extract', DEFAULT_EXTRACT) if i in ITEMS] or DEFAULT_EXTRACT
    send = [i for i in state.get('send', DEFAULT_SEND) if i in ITEMS]
    return {'items': ITEMS, 'extract': extract, 'send': send}


def selected_session(names):
    """The session to use: the remembered one if it still exists, else the first available."""
    remembered = load_state().get('selected')
    if remembered in names:
        return remembered
    return names[0] if names else None


def list_sessions():
    names = []
    if os.path.isdir(LEGACY_PROFILE):
        names.append('default')
    if os.path.isdir(PROFILES_DIR):
        names += sorted(d for d in os.listdir(PROFILES_DIR)
                        if os.path.isdir(os.path.join(PROFILES_DIR, d)))
    out = []
    for name in names:
        info = sessions.get(name, {})
        proc = info.get('proc')
        state = info.get('state', 'ready')
        if state == 'waiting' and proc and proc.poll() is not None:
            state = 'ready'  # the window was closed by hand
            info = dict(info, state=state, proc=None)
            sessions[name] = info
        out.append({'name': name, 'state': state,
                    'check': info.get('check') or load_checks().get(name)})
    return out


def keep_session_cookies(profile):
    """Turn on "Continue where you left off" for this profile.

    Chrome throws session cookies away when it quits, and many sites (Vollna included) keep you
    signed in with exactly that kind of cookie. With this setting Chrome writes them to disk on
    exit instead, so the login survives closing the window.
    """
    path = os.path.join(profile, 'Default', 'Preferences')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    if os.path.exists(path):
        try:
            with open(path) as handle:
                data = json.load(handle)
        except (ValueError, OSError):
            data = {}
    data.setdefault('session', {})['restore_on_startup'] = 1
    data.setdefault('profile', {})['exit_type'] = 'Normal'
    with open(path, 'w') as handle:
        json.dump(data, handle)


def open_login_window(name, url):
    profile = profile_path(name)
    os.makedirs(profile, exist_ok=True)
    keep_session_cookies(profile)
    proc = subprocess.Popen(
        [scrape.CHROME_BIN, '--user-data-dir=' + profile] + scrape.COMMON_FLAGS + [url or 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with lock:
        sessions[name] = {'state': 'waiting', 'proc': proc, 'url': url or ''}


def open_window(name, url):
    """Open a normal Chrome window on this session's profile, already logged in."""
    profile = profile_path(name)
    os.makedirs(profile, exist_ok=True)
    keep_session_cookies(profile)
    proc = subprocess.Popen(
        [scrape.CHROME_BIN, '--user-data-dir=' + profile] + scrape.COMMON_FLAGS + [url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with lock:
        sessions[name] = dict(sessions.get(name, {}), proc=proc, state='ready')


def finish_login(name, close_window=False):
    """Mark the login as finished. The window may stay open: scraping reads a copy of the profile,
    and keeping it open preserves session cookies, which is how many sites hold a login."""
    if close_window:
        info = sessions.get(name, {})
        proc = info.get('proc')
        if proc and proc.poll() is None:
            proc.terminate()
            for _ in range(40):
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
            if proc.poll() is None:
                proc.kill()
        subprocess.run(['pkill', '-f', 'user-data-dir=%s' % profile_path(name)], check=False)
        time.sleep(1.5)
    with lock:
        sessions[name] = dict(sessions.get(name, {}), state='ready', proc=None)


def check_session(name):
    """Answer one question: is this session logged into Vollna? Access to a given page is a
    separate matter, decided per URL when you run it."""
    profile = profile_path(name)
    result = {'name': name, 'ok': False, 'status': 'logged-out', 'detail': '',
              'at': time.strftime('%Y-%m-%dT%H:%M:%S')}

    if not os.path.isdir(profile):
        result['status'] = 'missing'
        result['detail'] = 'No profile folder for this session.'
        return result

    try:
        html = scrape.chrome_dump(VOLLNA_DASHBOARD, profile, 20000, use_snapshot=True)
    except SystemExit as stop:
        result['detail'] = str(stop)
        return result

    context = scrape.page_context(html)
    result['account'] = context['account']

    if needs_login(html):
        result['detail'] = 'Vollna showed the sign-in page, so this session is logged out.'
        return result

    result.update(ok=True, status='logged-in',
                  detail='Logged in as %s.' % (context['account'] or 'an account Vollna did not name'))
    return result


def delete_session(name):
    """Close any window using the session, then remove its Chrome profile from disk."""
    if not name or not name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Unknown session name.')
    path = os.path.abspath(profile_path(name))
    allowed = (os.path.abspath(PROFILES_DIR), os.path.abspath(LEGACY_PROFILE))
    if not (path == allowed[1] or os.path.dirname(path) == allowed[0]):
        raise ValueError('That is not a session folder.')
    if not os.path.isdir(path):
        raise ValueError('Session "%s" does not exist.' % name)

    finish_login(name, close_window=True)   # a deleted profile must not stay in use
    shutil.rmtree(path)
    with lock:
        sessions.pop(name, None)
    checks = load_state().get('checks', {})
    checks.pop(name, None)
    save_state(checks=checks)
    if load_state().get('selected') == name:
        save_state(selected=None)


def needs_login(html):
    import re
    if re.search(r'type\s*=\s*["\']password["\']', html, re.I):
        return True
    head = scrape.text_from_html(html)[:400].lower()
    return any(sign in head for sign in ('sign in to', 'log in to', 'sign in with google'))


def run_scrape(name, url, selector, wait, extract=None):
    profile = profile_path(name)
    if not os.path.isdir(profile):
        return {'error': 'Session "%s" does not exist yet. Set it up first.' % name}
    # Reading a copy of the profile means an open login window is fine.
    wanted = extract or preferences()['extract']
    html = scrape.chrome_dump(url, profile, wait * 1000, use_snapshot=True)
    result = scrape.result_from_html(html, url, {'textSelector': selector or None})

    # the client's name is read out of the work history, so that fetch is needed for either item
    needs_history = 'Work history' in wanted or 'Client name' in wanted
    history = scrape.fetch_work_history(html, profile, wait * 1000) if needs_history else None
    name_found, mentions = scrape.client_name(history) if 'Client name' in wanted else (None, 0)

    jobs = scrape.parse_vollna(html)
    payload = {
        'extract': wanted,
        'history': history if 'Work history' in wanted else None,
        'clientName': {'name': name_found, 'mentions': mentions,
                       'engine': 'spaCy' if scrape.spacy_model() else 'rules'}
                      if 'Client name' in wanted else None,
        'title': result['title'],
        'url': url,
        'text': result['data']['text'],
        'fields': {k: v for k, v in jobs.items() if k in wanted},
        'client': scrape.parse_client(html) if 'Client info' in wanted else None,
        'project': scrape.parse_project(html) if 'Project info' in wanted else None,
        'loginNeeded': needs_login(html),
        **scrape.page_context(html),
        'chars': len(result['data']['text']),
    }
    os.makedirs(scrape.OUT_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    with open(os.path.join(scrape.OUT_DIR, 'ui-%s.json' % stamp), 'w') as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal quiet

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/reports/thread'):
            from urllib.parse import parse_qs, urlparse
            wanted = parse_qs(urlparse(self.path).query).get('id', [''])[0]
            found = reports.thread(wanted)
            if not found:
                return self.send_json({'error': 'No such conversation.'}, 404)
            return self.send_json({'thread': found})

        if self.path.startswith('/api/reports'):
            note = None
            try:
                reports.poll()                     # pick up anything the server sent
            except RuntimeError as problem:
                note = str(problem)                # show threads anyway when the relay is down
            return self.send_json({'threads': reports.threads(), 'note': note,
                                   'projectName': reports.project_name(),
                                   'registered': reports.registered(),
                                   'serverId': reports.load().get('serverId')})

        if self.path.startswith('/api/auto'):
            return self.send_json(auto.status())

        if self.path.startswith('/api/prefs'):
            return self.send_json(preferences())

        if self.path.startswith('/api/sessions'):
            listing = list_sessions()
            return self.send_json({'sessions': listing,
                                   'selected': selected_session([s['name'] for s in listing])})
        page = os.path.join(HERE, 'ui.html')
        with open(page, 'rb') as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except json.JSONDecodeError:
            return self.send_json({'error': 'bad request'}, 400)

        try:
            if self.path == '/api/session/new':
                name = (data.get('name') or '').strip()
                if not name.replace('-', '').replace('_', '').isalnum():
                    return self.send_json({'error': 'Use letters, digits, - and _ for the name.'}, 400)
                open_login_window(name, data.get('url'))
                save_state(selected=name)       # a session you just made is the one you want
                return self.send_json({'sessions': list_sessions(), 'waiting': name, 'selected': name})

            if self.path == '/api/session/done':
                name = (data.get('name') or '').strip()
                finish_login(name)
                check = check_session(name)
                with lock:
                    sessions[name] = dict(sessions.get(name, {}), check=check)
                save_check(name, check)
                return self.send_json({'sessions': list_sessions(), 'check': check})

            if self.path == '/api/reports/message':
                thread = reports.send((data.get('id') or '').strip(), (data.get('text') or '').strip())
                return self.send_json({'thread': thread})

            if self.path == '/api/reports/complete':
                thread = reports.set_completed((data.get('id') or '').strip(),
                                               bool(data.get('completed', True)))
                return self.send_json({'thread': thread})

            if self.path == '/api/reports/register':
                url = (data.get('url') or '').strip()
                if not url.startswith('http'):
                    return self.send_json({'error': 'Give the server URL, starting with http.'}, 400)
                return self.send_json({'thread': reports.register(url)})

            if self.path == '/api/reports/again':
                return self.send_json({'thread': reports.request_again((data.get('id') or '').strip())})

            if self.path == '/api/reports/new':
                text = (data.get('text') or '').strip()
                if not text:
                    return self.send_json({'error': 'Write something to send.'}, 400)
                thread = reports.start((data.get('title') or '').strip(), text)
                return self.send_json({'thread': thread})

            if self.path == '/api/session/open':
                name = (data.get('name') or '').strip()
                if not os.path.isdir(profile_path(name)):
                    return self.send_json({'error': 'No session called "%s".' % name}, 400)
                open_window(name, (data.get('url') or '').strip() or VOLLNA_DASHBOARD)
                return self.send_json({'sessions': list_sessions()})

            if self.path == '/api/session/fix':
                name = (data.get('name') or '').strip()
                if not os.path.isdir(profile_path(name)):
                    return self.send_json({'error': 'No session called "%s".' % name}, 400)
                open_login_window(name, VOLLNA_LOGIN)
                return self.send_json({'sessions': list_sessions(), 'waiting': name})

            if self.path == '/api/auto/start':
                name = (data.get('session') or selected_session([s['name'] for s in list_sessions()]) or '').strip()
                url = (data.get('url') or '').strip()
                if not url.startswith('http'):
                    return self.send_json({'error': 'Give the page URL to watch.'}, 400)
                if not os.path.isdir(profile_path(name)):
                    return self.send_json({'error': 'Session "%s" does not exist.' % name}, 400)
                prefs = preferences()
                return self.send_json(auto.start(url, name, profile_path(name),
                                                 int(data.get('interval') or 120),
                                                 prefs['extract'], prefs['send']))

            if self.path == '/api/auto/stop':
                return self.send_json(auto.stop())

            if self.path == '/api/auto/forget':
                return self.send_json(auto.forget())

            if self.path == '/api/prefs':
                keep = lambda names: [i for i in (names or []) if i in ITEMS]
                save_state(extract=keep(data.get('extract')) or DEFAULT_EXTRACT,
                           send=keep(data.get('send')))
                return self.send_json(preferences())

            if self.path == '/api/session/select':
                name = (data.get('name') or '').strip()
                names = [s['name'] for s in list_sessions()]
                if name not in names:
                    return self.send_json({'error': 'No session called "%s".' % name}, 400)
                save_state(selected=name)
                return self.send_json({'selected': name})

            if self.path == '/api/session/delete':
                delete_session((data.get('name') or '').strip())
                return self.send_json({'sessions': list_sessions()})

            if self.path == '/api/run':
                result = run_scrape((data.get('session') or 'default').strip(),
                                    (data.get('url') or '').strip(),
                                    (data.get('selector') or '').strip(),
                                    int(data.get('wait') or 20),
                                    data.get('extract'))
                return self.send_json(result)
        except SystemExit as stop:          # scrape.py exits on Chrome problems
            return self.send_json({'error': str(stop)}, 500)
        except RuntimeError as problem:     # relay trouble, bad conversation id, …
            return self.send_json({'error': str(problem)}, 400)
        except Exception as problem:        # noqa: BLE001 - surface anything else in the UI
            return self.send_json({'error': '%s: %s' % (type(problem).__name__, problem)}, 500)

        self.send_json({'error': 'unknown endpoint'}, 404)


if __name__ == '__main__':
    os.makedirs(PROFILES_DIR, exist_ok=True)
    print('Scraper UI: http://127.0.0.1:%d  (Ctrl+C to stop)' % PORT)
    HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
