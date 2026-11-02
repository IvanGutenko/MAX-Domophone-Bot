import csv
import logging
from datetime import datetime
from pathlib import Path

from bot.config import (
    GOOGLE_SHEETS_CREDENTIALS_JSON,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    GOOGLE_SHEETS_WORKSHEET_NAME,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CSV_PATH = BASE_DIR / "requests.csv"


async def save_to_cloud(data: dict) -> str:
    """
    Сохранение заявки: Google Sheets (если настроено), иначе CSV для импорта.
    """
    await _append_csv(data)
    ok = await _try_append_google_sheet(data)
    if ok:
        return "google_sheet"
    return str(CSV_PATH)


async def _append_csv(data: dict) -> None:
    file_exists = CSV_PATH.exists()
    fieldnames = [
        "datetime",
        "user_id",
        "username",
        "request_type",
        "city",
        "street",
        "house_apartment",
        "phone",
        "description",
        "audio_file_id",
    ]
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": data.get("user_id", ""),
                "username": data.get("username", ""),
                "request_type": data.get("request_type", ""),
                "city": data.get("city", ""),
                "street": data.get("street", ""),
                "house_apartment": data.get("house", ""),
                "phone": data.get("phone", ""),
                "description": data.get("description", ""),
                "audio_file_id": data.get("audio_file_id", ""),
            }
        )


async def _try_append_google_sheet(data: dict) -> bool:
    if not GOOGLE_SHEETS_CREDENTIALS_JSON or not GOOGLE_SHEETS_SPREADSHEET_ID:
        return False
    cred_path = Path(GOOGLE_SHEETS_CREDENTIALS_JSON)
    if not cred_path.is_absolute():
        cred_path = BASE_DIR / cred_path
    if not cred_path.is_file():
        logger.warning("Google Sheets: файл ключа не найден: %s", cred_path)
        return False
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(str(cred_path), scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
        try:
            ws = sh.worksheet(GOOGLE_SHEETS_WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(
                title=GOOGLE_SHEETS_WORKSHEET_NAME, rows=1000, cols=11
            )
            ws.append_row(
                [
                    "Дата и время",
                    "user_id",
                    "Имя/username",
                    "Тип",
                    "Город",
                    "Улица",
                    "Дом/кв",
                    "Телефон",
                    "Проблема",
                    "Аудио",
                ]
            )

        ws.append_row(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                str(data.get("user_id", "")),
                str(data.get("username", "")),
                str(data.get("request_type", "")),
                str(data.get("city", "")),
                str(data.get("street", "")),
                str(data.get("house", "")),
                str(data.get("phone", "")),
                str(data.get("description", "")),
                str(data.get("audio_file_id", "")),
            ]
        )
        return True
    except Exception as e:
        logger.exception("Google Sheets: ошибка записи: %s", e)
        return False


async def save_audio_file(audio_data: bytes, user_id: int) -> str:
    audio_dir = BASE_DIR / "audio"
    audio_dir.mkdir(exist_ok=True)
    filename = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
    filepath = audio_dir / filename
    with open(filepath, "wb") as f:
        f.write(audio_data)
    return str(filepath)
