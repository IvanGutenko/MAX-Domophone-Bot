import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Диспетчеры: список user_id в API MAX (не номер телефона).
# Формат DISPATCHERS: id1:Имя,id2:Имя (имя для кнопок; без запятых в имени). Пример: 12345:Анна,67890:Борис
# Обратная совместимость: только DISPATCHER_USER_ID=123 — один диспетчер с подписью «Диспетчер».
def _parse_dispatchers() -> list[tuple[int, str]]:
    raw = os.getenv("DISPATCHERS", "").strip()
    out: list[tuple[int, str]] = []
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                uid_s, label = part.split(":", 1)
                uid = int(uid_s.strip())
                name = (label.strip() or "Диспетчер")
            else:
                uid = int(part.strip())
                name = "Диспетчер"
            out.append((uid, name))
        return out
    legacy = int(os.getenv("DISPATCHER_USER_ID", "0") or "0")
    if legacy:
        return [(legacy, "Диспетчер")]
    return []


DISPATCHERS: list[tuple[int, str]] = _parse_dispatchers()
# Первый id для обратной совместимости; 0 если список пуст.
DISPATCHER_USER_ID: int = DISPATCHERS[0][0] if DISPATCHERS else 0

# Справочно (для настройки и документов); в коде не используется.
DISPATCHER_PHONE = os.getenv("DISPATCHER_PHONE", "").strip()

# Директор
_dir_uid = os.getenv("DIRECTOR_USER_ID", "0").strip()
DIRECTOR_USER_ID: int = int(_dir_uid) if _dir_uid else 0

DISPATCHER_USER_IDS: frozenset[int] = frozenset(uid for uid, _ in DISPATCHERS) | (frozenset([DIRECTOR_USER_ID]) if DIRECTOR_USER_ID else frozenset())

# Опционально: запасной chat_id, если у единственного диспетчера нет личного диалога с ботом (сначала шлём на user_id).
# При нескольких диспетчерах не используется.
_disp_chat = os.getenv("DISPATCHER_CHAT_ID", "").strip()
DISPATCHER_CHAT_ID: int | None = int(_disp_chat) if _disp_chat else None

PDF_URL = "https://lk.domofon-sh.ru/rules/policy.pdf"
# Личный кабинет абонента (оплата, задолженность, проверка начислений)
PERSONAL_ACCOUNT_URL = "https://lk.domofon-sh.ru/lk.php"
WEBSITE_URL = "https://domofon-sh.ru"
SERVICES_PAGE_URL = f"{WEBSITE_URL.rstrip('/')}/services/"
VIDEODOMOFON_INSTALL_URL = f"{SERVICES_PAGE_URL}ustanovka_oborudovaniya/59/"
CCTV_INSTALL_URL = f"{SERVICES_PAGE_URL}ustanovka_oborudovaniya/61/"
# Раздел «Подключение подъезда к системе Умный домофон» (для пункта «Что такое умный домофон» в боте)
SMART_INTERCOM_ABOUT_URL = (
    "https://domofon-sh.ru/company/articles/146/"
)
# «Как подключить дом к системе умный домофон» / «Как подключить дом к системе УД»
SMART_INTERCOM_CONNECT_URL = (
    "https://domofon-sh.ru/services/podklyuchenie_k_sisteme_umnyy_domofon/289/"
)
# Ссылка в ответах УД (переопределение: MANAGER_WRITE_URL в .env)
_manager_write = os.getenv("MANAGER_WRITE_URL", "").strip()
MANAGER_WRITE_URL = _manager_write or SMART_INTERCOM_CONNECT_URL

SMART_INTERCOM_DOM_CONNECT_REPLY_HTML = (
    "Для подключения к системе умный домофон необходимо обратиться в нашу компанию.\n\n"
    "Мастер выедет на место, изучит систему, определит возможно ли согласовать УД "
    "с установленным домофоном. Доложит в офис, менеджер подготовит КП и передаст Вам.\n\n"
    f'<a href="{MANAGER_WRITE_URL}">Подробнее на сайте</a>'
)

