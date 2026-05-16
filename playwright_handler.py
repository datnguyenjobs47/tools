import logging
import asyncio
import json
import os
import sys
import shutil
import subprocess
from typing import Any
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright, Page, Request, Response
from user_agents_profiles import generate_desktop_fingerprint, generate_mobile_fingerprint

logger = logging.getLogger(__name__)


def get_browser_executable(browser_name: str = "chrome") -> str:
    browser_name = browser_name.lower()

    # Windows: tìm qua registry
    if sys.platform == "win32":
        import winreg

        registry_keys = {
            "chrome": [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
            ],
            "edge": [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
            ],
            "firefox": [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
            ],
        }

        if browser_name in registry_keys:
            for key_path in registry_keys[browser_name]:
                for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        with winreg.OpenKey(root, key_path) as key:
                            path, _ = winreg.QueryValueEx(key, "")
                            if path and Path(path).exists():
                                return path
                    except FileNotFoundError:
                        pass

    # Linux: tìm qua common paths
    linux_paths = {
        "chrome": [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ],
        "edge": [
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
        ],
        "firefox": [
            "/usr/bin/firefox",
            "/snap/bin/firefox",
        ],
    }

    if sys.platform.startswith("linux") and browser_name in linux_paths:
        for path in linux_paths[browser_name]:
            if Path(path).exists():
                return path

    # Fallback: tìm trong PATH
    exe_names = {
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome.exe"],
        "edge":    ["microsoft-edge", "microsoft-edge-stable", "msedge.exe"],
        "firefox": ["firefox", "firefox.exe"],
    }

    for name in exe_names.get(browser_name, [browser_name]):
        path = shutil.which(name)
        if path:
            return path

    raise FileNotFoundError(
        f"Could not find '{browser_name}' executable. "
        f"Platform: {sys.platform}"
    )


# ---------------------------------------------------------------------------
# Platform-aware Chrome args builder
# ---------------------------------------------------------------------------

def build_chrome_args(
    chrome_path: str,
    port: int,
    user_data_dir: str,
    proxy_args: list[str],
    ua_agents: list[str],
    headless: bool,
) -> list[str]:
    """
    Build Chrome subprocess args theo platform:
    - Windows : dùng --exclude-switches thay vì blink flags (tránh warning)
    - Linux   : cần --no-sandbox, --disable-dev-shm-usage, v.v.
    """
    is_linux = sys.platform.startswith("linux")

    # Base args (cross-platform)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", 

    ]

    if is_linux:
        args += [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--single-process",
            "--disable-blink-features=AutomationControlled",
        ]
    else:
        # Windows: --disable-blink-features gây warning, dùng exclude-switches thay thế
        args += [
            "--exclude-switches=enable-automation",
            "--disable-infobars",
        ]

    if headless:
        args.append("--headless=new")

    return args + proxy_args + ua_agents


# ---------------------------------------------------------------------------
# NetworkMonitor
# ---------------------------------------------------------------------------

class NetworkMonitor:
    def __init__(self) -> None:
        self.requests:        list[dict] = []
        self.responses:       list[dict] = []
        self.failed_requests: list[dict] = []

    def clear(self) -> None:
        self.requests.clear()
        self.responses.clear()
        self.failed_requests.clear()

    async def on_request(self, request: Request) -> None:
        self.requests.append({
            "url":           request.url,
            "method":        request.method,
            "headers":       request.headers,
            "post_data":     request.post_data,
            "resource_type": request.resource_type,
        })
        logger.debug(f"Request: {request.method} {request.url}")

    async def on_response(self, response: Response) -> None:
        try:
            content_type = response.headers.get("content-type", "")
            body = None
            if any(t in content_type.lower() for t in ["json", "text", "xml", "html"]):
                try:
                    body = await response.text()
                except Exception:
                    body = None
            self.responses.append({
                "url":     response.url,
                "status":  response.status,
                "headers": response.headers,
                "body":    body,
                "ok":      response.ok,
            })
        except Exception as e:
            logger.error(f"Error processing response: {e}")

    async def on_request_failed(self, request: Request) -> None:
        self.failed_requests.append({
            "url":           request.url,
            "method":        request.method,
            "failure":       request.failure,
            "resource_type": request.resource_type,
        })
        logger.warning(f"Request failed: {request.url} - {request.failure}")

    def get_responses_by_url(self, url_pattern: str) -> list[dict]:
        return [r for r in self.responses if url_pattern in r["url"]]

    def get_json_responses(self) -> list[dict]:
        results = []
        for resp in self.responses:
            if resp["body"] and "application/json" in resp["headers"].get("content-type", ""):
                try:
                    resp["json"] = json.loads(resp["body"])
                    results.append(resp)
                except Exception:
                    pass
        return results

    def get_api_calls(self, api_pattern: str = "/api/") -> list[dict]:
        return [r for r in self.responses if api_pattern in r["url"]]


