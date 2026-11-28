"""Manual current-state packet from existing public brief. No forecasts or trades."""
import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from data_logic import at, parse_utc, validate_brief, is_real_number

URL = "https://raw.githubusercontent.com/kh827y/btc-market-data/main/btc-monitor/data/brief.json"
ROOT = Path(__file__).resolve().parent / "data/research/state_packets"
MAX_BYTES = 4 * 1024 * 1024


def fetch():
    with urlopen(Request(URL, headers={"User-Agent": "BTC-Lab state packet"}), timeout=45) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Brief exceeds size limit")
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def age(observed, now, cutoff):
    """Date-only observations retain day precision, not invented publication times."""
    if isinstance(observed, str) and len(observed) == 10:
        try:
            d = date.fromisoformat(observed)
        except ValueError:
            return None, "invalid_time"
        if d > cutoff.date() or d > now.date():
            return None, "future_observation"
        return (now.date() - d).days * 24, "date_only"
    t = parse_utc(observed)
    if t is None:
        return None, "invalid_time"
    if t > cutoff or t > now:
        return None, "future_observation"
    return (now - t).total_seconds() / 3600, "timestamp"


def packet(data, now):
    validate_brief(data)
    cutoff = parse_utc(data["as_of_utc"])
    if cutoff > now:
        raise ValueError("Brief timestamp after retrieval clock")
    snapshot_age = (now - cutoff).total_seconds()/3600
    families = {}
    def add(family, name, path, quality, source, unit, max_age, note="", source_status_path=None):
        q = at(data, "metric_quality.checks."+quality, {})
        if not isinstance(q, dict):
            q = {}
        value = at(data, path)
        obs = q.get("observed_at")
        # FRED quality checks are family-level; use the actual series date.
        if path.startswith("macro.fred."):
            obs = at(data, path.rsplit(".",1)[0]+".date")
        hours, precision = age(obs, now, cutoff)
        status = q.get("status", "unchecked")
        source_status = at(data, "sources."+source+".status")
        detail_status = at(data, source_status_path) if source_status_path else None
        if status != "usable":
            usable, reason = False, "source_quality_not_usable"
        elif source_status not in ("fresh", "usable", "healthy"):
            usable, reason = False, "collector_status_not_fresh"
        elif source_status_path and detail_status not in ("usable", "available", "fresh", "standard"):
            usable, reason = False, "metric_source_status_not_usable"
        elif not is_real_number(value):
            usable, reason = False, "missing_or_invalid_number"
        elif hours is None:
            usable, reason = False, precision
        elif snapshot_age > 3:
            usable, reason = False, "snapshot_older_than_3h"
        elif hours > max_age:
            usable, reason = False, "observation_older_than_limit"
        else:
            usable, reason = True, None
        item = {"id":name, "value":value if usable else None, "unit":unit,
                "status":"usable" if usable else reason, "upstream_status":status,
                "upstream_reason":q.get("reason"), "observed_at":obs, "time_precision":precision,
                "age_h":round(hours,2) if hours is not None else None, "max_age_h":max_age,
                "scope":q.get("scope"), "comparison_key":q.get("comparison_key"),
                "source":at(data, "sources."+source+".original"), "collector_status":source_status,
                "source_field":path, "note":note}
        families.setdefault(family, []).append(item)
    def p(name, path, unit, note=""):
        add("price",name,"btc_technicals."+path,"price.closed_daily_weekly","price_technical",unit,48,note)
    add("price","spot_quote","btc_technicals.latest_spot_price_usdt","price.live_spot_quote",
        "price_technical","USDT/BTC",2,"Binance spot, not execution price.")
    p("daily_close","latest_closed_day_price_usdt","USDT/BTC")
    for w in ("1d","7d","30d"):
        p("return_"+w,"daily_change_pct."+w,"percent")
    for n in (20,50,200):
        p("ma"+str(n),"daily_ma.ma"+str(n),"USDT/BTC")
    p("rsi14","daily_rsi14_wilder","index","Price-derived; not independent of returns.")
    for w in ("24h","168h","720h"):
        prefix="spot_cvd.windows."+w
        note="Aggressive buy minus sell notional, not capital inflow. Trade/receive UTC-hour conventions differ."
        add("spot","original_five_"+w,prefix+".net_usd_approx","spot_cvd.original_five."+w,
            "spot_cvd","approx USD",4,note)
        add("spot","ex_coinbase_"+w,prefix+".fixed_five_ex_coinbase.net_usd_approx",
            "spot_cvd.fixed_ex_coinbase."+w,"spot_cvd","approx USD",4,
            note+" Separate fixed basket including Bitget; never substitute original five.")
    for name,field in (("latest","net_flow_usd"),("5_sessions","five_sessions_net_flow_usd"),
                       ("21_sessions","last_21_reported_sessions_net_flow_usd")):
        add("etf",name,"us_spot_bitcoin_etf."+field,"macro.spot_etf_flow","macro_etf","USD",120,
            "Reported sessions only; date age is not proof of latest expected session. Not intraday.",
            "us_spot_bitcoin_etf.status")
    add("derivatives","oi_notional","derivatives.oi_five_venue_usd","derivatives.oi_five","derivatives",
        "USD notional",4,"Contains price; cannot infer contract-quantity contraction.")
    for w in ("1d","7d","30d"):
        add("derivatives","oi_notional_change_"+w,"derivatives.oi_1d_7d_30d_pct."+w,
            "derivatives.oi_five","derivatives","percent USD notional",4,
            "Same basket per upstream; quantity not available; no approximate BTC conversion.")
    for v in ("Binance","Bybit","OKX"):
        add("derivatives","funding_"+v,"derivatives.funding_settled."+v+".rate_8h",
            "derivatives.funding_8h."+v,"derivatives","fraction / 8h",16,"Settled, not forecast.")
    add("derivatives","cme_basis","derivatives.cme_front_basis.annualized_basis_pct","derivatives.cme_basis",
        "derivatives","annualized percent",120,"Specific dated CME contract, not perp premium.")
    for side in ("long","short"):
        add("derivatives","liquidations_"+side,"derivatives.forced_liquidations_24h."+side+"_usd",
            "derivatives.liquidations_24h","derivatives","USD",4,"Reported Binance+Bybit only.")
    add("options","dvol","options.dvol.percent","options.dvol_closed_daily","options","annualized index percent",48,
        "Risk magnitude, not directional probability.")
    for name,field in (("atm_iv","atm_iv_pct"),("rr25","rr25_call_minus_put_volpts")):
        add("options",name,"options.one_month."+field,"options.deribit.1M","options",
            "IV percent" if name=="atm_iv" else "volatility points",4,
            "Interpolated Deribit mark IV; RR is call minus put.", "options.one_month.status")
    for k,unit in (("lth_change_7d_150d","BTC"),("lth_change_30d_150d","BTC"),
                   ("lth_realized_price_150d","USD/BTC"),("sth_realized_price_150d","USD/BTC"),
                   ("realized_price_bitview","USD/BTC")):
        path="onchain.lth_sth_bitview."+k
        add("holders",k,path+".value",path,"onchain",unit,72,
            "Bitview UTXO age 150d; aging/transfers are not proof of sales.",path+".status")
    for k in ("mvrv","nupl","sth_sopr","lth_sopr"):
        path="onchain.market_onchain."+k
        add("holders",k,path+".value",path,"onchain","source ratio",72,
            "No substitute across cohort definitions.",path+".status")
    add("macro","dxy","macro.dxy_exact.value","macro.ice_dxy_exact","macro_etf","index",120,
        "Prior market session; date age is not a trading calendar check.","macro.dxy_exact.status")
    for name,key in (("fed_funds_effective_pct","fed_rates"),("treasury_2y_pct","treasury_yields"),
                     ("treasury_10y_pct","treasury_yields"),("usd_broad_trade_weighted","usd_broad_index")):
        path="macro.fred."+name
        add("macro",name,path+".value","macro."+key,"macro_etf",
            "index" if name.startswith("usd") else "percent",168,
            "Source series; no substitution. Family-level upstream check.",path+".status")
    close_usable = any(x["id"]=="daily_close" and x["status"]=="usable" for x in families["price"])
    structure = at(data,"btc_technicals.swings.classification")
    technical_context = {
        "observed_at":at(data,"metric_quality.checks.price.closed_daily_weekly.observed_at"),
        "classification":structure if close_usable and structure in ("HH_HL","LH_LL","mixed","MIXED","unknown") else None,
        "source":"Binance closed spot candles; swing labels are upstream descriptions, not forecasts.",
    }
    return {"version":"market-state-v1", "source_url":URL,
            "as_of_utc":data["as_of_utc"], "retrieved_utc":now.isoformat(),
            "snapshot_age_h":round(snapshot_age,2), "families":families,
            "technical_context":technical_context,
            "coverage_gaps":data.get("coverage_gaps",[]),
            "not_in_packet":["OI quantity and perpetual premium history not available in selected brief fields",
                "News, expectations and publication-time verification not collected here",
                "Week-over-week snapshot comparisons not yet implemented",
                "Orderbook and additional indicators deferred until a named decision gap"],
            "limitations":["Upstream quality checks are inherited, not independently verified.",
                "Date-only age is calendar-day resolution; freshness limits are provisional operational caps, not predictive thresholds.",
                "Related observations are not independent votes. Missing is not bearish or zero.",
                "No LLM, trading signal, forecast, or changes to monitoring/journals."]}


def run(root=ROOT):
    raw=fetch()
    now=datetime.now(timezone.utc)
    report=packet(json.loads(raw),now)
    report["brief_sha256"]=sha(raw)
    folder=Path(root)/now.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True,exist_ok=False)
    (folder/"brief.json").write_bytes(raw)
    target=folder/"market_state.json"
    with target.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    items=[x for group in report["families"].values() for x in group]
    print("Usable:",sum(x["status"]=="usable" for x in items),"/",len(items))
    print("Send:",target,"SHA-256:",sha(target.read_bytes()))


if __name__=="__main__":
    run()
