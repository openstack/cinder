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

import urllib2

from cinder.i18n import _
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging
from cinder.volume.drivers import nexenta

LOG = logging.getLogger(__name__)


class NexentaJSONException(nexenta.NexentaException):
    pass


class NexentaJSONProxy(object):

    def __init__(self, scheme, host, port, path, user, password, auto=False,
                 obj=None, method=None):
        self.scheme = scheme.lower()
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
        return NexentaJSONProxy(self.scheme, self.host, self.port, self.path,
                                self.user, self.password, self.auto, obj,
                                method)

    @property
    def url(self):
        return '%s://%s:%s%s' % (self.scheme, self.host, self.port, self.path)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'NMS proxy: %s' % self.url

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
            if not self.auto or self.scheme != 'http':
                LOG.error(_('No headers in server response'))
                raise NexentaJSONException(_('Bad response from server'))
            LOG.info(_('Auto switching to HTTPS connection to %s'), self.url)
            self.scheme = 'https'
            request = urllib2.Request(self.url, data, headers)
            response_obj = urllib2.urlopen(request)

        response_data = response_obj.read()
        LOG.debug('Got response: %s', response_data)
        response = jsonutils.loads(response_data)
        if response.get('error') is not None:
            raise NexentaJSONException(response['error'].get('message', ''))
        return response.get('result')
