import re
import base64
import json
from urllib.parse import urlparse, parse_qs, unquote
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
    # Добавлены wireguard и hysteria2 протоколы
    pattern = r'(?:vmess|trojan|vless|ss|wireguard|hysteria2)://[^\s]+'
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

def parse_wireguard(link):
    """Парсит WireGuard ссылки"""
    try:
        # WireGuard ссылки обычно имеют формат wireguard://config_base64?name=...
        # или wireguard://endpoint:port?publickey=...&privatekey=...&name=...
        parsed = urlparse(link)
        
        # Если это base64 конфиг
        if not parsed.netloc:
            # Пытаемся декодировать как base64
            try:
                config_data = parsed.path
                missing_padding = len(config_data) % 4
                if missing_padding:
                    config_data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(config_data).decode('utf-8')
                
                # Ищем Endpoint в конфиге
                endpoint_match = re.search(r'Endpoint\s*=\s*([^:\s]+):(\d+)', decoded, re.IGNORECASE)
                if endpoint_match:
                    host = endpoint_match.group(1)
                    port = int(endpoint_match.group(2))
                    return host, port, decoded
            except:
                pass
        
        # Если это URL с параметрами
        if parsed.netloc:
            host_port = parsed.netloc.split(':')
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 51820  # стандартный порт WireGuard
            return host, port, parsed
        
        # Пытаемся извлечь из query параметров
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

def parse_hysteria2(link):
    """Парсит Hysteria2 ссылки"""
    try:
        # Hysteria2 ссылки имеют формат hysteria2://password@host:port?param=value#name
        parsed = urlparse(link)
        
        if parsed.hostname:
            host = parsed.hostname
            port = parsed.port if parsed.port else 443  # стандартный порт для Hysteria2
            return host, port, parsed
        
        # Альтернативный парсинг если стандартный не работает
        # Убираем протокол
        content = link[11:]  # убираем 'hysteria2://'
        
        # Ищем @ для разделения пароля и хоста
        if '@' in content:
            _, host_part = content.split('@', 1)
        else:
            host_part = content
        
        # Убираем параметры и имя
        if '?' in host_part:
            host_part = host_part.split('?')[0]
        if '#' in host_part:
            host_part = host_part.split('#')[0]
        
        # Парсим host:port
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
        print(f"Ошибка парсинга Hysteria2: {str(e)}")
    
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
            
        elif protocol in ['trojan', 'vless', 'ss', 'hysteria2']:
            # Для trojan, vless, ss и hysteria2 изменяем fragment (имя после #)
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
                
        elif protocol == 'wireguard':
            # Для WireGuard добавляем имя в query параметры или модифицируем существующее
            from urllib.parse import parse_qs, urlencode, quote
            
            if '?' in link:
                base_link, query_string = link.split('?', 1)
                
                # Парсим существующие параметры
                if '#' in query_string:
                    query_string, fragment = query_string.rsplit('#', 1)
                    fragment = unquote(fragment)
                    if not fragment.startswith(f"[{country_code}]"):
                        fragment = f"[{country_code}] {fragment}".strip()
                    return f"{base_link}?{query_string}#{quote(fragment)}"
                else:
                    # Добавляем name в query параметры
                    params = parse_qs(query_string)
                    if 'name' in params:
                        current_name = params['name'][0]
                        if not current_name.startswith(f"[{country_code}]"):
                            params['name'] = [f"[{country_code}] {current_name}".strip()]
                    else:
                        params['name'] = [f"[{country_code}] WireGuard Server"]
                    
                    new_query = urlencode(params, doseq=True)
                    return f"{base_link}?{new_query}"
            else:
                # Если нет параметров, добавляем name
                from urllib.parse import quote
                return f"{link}?name={quote(f'[{country_code}] WireGuard Server')}"
                
    except Exception as e:
        print(f"Ошибка при модификации ссылки: {str(e)}")
    
    return link  # Возвращаем оригинальную ссылку в случае ошибки

