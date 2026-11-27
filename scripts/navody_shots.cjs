// Screenshots for the UA/RU buying guides: node scripts/navody_shots.cjs <prefix> @scripts/navody_flows/<shop>.txt, then python3 scripts/navody_img.py $NAVOD_OUT
// Never submits an order: flows stop before the final button. Example data only (Olena Kovalenko, Vodičkova 1, Praha).
// node run.cjs <shop> cmd1 cmd2 ...   (persistent profile per shop, mobile 390x844 @2x)
// cmds: goto:URL | click:text | clicksel:css | fill:css=value | select:css=value | wait:ms | top:text (scroll element to top)
//       center:text | y:px | mark:text1|text2|sel:css (numbered circles+outline, in order) | unmark | shot:name | dump | blur:css (grey box)
const p = require(process.env.PUPPETEER_CORE || 'puppeteer-core');
const D = (process.env.NAVOD_OUT || '/tmp/navody') + '/';
const [shop, ...args] = process.argv.slice(2);
const cmds = args.flatMap(a => a.startsWith('@') ? require('fs').readFileSync(a.slice(1), 'utf8').split('\n').map(x => x.trim()).filter(x => x && !x.startsWith('#')) : [a]);
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1';
const FIND = (spec) => {
  // spec: "sel:css" or text (case-insensitive substring of visible element text/value/placeholder/label)
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  if (spec.startsWith('sel:')) return [...document.querySelectorAll(spec.slice(4))].find(vis) || null;
  const exact = spec.startsWith('=');
  const t = (exact ? spec.slice(1) : spec).toLowerCase();
  const cands = [...document.querySelectorAll('button, a, [role=button], input, select, textarea, label, h1, h2, h3, h4, span, div, p, td, th, strong, b')].filter(vis);
  const txt = e => ((e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || '') + '').trim().replace(/\s+/g, ' ').toLowerCase();
  const hits = cands.filter(e => exact ? txt(e) === t : txt(e).includes(t));
  // the smallest matching element (innermost)
  hits.sort((a, b) => a.getBoundingClientRect().width * a.getBoundingClientRect().height - b.getBoundingClientRect().width * b.getBoundingClientRect().height);
  return hits[0] || null;
};
(async () => {
  const b = await p.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--lang=cs-CZ'], userDataDir: D + 'profile-' + shop });
  let pg = (await b.pages())[0] || await b.newPage();
  await pg.setUserAgent(UA);
  await pg.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  await pg.setExtraHTTPHeaders({ 'Accept-Language': 'cs-CZ,cs;q=0.9' });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const settle = async () => { await sleep(1200); await pg.waitForNetworkIdle({ idleTime: 700, timeout: 15000 }).catch(() => {}); };
  const reattach = async () => {
    const ps = (await b.pages()).filter(x => !x.isClosed());
    pg = ps[ps.length - 1] || await b.newPage();
    await pg.setUserAgent(UA).catch(() => {});
    await pg.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }).catch(() => {});
  };
  for (let ci = 0, retried = false; ci < cmds.length; ci++) {
    const c = cmds[ci];
    const i = c.indexOf(':'), k = i < 0 ? c : c.slice(0, i), v = i < 0 ? '' : c.slice(i + 1);
    try {
      if (k === 'goto') { await pg.goto(v, { waitUntil: 'networkidle2', timeout: 60000 }).catch(e => console.log('goto', e.message)); await settle(); }
      else if (k === 'click' || k === 'clicksel') {
        const ok = await pg.evaluate((spec, F) => { const e = eval(F)(spec); if (!e) return false; e.scrollIntoView({ block: 'center' }); (e.closest('button, a, label, [role=button]') || e).click(); return true; }, k === 'clicksel' ? 'sel:' + v : v, FIND.toString());
        console.log(c, ok); await settle();
      }
      else if (k === 'fill') { const [s, val] = v.split(/=(.*)/s); await pg.evaluate(s => { const e = document.querySelector(s); e && e.scrollIntoView({ block: 'center' }); }, s); const e = await pg.$(s); if (e) { await e.click({ clickCount: 3 }).catch(() => {}); await e.type(val, { delay: 15 }); } console.log(c, !!e); }
      else if (k === 'set' || k === 'setq') { const [s, val] = v.split(/=(.*)/s); const ok = await pg.evaluate((s, val, k) => { const e = document.querySelector(s); if (!e) return false;
          const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, val);
          [k === 'set' ? 'input' : null, 'change', 'blur'].filter(Boolean).forEach(t => e.dispatchEvent(new Event(t, { bubbles: true }))); return true; }, s, val, k); console.log(c, ok); }
      else if (k === 'key') { await pg.keyboard.press(v); await sleep(300); }
      else if (k === 'select') { const [s, val] = v.split(/=(.*)/s); console.log(c, await pg.select(s, val)); await settle(); }
      else if (k === 'wait') await sleep(+v);
      else if (k === 'y') { await pg.evaluate(y => window.scrollTo(0, y), +v); await sleep(600); }
      else if (k === 'top' || k === 'center') {
        const ok = await pg.evaluate((spec, F, k) => { const e = eval(F)(spec); if (!e) return false; const r = e.getBoundingClientRect(); window.scrollTo(0, scrollY + r.top - (k === 'top' ? 90 : (innerHeight - r.height) / 2)); return true; }, v, FIND.toString(), k);
        console.log(c, ok); await sleep(700);
      }
      else if (k === 'mark') {
        const r = await pg.evaluate((specs, F) => {
          document.querySelectorAll('.rp-mark').forEach(x => x.remove());
          return specs.split('|').map((spec, n) => {
            let e = eval(F)(spec); if (!e) return spec + ':MISSING';
            if (!spec.startsWith('sel:')) { const box = e.closest('label, button, a, [role=button], li'); if (box && box.getBoundingClientRect().width < innerWidth * 0.98) e = box; }
            const r = e.getBoundingClientRect();
            const box = document.createElement('div'); box.className = 'rp-mark';
            Object.assign(box.style, { position: 'absolute', left: (r.left + scrollX - 4) + 'px', top: (r.top + scrollY - 4) + 'px', width: (r.width + 8) + 'px', height: (r.height + 8) + 'px',
              border: '3px solid #E5195E', borderRadius: '10px', zIndex: 2147483646, pointerEvents: 'none', boxSizing: 'border-box' });
            const dot = document.createElement('div'); dot.className = 'rp-mark'; dot.textContent = n + 1;
            const left = r.right + 40 < innerWidth ? r.right + scrollX + 6 : Math.min(Math.max(r.right + scrollX - 22, 2), scrollX + innerWidth - 36);
            Object.assign(dot.style, { position: 'absolute', left: left + 'px', top: (r.right + 40 < innerWidth ? r.top + scrollY + r.height / 2 - 16 : r.top + scrollY - 14) + 'px', width: '32px', height: '32px', borderRadius: '50%', background: '#E5195E',
              color: '#fff', font: '700 19px/32px Arial,sans-serif', textAlign: 'center', zIndex: 2147483647, pointerEvents: 'none', boxShadow: '0 1px 4px rgba(0,0,0,.4)' });
            document.body.append(box, dot);
            return spec + ':ok';
          });
        }, v, FIND.toString());
        console.log('mark', r.join(' '));
      }
      else if (k === 'unmark') await pg.evaluate(() => document.querySelectorAll('.rp-mark').forEach(x => x.remove()));
      else if (k === 'hide') await pg.evaluate(s => document.querySelectorAll(s).forEach(x => x.style.setProperty('display', 'none', 'important')), v);
      else if (k === 'blur') await pg.evaluate(s => document.querySelectorAll(s).forEach(x => { x.style.filter = 'blur(6px)'; }), v);
      else if (k === 'vh') { await pg.setViewport({ width: 390, height: +v, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }); await sleep(500); }
      else if (k === 'clean') {   // close popups/backdrops and floating chat bubbles before a shot
        await pg.evaluate((extra) => {
          document.querySelectorAll('.modal.show, .modal-backdrop, [class*=popup], [id*=popup], [class*=newsletter-modal], #chat-widget-root, [id*=chat-widget], [class*=chat-widget], #smartsupp-widget-container, iframe[title*=chat i], [id^=hubspot-messages]' + (extra ? ',' + extra : '')).forEach(x => x.style.setProperty('display', 'none', 'important'));
          document.querySelectorAll('.js-validator-msg, [class*=validator-msg], [class*=msg--error], [class*=error-message], .msg-error, [role=alert], .tooltip, [class*=whisper], [class*=autocomplete], [class*=suggest]').forEach(x => x.style.setProperty('display', 'none', 'important'));
          document.querySelectorAll('input, .form-group, [class*=validated]').forEach(x => [...x.classList].forEach(c => { if (/error|invalid|warning/i.test(c)) x.classList.remove(c); }));
          if (document.activeElement) document.activeElement.blur();
          document.body.classList.remove('modal-open'); document.body.style.overflow = ''; document.documentElement.style.overflow = '';
          document.querySelectorAll('body *').forEach(x => { const s = getComputedStyle(x); if (s.position !== 'fixed' || x.classList.contains('rp-mark')) return; const r = x.getBoundingClientRect();
            if ((r.top > innerHeight * 0.55 && r.width < 140 && r.height < 140) || (r.top > innerHeight * 0.6 && /Chceš slevu|slevu na první|newsletter/i.test(x.innerText || ''))) x.style.setProperty('display', 'none', 'important'); });
        }, v);
        await sleep(300);
      }
      else if (k === 'shot') { await pg.screenshot({ path: D + shop + '-' + v + '.png' }); console.log('shot', v); }
      else if (k === 'dump') {
        const info = await pg.evaluate(() => {
          const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
          const out = [];
          document.querySelectorAll('button, a, [role=button], input, select, textarea, label, h1, h2, h3').forEach(e => {
            if (!vis(e)) return; const r = e.getBoundingClientRect();
            let t = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 70);
            if (e.tagName === 'A' && !/košík|objedn|pokrač|zpět|dopr|platb|přihl|registr|kup|koupit|smaz|odebr/i.test(t)) return;
            const id = e.id ? '#' + e.id : (e.name ? '[name=' + e.name + ']' : '');
            if (t || id) out.push(`${e.tagName.toLowerCase()}${e.type ? '[' + e.type + ']' : ''}${id} y=${Math.round(r.top + scrollY)} "${t}"`);
          });
          return { url: location.href, h: document.documentElement.scrollHeight, els: out.slice(0, 120) };
        });
        console.log('== dump', info.url, 'h', info.h); info.els.forEach(x => console.log('  ', x));
      }
      retried = false;
    } catch (e) {
      if (!retried && /detached|Session closed|Target closed/i.test(e.message)) { retried = true; await reattach(); await sleep(1500); ci--; continue; }
      retried = false;
      console.log('ERR', c, e.message);
    }
  }
  await b.close();
})();
