# Third-party notices

このプロジェクトの独自コード・文書・合成デモにはルートのMITライセンスを適用します。
以下の第三者の著作物をMITへ変更するものではありません。

| 対象 | ライセンス・扱い | 参照先 |
|---|---|---|
| NumPy | BSD-3-Clause等。wheelのLICENSEには内包する第三者コードの条項も含まれます | [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| pyqtgraph | MIT | [pyqtgraph license](https://github.com/pyqtgraph/pyqtgraph/blob/master/LICENSE.txt) |
| colorama | BSD-3-Clause | [colorama license](https://github.com/tartley/colorama/blob/master/LICENSE.txt) |
| PySide6 / Shiboken6 / Qt | LGPL/GPL/商用ライセンスの選択肢があり、モジュール・第三者部品ごとに条件が異なります | [Qt for Python](https://doc.qt.io/qtforpython-6/), [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) |
| CPython | PSF License等。凍結実行版には実際のPythonのLICENSE.txtを添付 | [Python license](https://docs.python.org/3/license.html) |
| PyInstaller | GPLv2-or-laterとbootloaderの例外等。アプリ本体をGPLに変更するという意味ではありません | [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |
| OS由来の共有ライブラリ | MIT/BSD/LGPL/GPL等、実際に同梱する部品ごとに確認が必要 | 凍結実行版の `licenses/NATIVE-LIBRARIES.json` |
| sigrok-cli / libsigrokdecode | 外部ツール。通常の配布物には同梱しません | [sigrok-cli](https://github.com/sigrokproject/sigrok-cli), [libsigrokdecode](https://github.com/sigrokproject/libsigrokdecode) |

表は概要であり、正確な条件は使用した版のライセンス本文・著作権表記を優先します。
依存の著作権者名・連絡先がライセンス本文に含まれる場合は、必要な帰属表示として保持します。

## ソース公開と同梱バイナリ配布の違い

ソースリポジトリにQtやOSライブラリのバイナリは含めません。Python環境へ依存を導入して使います。
一方、展開実行版はPython・Qt・NumPy・OS由来ライブラリを含みます。
`scripts/build-linux.py` はPythonのLICENSE、wheelの付属表記、Qtのライセンス本文、
取得可能なOSパッケージの著作権表記と構成一覧を添付します。

**この収集だけで、同梱バイナリの再配布条件の確認が完了したとは扱いません。**
公開バイナリ配布の前に、正確な版のソース提供・著作権表記・LGPLに基づくライブラリ交換や
再リンク等の条件、Qtの各モジュールと内包部品の条件を確認してください。
未確認項目は `BINARY-LICENSE-REVIEW.md` と `licenses/NATIVE-LIBRARIES.json` に記録します。
現時点の凍結実行版は検証用で、GitHub Releasesへそのまま公開する承認済み成果物とはしていません。

## データ・画像・仕様資料

- `demo/` は数式から生成した合成データです。生成元は `scripts/generate-demo.py` / `core/demo.py` で、MITの対象です。
- `samples/` / `captures/` の元の実測波形、利用者が追加したファイル、メーカーのインストーラーはローカル用です。公開・配布対象に含めません。
- 公開するアプリ画面例は合成波形を使って生成します。メーカー本体の画面画像は公開対象から外し、元画像はローカルに保管します。
- Yokogawa/DL1640やEnDat等の名称・商標の権利は各権利者に帰属します。このソフトはメーカー公式製品やメーカーによる承認を意味しません。
- Yokogawa・HEIDENHAIN等のマニュアルPDFは同梱せず、公式の公開先を参照します。マニュアル本文へMITを適用しません。
- EnDatは公開資料を参照した独自のPython実装です。TIのCコードを一時環境でコンパイルしたCRC照合を行いましたが、そのCソースやメーカーの実行ファイルをリポジトリへ組み込んではいません。参照先と範囲は `docs/endat.md` に記載しています。

## ライセンス本文の同梱

`packaging/licenses/` の本文は、それぞれの第三者ライセンスの原文です。
ルートの `LICENSE` とは別の範囲に適用されます。
本体のMITにGPL本文を追加してデュアルライセンス化したものではありません。
