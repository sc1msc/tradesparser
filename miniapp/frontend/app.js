// honestlot - мини-апп Telegram. Чистый JavaScript без сборки: браузер
// загружает этот файл как есть. Экраны: лента, избранное, карточка лота,
// фильтры. Все данные - с бэкенда (/api/*), процент к рынку и текущая цена
// считаются там, фронт их только показывает.

const tg = window.Telegram && window.Telegram.WebApp;
const IN_TG = !!(tg && tg.initData);
const PAGE = 20;
const BOT = "honestlot_bot";

if (tg) { tg.ready(); tg.expand(); }
document.documentElement.classList.toggle("tg", IN_TG);

function applyScheme() {
  const dark = IN_TG ? tg.colorScheme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
}
applyScheme();
if (IN_TG) tg.onEvent("themeChanged", applyScheme);

// ---------- утилиты ----------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v; // только для своих SVG-иконок
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  search: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  filter: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>',
  heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 20.5s-7.5-4.6-9.2-9.3C1.6 7.8 3.9 4.5 7.3 4.5c2 0 3.5 1.1 4.7 2.7 1.2-1.6 2.7-2.7 4.7-2.7 3.4 0 5.7 3.3 4.5 6.7-1.7 4.7-9.2 9.3-9.2 9.3z"/></svg>',
  heartOn: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 20.5s-7.5-4.6-9.2-9.3C1.6 7.8 3.9 4.5 7.3 4.5c2 0 3.5 1.1 4.7 2.7 1.2-1.6 2.7-2.7 4.7-2.7 3.4 0 5.7 3.3 4.5 6.7-1.7 4.7-9.2 9.3-9.2 9.3z"/></svg>',
  list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="7" height="7" rx="2"/><rect x="3" y="13" width="7" height="7" rx="2"/><path d="M13 6h8M13 9h5M13 15h8M13 18h5"/></svg>',
  car: '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M5 16H3v-4l2-5h14l2 5v4h-2M7 16h10"/><circle cx="7" cy="16.5" r="1.8"/><circle cx="17" cy="16.5" r="1.8"/></svg>',
  back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
};
const icon = (name) => h("span", { html: ICONS[name], style: { display: "contents" } });

const nf = new Intl.NumberFormat("ru-RU");
const rub = (n) => (n == null ? "—" : nf.format(n) + " ₽");
function short(n) {
  if (n >= 1e6) return (Math.round(n / 1e4) / 100).toString().replace(".", ",") + " млн";
  if (n >= 1e3) return Math.round(n / 1e3) + " тыс.";
  return String(n);
}
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}
const MSK = { timeZone: "Europe/Moscow" };
const dateFmt = (iso, o) => new Intl.DateTimeFormat("ru-RU", { ...MSK, ...o }).format(new Date(iso));
const dShort = (iso) => dateFmt(iso, { day: "numeric", month: "short" }).replace(".", "");
const dLong = (iso) => dateFmt(iso, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

// short=true - для карточки в ленте, где мало места: "22 ч", "7 дн".
function timeLeft(iso, short) {
  const ms = new Date(iso) - Date.now();
  if (ms <= 0) return "завершён";
  const hours = ms / 36e5;
  if (hours < 1) return short ? "< 1 ч" : "меньше часа";
  if (hours < 24) { const n = Math.floor(hours); return `${n} ${short ? "ч" : plural(n, "час", "часа", "часов")}`; }
  const d = Math.floor(hours / 24);
  return `${d} ${short ? "дн" : plural(d, "день", "дня", "дней")}`;
}
const isSoon = (iso) => new Date(iso) - Date.now() < 48 * 36e5;
const regionShort = (r) => (r || "").replace(/^г\.\s*/, "").replace("Московская область", "МО");
const kmText = (it) => it.mileage_km == null ? null : (it.mileage_estimated ? "~" : "") + nf.format(it.mileage_km) + " км";

function gapBadge(gap) {
  if (gap == null) return null;
  const r = Math.round(gap);
  if (gap >= 0.5) return h("span", { class: "gap good" }, `−${r}% к рынку`);
  if (gap > -0.5) return h("span", { class: "gap neutral" }, "≈ рынок");
  return h("span", { class: "gap neutral" }, `+${-r}% к рынку`);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem("hl_" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("hl_" + k, JSON.stringify(v)); } catch { /* приватный режим и т.п. */ } },
};

