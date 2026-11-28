"""Manual current-state packet from existing public brief. No forecasts or trades."""
import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from data_logic import at, parse_utc, validate_brief, is_real_number
from live_derivatives import run as collect_derivatives

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


def demand_context(data, families):
    """Non-overlapping spot totals and reported ETF session signs, not a signal."""
    spot = {x["id"]: x for x in families["spot"]}
    result = {"version":"demand-context-v1","spot":{},"etf":{},
              "limitations":["Spot baskets overlap; not independent confirmations.",
                  "Mixed trade/receive-hour basis remains inherited; no per-venue or per-day breadth inferred.",
                  "Net taker notional is not capital inflow; ETF flows are distinct.",
                  "ETF counts describe reported sessions, not a verified exchange calendar."]}
    for basket, venues, prefix in (
        ("original_five","binance,coinbase,okx,bybit,kraken","original_five"),
        ("ex_coinbase","binance,okx,bybit,kraken,bitget","fixed_ex_coinbase")):
        recent, week = (spot[basket+"_"+w] for w in ("24h","168h"))
        records = (recent, week)
        keys = ["BTC spot taker executed|"+venues+"|"+w+"|USD~USDT|exchange-trade-or-received-UTC-hours"
                for w in ("24h","168h")]
        endpoint = parse_utc(recent["observed_at"])
        valid = (endpoint is not None and endpoint == parse_utc(week["observed_at"])
                 and endpoint.minute == endpoint.second == endpoint.microsecond == 0
                 and all(x["status"]=="usable" and x["comparison_key"]==key
                         and x["unit"]=="approx USD" and is_real_number(x["value"])
                         for x,key in zip(records,keys)))
        item = {"status":"usable" if valid else "incompatible_or_unavailable_windows",
                "observed_end_utc":endpoint.isoformat() if valid else None,
                "last_24h_usd_approx":recent["value"] if valid else None,
                "prior_144h_usd_approx":week["value"]-recent["value"] if valid else None,
                "prior_144h_mean_per_24h_usd_approx":(week["value"]-recent["value"])/6 if valid else None,
                "venues":venues.split(","),"source_fields":[x["source_field"] for x in records],
                "input_comparison_keys":[x["comparison_key"] for x in records],
                "note":"Subtract aligned nested totals; no daily persistence or venue breadth inferred."}
        result["spot"][basket]=item
    e = {x["id"]:x for x in families["etf"]}
    latest, five = e["latest"],e["5_sessions"]
    pos=at(data,"us_spot_bitcoin_etf.five_sessions_positive")
    neg=at(data,"us_spot_bitcoin_etf.five_sessions_negative")
    day=at(data,"us_spot_bitcoin_etf.latest_session_date")
    valid=(latest["status"]==five["status"]=="usable" and
           latest["observed_at"]==five["observed_at"]==day and
           latest["comparison_key"]==five["comparison_key"]=="macro|spot_etf_flow" and
           at(data,"us_spot_bitcoin_etf.US_spot_only") is True and
           at(data,"us_spot_bitcoin_etf.not_intraday") is True and
           type(pos) is int and type(neg) is int and 0<=pos<=5 and 0<=neg<=5 and pos+neg<=5)
    if valid:
        a,b=latest["value"],five["value"]
        valid=not ((a>0 or b>0) and pos==0 or (a<0 or b<0) and neg==0 or
                   pos==5 and (a<=0 or b<=0) or neg==5 and (a>=0 or b>=0))
    result["etf"]={"status":"usable" if valid else "incompatible_or_unavailable_counts",
        "latest_reported_session":day if valid else None,
        "positive_sessions":pos if valid else None,"negative_sessions":neg if valid else None,
        "remaining_sessions_not_classified":5-pos-neg if valid else None,
        "prior_4_reported_sessions_net_usd":five["value"]-latest["value"] if valid else None,
        "source_fields":["us_spot_bitcoin_etf.five_sessions_positive","us_spot_bitcoin_etf.five_sessions_negative",
                         latest["source_field"],five["source_field"]]}
    return result


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
            "demand_context":demand_context(data,families),
            "coverage_gaps":data.get("coverage_gaps",[]),
            "not_in_packet":["OI quantity and perpetual premium history not available in selected brief fields",
                "News, expectations and publication-time verification not collected here",
                "Week-over-week snapshot comparisons not yet implemented",
                "Orderbook and additional indicators deferred until a named decision gap"],
            "limitations":["Upstream quality checks are inherited, not independently verified.",
                "Date-only age is calendar-day resolution; freshness limits are provisional operational caps, not predictive thresholds.",
                "Related observations are not independent votes. Missing is not bearish or zero.",
                "No LLM, trading signal, forecast, or changes to monitoring/journals."]}


