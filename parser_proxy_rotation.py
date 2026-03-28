"""
Avito Parser v3.2 — Proxy Rotation
"""

import asyncio
import json
import logging
import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from telegram import Bot
from telegram.constants import ParseMode

from config_proxy_rotation import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SEARCH_TASKS,
    CHECK_INTERVAL_SECONDS,
    TASK_PAUSE_MIN,
    TASK_PAUSE_MAX,
    IP_BLOCK_WAIT,
    HEADLESS,
    DB_PATH,
    USER_AGENTS,
    PROXIES,
)

Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/parser.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

COOKIES_FILE   = "data/cookies.json"
FIRST_RUN_FILE = "data/first_run_done"
SCREENSHOT_DIR = Path("logs/screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

ITEM_SELECTORS  = ["[data-marker='item']", "div[class*='iva-item-root']", "article[class*='item']"]
TITLE_SELECTORS = ["[itemprop='name']", "[data-marker='item-title']", "h3"]
PRICE_SELECTORS = ["[data-marker='item-price']", "span[class*='price-price']", "[class*='price']"]



class ProxyRotator:
    """
    Хранит список прокси и текущий индекс.
    При блокировке переключается на следующий.
    Если все прокси заблокированы — ждёт IP_BLOCK_WAIT и сбрасывает счётчик.
    """

    def __init__(self, proxies: list[str]):
        if not proxies:
            raise ValueError("Список PROXIES пуст — добавь хотя бы один прокси")
        self._proxies  = proxies[:]
        self._index    = 0
        # blocked_until[proxy] = asyncio timestamp когда можно снова пробовать
        self._blocked: dict[str, float] = {}

    @property
    def current(self) -> str:
        return self._proxies[self._index]

    def rotate(self) -> str | None:
        """
        Помечает текущий прокси как заблокированный и переходит к следующему.
        Возвращает новый прокси или None если все заблокированы.
        """
        now = asyncio.get_event_loop().time()
        self._blocked[self.current] = now + IP_BLOCK_WAIT
        log.warning(f"🔄 Прокси {self.current} заблокирован, ищу следующий...")

        for _ in range(len(self._proxies)):
            self._index = (self._index + 1) % len(self._proxies)
            proxy = self._proxies[self._index]
            if self._blocked.get(proxy, 0) <= now:
                log.info(f"✅ Переключился на прокси #{self._index + 1}: {self._mask(proxy)}")
                return proxy

        return None

    def unblock_expired(self):
        """Снимает блокировку с прокси у которых истёк таймаут."""
        now = asyncio.get_event_loop().time()
        for proxy in list(self._blocked):
            if self._blocked[proxy] <= now:
                del self._blocked[proxy]
                log.info(f"♻️  Прокси разблокирован: {self._mask(proxy)}")

    def wait_until_available(self) -> float:
        """Возвращает сколько секунд ждать до разблокировки хотя бы одного прокси."""
        now = asyncio.get_event_loop().time()
        times = [v for v in self._blocked.values() if v > now]
        return (min(times) - now) if times else 0

    @staticmethod
    def _mask(proxy: str) -> str:
        """Скрывает пароль в логах: http://user:***@host:port"""
        return re.sub(r":([^/@]+)@", r":***@", proxy)

    def status(self) -> str:
        return (
            f"Прокси #{self._index + 1}/{len(self._proxies)} "
            f"| заблокировано: {len(self._blocked)}"
        )



def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS seen_ads (
        id TEXT PRIMARY KEY, title TEXT, price TEXT,
        url TEXT, task_name TEXT, seen_at TEXT
    )""")
    conn.commit()
    return conn

def is_new_ad(conn, ad_id):
    return conn.execute("SELECT 1 FROM seen_ads WHERE id=?", (ad_id,)).fetchone() is None

def save_ad(conn, ad, task_name):
    conn.execute(
        "INSERT OR IGNORE INTO seen_ads VALUES (?,?,?,?,?,?)",
        (ad["id"], ad["title"], ad["price"], ad["url"],
         task_name, datetime.now().isoformat()),
    )
    conn.commit()



def passes_filter(ad: dict, task: dict) -> bool:
    text = (ad["title"] + " " + ad["url"]).lower()

    for word in task.get("exclude", []):
        if word.lower() in text:
            log.debug(f"Blacklist [{word}]: {ad['title']}")
            return False

    keywords = task.get("keywords", [])
    if keywords and not any(kw.lower() in text for kw in keywords):
        log.debug(f"Не по теме: {ad['title']}")
        return False

    numeric = int(re.sub(r"[^\d]", "", ad["price"]) or 0)
    mn, mx = task.get("min_price", 0), task.get("max_price", 0)
    if mn and numeric and numeric < mn:
        return False
    if mx and numeric and numeric > mx:
        return False

    return True



async def send_telegram(bot: Bot, ad: dict, task_name: str):
    text = (
        f"{task_name}\n\n"
        f"*{ad['title']}*\n\n"
        f"💰 Цена: *{ad['price']}*\n"
        f"📍 {ad.get('location', '—')}\n"
        f"🕐 {ad.get('date', '—')}\n\n"
        f"🔗 [Открыть объявление]({ad['url']})"
    )
    if ad.get("image_url"):
        try:
            await bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID, photo=ad["image_url"],
                caption=text, parse_mode=ParseMode.MARKDOWN,
            )
            return
        except Exception:
            pass
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID, text=text,
        parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False,
    )

async def notify_proxy_switch(bot: Bot, rotator: ProxyRotator):
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                f"🔄 *Смена прокси*\n\n"
                f"Avito заблокировал прокси.\n"
                f"Статус: {rotator.status()}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

async def notify_all_blocked(bot: Bot, wait_sec: int):
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                f"⚠️ *Все прокси заблокированы*\n\n"
                f"Ожидаю {wait_sec // 60} мин. перед следующей попыткой."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass



async def save_cookies(context):
    try:
        cookies = await context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
    except Exception:
        pass

async def load_cookies(context):
    if not Path(COOKIES_FILE).exists():
        return
    try:
        with open(COOKIES_FILE) as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
    except Exception as e:
        log.debug(f"Cookies не загружены: {e}")



async def screenshot(page, name: str):
    try:
        p = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(p), full_page=True)
        log.info(f"Скриншот: {p}")
    except Exception:
        pass


class IpBlockError(Exception):
    pass

class PageBlockedError(Exception):
    pass


async def check_page(page):
    url   = page.url
    title = await page.title()

    if "проблема с ip" in title.lower() or ("ip" in title.lower() and "ограничен" in title.lower()):
        await screenshot(page, "ip_block")
        raise IpBlockError(f"IP заблокирован: {title}")

    soft = [
        "captcha" in url.lower(),
        "blocked" in url.lower(),
        "Доступ ограничен" in title,
        "Подтвердите" in title,
        "Проверка" in title,
        "429" in title,
    ]
    if any(soft):
        await screenshot(page, "soft_block")
        raise PageBlockedError(f"Мягкая блокировка: {title}")

    captcha_el = await page.query_selector("iframe[src*='captcha'], div[class*='captcha']")
    if captcha_el:
        await screenshot(page, "captcha")
        raise PageBlockedError("Капча на странице")


async def mouse_wiggle(page):
    try:
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(
                random.randint(200, 1100),
                random.randint(150, 600),
                steps=random.randint(8, 20),
            )
            await asyncio.sleep(random.uniform(0.15, 0.5))
    except Exception:
        pass

async def slow_scroll(page):
    try:
        await page.evaluate("""async () => {
            const s = ms => new Promise(r => setTimeout(r, ms));
            let done = 0;
            const limit = document.body.scrollHeight * 0.7;
            while (done < limit) {
                const step = Math.random()*120+40;
                window.scrollBy({top:step, behavior:'smooth'});
                done += step;
                await s(Math.random()*350+80);
            }
        }""")
    except Exception:
        pass


def make_proxy_config(proxy: str) -> dict:
    """Парсит строку прокси в формат Playwright."""
    # socks5://user:pass@host:port → {"server": "socks5://host:port", "username": ..., "password": ...}
    m = re.match(r"(https?|socks5)://(?:([^:@]+):([^@]+)@)?(.+)", proxy)
    if not m:
        return {"server": proxy}
    scheme, user, pwd, hostport = m.groups()
    cfg: dict = {"server": f"{scheme}://{hostport}"}
    if user:
        cfg["username"] = user
        cfg["password"] = pwd or ""
    return cfg


async def make_context(browser, proxy: str):
    proxy_cfg = make_proxy_config(proxy)
    ctx = await browser.new_context(
        proxy=proxy_cfg,
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1280 + random.randint(0, 200), "height": 720 + random.randint(0, 120)},
        locale="ru-RU",
        timezone_id="Europe/Moscow",
        extra_http_headers={
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Referer": "https://www.avito.ru/",
        },
    )
    await ctx.add_init_script("""
        delete Object.getPrototypeOf(navigator).webdriver;
        Object.defineProperty(navigator,'plugins',{get:()=>{
            const a=[
                {name:'Chrome PDF Plugin',filename:'internal-pdf-viewer'},
                {name:'Chrome PDF Viewer',filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                {name:'Native Client',filename:'internal-nacl-plugin'},
            ];
            a.item=i=>a[i]; a.namedItem=n=>a.find(p=>p.name===n); a.refresh=()=>{};
            return a;
        }});
        Object.defineProperty(navigator,'languages',{get:()=>['ru-RU','ru']});
        window.chrome={runtime:{},loadTimes:()=>({}),csi:()=>({})};
        const _q=navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query=p=>
            p.name==='notifications'?Promise.resolve({state:Notification.permission}):_q(p);
    """)
    return ctx



async def find_item_selector(page) -> str | None:
    for sel in ITEM_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=10_000)
            n = len(await page.query_selector_all(sel))
            if n > 3:
                return sel
        except PlaywrightTimeout:
            continue
    return None


async def parse_page(page) -> list[dict]:
    ads = []
    selector = await find_item_selector(page)
    if not selector:
        await screenshot(page, "no_items")
        log.warning("Карточки не найдены → смотрите logs/screenshots/")
        return ads

    items = await page.query_selector_all(selector)
    log.info(f"Карточек: {len(items)}")

    for item in items:
        try:
            ad_id = await item.get_attribute("data-item-id")
            if not ad_id:
                lnk = await item.query_selector("a[href*='/']")
                if lnk:
                    href = await lnk.get_attribute("href") or ""
                    m = re.search(r"_(\d+)$", href)
                    ad_id = m.group(1) if m else None
            if not ad_id:
                continue

            title = "Без названия"
            for sel in TITLE_SELECTORS:
                el = await item.query_selector(sel)
                if el:
                    t = (await el.inner_text()).strip()
                    if t:
                        title = t; break

            price = "Цена не указана"
            for sel in PRICE_SELECTORS:
                el = await item.query_selector(sel)
                if el:
                    r = (await el.inner_text()).strip()
                    if r:
                        price = re.sub(r"\s+", " ", r); break

            lnk = await item.query_selector("a[href*='/']")
            href = await lnk.get_attribute("href") if lnk else None
            if not href:
                continue
            url = f"https://www.avito.ru{href}" if href.startswith("/") else href

            geo = await item.query_selector(
                "[data-marker='item-address'],[class*='geo'],[class*='address']")
            location = (await geo.inner_text()).strip() if geo else "—"

            dte = await item.query_selector(
                "[data-marker='item-date'],time,[class*='date']")
            date = (await dte.inner_text()).strip() if dte else "—"

            img = await item.query_selector("img")
            image_url = None
            if img:
                src = await img.get_attribute("src") or await img.get_attribute("data-src")
                if src and src.startswith("http"):
                    image_url = src

            ads.append({"id": ad_id, "title": title, "price": price,
                        "url": url, "location": location, "date": date, "image_url": image_url})
        except Exception as e:
            log.debug(f"Ошибка карточки: {e}")

    return ads


async def load_task_page(browser, task_url: str, use_main_first: bool, proxy: str) -> tuple:
    ctx  = await make_context(browser, proxy)
    await load_cookies(ctx)
    page = await ctx.new_page()

    if use_main_first:
        log.info("→ Главная страница avito.ru...")
        await page.goto("https://www.avito.ru/", wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await check_page(page)
        await mouse_wiggle(page)
        await asyncio.sleep(random.uniform(1.5, 3.0))
        await save_cookies(ctx)

    log.info(f"→ {task_url[:90]}...")
    await page.goto(task_url, wait_until="domcontentloaded", timeout=45_000)
    await asyncio.sleep(random.uniform(2.5, 5.0))
    await check_page(page)
    await slow_scroll(page)
    await asyncio.sleep(random.uniform(1.0, 2.0))

    return ctx, page



async def run():
    conn     = init_db()
    bot      = Bot(token=TELEGRAM_BOT_TOKEN)
    rotator  = ProxyRotator(PROXIES)

    is_first_run = not Path(FIRST_RUN_FILE).exists()
    if is_first_run:
        log.info("=" * 60)
        log.info("ПЕРВЫЙ ЗАПУСК: сохраняем базу, в Telegram ничего не шлём.")
        log.info("Со следующего цикла придут только НОВЫЕ объявления.")
        log.info("=" * 60)

    log.info(f"Задач: {len(SEARCH_TASKS)} | Прокси: {len(PROXIES)} | Интервал: {CHECK_INTERVAL_SECONDS}s")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-infobars", "--window-size=1366,768",
                "--lang=ru-RU",
            ],
        )

        cycle = 0

        while True:
            rotator.unblock_expired()
            wait_sec = rotator.wait_until_available()
            if wait_sec > 0:
                log.warning(f"Все прокси заблокированы. Ждём {wait_sec:.0f} сек...")
                await asyncio.sleep(min(wait_sec, 60))
                continue

            cycle += 1
            log.info(f"\n{'='*55}")
            log.info(f"Цикл #{cycle} | {rotator.status()}")

            open_main_for_first_task = True

            for i, task in enumerate(SEARCH_TASKS):
                log.info(f"\n--- {task['name']} ---")

                if i > 0:
                    pause = random.uniform(TASK_PAUSE_MIN, TASK_PAUSE_MAX)
                    log.info(f"Пауза {pause:.0f} сек...")
                    await asyncio.sleep(pause)

                # Попытки со сменой прокси при блокировке
                attempts = len(PROXIES)  # максимум — перебрать все прокси
                ctx = None
                success = False

                for attempt in range(attempts):
                    proxy = rotator.current
                    log.info(f"[Прокси #{rotator._index + 1}] {ProxyRotator._mask(proxy)}")

                    try:
                        use_main = open_main_for_first_task or (random.random() < 0.2)
                        open_main_for_first_task = False

                        try:
                            ctx, page = await load_task_page(browser, task["url"], use_main, proxy)
                        except PageBlockedError:
                            if not use_main:
                                log.warning("Мягкая блокировка, пробую через главную...")
                                ctx, page = await load_task_page(browser, task["url"], True, proxy)
                            else:
                                raise

                        # Успешно загрузили страницу
                        success = True
                        break

                    except IpBlockError as e:
                        log.error(f"🚫 IP-блок на прокси #{rotator._index + 1}: {e}")
                        try:
                            await ctx.close()
                        except Exception:
                            pass
                        ctx = None

                        next_proxy = rotator.rotate()
                        if next_proxy is None:
                            log.error("Все прокси заблокированы!")
                            await notify_all_blocked(bot, IP_BLOCK_WAIT)
                            break
                        else:
                            await notify_proxy_switch(bot, rotator)
                            await asyncio.sleep(random.uniform(5, 15))

                    except (PageBlockedError, PlaywrightTimeout) as e:
                        log.error(f"Ошибка '{task['name']}': {e}")
                        try:
                            await ctx.close()
                        except Exception:
                            pass
                        ctx = None
                        break

                    except Exception as e:
                        log.error(f"Ошибка '{task['name']}': {e}", exc_info=True)
                        try:
                            await ctx.close()
                        except Exception:
                            pass
                        ctx = None
                        break

                if not success or ctx is None:
                    continue

                # Парсим объявления
                try:
                    ads = await parse_page(page)
                    sent = skipped = seen = 0

                    for ad in ads:
                        if not is_new_ad(conn, ad["id"]):
                            seen += 1
                            continue
                        if not passes_filter(ad, task):
                            skipped += 1
                            save_ad(conn, ad, task["name"])
                            continue
                        save_ad(conn, ad, task["name"])
                        if not is_first_run:
                            await send_telegram(bot, ad, task["name"])
                            sent += 1
                            log.info(f"✅ {ad['title']} — {ad['price']}")
                            await asyncio.sleep(random.uniform(1.5, 3.0))
                        else:
                            log.info(f"[тихо] {ad['title']} — {ad['price']}")

                    log.info(f"Итог: отправлено={sent}, фильтр={skipped}, видели={seen}")
                    await save_cookies(ctx)

                except Exception as e:
                    log.error(f"Ошибка парсинга '{task['name']}': {e}", exc_info=True)
                finally:
                    try:
                        await ctx.close()
                    except Exception:
                        pass

            if is_first_run:
                Path(FIRST_RUN_FILE).write_text("done")
                is_first_run = False
                log.info("\n✅ Первый запуск завершён. Следующий цикл — обычный режим.")

            sleep = CHECK_INTERVAL_SECONDS * random.uniform(0.85, 1.15)
            log.info(f"\n💤 Следующий цикл через {sleep:.0f} сек")
            await asyncio.sleep(sleep)


if __name__ == "__main__":
    asyncio.run(run())