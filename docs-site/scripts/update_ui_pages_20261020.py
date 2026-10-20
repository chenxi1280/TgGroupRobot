"""Targeted UI updates; preserve all unrelated curated flow content."""
from copy import deepcopy


def _button(label, callback, target, action='goto'):
    return {'label': label, 'callbackData': callback, 'action': action,
            'target': target, 'feedback': '打开对应页面；本示意不执行真实操作。'}


def _screen(payload, name):
    return next(s for s in payload['screens'] if s['id'] == name)


def _put_screen(payload, value):
    payload['screens'] = [s for s in payload['screens'] if s['id'] != value['id']] + [value]


def update_points(payload):
    home = _screen(payload, 'home')
    home['keyboard'] = [
        [_button('状态', 'pts:home:{chat_id}', 'home', 'toast'),
         _button('启用', 'pts:toggle:all_enabled:{chat_id}:1', 'home', 'toast'),
         _button('关闭', 'pts:toggle:all_enabled:{chat_id}:0', 'home', 'toast')],
        [_button('签到规则', 'pts:rule:checkin:{chat_id}', 'sign_rule'), _button('发言规则', 'pts:rule:speech:{chat_id}', 'speech_rule')],
        [_button('邀请规则', 'pts:rule:invite:{chat_id}', 'invite_rule'), _button('展示与排行', 'pts:home:{chat_id}:display', 'display_section')],
        [_button('积分管理', 'pts:home:{chat_id}:manage', 'manage_section'), _button('积分抽奖', 'adm:menu:lottery:{chat_id}', 'result')],
        [_button('返回', 'adm:menu:category_growth:{chat_id}', 'entry', 'back')],
    ]
    back = [_button('返回主积分', 'pts:home:{chat_id}:main', 'home', 'back')]
    display = []
    for label, field, view in [('展示规则', 'points_display_rule_enabled', 'display_rules'), ('发言总排行', 'points_speech_rank_enabled', 'speech_rank'), ('个人发言量', 'points_personal_speech_enabled', 'personal_speech')]:
        display.append([_button(label, f'pts:view:{view}:{{chat_id}}', 'result'),
                        _button('开启', f'pts:toggle:{field}:{{chat_id}}:1', 'display_section', 'toast'),
                        _button('关闭', f'pts:toggle:{field}:{{chat_id}}:0', 'display_section', 'toast')])
    _put_screen(payload, {'id':'display_section', 'title':'展示与排行', 'message':['当前状态与完整规则显示在正文。'], 'keyboard':display+[back]})
    ops = [('转让积分','transfer'),('积分查询词','points_alias'),('排行查询词','points_rank_alias'),('增加积分','admin_add'),('扣除积分','admin_deduct')]
    buttons = [_button(label, f'pts:edit:{field}:{{chat_id}}', 'text_input' if 'alias' in field else 'points_input', 'input') for label, field in ops]
    buttons += [_button('额外规则','pts:view:extra_rules:{chat_id}','extra_rules'), _button('导出操作日志','pts:view:export_logs:{chat_id}','result')]
    rows = [buttons[i:i+2] for i in range(0,len(buttons),2)]
    rows += [[_button('清空积分','pts:edit:clear_points:{chat_id}','points_input','input')],back]
    _put_screen(payload, {'id':'manage_section','title':'积分管理','message':['清空仍需输入 CONFIRM。退出输入保留已保存值。'],'keyboard':rows})


def update_quick_publish(payload):
    home = _screen(payload,'home')
    items = {b['callbackData']: b for row in home['keyboard'] for b in row}
    home['keyboard'] = [[items['qpub:input:{chat_id}:text'],items['qpub:input:{chat_id}:media']], [items['qpub:input:{chat_id}:buttons']]]
    for action, label in [('clear','清空草稿'), ('send','立即发送')]:
        target=f'{action}_confirm'
        home['keyboard'].append([_button(label,f'qpub:{action}:{{chat_id}}',target)])
        _put_screen(payload, {'id':target,'title':f'确认{label}', 'message':['核对目标群与草稿；仅确认后执行。令牌过期或草稿变化时拒绝。'], 'keyboard':[[
            _button('取消','qpub:home:{chat_id}','home','back'),
            _button('确认执行',f'qpub:{action}:{{chat_id}}:ok:{{token}}','result','confirm')]]})
    home['keyboard'].append([_button('返回','adm:menu:category_messages:{chat_id}','entry','back')])


