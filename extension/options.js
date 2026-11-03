// The control panel: what is read and sent, the jobs handled, the server conversations and the
// profile (project name, Telegram, moving over from the Python version).
const $ = (id) => document.getElementById(id);
const ITEMS = ['Job title', 'Job link', 'Job description', 'Screening Questions', 'Project info',
  'Client info', 'Work history', 'Client name'];
let openThread = null;

async function ask(type, extra = {}) {
  const answer = await chrome.runtime.sendMessage({ type, ...extra });
  if (!answer || !answer.ok) throw new Error((answer && answer.error) || 'No answer from the extension.');
  return answer.result;
}

function show(text, ok) {
  $('msg').textContent = text;
  $('msg').className = 'msg ' + (ok ? 'ok' : 'err');
}
const attempt = (work, done) => async () => {
  try { await work(); if (done) show(done, true); } catch (e) { show(e.message, false); }
};

// The relay is on its own address: Chrome asks once whether the extension may talk to it. This has to
// run straight from the click, before anything is awaited, or Chrome refuses to ask.
function allowServer(url) {
  let origin;
  try { origin = new URL(url).origin + '/*'; } catch (e) { return Promise.reject(new Error('That is not a web address.')); }
  return chrome.permissions.request({ origins: [origin] }).then((granted) => {
    if (!granted) throw new Error('Without permission to reach ' + origin.slice(0, -2) + ' the extension cannot talk to the server.');
  });
}

// ---------------------------------------------------------------- Workplace

function renderPicks(settings) {
  const extract = new Set(settings.extract || []);
  const send = new Set(settings.send || []);
  [['extractList', extract], ['sendList', send]].forEach(([id, chosen]) => {
    const box = $(id);
    box.innerHTML = '';
    for (const item of ITEMS) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = chosen.has(item);
      input.onchange = attempt(async () => {
        if (input.checked) chosen.add(item); else chosen.delete(item);
        if (id === 'sendList' && input.checked) extract.add(item);     // cannot send what is not read
        await ask('prefs', { extract: [...extract], send: [...send] });
      });
      label.append(input, ' ' + item);
      box.append(label);
    }
  });
}

function renderHandled(jobs, watch, link) {
  const bar = $('watchStatus');
  bar.className = 'status-bar ' + (watch.running ? 'ok' : watch.error ? 'err' : 'warn');
  bar.textContent = watch.running
    ? `Watching ${link ? link.url : ''}` + (watch.checked ? ` · last checked ${watch.checked}` : '')
    : watch.error ? 'Stopped: ' + watch.error : 'Not watching.';
  if (watch.note) bar.textContent += ' · ' + watch.note;
  const body = $('handled');
  body.innerHTML = '';
  for (const job of jobs.handled || []) {
    const row = document.createElement('tr');
    const at = document.createElement('td');
    at.textContent = job.at;
    const title = document.createElement('td');
    const anchor = document.createElement('a');
    anchor.href = job.link || '#';
    anchor.target = '_blank';
    anchor.textContent = job.title || job.projectId;
    title.append(anchor);
    const why = document.createElement('div');
    why.className = 'note';
    why.style.margin = '0';
    why.textContent = job.why + (job.historyUnreadable ? ' · work history unreadable' : '');
    title.append(why);
    const decision = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = 'pill ' + (job.decision === 'bid' ? 'bid' : job.decision === 'skip' ? 'skip' : 'manual');
    pill.textContent = job.decision;
    decision.append(pill);
    const sent = document.createElement('td');
    const status = document.createElement('span');
    status.className = 'pill ' + (job.status === 'sent' ? 'sent' : job.status.startsWith('failed') ? 'failed' : 'skip');
    status.textContent = job.status === 'sent' ? 'sent' : job.status.startsWith('failed') ? 'failed' : 'not sent';
    status.title = job.status;
    sent.append(status);
    row.append(at, title, decision, sent);
    body.append(row);
  }
  if (!body.children.length) body.innerHTML = '<tr><td colspan="4" class="muted">Nothing handled yet.</td></tr>';
}

$('forget').onclick = attempt(async () => {
  if (!confirm('Forget every job seen so far? The next check will treat them all as new.')) return;
  await ask('forget');
}, 'Cleared.');

// ---------------------------------------------------------------- Report

