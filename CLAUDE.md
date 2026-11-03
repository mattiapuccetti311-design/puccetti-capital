# Puccetti Capital Research

Static website publishing equity and start-up research notes by Mattia Puccetti (BBA, EDHEC Business School).
Hosted on GitHub Pages from `main` at https://mattiapuccetti311-design.github.io/puccetti-capital. No framework, no bundler, no package.json.

## Layout

- `index.html`: the whole site. One file holding the CSS, the inline JS and every page (`#home`, `#research`, `#markets`, `#find`, `#calendar`, `#esg`, `#demo`, `#news`, `#methodology`). Routing is hash-based (`location.hash`).
- `404.html`: **byte-for-byte copy of `index.html`** (GitHub Pages fallback). After editing `index.html`, always run `cp index.html 404.html`.
- `notes/<slug>.html`: one HTML fragment per research note, fetched by `index.html` and shown at `#<slug>`.
- `notes/index.json`: note registry, newest first. Fields: `slug, date, sector, country, company, ticker, headline, rating, target, price, potential`. Add `"private": true` for start-ups; external pieces use `"external": "<url>"` and no slug.
- `data/market.json`: **hand-maintained** per-note data (price series, dividends, our target and rating, analyst consensus, ESG, news, next results). Keyed by note slug. `type` is `listed` or `private`.
- `data/markets/*.json`: **generated** by `tools/update_markets.py`. Do not edit by hand.
- `pdf/<slug>.pdf`: printable version of each note, built by `tools/make-pdf.js`.
- `sw.js`: network-first service worker. Bump `CACHE` (`pcr-vN`) when you change cached shell files.
- `manifest.webmanifest`, `icons/`: PWA files.

## Commands

There is no build step and no test suite. These are the checks to run instead.

```bash
# Serve the site locally (it fetches JSON, so file:// will not work)
python3 -m http.server 8000      # then open http://localhost:8000/#home

# Refresh market data (needs network access to Wikipedia and Yahoo Finance; slow, up to ~2 h)
pip install yfinance pandas lxml requests
python tools/update_markets.py
#   env: TARGETS_PER_RUN (default 2800), FETCH_ESG=1 to refresh the ESG cache

# Build note PDFs (deps dir needs chart.js@4.4.1 and @fontsource/source-serif-4,
# @fontsource/ibm-plex-sans, @fontsource/ibm-plex-mono in node_modules; Playwright is preinstalled)
node tools/make-pdf.js . <deps-dir> [slug ...]   # no slugs = every note without a PDF

# Checks before committing
python3 -m py_compile tools/update_markets.py
python3 -c "import json;[json.load(open(f)) for f in ['notes/index.json','data/market.json']]"
cmp index.html 404.html
```

Smoke test: serve the site, open `#home`, `#research`, `#markets` and the changed note with Playwright, and fail on any `pageerror`.

## CI

`.github/workflows/update-markets.yml` runs `update_markets.py` on weekdays at 16:47 and 22:37 UTC (and on pushes to `main` that touch the script or workflow), then commits `data/markets` as `puccetti-capital-bot` with the message `Market data YYYY-MM-DD`. Expect bot commits on `main`; pull or rebase before pushing.

## Adding a research note

1. Write `notes/<slug>.html`, copying the structure of an existing note (e.g. `notes/adyen.html`): `.notehead` (rating, target, price, potential), a `.rail` with section links `<a href="#<slug>" data-jump="<prefix>-sN">`, and `section.sec` blocks with ids `<prefix>-s1`, `<prefix>-s2`, … where `<prefix>` is a short company tag (`ady`, `bnp`…).
2. Charts go in one trailing `<script>` that sets `window.NOTE_DRAW=function(){…}`, pushes each Chart into `charts`, and reads colours with `css('--var')` so light and dark themes both work.
3. Add the entry at the top of `notes/index.json` and the company block in `data/market.json`.
4. Build `pdf/<slug>.pdf`.
5. Commit message: `Add note: <Company> (YYYY-MM-DD)`.

## Code style

- Vanilla HTML/CSS/JS, compact (often minified-style) inline code. Match the surrounding density; don't reformat existing code.
- External scripts only Chart.js 4.4.1 from cdnjs; fonts from Google Fonts (Source Serif 4, IBM Plex Sans, IBM Plex Mono).
- Colours only through the CSS variables on `:root`, with dark-mode overrides (`prefers-color-scheme` and `[data-theme="dark"]`). Never hard-code hex in new UI.
- Must work at phone width with no horizontal scroll.
- Python: standard library plus pandas, requests, yfinance. Each index is processed on its own so one failing source keeps the previous file.

## Writing style for notes

- English, plain and direct sentences. Bold lead sentence states the rating, the target and the upside versus a dated close.
- Ratings: listed companies `BUY`, `HOLD`, `REDUCE`; start-ups `STRETCHED` (and similar), with a value against the latest funding round. Market reviews use `REVIEW`.
- Prices in the note's currency with the date of the close; cite sources (Yahoo Finance, company reports, consensus provider and date).
- Keep the disclaimer: academic research, not investment advice.

## Notes

- Some of Mattia's commits are GitHub web uploads ("Add files via upload"), which sometimes create files like `index 2.json`. Check filenames after an upload.
- `tools/__pycache__/` is committed by mistake; don't add more `.pyc` files.
