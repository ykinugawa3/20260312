"""レース実況アニメーション用の「台本」を作る.

各馬の「時刻 → 走った距離」と実況テキストを計算し、画面側 (assets/race_view.html) に渡す。
位置はデータからの近似であり、実際のレースの位置取りを再現するものではない。

- simulate_race: 予想勝率から着順を抽選し、脚質に応じたペース配分で仮想レースを作る
- replay_race:   確定済みレースの走破タイムと上がり3Fから各馬の動きを再現する
どちらも「前半 (残り600mまで) を一定速度、後半を上がり3Fの速度」で走る単純なモデル。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ASSET = Path(__file__).parent / "assets" / "race_view.html"

LENGTH_M = 2.4          # 1 馬身 ≈ 2.4m
START_RAMP_S = 2.5      # スタートから巡航速度に達するまでの秒数
FRAME_DT = 0.2          # 台本のコマ間隔 (秒)
LEFT_HANDED = {"東京", "中京", "新潟"}  # 左回りの競馬場 (それ以外は右回り)

# JRA の枠色 (背景色, 文字色)
FRAME_COLORS = {
    1: ("#ffffff", "#111111"), 2: ("#222222", "#ffffff"), 3: ("#e60012", "#ffffff"),
    4: ("#1e5bc6", "#ffffff"), 5: ("#f5d400", "#111111"), 6: ("#1a9b48", "#ffffff"),
    7: ("#f08300", "#111111"), 8: ("#f5a0c0", "#111111"),
}


# ---------------------------------------------------------------- ペースと位置

def _realistic_last3f(total: np.ndarray, last3f: np.ndarray, distance: int) -> np.ndarray:
    """前半の速度が 13〜19 m/s に収まるよう上がり3Fを補正する (データの外れ値対策)."""
    early_dist = distance - 600
    # 上がりが遅いほど前半は速く走ったことになる
    lower = total - (early_dist / 13.0 + START_RAMP_S / 2)   # 前半 13 m/s のときの上がり
    upper = total - (early_dist / 19.0 + START_RAMP_S / 2)   # 前半 19 m/s のときの上がり
    return np.clip(last3f, np.maximum(lower, 30.0), np.minimum(upper, 45.0))


def distance_curves(total: np.ndarray, last3f: np.ndarray, distance: int, t: np.ndarray) -> np.ndarray:
    """各馬の時刻 t における走行距離 (行 = 馬, 列 = 時刻). ゴール後は 40m ほど流して止まる."""
    total = total[:, None]
    l3f = last3f[:, None]
    early = distance - 600
    t1 = total - l3f                                # 残り600m 地点の通過時刻
    v1 = early / (t1 - START_RAMP_S / 2)            # 前半の巡航速度
    v2 = 600 / l3f                                  # 上がりの速度
    tt = t[None, :]
    ramp = v1 * np.minimum(tt, START_RAMP_S) ** 2 / (2 * START_RAMP_S)
    cruise = v1 * np.clip(tt - START_RAMP_S, 0, None)
    d = np.where(tt <= t1, ramp + cruise, early + v2 * (tt - t1))
    # ゴール後は減速しながら最大 40m 進んで止まる
    after = np.clip(tt - total, 0, None)
    run_out = 40 * (1 - np.exp(-v2 * after / 40))
    d = np.where(tt <= total, d, distance + run_out)
    return d


def margin_text(meters: float) -> str:
    """距離差を「クビ差」「1馬身半」などの着差表現にする."""
    lengths = meters / LENGTH_M
    if lengths < 0.15:
        return "ハナ差"
    if lengths < 0.3:
        return "アタマ差"
    if lengths < 0.45:
        return "クビ差"
    if lengths < 0.65:
        return "半馬身"
    if lengths < 0.85:
        return "3/4馬身"
    if lengths >= 10:
        return "大差"
    whole = int(lengths + 0.125)
    frac = lengths - whole
    if frac >= 0.375:
        return f"{whole}馬身半" if whole else "半馬身"
    if frac >= 0.125:
        return f"{whole}馬身1/4"
    return f"{whole}馬身"


# ---------------------------------------------------------------- 脚質

def running_style_score(race: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """-1 (逃げ) 〜 +1 (追込). 過去5走の上がり順位比から推定し、無ければ乱数."""
    ratio = race.get("avg_last3f_rank_ratio_5")
    if ratio is None:
        ratio = pd.Series(np.nan, index=race.index)
    score = (1 - 2 * ratio.to_numpy(float))  # 上がりが速い (比が小さい) ほど後ろから
    missing = np.isnan(score)
    score[missing] = rng.uniform(-0.6, 0.6, missing.sum())
    return np.clip(score + rng.normal(0, 0.15, len(score)), -1, 1)


def style_labels(mid_rank: np.ndarray) -> list[str]:
    """中間地点での位置 (0 = 先頭) から 逃げ / 先行 / 差し / 追込 に分ける."""
    n = len(mid_rank)
    labels = []
    for r in mid_rank:
        if r == 0:
            labels.append("逃げ")
        elif r < max(2, round(n * 0.35)):
            labels.append("先行")
        elif r < round(n * 0.75):
            labels.append("差し")
        else:
            labels.append("追込")
    return labels


# ---------------------------------------------------------------- 台本

def _base_speed(race: pd.Series) -> float:
    v = 16.9 if race["surface"] == "芝" else 16.2
    v -= (race["distance"] - 1600) * 0.0006
    if race.get("track_condition") in ("重", "不良"):
        v *= 0.99 if race["surface"] == "芝" else 1.005  # ダートは脚抜きが良くなる
    return v


def sample_finish_order(win_prob: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """勝率に比例した Plackett-Luce モデルで着順を抽選する (Gumbel 法). 戻り値は着順 (1 始まり)."""
    keys = np.log(np.clip(win_prob, 1e-9, 1)) + rng.gumbel(size=len(win_prob))
    return (-keys).argsort().argsort() + 1


def simulate_race(race: pd.DataFrame, win_prob: np.ndarray, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    head = race.iloc[0]
    distance = int(head["distance"])
    n = len(race)
    order = sample_finish_order(win_prob, rng)
    style = running_style_score(race, rng)

    t_win = distance / _base_speed(head) * rng.normal(1, 0.004)
    # 着順ごとの勝ち馬からのタイム差 (1 着差あたり平均 0.17 秒 ≈ 1 馬身)
    finish_gap = np.concatenate([[0], np.cumsum(rng.exponential(0.17, n - 1))])
    total = t_win + finish_gap[order - 1]

    base_l3f = 600 / (distance / t_win) * (0.985 if head["surface"] == "芝" else 1.0)
    rank_ratio = (order - 1) / max(n - 1, 1)
    last3f = base_l3f - 0.45 * style + 0.4 * rank_ratio + rng.normal(0, 0.15, n)
    return _build(race, total, last3f, mode="simulation", note="予想勝率から抽選した仮想レース")


def replay_race(race: pd.DataFrame) -> dict:
    race = race[race["time_sec"].notna() & race["last_3f"].notna()]
    if race.empty:
        raise ValueError("走破タイムと上がり3Fのある馬がいません")
    total = race["time_sec"].to_numpy(float)
    last3f = race["last_3f"].to_numpy(float)
    return _build(race, total, last3f, mode="replay", note="走破タイムと上がり3Fから再現 (位置取りは近似)")


def _build(race: pd.DataFrame, total: np.ndarray, last3f: np.ndarray, mode: str, note: str) -> dict:
    head = race.iloc[0]
    distance = int(head["distance"])
    last3f = _realistic_last3f(total, last3f, distance)
    t = np.arange(0, total.max() + 4, FRAME_DT)
    d = distance_curves(total, last3f, distance, t)
    order = total.argsort().argsort() + 1
    # 表示上の脚質は、実際に描く隊列 (先頭が中間地点に来たときの位置) から決める
    mid = int(np.argmax(d.max(axis=0) >= distance * 0.5))
    labels = style_labels((-d[:, mid]).argsort().argsort())

    horses = []
    for i, (_, r) in enumerate(race.iterrows()):
        frame = int(r["frame_number"]) if pd.notna(r.get("frame_number")) else (int(r["horse_number"]) - 1) % 8 + 1
        bg, fg = FRAME_COLORS.get(frame, ("#888888", "#ffffff"))
        horses.append({
            "num": int(r["horse_number"]), "name": str(r["horse_name"]), "frame": frame,
            "bg": bg, "fg": fg, "mark": str(r.get("mark") or ""), "style": labels[i],
            "stake": float(r.get("stake") or 0), "odds": float(r["odds"]) if pd.notna(r.get("odds")) else None,
            "time": round(float(total[i]), 1), "finish": int(order[i]),
        })

    return {
        "mode": mode, "note": note,
        "title": f"{head['course']} {int(head['race_number'])}R {head['surface']}{distance}m "
                 f"{head.get('track_condition') or ''} {head.get('race_class') or ''}".strip(),
        "distance": distance,
        "left_handed": head["course"] in LEFT_HANDED,
        "dt": FRAME_DT,
        "positions": np.round(d, 1).tolist(),
        "horses": horses,
        "events": commentary(race, d, t, total, distance, horses),
    }


# ---------------------------------------------------------------- 実況

def gap_phrase(meters: float) -> str:
    """「ハナ差」「2馬身差」のように「差」を付けた表現."""
    text = margin_text(meters)
    return text if text.endswith("差") else text + "差"


def _who(h: dict) -> str:
    return f"{h['num']}番{h['name']}"


def commentary(race: pd.DataFrame, d: np.ndarray, t: np.ndarray, total: np.ndarray,
               distance: int, horses: list[dict]) -> list[dict]:
    """台本の時刻に合わせた実況テキスト."""
    events = [{"t": 0.0, "text": f"スタートしました！ {len(horses)}頭、各馬そろった好スタート。"}]

    def at(frame: int) -> tuple[np.ndarray, np.ndarray]:
        pos = d[:, frame]
        return pos, (-pos).argsort()

    def leader_frame(dist: float) -> int:
        idx = np.argmax(d.max(axis=0) >= dist)
        return int(idx)

    # 序盤: ハナを切った馬
    f = leader_frame(min(200, distance * 0.15))
    pos, rank = at(f)
    lead, second = horses[rank[0]], horses[rank[1]]
    events.append({"t": float(t[f]), "text": f"ハナを切ったのは{_who(lead)}。"
                   f"{gap_phrase(pos[rank[0]] - pos[rank[1]])}で{_who(second)}が続きます。"})

    # 中盤: 隊列
    f = leader_frame(distance * 0.5)
    pos, rank = at(f)
    front = "、".join(_who(horses[i]) for i in rank[1:3])
    last = horses[rank[-1]]
    span = f"約{max(1, round((pos[rank[0]] - pos[rank[-1]]) / LENGTH_M))}馬身"
    events.append({"t": float(t[f]), "text": f"中間地点、先頭は{_who(horses[rank[0]])}。"
                   f"その後ろに{front}。最後方は{_who(last)}、先頭から最後方まで{span}。"})

    # 残り600m: 4コーナー
    f = leader_frame(distance - 600)
    pos, rank = at(f)
    events.append({"t": float(t[f]), "text": f"残り600、4コーナーをカーブして先頭は{_who(horses[rank[0]])}！"
                   f"後続も差を詰めてくる！"})

    # 残り400m: 直線
    f = leader_frame(distance - 400)
    pos, rank = at(f)
    prev = d[:, max(f - int(4 / FRAME_DT), 0)]
    gain = (pos - prev) - (pos - prev)[rank[0]]
    charger = int(np.argmax(np.where(np.arange(len(horses)) == rank[0], -np.inf, gain)))
    events.append({"t": float(t[f]), "text": f"最後の直線！ 先頭は{_who(horses[rank[0]])}！"
                   f"外から{_who(horses[charger])}が伸びてくる！"})

    # 残り200m
    f = leader_frame(distance - 200)
    pos, rank = at(f)
    a, b = horses[rank[0]], horses[rank[1]]
    events.append({"t": float(t[f]), "text": f"残り200！ {_who(a)}か、{_who(b)}か！"
                   f"その差{margin_text(pos[rank[0]] - pos[rank[1]])}！"})

    # ゴール
    fin = total.argsort()
    w, s2, s3 = (horses[i] for i in fin[:3])
    m12 = gap_phrase((total[fin[1]] - total[fin[0]]) * distance / total[fin[0]])
    text = f"ゴール！ 1着は{_who(w)}！ {m12}の2着に{_who(s2)}、3着{_who(s3)}。"
    if w["mark"] == "◎":
        text += " 本命◎がきっちり勝ちました！"
    elif w["stake"] > 0:
        text += f" 推奨馬券的中！ 払戻 {w['stake'] * (w['odds'] or 0):,.0f} 円！"
    events.append({"t": float(total.min()), "text": text, "final": True})
    return events


def render_html(script: dict | list[dict]) -> str:
    """台本 (複数ならレース切り替え付き) を埋め込んだ HTML を返す."""
    html = ASSET.read_text(encoding="utf-8")
    # </script> を含む馬名などでスクリプトが途切れないようにする
    data = json.dumps(script, ensure_ascii=False).replace("</", "<\\/")
    return html.replace("__RACE_DATA__", data)
