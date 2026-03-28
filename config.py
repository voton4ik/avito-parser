TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = 111111111 #должен начинаться с -

# ВАЖНО: URL берётся прямо с Avito — настройте фильтры в браузере,
# выберите сортировку «По дате» и скопируйте URL.
# Обязательно должен начинаться с https://www.avito.ru/
#
# keywords  — объявление должно содержать ХОТЯ БЫ ОДНО слово из списка
# exclude   — объявление будет пропущено если содержит ЛЮБОЕ из этих слов
# min/max_price — 0 = без ограничений

SEARCH_TASKS = [
    {
        "name": "💾 Оперативная память DDR5",

        "url": (
            "https://www.avito.ru/samarskaya_oblast/bytovaya_elektronika?cd=1&localPriority=0&q=%D0%BE%D0%BF%D0%B5%D1%80%D0%B0%D1%82%D0%B8%D0%B2%D0%BD%D0%B0%D1%8F+%D0%BF%D0%B0%D0%BC%D1%8F%D1%82%D1%8C+ddr5&s=104"

        ),
        "keywords": ["ddr5", "ddr 5"],
        "exclude": [
            "sodimm", "so-dimm", "so dimm",   # память для ноутбуков
            "ноутбук", "ноут", "laptop",
            "компьютер", "сборк", "пк",        # готовые сборки
            "материнск",                        # материнские платы
        ],
        "min_price": 1_000,
        "max_price": 60_000,
    },
    {
        "name": "🎮 Видеокарты NVIDIA RTX",
        # Категория «Видеокарты» на Avito, фильтр по rtx
        "url": (
            "https://www.avito.ru/samarskaya_oblast?cd=1&localPriority=0&q=%D0%B2%D0%B8%D0%B4%D0%B5%D0%BE%D0%BA%D0%B0%D1%80%D1%82%D1%8B+nvidia+rtx&s=104"

        ),
        "keywords": [
            "rtx 2060", "rtx 2070", "rtx 2080",
            "rtx 3060", "rtx 3070", "rtx 3080", "rtx 3090",
            "rtx 4060", "rtx 4070", "rtx 4080", "rtx 4090",
            "rtx2060", "rtx2070", "rtx2080",
            "rtx3060", "rtx3070", "rtx3080", "rtx3090",
            "rtx4060", "rtx4070", "rtx4080", "rtx4090",
        ],
        "exclude": [
            "ноутбук", "ноут", "laptop",
            "сломан", "не работает", "на запчасти", "дефект",
        ],
        "min_price": 5_000,
        "max_price": 150_000,
    },
    {
        "name": "🎮 Видеокарты AMD RX",
        # Категория «Видеокарты», фильтр по rx
        "url": (
            "https://www.avito.ru/samarskaya_oblast?cd=1&localPriority=0&q=%D0%B2%D0%B8%D0%B4%D0%B5%D0%BE%D0%BA%D0%B0%D1%80%D1%82%D1%8B+amd+rx&s=104"

        ),
        "keywords": [
            "rx 5500", "rx 5600", "rx 5700",
            "rx 6500", "rx 6600", "rx 6650", "rx 6700", "rx 6750",
            "rx 6800", "rx 6900", "rx 6950",
            "rx 7600", "rx 7700", "rx 7800", "rx 7900",
            "rx5500", "rx5600", "rx5700",
            "rx6500", "rx6600", "rx6700", "rx6800", "rx6900",
            "rx7600", "rx7700", "rx7800", "rx7900",
        ],
        "exclude": [
            "ноутбук", "ноут", "laptop",
            "сломан", "не работает", "на запчасти", "дефект",
        ],
        "min_price": 5_000,
        "max_price": 100_000,
    },
]

# Один цикл = проход по всем задачам.
# Рекомендуется не менее 300 сек (5 минут).
CHECK_INTERVAL_SECONDS = 600

# Минимальная и максимальная задержка между переходами по задачам.
TASK_PAUSE_MIN = 60
TASK_PAUSE_MAX = 120

# Ожидания после блока IP
IP_BLOCK_WAIT = 900

HEADLESS = True 

DB_PATH = "data/seen_ads.db"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
