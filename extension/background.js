// The extension's engine: watches the linked Vollna tab, decides on each new job, sends it to the
// relay and alerts Telegram when something goes wrong. Ports of auto.py, reports.py and notify.py.
//
// Everything lives in chrome.storage.local, so the popup and the control panel redraw from
// storage.onChanged and a restarted service worker carries on where the last one stopped.
import * as rules from './rules.js';

const ITEMS = ['Job title', 'Job link', 'Job description', 'Screening Questions', 'Project info',
  'Client info', 'Work history', 'Client name'];
const DEFAULT_EXTRACT = ['Job title', 'Job link', 'Job description', 'Project info', 'Client info'];
const DEFAULT_SEND = ['Job title', 'Job link', 'Job description'];
const PROJECT_CATEGORIES = ['Time per week', 'Project period', 'Expecting level', 'Project type'];
const CLIENT_CATEGORIES = ['Client Rank', 'Payment method verified', 'total spent', 'Hired number',
  'active job', 'Posted job', 'Hire rate', 'Opened job', 'avg hourly rate', 'total hours',
  'review score', 'review number', 'Registered', 'country', 'Region'];
const JOB_TYPES = ['job', 'alert', 'invite', 'message', 'email', 'test'];
const MAX_HANDLED = 200;
const LOAD_ATTEMPTS = 3;       // a page that will not load is tried this many times before stopping
const LOAD_TIMEOUT = 60000;    // how long one load may take before it counts as not loading
const CATCH_UP_DEPTH = 25;     // how far down the page to look for the last job before giving up
const LIST_TOP = 10;           // the jobs compared from one check to the next to tell the list changed

const DEFAULTS = {
  settings: { projectName: 'vollna-scraper', telegramToken: '', telegramChat: '',
    extract: DEFAULT_EXTRACT, send: DEFAULT_SEND, interval: 120, reloadAfter: 1800 },
  link: null,                  // {tabId, url, title, at}
  // listTop: the top of the job list last seen; changedAt: when it last changed (or the tab was
  // reloaded); the tab is reloaded only when that is longer ago than settings.reloadAfter
  watch: { running: false, checked: null, error: null, note: null, catchUp: null, listTop: [],
    changedAt: 0, reloaded: null },
  jobs: { handled: [], seen: [], last: {} },
  relay: { relayUrl: '', serverId: '', channels: [], channel: '', threads: [], noticeKeys: [],
    lastPoll: null },
};

// ---------------------------------------------------------------- storage

async function load(key) {
  const found = (await chrome.storage.local.get(key))[key];
  return found === undefined ? structuredClone(DEFAULTS[key]) : found;
}
const save = (key, value) => chrome.storage.local.set({ [key]: value });
async function update(key, changes) {
  const value = Object.assign(await load(key), changes);
  await save(key, value);
  return value;
}

const pad = (n) => String(n).padStart(2, '0');
function now(seconds = false) {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    + (seconds ? ':' + pad(d.getSeconds()) : '');
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const escapeHtml = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function isVollna(url) {
  try {
    const host = new URL(url).hostname;
    return host === 'vollna.com' || host.endsWith('.vollna.com');
  } catch (e) { return false; }
}

// ---------------------------------------------------------------- Telegram (notify.py)

// Send text to the configured chat. Returns 'sent' or why not; never throws. An error alert gets a
// red cross before the project name, so it stands out in the chat at a glance.
async function telegram(text, error = false) {
  const { telegramToken: token, telegramChat: chat, projectName } = await load('settings');
  if (!token || !chat) return 'not sent: save a Telegram bot token and chat id on the Profile tab';
  const message = `${error ? '❌ ' : ''}<b>${escapeHtml(projectName || 'vollna-scraper')}</b>\n${escapeHtml(String(text).slice(0, 3900))}`;
  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chat, text: message, parse_mode: 'HTML', disable_web_page_preview: true }),
    });
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) return `not sent: Telegram answered ${response.status}: ${String(answer.description || '').slice(0, 150)}`;
    return answer.ok ? 'sent' : 'not sent: ' + JSON.stringify(answer).slice(0, 150);
  } catch (problem) {
    return 'not sent: Telegram unreachable: ' + problem.message;
  }
}

// ---------------------------------------------------------------- relay (reports.py)

