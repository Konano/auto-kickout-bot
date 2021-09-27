import configparser, logging, traceback
from telegram.ext import Updater, Filters, MessageHandler
import sys


# Config
config = configparser.ConfigParser()
config.read('config.ini')


# Log
BASIC_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(funcName)s - %(message)s'
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

logger = logging.getLogger(__name__)
logger.setLevel('INFO')
logger.addHandler(chlr)
logger.addHandler(ehlr)


# Error Callback
def error_callback(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def kickout(update, context):
    try:
        for new_user in update.effective_message.new_chat_members:
            update.effective_chat.kick_member(user_id=new_user.id)
        for new_user in update.effective_message.new_chat_members:
            update.effective_chat.unban_member(user_id=new_user.id)
        update.effective_message.delete()
    except Exception as e:
        logger.error(e)
        logger.warning(traceback.format_exc())


def remove_kickout_msg(update, context):
    try:
        update.effective_message.delete()
    except Exception as e:
        logger.error(e)
        logger.warning(traceback.format_exc())


def main():
    updater = Updater(config['BOT']['accesstoken'], use_context=True)
    dp = updater.dispatcher
    dp.add_error_handler(error_callback)

    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, kickout))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, remove_kickout_msg))
    
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
