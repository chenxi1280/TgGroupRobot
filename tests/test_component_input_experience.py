import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.time_helper import parse_date_time_string, format_timestamp, get_interval_description
from backend.shared.time_ui import format_interval_minutes_label, build_copy_options_keyboard
from backend.shared.ui.copy import copy_button, copy_value_rows
from backend.features.automation.services.ad_rotation_formatting import format_interval_seconds_label
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.scheduled_message_mutation_helpers import _datetime_edit_spec, _set_day_end, SetFieldRequest
from backend.features.automation.ui.ads import ads_copy_time_keyboard
from backend.shared.button_layout_service import ButtonEditorContext
from backend.shared.button_layout_views import build_detail_keyboard
from backend.shared.services.base import ValidationError


@pytest.mark.parametrize('raw', ['2099-01-02 09:30', '2099-01-02 09:30:00', '２０９９/０１/０２　０９：３０', ' 2099/1/2\n09:30 '])
def test_displayed_or_pasted_datetime_round_trips(raw):
    value = parse_date_time_string(raw)
    assert value == int(dt.datetime(2099, 1, 2, 1, 30, tzinfo=dt.UTC).timestamp())
    assert format_timestamp(value) == '2099-01-02 09:30'


@pytest.mark.parametrize('raw', ['2099-02-30 09:30', '2099-01-01 24:00', '明天9点', '2099-01-01 09:30Z', '', None])
def test_datetime_rejects_invalid_or_ambiguous_input(raw):
    assert parse_date_time_string(raw) is None


@pytest.mark.parametrize(('minutes', 'expected'), [(90,'1小时30分钟'),(1500,'1天1小时'),(1501,'1天1小时1分钟'),(15,'15分钟')])
def test_interval_preserves_all_units(minutes, expected):
    assert format_interval_minutes_label(minutes) == expected
    assert format_interval_seconds_label(minutes * 60) == expected
    assert get_interval_description(minutes).replace(' ', '') == '每' + expected


def test_time_pages_have_real_native_copy_payloads():
    sample='2099-01-01 10:00'
    assert ads_copy_time_keyboard('ads:rules:-1', sample).inline_keyboard[0][0].to_dict()['copy_text']['text'] == sample
    spec = _datetime_edit_spec('start_at', -1, 'short')
    copied=spec.keyboard.inline_keyboard[0][0].to_dict()['copy_text']['text']
    assert parse_date_time_string(copied) is not None
    assert f'<code>{copied}</code>' in spec.text
    assert 'UTC+8' in spec.text and '<tg-time' not in spec.text


def test_copy_length_and_non_mutating_payloads():
    assert copy_button('复制','a'*256).to_dict() == {'text':'复制','copy_text':{'text':'a'*256}}
    with pytest.raises(ValueError):
        copy_button('复制','a'*257)
    assert copy_value_rows([('长链接','https://example.com/'+'x'*256)]) == []
    markup=build_copy_options_keyboard('back',[('复制 15','15'),('复制 30','30'),('复制 60','60')])
    assert [len(row) for row in markup.inline_keyboard] == [2,1,1]


def test_button_current_values_are_copied_verbatim():
    cell={'text':'A & B', 'url':'https://example.com/?a=1&b=2','payload':'签到'}
    markup=build_detail_keyboard(ButtonEditorContext('auto_reply',-1,1,0,0),cell)
    copies=[b.to_dict()['copy_text']['text'] for row in markup.inline_keyboard for b in row if 'copy_text' in b.to_dict()]
    assert copies == list(cell.values())
    deletion=[row for row in markup.inline_keyboard if any(b.callback_data and ':delete:' in b.callback_data for b in row)]
    assert len(deletion[0]) == 1


@pytest.mark.parametrize('minutes',[1,7,90,1500,525600])
def test_custom_repeat_minutes_valid(minutes):
    ScheduledMessageService.validate_repeat_interval(minutes)


@pytest.mark.parametrize('minutes',[0,-1,525601,1.5,True,'90'])
def test_custom_repeat_minutes_invalid(minutes):
    with pytest.raises(ValidationError):
        ScheduledMessageService.validate_repeat_interval(minutes)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'task_id':'other'},{'target_chat_id':-2},{'picker_token':'old'}])
