# 開発・スクリプト

[ドキュメント一覧](README.md) / [使い方](usage.md) / [内部処理](implementation.md)

## 開発環境

`pyproject.toml` の対応範囲はPython 3.11以上3.15未満です。通常の起動スクリプトと開発手順は、検証済みのPython 3.12を選びます。LinuxはWaylandまたはX11のデスクトップ環境が必要です。Windows向けスクリプトはありますが、実機試験は未実施です。

依存はNumPy、PySide6、pyqtgraph、開発用にpytestです。ビルドバックエンドはhatchlingです。`uv.lock` に解決済みの版を記録し、通常は `--locked` を付けて同期・起動します。

```bash
uv sync --locked --python 3.12 --group dev
uv run --locked --python 3.12 yokogawa-tool demo/0000.WVF
```

`uv.lock` は依存を揃えるためのファイルです。依存を変更するときだけ `pyproject.toml` を編集して `uv lock` し、テストと起動を再確認してください。`.venv/` は生成物なので、別PCには持ち運びません。初回のPython・依存の取得にはインターネット接続が必要です。

## ディレクトリ

```text
src/yokogawa_tool/   アプリ本体
  app.py            コンソール起動の入口
  core/             波形モデル・ファイル入出力・Math・測定・補間
  acquisition/      DL1640通信・設定・本体画面の取得
  protocols/        共通注釈と論理値化・sigrok・EnDat内蔵復号
  gui/              ウィンドウ・各パネル・描画・テーマ・表示状態
tests/              数値処理・通信・Qt UIの自動テスト
scripts/            描画速度の比較・Linuxビルド用スクリプト
packaging/          凍結実行の入口・配布先README・Ubuntuビルド設定・ライセンス
demo/               MITで公開する数式由来の合成WVF/HDR
samples/            ローカル専用の元サンプル（公開・配布しない）
docs/               この文書と画面例
captures/           この作業環境で取得した波形（配布対象外）
dist/               uv buildの生成物（Git対象外）
```

`captures/` や追加の `.scope.npz / .scope.json` は、取得・保存時にできるローカルデータです。新しい環境やソース配布に存在するとは限りません。

## 各スクリプトの動作

### `run.sh`

Linux用のBash起動スクリプトです。

```bash
bash run.sh
bash run.sh demo/0000.WVF
bash run.sh --help
```

`set -euo pipefail` を指定し、スクリプト自身のディレクトリへ移動します。`uv` の存在を確認してから `exec uv run --locked --python 3.12 yokogawa-tool "$@"` を実行し、渡された引数をそのままアプリに渡します。終了コードもアプリのものになります。相対ファイルパスはプロジェクト直下を基準に解決されるため、別ディレクトリの波形には絶対パスを渡すと確実です。スクリプトはアプリの再実装ではなく、ロック済み環境で起動する入口です。

### `run.cmd`

Windows用の起動スクリプトです。`cd /d "%~dp0"` で自分のディレクトリへ移動し、`where uv` で確認後、`uv run --locked --python 3.12 yokogawa-tool %*` を実行します。`uv` がない場合は案内を出して停止します。

```bat
run.cmd
run.cmd demo\0000.WVF
```

### `src/yokogawa_tool/__main__.py` とコンソールコマンド

`__main__.py` は `gui.app.main()` を呼びます。`pyproject.toml` の `[project.scripts]` に定義した `yokogawa-tool` も同じ関数を呼ぶため、以下は同じ起動処理です。

```bash
uv run --locked --python 3.12 yokogawa-tool demo/0000.WVF
uv run --locked --python 3.12 python -m yokogawa_tool demo/0000.WVF
```

`gui.app.main()` はargparseで任意のファイル引数1個を受け取り、`QApplication` を作り、テーマを設定して `MainWindow` を表示します。ファイル指定があれば読み込んでからイベントループに入ります。`--help` はQtの画面を作らずに説明を表示します。

### `scripts/benchmark-render.py`

同じ波形・アンチエイリアスONで描画経路を比較する開発用スクリプトです。通信は行いません。

```bash
uv run --locked --python 3.12 python scripts/benchmark-render.py
```

プロジェクトの `src` をインポート対象にし、ウィンドウを作成、`demo/0000.WVF` を開きます。線分描画モード `auto` と `on` について、X幅を0.88倍ずつ12回変更し、イベント処理を含む経過時間を `time.perf_counter()` で表示します。AAの元の設定を戻して終了します。

実際のGUI環境で測る用途です。オフスクリーンでも実行できますが、通常画面の体感速度とは条件が異なります。結果はGPU、画面サイズ、Qtのバックエンド、CPUなどに依存し、固定の速度保証やテストの合否判定には使いません。

### `scripts/benchmark-dense.py`

```bash
QT_QPA_PLATFORM=offscreen uv run --locked --python 3.12 python scripts/benchmark-dense.py
```

