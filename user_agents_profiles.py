import random

# Chrome version hiện tại
CHROME_MAJOR = 148
CHROME_FULL = "148.0.7778.168"

# Windows versions
WINDOWS_VERSIONS = [
    ("Windows NT 10.0; Win64; x64", "Windows", False),
    ("Windows NT 10.0; WOW64", "Windows", False),
]

# macOS versions
MAC_VERSIONS = [
    ("Macintosh; Intel Mac OS X 10_15_7", "macOS", False),
    ("Macintosh; Intel Mac OS X 13_5", "macOS", False),
    ("Macintosh; Intel Mac OS X 14_2", "macOS", False),
]

# Linux
LINUX_VERSIONS = [
    ("X11; Linux x86_64", "Linux", False),
]

# Android devices (device_string, android_version, model_name)
ANDROID_DEVICES = [
    ("Linux; Android 14; SM-S918B", "14", "SM-S918B"),      # S23 Ultra
    ("Linux; Android 14; SM-S921B", "14", "SM-S921B"),      # S24
    ("Linux; Android 15; Pixel 9 Pro", "15", "Pixel 9 Pro"),
    ("Linux; Android 14; Pixel 8", "14", "Pixel 8"),
    ("Linux; Android 14; Redmi Note 13", "14", "Redmi Note 13"),
]

# iOS devices
IOS_DEVICES = [
    ("iPhone; CPU iPhone OS 17_5 like Mac OS X", "17.5"),
    ("iPhone; CPU iPhone OS 18_0 like Mac OS X", "18.0"),
]

def generate_chrome_version() -> str:
    """Generate realistic Chrome version."""
    build = random.randint(6700, 6999)
    patch = random.randint(0, 200)
    return f"{CHROME_MAJOR}.0.{build}.{patch}"

def generate_sec_ch_ua(chrome_version: str) -> str:
    """
    Generate sec-ch-ua header.
    Example: "Chromium";v="131", "Google Chrome";v="131", "Not/A)Brand";v="99"
    """
    major = chrome_version.split('.')[0]
    # Random "Not Brand" để tránh fingerprint giống hệt nhau
    not_brands = [
        f'"Not/A)Brand";v="99"',
        f'"Not_A Brand";v="8"',
        f'"Not:A-Brand";v="99"',
    ]
    return f'"Chromium";v="{major}", "Google Chrome";v="{major}", {random.choice(not_brands)}'

def generate_desktop_fingerprint() -> dict:
    """Generate complete desktop browser fingerprint."""
    
    # Random OS
    os_data = random.choice(WINDOWS_VERSIONS + MAC_VERSIONS + LINUX_VERSIONS)
    platform_string, platform_name, is_mobile = os_data
    
    # Chrome version
    chrome_ver = generate_chrome_version()
    
    # User-Agent
    user_agent = (
        f"Mozilla/5.0 ({platform_string}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_ver} Safari/537.36"
    )
    
    # Viewport theo OS
    if "Windows" in platform_string:
        viewport = random.choice([[1920, 1080], [1366, 768], [2560, 1440]])
    elif "Macintosh" in platform_string:
        viewport = random.choice([[1440, 900], [1920, 1080], [2560, 1600]])
    else:  # Linux
        viewport = [1920, 1080]
    
    return {
        # User-Agent
        "user_agent": user_agent,
        
        # Client Hints Headers (Chrome 89+)
        "sec_ch_ua": generate_sec_ch_ua(chrome_ver),
        "sec_ch_ua_mobile": "?0",  # Desktop = ?0
        "sec_ch_ua_platform": f'"{platform_name}"',
        
        # Navigator properties
        "platform": "Win32" if platform_name == "Windows" else ("MacIntel" if platform_name == "macOS" else "Linux x86_64"),
        "mobile": False,
        
        # Viewport
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "screen": {"width": viewport[0], "height": viewport[1]},
        
        # Language & Timezone
        "language": random.choice(["en-US", "en-GB", "vi-VN"]),
        "timezone": random.choice([
            "America/New_York",
            "Europe/London",
            "Asia/Ho_Chi_Minh"
        ]),
        
        # Hardware
        "hardware_concurrency": random.choice([4, 8, 12, 16]),
        "device_memory": random.choice([4, 8, 16, 32]),
        
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    }

