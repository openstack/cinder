# Copyright 2011 Nexenta Systems, Inc.
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
:mod:`nexenta.jsonrpc` -- Nexenta-specific JSON RPC client
=====================================================================

.. automodule:: nexenta.jsonrpc
"""

import time

from oslo_log import log as logging
from oslo_serialization import jsonutils
import requests

from cinder import exception

LOG = logging.getLogger(__name__)


class NexentaJSONProxy(object):

    def __init__(self, scheme, host, port, user,
                 password, auto=False, method=None):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.auto = True
        self.method = method

    @property
    def url(self):
        return '%s://%s:%s/' % (self.scheme, self.host, self.port)

    def __getattr__(self, method=None):
        if method:
            return NexentaJSONProxy(
                self.scheme, self.host, self.port,
                self.user, self.password, self.auto, method)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'NEF proxy: %s' % self.url

    def __call__(self, path, data=None):
        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }
        url = self.url + path

        if data:
            data = jsonutils.dumps(data)

        LOG.debug('Sending JSON to url: %s, data: %s, method: %s',
                  path, data, self.method)
        if self.method == 'get':
            resp = requests.get(url, headers=headers)
        if self.method == 'post':
            resp = requests.post(url, data=data, headers=headers)
        if self.method == 'put':
            resp = requests.put(url, data=data, headers=headers)
        if self.method == 'delete':
            resp = requests.delete(url, data=data, headers=headers)

        if resp.status_code == 201 or (
                resp.status_code == 200 and not resp.content):
            LOG.debug('Got response: Success')
            return 'Success'

        response = resp.json()
        resp.close()
        if response and resp.status_code == 202:
            url = self.url + response['links'][0]['href']
            while resp.status_code == 202:
                time.sleep(1)
                resp = requests.get(url)
                if resp.status_code == 201 or (
                        resp.status_code == 200 and not resp.content):
                    LOG.debug('Got response: Success')
                    return 'Success'
                else:
                    response = resp.json()
                resp.close()
        if response.get('code'):
            raise exception.NexentaException(response)
        LOG.debug('Got response: %s', response)
        return response
