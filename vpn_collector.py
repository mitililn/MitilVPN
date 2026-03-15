import re
import base64
import json
import os
import time
import socket
import ssl
import sys
from urllib.parse import urlparse, parse_qs, unquote, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

# Проверка зависимостей
try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except ImportError:
    print("❌ Ошибка: pip install requests")
    exit(1)

try:
    from telethon.sync import TelegramClient
    from telethon import errors
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
# 1. НАСТРОЙКИ (КАНАЛЫ И АККАУНТ)
# ═══════════════════════════════════════════════════════════

TELEGRAM_API_ID   = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE    = os.environ.get("TELEGRAM_PHONE", "")

TELEGRAM_CHANNELS = [
    "napsternetv", "config_proxy", "v2rayngvpn", "vpnplusee_free", 
    "v2Line", "V2rayNGX", "VmessSub", "v2ray_outline_config"
]
TELEGRAM_POSTS_LIMIT = 100

# ═══════════════════════════════════════════════════════════
# 2. ФУНКЦИИ СБОРА И ПРОВЕРКИ
# ═══════════════════════════════════════════════════════════

def get_country_by_ip(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3)
        return r.json().get('countryCode', 'XX')
    except: return "XX"

def extract_links(content):
    protocols = ['vmess', 'trojan', 'vless', 'ss', 'shadowsocks', 'wireguard', 'hysteria', 'hy2', 'tuic']
    pattern = r'(?:' + '|'.join(protocols) + r')://[^\s<>"\`]+'
    return re.findall(pattern, content, re.IGNORECASE)

def parse_vmess(link):
    try:
        b64_str = link[8:]
        b64_str += '=' * (-len(b64_str) % 4)
        config = json.loads(base64.b64decode(b64_str).decode('utf-8'))
        return config.get('add'), config.get('port')
    except: return None, None

def parse_generic(link):
    try:
        parsed = urlparse(link)
        return parsed.hostname, parsed.port or 443
    except: return None, None

PARSERS = {
    'vmess': parse_vmess, 'vless': parse_generic, 'trojan': parse_generic,
    'ss': parse_generic, 'shadowsocks': parse_generic, 'hysteria2': parse_generic, 'hy2': parse_generic,
}

def deep_check(host, port, protocol, timeout=4):
    try:
        port = int(port)
        sock = socket.create_connection((host, port), timeout=timeout)
        tls_protocols = ['vless', 'vmess', 'trojan', 'https', 'anytls', 'hysteria', 'hy2']
        if any(p in protocol.lower() for p in tls_protocols):
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            try:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    ssock.settimeout(timeout)
                    return True
            except: return False
        sock.close()
        return True
    except: return False

def modify_link_with_country(link, country_code):
    try:
        if '#' in link:
            base, name = link.rsplit('#', 1)
            return f"{base}#{quote(f'[{country_code}] {unquote(name)}')}"
        return f"{link}#{quote(f'[{country_code}] Node')}"
    except: return link

def check_link_worker(link):
    protocol = link.split('://')[0].lower()
    parser = PARSERS.get(protocol, parse_generic)
    host, port = parser(link)
    if host and port:
        if deep_check(host, port, protocol):
            try:
                ip = socket.gethostbyname(host) if not re.match(r'\d+\.\d+', host) else host
                cc = get_country_by_ip(ip)
                return modify_link_with_country(link, cc)
            except: return modify_link_with_country(link, "XX")
    return None

