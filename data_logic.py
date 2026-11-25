"""Read-only helpers for the BTC panel. No network, GUI or trading logic here."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOOD_STATUSES = {"usable", "available", "fresh", "healthy", "verified", "complete", "standard"}


def at(data: dict, dotted: str, default=None):
    """Safe lookup for keys in nested JSON; dot is a separator, not a Python expression."""
    item: Any = data
    parts = dotted.split(".")
    index = 0
    while index < len(parts):
        if not isinstance(item, dict):
            return default
        # A JSON key can itself contain a dot (e.g. "0.2", "spot_cvd.original_five.24h").
        # Prefer the longest key actually present rather than splitting it apart.
        for end in range(len(parts), index, -1):
            candidate = ".".join(parts[index:end])
            if candidate in item:
                item = item[candidate]
                index = end
                break
        else:
            return default
    return item


def parse_utc(text: str | None) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return None
        return instant.astimezone(timezone.utc)
    except ValueError:
        return None


def hours_since(text: str | None, now: datetime | None = None) -> float | None:
    timestamp = parse_utc(text)
    if timestamp is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - timestamp).total_seconds() / 3600)


def validate_brief(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON должен быть объектом")
    if not parse_utc(data.get("as_of_utc")):
        raise ValueError("Нет корректного as_of_utc с часовым поясом")
    if not isinstance(data.get("metric_quality"), dict):
        raise ValueError("В файле отсутствует блок metric_quality")
    if not isinstance(data.get("btc_technicals"), dict):
        raise ValueError("В файле отсутствует блок btc_technicals")
    return data


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as fh:
        return validate_brief(json.load(fh))


def is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def formatted(value: Any, unit: str = "number", decimals: int = 2) -> str:
    """Format only; never fill missing numeric values with zero."""
    if value is None or not is_real_number(value):
        return "—"
    if unit == "usd":
        return f"${value:,.{decimals}f}".replace(",", "\u202f")
    if unit == "usd0":
        return f"${value:,.0f}".replace(",", "\u202f")
    if unit == "usd_m":
        return f"{_sign(value)}${abs(value) / 1_000_000:,.1f} млн"
    if unit == "usd_b":
        return f"{_sign(value)}${abs(value) / 1_000_000_000:,.2f} млрд"
    if unit == "usd_t":
        return f"${value / 1_000_000_000_000:,.2f} трлн"
    if unit == "pct":
        return f"{value:+,.2f}%"
    if unit == "pct_abs":
        return f"{value:,.2f}%"
    if unit == "funding_8h":
        return f"{value * 100:+.4f}%"
    if unit == "btc":
        return f"{value:,.0f} BTC".replace(",", "\u202f")
    if unit == "btc_signed":
        return f"{value:+,.0f} BTC".replace(",", "\u202f")
    if unit == "ratio":
        return f"{value:,.3f}"
    if unit == "share":
        return f"{value * 100:,.0f}%"
    if unit == "pp":
        return f"{value:+,.2f} п.п."
    if unit == "int":
        return f"{value:,.0f}".replace(",", "\u202f")
    return f"{value:,.{decimals}f}"


def _sign(value: float) -> str:
    return "−" if value < 0 else ""


def metric_status(data: dict, quality_key: str | None, source_status: str | None = None) -> tuple[str, str]:
    """Authoritative metric_quality.checks gates a value; source status is a second gate.

    Returns (status, reason). 'unchecked' is not considered verified.
    """
    check = at(data, f"metric_quality.checks.{quality_key}") if quality_key else None
    q_status = (check or {}).get("status") if isinstance(check, dict) else None
    reason = (check or {}).get("reason") if isinstance(check, dict) else None
    if q_status and q_status not in GOOD_STATUSES:
        return str(q_status), str(reason or "Отклонено проверкой качества агрегатора")
    if source_status and source_status not in GOOD_STATUSES:
        return source_status, str(reason or "Недоступно по статусу первичных данных")
    if q_status:
        return "usable", ""
    if source_status in GOOD_STATUSES:
        return "usable", "Проверено на уровне источника; отдельная проверка metric_quality не найдена"
    return "unchecked", "Нет отдельной проверки качества; значение требует осторожности"


def metric_value(data: dict, path: str, quality_key: str | None = None,
                 source_status: str | None = None) -> dict:
    value = at(data, path)
    status, reason = metric_status(data, quality_key, source_status)
    if not is_real_number(value):
        # Keep the more specific source verdict, even if the numerical field is null.
        missing_status = status if status not in {"usable", "unchecked"} else ("missing" if value is None else "invalid")
        return {"value": None, "status": missing_status,
                "reason": reason or ("Число отсутствует" if value is None else "Некорректное число"), "path": path}
    if status not in {"usable", "unchecked"}:
        return {"value": None, "status": status, "reason": reason, "path": path}
    return {"value": value, "status": status, "reason": reason, "path": path}


def cvd_value(data: dict, window: str) -> dict:
    path = f"spot_cvd.windows.{window}.net_usd_approx"
    complete = at(data, f"spot_cvd.windows.{window}.complete")
    result = metric_value(data, path, f"spot_cvd.original_five.{window}", "usable" if complete else "incomplete")
    if not complete:
        result["value"] = None
        result["status"] = "incomplete"
        result["reason"] = "Неполная фиксированная пятёрка бирж; значение не подменено другим составом"
    return result


def orderbook_rows(data: dict, band: str, market_type: str = "Все") -> list[dict]:
    venues = at(data, "orderbook_live.venues", {})
    if not isinstance(venues, dict):
        return []
    rows = []
    for venue, payload in venues.items():
        if not isinstance(payload, dict):
            continue
        market = "Спот" if venue.endswith("_spot") else "Бессрочные"
        if market_type != "Все" and market_type != market:
            continue
        b = at(payload, f"bands.{band}")
        q, reason = metric_status(data, f"live_depth.{venue}.{band}")
        ok = isinstance(b, dict) and b.get("complete") is True and q == "usable"
        bid = b.get("bid_usd") if isinstance(b, dict) else None
        ask = b.get("ask_usd") if isinstance(b, dict) else None
        if not (is_real_number(bid) and is_real_number(ask)):
            ok = False
        rows.append({
            "Биржа": venue, "Рынок": market,
            "Спрос, USD": bid if ok else None,
            "Предложение, USD": ask if ok else None,
            "Доля заявок на покупку": (bid / (bid + ask)) if ok and bid + ask > 0 else None,
            "Статус": "usable" if ok else (q if q != "usable" else "incomplete"),
            "Причина": "" if ok else (reason or "Неполная глубина или отсутствует значение"),
        })
    return rows


def source_rows(data: dict) -> list[dict]:
    rows = []
    for name, item in at(data, "collector_watchdog.sources", {}).items():
        if not isinstance(item, dict):
            continue
        rows.append({
            "Сборщик": name,
            "Статус": item.get("status", "unknown"),
            "Возраст файла, ч (на момент проверки)": item.get("file_age_h"),
            "Причина": item.get("reason") or "",
            "Пробелы покрытия": "; ".join(str(a) for a in item.get("coverage_gaps", [])[:3]),
        })
    return rows


def quality_rows(data: dict) -> list[dict]:
    checks = at(data, "metric_quality.checks", {})
    return [{
        "Метрика": key,
        "Статус": v.get("status", "unknown"),
        "Причина": v.get("reason") or "",
        "Наблюдение UTC": v.get("observed_at") or "",
        "Охват": v.get("scope") or "",
    } for key, v in checks.items() if isinstance(v, dict)]


# ---------------------------------------------------------------------------
# Derived values: computed only when every input passed the quality gate.
# ---------------------------------------------------------------------------

def pct_distance(price_info: dict, level_info: dict) -> dict:
    """How far the price is from a level, in % of the level. Null unless both are usable."""
    price, level = price_info.get("value"), level_info.get("value")
    if not (is_real_number(price) and is_real_number(level)) or level == 0:
        bad = price_info if price_info.get("value") is None else level_info
        return {"value": None, "status": bad.get("status", "missing"),
                "reason": bad.get("reason") or "Нет одного из значений для расчёта"}
    return {"value": (price / level - 1) * 100, "status": "usable", "reason": ""}


def average_usable(infos: list[dict]) -> dict:
    """Simple mean of usable values. Null if any input is unusable (no silent subset)."""
    values = [i.get("value") for i in infos]
    if not infos or not all(is_real_number(v) for v in values):
        return {"value": None, "status": "incomplete",
                "reason": "Не у всех бирж есть проверенное значение — среднее не считается"}
    return {"value": sum(values) / len(values), "status": "usable", "reason": ""}


# ---------------------------------------------------------------------------
# Human-readable labels for aggregator codes. Unknown codes are shown as-is.
# ---------------------------------------------------------------------------

LABELS = {
    "trend": {"up": "восходящий", "bullish": "восходящий", "down": "нисходящий",
              "bearish": "нисходящий", "mixed": "смешанный", "sideways": "боковой"},
    "swings": {"HH_HL": "растущие максимумы и минимумы", "LH_LL": "снижающиеся максимумы и минимумы",
               "LH_HL": "сужение диапазона", "HH_LL": "расширение диапазона"},
    "breakout20": {"within_prev20_range": "внутри диапазона 20 дней",
                   "above_prev20_high": "выше максимума 20 дней",
                   "below_prev20_low": "ниже минимума 20 дней"},
    "health": {"healthy": "в норме", "ok": "в норме", "degraded": "частично", "stale": "устарело",
               "failed": "сбой", "error": "ошибка", "unknown": "неизвестно"},
    "status": {"usable": "проверено", "unchecked": "без отдельной проверки", "missing": "нет значения",
               "incomplete": "неполно", "stale": "устарело", "unavailable": "недоступно",
               "invalid": "ошибка", "unverified": "не подтверждено", "not_comparable": "несопоставимо",
               "missing_or_delayed": "задерживается", "reference_only_delayed": "только справочно"},
}


def label(kind: str, code: Any) -> str:
    if code is None or code == "":
        return "—"
    return LABELS.get(kind, {}).get(str(code), str(code).replace("_", " "))


def status_kind(status: str) -> str:
    """Three visual classes: good / neutral / bad."""
    if status == "usable":
        return "good"
    if status == "unchecked":
        return "neutral"
    return "bad"


# ---------------------------------------------------------------------------
# Time formatting in the user's local zone.
# ---------------------------------------------------------------------------

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def local_tz(name: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # Windows without the tzdata package: fall back to a fixed offset
        from datetime import timedelta
        return timezone(timedelta(hours=7), "UTC+7")


def human_age(hours: float | None) -> str:
    if hours is None:
        return "возраст неизвестен"
    minutes = hours * 60
    if minutes < 1.5:
        return "только что"
    if minutes < 90:
        return f"{minutes:.0f} мин назад"
    if hours < 48:
        return f"{hours:.0f} ч назад"
    return f"{hours / 24:.0f} дн назад"


def human_time(text: Any, tz, now: datetime | None = None) -> str:
    """'23 ноя 22:00 · 2 ч назад' for timestamps, '21 ноя' for plain dates."""
    if not isinstance(text, str) or not text:
        return ""
    instant = parse_utc(text)
    if instant is None:
        # Plain calendar date such as '2026-11-21' (daily data, no clock time).
        try:
            day = datetime.strptime(text[:10], "%Y-%m-%d")
            return f"данные за {day.day} {MONTHS[day.month - 1]}"
        except ValueError:
            return text
    local = instant.astimezone(tz)
    return f"{local.day} {MONTHS[local.month - 1]} {local:%H:%M} · {human_age(hours_since(text, now))}"
