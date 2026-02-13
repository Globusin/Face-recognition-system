# app.py - Основное приложение
from flask import Flask, jsonify, render_template_string
import subprocess
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import create_embeddings_from_camera, save_embedding
from utils.hotspot import start_hotspot

app = Flask(__name__)
app.secret_key = os.urandom(24)

# HTML шаблон для главной страницы captive portal
INDEX_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Smart Door Authentication</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background-color: #f0f0f0;
        }
        .container {
            max-width: 500px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }
        button {
            background-color: #4CAF50;
            color: white;
            padding: 15px 32px;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            font-size: 16px;
            margin: 4px 2px;
            cursor: pointer;
            border: none;
            border-radius: 4px;
        }
        button:hover {
            background-color: #45a049;
        }
        .status {
            margin: 20px 0;
            padding: 10px;
            border-radius: 4px;
        }
        .success { background-color: #d4edda; color: #155724; }
        .error { background-color: #f8d7da; color: #721c24; }
        .info { background-color: #d1ecf1; color: #0c5460; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Добро пожаловать!</h1>
        <p>Для доступа к сети выполните аутентификацию через систему распознавания лица.</p>
        
        <div id="status" class="status info">Готово к аутентификации</div>
        
        <button onclick="authenticateUser()">Аутентифицироваться</button>
        
        <div id="result"></div>
    </div>
    
    <script>
        function authenticateUser() {
            const statusDiv = document.getElementById('status');
            statusDiv.innerHTML = 'Выполняется аутентификация...';
            statusDiv.className = 'status info';
            
            fetch('/api/authenticate', {method: 'POST'})
              .then(response => response.json())
              .then(data => {
                  if (data.status === 'success') {
                      statusDiv.innerHTML = 'Аутентификация успешна! Предоставляется доступ к сети.';
                      statusDiv.className = 'status success';
                      
                      // Перенаправление на внешний ресурс или обновление страницы
                      setTimeout(() => {
                          window.location.href = 'http://www.google.com';
                      }, 2000);
                  } else {
                      statusDiv.innerHTML = data.message || 'Аутентификация не удалась';
                      statusDiv.className = 'status error';
                  }
              })
              .catch(error => {
                  statusDiv.innerHTML = 'Ошибка соединения';
                  statusDiv.className = 'status error';
              });
        }
    </script>
</body>
</html>
'''

# Настройка iptables для перехвата трафика
def setup_captive_portal():
    # Перенаправление HTTP трафика на наш порт
    subprocess.run([
        'iptables', '-t', 'nat', '-A', 'PREROUTING',
        '-i', 'wlan0', '-p', 'tcp', '--dport', '80',
        '-j', 'REDIRECT', '--to-port', '5000'
    ], capture_output=True)
    # Блокируем весь исходящий трафик в интернет
    subprocess.run([
        'iptables', '-A', 'FORWARD', '-i', 'wlan0',
        '-o', 'eth0', '-j', 'DROP'
    ], capture_output=True)

def create_wifi_hotspot():
    ssid = "SmartDoor-Auth"
    password = "12345678"

    start_hotspot(ssid, password)

@app.route('/')
def captive_redirect():
    """Главная страница captive portal"""
    return render_template_string(INDEX_TEMPLATE)

@app.route('/login')
def login_page():
    """Страница входа"""
    return render_template_string(INDEX_TEMPLATE)

@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    """API endpoint для аутентификации пользователя по лицу"""
    from utils.recognition import recognize_face_from_camera
    
    is_authenticated, user_id, distance = recognize_face_from_camera()
    
    if is_authenticated:
        # Лицо распознано, предоставляем доступ
        return jsonify({
            'status': 'success', 
            'message': 'Аутентификация прошла успешно',
            'user_id': user_id,
            'distance': distance
        })
    else:
        # Лицо не распознано, возвращаем ошибку
        return jsonify({
            'status': 'error', 
            'message': 'Лицо не распознано или не найдено в базе данных'
        })

@app.route('/api/add_user', methods=['POST'])
def add_user():
    embeddings = create_embeddings_from_camera()
        
    if embeddings:
        if len(embeddings) > 1:
            save_embedding(embeddings[0])
        else:
            return jsonify({'status': 'not success', 'message': 'error'})
    else:
        return jsonify({'status': 'not success', 'message': 'error'})
    
    return jsonify({'status': 'success', 'message': 'User added'})