let toastTimer;
function toast(text) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = h("div", { class: "toast" }, text);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 2200);
}
const haptic = (kind) => { try { tg && tg.HapticFeedback.impactOccurred(kind || "light"); } catch { /* вне Telegram */ } };
function openLink(url) { if (IN_TG) tg.openLink(url); else window.open(url, "_blank", "noopener"); }
// Аналитика: ошибки не показываем пользователю - это не его забота.
function track(type, lotId) {
  api("/events", { method: "POST", keepalive: true, body: JSON.stringify({ type, lot_id: lotId || null }) })
    .catch(() => {});
}

// ---------- API ----------

class AuthError extends Error {}
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {
    ...opts,
    headers: {
      Authorization: "tma " + ((tg && tg.initData) || ""),
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (r.status === 401) throw new AuthError(await r.text());
  if (!r.ok) throw new Error(`Ошибка ${r.status}`);
  return r.json();
}

// ---------- состояние ----------

const emptyFilters = () => ({ brands: [], models: {}, year: null, price: null, mileageTo: null, gapMin: null, regions: [], trade: [] });
const SORTS = [["gap", "Выгоднее"], ["deadline", "Скоро дедлайн"], ["price_asc", "Дешевле"], ["price_desc", "Дороже"]];

const state = {
  tab: "feed",
  filters: { ...emptyFilters(), ...store.get("filters", {}) },
  sort: store.get("sort", "gap"),
  q: "",
  items: [],
  total: 0,
  facets: null,
  favIds: new Set(),
  stack: [],       // открытые поверх вкладок экраны: {kind: "lot"|"filters", ...}
  scrolls: [],
  reqId: 0,
};

function queryString(filters, q, sort) {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (sort) p.set("sort", sort);
  if (filters.brands.length) p.set("brands", filters.brands.join(","));
  const models = [];
  for (const [b, ms] of Object.entries(filters.models)) for (const m of ms) models.push(`${b}|${m}`);
  if (models.length) p.set("models", models.join(","));
  if (filters.year) { if (filters.year[0] != null) p.set("year_from", filters.year[0]); if (filters.year[1] != null) p.set("year_to", filters.year[1]); }
  if (filters.price) { if (filters.price[0] != null) p.set("price_from", filters.price[0]); if (filters.price[1] != null) p.set("price_to", filters.price[1]); }
  if (filters.mileageTo != null) p.set("mileage_to", filters.mileageTo);
  if (filters.gapMin != null) p.set("gap_min", filters.gapMin);
  if (filters.regions.length) p.set("regions", filters.regions.join(","));
  if (filters.trade.length) p.set("trade", filters.trade.join(","));
  return p.toString();
}

function activeFilterCount(f) {
  return [f.brands.length, f.year, f.price, f.mileageTo != null, f.gapMin != null, f.regions.length, f.trade.length]
    .filter(Boolean).length;
}

// ---------- избранное ----------

async function toggleFav(id) {
  const on = !state.favIds.has(id);
  on ? state.favIds.add(id) : state.favIds.delete(id);
  syncHearts(id);
  haptic();
  try {
    await api(`/favorites/${id}`, { method: on ? "PUT" : "DELETE" });
    toast(on ? "Добавлено в избранное" : "Убрано из избранного");
  } catch (e) {
    on ? state.favIds.delete(id) : state.favIds.add(id);
    syncHearts(id);
    toast("Не получилось, попробуйте ещё раз");
  }
}

function heartButton(id, extraClass) {
  const on = state.favIds.has(id);
  return h("button", {
    class: `fav ${extraClass || ""} ${on ? "on" : ""}`, "data-fav": id, "aria-label": "В избранное",
    html: on ? ICONS.heartOn : ICONS.heart,
    onclick: (e) => { e.stopPropagation(); toggleFav(id); },
  });
}

function syncHearts(id) {
  const on = state.favIds.has(id);
  document.querySelectorAll(`[data-fav="${id}"]`).forEach((b) => {
    b.classList.toggle("on", on);
    b.innerHTML = on ? ICONS.heartOn : ICONS.heart;
  });
}

// ---------- карточка в ленте ----------

function card(it) {
  const thumb = h("div", { class: "thumb", style: it.photo ? { backgroundImage: `url("${it.photo}")` } : null },
    it.photo ? null : icon("car"),
    it.damaged ? h("span", { class: "warn", title: "Возможно, повреждён" }, "⚠") : null);
  const meta = [kmText(it), regionShort(it.region)].filter(Boolean).join(" · ");
  const deadline = it.is_open
    ? h("div", { class: "deadline" + (isSoon(it.deadline) ? " soon" : "") },
        `Заявки до ${dShort(it.deadline)} · ${timeLeft(it.deadline, true)}`,
        it.trade === "public_offer" ? h("span", { class: "tag" }, "ПП") : null)
    : h("div", { class: "deadline" }, "Приём заявок завершён");
  return h("div", { class: "card" + (it.is_open ? "" : " closed"), role: "button", onclick: () => push({ kind: "lot", id: it.id }) },
    thumb,
    h("div", { class: "info" },
      h("div", { class: "name" }, it.name, it.year ? h("span", { class: "yr" }, `, ${it.year}`) : null),
      h("div", { class: "priceline" }, h("span", { class: "price" }, rub(it.price)), gapBadge(it.gap),
        it.gap_uncertain ? h("span", { class: "unsure", title: "Оценка может быть неточной" }, "неточно") : null),
      meta ? h("div", { class: "meta" }, meta) : null,
      deadline),
    heartButton(it.id));
}

// ---------- лента ----------

const root = h("div", { id: "root" });
const overlay = h("div", { id: "overlay" });
const feed = {};

function buildFeed() {
  feed.input = h("input", { type: "search", placeholder: "Марка, модель или VIN", enterkeyhint: "search", value: state.q });
  let t;
  feed.input.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = feed.input.value.trim(); loadFeed(true); }, 350);
  });
  feed.input.addEventListener("keydown", (e) => { if (e.key === "Enter") feed.input.blur(); });
  feed.badge = h("span", { class: "badge hidden" });
  feed.sorts = h("div", { class: "sortrow" });
  feed.total = h("div", { class: "total" });
  feed.list = h("div", { class: "list" });
  feed.more = h("button", { class: "more hidden", onclick: () => loadFeed(false) }, "Показать ещё");
  feed.el = h("div", { class: "screen" },
    h("div", { class: "topbar" },
      h("div", { class: "brandline" }, h("img", { src: "logo.svg", alt: "" }), h("div", { class: "word" }, "honest", h("span", {}, "lot"))),
      h("div", { class: "searchrow" },
        h("label", { class: "search" }, icon("search"), feed.input),
        h("button", { class: "iconbtn", "aria-label": "Фильтры", onclick: () => push({ kind: "filters" }) }, icon("filter"), feed.badge)),
      feed.sorts),
    feed.total, feed.list, feed.more);
  renderSorts();
  renderBadge();
  return feed.el;
}

