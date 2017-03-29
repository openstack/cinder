# Copyright (c) 2017 Veritas Technologies LLC.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Error Codes
"""

EX_BAD_PARAM = 10
EX_BAD_MESSAGE = 106
MSG_SUCCESS = 0
MSG_ERROR = 1

"""
Constants
"""
HS_VHOST = "/"
ACK_YES = 1
ACK_NO = 0
BLK_YES = 1
BLK_NO = 0
EXCH_DIRECT = "direct"
EXCH_FANOUT = "fanout"
EXCH_TOPIC = "topic"

MSG_REQUEST = 1
MSG_RESPONSE = 2
MSG_TOKEN = "token"
MSG_OWNER = "owner"
MSG_TYPE = "type"
MSG_ERROR = "err_code"
MSG_ACK = "ack"
MSG_BLK = "blocking"
MSG_BLK_INFO = "blocking_info"
MSG_BLK_NAME = "name"
MSG_BLK_BINDKEY = "bindkey"
MSG_BLK_TYPE = "type"
MSG_PAYLOAD = "payload"

# HyperScale Controller Exchange
HS_CONTROLLER_EXCH = 'hyperscale-controller'
HS_RPC_EXCH = 'hyperscale-recv'
HS_DATANODE_EXCH = 'hyperscale-datanode'
HS_COMPUTE_EXCH = 'hyperscale-storage'

SNAP_RESTORE_RF = 3
