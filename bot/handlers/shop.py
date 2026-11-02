import asyncio
import json
import logging
import mimetypes
from html import escape
from json import JSONDecodeError, loads
from pathlib import Path

from aiohttp import ClientSession, FormData
from maxapi.enums.parse_mode import ParseMode
from maxapi.enums.upload_type import UploadType
from maxapi.types import MessageCreated
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload

from bot.config import KEYS_CATALOG_INTRO_HTML
from bot.keyboards.inline import get_product_keyboard
from bot.keyboards.reply import (
    get_back_to_menu_keyboard,
    get_shop_menu_keyboard,
)
from bot.utils import get_message_text, normalize_menu_text

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PRODUCTS_PATH = BASE_DIR / "data" / "products.json"
IMAGES_DIR = BASE_DIR / "data" / "images"


def load_products():
    with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


PRODUCTS = load_products()


def _product_caption(product: dict, *, with_link: bool = False) -> str:
    caption = f"📦 {escape(product['name'])}"
    if product.get("description"):
        caption += f"\n{escape(product['description'])}"
    if with_link and product.get("url"):
        url = escape(product["url"], quote=True)
        caption += f'\n<a href="{url}">Перейти к товару</a>'
    return caption


async def _upload_image_for_message(
    event: MessageCreated, img_path: Path
) -> AttachmentUpload:
    """Загрузка отдельной сессией: maxapi-сессия с base_url не принимает upload URL."""
    bot = event.message._ensure_bot()
    upload = await bot.get_upload_url(UploadType.IMAGE)
    content_type = mimetypes.guess_type(img_path.name)[0] or "image/*"

    form = FormData(quote_fields=False)
    form.add_field(
        name="data",
        value=img_path.read_bytes(),
        filename=img_path.name,
        content_type=content_type,
    )

    async with ClientSession() as session:
        response = await session.post(url=upload.url, data=form)
        response_text = await response.text()
        response.raise_for_status()

    token = _extract_image_token(response_text)
    return AttachmentUpload(
        type=UploadType.IMAGE,
        payload=AttachmentPayload(token=token),
    )


def _extract_image_token(upload_response: str) -> str:
    try:
        json_response = loads(upload_response)
    except JSONDecodeError as e:
        raise RuntimeError("Не удалось распарсить ответ upload-сервера MAX") from e

    photos = json_response.get("photos")
    if not isinstance(photos, dict) or not photos:
        raise RuntimeError("В ответе upload-сервера MAX отсутствует photos")

    first_photo = next(iter(photos.values()))
    if isinstance(first_photo, dict):
        token = first_photo.get("token")
        if isinstance(token, str) and token:
            return token

    raise RuntimeError("В ответе upload-сервера MAX отсутствует token изображения")


CATEGORY_URLS = {
    "Видеодомофоны": "https://domofon-sh.ru/catalog/videodomofony/",
    "Замки, доводчики, кнопки выхода, контроллеры": "https://domofon-sh.ru/catalog/zamki_dovodchiki_knopki_vykhoda_kontrollery/",
    "Блоки питания": "https://domofon-sh.ru/catalog/bloki_pitaniya_/",
    "Видеонаблюдение": "https://domofon-sh.ru/catalog/videonablyudenie/",
}


def _shop_category_url(text: str) -> str | None:
    nt = normalize_menu_text(text)
    for label, url in CATEGORY_URLS.items():
        if normalize_menu_text(label) == nt:
            return url
    return None


async def try_handle_shop(event: MessageCreated) -> bool:
    """Возвращает True, если сообщение обработано как магазин."""
    text = get_message_text(event.message) or ""

    category_url = _shop_category_url(text)
    if category_url:
        await event.message.answer(
            text=(
                "Вы покидаете бота для просмотра каталога.\n"
                f'<a href="{category_url}">Перейти в каталог на сайте</a>'
            ),
            attachments=[get_back_to_menu_keyboard()],
            format=ParseMode.HTML,
            disable_link_preview=True,
        )
        return True

    if normalize_menu_text(text) == normalize_menu_text("Купить ключ от домофона"):
        await send_products(event, "keys")
        return True

    return False


async def send_products(event: MessageCreated, category: str):
    products = PRODUCTS.get(category, [])

    if not products:
        await event.message.answer(
            text="В данной категории товары временно недоступны.",
            attachments=[get_shop_menu_keyboard()],
        )
        return

    if category == "keys":
        await event.message.answer(
            text=KEYS_CATALOG_INTRO_HTML,
            format=ParseMode.HTML,
            disable_link_preview=True,
        )

    for product in products:
        img_name = product.get("image")
        img_path = IMAGES_DIR / img_name if img_name and img_name.strip() else None
        
        try:
            if img_path and img_path.is_file():
                image_attachment = await _upload_image_for_message(event, img_path)
                await event.message.answer(
                    text=_product_caption(product, with_link=True),
                    attachments=[image_attachment],
                    format=ParseMode.HTML,
                    disable_link_preview=True,
                )
            else:
                await event.message.answer(
                    text=_product_caption(product),
                    attachments=[get_product_keyboard(product["url"])],
                    format=ParseMode.HTML,
                    disable_link_preview=True,
                )
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(
                "Не удалось отправить товар %s: %r",
                product.get("id"),
                e,
                exc_info=True,
            )
            try:
                await event.message.answer(
                    text=_product_caption(product, with_link=True),
                    format=ParseMode.HTML,
                    disable_link_preview=True,
                )
            except Exception as e2:
                logger.error("Повторная попытка отправить товар %s также не удалась: %r", product.get("id"), e2)

    await event.message.answer(
        text="Выберите категорию или вернитесь в меню:",
        attachments=[get_back_to_menu_keyboard()],
    )
