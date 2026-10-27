"""天下布武 Lite (Phase 1) の Web UI.

起動:  streamlit run sengoku_app.py
"""

from __future__ import annotations

import math
import random

import altair as alt
import pandas as pd
import streamlit as st

from sengoku import data
from sengoku.engine import COMMAND_COST, RECRUIT_GOLD, CommandError, Game

NEUTRAL = "国人衆"
NEUTRAL_COLOR = "#c8c6bf"
EDGE_COLOR = "#d9d7d0"

st.set_page_config(page_title="天下布武 Lite", page_icon="🏯", layout="wide")


# ---------------------------------------------------------------- タイトル画面

def title_screen() -> None:
    st.title("天下布武 Lite")
    st.caption("1560年 桶狭間前夜 ― 60季節 (15年) のうちに天下統一を目指す")
    rows = []
    for name, leader, provs, _, _ in data.CLANS:
        koku = sum(p[1] for p in data.PROVINCES if p[0] in provs)
        rows.append({"大名家": name, "当主": leader, "国数": len(provs), "石高(万石)": koku,
                     "武将": sum(1 for g in data.GENERALS if g[1] == name)})
    table = pd.DataFrame(rows).sort_values("石高(万石)", ascending=False)
    st.dataframe(table, hide_index=True, width="content")

    labels = {f"{r['大名家']}家 ({r['当主']}・{r['国数']}か国)": r["大名家"] for r in rows}
    choice = st.selectbox("担当する大名家", list(labels), index=0)
    seed = st.number_input("乱数シード (0 = 毎回ちがう展開)", min_value=0, value=0, step=1)
    if st.button("この家で始める", type="primary"):
        st.session_state.game = Game(labels[choice], seed=int(seed) or random.randrange(1, 10**9))
        st.session_state.selected = st.session_state.game.generals[
            st.session_state.game.clans[labels[choice]].leader].province
        st.session_state.flash = []
        st.rerun()
    st.markdown(
        "**遊び方**: 地図で国を選び、武将ごとに1つ命令を出します (開墾・商業・築城・徴兵・出陣・移動・輸送)。"
        "命令を出し終えたら「季節を終える」。出陣した軍は季節の終わりにオート合戦で決着します。"
        "秋に兵糧が入り、商業からは毎季節に金が入ります。冬は雪国から/への出陣ができません。")


# ---------------------------------------------------------------- 地図

def owner_label(game: Game, prov: str) -> str:
    return game.provinces[prov].owner or NEUTRAL


def map_chart(game: Game, selected: str) -> alt.LayerChart:
    provs = pd.DataFrame([{
        "name": p.name, "lon": p.lon, "lat": p.lat, "勢力": p.owner or NEUTRAL, "兵": p.troops,
        "農業": f"{p.farm}/{p.farm_max}", "商業": f"{p.commerce}/{p.commerce_max}", "防御": p.defense,
        "縁": "#111111" if p.name == selected or p.owner == game.player else "transparent",
        "縁の太さ": 3.5 if p.name == selected else 1.5,
    } for p in game.provinces.values()])
    edges = pd.DataFrame([{
        "lon": game.provinces[a].lon, "lat": game.provinces[a].lat,
        "lon2": game.provinces[b].lon, "lat2": game.provinces[b].lat,
    } for a in game.adj for b in game.adj[a] if a < b])

    domain = [c.name for c in game.clans.values()] + [NEUTRAL]
    colors = [c.color for c in game.clans.values()] + [NEUTRAL_COLOR]
    x = alt.X("lon:Q", scale=alt.Scale(domain=[129.7, 141.6]), axis=None)
    y = alt.Y("lat:Q", scale=alt.Scale(domain=[31.2, 39.4]), axis=None)
    pick = alt.selection_point(name="prov", fields=["name"], on="click", clear=False)

    lines = alt.Chart(edges).mark_rule(color=EDGE_COLOR, strokeWidth=1).encode(
        x=x, y=y, x2="lon2:Q", y2="lat2:Q")
    dots = alt.Chart(provs).mark_circle(opacity=0.95).encode(
        x=x, y=y,
        color=alt.Color("勢力:N", scale=alt.Scale(domain=domain, range=colors), legend=None),
        size=alt.Size("兵:Q", scale=alt.Scale(range=[60, 700], zero=True), legend=None),
        stroke=alt.Stroke("縁:N", scale=None),
        strokeWidth=alt.StrokeWidth("縁の太さ:Q", scale=None),
        tooltip=["name", "勢力", "兵", "農業", "商業", "防御"],
    ).add_params(pick)
    labels = alt.Chart(provs).mark_text(dy=-13, fontSize=10, color="#555555").encode(
        x=x, y=y, text="name")
    return (lines + dots + labels).properties(width=660, height=560).configure_view(stroke=None)


def clan_cell_style(game: Game):
    def style(value: str) -> str:
        clan = game.clans.get(str(value).removesuffix("家"))
        color = clan.color if clan else NEUTRAL_COLOR
        return f"background-color: {color}; color: white; font-weight: 600"
    return style


