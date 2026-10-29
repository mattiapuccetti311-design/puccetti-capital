// Builds pdf/<slug>.pdf for each research note.
// Usage: node tools/make-pdf.js <site-dir> <deps-dir> [slug ...]
//   <deps-dir> must contain node_modules with chart.js@4.4.1 and
//   @fontsource/source-serif-4, @fontsource/ibm-plex-sans, @fontsource/ibm-plex-mono.
//   Without slugs, every note in notes/index.json without a PDF is built.
const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const site = path.resolve(process.argv[2] || '.');
const deps = path.resolve(process.argv[3] || '.');
let slugs = process.argv.slice(4);
const nm = path.join(deps, 'node_modules');
const TYPES = { '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.js': 'text/javascript', '.png': 'image/png', '.webmanifest': 'application/manifest+json', '.pdf': 'application/pdf' };

const reg = JSON.parse(fs.readFileSync(path.join(site, 'notes/index.json'), 'utf8')).filter(e => !e.external);
if (!slugs.length) slugs = reg.map(e => e.slug).filter(s => !fs.existsSync(path.join(site, 'pdf', s + '.pdf')));
fs.mkdirSync(path.join(site, 'pdf'), { recursive: true });

function fontCss() {
  const fam = [['Source Serif 4', 'source-serif-4', [[500, 'normal'], [600, 'normal'], [700, 'normal'], [500, 'italic']]],
               ['IBM Plex Sans', 'ibm-plex-sans', [[400, 'normal'], [500, 'normal'], [600, 'normal']]],
               ['IBM Plex Mono', 'ibm-plex-mono', [[400, 'normal'], [500, 'normal']]]];
  let css = '';
  for (const [name, pkg, ws] of fam) for (const [w, st] of ws) for (const sub of ['latin', 'latin-ext']) {
    const f = `${pkg}-${sub}-${w}-${st}.woff2`;
    if (fs.existsSync(path.join(nm, '@fontsource', pkg, 'files', f)))
      css += `@font-face{font-family:'${name}';font-style:${st};font-weight:${w};font-display:block;src:url(/__fonts/${pkg}/${f}) format('woff2')}\n`;
  }
  return css;
}

const server = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]);
  let f;
  if (u.startsWith('/__fonts/')) { const [, , pkg, file] = u.split('/'); f = path.join(nm, '@fontsource', pkg, 'files', file); }
  else f = path.join(site, u === '/' ? 'index.html' : u);
  if (!f.startsWith(site) && !f.startsWith(nm)) { res.writeHead(403); return res.end(); }
  fs.readFile(f, (err, buf) => {
    if (err) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': f.endsWith('.woff2') ? 'font/woff2' : (TYPES[path.extname(f)] || 'application/octet-stream') });
    res.end(buf);
  });
});

(async () => {
  await new Promise(r => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 700, height: 1000 }, serviceWorkers: 'block' });
  await ctx.route('**/chart.umd.min.js', r => r.fulfill({ path: path.join(nm, 'chart.js/dist/chart.umd.js'), contentType: 'text/javascript' }));
  await ctx.route(/fonts\.googleapis\.com/, r => r.fulfill({ body: fontCss(), contentType: 'text/css' }));
  await ctx.route(/fonts\.gstatic\.com/, r => r.abort());
  for (const slug of slugs) {
    const e = reg.find(x => x.slug === slug);
    if (!e) { console.log('skip (not in registry):', slug); continue; }
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', x => errors.push(x.message));
    await page.emulateMedia({ media: 'print' });
    await page.goto(`${base}/#${slug}`);
    await page.waitForSelector('.notehead', { timeout: 20000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(2500);
    await page.evaluate(() => { if (window.charts) window.charts.forEach(c => { c.resize(); c.update('none'); }); });
    await page.waitForTimeout(500);
    const out = path.join(site, 'pdf', slug + '.pdf');
    await page.pdf({
      path: out, format: 'A4', printBackground: true,
      margin: { top: '14mm', bottom: '16mm', left: '12mm', right: '12mm' },
      displayHeaderFooter: true,
      headerTemplate: `<div style="font:8px Helvetica,Arial,sans-serif;color:#667;width:100%;padding:0 12mm;display:flex;justify-content:space-between"><span>Puccetti Capital Research</span><span>${e.company} · ${e.date}</span></div>`,
      footerTemplate: `<div style="font:8px Helvetica,Arial,sans-serif;color:#667;width:100%;padding:0 12mm;display:flex;justify-content:space-between"><span>Academic research by Mattia Puccetti, EDHEC Business School. Not investment advice.</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
    });
    console.log('ok', slug, (fs.statSync(out).size / 1024).toFixed(0) + ' KB', errors.length ? 'errors: ' + errors.join(' | ') : '');
    await page.close();
  }
  await browser.close();
  server.close();
})();
