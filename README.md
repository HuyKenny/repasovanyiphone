# repasovanyiphone.cz

Static price comparison of refurbished, like-new and open-box iPhones in the Czech Republic.

- `scripts/fetch.py` downloads the shops' product feeds (eHub XML exports, CJ product search) into `data/raw/`
- `scripts/parse.py` recognises model, storage, condition grade, colour, battery and eSIM-only from titles and parameters
- `scripts/build.py` writes plain HTML into `dist/` (model pages, model x storage pages, shops, guides, sitemap); 0.3 s
- `scripts/deploy.py` uploads `dist/` as Cloudflare Workers static assets (no Worker code, nothing billed)
- `.github/workflows/build.yml` runs it every night at 01:10 CET; "Run workflow" with **quick** rebuilds without fetching (~1 min)

Local: `python3 scripts/fetch.py && python3 scripts/build.py && (cd dist && python3 -m http.server)`.
Keys are never in this public repo: GitHub secrets in Actions, `~/ai/credentials/` locally (`scripts/localenv.py`).
Shop list: `data/shops.json`; iPhone models and launch specs: `data/models.json`; guides: `content/guides/*.html`.
