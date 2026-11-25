"""Historical page. Downloads only selected public archives, read-only."""
import json
from urllib.request import Request, urlopen
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from history_logic import METRICS, PRICE, ETF, CVD, FULL_ETF, BINANCE_DAILY, period_slice, series_for
from history_store import ROLLING, save_archive, saved_series, last_fetch, coverage
import pandas as pd
from extended_history import read_local, request_json, parse_etf, TFTC_URL

BASE="https://raw.githubusercontent.com/kh827y/btc-market-data/main/"
LIMIT=12_000_000

@st.cache_data(ttl=300,show_spinner=False)
def load_history(path):
    if path not in {x[0] for x in METRICS.values()}:raise ValueError("Неизвестный архив")
    if path==FULL_ETF:
        try:return parse_etf(request_json(TFTC_URL))
        except Exception:
            result=read_local(path)
            result["offline_copy"]=True
            return result
    if path.startswith("local/"):return read_local(path)
    req=Request(BASE+path,headers={"User-Agent":"btc-lab-history/1.0","Cache-Control":"no-cache"})
    with urlopen(req,timeout=25) as response:
        raw=response.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError("Архив слишком большой")
    return json.loads(raw.decode("utf-8-sig"))

@st.cache_data(ttl=1800,show_spinner=False)
def collect_rolling():
    """Runs only while a Streamlit session is active; no background service."""
    errors={}
    for path in sorted(ROLLING):
        try:save_archive(path,load_history(path))
        except Exception as exc:errors[path]=type(exc).__name__
    return errors

def get_history_series(metric,doc=None):
    path=METRICS[metric][0]
    if path in ROLLING:
        if doc is not None:save_archive(path,doc)
        return saved_series(metric)
    return series_for(metric,doc if doc is not None else load_history(path))

def show_history_quality():
    st.header("Качество истории")
    st.caption("Проверка покрытия, не доказательство корректности методологии или доступности данных в момент сигнала. Пропуски считаются внутри ряда; для нерегулярных сессий календарь пока не проверяется.")
    if not st.button("Проверить все исторические ряды",key="history_audit_run"):
        st.info("Нажми кнопку, чтобы проверить все доступные архивы.")
        return
    rows=[]
    docs={}
    failures={}
    for metric,(path,_,freq,unit,note) in METRICS.items():
        row={"Показатель":metric,"Единица":unit}
        try:
            if path not in docs and path not in failures:
                try:docs[path]=load_history(path)
                except Exception as exc:failures[path]=type(exc).__name__
            if path in failures and path not in ROLLING:raise ValueError(failures[path])
            if path in ROLLING:
                if path in docs:save_archive(path,docs[path])
                s=saved_series(metric)
            else:s=series_for(metric,docs[path])
            info=coverage(s,freq)
            row.update({"Наблюдений":info["observations"],"Пропусков":info["gaps"],
                "Начало UTC":info["first"],"Конец UTC":info["last"],"Возраст последнего, д":info["lag_days"],
                "Статус":("нет данных" if not info["observations"] else "локальная копия" if path in failures or docs.get(path,{}).get("offline_copy") else "есть пропуски" if info["gaps"] else "есть наблюдения")})
        except Exception as exc:row["Статус"]="недоступно: "+type(exc).__name__
        rows.append(row)
    st.session_state["history_audit_rows"]=rows

def render_history_quality():
    show_history_quality()
    if st.session_state.get("history_audit_rows"):
        st.dataframe(pd.DataFrame(st.session_state["history_audit_rows"]),use_container_width=True,hide_index=True)
        st.caption("Возраст — от даты наблюдения, не от даты публикации. Строка «есть наблюдения» не означает, что ряд пригоден для бэктеста.")

