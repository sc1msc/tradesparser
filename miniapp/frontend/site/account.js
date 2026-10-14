// Блок «аккаунт» в шапке страниц сайта (/pro, /offer, ...) и оплаты (/pay/...): кто вошёл и «Выйти».
// Вход общий с веб-версией honestlot.ru: токен в localStorage hl_web_token (auth.make_web_token,
// base64url JSON {id, u, n, exp}). На страницах оплаты бывает ещё вход виджетом Telegram только
// для этой вкладки (sessionStorage hl_tglogin, см. pay/pay.js). Подпись токена проверяет сервер,
// здесь только показываем имя. Не вошёл - ссылка «Войти» ведёт в веб-версию.
// «Моя подписка» - путь к отмене подписки и отвязке карты (этого ждёт ЮKassa для автоплатежей).
(function () {
  function decode(b64) {
    const s = b64.replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(s + "=".repeat((4 - s.length % 4) % 4));
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
  }
  function who() {
    try {
      const t = JSON.parse(localStorage.getItem("hl_web_token") || "null");
      if (t) {
        const p = decode(t.split(".")[0]);
        if (!p.exp || p.exp * 1000 > Date.now()) return p.n || (p.u ? "@" + p.u : "аккаунт Telegram");
      }
    } catch { /* приватный режим, битый токен */ }
    try {
      const s = sessionStorage.getItem("hl_tglogin");
      if (s) {
        const u = JSON.parse(decodeURIComponent(escape(atob(s))));
        return u.first_name || (u.username ? "@" + u.username : "аккаунт Telegram");
      }
    } catch { /* */ }
    return null;
  }
  function logout() {
    try { localStorage.removeItem("hl_web_token"); } catch { /* */ }
    try { sessionStorage.removeItem("hl_tglogin"); } catch { /* */ }
    // ссылка из письма (#link=) тоже входит - после выхода открываем страницу без неё
    location.replace(location.pathname);
  }
  function render() {
    const box = document.getElementById("acct");
    if (!box) return;
    const name = who();
    box.replaceChildren();
    if (name) {
      const n = document.createElement("span");
      n.className = "acct-name";
      n.title = "Вы вошли через Telegram";
      n.textContent = name;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "acct-out";
      b.title = "Выйти";
      b.setAttribute("aria-label", "Выйти");
      b.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg><span>Выйти</span>';
      b.onclick = logout;
      if (!location.pathname.endsWith("/manage.html")) {
        const m = document.createElement("a");
        m.className = "acct-sub";
        m.href = "/pay/manage.html";
        m.textContent = "Моя подписка";
        box.append(m);
      }
      box.append(n, b);
    } else if (box.dataset.guest !== "none") {
      const a = document.createElement("a");
      a.className = "acct-in";
      a.href = "/";
      a.textContent = "Войти";
      box.append(a);
    }
  }
  window.hlAccountRefresh = render;  // pay.js зовёт после входа виджетом
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
