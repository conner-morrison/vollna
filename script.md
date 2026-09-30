# Vollna Gmail alerts → Relay (Google Apps Script)

Runs on Google's servers on a timer (every 5 minutes by default, changeable in the panel). It reads new Vollna job alerts, Upwork job alerts, Upwork invitations, and Upwork messages from Gmail and publishes each one to the relay workspace `upwork`, in the channel you pick for that kind in the control panel. A control panel web app, which only your Google account can open, lets you pause, resume, choose what to send, and change the worker settings.

## Setup

1. **Approve the worker.** In the relay console for the `upwork` workspace, `zachary-upwork-vollna-alert` is approved and a member of the `jobs` channel.
2. **Create the script.** At https://script.google.com, create a **New project**.
   - Paste **Code.gs** below into the `Code.gs` file.
   - Click **+** next to Files → **HTML**, name it `Index`, and paste **Index.html** below.
3. **Add script properties.** In **Project Settings → Script properties**, add these (later you can change them in the control panel):

   | Property | Value |
   |---|---|
   | `RELAY_URL` | `https://relay-production-7643.up.railway.app/upwork` |
   | `RELAY_ID` | `zachary-upwork-vollna-alert` |
   | `RELAY_TOKEN` | the worker token |
   | `RELAY_CHANNEL` | `jobs` (the default channel) |
   | `CHANNEL_JOB`, `CHANNEL_ALERT`, `CHANNEL_INVITE`, `CHANNEL_MESSAGE` | optional, one channel per kind. Set these in the control panel rather than here; any kind without one uses `RELAY_CHANNEL`. |

4. **Test.** Run `testRelay` and approve Google's permission prompt. The log should say `OK`, and a test message should appear in the channel.
5. **Start.** Run `setup` once. It creates the trigger (every 5 minutes by default) and skips emails that already exist, so only new ones are sent.
6. **Open the control panel.** Click **Deploy → New deployment**, choose type **Web app**, and set:
   - **Execute as:** Me
   - **Who has access:** Only myself

   Click **Deploy** and bookmark the web app URL.

   After you change the code later, open **Deploy → Manage deployments → Edit (pencil) → Version: New version → Deploy** so the panel uses the new code. The URL stays the same.

## Control panel

| Control | What it does |
|---|---|
| **Pause** | Stops sending. The trigger keeps running but does nothing. |
| **Resume** | Starts sending again, including emails that arrived while paused (up to 2 days old). |
| **Resume, skip missed** | Starts sending again, but skips every email that arrived while paused. |
| **Install timer** | Shown only when the trigger is missing. Installs it and skips existing emails. |
| **Check Gmail every N minutes** | 1, 5, 10, 15 or 30 (the values Apps Script allows). Default 5. Changing it re-creates the trigger immediately. |
| **Save** | Saves the relay URL, worker ID, default channel, per-kind channels, and token. Leave a per-kind channel empty to use the default channel. Leave the token empty to keep the current one. |
| **Register worker** | Sends the saved worker ID and token to the relay's enrol endpoint. Then approve the worker in the relay console and add it to the channel. |
| **Send test message** | Publishes a test message to every channel in use (the default channel plus any per-kind channels) with the saved token, and reports each one. |
| **Send: Vollna job alerts / Upwork job alerts / Upwork invitations / Upwork messages** | Turns each kind of email on or off. All on by default. Emails of a kind that is off are marked as handled and are not sent later. |
| **Only jobs whose client has a verified payment method** | On by default. Applies to Vollna job alerts and Upwork job alerts. Skipped jobs are shown under **Last skipped**. |

The same actions are available from the editor's **Run** dropdown: `pause`, `resume`, `resumeSkipMissed`, `requireVerifiedPayment`, `allowUnverifiedPayment`, `status`, `testRelay`, `enrol`, `setup`.

To remove everything, open **Triggers** (clock icon on the left) and delete the `checkVollna` trigger, then archive the web app under **Deploy → Manage deployments**.

## When a run fails

A run stops early, without losing anything, when the relay refuses a message, when an email cannot be read, or after 4 minutes of work (Apps Script stops a run at 6). Whatever is left is picked up on the next run.

**Gmail's daily limit.** A personal Gmail account allows a script 20,000 Gmail calls per day (50,000 on Workspace). A run uses about two — one search and one batched fetch of everything it matched — plus roughly one body read per email it sends. That is around 600 calls a day at 5 minutes, or about 3,000–6,000 at 1 minute, both inside the cap.

The earlier version fetched each conversation separately (25–50 calls per run) and ran every minute, which is what caused `Service invoked too many times for one day: gmail`.

**What such an outage does:** every run stops at its first Gmail call, so nothing is read or sent and the channel goes quiet. Nothing is lost or duplicated, because an email is only marked as handled once it has been sent; everything queues up and goes out when the quota resets, around midnight US Pacific time. The reason is shown under **Last error** in the panel. Only emails older than the 2-day search window are missed, so an outage would have to last that long to lose anything. If it happens, pick a longer interval.

An email that fails three times in a row is given up on: it is marked as handled, and the reason appears under **Last skipped** in the panel. Any unexpected error is shown under **Last error** and written to the execution log, so Google's "script failed" email should become rare. To see the details of a run, open **Executions** in the editor.

## Which emails are sent

| Email | Sender | Subject | Sent as |
|---|---|---|---|
| Vollna job alert | `info@vollna.com` | any | `"type": "job"` |
| Upwork job alert | `Upwork Notification <donotreply@upwork.com>` | `New job alert: …` | `"type": "alert"` |
| Upwork invitation | `Upwork <upwork@t.upwork.com>` | `Invitation to Interview for: …` | `"type": "invite"` |
| Upwork Enterprise invitation | `donotreply@upwork.com` | `You have been invited to an Upwork Enterprise job!` | `"type": "invite"`, `"enterprise": true` |
| Upwork message | `<name> via Upwork <room_…@email.upwork.com>` | `<name> sent you a message` | `"type": "message"` |

Every other Upwork email (payments, Connects, contracts, feedback, offers, marketing) is ignored.

**Channels:** each kind goes to the channel you choose for it in the control panel, under **Channel per kind**. A kind with no channel of its own uses the default channel. The worker must be a member of every channel it sends to.

### Upwork job alert format

```json
{
  "source": "upwork",
  "type": "alert",
  "index": 0,
  "title": "Automations & AI",
  "upworkUrl": "https://www.upwork.com/jobs/~022100070000365204895",
  "jobType": "Hourly",
  "budget": "$25.00 - $65.00",
  "description": "I run a Youtube agency that helps US realtors get more views, leads and deals. …",
  "skills": ["Artificial Intelligence", "Automation"],
  "client": { "paymentVerified": true, "rating": "4.82", "spent": "$166K spent", "location": "Netherlands" },
  "emailId": "…",
  "emailSubject": "New job alert: Automations & AI",
  "receivedAt": "2026-09-15T21:22:00.000Z"
}
```

