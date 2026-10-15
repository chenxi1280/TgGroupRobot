"""Compact layouts preserve actions, semantic groups and authored keyboards."""
from itertools import product
from types import SimpleNamespace

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup

from backend.shared.ui.admin_keyboard import admin_keyboard
from backend.features.admin.ui.admin_verification_keyboards import verification_mode_menu
from backend.features.moderation.ui.auto_reply import auto_reply_menu_keyboard
from backend.features.moderation.ui.banned_word import banned_word_menu_keyboard


def flatten(rows):
    return [button.to_dict() for row in rows for button in row]


def button(label):
    return Button(label, callback_data=f'config:-100123:{label}')


def test_compaction_preserves_data_order_groups_and_is_idempotent():
    options = [button('文本'), button('封面'), button('时间')]
    label = Button('状态：', callback_data='_noop')
    toggle = [label, button('启用'), button('停用')]
    long_name = button('这是一个需要保留整行显示的非常长的名称')
    delete = button('删除配置')
    confirm = [button('确认删除'), button('取消')]
    url = Button('帮助', url='https://example.com')
    cancel = button('取消输入')
    nav = [[button('刷新')], [button('返回')]]
    rows = [[options[0]], [options[1]], [options[2]], toggle, [long_name],
            [delete], confirm, [url], [cancel], *nav]
    before = InlineKeyboardMarkup(rows).to_dict()
    actual = admin_keyboard(iter(rows))
    assert actual.inline_keyboard[0] == tuple(options[:2])
    assert actual.inline_keyboard[1] == (options[2],)
    assert actual.inline_keyboard[2] == tuple(toggle)
    assert all((b,) in actual.inline_keyboard for b in (long_name, delete, url, cancel))
    assert actual.inline_keyboard[-1] == (nav[0][0], nav[1][0])
    assert tuple(confirm) in actual.inline_keyboard
    assert flatten(actual.inline_keyboard) == flatten(rows)
    assert InlineKeyboardMarkup(rows).to_dict() == before
    assert admin_keyboard(actual.inline_keyboard) == actual


def test_mixed_unicode_and_odd_option_runs_do_not_cross_row_boundaries():
    # Include empty rows, long titles, noop headings and explicit numeric grids.
    samples = [[button('短')], [button('另一个')], [button('中' * 20)],
               [Button('说明', callback_data='adm:noop:-100123')], [],
               [button(str(i)) for i in range(4)]]
    for indexes in product(range(len(samples)), repeat=3):
        rows = [samples[i] for i in indexes]
        result = admin_keyboard(rows)
        assert flatten(result.inline_keyboard) == flatten(rows)
        assert admin_keyboard(result.inline_keyboard) == result
        for row in rows:
            if len(row) != 1:
                assert tuple(row) in result.inline_keyboard


def test_short_management_entry_options_are_paired_and_scoped():
    for markup in (auto_reply_menu_keyboard(-100123), banned_word_menu_keyboard(-100123),
                   verification_mode_menu('button', -100123)):
        assert len(markup.inline_keyboard[0]) == 2
        assert len(markup.inline_keyboard[-1]) == 1
        assert '返回' in markup.inline_keyboard[-1][0].text
        assert all('-100123' in b.callback_data for row in markup.inline_keyboard for b in row)


def test_published_button_grid_is_not_compacted():
    from backend.features.automation.services.ad_rotation_formatting import build_item_markup
    grid = [[{'text':'链接一','url':'https://example.com/one'}],
            [{'text':'链接二','url':'https://example.com/two'}]]
    markup = build_item_markup(SimpleNamespace(buttons=grid))
    assert [[b.text for b in row] for row in markup.inline_keyboard] == [['链接一'], ['链接二']]


def test_existing_profile_defaults_and_explicit_new_permissions_are_preserved():
    from backend.features.group_ops.services.group_permission_profiles import profile_permissions
    for values, expected in [
        ({'can_send_messages': True, 'can_pin_messages': True}, (True, True)),
        ({'can_send_messages': False, 'can_pin_messages': False}, (False, False)),
        ({'can_send_messages': True, 'can_pin_messages': True,
          'can_react_to_messages': False, 'can_edit_tag': False}, (False, False)),
    ]:
        settings = SimpleNamespace(module_config={'group_lock': {'profiles': {'open': values}}})
        actual = profile_permissions(settings, closed=False).to_dict()
        assert (actual['can_react_to_messages'], actual['can_edit_tag']) == expected
