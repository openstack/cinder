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
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
.. moduleauthor:: Victor Rodionov <victor.rodionov@nexenta.com>
"""

import urllib
import urllib2

from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging
from cinder.volume.drivers import nexenta

LOG = logging.getLogger(__name__)


class NexentaJSONException(nexenta.NexentaException):
    pass


class NexentaJSONProxy(object):

    def __init__(self, protocol, host, port, path, user, password, auto=False,
                 obj=None, method=None):
        self.protocol = protocol.lower()
        self.host = host
        self.port = port
        self.path = path
        self.user = user
        self.password = password
        self.auto = auto
        self.obj = obj
        self.method = method

    def __getattr__(self, name):
        if not self.obj:
            obj, method = name, None
        elif not self.method:
            obj, method = self.obj, name
        else:
            obj, method = '%s.%s' % (self.obj, self.method), name
        return NexentaJSONProxy(self.protocol, self.host, self.port, self.path,
                                self.user, self.password, self.auto, obj,
                                method)

    @property
    def url(self):
        return '%s://%s:%s%s' % (self.protocol, self.host, self.port, self.path)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url

    def __call__(self, *args):
        data = jsonutils.dumps({
            'object': self.obj,
            'method': self.method,
            'params': args
        })
        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }
        LOG.debug('Sending JSON data: %s', data)
        request = urllib2.Request(self.url, data, headers)
        response_obj = urllib2.urlopen(request)
        if response_obj.info().status == 'EOF in headers':
            if not self.auto or self.protocol != 'http':
                LOG.error(_('No headers in server response'))
                raise NexentaJSONException(_('Bad response from server'))
            LOG.info(_('Auto switching to HTTPS connection to %s'), self.url)
            self.protocol = 'https'
            request = urllib2.Request(self.url, data, headers)
            response_obj = urllib2.urlopen(request)

        response_data = response_obj.read()
        LOG.debug('Got response: %s', response_data)
        response = jsonutils.loads(response_data)
        if response.get('error') is not None:
            raise NexentaJSONException(response['error'].get('message', ''))
        return response.get('result')

class NexentaEdgeResourceProxy(object):

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
        return '%s://%s:%s%s' % (self.protocol, self.host, self.port, self.path)

    def __getattr__(self, name):
        if not self.method:
            method = name
        else:
            raise Exception("Wrong resource call syntax")
        return NexentaEdgeResourceProxy(self.protocol, self.host, self.port, self.path,
                                self.user, self.password, self.auto, method)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'HTTP Resource proxy: %s' % self.url

    def __call__(self, *args):
        d = None
        self.path += args[0]

        if len(args) > 1:
            if self.method == 'delete':
                self.path += '/' + args[1]
            elif self.method == 'get':
                self.path += '?' + urllib.urlencode(args[1])
            else:
                d = args[1]

        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }

        LOG.debug('Sending JSON data: %s', self.url)

        #
        # urllib2 will use POST if data is provided, otherwise it'll be GET
        #
        data = None
        if d:
            data = jsonutils.dumps(d)

        try:
            request = urllib2.Request(self.url, data, headers)
            if self.method == 'delete':
                request.get_method = lambda: 'DELETE'
            response_obj = urllib2.urlopen(request)

            #
            # Handle 'auto' switch mode.. from HTTP to HTTPS
            #
            if response_obj.info().status == 'EOF in headers':
                if not self.auto or self.protocol != 'http':
                    LOG.error(_('No headers in server response'))
                    raise NexentaJSONException(_('Bad response from server'))
                LOG.info(_('Auto switching to HTTPS connection to %s'), self.url)
                self.protocol = 'https'
                request = urllib2.Request(self.url, data, headers)
                if self.method == 'delete':
                    request.get_method = lambda: 'DELETE'
                response_obj = urllib2.urlopen(request)

            response_data = response_obj.read()
            rsp = jsonutils.loads(response_data)
        except urllib2.HTTPError, e:
            response_data = e.read()
            rsp = jsonutils.loads(response_data)
        except urllib2.URLError, e:
            rsp = { 'code' : str(e.reason), 'message' : str(e) }
        except Exception, e:
            rsp = { 'code' : 'UNKNOWN_ERROR',
                "message" : _("Received Unknown Error from the backend") }

        LOG.debug('Got response: %s', rsp)

        if rsp.has_key('code'):
            raise NexentaJSONException(rsp['message'])
        return rsp['response']
