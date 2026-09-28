# -*- coding: utf-8 -*-
r"""
Общие формулы по лоту - ОДНА реализация на всех потребителей:
  - build_lot_selections.py (подборки -> дайджест в канал);
  - miniapp/backend (лента мини-аппа honestlot).

Зачем отдельный модуль: "% below mkt" раньше считался только внутри
build_lot_selections.py. Мини-апп обязан показывать тот же процент по той же
формуле, что и дайджест - иначе один и тот же лот в канале и в приложении
будет "выгоднее" на разное число процентов. Держим формулу здесь, а не
копируем. Модуль без зависимостей (ни gspread, ни config) - его целиком
копирует к себе Docker-образ бэкенда (см. miniapp/backend/Dockerfile).
"""

# Ключевые слова, по которым лот выглядит как повреждённый/неисправный.
# Используются двояко:
#   - build_lot_selections.py исключает такие лоты из топа по выгодности
#     (огромный дисконт у них объясняется состоянием, а не выгодой -
#     Auto.ru оценивает исправный авто того же года/модели);
#   - мини-апп ставит на карточке значок "возможно, повреждён" и пишет на
#     экране лота, какие именно слова нашлись.
# Список - первое приближение по тому, что реально встречалось в title;
# расширяйте по мере обнаружения новых выбросов.
DAMAGE_KEYWORDS = [
    "ДТП", "НЕИСПРАВН", "НЕ НА ХОДУ", "НЕ НАХОДУ", "БИТ", "АВАРИЙН",
    "ГОДНЫЕ ОСТАТКИ", "ГОДНЫЕ ОСТАНКИ", "УТИЛИЗАЦ", "ТРЕБУЕТ РЕМОНТА",
    "ПОСЛЕ ПОЖАРА", "СГОРЕВШ", "ЗАТОПЛЕН", "КОНСТРУКТИВНАЯ ГИБЕЛЬ",
]


def damage_keywords(text):
    """Какие из DAMAGE_KEYWORDS нашлись в тексте (пустой список - ничего)."""
    upper = (text or "").upper()
    return [kw for kw in DAMAGE_KEYWORDS if kw in upper]


def looks_damaged(text):
    return bool(damage_keywords(text))


def gap_percent(price_current, market_low, market_high):
    """% below mkt = (market_mid - price_current) / market_mid * 100, где
    market_mid = (low + high) / 2 - середина вилки Авто.ру.

    Положительное значение - лот дешевле рынка, отрицательное - дороже.
    None, если цена или вилка не заданы, или market_mid <= 0 (защита от
    деления на ноль/мусора) - "нет оценки", а не ноль."""
    if price_current is None or market_low is None or market_high is None:
        return None
    market_mid = (market_low + market_high) / 2
    if market_mid <= 0:
        return None
    return (market_mid - price_current) / market_mid * 100
