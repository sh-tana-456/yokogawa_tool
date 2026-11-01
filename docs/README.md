# ドキュメント

[プロジェクトのREADME](../readme.md)

DL1640 Waveform Workbenchの仮完成版の仕様と使い方です。現在の対象はPython / PySide6によるデスクトップアプリです。

| ページ | 読みたい内容 |
|---|---|
| [使い方](usage.md) | インストール、拡大・カーソル・Math、保存、実機操作、ライブ更新、困ったとき |
| [Linuxパッケージの作成と配布](packaging-linux.md) | Python同梱の展開実行版、再ビルド、配布先での検証、Linux互換性 |
| [プロトコル解析](protocols.md) | sigrok-cliの準備、各プロトコルの設定、結果表とCSV、制約 |
| [EnDat 2.1/2.2解析](endat.md) | 公開資料、内蔵デコーダーの設定、検証範囲と未対応条件 |
| [内部処理・実装](implementation.md) | ファイルごとの役割、データモデル、換算式、描画の軽量化、通信と自動同期 |
| [開発・スクリプト](development.md) | 各スクリプトの動作、依存関係、テスト、パッケージ生成、検証済み範囲 |
| [今後の拡張](roadmap.md) | 対応済みプロトコルとEnDatの残課題、間欠取得での制約 |

初めて使う場合は[使い方](usage.md)、コードを変更する場合は[内部処理](implementation.md)から進んでください。

## 構成整理について

Go/Rust実装、共通Web画面、ブラウザ用のウィンドウ起動機能、専用テスト・ビルドスクリプト、およびそれら向けのAppImage/Flatpak設定・生成物を削除しました。Python版にはPyInstallerによるLinux展開実行版を追加しました。AppImage/Flatpak化は実装していません。ソースとロックファイルによる再構築、Pythonパッケージのインストールも使用できます。

`samples/` の波形と `captures/` の実機取得データは保持しています。過去の実装名を含むファイル名でも、`.scope.json` はPython版で引き続き開けます。作業環境の `.venv/` も保持しますが、別PCにはコピーせず作り直します。

`*.scope.npz`、`*.scope.json`、`captures/` のデータは配布ソースに含めない運用です。必要な波形はアプリの保存機能を使い、別途持ち運んでください。

公開・配布するサンプルは `demo/` にある合成波形6組だけです。`samples/` と `captures/` の元データは保持しますが、すべてローカル専用です。

## 仕様の参照元

- [DL1620/DL1640/DL1640L User's Manual IM701610-01E](https://cdn.tmi.yokogawa.com/IM701610-01E.pdf): Appendix 3のWVF/HDR形式と換算式、本体操作。
- [Communication Interface User's Manual IM701610-17E](https://cdn.tmi.yokogawa.com/IM701610-17E.pdf): 認証、ポート、波形転送、機器操作コマンド。
- [YOKOGAWA公式の旧機種Ethernet接続方式](https://tmi.yokogawa.com/us/library/resources/faqs/how-to-connect-to-legacy-yokogawa-products-using-ethernet-protocol/): 長さ付きフレームと空メッセージ。

対応範囲と実際の実装上の制約は、このディレクトリの説明を参照してください。

