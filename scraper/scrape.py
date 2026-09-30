#!/usr/bin/env python3
"""Extract data from a page in the Chrome window you are already signed into.

    python3 scrape.py recipes/example.json
    python3 scrape.py recipes/example.json --url https://site/other-page
    python3 scrape.py recipes/example.json --json          # print raw JSON
    python3 scrape.py --url https://example.com --text     # no recipe: just the page text

A recipe is JSON describing one page and what to pull out of it. See README.md.
When the page turns out to be a login page, the script says so and waits while you
log in in Chrome, then carries on by itself.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME_JS = os.path.join(HERE, 'chrome.js')
OUT_DIR = os.path.join(HERE, 'out')
PAGES_DIR = os.path.join(HERE, 'pages')
CHROME_BIN = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
PROFILE_DIR = os.path.join(HERE, 'chrome-profile')
COMMON_FLAGS = ['--no-first-run', '--no-default-browser-check']

STATUS_JS = """(function () {
  var login = %s;
  var text = (document.body ? document.body.innerText : '') || '';
  var needed = false;
  if (login) {
    if (login.selector && document.querySelector(login.selector)) needed = true;
    (login.textIncludes || []).forEach(function (t) { if (text.indexOf(t) >= 0) needed = true; });
    if (login.urlIncludes && location.href.indexOf(login.urlIncludes) >= 0) needed = true;
  }
  var waitFor = %s;
  return JSON.stringify({
    ready: document.readyState,
    url: location.href,
    title: document.title,
    loginNeeded: needed,
    waitReady: waitFor ? !!document.querySelector(waitFor) : true,
    chars: text.length
  });
})()"""

EXTRACT_JS = """(function () {
  var recipe = %s;
  function all(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }
  function value(el, spec) {
    if (!el) return null;
    if (spec.attr) return el.getAttribute(spec.attr);
    if (spec.html) return el.innerHTML.trim();
    return ((el.innerText || el.textContent || '')).replace(/[ \\t]+/g, ' ').trim();
  }
  function fields(root, defs) {
    var out = {};
    Object.keys(defs).forEach(function (name) {
      var spec = defs[name];
      if (typeof spec === 'string') spec = { selector: spec };
      if (spec.each) {
        out[name] = all(root, spec.each).map(function (el) {
          return spec.fields ? fields(el, spec.fields) : value(el, spec);
        });
      } else if (spec.all) {
        out[name] = all(root, spec.selector).map(function (el) { return value(el, spec); });
      } else {
        out[name] = value(spec.selector ? root.querySelector(spec.selector) : root, spec);
      }
    });
    return out;
  }
  var data = recipe.fields ? fields(document, recipe.fields) : {};
  if (recipe.text) {
    var main = recipe.textSelector ? document.querySelector(recipe.textSelector) : document.body;
    data.text = main ? (main.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim() : '';
  }
  return JSON.stringify({ url: location.href, title: document.title, data: data });
})()"""


def find_element(html, selector):
    """Inner HTML of the first element matching a simple selector: tag, .class, #id, or a mix."""
    import re as regex

    parsed = regex.match(r'^([A-Za-z][\w-]*)?((?:[.#][\w-]+)*)$', selector.strip())
    if not parsed:
        return None
    tag = parsed.group(1) or r'[A-Za-z][\w-]*'
    wanted = regex.findall(r'[.#][\w-]+', parsed.group(2) or '')
    classes = [w[1:] for w in wanted if w[0] == '.']
    ids = [w[1:] for w in wanted if w[0] == '#']

    for opening in regex.finditer(r'<(%s)\b([^>]*)>' % tag, html, regex.I):
        attrs = opening.group(2)
        found = regex.search(r'class\s*=\s*"([^"]*)"', attrs, regex.I)
        present = found.group(1).split() if found else []
        if not all(c in present for c in classes):
            continue
        if ids:
            found_id = regex.search(r'id\s*=\s*"([^"]*)"', attrs, regex.I)
            if not found_id or found_id.group(1) not in ids:
                continue
        name = opening.group(1)
        pattern = regex.compile(r'<(/?)%s\b[^>]*>' % regex.escape(name), regex.I)
        depth, pos = 1, opening.end()
        while pos < len(html):
            nxt = pattern.search(html, pos)
            if not nxt:
                break
            depth += -1 if nxt.group(1) else 1
            if depth == 0:
                return html[opening.end():nxt.start()]
            pos = nxt.end()
        return html[opening.end():]
    return None


def text_from_html(html, text_selector=None):
    """Readable text from a saved page, without needing a browser."""
    import html as html_module
    import re as regex

    if text_selector:
        inner = find_element(html, text_selector)
        if inner is None:
            print('note: nothing matched "%s"; using the whole page.' % text_selector, file=sys.stderr)
        else:
            html = inner
    body = regex.sub(r'(?is)<(script|style|head|noscript)[^>]*>.*?</\1>', ' ', html)
    body = regex.sub(r'(?i)<br\s*/?>|</(p|div|tr|td|th|li|h\d|section|article)>', '\n', body)
    body = regex.sub(r'(?s)<[^>]+>', '', body)
    body = html_module.unescape(body)
    body = regex.sub(r'[ \t ]+', ' ', body)
    body = regex.sub(r'\n\s*\n\s*\n+', '\n\n', body)
    return '\n'.join(line.strip() for line in body.splitlines()).strip()


VOLLNA_CATEGORIES = ('Job title', 'Job link', 'Job description')


def page_context(html):
    """Who the page thinks you are, and whether Vollna refused to show it."""
    import re as regex

    text = text_from_html(html)
    account = None
    signed = regex.search(r'Signed in as\s*\n?\s*([\w.+-]+@[\w.-]+\.\w+)', text)
    if signed:
        account = signed.group(1)
    else:
        any_email = regex.search(r'[\w.+-]+@[\w.-]+\.\w+', text)
        account = any_email.group(0) if any_email else None
    denied = bool(regex.search(r"do(?:n['’]t| not) have access to this page", text, regex.I))
    return {'account': account, 'accessDenied': denied}


def parse_vollna(html):
    """Pull the job title, the real Upwork link and the description out of a Vollna result page."""
    import re as regex
    import urllib.parse

    found = dict.fromkeys(VOLLNA_CATEGORIES)

    title_html = find_element(html, '.table-column-title')
    if title_html:
        lines = text_from_html(title_html)
        found['Job title'] = lines.splitlines()[0].strip() if lines else None

    # Vollna wraps the job link in /go?...&url=<double-encoded Upwork URL>
    redirect = regex.search(r'href="(/go\?[^"]*url=[^"&]+)"', html)
    if redirect:
        query = urllib.parse.urlparse(redirect.group(1).replace('&amp;', '&')).query
        encoded = urllib.parse.parse_qs(query).get('url', [''])[0]
        found['Job link'] = urllib.parse.unquote(urllib.parse.unquote(encoded)) or None
    if not found['Job link']:
        direct = regex.search(r'https://www\.upwork\.com/jobs/~\d+', html)
        found['Job link'] = direct.group(0) if direct else None

    description_html = find_element(html, 'div.break-words')
    if description_html:
        found['Job description'] = text_from_html(description_html) or None
    return found


CLIENT_CATEGORIES = ('Client Rank', 'Payment method verified', 'total spent', 'Hired number',
                     'active job', 'Posted job', 'Hire rate', 'Opened job', 'avg hourly rate',
                     'total hours', 'review score', 'review number', 'Registered', 'country', 'Region')


def parse_client(html):
    """Client details from a Vollna feed row (the first job shown on the page)."""
    import re as regex

    found = dict.fromkeys(CLIENT_CATEGORIES)
    lines = text_from_html(html).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith('Client Rank')), None)
    if start is None:
        return found

    window = []
    for line in lines[start:start + 60]:
        if regex.match(r'^(Save job|Required Connects|Mark as)', line.strip()):
            break
        if line.strip():
            window.append(line.strip())
    block = '\n'.join(window)
    digits = lambda text: regex.sub(r'[\s,]', '', text)

    def grab(pattern, clean=True):
        hit = regex.search(pattern, block, regex.I)
        if not hit:
            return None
        return digits(hit.group(1)) if clean else hit.group(1).strip()

    found['Client Rank'] = grab(r'Client Rank\s*-?\s*([A-Za-z ]+)', clean=False)
    payment = regex.search(r'Payment method (not verified|verified|unverified)', block, regex.I)
    found['Payment method verified'] = payment.group(1).lower() if payment else None
    spent = grab(r'\$([\d\s,]+)\s*total spent')
    found['total spent'] = '$' + spent if spent else None
    found['Hired number'] = grab(r'([\d\s,]+)\s*hires')
    found['active job'] = grab(r'([\d\s,]+)\s*active')
    found['Posted job'] = grab(r'([\d\s,]+)\s*jobs posted')
    found['Hire rate'] = grab(r'([\d\s,]+%)\s*hire rate')
    found['Opened job'] = grab(r'([\d\s,]+)\s*open job')
    rate = grab(r'([\d.,\s]+)/hr avg hourly rate')
    found['avg hourly rate'] = rate + '/hr' if rate else None
    found['total hours'] = grab(r'([\d\s,]+)\s*hours paid')
    found['review score'] = grab(r'([\d.]+)\s*\n?\s*of\s+[\d\s,]+\s*reviews')
    found['review number'] = grab(r'of\s+([\d\s,]+)\s*reviews')
    found['Registered'] = grab(r'Registered:\s*(.+)', clean=False)

    # After "Registered:" Vollna prints the country (twice) and then the city.
    after = []
    seen_registered = False
    for line in window:
        if seen_registered:
            after.append(line)
        if line.lower().startswith('registered:'):
            seen_registered = True
    if after:
        found['country'] = after[0]
        for line in after[1:]:
            if line != found['country'] and not regex.match(r'^\d{1,2}:\d{2}', line):
                found['Region'] = line
                break
    return found


