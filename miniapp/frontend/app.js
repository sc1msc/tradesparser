// honestlot - мини-апп Telegram. Чистый JavaScript без сборки: браузер
// загружает этот файл как есть. Экраны: лента, избранное, карточка лота,
// фильтры. Все данные - с бэкенда (/api/*), процент к рынку и текущая цена
// считаются там, фронт их только показывает.

const tg = window.Telegram && window.Telegram.WebApp;
const IN_TG = !!(tg && tg.initData);
// Где открыто приложение:
//   IN_TG - мини-апп в Telegram (initData);
//   WEB   - веб-версия: honestlot.ru в обычном браузере (Telegram.WebApp.platform "unknown").
//           Вход через Telegram Login Widget, сервер выдаёт токен на 30 дней (auth.py),
//           без входа лоты не показываем (решение владельца 13.10.2026). Сайт, где принимают
//           оплату, не должен уводить в Telegram - требование ЮKassa;
//   иначе - локальная разработка на localhost (сервер с HONESTLOT_DEV_USER_ID пускает без входа;
//           ?web=1 в адресе включает веб-режим и там).
const OUTSIDE_TG = !(tg && tg.platform && tg.platform !== "unknown");
const LOCAL = ["localhost", "127.0.0.1"].includes(location.hostname);
const WEB = OUTSIDE_TG && (!LOCAL || new URLSearchParams(location.search).has("web"));
const PAGE = 20;
const BOT = "honestlot_bot";
// Аккаунт поддержки в Telegram (без @). Пусто - ссылка "Написать в поддержку" не показывается.
const SUPPORT = "honestlot_support_bot";

// Итог торгов (fav_state / outcome с сервера, см. lots.outcome) - как подписать.
const OUTCOME_TEXT = {
  awaiting: "Приём заявок завершён · ждём итогов",
  done: "Торги завершены",
  failed: "Торги не состоялись · следим за перевыставлением",
  cancelled: "Торги отменены",
  suspended: "Торги приостановлены",
  removed: "Лот удалён с сайта торгов",
};
const OUTCOME_SHORT = { open: "идёт приём заявок", awaiting: "ждём итогов", done: "завершены", failed: "не состоялись", cancelled: "отменены", suspended: "приостановлены", removed: "удалён с сайта" };

if (tg) { tg.ready(); tg.expand(); }
// Метод Telegram есть в этой версии клиента? Только внутри Telegram: в браузере telegram-web-app.js тоже
// загружен (версия 6.0), и вызовы новых методов пишут в консоль «… is not supported in version 6.0».
const tgv = (v) => IN_TG && !!tg.isVersionAtLeast && tg.isVersionAtLeast(v);

// Шапка Telegram («Закрыть», «⋯»), фон окна и системная панель Android - в цвета приложения (22.10.2026).
// По умолчанию Telegram красит шапку и фон в bg_color, а лента и липкая верхняя часть у нас - secondary_bg_color
// (--bg2): между шапкой и лентой была видна граница; панель Android брала bottom_bar_bg_color темы, а наши
// вкладки - bg_color (--bg). Ключевые слова, а не hex: при смене темы Telegram перекрашивает сам, повторять на
// themeChanged не нужно. dark - на время просмотра фото на весь экран (openViewer): шапка и панель чёрные
// (произвольный цвет шапки - с Bot API 6.9, панели - с 7.10). Все значения - здесь.
function tgChrome(dark) {
  try {
    if (tgv("6.1")) {
      if (!dark) { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); }
      else if (tgv("6.9")) tg.setHeaderColor("#000000");
    }
    if (tgv("7.10")) tg.setBottomBarColor(dark ? "#000000" : "bg_color");
  } catch { /* клиент не принял цвет - остаются цвета Telegram */ }
}
tgChrome(false);
document.documentElement.classList.toggle("tg", IN_TG);
document.documentElement.classList.toggle("web", WEB);

function applyScheme() {
  const dark = IN_TG ? tg.colorScheme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
}
applyScheme();
if (IN_TG) tg.onEvent("themeChanged", applyScheme);

// ---------- утилиты ----------

// Надпись «honestlot» в кривых (Unbounded 600) - копия путей из miniapp/assets/render_userpics.py.
// «honest» - цвет текста, «lot» - фирменная мята (--wm-lot).
const WORDMARK = '<svg class="wm" viewBox="60 -770 5757 786" role="img" aria-label="HonestLot"><path d="M60 -770H245V0H60ZM459 -586Q540 -586 597.5 -553.5Q655 -521 685.5 -461Q716 -401 716 -318V0H530V-290Q530 -361 495.5 -397.5Q461 -434 395 -434Q350 -434 316 -414.5Q282 -395 263.5 -359.5Q245 -324 245 -275L186 -306Q198 -397 236 -459Q274 -521 331.5 -553.5Q389 -586 459 -586ZM1135 16Q1027 16 946 -22Q865 -60 820 -128Q775 -196 775 -285Q775 -375 820 -442.5Q865 -510 946.5 -548Q1028 -586 1135 -586Q1243 -586 1324.5 -548Q1406 -510 1451 -442.5Q1496 -375 1496 -285Q1496 -195 1451 -127.5Q1406 -60 1324.5 -22Q1243 16 1135 16ZM1135 -124Q1190 -124 1228.5 -143.5Q1267 -163 1287.5 -199Q1308 -235 1308 -285Q1308 -335 1287.5 -371Q1267 -407 1228.5 -426.5Q1190 -446 1135 -446Q1082 -446 1043 -426.5Q1004 -407 983 -371Q962 -335 962 -285Q962 -235 983 -199Q1004 -163 1043 -143.5Q1082 -124 1135 -124ZM1533 -570H1718L1755 -348V0H1569V-376ZM1968 -586Q2050 -586 2107.5 -553.5Q2165 -521 2195.5 -461Q2226 -401 2226 -318V0H2040V-290Q2040 -361 2005 -397.5Q1970 -434 1905 -434Q1859 -434 1825.5 -414.5Q1792 -395 1773.5 -359.5Q1755 -324 1755 -275L1696 -306Q1707 -397 1745.5 -459Q1784 -521 1841.5 -553.5Q1899 -586 1968 -586ZM2640 16Q2538 16 2457.5 -22Q2377 -60 2331 -128Q2285 -196 2285 -287Q2285 -376 2329 -443Q2373 -510 2450.5 -548Q2528 -586 2626 -586Q2726 -586 2798 -542Q2870 -498 2909 -418Q2948 -338 2948 -230H2434V-347H2846L2779 -305Q2776 -352 2756.5 -384.5Q2737 -417 2705 -434.5Q2673 -452 2629 -452Q2581 -452 2546 -433Q2511 -414 2491.5 -380Q2472 -346 2472 -301Q2472 -244 2497.5 -204Q2523 -164 2571.5 -143Q2620 -122 2690 -122Q2754 -122 2818 -139.5Q2882 -157 2933 -189V-68Q2875 -28 2800.5 -6Q2726 16 2640 16ZM3658 -183Q3658 -119 3620.5 -74.5Q3583 -30 3511 -7Q3439 16 3336 16Q3231 16 3152 -10Q3073 -36 3029 -83Q2985 -130 2982 -192H3171Q3177 -167 3199.5 -148Q3222 -129 3258 -119.5Q3294 -110 3343 -110Q3409 -110 3443 -124Q3477 -138 3477 -166Q3477 -187 3452.5 -198Q3428 -209 3365 -214L3261 -222Q3163 -229 3105 -253Q3047 -277 3022.5 -314Q2998 -351 2998 -397Q2998 -460 3037.5 -502Q3077 -544 3147 -565Q3217 -586 3311 -586Q3405 -586 3478.5 -561Q3552 -536 3596.5 -492Q3641 -448 3647 -389H3458Q3454 -409 3436.5 -426Q3419 -443 3386.5 -453.5Q3354 -464 3302 -464Q3243 -464 3212 -451Q3181 -438 3181 -413Q3181 -394 3200 -383Q3219 -372 3272 -367L3407 -357Q3503 -349 3557.5 -326.5Q3612 -304 3635 -268Q3658 -232 3658 -183ZM3662 -432V-513L3780 -556L3860 -722H3966V-570H4212V-432H3966V-244Q3966 -180 3992 -154.5Q4018 -129 4085 -129Q4128 -129 4160.5 -136.5Q4193 -144 4222 -157V-16Q4192 -4 4143.5 6Q4095 16 4043 16Q3952 16 3893.5 -13Q3835 -42 3807.5 -94.5Q3780 -147 3780 -218V-432Z"/><path class="lot" d="M4283 -770H4468V0H4283ZM4895 16Q4787 16 4706 -22Q4625 -60 4580 -128Q4535 -196 4535 -285Q4535 -375 4580 -442.5Q4625 -510 4706.5 -548Q4788 -586 4895 -586Q5003 -586 5084.5 -548Q5166 -510 5211 -442.5Q5256 -375 5256 -285Q5256 -195 5211 -127.5Q5166 -60 5084.5 -22Q5003 16 4895 16ZM4895 -124Q4950 -124 4988.5 -143.5Q5027 -163 5047.5 -199Q5068 -235 5068 -285Q5068 -335 5047.5 -371Q5027 -407 4988.5 -426.5Q4950 -446 4895 -446Q4842 -446 4803 -426.5Q4764 -407 4743 -371Q4722 -335 4722 -285Q4722 -235 4743 -199Q4764 -163 4803 -143.5Q4842 -124 4895 -124ZM5257 -432V-513L5375 -556L5455 -722H5561V-570H5807V-432H5561V-244Q5561 -180 5587 -154.5Q5613 -129 5680 -129Q5723 -129 5755.5 -136.5Q5788 -144 5817 -157V-16Q5787 -4 5738.5 6Q5690 16 5638 16Q5547 16 5488.5 -13Q5430 -42 5402.5 -94.5Q5375 -147 5375 -218V-432Z"/></svg>';
function wordmark() {
  const s = document.createElement("span");
  s.className = "wmw";
  s.innerHTML = WORDMARK;
  return s;
}

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
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>',
  list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="7" height="7" rx="2"/><rect x="3" y="13" width="7" height="7" rx="2"/><path d="M13 6h8M13 9h5M13 15h8M13 18h5"/></svg>',
  car: '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M5 16H3v-4l2-5h14l2 5v4h-2M7 16h10"/><circle cx="7" cy="16.5" r="1.8"/><circle cx="17" cy="16.5" r="1.8"/></svg>',
  back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
  logout: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>',
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M7.5 7.5 12 3l4.5 4.5"/><path d="M8 11H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-2"/></svg>',
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
// «~» - пробег не из описания лота: расчётный по году выпуска или пересчитанная на сегодня запись из отчёта
const mileageApprox = (it) => it.mileage_estimated || it.mileage_source === "report";
const kmText = (it) => it.mileage_km == null ? null : (mileageApprox(it) ? "~" : "") + nf.format(it.mileage_km) + " км";

// damaged - у лота возможны повреждения: скидка к рынку не «выгода», плашка жёлтая (решение владельца 19.10.2026)
function gapBadge(gap, damaged) {
  if (gap == null) return null;
  const r = Math.round(gap);
  if (gap >= 0.5) return h("span", { class: damaged ? "gap warn" : "gap good" }, `−${r}% к рынку`);
  if (gap > -0.5) return h("span", { class: "gap neutral" }, "≈ рынок");
  return h("span", { class: "gap neutral" }, `+${-r}% к рынку`);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem("hl_" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("hl_" + k, JSON.stringify(v)); } catch { /* приватный режим и т.п. */ } },
};

let toastTimer;
// action - необязательная кнопка в уведомлении: {label, onclick}. С кнопкой
// уведомление висит дольше - чтобы успеть нажать.
function toast(text, action, ms) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = h("div", { class: "toast" + (action ? " with-action" : "") }, h("span", {}, text),
    action ? h("button", { class: "toast-act", onclick: () => { t.remove(); action.onclick(); } }, action.label) : null);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), ms || (action ? 4500 : 2200));
}
// Вибрация (HapticFeedback, Bot API 6.1+; вне Telegram - ничего):
//   haptic       - «толчок»: избранное, «Поделиться», окна (сохранение поиска, Pro), просмотр фото;
//   hapticSelect - лёгкий щелчок выбора: чипы, галочки, переключатели, ползунки (на каждый шаг), смена вкладки;
//   hapticNotify - итог действия: "success" (поиск сохранён/удалён, почта принята), "error" - запрос не прошёл
//                  (там же, где тост «Не получилось…»). На прокрутку, открытие лота, «Показать ещё» - без вибрации.
const haptic = (kind) => { try { if (tgv("6.1")) tg.HapticFeedback.impactOccurred(kind || "light"); } catch { /* старый клиент */ } };
const hapticSelect = () => { try { if (tgv("6.1")) tg.HapticFeedback.selectionChanged(); } catch { /* старый клиент */ } };
const hapticNotify = (type) => { try { if (tgv("6.1")) tg.HapticFeedback.notificationOccurred(type); } catch { /* старый клиент */ } };
function openLink(url) { if (IN_TG) tg.openLink(url); else window.open(url, "_blank", "noopener"); }
// Аналитика: ошибки не показываем пользователю - это не его забота.
function track(type, lotId, place) {
  api("/events", { method: "POST", keepalive: true, body: JSON.stringify({ type, lot_id: lotId || null, place: place || null }) })
    .catch(() => {});
}

