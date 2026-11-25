"""Historical L2 charts with strict same-clock and full-band filters."""
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from depth_history import MARKETS,BANDS,archive_path,depth_frame,BYBIT
from history_logic import period_slice
from history_page import BASE
from extended_history import request_json

@st.cache_data(ttl=1800,show_spinner=False)
def load_depth(path):
    return request_json(BASE+path)

def show_depth():
    st.header("История стаканов")
    st.caption("Реальные исторические снимки лимитных заявок, не исполненные сделки и не средняя ликвидность за день. Спот и бессрочные контракты разделены.")
    c=st.columns([3,1,1])
    market=c[0].selectbox("Рынок",list(MARKETS),format_func=lambda k:MARKETS[k][0],key="depth_market")
    band=c[1].selectbox("Полоса от mid",BANDS,format_func=lambda k:f"±{k}%",key="depth_band")
    period=c[2].selectbox("Период",["30 дней","90 дней","1 год","Вся история"],index=1,key="depth_period")
    days={"30 дней":30,"90 дней":90,"1 год":365,"Вся история":None}[period]
    path=archive_path(market)
    if path==BYBIT:st.caption("Bybit: первый снимок 00:00 UTC + не более 180 секунд. Глубина архива менялась с 500 до 200 уровней; полная CRC ZIP не проверена.")
    else:st.caption("CryptoHFTData: строго 12:00 UTC ±30 минут. Снимки из других часов исключаются. Для OKX perpetual использован исторический множитель из агрегатора, не подтверждённый на все даты.")
    try:
        with st.spinner("Загрузка архива стаканов…"):
            full=depth_frame(load_depth(path),market,band)
            df=period_slice(full,days)
    except Exception as exc:
        st.error(f"Не удалось прочитать архив: {exc}")
        return
    st.markdown(f"[Исходный архив](https://github.com/kh827y/btc-market-data/blob/main/{path})")
    ok=df["bid"].notna() & df["ask"].notna()
    c=st.columns(3)
    c[0].metric("Полных снимков",int(ok.sum()))
    c[1].metric("Пропусков внутри ряда",int((~ok).sum()))
    c[2].metric("Доля покупок в последнем полном",f"{df.loc[ok,'share'].iloc[-1]:.1f}%" if ok.any() else "—")
    if not full.empty:
        st.caption(f"Диапазон архива: {full.index.min():%Y-%m-%d} — {full.index.max():%Y-%m-%d} UTC. Даты вне диапазона не считаются пропусками.")
    if ok.any():
        fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.1,subplot_titles=["Объём заявок в полосе","Доля bid"])
        for side,name,color in [("bid","Покупка","#33c9a4"),("ask","Продажа","#f07f6c")]:
            fig.add_trace(go.Scatter(x=df.index,y=df[side],mode="lines+markers",name=name,line=dict(color=color),marker=dict(size=3),connectgaps=False),row=1,col=1)
        fig.add_trace(go.Scatter(x=df.index,y=df["share"],mode="lines+markers",name="Доля bid",connectgaps=False,marker=dict(size=3)),row=2,col=1)
        fig.add_hline(y=50,line_dash="dot",row=2,col=1)
        fig.update_yaxes(title_text="USD ≈ USDT",row=1,col=1)
        fig.update_yaxes(title_text="%",range=[0,100],row=2,col=1)
        fig.update_layout(height=620,template="plotly_dark",hovermode="x unified",legend=dict(orientation="h"),margin=dict(l=8,r=8,t=45,b=8))
        st.plotly_chart(fig,use_container_width=True)
    else:st.warning("Нет полных сопоставимых снимков. Выбери более узкую полосу или другой период.")
    st.dataframe(df.rename(columns={"bid":"Bid, USD≈USDT","ask":"Ask, USD≈USDT","share":"Bid, %","snapshot":"Время снимка UTC","status":"Статус"}).sort_index(ascending=False),use_container_width=True)
