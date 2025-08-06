import re
import base64
import json
from urllib.parse import urlparse
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket

def get_country_by_ip(ip):
    """Определяет страну по IP адресу"""
    try:
        # Используем бесплатный API ip-api.com
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=country,countryCode", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') != 'fail':
                country_code = data.get('countryCode', 'XX')
                country_name = data.get('country', 'Unknown')
                return f"{country_code}"
        
        # Резервный API - ipinfo.io (тоже бесплатный)
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get('country', 'XX')
            return country_code
            
    except Exception as e:
        print(f"Ошибка определения страны для {ip}: {str(e)}")
    
    return "XX"  # Неизвестная страна

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
        if links:
            f.write('\n'.join(links) + '\n')
        else:
            f.write('')  # Создаем пустой файл если нет ссылок

def parse_vmess(link):
    try:
        b64_str = link[8:]
        missing_padding = len(b64_str) % 4
        if missing_padding:
            b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        config = json.loads(decoded)
        return config.get('add'), config.get('port'), config
    except:
        return None, None, None

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
                
        return host, port, parsed
    except:
        return None, None, None

def modify_link_with_country(link, country_code):
    """Модифицирует ссылку, добавляя код страны к имени"""
    protocol = link.split('://')[0].lower()
    
    try:
        if protocol == 'vmess':
            # Для VMess нужно декодировать, изменить ps (имя) и закодировать обратно
            b64_str = link[8:]
            missing_padding = len(b64_str) % 4
            if missing_padding:
                b64_str += '=' * (4 - missing_padding)
            decoded = base64.b64decode(b64_str).decode('utf-8')
            config = json.loads(decoded)
            
            # Добавляем код страны к имени
            current_ps = config.get('ps', '')
            if not current_ps.startswith(f"[{country_code}]"):
                config['ps'] = f"[{country_code}] {current_ps}".strip()
            
            # Кодируем обратно
            new_config_str = json.dumps(config, ensure_ascii=False)
            new_b64 = base64.b64encode(new_config_str.encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
            
        elif protocol in ['trojan', 'vless']:
            # Для trojan и vless изменяем fragment (имя после #)
            if '#' in link:
                base_link, current_name = link.rsplit('#', 1)
                from urllib.parse import unquote, quote
                current_name = unquote(current_name)
                if not current_name.startswith(f"[{country_code}]"):
                    new_name = f"[{country_code}] {current_name}".strip()
                    return f"{base_link}#{quote(new_name)}"
            else:
                # Если нет имени, добавляем его
                return f"{link}#{quote(f'[{country_code}] Server')}"
                
        elif protocol == 'ss':
            # Для shadowsocks также работаем с fragment
            if '#' in link:
                base_link, current_name = link.rsplit('#', 1)
                from urllib.parse import unquote, quote
                current_name = unquote(current_name)
                if not current_name.startswith(f"[{country_code}]"):
                    new_name = f"[{country_code}] {current_name}".strip()
                    return f"{base_link}#{quote(new_name)}"
            else:
                # Если нет имени, добавляем его
                from urllib.parse import quote
                return f"{link}#{quote(f'[{country_code}] Server')}"
                
    except Exception as e:
        print(f"Ошибка при модификации ссылки: {str(e)}")
    
    return link  # Возвращаем оригинальную ссылку в случае ошибки

def check_connection_advanced(host, port, timeout=10):
    """Улучшенная проверка соединения через HTTP запросы"""
    if not host or not port:
        return False
    
    try:
        port = int(port)
        
        # Проверяем через разные методы
        test_urls = [
            f"https://{host}:{port}",
            f"http://{host}:{port}",
            f"https://{host}" if port == 443 else None,
            f"http://{host}" if port == 80 else None
        ]
        
        # Убираем None значения
        test_urls = [url for url in test_urls if url is not None]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        for url in test_urls:
            try:
                # Проба HEAD запроса (быстрее)
                response = session.head(url, timeout=timeout, verify=False, allow_redirects=True)
                if response.status_code < 500:  # Любой код кроме серверных ошибок считаем успехом
                    return True
            except requests.exceptions.SSLError:
                # Если SSL ошибка, пробуем GET запрос
                try:
                    response = session.get(url, timeout=timeout//2, verify=False, allow_redirects=True)
                    if response.status_code < 500:
                        return True
                except:
                    continue
            except requests.exceptions.ConnectTimeout:
                continue
            except requests.exceptions.ConnectionError:
                continue
            except:
                continue
        
        # Если HTTP не работает, пробуем простое TCP соединение
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout//2)
                result = s.connect_ex((host, port))
                return result == 0
        except:
            pass
            
        return False
        
    except Exception as e:
        print(f"Error checking {host}:{port} - {str(e)}")
        return False

def resolve_hostname(hostname):
    """Резолвит hostname в IP адрес"""
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except:
        return None

def check_link_wrapper(link):
    """Обертка для проверки ссылки с определением страны"""
    protocol = link.split('://')[0].lower()
    host, port = None, None
    
    if protocol == 'vmess':
        host, port, config = parse_vmess(link)
    elif protocol in ['trojan', 'vless', 'ss']:
        host, port, parsed = parse_generic_url(link)
    
    # Проверяем соединение
    is_working = check_connection_advanced(host, port)
    
    if is_working:
        # Определяем IP адрес
        ip = resolve_hostname(host) if host else None
        if not ip:
            ip = host  # Если host уже является IP
            
        # Определяем страну
        country_code = "XX"
        if ip and ip != host:
            country_code = get_country_by_ip(ip)
        elif ip:  # host является IP адресом
            country_code = get_country_by_ip(ip)
            
        # Ограничиваем количество запросов к API (небольшая задержка)
        time.sleep(0.1)
        
        # Модифицируем ссылку с добавлением страны
        modified_link = modify_link_with_country(link, country_code)
        
        print(f"✅ Working [{country_code}]: {protocol}://{host}:{port}")
        return modified_link
    else:
        print(f"❌ Not working: {protocol}://{host}:{port}")
        return None

def main():
    base_dir = r'D:\01\mygithub\MitilVPN'
    input_file = os.path.join(base_dir, 'configs.txt')
    all_file = os.path.join(base_dir, 'config_all.txt')
    good_file = os.path.join(base_dir, 'config_good.txt')

    print("Начинаем обработку ссылок...")
    
    # Чтение и обработка исходного файла
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    new_links = extract_links(content)
    print(f"Найдено новых ссылок: {len(new_links)}")

    # Получение существующих ссылок
    existing_links = read_existing_links(all_file)
    print(f"Существующих ссылок: {len(existing_links)}")
    
    # Объединение и удаление дубликатов
    unique_links = list({link: None for link in existing_links + new_links}.keys())
    print(f"Уникальных ссылок всего: {len(unique_links)}")

    # Сохранение в config_all.txt
    save_links(all_file, unique_links)
    print(f"Сохранено в {all_file}")

    # Обнуляем файл config_good.txt перед проверкой
    save_links(good_file, [], mode='w')
    print(f"Файл {good_file} обнулен")

    # Проверка всех ссылок с многопоточностью
    print("Начинаем проверку ссылок...")
    good_links = []
    
    # Используем меньше потоков для избежания блокировки API геолокации
    max_workers = min(10, len(unique_links))  # Уменьшено до 10 потоков
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Запускаем проверку всех ссылок
        future_to_link = {executor.submit(check_link_wrapper, link): link for link in unique_links}
        
        completed = 0
        for future in as_completed(future_to_link):
            completed += 1
            result = future.result()
            if result:
                good_links.append(result)
            
            # Показываем прогресс
            if completed % 10 == 0 or completed == len(unique_links):
                print(f"Проверено: {completed}/{len(unique_links)}, найдено рабочих: {len(good_links)}")
    
    print(f"\nВсего проверено: {len(unique_links)}")
    print(f"Рабочих ссылок: {len(good_links)}")

    # Сохранение рабочих ссылок (полная перезапись)
    save_links(good_file, good_links)
    print(f"Рабочие ссылки сохранены в {good_file}")

    # Git операции
    print("Выполняем Git операции...")
    os.chdir(base_dir)
    
    # Проверяем статус git
    git_status = os.system('git status')
    
    os.system('git add config_all.txt config_good.txt')
    commit_result = os.system('git commit -m "Auto-update config files with country codes"')
    
    if commit_result == 0:  # Если коммит успешен
        push_result = os.system('git push')
        if push_result == 0:
            print("✅ Изменения успешно отправлены в GitHub")
        else:
            print("❌ Ошибка при отправке в GitHub")
    else:
        print("ℹ️ Нет изменений для коммита")

if __name__ == "__main__":
    main()