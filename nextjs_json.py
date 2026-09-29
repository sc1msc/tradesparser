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
Длинные строковые поля внутри объекта бывают ссылками на отдельный
текстовый чанк - их разворачивает resolve_text_ref().
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


# Длинные строки (название лота, описание, условия) Next.js кладёт не в сам
# объект, а отдельным текстовым чанком "<id>:T<длина в байтах, hex>,<текст>",
# а в объекте оставляет ссылку "$<id>" (например "title": "$80"). Без
# разворачивания в таблицу попадало буквально "$7c" - у лота пропадали
# марка/модель из названия, слова-признаки повреждений и то, что лот
# состоит из нескольких машин.
TEXT_REF_RE = re.compile(r"\$([0-9a-f]+)")


def is_text_ref(value):
    return isinstance(value, str) and TEXT_REF_RE.fullmatch(value.strip()) is not None


def resolve_text_ref(payload, value):
    """
    "$80" -> текст чанка 80 из payload. Не ссылка - значение как есть.
    Ссылка, для которой текстового чанка нет, - None: лучше пустая ячейка,
    чем "$80" в названии лота.
    """
    if not is_text_ref(value):
        return value
    ref_id = TEXT_REF_RE.fullmatch(value.strip()).group(1)
    m = re.search(r"(?<![0-9a-f])" + ref_id + r":T([0-9a-f]+),", payload)
    if not m:
        return None
    length = int(m.group(1), 16)  # длина в БАЙТАХ utf-8, а не в символах
    chunk = payload[m.end():m.end() + length]  # символов не меньше, чем байт
    return chunk.encode("utf-8")[:length].decode("utf-8", errors="ignore")
