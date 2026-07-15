import asyncio
import logging
from contextlib import suppress

from core.client import CoreClient, CoreClientError, CoreEvent

EVENT_POLLER_KEY = 'core_event_poller'


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f'Invalid event field: {key}')
    return value


async def process_event(bot, client: CoreClient, event: CoreEvent) -> None:
    payload = event.payload
    chat_id = _integer(payload, 'chat_id')
    if event.event_type == 'game_scheduled':
        message = payload.get('message')
        session_id = _integer(payload, 'session_id')
        if not isinstance(message, str):
            raise ValueError('Invalid event field: message')
        announcement = await bot.send_message(chat_id=chat_id, text=message)
        await client.set_game_announcement(session_id, announcement.id)
        await bot.pin_chat_message(
            chat_id=chat_id, message_id=announcement.id, disable_notification=True
        )
        previous = payload.get('previous_message_id')
        if isinstance(previous, int):
            await bot.unpin_chat_message(chat_id=chat_id, message_id=previous)
    elif event.event_type == 'session_started':
        number = _integer(payload, 'number')
        title = payload.get('title')
        previous = payload.get('announcement_message_id')
        if isinstance(previous, int):
            await bot.unpin_chat_message(chat_id=chat_id, message_id=previous)
        title_text = f' — {title}' if isinstance(title, str) and title else ''
        await bot.send_message(chat_id=chat_id, text=f'▶️ Сессия №{number}{title_text} началась!')
    elif event.event_type == 'session_stopped':
        number = _integer(payload, 'number')
        await bot.send_message(chat_id=chat_id, text=f'⏹️ Сессия №{number} завершена.')
    else:
        raise ValueError(f'Unknown Core event: {event.event_type}')
    await client.acknowledge_event(event.id)


async def poll_events(application) -> None:
    client: CoreClient = application.bot_data['core_client']
    while True:
        try:
            for event in await client.get_events():
                await process_event(application.bot, client, event)
        except CoreClientError:
            logging.warning('Could not poll Core events')
        except Exception:
            logging.exception('Could not process Core event')
        await asyncio.sleep(2)


async def stop_event_poller(application) -> None:
    task = application.bot_data.pop(EVENT_POLLER_KEY, None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
