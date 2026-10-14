// Общее для страниц подписки (honestlot.ru/pay, см. billing.py): кто пользователь и запросы к API.
// Пользователь узнаётся (по порядку): #link=<токен> из письма, #init=<initData> из мини-аппа,
// токен веб-версии honestlot.ru (localStorage hl_web_token),
// вход через Telegram Login Widget (данные хранятся в sessionStorage этой вкладки).
export const BOT = "honestlot_bot";

export function authHeader() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("link")) return "link " + h.get("link");
  if (h.get("init")) return "tma " + h.get("init");
  // уже вошёл в веб-версию honestlot.ru (app.js, токен на 30 дней) - тот же вход
  try { const w = JSON.parse(localStorage.getItem("hl_web_token") || "null"); if (w) return "web " + w; } catch { /* */ }
  try { const s = sessionStorage.getItem("hl_tglogin"); if (s) return "tglogin " + s; } catch { /* приватный режим */ }
  return "";
}

export async function api(path, opts = {}) {
  const r = await fetch("/api/pay" + path, { ...opts, headers: { Authorization: authHeader(), ...(opts.body ? { "Content-Type": "application/json" } : {}) } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.detail || `Ошибка ${r.status}`), { status: r.status });
  return data;
}

// Кнопка "Войти через Telegram" (виджет работает только на домене, заданном боту в @BotFather).
export function showLogin(box, onDone) {
  window.onTelegramAuth = (user) => {
    try { sessionStorage.setItem("hl_tglogin", btoa(unescape(encodeURIComponent(JSON.stringify(user))))); } catch { /* */ }
    window.hlAccountRefresh?.();  // site/account.js: показать имя и «Выйти»
    onDone();
  };
  box.innerHTML = '<p>Чтобы оформить или изменить подписку, войдите через Telegram - тем же аккаунтом, что в мини-аппе HonestLot.</p>';
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://telegram.org/js/telegram-widget.js?22";
  s.dataset.telegramLogin = BOT;
  s.dataset.size = "large";
  s.dataset.radius = "10";
  s.dataset.onauth = "onTelegramAuth(user)";
  box.append(s);
  box.classList.remove("hidden");
}

export const rub = (n) => new Intl.NumberFormat("ru-RU").format(n) + " ₽";
export const date = (iso) => new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "numeric", month: "long", year: "numeric" }).format(new Date(iso)).replace(/ г\.$/, "");
export const months = (m) => (m === 1 ? "месяц" : m === 12 ? "12 месяцев" : `${m} месяца`);
