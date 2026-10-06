# 株価予想ソフト (米国株) — Phase 1

企画案は [`../STOCK_PROPOSAL.md`](../STOCK_PROPOSAL.md)。
「明日上がるか」ではなく **今後 20 営業日で S&P 500 (SPY) をどれだけ上回るかの銘柄間の順位** を予測する。

## Windows での使い方 (ダブルクリック)

1. [Python](https://www.python.org/downloads/) 3.10 以上をインストールする (最初の画面で **Add python.exe to PATH** にチェック)
2. `stock` フォルダの **`setup.bat`** をダブルクリック (初回のみ。ライブラリの導入・仮データ作成・学習)
3. **`predict.bat`** をダブルクリックすると、最新日の銘柄ランキングが表示される

実データ (yfinance) を使うときは、黒い画面 (コマンドプロンプト) で次を実行してから `predict.bat` を開く:

```bat
cd stock
.venv\Scripts\activate
kabu --db data\real.db fetch --universe sp500 --start 2010-01-01
kabu --db data\real.db train
kabu --db data\real.db predict
```

## 使い方 (コマンド)

```bash
cd stock
pip install -e '.[dev,fetch]'

# 1. データ投入
kabu sample                                    # 仮データ (ネット不要) を data/kabu.db に投入
kabu sample --csv-dir out/                     # 見本の CSV も書き出す
kabu fetch --tickers AAPL MSFT NVDA --start 2015-01-01   # yfinance から取得 (SPY は自動で追加)
kabu fetch --universe sp500 --start 2010-01-01           # S&P 500 の現在の構成銘柄 (Wikipedia の一覧)
kabu import prices.csv --securities securities.csv --membership membership.csv   # 自分で用意した CSV
kabu check --calendar                          # 欠損日・急変動などのチェック (NYSE の取引日と照合)

# 2. 検証: 指定日より前で学習し、以降をベースラインと比較
kabu evaluate --test-start 2025-01-01
kabu evaluate --test-start 2025-01-01 --top-n 30 --cost-bps 20 --objective lambdarank

# 3. 全期間で学習して models/rank_model.pkl に保存
kabu train

# 4. 最新日 (または指定日) の銘柄ランキング
kabu predict --top-n 20 --output ranking.csv
kabu predict --date 2026-06-30
```

`--db data/real.db` のように DB ファイルを分ければ、仮データと実データを使い分けられる。

## 仕組み

1. **取り込み**: 株価は **調整前** の値で保存し、分割・配当は別のテーブルに持つ。
   yfinance の値は分割調整済みなので、分割の記録を使って調整前に戻してから保存する。
   同じ銘柄・日付は上書きするので、何度取り込んでも結果は同じ。
2. **調整後株価** (`kabu/adjust.py`): 分割・配当から毎回計算する (配当再投資ベースのトータルリターン)。
3. **対象銘柄**: 各日付に指数 (SP500) の構成銘柄だった銘柄のみ。1 年分の株価があり、終値 5 ドル以上。
4. **特徴量** (`kabu/features.py`): 過去リターン (5〜250 日)・12-1 ヶ月モメンタム・移動平均乖離・52 週高安値の位置・
   ボラティリティ・下方ボラ・ベータ・RSI・ボリンジャー位置・出来高比・売買代金。
   その日の引け後に分かる値だけを使い、**日ごとの順位 (0〜1)** に直してモデルに渡す。
5. **目的変数**: 翌営業日の寄付で買い、20 営業日後の寄付で売ったときの対 SPY 超過リターン。
   期間中に上場廃止した銘柄は最後の終値で清算したものとする (廃止による損失を検証から落とさない)。
6. **モデル** (`kabu/model.py`): LightGBM。既定は目的変数の日ごとの順位を当てる回帰 (`rank_regression`)。
   順位学習 (`lambdarank`) も選べるが、仮データでは値動きの大きい銘柄に偏り IC がほぼ 0 だった。
7. **評価** (`kabu/evaluate.py`): ベースライン (12-1 ヶ月モメンタム、モメンタム + 短期反転 + 低ボラの複合) と並べて表示。
   - **IC**: 日ごとの予測スコアと実際の超過リターンの順位相関。株式では 0.02〜0.05 でも有用とされる
   - **IC t値**: 20 日おきの IC だけで計算 (期間が重なる日同士は独立でないため)
   - **簡易ポートフォリオ**: 20 営業日ごとに上位 N 銘柄を等金額で入れ替え、片道コストを差し引く
   - 学習期間と検証期間の境目では、目的変数の期間が重ならないよう手前 21 営業日を学習から外す (パージ)

### 仮データでの結果の例

`kabu sample --seed N` (300 銘柄・指数 200 銘柄・2000 営業日) → `kabu evaluate --test-start 2025-01-01`
(検証期間 2025-01〜2026-09、上位 20 銘柄・片道コスト 10bp):

| 乱数シード | 指標 | LightGBM | モメンタム | 複合ファクター |
|---|---|---|---|---|
| 0 | IC 平均 / シャープ | +0.074 / 1.69 | +0.049 / 1.34 | +0.057 / 1.50 |
| 1 | IC 平均 / シャープ | +0.045 / 0.25 | +0.008 / 0.22 | +0.060 / 1.20 |
| 2 | IC 平均 / シャープ | +0.076 / 1.36 | +0.047 / 0.68 | +0.072 / 1.38 |

LightGBM は単純なモメンタムには毎回勝つが、**複合ファクターには勝ったり負けたりで、安定して上回るとは言えない**。
実データでもまずこの比較で「機械学習を使う意味があるか」を確かめる。
**数字は仮データの設定 (`kabu/sample_data.py` 冒頭) 次第で変わるもので、実データで同じ成績が出ることを意味しない。**
また特徴量の重要度でベータが上位に来ることがあるのは、検証期間の相場が上昇基調で
「値動きの大きい銘柄ほど SPY に勝ちやすかった」ためで、相場が下がる局面では逆に働く。

## CSV の形式

- `prices.csv`: `ticker, date, open, high, low, close, volume` (調整前の値)。
  `split_ratio` (2 分割なら 2)・`dividend` (1 株あたり) 列があれば分割・配当としても取り込む
- `securities.csv` (任意): `ticker, name, sector, listed_date, delisted_date`
- `actions.csv` (任意): `ticker, date, split_ratio, dividend`
- `membership.csv` (任意): `ticker, start_date, end_date` (指数の構成銘柄履歴。無ければ全銘柄が対象)
- ベンチマークとして **`SPY` の株価が必要**

## 構成

| ファイル | 役割 |
|----------|------|
| `kabu/db.py` | SQLite スキーマと入出力 |
| `kabu/importer.py` | 取り込み・データチェック (重複・異常値・分割なしの急変動・取引日の欠損) |
| `kabu/sources.py` | yfinance からの取得と調整前への変換、Wikipedia の S&P 500 一覧 |
| `kabu/adjust.py` | 分割・配当からの調整後株価 |
| `kabu/sample_data.py` | 開発用の仮データ (分割・配当・上場廃止・新規上場・指数の入替あり) |
| `kabu/features.py` | 特徴量・目的変数・対象銘柄の絞り込み |
| `kabu/model.py` | LightGBM の学習・保存・予測 |
| `kabu/evaluate.py` | IC・分位スプレッド・簡易ポートフォリオ・ベースライン |
| `kabu/cli.py` | コマンドライン |

## 現時点の制約

- **yfinance は動作確認・開発用**。非公式のため使えなくなることがあり、上場廃止銘柄も取れない。
  `--universe sp500` は **現在の** 構成銘柄だけなので、過去の検証成績は実際より良く見える (生存者バイアス)。
  本格的な検証には上場廃止銘柄と構成銘柄の入替履歴を含むデータ (Sharadar / Norgate など) が必要 (Phase 2)。
- 検証は 1 回の分割 (`--test-start` の前後) のみ。月ごとに再学習するウォークフォワード検証は Phase 2。
- 簡易ポートフォリオは、保有期間中の比率の変化・約定できる量・為替手数料を考慮していない。
- 財務データ (SEC EDGAR)・円建て成績・Web 画面は Phase 2 以降。
