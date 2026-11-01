"""Read the instrument's Web monitor image without acquisition commands."""
import struct
import time
from urllib.request import (Request, build_opener, ProxyHandler, HTTPBasicAuthHandler,
                            HTTPPasswordMgrWithDefaultRealm, HTTPRedirectHandler)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError("本体画面の取得先がリダイレクトされました。IPとHTTPポートを確認してください。")


def fetch_screen(host, port=80, username="anonymous", password="", timeout=20):
    host = str(host).strip()
    if not host or any(c in host for c in "/?#@\\\r\n\t "):
        raise ValueError("本体のIPアドレスまたはホスト名を指定してください。")
    if not 1 <= int(port) <= 65535:
        raise ValueError("HTTPポートは1〜65535を指定してください。")
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    base = f"http://{authority}:{int(port)}/"
    credentials = HTTPPasswordMgrWithDefaultRealm()
    credentials.add_password(None, base, username, password)
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPBasicAuthHandler(credentials))
    started = time.monotonic()
    request = Request(base + "webmonimage.png", headers={"Cache-Control": "no-cache"})
    limit = 8 * 1024 * 1024
    with opener.open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("本体画面の画像が8MiBの上限を超えました。")
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("本体からPNG画像を取得できませんでした。Webサーバーの設定を確認してください。")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height or width * height > 16_777_216:
        raise ValueError("本体画面の画像サイズが不正です。")
    return {"png": data, "seconds": time.monotonic() - started}