`description` is the preview shown in the email, which Upwork cuts off. `budget` is the range as written; Upwork sends `"$0.00 - $0.00"` when the client set no rate.

### Invitation format

```json
{
  "source": "upwork",
  "type": "invite",
  "index": 0,
  "title": "Microsoft Dynamics and Power BI Dashboard Creator",
  "enterprise": false,
  "terms": "Hourly • 1 to 3 months",
  "description": "We need an experienced freelancer to create dashboards and reports for our business operations. …",
  "clientNote": "Hello!\nI'd like to invite you to take a look at the job I've posted. Please submit a proposal if you're available and interested.\nThomas S.",
  "clientName": "Thomas S.",
  "client": null,
  "inviteUrl": "https://link.t.upwork.com/ls/click?upn=…",
  "emailId": "…",
  "emailSubject": "Invitation to Interview for: Microsoft Dynamics and Power BI Dashboard Creator",
  "receivedAt": "2026-09-14T01:23:54.000Z"
}
```

- `description` is the short preview in the email, which Upwork cuts off.
- `inviteUrl` is the email's **View invite** link, which goes through Upwork's click tracking.
- For Enterprise invitations, `terms` holds the budget (e.g. `"Fixed • Est. budget $30.00"`), `client` holds the client summary, and `inviteUrl` is the direct proposal link.

### Message format

```json
{
  "source": "upwork",
  "type": "message",
  "index": 0,
  "from": "Roh K.",
  "jobTitle": "CPG FP&A and Data Analyst (Consumer Goods, Retail and Ecommerce)",
  "messages": [
    { "author": "Roh K.", "time": "1:37 AM UTC, 15 Sep 2026", "text": "Hi, let's do a call. …" }
  ],
  "text": "Hi, let's do a call. …",
  "roomUrl": "https://www.upwork.com/ab/messages/rooms/room_e1ab7cfde8855886619bb4fcae1d2f6f",
  "emailId": "…",
  "emailSubject": "Roh K. sent you a message",
  "receivedAt": "2026-09-15T01:45:30.000Z"
}
```

`messages` lists each message shown in the email. `text` joins their texts. `roomUrl` opens the conversation on Upwork.

## Payment verification filter

This applies to Vollna job alerts and Upwork job alerts. With the filter on (the default), a job is sent only when its email says **Payment method verified** (Vollna) or **Payment verified** (Upwork). Everything else is skipped and not sent later:

- the email says the payment method is not verified;
- the email has no payment line;
- the job comes from a "Here are N new freelance jobs" email, which has no client details.

Skipped emails are marked as handled, so turning the filter off later does not send them. Vollna emails that cannot be read at all are still sent as `"type": "email"`, so a change in Vollna's email layout does not go unnoticed.

## Vollna job format

Vollna sends two kinds of job-alert email, and the script reads both.

**"New Job: …" emails** (one job, full details):

```json
{
  "source": "vollna",
  "type": "job",
  "index": 0,
  "title": "Senior Data Engineer Needed – Pipeline Architecture, Data Modeling & Warehouse Optimization",
  "upworkUrl": "https://www.upwork.com/jobs/~022099478094724251784",
  "vollnaProjectId": "75225930",
  "budget": "Hourly Rate: 50 - 95 USD",
  "published": "Sep 14, 2026 12:40 PM",
  "filter": "Data Engineering & Analytics Jobs",
  "description": "We're hiring a Senior Data Engineer to design and scale …",
  "client": {
    "rank": "Medium",
    "paymentVerified": true,
    "reviews": "no reviews",
    "registered": "31/07/2026",
    "location": "🇺🇸 United States"
  },
  "aiQualification": "Qualified",
  "aiReason": "Fits core skills (Python, SQL, ETL, cloud), aligns with data engineering focus, detailed genuine brief, no red flags.",
  "emailId": "1a09ff0b4e589d39",
  "emailSubject": "New Job: Senior Data Engineer Needed – Pipeline Architecture, Data Modeling & Warehouse Optimization",
  "receivedAt": "2026-09-14T12:42:27.000Z"
}
```

`budget` is `"not specified"`, a budget amount, or `"Hourly Rate: …"` / `"Fixed Price: …"`, as written in the email.

**"Here are N new freelance jobs" emails** (a table, fewer details):

```json
{
  "source": "vollna",
  "type": "job",
  "index": 0,
  "title": "Automation Expert AI",
  "upworkUrl": "https://www.upwork.com/jobs/~022099098384666775033",
  "vollnaProjectId": "75221231",
  "budget": "not specified",
  "published": "09/13/2026 7:31 AM",
  "emailId": "…",
  "emailSubject": "Here are 1 new freelance jobs for you.",
  "receivedAt": "2026-09-13T11:41:10.000Z"
}
```

`index` is the job's position inside its email (0, 1, 2, …). The message `id` is `<emailId>-<index>`, so a retry does not create a duplicate. If no job can be read from an email, it is sent as `"type": "email"` with the first 2,000 characters of its text instead.

## Code.gs

