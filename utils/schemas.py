from pydantic import BaseModel, Field, field_validator

from typing import Optional, List, Literal
from datetime import date, datetime, timezone


class BasicProductSchema(BaseModel):
    """Schema for basic product data after transformation"""
    rdate: date = Field(..., description="Scrape date")
    rtime: datetime = Field(..., description="Scrape time")
    daily_scrape_order: int = Field(..., description="Daily scrape order")
    task_id: str = Field(..., description="Task identification")
    config_id: str = Field(..., description="Configuration identifier")
    filename: str = Field(..., description="Source file of the product")
    mall_pid: str = Field(..., description="Platform product ID")
    mall_url: str = Field(..., description="Product URL")
    title: str = Field(..., description="Product title")
    product_price: Optional[int] = Field(None, description="Original price")
    product_sales_price: Optional[int] = Field(None, description="Sales price")
    product_pay_price: Optional[int] = Field(None, description="Final pay price")
    product_sales_cnt: Optional[int] = Field(None, description="Sales count")
    product_remain_cnt: Optional[int] = Field(None, description="Remaining count")
    product_discount_rate: Optional[float] = Field(None, description="Discount rate")
    brand: Optional[str] = Field(None, description="Brand name")
    retailer_name: Optional[str] = Field(None, description="Retailer name")
    retailer_url: Optional[str] = Field(None, description="Retailer URL")
    retailer_id: Optional[str] = Field(None, description="Retailer ID")
    out_of_stock: int = Field(..., ge=0, le=1, description="Out of stock flag")
    not_available: int = Field(..., ge=0, le=1, description="Not available flag")
    review_cnt: Optional[int] = Field(None, description="Review count")
    star_rating: Optional[float] = Field(None, ge=0, le=5, description="Star rating")
    delivery_txt: Optional[str] = Field(None, description="Delivery text")
    update_tms: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("rdate", mode="before")
    def parse_rdate(cls, v):
        return date.fromisoformat(v)

    @field_validator("rtime", mode="before")
    def parse_rtime(cls, v):
        try:
            ts = float(v)
            if ts > 1e12:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except:
            return None
        
    @field_validator("product_sales_cnt", mode="before")
    def clean_sales_cnt(cls, v):
        if isinstance(v, str):
            return int(v.replace(",", ""))
        return v
    
    @field_validator("product_remain_cnt", mode="before")
    def clean_remain_cnt(cls, v):
        if isinstance(v, str):
            return int(v.replace(",", ""))
        return v
    
    @field_validator("product_discount_rate", mode="before")
    def clean_discount_rate(cls, v):
        if isinstance(v, str):
            if "%" in v:
                return float(v.replace("%", ""))
        return v


class DetailProductSchema(BaseModel):
    """Schema for detail product data after transformation"""
    rdate: date = Field(..., description="Scrape date")
    rtime: datetime = Field(..., description="Scrape time")
    daily_scrape_order: int = Field(..., description="Daily scrape order")
    search_keyword: str = Field(..., description="Keyword for scraping")
    mall: str = Field(..., description="Platform URL")
    task_id: str = Field(..., description="Task identification")
    config_id: str = Field(..., description="Configuration identifier")
    filename: str = Field(..., description="Source file of the product")
    mall_pid: str = Field(..., description="Platform product ID")
    mall_url: str = Field(..., description="Product URL")
    title: str = Field(..., description="Product title")
    product_price: Optional[int] = Field(None, description="Product original price")
    product_sales_price: Optional[int] = Field(None, description="Product discount price")
    product_pay_price: Optional[int] = Field(None, description="Product final pay price")
    product_sales_cnt: Optional[int] = Field(None, description="Product sales count")
    product_remain_cnt: Optional[int] = Field(None, description="Product remaining count")
    product_discount_rate: Optional[float] = Field(None, description="Discount rate")
    delivery_type: Optional[int] = Field(None, description="Delivery type flag (0 = free shipping, 1 = paid shipping)")
    delivery_charge: Optional[int] = Field(None, description="Shipping fee amount")
    delivery_txt: Optional[str] = Field(None, description="Raw delivery information text scraped from source")
    delivery_section: Optional[str] = Field(None, description="Delivery region or shipping coverage area")
    delivery_company: Optional[str] = Field(None, description="Delivery region or shipping coverage area")
    out_of_stock: int = Field(..., ge=0, le=1, description="Out of stock flag")
    not_available: int = Field(..., ge=0, le=1, description="Not available flag")
    manufacturer: Optional[str] = Field(None, description="Product manufacturer or producing company")
    brand: Optional[str] = Field(None, description="Product brand name")
    category_txt: str = Field(..., description="Product category listing")
    star_rating: Optional[float] = Field(None, ge=0, le=5, description="Average product star rating (0-5 scale)")
    review_cnt: Optional[int] = Field(None, description="Total number of product reviews")
    retailer_id: Optional[str] = Field(None, description="Unique retailer identifier from source platform (seller/shop ID)")
    retailer_name: Optional[str] = Field(None, description="Retailer or seller display name on the platform")
    retailer_url: Optional[str] = Field(None, description="URL to retailer or seller profile page")
    have_option: bool = Field(..., desciption="Indicates whether product has variants/options")
    mall_opt_type: Optional[Literal["single", "related", "combination"]] = Field(None, description="Type of option of product")
    mall_opt_id: Optional[str] = Field(None, description="Unique identifier of product option/variant")
    mall_opt_txt: Optional[str] = Field(None, description="Display name of product option/variant")
    mall_opt_price: Optional[int] = Field(None, description="Original price of product option")
    mall_opt_sales_price: Optional[int] = Field(None, description="Discounted price of product option")
    mall_opt_sales_cnt: Optional[int] = Field(None, description="Number of units sold for this option")
    mall_opt_remain_cnt: Optional[int] = Field(None, description="Remaining stock quantity for this option")
    company_name: Optional[str] = Field(None)
    representative_name: Optional[str] = Field(None)
    business_registration_number: Optional[str] = Field(None)
    return_addr: Optional[str] = Field(None, description="Return/exchange address for product returns")
    morder_name: Optional[str] = Field(None, description="Internal middle-layer order name")
    morder_number: Optional[str] = Field(None, description="Internal middle-layer order identifier")
    update_tms: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("rdate", mode="before")
    def parse_rdate(cls, v):
        return date.fromisoformat(v)

    @field_validator("rtime", mode="before")
    def parse_rtime(cls, v):
        try:
            ts = float(v)
            if ts > 1e12:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except:
            return None
    
    @field_validator("product_discount_rate", mode="before")
    def clean_discount_rate(cls, v):
        if isinstance(v, str):
            if "%" in v:
                return float(v.replace("%", ""))
        return v