# ---------------------------------------------------------------------------
# PlaywrightHandler
# ---------------------------------------------------------------------------

class PlaywrightHandler:
    """
    Chrome CDP handler với hỗ trợ:
    - Real Chrome profile qua debugging port
    - Mobile emulation qua CDP Emulation API (CDP session cached theo page)
    - Platform-aware Chrome args (Windows / Linux / Docker)
    - Profile persistence tuỳ chọn (keep_profile)
    - Proxy middleware (LocalProxyMiddleware)
    - Network monitoring
    """

    def __init__(
        self,
        browser_type:    str = "chrome",
        headless:        bool = True,
        proxy:           dict[str, str] | None = None,
        browser_id:      int = 0,
        monitor_network: bool = False,
        cookies:         list[dict] | None = None,
        is_mobile:          bool = False,
        keep_profile:    bool = False,
    ) -> None:
        self.browser_type    = browser_type.lower()
        self.headless        = headless
        self.proxy           = proxy
        self.browser_id      = browser_id
        self.monitor_network = monitor_network
        self.cookies         = cookies or []
        self.is_mobile       = is_mobile
        self.keep_profile    = keep_profile
        self.middleware_port = 8800 + browser_id
        self.middleware_task = None
        self.fingerprint     = generate_mobile_fingerprint() if is_mobile else generate_desktop_fingerprint()
        
        self.chrome_prefs = {
            "webrtc.ip_handling_policy": "disable_non_proxied_udp",
            "webrtc.multiple_routes_enabled": False,
            "webrtc.nonproxied_udp_enabled": False
        }

        self.playwright     = None
        self.browser        = None
        self.context        = None
        self.chrome_process = None
        self._is_active     = False

        self._cdp_sessions: dict[Page, Any] = {}

        self.network_monitor = NetworkMonitor() if monitor_network else None

    # ------------------------------------------------------------------
    # Mobile config helpers
    # ------------------------------------------------------------------


    def _build_fingerprint_subprocess_args(self) -> list[str]:
        """UA + window size inject vào Chrome subprocess."""
        fp = self.fingerprint
        return [
            f'--user-agent={fp["user_agent"]}',
            f'--window-size={fp["viewport"]["width"]},{fp["viewport"]["height"]}',
            f'--accept-lang={fp["language"]}',
        ]

    async def _get_cdp_session(self, page: Page):
        """
        Lấy CDP session cho page từ cache.
        Nếu chưa có thì tạo mới và cache lại.
        Tự xóa khỏi cache khi page đóng.
        """
        if page not in self._cdp_sessions:
            self._cdp_sessions[page] = await self.context.new_cdp_session(page)
            page.on("close", lambda p=page: self._cdp_sessions.pop(p, None))
        return self._cdp_sessions[page]

    async def _apply_fingerprint_emulation(self, page: Page) -> None:
        """
        Apply fingerprint emulation qua CDP Emulation API.
        Dùng cached CDP session — chỉ gọi khi tạo page mới.
        """
        if getattr(page, "_emulation_applied", False):
            return

        fp = self.fingerprint
        w, h  = fp["viewport"]["width"], fp["viewport"]["height"]
        scale = 3 if fp["mobile"] else 1

        try:
            cdp = await self._get_cdp_session(page)

            # 1. Viewport + scale + mobile flag
            await cdp.send("Emulation.setDeviceMetricsOverride", {
                "width":             w,
                "height":            h,
                "deviceScaleFactor": scale,
                "mobile":            fp["mobile"],
                "screenWidth":       fp["screen"]["width"],
                "screenHeight":      fp["screen"]["height"],
            })

            # 2. Touch support
            if fp["mobile"]:
                await cdp.send("Emulation.setTouchEmulationEnabled", {
                    "enabled":        True,
                    "maxTouchPoints": 5,
                })

            # 3. UA override
            await cdp.send("Network.setUserAgentOverride", {
                "userAgent": fp["user_agent"],
                "platform":  fp["platform"],
                "acceptLanguage": fp["language"],
            })

            # 4. Timezone
            await cdp.send("Emulation.setTimezoneOverride", {
                "timezoneId": fp["timezone"]
            })

            page._emulation_applied = True # type: ignore
            logger.info(
                f"Fingerprint emulation applied: {'Mobile' if fp['mobile'] else 'Desktop'} ({w}x{h} @{scale}x)"
            )
        except Exception as e:
            logger.error(f"Failed to apply fingerprint emulation: {e}")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "PlaywrightHandler":
        try:
            p = async_playwright()
            self.playwright = await p.start()

            port          = 9222 + self.browser_id
            user_data_dir = os.path.abspath(
                f"./__temp__/profiles/profile-{self.browser_id}"
            )

            # Xóa profile cũ nếu keep_profile=False
            if not self.keep_profile and os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir)
                except Exception:
                    pass
            os.makedirs(user_data_dir, exist_ok=True)

            # Apply Chrome preferences
            if self.browser_type != "firefox" and self.chrome_prefs:
                default_dir = os.path.join(user_data_dir, "Default")
                os.makedirs(default_dir, exist_ok=True)
                prefs_file = os.path.join(default_dir, "Preferences")
                
                current_prefs = {}
                if os.path.exists(prefs_file):
                    try:
                        with open(prefs_file, "r", encoding="utf-8") as f:
                            current_prefs = json.load(f)
                    except Exception:
                        pass
                
                for k, v in self.chrome_prefs.items():
                    parts = k.split(".")
                    d = current_prefs
                    for p in parts[:-1]:
                        d = d.setdefault(p, {})
                    d[parts[-1]] = v
                    
                with open(prefs_file, "w", encoding="utf-8") as f:
                    json.dump(current_prefs, f)

            # Proxy middleware
            proxy_args = []
            if self.proxy:
                try:
                    from proxy_middleware import LocalProxyMiddleware
                    server    = self.proxy.get("server", "")
                    host_port = server.split("://")[1] if "://" in server else server
                    u_host, u_port = host_port.split(":")
                    middleware = LocalProxyMiddleware(
                        local_port=self.middleware_port,
                        upstream_host=u_host,
                        upstream_port=int(u_port),
                        username=self.proxy.get("username"), # type: ignore
                        password=self.proxy.get("password"), # type: ignore
                    )
                    self.middleware_task = asyncio.create_task(middleware.start())
                    proxy_args = [f"--proxy-server=http://127.0.0.1:{self.middleware_port}"]
                    logger.info(f"Proxy middleware started on port {self.middleware_port}")
                except ImportError:
                    logger.warning("proxy_middleware not found, using direct proxy flag")
                    proxy_args = [f'--proxy-server={self.proxy.get("server", "")}']

            if self.browser_type == "firefox":
                proxy_config = (
                    {"server": f"http://127.0.0.1:{self.middleware_port}"}
                    if self.proxy else None
                )
                self.context = await self.playwright.firefox.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=self.headless,
                    proxy=proxy_config, # type: ignore
                )
                self.browser = self.context.browser

            else:
                chrome_path = get_browser_executable("chrome")

                args = build_chrome_args(
                    chrome_path=chrome_path,
                    port=port,
                    user_data_dir=user_data_dir,
                    proxy_args=proxy_args,
                    ua_agents=self._build_fingerprint_subprocess_args(),
                    headless=self.headless,
                )

                self.chrome_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                await self._wait_for_cdp_port(port)

                self.browser = await self.playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )

                self.context = (
                    self.browser.contexts[0]
                    if self.browser.contexts
                    else await self.browser.new_context()
                )

            # Anti-fingerprint init script
            fp = self.fingerprint
            scale = 3 if fp["mobile"] else 1
            w, h = fp["viewport"]["width"], fp["viewport"]["height"]
            
            init_script = f"""
            (() => {{
                const defineGetter = (target, prop, value) => {{
                    try {{
                        const descriptor = Object.getOwnPropertyDescriptor(target, prop);
                        if (descriptor && descriptor.configurable === false) return;

                        Object.defineProperty(target, prop, {{
                            get: () => value,
                            configurable: true
                        }});
                    }} catch (e) {{}}
                }};

                // Hardware
                defineGetter(Navigator.prototype, 'hardwareConcurrency', {fp['hardware_concurrency']});
                defineGetter(Navigator.prototype, 'deviceMemory', {fp['device_memory']});
                defineGetter(Navigator.prototype, 'platform', '{fp['platform']}');

                // Screen
                defineGetter(window, 'devicePixelRatio', {scale});
                defineGetter(Screen.prototype, 'width', {w});
                defineGetter(Screen.prototype, 'height', {h});
                defineGetter(Screen.prototype, 'availWidth', {w});
                defineGetter(Screen.prototype, 'availHeight', {h});

                // Touch
                if ({str(fp['mobile']).lower()}) {{
                    defineGetter(Navigator.prototype, 'maxTouchPoints', 5);

                    try {{
                        if (!('ontouchstart' in window)) {{
                            Object.defineProperty(window, 'ontouchstart', {{
                                value: null,
                                configurable: true
                            }});
                        }}
                    }} catch (e) {{}}
                }}

                // WebGL
                try {{
                    const patchWebGL = (ContextClass) => {{
                        if (!ContextClass || !ContextClass.prototype || !ContextClass.prototype.getParameter) return;

                        const originalGetParameter = ContextClass.prototype.getParameter;

                        ContextClass.prototype.getParameter = function(parameter) {{
                            if (parameter === 37445) return '{fp.get("webgl_vendor", "Qualcomm")}';
                            if (parameter === 37446) return '{fp.get("webgl_renderer", "Adreno (TM) 740")}';
                            return originalGetParameter.apply(this, arguments);
                        }};
                    }};

                    patchWebGL(window.WebGLRenderingContext);
                    patchWebGL(window.WebGL2RenderingContext);
                }} catch (e) {{}}

                // Media Devices
                try {{
                    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
                        const originalEnumerateDevices =
                            navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);

                        navigator.mediaDevices.enumerateDevices = async function() {{
                            try {{
                                return await originalEnumerateDevices();
                            }} catch (e) {{
                                return [];
                            }}
                        }};
                    }}
                }} catch (e) {{}}
            }})();
            """
            await self.context.add_init_script(init_script)

            if self.cookies:
                await self.context.add_cookies(self.cookies)

            self._is_active = True
            logger.info(
                f"Browser {self.browser_id} started "
                f"(platform={sys.platform}, mobile={self.fingerprint['mobile']}, "
                f"keep_profile={self.keep_profile})"
            )
            return self

        except Exception as e:
            logger.error(f"Browser {self.browser_id} failed to start: {e}")
            await self._cleanup()
            raise

    async def __aexit__(self, exc_type, exc, tb):
        self._is_active = False
        await self._cleanup()

    async def _cleanup(self):
        self._cdp_sessions.clear()

        for coro_fn, label in [
            (lambda: self.context.close() if self.browser_type == "firefox" and self.context else None, "context"),
            (lambda: self.browser.close()  if self.browser    else None, "browser"),
            (lambda: self.playwright.stop() if self.playwright else None, "playwright"),
        ]:
            try:
                result = coro_fn()
                if result:
                    await result
            except Exception as e:
                logger.error(f"Error closing {label}: {e}")

        if self.middleware_task:
            self.middleware_task.cancel()

        if self.chrome_process:
            try:
                self.chrome_process.terminate()
                self.chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.chrome_process.kill()
            except Exception as e:
                logger.error(f"Error killing chrome: {e}")

        logger.info(f"Browser {self.browser_id} closed")

    # ------------------------------------------------------------------
    # CDP port wait
    # ------------------------------------------------------------------

    async def _wait_for_cdp_port(self, port: int, retries: int = 30) -> None:
        for _ in range(retries):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=1
                )
                return
            except Exception:
                await asyncio.sleep(0.5)
        raise RuntimeError(
            f"Timeout: Chrome did not open CDP port {port} after {retries * 0.5}s"
        )

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    async def get_page(self, force_new: bool = False) -> Page:
        """
        Lấy page cuối cùng hoặc tạo page mới.
        Mobile emulation và network monitoring chỉ apply 1 lần khi tạo page mới.
        """
        if not self.context:
            raise RuntimeError("Context not initialized")

        pages  = self.context.pages
        is_new = not pages or force_new

        if is_new:
            page = await self.context.new_page()
            logger.debug("Created new page")
        else:
            # Reuse page cuối cùng
            page = pages[-1]
            logger.debug(f"Reusing page (index={len(pages) - 1})")

        # Apply emulation (sẽ bị skip nếu đã apply)
        await self._apply_fingerprint_emulation(page)

        # Bind network monitoring 1 lần khi tạo page mới
        if is_new and self.monitor_network and self.network_monitor:
            page.on("request",       self.network_monitor.on_request)
            page.on("response",      self.network_monitor.on_response)
            page.on("requestfailed", self.network_monitor.on_request_failed)

        return page

    # ------------------------------------------------------------------
    # Proxy swap (runtime, không cần restart browser)
    # ------------------------------------------------------------------
    # async def change_proxy(self, new_proxy: dict) -> bool:
    #     """
    #     Đổi upstream proxy runtime bằng cách restart LocalProxyMiddleware.
    #     Chrome vẫn trỏ vào 127.0.0.1:self.middleware_port.
    #     """
    #     if not self.context:
    #         logger.error("Context not initialized — không thể change proxy")
    #         return False

    #     self.proxy = new_proxy

    #     # Tắt middleware cũ
    #     if self.middleware_task:
    #         self.middleware_task.cancel()
    #         try:
    #             await self.middleware_task
    #         except asyncio.CancelledError:
    #             pass
    #         except Exception as e:
    #             logger.warning(f"Old proxy middleware stopped with error: {e}")

    #         self.middleware_task = None
    #         logger.info("Killed old proxy middleware")

    #         # Cho port có thời gian release
    #         await asyncio.sleep(0.5)

    #     # Khởi động middleware mới
    #     try:
    #         from proxy_middleware import LocalProxyMiddleware

    #         server = new_proxy.get("server", "")
    #         if not server:
    #             logger.error("New proxy missing 'server'")
    #             return False

    #         host_port = server.split("://")[1] if "://" in server else server
    #         u_host, u_port = host_port.split(":")

    #         middleware = LocalProxyMiddleware(
    #             local_port=self.middleware_port,
    #             upstream_host=u_host,
    #             upstream_port=int(u_port),
    #             username=new_proxy.get("username"),
    #             password=new_proxy.get("password"),
    #         )

    #         self.middleware_task = asyncio.create_task(middleware.start())

    #         logger.info(f"Proxy changed to {server}")
    #         return True

    #     except Exception as e:
    #         logger.error(f"Error changing proxy: {e}")
    #         return False

    # ------------------------------------------------------------------
    # IP check
    # ------------------------------------------------------------------

    async def check_ip(self) -> str | None:
        if not self.context:
            return None
        page = await self.context.new_page()
        try:
            await page.goto("https://api.ipify.org?format=json", timeout=10000)
            text = await page.locator("body").inner_text()
            ip   = json.loads(text).get("ip")
            logger.info(f"Current IP: {ip}")
            return ip
        except Exception as e:
            logger.error(f"Failed to check IP: {e}")
            return None
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    def get_network_stats(self) -> dict:
        if not self.network_monitor:
            return {}
        return {
            "total_requests":      len(self.network_monitor.requests),
            "total_responses":     len(self.network_monitor.responses),
            "failed_requests":     len(self.network_monitor.failed_requests),
            "successful_requests": len([r for r in self.network_monitor.responses if r["ok"]]),
            "error_responses":     len([r for r in self.network_monitor.responses if not r["ok"]]),
        }

    def clear_network_data(self) -> None:
        if self.network_monitor:
            self.network_monitor.clear()
            logger.info("Network data cleared")

    async def wait_for_response(
        self, url_pattern: str, timeout: int = 30000
    ) -> Response | None:
        if not self.context:
            raise RuntimeError("Context not initialized")
        try:
            async with self.context.expect_response(
                lambda r: url_pattern in r.url, timeout=timeout
            ) as response_info:
                return await response_info.value
        except Exception as e:
            logger.error(f"Failed to wait for response {url_pattern}: {e}")
            return None

    # ------------------------------------------------------------------
    # Static cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def cleanup_temp() -> None:
        """Xóa toàn bộ temp profiles. Gọi 1 lần khi shutdown toàn bộ process."""
        temp_dir = os.path.abspath("./__temp__")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info("Temp profiles cleared")