```js
/**
 * Vollna job alerts, Upwork invitations and Upwork messages (Gmail) -> Relay workspace,
 * with a control panel web app.
 * Script properties: RELAY_URL, RELAY_ID, RELAY_TOKEN, RELAY_CHANNEL (default channel),
 *                     CHANNEL_JOB / CHANNEL_ALERT / CHANNEL_INVITE / CHANNEL_MESSAGE (optional, per kind)
 * Internal properties: PAUSED, ONLY_VERIFIED, SEND_JOB, SEND_ALERT, SEND_INVITE, SEND_MESSAGE,
 *                      SENT_IDS, FAILED_IDS, LAST_SENT, LAST_SKIPPED, LAST_ERROR, INTERVAL_MINUTES
 */
// A 2-day window costs nothing extra (messages are fetched in one batch) and leaves room to catch
// up after an outage, such as Gmail's daily call limit being reached.
const QUERY = 'newer_than:2d (from:info@vollna.com'
  + ' OR (from:upwork@t.upwork.com subject:"Invitation to Interview")'
  + ' OR (from:donotreply@upwork.com subject:"Upwork Enterprise job")'
  + ' OR (from:donotreply@upwork.com subject:"New job alert")'
  + ' OR (from:email.upwork.com subject:"sent you a message"))';
const MAX_IDS = 300;
// Minutes between checks. Gmail caps how many calls a script may make per day (20,000 on a
// personal account), so checking every minute can run out; the values Apps Script allows are fixed.
const INTERVALS = [1, 5, 10, 15, 30];
const DEFAULT_INTERVAL = 5;
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$/;
const KINDS = {
  job: 'Vollna job alerts', alert: 'Upwork job alerts', invite: 'Upwork invitations', message: 'Upwork messages',
};

function props_() {
  return PropertiesService.getScriptProperties();
}

function isSending_(kind) {
  return props_().getProperty('SEND_' + kind.toUpperCase()) !== 'false';
}

// ---------------------------------------------------------------------------
// Editor actions (Run dropdown)
// ---------------------------------------------------------------------------

// Run once: creates the trigger and skips emails that already exist.
function setup() {
  installTrigger_(intervalMinutes_());
  markExistingSent_();
}

// How often the script checks Gmail, as chosen in the control panel.
function intervalMinutes_() {
  const saved = Number(props_().getProperty('INTERVAL_MINUTES'));
  return INTERVALS.indexOf(saved) >= 0 ? saved : DEFAULT_INTERVAL;
}

function installTrigger_(minutes) {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'checkVollna')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkVollna').timeBased().everyMinutes(minutes).create();
}

// Confirms the relay accepts messages from this worker on every channel it sends to.
function testRelay() {
  const results = sendTests_();
  if (!results.length) Logger.log('FAILED: no channel is set');
  results.forEach(r => Logger.log(`${r.channel}: ${r.ok ? 'OK' : 'FAILED: ' + r.error}`));
}

// Asks the relay to register RELAY_ID with RELAY_TOKEN (then approve it in the console).
function enrol() {
  const r = enrol_();
  Logger.log(r.code + ' ' + r.text);
}

// Stop sending. Emails that arrive meanwhile are not lost; resume() sends them (up to 2 days old).
function pause() {
  props_().setProperty('PAUSED', 'true');
  Logger.log('Paused');
}

// Start sending again, including emails that arrived while paused.
function resume() {
  props_().deleteProperty('PAUSED');
  Logger.log('Resumed');
}

// Start sending again, but skip emails that arrived while paused.
function resumeSkipMissed() {
  markExistingSent_();
  resume();
}

// Only send Vollna jobs whose client has a verified payment method (the default).
function requireVerifiedPayment() {
  props_().deleteProperty('ONLY_VERIFIED');
  Logger.log('Only jobs with a verified payment method will be sent');
}

// Send Vollna jobs regardless of the client's payment method.
function allowUnverifiedPayment() {
  props_().setProperty('ONLY_VERIFIED', 'false');
  Logger.log('Jobs will be sent regardless of payment verification');
}

function status() {
  const s = getState();
  const kinds = Object.keys(KINDS).map(k => `${KINDS[k]}: ${s.send[k] ? 'on' : 'off'}`).join(', ');
  Logger.log(`Sending: ${s.paused ? 'PAUSED' : 'ON'} | trigger: ${s.trigger ? `every ${s.interval} min` : 'missing (run setup)'}`
    + ` | ${kinds} | Verified payment only: ${s.onlyVerified ? 'yes' : 'no'}`);
}

// ---------------------------------------------------------------------------
// Control panel (web app)
// ---------------------------------------------------------------------------

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Vollna Alert Worker')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function getState() {
  migrate_();
  const p = props_();
  const token = p.getProperty('RELAY_TOKEN') || '';
  const send = {};
  const channels = {};
  Object.keys(KINDS).forEach(k => {
    send[k] = isSending_(k);
    channels[k] = p.getProperty('CHANNEL_' + k.toUpperCase()) || '';
  });
  return {
    paused: p.getProperty('PAUSED') === 'true',
    onlyVerified: p.getProperty('ONLY_VERIFIED') !== 'false',
    interval: intervalMinutes_(),
    intervals: INTERVALS,
    send,
    trigger: ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'checkVollna'),
    url: p.getProperty('RELAY_URL') || '',
    id: p.getProperty('RELAY_ID') || '',
    channel: p.getProperty('RELAY_CHANNEL') || '',
    channels,
    tokenHint: token ? `set, ends in "${token.slice(-2)}"` : 'not set',
    lastSent: JSON.parse(p.getProperty('LAST_SENT') || 'null'),
    lastSkipped: JSON.parse(p.getProperty('LAST_SKIPPED') || 'null'),
    lastError: JSON.parse(p.getProperty('LAST_ERROR') || 'null'),
  };
}

function panelSetPaused(paused, skipMissed) {
  if (paused) pause();
  else if (skipMissed) resumeSkipMissed();
  else resume();
  return getState();
}

function panelSetOnlyVerified(on) {
  if (on) requireVerifiedPayment();
  else allowUnverifiedPayment();
  return getState();
}

// Changes how often Gmail is checked, and re-creates the trigger when one is installed.
function panelSetInterval(minutes) {
  const value = Number(minutes);
  if (INTERVALS.indexOf(value) < 0) throw new Error('Interval must be one of: ' + INTERVALS.join(', ') + ' minutes.');
  props_().setProperty('INTERVAL_MINUTES', String(value));
  if (ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'checkVollna')) installTrigger_(value);
  return getState();
}

function panelSetSending(kind, on) {
  if (!KINDS[kind]) throw new Error('Unknown kind: ' + kind);
  if (on) props_().deleteProperty('SEND_' + kind.toUpperCase());
  else props_().setProperty('SEND_' + kind.toUpperCase(), 'false');
  return getState();
}

function panelInstallTrigger() {
  setup();
  return getState();
}

function panelSaveSettings(s) {
  const url = String(s.url || '').trim().replace(/\/+$/, '');
  const id = String(s.id || '').trim();
  const channel = String(s.channel || '').trim();
  const token = String(s.token || '').trim();
  if (!/^https:\/\/\S+$/.test(url)) throw new Error('Relay URL must start with https://');
  if (!NAME_PATTERN.test(id)) throw new Error('Worker ID may use letters, digits, _ . - (up to 64 characters).');
  if (!NAME_PATTERN.test(channel)) throw new Error('Default channel may use letters, digits, _ . - (up to 64 characters).');

  // Validate every per-kind channel before writing anything.
  const perKind = {};
  Object.keys(KINDS).forEach(k => {
    const value = String((s.channels || {})[k] || '').trim();
    if (value && !NAME_PATTERN.test(value)) {
      throw new Error(`${KINDS[k]} channel may use letters, digits, _ . - (up to 64 characters).`);
    }
    perKind[k] = value;
  });

  const p = props_();
  p.setProperties({ RELAY_URL: url, RELAY_ID: id, RELAY_CHANNEL: channel });
  Object.keys(perKind).forEach(k => {
    if (perKind[k]) p.setProperty('CHANNEL_' + k.toUpperCase(), perKind[k]);
    else p.deleteProperty('CHANNEL_' + k.toUpperCase());
  });
  if (token) p.setProperty('RELAY_TOKEN', token);
  return getState();
}

function panelEnrol() {
  return Object.assign(enrol_(), { state: getState() });
}

function panelTest() {
  const results = sendTests_();
  return { results, state: getState() };
}

// ---------------------------------------------------------------------------
// Worker
// ---------------------------------------------------------------------------

function checkVollna() {
  migrate_();
  const p = props_();
  if (p.getProperty('PAUSED') === 'true') return;
  const onlyVerified = p.getProperty('ONLY_VERIFIED') !== 'false';
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return;
  try {
    const sent = new Set(loadIds_());
    const messages = [];
    // One search plus one batched fetch: Gmail calls are capped per day, so keep them few.
    GmailApp.getMessagesForThreads(GmailApp.search(QUERY, 0, 25)).forEach(thread =>
      thread.forEach(m => { if (!sent.has(m.getId())) messages.push(m); }));
    messages.sort((a, b) => a.getDate() - b.getDate());

    const deadline = Date.now() + 4 * 60 * 1000; // stop well before Apps Script's 6-minute limit
    for (const m of messages) {
      if (Date.now() > deadline) return; // whatever is left is picked up next run
      let handled;
      try {
        handled = handleMessage_(m, onlyVerified);
      } catch (e) {
        noteFailure_(m, e, sent); // one bad email must not fail the whole run
        return;
      }
      if (!handled) return; // relay down or not approved: retry next run
      clearFailure_(m.getId());
      sent.add(m.getId());
      saveIds_([...sent]);
    }
  } catch (e) {
    // e.g. Gmail's daily call limit. Record it for the panel instead of failing the run.
    const message = e && e.message ? e.message : String(e);
    console.error('Run failed: ' + message);
    p.setProperty('LAST_ERROR', JSON.stringify({ message: `Run failed: ${message}`, at: new Date().toISOString() }));
  } finally {
    lock.releaseLock();
  }
}

// Publishes one email. Returns false when the relay refused it, so the run can retry later.
function handleMessage_(m, onlyVerified) {
  const p = props_();
  const kind = classify_(m.getFrom(), m.getSubject());
  const base = { emailId: m.getId(), emailSubject: m.getSubject(), receivedAt: m.getDate().toISOString() };
  let bodies = [];
  let skipped = null;

  if (kind && !isSending_(kind)) {
    skipped = { title: m.getSubject(), count: 1, reason: `${KINDS[kind]} are turned off` };
  } else if (kind === 'job' || kind === 'alert') {
    const jobs = kind === 'job'
      ? parseJobs_(m.getBody()).map((j, i) => ({ source: 'vollna', type: 'job', index: i, ...j, ...base }))
      : [{ source: 'upwork', type: 'alert', index: 0, ...parseAlert_(m.getBody(), m.getSubject()), ...base }];
    // A job without client details (e.g. the Vollna results-table email) counts as not verified.
    const keep = j => !onlyVerified || (j.client && j.client.paymentVerified === true);
    const dropped = jobs.filter(j => !keep(j));
    bodies = jobs.length
      ? jobs.filter(keep)
      : [{ source: 'vollna', type: 'email', index: 0, text: m.getPlainBody().slice(0, 2000), ...base }];
    if (dropped.length) {
      skipped = { title: dropped[dropped.length - 1].title, count: dropped.length, reason: 'payment method not verified' };
    }
  } else if (kind === 'invite') {
    bodies = [{ source: 'upwork', type: 'invite', index: 0, ...parseInvite_(m.getBody(), m.getSubject()), ...base }];
  } else if (kind === 'message') {
    bodies = [{ source: 'upwork', type: 'message', index: 0, ...parseMessage_(m.getBody(), m.getFrom()), ...base }];
  }

  for (const body of bodies) {
    if (!publish_(`${m.getId()}-${body.index}`, body, channelFor_(body))) return false;
  }

  const now = new Date().toISOString();
  if (bodies.length) {
    p.setProperty('LAST_SENT', JSON.stringify({ title: label_(bodies[bodies.length - 1]), count: bodies.length, at: now }));
  }
  if (skipped) {
    p.setProperty('LAST_SKIPPED', JSON.stringify({ ...skipped, at: now }));
  }
  return true;
}

// Records an unexpected error, and gives up on an email after three failed attempts.
function noteFailure_(m, e, sent) {
  const p = props_();
  const id = m.getId();
  const message = e && e.message ? e.message : String(e);
  const at = new Date().toISOString();
  console.error(`Failed on "${m.getSubject()}" (${id}): ${message}`);

  const fails = JSON.parse(p.getProperty('FAILED_IDS') || '{}');
  fails[id] = (fails[id] || 0) + 1;
  if (fails[id] >= 3) {
    delete fails[id];
    sent.add(id);
    saveIds_([...sent]);
    p.setProperty('LAST_SKIPPED', JSON.stringify({ title: m.getSubject(), count: 1, reason: `could not be read: ${message}`, at }));
  }
  p.setProperty('FAILED_IDS', JSON.stringify(fails));
  p.setProperty('LAST_ERROR', JSON.stringify({ message: `Could not handle "${m.getSubject()}": ${message}`, at }));
}

function clearFailure_(id) {
  const p = props_();
  const fails = JSON.parse(p.getProperty('FAILED_IDS') || '{}');
  if (!(id in fails)) return;
  delete fails[id];
  p.setProperty('FAILED_IDS', JSON.stringify(fails));
}

// Which kind of email this is, or null for any other email the search matched.
function classify_(from, subject) {
  if (/\binfo@vollna\.com\b/i.test(from)) return 'job';
  if (/\bupwork@t\.upwork\.com\b/i.test(from) && /^Invitation to Interview for:/i.test(subject)) return 'invite';
  if (/\bdonotreply@upwork\.com\b/i.test(from) && /invited to an Upwork Enterprise job/i.test(subject)) return 'invite';
  if (/\bdonotreply@upwork\.com\b/i.test(from) && /^New job alerts?:/i.test(subject)) return 'alert';
  if (/ via Upwork"?\s*<room_[0-9a-f]+@email\.upwork\.com>/i.test(from) && /sent you a message$/i.test(subject)) return 'message';
  return null;
}

function label_(body) {
  if (body.type === 'alert') return `Job alert: ${body.title || body.emailSubject}`;
  if (body.type === 'invite') return `Invitation: ${body.title || body.emailSubject}`;
  if (body.type === 'message') return `Message from ${body.from || '?'}${body.jobTitle ? ` (${body.jobTitle})` : ''}`;
  return body.title || body.emailSubject;
}

// Each kind uses its own channel when one is set in the control panel; everything else uses RELAY_CHANNEL.
function channelFor_(body) {
  const p = props_();
  const own = KINDS[body.type] ? p.getProperty('CHANNEL_' + body.type.toUpperCase()) : null;
  return own || p.getProperty('RELAY_CHANNEL');
}

// Moves the earlier single RELAY_UPWORK_CHANNEL setting onto the per-kind messages channel.
function migrate_() {
  const p = props_();
  const old = p.getProperty('RELAY_UPWORK_CHANNEL');
  if (!old) return;
  if (!p.getProperty('CHANNEL_MESSAGE')) p.setProperty('CHANNEL_MESSAGE', old);
  p.deleteProperty('RELAY_UPWORK_CHANNEL');
}

function markExistingSent_() {
  const ids = loadIds_();
  GmailApp.getMessagesForThreads(GmailApp.search(QUERY, 0, 100))
    .forEach(thread => thread.forEach(m => ids.push(m.getId())));
  saveIds_([...new Set(ids)]);
}

// Reads jobs from both Vollna formats: the results table and the single "New Job" card.
function parseJobs_(html) {
  const re = /<a\b[^>]*href="([^"]*place(?:=|%3D)title[^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
  const seen = new Set();
  const anchors = [...html.matchAll(re)]
    .map(m => ({
      m,
      text: lines_(m[2]).join(' '),
      jobId: (m[1].match(/jobs(?:\/|%2F|%252F|%25252F)(~\d+)/i) || [])[1],
      pid: (m[1].match(/pid(?:=|%3D)(\d+)/i) || [])[1],
    }))
    .filter(a => a.text && !/^view on /i.test(a.text))
    .filter(a => { const k = a.jobId || a.text; if (seen.has(k)) return false; seen.add(k); return true; });

  return anchors.map((a, i) => {
    const start = a.m.index + a.m[0].length;
    const end = i + 1 < anchors.length ? anchors[i + 1].m.index : html.length;
    const cells = [];
    for (const c of lines_(html.slice(start, end))) {
      if (/^(Open results|Show live feed|View on Vollna|View on Upwork|You can pause|Your Vollna trial)/i.test(c)) break;
      cells.push(c);
    }
    const job = {
      title: a.text,
      upworkUrl: a.jobId ? `https://www.upwork.com/jobs/${a.jobId}` : null,
      vollnaProjectId: a.pid || null,
    };
    return cells.some(c => /^Published:/i.test(c))
      ? Object.assign(job, labeled_(cells))
      : Object.assign(job, { budget: cells[0] || null, published: cells[1] || null });
  });
}

