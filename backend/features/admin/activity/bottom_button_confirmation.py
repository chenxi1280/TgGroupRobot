"""Confirm the exact saved bottom-button layout before destructive actions."""
from sqlalchemy import select

from backend.platform.db.schema.models.expansion_bottom_button import BottomButtonLayout
from backend.shared.ui.action_confirmation import confirm_action


async def confirm_bottom_removal(update, context, session, *, chat_id, layout_id=None):
    from backend.platform.state.edit_drafts import suspend_inputs
    await suspend_inputs(session, update.effective_user.id)
    query = select(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat_id)
    if layout_id is not None:
        query = query.where(BottomButtonLayout.id == layout_id)
    rows = list((await session.scalars(query.order_by(BottomButtonLayout.id).with_for_update())).all())
    callback = (f"btm:button:{chat_id}:delete:{layout_id}" if layout_id is not None
                else f"btm:layout:{chat_id}:clear")
    back = (f"btm:button:{chat_id}:detail:{layout_id}" if layout_id is not None
            else f"btm:layout:{chat_id}:edit")
    scope = f"按钮 #{layout_id}" if layout_id is not None else f"全部 {len(rows)} 个底部按钮"
    confirmed = await confirm_action(update, context, callback=callback, back=back,
        text=f"群：{chat_id}\n确认删除{scope}？\n若底部按钮已启用，将同步更新群内键盘。",
        version=[(row.id, row.updated_at) for row in rows])

    if not confirmed:
        await session.commit()
    return confirmed
