"""Local read-only BTC market dashboard. Run with: streamlit run app.py"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from history_page import show_history, load_history, collect_rolling, render_history_quality

from data_logic import (
    at, average_usable, cvd_value, formatted, hours_since, human_age, human_time, is_real_number,
    label, local_tz, metric_status, metric_value, orderbook_rows, pct_distance, quality_rows, read_json,
    source_rows, status_kind, validate_brief,
)

# ---------------------------------------------------------------------------
# Settings you may want to change
# ---------------------------------------------------------------------------
LOCAL_TZ_NAME = "Asia/Tomsk"          # часовой пояс для отображения времени
REFRESH_SECONDS = 180                  # как часто перерисовывать экран
SOURCE_URL = "https://raw.githubusercontent.com/kh827y/btc-market-data/main/btc-monitor/data/brief.json"
REPO_URL = "https://github.com/kh827y/btc-market-data"

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "last_good.json"
TZ = local_tz(LOCAL_TZ_NAME)

st.set_page_config(page_title="BTC Market Panel", page_icon="₿", layout="wide",
                   initial_sidebar_state="expanded")

CSS = """
<style>
.block-container{padding-top:1.4rem;padding-bottom:3rem;max-width:1500px}
h1,h2,h3{letter-spacing:-.02em}
h3{margin-top:.6rem}
.grid{display:grid;grid-template-columns:repeat(var(--cols),minmax(0,1fr));gap:12px;margin:6px 0 22px}
@media (max-width:1100px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card{background:#121c27;border:1px solid #213040;border-radius:12px;padding:14px 16px 12px;min-height:122px;display:flex;flex-direction:column;gap:3px}
.card .t{font-size:.8rem;color:#8ea0b2;line-height:1.3}
.card .v{font-size:1.5rem;font-weight:600;color:#e8eef5;font-variant-numeric:tabular-nums;line-height:1.25;margin-top:2px}
.card .v.up{color:#33c9a4}.card .v.down{color:#f07f6c}
.card.bad .v{color:#5f7184}
.card .s{font-size:.84rem;color:#a7b5c4;line-height:1.35}
.card .s.up{color:#33c9a4}.card .s.down{color:#f07f6c}
.card .f{margin-top:auto;padding-top:8px;font-size:.74rem;color:#6d8194;display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;flex:none}
.dot.good{background:#33c9a4}.dot.neutral{background:#7d8fa1}.dot.bad{background:#e3a04f}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 18px}
.pill{font-size:.8rem;padding:5px 10px;border-radius:999px;border:1px solid #2a3a4c;color:#b8c5d2;background:#121c27}
.pill b{font-weight:600;color:#e8eef5}
.pill.good{border-color:#1f6b59;color:#7fdcc2}.pill.bad{border-color:#7a5524;color:#f0c07c}
.note{font-size:.88rem;color:#8ea0b2;margin:-.35rem 0 .7rem}
.ladder{border:1px solid #213040;border-radius:12px;overflow:hidden;margin:6px 0 18px}
.lrow{display:grid;grid-template-columns:1fr 130px 110px;padding:9px 16px;border-top:1px solid #1a2633;font-size:.9rem;color:#c3cfdb;font-variant-numeric:tabular-nums}
.lrow:first-child{border-top:none}
.lrow .d{text-align:right;color:#8ea0b2}.lrow .p{text-align:right}
.lrow.now{background:#16314a;color:#fff;font-weight:600}
.lrow .tag{font-size:.75rem;color:#6d8194;margin-left:6px}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120, show_spinner=False)
def fetch_remote() -> dict:
    req = Request(SOURCE_URL, headers={"User-Agent": "btc-market-panel/1.1", "Cache-Control": "no-cache"})
    with urlopen(req, timeout=16) as response:
        raw = response.read(5_000_000)
    parsed = validate_brief(json.loads(raw.decode("utf-8-sig")))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE.with_suffix(".tmp")
    temp.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    temp.replace(CACHE)
    return parsed


def load(source: str, local_path: str) -> tuple[dict | None, str, str | None]:
    if source == "Локальный JSON":
        try:
            return read_json(Path(local_path).expanduser()), "локальный файл", None
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return None, "локальный файл", str(exc)
    try:
        return fetch_remote(), "GitHub", None
    except Exception as exc:  # network errors, HTTP errors, bad JSON
        if CACHE.exists():
            try:
                return read_json(CACHE), "сохранённая копия", str(exc)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return None, "GitHub", f"Не получилось скачать brief.json: {exc}"


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------

def mv(data: dict, path: str, quality: str | None = None, source_status: str | None = None) -> dict:
    return metric_value(data, path, quality, source_status)


def onchain(data: dict, group: str, name: str) -> dict:
    """Onchain items carry their own status; the metric_quality check is the main gate."""
    base = f"onchain.{group}.{name}"
    info = metric_value(data, f"{base}.value", base, at(data, f"{base}.status"))
    info["date"] = at(data, f"{base}.date")
    return info


def tone(value, invert: bool = False) -> str:
    if not is_real_number(value) or value == 0:
        return ""
    positive = value > 0
    if invert:
        positive = not positive
    return "up" if positive else "down"


def card(title: str, info: dict, unit: str = "number", sub: str = "", sub_tone: str = "",
         when: str | None = None, value_tone: str = "", display: str | None = None,
         hint: str = "") -> str:
    status = info.get("status", "missing")
    kind = status_kind(status)
    value = display if display is not None else formatted(info.get("value"), unit)
    if info.get("value") is None and display is None:
        value = "—"
    reason = info.get("reason") or ""
    footer_bits = []
    if kind != "good":
        footer_bits.append(label("status", status))
    if when:
        footer_bits.append(when)
    footer = " · ".join(footer_bits) or "проверено"
    tooltip = escape(reason or hint, quote=True)
    sub_html = f'<div class="s {sub_tone}">{escape(sub)}</div>' if sub else ""
    if kind == "bad" and reason and not sub:
        sub_html = f'<div class="s">{escape(reason[:90])}</div>'
    return (f'<div class="card {kind}" title="{tooltip}"><div class="t">{escape(title)}</div>'
            f'<div class="v {value_tone if kind == "good" else ""}">{escape(value)}</div>{sub_html}'
            f'<div class="f"><span class="dot {kind}"></span>{escape(footer)}</div></div>')


def grid(cards: list[str], cols: int = 4) -> None:
    st.markdown(f'<div class="grid" style="--cols:{cols}">{"".join(cards)}</div>', unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    st.subheader(title)
    if note:
        st.markdown(f'<div class="note">{escape(note)}</div>', unsafe_allow_html=True)


def when(data: dict, path: str) -> str:
    return human_time(at(data, path), TZ)


def table(df: pd.DataFrame, **kwargs) -> None:
    """st.dataframe across Streamlit versions (use_container_width was replaced by width)."""
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kwargs)
    except TypeError:
        st.dataframe(df, hide_index=True, use_container_width=True, **kwargs)


def chart(fig) -> None:
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


VENUE_NAMES = {"binance": "Binance", "bybit": "Bybit", "okx": "OKX", "bitget": "Bitget",
               "coinbase": "Coinbase", "gate": "Gate", "kraken": "Kraken"}


def venue_name(code: str) -> str:
    base, _, rest = code.partition("_")
    market = "спот" if rest == "spot" else "бессрочный"
    return f"{VENUE_NAMES.get(base, base.title())} · {market}"


# Common values used on several pages -------------------------------------------------

def price_info(data: dict) -> dict:
    return mv(data, "btc_technicals.latest_spot_price_usdt", "price.live_spot_quote")


def closed(data: dict, path: str) -> dict:
    return mv(data, f"btc_technicals.{path}", "price.closed_daily_weekly")


def funding_infos(data: dict) -> list[dict]:
    return [mv(data, f"derivatives.funding_settled.{n}.rate_8h", f"derivatives.funding_8h.{n}")
            for n in ("Binance", "Bybit", "OKX")]


def distance_text(dist: dict, what: str) -> tuple[str, str]:
    v = dist.get("value")
    if not is_real_number(v):
        return "", ""
    side = "выше" if v >= 0 else "ниже"
    return f"цена на {abs(v):.1f}% {side} {what}", tone(v)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def header(data: dict, source: str) -> None:
    st.title("₿ BTC Market Panel")
    age = hours_since(data.get("as_of_utc"))
    if age is None:
        snap = '<span class="pill bad">Возраст снимка неизвестен</span>'
    else:
        cls = "good" if age < 1.5 else "bad"
        snap = f'<span class="pill {cls}">Снимок: <b>{escape(human_time(data.get("as_of_utc"), TZ))}</b></span>'
    wd = at(data, "collector_watchdog.status", "unknown")
    wd_cls = "good" if wd in ("healthy", "ok") else "bad"
    counts = at(data, "metric_quality.status_counts", {}) or {}
    total = at(data, "metric_quality.metrics_checked")
    usable = counts.get("usable") if isinstance(counts, dict) else None
    q = f"{usable} из {total}" if usable is not None and total else "—"
    pills = [snap,
             f'<span class="pill {wd_cls}">Сборщики: <b>{escape(label("health", wd))}</b></span>',
             f'<span class="pill">Проверенных метрик: <b>{escape(q)}</b></span>',
             f'<span class="pill">Источник: <b>{escape(source)}</b></span>']
    st.markdown(f'<div class="pills">{"".join(pills)}</div>', unsafe_allow_html=True)
    if age is not None and age > 1.5:
        st.warning(f"Снимок агрегатора обновлялся {human_age(age)}. Не считай эти цифры текущим состоянием рынка.")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def overview(data: dict) -> None:
    price = price_info(data)
    d1 = closed(data, "daily_change_pct.1d")
    ma200 = closed(data, "daily_ma.ma200")
    sth = onchain(data, "lth_sth_bitview", "sth_realized_price_150d")
    rsi = closed(data, "daily_rsi14_wilder")

    dist_ma = pct_distance(price, ma200)
    dist_sth = pct_distance(price, sth)
    rsi_v = rsi.get("value")
    rsi_zone = ("" if not is_real_number(rsi_v) else "зона перепроданности" if rsi_v < 30
                else "зона перекупленности" if rsi_v > 70 else "нейтральная зона")

    section("Цена и положение", "Binance BTCUSDT spot. Изменения и индикаторы — по закрытым дневным свечам UTC.")
    grid([
        card("BTC · спот", price, "usd0", sub=f"{formatted(d1.get('value'), 'pct')} за закрытые сутки",
             sub_tone=tone(d1.get("value")), when=when(data, "btc_technicals.latest_spot_observed_utc")),
        card("Цена относительно MA200 (день)", dist_ma, "pct", value_tone=tone(dist_ma.get("value")),
             sub=f"MA200 = {formatted(ma200.get('value'), 'usd0')}"),
        card("Цена относительно себестоимости STH", dist_sth, "pct", value_tone=tone(dist_sth.get("value")),
             sub=f"STH (<150 дн) = {formatted(sth.get('value'), 'usd0')}",
             when=human_time(sth.get("date"), TZ), hint="Bitview, когорта UTXO моложе 150 дней"),
        card("RSI 14 · день", rsi, "number", sub=rsi_zone),
    ])

    funding_avg = average_usable(funding_infos(data))
    fa = funding_avg.get("value")
    oi = mv(data, "derivatives.oi_five_venue_usd", "derivatives.oi_five")
    oi7 = mv(data, "derivatives.oi_1d_7d_30d_pct.7d", "derivatives.oi_five")
    cvd = cvd_value(data, "24h")
    etf = mv(data, "us_spot_bitcoin_etf.net_flow_usd", "macro.spot_etf_flow", at(data, "us_spot_bitcoin_etf.status"))
    etf5 = mv(data, "us_spot_bitcoin_etf.five_sessions_net_flow_usd", "macro.spot_etf_flow")

    section("Спрос и позиционирование")
    grid([
        card("Funding · среднее Binance/Bybit/OKX", funding_avg, "funding_8h", value_tone=tone(fa),
             sub=(f"≈ {fa * 3 * 365 * 100:+.1f}% годовых" if is_real_number(fa) else ""),
             when=when(data, "derivatives.funding_settled.Binance.last")),
        card("Открытый интерес · 5 бирж", oi, "usd_b",
             sub=f"{formatted(oi7.get('value'), 'pct')} за 7 дней", sub_tone=tone(oi7.get("value")),
             when=when(data, "derivatives.oi_latest_hour")),
        card("Спотовый CVD · 24 ч", cvd, "usd_m", value_tone=tone(cvd.get("value")),
             sub="агрессивные покупки минус продажи, 5 бирж",
             when=when(data, "spot_cvd.last_complete_hour")),
        card("ETF США · последняя сессия", etf, "usd_m", value_tone=tone(etf.get("value")),
             sub=f"5 сессий: {formatted(etf5.get('value'), 'usd_b')}", sub_tone=tone(etf5.get("value")),
             when=human_time(at(data, "us_spot_bitcoin_etf.latest_session_date"), TZ)),
    ])

    dvol = mv(data, "options.dvol.percent", "options.dvol_closed_daily")
    dvol_p = mv(data, "options.dvol.percentile", "options.dvol_closed_daily").get("value")
    rr = mv(data, "options.one_month.rr25_call_minus_put_volpts", "options.deribit.1M")
    rr_v = rr.get("value")
    long_l = mv(data, "derivatives.forced_liquidations_24h.long_usd", "derivatives.liquidations_24h")
    short_l = mv(data, "derivatives.forced_liquidations_24h.short_usd", "derivatives.liquidations_24h")
    liq_total = ({"value": long_l["value"] + short_l["value"], "status": "usable", "reason": ""}
                 if is_real_number(long_l.get("value")) and is_real_number(short_l.get("value")) else long_l)
    dxy = mv(data, "macro.dxy_exact.value", "macro.ice_dxy_exact", at(data, "macro.dxy_exact.status"))

    section("Волатильность, ликвидации, макро")
    grid([
        card("DVOL · ожидаемая волатильность", dvol, "pct_abs",
             sub=(f"выше, чем в {dvol_p:.0f}% дней за год" if is_real_number(dvol_p) else ""),
             when=human_time(at(data, "options.dvol.last_date"), TZ)),
        card("25Δ risk reversal · 1 мес", rr, "pp", value_tone=tone(rr_v),
             sub=("путы дороже коллов — спрос на защиту" if is_real_number(rr_v) and rr_v < 0
                  else "коллы дороже путов" if is_real_number(rr_v) else "")),
        card("Ликвидации · 24 ч", liq_total, "usd_m",
             sub=f"лонги {formatted(long_l.get('value'), 'usd_m')} · шорты {formatted(short_l.get('value'), 'usd_m')}",
             when=when(data, "derivatives.forced_liquidations_24h.updated")),
        card("Индекс доллара DXY", dxy, "number", when=human_time(at(data, "macro.dxy_exact.date"), TZ),
             sub="текущая сессия, не закрыта" if at(data, "macro.dxy_exact.not_finalized_eod") else ""),
    ])

    trend = label("trend", at(data, "btc_technicals.trend"))
    swings = label("swings", at(data, "btc_technicals.swings.classification"))
    rng = label("breakout20", at(data, "btc_technicals.breakout20"))
    wk = at(data, "btc_technicals.weekly_above_ma200")
    wk_txt = "неделя закрылась выше MA200" if wk is True else "неделя закрылась ниже MA200" if wk is False else "—"
    pills = [f'<span class="pill">Тренд: <b>{escape(trend)}</b></span>',
             f'<span class="pill">Структура: <b>{escape(swings)}</b></span>',
             f'<span class="pill">Диапазон: <b>{escape(rng)}</b></span>',
             f'<span class="pill">Недельный график: <b>{escape(wk_txt)}</b></span>']
    st.markdown(f'<div class="pills">{"".join(pills)}</div>', unsafe_allow_html=True)

    gaps = data.get("coverage_gaps") or []
    if gaps:
        with st.expander(f"Пробелы в данных: {len(gaps)}"):
            st.markdown("\n".join(f"- `{escape(str(g))}`" for g in gaps))
            st.caption("Подробности — на странице «Качество данных».")


def levels(data: dict) -> None:
    price = price_info(data)
    p = price.get("value")
    items = [
        ("MA20 · день", closed(data, "daily_ma.ma20"), ""),
        ("MA50 · день", closed(data, "daily_ma.ma50"), ""),
        ("MA200 · день", closed(data, "daily_ma.ma200"), ""),
        ("MA200 · неделя", closed(data, "weekly_ma200"), ""),
        ("Себестоимость STH (<150 дн)", onchain(data, "lth_sth_bitview", "sth_realized_price_150d"), "ончейн"),
        ("Realized price сети", onchain(data, "lth_sth_bitview", "realized_price_bitview"), "ончейн"),
        ("Себестоимость LTH (≥150 дн)", onchain(data, "lth_sth_bitview", "lth_realized_price_150d"), "ончейн"),
    ]
    swing_ok = metric_status(data, "price.closed_daily_weekly")[0] == "usable"
    if swing_ok:
        for kind, word in (("recent_highs", "Локальный максимум"), ("recent_lows", "Локальный минимум")):
            for point in at(data, f"btc_technicals.swings.{kind}", []) or []:
                if isinstance(point, dict) and is_real_number(point.get("value_usdt")):
                    items.append((word, {"value": point["value_usdt"], "status": "usable"},
                                  human_time(point.get("day"), TZ).replace("данные за ", "")))
    rows = [(name, info["value"], tag) for name, info, tag in items if is_real_number(info.get("value"))]
    if not is_real_number(p) or not rows:
        st.info("Нет проверенной цены или уровней для карты.")
        return
    rows.append(("Текущая цена", p, "now"))
    rows.sort(key=lambda r: r[1], reverse=True)
    html = []
    for name, value, tag in rows:
        if tag == "now":
            html.append(f'<div class="lrow now"><span>{escape(name)}</span>'
                        f'<span class="p">{formatted(value, "usd0")}</span><span class="d"></span></div>')
            continue
        dist = (value / p - 1) * 100
        tag_html = f'<span class="tag">{escape(tag)}</span>' if tag else ""
        html.append(f'<div class="lrow"><span>{escape(name)}{tag_html}</span>'
                    f'<span class="p">{formatted(value, "usd0")}</span><span class="d">{dist:+.1f}%</span></div>')
    st.markdown(f'<div class="ladder">{"".join(html)}</div>', unsafe_allow_html=True)


def price_page(data: dict) -> None:
    section("Цена и тренд", "Скользящие средние и RSI — по закрытым свечам, а не по текущему тику.")
    price = price_info(data)
    grid([
        card("BTC · спот", price, "usd0", when=when(data, "btc_technicals.latest_spot_observed_utc")),
        *[card(f"Изменение · {lbl}", closed(data, f"daily_change_pct.{k}"), "pct",
               value_tone=tone(closed(data, f"daily_change_pct.{k}").get("value")))
          for k, lbl in (("1d", "1 день"), ("7d", "7 дней"), ("30d", "30 дней"))],
    ])
    rsi_prev = at(data, "btc_technicals.rsi14_previous")
    wk_close = closed(data, "weekly_close_usdt")
    grid([
        card("RSI 14 · день", closed(data, "daily_rsi14_wilder"), "number",
             sub=f"днём ранее: {formatted(rsi_prev)}" if is_real_number(rsi_prev) else ""),
        card("Объём к медиане 20 дней", closed(data, "volume_vs_20d_median"), "ratio",
             sub="больше 1 — объём выше обычного"),
        card("Закрытие недели", wk_close, "usd0",
             when=human_time(at(data, "btc_technicals.last_closed_week_monday_utc"), TZ).replace("данные за", "неделя с")),
        card("MA200 · неделя", closed(data, "weekly_ma200"), "usd0",
             sub=("растёт" if at(data, "btc_technicals.weekly_ma200_rising") is True
                  else "снижается" if at(data, "btc_technicals.weekly_ma200_rising") is False else "")),
    ])
    pills = [f'<span class="pill">Тренд: <b>{escape(label("trend", at(data, "btc_technicals.trend")))}</b></span>',
             f'<span class="pill">Структура: <b>{escape(label("swings", at(data, "btc_technicals.swings.classification")))}</b></span>',
             f'<span class="pill">Диапазон: <b>{escape(label("breakout20", at(data, "btc_technicals.breakout20")))}</b></span>']
    st.markdown(f'<div class="pills">{"".join(pills)}</div>', unsafe_allow_html=True)

    section("Карта уровней", "Все проверенные уровни из снимка, отсортированные по цене; справа — расстояние от текущей цены.")
    levels(data)
    st.link_button("Открыть график BTCUSDT на TradingView", "https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT")


def demand(data: dict) -> None:
    section("Спотовый CVD", "Агрессивные (taker) покупки минус продажи на споте: Binance, Coinbase, OKX, Bybit, Kraken. "
                            "Неполное окно не заменяется другим составом бирж.")
    cards = []
    for w, lbl in (("1h", "1 час"), ("24h", "24 часа"), ("168h", "7 дней"), ("720h", "30 дней")):
        info = cvd_value(data, w)
        cards.append(card(f"CVD · {lbl}", info, "usd_m", value_tone=tone(info.get("value"))))
    grid(cards)
    st.caption(f"Последний полный час: {when(data, 'spot_cvd.last_complete_hour') or '—'}")
    with st.expander("Покрытие бирж по окнам"):
        rows = []
        for w in ("1h", "24h", "168h", "720h"):
            sub = at(data, f"spot_cvd.windows.{w}.complete_venue_subset", {})
            sub = sub if isinstance(sub, dict) else {}
            rows.append({"Окно": w,
                         "Все 5 бирж полностью": "да" if at(data, f"spot_cvd.windows.{w}.complete") is True else "нет",
                         "Подмножество бирж": ", ".join(sub.get("venues", []) or []) or "—",
                         "CVD подмножества": formatted(sub.get("net_usd_approx"), "usd_m") if sub.get("available") else "—"})
        table(pd.DataFrame(rows))
        st.caption("Подмножество — другой состав бирж; его нельзя сравнивать с основной пятёркой как с тем же показателем.")

    section("Потоки в спотовые BTC-ETF США", "Опубликованные торговые сессии, не внутридневные данные.")
    etf_status = at(data, "us_spot_bitcoin_etf.status")
    last = mv(data, "us_spot_bitcoin_etf.net_flow_usd", "macro.spot_etf_flow", etf_status)
    five = mv(data, "us_spot_bitcoin_etf.five_sessions_net_flow_usd", "macro.spot_etf_flow", etf_status)
    m21 = mv(data, "us_spot_bitcoin_etf.last_21_reported_sessions_net_flow_usd", "macro.spot_etf_flow", etf_status)
    pos, neg = at(data, "us_spot_bitcoin_etf.five_sessions_positive"), at(data, "us_spot_bitcoin_etf.five_sessions_negative")
    grid([
        card("Последняя сессия", last, "usd_m", value_tone=tone(last.get("value")),
             when=human_time(at(data, "us_spot_bitcoin_etf.latest_session_date"), TZ)),
        card("5 сессий", five, "usd_b", value_tone=tone(five.get("value")),
             sub=f"притоков {pos}, оттоков {neg}" if pos is not None and neg is not None else ""),
        card("21 сессия (~месяц)", m21, "usd_b", value_tone=tone(m21.get("value"))),
    ], cols=3)
    funds = at(data, "us_spot_bitcoin_etf.per_fund_flow_usd", {})
    if isinstance(funds, dict) and last.get("status") == "usable":
        nonzero = sorted(((k, v) for k, v in funds.items() if is_real_number(v) and v != 0), key=lambda kv: kv[1])
        if nonzero:
            fig = go.Figure(go.Bar(
                x=[v / 1e6 for _, v in nonzero], y=[k for k, _ in nonzero], orientation="h",
                marker_color=["#f07f6c" if v < 0 else "#33c9a4" for _, v in nonzero],
                hovertemplate="%{y}: %{x:,.1f} млн $<extra></extra>"))
            fig.update_layout(height=max(220, 34 * len(nonzero)), margin=dict(l=8, r=8, t=8, b=8),
                              xaxis_title="млн USD, последняя сессия", template="plotly_dark",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            chart(fig)
        st.caption(f"Фонды без движения не показаны. Источник: {at(data, 'us_spot_bitcoin_etf.attribution', '—')}")


def derivatives(data: dict) -> None:
    section("Открытый интерес · 5 бирж")
    oi_cards = [card("OI · сейчас", mv(data, "derivatives.oi_five_venue_usd", "derivatives.oi_five"), "usd_b",
                     when=when(data, "derivatives.oi_latest_hour"))]
    for k, lbl in (("1d", "1 день"), ("7d", "7 дней"), ("30d", "30 дней")):
        info = mv(data, f"derivatives.oi_1d_7d_30d_pct.{k}", "derivatives.oi_five")
        oi_cards.append(card(f"Изменение OI · {lbl}", info, "pct", value_tone=tone(info.get("value"))))
    grid(oi_cards)

    section("Funding · последняя расчётная ставка за 8 часов",
            "Положительный funding — лонги платят шортам. Под ставкой — то же в пересчёте на год.")
    infos = funding_infos(data)
    fcards = []
    for name, info in zip(("Binance", "Bybit", "OKX"), infos):
        v = info.get("value")
        fcards.append(card(name, info, "funding_8h", value_tone=tone(v),
                           sub=f"≈ {v * 3 * 365 * 100:+.1f}% годовых" if is_real_number(v) else "",
                           when=when(data, f"derivatives.funding_settled.{name}.last")))
    avg = average_usable(infos)
    fcards.append(card("Среднее по трём", avg, "funding_8h", value_tone=tone(avg.get("value"))))
    grid(fcards)

    section("Ликвидации и базис")
    long_l = mv(data, "derivatives.forced_liquidations_24h.long_usd", "derivatives.liquidations_24h")
    short_l = mv(data, "derivatives.forced_liquidations_24h.short_usd", "derivatives.liquidations_24h")
    lv, sv = long_l.get("value"), short_l.get("value")
    share = (f"{lv / (lv + sv) * 100:.0f}% от всех ликвидаций"
             if is_real_number(lv) and is_real_number(sv) and lv + sv > 0 else "")
    share_s = (f"{sv / (lv + sv) * 100:.0f}% от всех ликвидаций"
               if is_real_number(lv) and is_real_number(sv) and lv + sv > 0 else "")
    basis = mv(data, "derivatives.cme_front_basis.annualized_basis_pct", "derivatives.cme_basis")
    grid([
        card("Ликвидации лонгов · 24 ч", long_l, "usd_m", sub=share,
             when=when(data, "derivatives.forced_liquidations_24h.updated")),
        card("Ликвидации шортов · 24 ч", short_l, "usd_m", sub=share_s),
        card("Базис CME · годовых", basis, "pct_abs",
             sub=f"контракт {at(data, 'derivatives.cme_front_basis.contract', '—')}",
             when=human_time(at(data, "derivatives.cme_front_basis.date"), TZ)),
    ], cols=3)
    st.caption("Ликвидации — только Binance и Bybit по данным агрегатора, не весь рынок.")

    section("CME: позиции по отчёту CFTC", "Еженедельно, наблюдение по вторникам. Контракт = 5 BTC.")
    pos = at(data, "derivatives.cftc_cme_weekly.positions", {})
    cot_ok = metric_value(data, "derivatives.cftc_cme_weekly.positions.open_interest_contracts",
                          "derivatives.cftc_cme_weekly").get("status") == "usable"
    if isinstance(pos, dict) and pos and cot_ok:
        rows = []
        for key, name in (("asset_manager", "Управляющие активами"), ("leveraged", "Фонды с плечом"),
                          ("dealer", "Дилеры")):
            lo, sh = pos.get(f"{key}_long"), pos.get(f"{key}_short")
            if is_real_number(lo) and is_real_number(sh):
                rows.append({"Группа": name, "Лонг, контр.": f"{lo:,.0f}", "Шорт, контр.": f"{sh:,.0f}",
                             "Нетто, контр.": f"{lo - sh:+,.0f}", "Нетто, BTC": f"{(lo - sh) * 5:+,.0f}"})
        table(pd.DataFrame(rows))
        st.caption(f"Дата наблюдения: {human_time(at(data, 'derivatives.cftc_cme_weekly.as_of'), TZ)}. "
                   f"Открытый интерес: {formatted(pos.get('open_interest_btc_equivalent'), 'btc')}.")
    else:
        st.info("Проверенных данных CFTC в этом снимке нет.")


def options_onchain(data: dict) -> None:
    section("Опционы Deribit", "Подразумеваемая волатильность и перекос (skew) на горизонте около месяца.")
    dvol_p = mv(data, "options.dvol.percentile", "options.dvol_closed_daily").get("value")
    rr = mv(data, "options.one_month.rr25_call_minus_put_volpts", "options.deribit.1M")
    grid([
        card("DVOL", mv(data, "options.dvol.percent", "options.dvol_closed_daily"), "pct_abs",
             sub=f"выше, чем в {dvol_p:.0f}% дней за год" if is_real_number(dvol_p) else "",
             when=human_time(at(data, "options.dvol.last_date"), TZ)),
        card("ATM IV · 1 мес", mv(data, "options.one_month.atm_iv_pct", "options.deribit.1M"), "pct_abs",
             when=when(data, "options.deribit_as_of")),
        card("25Δ risk reversal", rr, "pp", value_tone=tone(rr.get("value")),
             sub="колл минус пут; минус — путы дороже"),
        card("25Δ butterfly", mv(data, "options.one_month.bf25_volpts", "options.deribit.1M"), "pp",
             sub="цена «хвостов» относительно центра"),
    ])

    price = price_info(data)
    section("Себестоимость держателей", "Bitview, когорты по возрасту UTXO: моложе и старше 150 дней. "
                                         "Не смешивать с 155-дневными когортами других источников.")
    cb = []
    for name, key in (("Краткосрочные (STH)", "sth_realized_price_150d"),
                      ("Realized price сети", "realized_price_bitview"),
                      ("Долгосрочные (LTH)", "lth_realized_price_150d")):
        info = onchain(data, "lth_sth_bitview", key)
        text, t = distance_text(pct_distance(price, info), "уровня")
        cb.append(card(name, info, "usd0", sub=text, sub_tone=t, when=human_time(info.get("date"), TZ)))
    grid(cb, cols=3)

    section("Прибыль и убыток держателей", "Оценки Bitview по себестоимости UTXO.")
    vals = [("MVRV · оценка", "network_valuation_bitview", "mvrv_utxo_cost_basis_estimate", "ratio",
             "больше 1 — в среднем монеты в прибыли"),
            ("NUPL сети · оценка", "network_valuation_bitview", "nupl_utxo_cost_basis_estimate", "ratio", ""),
            ("NUPL краткосрочных", "lth_sth_bitview", "sth_nupl_150d", "ratio", "меньше 0 — в среднем в убытке"),
            ("NUPL долгосрочных", "lth_sth_bitview", "lth_nupl_150d", "ratio", "")]
    vcards = []
    for t, g, k, u, s in vals:
        info = onchain(data, g, k)
        vcards.append(card(t, info, u, sub=s, value_tone=tone(info.get("value")),
                           when=human_time(info.get("date"), TZ)))
    grid(vcards)

    section("Поведение держателей и биржи")
    lth7 = onchain(data, "lth_sth_bitview", "lth_change_7d_150d")
    lth30 = onchain(data, "lth_sth_bitview", "lth_change_30d_150d")
    ex_in = onchain(data, "market_onchain", "exchange_in_btc")
    ex_out = onchain(data, "market_onchain", "exchange_out_btc")
    net = ({"value": ex_in["value"] - ex_out["value"], "status": "usable", "reason": ""}
           if is_real_number(ex_in.get("value")) and is_real_number(ex_out.get("value")) else ex_in)
    grid([
        card("Запас LTH · 7 дней", lth7, "btc_signed", value_tone=tone(lth7.get("value")),
             when=human_time(lth7.get("date"), TZ)),
        card("Запас LTH · 30 дней", lth30, "btc_signed", value_tone=tone(lth30.get("value"))),
        card("Нетто-поток на биржи · день", net, "btc_signed", value_tone=tone(net.get("value"), invert=True),
             sub=f"минус — больше выводят: ввод {formatted(ex_in.get('value'), 'btc')}, вывод {formatted(ex_out.get('value'), 'btc')}",
             when=human_time(ex_in.get("date"), TZ)),
        card("Резервы бирж", onchain(data, "market_onchain", "exchange_reserves_btc"), "btc"),
    ])
    wcount = onchain(data, "whale_deposits", "whale_exchange_deposit_count")
    grid([
        card("Депозиты китов на биржи", wcount, "int", when=human_time(wcount.get("date"), TZ)),
        card("Объём депозитов китов", onchain(data, "whale_deposits", "whale_exchange_deposit_volume_btc"), "btc"),
        card("Доля топ-10 в депозитах", onchain(data, "whale_deposits", "whale_only_top10_deposit_ratio"), "share"),
    ], cols=3)

    stale = []
    for group in ("market_onchain", "historical_whale_alerts"):
        items = at(data, f"onchain.{group}", {}) or {}
        for name, item in items.items():
            if isinstance(item, dict) and onchain(data, group, name).get("status") != "usable":
                stale.append({"Метрика": f"{group}.{name}", "Статус": label("status", item.get("status")),
                              "Последняя дата": item.get("date") or "—"})
    if stale:
        with st.expander(f"Временно недоступные ончейн-метрики: {len(stale)}"):
            table(pd.DataFrame(stale))
            st.caption("Источник задерживает или не отдал данные. Числа из других методик сюда не подставляются.")


def macro(data: dict) -> None:
    section("Ставки и доходности", "Серии FRED публикуются с задержкой — смотри дату под каждым значением.")

    def fred(key: str, quality: str | None = None) -> dict:
        info = mv(data, f"macro.fred.{key}.value", quality, at(data, f"macro.fred.{key}.status"))
        info["date"] = at(data, f"macro.fred.{key}.date")
        return info

    lo, hi = fred("fed_target_lower_pct", "macro.fed_rates"), fred("fed_target_upper_pct", "macro.fed_rates")
    rng_ok = is_real_number(lo.get("value")) and is_real_number(hi.get("value"))
    eff, y2, y10 = fred("fed_funds_effective_pct", "macro.fed_rates"), fred("treasury_2y_pct", "macro.treasury_yields"), \
        fred("treasury_10y_pct", "macro.treasury_yields")
    curve = mv(data, "macro.treasury_curve.spread_pct_points", "macro.treasury_yields", at(data, "macro.treasury_curve.status"))
    grid([
        card("Целевой диапазон ФРС", lo if rng_ok else (hi if lo.get("value") is not None else lo), display=f"{lo['value']:.2f}–{hi['value']:.2f}%" if rng_ok else "—",
             when=human_time(lo.get("date"), TZ)),
        card("Эффективная ставка ФРС", eff, "pct_abs", when=human_time(eff.get("date"), TZ)),
        card("UST 2 года", y2, "pct_abs", when=human_time(y2.get("date"), TZ)),
        card("UST 10 лет", y10, "pct_abs", when=human_time(y10.get("date"), TZ),
             sub=f"10Y − 2Y: {formatted(curve.get('value'), 'pp')}"),
    ])
    section("Доллар и ликвидность")
    dxy = mv(data, "macro.dxy_exact.value", "macro.ice_dxy_exact", at(data, "macro.dxy_exact.status"))
    broad = fred("usd_broad_trade_weighted", "macro.usd_broad_index")
    bal = fred("fed_balance_sheet_millions")
    bal_usd = dict(bal, value=bal["value"] * 1_000_000 if is_real_number(bal.get("value")) else None)
    grid([
        card("ICE DXY", dxy, "number", when=human_time(at(data, "macro.dxy_exact.date"), TZ),
             sub="текущая сессия, не закрыта" if at(data, "macro.dxy_exact.not_finalized_eod") else ""),
        card("Широкий индекс доллара (не DXY)", broad, "number", when=human_time(broad.get("date"), TZ)),
        card("Баланс ФРС", bal_usd, "usd_t", when=human_time(bal.get("date"), TZ)),
    ], cols=3)


def liquidity(data: dict) -> None:
    section("Глубина стаканов", "Снимок лимитных заявок в полосе от средней цены. Заявки можно отменить — "
                                 "стакан не равен исполненному спросу.")
    c1, c2 = st.columns(2)
    with c1:
        band = st.selectbox("Полоса от средней цены", ["0.01", "0.05", "0.2", "1.0"], index=2,
                            format_func=lambda x: f"±{x}%")
    with c2:
        market = st.selectbox("Рынок", ["Все", "Спот", "Бессрочные"])
    rows = orderbook_rows(data, band, market)
    ok = [r for r in rows if r["Статус"] == "usable"]
    st.caption(f"Проверенных стаканов в этой полосе: {len(ok)} из {len(rows)}. "
               f"Снимок: {when(data, 'orderbook_live.venues.binance_spot.captured_at') or '—'}")
    if ok:
        names = [venue_name(r["Биржа"]) for r in ok]
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Покупка (bid)", y=names, x=[r["Спрос, USD"] / 1e6 for r in ok],
                             orientation="h", marker_color="#33c9a4"))
        fig.add_trace(go.Bar(name="Продажа (ask)", y=names, x=[r["Предложение, USD"] / 1e6 for r in ok],
                             orientation="h", marker_color="#f07f6c"))
        fig.update_layout(barmode="group", height=max(340, 46 * len(names)), margin=dict(l=8, r=8, t=30, b=8),
                          xaxis_title="млн USD в заявках", yaxis=dict(autorange="reversed"),
                          legend=dict(orientation="h", y=1.08), template="plotly_dark",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        chart(fig)
    else:
        st.info("Нет проверенной глубины в выбранной полосе.")
    view = [{"Рынок": venue_name(r["Биржа"]),
             "Покупка": formatted(r["Спрос, USD"], "usd_m"), "Продажа": formatted(r["Предложение, USD"], "usd_m"),
             "Доля покупок": f"{r['Доля заявок на покупку'] * 100:.0f}%" if is_real_number(r["Доля заявок на покупку"]) else "—",
             "Статус": label("status", r["Статус"]), "Причина": r["Причина"]} for r in rows]
    table(pd.DataFrame(view))


def quality(data: dict) -> None:
    section("Здоровье сборщиков", "Статусы приходят из агрегатора; панель их не переопределяет.")
    src = source_rows(data)
    for r in src:
        r["Статус"] = label("health", r["Статус"])
    table(pd.DataFrame(src))
    gaps = data.get("coverage_gaps") or []
    if gaps:
        st.markdown("**Пробелы покрытия**")
        st.code("\n".join(str(v) for v in gaps), language=None)

    section("Проверки отдельных метрик")
    checks = quality_rows(data)
    c1, c2 = st.columns([1, 2])
    with c1:
        bad_only = st.checkbox("Только проблемные", value=True)
    with c2:
        search = st.text_input("Поиск по названию или причине", "")
    filtered = [r for r in checks if (not bad_only or r["Статус"] != "usable")
                and (not search or search.lower() in (r["Метрика"] + " " + r["Причина"]).lower())]
    for r in filtered:
        r["Статус"] = label("status", r["Статус"])
    table(pd.DataFrame(filtered), height=420)
    st.caption(f"Показано {len(filtered)} из {len(checks)} проверок.")
    with st.expander("Сводные флаги готовности"):
        st.json(at(data, "family_readiness", {}), expanded=False)
    st.download_button("Скачать текущий brief.json", json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name="brief.json", mime="application/json")


PAGES = {
    "Обзор": overview,
    "Цена и тренд": price_page,
    "Спрос и ETF": demand,
    "Деривативы": derivatives,
    "Опционы и ончейн": options_onchain,
    "Макро": macro,
    "Стаканы": liquidity,
    "История": show_history,
    "Качество истории": render_history_quality,
    "Качество данных": quality,
}

# ---------------------------------------------------------------------------
# Sidebar and main loop
# ---------------------------------------------------------------------------
st.sidebar.title("₿ BTC Panel")
page = st.sidebar.radio("Раздел", list(PAGES))
st.sidebar.divider()
mode = st.sidebar.radio("Откуда брать данные", ["GitHub (онлайн)", "Локальный JSON"])
local = st.sidebar.text_input("Путь к brief.json", value=str(CACHE), disabled=mode != "Локальный JSON")
if st.sidebar.button("Обновить сейчас"):
    fetch_remote.clear()
    load_history.clear()
    collect_rolling.clear()
    st.rerun()
st.sidebar.caption(f"Экран обновляется сам каждые {REFRESH_SECONDS // 60} мин. Время — {LOCAL_TZ_NAME}.")
st.sidebar.caption("Наведи курсор на карточку, чтобы увидеть причину статуса.")
st.sidebar.link_button("Репозиторий с данными", REPO_URL)


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def live_view() -> None:
    if mode == "GitHub (онлайн)":
        errors=collect_rolling()
        if errors:st.caption(f"Не удалось обновить {len(errors)} скользящих архивов; локальная история сохранена.")
    if page == "Качество истории":
        if mode == "Локальный JSON":
            st.info("Для общей проверки переключи источник на GitHub (онлайн).")
            return
        render_history_quality()
        return
    if page == "История":
        if mode == "Локальный JSON":
            st.info("История пока читается только из публичных архивов GitHub. Переключи источник на GitHub (онлайн).")
            return
        show_history()
        return
    doc, source, error = load(mode, local)
    if doc is None:
        st.error(error or "Нет доступных данных")
        st.info("Проверь интернет или переключись на локальный brief.json. После первой удачной загрузки "
                "панель сохраняет копию и показывает её при обрыве сети.")
        return
    if error:
        st.error(f"Сеть недоступна — показана последняя сохранённая копия. Причина: {error}")
    header(doc, source)
    PAGES[page](doc)


live_view()
