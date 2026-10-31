// «Игры» живут в отдельной службе; экран рисует оболочка webui/assets/games/shell.js.
export const page = (el, params, token) => window.QB_GAMES.page(el, params[0], token);
