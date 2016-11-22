# Copyright 2015 Nexenta Systems, Inc.
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

import json
import requests
import socket

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry

LOG = logging.getLogger(__name__)
socket.setdefaulttimeout(100)


class NexentaEdgeJSONProxy(object):

    retry_exc_tuple = (
        requests.exceptions.ConnectionError,
    )

    def __init__(self, protocol, host, port, path, user, password, auto=False,
                 method=None):
        self.protocol = protocol.lower()
        self.host = host
        self.port = port
        self.path = path
        self.user = user
        self.password = password
        self.auto = auto
        self.method = method

    @property
    def url(self):
        return '%s://%s:%s/%s' % (self.protocol,
                                  self.host, self.port, self.path)

    def __getattr__(self, name):
        if not self.method:
            method = name
        else:
            raise exception.VolumeDriverException(
                _("Wrong resource call syntax"))
        return NexentaEdgeJSONProxy(
            self.protocol, self.host, self.port, self.path,
            self.user, self.password, self.auto, method)

    def __hash__(self):
        return self.url.__hash___()

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url

    @retry(retry_exc_tuple, interval=1, retries=6)
    def __call__(self, *args):
        self.path = args[0]
        data = None
        if len(args) > 1:
            data = json.dumps(args[1])

        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }

        LOG.debug('Sending JSON data: %s, data: %s', self.url, data)

        if self.method == 'get':
            req = requests.get(self.url, headers=headers)
        if self.method == 'post':
            req = requests.post(self.url, data=data, headers=headers)
        if self.method == 'put':
            req = requests.put(self.url, data=data, headers=headers)
        if self.method == 'delete':
            req = requests.delete(self.url, data=data, headers=headers)

        rsp = req.json()
        req.close()

        LOG.debug('Got response: %s', rsp)
        if rsp.get('response') is None:
            raise exception.VolumeBackendAPIException(
                _('Error response: %s') % rsp)
        return rsp.get('response')
