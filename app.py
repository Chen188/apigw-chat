from boto3.session import Session

from chalice import Chalice

from chalicelib import Storage
from chalicelib import Sender
from chalicelib import Handler

import requests
import logging

from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
from datetime import datetime

app = Chalice(app_name="chalice-chat")
app.websocket_api.session = Session(region_name='cn-northwest-1')
app.websocket_api.configure('<replace-with-your-apigw-id>.execute-api.cn-northwest-1.amazonaws.com.cn', 'api')

app.experimental_feature_flags.update([
    'WEBSOCKETS'
])

STORAGE = Storage.from_env()
SENDER = Sender(app, STORAGE)
HANDLER = Handler(STORAGE, SENDER)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
patch_all()

@app.on_ws_connect()
def connect(event):
    xray_recorder.begin_subsegment('on_ws_connect')
    # logger.info("on_ws_connect start connection_id:{},time:{}"
    #             .format(event.connection_id,datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    STORAGE.create_connection(event.connection_id)
    # logger.info("on_ws_connect  end  connection_id:{},time:{}"
    #             .format(event.connection_id, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    xray_recorder.end_subsegment()


@app.on_ws_disconnect()
def disconnect(event):
    xray_recorder.begin_subsegment('disconnect')
    # logger.info("on_ws_disconnect start connection_id:{},time:{}"
    #             .format(event.connection_id, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    STORAGE.delete_connection(event.connection_id)
    # logger.info("on_ws_disconnect  end  connection_id:{},time:{}"
    #             .format(event.connection_id, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    xray_recorder.end_subsegment()

@app.on_ws_message()
def message(event):
    xray_recorder.begin_subsegment('on_ws_message')
    # logger.info("on_ws_message start connection_id:{},time:{}"
    #             .format(event.connection_id,datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    HANDLER.handle(event.connection_id, event.body)
    # logger.info("on_ws_message  end  connection_id:{},time:{}"
    #             .format(event.connection_id, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]))
    xray_recorder.end_subsegment()

@app.route("/ip")
def ip():
    subsegment = xray_recorder.begin_subsegment('ip"')
    subsegment.put_http_meta('url', '/ip"')
    subsegment.put_http_meta('method', 'GET')
    xray_recorder.end_subsegment()
    r = requests.get('http://api.ipify.org/')
    return {"ip": r.text}