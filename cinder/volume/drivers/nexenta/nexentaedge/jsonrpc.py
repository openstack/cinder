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

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry

LOG = logging.getLogger(__name__)
TIMEOUT = 60


class NexentaEdgeJSONProxy(object):

    retry_exc_tuple = (
        requests.exceptions.ConnectionError,
        requests.exceptions.ConnectTimeout
    )

    def __init__(self, protocol, host, port, path, user, password, verify,
                 auto=False, method=None, session=None):
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.auth = (user, password)
            self.session.headers.update({'Content-Type': 'application/json'})
        self.protocol = protocol.lower()
        self.verify = verify
        self.host = host
        self.port = port
        self.path = path
        self.user = user
        self.password = password
        self.auto = auto
        self.method = method

    @property
    def url(self):
        return '%s://%s:%s/%s' % (
            self.protocol, self.host, self.port, self.path)

    def __getattr__(self, name):
        if name in ('get', 'post', 'put', 'delete'):
            return NexentaEdgeJSONProxy(
                self.protocol, self.host, self.port, self.path, self.user,
                self.password, self.verify, self.auto, name, self.session)
        return super(NexentaEdgeJSONProxy, self).__getattr__(name)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url

    @retry(retry_exc_tuple, interval=1, retries=6)
    def __call__(self, *args):
        self.path = args[0]
        kwargs = {'timeout': TIMEOUT, 'verify': self.verify}
        data = None
        if len(args) > 1:
            data = json.dumps(args[1])
            kwargs['data'] = data

        LOG.debug('Sending JSON data: %s, method: %s, data: %s',
                  self.url, self.method, data)

        func = getattr(self.session, self.method)
        if func:
            req = func(self.url, **kwargs)
        else:
            raise exception.VolumeDriverException(
                message=_('Unsupported method: %s') % self.method)

        rsp = req.json()

        LOG.debug('Got response: %s', rsp)
        if rsp.get('response') is None:
            raise exception.VolumeBackendAPIException(
                data=_('Error response: %s') % rsp)
        return rsp.get('response')
