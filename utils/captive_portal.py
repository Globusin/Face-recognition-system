import subprocess
import sys
import http.server
import socketserver
from threading import Thread

def setup_captive_portal(port=4449, html_content=None):
    if html_content is None:
        html_content = """
        <html>
            <head><title>Captive Portal</title></head>
            <body>
                <h1>Добро пожаловать!</h1>
                <p>Это локальная точка доступа без доступа к интернету.</p>
            </body>
        </html>
        """

    class CaptivePortalHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html_content.encode())

    def run_server():
        with socketserver.TCPServer(("", port), CaptivePortalHandler) as httpd:
            print(f"Captive portal запущен на порту {port}...")
            httpd.serve_forever()

    # Запуск сервера в отдельном потоке
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # Настройка iptables для перенаправления всех HTTP-запросов на наш портал
    try:
        print("Настраиваем iptables для captive portal...")
        # Пример: перенаправление всех запросов на порт на localhost
        subprocess.run(
            ["iptables", "-t", "nat", "-A", "PREROUTING", "-p", "tcp", "--dport", str(port), "-j", "DNAT", "--to-destination", "127.0.0.1:80"],
            check=True
        )
        print("Iptables правило добавлено.")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка настройки iptables: {e}")
        sys.exit(1)