// Fields of a "New Job" card, read by their labels.
function labeled_(cells) {
  const out = { budget: null, published: null, filter: null, description: null, client: {}, aiQualification: null, aiReason: null };
  const desc = [];
  let section = 'head';
  for (const c of cells) {
    let m;
    if (section !== 'ai' && (m = c.match(/^Client rank:\s*(.*)$/i))) { out.client.rank = m[1] || null; section = 'client'; continue; }
    if ((m = c.match(/^AI Qualification:\s*(.*)$/i))) { out.aiQualification = m[1] || null; section = 'ai'; continue; }
    if (section === 'head') {
      if ((m = c.match(/^Budget\b:?\s*(.*)$/i))) out.budget = m[1] || null;
      else if ((m = c.match(/^(Hourly Rate|Fixed[- ]Price)\b:?\s*(.*)$/i))) out.budget = `${m[1]}: ${m[2]}`;
      else if ((m = c.match(/^Published:\s*(.*)$/i))) out.published = m[1] || null;
      else if ((m = c.match(/^Filter:\s*(.*)$/i))) { out.filter = m[1] || null; section = 'desc'; }
      else { desc.push(c); if (out.published) section = 'desc'; }
    } else if (section === 'desc') {
      desc.push(c);
    } else if (section === 'client') {
      if ((m = c.match(/^Registered:\s*(.*)$/i))) out.client.registered = m[1];
      else if (/payment method/i.test(c)) out.client.paymentVerified = !/not verified|unverified/i.test(c);
      else if (/review/i.test(c)) out.client.reviews = c;
      else out.client.location = c;
    } else if ((m = c.match(/^Reason:\s*(.*)$/i))) {
      out.aiReason = m[1] || null;
    } else if (!out.aiQualification) {
      out.aiQualification = c;
    }
  }
  out.description = desc.join('\n').replace(/^["“]\s*|\s*["”]$/g, '') || null;
  return out;
}

