# -*- coding: utf-8 -*-
r"""
Юзерпики ботов: монограмма HL (Honest Lot), которую разрезает полоса с
надписью - композиция взята у логотипа канала Honest Dealer (HD), цвета -
фирменные цвета мини-аппа: белый знак на зелёном (#179a50, как logo.svg).
Золотой вариант на чёрном был 01.10.2026 и отклонён - бело-зелёный.
  bot_userpic     - @honestlot_bot, в полосе "HONEST LOT"
  support_userpic - @honestlot_support_bot, в полосе "ПОДДЕРЖКА"

Telegram обрезает аватар в круг - знак держится в центральной части.
Надпись - Montserrat 800 из Google Fonts: PNG рендерится браузером Playwright
(уже стоит для evaluate_autoru_browser.py) с подключённым шрифтом. SVG рядом -
исходник для правок; без установленного Montserrat он покажет запасной шрифт.

Запуск из корня репозитория:  python miniapp/assets/render_userpics.py
"""
import base64
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_CSS = "https://fonts.googleapis.com/css2?family=Montserrat:wght@800&display=block"
BG = "#179a50"  # фирменный зелёный мини-аппа (frontend/logo.svg)
FG = "#ffffff"


def svg(band_text):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" width="640" height="640">
  <!-- Сгенерировано miniapp/assets/render_userpics.py - правьте там. -->
  <defs>
    <mask id="cut">
      <rect width="640" height="640" fill="#fff"/>
      <rect x="0" y="338" width="640" height="64" fill="#000"/>
    </mask>
  </defs>
  <rect width="640" height="640" fill="{BG}"/>
  <g fill="{FG}" mask="url(#cut)">
    <rect x="128" y="168" width="62" height="304"/>
    <rect x="262" y="168" width="62" height="304"/>
    <rect x="128" y="296" width="196" height="42"/>
    <rect x="364" y="168" width="62" height="304"/>
    <rect x="364" y="410" width="148" height="62"/>
  </g>
  <text x="320" y="390" text-anchor="middle" fill="{FG}"
        font-family="Montserrat, Arial Black, sans-serif" font-weight="800"
        font-size="50" letter-spacing="3">{band_text}</text>
</svg>
'''


USERPICS = {"bot_userpic": "HONEST LOT", "support_userpic": "ПОДДЕРЖКА"}


def main(preview_path=None):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 640, "height": 640})
        for name, text in USERPICS.items():
            source = svg(text)
            with open(os.path.join(HERE, f"{name}.svg"), "w", encoding="utf-8", newline="\n") as f:
                f.write(source)
            page.set_content(f"<html><head><link href='{FONT_CSS}' rel='stylesheet'></head>"
                             f"<body style='margin:0;background:{BG}'>{source}</body></html>")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            if not page.evaluate("document.fonts.check('800 50px Montserrat')"):
                print(f"{name}: шрифт Montserrat не загрузился - проверьте интернет")
            page.screenshot(path=os.path.join(HERE, f"{name}.png"), clip={"x": 0, "y": 0, "width": 640, "height": 640})
            print(f"{name}.png готов")
        if preview_path:  # оба аватара в кругах - как их покажет Telegram
            imgs = [base64.b64encode(open(os.path.join(HERE, f"{n}.png"), "rb").read()).decode() for n in USERPICS]
            page.set_viewport_size({"width": 640, "height": 320})
            page.set_content("<html><body style='margin:0;background:#e9edf0;display:flex;gap:60px;"
                             "justify-content:center;align-items:center;height:320px'>" + "".join(
                                 f"<div style='width:220px;height:220px;border-radius:50%;overflow:hidden'>"
                                 f"<img src='data:image/png;base64,{i}' width=220 height=220></div>" for i in imgs)
                             + "</body></html>")
            page.screenshot(path=preview_path)
        browser.close()


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