function renderSorts() {
  feed.sorts.replaceChildren(...SORTS.map(([key, label]) =>
    h("button", {
      class: "chip" + (state.sort === key ? " on" : ""),
      onclick: () => { state.sort = key; store.set("sort", key); renderSorts(); loadFeed(true); },
    }, label)));
}

function renderBadge() {
  const n = activeFilterCount(state.filters);
  feed.badge.textContent = n;
  feed.badge.classList.toggle("hidden", !n);
}

async function loadFeed(reset) {
  const id = ++state.reqId;
  const offset = reset ? 0 : state.items.length;
  if (reset) { feed.list.replaceChildren(h("div", { class: "loader" }, "Загружаем лоты…")); feed.more.classList.add("hidden"); }
  else { feed.more.disabled = true; feed.more.textContent = "Загружаем…"; }
  try {
    const data = await api(`/lots?${queryString(state.filters, state.q, state.sort)}&offset=${offset}&limit=${PAGE}`);
    if (id !== state.reqId) return; // пришёл ответ на устаревший запрос
    state.items = reset ? data.items : state.items.concat(data.items);
    state.total = data.total;
    if (reset) { feed.list.replaceChildren(); window.scrollTo(0, 0); }
    feed.list.append(...data.items.map(card));
    feed.total.textContent = `${nf.format(data.total)} ${plural(data.total, "лот", "лота", "лотов")}`;
    if (!state.items.length) {
      feed.list.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Ничего не нашлось"),
        activeFilterCount(state.filters) || state.q ? "Попробуйте ослабить фильтры или изменить запрос." : "Лотов пока нет."));
    }
  } catch (e) {
    if (id !== state.reqId) return;
    if (e instanceof AuthError) return showStub();
    if (reset) feed.list.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить"), "Проверьте интернет и попробуйте ещё раз."));
    else toast("Не удалось загрузить");
  } finally {
    if (id === state.reqId) {
      feed.more.disabled = false;
      feed.more.textContent = "Показать ещё";
      feed.more.classList.toggle("hidden", state.items.length >= state.total);
    }
  }
}