# ---------------------------------------------------------------- 国の情報と命令

def province_panel(game: Game, prov: str) -> None:
    p = game.provinces[prov]
    st.subheader(f"{p.name} ({owner_label(game, prov)})")
    cols = st.columns(2)
    cols[0].progress(min(p.troops / max(game.max_troops(prov), 1), 1.0),
                     text=f"兵 {p.troops} / 上限 {game.max_troops(prov)}")
    cols[1].progress(p.defense / 1000, text=f"城の防御 {p.defense} / 1000")
    cols[0].progress(p.farm / p.farm_max, text=f"農業 {p.farm} / {p.farm_max}")
    cols[1].progress(p.commerce / p.commerce_max, text=f"商業 {p.commerce} / {p.commerce_max}")
    st.caption(f"石高 {p.kokudaka}万石 ・ 隣国: {'、'.join(game.neighbors(prov))}"
               + (" ・ 雪国" if p.snow else ""))

    gens = game.generals_in(prov)
    if gens:
        st.dataframe(pd.DataFrame([{
            "武将": g.name, "統率": g.leadership, "武勇": g.valor, "知略": g.intellect, "政治": g.politics,
            "今季": "済" if g.acted else "未",
        } for g in sorted(gens, key=lambda g: -g.leadership)]), hide_index=True, width="stretch")
    else:
        st.caption("武将はいない")

    if p.owner == game.player and game.status == "playing":
        command_form(game, prov)


