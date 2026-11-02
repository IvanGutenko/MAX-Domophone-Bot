from maxapi.types.attachments.buttons import MessageButton
from maxapi.types.attachments.attachment import ButtonsPayload, Attachment
from maxapi.enums.attachment import AttachmentType


def _create_reply_keyboard(buttons: list[list[str]]) -> Attachment:
    rows = []
    for row in buttons:
        row_buttons = []
        for btn_text in row:
            row_buttons.append(MessageButton(text=btn_text))
        rows.append(row_buttons)
    
    # В MAX клавиатура с кнопками, отправляющими текст — это inline_keyboard + MessageButton
    return Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=ButtonsPayload(buttons=rows),
    )


def get_consent_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Даю согласие на обработку персональных данных"]
    ])


_MAIN_MENU_ROWS: list[list[str]] = [
    ["Подать заявку на ремонт"],
    ["Как перейти на обслуживание в вашу компанию?"],
    ["Купить ключ от домофона"],
    ["Купить видеодомофон и др. оборудование"],
    ["Как установить видеодомофон?"],
    ["Как установить систему видеонаблюдения?"],
    ["Отправить фото документа"],
    ["Как оплатить абонентскую плату без комиссии"],
    ["Что делать если квитанция пришла с задолженностью?"],
    ["Как подключиться к системе умный домофон"],
    ["Как подключить дом к системе умный домофон?"],
    ["Что такое умный домофон"],
    ["Написать диспетчеру"],
    ["Написать директору"],
]

# Тексты кнопок главного меню (для выхода из режима переписки с диспетчером)
MAIN_MENU_BUTTON_TEXTS: frozenset[str] = frozenset(
    label for row in _MAIN_MENU_ROWS for label in row
)


def get_main_menu_keyboard() -> Attachment:
    return _create_reply_keyboard(_MAIN_MENU_ROWS)


# Шаг выбора способа заявки — не считать этим текстом «уход в главное меню»
REQUEST_TYPE_CHOICE_TEXTS: frozenset[str] = frozenset(
    {"Написать текстом", "Записать голосовое"}
)


def get_request_type_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Написать текстом"],
        ["Записать голосовое"],
        ["Отмена"],
        ["Назад в главное меню"],
    ])


def get_smart_intercom_menu_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Что такое умный домофон"],
        ["Как подключить дом к системе УД"],
        ["Назад в главное меню"],
    ])


def get_faq_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Как оплатить абонентскую плату без комиссии"],
        ["Что делать если квитанция пришла с задолженностью?"],
        ["Как перейти на обслуживание в вашу компанию?"],
        ["Как установить видеодомофон?"],
        ["Как установить систему видеонаблюдения?"],
        ["Назад в главное меню"],
    ])


def get_shop_menu_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Видеодомофоны"],
        ["Замки, доводчики, кнопки выхода, контроллеры"],
        ["Блоки питания"],
        ["Видеонаблюдение"],
        ["Назад в главное меню"],
    ])

def get_cancel_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Отмена"]
    ])

def get_back_to_menu_keyboard() -> Attachment:
    return _create_reply_keyboard([
        ["Назад в главное меню"]
    ])


def get_write_manager_followup_keyboard() -> Attachment:
    """После ответов УД: связь с офисом через диспетчера (без отдельной кнопки «менеджер»)."""
    return _create_reply_keyboard([
        ["Написать диспетчеру"],
        ["Назад в главное меню"],
    ])


def get_dispatcher_relay_keyboard() -> Attachment:
    """Клавиатура для диспетчера в режиме переписки с клиентом."""
    return _create_reply_keyboard([
        ["🛑 Завершить диалог"]
    ])