// Upwork "New job alert: …" emails, which carry one job each.
function parseAlert_(html, subject) {
  const L = lines_(html);
  const out = { title: null, upworkUrl: null, jobType: null, budget: null, description: null, skills: [], client: {} };
  const anchors = [...html.matchAll(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)]
    .map(a => ({ href: cleanUrl_(a[1]), text: lines_(a[2]).join(' ') }));
  const titleLink = anchors.find(a => /upwork\.com\/jobs\/~/i.test(a.href) && a.text && !/^more$/i.test(a.text));
  if (titleLink) out.upworkUrl = titleLink.href;
  out.title = (subject.match(/^New job alerts?:\s*(.+)$/i) || [])[1] || (titleLink ? titleLink.text : null);
  out.skills = anchors
    .filter(a => /\/nx\/search\/jobs/i.test(a.href) && a.text && !/^\+\d+$/.test(a.text))
    .map(a => a.text);

  let i = L.findIndex(c => /^Posted\b/i.test(c));
  i = i < 0 ? 0 : i + 1;
  if (L[i] && (L[i] === out.title || (titleLink && L[i] === titleLink.text))) i++;
  if (/^(Hourly|Fixed)/i.test(L[i] || '')) out.jobType = L[i++];
  while (L[i] && /^[•·|–—-]+$/.test(L[i])) i++; // separator between job type and budget
  if (/^\$/.test(L[i] || '')) out.budget = L[i++];

  const desc = [];
  const STOP = /^(Payment (verified|unverified)|View job details|You received this email)/i;
  while (i < L.length && !STOP.test(L[i])) desc.push(L[i++]);
  if (desc.length && out.skills.length && desc[desc.length - 1].startsWith(out.skills[0])) desc.pop(); // the skills row
  out.description = desc.join('\n').replace(/\s*(?:\.{3}|…)?\s*more$/i, '…') || null;

  for (; i < L.length && !/^(View job details|You received this email)/i.test(L[i]); i++) {
    const c = L[i];
    if (/^Payment/i.test(c)) out.client.paymentVerified = /^Payment verified/i.test(c);
    else if (/^\d+(\.\d+)?$/.test(c)) out.client.rating = c;
    else if (/spent$/i.test(c)) out.client.spent = c;
    else out.client.location = c;
  }
  return out;
}

