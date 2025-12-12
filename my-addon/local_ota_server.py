#!/usr/bin/env python3
import http.server
import socketserver
import threading
import functools
import os


class OTARequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    支援多層資料夾的靜態檔案伺服器。
    directory 參數會指定 OTA 根目錄。
    """
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    # 避免 log 太吵
    def log_message(self, format, *args):
        print(f"[OTA] {self.address_string()} - {format % args}")


def start_ota_server_in_thread(root_dir: str, port: int) -> threading.Thread:
    """
    在背景 thread 啟動 OTA HTTP 伺服器。
    root_dir: OTA 根目錄，例如 /share/zp2_fw
    port: 對外 HTTP 連接埠，例如 8088
    """
    os.makedirs(root_dir, exist_ok=True)

    def _run_server():
        print(f"[OTA] Root: {root_dir}")
        print(f"[OTA] Listen on: 0.0.0.0:{port}")
        print("[OTA] 例如：/STM32/ZP2/fota-ZP2-5-0-20251205-S01.bin")
        print("[OTA] → http://<HA_IP>:%d/STM32/ZP2/fota-ZP2-5-0-20251205-S01.bin" % port)

        handler = functools.partial(OTARequestHandler, directory=root_dir)

        with socketserver.TCPServer(("", port), handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("[OTA] 收到中斷，關閉伺服器...")
            finally:
                httpd.server_close()

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()
    return t


# 單獨執行這支檔案時，也可以直接跑（方便你單機測試）
if __name__ == "__main__":
    root = os.environ.get("OTA_ROOT", "/share/zp2_fw")
    port = int(os.environ.get("OTA_PORT", "8088"))
    start_ota_server_in_thread(root, port).join()
