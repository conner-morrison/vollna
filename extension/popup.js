// The popup: link the current tab, start and stop watching it.
const $ = (id) => document.getElementById(id);

async function ask(type, extra = {}) {
  const answer = await chrome.runtime.sendMessage({ type, ...extra });
  if (!answer || !answer.ok) throw new Error((answer && answer.error) || 'No answer from the extension.');
  return answer.result;
}

function show(text, ok) {
  $('msg').textContent = text;
  $('msg').className = 'msg ' + (ok ? 'ok' : 'err');
}

async function render() {
  const { link, watch = {}, settings = {} } = await chrome.storage.local.get(['link', 'watch', 'settings']);
  $('linked').innerHTML = '';
  if (link) {
    const title = document.createElement('strong');
    title.textContent = link.title;
    $('linked').append(title, link.url);
    $('linked').classList.remove('muted');
  } else {
    $('linked').textContent = 'No tab linked yet. Open your Vollna filter page and press Link this tab.';
    $('linked').classList.add('muted');
  }
  const bar = $('status');
  if (watch.running) {
    bar.className = 'status-bar ok';
    bar.textContent = 'Watching' + (watch.checked ? ` · last checked ${watch.checked}` : ' · first check running');
  } else if (watch.error) {
    bar.className = 'status-bar err';
    bar.textContent = 'Stopped: ' + watch.error;
  } else {
    bar.className = 'status-bar warn';
    bar.textContent = 'Not watching.';
  }
  if (watch.running && watch.reloaded) bar.textContent += ` · last reload ${watch.reloaded}`;
  if (watch.note && watch.running) bar.textContent += ' · ' + watch.note;
  if (document.activeElement !== $('interval')) $('interval').value = settings.interval || 120;
  if (document.activeElement !== $('reloadAfter')) $('reloadAfter').value = Math.round((settings.reloadAfter || 1800) / 60);
  $('start').disabled = !!watch.running || !link;
  $('stop').disabled = !watch.running;
  $('link').disabled = !!watch.running;
  $('unlink').disabled = !!watch.running || !link;
}

$('link').onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    await ask('link', { tab: { id: tab.id, url: tab.url, title: tab.title } });
    show('Linked. Press Start to watch it.', true);
  } catch (e) { show(e.message, false); }
};
$('unlink').onclick = async () => {
  try { await ask('unlink'); show('Unlinked.', true); } catch (e) { show(e.message, false); }
};
$('start').onclick = async () => {
  try {
    await ask('start', { catchUp: $('catchUp').checked, interval: $('interval').value,
      reloadAfter: Math.max(1, Number($('reloadAfter').value) || 30) * 60 });
    show($('catchUp').checked ? 'Watching started: missed jobs are analysed first.' : 'Watching started.', true);
  } catch (e) { show(e.message, false); }
};
$('stop').onclick = async () => {
  try { await ask('stop'); show('Stopped.', true); } catch (e) { show(e.message, false); }
};
$('openPanel').onclick = (event) => {
  event.preventDefault();
  chrome.runtime.openOptionsPage();
};

chrome.storage.onChanged.addListener(render);
render();