def command_form(game: Game, prov: str) -> None:
    p = game.provinces[prov]
    idle = sorted(game.idle_generals(prov), key=lambda g: -g.leadership)
    if not idle:
        st.info("この国の武将は今季の行動を終えている")
        return
    with st.container(border=True):
        st.markdown("**命令**")
        names = {f"{g.name} (統率{g.leadership} 政治{g.politics})": g.name for g in idle}
        general = names[st.selectbox("武将", list(names), key=f"gen_{prov}")]
        g = game.generals[general]
        actions = ["開墾", "商業", "築城", "徴兵", "出陣", "移動", "輸送"]
        action = st.radio("内容", actions, horizontal=True, key=f"act_{prov}")
        own_neighbors = [n for n in game.neighbors(prov) if game.provinces[n].owner == game.player]
        run = None

        if action in ("開墾", "商業", "築城"):
            ability = "統率" if action == "築城" else "政治"
            st.caption(f"金 {COMMAND_COST}。上がり幅は{ability}で決まる")
            run = {"開墾": game.develop, "商業": game.trade, "築城": game.fortify}[action]
            run = (lambda f=run: f(general))
        elif action == "徴兵":
            amount = game.recruit_amount(general)
            st.caption(f"{amount} 人 (金 {math.ceil(amount * RECRUIT_GOLD)})。人数は政治で決まり、上限は農業 × 8")
            run = lambda: game.recruit(general)
        elif action == "出陣":
            targets = game.attack_targets(prov)
            if not targets:
                st.warning("攻め込める隣国がない (冬の雪国は出陣できない)")
            elif p.troops < 100:
                st.warning("兵が100人未満のため出陣できない")
            else:
                def fmt(t: str) -> str:
                    tp = game.provinces[t]
                    return f"{t} ({owner_label(game, t)}・兵 {tp.troops}・防御 {tp.defense})"
                target = st.selectbox("攻める国", targets, format_func=fmt, key=f"tgt_{prov}")
                troops = st.slider("率いる兵", 100, p.troops, max(100, int(p.troops * 0.8)), step=50,
                                   key=f"att_{prov}") if p.troops > 100 else p.troops
                ratio = troops * (1 + g.leadership / 100) / max(game.defense_strength(target), 1)
                st.caption(f"戦力比 {ratio:.2f} (目安: 1.5 以上で優勢) ・ 兵糧 {game.march_food(troops)}")
                run = lambda: game.attack(general, target, troops)
        else:
            if not own_neighbors:
                st.warning("隣接する自国がない")
            else:
                dest = st.selectbox("行き先", own_neighbors, key=f"dst_{prov}")
                low = 0 if action == "移動" else 1
                troops = st.slider("送る兵", low, p.troops, max(low, p.troops // 2 if action == "輸送" else 0),
                                   key=f"mv_{prov}_{action}") if p.troops > low else p.troops
                with_general = action == "移動"
                st.caption("武将が兵を連れて移る" if with_general else "武将は残り、兵だけを送る")
                if action == "輸送" and troops == 0:
                    st.warning("送る兵がいない")
                else:
                    run = lambda: game.move(general, dest, troops, with_general=with_general)

        if st.button("実行", type="primary", disabled=run is None, key=f"run_{prov}"):
            try:
                st.session_state.flash.append(run())
                st.rerun()
            except CommandError as e:
                st.error(str(e))


# ---------------------------------------------------------------- 報告・勢力・家臣

def report_tab(game: Game) -> None:
    if not game.reports:
        st.caption("まだ報告はない。命令を出したら「季節を終える」を押す")
        return
    report = game.reports[-1]
    st.markdown(f"**{report.label} の報告**")
    for line in report.events:
        st.write("・" + line)
    if report.battles:
        def mine(b) -> bool:
            return game.player in (b.attacker, b.defender)
        rows = [{
            "自家": "◎" if mine(b) else "",
            "国": b.province,
            "攻撃": f"{b.attacker}家 {b.att_general}",
            "攻撃兵": f"{b.att_start} → {b.outcome.attacker_left}",
            "守備": f"{b.defender + '家' if b.defender else NEUTRAL} {b.def_general or ''}",
            "守備兵": f"{b.def_start} → {b.outcome.defender_left}",
            "結果": "攻略" if b.outcome.attacker_won else "撃退",
        } for b in sorted(report.battles, key=lambda b: not mine(b))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("合戦はなかった")


def clans_tab(game: Game) -> None:
    rows = sorted(({
        "勢力": f"{c.name}家", "当主": c.leader, "国数": len(game.owned(c.name)),
        "兵": game.clan_troops(c.name), "金": c.gold, "兵糧": c.food, "武将": len(game.members(c.name)),
    } for c in game.alive_clans()), key=lambda r: (-r["国数"], -r["兵"]))
    df = pd.DataFrame(rows)
    st.dataframe(df.style.map(clan_cell_style(game), subset=["勢力"]), hide_index=True, width="stretch")
    fallen = [c.name for c in game.clans.values() if not c.alive]
    if fallen:
        st.caption("滅亡: " + "、".join(f"{n}家" for n in fallen))


def retainers_tab(game: Game) -> None:
    marching = {a.general: a for a in game.armies}
    rows = []
    for g in sorted(game.members(game.player), key=lambda g: -g.leadership):
        state = f"出陣中 → {marching[g.name].target}" if g.name in marching else ("済" if g.acted else "未行動")
        rows.append({"武将": g.name, "所在": g.province or "", "統率": g.leadership, "武勇": g.valor,
                     "知略": g.intellect, "政治": g.politics, "今季": state})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------------------------------------------------------------- メイン画面

def main_screen(game: Game) -> None:
    clan = game.clans[game.player]
    head = st.columns([2, 1, 1, 1, 1, 1])
    head[0].markdown(f"## {game.player}家 ・ {game.date_label}")
    head[1].metric("季節", f"{min(game.turn + 1, data.TOTAL_TURNS)} / {data.TOTAL_TURNS}")
    head[2].metric("国", len(game.owned(game.player)))
    head[3].metric("兵", game.clan_troops(game.player))
    head[4].metric("金", clan.gold)
    head[5].metric("兵糧", clan.food)

    if game.status != "playing":
        (st.success if game.status == "won" else st.error)(game.result)
        if st.button("タイトルへ戻る", type="primary"):
            del st.session_state.game
            st.rerun()

    for msg in st.session_state.flash:
        st.toast(msg)
    st.session_state.flash = []

    left, right = st.columns([3, 2])
    with left:
        event = st.altair_chart(map_chart(game, st.session_state.selected), on_select="rerun", key="map",
                                selection_mode="prov")
        picked = (event.selection.get("prov") or [{}])[0].get("name") if event else None
        if picked != st.session_state.get("last_pick"):
            st.session_state.last_pick = picked
            if picked:
                st.session_state.selected = picked
                st.rerun()
        st.caption("国をクリックで選択。丸の大きさは兵数。黒い縁は自国、太い縁は選択中の国")
    with right:
        # 選択肢と表示名は固定にする (持ち主が変わるたびに選択肢を変えると、表示が古いまま残る)
        st.selectbox("国を選ぶ", list(game.provinces), key="selected")
        own = [p.name for p in game.owned(game.player)]
        waiting = [f"{n} {len(game.idle_generals(n))}人" for n in own if game.idle_generals(n)]
        if waiting and game.status == "playing":
            st.caption("未行動の武将がいる自国: " + "、".join(waiting))
        province_panel(game, st.session_state.selected)

        if game.status == "playing":
            idle = sum(len(game.idle_generals(p)) for p in own)
            b1, b2 = st.columns(2)
            if b1.button(f"未行動の武将 {idle} 人を委任", disabled=idle == 0, width="stretch",
                         help="AI が内政・出陣を代わりに決める"):
                game.delegate()
                st.session_state.flash.append("残りの武将に命令を任せた")
                st.rerun()
            if b2.button("季節を終える", type="primary", width="stretch"):
                game.end_turn()
                st.rerun()

    tabs = st.tabs(["報告", "勢力", "家臣"])
    with tabs[0]:
        report_tab(game)
    with tabs[1]:
        clans_tab(game)
    with tabs[2]:
        retainers_tab(game)


if "game" not in st.session_state:
    title_screen()
else:
    main_screen(st.session_state.game)
