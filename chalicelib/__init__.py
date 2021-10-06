import os
import boto3
import logging
import datetime
import time

from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

from boto3.dynamodb.conditions import Key

from chalice import WebsocketDisconnectedError


logger = logging.getLogger()
logger.setLevel(logging.INFO)
patch_all()

TTL_MINUTES = 10


def add_minutes(min):
    """返回输入数量之后的unix时间戳

    :param min: 分钟数
    """
    nowadd = datetime.datetime.now() + datetime.timedelta(minutes=min)

    return int(time.mktime(nowadd.timetuple()))

class Storage(object):
    """与DynamoDB表进行交互的抽象类"""
    def __init__(self, table):
        """初始化存储对象

        :param table: boto3动态表对象.
        """
        self._table = table

    @classmethod
    def from_env(cls):
        """从环境创建表。

        环境变量TABLE存在于已部署的应用程序中，因为它是通过CloudFormation在所有Lambda函数中设置的引用。
        我们默认变量为''，当执行``chalice package``时，它会加载了应用程序，并且不设置环境变量。
        对于本地测试，应该在环境中手动设置环境变量。
        """
        table_name = os.environ.get('TABLE', '')
        table = boto3.resource('dynamodb').Table(table_name)
        return cls(table)
    def create_connection(self, connection_id):
        """在DynamoDB表中创建一个新的连接对象。

        创建新连接后，我们将为这个连接在表中创建一个存根。
        存根用connection_id做主键和用username_做排序键。
        这会将一个连接翻译成一个未使用的用户名。
        第一条通过这个连接发送的信息将被用作用户名，该条目将被重写。

        ：param connection_id：要写入的连接ID
        """
        xray_recorder.begin_subsegment('create_connection')

        logger.info("create_connection connection_id:{0}".format(connection_id))

        self._table.put_item(
            Item={
                'PK': connection_id,
                'SK': 'username_',
                'TTL': add_minutes(TTL_MINUTES),
            },
        )
        xray_recorder.end_subsegment()

    def set_username(self, connection_id, old_name, username):
        """设置用户名。

        该连接ID开头的SK条目使用username_作为用户名。以前的条目需要删除，并且需要一个新条目会被写入。

        ：param connection_id：需要更名的用户的连接ID

        ：param old_name：原始用户名。组成key的一部分，所以需要将其删除并重新创建，而不是更新。

        ：param用户名：新用户名。
        """
        logger.info("set_username connection_id:{0},username:{1}".format(connection_id, username))

        self._table.delete_item(
            Key={
                'PK': connection_id,
                'SK': 'username_%s' % old_name,
            },
        )
        self._table.put_item(
            Item={
                'PK': connection_id,
                'SK': 'username_%s' % username,
                'TTL': add_minutes(TTL_MINUTES),
            },
        )
    def list_rooms(self):
        """获取所有现有房间的列表。

        遍历表以查找SK中以room_开头的数据，这些数据代表有人在房间内。
        返回去重的房间id
        """
        r = self._table.scan()
        rooms = set([item['SK'].split('_', 1)[1] for item in r['Items']
                     if item['SK'].startswith('room_')])
        return rooms
    def set_room(self, connection_id, room):
        """设置用户当前所在的房间。

        用户所在的房间数据的SK以room_为前缀。

        ：param connection_id：要移动到房间的连接ID。

        ：param room：要加入的房间名称。
        """
        self._table.put_item(
            Item={
                'PK': connection_id,
                'SK': 'room_%s' % room,
                'TTL': add_minutes(TTL_MINUTES),
            },
        )
    def remove_room(self, connection_id, room):
        """将用户从房间中删除。

        用户所在的房间数据的SK以room_为前缀。要离开房间，我们需要删除此条目。

        ：param connection_id：要移动的连接ID。

        ：param room：要加入的房间名称。
        """
        self._table.delete_item(
            Key={
                'PK': connection_id,
                'SK': 'room_%s' % room,
            },
        )
    def get_connection_ids_by_room(self, room):
        """查找某个会议室的所有连接ID。

        当需要在一个房间广播时会用到。的连接ID，以便我们可以向他们发送消息。
        我们使用ReverseLookup表反转了PK，SK关系
        创建一个名为room_ {room}的分区。分区里面的一切是房间中的连接。

        ：param room：从中获取所有连接ID的房间名称。
        """

        r = self._table.query(
            IndexName='ReverseLookup',
            KeyConditionExpression=(
                Key('SK').eq('room_%s' % room)
            ),
            Select='ALL_ATTRIBUTES',
        )
        ret = [item['PK'] for item in r['Items']]

        logger.info("get_connection_ids_by_room room:{0},len:{1}".format(room, str(len(ret))))

        return ret

    def delete_connection(self, connection_id):
        """删除连接。

        当连接断开并且需要删除所有关联这个连接的条目时被调用。

        ：param connection_id：要从表中删除的连接
        """
        try:
            r = self._table.query(
                KeyConditionExpression=(
                    Key('PK').eq(connection_id)
                ),
                Select='ALL_ATTRIBUTES',
            )
            for item in r['Items']:
                self._table.delete_item(
                    Key={
                        'PK': connection_id,
                        'SK': item['SK'],
                    },
                )
        except Exception as e:
            print(e)

    def get_record_by_connection(self, connection_id):
        """获取与连接关联的所有属性。

        每个connection_id在表中创建一个分区，分区中包含多个SK条目。
        每个SK条目的格式均为{property} _ {value}。
        此方法从数据库中读取所有这些记录并将其放入全部放入字典并返回。

        ：param connection_id：要获取其属性的连接。
        """
        r = self._table.query(
            KeyConditionExpression=(
                Key('PK').eq(connection_id)
            ),
            Select='ALL_ATTRIBUTES',
        )
        r = {
            entry['SK'].split('_', 1)[0]: entry['SK'].split('_', 1)[1]
            for entry in r['Items']
        }
        return r

