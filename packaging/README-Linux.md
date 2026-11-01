# Linux展開実行版

このフォルダにはPythonと実行に必要なPythonパッケージ・Qtを同梱しています。現時点では検証用です。公開再配布前の未確認項目を `BINARY-LICENSE-REVIEW.md` と `THIRD_PARTY_NOTICES.md` に記載しています。

```bash
./run.sh
./run.sh demo/0000.WVF
```

ファイルマネージャーから `yokogawa-tool` を起動することもできます。
tar.gzはUSBメモリーでも持ち運べますが、展開先はシンボリックリンクに対応するLinuxファイルシステム（ext4等）を使ってください。
`_internal/` を含むフォルダ全体を保持してください。実行ファイルだけのコピーでは起動しません。
保存先は自分で選択でき、表示設定は利用者のQt設定領域に保存します。

実行権限が失われた場合：

```bash
chmod +x run.sh yokogawa-tool
```

CPUは `BUILD-INFO.json` の `architecture` と一致するものが必要です。
LinuxのGUI・フォント・glibcなど一部のシステムライブラリは別途必要です。
`BUILD-INFO.json` にビルド環境と同梱ELFのglibcシンボル情報を記録しています。
新しいLinuxで作ったパッケージが古いLinuxでも動作するとは限りません。
配布先で確認するか、配布先に対応した古い環境でビルドしてください。

画面を開かないパッケージ確認（端末から実行）：

```bash
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME="$(mktemp -d)" ./yokogawa-tool --package-self-test
```

通常利用時は `QT_QPA_PLATFORM=offscreen` を設定しないでください。
実機試験やネットワーク接続をせず、同梱サンプル・Math・FFT・EnDat設定画面・セッション保存・描画を確認します。

UART / SPI / I²C / CANの復号には、配布先OSへ `sigrok-cli` と `libsigrokdecode` の導入が別途必要です。
波形表示・保存・測定・EnDat内蔵解析はこれらがなくても使用できます。
実機接続では「実機操作」の接続先を自分のDL1640に合わせてください。

詳細なビルド・配布・トラブル対処は `docs/packaging-linux.md` を参照してください。
