from bot.fsm.states import RequestState, user_state
from bot.handlers.start import _user_id
from bot.utils import get_message_text


async def handle_request_fsm(event):
    user_id = _user_id(event.from_user)
    text = (get_message_text(event.message) or "").strip()
    state = user_state.get_state(user_id)
    data = user_state.get_data(user_id)

    if text in ("Назад в главное меню", "Отмена"):
        user_state.clear(user_id)
        return None, "main_menu"

    if state == RequestState.AWAITING_ADDRESS:
        user_state.update_data(user_id, "address", text)
        user_state.set_state(user_id, RequestState.AWAITING_DESCRIPTION)
        return None, "ask_description"

    if state == RequestState.AWAITING_DESCRIPTION:
        user_state.update_data(user_id, "description", text)
        user_state.set_state(user_id, RequestState.AWAITING_PHONE)
        return None, "ask_phone"

    if state == RequestState.AWAITING_PHONE:
        phone = text.strip()
        if not phone:
            return None, "invalid_phone"
        user_state.update_data(user_id, "phone", phone)
        final_data = user_state.get_data(user_id)
        user_state.clear(user_id)
        return final_data, "submit_request"

    return None, None


async def start_request_text(event):
    user_id = _user_id(event.from_user)
    user_state.set_state(user_id, RequestState.AWAITING_ADDRESS)
    user_state.update_data(user_id, "request_type", "text")
    return "ask_address"


async def start_request_voice(event):
    user_id = _user_id(event.from_user)
    user_state.set_state(user_id, RequestState.AWAITING_VOICE)
    user_state.update_data(user_id, "request_type", "voice")
    return "ask_voice"


async def handle_voice_submit(event):
    from bot.utils import audio_attachment, attachment_ref_for_db

    user_id = _user_id(event.from_user)
    data = user_state.get_data(user_id)
    att = audio_attachment(event.message)
    if not att:
        return None, "no_audio"

    user_state.update_data(user_id, "audio_file_id", attachment_ref_for_db(att))
    # Исходное вложение для уведомления диспетчеру (иначе в чат уходит только URL в тексте)
    user_state.update_data(user_id, "voice_attachment", att)
    user_state.update_data(user_id, "request_type", "voice")
    user_state.set_state(user_id, RequestState.AWAITING_PHONE)
    return None, "ask_phone"