def perpetual_context(report, now):
    """Independent direct REST observations; never substitute the USD basket."""
    observed = report.get("observed_end_utc")
    retrieved = parse_utc(report.get("retrieved_utc"))
    stamp = parse_utc(observed)
    hours = (now-stamp).total_seconds()/3600 if stamp is not None else None
    valid = (report.get("version") == "live-derivatives-readiness-v1" and
             report.get("market") == "Binance USD-M BTCUSDT perpetual" and
             stamp is not None and retrieved is not None and stamp <= retrieved <= now and
             0 <= hours <= 4)
    items = []
    def add(name, value, unit, complete=True, coverage=None):
        ok = valid and complete and is_real_number(value)
        items.append({"id":name,"value":value if ok else None,"unit":unit,
            "status":"usable" if ok else ("invalid_or_stale_source" if not valid else "incomplete_or_invalid"),
            "observed_at":observed,"retrieved_utc":report.get("retrieved_utc"),
            "age_h":round(hours,2) if hours is not None else None,"max_age_h":4,
            "scope":"Binance USD-M BTCUSDT perpetual only",
            "comparison_key":"Binance USD-M BTCUSDT perpetual|"+name,
            "coverage":coverage})
    q = report.get("oi_latest_checked_btc")
    add("oi_quantity",q,"BTC",is_real_number(q) and q>0)
    add("premium_last_closed",report.get("premium_last_closed_fraction"),"fraction")
    for days in (1,7,28):
        w = at(report,"windows."+str(days),{})
        if not isinstance(w,dict):
            w = {}
        a,b = w.get("oi_start_btc"),w.get("oi_end_btc")
        n = w.get("oi_checked_points")
        oi_ok = (is_real_number(a) and a>0 and is_real_number(b) and b>0 and
                 is_real_number(q) and b==q and type(n) is int and 2<=n<=days*24+1 and
                 w.get("oi_expected_points")==days*24+1)
        # Exact endpoints suffice for the change; do not imply complete interior coverage.
        add("oi_quantity_change_"+str(days)+"d",100*(b/a-1) if oi_ok else None,
            "percent BTC quantity",oi_ok,{"valid":n,"expected":days*24+1})
        n = w.get("premium_valid_hours")
        p_ok = type(n) is int and n==days*24 and w.get("premium_expected_hours")==days*24
        coverage = {"valid":n,"expected":days*24}
        add("premium_mean_"+str(days)+"d",w.get("premium_mean_close_fraction"),"fraction",p_ok,coverage)
        share = w.get("premium_negative_hour_share")
        add("premium_negative_share_"+str(days)+"d",share,"fraction",
            p_ok and is_real_number(share) and 0<=share<=1,coverage)
    return items


def run(root=ROOT):
    raw=fetch()
    brief_received=datetime.now(timezone.utc)
    data=json.loads(raw)
    validate_brief(data)
    folder=Path(root)/brief_received.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True,exist_ok=False)
    (folder/"brief.json").write_bytes(raw)
    try:
        derivative_path=collect_derivatives(root=folder/"binance_perpetual")
        derivative_raw=derivative_path.read_bytes()
        derivative_report=json.loads(derivative_raw)
        provenance={"report_path":derivative_path.relative_to(folder).as_posix(),
                    "report_sha256":sha(derivative_raw),
                    "sources":derivative_report.get("sources",[]),
                    "errors":derivative_report.get("errors",{}),
                    "oi_unit_check_rejected":derivative_report.get("oi_unit_check_rejected",[]),
                    "limitations":derivative_report.get("limitations",[])}
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
        derivative_report={}
        provenance={"errors":{"collector":str(exc)[:300]}}
    now=datetime.now(timezone.utc)
    report=packet(data,now)
    report["version"]="market-state-v3"
    report["retrieved_utc"]=brief_received.isoformat()
    report["assembled_utc"]=now.isoformat()
    report["brief_sha256"]=sha(raw)
    report["families"]["binance_perpetual"]=perpetual_context(derivative_report,now)
    report["binance_perpetual_provenance"]=provenance
    report["not_in_packet"][0]="Multi-venue OI quantity unavailable; separate Binance perpetual only."
    if any(x["status"]!="usable" for x in report["families"]["binance_perpetual"]):
        report["coverage_gaps"].append("binance_perpetual:partial_or_unavailable")
    report["limitations"].append("Direct Binance fields use their own observation/retrieval times; premium index is not funding, trade basis or directional positioning. No inferred global quantity.")
    target=folder/"market_state.json"
    with target.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    items=[x for group in report["families"].values() for x in group]
    print("Usable:",sum(x["status"]=="usable" for x in items),"/",len(items))
    print("Send:",target,"SHA-256:",sha(target.read_bytes()))


if __name__=="__main__":
    run()