function renderReport(relay) {
  const list = $('threads');
  list.innerHTML = '';
  for (const thread of relay.threads || []) {
    const item = document.createElement('div');
    item.className = 'thread' + (thread.id === openThread ? ' active' : '') + (thread.completed ? ' done' : '');
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = thread.title;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${thread.created} · ${thread.messages.length} message${thread.messages.length === 1 ? '' : 's'}`
      + (thread.kind === 'register' ? ' · ' + thread.status : '');
    item.append(title, meta);
    item.onclick = () => { openThread = thread.id; renderReport(relay); };
    list.append(item);
  }
  if (!list.children.length) list.innerHTML = '<p class="muted">No conversations yet.</p>';
  $('relayInfo').textContent = relay.serverId
    ? `Registered as ${relay.serverId.slice(0, 6)}… · channel ${(relay.channels || []).join(', ') || 'none yet'} · last asked ${relay.lastPoll || 'never'}`
    : 'Not registered with a server yet.';

  const thread = (relay.threads || []).find((t) => t.id === openThread);
  $('threadView').classList.toggle('hidden', !thread);
  if (!thread) return;
  $('threadTitle').textContent = thread.title;
  $('again').classList.toggle('hidden', !(thread.kind === 'register' && thread.status !== 'registered'));
  $('complete').textContent = thread.completed ? 'Reopen' : 'Mark completed';
  const chat = $('chat');
  chat.innerHTML = '';
  for (const message of thread.messages) {
    const bubble = document.createElement('div');
    bubble.className = 'bubble ' + (message.from === 'me' ? 'me' : 'server');
    bubble.textContent = message.text;
    const when = document.createElement('span');
    when.className = 'when';
    when.textContent = message.at;
    bubble.append(when);
    chat.append(bubble);
  }
  chat.scrollTop = chat.scrollHeight;
}

$('pollNow').onclick = attempt(() => ask('poll'), 'Asked the server.');
$('again').onclick = attempt(() => ask('again', { id: openThread }));
$('complete').onclick = attempt(async () => {
  const { relay } = await chrome.storage.local.get('relay');
  const thread = relay.threads.find((t) => t.id === openThread);
  await ask('complete', { id: openThread, done: !thread.completed });
});
$('reply').onclick = attempt(async () => {
  const text = $('replyText').value.trim();
  if (!text) return;
  await ask('reply', { id: openThread, text });
  $('replyText').value = '';
});
$('register').onclick = () => {
  const url = $('registerUrl').value.trim();
  allowServer(url).then(() => ask('register', { url })).then((thread) => {
    openThread = thread.id;
    show('Registration sent.', true);
  }).catch((e) => show(e.message, false));
};
$('newSend').onclick = attempt(async () => {
  const text = $('newText').value.trim();
  if (!text) throw new Error('Write the request first.');
  const thread = await ask('newRequest', { title: $('newTitle').value.trim(), text });
  openThread = thread.id;
  $('newTitle').value = '';
  $('newText').value = '';
}, 'Request sent.');

// ---------------------------------------------------------------- Profile

function renderProfile(settings) {
  if (document.activeElement !== $('projectName')) $('projectName').value = settings.projectName || '';
  const set = settings.telegramToken && settings.telegramChat;
  const bar = $('tgStatus');
  bar.className = 'status-bar ' + (set ? '' : 'warn');
  bar.textContent = set
    ? `Alerts go to chat ${settings.telegramChat} with the bot token ending …${settings.telegramToken.slice(-4)}.`
    : 'Not set up: alerts are not sent.';
  if (document.activeElement !== $('tgChat')) $('tgChat').value = settings.telegramChat || '';
  $('tgTest').disabled = !set;
}

$('saveProject').onclick = attempt(() => ask('profile', { projectName: $('projectName').value }), 'Saved.');
$('tgSave').onclick = attempt(async () => {
  await ask('telegram', { token: $('tgToken').value, chatId: $('tgChat').value });
  $('tgToken').value = '';
}, 'Saved.');
$('tgTest').onclick = attempt(() => ask('telegramTest'), 'Test sent: check Telegram.');

const readJson = (input) => (input.files[0] ? input.files[0].text().then(JSON.parse) : Promise.resolve(null));
$('import').onclick = () => {
  // Chrome only shows the permission prompt for a short while after a click; reading two small
  // files first is quick enough to stay inside it
  Promise.all([readJson($('importReports')), readJson($('importHandled'))]).catch(() => {
    throw new Error('That file is not valid JSON.');
  }).then(([reports, handled]) => {
    if (!reports && !handled) throw new Error('Pick reports.json, handled.json or both.');
    const allowed = reports && reports.relayUrl ? allowServer(reports.relayUrl) : Promise.resolve();
    return allowed.then(() => ask('import', { reports, handled }));
  }).then(() => show('Imported.', true)).catch((e) => show(e.message, false));
};

// ---------------------------------------------------------------- tabs and redraw

function showTab(name) {
  ['workplace', 'report', 'profile'].forEach((tab) => $('tab-' + tab).classList.toggle('hidden', tab !== name));
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  location.hash = name;
}
document.querySelectorAll('.tab').forEach((button) => { button.onclick = () => showTab(button.dataset.tab); });
showTab(['workplace', 'report', 'profile'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'workplace');

async function render() {
  const { settings = {}, jobs = { handled: [] }, watch = {}, link = null, relay = { threads: [] } } =
    await chrome.storage.local.get(['settings', 'jobs', 'watch', 'link', 'relay']);
  renderPicks(Object.assign({ extract: ['Job title', 'Job link', 'Job description', 'Project info', 'Client info'],
    send: ['Job title', 'Job link', 'Job description'] }, settings));
  renderHandled(jobs, watch, link);
  renderReport(relay);
  renderProfile(settings);
}
chrome.storage.onChanged.addListener(render);
render();