# ---------------------------------------------------------------------------
# Usage example
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(level=logging.INFO)

    async with PlaywrightHandler(
        browser_type="chrome",
        headless=False,
        is_mobile=True,
        proxy=None,
        browser_id=0,
        monitor_network=True,
        keep_profile=True,
    ) as handler:

        ip = await handler.check_ip()
        print(f"Current IP: {ip}")

        # Lần đầu: tạo page mới → apply mobile emulation 1 lần
        page = await handler.get_page()

        ua    = await page.evaluate("navigator.userAgent")
        vp    = await page.evaluate("({ w: window.innerWidth, h: window.innerHeight })")
        touch = await page.evaluate("'ontouchstart' in window")
        print(f"UA      : {ua}")
        print(f"Viewport: {vp}")
        print(f"Touch   : {touch}")

        await page.goto("https://m.11st.co.kr")
        await page.wait_for_timeout(2000)

        # Lần sau: reuse page cuối — không tạo mới, không apply lại emulation
        page2 = await handler.get_page()
        assert page is page2

        # Đổi device runtime → force_new=True để tạo page mới với emulation mới
        handler.fingerprint = generate_mobile_fingerprint()
        page3 = await handler.get_page(force_new=True)
        ua3   = await page3.evaluate("navigator.userAgent")
        print(f"New UA  : {ua3}")

        print(f"Network : {handler.get_network_stats()}")


if __name__ == "__main__":
    asyncio.run(main())