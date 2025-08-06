import re
import base64
import json
from urllib.parse import urlparse
import socket
import os

def extract_links(content):
    pattern = r'(?:vmess|trojan|vless|ss)://[^\s]+'
    return re.findall(pattern, content)

def read_existing_links(filename):
    """Читает существующие ссылки из файла"""
    if not os.path.exists(filename):
        return []
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def save_links(filename, links, mode='w'):
    """Сохраняет ссылки в файл с указанным режимом"""
    with open(filename, mode, encoding='utf-8') as f:
        f.write('\n'.join(links) + '\n')

def parse_vmess(link):
    try:
        b64_str = link[8:]
        missing_padding = len(b64_str) % 4
        if missing_padding:
            b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        config = json.loads(decoded)
        return config.get('add'), config.get('port')
    except:
        return None, None

def parse_generic_url(link):
    """Обрабатывает ss, trojan и vless ссылки"""
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port
        
        # Установка портов по умолчанию для разных протоколов
        if not port:
            if parsed.scheme == "trojan":
                port = 443
            elif parsed.scheme == "ss":
                port = 8388  # стандартный порт Shadowsocks
            else:  # vless и другие
                port = 443
                
        return host, port
    except:
        return None, None

def check_connection(host, port, timeout=5):
    if not host or not port:
        return False
    try:
        port = int(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except:
        return False

def main():
    base_dir = r'D:\01\mygithub\MitilVPN'
    input_file = os.path.join(base_dir, 'configs.txt')
    all_file = os.path.join(base_dir, 'config_all.txt')
    good_file = os.path.join(base_dir, 'config_good.txt')

    # Чтение и обработка исходного файла
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    new_links = extract_links(content)

    # Получение существующих ссылок
    existing_links = read_existing_links(all_file)
    
    # Объединение и удаление дубликатов
    unique_links = list({link: None for link in existing_links + new_links}.keys())

    # Сохранение в config_all.txt
    save_links(all_file, unique_links)

    # Проверка всех ссылок
    good_links = []
    for link in unique_links:
        protocol = link.split('://')[0].lower()
        host, port = None, None
        
        if protocol == 'vmess':
            host, port = parse_vmess(link)
        elif protocol in ['trojan', 'vless', 'ss']:
            host, port = parse_generic_url(link)
        
        if check_connection(host, port):
            good_links.append(link)
            print(f"✅ Working: {link}")
        else:
            print(f"❌ Not working: {link}")

    # Сохранение рабочих ссылок (полная перезапись)
    save_links(good_file, good_links)

    # Git операции
    os.chdir(base_dir)
    os.system('git add config_all.txt config_good.txt')
    os.system('git commit -m "Auto-update config files"')
    os.system('git push')

if __name__ == "__main__":
    main()