NIGHT_LAYOUTS = {'home': [[('🧹 消息拦截', 'adm:menu:night:{chat_id}'), ('启动', 'adm:night:{chat_id}:set:enabled:1'), ('✅ 关闭', 'adm:night:{chat_id}:set:enabled:0')], [('管控开始', 'adm:night:{chat_id}:input:start'), ('管控结束', 'adm:night:{chat_id}:input:end')], [('🔒 全员禁言模式', 'adm:menu:night:{chat_id}'), ('启动', 'adm:night:{chat_id}:set:lock_schedule:1'), ('✅ 关闭', 'adm:night:{chat_id}:set:lock_schedule:0')], [('🗣 口令开关群', 'adm:menu:night:{chat_id}'), ('启动', 'adm:night:{chat_id}:set:lock_phrase:1'), ('✅ 关闭', 'adm:night:{chat_id}:set:lock_phrase:0')], [('口令设置', 'adm:night:{chat_id}:section:phrases'), ('例外与提示', 'adm:night:{chat_id}:section:policy')], [('通知设置', 'adm:night:{chat_id}:section:notices'), ('权限方案', 'adm:night:{chat_id}:section:permissions')], [('执行/恢复记录', 'eff:{chat_id}:group_lock:list')], [('🔙 返回', 'adm:menu:category_safety:{chat_id}')]], 'phrases': [[('开群口令', 'adm:night:{chat_id}:input:open_phrase'), ('关群口令', 'adm:night:{chat_id}:input:close_phrase')], [('返回夜间管控', 'adm:night:{chat_id}:section:home')]], 'policy': [[('🛡️ 管理员豁免', 'adm:menu:night:{chat_id}'), ('✅ 启动', 'adm:night:{chat_id}:set:exempt_admin:1'), ('关闭', 'adm:night:{chat_id}:set:exempt_admin:0')], [('白名单', 'adm:night:{chat_id}:input:whitelist')], [('🗑 删除触发消息', 'adm:menu:night:{chat_id}'), ('✅ 启动', 'adm:night:{chat_id}:set:delete_message:1'), ('关闭', 'adm:night:{chat_id}:set:delete_message:0')], [('💬 提示消息', 'adm:menu:night:{chat_id}'), ('✅ 启动', 'adm:night:{chat_id}:set:warn_enabled:1'), ('关闭', 'adm:night:{chat_id}:set:warn_enabled:0')], [('✏️ 提示文案', 'adm:night:{chat_id}:input:warn_text'), ('提示保留时间', 'adm:night:{chat_id}:cycle:warn_delete')], [('返回夜间管控', 'adm:night:{chat_id}:section:home')]], 'notices': [[('🧹 触发口令 · 保留', 'adm:night:{chat_id}:notice:delete')], [('开群通知', 'gnote:{chat_id}:open:view'), ('关群通知', 'gnote:{chat_id}:closed:view')], [('返回夜间管控', 'adm:night:{chat_id}:section:home')]], 'permissions': [[('开群权限', 'gperm:{chat_id}:open:view'), ('关群权限', 'gperm:{chat_id}:closed:view')], [('返回夜间管控', 'adm:night:{chat_id}:section:home')]]}


def update_night(payload):
    old = {b['callbackData']: b for screen in payload['screens'] for row in screen.get('keyboard',[]) for b in row}
    for section, rows in NIGHT_LAYOUTS.items():
        ident = 'home' if section == 'home' else 'night_'+section
        result = []
        for row in rows:
            buttons = []
            for label, callback in row:
                if ':section:' in callback:
                    name = callback.rsplit(':',1)[-1]
                    buttons.append(_button(label,callback,'home' if name == 'home' else 'night_'+name))
                elif callback in old:
                    button = deepcopy(old[callback]); button['label'] = label
                    if button['action'] in {'toast','toggle'}:
                        button['target'] = ident
                    buttons.append(button)
                else:
                    buttons.append(_button(label,callback,'result'))
            result.append(buttons)
        if section == 'home':
            _screen(payload,'home')['keyboard'] = result
        else:
            _put_screen(payload, {'id':ident,'title':{'phrases':'开关群口令','policy':'例外与提示','notices':'通知设置','permissions':'权限方案'}[section],
                'message':['原有功能按用途分组；返回保留当前群，退出输入不会修改原值。'], 'keyboard':result})
    for screen in payload['screens']:
        section = 'phrases' if screen['id'] in {'open_phrase_input','close_phrase_input'} else 'policy' if screen['id'] in {'whitelist_input','warn_input'} else None
        if section:
            for row in screen.get('keyboard',[]):
                for button in row:
                    if button['action'] == 'back':
                        button.update(callbackData=f'adm:night:{{chat_id}}:section:{section}',target='night_'+section)


