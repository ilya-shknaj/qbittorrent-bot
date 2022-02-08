import logging
import os
import re
from html import escape
import hashlib

# noinspection PyPackageRequirements
from typing import Optional

from telegram import Update, BotCommand, ParseMode, User, Bot
from telegram.ext import Filters, MessageHandler, CallbackContext, CallbackQueryHandler
import bencoding

from bot.qbtinstance import qb
from bot.updater import updater
from utils import u
from utils import kb
from utils import Permissions
from config import config

logger = logging.getLogger(__name__)

DOWNLOAD_FOLDERS_PRESETS = ["Downloads", "Series", "Movies"]

last_torrent_url = None

def notify_addition(current_chat_id: int, bot: Bot, user: User, torrent_description: str):
    if not config.notifications.added_torrents:
        return

    target_chat_id = config.notifications.added_torrents
    if target_chat_id != current_chat_id:  # do not send if the target chat is the current chat
        return

    text = f"User {escape(user.full_name)} [<code>{user.id}</code>] added a torrent: " \
           f"<code>{escape(torrent_description)}</code>"
    bot.send_message(
        target_chat_id,
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


def get_qbt_request_kwargs(download_folder) -> dict:
    kwargs = dict()
    if config.qbittorrent.added_torrents_tag:
        # string with tags separated by ",", but since it's only one tehre's no need to join
        kwargs["tags"] = config.qbittorrent.added_torrents_tag
    if config.qbittorrent.added_torrents_category:
        kwargs["category"] = config.qbittorrent.added_torrents_category
    if download_folder is not None:
        kwargs["savepath"] = qb.get_default_save_path() + "../" + download_folder

    return kwargs


@u.check_permissions(required_permission=Permissions.WRITE)
@u.failwithmessage
def add_from_magnet(update: Update, context: CallbackContext):
    logger.info('magnet url from %s', update.effective_user.first_name)

    global last_torrent_url
    last_torrent_url = update.message.text

    ask_download_folder(update, 'magnet')

@u.check_permissions(required_permission=Permissions.WRITE)
@u.failwithmessage
def add_from_file(update: Update, context: CallbackContext):
    logger.info('application/x-bittorrent document from %s', update.effective_user.first_name)

    document = update.message.document
    if document.mime_type != "application/x-bittorrent" and not document.file_name.lower().endswith(".torrent"):
        logger.info('invalid document from %s (mime type: %s; file name: %s)', update.effective_user.full_name,
                    document.mime_type, document.file_name)

        update.message.reply_markdown(
            'Please send me a valid torrent file (`.torrent` extension or `application/x-bittorrent` mime type)',
            quote=True
        )
        return

    file_id = document.file_id
    torrent_file = context.bot.get_file(file_id)

    file_path = './downloads/{}'.format(document.file_name)
    torrent_file.download(file_path)

    kwargs = get_qbt_request_kwargs(None)

    with open(file_path, 'rb') as f:
        # https://stackoverflow.com/a/46270711
        decoded_dict = bencoding.bdecode(f.read())
        torrent_hash = hashlib.sha1(bencoding.bencode(decoded_dict[b"info"])).hexdigest()

        f.seek(0)

        # this method always returns an empty json:
        # https://python-qbittorrent.readthedocs.io/en/latest/modules/api.html#qbittorrent.client.Client.download_from_file
        qb.download_from_file(f, **kwargs)

    update.message.reply_text(
        'Torrent added',
        quote=True,
        reply_markup=kb.short_markup(torrent_hash)
    )

    os.remove(file_path)

    notify_addition(update.effective_chat.id, context.bot, update.effective_user, document.file_name or "[unknown file name]")


@u.check_permissions(required_permission=Permissions.WRITE)
@u.failwithmessage
def add_from_url(update: Update, context: CallbackContext):
    logger.info('url from %s', update.effective_user.first_name)

    global last_torrent_url
    last_torrent_url = update.message.text

    ask_download_folder(update, 'link')

@u.check_permissions(required_permission=Permissions.READ)
@u.failwithmessage
def ask_download_folder(update: Update, download_method):
    logger.info('ask download folder', update.message.from_user.first_name)

    # if re.search(r'[^^(?!downloadFoler).*$]', update.message.text, re.I):
    logger.info('showing download folders presets')
    reply_markup = kb.download_folders(DOWNLOAD_FOLDERS_PRESETS, download_method)
    update.message.reply_markdown('Select download folder', reply_markup=reply_markup)


@u.check_permissions(required_permission=Permissions.WRITE)
@u.failwithmessage
def start_download_to_folder_callback(update: Update, context: CallbackContext):
    download_folder = context.match[2]
    download_method = context.match[3]

    logger.info('start download to folder ', download_folder)
    logger.info('download method ', download_method)
    global last_torrent_url
    kwargs = get_qbt_request_kwargs(download_folder)

    if download_method == "link":
        qb.download_from_link(last_torrent_url, **kwargs)
        # always returns an empty json:
        # https://python-qbittorrent.readthedocs.io/en/latest/modules/api.html#qbittorrent.client.Client.download_from_link

        update.callback_query.answer('Torrent url added')

        notify_addition(update.effective_chat.id, context.bot, update.effective_user, last_torrent_url)
    if download_method=="magnet":
        qb.download_from_link(last_torrent_url, **kwargs)
        # always returns an empty json:
        # https://python-qbittorrent.readthedocs.io/en/latest/modules/api.html#qbittorrent.client.Client.download_from_link

        torrent_hash = u.hash_from_magnet(last_torrent_url)
        logger.info('torrent hash from regex: %s', torrent_hash)

        update.callback_query.answer('Magnet added')

        notify_addition(update.effective_chat.id, context.bot, update.effective_user, torrent_hash)
    last_torrent_url = None

updater.add_handler(MessageHandler(Filters.document, add_from_file))
updater.add_handler(MessageHandler(Filters.text & Filters.regex(r'^magnet:\?.*'), add_from_magnet))
updater.add_handler(MessageHandler(Filters.text & Filters.regex(r"^https?:\/\/.*(jackett|\.torren|\/torrent|td.php).*"), add_from_url))
updater.add_handler(CallbackQueryHandler(start_download_to_folder_callback, pattern=r'(downloadFolder:)(.*), downloadMethod:(.*)$'))