// ---------- API ----------

class AuthError extends Error {}
const webToken = () => (WEB ? store.get("web_token", null) : null);
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {
    ...opts,
    headers: {
      Authorization: IN_TG ? "tma " + tg.initData : webToken() ? "web " + webToken() : "tma ",
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (r.status === 401) throw new AuthError(await r.text());
  if (!r.ok) {
    let detail = null;  // текст ошибки от сервера («можно сохранить до 10 поисков…») - для показа
    try { detail = (await r.json()).detail; } catch { /* не JSON */ }
    throw Object.assign(new Error(`Ошибка ${r.status}`), { status: r.status, detail: typeof detail === "string" ? detail : null });
  }
  return r.json();
}

// ---------- состояние ----------

// hideDamaged - "Скрыть битые" (тотальные повреждения), по умолчанию включена и в счётчик фильтров не входит
// price: [300000, null] - по умолчанию "от 300 тыс.": ниже - в основном хлам и мусорные лоты (12.10.2026)
// fuel/gearbox/drive - характеристики с Авто.ру (значения как в lots.FUELS/GEARBOXES/DRIVES),
// volume - [от, до] в литрах, power - [от, до] в л.с.; null в паре - без границы
const emptyFilters = () => ({ brands: [], models: {}, year: null, price: [300e3, null], mileageTo: null, gapMin: null, ownersTo: null, dtpTo: null, regions: [], trade: [], kinds: [],
  fuel: [], gearbox: [], drive: [], body: [], volume: null, power: null, hideDamaged: true });
// «Сначала новые» - по умолчанию с 20.10.2026 (решение владельца): внутри дня - выгоднее сверху.
// Выбранная пользователем сортировка хранится на устройстве и не меняется.
const SORTS = [["new", "Новые"], ["gap", "Выгоднее"], ["deadline", "Скоро дедлайн"], ["price_asc", "Дешевле"], ["price_desc", "Дороже"]];

const state = {
  tab: "feed",
  filters: { ...emptyFilters(), ...store.get("filters", {}) },
  sort: store.get("sort", "new"),
  q: "",
  items: [],
  total: 0,
  facets: null,
  favIds: new Set(),
  searchesOn: false,    // сохранённые поиски включены (/api/me searches)
  searches: null,       // сохранённые поиски (GET /api/searches)
  searchLimit: 10,
  notifySettings: null, // каналы уведомлений
  activeSearch: null,   // открытый из «Поисков» поиск: окно сохранения предложит его обновить
  newIds: new Set(),    // лоты открытого поиска, пришедшие после прошлого открытия - метка «новый»
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
  if (filters.ownersTo != null) p.set("owners_to", filters.ownersTo);
  if (filters.dtpTo != null) p.set("dtp_to", filters.dtpTo);
  if (filters.regions.length) p.set("regions", filters.regions.join(","));
  if (filters.trade.length) p.set("trade", filters.trade.join(","));
  if ((filters.kinds || []).length) p.set("kinds", filters.kinds.join(","));
  for (const k of ["fuel", "gearbox", "drive", "body"]) if ((filters[k] || []).length) p.set(k, filters[k].join(","));
  if (filters.volume) { if (filters.volume[0] != null) p.set("vol_from", filters.volume[0]); if (filters.volume[1] != null) p.set("vol_to", filters.volume[1]); }
  if (filters.power) { if (filters.power[0] != null) p.set("power_from", filters.power[0]); if (filters.power[1] != null) p.set("power_to", filters.power[1]); }
  if (filters.hideDamaged !== false) p.set("hide_damaged", "1");
  return p.toString();
}

function activeFilterCount(f) {
  return [f.brands.length, f.year, f.price, f.mileageTo != null, f.gapMin != null, f.ownersTo != null, f.dtpTo != null, f.regions.length, f.trade.length, (f.kinds || []).length,
    (f.fuel || []).length, (f.gearbox || []).length, (f.drive || []).length, (f.body || []).length, f.volume, f.power]
    .filter(Boolean).length;
}

// ---------- избранное ----------

// item - данные лота (карточки или экрана лота): для "Поделиться" в уведомлении.
async function toggleFav(id, item) {
  const on = !state.favIds.has(id);
  on ? state.favIds.add(id) : state.favIds.delete(id);
  syncHearts(id);
  haptic();
  try {
    await api(`/favorites/${id}`, { method: on ? "PUT" : "DELETE" });
    // лот только что отметили как интересный - лучший момент предложить переслать его
    if (on && item) toast("Добавлено в избранное", { label: "Поделиться ›", onclick: () => shareLot(item, "toast") });
    else toast(on ? "Добавлено в избранное" : "Убрано из избранного");
  } catch (e) {
    on ? state.favIds.delete(id) : state.favIds.add(id);
    syncHearts(id);
    hapticNotify("error");
    toast("Не получилось, попробуйте ещё раз");
  }
}

function heartButton(id, item) {
  const on = state.favIds.has(id);
  return h("button", {
    class: `fav ${on ? "on" : ""}`, "data-fav": id, "aria-label": "В избранное",
    html: on ? ICONS.heartOn : ICONS.heart,
    onclick: (e) => { e.stopPropagation(); if (!locked("favs")) toggleFav(id, item); },
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

function priceChange(price, prev) {
  if (!price || !prev || price === prev) return "";
  const pct = Math.round(((price - prev) / prev) * 100);
  return pct < 0 ? ` · дешевле на ${-pct}%` : ` · дороже на ${pct}%`;
}

// Превью в ленте с запасными вариантами (с 16.10.2026): фото площадки, не открылось (площадка
// закрыла доступ, у пользователя VPN) - следующее (photo_alts, обычно фото агрегатора), не открылось
// ничего - «Нет фото», а не пустой квадрат.
function thumbBox(it) {
  const urls = [it.photo, ...(it.photo_alts || [])].filter(Boolean);
  const el = h("div", { class: "thumb" },
    it.damaged ? h("span", { class: "warn", title: "Возможно, повреждён" }, "⚠") : null);
  const noPhoto = () => {
    el.classList.add("nophoto");
    el.style.backgroundImage = "";
    el.prepend(icon("car"), h("span", { class: "nophoto-t" }, "Нет фото"));
  };
  const tryUrl = (i) => {
    if (i >= urls.length) return noPhoto();
    const probe = new Image();
    probe.onload = () => { el.style.backgroundImage = `url("${urls[i]}")`; };
    probe.onerror = () => tryUrl(i + 1);
    probe.src = urls[i];
  };
  tryUrl(0);
  return el;
}

function card(it) {
  if (it.favorite) state.favIds.add(it.id); // избранное следует за машиной - сервер знает лучше
  const thumb = thumbBox(it);
  // «новый»: лот открытого поиска, пришедший после прошлого открытия, или появившийся в ленте за сутки
  if (state.newIds.has(it.id) || it.is_new) thumb.append(h("span", { class: "newb" }, "новый"));
  const meta = [kmText(it), regionShort(it.region), it.dtp_count ? `ДТП: ${it.dtp_count}` : null].filter(Boolean).join(" · ");
  const specLine = specsShort(it);
  const closedText = (it.fav_state && it.fav_state !== "open" && OUTCOME_TEXT[it.fav_state]) || "Приём заявок завершён";
  const deadline = it.is_open
    ? h("div", { class: "deadline" + (isSoon(it.deadline) ? " soon" : "") },
        `Заявки до ${dShort(it.deadline)} · ${timeLeft(it.deadline, true)}`,
        it.trade === "public_offer" ? h("span", { class: "tag" }, "ПП") : null,
        it.kind === "multilot" ? h("span", { class: "tag" }, "Мультилот") : null,
        it.listings > 1 ? h("span", { class: "tag" }, `+${it.listings - 1} площ.`) : null)
    : h("div", { class: "deadline" }, closedText);
  const relisted = it.relisted ? h("div", { class: "relisted" }, "Перевыставлен" + priceChange(it.price, it.prev_price)) : null;
  // Карточка - блок со «растянутой» ссылкой на лот (22.10.2026): с клавиатуры (Tab, Enter), Ctrl/Cmd/средней
  // кнопкой - в новой вкладке (адрес /?lot=ID); обычный клик открывает лот внутри приложения. ♡ - поверх ссылки.
  const link = h("a", { class: "card-link", href: lotHref(it.id), "aria-label": `${it.name}${it.year ? ", " + it.year : ""}, ${rub(it.price)}`,
    onclick: (e) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // новая вкладка - сам браузер
      e.preventDefault();
      push({ kind: "lot", id: it.id });
    } });
  return h("div", { class: "card" + (it.is_open ? "" : " closed") },
    link,
    thumb,
    h("div", { class: "info" },
      h("div", { class: "name" }, it.name, it.year ? h("span", { class: "yr" }, `, ${it.year}`) : null),
      // у аукциона в ленте - начальная цена (итоговая определится на торгах): подписываем
      h("div", { class: "priceline" }, h("span", { class: "price" }, it.trade === "auction" ? h("span", { class: "pfx" }, "старт ") : null, rub(it.price)), gapBadge(it.gap, it.damaged),
        it.gap_uncertain ? h("span", { class: "unsure", title: "Оценка может быть неточной" }, "неточно") : null),
      specLine ? h("div", { class: "specs" }, specLine) : null,
      meta ? h("div", { class: "meta" }, meta) : null,
      relisted,
      deadline),
    heartButton(it.id, it));
}

function supportLink() {
  if (!SUPPORT) return null;
  return h("button", { class: "support", onclick: () => {
    const url = `https://t.me/${SUPPORT}`;
    if (IN_TG) tg.openTelegramLink(url); else window.open(url, "_blank", "noopener");
  } }, "Написать в поддержку");
}

// ---------- поделиться лотом ----------

// Ссылка t.me/<бот>?startapp=lot<id>_<код> открывает мини-апп сразу на этом
// лоте (см. start()). Код - не telegram_id, а случайный код поделившегося
// (GET /api/me): так видно, кого кто привёл, а получатель ничего о нём не узнаёт.
// Код берём заранее, при открытии экрана лота, - клик "Поделиться" не ждёт сети.
// GET /api/me - один раз: код для ссылок "Поделиться" и (когда оплата включена) признак Pro.
let mePromise = null;
function loadMe() {
  if (mePromise === null) mePromise = api("/me").catch(() => { mePromise = null; return {}; });
  return mePromise;
}
const loadRef = () => loadMe().then((d) => d.ref || null);
const shareParam = (lotId, ref) => `lot${lotId}${ref ? "_" + ref : ""}`;

// place - откуда нажали (top / bottom / toast): видно, какая кнопка работает.
async function shareLot(lot, place) {
  haptic();
  track("share", lot.id, place);
  const ref = await Promise.race([loadRef(), new Promise((r) => setTimeout(() => r(null), 1500))]);
  // из Telegram - ссылка на лот в мини-аппе, из браузера - на лот в веб-версии (тот же параметр
  // startapp: startLotId откроет лот после входа, а сервер засчитает приглашение)
  const param = shareParam(lot.id, ref);
  const link = IN_TG ? `https://t.me/${BOT}?startapp=${param}` : `${location.origin}/?startapp=${param}`;
  const gap = lot.gap != null && lot.gap >= 0.5 ? `, на ${Math.round(lot.gap)}% ниже рынка` : "";
  const text = `${lot.name}${lot.year ? ", " + lot.year : ""} — ${rub(lot.price)}${gap}`;
  if (IN_TG) {
    // стандартный выбор чата Telegram; серверу Telegram для этого не нужен
    tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`);
  } else if (navigator.share) {
    navigator.share({ text, url: link }).catch(() => {});
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(`${text}\n${link}`).then(() => toast("Ссылка скопирована"), () => {});
  }
}

// Параметр запуска: в Telegram - start_param из initData, в браузере (веб-версия и локальная
// проверка) - ?startapp=... в адресе страницы (ссылка «Поделиться» из веб-версии).
function startLotId() {
  const p = (IN_TG && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || new URLSearchParams(location.search).get("startapp") || "";
  const m = /^lot(\d+)/.exec(p);
  return m ? m[1] : null;
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
    t = setTimeout(() => { state.q = feed.input.value.trim(); renderActive(); loadFeed(true); }, 350);
  });
  feed.input.addEventListener("keydown", (e) => { if (e.key === "Enter") feed.input.blur(); });
  feed.badge = h("span", { class: "badge hidden" });
  feed.sorts = h("div", { class: "sortrow" });
  feed.active = h("div", { class: "activerow hidden" });
  feed.total = h("div", { class: "total" });
  feed.list = h("div", { class: "list" });
  feed.more = h("button", { class: "more hidden", onclick: () => loadFeed(false) }, "Показать ещё");
  feed.el = h("div", { class: "screen" },
    h("div", { class: "topbar" },
      h("div", { class: "brandline" }, h("img", { src: "logo.svg", alt: "" }), wordmark()),
      h("div", { class: "searchrow" },
        h("label", { class: "search" }, icon("search"), feed.input),
        h("button", { class: "iconbtn", "aria-label": "Фильтры", onclick: () => { if (!locked("filters")) push({ kind: "filters" }); } }, icon("filter"), feed.badge)),
      feed.sorts, feed.active),
    feed.total, feed.list, feed.more, supportLink(), webLinks());
  renderSorts();
  renderBadge();
  return feed.el;
}

function renderSorts() {
  feed.sorts.replaceChildren(...SORTS.map(([key, label]) =>
    h("button", {
      class: "chip" + (state.sort === key ? " on" : ""),
      onclick: () => { if (state.sort !== key) hapticSelect(); state.sort = key; store.set("sort", key); renderSorts(); loadFeed(true); },
    }, label)));
}

function renderBadge() {
  const n = activeFilterCount(state.filters);
  feed.badge.textContent = n;
  feed.badge.classList.toggle("hidden", !n);
  renderActive();
}

// Включённые фильтры - чипами под сортировкой: видно, что именно включено. Особенно цена
// "от 300 тыс." по умолчанию (12.10.2026) - иначе новичок видит на кнопке фильтров "1" без
// объяснения. Нажатие на чип - экран фильтров, крестик - снять только этот фильтр.
// "Скрыть битые" не показываем: это настройка по умолчанию, в счётчик она тоже не входит.
function rangeText([a, b], fmt) {
  if (a != null && b != null) return `${fmt(a)} – ${fmt(b)}`;
  return a != null ? `от ${fmt(a)}` : `до ${fmt(b)}`;
}
function activeChips(f) {
  const out = [];  // [надпись, функция, которая снимает фильтр с копии]
  const brandLabel = (key) => ((state.facets && state.facets.brands.find((b) => b.key === key)) || {}).label || key;
  if (f.brands.length) out.push([f.brands.length === 1 ? brandLabel(f.brands[0]) : `Марки: ${f.brands.length}`,
    (x) => { x.brands = []; x.models = {}; }]);
  if (f.price) out.push([`Цена ${rangeText(f.price, short)} ₽`, (x) => { x.price = null; }]);
  if (f.year) out.push([`Год ${rangeText(f.year, String)}`, (x) => { x.year = null; }]);
  if (f.mileageTo != null) out.push([`Пробег до ${short(f.mileageTo)} км`, (x) => { x.mileageTo = null; }]);
  if (f.gapMin != null) out.push([f.gapMin < 1 ? "Ниже рынка" : `Ниже рынка ${GAP_OPTIONS.find(([v]) => v === f.gapMin)?.[1] || ""}`.trim(),
    (x) => { x.gapMin = null; }]);
  if (f.ownersTo != null) out.push([f.ownersTo === 1 ? "1 владелец" : `Владельцев до ${f.ownersTo}`, (x) => { x.ownersTo = null; }]);
  if (f.dtpTo != null) out.push([f.dtpTo === 0 ? "Без ДТП" : `ДТП до ${f.dtpTo}`, (x) => { x.dtpTo = null; }]);
  for (const r of f.regions) out.push([regionShort(r) === "МО" ? "Московская обл." : regionShort(r),
    (x) => { x.regions = x.regions.filter((v) => v !== r); }]);
  for (const [v, label] of TRADES) if (f.trade.includes(v)) out.push([label, (x) => { x.trade = x.trade.filter((t) => t !== v); }]);
  for (const [v, label] of KINDS) if ((f.kinds || []).includes(v)) out.push([label, (x) => { x.kinds = x.kinds.filter((k) => k !== v); }]);
  for (const [key, label] of [["body", (v) => cap(v)], ["fuel", (v) => cap(v)], ["gearbox", (v) => cap(v)], ["drive", (v) => `${cap(v)} привод`]])
    for (const v of f[key] || []) out.push([label(v), (x) => { x[key] = x[key].filter((y) => y !== v); }]);
  if (f.volume) out.push([`Объём ${rangeText(f.volume, litersText)} л`, (x) => { x.volume = null; }]);
  if (f.power) out.push([`Мощность ${rangeText(f.power, String)} л.с.`, (x) => { x.power = null; }]);
  return out;
}
function renderActive() {
  if (!feed.active) return;
  const chips = activeChips(state.filters);
  const save = saveChip();  // сохранённые поиски: «Сохранить поиск» / «Поиск сохранён»
  feed.active.classList.toggle("hidden", !chips.length && !save);
  feed.active.replaceChildren(...[save].filter(Boolean), ...chips.map(([label, clear]) => h("span", { class: "fchip" },
    h("button", { class: "fchip-l", onclick: () => { if (!locked("filters")) push({ kind: "filters" }); } }, label),
    h("button", { class: "fchip-x", "aria-label": `Убрать фильтр «${label}»`, onclick: () => {
      if (locked("filters")) return;
      const f = JSON.parse(JSON.stringify(state.filters));
      clear(f);
      state.filters = f;
      store.set("filters", f);
      renderBadge();
      loadFeed(true);
    } }, "✕"))));
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
    feed.total.textContent = `${nf.format(data.total)} ${plural(data.total, "лот", "лота", "лотов")}` +
      (data.hidden_damaged ? ` · битых скрыто: ${data.hidden_damaged}` : "");
    if (!state.items.length) {
      const filtered = activeFilterCount(state.filters) || state.q;
      feed.list.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Ничего не нашлось"),
        !filtered ? "Лотов пока нет."
          : state.searchesOn ? "Сохраните поиск кнопкой «Сохранить поиск» вверху — пришлём, когда такие лоты появятся. Или ослабьте фильтры."
          : "Попробуйте ослабить фильтры или изменить запрос."));
    }
  } catch (e) {
    if (id !== state.reqId) return;
    if (e instanceof AuthError) return showStub();
    if (reset) feed.list.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить"), "Проверьте интернет и попробуйте ещё раз."));
    else { hapticNotify("error"); toast("Не удалось загрузить"); }
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
    // открытые - сверху; закрытые - ниже с итогом торгов; через 60 дней - в свёрнутый архив
    const active = items.filter((i) => i.fav_state === "open");
    const closed = items.filter((i) => i.fav_state !== "open" && !i.archived);
    const archived = items.filter((i) => i.archived);
    const archiveList = h("div", { class: "list hidden" }, archived.map(card));
    const parts = [];
    if (active.length) parts.push(h("div", { class: "list" }, active.map(card)));
    if (closed.length) parts.push(h("div", { class: "fav-title" }, "Торги закончились"), h("div", { class: "list" }, closed.map(card)));
    if (archived.length) parts.push(h("button", { class: "archive-toggle", onclick: (e) => {
      const hidden = archiveList.classList.toggle("hidden");
      e.currentTarget.textContent = `${hidden ? "Показать" : "Скрыть"} архив (${archived.length})`;
    } }, `Показать архив (${archived.length})`), archiveList);
    favsEl.replaceChildren(favsEl.firstChild, ...(items.length ? parts :
      [h("div", { class: "empty" }, h("b", {}, "Здесь пока пусто"), "Нажмите ♡ на карточке лота, чтобы сохранить его сюда. Если машину выставят снова, новые торги появятся здесь же.")]),
      ...[supportLink()].filter(Boolean));
  } catch (e) {
    if (e instanceof AuthError) return showStub();
    favsEl.replaceChildren(favsEl.firstChild, h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить")));
  }
}

// ---------- сохранённые поиски (вкладка) ----------
// Поиск - фильтры ленты и текст под именем (searches.py на сервере), новые лоты по нему присылает бот
// (notify.py). Сохранить - кнопка первой в строке фильтров ленты: видна, когда фильтры отличаются от
// начальных (решения владельца 19.10.2026: вкладка «Поиски», кнопка в строке фильтров). Открыть поиск -
// поставить его фильтры в ленту; лоты из уведомлений после прошлого открытия помечены «новый».
// Включено, когда /api/me отдаёт searches (HONESTLOT_SAVED_SEARCHES на сервере); только в Pro.

const searchesEl = h("div", { class: "screen" });

const paramsOf = (filters, q) => Object.fromEntries(new URLSearchParams(queryString(filters, q, null)));
const canon = (p) => JSON.stringify(Object.entries(p || {}).map(([k, v]) => [k, String(v)]).sort());

// параметры поиска (как у /api/lots) -> фильтры ленты; обратное - paramsOf
function filtersFromParams(p) {
  const list = (k) => (p[k] ? String(p[k]).split(",").filter(Boolean) : []);
  const num = (k) => (p[k] != null && p[k] !== "" ? Number(p[k]) : null);
  const pair = (a, b) => (num(a) != null || num(b) != null ? [num(a), num(b)] : null);
  const models = {};
  for (const item of list("models")) {
    const i = item.indexOf("|");
    if (i > 0) (models[item.slice(0, i)] = models[item.slice(0, i)] || []).push(item.slice(i + 1));
  }
  return { ...emptyFilters(), brands: list("brands"), models, year: pair("year_from", "year_to"),
    price: pair("price_from", "price_to"), mileageTo: num("mileage_to"), gapMin: num("gap_min"), ownersTo: num("owners_to"), dtpTo: num("dtp_to"),
    regions: list("regions"), trade: list("trade"), kinds: list("kinds"), fuel: list("fuel"),
    gearbox: list("gearbox"), drive: list("drive"), body: list("body"), volume: pair("vol_from", "vol_to"),
    power: pair("power_from", "power_to"), hideDamaged: p.hide_damaged === "1" };
}

async function loadSearches() {
  const data = await api("/searches");
  state.searches = data.items;
  state.searchLimit = data.limit;
  state.notifySettings = data.settings;
  renderTabs();
  return data;
}

const newCount = () => (state.searches || []).reduce((n, s) => n + s.new_ids.length, 0);

function saveChip() {
  if (!state.searchesOn) return null;
  const cur = paramsOf(state.filters, state.q);
  if (canon(cur) === canon(paramsOf(emptyFilters(), ""))) return null;  // фильтры не трогали - сохранять нечего
  const saved = (state.searches || []).find((s) => canon(s.params) === canon(cur));
  if (saved) return h("button", { class: "savechip on", onclick: () => selectTab("searches") }, "✓ Поиск сохранён");
  return h("button", { class: "savechip", onclick: () => { if (!locked("searches")) openSaveSheet(cur); } },
    icon("bell"), "Сохранить поиск");
}

// Лист снизу (оформление - как у окна Pro): заголовок и содержимое. -> функция закрытия.
function openSheet(title, ...body) {
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const bg = h("div", { class: "paywall", onclick: (e) => { if (e.target === bg) close(); } },
    h("div", { class: "pw-box sheet", role: "dialog", "aria-modal": "true", "aria-label": title }, h("h3", {}, title), ...body));
  document.addEventListener("keydown", onKey);
  document.body.append(bg);
  return close;
}

function switchEl(on, onchange, label) {
  const input = h("input", { type: "checkbox", checked: !!on, "aria-label": label,
    onchange: (e) => { hapticSelect(); onchange(e.target.checked, e.target); } });
  return h("label", { class: "sw", onclick: (e) => e.stopPropagation() }, input, h("span"));
}

async function setNotify(patch) {
  state.notifySettings = await api("/notify/settings", { method: "POST", body: JSON.stringify(patch) });
  return state.notifySettings;
}

// Бот может писать человеку, только если тот разрешил. Свой текст в запрос Telegram не вставить -
// сначала своё объяснение (showPopup), потом requestWriteAccess. Кто уже разрешил (запускал бота),
// тому ничего не показываем (allows_write_to_pm в initData). -> разрешено ли.
async function ensureTelegram() {
  if (!IN_TG) return false;
  if (state.notifySettings && state.notifySettings.tg) return true;
  const u = tg.initDataUnsafe && tg.initDataUnsafe.user;
  let allowed = !!(u && u.allows_write_to_pm);
  if (!allowed) {
    if (!(tg.isVersionAtLeast && tg.isVersionAtLeast("6.9"))) return false;
    const choice = await new Promise((res) => {
      try {
        tg.showPopup({ title: "Уведомления в Telegram",
          message: "Чтобы присылать новые лоты по вашим поискам, боту HonestLot нужно разрешение писать вам.",
          buttons: [{ id: "later", type: "default", text: "Не сейчас" }, { id: "ok", type: "default", text: "Разрешить" }] }, res);
      } catch { res("ok"); }
    });
    if (choice !== "ok") return false;
    allowed = await new Promise((res) => { try { tg.requestWriteAccess((ok) => res(!!ok)); } catch { res(false); } });
  }
  try { await setNotify({ tg: allowed }); } catch { /* попробуем при следующем сохранении */ }
  return allowed;
}

async function openSaveSheet(params) {
  haptic();
  const active = state.activeSearch && (state.searches || []).find((s) => s.id === state.activeSearch);
  const full = (state.searches || []).length >= (state.searchLimit || 10);
  const name = h("input", { class: "textin", type: "text", maxlength: "60", placeholder: "Название" });
  const info = h("div", { class: "sub" }, "Считаем лоты…");
  const notifyBox = h("input", { type: "checkbox", checked: true, onchange: hapticSelect });
  const err = h("div", { class: "sheet-err hidden" });
  const save = full ? null : h("button", { class: "btn" }, active ? "Сохранить как новый" : "Сохранить");
  const update = active ? h("button", { class: "btn" + (save ? " secondary wide" : "") },
    active.name.includes("«") ? "Обновить сохранённый поиск" : `Обновить «${active.name}»`) : null;
  const close = openSheet("Сохранить поиск",
    h("label", { class: "fld" }, h("span", {}, "Название"), name),
    info,
    h("label", { class: "togglerow" }, notifyBox, h("span", {}, h("b", {}, "Присылать новые лоты"),
      h("span", { class: "sub" }, (IN_TG ? "В этот чат, как только" : "Как только") + " появится подходящая машина. О каждой машине — один раз."))),
    full ? h("div", { class: "sub" }, `Сохранено ${state.searchLimit} поисков — это максимум. Удалите ненужный во вкладке «Поиски».`) : null,
    err,
    h("div", { class: "sheet-acts" }, save, update));
  api(`/searches/preview?${new URLSearchParams(params)}`).then((p) => {
    name.placeholder = p.name;
    info.textContent = `Сейчас подходит ${nf.format(p.total)} ${plural(p.total, "лот", "лота", "лотов")}`;
  }).catch(() => { info.textContent = ""; });
  const run = async (request) => {
    [save, update].forEach((b) => b && (b.disabled = true));
    try {
      const data = await request();
      hapticNotify("success");
      state.searches = data.items;
      state.notifySettings = data.settings;
      state.activeSearch = null;
      close();
      renderActive();
      renderTabs();
      const notifyOn = notifyBox.checked;
      const tgOk = notifyOn && await ensureTelegram();
      const st = state.notifySettings || {};
      if (!notifyOn) toast("Поиск сохранён");
      else if (tgOk) toast("Поиск сохранён. Новые лоты придут в этот чат.", null, 3500);
      else if (st.email_on) toast("Поиск сохранён. Новые лоты придут на почту.", null, 3500);
      else toast("Поиск сохранён", { label: IN_TG ? "Уведомления ›" : "Указать почту ›", onclick: () => selectTab("searches") });
    } catch (e) {
      if (e instanceof AuthError) { close(); return showStub(); }
      hapticNotify("error");
      err.textContent = e.detail || "Не получилось сохранить, попробуйте ещё раз";
      err.classList.remove("hidden");
      [save, update].forEach((b) => b && (b.disabled = false));
    }
  };
  const body = (extra) => JSON.stringify({ params, notify: notifyBox.checked, ...extra });
  if (save) save.addEventListener("click", () => run(() => api("/searches", { method: "POST", body: body({ name: name.value.trim() || null }) })));
  if (update) update.addEventListener("click", () => run(() => api(`/searches/${active.id}`, { method: "PATCH",
    body: body(name.value.trim() ? { name: name.value.trim() } : {}) })));
}

// Открыть поиск: его фильтры и текст - в ленту; лоты из уведомлений с прошлого раза - «новый».
// editFilters («Изменить фильтры» в меню поиска) - сразу экран фильтров, а окно сохранения предложит
// обновить этот поиск; при простом открытии изменённые фильтры сохраняются новым поиском.
function openSearch(s, editFilters) {
  state.filters = filtersFromParams(s.params);
  store.set("filters", state.filters);
  state.q = s.params.q || "";
  if (feed.input) feed.input.value = state.q;
  state.activeSearch = editFilters ? s.id : null;
  state.newIds = new Set(s.new_ids);
  s.new_ids = [];
  api(`/searches/${s.id}/open`, { method: "POST" }).catch(() => {});
  selectTab("feed");
  renderTabs();
  renderBadge();
  loadFeed(true);
  if (editFilters) push({ kind: "filters" });
}

function searchCard(s) {
  const fresh = s.new_ids.length;
  return h("div", { class: "scard", role: "button", onclick: () => openSearch(s) },
    h("div", { class: "sn" }, s.name),
    s.custom_name ? h("div", { class: "sf" }, s.filters) : null,
    h("div", { class: "sc" }, `${nf.format(s.total)} ${plural(s.total, "лот", "лота", "лотов")}`,
      fresh ? h("b", {}, `+${fresh} ${plural(fresh, "новый", "новых", "новых")}`) : null),
    switchEl(s.notify, async (on, input) => {
      try {
        const data = await api(`/searches/${s.id}`, { method: "PATCH", body: JSON.stringify({ notify: on }) });
        state.searches = data.items;
        if (on && IN_TG) await ensureTelegram();
      } catch { input.checked = !on; hapticNotify("error"); toast("Не получилось, попробуйте ещё раз"); }
    }, "Присылать новые лоты"),
    h("button", { class: "sdots", "aria-label": "Действия с поиском", onclick: (e) => { e.stopPropagation(); searchMenu(s); } }, "···"));
}

function searchMenu(s) {
  const box = h("div", { class: "menulist" });
  const close = openSheet(s.name, box);
  const act = (label, fn, cls) => h("button", { class: cls || "", onclick: fn }, label);
  const draw = () => box.replaceChildren(
    act("Изменить фильтры", () => { close(); openSearch(s, true); }),
    act("Переименовать", () => { close(); renameSheet(s); }),
    act("Удалить поиск", () => box.replaceChildren(
      h("div", { class: "menunote" }, "Удалить поиск? Новые лоты по нему перестанут приходить."),
      act("Удалить", async () => {
        try {
          const data = await api(`/searches/${s.id}`, { method: "DELETE" });
          state.searches = data.items;
          if (state.activeSearch === s.id) state.activeSearch = null;
          hapticNotify("success");
          close(); renderSearches(); renderActive();
        } catch { hapticNotify("error"); toast("Не получилось удалить"); }
      }, "danger"),
      act("Отмена", draw)), "danger"));
  draw();
}

function renameSheet(s) {
  const input = h("input", { class: "textin", type: "text", maxlength: "60", value: s.custom_name ? s.name : "", placeholder: s.filters });
  const save = h("button", { class: "btn" }, "Сохранить");
  const close = openSheet("Название поиска", input,
    h("div", { class: "sub" }, "Пустое — название по фильтрам."), h("div", { class: "sheet-acts" }, save));
  save.addEventListener("click", async () => {
    try {
      const data = await api(`/searches/${s.id}`, { method: "PATCH", body: JSON.stringify({ name: input.value.trim() }) });
      state.searches = data.items;
      close(); renderSearches();
    } catch { hapticNotify("error"); toast("Не получилось сохранить"); }
  });
  input.focus();
}

function setRow(title, sub, control, extra) {
  return h("div", { class: "setrow" }, h("div", { class: "l" }, h("b", {}, title), sub ? h("span", { class: "sub" }, sub) : null, extra), control);
}

function emailRow(st) {
  const form = (value) => {
    const input = h("input", { class: "textin", type: "email", placeholder: "you@example.com", value: value || "", autocomplete: "email" });
    const send = h("button", { class: "smallbtn" }, "Получать");
    send.addEventListener("click", async () => {
      send.disabled = true;
      try {
        const r = await api("/notify/email", { method: "POST", body: JSON.stringify({ email: input.value.trim() }) });
        state.notifySettings = r;
        hapticNotify("success");
        toast(r.status === "verified" ? "Почта подключена" : "Отправили письмо — откройте ссылку в нём", null, 3500);
        renderSearches();
      } catch (e) { send.disabled = false; hapticNotify("error"); toast(e.detail || "Не получилось, проверьте адрес"); }
    });
    return h("div", { class: "emailform" }, input, send);
  };
  if (st.email_verified) {
    const other = h("button", { class: "linkbtn" }, "Другой адрес");
    const row = setRow("Почта", `${st.email} · одно письмо в день`,
      switchEl(st.email_on, (on) => setNotify({ email_on: on }).catch(() => { hapticNotify("error"); toast("Не получилось"); })), other);
    other.addEventListener("click", () => { other.replaceWith(form("")); });
    return row;
  }
  if (st.email) {
    return setRow("Почта", `Ждём подтверждения: письмо отправлено на ${st.email}. Не пришло — проверьте «Спам» или укажите адрес ещё раз.`,
      null, form(st.email));
  }
  return setRow("Почта", "Одно письмо в день: новое по поискам и избранному", null, form(""));
}

function notifyBlock() {
  const st = state.notifySettings || {};
  const rows = [];
  if (IN_TG) {
    const sub = st.tg ? "Новые лоты приходят в этот чат сразу" : st.tg_blocked ? "Бот не может вам писать — включите, чтобы разрешить" : "Выключены";
    rows.push(setRow("Telegram", sub, switchEl(st.tg, async (on, input) => {
      if (on) { const ok = await ensureTelegram(); input.checked = ok; if (!ok) toast("Telegram не дал разрешение"); }
      else { try { await setNotify({ tg: false }); } catch { input.checked = true; } }
      renderSearches();
    }, "Уведомления в Telegram")));
  } else if (st.tg) {
    rows.push(setRow("Telegram", "Новые лоты приходят в чат с ботом HonestLot", null));
  }
  rows.push(emailRow(st));
  rows.push(setRow("Изменения в избранном", "Цена снизилась, машину выставили снова",
    switchEl(st.fav_events !== false, (on) => setNotify({ fav_events: on }).catch(() => { hapticNotify("error"); toast("Не получилось"); }),
      "Изменения в избранном")));
  return [h("div", { class: "fav-title" }, "Уведомления"), h("div", { class: "setblock" }, rows)];
}

async function renderSearches() {
  const head = h("div", { class: "topbar" }, h("div", { class: "brandline" }, h("div", { class: "word" }, "Поиски")));
  if (proLocked) {
    searchesEl.replaceChildren(head, h("div", { class: "lockcard" },
      h("div", { class: "pw-tag" }, "HonestLot Pro"),
      h("h3", {}, "Новые лоты сами придут к вам"),
      h("p", {}, "Сохраните поиск — и бот напишет, как только появится подходящая машина. Если подешевеет машина из избранного или её выставят снова, тоже сообщим."),
      IN_TG ? h("button", { class: "btn", onclick: () => goPro("searches") }, "Оформить Pro")
        : h("a", { class: "btn", href: "/pro", onclick: () => track("paywall_go", null, "searches") }, "Перейти на Pro")));
    return;
  }
  if (!state.searches) searchesEl.replaceChildren(head, h("div", { class: "loader" }, "Загружаем…"));
  try { await loadSearches(); } catch (e) {
    if (e instanceof AuthError) return showStub();
    searchesEl.replaceChildren(head, h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить")));
    return;
  }
  const list = state.searches.length ? h("div", { class: "list" }, state.searches.map(searchCard))
    : h("div", { class: "empty" }, h("b", {}, "Сохранённых поисков пока нет"),
      `Настройте фильтры в ленте и нажмите «Сохранить поиск» — новые лоты по нему придут ${IN_TG ? "в этот чат" : "на почту"}.`);
  searchesEl.replaceChildren(head, list, ...notifyBlock(), ...[supportLink()].filter(Boolean));
  renderActive();
}

// ---------- вкладки и навигация ----------

const tabsEl = h("nav", { class: "tabs" });
function selectTab(key) {
  if (key === "favs" && locked("favs")) return;
  if (state.stack.length) { state.stack = []; state.scrolls = []; renderTop(); }  // из экрана лота - сразу в раздел
  if (state.tab === key) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
  hapticSelect();
  state.tab = key; renderTabs(); showTab();
}
function renderTabs() {
  const tab = (key, label, ic, n) => h("button", { class: state.tab === key ? "on" : "", onclick: () => selectTab(key) },
    h("span", { class: "tabicon" }, icon(ic), n ? h("span", { class: "badge" }, n) : null), label);
  tabsEl.replaceChildren(tab("feed", "Лоты", "list"), ...(state.searchesOn ? [tab("searches", "Поиски", "bell", newCount())] : []),
    tab("favs", "Избранное", "heart"));
  if (webNav) webNav.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === state.tab));
}
function showTab() {
  feed.el.classList.toggle("hidden", state.tab !== "feed");
  favsEl.classList.toggle("hidden", state.tab !== "favs");
  searchesEl.classList.toggle("hidden", state.tab !== "searches");
  if (state.tab === "favs") renderFavs();
  if (state.tab === "searches") renderSearches();
  window.scrollTo(0, 0);
}

// Адреса экранов в веб-версии (22.10.2026): открытый лот - /?lot=ID в истории браузера, фильтры - запись истории
// без смены адреса. «Назад»/«Вперёд» браузера закрывают и открывают экраны, лот открывается в новой вкладке и
// переживает обновление страницы (start() читает ?lot=). В Telegram - как раньше: «Назад» - кнопка Telegram.
const URL_NAV = WEB;
if (URL_NAV && "scrollRestoration" in history) history.scrollRestoration = "manual";  // прокрутку ленты ведём сами
// локально веб-версия включается параметром ?web - сохраняем его в адресах (на сайте его нет)
const WEB_FLAG = LOCAL && WEB ? "web&" : "";
const lotHref = (id) => `/?${WEB_FLAG}lot=${id}`;

function push(screen) {
  state.scrolls.push(window.scrollY);
  state.stack.push(screen);
  if (URL_NAV) {
    history.pushState({ hl: state.stack.length, kind: screen.kind, lot: screen.kind === "lot" ? screen.id : null }, "",
      screen.kind === "lot" ? lotHref(screen.id) : location.pathname + location.search);
  }
  renderTop();
  window.scrollTo(0, 0);
}
function pop() {
  // экран открыт записью истории - закрываем через историю, чтобы «Вперёд» и адрес остались верными (popstate)
  if (URL_NAV && state.stack.length && history.state && history.state.hl === state.stack.length) {
    history.back();
    return;
  }
  popLocal();
}
function popLocal() {
  state.stack.pop();
  renderTop();
  const y = state.scrolls.pop() || 0;
  requestAnimationFrame(() => window.scrollTo(0, y));
}
if (URL_NAV) {
  window.addEventListener("popstate", (e) => {
    const depth = (e.state && e.state.hl) || 0;
    if (viewerClose) viewerClose();  // открытый просмотр фото закрываем вместе с экраном
    while (state.stack.length > depth) popLocal();
    if (state.stack.length < depth && e.state && e.state.kind === "lot") {  // «Вперёд» на лот
      state.scrolls.push(window.scrollY);
      state.stack.push({ kind: "lot", id: e.state.lot });
      renderTop();
      window.scrollTo(0, 0);
    }
  });
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
// «Назад» Telegram при открытом просмотре фото закрывает просмотр, а не экран лота
if (IN_TG) tg.BackButton.onClick(() => (viewerClose ? viewerClose() : pop()));

function backbar(right) {
  return h("div", { class: "backbar" },
    IN_TG ? h("span") : h("button", { class: "left", onclick: pop }, icon("back"), "Назад"),
    right || h("span"));
}

// ---------- экран лота ----------

// Галерея с запасными наборами фото (lot.photo_sets, lots._photo_sets на сервере): если фото
// набора не открылось, галерея целиком переходит на следующий набор (обычно фото агрегатора); в
// последнем наборе неоткрывшиеся фото просто убираются, не осталось ни одного - «нет фото».
function gallery(lot) {
  const sets = (lot.photo_sets && lot.photo_sets.length ? lot.photo_sets : [lot.photos || []]).filter((s) => s.length);
  const box = h("div", { class: "gallery-wrap" });
  const render = (k) => box.replaceChildren(sets[k] ? gallerySet(sets[k], () => render(k + 1), k === sets.length - 1)
    : h("div", { class: "nophoto" }, icon("car")));
  render(0);
  return box;
}

function gallerySet(photos, fallback, last) {
  let switched = false;
  const counter = h("div", { class: "counter" }, `1 / ${photos.length}`);
  const onError = (e) => {
    if (!last) { if (!switched) { switched = true; fallback(); } return; }
    e.target.remove();
    const left = slides.querySelectorAll("img").length;
    if (!left) return fallback();
    counter.textContent = `1 / ${left}`;
  };
  const slides = h("div", { class: "slides" },
    photos.map((p, i) => h("img", {
      src: p.full, alt: "", loading: i ? "lazy" : "eager", onerror: onError,
      // на весь экран с увеличением; после закрытия галерея встаёт на то же фото
      onclick: () => openViewer(photos, i, (at) => { slides.scrollLeft = at * slides.clientWidth; }),
    })));
  slides.addEventListener("scroll", () => {
    const i = Math.round(slides.scrollLeft / slides.clientWidth);
    counter.textContent = `${i + 1} / ${photos.length}`;
  }, { passive: true });
  const arrows = WEB && photos.length > 1 ? [-1, 1].map((d) => h("button", {
    class: "gnav " + (d < 0 ? "prev" : "next"), "aria-label": d < 0 ? "Предыдущее фото" : "Следующее фото",
    onclick: () => slides.scrollBy({ left: d * slides.clientWidth, behavior: "smooth" }),
  }, d < 0 ? "‹" : "›")) : [];
  return h("div", { class: "gallery" }, slides, ...arrows, photos.length > 1 ? counter : null);
}

// ---------- просмотр фото на весь экран ----------
// Нажатие на фото в галерее лота открывает его на весь экран (16.10.2026): листание - свайпом
// (прокрутка с привязкой к кадру, как в галерее; на компьютере - стрелки и клавиши ← →),
// увеличение - двумя пальцами или двойным касанием (на компьютере - колесом и двойным
// щелчком), увеличенное фото перетаскивается. Закрыть - крестик, «Назад» Telegram, Esc.
// Свой код, а не библиотека: нужен только зум. Свайп вниз в Telegram сворачивает мини-апп -
// на время просмотра выключен (disableVerticalSwipes, Bot API 7.7).
let viewerClose = null;
const ZOOM_MAX = 4, ZOOM_TAP = 2.5;

function openViewer(photos, start, onClose) {
  const frames = photos.map((p) => {
    const img = h("img", { src: p.full, alt: "", draggable: "false", class: p.light ? "light" : null });
    return { frame: h("div", { class: "pv-frame" }, img), img, s: 1, x: 0, y: 0 };
  });
  const track = h("div", { class: "pv-track" }, frames.map((f) => f.frame));
  const counter = h("div", { class: "pv-counter" });
  const arrows = WEB && photos.length > 1 ? [-1, 1].map((d) => h("button", {
    class: "gnav pv-nav " + (d < 0 ? "prev" : "next"), "aria-label": d < 0 ? "Предыдущее фото" : "Следующее фото",
    onclick: () => go(cur() + d),
  }, d < 0 ? "‹" : "›")) : [];
  const box = h("div", { class: "pv", role: "dialog", "aria-modal": "true", "aria-label": "Фото лота" }, track,
    h("button", { class: "pv-close", "aria-label": "Закрыть", onclick: () => close() }, "×"),
    ...arrows, photos.length > 1 ? counter : null);

  const cur = () => Math.max(0, Math.min(frames.length - 1, Math.round(track.scrollLeft / (track.clientWidth || 1))));
  const showCounter = () => { counter.textContent = `${cur() + 1} / ${photos.length}`; };
  const go = (i) => {
    reset(frames[cur()]);
    track.scrollTo({ left: Math.max(0, Math.min(frames.length - 1, i)) * track.clientWidth, behavior: "smooth" });
  };
  // Не дальше края фото: размер картинки при масштабе 1 - вписанная в кадр (object-fit: contain).
  function clamp(f) {
    const fw = f.frame.clientWidth, fh = f.frame.clientHeight;
    const nw = f.img.naturalWidth || fw, nh = f.img.naturalHeight || fh;
    const k = Math.min(fw / nw, fh / nh) * f.s;
    const mx = Math.max(0, (nw * k - fw) / 2), my = Math.max(0, (nh * k - fh) / 2);
    f.x = Math.max(-mx, Math.min(mx, f.x));
    f.y = Math.max(-my, Math.min(my, f.y));
  }
  function apply(f, animate) {
    clamp(f);
    f.img.style.transition = animate ? "transform .2s ease" : "none";
    f.img.style.transform = `translate(${f.x}px, ${f.y}px) scale(${f.s})`;
    track.classList.toggle("zoomed", f.s > 1.01);
  }
  function reset(f) { f.s = 1; f.x = 0; f.y = 0; apply(f, true); }
  // Точка экрана -> координаты от центра кадра; масштаб вокруг точки p.
  const local = (f, cx, cy) => {
    const r = f.frame.getBoundingClientRect();
    return { x: cx - r.left - r.width / 2, y: cy - r.top - r.height / 2 };
  };
  function zoomAt(f, s, p, animate) {
    s = Math.max(1, Math.min(ZOOM_MAX, s));
    f.x = p.x - (p.x - f.x) * s / f.s;
    f.y = p.y - (p.y - f.y) * s / f.s;
    f.s = s;
    apply(f, animate);
  }
  const toggleZoom = (f, p) => (f.s > 1.01 ? reset(f) : zoomAt(f, ZOOM_TAP, p, true));

  // касания: два пальца - масштаб, один палец по увеличенному фото - перетаскивание, двойное касание - зум
  let pinch = null, pan = null, tap = null, lastTap = null;
  const mid = (a, b) => ({ x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 });
  const dist = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1;
  track.addEventListener("touchstart", (e) => {
    const f = frames[cur()];
    if (e.touches.length === 2) {
      e.preventDefault();
      const m = mid(e.touches[0], e.touches[1]);
      pinch = { f, d: dist(e.touches[0], e.touches[1]), s: f.s, x: f.x, y: f.y, p: local(f, m.x, m.y) };
      pan = tap = null;
    } else if (e.touches.length === 1) {
      const t = e.touches[0];
      tap = { x: t.clientX, y: t.clientY, at: Date.now() };
      pan = f.s > 1.01 ? { f, sx: t.clientX, sy: t.clientY, x: f.x, y: f.y } : null;
    }
  }, { passive: false });
  track.addEventListener("touchmove", (e) => {
    if (pinch && e.touches.length === 2) {
      e.preventDefault();
      const f = pinch.f, m = mid(e.touches[0], e.touches[1]), p = local(f, m.x, m.y);
      const s = Math.max(1, Math.min(ZOOM_MAX, pinch.s * dist(e.touches[0], e.touches[1]) / pinch.d));
      f.s = s;
      f.x = pinch.p.x - (pinch.p.x - pinch.x) * s / pinch.s + (p.x - pinch.p.x);
      f.y = pinch.p.y - (pinch.p.y - pinch.y) * s / pinch.s + (p.y - pinch.p.y);
      apply(f);
    } else if (pan && e.touches.length === 1) {
      e.preventDefault();
      const t = e.touches[0];
      pan.f.x = pan.x + t.clientX - pan.sx;
      pan.f.y = pan.y + t.clientY - pan.sy;
      apply(pan.f);
    }
    if (tap && e.touches.length === 1 && Math.hypot(e.touches[0].clientX - tap.x, e.touches[0].clientY - tap.y) > 10) tap = null;
  }, { passive: false });
  track.addEventListener("touchend", (e) => {
    if (pinch && e.touches.length < 2) {
      if (pinch.f.s < 1.05) reset(pinch.f);
      pinch = null;
      tap = lastTap = null;
      return;
    }
    if (e.touches.length || !tap || Date.now() - tap.at > 300) { if (!e.touches.length) pan = null; return; }
    const f = frames[cur()];
    if (lastTap && Date.now() - lastTap.at < 300 && Math.hypot(tap.x - lastTap.x, tap.y - lastTap.y) < 40) {
      e.preventDefault();
      toggleZoom(f, local(f, tap.x, tap.y));
      lastTap = null;
    } else lastTap = tap;
    tap = pan = null;
  });
  // мышь: двойной щелчок и колесо - масштаб, перетаскивание увеличенного фото
  track.addEventListener("dblclick", (e) => { const f = frames[cur()]; toggleZoom(f, local(f, e.clientX, e.clientY)); });
  track.addEventListener("wheel", (e) => {
    e.preventDefault();
    const f = frames[cur()];
    zoomAt(f, f.s * Math.exp(-e.deltaY / 400), local(f, e.clientX, e.clientY));
  }, { passive: false });
  let drag = null;
  track.addEventListener("mousedown", (e) => {
    const f = frames[cur()];
    if (f.s > 1.01) { e.preventDefault(); drag = { f, sx: e.clientX, sy: e.clientY, x: f.x, y: f.y }; }
  });
  const onMouseMove = (e) => {
    if (!drag) return;
    drag.f.x = drag.x + e.clientX - drag.sx;
    drag.f.y = drag.y + e.clientY - drag.sy;
    apply(drag.f);
  };
  const onMouseUp = () => { drag = null; };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") go(cur() - 1);
    else if (e.key === "ArrowRight") go(cur() + 1);
  };
  track.addEventListener("scroll", showCounter, { passive: true });

  const swipes = IN_TG && tg.isVersionAtLeast && tg.isVersionAtLeast("7.7");
  function close() {
    const at = cur();
    box.remove();
    document.documentElement.classList.remove("pv-open");
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    if (swipes) tg.enableVerticalSwipes();
    tgChrome(false);
    viewerClose = null;
    if (onClose) onClose(at);
  }
  viewerClose = close;
  if (swipes) tg.disableVerticalSwipes();
  tgChrome(true);  // шапка и панель Telegram - чёрные, как фон просмотра (схемы ДТП - тоже здесь)
  document.documentElement.classList.add("pv-open");
  document.addEventListener("keydown", onKey);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
  document.body.append(box);
  track.scrollLeft = start * track.clientWidth;
  showCounter();
  haptic();
}

function rows(pairs) {
  return h("div", { class: "rows" }, pairs.filter((p) => p && p[1] != null && p[1] !== "")
    .map(([k, v]) => h("div", { class: "row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, v))));
}

// ДТП по VIN (TRONK, с 19.10.2026; решения владельца): «ДТП: N» раскрывается - даты, места и схемы
// повреждений (схема на весь экран - в просмотрщике фото); подробности только с Pro, число - всем.
// Нет данных по машине - блока нет (это не «чистая машина»); данные есть, ДТП нет - «ДТП не найдены».
const dtpDate = (iso) => (iso || "").slice(0, 10).split("-").reverse().join(".");
function dtpBlock(lot) {
  const d = lot.dtp;
  if (!d) return null;
  const asOf = d.as_of ? h("div", { class: "sub" }, `По данным Госавтоинспекции на ${dtpDate(d.as_of)}`) : null;
  if (!d.count) return h("div", { class: "block dtp" }, h("div", { class: "dtp-head clean" }, "ДТП не найдены"), asOf);
  const list = d.accidents || [];
  const schemes = list.filter((a) => a.scheme).map((a) => ({ full: a.scheme, light: true }));
  let open = false;
  const items = h("div", { class: "dtp-list hidden" }, list.map((a) => {
    const idx = schemes.findIndex((s) => s.full === a.scheme);
    return h("div", { class: "dtp-item" },
      h("div", { class: "dtp-text" },
        h("b", {}, dtpDate(a.date) || "Дата неизвестна"),
        h("span", {}, [a.type, a.region].filter(Boolean).join(" · "))),
      a.scheme ? h("button", { class: "dtp-scheme", "aria-label": "Схема повреждений",
        onclick: () => openViewer(schemes.slice(idx).concat(schemes.slice(0, idx)), 0) },
        h("img", { src: a.scheme, alt: "Схема повреждений", loading: "lazy" })) : null);
  }), h("div", { class: "sub" }, "Схема — места повреждений по данным Госавтоинспекции. Нажмите, чтобы увеличить."));
  const last = list[0] && list[0].date ? ` · последнее ${dtpDate(list[0].date)}` : "";
  const arrow = h("span", { class: "dtp-arrow" }, "▾");
  const head = h("button", { class: "dtp-head", "aria-expanded": "false", onclick: () => {
    if (locked("dtp")) return;
    open = !open;
    items.classList.toggle("hidden", !open);
    arrow.textContent = open ? "▴" : "▾";
    head.setAttribute("aria-expanded", String(open));
    if (open) track("dtp_open", lot.id);
  } }, h("span", {}, `ДТП: ${d.count}${last}`), arrow);
  return h("div", { class: "block dtp" }, head, asOf, items);
}

function marketBlock(lot) {
  if (lot.kind === "multilot") {
    return h("div", { class: "block" }, h("h3", {}, "Рынок"),
      h("div", { class: "sub" }, "Мультилот: несколько машин одним лотом. Сравнение с рынком для такого лота не считаем — смотрите состав лота в описании."));
  }
  if (lot.market_low == null || lot.market_high == null) {
    return h("div", { class: "block" }, h("h3", {}, "Рынок"), h("div", { class: "sub" }, "Рыночной оценки для этого лота пока нет."));
  }
  const lo = Math.min(lot.market_low, lot.price) * 0.9;
  const hi = Math.max(lot.market_high, lot.price) * 1.1;
  const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const mid = (lot.market_low + lot.market_high) / 2;
  const auction = lot.trade === "auction";
  const what = auction ? "Начальная цена" : "Лот";
  let verdict = auction ? "Начальная цена на уровне рынка" : "Цена на уровне рынка";
  if (lot.gap >= 0.5) verdict = `${what} ${auction ? "ниже" : "дешевле"} середины рынка на ${Math.round(lot.gap)}%`;
  else if (lot.gap <= -0.5) verdict = `${what} ${auction ? "выше" : "дороже"} середины рынка на ${Math.round(-lot.gap)}%`;
  if (auction) verdict += ". Итоговая цена определится на торгах.";
  return h("div", { class: "block" },
    h("h3", {}, "Рыночная цена"),
    h("div", {}, `${rub(lot.market_low)} — ${rub(lot.market_high)}`),
    h("div", { class: "range" },
      h("div", { class: "band", style: { left: pos(lot.market_low), width: `calc(${pos(lot.market_high)} - ${pos(lot.market_low)})` } }),
      h("div", { class: "mark", style: { left: pos(lot.price) }, title: "Цена лота" })),
    h("div", { class: "range-labels" }, h("span", {}, auction ? "▮ начальная цена" : "▮ цена лота"), h("span", {}, `середина ${short(Math.round(mid))} ₽`)),
    h("div", { class: "sub", style: { marginTop: "8px" } }, verdict),
    lot.gap_uncertain ? h("div", { class: "sub unsure-note" },
      "Оценка может быть неточной: для этой машины у неё большая погрешность.") : null,
    lot.mileage_estimated ? h("div", { class: "sub" }, "Оценка сделана по примерному пробегу.") : null);
}

async function renderLot(id) {
  overlay.replaceChildren(h("div", { class: "screen no-tabs" }, backbar(), h("div", { class: "loader" }, "Загружаем лот…")));
  loadRef();
  let lot;
  try { lot = await api(`/lots/${encodeURIComponent(id)}`); } catch (e) {
    if (e instanceof AuthError) return showStub();
    overlay.replaceChildren(h("div", { class: "screen no-tabs" }, backbar(), e.status === 404
      ? h("div", { class: "empty" }, h("b", {}, "Лот больше недоступен"), "Его уже нет в нашей базе. Посмотрите другие лоты в ленте.")
      : h("div", { class: "empty" }, h("b", {}, "Не удалось загрузить лот"))));
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

  // эта же машина: параллельно на других площадках и история всех её торгов
  const listingsBlock = (lot.listings_list || []).length > 1 ? h("div", { class: "block" },
    h("h3", {}, "Эта машина на нескольких площадках"),
    h("div", { class: "rows wrap-k" }, lot.listings_list.map((x) =>
      h("div", { class: "row" + (x.this ? " cur" : ""), role: x.this ? null : "button",
        onclick: x.this ? null : () => push({ kind: "lot", id: x.id }) },
        h("span", { class: "k" }, (x.platform || "площадка не указана").slice(0, 40), x.this ? " · этот лот" : ""),
        h("span", { class: "v" }, rub(x.price)))))) : null;
  const historyBlock = (lot.history || []).length > 1 ? h("div", { class: "block" },
    h("h3", {}, "История торгов этой машины"),
    h("div", { class: "rows wrap-k" }, lot.history.map((x) =>
      h("div", { class: "row" + (x.this ? " cur" : ""), role: x.this ? null : "button",
        onclick: x.this ? null : () => push({ kind: "lot", id: x.id }) },
        h("span", { class: "k" }, `${x.deadline ? "до " + dShort(x.deadline) : "—"} · ${x.trade === "public_offer" ? "публичное" : "аукцион"} · ${OUTCOME_SHORT[x.outcome] || ""}`),
        h("span", { class: "v" }, rub(x.price)))))) : null;

  const vin = lot.vin ? h("button", { class: "copy", onclick: () => {
    navigator.clipboard && navigator.clipboard.writeText(lot.vin).then(() => toast("VIN скопирован"), () => {});
  } }, lot.vin) : null;
  // пробег: из описания лота - как есть; из отчёта по истории машины - пересчитан на сегодня (+16 600 км в
  // год с даты записи), с датой записи; по году выпуска - «расчётный» (решение владельца 19.10.2026)
  const recDate = lot.mileage_record_date && /^\d{4}-\d{2}-\d{2}/.test(lot.mileage_record_date)
    ? lot.mileage_record_date.slice(0, 10).split("-").reverse().join(".") : null;
  const mileage = lot.mileage_km == null ? null
    : lot.mileage_estimated ? `~${nf.format(lot.mileage_km)} км (расчётный)`
    : lot.mileage_source === "report" ? `~${nf.format(lot.mileage_km)} км (по записи из отчёта${recDate ? " от " + recDate : ""})`
    : `${nf.format(lot.mileage_km)} км`;

  let descOpen = false;
  const desc = lot.description ? h("div", { class: "desc clamp" }, lot.description) : null;
  const descToggle = lot.description && lot.description.length > 300 ? h("button", { class: "linkbtn", onclick: (e) => {
    descOpen = !descOpen; desc.classList.toggle("clamp", !descOpen);
    e.currentTarget.textContent = descOpen ? "Свернуть" : "Показать полностью";
  } }, "Показать полностью") : null;

  // торги этого лота закончились, а машина снова выставлена (часто так и бывает
  // со ссылкой, которой поделились неделю назад) - ведём на текущие торги
  const current = !lot.is_open && (lot.listings_list || []).find((x) => !x.this);
  const relistedBox = current ? h("button", { class: "block relisted-box", onclick: () => push({ kind: "lot", id: current.id }) },
    h("b", {}, "Эта машина снова на торгах"),
    h("span", {}, `${rub(current.price)}${current.deadline ? " · заявки до " + dShort(current.deadline) : ""} · открыть →`)) : null;

  const headBlock = h("div", { class: "block headblock" },
      h("h2", {}, lot.name, lot.year ? `, ${lot.year}` : ""),
      h("div", { class: "sub" }, [mileage, regionShort(lot.region)].filter(Boolean).join(" · ")),
      lot.trade === "auction" ? h("div", { class: "pricecap" }, "Начальная цена") : null,
      h("div", { class: "bigprice" }, rub(lot.price), gapBadge(lot.gap, lot.total_damage || (lot.damage || []).length > 0)),
      lot.next_price && lot.is_open ? h("div", { class: "nextstep" },
        `С ${dShort(lot.next_price_from)} цена снизится до ${rub(lot.next_price)}`) : null);
  const bottomBar = h("div", { class: "bottombar" },
    h("button", { class: "btn share", "aria-label": "Поделиться", html: ICONS.share, onclick: () => shareLot(lot, "bottom") }),
    // площадка торгов; торги без ЭТП - объявление о торгах на ЕФРСБ (Федресурс), а не агрегатор (17.10.2026)
    h("button", { class: "btn", onclick: () => { track("source_click", lot.id); openLink(lot.etp_url || lot.efrsb_url || lot.url); } },
      lot.etp_url || !lot.efrsb_url ? "Открыть лот на сайте торгов" : "Открыть объявление на Федресурсе"));
  const blocks = [
    deadlineBlock,
    damageBox(lot),
    marketBlock(lot),
    dtpBlock(lot),
    periods,
    listingsBlock,
    historyBlock,
    h("div", { class: "block" }, h("h3", {}, "Характеристики"), rows([
      ["Год", lot.year],
      ["Пробег", mileage],
      ["Кузов", lot.body_name || (lot.body ? cap(lot.body) : null)],
      ["Двигатель", engineText(lot)],
      ["Коробка", lot.transmission],
      ["Привод", lot.drive],
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
  ];
  // В веб-версии на широком экране - две колонки: фото слева, цена, кнопки и блоки справа
  // (кнопки сразу под ценой: на компьютере нижней панели нет). На телефоне колонки
  // складываются в одну в прежнем порядке, панель снова внизу экрана (style.css).
  const body = WEB
    ? [h("div", { class: "lotgrid" }, h("div", { class: "lotleft" }, gallery(lot)),
        h("div", { class: "lotright" }, headBlock, bottomBar, ...blocks))]
    : [gallery(lot), headBlock, ...blocks, bottomBar];
  overlay.replaceChildren(h("div", { class: "screen no-tabs" + (WEB ? " lotscreen" : "") },
    backbar(h("div", { class: "actions" },
      h("button", { class: "sharebtn", "aria-label": "Поделиться", html: ICONS.share, onclick: () => shareLot(lot, "top") }),
      heartButton(lot.id, lot))),
    relistedBox,
    ...body));
}

const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;
const litersText = (l) => Number(l).toFixed(1).replace(".", ",");
const GEARBOX_SHORT = { "автомат": "АКПП", "механика": "МКПП" };
// Для карточки ленты: "1,6 л · 110 л.с. · АКПП · передний · дизель" - что известно (Авто.ру).
// Бензин - у большинства, в ленте его не пишем, чтобы строка помещалась; на экране лота он есть.
function specsShort(it) {
  return [
    it.body,  // группа кузова из оценки: «седан», «внедорожник» (с 24.10.2026)
    it.displacement ? `${litersText(Math.round(it.displacement / 100) / 10)} л` : null,
    it.power ? `${it.power} л.с.` : null,
    it.transmission ? GEARBOX_SHORT[it.transmission] || it.transmission : null,
    it.drive,
    it.engine_type !== "бензин" ? it.engine_type : null,
  ].filter(Boolean).join(" · ");
}

// "1,6 л, 110 л.с., бензин" - из того, что известно (объём в см³ -> литры с одним знаком)
function engineText(lot) {
  const parts = [
    lot.displacement ? `${litersText(Math.round(lot.displacement / 100) / 10)} л` : null,
    lot.power ? `${lot.power} л.с.` : null,
    lot.engine_type,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

// Предупреждение о повреждениях: тотальные (сгорела, на запчасти - по тексту или по
// проверке фото) и просто упоминания в тексте (после ДТП, битая).
function damageBox(lot) {
  const words = lot.damage || [], photo = lot.photo_damage || [];
  if (!lot.total_damage && !words.length) return null;
  const parts = [];
  if (photo.length || lot.total_damage && !words.length) parts.push(`по фото: ${photo.length ? photo.join(", ") : "тотальные повреждения"}`);
  if (words.length) parts.push(`в описании: ${words.join(", ")}`);
  const head = lot.total_damage ? "⚠ Похоже на тотальные повреждения, машина скорее на запчасти" : "⚠ Возможны повреждения";
  return h("div", { class: "block warnbox" }, `${head} (${parts.join("; ")}).`);
}

// ---------- фильтры ----------

const PRICE_STEPS = [0, 100e3, 200e3, 300e3, 400e3, 500e3, 600e3, 700e3, 800e3, 900e3, 1e6, 1.2e6, 1.5e6, 2e6, 2.5e6, 3e6, 4e6, 5e6, 7e6, 10e6, 15e6, 20e6, null];
const MILEAGE_STEPS = [20e3, 40e3, 60e3, 80e3, 100e3, 120e3, 150e3, 200e3, 250e3, 300e3, null];
// первый шаг - "без нижней границы", null в конце - "без верхней"
const VOLUME_STEPS = [0, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, null];
const POWER_STEPS = [0, 70, 90, 100, 110, 120, 150, 180, 200, 250, 300, 400, null];
const GAP_OPTIONS = [[null, "Любой"], [0.5, "Ниже рынка"], [10, "от 10%"], [20, "от 20%"], [30, "от 30%"]];
// число владельцев - из рыночной оценки по VIN (19.10.2026); лоты без него при фильтре не показываются
const OWNERS_OPTIONS = [[null, "Любое"], [1, "1"], [2, "до 2"], [3, "до 3"]];
// ДТП по VIN (TRONK, 20.10.2026); машины без данных при фильтре не показываются
const DTP_OPTIONS = [[null, "Любое"], [0, "Без ДТП"], [1, "до 1"], [2, "до 2"]];
const TRADES = [["auction", "Аукцион"], ["public_offer", "Публичное предложение"]];
const KINDS = [["car", "Одна машина"], ["multilot", "Мультилоты"]];

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
  // щелчок вибрации - на каждый шаг; input приходит и без смены шага (и при упоре в другой ползунок)
  let last = `${iFrom}:${iTo}`;
  const tick = () => { const now = `${a.value}:${b.value}`; if (now !== last) { last = now; hapticSelect(); } };
  a.addEventListener("input", () => { if (+a.value > +b.value) a.value = b.value; paint(); tick(); onInput(+a.value, +b.value); });
  b.addEventListener("input", () => { if (+b.value < +a.value) b.value = a.value; paint(); tick(); onInput(+a.value, +b.value); });
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
        showBtn.textContent = total ? `Показать ${nf.format(total)} ${plural(total, "лот", "лота", "лотов")}`
          : state.searchesOn ? "Лотов пока нет — применить" : "Ничего не найдено";
        showBtn.disabled = !total && !state.searchesOn;  // без лотов - чтобы сохранить поиск на будущее
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
    hapticSelect();
    if (draft.brands.includes(key)) { draft.brands = draft.brands.filter((b) => b !== key); delete draft.models[key]; }
    else { draft.brands.push(key); expanded.add(key); }
    drawBrands(); refreshCount();
  }
  function toggleModel(bkey, mkey) {
    hapticSelect();
    const ms = new Set(draft.models[bkey] || []);
    ms.has(mkey) ? ms.delete(mkey) : ms.add(mkey);
    if (ms.size) { draft.models[bkey] = [...ms]; if (!draft.brands.includes(bkey)) draft.brands.push(bkey); }
    else { delete draft.models[bkey]; draft.brands = draft.brands.filter((b) => b !== bkey); }
    drawBrands(); refreshCount();
  }
  // Марки и модели без лотов сейчас (были раньше, сервер отдаёт их с count 0) - по кнопке «Показать все»:
  // по ним можно сохранить поиск на будущее (19.10.2026). Поиск по маркам ищет и среди них.
  let allBrands = false;
  const allModels = new Set();
  function drawBrands() {
    const q = brandSearch.value.trim().toUpperCase();
    const visible = (b) => q || allBrands || b.count > 0 || draft.brands.includes(b.key);
    const list = brandOrder.filter((b) => visible(b) && (!q || b.label.toUpperCase().includes(q) || b.models.some((m) => m.label.toUpperCase().includes(q))));
    const hiddenBrands = q ? 0 : brandOrder.filter((b) => !visible(b)).length;
    const toggleAll = (hiddenBrands || allBrands) && !q ? h("button", { class: "linkbtn allbrands", onclick: () => { allBrands = !allBrands; drawBrands(); } },
      allBrands ? "Только марки с лотами" : `Показать все марки (+${hiddenBrands} без лотов сейчас)`) : null;
    brandList.replaceChildren(...list.map((b) => {
      const sel = draft.brands.includes(b.key);
      const models = draft.models[b.key] || [];
      const open = expanded.has(b.key) && b.models.length > 1;
      const showModel = (m) => allModels.has(b.key) || m.count > 0 || models.includes(m.key);
      const hiddenModels = b.models.filter((m) => !showModel(m)).length;
      return h("div", { class: "brand" },
        h("div", { class: "brandrow" },
          h("button", { class: "check" + (sel && !models.length ? " on" : "") + (models.length ? " part" : ""), onclick: () => toggleBrand(b.key), "aria-label": b.label },
            sel && !models.length ? "✓" : ""),
          h("button", { class: "lbl", style: { textAlign: "left" }, onclick: () => toggleBrand(b.key) }, b.label),
          h("span", { class: "cnt" + (b.count ? "" : " zero") }, b.count),
          b.models.length > 1 ? h("button", { class: "exp", onclick: () => { expanded.has(b.key) ? expanded.delete(b.key) : expanded.add(b.key); drawBrands(); } }, open ? "▴" : "▾") : null),
        open ? h("div", { class: "models chips" }, b.models.filter(showModel).map((m) =>
          h("button", { class: "chip" + (models.includes(m.key) ? " on" : "") + (m.count ? "" : " zero"), onclick: () => toggleModel(b.key, m.key) },
            m.label, h("span", { class: "cnt" }, m.count))),
          hiddenModels || allModels.has(b.key) ? h("button", { class: "chip more-models", onclick: () => {
            allModels.has(b.key) ? allModels.delete(b.key) : allModels.add(b.key); drawBrands(); } },
            allModels.has(b.key) ? "Только с лотами" : `Все модели (+${hiddenModels})`) : null) : null);
    }), ...(toggleAll ? [toggleAll] : []));
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
      h("button", { class: "chip" + (isOn(v) ? " on" : ""), onclick: () => { hapticSelect(); onToggle(v); draw(); refreshCount(); } },
        label, cnt != null ? h("span", { class: "cnt" }, cnt) : null)));
    draw();
    return box;
  }
  const toggleIn = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : arr.concat(v));
  const gapChips = chipGroup(GAP_OPTIONS, (v) => draft.gapMin === v, (v) => { draft.gapMin = v; });
  const ownersChips = chipGroup(OWNERS_OPTIONS, (v) => (draft.ownersTo ?? null) === v, (v) => { draft.ownersTo = v; });
  const dtpChips = chipGroup(DTP_OPTIONS, (v) => (draft.dtpTo ?? null) === v, (v) => { draft.dtpTo = v; });
  const dtpNote = facets.cars && facets.dtp_known != null && facets.dtp_known < facets.cars
    ? h("div", { class: "sub" }, `Известно у ${nf.format(facets.dtp_known)} из ${nf.format(facets.cars)} машин. `
      + "Если выбрать фильтр, лоты без этих данных не покажутся.") : null;
  const ownersNote = facets.cars && facets.owners_known != null && facets.owners_known < facets.cars
    ? h("div", { class: "sub" }, `Известно у ${nf.format(facets.owners_known)} из ${nf.format(facets.cars)} машин. `
      + "Если выбрать фильтр, лоты без этих данных не покажутся.") : null;
  const regionChips = chipGroup(facets.regions.map((r) => [r.key, regionShort(r.key) === "МО" ? "Московская обл." : regionShort(r.key), r.count]),
    (v) => draft.regions.includes(v), (v) => { draft.regions = toggleIn(draft.regions, v); });
  const tradeChips = chipGroup(TRADES, (v) => draft.trade.includes(v), (v) => { draft.trade = toggleIn(draft.trade, v); });
  draft.kinds = draft.kinds || [];
  const kindChips = chipGroup(KINDS, (v) => draft.kinds.includes(v), (v) => { draft.kinds = toggleIn(draft.kinds, v); });

  // --- характеристики: топливо, коробка, привод (чипы), объём и мощность (слайдеры) ---
  for (const k of ["fuel", "gearbox", "drive", "body"]) draft[k] = draft[k] || [];
  const specChips = (key) => (facets[key] || []).length ? chipGroup(facets[key].map((o) => [o.key, cap(o.key), o.count]),
    (v) => draft[key].includes(v), (v) => { draft[key] = toggleIn(draft[key], v); }) : h("div", { class: "sub" }, "Пока нет данных");
  function rangeSection(title, steps, key, fmt, unit) {
    const idx = (v, dflt) => { const i = v == null ? -1 : steps.indexOf(v); return i >= 0 ? i : dflt; };
    const text = () => draft[key] ? `${rangeText(draft[key], fmt)} ${unit}` : "любая";
    const sec = section(title, text(), dualSlider(steps,
      [idx(draft[key] && draft[key][0], 0), idx(draft[key] && draft[key][1], steps.length - 1)],
      (i, j) => {
        const from = i === 0 ? null : steps[i], to = steps[j];
        draft[key] = from == null && to == null ? null : [from, to];
        sec.val.textContent = text(); refreshCount();
      }));
    return sec;
  }
  const volumeSec = rangeSection("Объём двигателя", VOLUME_STEPS, "volume", litersText, "л");
  const powerSec = rangeSection("Мощность", POWER_STEPS, "power", String, "л.с.");
  const specsNote = facets.cars && facets.specs_known < facets.cars
    ? h("div", { class: "sub" }, `Характеристики известны у ${nf.format(facets.specs_known)} из ${nf.format(facets.cars)} машин. `
      + "Если выбрать фильтр ниже, лоты без них не покажутся.") : null;
  const damageToggle = h("label", { class: "togglerow" },
    h("input", { type: "checkbox", checked: draft.hideDamaged !== false,
      onchange: (e) => { hapticSelect(); draft.hideDamaged = e.target.checked; refreshCount(); } }),
    h("span", {}, h("b", {}, "Скрыть битые"),
      h("span", { class: "sub" }, "Сгоревшие, разобранные, на запчасти — по описанию и фото лота")));

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
    h("div", { class: "fsec" }, h("h3", {}, "Кузов"), specChips("body")),
    h("div", { class: "fsec" }, h("h3", {}, "Двигатель"), specsNote, specChips("fuel")),
    volumeSec.el, powerSec.el,
    h("div", { class: "fsec" }, h("h3", {}, "Коробка"), specChips("gearbox")),
    h("div", { class: "fsec" }, h("h3", {}, "Привод"), specChips("drive")),
    h("div", { class: "fsec" }, h("h3", {}, "Ниже рынка"), gapChips),
    h("div", { class: "fsec" }, h("h3", {}, "Владельцы"), ownersNote, ownersChips),
    h("div", { class: "fsec" }, h("h3", {}, "ДТП"), dtpNote, dtpChips),
    h("div", { class: "fsec" }, h("h3", {}, "Регион"), regionChips),
    h("div", { class: "fsec" }, h("h3", {}, "Форма торгов"), tradeChips),
    h("div", { class: "fsec" }, h("h3", {}, "Тип лота"), kindChips),
    h("div", { class: "fsec" }, damageToggle),
    h("div", { class: "bottombar" }, reset, showBtn)));
  refreshCount();
}

// ---------- заглушка вне Telegram ----------

function showStub() {
  if (WEB) return showLogin(!!webToken());  // веб-версия: вход устарел или токен не подошёл
  document.getElementById("app").replaceChildren(h("div", { class: "stub" },
    h("img", { src: "logo.svg", alt: "" }),
    h("h2", {}, "HonestLot"),
    h("p", {}, "Выгодные лоты с банкротных торгов. Приложение работает внутри Telegram."),
    h("button", { class: "btn", style: { maxWidth: "280px", margin: "16px auto 0", display: "block" }, onclick: () => { location.href = `https://t.me/${BOT}`; } },
      `Открыть @${BOT}`)));
  if (IN_TG) tg.BackButton.hide();
}

// ---------- Pro в веб-версии ----------

// Фильтры и избранное - для подписчиков Pro (веб-версия - с 13.10.2026, мини-апп в Telegram - с
// 15.10.2026, решения владельца), остальным по нажатию - окно «… — в подписке Pro». Признак - поле
// "pro" в /api/me: оно есть, только когда оплата включена (billing.enabled), без него ничего не
// закрываем. Закрыто только в интерфейсе: API эти функции пока не ограничивает (TODO "Разделение
// бесплатного и Pro"). В Telegram кнопка «Оформить Pro» (с 29.10.2026, решение владельца: вести на оплату,
// несмотря на правила Telegram 6.2 и Apple 3.1.1 про оплату мимо Stars) открывает страницу оплаты в браузере
// (tg.openLink) и передаёт в адресе после «#» initData - страница узнаёт того же пользователя без входа
// (pay.js authHeader, подпись initData действует 7 дней).
let proLocked = false;
function payUrl() { return location.origin + "/pay/" + (IN_TG && tg.initData ? "#init=" + encodeURIComponent(tg.initData) : ""); }
function goPro(kind) { track("paywall_go", null, kind); openLink(payUrl()); }
function locked(kind) {
  if (!proLocked) return false;
  showPaywall(kind);
  return true;
}

const PAYWALL = {
  filters: ["Фильтры — в подписке Pro", "Подбирайте лоты по марке и модели, году, цене, пробегу и скидке к рынку."],
  favs: ["Избранное — в подписке Pro", "Сохраняйте лоты и следите за итогами торгов и перевыставлением машин."],
  searches: ["Сохранённые поиски — в подписке Pro", "Сохраните поиск — и бот напишет, как только появится подходящая машина."],
  dtp: ["История ДТП — в подписке Pro", "Даты, места и схемы повреждений из ДТП машины — чтобы понимать, куда был удар."],
};
function showPaywall(kind) {
  haptic();
  track("paywall", null, kind);
  const [title, text] = PAYWALL[kind];
  const close = () => { sheet.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const sheet = h("div", { class: "paywall", onclick: (e) => { if (e.target === sheet) close(); } },
    h("div", { class: "pw-box", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "pw-tag" }, "HonestLot Pro"),
      h("h3", {}, title),
      h("p", {}, text),
      IN_TG
        ? h("button", { class: "btn", onclick: () => { close(); goPro(kind); } }, "Оформить Pro")
        : h("a", { class: "btn", href: "/pro", onclick: () => track("paywall_go", null, kind) }, "Перейти на Pro"),
      h("button", { class: "linkbtn", onclick: close }, "Не сейчас")));
  document.addEventListener("keydown", onKey);
  document.body.append(sheet);
  sheet.querySelector(".btn").focus();
}

// ---------- веб-версия: вход через Telegram ----------

// Кнопка входа - Telegram Login Widget (работает только на домене, заданном боту в @BotFather:
// /setdomain honestlot.ru). Виджет грузится с telegram.org - из части российских сетей без VPN он
// не открывается, тогда показываем подсказку открыть приложение в Telegram.
let loginShown = false;  // несколько запросов сразу получают 401 - экран входа рисуем один раз
function showLogin(expired) {
  if (loginShown) return;
  loginShown = true;
  store.set("web_token", null);
  const box = h("div", { class: "widget" });
  const fallback = h("p", { class: "hint hidden" },
    "Кнопка входа не загрузилась? Сайт Telegram может быть недоступен без VPN. Откройте HonestLot в Telegram: ",
    h("a", { href: `https://t.me/${BOT}`, target: "_blank", rel: "noopener" }, `@${BOT}`), ".");
  window.onTelegramAuth = async (user) => {
    try {
      const r = await fetch("/api/web-login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user, start: new URLSearchParams(location.search).get("startapp") }) });
      if (!r.ok) throw new Error(String(r.status));
      store.set("web_token", (await r.json()).token);
      location.reload();
    } catch {
      toast("Не получилось войти, попробуйте ещё раз");
    }
  };
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://telegram.org/js/telegram-widget.js?22";
  Object.assign(s.dataset, { telegramLogin: BOT, size: "large", radius: "12", onauth: "onTelegramAuth(user)" });
  s.onerror = () => fallback.classList.remove("hidden");
  box.append(s);
  setTimeout(() => { if (!box.querySelector("iframe")) fallback.classList.remove("hidden"); }, 6000);
  document.getElementById("app").replaceChildren(h("div", { class: "stub login" },
    h("img", { src: "logo.svg", alt: "" }),
    h("h2", {}, "HonestLot"),
    h("p", {}, "Автомобили с торгов по банкротству в Москве и Московской области — с рыночной оценкой."),
    h("p", { class: "lead" }, expired ? "Вход устарел — войдите через Telegram ещё раз." : "Авторизуйтесь, чтобы смотреть лоты."),
    box, fallback,
    siteLinks()));
}

function siteLinks(...extra) {
  return h("div", { class: "sitelinks" },
    h("a", { href: "/pro" }, "Подписка и цены"), h("a", { href: "/offer" }, "Оферта"),
    h("a", { href: "/privacy" }, "Персональные данные"), ...extra);
}

// Внизу ленты в веб-версии: страницы сайта и выход.
function webLinks() {
  return WEB ? siteLinks() : null;
}

function logout() { store.set("web_token", null); location.reload(); }

// Имя из токена входа (auth.make_web_token: base64url JSON {id, u, n, exp}) - для шапки сайта.
function webUserName() {
  try {
    const b = webToken().split(".")[0].replace(/-/g, "+").replace(/_/g, "/");
    const p = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(b + "=".repeat((4 - b.length % 4) % 4)), (c) => c.charCodeAt(0))));
    return p.n || (p.u ? "@" + p.u : "");
  } catch { return ""; }
}

