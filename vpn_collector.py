import re
import base64
import json
from urllib.parse import urlparse, parse_qs, unquote, quote, urlencode
import requests
import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket

# ─────────────────────────────────────────────
# TELEGRAM НАСТРОЙКИ
# Получить на https://my.telegram.org → API development tools
# ─────────────────────────────────────────────
TELEGRAM_API_ID   = 28391727
TELEGRAM_API_HASH = "04797f2c1301efeb568e62d9e0af7dc3"
TELEGRAM_PHONE    = "+79053896424"         # ← вставьте ваш номер телефона, например "+79001234567"
TELEGRAM_CHANNELS = [
    "napsternetv",
    "config_proxy",
    "v2rayngvpn",
    "vpnplusee_free",
    "v2Line",
    "V2rayNGX",
]
TELEGRAM_POSTS_LIMIT = 100     # сколько последних постов брать с каждого канала

# ─────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════
# GEO / IP
# ═══════════════════════════════════════════════════════════

def get_country_by_ip(ip):
    """Определяет страну по IP адресу"""
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=country,countryCode", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') != 'fail':
                return data.get('countryCode', 'XX')

        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        if response.status_code == 200:
            return response.json().get('country', 'XX')
    except Exception as e:
        print(f"Ошибка определения страны для {ip}: {e}")
    return "XX"


# ═══════════════════════════════════════════════════════════
# TELEGRAM — сбор ссылок
# ═══════════════════════════════════════════════════════════

