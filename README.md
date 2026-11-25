# repasovanyiphone.cz

Static price comparison of refurbished, like-new and open-box iPhones in the Czech Republic.

- `scripts/fetch.py` downloads the shops' product feeds (eHub XML exports, CJ product search) into `data/raw/`; `--coupons` = valid eHub voucher codes
- `scripts/parse.py` recognises model, storage, quality (Nový/A+/A/B/C), official Apple colour (`data/colors.json`), battery and eSIM-only; `coupon_effect()` reads voucher rules
- `scripts/photos.py` keeps a self-hosted photo library per model and colour (clean renders first; MobileGear's watermarked screen is blanked)
- `scripts/build.py` writes plain HTML into `dist/` (configurator per model, model x storage, category landings, shops, guides, sitemap with images, `_redirects`)
- `scripts/seo_lint.py` checks the build (broken links, titles, canonicals, JSON-LD, sitemap); a hard error stops the deploy
- `scripts/deploy.py` uploads `dist/` as Cloudflare Workers static assets (no Worker code, nothing billed)
- `.github/workflows/build.yml` runs it every night at 01:10 CET; "Run workflow" with **quick** rebuilds without fetching (~1 min)

Local: `python3 scripts/fetch.py && python3 scripts/build.py && (cd dist && python3 -m http.server)`.
Keys are never in this public repo: GitHub secrets in Actions, `~/ai/credentials/` locally (`scripts/localenv.py`).
Shop list: `data/shops.json`; iPhone models and launch specs: `data/models.json`; guides: `content/guides/*.html`.
