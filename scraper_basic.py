import os
import sys
# src_dir = os.path.abspath(os.path.join(__file__, "../../../../"))
# project_dir = os.path.dirname(src_dir)
# sys.path.append(project_dir)
# os.chdir(project_dir)

import aiofiles
import asyncio
import random
import ast
import argparse
import time
import json
from datetime import datetime
from loguru import logger
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, expect
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.asyncio import tqdm

# from src.utils.config import *
from utils.system_helper import *
from utils.proxy_helper import *
from utils.preprocess import *
from utils.helper import *
from playwright_handler import PlaywrightHandler

# ================= PARSE ARGS =================
parser = argparse.ArgumentParser()
parser.add_argument("--platform", default="auction")
parser.add_argument("--config-id", required=True)
parser.add_argument("--scrape-date", default=datetime.now().strftime("%Y-%m-%d"))
parser.add_argument("--scrape-order", required=True)
args = parser.parse_args()

# ================= GLOBAL CONFIG =================
PLATFORM = args.platform
CONFIG_ID = args.config_id
SCRAPE_ORDER = args.scrape_order
SCRAPE_DATE = args.scrape_date

# ================= PATH SETUP =================
base = f"{PLATFORM}/{CONFIG_ID}/basic"
detail_config = f"./configs/{base}/{SCRAPE_DATE}/{SCRAPE_DATE}_{PLATFORM}_search-keyword.txt"
raw_json_basic_data_dir = f"./data/{base}/{SCRAPE_DATE}/{SCRAPE_ORDER}/raw/json/"
log_dir = f"./logs/{base}/{SCRAPE_DATE}/{SCRAPE_ORDER}"

os.makedirs(raw_json_basic_data_dir, exist_ok=True)
os.makedirs(log_dir, exist_ok=True)

# ================= PROXY SETUP =================
proxy_auths = r"D:\repository\browser_template\configs\proxy.json"
data = read_file(proxy_auths, "json")
print(data)
auction_proxies = [proxy for proxy in data if proxy.get("scraper_name") == PLATFORM]

# ================= CONSTANTS =================
max_page = 50

platform_config = load_scraper_basic_config(PLATFORM)
price_ranges = get_price_ranges(platform_config)

base_url = r"https://www.auction.co.kr/n/search?keyword=%ec%ba%a1%ec%8a%90+%ec%bb%a4%ed%94%bc&f=c:38000000"
search_path = "/n/search"


def chunk_list(data, n):
    return [data[i::n] for i in range(n)]


def filter_unscraped(total_price_range: list[tuple], done_log_path: str):
    done_price_range = set()
    if os.path.exists(done_log_path):
        lines = read_file(done_log_path, "txt").splitlines()
        for line in lines:
            done_price_range.add(ast.literal_eval(line))

    unscraped = [price_range for price_range in total_price_range if price_range not in done_price_range]
    return unscraped


def build_search_url(from_price, to_price, page):
    price_filter = f"p:{from_price}^{to_price}"
    return (
        f"{search_path}"
        f"?keyword={platform_config['keyword']}"
        f"&f={platform_config['category']},{price_filter}"
        f"&s={platform_config['sort']}"
        f"&p={page}"
    )


def extract_data(html) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []

    try:
        data = json.loads(script.string)

        modules = (
            data["props"]["pageProps"]["initialStates"]
            ["curatorData"]["regionsData"]["content"]
            .get("modules", [])
        )

        items = []
        for module in modules:
            if module.get("designGroup") == 17:
                rows = module.get("rows")
                if isinstance(rows, list):
                    items.extend(rows)
        
        return items
    except Exception:
        logger.error("Parse __NEXT_DATA__ failed", exc_info=True)
        return []


def extract_item_no(row):
    return row.get("viewModel", {}).get("itemNo")


# setup_browser đã được thay thế bằng PlaywrightHandler trực tiếp trong worker


async def fetch_html(page, url, retry=3):
    for _ in range(retry):
        try:
            return await page.evaluate(
                """async (url) => {
                    const res = await fetch(url, { credentials: "include" });
                    if (!res.ok) throw new Error(res.status);
                    return await res.text();
                }""",
                url
            )
        except Exception as e:
            logger.error(f"Fetch HTML failed for {url}: {e}")
            await asyncio.sleep(random.uniform(2, 5))
    return None


