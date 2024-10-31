import configparser
import logging
import sys
import traceback
from datetime import datetime
from logging import Filter
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

import sentry_sdk
from sentry_sdk.integrations.logging import SentryHandler
from telegram import Chat, Message, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

# config

config = configparser.ConfigParser()
config.read('config.ini')
accessToken = config['BOT']['accesstoken']
botID = int(accessToken.split(':')[0])
webhookConfig = {
    'listen': config['WEBHOOK']['listen'],
    'port': int(config['WEBHOOK']['port']),
    'cert': config['WEBHOOK']['cert'],
    'webhook_url': config['WEBHOOK']['webhook_url'],
    'secret_token': config['WEBHOOK']['secret_token']
}


# logging

BASIC_FORMAT = '%(asctime)s - %(levelname)s - %(lineno)d - %(funcName)s - %(message)s'
DATE_FORMAT = None
basic_formatter = logging.Formatter(BASIC_FORMAT, DATE_FORMAT)


class MaxFilter(Filter):
    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        if record.levelno <= self.max_level:
            return True


class EnhancedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename, when='h', interval=1, backupCount=0, encoding=None, delay=False, utc=False):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc)

    def computeRollover(self, currentTime: int):
        """
        Work out the rollover time based on the specified time.
        """
        if self.when == 'MIDNIGHT' or self.when.startswith('W'):
            return super().computeRollover(currentTime)
        if self.when == 'D':
            # 8 hours ahead of UTC
            return currentTime - currentTime % self.interval + self.interval - 8 * 3600
        return currentTime - currentTime % self.interval + self.interval


chlr = logging.StreamHandler(stream=sys.stdout)
chlr.setFormatter(basic_formatter)
chlr.setLevel('INFO')
chlr.addFilter(MaxFilter(logging.INFO))

ehlr = logging.StreamHandler(stream=sys.stderr)
ehlr.setFormatter(basic_formatter)
ehlr.setLevel('WARNING')

fhlr = EnhancedRotatingFileHandler(
    'log/server.log', when='D', interval=1, backupCount=4*7)
fhlr.setFormatter(basic_formatter)
fhlr.setLevel('DEBUG')

logger = logging.getLogger()
logger.setLevel('INFO')
logger.addHandler(fhlr)

logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')
logger.addHandler(chlr)
logger.addHandler(ehlr)


# sentry

if 'SENTRY' in config and config['SENTRY'].get('dsn'):
    sentry_sdk.init(
        dsn=config['SENTRY']['dsn'],
        release=datetime.now().strftime('%Y-%m-%d'),
        attach_stacktrace=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        _experiments={
            # Set continuous_profiling_auto_start to True
            # to automatically start the profiler on when
            # possible.
            "continuous_profiling_auto_start": True,
        },
    )
    shlr = SentryHandler()
    shlr.setLevel('WARNING')
    logging.getLogger().addHandler(shlr)
    logging.getLogger(__name__).addHandler(shlr)


# except handler

def exception_desc(e: Exception) -> str:
    """
    Return exception description.
    """
    if str(e) != '':
        return f'{e.__class__.__module__}.{e.__class__.__name__} ({e})'
    return f'{e.__class__.__module__}.{e.__class__.__name__}'


def eprint(e: Exception, level: int = logging.WARNING, msg: Optional[str] = None, stacklevel: int = 2) -> None:
    """
    Print exception with traceback.
    """
    if not (isinstance(level, int) and level in logging._levelToName):
        level = logging.WARNING

    if msg is not None:
        logger.log(level, msg, stacklevel=stacklevel)

    exception_str = f'Exception: {exception_desc(e)}'
    logger.log(level, exception_str, stacklevel=stacklevel)

    logger.debug(traceback.format_exc(), stacklevel=stacklevel)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error for debuging."""
    logger.error("Exception while handling an update: %s", context.error)
    logger.debug(msg="The traceback of the exception:", exc_info=context.error)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    logger.debug(update_str)


async def kickout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat: Chat = update.effective_chat  # type: ignore
        msg: Message = update.effective_message  # type: ignore
        if len(msg.new_chat_members) > 1:
            logger.info(f'[{chat.id}] {chat.title}: others added users, skip')
            return
        assert msg.new_chat_members
        new_user = msg.new_chat_members[0]
        if new_user.id == botID:
            logger.info(f'[{chat.id}] {chat.title}: bot join, skip')
            return
        if msg.from_user and new_user.id != msg.from_user.id:
            logger.info(f'[{chat.id}] {chat.title}: others added user, skip')
            return

        # Comfirm join message
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: kickout new user')

        # Kickout new user
        try:
            await chat.ban_member(user_id=new_user.id)
            await chat.unban_member(user_id=new_user.id)
        except Forbidden as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')
        except TelegramError as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')

        # Remove join message
        try:
            await msg.delete()
        except (Forbidden, BadRequest) as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG)
        except TelegramError as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')

    except Exception as e:
        eprint(e)


async def remove_kickout_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat: Chat = update.effective_chat  # type: ignore
        msg: Message = update.effective_message  # type: ignore
        if msg.from_user and msg.from_user.id != botID:
            logger.info(f'[{chat.id}] {chat.title}: others remove user, skip')
            return

        # Comfirm join message
        logger.info(
            f'[{chat.id}] {chat.title}: RUNNING: remove kickout message')

        # Remove kickout message
        try:
            await msg.delete()
        except (Forbidden, BadRequest) as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG)
        except TelegramError as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')

    except Exception as e:
        eprint(e)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text(text='pong')


def main():
    """Start the bot."""
    app = Application.builder().token(accessToken).build()

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler('ping', ping))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, kickout))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER, remove_kickout_msg))

    app.run_webhook(**webhookConfig)


if __name__ == '__main__':
    main()
