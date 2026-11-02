# Japan Pocket Guide (Android)

訪日外国人旅行者向けのオフライン旅行アシスタントアプリ。ネット接続も特別な権限も不要。

## 機能

| タブ | 内容 |
| --- | --- |
| 会話 (Phrases) | 基本・飲食店・買い物・交通・宿泊・緊急の 6 カテゴリ、約 40 の日本語フレーズ。ローマ字つき。🔊 で端末の音声合成が日本語で読み上げ、⛶ で店員に見せる大きな文字の画面を表示。全言語で検索可 |
| 金額 (Money) | 円 ⇄ 外貨 (USD/EUR/GBP/CNY/TWD/HKD/KRW/THB/SGD/AUD) の換算。レートは編集でき端末に保存。消費税・免税・現金/ATM の案内 |
| マナー (Manners) | チップ不要、電車内、行列、ゴミ、靴、温泉、箸、食べ歩き、エスカレーター、IC カード |
| SOS | 110 / 119 / Japan Visitor Hotline (050-3816-2787) をタップで発信画面へ。地震時の行動、緊急フレーズ |

- 表示言語: English / 简体中文 / 繁體中文 / 한국어 (端末の言語から自動選択、右上で切替)
- 日本語の文字は `ja-JP` ロケールで描画 (中国語・韓国語の端末でも日本の字形で表示)
- 最低 Android 8.0 (API 26)

## APK の入手 (PC 不要)

`android/` を変更して push すると GitHub Actions がテストとビルドを実行する。

1. GitHub のリポジトリ → **Actions** → **Android app** → 最新の実行を開く
2. 下部の **Artifacts** から `japan-pocket-guide-debug-apk` をダウンロードして展開
3. `app-debug.apk` をスマホに送って開く (「提供元不明のアプリ」を許可)

## 自分でビルドする場合

Android Studio で `android/` フォルダを開いて ▶ Run。コマンドラインなら (JDK 17 と Android SDK が必要):

```bash
cd android
./gradlew testDebugUnitTest assembleDebug
```

## 構成

```
app/src/main/java/io/github/ykinugawa3/japanguide/
  i18n/   Lang (対応言語), L (4 言語の文字列), S (UI 文言)
  data/   Phrasebook (フレーズ), Tips (マナー・買い物), Money (通貨と換算)
  ui/     App (タブと言語切替), Screens, Components, Theme
  Platform.kt   設定保存 (SharedPreferences) と音声合成 (TextToSpeech)
```

フレーズや言語を追加するときは `data/` と `i18n/S.kt` を編集する。
`ContentTest` が全言語の訳抜けをチェックする。

## 注意

- 内蔵の為替レートは目安。免税制度は 2026 年 11 月から還付方式に変わったため、細部は公式情報で確認すること
- 読み上げには端末に日本語音声データが必要 (無い場合はアプリ内から導入画面を開ける)
- Google Play で公開するにはリリース用の署名鍵の作成が別途必要