// Upwork "Invitation to Interview for: …" and "You have been invited to an Upwork Enterprise job!" emails.
function parseInvite_(html, subject) {
  const L = lines_(html);
  const enterprise = /Upwork Enterprise/i.test(subject);
  const out = { title: null, enterprise, terms: null, description: null, clientNote: null, clientName: null, client: null, inviteUrl: null };
  const END = /^(Personal note from client|View invite|Submit a Proposal|Decline)\b/i;

  let i = L.findIndex(c => /(good fit\.?|Enterprise Client:)$/i.test(c)) + 1;
  out.title = (subject.match(/^Invitation to Interview for:\s*(.+)$/i) || [])[1] || L[i] || null;
  i++;

  const terms = [];
  while (i < L.length && /^(Hourly|Fixed|•)/i.test(L[i])) terms.push(L[i++].replace(/^•\s*/, ''));
  out.terms = terms.join(' • ') || null;

  const desc = [];
  while (i < L.length && !END.test(L[i])) desc.push(L[i++]);
  out.description = desc.join('\n').replace(/\s*(\.{3}|…)\s*more$/i, '…') || null;

  if (/^Personal note from client$/i.test(L[i] || '')) {
    const note = [];
    for (i++; i < L.length && !END.test(L[i]); i++) note.push(L[i]);
    out.clientNote = note.join('\n') || null;
    const last = note[note.length - 1] || '';
    if (last.length <= 40 && /^\p{Lu}[\p{L}'’-]*(?: \p{Lu}[\p{L}'’-]*\.?)+$/u.test(last)) out.clientName = last;
  }

  const more = L.findIndex(c => /^More about this Upwork Enterprise Client$/i.test(c));
  if (more >= 0) {
    const info = [];
    for (let k = more + 1; k < L.length && !/^(Privacy Policy|Mobile app|Follow us|©|You are receiving)/i.test(L[k]); k++) {
      if (!/^(Learn more|Upwork Enterprise Client)$/i.test(L[k])) info.push(L[k]);
    }
    out.client = info.join(' ').replace(/,\s*$/, '') || null;
  }

  const link = [...html.matchAll(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)]
    .find(a => /^(View invite|Submit a Proposal)\b/i.test(lines_(a[2]).join(' ')));
  if (link) out.inviteUrl = cleanUrl_(link[1]);
  return out;
}

