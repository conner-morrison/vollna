# Vollna Watcher (Chrome extension)

The scraper as a Chrome extension. Instead of a separate Chrome profile that has to be logged in, it
works in a Vollna tab you already have open: link the tab, press Start, and on every check it reads
the new jobs off that tab, decides on each (rules.md) and sends them to the relay, the same way the
Python version does.

## Install

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. **Load unpacked** → choose this `extension/` folder.
3. Pin it: puzzle-piece icon → pin **Vollna Watcher**.

## Set up (once)

Open the extension's **Control panel** (link in the popup):

- **Profile → Telegram alerts**: bot token and chat id, then **Send test**.
- **Profile → Move over from the Python version**: pick the Python project's `reports.json` (keeps
  the relay registration and channel) and `handled.json` (keeps the jobs already handled, so they are
  not sent twice). Chrome asks once whether the extension may reach the relay's address: allow it.
  Or, for a fresh start: **Report → Register me** with the relay URL.

Stop the Python watcher before the extension takes over. Both use the same relay id, so running
both would split the server's messages between them (jobs themselves are never sent twice: the relay
refuses a job id it already has).

## Use

1. Open your Vollna filter page (e.g. `https://www.vollna.com/dashboard/filter/47103`), logged in.
2. Click the extension → **Link this tab**.
3. Choose the interval and **Start**.

Leave that tab open. A check does not reload it: Vollna's filter page adds new jobs to itself as
they are posted, and the extension reads what the tab shows. The tab is reloaded only when:

- its job list has not changed for longer than **Reload if no change for … minutes** (default 30),
  in case Vollna's own updating has stalled; the wait starts again after each change or reload;
- there is no job list on it to read (the list failed to load, or the tab was moved to another
  Vollna page).

Chrome is told not to unload the tab to save memory.
Chrome has to be running for the extension to watch.

**A tab that is not Vollna** is refused, and Telegram hears that you are out of your mind. The same
alert comes if the linked tab is later moved off Vollna while watching.

Watching stops, with a Telegram alert, when:

- the linked tab is closed, moved off Vollna, or logged out;
- the job list does not load three times in a row (Vollna's list loader, `POST /load/<filter>`,
  sometimes hangs while the rest of the page loads);
- a job could not be delivered to the relay.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | Extension definition (Manifest V3). |
| `background.js` | The watcher, relay client and Telegram alerts (ports of auto.py, reports.py, notify.py). |
| `parse.js` | Reads a Vollna page: job rows, client and project blocks, work history (port of scrape.py). Runs inside the Vollna tab. |
| `rules.js` | Bid / manual check / skip, and the "not software work" filter (ports of rules.py, relevance.py). |
| `popup.html/js` | Link this tab, Start, Stop. |
| `options.html/js` | Control panel: Workplace, Report, Profile. |

The client name is guessed from capitalised words in feedback; the Python version can add spaCy,
which a browser does not have, so names may be found a little less often.