PROJECT_CATEGORIES = ('Time per week', 'Project period', 'Expecting level', 'Project type')


def parse_project(html):
    """How the job is set up: weekly hours, duration, experience level and one-time vs ongoing."""
    import re as regex

    found = dict.fromkeys(PROJECT_CATEGORIES)
    patterns = {
        'Time per week': r'^(?:(?:Less|More) than\s*\d+\s*hrs?/week|\d+\+?\s*hrs?/week)$',
        'Project period': r'^(?:Less than \d+ months?|More than \d+ months?|\d+\s*to\s*\d+\s*months?)$',
        'Expecting level': r'^(?:Entry level|Intermediate|Expert)$',
        'Project type': r'^(?:One-time project|Ongoing project|Complex project)$',
    }

    lines = text_from_html(html).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith('Client Rank')), 0)
    for line in lines[start:start + 260]:
        line = line.strip()
        if line.startswith("Client's Work History"):
            break                     # end of the first job's details
        for name, pattern in patterns.items():
            if found[name] is None and regex.match(pattern, line, regex.I):
                found[name] = line
    return found


HISTORY_CATEGORIES = ('job title', 'feedback score to freelancer', 'written feedback to freelancer',
                      'feedback score to client', 'written feedback to client', 'Project period',
                      'project time commitment', 'hourly rate', 'total billed')

