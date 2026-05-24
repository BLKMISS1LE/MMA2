#!/usr/bin/env python3
"""
Meijer Receipt Formatter

Reads a Meijer digital receipt PDF, extracts line items, expands short receipt names
using a local alias/cache + optional barcode lookup APIs, assigns icons, and exports
a clean HTML receipt.

Usage:
  python meijer_receipt_formatter.py meijer_digital_receipt.pdf
  python meijer_receipt_formatter.py meijer_digital_receipt.pdf --no-online
  python meijer_receipt_formatter.py meijer_digital_receipt.pdf --out formatted_receipt.html

Optional:
  Set BARCODE_LOOKUP_API_KEY to use BarcodeLookup.com for non-food/general merch.
  Open Food Facts is attempted for food-style barcodes without an API key.

Install:
  pip install pymupdf requests
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

try:
    import fitz  # PyMuPDF, used by the desktop app when available.
except ImportError:
    fitz = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import requests
except ImportError:
    requests = None


# Starter aliases from the uploaded sample receipt.
# Add to this over time when a barcode API misses a product or Meijer uses an internal code.
LOCAL_PRODUCT_ALIASES = {
    "7192444899": {
        "name": "Mobil 1 Motor Oil",
        "brand": "Mobil 1",
        "icon": "🛢️",
        "category": "Automotive",
        "image_url": "https://www.meijer.com/content/dam/meijer/product/0071/92/4448/99/0071924448995_0_A1C1_0600.jpg",
    },
    "1111101250": {
        "name": "Dove Beauty Bar Soap",
        "brand": "Dove",
        "icon": "🧼",
        "category": "Health & Beauty",
        "image_code": "1111103644",
    },
    "2310011019": {
        "name": "Sheba Cat Food",
        "brand": "Sheba",
        "icon": "🐱",
        "category": "Pet Food",
        "image_code": "2310011020",
    },
    "2310011021": {
        "name": "Sheba Cat Food",
        "brand": "Sheba",
        "icon": "🐱",
        "category": "Pet Food",
        "image_code": "2310011020",
    },
    "2310011024": {
        "name": "Sheba Cat Food",
        "brand": "Sheba",
        "icon": "🐱",
        "category": "Pet Food",
        "image_code": "2310011020",
    },
    "2310011026": {
        "name": "Sheba Cat Food",
        "brand": "Sheba",
        "icon": "🐱",
        "category": "Pet Food",
        "image_code": "2310011020",
    },
    "70882031325": {
        "name": "Meijer Purified Drinking Water",
        "brand": "Meijer",
        "icon": "💧",
        "category": "Beverages",
        "image_code": "71373350224",
    },
    "2430086541": {
        "name": "Little Debbie Snack Cakes",
        "brand": "Little Debbie",
        "icon": "🍰",
        "category": "Snacks",
    },
    "4125010201": {
        "name": "Milk",
        "brand": "Meijer",
        "icon": "🥛",
        "category": "Dairy",
        "image_code": "4125010200",
    },
    "70882065176": {
        "name": "Meijer Blueberry Muffins",
        "brand": "Meijer",
        "icon": "🫐",
        "category": "Bakery",
    },
    "71928348866": {
        "name": "Foam Plates",
        "brand": "Meijer",
        "icon": "🍽️",
        "category": "Household",
    },
    "76023604152": {
        "name": "Coffee Cakes",
        "brand": "",
        "icon": "☕",
        "category": "Bakery",
    },
    "71373396628": {
        "name": "Frozen Appetizers",
        "brand": "",
        "icon": "🥟",
        "category": "Frozen",
    },
    "3400094653": {
        "name": "Candy",
        "brand": "",
        "icon": "🍬",
        "category": "Candy",
    },
    "4125000066": {
        "name": "Cookies",
        "brand": "",
        "icon": "🍪",
        "category": "Bakery",
    },
    "3400029605": {
        "name": "Candy",
        "brand": "",
        "icon": "🍬",
        "category": "Candy",
    },
    "4900001278": {
        "name": "Coca-Cola",
        "brand": "Coca-Cola",
        "icon": "🥤",
        "category": "Beverages",
        "image_code": "4900001278",
    },
    "99999": {
        "name": "Bottle Deposit",
        "brand": "",
        "icon": "♻️",
        "category": "Deposit",
    },
}

CATEGORY_ICONS = {
    "GENERAL MERCHANDISE": "🧰",
    "DRUGSTORE": "🧼",
    "GROCERY": "🛒",
    "AUTOMOTIVE": "🛢️",
    "BEVERAGES": "🥤",
    "DAIRY": "🥛",
    "BAKERY": "🥐",
    "HOUSEHOLD": "🏠",
    "FROZEN": "❄️",
    "CANDY": "🍬",
    "PET FOOD": "🐱",
    "DEPOSIT": "♻️",
}


@dataclass
class ReceiptItem:
    code: str
    raw_name: str
    display_name: str
    category: str
    icon: str
    quantity: float = 1
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    tax_flag: str = ""
    brand: str = ""
    image_url: str = ""
    image_urls: list[str] = None
    discounts: list[str] = None
    adjustments_total: float = 0.0

    def __post_init__(self):
        if self.image_urls is None:
            self.image_urls = [self.image_url] if self.image_url else []
        if self.discounts is None:
            self.discounts = []


def money_to_float(value: str) -> Optional[float]:
    value = value.strip().replace(",", "")
    if value.startswith("-."):
        value = "-0" + value[1:]
    try:
        return float(value)
    except ValueError:
        return None


def add_money(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if right is None:
        return left
    if left is None:
        left = 0.0
    return round(left + right, 2)


def adjustment_labels(discounts: list[str]) -> list[str]:
    labels = []
    for discount in discounts or []:
        lowered = discount.lower()
        if "free item" in lowered and "FREE ITEM" not in labels:
            labels.append("FREE ITEM")
        if "sale price" in lowered and "SALE PRICE" not in labels:
            labels.append("SALE PRICE")
    if discounts and not labels:
        labels.append("SALE")
    return labels


def extract_text(pdf_path: Path) -> str:
    """Extract text from a PDF.

    Desktop builds can use PyMuPDF. The mobile app uses pypdf because it is
    pure Python and much easier to package into an Android APK.
    """
    if fitz is not None:
        doc = fitz.open(str(pdf_path))
        return "\n".join(page.get_text("text") for page in doc)

    if PdfReader is not None:
        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    raise RuntimeError("Missing PDF dependency. Install pypdf for mobile or pymupdf for desktop.")


def normalize_code_variants(code: str) -> list[str]:
    """Barcode databases often expect 12/13/14 digits; Meijer receipts may drop leading zeroes."""
    variants = [code]
    for length in (12, 13, 14):
        if len(code) < length:
            variants.append(code.zfill(length))
    return list(dict.fromkeys(variants))


def load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def guess_icon(name: str, category: str) -> str:
    n = name.upper()
    if "OIL" in n:
        return "🛢️"
    if "SOAP" in n or "DOVE" in n:
        return "🧼"
    if "SHEBA" in n or "CAT" in n:
        return "🐱"
    if "WATER" in n:
        return "💧"
    if "MILK" in n:
        return "🥛"
    if "MUFFIN" in n:
        return "🫐"
    if "PLATE" in n:
        return "🍽️"
    if "COFFEE" in n:
        return "☕"
    if "APPETIZER" in n:
        return "🥟"
    if "CANDY" in n:
        return "🍬"
    if "COOKIE" in n:
        return "🍪"
    if "COCA" in n or "COLA" in n:
        return "🥤"
    return CATEGORY_ICONS.get(category.upper(), "🛒")


def lookup_open_food_facts(code: str) -> Optional[dict]:
    if requests is None:
        return None
    for variant in normalize_code_variants(code):
        url = f"https://world.openfoodfacts.org/api/v2/product/{variant}.json"
        try:
            r = requests.get(url, timeout=8, headers={"User-Agent": "MeijerReceiptFormatter/0.1"})
            if r.ok:
                data = r.json()
                product = data.get("product") or {}
                if data.get("status") == 1 and product:
                    name = product.get("product_name") or product.get("generic_name")
                    if name:
                        return {
                            "name": name,
                            "brand": product.get("brands", ""),
                            "category": (product.get("categories_tags") or ["Grocery"])[0].replace("en:", "").title(),
                            "icon": guess_icon(name, "Grocery"),
                            "image_url": product.get("image_front_url") or product.get("image_url") or "",
                            "source": "openfoodfacts",
                        }
        except Exception:
            continue
    return None


def lookup_barcode_lookup_api(code: str, api_key: str) -> Optional[dict]:
    if requests is None or not api_key:
        return None
    for variant in normalize_code_variants(code):
        url = "https://api.barcodelookup.com/v3/products"
        try:
            r = requests.get(
                url,
                params={"barcode": variant, "formatted": "y", "key": api_key},
                timeout=8,
                headers={"User-Agent": "MeijerReceiptFormatter/0.1"},
            )
            if r.ok:
                data = r.json()
                products = data.get("products") or []
                if products:
                    p = products[0]
                    name = p.get("title") or p.get("product_name")
                    if name:
                        return {
                            "name": name,
                            "brand": p.get("brand", ""),
                            "category": p.get("category", "General"),
                            "icon": guess_icon(name, p.get("category", "")),
                            "image_url": (p.get("images") or [""])[0],
                            "source": "barcodelookup",
                        }
        except Exception:
            continue
    return None


def upc_check_digit(first_11_digits: str) -> str:
    digits = [int(d) for d in first_11_digits]
    odd_sum = sum(digits[0::2])
    even_sum = sum(digits[1::2])
    return str((10 - ((odd_sum * 3 + even_sum) % 10)) % 10)


def meijer_image_ids_from_code(code: str) -> list[str]:
    if not code or not code.isdigit():
        return []

    ids = []
    if len(code) <= 11:
        upc12 = code.zfill(11) + upc_check_digit(code.zfill(11))
        ids.append(upc12.zfill(13))

    if len(code) == 12:
        ids.append(code.zfill(13))

    ids.extend([code.zfill(13), code])
    return list(dict.fromkeys(ids))


def meijer_image_url_from_id(image_id: str, variant: str = "0", size: str = "0600", ext: str = "jpg") -> str:
    folder = f"{image_id[0:4]}/{image_id[4:6]}/{image_id[6:10]}/{image_id[10:12]}"
    return f"https://www.meijer.com/content/dam/meijer/product/{folder}/{image_id}_{variant}_A1C1_{size}.{ext}"


def meijer_image_url_from_code(code: str) -> str:
    ids = meijer_image_ids_from_code(code)
    return meijer_image_url_from_id(ids[0]) if ids else ""


def meijer_image_candidates_from_code(code: str) -> list[str]:
    if not code:
        return []
    candidates = []
    for image_id in meijer_image_ids_from_code(code):
        for variant in ("0", "1"):
            for size in ("0600", "1200"):
                for ext in ("jpg", "png"):
                    candidates.append(meijer_image_url_from_id(image_id, variant, size, ext))
    return list(dict.fromkeys(candidates))


def merge_image_urls(*groups) -> list[str]:
    urls = []
    for group in groups:
        if not group:
            continue
        if isinstance(group, str):
            group = [group]
        for url in group:
            if url and url not in urls:
                urls.append(url)
    return urls


def browser_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.meijer.com/",
    }


def image_headers() -> dict:
    headers = browser_headers()
    headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    return headers


def lookup_meijer_search_result(code: str, product_name: str) -> str:
    if requests is None:
        return ""

    product_link_re = re.compile(r"(?P<link>/shopping/product/[^\"'<>]+?/(?P<id>\d{5,14})\.html)", re.I)
    image_re = re.compile(r"https://[^\"'\\\s<>]+(?:meijer|scene7)[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)", re.I)

    for query in [code, product_name]:
        if not query:
            continue
        try:
            response = requests.get(
                f"https://www.meijer.com/shopping/search.html?text={quote_plus(query)}",
                timeout=5,
                headers=browser_headers(),
            )
            if not response.ok:
                continue
            body = response.text

            for match in image_re.findall(body):
                image_url = match.replace("\\u002F", "/").replace("\\/", "/")
                lowered = image_url.lower()
                if "logo" not in lowered and "placeholder" not in lowered:
                    return image_url

            product_ids = []
            for match in product_link_re.finditer(body):
                product_id = match.group("id")
                product_url = "https://www.meijer.com" + match.group("link").replace("\\/", "/")
                page_image = lookup_meijer_product_page_image(product_url)
                if page_image:
                    return page_image
                if product_id not in product_ids:
                    product_ids.append(product_id)
            if product_ids:
                return meijer_image_url_from_code(product_ids[0])
        except Exception:
            continue

    return ""


def lookup_meijer_product_page_image(product_url: str) -> str:
    if requests is None:
        return ""

    image_patterns = [
        re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](?P<url>[^"\']+)["\']', re.I),
        re.compile(r'<meta[^>]+content=["\'](?P<url>[^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
        re.compile(r'"image"\s*:\s*"(?P<url>https?:\\?/\\?/[^"]+)"', re.I),
        re.compile(r"https://[^\"'\\\s<>]+(?:meijer|scene7)[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)", re.I),
    ]
    try:
        response = requests.get(product_url, timeout=5, headers=browser_headers())
        if not response.ok:
            return ""
        body = response.text
        for pattern in image_patterns:
            for match in pattern.finditer(body):
                image_url = match.groupdict().get("url") or match.group(0)
                image_url = image_url.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
                lowered = image_url.lower()
                if "logo" not in lowered and "placeholder" not in lowered:
                    return image_url
    except Exception:
        return ""
    return ""


def lookup_meijer_image(code: str, product_name: str) -> str:
    """Best-effort Meijer.com image lookup. Results are saved in product_cache.json."""
    if requests is None:
        return ""

    found = lookup_meijer_search_result(code, product_name)
    if found:
        return found

    for variant in normalize_code_variants(code):
        if len(variant) < 12:
            continue
        png_url = meijer_image_url_from_code(variant)
        jpg_url = png_url.removesuffix(".png") + ".jpg"
        for ext in ("png", "jpg"):
            image_url = png_url if ext == "png" else jpg_url
            try:
                response = requests.get(image_url, timeout=3, stream=True, headers=image_headers())
                if response.ok and response.headers.get("content-type", "").lower().startswith("image/"):
                    response.close()
                    return image_url
                response.close()
            except Exception:
                continue

    return ""


def resolve_product(code: str, raw_name: str, receipt_category: str, cache: dict, online: bool) -> dict:
    if code in LOCAL_PRODUCT_ALIASES:
        product = dict(LOCAL_PRODUCT_ALIASES[code])
        if online:
            product["image_urls"] = merge_image_urls(
                product.get("image_urls"),
                product.get("image_url"),
                meijer_image_candidates_from_code(code),
                meijer_image_candidates_from_code(product.get("image_code", "")) if product.get("image_code") else [],
            )
            product["image_url"] = product["image_urls"][0] if product["image_urls"] else ""
            image_url = lookup_meijer_image(code, product.get("name") or raw_name)
            if image_url:
                product["image_urls"] = merge_image_urls(image_url, product.get("image_urls"))
                product["image_url"] = product["image_urls"][0]
                cache[code] = product
        else:
            product["image_url"] = ""
            product["image_urls"] = []
        return product

    if code in cache:
        product = cache[code]
        if online:
            product["image_urls"] = merge_image_urls(
                product.get("image_urls"),
                product.get("image_url"),
                meijer_image_candidates_from_code(code),
            )
            product["image_url"] = product["image_urls"][0] if product["image_urls"] else ""
            image_url = lookup_meijer_image(code, product.get("name") or raw_name)
            if image_url:
                product["image_urls"] = merge_image_urls(image_url, product.get("image_urls"))
                product["image_url"] = product["image_urls"][0]
                cache[code] = product
        else:
            product["image_url"] = ""
            product["image_urls"] = []
        return product

    found = None
    if online:
        # Food first; it is free/open and works well for grocery items.
        found = lookup_open_food_facts(code)

        # Optional paid/trial API for general merch and better coverage.
        if found is None:
            found = lookup_barcode_lookup_api(code, os.getenv("BARCODE_LOOKUP_API_KEY", ""))

    if found:
        if online:
            meijer_image_url = lookup_meijer_image(code, found.get("name") or raw_name)
            if meijer_image_url:
                found["image_url"] = meijer_image_url
            found["image_urls"] = merge_image_urls(
                found.get("image_url"),
                found.get("image_urls"),
                meijer_image_candidates_from_code(code),
            )
        else:
            found["image_url"] = ""
            found["image_urls"] = []
        found["image_url"] = found["image_urls"][0] if found["image_urls"] else ""
        cache[code] = found
        return found

    image_url = lookup_meijer_image(code, raw_name) if online else ""
    image_urls = merge_image_urls(image_url, meijer_image_candidates_from_code(code)) if online else []
    fallback = {
        "name": raw_name.title(),
        "brand": "",
        "category": receipt_category.title(),
        "icon": guess_icon(raw_name, receipt_category),
        "image_url": image_urls[0] if image_urls else "",
        "image_urls": image_urls,
        "source": "receipt-fallback",
    }
    cache[code] = fallback
    return fallback


def parse_receipt_text(text: str, online: bool = True, cache_path: Path = Path("product_cache.json")) -> tuple[list[ReceiptItem], dict]:
    cache = load_cache(cache_path)
    items: list[ReceiptItem] = []
    current_category = "Uncategorized"
    current_item: Optional[ReceiptItem] = None

    category_re = re.compile(r"^(GENERAL MERCHANDISE|DRUGSTORE|GROCERY)$")
    item_re = re.compile(
        r"^\*?(?P<code>\d{5,14})\s+(?P<name>[A-Z0-9 &.'/-]+?)(?:\s+(?P<total>-?\d+\.\d{2}|-\.\d{2})\s*(?P<tax>[A-Z]{1,2})?)?$"
    )
    qty_re = re.compile(
        r"^(?P<qty>\d+(?:\.\d+)?)\s+@\s+(?P<unit>\d+\.\d{2})\s+(?P<total>-?\d+\.\d{2}|-\.\d{2})\s*(?P<tax>[A-Z]{1,2})?"
    )
    discount_re = re.compile(r"^=>\s+(?P<label>.+?)\s+(?P<amount>-?\d+\.\d{2}|-\.\d{2})\s*(?P<tax>[A-Z])?$")
    was_now_re = re.compile(r"^was\s+(?P<was>\d+\.\d{2})\s+now\s+(?P<now>\d+\.\d{2})\s*(?P<tax>[A-Z])?")

    totals = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if category_re.match(line):
            current_category = line
            current_item = None
            continue

        if line in {"TOTAL", "PAYMENTS"}:
            current_item = None
            current_category = line
            continue

        if current_category == "TOTAL":
            if line.startswith("TOTAL TAX"):
                totals["tax"] = money_to_float(line.split()[-1])
            elif line.startswith("TOTAL "):
                totals["total"] = money_to_float(line.split()[-1])
            elif "Sales Tax" in line:
                totals["sales_tax"] = money_to_float(line.split()[-1])
            continue

        if current_category == "PAYMENTS":
            continue

        m = item_re.match(line)
        if m and current_category not in {"TOTAL", "PAYMENTS"}:
            code = m.group("code")
            raw_name = m.group("name").strip()
            product = resolve_product(code, raw_name, current_category, cache, online)
            current_item = ReceiptItem(
                code=code,
                raw_name=raw_name,
                display_name=product.get("name") or raw_name.title(),
                brand=product.get("brand", ""),
                category=product.get("category") or current_category.title(),
                icon=product.get("icon") or guess_icon(raw_name, current_category),
                image_url=product.get("image_url", ""),
                image_urls=product.get("image_urls") or ([product.get("image_url")] if product.get("image_url") else []),
                line_total=money_to_float(m.group("total") or "") if m.group("total") else None,
                tax_flag=m.group("tax") or "",
            )
            items.append(current_item)
            continue

        if current_item:
            q = qty_re.match(line)
            if q:
                current_item.quantity = float(q.group("qty"))
                current_item.unit_price = money_to_float(q.group("unit"))
                current_item.line_total = money_to_float(q.group("total"))
                current_item.tax_flag = q.group("tax") or current_item.tax_flag
                continue

            d = discount_re.match(line)
            if d:
                amount = money_to_float(d.group("amount"))
                current_item.discounts.append(f"{d.group('label')} {d.group('amount')}")
                current_item.line_total = add_money(current_item.line_total, amount)
                current_item.adjustments_total = add_money(current_item.adjustments_total, amount) or 0.0
                current_item.tax_flag = d.group("tax") or current_item.tax_flag
                continue

            wn = was_now_re.match(line)
            if wn:
                current_item.discounts.append(f"was {wn.group('was')} now {wn.group('now')}")
                was = money_to_float(wn.group("was"))
                now = money_to_float(wn.group("now"))
                if was is not None and now is not None:
                    current_item.adjustments_total = add_money(current_item.adjustments_total, -(was - now)) or 0.0
                if current_item.line_total is None:
                    current_item.line_total = now
                current_item.tax_flag = wn.group("tax") or current_item.tax_flag
                continue

    save_cache(cache_path, cache)
    return items, totals


def render_html(items: list[ReceiptItem], totals: dict, out_path: Path) -> None:
    rows = []
    for item in items:
        brand = f"<div class='brand'>{html.escape(item.brand)}</div>" if item.brand else ""
        discounts = "".join(f"<div class='discount'>↳ {html.escape(d)}</div>" for d in item.discounts)
        adjustment = ""
        if item.adjustments_total:
            adjustment = f"<div class='adjustment'>Sale savings: ${abs(item.adjustments_total):.2f}</div>"
        badges = "".join(f"<span class='item-badge'>{html.escape(label)}</span>" for label in adjustment_labels(item.discounts))
        image = (
            f"<img class='product-image' src='{html.escape(item.image_url, quote=True)}' alt=''>"
            if item.image_url
            else "<div class='product-image placeholder'></div>"
        )
        qty = f"{item.quantity:g}"
        unit = f"${item.unit_price:.2f}" if item.unit_price is not None else ""
        total = f"${item.line_total:.2f}" if item.line_total is not None else ""
        tax = html.escape(item.tax_flag)
        rows.append(f"""
        <tr>
          <td class="image-cell">{image}</td>
          <td>
            <div class="name">{html.escape(item.display_name)}</div>
            <div class="badges">{badges}</div>
            {brand}
            <div class="meta">{html.escape(item.category)} · #{html.escape(item.code)} · receipt: {html.escape(item.raw_name)}</div>
            {discounts}
            {adjustment}
          </td>
          <td>{qty}</td>
          <td>{unit}</td>
          <td class="money">{total}</td>
          <td>{tax}</td>
        </tr>""")

    total_html = ""
    if totals:
        for label, value in totals.items():
            if value is not None:
                total_html += f"<div><span>{html.escape(label.replace('_', ' ').title())}</span><b>${value:.2f}</b></div>"

    doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Formatted Meijer Receipt</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #0b0d12; color: #f4f7fb; }}
  .page {{ max-width: 980px; margin: 32px auto; padding: 24px; }}
  .card {{ background: linear-gradient(145deg, #171b25, #0f1219); border: 1px solid #2a3142; border-radius: 22px; overflow: hidden; box-shadow: 0 18px 60px rgba(0,0,0,.35); }}
  header {{ padding: 24px 28px; border-bottom: 1px solid #293044; display: flex; justify-content: space-between; gap: 20px; align-items: center; }}
  h1 {{ margin: 0; font-size: 28px; letter-spacing: .3px; }}
  .subtitle {{ color: #aab4c8; margin-top: 6px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; color: #97a3ba; font-size: 12px; text-transform: uppercase; letter-spacing: .12em; padding: 14px 18px; background: #111520; }}
  td {{ padding: 15px 18px; border-top: 1px solid #22283a; vertical-align: top; }}
  .image-cell {{ width: 58px; }}
  .product-image {{ width: 46px; height: 46px; object-fit: contain; border-radius: 8px; background: #fff; display: block; }}
  .product-image.placeholder {{ background: #232b3d; border: 1px solid #33405a; }}
  .name {{ font-size: 17px; font-weight: 750; }}
  .badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }}
  .item-badge {{ display: inline-block; background: #0f7a3d; color: white; border-radius: 5px; padding: 3px 7px; font-size: 11px; font-weight: 800; letter-spacing: .04em; }}
  .brand {{ color: #dce6ff; font-size: 13px; margin-top: 2px; }}
  .meta {{ color: #8f9bb4; font-size: 12px; margin-top: 4px; }}
  .discount {{ color: #76f0aa; font-size: 12px; margin-top: 4px; }}
  .adjustment {{ color: #76f0aa; font-size: 12px; font-weight: 700; margin-top: 4px; }}
  .money {{ text-align: right; font-weight: 700; }}
  .totals {{ margin: 20px 28px 28px auto; width: min(320px, calc(100% - 56px)); }}
  .totals div {{ display: flex; justify-content: space-between; padding: 8px 0; color: #b9c4da; }}
  .totals b {{ color: #fff; }}
  .badge {{ background: #24304a; border: 1px solid #3d4a68; padding: 7px 12px; border-radius: 999px; color: #d8e2ff; font-size: 13px; }}
</style>
</head>
<body>
<div class="page">
  <div class="card">
    <header>
      <div>
        <h1>🛒 Formatted Meijer Receipt</h1>
        <div class="subtitle">Clean names, item numbers, icons, quantities, discounts, and tax flags.</div>
      </div>
      <div class="badge">{len(items)} receipt lines</div>
    </header>
    <table>
      <thead>
        <tr><th></th><th>Item</th><th>Qty</th><th>Each</th><th class="money">Total</th><th>Tax</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    <div class="totals">{total_html}</div>
  </div>
</div>
</body>
</html>"""
    out_path.write_text(doc, encoding="utf-8")