def generate_mobile_fingerprint() -> dict:
    """Generate complete mobile browser fingerprint."""
    
    # Random device
    if random.random() < 0.8:  # 80% Android, 20% iOS
        # Android
        device_data = random.choice(ANDROID_DEVICES)
        device_string, android_ver, model = device_data
        
        chrome_ver = generate_chrome_version()
        
        user_agent = (
            f"Mozilla/5.0 ({device_string}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chrome_ver} Mobile Safari/537.36"
        )
        
        platform_name = "Android"
        viewport = random.choice([
            [393, 851],   # Pixel
            [412, 915],   # Samsung
            [360, 800],   # Standard
        ])
        
        return {
            "user_agent": user_agent,
            "sec_ch_ua": generate_sec_ch_ua(chrome_ver),
            "sec_ch_ua_mobile": "?1",  # Mobile = ?1
            "sec_ch_ua_platform": '"Android"',
            "sec_ch_ua_model": f'"{model}"',  # Android có thêm model
            
            "platform": "Linux armv8l",
            "mobile": True,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "screen": {"width": viewport[0], "height": viewport[1]},
            "language": random.choice(["en-US", "vi-VN"]),
            "timezone": "Asia/Ho_Chi_Minh",
            "hardware_concurrency": random.choice([4, 6, 8]),
            "device_memory": random.choice([4, 6, 8]),
            "webgl_vendor": "Qualcomm",
            "webgl_renderer": f"Adreno (TM) {random.choice(['640', '650', '660', '730', '740'])}",
        }
    else:
        # iOS
        device_data = random.choice(IOS_DEVICES)
        device_string, ios_ver = device_data
        
        user_agent = (
            f"Mozilla/5.0 ({device_string}) AppleWebKit/605.1.15 "
            f"(KHTML, like Gecko) Version/{ios_ver} Mobile/15E148 Safari/604.1"
        )
        
        viewport = random.choice([
            [390, 844],   # iPhone 13/14
            [393, 852],   # iPhone 15
        ])
        
        # iOS Safari KHÔNG có sec-ch-ua (chỉ Chrome mới có)
        return {
            "user_agent": user_agent,
            # iOS Safari không gửi Client Hints
            "sec_ch_ua": None,
            "sec_ch_ua_mobile": None,
            "sec_ch_ua_platform": None,
            
            "platform": "iPhone",
            "mobile": True,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "screen": {"width": viewport[0], "height": viewport[1]},
            "language": random.choice(["en-US", "vi-VN"]),
            "timezone": "Asia/Ho_Chi_Minh",
            "hardware_concurrency": random.choice([4, 6, 8]),
            "device_memory": random.choice([4, 6, 8]),
            "webgl_vendor": "Apple Inc.",
            "webgl_renderer": "Apple GPU",
        }

def get_request_headers(fingerprint: dict) -> dict[str, str]:
    """
    Convert fingerprint to HTTP request headers.
    Dùng cho requests/httpx.
    """
    headers = {
        "User-Agent": fingerprint["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": f"{fingerprint['language']},en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    # Add Client Hints nếu có (Chrome on Android/Desktop)
    if fingerprint.get("sec_ch_ua"):
        headers["sec-ch-ua"] = fingerprint["sec_ch_ua"]
        headers["sec-ch-ua-mobile"] = fingerprint["sec_ch_ua_mobile"]
        headers["sec-ch-ua-platform"] = fingerprint["sec_ch_ua_platform"]
        
        # Android có thêm model
        if fingerprint.get("sec_ch_ua_model"):
            headers["sec-ch-ua-model"] = fingerprint["sec_ch_ua_model"]
    
    return headers