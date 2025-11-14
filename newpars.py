import re
import base64
import json
from urllib.parse import urlparse, parse_qs, unquote, quote
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
                return f"{country_code}"
        
        # Резервный API - ipinfo.io
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get('country', 'XX')
            return country_code
            
    except Exception as e:
        print(f"Ошибка определения страны для {ip}: {str(e)}")
    
    return "XX"

def fetch_remote_configs(url):
    """Загружает и декодирует конфигурации из удаленного источника"""
    try:
        print(f"Загрузка конфигов из: {url}")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            content = response.text
            
            # Пытаемся декодировать base64
            try:
                # Убираем возможные пробелы и переносы строк
                content = content.strip()
                
                # Добавляем недостающий padding
                missing_padding = len(content) % 4
                if missing_padding:
                    content += '=' * (4 - missing_padding)
                
                decoded = base64.b64decode(content).decode('utf-8')
                print(f"✅ Декодировано из {url}")
                return decoded
            except Exception as e:
                # Если не base64, возвращаем как есть
                print(f"⚠️ Не base64 формат, используем как есть: {url}")
                return content
        else:
            print(f"❌ Ошибка загрузки {url}: HTTP {response.status_code}")
            return ""
    except Exception as e:
        print(f"❌ Ошибка при загрузке {url}: {str(e)}")
        return ""

def extract_links(content):
    """Извлекает ссылки всех поддерживаемых протоколов"""
    # Расширенный список протоколов
    protocols = [
        'vmess', 'trojan', 'vless', 'ss', 'shadowsocks',
        'wireguard', 'wg', 'hysteria', 'hysteria2', 'hy2',
        'tuic', 'anytls', 'ssh', 'socks', 'socks4', 'socks5',
        'http', 'https'
    ]
    
    pattern = r'(?:' + '|'.join(protocols) + r')://[^\s]+'
    links = re.findall(pattern, content, re.IGNORECASE)
    
    # Также ищем конфиги в JSON формате (для custom configs)
    json_pattern = r'\{[^}]*"protocol"\s*:\s*"[^"]*"[^}]*\}'
    json_configs = re.findall(json_pattern, content)
    
    return links + json_configs

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
            f.write('')

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

def parse_shadowsocks(link):
    """Парсит Shadowsocks ссылки (ss:// и shadowsocks://)"""
    try:
        # Убираем префикс протокола
        if link.startswith('shadowsocks://'):
            content = link[14:]
        else:
            content = link[5:]
        
        # Shadowsocks может быть в формате: ss://base64#name или ss://method:password@host:port#name
        if '@' in content:
            # Формат: method:password@host:port
            if '#' in content:
                config_part, name = content.rsplit('#', 1)
            else:
                config_part = content
            
            # Разделяем на метод:пароль и хост:порт
            if '@' in config_part:
                auth_part, server_part = config_part.split('@', 1)
                if ':' in server_part:
                    host, port = server_part.rsplit(':', 1)
                    return host, int(port), content
        else:
            # Base64 формат
            if '#' in content:
                b64_part, name = content.rsplit('#', 1)
            else:
                b64_part = content
            
            missing_padding = len(b64_part) % 4
            if missing_padding:
                b64_part += '=' * (4 - missing_padding)
            
            decoded = base64.b64decode(b64_part).decode('utf-8')
            # Формат: method:password@host:port
            if '@' in decoded:
                _, server_part = decoded.split('@', 1)
                if ':' in server_part:
                    host, port = server_part.rsplit(':', 1)
                    return host, int(port), decoded
        
    except Exception as e:
        print(f"Ошибка парсинга Shadowsocks: {str(e)}")
    
    return None, None, None

def parse_socks(link):
    """Парсит SOCKS ссылки"""
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port if parsed.port else 1080  # стандартный порт SOCKS
        return host, port, parsed
    except:
        return None, None, None

def parse_tuic(link):
    """Парсит TUIC ссылки"""
    try:
        # TUIC формат: tuic://uuid:password@host:port?param=value#name
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port if parsed.port else 443
        return host, port, parsed
    except:
        return None, None, None

def parse_ssh(link):
    """Парсит SSH ссылки"""
    try:
        # SSH формат: ssh://user:password@host:port или ssh://user@host:port
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port if parsed.port else 22  # стандартный порт SSH
        return host, port, parsed
    except:
        return None, None, None