// Шапка веб-версии: логотип, разделы (на компьютере вместо нижних вкладок), подписка, имя и выход.
// pro: true - подписчик, false - без подписки (оплата включена), undefined - оплата выключена.
let webNav = null;
function webHeader(pro) {
  webNav = h("nav", { class: "wnav" },
    [["feed", "Лоты"], ...(state.searchesOn ? [["searches", "Поиски"]] : []), ["favs", "Избранное"]].map(([key, label]) =>
      h("button", { "data-tab": key, class: state.tab === key ? "on" : "", onclick: () => selectTab(key) }, label)));
  const name = webUserName();
  return h("header", { class: "webhead" }, h("div", { class: "wh-in" },
    h("button", { class: "wh-brand", "aria-label": "HonestLot — к ленте", onclick: () => selectTab("feed") },
      h("img", { src: "logo.svg", alt: "" }), wordmark()),
    webNav,
    h("div", { class: "wh-right" },
      pro === true ? h("a", { class: "wh-pro", href: "/pay/manage.html", title: "Моя подписка" }, "Pro")
        : pro === false ? h("a", { class: "wh-cta", href: "/pro" }, "Перейти на Pro")
          : h("a", { class: "wh-link", href: "/pro" }, "Подписка"),
      name ? h("span", { class: "wh-user" }, name) : null,
      h("button", { class: "wh-link wh-out", title: "Выйти", "aria-label": "Выйти", onclick: logout }, icon("logout"), h("span", {}, "Выйти")))));
}