WORK_HISTORY_URL = 'https://www.vollna.com/project/%s/work-history'


def parse_work_history(fragment):
    """One dict per past contract in Vollna's "Client's recent history" fragment."""
    import re as regex

    entries = []
    running = regex.search(r'Jobs in progress\s*\((\d+)\)', fragment)
    in_progress = int(running.group(1)) if running else 0
    blocks = fragment.split('<div class="flex items-start gap-2 justify-between">')[1:]
    for block in blocks:
        entry = dict.fromkeys(HISTORY_CATEGORIES)
        entry['status'] = 'in progress' if len(entries) < in_progress else 'completed'

        link = regex.search(r'<a\b[^>]*>([\s\S]*?)</a>', block)
        if link:
            entry['job title'] = ' '.join(text_from_html(link.group(1)).split()) or None
        else:                                   # private jobs have no link
            head = text_from_html(block.split('Freelancer:')[0])
            entry['job title'] = head.splitlines()[0].strip() if head.strip() else None

        for who, score_key, text_key in (
                ('To freelancer:', 'feedback score to freelancer', 'written feedback to freelancer'),
                ('To client:', 'feedback score to client', 'written feedback to client')):
            part = block.split(who, 1)
            if len(part) < 2:
                continue
            chunk = part[1][:1200]
            score = regex.search(r'<span class="text-sm font-medium">([\d.]+)</span>', chunk)
            if score:
                entry[score_key] = score.group(1)
            written = regex.search(r'<div class="text-sm text-gray-700 break-words">([\s\S]*?)</div>', chunk)
            if written:
                entry[text_key] = ' '.join(text_from_html(written.group(1)).split()) or None

        column = regex.search(r'<div class="text-sm text-gray-600 w-\[200px\][^"]*"[^>]*>([\s\S]*?)</div>', block)
        if column:
            info = text_from_html(column.group(1))
            flat = ' '.join(info.split())
            period = regex.match(r'([A-Z][a-z]{2}\s+\d{4})(?:\s*-\s*([A-Z][a-z]{2}\s+\d{4}|Present))?', flat)
            if period:
                entry['Project period'] = (period.group(1) + ' - ' + period.group(2)
                                           if period.group(2) else period.group(1))
            worked = regex.search(r'([\d,.]+)\s*hrs?\s*@\s*\$([\d,.]+)/hr', flat)
            if worked:
                entry['project time commitment'] = worked.group(1) + 'hrs'
                entry['hourly rate'] = '$' + worked.group(2) + '/hr'
            billed = regex.search(r'Billed:\s*\$([\d,.]+)', flat)
            if billed:
                entry['total billed'] = '$' + billed.group(1)
        entries.append(entry)
    return entries


