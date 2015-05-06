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
import time
import urllib2

from oslo_log import log as logging
from oslo_serialization import jsonutils

from cinder.i18n import _
from cinder.volume.drivers import nexenta

LOG = logging.getLogger(__name__)


class NexentaJSONException(nexenta.NexentaException):
    pass


class NexentaJSONProxy(object):

    def __init__(self, scheme, host, port, user, password, auto=False):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.auto = True

    @property
    def url(self):
        return '%s://%s:%s/' % (self.scheme, self.host, self.port)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'NEF proxy: %s' % self.url

    def __call__(self, path, data=None, method=None):
        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % auth
        }
        LOG.debug('Sending JSON data: %s', data)
        url = self.url + path
        if data:
            data = jsonutils.dumps(data)
        try:
            request = urllib2.Request(url, data, headers)
            if method:
                request.get_method = lambda: method
            response_obj = urllib2.urlopen(request)
            response_data = response_obj.read()
        except urllib2.HTTPError as error:
            raise NexentaJSONException(_(error.read()))
        if response_obj.code in (200, 201) and not response_data:
            return 'Success'
        if response_data and response_obj.code == 202:
            response = jsonutils.loads(response_data)
            url = self.url + response['links'][0]['href']
            while response_obj.code == 202:
                try:
                    time.sleep(1)
                    request = urllib2.Request(url, None, headers)
                    response_obj = urllib2.urlopen(request)
                    response_data = response_obj.read()
                except urllib2.HTTPError as error:
                    raise NexentaJSONException(_(error.read()))
                if response_obj.code in (200, 201) and not response_data:
                    return 'Success'
        LOG.debug('Got response: %s', response_data)
        response = jsonutils.loads(response_data)
        return response
