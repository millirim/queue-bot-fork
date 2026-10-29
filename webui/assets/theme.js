// Тема ставится до отрисовки, чтобы страница не мигала светлой. system — по настройке устройства.
(function () {
  var theme = "system";
  try { theme = localStorage.getItem("qb-theme") || "system"; } catch (e) { /* хранилище недоступно */ }
  if (theme !== "system") document.documentElement.setAttribute("data-theme", theme);
})();
