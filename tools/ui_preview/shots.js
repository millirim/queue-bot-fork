// Снимает скриншоты экранов панели на стенде tools/ui_preview/seed_server.py.
//   NODE_PATH=$(npm root -g) NO_PROXY=127.0.0.1 node tools/ui_preview/shots.js <папка с токенами> <папка для картинок> [страница ...]
// Каждый токен входа одноразовый: для новой съёмки перезапусти стенд. Ошибки консоли и CSP печатаются в конце.
const { chromium } = require('playwright'); const fs = require('fs');
const [dir, out, ...pages] = process.argv.slice(2); const B = 'http://127.0.0.1:8099';
const [personId, subjectId] = fs.readFileSync(dir + '/shots.txt', 'utf8').trim().split(' ');
const SCREENS = {
  home: '#/queue', queue: '#/queue/' + subjectId, polls: '#/polls', ideas: '#/ideas', help: '#/help', games: '#/games',
  requests: '#/manage/requests', people: '#/manage/people', person: '#/manage/people/' + personId, broadcast: '#/manage/broadcast', journal: '#/manage/journal',
  server: '#/system/status', features: '#/system/features', subjects: '#/system/subjects', backups: '#/system/backups', live: '#/system/live',
};
const STAFF = new Set(['requests', 'people', 'person', 'broadcast', 'journal']);
const ADMIN = new Set(['server', 'features', 'subjects', 'backups', 'live']);
// [токен, роль, тема, ширина, высота]: ta/tb — создатель, tf — староста, td/te — студент.
const SETUPS = [['ta', 'admin', 'light', 1280, 800], ['tb', 'admin', 'dark', 390, 844], ['tf', 'starosta', 'amoled', 390, 844],
  ['td', 'user', 'light', 390, 844], ['te', 'user', 'dark', 1280, 800]];
(async () => {
  const b = await chromium.launch(); const errors = [];
  const wanted = pages.length ? pages : Object.keys(SCREENS);
  for (const [token, role, theme, w, h] of SETUPS) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 }); const pg = await ctx.newPage();
    pg.on('pageerror', (e) => errors.push(`${token}: ${e}`)); pg.on('console', (m) => m.type() === 'error' && errors.push(`${token}: ${m.text()}`));
    await pg.addInitScript(`localStorage.setItem('qb-theme','${theme}')`);
    await pg.request.post(B + '/api/login', { data: { token: fs.readFileSync(`${dir}/${token}.txt`, 'utf8').trim() }, headers: { 'X-Queue-Bot': '1' } });
    for (const name of wanted) {
      if ((STAFF.has(name) && role === 'user') || (ADMIN.has(name) && role !== 'admin')) continue;
      await pg.goto(B + '/' + SCREENS[name]); await pg.waitForTimeout(1300);
      const wide = await pg.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      if (wide) errors.push(`${token}/${name}: горизонтальная прокрутка`);
      await pg.screenshot({ path: `${out}/${name}-${role}-${theme}-${w}.png`, fullPage: w < 600 });
    }
    await ctx.close();
  }
  console.log('ОШИБКИ:', errors.length ? '\n' + errors.slice(0, 20).join('\n') : 'нет'); await b.close();
})();
