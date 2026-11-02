from enum import Enum


class RequestState(str, Enum):
    NONE = "none"
    SMART_INTERCOM_MENU = "smart_intercom_menu"
    AWAITING_TYPE = "awaiting_type"
    AWAITING_ADDRESS = "awaiting_address"
    AWAITING_DESCRIPTION = "awaiting_description"
    AWAITING_PHONE = "awaiting_phone"
    AWAITING_VOICE = "awaiting_voice"
    AWAITING_DOCUMENT_UPLOAD = "awaiting_document_upload"


class UserState:
    def __init__(self):
        self.states: dict[int, RequestState] = {}
        self.data: dict[int, dict] = {}

    def get_state(self, user_id: int) -> RequestState:
        return self.states.get(user_id, RequestState.NONE)

    def set_state(self, user_id: int, state: RequestState):
        self.states[user_id] = state

    def get_data(self, user_id: int) -> dict:
        if user_id not in self.data:
            self.data[user_id] = {}
        return self.data[user_id]

    def update_data(self, user_id: int, key: str, value):
        if user_id not in self.data:
            self.data[user_id] = {}
        self.data[user_id][key] = value

    def clear(self, user_id: int):
        self.states.pop(user_id, None)
        self.data.pop(user_id, None)


user_state = UserState()