"""Historical page. Downloads only selected public archives, read-only."""
import json
from urllib.request import Request, urlopen
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from history_logic import METRICS, PRICE, ETF, CVD, FULL_ETF, period_slice, series_for
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
    overlay=st.checkbox("Сопоставить с дневной ценой BTC",value=True,disabled=path==PRICE,key="history_overlay") and path!=PRICE
    try:
        with st.spinner("Загрузка исторического архива…"):
            archive=load_history(path)
            full=series_for(metric,archive)
            shown=period_slice(full,days)
    except FileNotFoundError:
        st.info("Локальный архив ещё не загружен. Запусти download_history.bat, затем нажми «Обновить сейчас».")
        return
    except Exception as exc:
        st.error(f"Не удалось прочитать историю: {exc}")
        return
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
            price=period_slice(series_for("Цена BTC · закрытие дня",load_history(PRICE)),days)
            price=price.loc[(price.index>=shown.index.min().floor("D"))&(price.index<=shown.index.max())]
            if price.dropna().empty:price=None
        except Exception as exc:
            st.warning(f"Сравнение с ценой недоступно: {exc}")
    fig=make_subplots(rows=2 if price is not None else 1,cols=1,shared_xaxes=True,vertical_spacing=.09,subplot_titles=[metric]+(["BTC · закрытие дня, USDT"] if price is not None else []))
    if path in (CVD,ETF,FULL_ETF) or metric.startswith("Ликвидации"):
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
