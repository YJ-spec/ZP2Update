#!/usr/bin/env python3
import http.server
import socketserver
import threading
import functools
import os


class OTARequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    簡單的靜態檔案伺服器。
    directory 參數會指定 OTA 根目錄。
    """
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)


def start_ota_server_in_thread(root_dir: str = "/share/zp2_fw", port: int = 8088) -> threading.Thread:
    """
    在背景 thread 啟動 HTTP Server，提供 root_dir 底下的靜態檔案。
    """
    if not os.path.isdir(root_dir):
        print(f"[OTA] ⚠ 目錄不存在：{root_dir}（仍然啟動 HTTP，但請確認 /share 掛載與路徑）", flush=True)
    else:
        print(f"[OTA] 使用根目錄：{root_dir}", flush=True)

    handler = functools.partial(OTARequestHandler, directory=root_dir)

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True

    def _run():
        with ThreadingTCPServer(("", port), handler) as httpd:
            print(f"[OTA] HTTP server 啟動：http://0.0.0.0:{port}/", flush=True)
            print(f"[OTA] 例如：http://<HA_IP>:{port}/STM32/ZP2/fota-ZP2-5-0-20251205-S01.bin", flush=True)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("[OTA] 收到中斷，關閉伺服器...", flush=True)
            finally:
                httpd.server_close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    root = os.environ.get("OTA_ROOT", "/share/zp2_fw")
    port = int(os.environ.get("OTA_PORT", "8088"))
    print(f"[OTA] 以獨立模式啟動，root={root}, port={port}", flush=True)
    start_ota_server_in_thread(root, port).join()
