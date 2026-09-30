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
import re

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


# ---------- тип лота: машина / мультилот / право требования / доля ----------

# Не всё, что продаётся в разделе "легковой транспорт", - это одна машина:
#   - право требования (ПРАВО ТРЕБОВАНИЯ передать ВАЗ 21013, к Иванову о
#     передаче ТС, исполнительный лист об истребовании) - покупатель получает
#     не машину, а иск; цена и "% ниже рынка" бессмысленны;
#   - доля (3/4 доли автомобиля) - то же;
#   - мультилот (несколько машин одним лотом: лот 7178974 - 17 Solaris за
#     6,27 млн давал "-510%") - оценка Авто.ру одной машины к цене лота
#     отношения не имеет.
# Решение пользователя (30.09.2026): права требования и доли исключаются
# отовсюду (срез, подборки, дайджест, мини-апп), мультилоты остаются
# отдельной группой без оценки и процента.
LOT_CAR = "car"
LOT_MULTILOT = "multilot"
LOT_RIGHTS = "rights"
LOT_SHARE = "share"
EXCLUDED_KINDS = {LOT_RIGHTS, LOT_SHARE}

_RIGHTS_RE = re.compile(r"ПРАВ[АО]?\s+ТРЕБОВАНИ|ДЕБИТОРСК|УСТУПК[АИ]\s+ПРАВ")
# "3/4 доли", "1/2 доля", "доля в праве". Не путать с "ДОЛЖНИК".
_SHARE_RE = re.compile(r"\d+\s*/\s*\d+\s*(ДОЛ[ЯИЮ]|ЧАСТ)|ДОЛ[ЯИЮ]\s+В\s+ПРАВЕ")
_VIN_RE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")
# Перед номером кузова/шасси/рамы стоит метка - это та же машина, не вторая
# (у Mazda/Volvo номер кузова отличается от VIN, но тоже 17 знаков).
_BODY_LABEL_RE = re.compile(r"(КУЗОВ|ШАССИ|РАМ[АЫ]|КАБИН)[^A-Z0-9]{0,30}$")


def lot_vins(text):
    """Разные VIN в тексте лота - без номеров кузова/шасси/рамы и без чисто
    цифровых 17-значных номеров (номер уголовного дела и т.п.)."""
    upper = (text or "").upper()
    vins = []
    for m in _VIN_RE.finditer(upper):
        vin = m.group(0)
        if vin.isdigit() or _BODY_LABEL_RE.search(upper[max(0, m.start() - 40):m.start()]):
            continue
        if vin not in vins:
            vins.append(vin)
    return vins


def lot_kind(text):
    """Тип лота по тексту (title + description): LOT_RIGHTS / LOT_SHARE /
    LOT_MULTILOT / LOT_CAR. Проверено на листе lots 01.10.2026: 13 прав
    требования и 1 доля находятся почти всегда по title; мультилот - два и
    больше разных VIN (лоты 7178974 - 17 VIN, 7219980 - второй VIN только в
    описании). Нумерацию "2." как признак не используем - она часто
    встречается в правилах осмотра, а не в перечне машин."""
    upper = (text or "").upper()
    if _RIGHTS_RE.search(upper):
        return LOT_RIGHTS
    if _SHARE_RE.search(upper):
        return LOT_SHARE
    if len(lot_vins(upper)) >= 2:
        return LOT_MULTILOT
    return LOT_CAR
