# -*- coding: utf-8 -*-
"""
Общий реестр подборок ("срезов") лотов - единственное место, где
сопоставлены ключ подборки, лист в таблице и тексты для дайджеста.

Читают:
  - build_lot_selections.py - какие листы вообще нужно строить
    (сама логика фильтрации - в build_lot_selections.py, в виде обычных
    функций типа build_top_gap; критерии слишком разные - пороги,
    сортировка, исключение по ключевым словам, OR по моделям - чтобы
    зажимать их в единый декларативный формат, поэтому здесь хранятся
    только МЕТАДАННЫЕ подборки, а не сами критерии)
  - send_digest.py - из какого листа брать лоты и что писать в заголовок
    Telegraph-страницы/вступительный абзац

Чтобы добавить новую подборку:
  1) написать функцию-фильтр build_XXX в build_lot_selections.py
  2) прописать её в BUILDERS там же
  3) добавить сюда запись с тем же "key"
"""

SELECTIONS = [
    {
        "key": "top_gap",
        "sheet": "lots_top_gap",
        "title": "Топ по дисконту",
        "digest_intro": "с наибольшей разницей между ценой торгов и рыночной оценкой",
    },
    {
        "key": "budget_1m",
        "sheet": "lots_budget_1m",
        "title": "Бюджетные варианты до 1 млн",
        "digest_intro": "дешевле 1 000 000 ₽",
    },
    {
        "key": "one_owner",
        "sheet": "lots_one_owner",
        "title": "Один владелец",
        "digest_intro": "с одним предыдущим владельцем (по данным Auto.ru)",
    },
    {
        "key": "heavy_luxury",
        "sheet": "lots_heavy_luxury",
        "title": "Премиум-сегмент",
        "digest_intro": "дороже 5 000 000 ₽",
    },
    {
        "key": "polo_rio_solyaris",
        "sheet": "lots_polo_rio_solyaris",
        "title": "Polo / Rio / Solaris",
        "digest_intro": "Polo, Rio и Solaris не старше 10 лет",
    },
]


def get(key):
    for item in SELECTIONS:
        if item["key"] == key:
            return item
    return None


def prompt_choice():
    """Печатает список подборок и спрашивает у пользователя, какую взять.
    Возвращает выбранный элемент SELECTIONS (dict) или None, если ввод
    некорректный после повторной попытки."""
    print("\nДоступные подборки:")
    for i, item in enumerate(SELECTIONS, 1):
        print(f"  [{i}] {item['title']} (лист {item['sheet']})")

    raw = input(f"\nНомер подборки (Enter - [1] {SELECTIONS[0]['title']}): ").strip()
    if not raw:
        return SELECTIONS[0]
    if raw.isdigit() and 1 <= int(raw) <= len(SELECTIONS):
        return SELECTIONS[int(raw) - 1]

    print("Не понял номер, беру подборку по умолчанию.")
    return SELECTIONS[0]
