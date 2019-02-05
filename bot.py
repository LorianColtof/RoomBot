import requests
import logging
import click
import telegram
import traceback
import dateutil.parser

from requests.exceptions import HTTPError
from collections import namedtuple
from telegram.ext import Updater, CommandHandler
from functools import wraps


RoomReaction = namedtuple(
    'RoomReaction', ['status', 'address', 'position',
                     'offered_position', 'amount_reactions',
                     'closing_date'])


def check_response(response):
    if not response.ok:
        raise HTTPError('{}: Got status code {}'.format(
            response.request.url,
            response.status_code))

    return response


def create_session(username, password):
    session = requests.Session()
    session.headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36'  # noqa
    }

    check_response(session.get('https://www.room.nl/my-room/inloggen/'))
    r = check_response(session.get(
        'https://www.room.nl/portal/account/frontend/getloginconfiguration/format/json'))  # noqa
    data = r.json()
    login_id = data["loginForm"]["id"]
    login_hash = data["loginForm"]["elements"]["__hash__"]["initialData"]

    check_response(session.post(
        'https://www.room.nl/portal/account/frontend/loginbyservice/format/json',  # noqa
                           data={
                               '__id__': login_id,
                               '__hash__': login_hash,
                               'username': username,
                               'password': password
                           }))

    return session


def get_active_reactions(session):
    r = check_response(session.get(
        'https://www.room.nl/portal/registration/frontend/getactievereacties/format/json'))  # noqa

    data = {}

    for room in r.json()['result']:
        room_data = room['object']
        status = room['advertentie']['status']

        address = "{} {}{}, {} {}".format(room_data['street'],
                                          room_data['houseNumber'],
                                          room_data['houseNumberAddition'],
                                          room_data['postalcode'],
                                          room_data['city']['name'])
        my_position = room['positie']
        if status == "Aangeboden":
            offered_position = room['huidigeAanbieding']['reactiePositie']
        else:
            offered_position = None

        amount_reactions = room['advertentie']['aantalReacties']
        closing_date = dateutil.parser.parse(room['object']['closingDate'])

        data[room['id']] = RoomReaction(
            status, address, my_position,
            offered_position, amount_reactions, closing_date)

    return data


def protect(f):

    @wraps(f)
    def wrapper(bot, update, *args, **kwargs):
        if update.message.from_user.username != 'loriancoltof':
            bot.send_message(chat_id=update.message.chat_id,
                             text="Access denied")
            return

        return f(bot, update, *args, **kwargs)

    return wrapper


@click.command()
@click.option('--username', '-u', type=str, required=True)
@click.option('--password', '-p', type=str, required=True)
@click.option('--tg-bot-token', '-t', type=str, required=True)
def main(username, password, tg_bot_token):
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO)

    chat_id = None
    reactions = None

    @protect
    def tg_start(bot, update):
        nonlocal chat_id, reactions
        chat_id = update.message.chat_id

        session = create_session(username, password)
        reactions = get_active_reactions(session)

        bot.send_message(chat_id=chat_id,
                         text="Keeping you updated from now on.")

    @protect
    def tg_show(bot, update):
        session = create_session(username, password)

        bot.send_message(chat_id=update.message.chat_id,
                         text="Current status of your reactions:")

        for reaction in get_active_reactions(session).values():
            text = f"*{reaction.address}*\n" + \
                f"   Status: {reaction.status}\n" + \
                f"   My position: {reaction.position}"

            if reaction.offered_position:
                text += \
                    f"\n   Offered to candidate: {reaction.offered_position}"

            if reaction.status == 'Gepubliceerd':
                text += \
                    f"\n   Amount of reactions: {reaction.amount_reactions}" +\
                    f"\n   Closing date: {reaction.closing_date}\n"

            bot.send_message(chat_id=update.message.chat_id, text=text,
                             parse_mode=telegram.ParseMode.MARKDOWN)

    def tg_send_messages(bot, job):
        nonlocal chat_id, reactions

        if not chat_id or not reactions:
            return

        try:
            try:
                session = create_session(username, password)
                new_reactions = get_active_reactions(session)
            except Exception as e:
                bot.send_message(chat_id=chat_id,
                                 text="Could not retrieve reactions")
                bot.send_message(chat_id=chat_id,
                                 text=f"```{repr(e)}```",
                                 parse_mode=telegram.ParseMode.MARKDOWN)
                return

            if new_reactions != reactions:
                text = "One or more reactions have changed:\n\n"

                vanished_ids = set(reactions.keys()) - set(
                    new_reactions.keys())
                new_ids = set(new_reactions.keys()) - set(reactions.keys())
                common_ids = set(
                    reactions.keys()).intersection(set(new_reactions.keys()))

                for _id in vanished_ids:
                    reaction = reactions[_id]
                    text += f"Reaction *{reaction.address}* is gone.\n\n"

                for _id in new_ids:
                    reaction = new_reactions[_id]
                    text += f"New reaction on *{reaction.address}*:\n" + \
                        f"   Status: {reaction.status}\n" + \
                        f"   My position: {reaction.position}"

                    if reaction.offered_position:
                        text += "\n   Offered to candidate: " + \
                            f"{reaction.offered_position}"

                    text += "\n\n"

                for _id in common_ids:
                    old_reaction = reactions[_id]
                    new_reaction = new_reactions[_id]
                    if old_reaction == new_reaction:
                        continue

                    print('old_reaction', old_reaction)
                    print('new_reaction', new_reaction)
                    print()

                    notify = False
                    details_text = ""

                    if old_reaction.status != new_reaction.status:
                        notify = True
                        details_text += "   Status changed: {} -> {}\n".format(
                            old_reaction.status, new_reaction.status)

                    if old_reaction.offered_position != \
                            new_reaction.offered_position and \
                            new_reaction.offered_position:
                        notify = True
                        details_text += "   Is now offered to candidate {}\n" \
                            .format(new_reaction.offered_position)

                        if old_reaction.offered_position:
                            details_text += "   (was previously offered " + \
                                "to candidate {})\n".format(
                                    old_reaction.offered_position)
                    if notify:
                        text += f"Reaction *{new_reaction.address}*:\n" + \
                            details_text

                reactions = new_reactions

                bot.send_message(chat_id=chat_id, text=text,
                                 parse_mode=telegram.ParseMode.MARKDOWN)

        except Exception:
            bot.send_message(chat_id=chat_id, text="Something went wrong!",
                             parse_mode=telegram.ParseMode.MARKDOWN)
            bot.send_message(chat_id=chat_id,
                             text=f"```\n{traceback.format_exc()}\n```",
                             parse_mode=telegram.ParseMode.MARKDOWN)

    tg_updater = Updater(token=tg_bot_token)
    tg_dispatcher = tg_updater.dispatcher
    tg_dispatcher.add_handler(CommandHandler('start', tg_start))
    tg_dispatcher.add_handler(CommandHandler('show', tg_show))

    tg_updater.job_queue.run_repeating(tg_send_messages, interval=60, first=0)

    tg_updater.start_polling()
    tg_updater.idle()


if __name__ == "__main__":
    main()
