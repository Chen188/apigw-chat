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
    STORAGE.create_connection(event.connection_id)
    xray_recorder.end_subsegment()


@app.on_ws_disconnect()
def disconnect(event):
    xray_recorder.begin_subsegment('disconnect')
    STORAGE.delete_connection(event.connection_id)
    xray_recorder.end_subsegment()

@app.on_ws_message()
def message(event):
    xray_recorder.begin_subsegment('on_ws_message')
    HANDLER.handle(event.connection_id, event.body)
    xray_recorder.end_subsegment()

@app.route("/ip")
def ip():
    subsegment = xray_recorder.begin_subsegment('ip"')
    subsegment.put_http_meta('url', '/ip"')
    subsegment.put_http_meta('method', 'GET')
    xray_recorder.end_subsegment()
    r = requests.get('http://api.ipify.org/')
    return {"ip": r.text}