async def fetch_one_page(page, semaphore: asyncio.Semaphore, price_range: tuple, page_no: int):
    from_price, to_price = price_range
    url = build_search_url(from_price, to_price, page_no)
    
    async with semaphore:
        try:
            html = await fetch_html(page, url)
            return html, page_no
        except Exception as e:
            logger.warning(f"({from_price}-{to_price} page={page_no} failed: {e})")
            return None, page_no

async def handle_price_range(page, price_range: tuple, semaphore: asyncio.Semaphore, thread_idx: int):
    from_price, to_price = price_range
    
    seen = set()
    items = []

    for page_no in range(1, max_page + 1):
        html, _ = await fetch_one_page(page, semaphore, price_range, page_no)
        if not html:
            break

        # Extract data
        rows = extract_data(html)
        new_items = 0
        for row in rows:
            item_no = extract_item_no(row)
            if not item_no or item_no in seen:
                continue
            seen.add(item_no)
            items.append({
                "itemNo": item_no,
                "scrape_time": int(time.time()),
                "data": row
            })
            new_items += 1

        if new_items == 0:
            break

        await asyncio.sleep(random.uniform(3,5))

    # Save JSON
    res = {
        "scrape_date": SCRAPE_DATE,
        "scrape_time": int(time.time()),
        "daily_scrape_order": SCRAPE_ORDER,
        "task_id": "basic",
        "config_id": CONFIG_ID,
        "platform": PLATFORM,
        "data": items
    }

    json_filename = f"{raw_json_basic_data_dir}/{SCRAPE_DATE}_{SCRAPE_ORDER}_{PLATFORM}_search-basic_{from_price}-{to_price}.json"
    async with aiofiles.open(json_filename, "w", encoding="utf-8") as f:
        await f.write(json.dumps(res, ensure_ascii=False, indent=2))

    # Log done
    async with aiofiles.open(
        f"{log_dir}/{SCRAPE_DATE}_{SCRAPE_ORDER}_{PLATFORM}_search-basic_price_done.txt",
        "a",
        encoding="utf-8"
    ) as log_f:
        await log_f.write(f"{price_range}\n")

    logger.info(f"Thread {thread_idx + 1}: Successfully scraped price range {from_price}-{to_price} with {len(items)} items!")


async def worker(batch_price_range: list[tuple], proxy_auth: dict, thread_idx: int, max_concurrent: int = 5):
    # Cấu hình proxy cho PlaywrightHandler
    proxy_config = None
    if proxy_auth:
        proxy_config = {
            "server": f"http://{proxy_auth['ip']}:{proxy_auth['port']}",
            "username": proxy_auth["username"],
            "password": proxy_auth["password"]
        }

    async with PlaywrightHandler(
        headless=False,
        proxy=proxy_config,
        browser_id=thread_idx,
        use_middleware=True 
    ) as handler:
        page = await handler.get_page()
        # Điều hướng tới trang chủ để init session/cookies
        home_url = "https://www.auction.co.kr/?redirect=1"
        logger.info(f"Initializing session via: {home_url}")
        await page.goto(home_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        
        semaphore = asyncio.Semaphore(max_concurrent)
        try:
            for price_range in batch_price_range:
                await handle_price_range(page, price_range, semaphore, thread_idx)
        except Exception as e:
            logger.error(f"Worker {thread_idx} exception: {e}")


def run_thread(batch_price_range: list[tuple], proxy_auth: dict, thread_idx: int):
    asyncio.run(worker(batch_price_range, proxy_auth, thread_idx, max_concurrent=5))


def start_threads(total_price_range: list[tuple], proxy_auths: list[dict]):
    num_threads = len(proxy_auths)
    print("num_threads", num_threads)
    batches = chunk_list(total_price_range, num_threads)
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        
        for idx, batch in enumerate(batches):
            futures.append(
                executor.submit(run_thread, batch, proxy_auths[idx % len(proxy_auths)], idx)
            )
        
        for future in futures:
            future.result()

def main():
    unscraped_price_range = filter_unscraped(price_ranges, f"{log_dir}/{SCRAPE_DATE}_{SCRAPE_ORDER}_{PLATFORM}_search-basic_price_done.txt")
    if len(unscraped_price_range) == 0:
        logger.info("All price range has been scraped !!!")
    else:
        start_threads(unscraped_price_range, auction_proxies)


if __name__ == "__main__":
    main()