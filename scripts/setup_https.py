"""Создаёт локальные TLS-ключи и токен, не перезаписывая существующие"""

import ipaddress
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.config_loader import load_config


def main():
    root = Path(__file__).resolve().parent.parent
    config = load_config()
    settings = config.get('server', {})
    cert = root / settings.get('cert_file', 'data/security/server.crt')
    key = root / settings.get('key_file', 'data/security/server.key')
    token = root / config.get('security', {}).get('admin_token_file', 'data/security/admin-token')
    os.umask(0o077)
    for path in (cert, key, token):
        path.parent.mkdir(parents=True, exist_ok=True)
    if cert.exists() != key.exists():
        raise RuntimeError('Найдена только часть TLS-пары, восстановите сертификат и ключ')
    if not cert.exists():
        names = ['DNS:localhost', 'IP:127.0.0.1', 'IP:::1']
        hostname = socket.gethostname()
        if all(char.isalnum() or char in '.-' for char in hostname):
            names.append('DNS:' + hostname)
        addresses = subprocess.check_output(['hostname', '-I'], text=True).split()
        for address in addresses:
            names.append('IP:' + str(ipaddress.ip_address(address)))
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes',
                        '-days', '365', '-subj', '/CN=Domovoi',
                        '-addext', 'subjectAltName=' + ','.join(names),
                        '-addext', 'basicConstraints=critical,CA:FALSE',
                        '-keyout', str(key), '-out', str(cert)], check=True)
    if not token.exists():
        with token.open('x', encoding='utf-8') as output:
            output.write(secrets.token_urlsafe(32) + '\n')
    key.chmod(0o600)
    token.chmod(0o600)
    print(f'Сертификат: {cert}')
    print(f'Токен администратора: {token} (содержимое в журнал не выводится)')
    print('Доверьте сертификат на компьютере администратора после проверки отпечатка')


if __name__ == '__main__':
    main()
