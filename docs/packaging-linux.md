# Linuxパッケージの作成と配布

[ドキュメント一覧](README.md) / [開発](development.md)

## 配布形式

ローカルで持ち運ぶ形式は **Python同梱の展開実行版** です。GitHub等で公開配布する前には、[第三者表記](../THIRD_PARTY_NOTICES.md)の確認が必要です。配布先へPython・uv・NumPy・PySide6をインストールする必要はありません。PyInstallerのonedir形式をtar.gzへまとめます。毎回の起動時に一時展開する方式ではなく、展開したフォルダ内の実行ファイルを使います。[PyInstallerの構成](https://pyinstaller.org/en/stable/operating-mode.html)

| 生成物 | 配布先で必要なもの | 用途 |
|---|---|---|
| `yokogawa-tool-0.1.0-linux-x86_64.tar.gz` | 対応するLinuxデスクトップ・CPU・システムライブラリ | 展開して使うローカル検証用（第三者条件の確認が必要） |
| 同名の `.tar.gz.sha256` | `sha256sum` | コピー後の整合性確認 |
| `yokogawa_tool-0.1.0-py3-none-any.whl` | Pythonと依存パッケージ | Python環境へインストール |
| `yokogawa_tool-0.1.0.tar.gz` | uv、初回ダウンロード用の通信環境 | ソースから再構築・開発 |

バージョンは `pyproject.toml`、CPU名はビルド機から取得します。ARM64では別の `aarch64` 配布物になります。Windows版・AppImage・Flatpakの生成はこの手順には含みません。

## 配布先での使い方

tar.gzとチェックサムを同じフォルダへコピーして実行します。

```bash
sha256sum -c yokogawa-tool-0.1.0-linux-x86_64.tar.gz.sha256
tar -xzf yokogawa-tool-0.1.0-linux-x86_64.tar.gz
cd yokogawa-tool-0.1.0-linux-x86_64
./run.sh
```

サンプルを開く場合：

```bash
./run.sh demo/0000.WVF
```

ファイルマネージャーから `yokogawa-tool` を起動することもできます。コピー・展開先に実行権限が必要です。権限が失われた場合は `chmod +x run.sh yokogawa-tool` を実行します。`_internal/` を含むフォルダ全体が必要で、実行ファイルだけのコピーでは起動しません。シンボリックリンクを保持する必要があるため、USBメモリーではtar.gzのまま運び、ext4等のLinuxファイルシステムへ展開してください。exFAT/FATへの直接展開は避けます。

設定・表示テーマなどは利用者のQt設定領域へ保存します。配布物に元のPCの設定やパスワードは含めません。波形の保存先はアプリで指定します。

実機接続では接続先IPと本体のRemote Cntl設定を合わせます。通信方式は通常起動と同じTCP/IPで、DL1640用のUSBドライバーは不要です。

## ビルドする環境の選び方

Pythonを同梱しても、Linuxのglibc・GUI・フォント・グラフィックスドライバーまで完全に独立するわけではありません。**配布したい最も古いLinux環境でビルドし、配布先でも確認**してください。新しい環境で作った実行形式は古いglibcでは起動しないことがあります。[PyInstallerのLinux互換性](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible)

- 開発機のLinux x86_64 / glibc 2.44で作る配布物は、その環境での動作確認用です。古いUbuntu等への互換性を保証するものではありません。
- ロック済みのPySide6 6.12.0では、x86_64のwheelは `manylinux_2_34`、ARM64は `manylinux_2_39` です。Pythonパッケージ自体にもglibcの条件があり、PyInstallerだけでこれを下げることはできません。
- x86_64で古いデスクトップも対象にするなら、Ubuntu 22.04などの専用VM、または下記コンテナーでのビルドが候補です。この環境にはDocker/Podmanがないため、コンテナー手順自体は未実行です。
- CPUの種類が違う配布先へ同じバイナリは使えません。ARM64版は対応するARM64ビルド環境を用意してください。

`BUILD-INFO.json` に、Python・依存パッケージ・PyInstallerの版、CPU、ビルド環境のglibc、同梱ELFから検出したglibcシンボルの最大値を記録します。シンボル調査は診断情報であり、他のライブラリやドライバーとの互換性確認の代わりにはなりません。

## 現在のLinux上でビルドする

ソースフォルダで実行します。ビルド機には[uv](https://docs.astral.sh/uv/getting-started/installation/)を用意してください。初回はPythonとビルド依存のダウンロードが必要です。

```bash
UV_PROJECT_ENVIRONMENT=build/packaging-venv \
  uv sync --locked --python 3.12 --no-dev --group packaging

UV_PROJECT_ENVIRONMENT=build/packaging-venv \
  uv run --locked --python 3.12 --no-dev --group packaging \
  python scripts/build-linux.py
```

実行時依存は `uv.lock` の版を使います。PyInstallerも `packaging` グループへ固定し、既存の開発用 `.venv` とは別の仮想環境でビルドします。通常起動ではこのグループは不要です。

ソース版の `run.sh` はuvを呼びますが、配布版に生成する `run.sh` は同梱実行ファイルを直接呼びます。配布版の起動にはuvは不要です。

出力：

```text
dist/yokogawa-tool-0.1.0-linux-x86_64.tar.gz
dist/yokogawa-tool-0.1.0-linux-x86_64.tar.gz.sha256
build/linux-package/release/yokogawa-tool-0.1.0-linux-x86_64/
```

展開実行版の中身：

```text
yokogawa-tool                 Python同梱の実行ファイル
_internal/                   Python・Qt・NumPy等の依存
run.sh                       実行ファイルへ引数を渡す入口
README-FIRST.md              配布先向けの簡単な手順
BUILD-INFO.json              版・CPU・glibcなどのビルド情報
demo/                        数式から生成した0000〜0005のWVF/HDRのみ
docs/                        使い方・ビルド・検証資料
licenses/                    依存のメタデータ・付属ライセンス本文
src/ scripts/ packaging/     参照・再ビルド用のソース
tests/ pyproject.toml uv.lock 元の開発・依存定義
```

ビルド用スクリプトは `scripts/build-linux.py`、凍結実行の入口は `packaging/frozen_entry.py` です。不要なQt WebEngine/PDF/QMLモジュールは解析対象から外します。実測ファイル、`samples/`、`captures/`、調査用ZIP、元PCの `.venv`・Qt設定は同梱しません。追加したサンプルを配布したい場合は、対象を明示してビルド用の許可リストを変更してください。

同梱のソースは参照・再ビルド用です。編集しても作成済みの実行ファイルは変わらないため、反映する場合は再ビルドします。

## Ubuntu 22.04コンテナーでビルドする場合

Dockerを使用できるLinux x86_64機で実行するための手順です。コンテナーはビルド用で、配布先にDockerは不要です。

```bash
docker build -f packaging/linux/Dockerfile -t yokogawa-tool-builder .
mkdir -p dist
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/dist:/out" yokogawa-tool-builder
```

DockerfileはUbuntu 22.04上でPython 3.12・ロック済み依存を使ってビルドします。`.dockerignore` でも個人の測定データ・キャッシュ等を除外します。コンテナー版も配布先で検証してください。VMで同じOSを用意し、前節のコマンドを実行する方式でも構いません。

## ビルド後・配布先での検証

まず展開し、プロジェクトの外で実行します。

```bash
mkdir -p /tmp/yokogawa-release-check
tar -xzf dist/yokogawa-tool-0.1.0-linux-x86_64.tar.gz \
  -C /tmp/yokogawa-release-check
cd /tmp/yokogawa-release-check/yokogawa-tool-0.1.0-linux-x86_64
./yokogawa-tool --help
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME="$(mktemp -d)" \
  ./yokogawa-tool --package-self-test
./run.sh demo/0000.WVF
```

自己診断はネットワークや実機を使わず、サンプル読み込み・Math・FFT・EnDatの設定画面・セッション保存と再読込・描画を確認し、成功時はJSONを出力します。設定保存先も一時ディレクトリに分離します。通常起動では `QT_QPA_PLATFORM=offscreen` は設定しません。

配布先でも、通常画面の拡大・カーソル・保存、必要な場合は実機接続を確認してください。別ディストリビューションでの起動、ネイティブWayland/X11、実機通信はoffscreen自己診断だけでは確認できません。

## Pythonパッケージも作る場合

```bash
uv build
uv export --locked --no-dev --no-emit-project --format requirements.txt \
  --output-file dist/requirements-runtime.txt
```

wheelに依存本体は含まれません。版まで揃える場合は、wheelとエクスポートしたrequirementsを同時に渡します。配布先でPython 3.12を用意できる場合：

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --require-hashes \
  -r requirements-runtime.txt
uv pip install --python .venv/bin/python --no-deps \
  yokogawa_tool-0.1.0-py3-none-any.whl
.venv/bin/yokogawa-tool
```

またはソース配布を展開し、`uv sync --locked --python 3.12 --no-dev` 後に `uv run --locked --python 3.12 --no-dev yokogawa-tool` を使います。`.venv` を別PCへ直接コピーせず、インストール先で再作成してください。[uvの同期](https://docs.astral.sh/uv/concepts/projects/sync/)

## トラブル対処

| 症状 | 確認すること |
|---|---|
| `GLIBC_2.xx not found` | 配布先より新しい環境で作った可能性。古い対象OSで再ビルドするか、そのPCでPython版を導入 |
| `Exec format error` | x86_64とARM64などのCPU不一致 |
| `Permission denied` | 実行権限と、展開先が `noexec` マウントでないか |
| `xcb` / Waylandプラグインエラー | 端末から起動し、`QT_DEBUG_PLUGINS=1 ./yokogawa-tool` で不足ライブラリを確認。X11なら `QT_QPA_PLATFORM=xcb ./yokogawa-tool` も確認 |
| `libEGL.so.1` / `libGL.so.1` 等がない | 配布先OSのGUI・グラフィックス用ライブラリを導入 |
| 日本語が四角になる | 配布先へ日本語フォントを導入（例：Noto CJK） |
| UART等の解析だけ動かない | 外部 `sigrok-cli` / `libsigrokdecode` を導入し、解析画面で実行ファイルを指定 |

Qtプラグインが必要とするシステムライブラリは[Qt公式のLinux要件](https://doc.qt.io/qt-6/linux-requirements.html)も参照してください。最小構成のサーバーOSでは、デスクトップ機に通常あるライブラリも追加が必要です。

外部sigrok-cliを起動する際は、凍結実行で変更された `LD_LIBRARY_PATH` を子プロセスだけ元に戻します。親アプリの環境は変更しません。[PyInstallerの外部プログラム起動](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application)

同梱依存のライセンス情報とOSパッケージの構成表を `licenses/` に配置します。PythonのLICENSE、取得できた著作権表記も添付し、取得できない項目を `NATIVE-LIBRARIES.json` へ残します。再配布条件の確認は未完了で、現時点の凍結実行版はGitHub Releasesへの公開を保留します。アプリ本体のライセンスを新たに変更するものではありません。組織外へ配布する場合も、使用する依存のライセンス条件を確認してください。

## 今回の確認範囲

2026-11-01にLinux x86_64・glibc 2.44・Python 3.12.14・PyInstaller 6.22.3で展開実行版を生成しました。サイズは約114 MiBです。同梱ELFの最大glibcシンボル参照は2.44（`libsqlite3.so.0`）であり、古いLinux向け配布物としては未検証です。

プロジェクト外へ展開し、仮想環境・PYTHONPATHを外して、チェックサム・CLIの入口・自己診断を確認しました。自己診断ではサンプル3CHの読込、Math、FFT、EnDat設定画面、セッション往復、offscreen描画が成功しています。外部デコーダー起動時の検索パス復元も模擬CLIで確認しました（実際のsigrok-cliの復号試験とは別です）。ユーザー追加の測定ファイル・インストーラー・仮想環境を含めないことも検証しています。

Ubuntuコンテナー・別のLinux実機・デスクトップのWayland/X11上での通常操作・実機通信は今回のパッケージ試験では未検証です。既存アプリの検証と、凍結配布物の移植性確認は分けて扱います。

公開向けの修正では、tarのuid/gid・所有者名・時刻を正規化し、ローカルの所有者名が入らないようにしました。元データを含まない合成デモだけを同梱します。開発ホストのOSライブラリにはx86_64-v3向けのものもあるため、`architecture=x86_64` だけでCPU互換性を保証しません。OSパッケージ情報を確認し、一般的な配布先向けには対応するビルド環境を用意してください。
