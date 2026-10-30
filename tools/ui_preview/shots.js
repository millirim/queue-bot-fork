// Снимает скриншоты экранов панели на стенде tools/ui_preview/seed_server.py.
//   NODE_PATH=$(npm root -g) NO_PROXY=127.0.0.1 node tools/ui_preview/shots.js <папка с токенами> <папка для картинок> [страница ...]
// Страницы по умолчанию — основные экраны. Каждый токен входа одноразовый: для новой съёмки перезапусти стенд.
const { chromium } = require('playwright'); const fs = require('fs');
const [dir, out, ...pages] = process.argv.slice(2); const B = 'http://127.0.0.1:8099';
const [personId, subjectId] = fs.readFileSync(dir + '/shots.txt', 'utf8').trim().split(' ');
const SCREENS = {
  overview: (id) => '#/overview', queues: () => '#/queues', queue: () => '#/queue/' + subjectId, my: () => '#/my', people: () => '#/people', person: () => '#/people/' + personId,
  requests: () => '#/requests', broadcast: () => '#/broadcast', journal: () => '#/journal', subjects: () => '#/subjects', polls: () => '#/polls',
  suggestions: () => '#/suggestions', rules: () => '#/rules', server: () => '#/server', live: () => '#/live', games: () => '#/games',
};
(async () => {
  const b = await chromium.launch(); const errors = [];
  // [токен, тема, ширина, высота, суффикс в имени файла]
  const setups = [['ta', 'light', 1280, 800, 'desktop-light'], ['tb', 'dark', 390, 844, 'phone-dark']];
  const wanted = pages.length ? pages : ['overview', 'queue', 'people', 'broadcast', 'polls', 'server'];
  for (const [token, theme, w, h, suffix] of setups) {
    const ctx = await b.newContext({ viewport: { width: w, height: h } }); const pg = await ctx.newPage();
    pg.on('pageerror', (e) => errors.push(String(e))); pg.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    await pg.addInitScript(`localStorage.setItem('qb-theme','${theme}')`);
    await pg.request.post(B + '/api/login', { data: { token: fs.readFileSync(`${dir}/${token}.txt`, 'utf8').trim() }, headers: { 'X-Queue-Bot': '1' } });
    for (const name of wanted) {
      await pg.goto(B + '/' + SCREENS[name]()); await pg.waitForTimeout(1500);
      await pg.screenshot({ path: `${out}/${name}-${suffix}.png` });
    }
    await ctx.close();
  }
  console.log('ОШИБКИ В КОНСОЛИ:', JSON.stringify(errors.slice(0, 8))); await b.close();
})();