def check_tcp_connection_speed(host, port, timeout=5, test_size=1024):
    """Проверяет TCP соединение и измеряет скорость"""
    try:
        port = int(port)
        start_time = time.time()
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            
            # Измеряем время подключения
            connect_start = time.time()
            result = s.connect_ex((host, port))
            connect_time = (time.time() - connect_start) * 1000  # в миллисекундах
            
            if result == 0:
                # Соединение успешно
                try:
                    # Пытаемся отправить небольшой объем данных для проверки скорости
                    test_data = b'A' * min(test_size, 512)  # Уменьшенный размер для безопасности
                    
                    send_start = time.time()
                    s.send(test_data)
                    send_time = (time.time() - send_start) * 1000
                    
                    # Рассчитываем примерную скорость (очень приблизительно)
                    if send_time > 0:
                        speed_kbps = (len(test_data) * 8) / (send_time / 1000) / 1024
                    else:
                        speed_kbps = 0
                    
                    return True, connect_time, speed_kbps
                    
                except (socket.timeout, ConnectionResetError, BrokenPipeError):
                    # Даже если отправка данных не удалась, соединение работает
                    return True, connect_time, 0
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
        # Основная проверка через TCP
        is_connected, connect_time, speed = check_tcp_connection_speed(host, port, timeout//2)
        
        if is_connected:
            # Дополнительные метрики
            metrics = {
                'connect_time_ms': round(connect_time, 2),
                'speed_kbps': round(speed, 2) if speed > 0 else 0,
                'connection_quality': 'excellent' if connect_time < 100 else 
                                    'good' if connect_time < 300 else 
                                    'average' if connect_time < 500 else 'poor'
            }
            
            # Дополнительная проверка через HTTP для веб-серверов (опционально)
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
                    pass  # HTTP проверка опциональна
            
            return True, metrics
        else:
            return False, {'connect_time_ms': connect_time, 'error': 'connection_failed'}
            
    except Exception as e:
        return False, {'error': str(e)}

def ping_test(host, timeout=3):
    """Простой ping тест для дополнительной проверки"""
    try:
        # Используем системную команду ping
        import subprocess
        import platform
        
        # Определяем параметры ping для разных ОС
        if platform.system().lower() == 'windows':
            cmd = ['ping', '-n', '1', '-w', str(timeout * 1000), host]
        else:
            cmd = ['ping', '-c', '1', '-W', str(timeout), host]
        
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        ping_time = (time.time() - start_time) * 1000
        
        if result.returncode == 0:
            # Извлекаем время ping из вывода
            output = result.stdout
            if platform.system().lower() == 'windows':
                ping_match = re.search(r'время[<=]\s*(\d+)\s*мс', output, re.IGNORECASE)
                if not ping_match:
                    ping_match = re.search(r'time[<=]\s*(\d+)\s*ms', output, re.IGNORECASE)
            else:
                ping_match = re.search(r'time=(\d+\.?\d*)\s*ms', output)
            
            if ping_match:
                actual_ping = float(ping_match.group(1))
                return True, actual_ping
            else:
                return True, ping_time
        
        return False, ping_time
        
    except:
        return False, float('inf')

def resolve_hostname(hostname):
    """Резолвит hostname в IP адрес"""
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except:
        return None

def parse_wireguard(link):
    """Парсит WireGuard ссылки"""
    try:
        # WireGuard ссылки обычно имеют формат wireguard://config_base64?name=...
        # или wireguard://endpoint:port?publickey=...&privatekey=...&name=...
        parsed = urlparse(link)
        
        # Если это base64 конфиг
        if not parsed.netloc:
            # Пытаемся декодировать как base64
            try:
                config_data = parsed.path
                missing_padding = len(config_data) % 4
                if missing_padding:
                    config_data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(config_data).decode('utf-8')
                
                # Ищем Endpoint в конфиге
                endpoint_match = re.search(r'Endpoint\s*=\s*([^:\s]+):(\d+)', decoded, re.IGNORECASE)
                if endpoint_match:
                    host = endpoint_match.group(1)
                    port = int(endpoint_match.group(2))
                    return host, port, decoded
            except:
                pass
        
        # Если это URL с параметрами
        if parsed.netloc:
            host_port = parsed.netloc.split(':')
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 51820  # стандартный порт WireGuard
            return host, port, parsed
        
        # Пытаемся извлечь из query параметров
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

def parse_hysteria2(link):
    """Парсит Hysteria2 ссылки"""
    try:
        # Hysteria2 ссылки имеют формат hysteria2://password@host:port?param=value#name
        parsed = urlparse(link)
        
        if parsed.hostname:
            host = parsed.hostname
            port = parsed.port if parsed.port else 443  # стандартный порт для Hysteria2
            return host, port, parsed
        
        # Альтернативный парсинг если стандартный не работает
        # Убираем протокол
        content = link[11:]  # убираем 'hysteria2://'
        
        # Ищем @ для разделения пароля и хоста
        if '@' in content:
            _, host_part = content.split('@', 1)
        else:
            host_part = content
        
        # Убираем параметры и имя
        if '?' in host_part:
            host_part = host_part.split('?')[0]
        if '#' in host_part:
            host_part = host_part.split('#')[0]
        
        # Парсим host:port
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
        print(f"Ошибка парсинга Hysteria2: {str(e)}")
    
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

def check_link_wrapper(link):
    """Обертка для проверки ссылки с определением страны и скорости"""
    protocol = link.split('://')[0].lower()
    host, port = None, None
    
    # Парсим ссылку в зависимости от протокола
    if protocol == 'vmess':
        host, port, config = parse_vmess(link)
    elif protocol == 'wireguard':
        host, port, config = parse_wireguard(link)
    elif protocol == 'hysteria2':
        host, port, config = parse_hysteria2(link)
    elif protocol in ['trojan', 'vless', 'ss']:
        host, port, parsed = parse_generic_url(link)
    
    # Проверяем соединение и скорость
    is_working, metrics = check_connection_with_speed(host, port)
    
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
        
        # Ping тест для дополнительной информации
        ping_success, ping_ms = ping_test(host)
        if ping_success:
            metrics['ping_ms'] = round(ping_ms, 2)
            
        # Ограничиваем количество запросов к API (небольшая задержка)
        time.sleep(0.1)
        
        # Модифицируем ссылку с добавлением страны
        modified_link = modify_link_with_country(link, country_code)
        
        # Расширенный вывод с метриками
        speed_info = f" | Speed: {metrics.get('speed_kbps', 0):.1f} KB/s" if metrics.get('speed_kbps', 0) > 0 else ""
        ping_info = f" | Ping: {metrics.get('ping_ms', 0):.1f}ms" if metrics.get('ping_ms', 0) > 0 else ""
        connect_info = f" | Connect: {metrics.get('connect_time_ms', 0):.1f}ms"
        quality_info = f" | Quality: {metrics.get('connection_quality', 'unknown')}"
        
        print(f"✅ Working [{country_code}]: {protocol}://{host}:{port}{connect_info}{ping_info}{speed_info}{quality_info}")
        return modified_link
    else:
        error_info = f" | Error: {metrics.get('error', 'unknown')}" if 'error' in metrics else ""
        print(f"❌ Not working: {protocol}://{host}:{port}{error_info}")
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