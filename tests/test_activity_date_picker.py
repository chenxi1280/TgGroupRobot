from backend.features.activity.date_picker import attach, fingerprint
from backend.features.activity.lottery_creation_wizard_prompts import _calendar_data
from backend.shared.ui.datetime_picker import KEY, entry_button


def test_full_participant_lottery_does_not_offer_calendar():
    data = _calendar_data({"target_chat_id": -1, "step": "draw_param", "draw_trigger": "full_participants"})
    assert KEY not in data
    dated = _calendar_data({**data, "draw_trigger": "time_deadline"})
    assert entry_button(dated[KEY]).callback_data.startswith("acal:")
    assert KEY not in _calendar_data({**dated, "step": "prize_name"})


def test_picker_fingerprint_covers_draft_and_naive_initial_is_beijing_time():
    draft = {"target_chat_id": -1, "title": "draft", "options": [{"key": "A"}]}
    data = attach(draft, back="back", initial="2099-12-31 12:34")
    assert data[KEY]["value"] == "2099-12-31 12:34"
    assert fingerprint(data) == data[KEY]["base"]
    assert fingerprint({**data, "title": "edited"}) != data[KEY]["base"]
    assert fingerprint({**data, "target_chat_id": -2}) != data[KEY]["base"]
