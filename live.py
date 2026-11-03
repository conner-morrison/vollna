#!/usr/bin/env python3
"""One Vollna page kept open in headless Chrome, read again on every check instead of reloaded.

Vollna's filter page fetches new jobs into itself as they are posted, so a watcher only has to look
at the open page. Chrome is driven over its DevTools pipe (--remote-debugging-pipe: requests and
answers are JSON, each ended by a NUL byte on file descriptors 3 and 4), which needs nothing outside
the standard library.

The page runs on a copy of the session's login files (scrape.snapshot_profile), so a login window
open on the same session is not in the way.
"""
import json
import os
import select
import shutil
import subprocess
import time

import scrape

# what the page shows right now: enough to tell a job list from a sign-in page or a refusal
STATE_JS = """JSON.stringify({
  url: location.href, ready: document.readyState,
  rows: document.querySelectorAll('[data-project-context]').length,
  password: !!document.querySelector('input[type="password"]'),
  denied: /do(?:n['’]t| not) have access to this page/i.test(document.body ? document.body.innerText : '')
})"""


class PageGone(RuntimeError):
    """Chrome quit or stopped answering."""


class LivePage:
    def __init__(self, profile, url):
        self.snapshot = scrape.snapshot_profile(profile)
        self.next_id = 0
        self.buffer = b''
        to_chrome, self.to_chrome = os.pipe()
        self.from_chrome, from_chrome = os.pipe()

        def pipes_as_3_and_4():
            os.dup2(to_chrome, 3)
            os.dup2(from_chrome, 4)

        self.process = subprocess.Popen(
            [scrape.CHROME_BIN, '--headless=new', '--disable-gpu', '--remote-debugging-pipe',
             '--user-data-dir=' + self.snapshot] + scrape.COMMON_FLAGS + ['about:blank'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(3, 4), preexec_fn=pipes_as_3_and_4, start_new_session=True)
        os.close(to_chrome)
        os.close(from_chrome)
        try:
            target = self.send('Target.createTarget', {'url': 'about:blank'}, session=False)['targetId']
            self.session = self.send('Target.attachToTarget', {'targetId': target, 'flatten': True},
                                     session=False)['sessionId']
            self.go(url)
        except Exception:
            self.close()
            raise

    def alive(self):
        return self.process.poll() is None

    def send(self, method, params=None, session=True, timeout=30):
        """Run one DevTools command and return its result."""
        if not self.alive():
            raise PageGone('Chrome has quit')
        self.next_id += 1
        message = {'id': self.next_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = self.session
        os.write(self.to_chrome, json.dumps(message).encode() + b'\0')
        until = time.time() + timeout
        while True:
            while b'\0' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\0', 1)
                answer = json.loads(raw)
                if answer.get('id') == self.next_id:          # anything else is an event: not needed
                    if 'error' in answer:
                        raise RuntimeError('Chrome: %s' % answer['error'].get('message'))
                    return answer.get('result', {})
            left = until - time.time()
            if left <= 0 or not select.select([self.from_chrome], [], [], left)[0]:
                raise PageGone('Chrome did not answer %s within %ds' % (method, timeout))
            chunk = os.read(self.from_chrome, 1 << 20)
            if not chunk:
                raise PageGone('Chrome has quit')
            self.buffer += chunk

    def evaluate(self, expression, timeout=30):
        """The value of a JavaScript expression in the page; a promise is waited for."""
        result = self.send('Runtime.evaluate', {'expression': expression, 'returnByValue': True,
                                                'awaitPromise': True, 'timeout': timeout * 1000},
                           timeout=timeout + 5)
        if result.get('exceptionDetails'):
            details = result['exceptionDetails']
            raise RuntimeError((details.get('exception') or {}).get('description') or details.get('text'))
        return result.get('result', {}).get('value')

    def go(self, url):
        self.send('Page.navigate', {'url': url})

    def state(self):
        try:
            return json.loads(self.evaluate(STATE_JS, timeout=10))
        except PageGone:
            raise
        except Exception:               # noqa: BLE001 - between two documents: nothing to read yet
            return None

    def html(self):
        return self.evaluate('document.documentElement.outerHTML')

    def wait(self, timeout):
        """Wait for a job list, a sign-in page or a refusal. (True, loaded) when one shows up within
        timeout, else (False, whether the page itself finished loading)."""
        until = time.time() + timeout
        loaded = False
        while time.time() < until:
            state = self.state()
            if state:
                loaded = loaded or state['ready'] == 'complete'
                if state['rows'] or state['password'] or state['denied']:
                    time.sleep(1.5)                  # let the rest of the list arrive
                    return True, loaded
            time.sleep(2)
        return False, loaded

    def fetch_text(self, path, timeout=30):
        """GET a Vollna address from inside the page, with the page's own login."""
        return self.evaluate('fetch(%s, {credentials: "include"}).then(r => r.text())' % json.dumps(path),
                             timeout=timeout)

    def close(self):
        if self.process.poll() is None:
            scrape.kill_group(self.process)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for fd in (self.to_chrome, self.from_chrome):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.snapshot, ignore_errors=True)
