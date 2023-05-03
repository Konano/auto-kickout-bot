import configparser, logging, traceback
from telegram.ext import Updater, Filters, MessageHandler
from telegram.error import BadRequest
import sys


# Config
config = configparser.ConfigParser()
config.read('config.ini')


# Log
BASIC_FORMAT = '%(asctime)s - %(levelname)s - %(lineno)d - %(funcName)s - %(message)s'
DATE_FORMAT = None
basic_formatter = logging.Formatter(BASIC_FORMAT, DATE_FORMAT)


class MaxFilter:
    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        if record.levelno <= self.max_level:
            return True


chlr = logging.StreamHandler(stream=sys.stdout)
chlr.setFormatter(basic_formatter)
chlr.setLevel('INFO')
chlr.addFilter(MaxFilter(logging.INFO))

ehlr = logging.StreamHandler(stream=sys.stderr)
ehlr.setFormatter(basic_formatter)
ehlr.setLevel('WARNING')

fhlr = logging.handlers.TimedRotatingFileHandler(
    'log/log', when='H', interval=1, backupCount=24*7)
fhlr.setFormatter(basic_formatter)
fhlr.setLevel('DEBUG')

logger = logging.getLogger()
logger.setLevel('NOTSET')
logger.addHandler(fhlr)

logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')
logger.addHandler(chlr)
logger.addHandler(ehlr)


# Error Callback
def error_callback(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def kickout(update, context):
    try:
        chat = update.effective_chat
        msg = update.effective_message
        if len(msg.new_chat_members) > 1:
            logger.info(f'[{chat.id}] {chat.title}: others added users')
            return
        new_user = msg.new_chat_members[0]
        if new_user.id == config['BOT'].getint('id'):
            logger.info(f'[{chat.id}] {chat.title}: bot join')
            return
        if new_user.id != msg.from_user.id:
            logger.info(f'[{chat.id}] {chat.title}: others added user')
            return
        # Comfirm join message
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: kickout new user')
        # Kickout new user
        try:
            chat.ban_member(user_id=new_user.id)
            chat.unban_member(user_id=new_user.id)
        except BadRequest as e:
            if e.message == 'Chat_admin_required' or e.message[:17] == 'Not enough rights':
                logger.info(f'FAILED: {e.message}')
                return  # Not enough rights, so do nothing
            else:
                logger.error(f'[{chat.id}] {chat.title}: {e.message}')
                logger.debug(traceback.format_exc())
        # Remove join message
        try:
            update.effective_message.delete()
        except BadRequest as e:
            if e.message[:24] == "Message can't be deleted" or e.message == 'Message to delete not found' or e.message == 'bot was kicked from the group chat':
                logger.info(f'FAILED: {e.message}')
            else:
                logger.error(f'[{chat.id}] {chat.title}: {e.message}')
                logger.debug(traceback.format_exc())

    except Exception as e:
        logger.error(e)
        logger.debug(traceback.format_exc())


def remove_kickout_msg(update, context):
    try:
        chat = update.effective_chat
        msg = update.effective_message
        if msg.from_user.id != config['BOT'].getint('id'):
            logger.info(f'[{chat.id}] {chat.title}: others remove user')
            return
        # Comfirm join message
        logger.info(f'[{chat.id}] {chat.title}: RUNNING: remove kickout message')
        # Remove kickout message
        try:
            update.effective_message.delete()
        except BadRequest as e:
            if e.message[:24] == "Message can't be deleted" or e.message == 'Message to delete not found' or e.message == 'bot was kicked from the group chat':
                logger.info(f'FAILED: {e.message}')
            else:
                logger.error(f'[{chat.id}] {chat.title}: {e.message}')
                logger.debug(traceback.format_exc())
    except Exception as e:
        logger.error(e)
        logger.debug(traceback.format_exc())


def main():
    updater = Updater(config['BOT']['accesstoken'], use_context=True)
    dp = updater.dispatcher
    dp.add_error_handler(error_callback)

    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, kickout))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, remove_kickout_msg))
    
    if config['BOT'].getboolean('webhook'):
        webhook = config._sections['WEBHOOK']
        updater.start_webhook(listen=webhook['listen'], port=webhook['port'], url_path=webhook['token'], cert=webhook['cert'], webhook_url=f'https://{webhook["url"]}:8443/{webhook["port"]}/{webhook["token"]}')
    else:
        updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
