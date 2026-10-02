// JXA helper: runs JavaScript inside a tab of the Chrome window you already use,
// so any site you are logged into stays logged in.
//
//   osascript -l JavaScript chrome.js tabs
//   osascript -l JavaScript chrome.js eval <url-prefix> <file-with-js>
ObjC.import('Foundation');

function readFile(path) {
  return ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null));
}

function findTab(chrome, prefix) {
  const windows = chrome.windows;
  for (let w = 0; w < windows.length; w++) {
    const tabs = windows[w].tabs;
    for (let t = 0; t < tabs.length; t++) {
      if (String(tabs[t].url()).indexOf(prefix) === 0) return { window: windows[w], tab: tabs[t] };
    }
  }
  return null;
}

function run(argv) {
  const chrome = Application('Google Chrome');
  if (!chrome.running()) return JSON.stringify({ error: 'Chrome is not running' });

  const command = argv[0];

  if (command === 'tabs') {
    const list = [];
    const windows = chrome.windows;
    for (let w = 0; w < windows.length; w++) {
      const tabs = windows[w].tabs;
      for (let t = 0; t < tabs.length; t++) list.push({ window: w, tab: t, url: String(tabs[t].url()), title: String(tabs[t].title()) });
    }
    return JSON.stringify(list);
  }

  if (command === 'eval') {
    const found = findTab(chrome, argv[1]);
    if (!found) return JSON.stringify({ error: 'no tab found for ' + argv[1] });
    const code = readFile(argv[2]);
    let result;
    try {
      result = found.tab.execute({ javascript: code });
    } catch (e) {
      return JSON.stringify({ error: 'execute failed: ' + e });
    }
    return result === undefined || result === null ? JSON.stringify({ error: 'no result' }) : String(result);
  }

  return JSON.stringify({ error: 'unknown command: ' + command });
}
