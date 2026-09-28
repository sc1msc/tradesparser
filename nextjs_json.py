# -*- coding: utf-8 -*-
"""
Извлечение данных из Next.js SSR-страниц (React Server Components).

Начиная с редизайна, сайт-агрегатор рендерится на Next.js. Реальные данные
(цена, организатор, VIN и т.д.) не всегда лежат прямо в видимой HTML-разметке
(там могут быть пустые <div> под будущую гидратацию) - вместо этого они
встроены в JSON внутри тегов <script>self.__next_f.push([1,"..."])</script>,
которые Next.js использует для передачи данных с сервера на клиент.

Формат каждого push-вызова - валидный JSON-массив [индекс, "строка"], где
строка - это конкатенация "чанков" вида "<id>:<данные>\n<id>:<данные>...".
Нам не нужно разбирать это построчно - достаточно склеить все строки-payload
в один большой текст и найти в нём нужный JSON-объект/массив по ключу
(например "lot":{...} или "initialLots":[...]) с помощью подсчёта скобок.
"""
import re
import json

PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)


def extract_combined_payload(html):
    """Склеивает все текстовые payload'ы из self.__next_f.push(...) в одну строку."""
    parts = []
    for raw in PUSH_RE.findall(html):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def _extract_balanced(text, start_idx, open_ch, close_ch):
    """Вырезает сбалансированный по скобкам фрагмент text[start_idx:...],
    корректно пропуская скобки внутри строковых литералов."""
    depth = 0
    i = start_idx
    in_string = False
    escape = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start_idx:i + 1]
        i += 1
    return None


def find_json_value(text, key, kind="object", start=0):
    """
    Ищет в тексте маркер "<key>": и вытаскивает следующий за ним JSON-объект
    ({...}, kind="object") или массив ([...], kind="array"), с учётом вложенных
    скобок. Возвращает (parsed_value, marker_end_index) или (None, -1),
    если ключ не найден. start - позиция, с которой начинать поиск (удобно
    для поиска СЛЕДУЮЩЕГО вхождения, если в тексте несколько одноимённых
    ключей на разных уровнях вложенности).
    """
    open_ch, close_ch = ("{", "}") if kind == "object" else ("[", "]")
    marker = f'"{key}":{open_ch}'
    idx = text.find(marker, start)
    if idx == -1:
        return None, -1
    brace_start = idx + len(marker) - 1  # позиция самой открывающей скобки
    raw = _extract_balanced(text, brace_start, open_ch, close_ch)
    if raw is None:
        return None, -1
    try:
        return json.loads(raw), idx + len(marker)
    except json.JSONDecodeError:
        return None, -1
