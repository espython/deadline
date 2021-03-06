"""
Defines handlers for the different type of received messages
"""
import json
import logging

import asyncio
import websockets

from accounts.models import User
from private_chat.classes import WebSocketConnection
from private_chat.constants import EXPIRED_TOKEN_ERR_TYPE, AUTHORIZATION_ERR_TYPE, NOT_FOUND_ERR_TYPE, \
    VALIDATION_ERR_TYPE, WARNING_ERR_TYPE
from private_chat.errors import ChatPairingError, UserTokenMatchError
from private_chat.helpers import extract_connect_path, fetch_and_validate_participants
from private_chat.models import Dialog, Message
from private_chat.services.dialog import get_or_create_dialog_token
from private_chat.router import MessageRouter

"""
REVISIT: This way of handling connections is not scalable in the slightest way - 
    we can never run more than one process of this server, 
    as the ws_connections variable will not get shared and ws frames could be sent
    to the process that did not establish the connection
IDEA:    Maybe it could get shared via some message broker (e.g connection established/authenticated/disconnected) 
            or store it in something like Redis or a DB?
IDEA:    Maybe we could rewrite it to something which allows parallelism with shared memory
"""
logger = logging.getLogger('django-private-dialog')
ws_connections: {(int, int): WebSocketConnection} = {}


async def send_message(conn, payload):
    """
    Distributed payload (message) to one connection
    """
    try:
        await conn.send(json.dumps(payload))
    except Exception as e:
        logger.error(f'Could not send message to websocket due to {e}')


async def fan_out_message(connections, payload):
    """
    distributes payload (message) to all connected ws clients
    """
    for conn in connections:
        try:
            await conn.send(json.dumps(payload))
        except Exception as e:
            logger.error(f'Could not send message to multiple websockets due to {e}')


async def authenticate(stream):
    """
    Authenticates the user and marks his websocket as valid

    Needs to be sent the following JSON
    {
    "type": "authenticate",
    "user_id": YOUR_USER_ID_HERE,
    "auth_token": YOUR_AUTH_TOKEN_HERE,
    "opponent_id": HIS_ID_HERE
    }
    """
    while True:
        packet = await stream.get()
        owner_id, opponent_id = int(packet.get('user_id')), int(packet.get('opponent_id'))

        to_send_message, payload = _authenticate(packet, owner_id, opponent_id)
        if to_send_message:
            asyncio.ensure_future(send_message(ws_connections[(owner_id, opponent_id)].web_socket, payload))

            opponent_is_online = ((opponent_id, owner_id) in ws_connections
                                  and ws_connections[(opponent_id, owner_id)].is_valid)
            asyncio.ensure_future(send_message(ws_connections[(owner_id, opponent_id)].web_socket,
                                               {'type': 'online-check', 'is_online': opponent_is_online}))
            # Notify the opponent that we came online
            if opponent_is_online:
                asyncio.ensure_future(send_message(ws_connections[(opponent_id, owner_id)].web_socket,
                                                   {'type': 'online-check', 'is_online': True}))


def _authenticate(packet: dict, owner_id, opponent_id) -> (bool, dict):
    """
    :return:
        - boolean indicating if we want to send a message
        - the payload we would send
    """

    try:
        owner, opponent = fetch_and_validate_participants(owner_id, opponent_id)
        if owner.auth_token.key != packet.get('auth_token'):  # authenticate user
            raise UserTokenMatchError(f'Invalid token!')
    except (User.DoesNotExist, UserTokenMatchError) as e:
        err_type = {User.DoesNotExist: NOT_FOUND_ERR_TYPE, UserTokenMatchError: AUTHORIZATION_ERR_TYPE}[e.__class__]
        logger.debug(f'Raised {e.__class__} in fetch-token handler. Error message was {str(e)}')
        return True, {'type': 'error', 'error_type': err_type, 'message': str(e)}

    ws_connections[(owner_id, opponent_id)].is_valid = True
    return True, {'type': 'OK', 'message': 'AUTHENTICATED'}


async def new_messages_handler(stream):
    """
    Receives a message from a user and direct it to the recipient

    Needs to be sent the following JSON
    {
        "type": "new-message",
        "message": "YOUR_MESSAGE_HERE",
        "user_id": YOUR_USER_ID_HERE,
        "opponent_id": HIS_ID_HERE,
        "conversation_token": YOUR_CONVESRATION_TOKEN_HERE
    }
    """
    while True:
        packet = await stream.get()
        owner_id, opponent_id = packet.get('user_id'), packet.get('opponent_id')
        to_send, is_err, payload = _new_messages_handler(packet, owner_id, opponent_id)

        if to_send:
            owner_id, opponent_id = int(owner_id), int(opponent_id)
            owner_socket = ws_connections[(owner_id, opponent_id)]

            connections = [owner_socket.web_socket]
            if not is_err and (opponent_id, owner_id) in ws_connections:
                opponent_socket: WebSocketConnection = ws_connections[(opponent_id, owner_id)]
                if opponent_socket.is_valid:
                    connections.append(opponent_socket.web_socket)

            await fan_out_message(connections, payload)


