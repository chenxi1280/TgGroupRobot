"""Copy selected configuration only; runtime ownership stays with the target."""
from copy import deepcopy
from sqlalchemy import delete, select
from backend.platform.db.schema.models.points import PointsLevel, PointsLevelSetting
from backend.shared.services.base import ValidationError
from backend.shared.services.module_config_service import get_module_config, update_module_config

LEVEL_FIELDS = ('level_no','level_name','point_threshold','enabled','allow_text','allow_audio','allow_photo',
                'allow_video','allow_sticker','allow_document','allow_mention')


async def copy_module_configuration(session, *, source, target, modules, context=None, actor_user_id=None):
    if 'night_mode' in modules or 'group_lock' in modules:
        await _copy_lock_config(session, source=source, target=target, context=context, actor_user_id=actor_user_id)
    for selected, module in (('points','sign_feedback'),('verification','verification')):
        if selected in modules:
            await update_module_config(session, target, module=module,
                patch=deepcopy(get_module_config(source,module)), replace=True)
    if 'points_level' in modules:
        await _copy_levels(session, source=source, target=target)


async def _copy_lock_config(session, *, source, target, context, actor_user_id):
    config=get_module_config(source,'group_lock')
    original=get_module_config(target,'group_lock').get('original_permissions')
    if config.get('profiles') and original is None:
        if context is None or actor_user_id is None:
            raise ValidationError('复制完整权限前须读取目标群原权限，请从管理页操作。')
        from backend.features.group_ops.services.permission_snapshot import capture_permissions
        try:
            await capture_permissions(context, session, target, user_id=actor_user_id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    await update_module_config(session,target,module='group_lock',patch={
        'profiles':deepcopy(config.get('profiles',{})), 'notices':deepcopy(config.get('notices',{}))})


async def _copy_levels(session, *, source, target):
    levels=list((await session.scalars(select(PointsLevel).where(PointsLevel.chat_id==source.chat_id)
        .order_by(PointsLevel.level_no))).all())
    setting=await session.get(PointsLevelSetting,source.chat_id)
    await session.execute(delete(PointsLevel).where(PointsLevel.chat_id==target.chat_id))
    target_setting=await session.get(PointsLevelSetting,target.chat_id,with_for_update=True)
    if target_setting is None:
        target_setting=PointsLevelSetting(chat_id=target.chat_id)
        session.add(target_setting)
    target_setting.enabled=bool(setting and setting.enabled)
    target_setting.exclude_teacher_enabled=bool(setting and setting.exclude_teacher_enabled)
    mapping={}
    for level in levels:
        copied=PointsLevel(chat_id=target.chat_id,**{key:getattr(level,key) for key in LEVEL_FIELDS})
        session.add(copied)
        await session.flush()
        mapping[str(level.id)]=str(copied.id)
    config=deepcopy(get_module_config(source,'level_tags'))
    config['levels']={mapping[key]:value for key,value in config.get('levels',{}).items() if key in mapping}
    await update_module_config(session,target,module='level_tags',patch=config,replace=True)