def render_pdf(items: list[ReceiptItem], totals: dict, out_path: Path, photo_bytes: Optional[list[bytes | None]] = None) -> None:
    doc = fitz.open()
    page_width, page_height = fitz.paper_size("letter")
    margin = 36
    row_height = 76
    y = margin

    navy = (0.05, 0.08, 0.14)
    muted = (0.36, 0.41, 0.50)
    border = (0.82, 0.85, 0.90)
    soft = (0.95, 0.97, 1.00)
    green = (0.00, 0.48, 0.24)

    def new_page() -> fitz.Page:
        page = doc.new_page(width=page_width, height=page_height)
        page.draw_rect(fitz.Rect(0, 0, page_width, page_height), color=(1, 1, 1), fill=(1, 1, 1))
        page.insert_text((margin, 34), "Formatted Meijer Receipt", fontsize=21, fontname="helv", color=navy)
        page.insert_text((margin, 56), f"{len(items)} receipt lines", fontsize=9.5, fontname="helv", color=muted)
        page.draw_line((margin, 74), (page_width - margin, 74), color=border, width=0.8)
        return page

    def ensure_space(page: fitz.Page, needed: float) -> tuple[fitz.Page, float]:
        nonlocal y
        if y + needed > page_height - margin:
            page = new_page()
            y = 92
        return page, y

    page = new_page()
    y = 92
    has_images = any(photo_bytes or [])

    for index, item in enumerate(items):
        page, y = ensure_space(page, row_height)
        row_rect = fitz.Rect(margin, y, page_width - margin, y + row_height - 8)
        page.draw_rect(row_rect, color=border, fill=soft, width=0.6)

        if has_images:
            image_rect = fitz.Rect(margin + 10, y + 8, margin + 54, y + 52)
            image_data = photo_bytes[index] if photo_bytes and index < len(photo_bytes) else None
            if image_data:
                try:
                    page.insert_image(image_rect, stream=image_data, keep_proportion=True)
                except Exception:
                    page.draw_rect(image_rect, color=border, fill=(1, 1, 1), width=0.6)
                    page.insert_textbox(image_rect, "no\nimage", fontsize=7, fontname="helv", color=muted, align=1)
            else:
                page.draw_rect(image_rect, color=border, fill=(1, 1, 1), width=0.6)
                page.insert_textbox(image_rect, "no\nimage", fontsize=7, fontname="helv", color=muted, align=1)

        x = margin + 72 if has_images else margin + 12
        right_x = page_width - margin - 112
        name_rect = fitz.Rect(x, y + 10, right_x, y + 29)
        badge_rect = fitz.Rect(x, y + 29, right_x, y + 43)
        meta_rect = fitz.Rect(x, y + 44, right_x, y + 58)
        discount_rect = fitz.Rect(x, y + 58, right_x, y + 72)

        page.insert_textbox(name_rect, item.display_name, fontsize=11.5, fontname="helv", color=navy)
        badge_x = x
        for label in adjustment_labels(item.discounts):
            badge_width = 36 if label == "SALE" else 62
            badge = fitz.Rect(badge_x, y + 29, badge_x + badge_width, y + 42)
            page.draw_rect(badge, color=green, fill=green, width=0.4)
            page.insert_textbox(badge, label, fontsize=6.6, fontname="helv", color=(1, 1, 1), align=1)
            badge_x += badge_width + 5
        meta = f"{item.brand + ' | ' if item.brand else ''}{item.category} | #{item.code} | receipt: {item.raw_name}"
        page.insert_textbox(meta_rect, meta, fontsize=7.8, fontname="helv", color=muted)
        if item.discounts:
            discount_text = "Applied: " + "; ".join(item.discounts)
            if item.adjustments_total:
                discount_text += f" | Sale savings: ${abs(item.adjustments_total):.2f}"
            page.insert_textbox(discount_rect, discount_text, fontsize=7.8, fontname="helv", color=green)

        qty = f"Qty {item.quantity:g}"
        each = f"${item.unit_price:.2f} ea" if item.unit_price is not None else ""
        total = f"${item.line_total:.2f}" if item.line_total is not None else ""
        page.insert_text((page_width - margin - 98, y + 20), qty, fontsize=8.5, fontname="helv", color=muted)
        if each:
            page.insert_text((page_width - margin - 98, y + 34), each, fontsize=8.5, fontname="helv", color=muted)
        if total:
            page.insert_text((page_width - margin - 98, y + 52), total, fontsize=12, fontname="helv", color=navy)

        y += row_height

    if totals:
        page, y = ensure_space(page, 92)
        totals_x = page_width - margin - 220
        page.draw_rect(fitz.Rect(totals_x, y, page_width - margin, y + 70), color=border, fill=(0.98, 0.99, 1), width=0.6)
        line_y = y + 18
        for label, value in totals.items():
            if value is None:
                continue
            page.insert_text((totals_x + 14, line_y), label.replace("_", " ").title(), fontsize=9.5, fontname="helv", color=muted)
            page.insert_text((page_width - margin - 72, line_y), f"${value:.2f}", fontsize=10.5, fontname="helv", color=navy)
            line_y += 18

    if out_path.exists():
        out_path.unlink()
    doc.save(str(out_path))
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Format Meijer digital receipts with icons and better product names.")
    parser.add_argument("pdf", type=Path, help="Path to a Meijer digital receipt PDF")
    parser.add_argument("--out", type=Path, default=Path("formatted_receipt.html"), help="Output HTML file")
    parser.add_argument("--cache", type=Path, default=Path("product_cache.json"), help="Product lookup cache JSON")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional parsed item JSON output")
    parser.add_argument("--no-online", action="store_true", help="Disable API lookup and only use local aliases/cache")
    args = parser.parse_args()

    text = extract_text(args.pdf)
    items, totals = parse_receipt_text(text, online=not args.no_online, cache_path=args.cache)
    render_html(items, totals, args.out)

    if args.json_out:
        args.json_out.write_text(json.dumps([asdict(i) for i in items], indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Parsed {len(items)} items")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