async function relay(path, method = 'GET', payload = undefined) {
  const data = await load('relay');
  // the relay address is remembered from the registration; the id doubles as the bearer token
  const base = (data.relayUrl || '').replace(/\/+$/, '');
  if (!base) throw new Error('No server yet. Use New -> Register me with the server URL.');
  if (!data.serverId) throw new Error('This project is not registered yet, so it has no id to talk with.');
  let response;
  try {
    response = await fetch(base + path, {
      method, headers: { Authorization: 'Bearer ' + data.serverId, 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
  } catch (problem) {
    throw new Error('Relay unreachable: ' + problem.message);
  }
  const body = await response.text();
  if (!response.ok) throw new Error(`Relay answered ${response.status}: ${body.slice(0, 200)}`);
  return body.trim() ? JSON.parse(body) : {};
}

// POST or GET any server (registration lives outside the relay): [status, answer]
async function callJson(url, payload) {
  let response;
  try {
    response = await fetch(url, payload === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
  } catch (problem) {
    throw new Error('Server unreachable: ' + problem.message);
  }
  const raw = await response.text();
  if (!response.ok) throw new Error(`Server answered ${response.status}: ${raw.slice(0, 200)}`);
  try { return [response.status, raw.trim() ? JSON.parse(raw) : {}]; } catch (e) { return [response.status, { raw: raw.slice(0, 500) }]; }
}

// Try the plain registration call, then the relay's own /enrol, so either kind of server works
async function attemptRegister(url, name) {
  const base = url.replace(/\/+$/, '');
  const attempts = /\/(enrol|enroll|register)$/.test(base)
    ? [[base, { name, label: 'Vollna scraper', type: 'register' }]]
    : [[base, { type: 'register', name }], [base + '/enrol', { name, label: 'Vollna scraper' }]];
  const problems = [];
  for (const [endpoint, payload] of attempts) {
    try {
      const [code, answer] = await callJson(endpoint, payload);
      if (answer && typeof answer.raw === 'string' && answer.raw.trimStart().startsWith('<')) {
        problems.push(`${endpoint} -> answered HTML, not a registration endpoint`);
        continue;
      }
      return [endpoint, code, answer];
    } catch (problem) {
      problems.push(`${endpoint} -> ${problem.message}`);
    }
  }
  throw new Error('Registration failed. ' + problems.join('; '));
}

// [id, status] from whatever shape the server replied with
function verdict(answer) {
  if (!answer || typeof answer !== 'object') return [null, 'waiting'];
  const given = answer.id || answer.worker_id || answer.workerId || answer.assignedId;
  const state = String(answer.status || '').toLowerCase();
  if (['pending', 'waiting', 'queued'].includes(state)) return [given ? String(given) : null, 'waiting'];
  if (['registered', 'approved', 'active', 'ok'].includes(state)) return [given ? String(given) : null, 'approved'];
  if (given) return [String(given), 'approved'];
  return [null, 'waiting'];
}

const noteOf = (answer) => (answer && answer.message) || JSON.stringify(answer).slice(0, 400);
const stripEnrol = (url) => url.replace(/\/+$/, '').replace(/\/enrol$/, '');

async function register(url) {
  const data = await load('relay');
  const name = (await load('settings')).projectName || 'vollna-scraper';
  const [endpoint, code, answer] = await attemptRegister(url, name);
  const [given, state] = verdict(answer);
  const thread = {
    id: 'register-' + Date.now(), title: 'Register me: ' + name, kind: 'register', url: endpoint,
    status: state === 'approved' && given ? 'registered' : state, serverId: given, completed: false,
    created: now(), ticket: (answer && answer.ticket) || null,
    messages: [{ from: 'me', text: `Registration request sent to ${endpoint} as "${name}".`, at: now() },
      { from: 'server', text: `Answered ${code}: ${noteOf(answer)}`, at: now() }],
  };
  if (thread.ticket) thread.messages.push({ from: 'me', text: `Ticket: ${thread.ticket} — use Request again to ask what came of it.`, at: now() });
  data.relayUrl = stripEnrol(endpoint);
  if (state === 'approved' && given) data.serverId = given;
  data.threads.unshift(thread);
  await save('relay', data);
  return thread;
}

// Ask once more, for a registration still waiting for approval
async function requestAgain(threadId) {
  const data = await load('relay');
  const found = data.threads.find((t) => t.id === threadId);
  if (!found || found.kind !== 'register') throw new Error('That is not a registration request.');
  let code, answer;
  if (found.ticket) {
    // the relay keeps the answer under the ticket: ask about that, do not register again
    [code, answer] = await callJson(`${stripEnrol(found.url)}/enrol/${found.ticket}`);
  } else {
    let endpoint;
    [endpoint, code, answer] = await attemptRegister(found.url, (await load('settings')).projectName);
    found.url = endpoint;
  }
  if (answer && answer.ticket) found.ticket = answer.ticket;
  found.messages.push({ from: 'me', text: 'Asked again.', at: now() },
    { from: 'server', text: `Answered ${code}: ${noteOf(answer)}`, at: now() });
  const [given, state] = verdict(answer);
  if (given) found.serverId = given;
  found.status = state === 'approved' && given ? 'registered' : state;
  if (state === 'approved' && given) {
    found.messages.push({ from: 'server', text: `Registered. Your id is ${given}.`, at: now() });
    data.serverId = given;
  }
  await save('relay', data);
  return found;
}

// Ask the server what came of any registration still waiting. This needs no id: before approval the
// project has nothing to authenticate with, so the ticket is the only way the answer can reach us.
async function checkTickets() {
  const data = await load('relay');
  let changed = 0;
  for (const thread of data.threads) {
    if (thread.kind !== 'register' || thread.status === 'registered' || !thread.ticket) continue;
    let answer;
    try { [, answer] = await callJson(`${stripEnrol(thread.url)}/enrol/${thread.ticket}`); } catch (e) { continue; }
    const [given, state] = verdict(answer);
    if (!given || state !== 'approved') continue;
    thread.serverId = given;
    thread.status = 'registered';
    thread.messages.push({ from: 'server', text: `Registered. Your id is ${given}.\n${noteOf(answer)}`, at: now() });
    data.serverId = given;
    data.relayUrl = data.relayUrl || stripEnrol(thread.url);
    changed++;
  }
  if (changed) await save('relay', data);
  return changed;
}

const JOIN_WORDS = ['join', 'added', 'add', 'member', 'allocat', 'assign', 'grant', 'subscrib', 'invite'];
const LEAVE_WORDS = ['left', 'leave', 'remov', 'revok', 'unsubscrib', 'kick', 'delet'];

// ['join' | 'leave' | null, [channel names]] read out of one server notice
function noticeChange(notice) {
  let names, words;
  if (notice && typeof notice === 'object') {
    names = notice.channels || notice.channel || [];
    names = typeof names === 'string' ? [names] : [...names];
    names = names.map((n) => (n && typeof n === 'object' ? n.name : n));
    words = ['type', 'kind', 'event', 'action', 'text', 'message'].map((k) => String(notice[k] || '')).join(' ');
    if (!names.length) names = [...words.matchAll(/#([\w.-]+)/g)].map((m) => m[1]);
  } else {
    words = String(notice);
    names = [...words.matchAll(/#([\w.-]+)/g)].map((m) => m[1]);
  }
  names = names.filter(Boolean).map((n) => String(n).replace(/^#+/, ''));
  const lowered = words.toLowerCase();
  if (LEAVE_WORDS.some((w) => lowered.includes(w))) return ['leave', names];
  if (JOIN_WORDS.some((w) => lowered.includes(w)) || names.length) return ['join', names];
  return [null, names];
}

function noticeKey(notice) {
  if (notice && typeof notice === 'object') {
    for (const key of ['id', 'seq', 'notice_id']) if (notice[key] != null) return `${key}:${notice[key]}`;
  }
  return JSON.stringify(notice);
}

function textOf(body) {
  if (typeof body === 'string') return body;
  if (body && typeof body === 'object') {
    for (const key of ['text', 'message', 'instruction', 'body', 'content']) if (typeof body[key] === 'string') return body[key];
  }
  return JSON.stringify(body);
}

function fileNotices(data, notices) {
  const seen = new Set(data.noticeKeys);
  const channels = new Set(data.channels);
  let fresh = 0;
  for (const notice of notices) {
    const key = noticeKey(notice);
    if (seen.has(key)) continue;            // a notice the relay repeats is still one notice
    seen.add(key);
    data.noticeKeys.push(key);
    const [action, names] = noticeChange(notice);
    if (action === 'join') names.forEach((n) => channels.add(n));
    if (action === 'leave') names.forEach((n) => channels.delete(n));
    let thread = data.threads.find((t) => t.id === 'notices');
    if (!thread) {
      thread = { id: 'notices', title: 'Server notices', kind: 'notices', completed: false, created: now(), messages: [] };
      data.threads.unshift(thread);
    }
    thread.messages.push({ from: 'server', text: textOf(notice), at: now() });
    fresh++;
  }
  data.noticeKeys = data.noticeKeys.slice(-200);
  data.channels = [...channels].sort();
  return fresh;
}

// Where to post: the chosen channel if the server allocated it, else the first allocated
function jobChannel(data) {
  if (!data.channels.length) return null;
  return data.channels.includes(data.channel) ? data.channel : data.channels[0];
}

let polling = null;
// Fetch anything new from the relay and file it into threads. One poll at a time.
function poll() {
  polling = polling || pollOnce().finally(() => { polling = null; });
  return polling;
}

async function pollOnce() {
  await checkTickets();
  if (!(await load('relay')).serverId) return 0;     // registration comes first
  const answer = await relay('/messages?wait=0&limit=50');
  const data = await load('relay');
  let added = fileNotices(data, answer.notices || []);
  if (Array.isArray(answer.channels)) {
    // the relay listing our channels outright is the final word
    data.channels = answer.channels.map((c) => String(c && typeof c === 'object' ? c.name : c)).sort();
  }
  data.lastPoll = now(true);
  for (const message of answer.messages || []) {
    const { body, channel, seq } = message;
    if (channel && !data.channels.includes(channel)) data.channels = [...data.channels, channel].sort();
    const isObject = body && typeof body === 'object';
    const given = isObject ? body.id || body.workerId || body.assignedId : null;
    const kind = isObject ? body.type : null;
    if (given && (['register-approved', 'registered', 'approval'].includes(kind) || String(kind || '').includes('register'))) {
      const waiting = data.threads.find((t) => t.kind === 'register' && t.status !== 'approved');
      if (waiting) {
        waiting.serverId = String(given);
        waiting.status = 'registered';
        waiting.messages.push({ from: 'server', text: `Approved. Your id is ${given}.`, at: now(), seq });
        data.serverId = String(given);
        added++;
      }
    } else if (!(isObject && (JOB_TYPES.includes(body.type) || ['vollna', 'upwork'].includes(body.source)))) {
      const threadId = (isObject && body.threadId) || `relay-${channel}-${seq}`;
      let thread = data.threads.find((t) => t.id === threadId);
      if (!thread) {
        const title = (isObject && body.title) || textOf(body).trim().split('\n')[0].slice(0, 70);
        thread = { id: threadId, title: title || 'Message from server', channel, completed: false, created: now(), messages: [] };
        data.threads.unshift(thread);
      }
      data.channel = data.channel || channel;
      thread.messages.push({ from: 'server', text: textOf(body), at: now(), seq });
      added++;
    }
    if (channel != null && seq != null) {
      try { await relay('/ack', 'POST', { channel, seq }); } catch (e) { /* delivered again next time */ }
    }
  }
  await save('relay', data);
  return added;
}

async function sendReport(threadId, text) {
  const data = await load('relay');
  const found = data.threads.find((t) => t.id === threadId);
  if (!found) throw new Error('No such conversation.');
  if (found.completed) throw new Error('This conversation is completed; reopen it to write.');
  if (!data.serverId) throw new Error('Not registered yet: only the registration request and asking again are allowed.');
  const channel = data.channels.includes(found.channel) ? found.channel : jobChannel(data);
  if (!channel) throw new Error('No channel allocated yet: the server has to add this project to a channel first.');
  await relay('/publish', 'POST', { channel, id: `report-${threadId}-${Date.now()}`,
    body: { type: 'report', threadId, text, from: data.serverId } });
  const fresh = await load('relay');           // the publish may have taken a while
  const thread = fresh.threads.find((t) => t.id === threadId);
  thread.messages.push({ from: 'me', text, at: now() });
  await save('relay', fresh);
  return thread;
}

async function setCompleted(threadId, done) {
  const data = await load('relay');
  const found = data.threads.find((t) => t.id === threadId);
  if (!found) throw new Error('No such conversation.');
  found.completed = !!done;
  const channel = data.channels.includes(found.channel) ? found.channel : jobChannel(data);
  if (done && data.serverId && channel) {
    try {
      await relay('/publish', 'POST', { channel, id: `report-done-${threadId}-${Date.now()}`,
        body: { type: 'report-complete', threadId } });
      found.messages.push({ from: 'me', text: '(marked completed)', at: now() });
    } catch (e) { /* completing locally must work even when the relay is down */ }
  }
  await save('relay', data);
  return found;
}

async function newRequest(title, text) {
  const data = await load('relay');
  if (!data.serverId) throw new Error('Not registered yet.');
  const channel = jobChannel(data);
  if (!channel) throw new Error('No channel allocated yet.');
  const id = 'local-' + Date.now();
  data.threads.unshift({ id, title: title || text.trim().split('\n')[0].slice(0, 70), channel,
    completed: false, created: now(), messages: [] });
  await save('relay', data);
  return sendReport(id, text);
}

// ---------------------------------------------------------------- reading the linked tab

// The linked page as it stands: {url, rows, login, denied, account}.
//
// The tab is not reloaded for a check. Vollna's filter page adds new jobs to itself as they are
// posted, so reading what the tab shows is enough. It is only (re)loaded when its job list has not
// changed for longer than the reload setting (stale), or when it has no job list to read: the list
// failed to arrive, Chrome unloaded the tab to save memory, or the tab was moved to another Vollna
// page. A page that was (re)loaded comes back with reloaded: true.
async function readTab(tabId, url, stale = false) {
  const tab = await chrome.tabs.get(tabId);
  const here = samePage(tab.url, url);
  if (!stale && !tab.discarded && tab.status === 'complete') {
    const page = await readPage(tabId);
    // a sign-in page is the answer wherever Vollna sent the tab (it redirects there when logged out)
    if (page.login || (here && (page.rows.length || page.denied))) return page;
  }
  return Object.assign(await loadPage(tabId, url, !here), { reloaded: true });
}

const samePage = (a, b) => String(a || '').replace(/[#?].*$/, '').replace(/\/+$/, '')
  === String(b || '').replace(/[#?].*$/, '').replace(/\/+$/, '');

async function readPage(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ['parse.js'] });
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: () => {
    const html = document.documentElement.outerHTML;
    const context = VollnaParse.pageContext(html);
    return { url: location.href, rows: VollnaParse.parseRows(html).filter((r) => r.projectId),
      login: VollnaParse.needsLogin(html), denied: context.accessDenied, account: context.account };
  } });
  return result.result;
}

// Wait for the page to show job rows, a sign-in page or a refusal, loading it first when asked to (a
// tab still loading the right page is just waited for). Throws after LOAD_TIMEOUT.
async function loadPage(tabId, url, navigate) {
  if (navigate) await chrome.tabs.update(tabId, { url });
  else {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete' || tab.discarded) await chrome.tabs.reload(tabId);
  }
  const until = Date.now() + LOAD_TIMEOUT;
  let loaded = false;
  await sleep(1500);
  while (Date.now() < until) {
    let state = null;
    try {
      const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: () => ({
        url: location.href, ready: document.readyState,
        rows: document.querySelectorAll('[data-project-context]').length,
        password: !!document.querySelector('input[type="password"]'),
        denied: /do(?:n['’]t| not) have access to this page/i.test(document.body ? document.body.innerText : ''),
      }) });
      state = result && result.result;
    } catch (e) { /* the page is between documents: try again */ }
    if (state && !isVollna(state.url)) throw new OutOfMind(state.url);
    // Rows on the page: give the rest of the list a moment to arrive, then read it. A page without
    // rows is not taken as an empty filter: a feed always lists recent jobs, and Vollna sometimes
    // serves the page while the request that brings the list (POST /load/<filter>) hangs, which
    // must not pass for "no new jobs".
    loaded = loaded || (state && state.ready === 'complete');
    if (state && (state.rows || state.password || state.denied)) {
      await sleep(1500);
      return readPage(tabId);
    }
    await sleep(2000);
  }
  throw new Error(loaded
    ? `Vollna's job list did not load within ${LOAD_TIMEOUT / 1000}s (the page opened, but no jobs arrived)`
    : `the Vollna page did not load within ${LOAD_TIMEOUT / 1000}s`);
}

// Work history and the client's name, fetched only when the sidebar asks for them. Read inside the
// Vollna tab, so it goes out with the tab's own login. Vollna answers {"success":false} (HTTP 429)
// once its rate limit is reached.
async function extras(tabId, row, wanted) {
  if (!(wanted.includes('Work history') || wanted.includes('Client name')) || !row.projectId) return [null, null, 0];
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['parse.js'] });
    const [result] = await chrome.scripting.executeScript({ target: { tabId }, args: [row.projectId], func: async (id) => {
      const response = await fetch(`/project/${id}/work-history`, { credentials: 'include' });
      const payload = JSON.parse(await response.text());
      if (!payload || typeof payload !== 'object' || payload.success === false) {
        throw new Error('Vollna refused: ' + JSON.stringify(payload).slice(0, 80));
      }
      const history = VollnaParse.parseWorkHistory(payload.content || '');
      return { history, name: VollnaParse.clientName(history) };
    } });
    if (!result || !result.result) throw new Error('no answer');
    const { history, name } = result.result;
    const [clientName, mentions] = wanted.includes('Client name') ? name : [null, 0];
    return [wanted.includes('Work history') ? history : null, clientName, mentions];
  } catch (e) {
    row.historyUnreadable = true;               // a missing history must not stop the run
    return [null, null, 0];
  }
}

// ---------------------------------------------------------------- the watcher (auto.py)

class OutOfMind extends Error {
  constructor(url) {
    super('the linked tab is not on Vollna any more: ' + url);
    this.url = url;
  }
}

const lines = (value) => (typeof value === 'string' ? value.split('\n').map((s) => s.trim()).filter(Boolean) : []);

// The message as plain text, one thing per line
function jobText(row, decision, why, send) {
  const block = [`Decision: ${decision}`, `Reason: ${why}`, `Project id: ${row.projectId}`, ''];
  if (send.includes('Job title')) block.push(`Job title: ${row['Job title'] || '(not found)'}`);
  if (send.includes('Job link')) block.push(`Job link: ${row['Job link'] || '(not found)'}`);
  if (send.includes('Client name')) {
    const found = row.clientName || {};
    block.push('Client name: ' + (found.name
      ? `${found.name} (named in ${found.mentions} feedback${found.mentions === 1 ? '' : 's'})`
      : '(no name written in any feedback)'));
  }
  if (send.includes('Job description')) block.push('', 'Job description:', ...lines(row['Job description'] || ''));
  if (send.includes('Screening Questions')) {
    const asked = row['Screening Questions'] || [];
    block.push('', 'Screening Questions:', ...(asked.length ? asked.map((q, n) => `  ${n + 1}. ${q}`) : ['  (none)']));
  }
  for (const [item, key, fields] of [['Project info', 'project', PROJECT_CATEGORIES], ['Client info', 'client', CLIENT_CATEGORIES]]) {
    if (send.includes(item)) {
      const values = row[key] || {};
      block.push('', item + ':', ...fields.map((name) => `  ${name}: ${values[name] || '(not found)'}`));
    }
  }
  if (send.includes('Work history') && row.historyUnreadable) {
    block.push('', 'Work history: unreadable');
  } else if (send.includes('Work history')) {
    const history = row.history || [];
    block.push('', `Work history (${history.length} past contract${history.length === 1 ? '' : 's'}):`);
    let done = 0;
    for (const entry of history) {
      const mark = entry.status === 'in progress' ? 'in progress' : '#' + (++done);
      block.push(`  ${mark} ${entry['job title'] || '(no title)'}`);
      if (entry['payment type'] === 'fixed') {
        block.push(`      ${entry['Project period'] || '?'} | fixed price | billed ${entry['total billed'] || '?'}`);
      } else {
        block.push(`      ${entry['Project period'] || '?'} | ${entry['project time commitment'] || '?'} | ${entry['hourly rate'] || '?'} | billed ${entry['total billed'] || '?'}`);
      }
      for (const [score, text, who] of [['feedback score to freelancer', 'written feedback to freelancer', 'to freelancer'],
        ['feedback score to client', 'written feedback to client', 'to client']]) {
        if (entry[score]) block.push(`      ${who} ${entry[score]}: ${entry[text] || '(no text)'}`);
      }
    }
  }
  return block.join('\n').trim();
}

// Publish the decision and the chosen fields. A skip is refused here too: nothing about a skipped
// job ever leaves the project. The id is always "job-<projectId>", so the relay's own duplicate
// check stops the same job being sent twice.
async function sendJob(row, decision, why, send) {
  if (decision === rules.SKIP) return 'not sent (skip)';
  const data = await load('relay');
  if (!data.serverId) return 'not sent: this project is not registered yet';
  const channel = jobChannel(data);
  if (!channel) return 'not sent: the server has not allocated a channel to this project';
  try {
    const answer = await relay('/publish', 'POST', { channel, id: 'job-' + row.projectId, body: jobText(row, decision, why, send) });
    if (answer.duplicate) return 'not sent (duplicate): the server already holds this job';
  } catch (problem) {
    return 'failed: ' + problem.message.slice(0, 120);
  }
  return 'sent';
}

// The jobs to handle on the first check after starting, and a note saying why
function missedJobs(rows, seen, catchUp, jobs, url, watch) {
  if (!catchUp) {
    watch.note = 'Started without sending missed jobs: only jobs posted from now on are handled.';
    return [];
  }
  const top = rows.slice(0, CATCH_UP_DEPTH);
  const ids = top.map((r) => r.projectId);
  let remembered = jobs.last[url] || {};
  let last = remembered.projectId;
  if (!last) {
    // nothing remembered for this page: the newest job on it that was already seen marks the place
    last = ids.find((id) => seen.has(id)) || null;
    remembered = { title: (top.find((r) => r.projectId === last) || {})['Job title'] };
  }
  let missed;
  if (last && ids.includes(last)) {
    missed = top.slice(0, ids.indexOf(last));
    watch.note = `Caught up: ${missed.length} job(s) were posted above the last one checked (${(remembered.title || '').slice(0, 60)}).`;
  } else {
    missed = top;
    watch.note = `The last job checked was not in the top ${CATCH_UP_DEPTH}${last ? '' : ' (none remembered for this page)'}, so the top ${missed.length} were analysed.`;
  }
  return missed.filter((r) => !seen.has(r.projectId));
}

// One pass: read the page, handle jobs not seen before
async function handleOnce() {
  const link = await load('link');
  if (!link) throw new Error('no tab is linked');
  let tab;
  try { tab = await chrome.tabs.get(link.tabId); } catch (e) { throw new Error('the linked tab was closed'); }
  if (!isVollna(tab.url || tab.pendingUrl || '')) throw new OutOfMind(tab.url);

  const before = await load('watch');
  const { reloadAfter } = await load('settings');
  // Vollna's own refresh can stall without the page saying so: a list unchanged for longer than the
  // setting gets one reload, and the wait starts again from there
  const stale = Date.now() - (before.changedAt || 0) > (reloadAfter || 1800) * 1000;
  let page, problem;
  for (let attempt = 0; attempt < LOAD_ATTEMPTS && !page; attempt++) {
    try { page = await readTab(link.tabId, link.url, stale && attempt === 0); } catch (e) {
      if (e instanceof OutOfMind) throw e;
      problem = e;
      if (!(await load('watch')).running) return;          // stopped by hand meanwhile
      await sleep(10000);
    }
  }
  if (!page) throw problem;
  if (page.denied) throw new Error('this Vollna account has no access to that page');
  // a logged-out tab shows the sign-in page, which parses as a feed with no jobs at all
  if (page.login) throw new Error('the linked tab is logged out of Vollna: log in there, then start watching again');

  const settings = await load('settings');
  const jobs = await load('jobs');
  const watch = await load('watch');
  const seen = new Set(jobs.seen);
  const rows = page.rows;
  if (page.reloaded) Object.assign(watch, { changedAt: Date.now(), reloaded: now() });
  const top = rows.slice(0, LIST_TOP).map((r) => r.projectId);
  if (top.join() !== (watch.listTop || []).join()) {
    // a new job at the top (or any reshuffle) is a change: the reload wait starts again
    Object.assign(watch, { listTop: top, changedAt: Date.now() });
  }
  let fresh;
  if (watch.catchUp !== null) {
    fresh = missedJobs(rows, seen, watch.catchUp, jobs, link.url, watch);
    rows.forEach((r) => seen.add(r.projectId));      // the rest of the page counts as seen
    watch.catchUp = null;
  } else {
    fresh = rows.filter((r) => !seen.has(r.projectId));
  }

  const handledNow = [];
  for (const row of fresh) {
    seen.add(row.projectId);
    // decided before the work-history lookup, so a job that is plainly not software work does not
    // spend one of the lookups Vollna rate-limits
    const other = rules.unrelated(row['Job title'], row.skills, row['Job description']);
    let history = null, name = null, mentions = 0, decision, why;
    if (other) {
      [decision, why] = [rules.SKIP, `not software work: "${other}" and nothing technical`];
    } else {
      [history, name, mentions] = await extras(link.tabId, row, settings.extract);
      [decision, why] = rules.decide(row.client);
    }
    row.history = history;
    row.clientName = name || settings.extract.includes('Client name') ? { name, mentions } : null;
    const status = await sendJob(row, decision, why, settings.send);
    handledNow.push({ at: now(), title: row['Job title'], link: row['Job link'], decision, why, status,
      projectId: row.projectId, clientName: row.clientName ? row.clientName.name : null,
      historyCount: history !== null ? history.length : null, historyUnreadable: !!row.historyUnreadable });
  }
  watch.checked = now();
  if (rows.length) {
    // the newest job looked at on this page: where the next start picks up from
    jobs.last[link.url] = { projectId: rows[0].projectId, title: rows[0]['Job title'], at: watch.checked };
  }
  jobs.handled = handledNow.reverse().concat(jobs.handled).slice(0, MAX_HANDLED);
  jobs.seen = [...seen].slice(-500);
  await save('jobs', jobs);
  await update('watch', { checked: watch.checked, note: watch.note, catchUp: watch.catchUp, error: null,
    listTop: watch.listTop, changedAt: watch.changedAt, reloaded: watch.reloaded });
  const failed = handledNow.filter((h) => h.status.startsWith('failed'));
  // a job the server never got is lost unless someone hears about it
  if (failed.length) throw new Error(`${failed.length} job(s) could not be sent to the server: ${failed[0].status}`);
}

let checking = null;
function check() {
  checking = checking || checkOnce().finally(() => { checking = null; });
  return checking;
}

async function checkOnce() {
  if (!(await load('watch')).running) return;
  try {
    await handleOnce();
  } catch (problem) {
    if (!(await load('watch')).running) return;      // stopped by hand mid-check: nothing to report
    // Watching on after an error only repeats it (a logged-out tab, a page that will not load), so
    // stop and alert a person, who can fix it and start again.
    const link = (await load('link')) || {};
    const when = now();
    await stopWatching();
    const alert = problem instanceof OutOfMind
      ? await outOfMind(problem.url, 'The linked tab was moved off Vollna, so watching stopped.')
      : await telegram(`Stopped watching because of an error.\n\nError: ${problem.message.slice(0, 500)}\nPage: ${link.url}\nAt: ${when}`, true);
    await update('watch', { error: `${problem.message.slice(0, 200)} (${when}) · Telegram alert ${alert}` });
  }
}

// The alert for a tab that is not Vollna at all
function outOfMind(url, what) {
  return telegram(`\u{1F92A} You are out of your mind: that is not a Vollna page.\n\n${what}\nTab: ${url || '(no address)'}\n\n`
    + 'Open a vollna.com page and press "Link this tab" there.', true);
}

async function linkTab(tab) {
  if (!tab || !isVollna(tab.url || '')) {
    const alert = await outOfMind(tab && tab.url, 'Someone tried to link a tab that is not on vollna.com.');
    throw new Error(`This tab is not a Vollna page, so it was not linked. Telegram alert ${alert}.`);
  }
  if ((await load('watch')).running) throw new Error('Stop watching before linking another tab.');
  const link = { tabId: tab.id, url: tab.url, title: tab.title || tab.url, at: now() };
  const previous = await load('link');
  if (previous && previous.tabId !== tab.id) await keepLoaded(previous.tabId, false);
  await save('link', link);
  // Chrome's Memory Saver unloads idle background tabs; the linked one has to stay loaded, since its
  // own refresh is what brings in new jobs
  await keepLoaded(tab.id, true);
  return link;
}

async function keepLoaded(tabId, keep) {
  try { await chrome.tabs.update(tabId, { autoDiscardable: !keep }); } catch (e) { /* tab already gone */ }
}

async function startWatching(catchUp, interval, reloadAfter) {
  const link = await load('link');
  if (!link) throw new Error('Link a Vollna tab first.');
  const relayData = await load('relay');
  if (!relayData.serverId) throw new Error('Not registered with a server yet: use Report -> New -> Register me first.');
  if (!jobChannel(relayData)) throw new Error('The server has not allocated a channel to this project yet, so jobs would have nowhere to go.');
  const seconds = Math.max(30, parseInt(interval, 10) || 120);
  const reloadSeconds = Math.max(60, parseInt(reloadAfter, 10) || 1800);
  await update('settings', { interval: seconds, reloadAfter: reloadSeconds });
  await save('watch', { running: true, checked: (await load('watch')).checked, error: null, note: null,
    catchUp: !!catchUp, listTop: [], changedAt: Date.now(), reloaded: null });
  await chrome.alarms.create('watch', { periodInMinutes: seconds / 60 });
  check();
}

async function stopWatching() {
  await chrome.alarms.clear('watch');
  await update('watch', { running: false });
}

// ---------------------------------------------------------------- wiring

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'watch') check();
  if (alarm.name === 'relay') poll().catch(() => { /* shown as lastPoll going stale */ });
});

function ensureRelayAlarm() {
  chrome.alarms.get('relay', (found) => { if (!found) chrome.alarms.create('relay', { periodInMinutes: 1 }); });
}
chrome.runtime.onInstalled.addListener(ensureRelayAlarm);
chrome.runtime.onStartup.addListener(ensureRelayAlarm);

// a linked tab that is closed while watching stops the watcher at once, rather than at the next check
chrome.tabs.onRemoved.addListener(async (tabId) => {
  const link = await load('link');
  if (!link || link.tabId !== tabId) return;
  await save('link', null);
  if ((await load('watch')).running) {
    await stopWatching();
    const alert = await telegram(`Stopped watching: the linked Vollna tab was closed.\nPage: ${link.url}\nAt: ${now()}`, true);
    await update('watch', { error: `the linked tab was closed (${now()}) · Telegram alert ${alert}` });
  }
});

const handlers = {
  link: ({ tab }) => linkTab(tab),
  unlink: async () => {
    if ((await load('watch')).running) throw new Error('Stop watching first.');
    const link = await load('link');
    if (link) await keepLoaded(link.tabId, false);
    await save('link', null);
  },
  start: ({ catchUp, interval, reloadAfter }) => startWatching(catchUp, interval, reloadAfter),
  stop: () => stopWatching(),
  forget: () => save('jobs', structuredClone(DEFAULTS.jobs)),
  prefs: ({ extract, send }) => {
    const keep = (names) => (names || []).filter((n) => ITEMS.includes(n));
    return update('settings', { extract: keep(extract).length ? keep(extract) : DEFAULT_EXTRACT, send: keep(send) });
  },
  profile: ({ projectName }) => update('settings', { projectName: (projectName || '').trim() || 'vollna-scraper' }),
  telegram: async ({ token, chatId }) => {
    const settings = await load('settings');
    token = (token || '').trim() || settings.telegramToken;
    const chat = String(chatId || '').trim();
    if (!token || !chat) throw new Error('Give both the bot token and the chat id.');
    if (!token.includes(':')) throw new Error('That does not look like a bot token (it has the form 123456:ABC...).');
    await update('settings', { telegramToken: token, telegramChat: chat });
  },
  telegramTest: async () => {
    const result = await telegram('Test message: alerts from this extension will arrive here.');
    if (result !== 'sent') throw new Error('Test ' + result);
  },
  register: ({ url }) => register(url),
  again: ({ id }) => requestAgain(id),
  reply: ({ id, text }) => sendReport(id, text),
  complete: ({ id, done }) => setCompleted(id, done),
  newRequest: ({ title, text }) => newRequest(title, text),
  poll: () => poll(),
  // the Python project's reports.json and handled.json, so the relay registration and the jobs
  // already handled carry over instead of starting again
  import: async ({ reports, handled }) => {
    if (reports) {
      const data = await load('relay');
      for (const key of ['relayUrl', 'serverId', 'channels', 'channel', 'threads', 'noticeKeys']) {
        if (reports[key] !== undefined && reports[key] !== null) data[key] = reports[key];
      }
      await save('relay', data);
    }
    if (handled) {
      await save('jobs', { handled: (handled.handled || []).slice(0, MAX_HANDLED), seen: (handled.seen || []).slice(-500), last: handled.last || {} });
    }
  },
};

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  const handler = handlers[message.type];
  if (!handler) return false;
  Promise.resolve(handler(message))
    .then((result) => reply({ ok: true, result }))
    .catch((problem) => reply({ ok: false, error: problem.message }));
  return true;                                    // the answer comes asynchronously
});
