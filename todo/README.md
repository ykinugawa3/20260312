# TODO アプリ (Streamlit + SQLite)

自分用のシンプルな TODO 管理アプリ。PC のブラウザと、同じ Wi-Fi のスマホから使える。

## 使い方

**Windows**: リポジトリ直下の **`start_todo.bat`** をダブルクリック。
初回はライブラリの導入に数分かかり、その後ブラウザで `http://localhost:8502` が開く。
スマホからは、起動時に表示される `Network URL` (`http://192.168.x.x:8502`) を開く。

**コマンド**:

```bash
pip install -e '.[dev,ui]'
streamlit run todo/app.py --server.port 8502
pytest tests/test_todo_db.py
```

データは `data/todo.db` (SQLite) に保存される。バックアップはこのファイルをコピーすればよい。

## 機能 (MVP)

| 画面 | 内容 |
|---|---|
| 📅 今日 | 期限切れ + 今日が期限の未完了タスク (優先度順)。上部ですばやく追加 |
| 📋 一覧 | 状態・タグ・優先度・キーワードで絞り込み、期限順 / 優先度順で並べ替え |
| ✔️ 完了履歴 | 完了日ごとに表示。チェックを外すと未完了に戻る |

- タスクは タイトル・期限・優先度 (🔴高 / 🟡中 / ⚪低)・タグ・メモ を持つ
- チェックで完了、「編集」から内容変更・削除
- 期限切れは赤字、今日が期限はオレンジで表示。サイドバーに期限切れの件数を警告

## 構成

```
todo/
  db.py    SQLite のスキーマと読み書き (画面から独立していてテスト可能)
  app.py   Streamlit の画面
tests/test_todo_db.py
start_todo.bat
```

`tasks` テーブルの列: `id, title, note, due_date, priority, tags, done, created_at, completed_at`。
列を追加するときは `db.py` の `MIGRATIONS` に `ALTER TABLE` 文を足すと、既存の DB も自動で更新される。

## 今後の拡張案

1. くり返しタスク (毎日・毎週・毎月) — `recurrence` 列を追加し、完了時に次回分を作る
2. サブタスク (チェックリスト) — `parent_id` 列
3. 振り返り画面 — 週ごとの完了数グラフ、連続達成日数
4. 見積もりと実績の比較 — `estimate_min` / `actual_min` 列
5. CSV の書き出し・読み込み
6. AI によるタスク分解、Google カレンダー連携
