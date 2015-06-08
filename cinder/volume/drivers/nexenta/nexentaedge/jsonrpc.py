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
:mod:`nexentaedge.jsonrpc` -- NexentaEdge-specific JSON RPC client
=====================================================================
.. automodule:: nexentaedge.jsonrpc
.. moduleauthor:: Zohar Mamedov <zohar.mamedov@nexenta.com>
.. moduleauthor:: Kyle Schochenmaier <kyle.schochenmaier@nexenta.com>
"""

import json
import urllib2

from cinder.i18n import _LE, _LI
from cinder.volume.drivers import nexenta
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class NexentaJSONException(nexenta.NexentaException):
    pass


class NexentaEdgeJSONProxy(object):

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
        return '%s://%s:%s%s' % (self.protocol,
                                 self.host, self.port, self.path)

    def __getattr__(self, name):
        if not self.method:
            method = name
        else:
            raise Exception("Wrong resource call syntax")
        return NexentaEdgeJSONProxy(
            self.protocol, self.host, self.port, self.path,
            self.user, self.password, self.auto, method)

    def __hash__(self):
        return self.url.__hash___()

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url

    def __call__(self, *args):
        self.path += args[0]
        data = None
        if len(args) > 1:
            data = json.dumps(args[1])

        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }

        LOG.info(_LI('Sending JSON data: %s') % self.url)

        try:
            request = urllib2.Request(self.url, data, headers)
            if self.method == 'get':
                request.get_method = lambda: 'GET'
            elif self.method == 'post':
                request.get_method = lambda: 'POST'
            elif self.method == 'put':
                request.get_method = lambda: 'PUT'
            elif self.method == 'delete':
                request.get_method = lambda: 'DELETE'

            response_obj = urllib2.urlopen(request)

            # Handle 'auto' switch mode.. from HTTP to HTTPS
            if response_obj.info().status == 'EOF in headers':
                if not self.auto or self.protocol != 'http':
                    LOG.error(_LE('No headers in server response'))
                    raise NexentaJSONException(_LE('Bad response from server'))
                LOG.info(
                    _LI('Auto switching to HTTPS connection to %s') % self.url)
                self.protocol = 'https'
                request = urllib2.Request(self.url, data, headers)
                if self.method == 'get':
                    request.get_method = lambda: 'GET'
                elif self.method == 'post':
                    request.get_method = lambda: 'POST'
                elif self.method == 'put':
                    request.get_method = lambda: 'PUT'
                elif self.method == 'delete':
                    request.get_method = lambda: 'DELETE'
                response_obj = urllib2.urlopen(request)

            response_data = response_obj.read()
            rsp = json.loads(response_data)
        except urllib2.HTTPError as e:
            response_data = e.read()
            rsp = json.loads(response_data)
        except urllib2.URLError as e:
            rsp = {'code': e.reason, 'message': e}
        except Exception as e:
            rsp = {'code': 'UNKNOWN_ERROR',
                   "message": _LE('Error: %s') % e}

        LOG.info(_LI('Got response: %s') % rsp)

        if 'code' in rsp:
            raise NexentaJSONException(rsp['message'])
        return rsp['response']
