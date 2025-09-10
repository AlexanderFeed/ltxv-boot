#!/usr/bin/env python3
"""
Простой HTTP сервер для фронтенда
Запускать: python run_frontend_server.py
"""

import http.server
import socketserver
import os

PORT = 8002

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Добавляем CORS заголовки для работы с API
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

if __name__ == '__main__':
    # Переходим в директорию с frontend.html
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print(f"🚀 Фронтенд сервер запущен на http://localhost:{PORT}")
    print(f"📄 Откройте http://localhost:{PORT}/frontend_simple.html в браузере")
    print("⏹️  Для остановки нажмите Ctrl+C")
    print("🌐 Фронтенд сервер запущен на http://localhost:8002")
    print("📱 Упрощенная версия с качеством разработчиков!")
    
    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        httpd.serve_forever() 