def parse_http_proxy(link):
    """Парсит HTTP/HTTPS прокси ссылки"""
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        return host, port, parsed
    except:
        return None, None, None

def parse_wireguard(link):
    """Парсит WireGuard ссылки"""
    try:
        parsed = urlparse(link)
        
        if not parsed.netloc:
            try:
                config_data = parsed.path
                missing_padding = len(config_data) % 4
                if missing_padding:
                    config_data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(config_data).decode('utf-8')
                
                endpoint_match = re.search(r'Endpoint\s*=\s*([^:\s]+):(\d+)', decoded, re.IGNORECASE)
                if endpoint_match:
                    host = endpoint_match.group(1)
                    port = int(endpoint_match.group(2))
                    return host, port, decoded
            except:
                pass
        
        if parsed.netloc:
            host_port = parsed.netloc.split(':')
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 51820
            return host, port, parsed
        
        query_params = parse_qs(parsed.query)
        if 'endpoint' in query_params:
            endpoint = query_params['endpoint'][0]
            if ':' in endpoint:
                host, port = endpoint.rsplit(':', 1)
                return host, int(port), parsed
            else:
                return endpoint, 51820, parsed
                
    except Exception as e:
        print(f"Ошибка парсинга WireGuard: {str(e)}")
    
    return None, None, None

def parse_hysteria(link):
    """Парсит Hysteria и Hysteria2 ссылки"""
    try:
        parsed = urlparse(link)
        
        if parsed.hostname:
            host = parsed.hostname
            port = parsed.port if parsed.port else 443
            return host, port, parsed
        
        # Альтернативный парсинг
        protocol_len = len(link.split('://')[0]) + 3
        content = link[protocol_len:]
        
        if '@' in content:
            _, host_part = content.split('@', 1)
        else:
            host_part = content
        
        if '?' in host_part:
            host_part = host_part.split('?')[0]
        if '#' in host_part:
            host_part = host_part.split('#')[0]
        
        if ':' in host_part:
            host, port = host_part.rsplit(':', 1)
            try:
                port = int(port)
            except:
                port = 443
        else:
            host = host_part
            port = 443
            
        return host, port, parsed
        
    except Exception as e:
        print(f"Ошибка парсинга Hysteria: {str(e)}")
    
    return None, None, None

def parse_generic_url(link):
    """Обрабатывает trojan, vless и другие ссылки"""
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port
        
        if not port:
            protocol = parsed.scheme.lower()
            default_ports = {
                'trojan': 443,
                'vless': 443,
                'tuic': 443,
                'anytls': 443,
            }
            port = default_ports.get(protocol, 443)
                
        return host, port, parsed
    except:
        return None, None, None