def fetch_work_history(page_html, profile, wait_ms=20000):
    """Vollna loads work history only on demand, from /project/<id>/work-history."""
    import json as json_module
    import re as regex

    project = regex.search(r'data-project-id="(\d+)"', page_html)
    if not project:
        return []
    dom = chrome_dump(WORK_HISTORY_URL % project.group(1), profile, wait_ms, use_snapshot=True)
    try:
        payload = json_module.loads(text_from_html(dom))
    except ValueError:
        return []
    return parse_work_history(payload.get('content') or '')


def result_from_html(html, url, recipe):
    import html as html_module
    import re as regex

    found = regex.search(r'(?is)<title[^>]*>(.*?)</title>', html)
    title = html_module.unescape(found.group(1)).strip() if found else ''
    return {'url': url, 'title': title,
            'data': {'text': text_from_html(html, recipe.get('textSelector'))}}


def scrape_file(path, recipe):
    with open(path, encoding='utf-8', errors='replace') as handle:
        html = handle.read()
    return result_from_html(html, 'file://' + os.path.abspath(path), recipe)


def chrome_login(url, profile):
    """Open a normal Chrome window on the scraper's own profile so you can log in once."""
    os.makedirs(profile, exist_ok=True)
    subprocess.Popen([CHROME_BIN, '--user-data-dir=' + profile] + COMMON_FLAGS + [url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('A separate Chrome window is opening on the scraper profile:\n  %s\n' % profile)
    print('Log in there, then CLOSE that window (the profile cannot be used twice at once)')
    print('and run the same command again without --login.')


SNAPSHOT_FILES = ('Local State', 'Default/Cookies', 'Default/Network/Cookies',
                  'Default/Preferences', 'Default/Login Data')


def snapshot_profile(profile):
    """Copy just the login-related files, so a profile in use by an open window can still be read.

    Chrome only lets one process use a profile, and closing that window throws away session
    cookies - which is how many sites (Vollna included) keep you signed in. Working from a copy
    avoids both problems.
    """
    import shutil
    import tempfile

    snapshot = tempfile.mkdtemp(prefix='scraper-profile-')
    for relative in SNAPSHOT_FILES:
        source = os.path.join(profile, relative)
        if os.path.exists(source):
            target = os.path.join(snapshot, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
    return snapshot


def chrome_dump(url, profile, wait_ms, use_snapshot=False):
    """Render a page headlessly on the scraper profile and return its HTML."""
    if not os.path.isdir(profile):
        sys.exit('No scraper Chrome profile yet. Run the same command with --login first.')
    if use_snapshot:
        snapshot = snapshot_profile(profile)
        try:
            return chrome_dump(url, snapshot, wait_ms)
        finally:
            import shutil
            shutil.rmtree(snapshot, ignore_errors=True)
    command = ([CHROME_BIN, '--headless=new', '--user-data-dir=' + profile, '--disable-gpu']
               + COMMON_FLAGS + ['--virtual-time-budget=%d' % wait_ms, '--dump-dom', url])
    # Headless Chrome prints the DOM but then keeps running on a saved profile, so take what it
    # printed and stop waiting for it to quit.
    limit = max(20, wait_ms / 1000 + 15)
    stderr = ''
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=limit)
        html, stderr = done.stdout, done.stderr
    except subprocess.TimeoutExpired as expired:
        html = expired.stdout or ''
        if isinstance(html, bytes):
            html = html.decode('utf-8', 'replace')

    if 'profile appears to be in use' in stderr or 'ProcessSingleton' in stderr:
        sys.exit('The scraper Chrome window is still open. Close it and run this again.')
    if not html.strip():
        sys.exit('Chrome rendered nothing within %ds.\n%s' % (limit, stderr.strip()[:500]))
    return html


def looks_like_login(html, recipe):
    login = recipe.get('loginWhen') or {}
    text = text_from_html(html)
    for needle in login.get('textIncludes', []):
        if needle in text:
            return True
    return False


def osascript(args):
    """Run the JXA helper and return its stdout, explaining the common Chrome blocks."""
    done = subprocess.run(['osascript', '-l', 'JavaScript', CHROME_JS] + args,
                          capture_output=True, text=True)
    if done.returncode != 0:
        stderr = done.stderr.strip()
        if 'Apple Events' in stderr or '-1743' in stderr or 'not allowed' in stderr:
            sys.exit('Chrome is refusing automation. Two one-time settings:\n'
                     '  1. Chrome menu: View > Developer > Allow JavaScript from Apple Events\n'
                     '  2. macOS: System Settings > Privacy & Security > Automation > allow your terminal to control Chrome')
        sys.exit('Chrome automation failed: ' + stderr)
    return done.stdout.strip()


def run_js(url_prefix, code):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as handle:
        handle.write(code)
        path = handle.name
    try:
        raw = osascript(['eval', url_prefix, path])
    finally:
        os.unlink(path)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {'error': 'unexpected reply from Chrome: ' + raw[:300]}
    if isinstance(result, dict) and 'Apple Events' in str(result.get('error', '')):
        sys.exit('Chrome will not run JavaScript for scripts yet.\n'
                 '  Turn it on once: Chrome menu bar > View > Developer > Allow JavaScript from Apple Events\n'
                 '  Then run this command again.')
    return result


def open_in_chrome(url):
    subprocess.run(['open', '-a', 'Google Chrome', url], check=False)


def tab_prefix(url):
    """Match a tab by scheme+host+path, ignoring any query or fragment."""
    return url.split('?')[0].split('#')[0]


def wait_for_page(url, recipe, wait_seconds):
    """Wait until the page is loaded and not a login page, prompting once if a login is needed."""
    prefix = tab_prefix(url)
    login = json.dumps(recipe.get('loginWhen')) if recipe.get('loginWhen') else 'null'
    wait_for = json.dumps(recipe.get('waitFor')) if recipe.get('waitFor') else 'null'
    code = STATUS_JS % (login, wait_for)

    asked = False
    missing_since = None
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        status = run_js(prefix, code)
        if status.get('error'):
            # A tab that never appears means Chrome opened it somewhere else, or the URL redirected.
            missing_since = missing_since or time.time()
            if time.time() - missing_since > 20:
                sys.exit('No Chrome tab whose address starts with:\n  %s\n'
                         'Chrome said: %s\n'
                         'Open the page yourself and run this again, or check the --url.'
                         % (prefix, status['error']))
            time.sleep(2)
            continue
        missing_since = None
        if status.get('ready') != 'complete' or not status.get('waitReady'):
            time.sleep(2)
            continue
        if status.get('loginNeeded'):
            if not asked:
                print('LOGIN NEEDED: "%s" is showing a sign-in page.' % status.get('title', ''))
                print('Log in in the Chrome window that just opened; this keeps waiting (%ds).' % wait_seconds)
                asked = True
            time.sleep(3)
            continue
        return status
    sys.exit('Gave up after %ds. Page never became ready (log in, then run the command again).' % wait_seconds)


def extract(url, recipe):
    payload = dict(recipe)
    payload.setdefault('text', not recipe.get('fields'))
    return run_js(tab_prefix(url), EXTRACT_JS % json.dumps(payload))


def render(result):
    """Plain text for reading; lists become numbered blocks."""
    lines = ['# %s' % result.get('title', ''), result.get('url', ''), '']
    data = result.get('data', {})
    for name, value in data.items():
        if isinstance(value, list):
            lines.append('%s (%d):' % (name, len(value)))
            for n, item in enumerate(value, 1):
                if isinstance(item, dict):
                    lines.append('  %d.' % n)
                    for key, val in item.items():
                        lines.append('     %-12s %s' % (key + ':', val))
                else:
                    lines.append('  %d. %s' % (n, item))
            lines.append('')
        elif name == 'text':
            lines += ['text:', value, '']
        else:
            lines.append('%-14s %s' % (name + ':', value))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Scrape a page through your logged-in Chrome.')
    parser.add_argument('recipe', nargs='?', help='path to a recipe JSON file')
    parser.add_argument('--url', help='page to open (overrides the recipe url)')
    parser.add_argument('--file', help='read a page saved from the browser (Cmd+S) instead of using Chrome')
    parser.add_argument('--headless', action='store_true',
                        help="render with the scraper's own Chrome profile (no Apple Events needed)")
    parser.add_argument('--login', action='store_true',
                        help='open that profile in a normal window so you can log in, then close it')
    parser.add_argument('--profile', default=PROFILE_DIR, help='where that profile lives')
    parser.add_argument('--save-html', action='store_true', help='also keep the rendered HTML in pages/')
    parser.add_argument('--text', action='store_true', help='include the page text')
    parser.add_argument('--json', action='store_true', dest='as_json', help='print raw JSON')
    parser.add_argument('--wait', type=int, default=300, help='seconds to wait for load/login (default 300)')
    parser.add_argument('--keep-open', action='store_true', help='(tabs are always left open)')
    args = parser.parse_args()

    recipe = {}
    if args.recipe:
        with open(args.recipe) as handle:
            recipe = json.load(handle)
    if args.text:
        recipe['text'] = True

    if args.login:
        url = args.url or recipe.get('url')
        if not url:
            sys.exit('Give a --url or a recipe containing one.')
        chrome_login(url, args.profile)
        return

    if args.file:
        result = scrape_file(args.file, recipe)
    elif args.headless:
        url = args.url or recipe.get('url')
        if not url:
            sys.exit('Give a --url or a recipe containing one.')
        html = chrome_dump(url, args.profile, args.wait * 1000)
        if looks_like_login(html, recipe):
            sys.exit('That page is still showing a login. Run the same command with --login, '
                     'sign in, close that window, then try again.')
        if args.save_html:
            os.makedirs(PAGES_DIR, exist_ok=True)
            path = os.path.join(PAGES_DIR, '%s-%s.html' % (recipe.get('name') or 'page',
                                                           time.strftime('%Y%m%d-%H%M%S')))
            with open(path, 'w') as handle:
                handle.write(html)
            print('rendered HTML: %s' % path)
        result = result_from_html(html, url, recipe)
    else:
        url = args.url or recipe.get('url')
        if not url:
            sys.exit('Give a --url, a --file, or a recipe containing a url.')
        open_in_chrome(url)
        time.sleep(2)
        wait_for_page(url, recipe, args.wait)
        result = extract(url, recipe)
        if result.get('error'):
            sys.exit('Extract failed: %s' % result['error'])

    output = json.dumps(result, indent=2, ensure_ascii=False) if args.as_json else render(result)
    print(output)

    os.makedirs(OUT_DIR, exist_ok=True)
    name = recipe.get('name') or 'page'
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = os.path.join(OUT_DIR, '%s-%s.json' % (name, stamp))
    with open(path, 'w') as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    print('\nsaved: %s' % path)


if __name__ == '__main__':
    main()