def _new_messages_handler(packet: dict, owner_id, opponent_id):
    """
    Validates the user_ids, the connection's validity and owner's authorization and sends the message to both
    """
    if (owner_id, opponent_id) not in ws_connections:
        return False, True, {}  # no such connection, we cannot send this to anybody

    message = packet.get('message')
    if not message:
        return True, True, {'type': 'error', 'error_type': VALIDATION_ERR_TYPE, 'message': 'Message cannot be empty!'}

    try:
        owner, opponent = fetch_and_validate_participants(owner_id, opponent_id)
    except (User.DoesNotExist, ChatPairingError) as e:
        # should not happen, as we should not have a non-existent user in ws_connections
        return True, True, {'type': 'error', 'error_type': NOT_FOUND_ERR_TYPE, 'message': str(e)}

    owner_socket: WebSocketConnection = ws_connections[(owner.id, opponent.id)]
    if not owner_socket.is_valid:
        return True, True, {'type': 'error', 'error_type': AUTHORIZATION_ERR_TYPE,
                            'message': 'You need to authorize yourself by fetching a token!'}

    dialog: Dialog = Dialog.objects.get_or_create_dialog_with_users(owner, opponent)

    msg = Message.objects.create(
        dialog=dialog,
        sender=owner,
        text=message
    )

    payload_to_send = {
        'type': 'received-message',
        'created': msg.get_formatted_create_datetime(),
        'sender_name': msg.sender.username,
        'message': message,
        'id': msg.id
    }

    return True, False, payload_to_send


async def is_typing_handler(stream):
    """
    Show message to opponent if user is typing message
    Expects the following JSON
    {
    "type": "is-typing",
    "conversation_token": YOUR_TOKEN_HERE,
    "user_id": YOUR_ID_HERE,
    "opponent_id": OPPONENT_ID_HERE
    }
    """
    while True:
        packet = await stream.get()
        owner_id, opponent_id = packet.get('user_id'), packet.get('opponent_id')
        conversation_token = packet.get('conversation_token')

        to_send_msg, payload = _is_typing(owner_id, opponent_id, conversation_token)
        owner_socket = ws_connections[(owner_id, opponent_id)].web_socket
        if to_send_msg:
            asyncio.ensure_future(send_message(owner_socket, payload))
            continue

        opponent_is_online = ((opponent_id, owner_id) in ws_connections
                              and ws_connections[(opponent_id, owner_id)].is_valid)
        if opponent_is_online:
            opponent_socket = ws_connections[(opponent_id, owner_id)].web_socket
            asyncio.ensure_future(send_message(opponent_socket, {'type': 'opponent-typing'}))
        else:
            asyncio.ensure_future(send_message(owner_socket, {'type': 'error', 'error_type': WARNING_ERR_TYPE,
                                                              'message': f'User {opponent_id} is offline!'}))


def _is_typing(owner_id: int, opponent_id: int, conversation_token: str) -> (bool, dict):
    """
    Returns a boolean indicating if we should send a message and the payload of said message
    """
    if (owner_id, opponent_id) not in ws_connections:
        return False, {}  # no such connection, we cannot send this to anybody

    try:
        owner, opponent = fetch_and_validate_participants(owner_id, opponent_id)
    except (User.DoesNotExist, ChatPairingError) as e:
        # should not happen, as we should not have a non-existent user in ws_connections
        return True, {'type': 'error', 'error_type': NOT_FOUND_ERR_TYPE, 'message': str(e)}

    owner_socket: WebSocketConnection = ws_connections[(owner.id, opponent.id)]
    if not owner_socket.is_valid:
        return True, {'type': 'error', 'error_type': AUTHORIZATION_ERR_TYPE,
                      'message': 'You need to authorize yourself by fetching a token!'}

    return False, {}


async def main_handler(websocket, path):
    """
    An Asyncio Task is created for every new websocket client connection
    that is established. This coroutine listens to messages from the connected
    client and routes the message to the proper queue depending on the message type.

    This coroutine can be thought of as a producer.

    Expected path for initial connection is
    /user_id/user_token/user_to_speak_to_id
    """
    # TODO: All these tokens being sent are useless, as once we authenticate a user we have this websocket saved
    # TODO:     These were made before we added checks for malicious `user_id` checks and as now we simply overwrite
    # TODO:     the field, we know that each message from a `user_id` is from him,
    # TODO:         so no need to authenticate on each message
    owner_id, opponent_id = extract_connect_path(path)
    try:
        owner, opponent = fetch_and_validate_participants(owner_id, opponent_id)
    except (ChatPairingError, User.DoesNotExist) as e:
        print(str(e))
        return

    if (owner.id, opponent.id) in ws_connections:
        # This websocket is already connected, overwrite it only if it is not valid
        if ws_connections[(owner.id, opponent.id)].is_valid:
            logger.debug(f'Tried to overwrite socket with ID {(owner.id, opponent.id)} but did not since it was valid!')
            return
        logger.debug(f'Overwrote socket with ID {(owner.id, opponent.id)}')

    ws_connections[(owner.id, opponent.id)] = WebSocketConnection(websocket, owner_id, opponent_id)

    asyncio.ensure_future(send_message(websocket, {'tank': 'YOU ARE CONNECTED :)'}))

    # While the websocket is open, listen for incoming messages/events
    is_overwritten = False
    try:
        while websocket.open:
            data = await websocket.recv()
            if ws_connections[(owner.id, opponent.id)].web_socket != websocket:
                # This socket has been overwritten, so stop it
                is_overwritten = True
                return

            if not data:
                continue

            try:
                print(f'Data is {data}')
                await MessageRouter(data, user_id=owner_id, opponent_id=opponent.id)()
            except Exception as e:
                logger.error(f'Could not route message {e}')

    except websockets.exceptions.InvalidState:  # User disconnected
        pass
    finally:
        if not is_overwritten:
            del ws_connections[(owner.id, opponent.id)]
            if (opponent.id, owner.id) in ws_connections and ws_connections[(opponent.id, owner.id)].is_valid:
                asyncio.ensure_future(send_message(ws_connections[(opponent.id, owner.id)].web_socket,
                                                   {'type': 'online-check', 'is_online': False}))
        else:
            logger.debug(f'Deleted old overwritten socket with ID {(owner.id, opponent.id)}')
