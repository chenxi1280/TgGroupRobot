"""Update only the four activity calendar flows, preserving curated menus."""
from update_ui_pages_20261020 import _button, _put_screen, _screen


def _calendar(payload, ident, destination):
    original = _screen(payload, ident)
    original['keyboard'] = [row for row in original.get('keyboard', [])
                            if not any(b.get('callbackData', '').startswith('acal:') for b in row)]
    original['keyboard'].insert(0, [_button('日历选择', 'acal:{token}:0:open:', 'activity_calendar_day')])
    for step, revision, action, value, following in [
        ('day', 1, 'day', '2099-12-31', 'hour'), ('hour', 2, 'hour', '23', 'minute'),
        ('minute', 3, 'minute', '0', 'confirm'), ('confirm', 4, 'apply', '', None),
    ]:
        target = 'activity_calendar_' + following if following else destination
        label = {'day': '31日', 'hour': '23:00', 'minute': '00分', 'confirm': '确认应用'}[step]
        _put_screen(payload, {'id': 'activity_calendar_' + step,
            'title': {'day': '选择日期', 'hour': '选择小时', 'minute': '选择分钟', 'confirm': '确认草稿日期'}[step],
            'message': ['北京时间 UTC+8；示意仅展示一个选项，真实日历支持翻月、跨年和全部小时/分钟。',
                        '日历确认只更新草稿或推进原步骤，不发布活动；旧按钮、权限失效或草稿变化时拒绝保存。'],
            'keyboard': [[_button(label, f'acal:{{token}}:{revision}:{action}:{value}', target, 'confirm' if not following else 'goto')],
                         [_button('手动输入', f'acal:{{token}}:{revision}:manual:', ident),
                          _button('取消并返回', f'acal:{{token}}:{revision}:cancel:', ident, 'back')]]})


def update_activities(flows):
    lottery = flows['lottery']
    _screen(lottery, 'create_input')['message'] = [
        '按向导填写名称、奖品和门槛。时间开奖的截止步骤可选日历；满员开奖仍填写人数，不显示日历。',
        '日历确认后按原玩法进入后续门槛或配置确认，最终仍需单独确认发布。']
    _calendar(lottery, 'create_input', 'create_input')
    solitaire = flows['solitaire']
    _screen(solitaire, 'create_input')['message'] = [
        '先用日历暂存截止时间，再按原格式一次性发送接龙配置。选择日期不会创建或发送活动。',
        '配置省略截止时间行时使用暂存值；显式填写该行则覆盖；留空该行清除截止时间；无效日期报错。']
    _calendar(solitaire, 'create_input', 'create_input')
    guess = flows['guess']
    _screen(guess, 'deadline_input')['message'] = ['填写未来截止时间，或使用日历；确认后返回竞猜草稿，保留标题、选项等配置，发布仍须单独确认。']
    _screen(guess, 'deadline_input')['keyboard'] = [[_button('返回草稿', 'guess:create:{chat_id}:preview', 'create', 'back')]]
    _calendar(guess, 'deadline_input', 'create')
    auction = flows['auction']
    _put_screen(auction, {'id': 'auction_date_input', 'title': '群内拍卖：截止时间',
        'message': ['群内发送“拍卖”，填写物品、标题和起拍价后进入本步。可输入未来截止时间或使用日历。',
                    '群内日历绑定创建者，其他成员不能修改；选择后仍先私聊预览、再由创建者确认发布。'], 'keyboard': []})
    _put_screen(auction, {'id': 'auction_date_confirm', 'title': '拍卖原确认步骤',
        'message': ['已保存截止时间并生成私聊预览。仍需发送“确认”发布，或“取消”退出并保留草稿。', '下方仅为文档导航；真实确认步骤使用文字指令。'], 'keyboard': [[_button('查看拍卖设置（文档导航）', 'auc:home:{chat_id}', 'home')]]})
    _calendar(auction, 'auction_date_input', 'auction_date_confirm')
    home = _screen(auction, 'home')
    home['input'] = {'type': 'text', 'prompt': '群内创建拍卖流程示意', 'placeholder': '拍卖',
        'examples': [{'label': '查看日期步骤', 'value': '拍卖', 'target': 'auction_date_input',
                      'feedback': '实际先填写物品、标题和起拍价，此处直接展示后续日期步骤。'}], 'errors': []}
    return flows


if __name__ == '__main__':
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'src/content/flows'
    flows = {name: json.loads((root / f'{name}.json').read_text()) for name in ('lottery', 'solitaire', 'guess', 'auction')}
    for name, data in update_activities(flows).items():
        (root / f'{name}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