def fetch_telegram_configs():
    if not (TELETHON_AVAILABLE and TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_PHONE):
        print("⚠️  Telegram данные не найдены. Пропуск.")
        return ""
    all_text = ""
    print("\n📨 Начинаю сбор из Telegram...")
    try:
        with TelegramClient('session_name', int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as client:
            for channel in TELEGRAM_CHANNELS:
                sys.stdout.write(f"\r   Читаю канал: {channel}... ")
                sys.stdout.flush()
                for msg in client.iter_messages(channel, limit=TELEGRAM_POSTS_LIMIT):
                    if msg.text: all_text += msg.text + "\n"
        print("\n✅ Telegram загружен.")
    except Exception as e:
        print(f"\n❌ Ошибка Telegram: {e}")
    return all_text

# ═══════════════════════════════════════════════════════════
# 3. ОСНОВНОЙ ЦИКЛ
# ═══════════════════════════════════════════════════════════

def main():
    start_time = time.time()
    all_content = ""
    
    # Вставьте сюда ваш полный список remote_sources (я оставил часть для примера)
    remote_sources = [
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vmess.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/trojan.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/ss.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/All_Configs_base64_Sub.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub1.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub2.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub3.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub4.txt',
        'https://raw.githubusercontent.com/coldwater-10/V2ray-Config/main/Sub1.txt',
        'https://raw.githubusercontent.com/coldwater-10/V2ray-Config/main/Sub2.txt',
        'https://raw.githubusercontent.com/coldwater-10/V2ray-Config/main/Sub3.txt',
        'https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2',
        'https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2ray.txt',
        'https://raw.githubusercontent.com/freev2ray/freev2ray/main/v2ray',
        'https://raw.githubusercontent.com/freev2ray/freev2ray/main/vmess',
        'https://raw.githubusercontent.com/vpei/Free-Node-Merge/main/o/node.txt',
        'https://raw.githubusercontent.com/vpei/Free-Node-Merge/main/o/all.txt',
        'https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub',
        'https://raw.githubusercontent.com/mheidari98/.proxy/main/all',
        'https://raw.githubusercontent.com/ts-sf/fly/main/v2',
        'https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt',
        'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/vmess/data.txt',
        'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/vless/data.txt',
        'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/trojan/data.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/vmess.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/vless.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/trojan.txt',
        'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/ss.txt',
        'https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/all.txt',
        'https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/v2ray.txt',
        'https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml',
        'https://raw.githubusercontent.com/anaer/Sub/main/v2ray.txt',
        'https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/sub.txt',
        'https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/vmess.txt',
        'https://raw.githubusercontent.com/Ruk1ng001/freeSub/main/subscription', 
        'https://raw.githubusercontent.com/Ruk1ng001/freeSub/main/clash.yaml',
        'https://raw.githubusercontent.com/itsyebekhe/HiN-VPN/main/subscription/normal/base64',
        'https://raw.githubusercontent.com/itsyebekhe/HiN-VPN/main/subscription/normal/plain',
        'https://raw.githubusercontent.com/itsyebekhe/HiN-VPN/main/subscription/hiddify/normal/base64',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vmess',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vless',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/trojan',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/shadowsocks',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/countries/us',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/countries/de',
        'https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/countries/fr',
        'https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt',
        'https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_BASE64.txt',
        'https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_raw.txt',
        'https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list_base64.txt',
        'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt',
        'https://raw.githubusercontent.com/zieng2/wl/refs/heads/main/vless_universal.txt',
        'https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/1.txt',
        'https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/4.txt',
        'https://raw.githubusercontent.com/STR97/STRUGOV/refs/heads/main/STR.BYPASS',
        'https://raw.githubusercontent.com/Danialsamadi/v2go/refs/heads/main/AllConfigsSub.txt',
        'https://raw.githubusercontent.com/Firmfox/Proxify/refs/heads/main/v2ray_configs/mixed/subscription-1.txt',
        'https://raw.githubusercontent.com/Firmfox/Proxify/refs/heads/main/v2ray_configs/mixed/subscription-2.txt',
        'https://raw.githubusercontent.com/Firmfox/Proxify/refs/heads/main/v2ray_configs/seperated_by_protocol/shadowsocks.txt',
        'https://raw.githubusercontent.com/LalatinaHub/Mineral/refs/heads/master/result/nodes',
        'https://raw.githubusercontent.com/Farid-Karimi/Config-Collector/refs/heads/main/mixed_iran.txt',
        'https://raw.githubusercontent.com/nscl5/4/refs/heads/main/Splitted-By-Protocol/ss.txt',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/refs/heads/main/subscriptions/v2ray/super-sub.txt',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/refs/heads/main/subscriptions/v2ray/all_sub.txt',
        'https://raw.githubusercontent.com/itsyebekhe/PSG/main/subscriptions/xray/base64/xhttp',
        'https://raw.githubusercontent.com/itsyebekhe/PSG/main/subscriptions/nekobox/mix.json',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/subs/sub1.txt',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/ss.txt',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt',
        'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vmess.txt',
        'https://robin.victoriacross.ir',
        'https://raw.githubusercontent.com/NiREvil/vless/refs/heads/main/sub/SSTime',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/ss.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vmess.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt',
        'https://v2.alicivil.workers.dev',
        'https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity',
        'https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/sub/splitted/trojan.txt',
        'https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/refs/heads/main/Best-Results/proxies.txt',
        'https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/main/splitted-by-protocol/vless.txt',
        'https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/main/splitted-by-protocol/shadowsocks.txt',
        'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/mixed',
        'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/python/hysteria2',
        'https://raw.githubusercontent.com/Pawdroid/Free-servers/main/static/sub_en',
        'https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/httpupgrade.txt',
        'https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/xhttp.txt',
        'https://shadowmere.xyz/api/b64sub',
        'https://openproxylist.com/v2ray/',
        'https://raw.githubusercontent.com/NiREvil/vless/refs/heads/main/sub/fragment',
        'https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/refs/heads/main/Protocols/ss.txt',
        'https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/mix/sub.html',
        'https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/vless.html',
        'https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/refs/heads/main/Protocols/vmess.txt',
        'https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/refs/heads/main/Protocols/vless.txt',
        'https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/master/sub/proxies.txt',
        'https://raw.githubusercontent.com/10ium/free-config/refs/heads/main/HighSpeed.txt',
        'https://github.com/4n0nymou3/multi-proxy-config-fetcher/raw/refs/heads/main/configs/proxy_configs.txt',
        'https://sub.amiralter.com/config-lite',
        'https://sub.amiralter.com/config',
        'https://raw.githubusercontent.com/DarknessShade/Sub/main/V2mix',
        'https://raw.githubusercontent.com/DarknessShade/Sub/main/Ss',
        'https://raw.githubusercontent.com/nscl5/5/refs/heads/main/configs/vmess.txt',
        'https://raw.githubusercontent.com/nscl5/5/refs/heads/main/configs/all.txt',
        'https://raw.githubusercontent.com/itsyebekhe/PSG/main/lite/subscriptions/xray/normal/hy2',
        'https://raw.githubusercontent.com/itsyebekhe/PSG/main/subscriptions/xray/normal/vmess',
        'https://raw.githubusercontent.com/lagzian/IranConfigCollector/main/Base64.txt',
        'https://raw.githubusercontent.com/lagzian/SS-Collector/refs/heads/main/SS/TrinityBase',
        'https://raw.githubusercontent.com/MahsaNetConfigTopic/config/refs/heads/main/xray_final.txt',
        'https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/sub/vless.txt',
        'https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/sub/vmess.txt',
        'https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/sub/ss.txt',
        'https://raw.githubusercontent.com/AzadNetCH/Clash/main/AzadNet.txt',
        'https://raw.githubusercontent.com/Leon406/SubCrawler/refs/heads/main/sub/share/a11',
        'https://raw.githubusercontent.com/imalrzai/ExclaveVirtual/refs/heads/main/ExclaveVirtual',
        'https://raw.githubusercontent.com/youfoundamin/V2rayCollector/main/mixed_iran.txt',
        'https://raw.githubusercontent.com/youfoundamin/V2rayCollector/main/ss_iran.txt',
        'https://raw.githubusercontent.com/youfoundamin/V2rayCollector/main/vless_iran.txt',
        'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/ss',
        'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/trojan',
        'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/vless',
        'https://raw.githubusercontent.com/HosseinKoofi/GO_V2rayCollector/main/mixed_iran.txt',
        'https://raw.githubusercontent.com/HosseinKoofi/GO_V2rayCollector/main/vless_iran.txt',
        'https://raw.githubusercontent.com/HosseinKoofi/GO_V2rayCollector/main/ss_iran.txt',
        'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/ss_configs.txt',
        'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt',
        'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/vmess_configs.txt',
        'https://raw.githubusercontent.com/Argh94/V2RayAutoConfig/refs/heads/main/configs/Vmess.txt',
        'https://raw.githubusercontent.com/Argh94/V2RayAutoConfig/refs/heads/main/configs/Hysteria2.txt',
        'https://raw.githubusercontent.com/Argh94/V2RayAutoConfig/refs/heads/main/configs/Germany.txt',
        'https://raw.githubusercontent.com/Stinsonysm/GO_V2rayCollector/refs/heads/main/trojan_iran.txt',
        'https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector_Py/refs/heads/main/sub/Mix/mix.txt',
        'https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector_Py/refs/heads/main/sub/United%20States/config.txt',
        'https://raw.githubusercontent.com/liketolivefree/kobabi/main/sub.txt',
        'https://raw.githubusercontent.com/liketolivefree/kobabi/main/sub_all.txt',
        'https://raw.githubusercontent.com/10ium/ScrapeAndCategorize/refs/heads/main/output_configs/Hysteria2.txt',
        'https://raw.githubusercontent.com/10ium/V2ray-Config/main/Splitted-By-Protocol/hysteria2.txt',
        'https://raw.githubusercontent.com/10ium/V2Hub3/main/merged_base64',
        'https://raw.githubusercontent.com/10ium/V2Hub3/refs/heads/main/Split/Normal/shadowsocks',
        'https://raw.githubusercontent.com/10ium/V2Hub3/refs/heads/main/Split/Normal/reality',
        'https://raw.githubusercontent.com/10ium/base64-encoder/main/encoded/10ium_mixed_iran.txt',
        'https://raw.githubusercontent.com/10ium/ScrapeAndCategorize/refs/heads/main/output_configs/Vless.txt',
        'https://raw.githubusercontent.com/10ium/ScrapeAndCategorize/refs/heads/main/output_configs/ShadowSocks.txt',
        'https://raw.githubusercontent.com/10ium/ScrapeAndCategorize/refs/heads/main/output_configs/Trojan.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/Sub1.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/Sub2.txt',
        'https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/Sub3.txt',
        'https://raw.githubusercontent.com/aqayerez/MatnOfficial-VPN/refs/heads/main/MatnOfficial',
        'https://raw.githubusercontent.com/V2RAYCONFIGSPOOL/V2RAY_SUB/refs/heads/main/v2ray_configs.txt',
        'https://raw.githubusercontent.com/bamdad23/JavidnamanIran/refs/heads/main/WS%2BHysteria2',
        'https://raw.githubusercontent.com/mshojaei77/v2rayAuto/refs/heads/main/telegram/popular_channels_1',
        'https://raw.githubusercontent.com/mshojaei77/v2rayAuto/refs/heads/main/telegram/popular_channels_2',
        'https://raw.githubusercontent.com/mshojaei77/v2rayAuto/refs/heads/main/subs/hysteria',
        'https://raw.githubusercontent.com/mshojaei77/v2rayAuto/refs/heads/main/subs/hy2',
        'https://raw.githubusercontent.com/ndsphonemy/proxy-sub/refs/heads/main/speed.txt',
        'https://raw.githubusercontent.com/ndsphonemy/proxy-sub/refs/heads/main/hys-tuic.txt',
        'https://trojanvmess.pages.dev/cmcm?b64',
        'https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Reality',
        'https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Vless',
        'https://raw.githubusercontent.com/AzadNetCH/Clash/refs/heads/main/AzadNet_iOS.txt',
        'https://raw.githubusercontent.com/Proxydaemitelegram/Proxydaemi44/refs/heads/main/Proxydaemi44',
        'https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/refs/heads/master/collected-proxies/xray-json-full/actives_all.json',
        'https://raw.githubusercontent.com/Created-By/Telegram-Eag1e_YT/refs/heads/main/%40Eag1e_YT',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub6.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub7.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub8.txt',
        'https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub9.txt',
        'https://azadnet05.pages.dev/sub/4d794980-54c0-4fcb-8def-c2beaecadbad',
        'https://raw.githubusercontent.com/rango-cfs/NewCollector/refs/heads/main/v2ray_links.txt'
    ]

    print(f"\n🚀 === СТАРТ СБОРА VPN ({time.strftime('%H:%M:%S')}) ===\n")

    # 1. Загрузка HTTP
    total_sources = len(remote_sources)
    for idx, url in enumerate(remote_sources, 1):
        domain = urlparse(url).netloc or "other"
        sys.stdout.write(f"\r🌐 HTTP [{idx}/{total_sources}]: {domain[:30]}... ")
        sys.stdout.flush()
        try:
            r = requests.get(url.strip(), timeout=10)
            if r.status_code == 200:
                all_content += r.text + "\n"
        except: pass
    print("\n✅ HTTP источники загружены.")

    # 2. Загрузка Telegram
    all_content += fetch_telegram_configs()

    # 3. Дедупликация
    print("\n🧹 Очистка дубликатов...")
    raw_links = extract_links(all_content)
    unique_links = list(dict.fromkeys([l.strip() for l in raw_links]))
    total_links = len(unique_links)
    print(f"📊 Всего уникальных ссылок: {total_links}")

    # 4. Проверка
    print(f"\n🔍 Проверка в 30 потоков (Deep TLS Check)...")
    good_links = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_link_worker, lnk): lnk for lnk in unique_links}
        for i, future in enumerate(as_completed(futures), 1):
            res = future.result()
            if res: good_links.append(res)
            
            percent = (i / total_links) * 100
            sys.stdout.write(f"\r   [{i}/{total_links}] {percent:.1f}% | Рабочих: {len(good_links)} ")
            sys.stdout.flush()

    # 5. Сохранение и Git
    print(f"\n\n💾 Сохранение...")
    with open('config_all.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_links))
    with open('config_good_all.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(good_links))

    if os.path.exists('.git'):
        print("↗️ Отправка в GitHub...")
        os.system('git add .')
        os.system(f'git commit -m "Update nodes: {len(good_links)}"')
        os.system('git push')

    print(f"\n🏁 Готово за {int(time.time() - start_time)} сек. Рабочих: {len(good_links)}")

if __name__ == "__main__":
    main()