async def test_old_or_foreign_end_selection_cannot_save(monkeypatch,change):
    data={'task_id':'current','target_chat_id':-1,'start_hour':22,'picker_token':'new',**change}
    state=SimpleNamespace(state_type='sm_edit_day_start',state_data=data)
    from backend.features.automation import scheduled_message_mutation_helpers as helpers
    monkeypatch.setattr(helpers.ConversationStateService,'get',AsyncMock(return_value=state))
    save=AsyncMock();monkeypatch.setattr(ScheduledMessageService,'update_task_day_period',save)
    update=SimpleNamespace(effective_chat=SimpleNamespace(id=42,type='private'),effective_user=SimpleNamespace(id=42),callback_query=SimpleNamespace(data='sm:set:-1:current:day_end:6:new'))
    request=SetFieldRequest(None,update,None,None,-1,'current','day_end','6')
    with pytest.raises(ValidationError):
        await _set_day_end(request)
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_input_validation_is_actionable_and_keeps_state():
    from backend.platform.telegram.private_config_handler import PrivateConfigHandler
    handler=PrivateConfigHandler()
    handler._config_handlers={'sample':AsyncMock(side_effect=ValidationError('请输入正整数分钟'))}
    session=SimpleNamespace(rollback=AsyncMock())
    message=SimpleNamespace(reply_text=AsyncMock())
    update=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_message=message)
    state=SimpleNamespace(state_type='sample',state_data={'target_chat_id':-1})
    await handler.handle(update,None,session,state=state,message_text='wrong')
    assert '请输入正整数分钟' in message.reply_text.call_args.args[0]
    assert state.state_type=='sample'
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_keeps_full_unicode_and_refuses_group(monkeypatch):
    from backend.shared import button_editor_tools as tools
    body='完整正文 & <标签>\n' * 500
    monkeypatch.setattr(tools,'ensure_message_draft',AsyncMock(return_value=SimpleNamespace(state_data={'message':{'text':body}})))
    message=SimpleNamespace(reply_document=AsyncMock(),reply_text=AsyncMock())
    request=SimpleNamespace(session=None,context=None,editor_ctx=None,action='export_body',
        update=SimpleNamespace(effective_chat=SimpleNamespace(type='private'),effective_message=message))
    await tools.export_draft(request)
    assert message.reply_document.call_args.args[0].getvalue().decode()==body
    assert message.reply_document.call_args.kwargs['filename']=='message.txt'
    message.reply_document.reset_mock()
    request.update.effective_chat.type='supergroup'
    with pytest.raises(ValidationError):
        await tools.export_draft(request)
    message.reply_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_confirmation_does_not_mutate_and_has_safe_cancel():
    from backend.shared.button_editor_tools import confirm_clear
    edit=AsyncMock()
    request=SimpleNamespace(editor_ctx=ButtonEditorContext('ads',-1,10),
        update=SimpleNamespace(callback_query=SimpleNamespace(edit_message_text=edit)))
    await confirm_clear(request)
    rows=edit.call_args.kwargs['reply_markup'].inline_keyboard
    assert [b.text for b in rows[0]]==['取消','确认清空按钮']
    assert rows[0][0].callback_data.startswith('btned:open:')
    assert rows[0][1].callback_data.startswith('btned:clear_confirm:')


@pytest.mark.asyncio
async def test_editor_input_exposes_existing_value_without_auto_saving(monkeypatch):
    from backend.shared import button_editor_tools as tools
    value='https://example.com/?a=1&b=2'
    monkeypatch.setattr(tools,'_ensure_draft',AsyncMock(return_value=[[{'text':'链接','url':value}]]))
    edit=AsyncMock()
    request=SimpleNamespace(session=None,context=None,editor_ctx=ButtonEditorContext('ads',-1,10,0,0),
        update=SimpleNamespace(callback_query=SimpleNamespace(edit_message_text=edit)))
    await tools.show_input(request,'请输入链接',field='url',return_action='detail')
    assert value in edit.call_args.args[0]
    rows=edit.call_args.kwargs['reply_markup'].inline_keyboard
    assert rows[0][0].to_dict()['copy_text']['text']==value
    assert rows[-1][0].text=='取消输入'


def test_datetime_editor_copies_current_value_separately_from_example():
    current = parse_date_time_string('2099-05-06 14:30')
    spec = _datetime_edit_spec('end_at', -1, 'short', current_timestamp=current)
    values = [b.to_dict()['copy_text']['text'] for row in spec.keyboard.inline_keyboard for b in row if 'copy_text' in b.to_dict()]
    assert values[0] == '2099-05-06 14:30'
    assert len(values) == 2
    assert '当前值：<code>2099-05-06 14:30</code>' in spec.text
