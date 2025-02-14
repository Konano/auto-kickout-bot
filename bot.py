import configparser
import logging
import os
import sys
import traceback
from datetime import datetime
from logging import Filter
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, cast

import sentry_sdk
from sentry_sdk.integrations.logging import SentryHandler
from telegram import ChatMemberRestricted, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, TelegramError, TimedOut
from telegram.ext import (Application, ChatMemberHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# config

config = configparser.ConfigParser()
config.read('config.ini')
accessToken = config.get('bot', 'accesstoken')
botID = int(accessToken.split(':')[0])
webhookConfig = {
    'listen': config.get('webhook', 'listen'),
    'port': config.getint('webhook', 'port'),
    'secret_token': config.get('webhook', 'secret_token'),
    'webhook_url': config.get('webhook', 'webhook_url'),
    'cert': config.get('webhook', 'cert'),
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
            return currentTime - (currentTime + 8 * 3600) % self.interval + self.interval
        return currentTime - currentTime % self.interval + self.interval


chlr = logging.StreamHandler(stream=sys.stdout)
chlr.setFormatter(basic_formatter)
chlr.setLevel('INFO')
chlr.addFilter(MaxFilter(logging.INFO))

ehlr = logging.StreamHandler(stream=sys.stderr)
ehlr.setFormatter(basic_formatter)
ehlr.setLevel('WARNING')

os.makedirs('log', exist_ok=True)
fhlr = EnhancedRotatingFileHandler('log/server.log', when='D', interval=1, backupCount=28)
fhlr.setFormatter(basic_formatter)
fhlr.setLevel('DEBUG')

# 日志默认设置
logger = logging.getLogger()
logger.setLevel('INFO')
logger.addHandler(fhlr)

# 模组调用: telegram
logger = logging.getLogger('telegram')
logger.setLevel('DEBUG')

# # 模组调用: apscheduler
# logger = logging.getLogger('apscheduler')
# logger.setLevel('DEBUG')

# 自行调用
logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')
logger.addHandler(chlr)
logger.addHandler(ehlr)


# sentry

if config.has_option('sentry', 'dsn'):
    sentry_sdk.init(
        dsn=config.get('sentry', 'dsn'),
        release=datetime.now().strftime('%Y-%m-%d'),
        attach_stacktrace=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # _experiments={
        #     # Set continuous_profiling_auto_start to True
        #     # to automatically start the profiler on when
        #     # possible.
        #     "continuous_profiling_auto_start": True,
        # },
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


def eprint(e: Exception, level: int = logging.WARNING, msg: Optional[str] = None, stacklevel: int = 2, print_trace=True) -> None:
    """
    Print exception with traceback.
    """
    if not (isinstance(level, int) and level in logging._levelToName):
        level = logging.WARNING

    if msg is not None:
        logger.log(level, msg, stacklevel=stacklevel)

    exception_str = f'Exception: {exception_desc(e)}'
    logger.log(level, exception_str, stacklevel=stacklevel)

    if print_trace:
        logger.debug(traceback.format_exc(), stacklevel=stacklevel)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error for debuging."""
    logger.error("Exception while handling an update: %s", context.error)
    logger.debug(msg="The traceback of the exception:", exc_info=context.error)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    logger.debug(update_str)


async def remove_join_left_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    chat = update.message.chat

    if len(update.message.new_chat_members):
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: remove join message')
    elif update.message.left_chat_member is not None:
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: remove left message')
    else:
        raise NotImplementedError

    # Remove join or left message
    try:
        await update.message.delete()
    except (Forbidden, BadRequest) as e:
        eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG)
    except TimedOut as e:
        eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG, print_trace=False)
    except TelegramError as e:
        eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')


async def member_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.chat_member is None or update.chat_member.from_user.id == botID:
        return
    chat = update.chat_member.chat
    from_user_id = update.chat_member.from_user.id
    old_member = update.chat_member.old_chat_member
    new_member = update.chat_member.new_chat_member
    user_id = new_member.user.id
    old_status = old_member.status
    new_status = new_member.status
    logger.info(f'[{chat.id}] {chat.title}: STATUS_CHANGE: ({from_user_id}) ({user_id}) {old_status} -> {new_status}')
    
    if from_user_id != user_id:
        return

    not_previously_in_group = False
    if old_status in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT):
        not_previously_in_group = True
    if old_status == ChatMemberStatus.RESTRICTED and not cast(ChatMemberRestricted, old_member).is_member:
        not_previously_in_group = True

    now_in_group = False
    if new_status == ChatMemberStatus.MEMBER:
        now_in_group = True
    if new_status == ChatMemberStatus.RESTRICTED and cast(ChatMemberRestricted, new_member).is_member:
        now_in_group = True

    if not_previously_in_group and now_in_group:
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: kickout new user')
        try:
            await chat.ban_member(user_id)
            await chat.unban_member(user_id)
        except (Forbidden, BadRequest) as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG)
        except TimedOut as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}', level=logging.DEBUG, print_trace=False)
        except TelegramError as e:
            eprint(e, msg=f'[{chat.id}] {chat.title}: {e.message}')


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text(text='pong')


def main():
    """Start the bot."""
    app = Application.builder().token(accessToken).build()

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler('ping', ping))

    app.add_handler(ChatMemberHandler(member_status_change, chat_member_types=0))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        remove_join_left_msg))

    app.run_webhook(**webhookConfig, allowed_updates=['message', 'chat_member'])


if __name__ == '__main__':
    main()