def fetch_telegram_configs():
    """
    Скачивает последние TELEGRAM_POSTS_LIMIT постов из каждого канала
    и возвращает общий текст со всеми ссылками.
    Требует установленного пакета: pip install telethon
    """
    try:
        from telethon.sync import TelegramClient
        from telethon import errors
    except ImportError:
        print("⚠️  Telethon не установлен. Выполните: pip install telethon")
        return ""

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH or not TELEGRAM_PHONE:
        print("⚠️  Telegram credentials не заданы (TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE)")
        return ""

    all_text = ""
    session_file = "tg_session"

    try:
        with TelegramClient(session_file, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            if not client.is_user_authorized():
                client.send_code_request(TELEGRAM_PHONE)
                code = input("Введите код из Telegram: ")
                client.sign_in(TELEGRAM_PHONE, code)

            for channel in TELEGRAM_CHANNELS:
                try:
                    print(f"📨 Читаем канал: t.me/{channel}")
                    messages = client.get_messages(channel, limit=TELEGRAM_POSTS_LIMIT)
                    channel_text = ""
                    for msg in messages:
                        if msg.text:
                            channel_text += msg.text + "\n"
                        # обрабатываем кнопки с URL (inline keyboard)
                        if msg.reply_markup:
                            try:
                                for row in msg.reply_markup.rows:
                                    for btn in row.buttons:
                                        if hasattr(btn, 'url') and btn.url:
                                            channel_text += btn.url + "\n"
                            except Exception:
                                pass

                    found = len(extract_links(channel_text))
                    print(f"   ✅ Получено постов: {len(messages)}, найдено ссылок: {found}")
                    all_text += channel_text + "\n"

                except errors.ChannelPrivateError:
                    print(f"   ❌ Канал {channel} закрытый — нет доступа")
                except Exception as e:
                    print(f"   ❌ Ошибка при чтении {channel}: {e}")

    except Exception as e:
        print(f"❌ Ошибка Telegram клиента: {e}")

    return all_text


# ═══════════════════════════════════════════════════════════
# REMOTE HTTP SOURCES
# ═══════════════════════════════════════════════════════════

def fetch_remote_configs(url):
    """Загружает и декодирует конфигурации из удаленного источника"""
    try:
        print(f"Загрузка конфигов из: {url}")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            content = response.text.strip()
            try:
                missing_padding = len(content) % 4
                if missing_padding:
                    content += '=' * (4 - missing_padding)
                decoded = base64.b64decode(content).decode('utf-8')
                print(f"✅ Декодировано из {url}")
                return decoded
            except Exception:
                print(f"⚠️ Не base64 формат, используем как есть: {url}")
                return response.text
        else:
            print(f"❌ Ошибка загрузки {url}: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка при загрузке {url}: {e}")
    return ""


# ═══════════════════════════════════════════════════════════
# EXTRACT LINKS
# ═══════════════════════════════════════════════════════════

def extract_links(content):
    """Извлекает ссылки всех поддерживаемых протоколов"""
    protocols = [
        'vmess', 'trojan',
        'vless',          # VLESS (Xray/V2Ray)
        'ss', 'shadowsocks',
        'wireguard', 'wg',
        'hysteria', 'hysteria2', 'hy2',
        'tuic',           # TUIC v5
        'anytls', 'ssh',
        'socks', 'socks4', 'socks5',
        'http', 'https',
    ]
    pattern = r'(?:' + '|'.join(protocols) + r')://[^\s<>"\'`]+'
    links = re.findall(pattern, content, re.IGNORECASE)

    # JSON-конфиги (custom)
    json_pattern = r'\{[^}]*"protocol"\s*:\s*"[^"]*"[^}]*\}'
    json_configs = re.findall(json_pattern, content)

    return links + json_configs


# ═══════════════════════════════════════════════════════════
# FILE HELPERS
# ═══════════════════════════════════════════════════════════

def read_existing_links(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def save_links(filename, links, mode='w'):
    with open(filename, mode, encoding='utf-8') as f:
        f.write('\n'.join(links) + '\n' if links else '')


# ═══════════════════════════════════════════════════════════
# PARSERS
# ═══════════════════════════════════════════════════════════

def parse_vmess(link):
    try:
        b64_str = link[8:]
        b64_str += '=' * (-len(b64_str) % 4)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        config = json.loads(decoded)
        return config.get('add'), config.get('port'), config
    except:
        return None, None, None


def parse_vless(link):
    """
    Формат VLESS (Xray):
      vless://<uuid>@<host>:<port>?<params>#<name>
    """
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port or 443
        return host, port, parsed
    except:
        return None, None, None


def parse_tuic(link):
    """
    TUIC v5:
      tuic://<uuid>:<password>@<host>:<port>?<params>#<name>
    """
    try:
        parsed = urlparse(link)
        host = parsed.hostname
        port = parsed.port or 443
        return host, port, parsed
    except:
        return None, None, None


def parse_shadowsocks(link):
    try:
        content = link[14:] if link.startswith('shadowsocks://') else link[5:]
        if '@' in content:
            config_part = content.split('#')[0] if '#' in content else content
            _, server_part = config_part.split('@', 1)
            host, port = server_part.rsplit(':', 1)
            return host, int(port), content
        else:
            b64_part = content.split('#')[0] if '#' in content else content
            b64_part += '=' * (-len(b64_part) % 4)
            decoded = base64.b64decode(b64_part).decode('utf-8')
            if '@' in decoded:
                _, server_part = decoded.split('@', 1)
                host, port = server_part.rsplit(':', 1)
                return host, int(port), decoded
    except Exception as e:
        print(f"Ошибка парсинга Shadowsocks: {e}")
    return None, None, None


def parse_wireguard(link):
    try:
        parsed = urlparse(link)
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
    except Exception as e:
        print(f"Ошибка парсинга WireGuard: {e}")
    return None, None, None


def parse_hysteria(link):
    try:
        parsed = urlparse(link)
        if parsed.hostname:
            return parsed.hostname, parsed.port or 443, parsed
        content = link.split('://', 1)[1]
        host_part = content.split('@', 1)[-1]
        host_part = host_part.split('?')[0].split('#')[0]
        if ':' in host_part:
            host, port = host_part.rsplit(':', 1)
            return host, int(port), parsed
    except Exception as e:
        print(f"Ошибка парсинга Hysteria: {e}")
    return None, None, None


def parse_socks(link):
    try:
        parsed = urlparse(link)
        return parsed.hostname, parsed.port or 1080, parsed
    except:
        return None, None, None


def parse_ssh(link):
    try:
        parsed = urlparse(link)
        return parsed.hostname, parsed.port or 22, parsed
    except:
        return None, None, None


def parse_http_proxy(link):
    try:
        parsed = urlparse(link)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        return parsed.hostname, port, parsed
    except:
        return None, None, None


def parse_generic_url(link):
    """trojan, anytls и др."""
    try:
        parsed = urlparse(link)
        default_ports = {'trojan': 443, 'vless': 443, 'tuic': 443, 'anytls': 443}
        port = parsed.port or default_ports.get(parsed.scheme.lower(), 443)
        return parsed.hostname, port, parsed
    except:
        return None, None, None


# ═══════════════════════════════════════════════════════════
# LINK MODIFIER (добавляет [XX] страну к имени)
# ═══════════════════════════════════════════════════════════

def modify_link_with_country(link, country_code):
    if link.strip().startswith('{'):
        return link

    protocol = link.split('://')[0].lower()

    try:
        if protocol == 'vmess':
            b64_str = link[8:] + '=' * (-len(link[8:]) % 4)
            config = json.loads(base64.b64decode(b64_str).decode('utf-8'))
            ps = config.get('ps', '')
            if not ps.startswith(f"[{country_code}]"):
                config['ps'] = f"[{country_code}] {ps}".strip()
            new_b64 = base64.b64encode(json.dumps(config, ensure_ascii=False).encode()).decode()
            return f"vmess://{new_b64}"

        elif protocol in ['trojan', 'vless', 'ss', 'shadowsocks',
                          'hysteria', 'hysteria2', 'hy2', 'tuic', 'anytls',
                          'ssh', 'socks', 'socks4', 'socks5', 'http', 'https']:
            if '#' in link:
                base_link, name = link.rsplit('#', 1)
                name = unquote(name)
                if not name.startswith(f"[{country_code}]"):
                    name = f"[{country_code}] {name}".strip()
                return f"{base_link}#{quote(name)}"
            else:
                return f"{link}#{quote(f'[{country_code}] Server')}"

        elif protocol in ['wireguard', 'wg']:
            if '#' in link:
                base_link, frag = link.rsplit('#', 1)
                frag = unquote(frag)
                if not frag.startswith(f"[{country_code}]"):
                    frag = f"[{country_code}] {frag}".strip()
                return f"{base_link}#{quote(frag)}"
            return f"{link}#{quote(f'[{country_code}] WireGuard')}"

    except Exception as e:
        print(f"Ошибка при модификации ссылки: {e}")

    return link


# ═══════════════════════════════════════════════════════════
# CONNECTION CHECK
# ═══════════════════════════════════════════════════════════

def check_tcp_connection_speed(host, port, timeout=5, test_size=512):
    try:
        port = int(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            t0 = time.time()
            result = s.connect_ex((host, port))
            connect_time = (time.time() - t0) * 1000
            if result == 0:
                try:
                    t1 = time.time()
                    s.send(b'A' * test_size)
                    send_time = (time.time() - t1) * 1000
                    speed = (test_size * 8) / (send_time / 1000) / 1024 if send_time > 0 else 0
                    return True, connect_time, speed
                except:
                    return True, connect_time, 0
            return False, connect_time, 0
    except:
        return False, float('inf'), 0


def check_connection_with_speed(host, port, timeout=10):
    if not host or not port:
        return False, {}
    try:
        ok, ct, speed = check_tcp_connection_speed(host, port, timeout // 2)
        if ok:
            quality = ('excellent' if ct < 100 else
                       'good'      if ct < 300 else
                       'average'   if ct < 500 else 'poor')
            metrics = {
                'connect_time_ms': round(ct, 2),
                'speed_kbps': round(speed, 2),
                'connection_quality': quality,
            }
            if port in [80, 443, 8080, 8443]:
                try:
                    proto = 'https' if port in [443, 8443] else 'http'
                    t0 = time.time()
                    r = requests.head(f"{proto}://{host}:{port}", timeout=timeout // 3, verify=False)
                    metrics['http_response_time_ms'] = round((time.time() - t0) * 1000, 2)
                    metrics['http_status'] = r.status_code
                except:
                    pass
            return True, metrics
        return False, {'connect_time_ms': ct, 'error': 'connection_failed'}
    except Exception as e:
        return False, {'error': str(e)}


def resolve_hostname(hostname):
    try:
        return socket.gethostbyname(hostname)
    except:
        return None


# ═══════════════════════════════════════════════════════════
# LINK CHECKER (thread worker)
# ═══════════════════════════════════════════════════════════

PARSERS = {
    'vmess':       parse_vmess,
    'vless':       parse_vless,
    'ss':          parse_shadowsocks,
    'shadowsocks': parse_shadowsocks,
    'wireguard':   parse_wireguard,
    'wg':          parse_wireguard,
    'hysteria':    parse_hysteria,
    'hysteria2':   parse_hysteria,
    'hy2':         parse_hysteria,
    'tuic':        parse_tuic,
    'ssh':         parse_ssh,
    'socks':       parse_socks,
    'socks4':      parse_socks,
    'socks5':      parse_socks,
    'http':        parse_http_proxy,
    'https':       parse_http_proxy,
    'trojan':      parse_generic_url,
    'anytls':      parse_generic_url,
}


def check_link_wrapper(link):
    if link.strip().startswith('{'):
        return None

    protocol = link.split('://')[0].lower()
    parser = PARSERS.get(protocol)
    if not parser:
        return None

    host, port, _ = parser(link)
    if not host or not port:
        return None

    is_working, metrics = check_connection_with_speed(host, port)

    if is_working:
        ip = resolve_hostname(host) or host
        country_code = get_country_by_ip(ip) if ip else "XX"
        time.sleep(0.1)

        modified = modify_link_with_country(link, country_code)
        speed_s   = f" | Speed: {metrics.get('speed_kbps', 0):.1f} KB/s"
        connect_s = f" | Connect: {metrics.get('connect_time_ms', 0):.1f}ms"
        quality_s = f" | Quality: {metrics.get('connection_quality', 'unknown')}"
        print(f"✅ [{country_code}] {protocol}://{host}:{port}{connect_s}{speed_s}{quality_s}")
        return modified
    else:
        err = f" | {metrics.get('error', '')}" if metrics.get('error') else ""
        print(f"❌ {protocol}://{host}:{port}{err}")
        return None


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    base_dir   = r'D:\01\mygithub\MitilVPN'
    input_file = os.path.join(base_dir, 'configs.txt')
    all_file   = os.path.join(base_dir, 'config_all.txt')
    good_file  = os.path.join(base_dir, 'config_good_all.txt')

    print("=" * 60)
    print("Начинаем обработку ссылок...")
    print("=" * 60)

    # ── 1. Локальный файл ──────────────────────────────────
    all_content = ""
    if os.path.exists(input_file):
        print(f"\nЧтение локального файла: {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            all_content += f.read() + "\n"

    # ── 2. Удалённые HTTP источники ────────────────────────
    remote_sources = [
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/All_Configs_base64_Sub.txt',
    ]
    for url in remote_sources:
        content = fetch_remote_configs(url)
        if content:
            all_content += content + "\n"

    # ── 3. Telegram каналы ─────────────────────────────────
    print("\n" + "=" * 60)
    print("Сбор ссылок из Telegram каналов...")
    print("=" * 60)
    tg_content = fetch_telegram_configs()
    if tg_content:
        all_content += tg_content + "\n"
        print(f"📨 Telegram: найдено {len(extract_links(tg_content))} ссылок")

    # ── 4. Извлечение и дедупликация ──────────────────────
    new_links       = extract_links(all_content)
    existing_links  = read_existing_links(all_file)
    unique_links    = list(dict.fromkeys(existing_links + new_links))

    print(f"\n📊 Новых ссылок из всех источников: {len(new_links)}")
    print(f"📊 Существующих ссылок: {len(existing_links)}")
    print(f"📊 Уникальных ссылок всего: {len(unique_links)}")

    save_links(all_file, unique_links)
    print(f"💾 Сохранено в {all_file}")

    # ── 5. Проверка ────────────────────────────────────────
    save_links(good_file, [], mode='w')
    print(f"🔄 Файл {good_file} обнулен\n")
    print("=" * 60)
    print("Проверяем ссылки...")
    print("=" * 60 + "\n")

    good_links   = []
    max_workers  = min(10, len(unique_links))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_link_wrapper, lnk): lnk for lnk in unique_links}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            if result:
                good_links.append(result)
            if completed % 10 == 0 or completed == len(unique_links):
                print(f"\n📈 {completed}/{len(unique_links)} проверено, рабочих: {len(good_links)}\n")

    print("\n" + "=" * 60)
    print(f"✅ Всего проверено: {len(unique_links)}")
    print(f"✅ Рабочих ссылок: {len(good_links)}")
    if unique_links:
        print(f"📊 Успешных: {len(good_links)/len(unique_links)*100:.1f}%")
    print("=" * 60)

    save_links(good_file, good_links)
    print(f"\n💾 Рабочие ссылки → {good_file}")

    # ── 6. Git ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Git операции...")
    print("=" * 60)
    os.chdir(base_dir)
    os.system('git add config_all.txt config_good_all.txt')
    if os.system('git commit -m "Auto-update: country codes + Telegram + remote sources"') == 0:
        if os.system('git push') == 0:
            print("✅ Успешно отправлено в GitHub")
        else:
            print("❌ Ошибка git push")
    else:
        print("ℹ️ Нет изменений для коммита")

    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()