// ---------- старт ----------

async function start() {
  // Pro - до того, как построить ленту: без Pro сохранённые раньше фильтры не применяем
  const me = await loadMe();
  proLocked = me.pro === false;
  state.searchesOn = !!me.searches;
  // пришёл по подарочной ссылке автора курса - сервер уже включил Pro, скажем об этом один раз
  if (me.gift) setTimeout(() => toast("Ваша подписка Pro активна", null, 5000), 600);
  // новый пользователь - пробный Pro (с 22.10.2026); при подарке по ссылке хватает сообщения о подарке
  else if (me.trial) setTimeout(() => toast(`Вам открыт Pro на ${me.trial.days} ${plural(me.trial.days, "день", "дня", "дней")} — до ${me.trial.until}`, null, 6000), 600);
  if (proLocked) state.filters = emptyFilters();
  if (WEB) document.getElementById("app").append(webHeader(me.pro));
  document.getElementById("app").append(root, overlay);
  root.append(buildFeed(), searchesEl, favsEl, tabsEl);
  favsEl.classList.add("hidden");
  searchesEl.classList.add("hidden");
  renderTabs();
  // открыли из уведомления (кнопка бота, ссылка в письме, notify.py): ?lot=, ?search=, ?tab=
  const qp = new URLSearchParams(location.search);
  const src = qp.get("src");
  if (src === "notify" || src === "email") track("notify_open", null, src);
  const searchParam = state.searchesOn && !proLocked && /^\d+$/.test(qp.get("search") || "") ? Number(qp.get("search")) : null;
  if (!searchParam) loadFeed(true);
  track("open");
  // открыли по ссылке "Поделиться" (или из уведомления) - сразу экран лота, "Назад" ведёт в ленту
  const sharedId = startLotId() || (/^\d+$/.test(qp.get("lot") || "") ? qp.get("lot") : null);
  // в браузере: основная запись истории - лента «/» без параметров (иначе обновление снова откроет лот), лот
  // поверх неё - своей записью с адресом /?lot=ID (push), «Назад» браузера ведёт в ленту
  if (!IN_TG) history.replaceState(URL_NAV ? { hl: 0 } : null, "", location.pathname + (WEB_FLAG ? "?web" : "") + location.hash);
  if (sharedId) push({ kind: "lot", id: sharedId });
  else if (qp.get("tab") === "favs") selectTab("favs");
  else if (qp.get("tab") === "searches" && state.searchesOn) selectTab("searches");
  if (state.searchesOn && !proLocked) {
    loadSearches().then(() => {
      renderActive();
      const s = searchParam && state.searches.find((x) => x.id === searchParam);
      if (s) openSearch(s); else if (searchParam) loadFeed(true);
    }).catch(() => { if (searchParam) loadFeed(true); });
  }
  try {
    const [facets, favs] = await Promise.all([api("/facets"), api("/favorites")]);
    state.facets = facets;
    renderActive();  // подписи марок в чипах - из фильтров
    state.favIds = new Set(favs.items.map((i) => i.id));
    state.items.forEach((it) => syncHearts(it.id));
  } catch (e) {
    if (e instanceof AuthError) showStub();
  }
}
if (WEB && !webToken()) showLogin(); else start();
