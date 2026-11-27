"""Weekly presentation of saved RISK and DD-001 with separate DVOL context."""
import json
import math
from pathlib import Path
from datetime import date,datetime
from binance_minute import digest
from buy_journal import live_prices,origin_for,utcnow,SNAPSHOT,REPO
from risk_journal import ROOT as RISK_ROOT,VERSION as RISK_VERSION
from research_buy import DAY,HASHES,window
from research_drawdown import group,ROOT as DD_ROOT
from research_dvol_context import snapshot as dvol_snapshot, describe as dvol_describe

ROOT=REPO/"data"/"research"/"decision_sheet"
DD_SHA="759bd8e43ef8644f0af875becb68c476882f7f465b21a094eee47da2026aa133"
PEAK_START=date(2015,7,20)
MODELS=("empirical_expanding","scaled_expanding")
HORIZONS=(7,28,90)


def checked_read(path,expected=None):
    raw=Path(path).read_bytes()
    if expected is not None and digest(raw)!=expected:
        raise ValueError("Source hash mismatch")
    return json.loads(raw),digest(raw)


def saved_prices(source,t,snapshot=SNAPSHOT):
    if source["snapshot_sha256"]!=HASHES["bitstamp"] or source["stop_exclusive"]!=(t-DAY).isoformat():
        raise ValueError("Wrong source identity")
    pages=iter(source["pages"])
    def replay(url,limit):
        p=next(pages,None)
        if p is None or p["url"]!=url:
            raise ValueError("Saved price page missing or reordered")
        raw=p["raw"].encode("utf-8")
        if len(raw)>limit or digest(raw)!=p["sha256"]:
            raise ValueError("Saved price page mismatch")
        return raw
    prices,_=live_prices(t-DAY,snapshot,replay)
    if next(pages,None) is not None:
        raise ValueError("Unexpected extra price page")
    return prices


def context(prices,t):
    stop=t-DAY
    if any(d>=stop for d in prices):
        raise ValueError("Future price supplied")
    a=window(prices,PEAK_START,stop)
    if a is None or len(a)<200:
        raise ValueError("Incomplete comparable peak history")
    c=a[:,3]
    close=float(c[-1]);peak=float(c.max())
    depth=max(0.,1-close/peak)
    return {"close":close,"peak":peak,"depth":depth,"bin":group(depth),
            "ma50":float(c[-50:].mean()),"ma200":float(c[-200:].mean())}


def pct(x):
    return f"{100*math.expm1(x):+.1f}%"


def risk_range(m,key):
    q=m[key]
    if len(q)!=3 or not all(math.isfinite(x) for x in q) or not q[0]<=q[1]<=q[2]:
        raise ValueError("Invalid quantiles")
    return " / ".join(pct(x) for x in q)


def historical_range(h,key):
    q=h[key]["quantiles"]
    return " / ".join(f"{q[str(i)]:+.1f}%" for i in (10,50,90))


