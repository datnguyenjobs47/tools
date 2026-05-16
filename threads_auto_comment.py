"""CLI tool for commenting on Threads posts with Playwright.

The tool intentionally works only from a logged-in browser profile and only on
explicit post URLs supplied by the operator. It does not solve CAPTCHAs, bypass
rate limits, discover targets, or rotate identities.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from playwright_handler import PlaywrightHandler

LOGGER = logging.getLogger(__name__)
THREADS_HOME_URL = "https://www.threads.net/"


@dataclass(frozen=True)
class CommentResult:
    """Result for one Threads comment attempt."""

    post_url: str
    comment: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class ThreadsAutoCommentConfig:
    """Runtime configuration for :class:`ThreadsAutoCommenter`."""

    post_urls: list[str]
    comments: list[str]
    browser_id: int = 0
    browser_type: str = "chromium"
    headless: bool = False
    keep_profile: bool = True
    is_mobile: bool = False
    dry_run: bool = False
    min_delay: float = 20.0
    max_delay: float = 45.0
    max_comments: int = 10
    login_wait_seconds: int = 90
    cdp_timeout_seconds: float = 60.0
    debug_browser: bool = False
    browser_log_path: str | None = None
    linux_single_process: bool = False
    navigation_timeout_ms: int = 45_000
    action_timeout_ms: int = 15_000

    def validate(self) -> None:
        if not self.post_urls:
            raise ValueError("Cần ít nhất 1 Threads post URL.")
        if not self.comments:
            raise ValueError("Cần ít nhất 1 nội dung comment.")
        if self.max_comments < 1:
            raise ValueError("--max-comments phải >= 1.")
        if self.min_delay < 0 or self.max_delay < 0:
            raise ValueError("Delay không được âm.")
        if self.max_delay < self.min_delay:
            raise ValueError("--max-delay phải >= --min-delay.")
        if self.cdp_timeout_seconds <= 0:
            raise ValueError("--cdp-timeout phải > 0.")
        if self.browser_type not in {"chrome", "chromium", "firefox"}:
            raise ValueError("--browser-type phải là: chrome, chromium, hoặc firefox.")


class ThreadsAutoCommenter:
    """Automate comments on explicitly supplied Threads post URLs.

    Safety/operational boundaries:
    - Uses the existing browser profile; login must be performed by the owner.
    - Does not bypass CAPTCHA/challenges or Threads platform limits.
    - Does not scrape/search for targets; every target URL is user supplied.
    """

    def __init__(self, config: ThreadsAutoCommentConfig) -> None:
        config.validate()
        self.config = config

    async def run(self) -> list[CommentResult]:
        results: list[CommentResult] = []
        total = min(self.config.max_comments, len(self.config.post_urls))

        async with PlaywrightHandler(
            browser_type=self.config.browser_type,
            headless=self.config.headless,
            browser_id=self.config.browser_id,
            keep_profile=self.config.keep_profile,
            is_mobile=self.config.is_mobile,
            cdp_timeout_seconds=self.config.cdp_timeout_seconds,
            debug_browser=self.config.debug_browser,
            browser_log_path=self.config.browser_log_path,
            linux_single_process=self.config.linux_single_process,
        ) as handler:
            page = await handler.get_page()
            await self._ensure_logged_in(page)

            for index, post_url in enumerate(self.config.post_urls[:total], start=1):
                comment = self.config.comments[(index - 1) % len(self.config.comments)]
                result = await self.comment_on_post(page, post_url, comment)
                results.append(result)
                LOGGER.info("[%s/%s] %s - %s", index, total, result.status, post_url)

                if index < total:
                    delay = random.uniform(self.config.min_delay, self.config.max_delay)
                    LOGGER.info("Waiting %.1fs before next post", delay)
                    await page.wait_for_timeout(int(delay * 1000))

        return results

    async def _ensure_logged_in(self, page: Page) -> None:
        await page.goto(THREADS_HOME_URL, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
        await page.wait_for_timeout(2_000)

        if await self._looks_logged_in(page):
            LOGGER.info("Threads profile appears to be logged in")
            return

        if self.config.headless:
            raise RuntimeError(
                "Threads chưa đăng nhập. Chạy không headless một lần với --keep-profile để đăng nhập thủ công."
            )

        LOGGER.warning(
            "Threads chưa đăng nhập. Vui lòng đăng nhập trong cửa sổ Chrome; tool sẽ chờ %ss.",
            self.config.login_wait_seconds,
        )
        await page.wait_for_timeout(self.config.login_wait_seconds * 1000)

        if not await self._looks_logged_in(page):
            raise RuntimeError("Không xác nhận được trạng thái đăng nhập Threads sau thời gian chờ.")

    async def _looks_logged_in(self, page: Page) -> bool:
        login_indicators = [
            page.get_by_role("link", name=_name_regex("Log in|Đăng nhập")),
            page.get_by_role("button", name=_name_regex("Log in|Đăng nhập")),
        ]
        for locator in login_indicators:
            if await _is_visible(locator, timeout=1_000):
                return False

        composer_candidates = [
            page.get_by_role("link", name=_name_regex("Create|New thread|Tạo|Bài viết mới")),
            page.get_by_role("button", name=_name_regex("Create|New thread|Tạo|Bài viết mới")),
            page.locator("a[href*='/@']").first,
        ]
        for locator in composer_candidates:
            if await _is_visible(locator, timeout=1_000):
                return True
        return False

    async def comment_on_post(self, page: Page, post_url: str, comment: str) -> CommentResult:
        if self.config.dry_run:
            LOGGER.info("DRY RUN: would comment on %s: %s", post_url, comment)
            return CommentResult(post_url=post_url, comment=comment, status="dry-run")

        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=self.config.navigation_timeout_ms)
        except PlaywrightTimeoutError:
            LOGGER.warning("Navigation timeout for %s; continuing with loaded DOM", post_url)

        try:
            await self._open_reply_composer(page)
            editor = await self._find_reply_editor(page)
            await editor.fill(comment, timeout=self.config.action_timeout_ms)
            await self._submit_reply(page)
            await page.wait_for_timeout(2_500)
            return CommentResult(post_url=post_url, comment=comment, status="posted")
        except Exception as exc:  # noqa: BLE001 - return per-post error and continue batch
            LOGGER.exception("Failed to comment on %s", post_url)
            return CommentResult(post_url=post_url, comment=comment, status="failed", message=str(exc))

    async def _open_reply_composer(self, page: Page) -> None:
        reply_buttons = [
            page.get_by_role("button", name=_name_regex("Reply|Comment|Trả lời|Bình luận")),
            page.locator("[aria-label*='Reply'], [aria-label*='Comment'], [aria-label*='Trả lời'], [aria-label*='Bình luận']"),
        ]
        for locator in reply_buttons:
            target = locator.first
            if await _is_visible(target, timeout=3_000):
                await target.click(timeout=self.config.action_timeout_ms)
                await page.wait_for_timeout(1_000)
                return
        raise RuntimeError("Không tìm thấy nút Reply/Comment trên post Threads.")

    async def _find_reply_editor(self, page: Page) -> Locator:
        editors = [
            page.get_by_role("textbox", name=_name_regex("Reply|Comment|Trả lời|Bình luận")),
            page.locator("textarea").last,
            page.locator("[contenteditable='true']").last,
            page.get_by_role("textbox").last,
        ]
        for editor in editors:
            if await _is_visible(editor, timeout=5_000):
                return editor
        raise RuntimeError("Không tìm thấy ô nhập reply/comment.")

    async def _submit_reply(self, page: Page) -> None:
        submit_buttons = [
            page.get_by_role("button", name=_name_regex("Post|Reply|Send|Đăng|Trả lời|Gửi")),
            page.locator("[aria-label*='Post'], [aria-label*='Reply'], [aria-label*='Send'], [aria-label*='Đăng'], [aria-label*='Gửi']"),
        ]
        for locator in submit_buttons:
            target = locator.last
            if await _is_visible(target, timeout=5_000):
                await target.click(timeout=self.config.action_timeout_ms)
                return
        raise RuntimeError("Không tìm thấy nút gửi comment.")


def _name_regex(pattern: str) -> object:
    """Return a compiled regex without importing re at call sites."""

    import re

    return re.compile(pattern, re.IGNORECASE)


async def _is_visible(locator: Locator, timeout: int) -> bool:
    try:
        return await locator.is_visible(timeout=timeout)
    except Exception:
        return False


def _read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _collect_values(values: Iterable[str] | None, file_path: str | None) -> list[str]:
    collected = list(values or [])
    if file_path:
        collected.extend(_read_lines(Path(file_path)))
    return collected


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto comment trên Threads cho danh sách post URL đã cung cấp sẵn.",
    )
    parser.add_argument("--post-url", action="append", default=[], help="Threads post URL. Có thể truyền nhiều lần.")
    parser.add_argument("--post-url-file", help="File chứa Threads post URL, mỗi dòng một URL.")
    parser.add_argument("--comment", action="append", default=[], help="Nội dung comment. Có thể truyền nhiều lần.")
    parser.add_argument("--comments-file", help="File chứa nội dung comment, mỗi dòng một comment.")
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
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in kế hoạch, không gửi comment.")
    parser.add_argument("--min-delay", type=float, default=20.0, help="Delay tối thiểu giữa các comment (giây).")
    parser.add_argument("--max-delay", type=float, default=45.0, help="Delay tối đa giữa các comment (giây).")
    parser.add_argument("--max-comments", type=int, default=10, help="Giới hạn số comment trong một lần chạy.")
    parser.add_argument("--login-wait-seconds", type=int, default=90, help="Thời gian chờ đăng nhập thủ công.")
    parser.add_argument("--cdp-timeout", type=float, default=60.0, help="Số giây chờ Chrome mở CDP port.")
    parser.add_argument("--debug-browser", action="store_true", help="Ghi Chrome stdout/stderr và launch args để debug lỗi CDP.")
    parser.add_argument("--browser-log-path", help="Đường dẫn file log Chrome khi dùng --debug-browser.")
    parser.add_argument("--linux-single-process", action="store_true", help="Bật lại --single-process trên Linux nếu container bắt buộc.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


async def async_main(args: argparse.Namespace) -> int:
    post_urls = _collect_values(args.post_url, args.post_url_file)
    comments = _collect_values(args.comment, args.comments_file)
    config = ThreadsAutoCommentConfig(
        post_urls=post_urls,
        comments=comments,
        browser_id=args.browser_id,
        browser_type=args.browser_type,
        headless=args.headless,
        keep_profile=not args.no_keep_profile,
        is_mobile=args.mobile,
        dry_run=args.dry_run,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_comments=args.max_comments,
        login_wait_seconds=args.login_wait_seconds,
        cdp_timeout_seconds=args.cdp_timeout,
        debug_browser=args.debug_browser,
        browser_log_path=args.browser_log_path,
        linux_single_process=args.linux_single_process,
    )
    commenter = ThreadsAutoCommenter(config)
    results = await commenter.run()

    posted = sum(result.status == "posted" for result in results)
    failed = sum(result.status == "failed" for result in results)
    for result in results:
        suffix = f" - {result.message}" if result.message else ""
        print(f"{result.status.upper()}: {result.post_url}{suffix}")
    print(f"Summary: posted={posted}, failed={failed}, total={len(results)}")
    return 1 if failed else 0


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
