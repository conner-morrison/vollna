// Reading a Vollna page: the job rows, the client and project blocks, work history, sign-in pages.
//
// A port of the parsing in scrape.py, kept as close to it as JavaScript allows, so both read a page
// the same way. It works on the page's HTML as a string, exactly like the Python version reads
// Chrome's --dump-dom. Injected into the linked tab (where the page's own DOM decodes entities) and
// loadable in Node for tests (where a small entity table stands in).
(function (root) {
  'use strict';

  const NAMED = {
    amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', rsquo: '’', lsquo: '‘',
    rdquo: '”', ldquo: '“', mdash: '—', ndash: '–', hellip: '…', bull: '•',
    middot: '·', copy: '©', reg: '®', trade: '™', euro: '€', pound: '£',
  };

  // html.unescape: the browser's own decoder when there is a page, else numeric and common names
  function unescapeHtml(text) {
    if (!text || text.indexOf('&') < 0) return text;
    if (typeof document !== 'undefined' && document.createElement) {
      const box = document.createElement('textarea');
      box.innerHTML = text;
      return box.value;
    }
    return text.replace(/&(#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]*);?/g, (whole, name) => {
      if (name[0] === '#') {
        const code = name[1] === 'x' || name[1] === 'X' ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
        try { return String.fromCodePoint(code); } catch (e) { return whole; }
      }
      return Object.prototype.hasOwnProperty.call(NAMED, name) ? NAMED[name] : whole;
    });
  }

  // urllib.parse.unquote: lenient, a broken %-sequence stays as it is
  function unquote(text) {
    return (text || '').replace(/(%[0-9A-Fa-f]{2})+/g, (run) => {
      try { return decodeURIComponent(run); } catch (e) { return run; }
    });
  }

  // str.splitlines() and str.split()
  const splitLines = (text) => text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/);
  const squash = (text) => text.split(/\s+/).filter(Boolean).join(' ');

  function textFromHtml(html) {
    let body = html.replace(/<(script|style|head|noscript)[^>]*>[\s\S]*?<\/\1>/gi, ' ');
    body = body.replace(/<br\s*\/?>|<\/(p|div|tr|td|th|li|h\d|section|article)>/gi, '\n');
    body = body.replace(/<[^>]+>/g, '');
    body = unescapeHtml(body);
    body = body.replace(/[ \t ]+/g, ' ');
    body = body.replace(/\n\s*\n\s*\n+/g, '\n\n');
    return splitLines(body).map((line) => line.trim()).join('\n').trim();
  }

  // Inner HTML of the first element matching a simple selector: tag, .class, #id, or a mix
  function findElement(html, selector) {
    const parsed = /^([A-Za-z][\w-]*)?((?:[.#][\w-]+)*)$/.exec(selector.trim());
    if (!parsed) return null;
    const tag = parsed[1] || '[A-Za-z][\\w-]*';
    const wanted = (parsed[2] || '').match(/[.#][\w-]+/g) || [];
    const classes = wanted.filter((w) => w[0] === '.').map((w) => w.slice(1));
    const ids = wanted.filter((w) => w[0] === '#').map((w) => w.slice(1));
    const opening = new RegExp('<(' + tag + ')\\b([^>]*)>', 'gi');
    let open;
    while ((open = opening.exec(html))) {
      const found = /class\s*=\s*"([^"]*)"/i.exec(open[2]);
      const present = found ? found[1].split(/\s+/).filter(Boolean) : [];
      if (!classes.every((c) => present.includes(c))) continue;
      if (ids.length) {
        const foundId = /id\s*=\s*"([^"]*)"/i.exec(open[2]);
        if (!foundId || !ids.includes(foundId[1])) continue;
      }
      const name = open[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const pattern = new RegExp('<(/?)' + name + '\\b[^>]*>', 'gi');
      let depth = 1;
      pattern.lastIndex = opening.lastIndex;
      let next;
      while ((next = pattern.exec(html))) {
        depth += next[1] ? -1 : 1;
        if (depth === 0) return html.slice(opening.lastIndex, next.index);
      }
      return html.slice(opening.lastIndex);
    }
    return null;
  }

  // Readable text: no tags, no HTML entities, no stray whitespace. Vollna's row JSON is escaped
  // twice and carries <span class="keyword-highlighted"> markup.
  function plainText(value) {
    if (typeof value !== 'string') return value;
    let text = value;
    for (let i = 0; i < 3; i++) {                 // &amp;#x27; -> &#x27; -> '
      const unescaped = unescapeHtml(text);
      if (unescaped === text) break;
      text = unescaped;
    }
    text = text.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ');
    text = text.replace(/<br\s*\/?>|<\/(p|div|li)>/gi, '\n');
    text = text.replace(/<[^>]+>/g, '');
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    text = text.replace(/[ \t]+/g, ' ');
    text = text.replace(/\n{3,}/g, '\n\n');
    return text.split('\n').map((line) => line.replace(/\s+$/, '')).join('\n').trim();
  }

  function textLines(value) {
    if (typeof value !== 'string') return value;
    return value.split('\n').map((part) => part.trim()).filter(Boolean);
  }

  function screeningQuestions(context, html) {
    let asked = ((context || {}).clientQuestions || []).map(plainText).filter(Boolean);
    if (asked.length) return asked;
    const block = /Client(?:'|&#0?39;|&apos;|’)s questions:\s*<\/div>\s*<ul[^>]*>([\s\S]*?)<\/ul>/.exec(html || '');
    if (!block) return [];
    const items = [...block[1].matchAll(/<li[^>]*>([\s\S]*?)<\/li>/g)].map((m) => m[1]);
    return items.map(plainText).filter(Boolean);
  }

  // Who the page thinks you are, and whether Vollna refused to show it
  function pageContext(html) {
    const text = textFromHtml(html);
    const signed = /Signed in as\s*\n?\s*([\w.+-]+@[\w.-]+\.\w+)/.exec(text);
    const anyEmail = /[\w.+-]+@[\w.-]+\.\w+/.exec(text);
    return {
      account: signed ? signed[1] : (anyEmail ? anyEmail[0] : null),
      accessDenied: /do(?:n['’]t| not) have access to this page/i.test(text),
    };
  }

  // True when the page is Vollna's sign-in screen rather than the content asked for
  function needsLogin(html) {
    if (/type\s*=\s*["']password["']/i.test(html)) return true;
    const head = textFromHtml(html).slice(0, 400).toLowerCase();
    return ['sign in to', 'log in to', 'sign in with google'].some((sign) => head.includes(sign));
  }

  const CLIENT_CATEGORIES = ['Client Rank', 'Payment method verified', 'total spent', 'Hired number',
    'active job', 'Posted job', 'Hire rate', 'Opened job', 'avg hourly rate', 'total hours',
    'review score', 'review number', 'Registered', 'country', 'Region'];
  const PROJECT_CATEGORIES = ['Time per week', 'Project period', 'Expecting level', 'Project type'];
  const HISTORY_CATEGORIES = ['job title', 'feedback score to freelancer', 'written feedback to freelancer',
    'feedback score to client', 'written feedback to client', 'Project period',
    'project time commitment', 'hourly rate', 'total billed', 'payment type'];

  const blank = (names) => Object.fromEntries(names.map((name) => [name, null]));

  // Client details from a Vollna feed row
  function parseClient(html) {
    const found = blank(CLIENT_CATEGORIES);
    const lines = splitLines(textFromHtml(html));
    const start = lines.findIndex((line) => line.trim().startsWith('Client Rank'));
    if (start < 0) return found;

    const window = [];
    for (const line of lines.slice(start, start + 60)) {
      if (/^(Save job|Required Connects|Mark as)/.test(line.trim())) break;
      if (line.trim()) window.push(line.trim());
    }
    const block = window.join('\n');
    const digits = (text) => text.replace(/[\s,]/g, '');
    const grab = (pattern, clean = true) => {
      const hit = new RegExp(pattern, 'i').exec(block);
      if (!hit) return null;
      return clean ? digits(hit[1]) : hit[1].trim();
    };

    found['Client Rank'] = grab('Client Rank\\s*-?\\s*([A-Za-z ]+)', false);
    const payment = /Payment method (not verified|verified|unverified)/i.exec(block);
    found['Payment method verified'] = payment ? payment[1].toLowerCase() : null;
    const spent = grab('\\$([\\d\\s,]+)\\s*total spent');
    found['total spent'] = spent ? '$' + spent : null;
    found['Hired number'] = grab('([\\d\\s,]+)\\s*hires');
    found['active job'] = grab('([\\d\\s,]+)\\s*active');
    found['Posted job'] = grab('([\\d\\s,]+)\\s*jobs posted');
    found['Hire rate'] = grab('([\\d\\s,]+%)\\s*hire rate');
    found['Opened job'] = grab('([\\d\\s,]+)\\s*open job');
    const rate = grab('([\\d.,\\s]+)/hr avg hourly rate');
    found['avg hourly rate'] = rate ? rate + '/hr' : null;
    found['total hours'] = grab('([\\d\\s,]+)\\s*hours paid');
    if (/\bno reviews\b/i.test(block)) {
      found['review number'] = '0';            // new clients show "no reviews" instead of a score
    } else {
      found['review score'] = grab('([\\d.]+)\\s*\\n?\\s*of\\s+[\\d\\s,]+\\s*reviews');
      found['review number'] = grab('of\\s+([\\d\\s,]+)\\s*reviews');
    }
    found['Registered'] = grab('Registered:\\s*(.+)', false);

    // After "Registered:" Vollna prints the country (twice) and then the city
    const after = [];
    let seenRegistered = false;
    for (const line of window) {
      if (seenRegistered) after.push(line);
      if (line.toLowerCase().startsWith('registered:')) seenRegistered = true;
    }
    if (after.length) {
      found.country = after[0];
      for (const line of after.slice(1)) {
        if (line !== found.country && !/^\d{1,2}:\d{2}/.test(line) && !/^[\d.,]+$/.test(line)) {
          found.Region = line;
          break;
        }
      }
    }
    return found;
  }

  // How the job is set up: weekly hours, duration, experience level and one-time vs ongoing
  function parseProject(html) {
    const found = blank(PROJECT_CATEGORIES);
    const patterns = {
      'Time per week': /^(?:(?:Less|More) than\s*\d+\s*hrs?\/week|\d+\+?\s*hrs?\/week)$/i,
      'Project period': /^(?:Less than \d+ months?|More than \d+ months?|\d+\s*to\s*\d+\s*months?)$/i,
      'Expecting level': /^(?:Entry level|Intermediate|Expert)$/i,
      'Project type': /^(?:One-time project|Ongoing project|Complex project)$/i,
    };
    const lines = splitLines(textFromHtml(html));
    let start = lines.findIndex((line) => line.trim().startsWith('Client Rank'));
    if (start < 0) start = 0;
    for (let line of lines.slice(start, start + 260)) {
      line = line.trim();
      if (line.startsWith("Client's Work History")) break;      // end of the first job's details
      for (const [name, pattern] of Object.entries(patterns)) {
        if (found[name] === null && pattern.test(line)) found[name] = line;
      }
    }
    return found;
  }

  // One entry per past contract in Vollna's "Client's recent history" fragment
  function parseWorkHistory(fragment) {
    const entries = [];
    const running = /Jobs in progress\s*\((\d+)\)/.exec(fragment);
    const inProgress = running ? parseInt(running[1], 10) : 0;
    const blocks = fragment.split('<div class="flex items-start gap-2 justify-between">').slice(1);
    for (const block of blocks) {
      const entry = blank(HISTORY_CATEGORIES);
      entry.status = entries.length < inProgress ? 'in progress' : 'completed';

      const link = /<a\b[^>]*>([\s\S]*?)<\/a>/.exec(block);
      if (link) {
        entry['job title'] = squash(textFromHtml(link[1])) || null;
      } else {                                     // private jobs have no link
        const head = textFromHtml(block.split('Freelancer:')[0]);
        entry['job title'] = head.trim() ? splitLines(head)[0].trim() : null;
      }

      for (const [who, scoreKey, textKey] of [
        ['To freelancer:', 'feedback score to freelancer', 'written feedback to freelancer'],
        ['To client:', 'feedback score to client', 'written feedback to client']]) {
        const at = block.indexOf(who);
        if (at < 0) continue;
        // one side's feedback ends where the other side's starts, or at the date column
        const rest = block.slice(at + who.length);
        const end = /To (?:freelancer|client):|<div class="text-sm text-gray-600 w-\[200px\]/.exec(rest);
        const chunk = end ? rest.slice(0, end.index) : rest;
        const score = /<span class="text-sm font-medium">([\d.]+)<\/span>/.exec(chunk);
        if (score) entry[scoreKey] = score[1];
        // long feedback is cut off with a "More" button; the whole text sits in js-comment-full
        const written = /<span class="js-comment-full[^"]*">([\s\S]*?)<\/span>/.exec(chunk)
          || /<div class="text-sm text-gray-700 break-words">([\s\S]*?)<\/div>/.exec(chunk);
        if (written) entry[textKey] = squash(textFromHtml(written[1])) || null;
      }

      const column = /<div class="text-sm text-gray-600 w-\[200px\][^"]*"[^>]*>([\s\S]*?)<\/div>/.exec(block);
      if (column) {
        const flat = squash(textFromHtml(column[1]));
        const period = /^([A-Z][a-z]{2}\s+\d{4})(?:\s*-\s*([A-Z][a-z]{2}\s+\d{4}|Present))?/.exec(flat);
        if (period) entry['Project period'] = period[2] ? period[1] + ' - ' + period[2] : period[1];
        // hourly contracts read "5 hrs @ $31.50/hr Billed: $157.50", fixed-price ones "FIXED $69.00"
        const worked = /([\d,.]+)\s*hrs?\s*@\s*\$([\d,.]+)\/hr/.exec(flat);
        if (worked) {
          entry['payment type'] = 'hourly';
          entry['project time commitment'] = worked[1] + 'hrs';
          entry['hourly rate'] = '$' + worked[2] + '/hr';
        }
        const billed = /Billed:\s*\$([\d,.]+)/.exec(flat);
        if (billed) entry['total billed'] = '$' + billed[1];
        const fixed = /FIXED\s*\$([\d,.]+)/i.exec(flat);
        if (fixed) {
          entry['payment type'] = 'fixed';
          entry['total billed'] = '$' + fixed[1];
        }
      }
      entries.push(entry);
    }
    return entries;
  }

  const NAME_STOPWORDS = new Set(`a an the and or but so if then than that this these those it its he she they them him her
his their was were is are be been being have has had do does did very highly great good nice excellent brilliant
awesome perfect cool amazing wonderful pleasure happy glad thank thanks looking forward recommend recommended
client clients customer buyer employer contract project projects job jobs work working worked task tasks team
communication communications payment paid time timely fast quick easy clear kind friendly professional again
future hope will would can could i we you my our your all always much more best better experience hire hired
hiring freelancer person guy sir madam ok okay yes no cooperation collaboration test finished after agreed
english availability really lot`.split(/\s+/));

  // The client's own name, read out of what freelancers wrote to them: capitalised words that are
  // not ordinary praise vocabulary (the Python version can add spaCy; a browser has none).
  function clientName(history) {
    const counts = new Map();
    for (const entry of history || []) {
      const text = entry['written feedback to client'] || '';
      if (!text.trim()) continue;
      const found = new Set([...text.matchAll(/\b([A-Z][a-z]{1,14})\b/g)].map((m) => m[1])
        .filter((word) => !NAME_STOPWORDS.has(word.toLowerCase())));
      for (const name of found) counts.set(name, (counts.get(name) || 0) + 1);
    }
    if (!counts.size) return [null, 0];

    // "Dev" and "Devanshu" are the same person: merge a short form into the longer one it starts
    const ordered = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const groups = [];
    for (const [name, hits] of ordered) {
      const group = groups.find((g) => Object.keys(g.variants).some((other) =>
        name.toLowerCase().startsWith(other.toLowerCase()) || other.toLowerCase().startsWith(name.toLowerCase())));
      if (group) {
        group.variants[name] = hits;
        group.total += hits;
      } else {
        groups.push({ variants: { [name]: hits }, total: hits });
      }
    }
    const best = groups.reduce((a, b) => (b.total > a.total ? b : a));
    // the most used spelling wins; when equally used, the longer one rather than the short prefix
    const name = Object.entries(best.variants)
      .sort((a, b) => a[1] - b[1] || a[0].length - b[0].length).pop()[0];
    return [name, best.total];
  }

  // Every job row on a feed page, newest first, the way Vollna lists them
  function parseRows(html) {
    const rows = [];
    const MARK = 'data-project-context="';
    const marks = [];
    for (let at = html.indexOf(MARK); at >= 0; at = html.indexOf(MARK, at + 1)) marks.push(at);
    marks.forEach((mark, index) => {
      const raw = html.slice(mark + MARK.length).split('"', 1)[0];
      let context;
      try { context = JSON.parse(unescapeHtml(raw)); } catch (e) { return; }
      // a row runs from the end of the previous row to its own context marker: the client block
      // sits above the marker, the details below it
      const start = index ? marks[index - 1] : 0;
      const end = index + 1 < marks.length ? marks[index + 1] : html.length;
      const own = html.slice(mark, end).slice(0, 40000);
      const body = html.slice(start, mark) + own;

      // body also holds the previous row's details, links included, so the link must carry this
      // row's own pid; the first link in body would be the previous job's
      const projectId = String(context.projectId || '');
      let link = null;
      const pid = new RegExp('[?&;]pid=' + projectId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?:&|$)');
      const redirect = [...body.matchAll(/href="(\/go\?[^"]*url=[^"&]+)"/g)].find((m) => pid.test(m[1]));
      if (redirect) {
        const query = redirect[1].replace(/&amp;/g, '&').split('?').slice(1).join('?');
        const encoded = new URLSearchParams(query).get('url') || '';
        link = unquote(unquote(encoded)) || null;
      }
      if (!link) {
        // without a pid to match, only look below this row's own marker
        const direct = /https:\/\/www\.upwork\.com\/jobs\/(~\d+)/.exec(own);
        link = direct ? 'https://www.upwork.com/jobs/' + direct[1] : null;
      }

      rows.push({
        projectId,
        'Job title': plainText(context.title),
        'Job link': link,
        'Job description': plainText(context.description),
        // the row's JSON is the only safe source on a feed: the visible "Client's questions" list
        // sits above the NEXT row's marker
        'Screening Questions': screeningQuestions(context, null),
        skills: (context.skills || []).map(plainText),
        budget: context.budgetRaw || {},
        client: parseClient(body),
        project: parseProject(body),
      });
    });
    return rows;
  }

  const api = {
    unescapeHtml, textFromHtml, findElement, plainText, textLines, screeningQuestions, pageContext,
    needsLogin, parseClient, parseProject, parseWorkHistory, clientName, parseRows,
    CLIENT_CATEGORIES, PROJECT_CATEGORIES,
  };
  root.VollnaParse = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
