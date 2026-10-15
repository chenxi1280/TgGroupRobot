"""Compatibility adapter to the shared durable alliance command path."""
from backend.features.group_ops.services.alliance_runtime import process_command


async def process_alliance_mute(context, db, *, chat, user, message):
    return await process_command(context,db,chat=chat,user=user,message=message,action='mute')