2CH・各10,020点の密集した方形波とノイズを生成し、2048×1126のウィンドウで全体表示と中間倍率を比較します。従来の「表示点数が画面幅以上」の判定と、現在の線の総延長による判定で各4回の更新・イベント処理・実描画を計測し、中央値と全計測値をJSONで表示します。通信せず、最後にAA設定を戻します。実機の取得周期や転送時間は測定しません。

## テスト

```bash
uv sync --locked --python 3.12 --group dev
uv run --locked --python 3.12 pytest -q
```

画面のないLinux環境ではQtのoffscreenプラットフォームを指定します。

```bash
QT_QPA_PLATFORM=offscreen uv run --locked --python 3.12 pytest -q
```

テストは模擬通信を使うため、実機を接続しなくても実行できます。`tests/conftest.py` で実際のソケット接続を禁止し、GUIの自動更新タイマーからも実機へアクセスしないようにしています。通信単体テストはこの接続関数を各自の模擬ソケットへ置き換えます。

| テストファイル | 主な検証対象 |
|---|---|
| `test_waveform.py` | 6組の合成サンプル、エンディアン・配置、欠損、破損、CSV、セッション、最寄り点 |
| `test_wvf_export.py` | 6組の合成WVF再出力、FS8バイト配置・振幅精度、異なる時間軸、NaN/Inf、不等間隔・不正名の拒否、ペア置換失敗時の復元 |
| `test_rendering.py` | 密集した遷移と滑らかな波形・NaN間隙の区別、拡大での通常描画復帰、ピーク・元サンプル・保存値の保持 |
| `test_interpolation.py` | 非等間隔の単調3次補間、節点・単調性・欠損保持、密集時の抑止、元サンプルとセッションの保持 |
| `test_sampling_info.py` | 本体設定とレコードのFsの区別、取得点数表示、CH切替時の遅延応答、電流単位・固定高・接続先変更時の値破棄 |
| `test_todo_controls.py` | 更新周期の永続化、詳細操作の折り畳み、暗色背景の独立指定、復号結果とCSV・波形移動、WorkerからのLCD復元失敗通知 |
| `test_endat.py` | TI参照CRCの固定値、EnDat 2.1/2.2位置・F1/F2・追加情報、パラメーター、異常系、遅延・極性、内蔵解析UI |
| `test_protocols.py` | 論理ビット列・入力条件・JSON時刻の復元、外部sigrok実行によるUART/SPI/I2C/CANの合成波形検証 |
| `test_measurements.py` | 台形波・正弦波・狭パルス、周期・デューティ・10–90%時間、欠損・ノイズ・微小振幅、非等間隔時刻 |
| `test_measurement_gui.py` | 測定項目の表示選択、設定保存、表示範囲・全体・A–B間の切替、元データの保持 |
| `test_display_control.py` | 元のLCD ON/OFFの復元、重複消灯の抑止、設定解除、復元失敗時のソケット解放と警告 |
| `test_analysis.py` | 数式の入力制限、時刻不一致、微積分、FFTの周波数・振幅・入力条件 |
| `test_instrument.py` | TCP分割・複数フレーム、空ACK認証、バイナリブロック、換算と転送設定の復元 |
| `test_instrument_settings.py` | SI値、単位・範囲検証、変更項目の抽出、エラー時停止、各操作コマンド |
| `test_panel_sync.py` | ±調整、微調整、1–2–5刻み、通信中の編集、読み戻しの再送防止、RUN/STOP表示、状態文言を変えたときのレイアウト固定 |
| `test_gui.py` | 読込・拡大・カーソル・Math・保存、テーマ、表更新、ホイール軸、左パネル、AA、実機タブ |
| `test_view_state.py` | 保存範囲の復旧、通常ズームの維持、元のviewデータを変更しないこと |
| `test_live.py` | ライブ取得の停止・再開、失敗時の復帰、単発待ち、読取専用取得、再開失敗、RUN中の準備と再開後の配列変換 |
| `test_live_gui.py` | セッションの実描画、全体表示、曲線再利用、ズーム・色維持、古いフレーム無視、要求重複防止、接続再利用、周期計算 |
| `test_run_control.py` | 読み出し中のSpaceによるSTOP予約、ボタンの無効化防止、停止中のMath保持、文字入力中のSpace、長押し防止、操作予約の相殺、オフライン波形の保持 |
| `test_screen.py` | HTTP GETとPNG検証、画像モードでの波形・Math・ズーム保持、2種類の自動更新の排他、接続先・モード変更後の応答破棄、数値制御接続を開かないこと、エラー分離、元PNGの保存 |

`samples/waveform.scope.npz` はユーザー提供の回帰確認用ファイルです。このファイルを使う2件は、存在しない環境ではskipします。Git対象外のため配布ソースにも含めません。同種の範囲復旧は合成データでも検証しています。公開版のデータはdemo/の合成WVF/HDR6組へ切り替えました。

プロトコルの実デコーダー試験4件は、sigrok-cliを指定した場合だけ実行します。

```bash
YOKOGAWA_TEST_SIGROK_CLI=/path/to/sigrok-cli uv run --locked --python 3.12 pytest -q tests/test_protocols.py
```