def show_history(_brief=None):
    st.header("История рынка")
    st.caption("Данные из архивов агрегатора и дополнительных источников, UTC. Это визуальная проверка истории, не готовая выборка для бэктеста. Дата наблюдения не гарантирует дату публикации. Статус текущего снимка выше не подтверждает качество всей истории.")
    st.caption("Дополнительная история Kote и Coinalyze: один раз запусти download_history.bat, затем повторяй по необходимости. ETF загружается без ключа.")
    cols=st.columns([3,1])
    with cols[0]:
        metric=st.selectbox("Показатель",list(METRICS),key="history_metric")
    with cols[1]:
        period=st.selectbox("Период",["7 дней","30 дней","90 дней","1 год","Вся история"],index=1,key="history_period")
    days={"7 дней":7,"30 дней":30,"90 дней":90,"1 год":365,"Вся история":None}[period]
    path,_,freq,unit,note=METRICS[metric]
    st.caption(note)
    is_price=metric.startswith("Цена BTC")
    overlay=st.checkbox("Сопоставить с дневной ценой BTC",value=True,disabled=is_price,key="history_overlay") and not is_price
    try:
        with st.spinner("Загрузка исторического архива…"):
            try:archive=load_history(path)
            except Exception:
                if path not in ROLLING:raise
                archive=None
            full=get_history_series(metric,archive)
            shown=period_slice(full,days)
    except FileNotFoundError:
        st.info("Локальный архив ещё не загружен. Запусти download_history.bat, затем нажми «Обновить сейчас».")
        return
    except Exception as exc:
        st.error(f"Не удалось прочитать историю: {exc}")
        return
    if path in ROLLING:
        st.caption("Локально накопленная история. Последнее успешное получение: "+str(last_fetch(path) or "—"))
        if archive is None:st.warning("Источник недоступен; показан ранее накопленный ряд.")
    if path.startswith("local/"):
        st.markdown(f"[Источник: {archive.get('source','—')}]({archive.get('url','')})")
        st.caption(f"Получено: {archive.get('downloaded_utc','—')}. Архив может содержать поздние ревизии.")
        if archive.get("offline_copy"):st.warning("Сеть недоступна; используется последняя локальная копия ETF.")
    else:
        st.markdown(f"[Исходный файл](https://github.com/kh827y/btc-market-data/blob/main/{path})")
    if shown.empty or shown.notna().sum()==0:
        st.warning("В выбранном периоде нет пригодных наблюдений. Выбери больший период или проверь источник.")
        if full.notna().any():st.caption(f"Последняя пригодная дата во всём архиве: {full.dropna().index[-1]:%Y-%m-%d %H:%M} UTC")
        return
    valid=shown.dropna()
    c=st.columns(3)
    c[0].metric("Наблюдения",f"{len(valid):,}".replace(","," "))
    c[1].metric("Пропуски внутри ряда",str(int(shown.isna().sum())) if freq else "н/п")
    c[2].metric("Последнее значение",f"{valid.iloc[-1]:,.{4 if abs(valid.iloc[-1])<10 else 2}f} {unit}".replace(","," "))
    st.caption(f"Доступный ряд: {full.index[0]:%Y-%m-%d} — {full.index[-1]:%Y-%m-%d}. Последнее пригодное наблюдение в выбранном периоде: {valid.index[-1]:%Y-%m-%d %H:%M} UTC. Пропуски внутри ряда не включают время до/после доступного диапазона.")
    if freq and shown.isna().any():st.warning("В ряду есть пропущенные или неполные интервалы. Линия на них прерывается.")
    if freq is None:st.caption("Показаны только опубликованные наблюдения; календарь ожидаемых сессий пока не проверяется.")
    price=None
    if overlay:
        try:
            try:price=period_slice(series_for("Цена BTC · длинная история Binance",load_history(BINANCE_DAILY)),days)
            except Exception:price=period_slice(series_for("Цена BTC · закрытие дня",load_history(PRICE)),days)
            price=price.loc[(price.index>=shown.index.min().floor("D"))&(price.index<=shown.index.max())]
            if price.dropna().empty:price=None
        except Exception as exc:
            st.warning(f"Сравнение с ценой недоступно: {exc}")
    fig=make_subplots(rows=2 if price is not None else 1,cols=1,shared_xaxes=True,vertical_spacing=.09,subplot_titles=[metric]+(["BTC · закрытие дня, USDT"] if price is not None else []))
    if path in (CVD,ETF,FULL_ETF) or metric.startswith(("Ликвидации","CVD")):
        fig.add_trace(go.Bar(x=shown.index,y=shown.tolist(),name=metric,marker_color=["#33c9a4" if v>=0 else "#f07f6c" for v in shown]),row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=shown.index,y=shown.tolist(),mode="markers" if freq is None else "lines",name=metric,connectgaps=False,line=dict(color="#33c9a4"),marker=dict(size=5)),row=1,col=1)
    if price is not None:
        fig.add_trace(go.Scatter(x=price.index,y=price.tolist(),mode="lines",name="BTCUSDT",connectgaps=False,line=dict(color="#e3a04f")),row=2,col=1)
        fig.update_yaxes(title_text="USDT",row=2,col=1)
    fig.update_yaxes(title_text=unit,row=1,col=1)
    fig.update_layout(height=650 if price is not None else 430,showlegend=False,template="plotly_dark",hovermode="x unified",margin=dict(l=8,r=8,t=45,b=8),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig,use_container_width=True)
    with st.expander("Исходные наблюдения за выбранный период"):
        table=shown.rename("Значение").to_frame()
        table.index.name="Дата UTC"
        st.dataframe(table.sort_index(ascending=False),use_container_width=True)
        st.caption("Пустые значения — отсутствующие или не прошедшие базовые проверки. Полная проверка методологии для исследований ещё не выполнена.")
