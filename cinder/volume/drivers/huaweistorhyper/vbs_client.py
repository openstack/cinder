# Copyright (c) 2014 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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
 Vbs Client for Huawei SDSHypervisor systems internal communication.
"""

import socket

from oslo_utils import units

from cinder.i18n import _, _LE
from cinder.openstack.common import log as logging
from cinder.volume.drivers.huaweistorhyper import utils as storhyper_utils

LOG = logging.getLogger(__name__)

BUFFER_SIZE = 1024


class VbsClient(object):

    def __init__(self, config_file):
        LOG.debug('Vbs client init.')
        self.config_file = config_file
        (self.ip_list, self.port) = \
            storhyper_utils.get_ip_and_port(config_file)

    def send_message(self, msg):
        return self._send_message_to_first_valid_host(msg)

    def _send_message_to_first_valid_host(self, msg):
        LOG.debug('Send message to first valid host.')
        if not self.ip_list:
            msg = _LE('No valid ip in vbs ip list.')
            LOG.error(msg)
            raise AssertionError(msg)

        exec_result = ''
        for ip in self.ip_list:
            exec_result = VbsClient.send_and_receive(
                ip, self.port, msg
            )
            if exec_result:
                return exec_result
        return exec_result

    @staticmethod
    def send_and_receive(ip, port, request):
        rsp = None
        socket_instance = None
        try:
            socket_instance = socket.socket(socket.AF_INET,
                                            socket.SOCK_STREAM)
            socket_instance.connect((ip, port))
            LOG.debug('Start sending requests.')
            socket_instance.send(request.encode('utf-8', 'strict'))
            LOG.debug('Waiting for response.')
            rsp = socket_instance.recv(units.Ki).decode(
                'utf-8', 'strict')
            LOG.debug('Response received: %s.' % repr(rsp))
            return rsp
        except OSError as ose:
            LOG.exception(_('Send message failed,OSError. %s.'), ose)
        except Exception as e:
            LOG.exception(_('Send message failed. %s.'), e)
        finally:
            if socket_instance:
                socket_instance.close()
        return rsp