未指定なら外部依存4件はskipし、入力検証などの単体テストは実行します。libsigrokはファイル入力でも初期化にlibusbを使うため、サンドボックスでは初期化が制限される場合があります。配布物へ外部デコーダーの実行ファイルは含めません。

## ビルドと配布

**Python同梱のLinux展開実行版は[専用手順](packaging-linux.md)を参照してください。** `packaging` 依存グループ、`scripts/build-linux.py`、`packaging/frozen_entry.py` とUbuntu 22.04向けDockerfileを追加しています。以下はPythonパッケージの生成手順です。

```bash
uv build
```

`dist/` にwheelとソース配布を生成します。

| 生成物 | 内容 |
|---|---|
| `yokogawa_tool-0.1.0-py3-none-any.whl` | アプリのPythonパッケージとコマンドの登録情報 |
| `yokogawa_tool-0.1.0.tar.gz` | ソース、テスト、合成デモWVF/HDR、docs、起動・計測スクリプト、設定・ロックファイル |

wheelはOS共通ですが、Python、依存パッケージ、Qtが利用するOSのGUIライブラリが別途必要です。単独実行ファイルではありません。

```bash
python -m pip install dist/yokogawa_tool-0.1.0-py3-none-any.whl
yokogawa-tool
```

依存の版まで揃えて別PCで使う場合は、プロジェクトまたはソース配布を展開し、同梱の `uv.lock` を使って `uv sync --locked --python 3.12` を実行してください。wheelのみをpipでインストールした場合、依存は許容範囲内で新たに解決されます。

ビルド対象は `pyproject.toml` のhatch設定で指定しています。`.venv`、キャッシュ、`dist`、`build`、`captures`、環境管理用の隠しディレクトリ、`samples/` に置いた調査用インストーラーZIPは含めません。

## 検証範囲と制約

Linux / Python 3.12とQt offscreenで動作を確認しています。DL1640のF1.08で、波形取得、RUN/STOP、設定の読み戻し、LCD制御、レコード長の設定を確認しています。

Windows実機、別のLinuxディストリビューションでの配布物の動作、EnDatの実信号は未検証です。USB/GP-IB、Enhancedトリガの詳細編集、リニアスケールONの直接取得、途切れのないストリーミングは未実装です。WVF/HDR出力はPC解析用で、本体への再読込や他ソフトでの受入れは未検証です。

描画の比較には合成波形を使用します。通信を含まない描画時間から実機の更新頻度を推定しないでください。

### 通信の最適化案の扱い（F1.08）

本体ファームの更新は行っていません。[通信仕様6.31節](https://cdn.tmi.yokogawa.com/IM701610-17E.pdf)で確認した機能と、現在の扱いは次のとおりです。

| 案 | 現在の扱い |
|---|---|
| バイナリ転送・接続再利用・状態確認 | WORD転送、ライブ中の接続保持、STOP完了待ち、単発の完了待ちは実装済みです。 |
| BYTE転送 | 換算分解能がWORDと異なるため、解析・保存する波形の取得方式には採用していません。 |
| DLENGTHによる点数削減、PP/DECIMATION | 公式仕様に存在しますが、アプリはDLENGTH AUTOの全点取得を継続します。PPと単純間引きは元波形と同一のデータではなく、時間軸・ピークの扱いの検証が必要です。F1.08での過去の縮小転送では受信点数が1,002点になっており、指定点数を前提に軸を作ることはできません。 |
| 転送・描画時間を分けて比較する | 通信なしの描画比較スクリプトと実機の過去の取得比較を分けて記録します。描画速度向上をそのまま実機fps向上として扱いません。 |

今回の中間倍率での遅延は本体停止・接続解除後も起こり得る描画側の問題です。ファーム更新や転送点数削減を必要とする修正ではありません。ファーム1.53でEthernetが高速化するという保証は置いていません。

## 変更時の確認箇所

UIの変更は `gui/app.py`、実機操作UIは `gui/instrument_panel.py` と `gui/quantity_control.py`、数値波形の通信は `acquisition/instrument.py`、値の制約は `acquisition/settings.py` を確認してください。本体画面は `acquisition/screen.py` と `gui/screen_panel.py` が担当し、数値解析と別のデータ・世代番号を使います。ファイル形式を変える場合はセッションのversionと過去ファイルの互換性、描画を変える場合は生データ・測定値の不変性と極端なズームからの復旧を確認します。

機能を追加・変更したときは、対応する使い方と内部処理も更新してください。

## 公開対象の確認

`python scripts/audit-public.py --artifacts` で、公開対象と履歴・配布物を検査できます。値そのものは出力しません。MITの適用範囲と、凍結実行版で残る第三者条件は [第三者表記](../THIRD_PARTY_NOTICES.md) を参照してください。

検証JSON、調査記録、ToDo、公開前監査記録はローカル専用です。Git・ソース配布・同梱実行版・コンテナーの公開対象から除外します。通常の使い方、実装説明、開発・ビルド手順は公開対象です。
