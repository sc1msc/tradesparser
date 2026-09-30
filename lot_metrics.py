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


# ---------- правдоподобие пробега ----------

# Пробег больше этого - почти наверняка ошибка источника, а не реальная
# машина (лот 7147717, Renault Logan 2007: TRONK отдал показание
# 2 224 050 км). Такой пробег считаем ОТСУТСТВУЮЩИМ - оценка Авто.ру идёт
# по году выпуска, как у лотов без пробега вообще. Порог по году
# (км в год) сознательно не ставим: такси/каршеринг набирают много.
MAX_PLAUSIBLE_MILEAGE_KM = 1_000_000


def plausible_mileage(km):
    """Пробег, если он правдоподобен, иначе None (0 и отрицательные - тоже
    "нет пробега")."""
    if km is None:
        return None
    try:
        km = int(round(float(str(km).replace(",", "."))))
    except ValueError:
        return None
    return km if 0 < km <= MAX_PLAUSIBLE_MILEAGE_KM else None


# ---------- точность оценки Авто.ру ----------

# Авто.ру (getStatsPredictByCarIdentifier) вместе с вилкой цены отдаёт
# autoru.uncertainty_percent - свою оценку погрешности прогноза (на сайте
# она не показывается, только в JSON; формула не опубликована). Чем она
# выше, тем дальше наш "% below mkt" уходит от нуля: у 262 из 788 оценок
# (ревью 29.09) она 90-100%, и "выгода" там часто - от неточной оценки, а
# не от цены. Такие лоты НЕ убираем из подборок (решение пользователя),
# а помечаем - пусть читатель сам решает. Статус "ambiguous" (Авто.ру не
# определил машину по VIN однозначно) - тоже неточная оценка.
UNCERTAIN_ESTIMATE_PERCENT = 90
UNCERTAIN_NOTE = "оценка может быть неточной"


def estimate_is_uncertain(uncertainty_percent, autoru_status=None):
    if (autoru_status or "").strip() == "ambiguous":
        return True
    try:
        return float(str(uncertainty_percent).replace(",", ".")) >= UNCERTAIN_ESTIMATE_PERCENT
    except (TypeError, ValueError):
        return False