// ---------- избранное (вкладка) ----------

const favsEl = h("div", { class: "screen" });

async function renderFavs() {
  favsEl.replaceChildren(
    h("div", { class: "topbar" }, h("div", { class: "brandline" }, h("div", { class: "word" }, "Избранное"))),
    h("div", { class: "loader" }, "Загружаем…"));
  try {
    const { items } = await api("/favorites");
    state.favIds = new Set(items.map((i) => i.id));
    const list = h("div", { class: "list" }, items.map(card));
    favsEl.replaceChildren(favsEl.firstChild, items.length ? list :
      h("div", { class: "empty" }, h("b", {}, "Здесь пока пусто"), "Нажмите ♡ на карточке лота, чтобы сохранить его сюда."));
  } catch (e) {
    if (e instanceof AuthError) return showStub();
    favsEl.replaceChildren(favsEl.firstChild, h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить")));
  }
}

// ---------- вкладки и навигация ----------

const tabsEl = h("nav", { class: "tabs" });
function renderTabs() {
  const tab = (key, label, ic) => h("button", {
    class: state.tab === key ? "on" : "",
    onclick: () => {
      if (state.tab === key) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
      state.tab = key; renderTabs(); showTab();
    },
  }, icon(ic), label);
  tabsEl.replaceChildren(tab("feed", "Лоты", "list"), tab("favs", "Избранное", "heart"));
}
function showTab() {
  feed.el.classList.toggle("hidden", state.tab !== "feed");
  favsEl.classList.toggle("hidden", state.tab !== "favs");
  if (state.tab === "favs") renderFavs();
  window.scrollTo(0, 0);
}

function push(screen) {
  state.scrolls.push(window.scrollY);
  state.stack.push(screen);
  renderTop();
  window.scrollTo(0, 0);
}
function pop() {
  state.stack.pop();
  renderTop();
  const y = state.scrolls.pop() || 0;
  requestAnimationFrame(() => window.scrollTo(0, y));
}
function renderTop() {
  const top = state.stack[state.stack.length - 1];
  root.classList.toggle("hidden", !!top);
  overlay.replaceChildren();
  if (IN_TG) top ? tg.BackButton.show() : tg.BackButton.hide();
  if (!top) return;
  if (top.kind === "lot") renderLot(top.id);
  if (top.kind === "filters") renderFilters(null);
}
if (IN_TG) tg.BackButton.onClick(() => pop());

function backbar(right) {
  return h("div", { class: "backbar" },
    IN_TG ? h("span") : h("button", { class: "left", onclick: pop }, icon("back"), "Назад"),
    right || h("span"));
}

// ---------- экран лота ----------

function gallery(photos) {
  if (!photos.length) return h("div", { class: "nophoto" }, icon("car"));
  const counter = h("div", { class: "counter" }, `1 / ${photos.length}`);
  const slides = h("div", { class: "slides" },
    photos.map((p, i) => h("img", { src: p.full, alt: "", loading: i ? "lazy" : "eager" })));
  slides.addEventListener("scroll", () => {
    const i = Math.round(slides.scrollLeft / slides.clientWidth);
    counter.textContent = `${i + 1} / ${photos.length}`;
  }, { passive: true });
  return h("div", { class: "gallery" }, slides, photos.length > 1 ? counter : null);
}

function rows(pairs) {
  return h("div", { class: "rows" }, pairs.filter((p) => p && p[1] != null && p[1] !== "")
    .map(([k, v]) => h("div", { class: "row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, v))));
}

function marketBlock(lot) {
  if (lot.market_low == null || lot.market_high == null) {
    return h("div", { class: "block" }, h("h3", {}, "Рынок"), h("div", { class: "sub" }, "Оценки Авто.ру для этого лота пока нет."));
  }
  const lo = Math.min(lot.market_low, lot.price) * 0.9;
  const hi = Math.max(lot.market_high, lot.price) * 1.1;
  const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const mid = (lot.market_low + lot.market_high) / 2;
  let verdict = "Цена на уровне рынка";
  if (lot.gap >= 0.5) verdict = `Лот дешевле середины рынка на ${Math.round(lot.gap)}%`;
  else if (lot.gap <= -0.5) verdict = `Лот дороже середины рынка на ${Math.round(-lot.gap)}%`;
  return h("div", { class: "block" },
    h("h3", {}, "Рыночная цена · Авто.ру"),
    h("div", {}, `${rub(lot.market_low)} — ${rub(lot.market_high)}`),
    h("div", { class: "range" },
      h("div", { class: "band", style: { left: pos(lot.market_low), width: `calc(${pos(lot.market_high)} - ${pos(lot.market_low)})` } }),
      h("div", { class: "mark", style: { left: pos(lot.price) }, title: "Цена лота" })),
    h("div", { class: "range-labels" }, h("span", {}, "▮ цена лота"), h("span", {}, `середина ${short(Math.round(mid))} ₽`)),
    h("div", { class: "sub", style: { marginTop: "8px" } }, verdict),
    lot.gap_uncertain ? h("div", { class: "sub unsure-note" },
      "Оценка может быть неточной: Авто.ру сам указывает большую погрешность для этой машины.") : null,
    lot.mileage_estimated ? h("div", { class: "sub" }, "Оценка сделана по примерному пробегу.") : null);
}

async function renderLot(id) {
  overlay.replaceChildren(h("div", { class: "screen no-tabs" }, backbar(), h("div", { class: "loader" }, "Загружаем лот…")));
  let lot;
  try { lot = await api(`/lots/${encodeURIComponent(id)}`); } catch (e) {
    if (e instanceof AuthError) return showStub();
    overlay.replaceChildren(h("div", { class: "screen no-tabs" }, backbar(), h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить лот"))));
    return;
  }
  const top = state.stack[state.stack.length - 1];
  if (!top || top.kind !== "lot" || top.id !== id) return; // пользователь уже ушёл с экрана

  const deadlineBlock = h("div", { class: "block" },
    h("h3", {}, lot.trade === "public_offer" ? "Приём заявок на текущем этапе" : "Приём заявок"),
    lot.is_open
      ? [h("div", { class: "dl" }, `до ${dLong(lot.deadline)} МСК`), h("div", { class: "dl-note" }, `осталось ${timeLeft(lot.deadline)}`)]
      : h("div", { class: "dl" }, "Приём заявок завершён"),
    lot.bidding_start && lot.trade !== "public_offer" ? h("div", { class: "dl-note" }, `Торги: ${dLong(lot.bidding_start)} МСК`) : null);

  // график без единой известной цены (сайт отдаёт нули) не показываем - одни прочерки
  const periods = lot.periods.some((p) => p.price) ? h("div", { class: "block periods" },
    h("h3", {}, "График снижения цены"),
    h("div", { class: "rows" }, lot.periods.map((p) =>
      h("div", { class: "row" + (p.is_current ? " cur" : "") + (p.is_past ? " past" : "") },
        h("span", { class: "k" }, `${p.begin ? dShort(p.begin) + " – " : "до "}${dShort(p.bid_end)}`, p.is_current ? " · сейчас" : ""),
        h("span", { class: "v" }, rub(p.price)))))) : null;

  const vin = lot.vin ? h("button", { class: "copy", onclick: () => {
    navigator.clipboard && navigator.clipboard.writeText(lot.vin).then(() => toast("VIN скопирован"), () => {});
  } }, lot.vin) : null;
  const mileage = lot.mileage_km == null ? null :
    (lot.mileage_estimated ? `~${nf.format(lot.mileage_km)} км (оценка по году)` : `${nf.format(lot.mileage_km)} км`);

  let descOpen = false;
  const desc = lot.description ? h("div", { class: "desc clamp" }, lot.description) : null;
  const descToggle = lot.description && lot.description.length > 300 ? h("button", { class: "linkbtn", onclick: (e) => {
    descOpen = !descOpen; desc.classList.toggle("clamp", !descOpen);
    e.currentTarget.textContent = descOpen ? "Свернуть" : "Показать полностью";
  } }, "Показать полностью") : null;

  overlay.replaceChildren(h("div", { class: "screen no-tabs" },
    backbar(heartButton(lot.id)),
    gallery(lot.photos),
    h("div", { class: "block" },
      h("h2", {}, lot.name, lot.year ? `, ${lot.year}` : ""),
      h("div", { class: "sub" }, [mileage, regionShort(lot.region)].filter(Boolean).join(" · ")),
      h("div", { class: "bigprice" }, rub(lot.price), gapBadge(lot.gap)),
      lot.next_price && lot.is_open ? h("div", { class: "nextstep" },
        `С ${dShort(lot.next_price_from)} цена снизится до ${rub(lot.next_price)}`) : null),
    deadlineBlock,
    lot.damage.length ? h("div", { class: "block warnbox" },
      `⚠ В описании лота упоминаются повреждения: ${lot.damage.map((d) => d.toLowerCase()).join(", ")}. Процент к рынку для такого лота может вводить в заблуждение.`) : null,
    marketBlock(lot),
    periods,
    h("div", { class: "block" }, h("h3", {}, "Характеристики"), rows([
      ["Год", lot.year],
      ["Пробег", mileage],
      ["VIN", vin],
      ["Госномер", lot.plate],
      ["Владельцев", lot.owners],
      ["Регион", lot.region],
      ["Форма торгов", lot.trade_form || (lot.trade === "public_offer" ? "Публичное предложение" : "Аукцион")],
      ["Площадка", lot.platform],
      ["Начальная цена", lot.price_start != null && lot.price_start !== lot.price ? rub(lot.price_start) : null],
      ["Статус", lot.status],
    ])),
    desc ? h("div", { class: "block" }, h("h3", {}, "Описание"), desc, descToggle) : null,
    h("div", { class: "bottombar" },
      h("button", { class: "btn", onclick: () => { track("source_click", lot.id); openLink(lot.url); } }, "Открыть лот на сайте торгов"))));
}

// ---------- фильтры ----------

const PRICE_STEPS = [0, 100e3, 200e3, 300e3, 400e3, 500e3, 600e3, 700e3, 800e3, 900e3, 1e6, 1.2e6, 1.5e6, 2e6, 2.5e6, 3e6, 4e6, 5e6, 7e6, 10e6, 15e6, 20e6, null];
const MILEAGE_STEPS = [20e3, 40e3, 60e3, 80e3, 100e3, 120e3, 150e3, 200e3, 250e3, 300e3, null];
const GAP_OPTIONS = [[null, "Любой"], [0.5, "Ниже рынка"], [10, "от 10%"], [20, "от 20%"], [30, "от 30%"]];
const TRADES = [["auction", "Аукцион"], ["public_offer", "Публичное предложение"]];

// Двухползунковый слайдер по массиву шагов. single=true - только правый ползунок ("до").
function dualSlider(steps, [iFrom, iTo], onInput, single) {
  const max = steps.length - 1;
  const a = h("input", { type: "range", min: 0, max, step: 1, value: iFrom });
  const b = h("input", { type: "range", min: 0, max, step: 1, value: iTo });
  const fill = h("div", { class: "fill" });
  const paint = () => {
    const x = +a.value, y = +b.value;
    fill.style.left = `${(x / max) * 100}%`;
    fill.style.width = `${((y - x) / max) * 100}%`;
  };
  a.addEventListener("input", () => { if (+a.value > +b.value) a.value = b.value; paint(); onInput(+a.value, +b.value); });
  b.addEventListener("input", () => { if (+b.value < +a.value) b.value = a.value; paint(); onInput(+a.value, +b.value); });
  paint();
  return h("div", { class: "dual" }, h("div", { class: "track" }), fill, single ? null : a, b);
}

// initial - с чего начать черновик (по умолчанию - текущие фильтры ленты).
// Черновик применяется к ленте только по кнопке "Показать".
function renderFilters(initial) {
  const facets = state.facets || { brands: [], regions: [], year: null };
  const draft = JSON.parse(JSON.stringify(initial || state.filters));
  const expanded = new Set(draft.brands);
  // Выбранные марки - сверху, но порядок фиксируем при открытии экрана:
  // если пересортировывать на каждый клик, отмеченная марка "уезжает" из-под пальца.
  const brandOrder = facets.brands.slice().sort((x, y) => draft.brands.includes(y.key) - draft.brands.includes(x.key));
  const showBtn = h("button", { class: "btn" }, "Показать");
  let countReq = 0, countTimer;

  function refreshCount() {
    clearTimeout(countTimer);
    showBtn.disabled = true;
    countTimer = setTimeout(async () => {
      const id = ++countReq;
      try {
        const { total } = await api(`/lots?${queryString(draft, state.q, null)}&limit=0`);
        if (id !== countReq) return;
        showBtn.textContent = total ? `Показать ${nf.format(total)} ${plural(total, "лот", "лота", "лотов")}` : "Ничего не найдено";
        showBtn.disabled = !total;
      } catch { showBtn.textContent = "Показать"; showBtn.disabled = false; }
    }, 250);
  }

  function section(title, valueText, body) {
    const val = h("span", { class: "val" }, valueText || "");
    return { el: h("div", { class: "fsec" }, h("h3", {}, title, val), body), val };
  }

  // --- марка / модель ---
  const brandSearch = h("input", { class: "brandsearch", type: "search", placeholder: "Найти марку" });
  const brandList = h("div", { class: "brandlist" });
  const brandVal = h("span", { class: "val" });
  function brandSummary() {
    const n = draft.brands.length;
    brandVal.textContent = n ? `выбрано: ${n}` : "любая";
  }
  function toggleBrand(key) {
    if (draft.brands.includes(key)) { draft.brands = draft.brands.filter((b) => b !== key); delete draft.models[key]; }
    else { draft.brands.push(key); expanded.add(key); }
    drawBrands(); refreshCount();
  }
  function toggleModel(bkey, mkey) {
    const ms = new Set(draft.models[bkey] || []);
    ms.has(mkey) ? ms.delete(mkey) : ms.add(mkey);
    if (ms.size) { draft.models[bkey] = [...ms]; if (!draft.brands.includes(bkey)) draft.brands.push(bkey); }
    else { delete draft.models[bkey]; draft.brands = draft.brands.filter((b) => b !== bkey); }
    drawBrands(); refreshCount();
  }
  function drawBrands() {
    const q = brandSearch.value.trim().toUpperCase();
    const list = brandOrder.filter((b) => !q || b.label.toUpperCase().includes(q) || b.models.some((m) => m.label.toUpperCase().includes(q)));
    brandList.replaceChildren(...list.map((b) => {
      const sel = draft.brands.includes(b.key);
      const models = draft.models[b.key] || [];
      const open = expanded.has(b.key) && b.models.length > 1;
      return h("div", { class: "brand" },
        h("div", { class: "brandrow" },
          h("button", { class: "check" + (sel && !models.length ? " on" : "") + (models.length ? " part" : ""), onclick: () => toggleBrand(b.key), "aria-label": b.label },
            sel && !models.length ? "✓" : ""),
          h("button", { class: "lbl", style: { textAlign: "left" }, onclick: () => toggleBrand(b.key) }, b.label),
          h("span", { class: "cnt" }, b.count),
          b.models.length > 1 ? h("button", { class: "exp", onclick: () => { expanded.has(b.key) ? expanded.delete(b.key) : expanded.add(b.key); drawBrands(); } }, open ? "▴" : "▾") : null),
        open ? h("div", { class: "models chips" }, b.models.map((m) =>
          h("button", { class: "chip" + (models.includes(m.key) ? " on" : ""), onclick: () => toggleModel(b.key, m.key) },
            m.label, h("span", { class: "cnt" }, m.count)))) : null);
    }));
    brandSummary();
  }
  brandSearch.addEventListener("input", drawBrands);

  // --- год ---
  const years = [];
  if (facets.year) for (let y = facets.year[0]; y <= facets.year[1]; y++) years.push(y);
  const yearIdx = (v, dflt) => { const i = years.indexOf(v); return i >= 0 ? i : dflt; };
  const yearText = () => !draft.year ? "любой" : `${draft.year[0] ?? years[0]} — ${draft.year[1] ?? years[years.length - 1]}`;
  const yearSec = section("Год выпуска", yearText(), years.length > 1 ? dualSlider(years,
    [yearIdx(draft.year && draft.year[0], 0), yearIdx(draft.year && draft.year[1], years.length - 1)],
    (i, j) => {
      const from = i === 0 ? null : years[i], to = j === years.length - 1 ? null : years[j];
      draft.year = from == null && to == null ? null : [from, to];
      yearSec.val.textContent = yearText(); refreshCount();
    }) : h("div", { class: "sub" }, "—"));

  // --- цена ---
  const pIdx = (v, dflt) => { const i = v == null ? -1 : PRICE_STEPS.indexOf(v); return i >= 0 ? i : dflt; };
  const priceText = () => {
    if (!draft.price) return "любая";
    const [a, b] = draft.price;
    if (a != null && b != null) return `${short(a)} — ${short(b)} ₽`;
    return a != null ? `от ${short(a)} ₽` : `до ${short(b)} ₽`;
  };
  const priceSec = section("Цена", priceText(), dualSlider(PRICE_STEPS,
    [pIdx(draft.price && draft.price[0], 0), pIdx(draft.price && draft.price[1], PRICE_STEPS.length - 1)],
    (i, j) => {
      const from = i === 0 ? null : PRICE_STEPS[i], to = PRICE_STEPS[j];
      draft.price = from == null && to == null ? null : [from, to];
      priceSec.val.textContent = priceText(); refreshCount();
    }));

  // --- пробег ---
  const mText = () => draft.mileageTo == null ? "любой" : `до ${nf.format(draft.mileageTo)} км`;
  const mIdx = MILEAGE_STEPS.indexOf(draft.mileageTo);
  const mileageSec = section("Пробег", mText(), dualSlider(MILEAGE_STEPS, [0, mIdx >= 0 ? mIdx : MILEAGE_STEPS.length - 1],
    (_, j) => { draft.mileageTo = MILEAGE_STEPS[j]; mileageSec.val.textContent = mText(); refreshCount(); }, true));

  // --- чипы: % к рынку, регион, форма торгов ---
  function chipGroup(options, isOn, onToggle) {
    const box = h("div", { class: "chips" });
    const draw = () => box.replaceChildren(...options.map(([v, label, cnt]) =>
      h("button", { class: "chip" + (isOn(v) ? " on" : ""), onclick: () => { onToggle(v); draw(); refreshCount(); } },
        label, cnt != null ? h("span", { class: "cnt" }, cnt) : null)));
    draw();
    return box;
  }
  const toggleIn = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : arr.concat(v));
  const gapChips = chipGroup(GAP_OPTIONS, (v) => draft.gapMin === v, (v) => { draft.gapMin = v; });
  const regionChips = chipGroup(facets.regions.map((r) => [r.key, regionShort(r.key) === "МО" ? "Московская обл." : regionShort(r.key), r.count]),
    (v) => draft.regions.includes(v), (v) => { draft.regions = toggleIn(draft.regions, v); });
  const tradeChips = chipGroup(TRADES, (v) => draft.trade.includes(v), (v) => { draft.trade = toggleIn(draft.trade, v); });

  const reset = h("button", { class: "btn secondary", onclick: () => renderFilters(emptyFilters()) }, "Сбросить");
  showBtn.addEventListener("click", () => {
    state.filters = draft;
    store.set("filters", draft);
    renderBadge();
    pop();
    loadFeed(true);
  });

  drawBrands();
  overlay.replaceChildren(h("div", { class: "screen no-tabs" },
    backbar(),
    h("div", { class: "fsec" }, h("h3", {}, "Марка и модель", brandVal), brandSearch, brandList),
    yearSec.el, priceSec.el, mileageSec.el,
    h("div", { class: "fsec" }, h("h3", {}, "Ниже рынка"), gapChips),
    h("div", { class: "fsec" }, h("h3", {}, "Регион"), regionChips),
    h("div", { class: "fsec" }, h("h3", {}, "Форма торгов"), tradeChips),
    h("div", { class: "bottombar" }, reset, showBtn)));
  refreshCount();
}

// ---------- заглушка вне Telegram ----------

function showStub() {
  document.getElementById("app").replaceChildren(h("div", { class: "stub" },
    h("img", { src: "logo.svg", alt: "" }),
    h("h2", {}, "honestlot"),
    h("p", {}, "Выгодные лоты с банкротных торгов. Приложение работает внутри Telegram."),
    h("button", { class: "btn", style: { maxWidth: "280px", margin: "16px auto 0", display: "block" }, onclick: () => { location.href = `https://t.me/${BOT}`; } },
      `Открыть @${BOT}`)));
  if (IN_TG) tg.BackButton.hide();
}

// ---------- старт ----------

async function start() {
  document.getElementById("app").append(root, overlay);
  root.append(buildFeed(), favsEl, tabsEl);
  favsEl.classList.add("hidden");
  renderTabs();
  loadFeed(true);
  track("open");
  try {
    const [facets, favs] = await Promise.all([api("/facets"), api("/favorites")]);
    state.facets = facets;
    state.favIds = new Set(favs.items.map((i) => i.id));
    state.items.forEach((it) => syncHearts(it.id));
  } catch (e) {
    if (e instanceof AuthError) showStub();
  }
}
start();
