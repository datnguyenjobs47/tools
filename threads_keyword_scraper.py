"""Scrape public Threads search results for explicit keywords.

Step 1 in the Threads workflow: collect candidate posts by keyword and write a
local dataset for later review. The scraper uses a normal browser profile via
``PlaywrightHandler``. It does not solve CAPTCHAs, bypass login gates, or post
content back to Threads.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from playwright_handler import PlaywrightHandler

LOGGER = logging.getLogger(__name__)
THREADS_HOME_URL = "https://www.threads.net/"
DEFAULT_SEARCH_URL_TEMPLATE = "https://www.threads.net/search?q={query}"


@dataclass(frozen=True)
class ThreadsSearchResult:
    """One post-like result found on a Threads search page."""

    keyword: str
    post_url: str
    username: str | None
    text: str
    timestamp: str | None
    scraped_at: str


@dataclass(frozen=True)
class ThreadsKeywordScraperConfig:
    """Runtime configuration for :class:`ThreadsKeywordScraper`."""

    keywords: list[str]
    output_path: Path = Path("data/threads_keyword_results.jsonl")
    output_format: str = "jsonl"
    search_url_template: str = DEFAULT_SEARCH_URL_TEMPLATE
    max_posts_per_keyword: int = 50
    max_scrolls: int = 10
    scroll_pause_ms: int = 1500
    browser_id: int = 20
    browser_type: str = "chromium"
    headless: bool = False
    keep_profile: bool = True
    is_mobile: bool = False
    login_wait_seconds: int = 90
    navigation_timeout_ms: int = 45_000
    debug_browser: bool = False
    browser_log_path: str | None = None
    cdp_timeout_seconds: float = 60.0
    linux_single_process: bool = False

    def validate(self) -> None:
        if not self.keywords:
            raise ValueError("Cần ít nhất 1 keyword để scrape Threads.")
        if self.output_format not in {"jsonl", "csv"}:
            raise ValueError("--output-format phải là jsonl hoặc csv.")
        if "{query}" not in self.search_url_template:
            raise ValueError("--search-url-template phải chứa placeholder {query}.")
        if self.max_posts_per_keyword < 1:
            raise ValueError("--max-posts-per-keyword phải >= 1.")
        if self.max_scrolls < 0:
            raise ValueError("--max-scrolls phải >= 0.")
        if self.scroll_pause_ms < 0:
            raise ValueError("--scroll-pause-ms không được âm.")
        if self.browser_type not in {"chrome", "chromium", "firefox"}:
            raise ValueError("--browser-type phải là: chrome, chromium, hoặc firefox.")
        if self.cdp_timeout_seconds <= 0:
            raise ValueError("--cdp-timeout phải > 0.")


class ThreadsKeywordScraper:
    """Collect Threads posts from explicit keyword search pages."""

    def __init__(self, config: ThreadsKeywordScraperConfig) -> None:
        config.validate()
        self.config = config

    async def run(self) -> list[ThreadsSearchResult]:
        results: list[ThreadsSearchResult] = []
        seen_urls: set[str] = set()

        async with PlaywrightHandler(
            browser_type=self.config.browser_type,
            headless=self.config.headless,
            browser_id=self.config.browser_id,
            keep_profile=self.config.keep_profile,
            is_mobile=self.config.is_mobile,
            debug_browser=self.config.debug_browser,
            browser_log_path=self.config.browser_log_path,
            cdp_timeout_seconds=self.config.cdp_timeout_seconds,
            linux_single_process=self.config.linux_single_process,
        ) as handler:
            page = await handler.get_page()
            await self._open_threads_home(page)

            for keyword in self.config.keywords:
                keyword_results = await self.scrape_keyword(page, keyword, seen_urls)
                results.extend(keyword_results)
                LOGGER.info("Keyword %r -> %s new results", keyword, len(keyword_results))

        write_results(results, self.config.output_path, self.config.output_format)
        return results

    async def _open_threads_home(self, page: Page) -> None:
        """Open Threads once so the operator can log in if the UI requires it."""

        try:
            await page.goto(
                THREADS_HOME_URL,
                wait_until="domcontentloaded",
                timeout=self.config.navigation_timeout_ms,
            )
            await page.wait_for_timeout(1500)
        except PlaywrightTimeoutError:
            LOGGER.warning("Threads home timed out; continuing to keyword search pages")
            return

        if await _login_prompt_visible(page) and not self.config.headless:
            LOGGER.warning(
                "Threads có thể đang yêu cầu đăng nhập. Vui lòng đăng nhập trong cửa sổ browser; tool sẽ chờ %ss.",
                self.config.login_wait_seconds,
            )
            await page.wait_for_timeout(self.config.login_wait_seconds * 1000)

    async def scrape_keyword(
        self,
        page: Page,
        keyword: str,
        seen_urls: set[str] | None = None,
    ) -> list[ThreadsSearchResult]:
        seen_urls = seen_urls if seen_urls is not None else set()
        search_url = self.build_search_url(keyword)
        LOGGER.info("Scraping keyword %r: %s", keyword, search_url)

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
            await page.wait_for_timeout(self.config.scroll_pause_ms)
        except PlaywrightTimeoutError:
            LOGGER.warning("Search page timeout for keyword %r; continuing with current DOM", keyword)

        keyword_results: list[ThreadsSearchResult] = []
        stagnant_rounds = 0

        for scroll_index in range(self.config.max_scrolls + 1):
            extracted = await extract_threads_results(page, keyword)
            before_count = len(keyword_results)

            for result in extracted:
                if result.post_url in seen_urls:
                    continue
                seen_urls.add(result.post_url)
                keyword_results.append(result)
                if len(keyword_results) >= self.config.max_posts_per_keyword:
                    return keyword_results

            if len(keyword_results) == before_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            if scroll_index >= self.config.max_scrolls or stagnant_rounds >= 3:
                break

            await page.mouse.wheel(0, 2400)
            await page.wait_for_timeout(self.config.scroll_pause_ms)

        return keyword_results

    def build_search_url(self, keyword: str) -> str:
        return self.config.search_url_template.format(query=quote_plus(keyword))


async def extract_threads_results(page: Page, keyword: str) -> list[ThreadsSearchResult]:
    """Extract post-like links and nearby text from the current Threads DOM."""

    scraped_at = datetime.now(UTC).isoformat()
    raw_items = await page.evaluate(
        r"""
        () => {
            const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
            const absolute = (href) => {
                try { return new URL(href, window.location.href).toString(); }
                catch (e) { return href || ''; }
            };
            const postUrl = (href) => {
                const url = absolute(href);
                if (!url.includes('threads.net/')) return '';
                if (url.includes('/post/') || url.includes('/t/')) return url.split('?')[0];
                return '';
            };
            const containerFor = (node) => {
                let current = node;
                for (let depth = 0; current && depth < 8; depth += 1) {
                    const role = current.getAttribute && current.getAttribute('role');
                    const text = clean(current.innerText);
                    if (role === 'article' || text.length >= 40) return current;
                    current = current.parentElement;
                }
                return node.parentElement || node;
            };

            const seen = new Set();
            const results = [];
            for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
                const url = postUrl(anchor.href);
                if (!url || seen.has(url)) continue;
                seen.add(url);

                const container = containerFor(anchor);
                const text = clean(container.innerText);
                const timeNode = container.querySelector ? container.querySelector('time') : null;
                const timestamp = timeNode ? (timeNode.getAttribute('datetime') || clean(timeNode.textContent)) : null;
                const usernameMatch = url.match(/threads\.net\/(@[^\/]+)\//);
                const textUsernameMatch = text.match(/@([A-Za-z0-9._]+)/);

                results.push({
                    post_url: url,
                    username: usernameMatch ? usernameMatch[1] : (textUsernameMatch ? `@${textUsernameMatch[1]}` : null),
                    text,
                    timestamp,
                });
            }
            return results;
        }
        """
    )

    results: list[ThreadsSearchResult] = []
    for item in raw_items:
        post_url = str(item.get("post_url") or "").strip()
        if not post_url:
            continue
        results.append(
            ThreadsSearchResult(
                keyword=keyword,
                post_url=post_url,
                username=item.get("username"),
                text=str(item.get("text") or ""),
                timestamp=item.get("timestamp"),
                scraped_at=scraped_at,
            )
        )
    return results


async def _login_prompt_visible(page: Page) -> bool:
    for locator in [
        page.get_by_role("link", name=_name_regex("Log in|Đăng nhập")),
        page.get_by_role("button", name=_name_regex("Log in|Đăng nhập")),
    ]:
        try:
            if await locator.first.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def _name_regex(pattern: str) -> object:
    import re

    return re.compile(pattern, re.IGNORECASE)


def _read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _collect_values(values: Iterable[str] | None, file_path: str | None) -> list[str]:
    collected = [value.strip() for value in values or [] if value.strip()]
    if file_path:
        collected.extend(_read_lines(Path(file_path)))
    return collected


def write_results(results: list[ThreadsSearchResult], output_path: Path, output_format: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(result) for result in results]

    if output_format == "jsonl":
        with output_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["keyword", "post_url", "username", "text", "timestamp", "scraped_at"],
        )
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bước 1: scrape dữ liệu Threads theo keyword và xuất JSONL/CSV.",
    )
    parser.add_argument("--keyword", action="append", default=[], help="Keyword cần tìm. Có thể truyền nhiều lần.")
    parser.add_argument("--keywords-file", help="File chứa keyword, mỗi dòng một keyword.")
    parser.add_argument("--output", default="data/threads_keyword_results.jsonl", help="Đường dẫn output JSONL/CSV.")
    parser.add_argument("--output-format", default="jsonl", choices=["jsonl", "csv"], help="Định dạng output.")
    parser.add_argument(
        "--search-url-template",
        default=DEFAULT_SEARCH_URL_TEMPLATE,
        help="Template URL search Threads, phải chứa {query}.",
    )
    parser.add_argument("--max-posts-per-keyword", type=int, default=50, help="Số post tối đa cho mỗi keyword.")
    parser.add_argument("--max-scrolls", type=int, default=10, help="Số lần scroll tối đa cho mỗi keyword.")
    parser.add_argument("--scroll-pause-ms", type=int, default=1500, help="Thời gian chờ sau mỗi scroll.")
    parser.add_argument("--browser-id", type=int, default=20, help="ID profile browser trong __temp__/profiles.")
    parser.add_argument(
        "--browser-type",
        default="chromium",
        choices=["chromium", "chrome", "firefox"],
        help="chromium dùng Playwright và không cần CDP port ngoài; chrome dùng Google Chrome qua CDP.",
    )
    parser.add_argument("--headless", action="store_true", help="Chạy headless. Chỉ dùng khi profile đã đăng nhập.")
    parser.add_argument("--no-keep-profile", action="store_true", help="Không giữ profile sau khi chạy.")
    parser.add_argument("--mobile", action="store_true", help="Dùng mobile fingerprint từ PlaywrightHandler.")
    parser.add_argument("--login-wait-seconds", type=int, default=90, help="Thời gian chờ đăng nhập thủ công.")
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000, help="Timeout điều hướng trang.")
    parser.add_argument("--cdp-timeout", type=float, default=60.0, help="Số giây chờ Chrome mở CDP port khi dùng --browser-type chrome.")
    parser.add_argument("--debug-browser", action="store_true", help="Ghi log launch args / Chrome stdout-stderr khi có.")
    parser.add_argument("--browser-log-path", help="Đường dẫn file log Chrome khi dùng --debug-browser --browser-type chrome.")
    parser.add_argument("--linux-single-process", action="store_true", help="Bật lại --single-process trên Linux nếu container bắt buộc.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


async def async_main(args: argparse.Namespace) -> int:
    keywords = _collect_values(args.keyword, args.keywords_file)
    config = ThreadsKeywordScraperConfig(
        keywords=keywords,
        output_path=Path(args.output),
        output_format=args.output_format,
        search_url_template=args.search_url_template,
        max_posts_per_keyword=args.max_posts_per_keyword,
        max_scrolls=args.max_scrolls,
        scroll_pause_ms=args.scroll_pause_ms,
        browser_id=args.browser_id,
        browser_type=args.browser_type,
        headless=args.headless,
        keep_profile=not args.no_keep_profile,
        is_mobile=args.mobile,
        login_wait_seconds=args.login_wait_seconds,
        navigation_timeout_ms=args.navigation_timeout_ms,
        debug_browser=args.debug_browser,
        browser_log_path=args.browser_log_path,
        cdp_timeout_seconds=args.cdp_timeout,
        linux_single_process=args.linux_single_process,
    )
    scraper = ThreadsKeywordScraper(config)
    results = await scraper.run()
    print(f"Scraped {len(results)} results -> {config.output_path}")
    return 0


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