def update_calendar(payload, input_ids):
    for ident in input_ids:
        original = _screen(payload, ident)
        back = next((b for row in original['keyboard'] for b in row if b['action']=='back'), None)
        if not back:
            continue
        prefix = 'calendar_'+ident
        original['keyboard'] = [[_button('日历选择', 'dtp:{token}:0:open:',prefix+'_day')], [deepcopy(back)]]
        original['message'] = list(dict.fromkeys(original['message'] + ['可复制完整时间示例，或用原生日期/小时/分钟选择器；选择后确认才保存。']))
        manual = _button('手动输入','dtp:{token}:1:manual:',ident)
        cancel = _button('取消并返回','dtp:{token}:1:cancel:',back['target'],'back')
        _put_screen(payload, {'id':prefix+'_day','title':'日历 · 北京时间 UTC+8', 'message':['此处展示选择步骤；真实日历按周一到周日七列排列，支持翻月、跨年与闰日。'], 'keyboard':[
            [_button('上个月','dtp:{token}:1:month:-1',prefix+'_day','toast'),_button('下个月','dtp:{token}:1:month:1',prefix+'_day','toast')],
            [_button('20日','dtp:{token}:1:day:2026-10-20',prefix+'_hour')], [manual,cancel]]})
        _put_screen(payload, {'id':prefix+'_hour','title':'选择小时', 'message':['真实页面覆盖 00—23 点，此处展示一个选项。'], 'keyboard':[
            [_button('23:00','dtp:{token}:2:hour:23',prefix+'_minute')], [manual,cancel]]})
        _put_screen(payload, {'id':prefix+'_minute','title':'选择分钟', 'message':['真实页面分三页覆盖全部 60 分钟；此处展示 00 分。'], 'keyboard':[
            [_button('00分','dtp:{token}:3:minute:0',prefix+'_confirm')], [manual,cancel]]})
        _put_screen(payload, {'id':prefix+'_confirm','title':'确认日期与时间','message':['当前选择：2026-10-20 23:00。真实按钮可原样复制所选时间。','确认只保存原群/原对象/原字段；不启用任务或发送群消息。'], 'keyboard':[
            [_button('确认应用','dtp:{token}:4:apply:',back['target'],'confirm')], [manual,cancel]]})


    for screen in payload['screens']:
        if not screen['id'].startswith('calendar_'):
            continue
        revision = {'day':1,'hour':2,'minute':3,'confirm':4}[screen['id'].rsplit('_',1)[-1]]
        screen['keyboard'] = deepcopy(screen['keyboard'])
        for row in screen['keyboard']:
            for button in row:
                if ':manual:' in button['callbackData'] or ':cancel:' in button['callbackData']:
                    parts = button['callbackData'].split(':'); parts[2] = str(revision)
                    button['callbackData'] = ':'.join(parts)


def apply_updates(flows):
    for slug in ('points-center','sign-points','message-points','invite-points','points-tasks'):
        if slug in flows and any(s['id']=='sign_rule' for s in flows[slug]['screens']):
            update_points(flows[slug])
    if 'scheduled-message' in flows:
        update_calendar(flows['scheduled-message'], ('start_input','end_input'))
    if 'rotating-ads' in flows:
        update_calendar(flows['rotating-ads'], ('rule_time_input','item_start_input','item_end_input'))
    if 'night-mode' in flows:
        update_night(flows['night-mode'])
    if 'quick-publish' in flows:
        update_quick_publish(flows['quick-publish'])
    return flows


if __name__ == '__main__':
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'src/content/flows'
    flows={p.stem: json.loads(p.read_text()) for p in root.glob('*.json')}
    before=deepcopy(flows)
    apply_updates(flows)
    for slug, payload in flows.items():
        if payload != before[slug]:
            (root/f'{slug}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
