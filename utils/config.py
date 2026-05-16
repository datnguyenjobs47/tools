from dataclasses import dataclass
from datetime import datetime

CONFIG_ID = "poc"
SCRAPE_TIME = 3
SCRAPE_DATE = datetime.now().strftime("%Y-%m-%d")

@dataclass
class Config:
    config_id: str
    scrape_time: int
    scrape_date: str


def create_config() -> Config:
    return Config(
        config_id=CONFIG_ID,
        scrape_time=SCRAPE_TIME,
        scrape_date=SCRAPE_DATE
    )