class Sender(object):
    """通过websocket发送消息类"""
    def __init__(self, app, storage):
        """初始化发送者对象。

        ：param app：Chalice应用程序对象。

        ：param storage：一个存储对象。
        """
        self._app = app
        self._storage = storage

    def send(self, connection_id, message):
        """通过websocket发送消息。

        ：param connection_id：API Gateway Connection ID，用于发送消息。

        ：param message：要发送到连接的消息。
        """
        try:
            # Call the chalice websocket api send method
            self._app.websocket_api.send(connection_id, message)
        except WebsocketDisconnectedError as e:
            # If the websocket has been closed, we delete the connection
            # from our database.
            self._storage.delete_connection(e.connection_id)

    def broadcast(self, connection_ids, message):
        """"将消息发送到多个连接。

        ：param connection_id：需要发送消息的API Gateway Connection ID列表
        ：param message：要发送到连接的消息。
        """
        nums = str(len(connection_ids))
        logger.info("broadcast start connections:{},message:{}".format(nums, message))
        for cid in connection_ids:
            self.send(cid, message)
        logger.info("broadcast  end  connections:{},message:{}".format(nums, message))

class Handler(object):
    """
    处理程序对象，用于处理从WebSocket接收的消息。
    此类实现了我们大部分的应用行为。
    """
    def __init__(self, storage, sender):
        """初始化Handler对象。

        ：param storage：与数据库交互的存储对象。

        ：param sender：发送者对象，用于通过websockets发送消息。
        """
        self._storage = storage
        self._sender = sender
        # 命令表将字符串命令名称转换为方法调用。
        self._command_table = {
            'help': self._help,
            'nick': self._nick,
            'join': self._join,
            'room': self._room,
            'quit': self._quit,
            'ls': self._list,
        }

    def handle(self, connection_id, message):
        """应用程序的入口。

        ：param connection_id：消息来自的连接ID。

        ：param message：从连接中得到的消息。
        """

        logger.info("handle message connection_id:{},message:{}".format(connection_id, message))

        # 首先在数据库中查找用户并获取记录。
        record = self._storage.get_record_by_connection(connection_id)
        if record['username'] == '':
            # 如果用户没有用户名，则假定该消息是他们想要的用户名，我们称为_handle_login_message。
            xray_recorder.begin_subsegment('_handle_login_message')
            self._handle_login_message(connection_id, message)
        else:
            # 否则，我们假设用户已登录。因此我们调用处理消息的方法。
            xray_recorder.begin_subsegment('_handle_message')
            self._handle_message(connection_id, message, record)
        xray_recorder.end_subsegment()

    def _handle_login_message(self, connection_id, message):
        """处理登录消息。

        message是用户发送的用户名。用于改写该用户的数据库条目，用于从“”重置其用户名
        发送到{message}。完成后，将消息发送回用户，确认名称设置成功。同时发送/ help提示给用户。
        """
        logger.info("_handle_login_message connection_id:{0},message:{1}".format(connection_id,message))

        self._storage.set_username(connection_id, '', message)
        self._sender.send(
            connection_id,
            'Using nickname: %s\nType /help for list of commands.' % message
        )

    def _handle_message(self, connection_id, message, record):
        """"处理来自已经连接并已登录用户的消息。

        如果消息以/开头，则为命令。否则它是一个发送给房间所有人的消息。

        ：param connection_id：消息来自的连接ID。

        ：param message：从连接中得到的消息。

        ：param record：关于发送者的数据记录。
        """
        if message == "":
            return
        if message.startswith('/'):
            self._handle_command(connection_id, message[1:], record)
        else:
            self._handle_text(connection_id, message, record)

    def _handle_command(self, connection_id, message, record):
        """处理命令消息。

        检查命令名称是否合法，如果合法则调用该方法并传递connection_id，参数和加载的记录。

        ：param connection_id：消息来自的连接ID。

        ：param message：从连接中得到的消息。

        ：param record：关于发送者的数据记录。
        """
        args = message.split(' ')
        command_name = args.pop(0).lower()
        command = self._command_table.get(command_name)
        if command:
            command(connection_id, args, record)
        else:
            # 如果找不到命令方法，则发送错误消息返回给用户。
            self._sender(
                connection_id, 'Unknown command: %s' % command_name)

    def _handle_text(self, connection_id, message, record):
        """处理文本消息。

        ：param connection_id：消息来自的连接ID。

        ：param message：从连接中得到的消息。

        ：param record：关于发送者的数据记录。
        """
        xray_recorder.begin_subsegment('_handle_text')
        if 'room' not in record:
            # 如果用户不在房间内，请向他们发送错误消息并且直接返回
            self._sender.send(
                connection_id, 'Cannot send message if not in chatroom.')
            return
        # 取得消息位于同一房间的用户的connection_id列表
        connection_ids = self._storage.get_connection_ids_by_room(
            record['room'])
        # 在消息前面加上发件人的名字。
        message = '%s: %s' % (record['username'], message)
        # 将新消息广播给会议室中的所有人。
        self._sender.broadcast(connection_ids, message)
        xray_recorder.end_subsegment()

    def _help(self, connection_id, _message, _record):
        """发送帮助消息。生成帮助消息并发送回相同的连接。

        ：param connection_id：消息来自的连接ID。
        """
        self._sender.send(
            connection_id,
            '\n'.join([
                'Commands available:',
                '    /help',
                '          显示此消息',
                '    /join {chat_room_name}',
                '          加入名为{chat_room_name}的聊天室',
                '    /nick {nickname}',
                '          将您的名字更改为{nickname}。如果没有{nickname}，将打印您的当前姓名',
                '    /room',
                '          打印出您当前房间的名称',
                '    /ls',
                '          如果您在一个房间中，请同时在其中列出所有用户，房间。否则，列出所有房间',
                '    /quit',
                '          离开当前房间',
                '',
                '如果您在房间里，无法发送以/开头的消息，并且消息会发送给所有人',
            ]),
        )
    def _nick(self, connection_id, args, record):
        """更改或检查昵称（用户名）

        ：param connection_id：消息来自的连接ID。

        ：param args：命令后的参数列表。

        ：param record：关于发送者的数据记录。
        """
        if not args:
            # 如果未提供昵称参数，我们只向用户返回当前昵称。
            self._sender.send(
                connection_id, 'Current nickname: %s' % record['username'])
            return
        # 假定第一个参数是所需的新昵称
        nick = args[0]
        # 将用户名从record ['username']更改为存储中的昵称
        # 这是个layer.
        self._storage.set_username(connection_id, record['username'], nick)
        # 向请求者发送消息以告知昵称更改成功
        self._sender.send(connection_id, 'Nickname is: %s' % nick)
        # 获取用户所在的房间
        room = record.get('room')
        if room:
            # 如果用户在房间里，请向房间广播更改了他们的名字。不需要讯息发送给更名用户，因为他已经收到了更名消息。
            room_connections = self._storage.get_connection_ids_by_room(room)
            room_connections.remove(connection_id)
            self._sender.broadcast(
                room_connections,
                '%s is now known as %s.' % (record['username'], nick))

    def _join(self, connection_id, args, record):
        """加入聊天室。

        ：param connection_id：消息来自的连接ID。

        ：param args：参数列表。第一个参数应该是要加入的房间的名称。

        ：param record：关于发送者的数据记录。
        """
        # 获取要加入的房间名称
        room = args[0]
        # 呼叫quit离开当前所在的房间（如果有）
        self._quit(connection_id, '', record)
        # 获取目标聊天室中的连接列表
        # room_connections = self._storage.get_connection_ids_by_room(room)
        # 加入目标聊天室
        self._storage.set_room(connection_id, room)
        # 向请求者发送一条消息，告知他已加入会议室。同时向所有已经在房间的人发送消息提醒有新用户
        self._sender.send(
            connection_id, 'Joined chat room "%s"' % room)
        # message = '%s joined room.' % record['username']
        # self._sender.broadcast(room_connections, message)

    def _room(self, connection_id, _args, record):
        """返回当前房间的名称。

        ：param connection_id：消息来自的连接ID。

        ：param record：关于发送者的数据记录。
        """
        if 'room' in record:
            # 如果用户在房间里，给他发回名字。
            self._sender.send(connection_id, record['room'])
        else:
            # 如果用户不在房间里。告知他并提示如何加入一个房间。
            self._sender.send(
                connection_id,
                'Not currently in a room. Type /join {room_name} to do so.'
            )

    def _quit(self, connection_id, _args, record):
        """从房间退出。

        ：param connection_id：消息来自的连接ID。

        ：param record：关于发送者的数据记录。
        """
        if 'room' not in record:
            # 如果用户不在房间里直接返回
            return
        # 查找当前房间名称，然后从表中删除该条目
        room_name = record['room']
        self._storage.remove_room(connection_id, room_name)
        # 向用户发送一条消息，通知他离开了房间成功。
        self._sender.send(
            connection_id, 'Left chat room "%s"' % room_name)
        # 告诉房间中的所有人该用户已经离开。
        self._sender.broadcast(
            self._storage.get_connection_ids_by_room(room_name),
            '%s left room.' % record['username'],
        )

    def _list(self, connection_id, _args, record):
        """显示上下文相关列表。

        ：param connection_id：消息来自的连接ID。

        ：param record：关于发送者的数据记录。
        """
        room = record.get('room')
        if room:
            # 如果用户在房间里，列出在房间里的所有人
            result = [
                self._storage.get_record_by_connection(c_id)['username']
                for c_id in self._storage.get_connection_ids_by_room(room)
            ]
        else:
            # 如果他们不在房间里。获取所有房间的清单
            result = self._storage.list_rooms()
        # 发送结果列表
        self._sender.send(connection_id, '\n'.join(result))
