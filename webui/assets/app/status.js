// Связь с сервером: пинг и время сервера. Меряем раз в 3 секунды, пока вкладка открыта (/api/ping лёгкий и в счётчики не попадает).
// Показываем маленькой строкой сверху (ping chip) и на вкладке «Система → Сервер».
import { h, pad } from "./core.js";

export const clock = { samples: [], offset: null, tz: 0, uptimeAt: null, lost: 0, online: null };
const KEEP = 20;

async function pingOnce() {
  const wall0 = Date.now(), t0 = performance.now();
  try {
    const res = await fetch("/api/ping", { cache: "no-store", credentials: "same-origin" });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    const rtt = performance.now() - t0;
    clock.samples.push({ rtt, offset: data.now - (wall0 + rtt / 2) });   // как в NTP: сервер ответил примерно посередине пути
    if (clock.samples.length > KEEP) clock.samples.shift();
    clock.offset = clock.samples.reduce((a, b) => (b.rtt < a.rtt ? b : a)).offset;
    clock.tz = data.tz;
    clock.uptimeAt = { uptime: data.uptime, at: performance.now() };
    clock.online = true;
  } catch (e) {
    clock.lost++;
    clock.online = false;
  }
}

export const lastPing = () => (clock.samples.length ? clock.samples[clock.samples.length - 1].rtt : null);
export const avgPing = () => (clock.samples.length ? clock.samples.reduce((a, s) => a + s.rtt, 0) / clock.samples.length : null);
export function serverTime() {
  if (clock.offset == null) return null;
  const d = new Date(Date.now() + clock.offset + clock.tz * 60000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}
export const uptimeSeconds = () => (clock.uptimeAt ? clock.uptimeAt.uptime + (performance.now() - clock.uptimeAt.at) / 1000 : null);

// Строка сверху: точка (цвет по качеству связи), пинг и время сервера. Возвращает элемент и функцию остановки.
export function startStatus(isActive) {
  const dot = h("i", { class: "dot" }), ms = h("span", { class: "ping-ms", text: "—" }), time = h("span", { class: "ping-time", text: "" });
  const el = h("div", { class: "ping", role: "status", title: "Пинг до сервера и время сервера", "aria-label": "Связь с сервером" }, dot, ms, time);
  const paint = () => {
    const p = lastPing();
    const down = clock.online === false;
    ms.textContent = down ? "нет связи" : p == null ? "—" : `${Math.round(p)} мс`;
    dot.className = "dot " + (down ? "down" : p == null ? "" : p < 120 ? "good" : p < 300 ? "mid" : "poor");
    time.textContent = down ? "" : serverTime() || "";
  };
  let pingTimer = 0, paintTimer = 0;
  const loop = async () => {
    if (!isActive()) { stop(); return; }
    if (!document.hidden) { await pingOnce(); paint(); }
    pingTimer = setTimeout(loop, 3000);
  };
  const stop = () => { clearTimeout(pingTimer); clearInterval(paintTimer); };
  paintTimer = setInterval(() => { if (!document.hidden) paint(); }, 500);   // секунды идут между замерами
  document.addEventListener("visibilitychange", () => { if (!document.hidden && isActive()) { clearTimeout(pingTimer); loop(); } });
  pingTimer = setTimeout(loop, 0);   // не сразу: оболочка ещё не показана, isActive() покажет «да» на следующем такте
  return { el, stop };
}
