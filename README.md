# Scraper

Pulls data out of web pages **through the Chrome window you already use**, so anything you are
signed into stays signed in. Nothing to install: it uses the Python that ships with macOS and
drives Chrome through AppleScript.

## One-time setup

1. In Chrome: **View → Developer → Allow JavaScript from Apple Events**.
2. The first run makes macOS ask whether your terminal may control Chrome — allow it.
   (Later: System Settings → Privacy & Security → Automation.)

## Use

```bash
python3 scrape.py recipes/example.json                 # run a recipe
python3 scrape.py recipes/vollna-result.json --json    # raw JSON instead of text
python3 scrape.py --url https://example.com --text     # no recipe, just the page text
python3 scrape.py recipes/x.json --url https://site/other-page   # same recipe, different page
```

The page opens in Chrome, the script waits until it has loaded, prints the result, and saves a
copy under `out/`.

**When a login is needed** the script prints `LOGIN NEEDED`, leaves the page open, and keeps
waiting (5 minutes by default, `--wait 600` for longer). Log in in Chrome and it carries on by
itself. Because it is your normal Chrome profile, you usually only have to do this once per site.

## Headless mode (own Chrome profile, no permissions needed)

This renders the page in a Chrome profile that belongs to the scraper, so JavaScript-built pages
work and nothing has to be enabled in your everyday Chrome.

```bash
python3 scrape.py recipes/vollna-result.json --login      # opens a window: log in, then close it
python3 scrape.py recipes/vollna-result.json --headless   # renders and prints the text
python3 scrape.py recipes/vollna-result.json --headless --save-html   # also keep the HTML
```

The login is remembered in `chrome-profile/`, so `--login` is usually a one-off per site. The
profile can only be used by one Chrome at a time: close the login window before scraping. macOS
may ask once for Keychain access — allow it, or the saved login can't be read back.

## Without Chrome automation: saved pages

If Chrome won't allow Apple Events, or a site is awkward to automate, save the page instead:
open it in the browser, press **Cmd+S**, choose **Page Source**, save it into `pages/`,
then:

```bash
python3 scrape.py --file pages/whatever.html
python3 scrape.py recipes/vollna-result.json --file pages/whatever.html
```

This reads the file directly, with no browser and no permissions. It returns the page's readable
text (selectors are ignored in this mode).

## Recipes

A recipe is a JSON file describing one page and what to take from it.

```json
{
  "name": "vollna-result",
  "url": "https://www.vollna.com/dashboard/monitoring/result41173302",
  "loginWhen": { "textIncludes": ["Sign in to Vollna"], "urlIncludes": "/login" },
  "waitFor": "table tbody tr",
  "fields": {
    "heading": "h1",
    "jobs": {
      "each": "table tbody tr",
      "fields": {
        "title": "td:nth-child(1)",
        "link": { "selector": "td:nth-child(1) a", "attr": "href" },
        "budget": "td:nth-child(2)"
      }
    }
  }
}
```

| Key | Meaning |
|---|---|
| `url` | Page to open. `--url` overrides it. |
| `loginWhen` | How to spot a sign-in page: `selector`, `textIncludes` (list), `urlIncludes`. |
| `waitFor` | CSS selector that must exist before extracting (for pages that load late). |
| `fields` | What to extract. Omit it to get the page text instead. |
| `text` | `true` also includes the page's readable text. |
| `textSelector` | Limit that text to one part of the page, e.g. `"main"`. |

Field forms:

- `"title": "h1"` — text of the first match.
- `"link": { "selector": "a.title", "attr": "href" }` — an attribute instead of text.
- `"skills": { "selector": ".skill", "all": true }` — every match, as a list.
- `"jobs": { "each": "tr", "fields": { … } }` — a list of rows, each with its own fields.
- `"html": true` on any field returns inner HTML rather than text.

## Finding selectors

In Chrome, right-click the part of the page you want → **Inspect** → right-click the highlighted
element → **Copy → Copy selector**. Paste that into the recipe and trim it down to something
stable (a class name usually survives longer than `div:nth-child(7)`).

## Files

| File | Purpose |
|---|---|
| `scrape.py` | The script: opens the page, waits for load/login, extracts, prints, saves. |
| `chrome.js` | Small AppleScript (JXA) helper that runs JavaScript inside your Chrome tab. |
| `recipes/` | One JSON file per page you scrape. |
| `out/` | Results, one timestamped JSON per run. |

## Limits

- Chrome must be running and not blocking Apple Events (see setup).
- The tab is left open so you can see what was read.
- Sites that forbid automated access in their terms are your call to respect; this only reads
  pages you are already allowed to see, in your own browser.
