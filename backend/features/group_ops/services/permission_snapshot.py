"""Read-only original permissions before opting into a full group profile."""
import datetime as dt
from backend.shared.services.module_config_service import get_module_config, update_module_config
from backend.shared.services.ops_audit_service import record_ops_event


async def capture_permissions(context, session, settings, *, user_id):
    config = get_module_config(settings, 'group_lock')
    if config.get('original_permissions') is not None:
        return config['original_permissions']
    try:
        chat = await context.bot.get_chat(settings.chat_id)
        if chat.permissions is None:
            raise ValueError('当前群未返回可读的默认权限。')
        snapshot = chat.permissions.to_dict()
    except Exception as exc:
        raise ValueError('无法读回原群权限，未启用新方案；请检查机器人权限后重试。') from exc
    await update_module_config(session, settings, module='group_lock', patch={
        'original_permissions': snapshot, 'snapshot_at': dt.datetime.now(dt.UTC).isoformat()})
    await record_ops_event(session, domain='group_lock', event_type='original_permissions_snapshot',
        chat_id=settings.chat_id, user_id=user_id, detail={'permissions': snapshot})
    return snapshot
