# 公開用の合成波形

`0000`〜`0005` のWVF/HDRは `scripts/generate-demo.py` が数式から生成したデモです。
実機から取得した波形、第三者の配布データ、個人情報、機器設定領域は含みません。
このプロジェクトのMITライセンスで公開します。

```bash
uv run --locked --python 3.12 python scripts/generate-demo.py
```

正弦波・余弦波・矩形波を固定の条件で生成し、Big endianのIS2形式へ量子化します。
テストは生成に使用したエクスポーターを再利用せず、この独立した形式定義と生バイトを検証します。
`samples/` と `captures/` は利用者のローカルデータ用であり、公開・配布対象ではありません。