# «Как подключиться к системе умный домофон» — абонент в подъезде с УД (про дом — отдельный пункт меню).
SMART_INTERCOM_ABONENT_CONNECT_REPLY_HTML = (
    "Если в вашем подъезде уже установлен умный домофон и вы хотите подключиться к услуге, "
    "нажмите кнопку «Написать диспетчеру» ниже или позвоните в офис: 8 (496) 567-09-19. "
    "К тарифу с трубкой добавляется 10 руб.\n\n"
    f'<a href="{MANAGER_WRITE_URL}">Подробнее на сайте</a>'
)
VK_GROUP_URL = "https://vk.com/club57433313"
DOMOFON_SHOP_SITE = "https://domofon-sh.ru"

# Интернет-магазин ключей ЩДС (каталог для сценария «Купить ключ»)
DOMOFON_SHOP_KEYS_CATALOG = (
    "https://domofon-sh.ru/catalog/klyuchi_s_programmirovaniem_dlya_abonentov_shchds/"
)

KEYS_CATALOG_INTRO_HTML = (
    "Ниже — ключи с программированием для абонентов ЩДС. Выберите нужный по фото; "
    f"заказ и оплата — в <a href=\"{DOMOFON_SHOP_KEYS_CATALOG}\">интернет-магазине</a>. "
    "Нажмите «Перейти к товару» под картинкой."
)

CONSENT_BUTTON_TEXT = "Принимаю"

WELCOME_TEXT = """Вас приветствует Щёлковская домофонная служба ИП Цыбульский С.Е.
МО, г. Щелково, ул. Талсинская, д. 24А помещение 1
8 (496) 567-09-19
8 (925) 538-65-20
Время работы: Пн-Пт (9.00 - 18.00)

Электронная почта shds-02@mail.ru

ВК https://vk.com/club57433313

При выборе товара Вы будете перенаправлены на официальный сайт компании https://щелковская-домофонная-служба.рф или https://domofon-sh.ru"""

# Сообщение в чат (HTML): ссылки спрятаны в слова, без голых URL в тексте.
WELCOME_TEXT_HTML = (
    "Вас приветствует Щёлковская домофонная служба ИП Цыбульский С.Е.\n"
    "МО, г. Щелково, ул. Талсинская, д. 24А помещение 1\n"
    "8 (496) 567-09-19\n"
    "8 (925) 538-65-20\n"
    "Время работы: Пн-Пт (9.00 - 18.00)\n\n"
    "Электронная почта shds-02@mail.ru\n\n"
    f'<a href="{VK_GROUP_URL}">Мы ВКонтакте</a>\n\n'
    "При выборе товара Вы будете перенаправлены на "
    f'<a href="{WEBSITE_URL}">официальный сайт компании</a> или '
    f'<a href="{DOMOFON_SHOP_SITE}">интернет-магазин domofon-sh.ru</a>'
)

MENU_CAPTION = """В данном чате Вы можете:
• Оставить заявку на ремонт
• Приобрести ключи или оборудование
• Получить консультацию"""

# Совместимость со старым именем (простой текст без разметки)
COMPANY_INFO = WELCOME_TEXT

FULL_WELCOME_MESSAGE = f"{WELCOME_TEXT}\n\n{MENU_CAPTION}"
FULL_WELCOME_MESSAGE_HTML = f"{WELCOME_TEXT_HTML}\n\n{MENU_CAPTION}"

DEFAULT_REJECT_DEBT_TEXT = (
    "Уважаемый клиент! Заявка не может быть принята в связи с наличием задолженности "
    "по абонентской плате. Погасите задолженность и подайте заявку повторно. "
    "Телефон: 8 (496) 567-09-19"
)

# Google Sheets (опционально): путь к JSON сервисного аккаунта и ID таблицы
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "Заявки")

# Webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