// Upwork "<name> sent you a message" emails from "<name> via Upwork".
function parseMessage_(html, from) {
  const L = lines_(html);
  const out = { from: (from.match(/^"?(.+?) via Upwork/i) || [])[1] || null, jobTitle: null, messages: [], text: null, roomUrl: null };
  const room = (from.match(/(room_[0-9a-f]+)@/i) || html.match(/messages\/rooms\/(room_[0-9a-f]+)/i) || [])[1];
  if (room) out.roomUrl = `https://www.upwork.com/ab/messages/rooms/${room}`;

  const head = L.findIndex(c => /^Unread messages? from .+ about /i.test(c));
  if (head >= 0) out.jobTitle = (L[head].match(/ about (.+)$/i) || [])[1] || null;
  const start = head + 1;
  let end = L.findIndex((c, k) => k >= start && /^View on Upwork$/i.test(c));
  if (end < 0) end = L.length;

  const TIME = /^\d{1,2}:\d{2}\s?[AP]M\b.*\d{4}$/i;
  const raw = L.slice(start, end);
  // Avatar initials ("RK") sit just before the author line and just after the time line.
  const body = raw.filter((c, k) => !(/^[A-Z]{1,3}$/.test(c) && (TIME.test(raw[k - 1] || '') || TIME.test(raw[k + 2] || ''))));
  const times = body.map((c, k) => (TIME.test(c) ? k : -1)).filter(k => k >= 0);
  times.forEach((t, n) => {
    const stop = n + 1 < times.length ? times[n + 1] - 1 : body.length; // the line before the next time is its author
    out.messages.push({ author: body[t - 1] || null, time: body[t], text: body.slice(t + 1, stop).join('\n') || null });
  });
  out.text = (times.length ? out.messages.map(x => x.text).filter(Boolean).join('\n\n') : body.join('\n')) || null;
  return out;
}

function cleanUrl_(url) {
  const u = url.replace(/&amp;/g, '&');
  return /^https:\/\/www\.upwork\.com\//i.test(u) ? u.replace(/[?#].*$/, '') : u;
}

const ENTITIES = {
  nbsp: ' ', amp: '&', quot: '"', apos: "'", lt: '<', gt: '>', raquo: '»', laquo: '«', bull: '•', hellip: '…',
  rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“', mdash: '—', ndash: '–', trade: '™', copy: '©', reg: '®',
  zwj: '', zwnj: '', shy: '',
};

function lines_(s) {
  return s
    .replace(/<(style|script|head)[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<br\s*\/?>|<\/(td|th|tr|p|div|h\d|li)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (e, n) => {
      if (n[0] !== '#') return ENTITIES[n.toLowerCase()] ?? e;
      const cp = /^#x/i.test(n) ? parseInt(n.slice(2), 16) : Number(n.slice(1));
      return cp > 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : '';
    })
    // Invisible spacer characters that emails use as preview-text padding.
    .replace(/[\u00AD\u034F\u115F\u1160\u17B4\u17B5\u180E\u2000-\u200F\u2028-\u202F\u205F-\u206F\u3000\u3164\uFEFF]/g, ' ')
    .split('\n').map(x => x.trim()).filter(Boolean);
}

// ---------------------------------------------------------------------------
// Relay
// ---------------------------------------------------------------------------

function relayUrl_(path) {
  return (props_().getProperty('RELAY_URL') || '').replace(/\/+$/, '') + path;
}

function publish_(id, body, channel) {
  const p = props_();
  let error;
  try {
    const res = UrlFetchApp.fetch(relayUrl_('/publish'), {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + p.getProperty('RELAY_TOKEN') },
      payload: JSON.stringify({ channel, id, body }),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code >= 200 && code < 300) {
      p.deleteProperty('LAST_ERROR');
      return true;
    }
    error = `Relay answered ${code} for channel "${channel}": ${res.getContentText().slice(0, 300)}`;
  } catch (e) {
    error = 'Relay unreachable: ' + e;
  }
  console.error(error);
  p.setProperty('LAST_ERROR', JSON.stringify({ message: error, at: new Date().toISOString() }));
  return false;
}

// Sends a test message to each channel in use; returns [{ channel, ok, error }].
function sendTests_() {
  const p = props_();
  const perKind = Object.keys(KINDS).map(k => p.getProperty('CHANNEL_' + k.toUpperCase()));
  const channels = [...new Set([p.getProperty('RELAY_CHANNEL'), ...perKind].filter(Boolean))];
  return channels.map(channel => {
    const ok = publish_('test-' + Date.now(), {
      source: 'apps-script', type: 'test', text: 'Test from Apps Script', ts: new Date().toISOString(),
    }, channel);
    return { channel, ok, error: ok ? null : (JSON.parse(p.getProperty('LAST_ERROR') || '{}').message || 'unknown error') };
  });
}

function enrol_() {
  const p = props_();
  const res = UrlFetchApp.fetch(relayUrl_('/enrol'), {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      worker_id: p.getProperty('RELAY_ID'),
      token: p.getProperty('RELAY_TOKEN'),
      label: 'Vollna Gmail alerts (Apps Script)',
    }),
    muteHttpExceptions: true,
  });
  return { code: res.getResponseCode(), text: res.getContentText().slice(0, 300) };
}

// ---------------------------------------------------------------------------
// Sent-email bookkeeping
// ---------------------------------------------------------------------------

function loadIds_() {
  return JSON.parse(props_().getProperty('SENT_IDS') || '[]');
}

function saveIds_(ids) {
  props_().setProperty('SENT_IDS', JSON.stringify(ids.slice(-MAX_IDS)));
}
```

## Index.html

```html
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <meta charset="utf-8">
  <style>
    :root {
      --bg: #f6f7f9; --card: #ffffff; --text: #1f2937; --muted: #6b7280; --line: #e5e7eb;
      --accent: #2563eb; --ok: #15803d; --okbg: #dcfce7; --warn: #b45309; --warnbg: #fef3c7;
      --err: #b91c1c; --errbg: #fee2e2;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f1115; --card: #181b21; --text: #e5e7eb; --muted: #9ca3af; --line: #2a2f37;
        --accent: #3b82f6; --ok: #4ade80; --okbg: #14321f; --warn: #fbbf24; --warnbg: #3a2c0b;
        --err: #f87171; --errbg: #3b1414;
      }
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 24px 16px; background: var(--bg); color: var(--text);
           font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    main { max-width: 560px; margin: 0 auto; display: grid; gap: 16px; }
    h1 { font-size: 20px; margin: 0; }
    h2 { font-size: 15px; margin: 0; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .between { justify-content: space-between; }
    .badge { padding: 2px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; }
    .badge.on { background: var(--okbg); color: var(--ok); }
    .badge.paused { background: var(--warnbg); color: var(--warn); }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 12px; margin: 12px 0; }
    dt { color: var(--muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    dd.error { color: var(--err); }
    fieldset { border: 0; padding: 0; margin: 0 0 12px; display: grid; gap: 6px; }
    legend { color: var(--muted); padding: 0; margin-bottom: 4px; }
    form { display: grid; gap: 12px; margin-top: 12px; }
    label { display: grid; gap: 4px; font-weight: 500; }
    label small, .note { color: var(--muted); font-weight: 400; }
    label.check { display: flex; align-items: center; gap: 8px; font-weight: 400; cursor: pointer; }
    label.check input { width: auto; margin: 0; }
    .note { margin: 0; font-size: 13px; }
    input { font: inherit; width: 100%; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px;
            background: var(--bg); color: var(--text); }
    select { font: inherit; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px;
             background: var(--bg); color: var(--text); }
    button { font: inherit; padding: 8px 14px; border-radius: 8px; border: 1px solid var(--line);
             background: var(--card); color: var(--text); cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button:disabled, input:disabled { opacity: .5; cursor: default; }
    #msg { padding: 10px 12px; border-radius: 8px; }
    #msg.ok { background: var(--okbg); color: var(--ok); }
    #msg.err { background: var(--errbg); color: var(--err); }
  </style>
</head>
<body>
  <main>
    <h1>Vollna Alert Worker</h1>
    <div id="msg" role="status" hidden></div>

    <section class="card">
      <div class="row between">
        <h2>Sending</h2>
        <span id="badge" class="badge">…</span>
      </div>
      <dl>
        <dt>Timer</dt><dd id="trigger">…</dd>
        <dt>Last sent</dt><dd id="lastSent">…</dd>
        <dt>Last skipped</dt><dd id="lastSkipped">…</dd>
        <dt>Last error</dt><dd id="lastError">…</dd>
      </dl>
      <fieldset>
        <legend>Send</legend>
        <label class="check"><input type="checkbox" class="toggle" data-kind="job"> Vollna job alerts</label>
        <label class="check"><input type="checkbox" class="toggle" data-kind="alert"> Upwork job alerts</label>
        <label class="check"><input type="checkbox" class="toggle" data-kind="invite"> Upwork invitations</label>
        <label class="check"><input type="checkbox" class="toggle" data-kind="message"> Upwork messages</label>
      </fieldset>
      <fieldset>
        <legend>Filter</legend>
        <label class="check">
          <input type="checkbox" class="toggle" id="onlyVerified">
          Only jobs whose client has a verified payment method
        </label>
        <p class="note" id="onlyVerifiedNote">Applies to Vollna job alerts and Upwork job alerts. Invitations and messages are never filtered.</p>
      </fieldset>
      <fieldset>
        <legend>Check Gmail</legend>
        <label class="check">Every <select id="interval"></select> minutes</label>
        <p class="note">Gmail allows a limited number of checks per day (20,000 calls on a personal account).
          Every 5 minutes is a safe default; every minute can use the day's allowance up.</p>
      </fieldset>
      <div class="row">
        <button id="pause">Pause</button>
        <button id="resume" class="primary">Resume</button>
        <button id="resumeSkip">Resume, skip missed</button>
        <button id="install" hidden>Install timer</button>
      </div>
    </section>

    <section class="card">
      <h2>Worker settings</h2>
      <form id="settings">
        <label>Relay URL
          <input name="url" type="url" required placeholder="https://relay.example.com/upwork">
        </label>
        <label>Worker ID
          <input name="id" required pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false">
        </label>
        <label>Default channel
          <input name="channel" required pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false">
        </label>
        <fieldset>
          <legend>Channel per kind <small>(empty = default channel)</small></legend>
          <label>Vollna job alerts
            <input data-channel="job" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false" placeholder="default channel">
          </label>
          <label>Upwork job alerts
            <input data-channel="alert" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false" placeholder="default channel">
          </label>
          <label>Upwork invitations
            <input data-channel="invite" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false" placeholder="default channel">
          </label>
          <label>Upwork messages
            <input data-channel="message" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" spellcheck="false" placeholder="default channel">
          </label>
        </fieldset>
        <label>Token <small id="tokenHint"></small>
          <input name="token" type="password" autocomplete="new-password" placeholder="Leave empty to keep the current token">
        </label>
        <div class="row">
          <button type="submit" class="primary">Save</button>
          <button type="button" id="enrol">Register worker</button>
          <button type="button" id="test">Send test message</button>
        </div>
        <p class="note">Register and Test use the saved settings. After changing the worker ID or token, click
          Register worker, then approve it in the relay console and add it to the channel.</p>
      </form>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const form = $('settings');
    const NAMES = {
      job: 'Vollna job alerts', alert: 'Upwork job alerts', invite: 'Upwork invitations', message: 'Upwork messages',
    };
    let busy = false;
    let state = null;

    function call(fn, ...args) {
      return new Promise((resolve, reject) =>
        google.script.run.withSuccessHandler(resolve).withFailureHandler(reject)[fn](...args));
    }

    function when(iso) {
      return iso ? new Date(iso).toLocaleString() : '';
    }

    function show(text, ok) {
      const m = $('msg');
      m.textContent = text;
      m.className = ok ? 'ok' : 'err';
      m.hidden = false;
    }

    function syncToggles() {
      document.querySelectorAll('.toggle, #interval').forEach((t) => { t.disabled = busy; });
      if (state && !busy) $('onlyVerified').disabled = !state.send.job && !state.send.alert;
    }

    function render(s) {
      state = s;
      $('badge').textContent = s.paused ? 'PAUSED' : 'ON';
      $('badge').className = 'badge ' + (s.paused ? 'paused' : 'on');
      $('trigger').textContent = s.trigger ? `Running every ${s.interval} min` : 'Not installed';
      const sel = $('interval');
      if (!sel.options.length) s.intervals.forEach((n) => sel.add(new Option(String(n), String(n))));
      if (document.activeElement !== sel) sel.value = String(s.interval);
      $('install').hidden = s.trigger;
      $('lastSent').textContent = s.lastSent
        ? `${s.lastSent.title}${s.lastSent.count > 1 ? ` (+${s.lastSent.count - 1} more)` : ''} · ${when(s.lastSent.at)}`
        : 'Nothing yet';
      $('lastSkipped').textContent = s.lastSkipped
        ? `${s.lastSkipped.title}${s.lastSkipped.count > 1 ? ` (+${s.lastSkipped.count - 1} more)` : ''}: ${s.lastSkipped.reason} · ${when(s.lastSkipped.at)}`
        : 'None';
      $('lastError').textContent = s.lastError ? `${s.lastError.message} · ${when(s.lastError.at)}` : 'None';
      $('lastError').className = s.lastError ? 'error' : '';
      document.querySelectorAll('[data-kind]').forEach((t) => { t.checked = s.send[t.dataset.kind]; });
      $('onlyVerified').checked = s.onlyVerified;
      $('pause').disabled = s.paused;
      $('resume').disabled = !s.paused;
      $('resumeSkip').disabled = !s.paused;
      for (const k of ['url', 'id', 'channel']) {
        if (document.activeElement !== form.elements[k]) form.elements[k].value = s[k];
      }
      document.querySelectorAll('[data-channel]').forEach((i) => {
        if (document.activeElement !== i) i.value = s.channels[i.dataset.channel] || '';
      });
      $('tokenHint').textContent = `(current: ${s.tokenHint})`;
      syncToggles();
    }

    function refresh() {
      return call('getState').then(render).catch((e) => show(e.message || String(e), false));
    }

    async function act(fn, args, done) {
      if (busy) return;
      busy = true;
      document.querySelectorAll('button').forEach((b) => { b.disabled = true; });
      syncToggles();
      let failed = false;
      try {
        const r = await call(fn, ...args);
        busy = false;
        render(r && r.state ? r.state : r);
        if (done) done(r);
      } catch (e) {
        failed = true;
        show(e.message || String(e), false);
      } finally {
        busy = false;
        document.querySelectorAll('#settings button, #install').forEach((b) => { b.disabled = false; });
        syncToggles();
        if (failed) refresh();
      }
    }

    $('pause').onclick = () => act('panelSetPaused', [true, false],
      () => show('Paused. Nothing will be sent.', true));
    $('resume').onclick = () => act('panelSetPaused', [false, false],
      () => show('Resumed. Emails that arrived while paused will be sent within a minute.', true));
    $('resumeSkip').onclick = () => act('panelSetPaused', [false, true],
      () => show('Resumed. Emails that arrived while paused were skipped.', true));
    $('install').onclick = () => act('panelInstallTrigger', [],
      () => show('Timer installed. Existing emails were skipped.', true));
    $('onlyVerified').onchange = (e) => {
      const on = e.target.checked;
      act('panelSetOnlyVerified', [on], () => show(on
        ? 'Only jobs whose client has a verified payment method will be sent.'
        : 'Jobs will be sent regardless of payment verification.', true));
    };
    $('interval').onchange = (e) => act('panelSetInterval', [Number(e.target.value)],
      (r) => show(`Checking Gmail every ${r.interval} minutes.`, true));
    document.querySelectorAll('[data-kind]').forEach((t) => {
      t.onchange = () => act('panelSetSending', [t.dataset.kind, t.checked],
        () => show(`${NAMES[t.dataset.kind]}: ${t.checked ? 'sending' : 'not sending'}.`, true));
    });

    form.onsubmit = (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      data.channels = {};
      document.querySelectorAll('[data-channel]').forEach((i) => { data.channels[i.dataset.channel] = i.value.trim(); });
      act('panelSaveSettings', [data], () => {
        form.elements.token.value = '';
        show('Settings saved.', true);
      });
    };
    $('enrol').onclick = () => act('panelEnrol', [],
      (r) => show(`Relay answered ${r.code}: ${r.text}`, r.code < 300));
    $('test').onclick = () => act('panelTest', [], (r) => {
      if (!r.results.length) return show('No channel is saved.', false);
      const failed = r.results.filter((x) => !x.ok);
      show(failed.length
        ? 'Test failed: ' + failed.map((x) => `${x.channel} (${x.error})`).join('; ')
        : 'Test message sent to ' + r.results.map((x) => x.channel).join(' and ') + '.', !failed.length);
    });

    refresh();
    setInterval(() => { if (!busy) refresh(); }, 30000);
  </script>
</body>
</html>
```