def modify_link_with_country(link, country_code):
    """Модифицирует ссылку, добавляя код страны к имени"""
    # Если это JSON конфиг, не модифицируем
    if link.strip().startswith('{'):
        return link
    
    protocol = link.split('://')[0].lower()
    
    try:
        if protocol == 'vmess':
            b64_str = link[8:]
            missing_padding = len(b64_str) % 4
            if missing_padding:
                b64_str += '=' * (4 - missing_padding)
            decoded = base64.b64decode(b64_str).decode('utf-8')
            config = json.loads(decoded)
            
            current_ps = config.get('ps', '')
            if not current_ps.startswith(f"[{country_code}]"):
                config['ps'] = f"[{country_code}] {current_ps}".strip()
            
            new_config_str = json.dumps(config, ensure_ascii=False)
            new_b64 = base64.b64encode(new_config_str.encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
            
        elif protocol in ['trojan', 'vless', 'ss', 'shadowsocks', 'hysteria', 'hysteria2', 
                         'hy2', 'tuic', 'ssh', 'socks', 'socks4', 'socks5', 'http', 'https']:
            if '#' in link:
                base_link, current_name = link.rsplit('#', 1)
                current_name = unquote(current_name)
                if not current_name.startswith(f"[{country_code}]"):
                    new_name = f"[{country_code}] {current_name}".strip()
                    return f"{base_link}#{quote(new_name)}"
            else:
                return f"{link}#{quote(f'[{country_code}] Server')}"
                
        elif protocol in ['wireguard', 'wg']:
            if '?' in link:
                base_link, query_string = link.split('?', 1)
                
                if '#' in query_string:
                    query_string, fragment = query_string.rsplit('#', 1)
                    fragment = unquote(fragment)
                    if not fragment.startswith(f"[{country_code}]"):
                        fragment = f"[{country_code}] {fragment}".strip()
                    return f"{base_link}?{query_string}#{quote(fragment)}"
                else:
                    params = parse_qs(query_string)
                    if 'name' in params:
                        current_name = params['name'][0]
                        if not current_name.startswith(f"[{country_code}]"):
                            params['name'] = [f"[{country_code}] {current_name}".strip()]
                    else:
                        params['name'] = [f"[{country_code}] WireGuard Server"]
                    
                    from urllib.parse import urlencode
                    new_query = urlencode(params, doseq=True)
                    return f"{base_link}?{new_query}"
            else:
                return f"{link}?name={quote(f'[{country_code}] WireGuard Server')}"
                
    except Exception as e:
        print(f"Ошибка при модификации ссылки: {str(e)}")
    
    return link

def check_tcp_connection_speed(host, port, timeout=5, test_size=1024):
    """Проверяет TCP соединение и измеряет скорость"""
    try:
        port = int(port)
        start_time = time.time()
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            
            connect_start = time.time()
            result = s.connect_ex((host, port))
            connect_time = (time.time() - connect_start) * 1000
            
            if result == 0:
                try:
                    test_data = b'A' * min(test_size, 512)
                    
                    send_start = time.time()
                    s.send(test_data)
                    send_time = (time.time() - send_start) * 1000
                    
                    if send_time > 0:
                        speed_kbps = (len(test_data) * 8) / (send_time / 1000) / 1024
                    else:
                        speed_kbps = 0
                    
                    return True, connect_time, speed_kbps
                    
                except:
                    return True, connect_time, 0
            else:
                return False, connect_time, 0
                
    except Exception as e:
        return False, float('inf'), 0

def check_connection_with_speed(host, port, timeout=10):
    """Улучшенная проверка соединения с измерением скорости"""
    if not host or not port:
        return False, {}
    
    try:
        is_connected, connect_time, speed = check_tcp_connection_speed(host, port, timeout//2)
        
        if is_connected:
            metrics = {
                'connect_time_ms': round(connect_time, 2),
                'speed_kbps': round(speed, 2) if speed > 0 else 0,
                'connection_quality': 'excellent' if connect_time < 100 else 
                                    'good' if connect_time < 300 else 
                                    'average' if connect_time < 500 else 'poor'
            }
            
            if port in [80, 443, 8080, 8443]:
                try:
                    protocol = 'https' if port in [443, 8443] else 'http'
                    url = f"{protocol}://{host}:{port}"
                    
                    http_start = time.time()
                    response = requests.head(url, timeout=timeout//3, verify=False)
                    http_time = (time.time() - http_start) * 1000
                    
                    if response.status_code < 500:
                        metrics['http_response_time_ms'] = round(http_time, 2)
                        metrics['http_status'] = response.status_code
                        
                except:
                    pass
            
            return True, metrics
        else:
            return False, {'connect_time_ms': connect_time, 'error': 'connection_failed'}
            
    except Exception as e:
        return False, {'error': str(e)}

def resolve_hostname(hostname):
    """Резолвит hostname в IP адрес"""
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except:
        return None

def check_link_wrapper(link):
    """Обертка для проверки ссылки с определением страны и скорости"""
    # Пропускаем JSON конфиги
    if link.strip().startswith('{'):
        return None
    
    protocol = link.split('://')[0].lower()
    host, port = None, None
    
    # Парсим ссылку в зависимости от протокола
    parsers = {
        'vmess': parse_vmess,
        'ss': parse_shadowsocks,
        'shadowsocks': parse_shadowsocks,
        'wireguard': parse_wireguard,
        'wg': parse_wireguard,
        'hysteria': parse_hysteria,
        'hysteria2': parse_hysteria,
        'hy2': parse_hysteria,
        'tuic': parse_tuic,
        'ssh': parse_ssh,
        'socks': parse_socks,
        'socks4': parse_socks,
        'socks5': parse_socks,
        'http': parse_http_proxy,
        'https': parse_http_proxy,
    }
    
    if protocol in parsers:
        host, port, config = parsers[protocol](link)
    elif protocol in ['trojan', 'vless', 'anytls']:
        host, port, parsed = parse_generic_url(link)
    
    if not host or not port:
        return None
    
    # Проверяем соединение
    is_working, metrics = check_connection_with_speed(host, port)
    
    if is_working:
        ip = resolve_hostname(host) if host else None
        if not ip:
            ip = host
            
        country_code = "XX"
        if ip:
            country_code = get_country_by_ip(ip)
        
        time.sleep(0.1)  # Задержка для API
        
        modified_link = modify_link_with_country(link, country_code)
        
        speed_info = f" | Speed: {metrics.get('speed_kbps', 0):.1f} KB/s" if metrics.get('speed_kbps', 0) > 0 else ""
        connect_info = f" | Connect: {metrics.get('connect_time_ms', 0):.1f}ms"
        quality_info = f" | Quality: {metrics.get('connection_quality', 'unknown')}"
        
        print(f"✅ Working [{country_code}]: {protocol}://{host}:{port}{connect_info}{speed_info}{quality_info}")
        return modified_link
    else:
        error_info = f" | Error: {metrics.get('error', 'unknown')}" if 'error' in metrics else ""
        print(f"❌ Not working: {protocol}://{host}:{port}{error_info}")
        return None

def main():
    base_dir = r'D:\01\mygithub\MitilVPN'
    input_file = os.path.join(base_dir, 'configs.txt')
    all_file = os.path.join(base_dir, 'config_all.txt')
    good_file = os.path.join(base_dir, 'config_good_all.txt')

    print("=" * 60)
    print("Начинаем обработку ссылок...")
    print("=" * 60)
    
    # Загрузка из удаленных источников
    remote_sources = [
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/All_Configs_base64_Sub.txt'
    ]
    
    all_content = ""
    
    # Читаем локальный файл
    if os.path.exists(input_file):
        print(f"\nЧтение локального файла: {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            all_content += f.read() + "\n"
    
    # Загружаем удаленные конфиги
    for url in remote_sources:
        remote_content = fetch_remote_configs(url)
        if remote_content:
            all_content += remote_content + "\n"
    
    # Извлекаем ссылки
    new_links = extract_links(all_content)
    print(f"\n📊 Найдено новых ссылок: {len(new_links)}")

    # Получение существующих ссылок
    existing_links = read_existing_links(all_file)
    print(f"📊 Существующих ссылок: {len(existing_links)}")
    
    # Объединение и удаление дубликатов
    unique_links = list(dict.fromkeys(existing_links + new_links))
    print(f"📊 Уникальных ссылок всего: {len(unique_links)}")

    # Сохранение в config_all.txt
    save_links(all_file, unique_links)
    print(f"💾 Сохранено в {all_file}")

    # Обнуляем файл config_good_all.txt перед проверкой
    save_links(good_file, [], mode='w')
    print(f"🔄 Файл {good_file} обнулен")

    # Проверка всех ссылок
    print("\n" + "=" * 60)
    print("Начинаем проверку ссылок...")
    print("=" * 60 + "\n")
    
    good_links = []
    max_workers = min(10, len(unique_links))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_link = {executor.submit(check_link_wrapper, link): link for link in unique_links}
        
        completed = 0
        for future in as_completed(future_to_link):
            completed += 1
            result = future.result()
            if result:
                good_links.append(result)
            
            if completed % 10 == 0 or completed == len(unique_links):
                print(f"\n📈 Прогресс: {completed}/{len(unique_links)}, найдено рабочих: {len(good_links)}\n")
    
    print("\n" + "=" * 60)
    print(f"✅ Всего проверено: {len(unique_links)}")
    print(f"✅ Рабочих ссылок: {len(good_links)}")
    print(f"📊 Процент успешных: {len(good_links)/len(unique_links)*100:.1f}%" if unique_links else "0%")
    print("=" * 60 + "\n")

    # Сохранение рабочих ссылок
    save_links(good_file, good_links)
    print(f"💾 Рабочие ссылки сохранены в {good_file}")

    # Git операции
    print("\n" + "=" * 60)
    print("Выполняем Git операции...")
    print("=" * 60)
    
    os.chdir(base_dir)
    
    os.system('git add config_all.txt config_good_all.txt')
    commit_result = os.system('git commit -m "Auto-update config files with country codes and remote sources"')
    
    if commit_result == 0:
        push_result = os.system('git push')
        if push_result == 0:
            print("✅ Изменения успешно отправлены в GitHub")
        else:
            print("❌ Ошибка при отправке в GitHub")
    else:
        print("ℹ️ Нет изменений для коммита")
    
    print("\n" + "=" * 60)
    print("Обработка завершена!")
    print("=" * 60)

if __name__ == "__main__":
    main()