def render(f,dd,c,forecast_sha,dd_sha,dvol=None):
    if not math.isclose(c["close"],f["state"]["close"],rel_tol=1e-12):
        raise ValueError("Risk forecast close mismatch")
    market=dd["markets"]["bitstamp"]
    if market["peak_history_start"]!=PEAK_START.isoformat():
        raise ValueError("Incompatible drawdown history")
    hist=market["by_depth"][c["bin"]]
    ma50,ma200=c["ma50"],c["ma200"]
    close=c["close"]
    lines=[f"# BTC-Lab: неделя {f['origin']} UTC",
        "",f"Срез: закрытие субботы, {close:,.2f} USD. Наблюдаемый максимум с 20.07.2015: {c['peak']:,.2f} USD; просадка {100*c['depth']:.1f}%.",
        f"MA50: {ma50:,.2f} USD; цена {'выше' if close>ma50 else 'не выше'} средней. MA200: {ma200:,.2f} USD; цена {'выше' if close>ma200 else 'не выше'} средней. Это состояние, не подтверждение разворота.",
        "","## 1. История при сопоставимой глубине просадки",
        f"Группа {c['bin']}; данные 2016–2023. Недельные окна перекрываются; число эпизодов не равно числу независимых циклов.",
        "","| Дни | Окна / эпизоды | Доходность P10/P50/P90 | Худшее снижение от входа P10/P50/P90 | Падение ≥15% |",
        "|---|---:|---|---|---:|"]
    for h in HORIZONS:
        x=hist["horizons"][str(h)]
        if not x["n"]:
            lines.append(f"| {h} | 0 | нет данных | нет данных | — |")
            continue
        lines.append(f"| {h} | {x['n']} / {x['distinct_drawdown_episodes']} | {historical_range(x,'return_pct')} | {historical_range(x,'worst_from_entry_pct')} | {100*x['further_loss_fraction']['15']:.1f}% |")
    lines+=["","## 2. Уже записанные прогнозные ориентиры RISK",
        "Две простые исторические модели; это оценочные распределения, не гарантии. На 90 днях нескалированный ориентир показываем первым; масштабированный оставляем для сравнения.",
        "","| Дни | Ориентир | История (окон) | Доходность P10/P50/P90 | Худшее снижение P10/P50/P90 | P(снижение ≥15%) |",
        "|---|---|---:|---|---|---:|"]
    for h in HORIZONS:
        for key,label in zip(MODELS,("История","С поправкой на волатильность")):
            m=f["horizons"][str(h)]["models"][key]
            p=m["p_loss_15"]
            if not 0<=p<=1:
                raise ValueError("Invalid forecast probability")
            lines.append(f"| {h} | {label} | {m['n_train']} | {risk_range(m,'return_log_quantiles')} | {risk_range(m,'worst_log_quantiles')} | {100*p:.1f}% |")
    lines+=["","## 3. Как читать",
        "P10/P50/P90 — нижний дециль, медиана и верхний дециль. Худшее снижение относится к цене входа, не к пику после покупки. Исторические частоты и диапазоны не доказывают будущую точность.",
        (dvol_describe(dvol) if dvol is not None else "DVOL: свежий снимок недоступен; историческое значение не выдаётся за текущее."),
        "OI собирается отдельно, без прогнозного веса.",
        "Покупать сейчас, ждать или делить сумму — решение владельца. Для персонального размера покупки нужен допустимый риск и цена упущенного роста; они не заданы.",
        "",f"Источники: RISK forecast SHA256 {forecast_sha}; DD-001 SHA256 {dd_sha}. Хэш не доказывает истинность выводов. Статус внешней квитанции прогноза проверяется отдельно.",
        "Таблица не является новым прогнозом и не изменяет журнал."]
    return "\n".join(lines)+"\n"


def run(root=ROOT,risk_root=RISK_ROOT,dd_root=DD_ROOT,snapshot=SNAPSHOT,clock=utcnow):
    t=origin_for(clock())
    p=Path(risk_root)/t.isoformat()/"risk_forecast.json"
    f,sha=checked_read(p)
    if f["version"]!=RISK_VERSION or f["origin"]!=t.isoformat() or f["market"]!="Bitstamp BTC/USD":
        raise ValueError("Wrong risk forecast")
    issued=datetime.fromisoformat(f["issued_utc"].replace("Z","+00:00"))
    if issued.tzinfo is None or origin_for(issued)!=t:
        raise ValueError("Invalid issue time")
    src,_=checked_read(p.parent/"source.json",f["source_sha256"])
    dd,dd_sha=checked_read(Path(dd_root)/"drawdown_report.json",DD_SHA)
    if dd["protocol"]!="DD-001-descriptive-v1" or dd["price_hashes"]!=HASHES or dd["test_numeric_values_parsed"] is not False:
        raise ValueError("Invalid drawdown source")
    c=context(saved_prices(src,t,snapshot),t)
    target=Path(root)/t.isoformat()/"decision_sheet.md"
    if target.exists():
        print("Decision sheet already saved:",target)
        return target
    try:
        dvol=dvol_snapshot(t-2*DAY,clock=clock)
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
        print("DVOL unavailable:",str(exc)[:300],flush=True)
        dvol=None
    report=render(f,dd,c,sha,dd_sha,dvol)
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open("x",encoding="utf-8",newline="\n") as out:
            out.write(report)
    except FileExistsError:
        if target.read_text(encoding="utf-8")!=report:
            raise ValueError("Existing sheet differs; preserve original") from None
    print("Decision sheet:",target)
    return target


if __name__=="__main__":
    run()
