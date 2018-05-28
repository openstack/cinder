# Copyright 2018 Nexenta Systems, Inc.
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

from oslo_log import log as logging
from oslo_serialization import jsonutils
import requests
from requests.packages.urllib3 import exceptions

from cinder import exception
from cinder.utils import retry

LOG = logging.getLogger(__name__)
TIMEOUT = 60
NMS_PLUGINS = {
    'rrdaemon_plugin': 'nms-rrdaemon',
    'rsf_plugin': 'nms-rsf-cluster'
}

requests.packages.urllib3.disable_warnings(exceptions.InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(
    exceptions.InsecurePlatformWarning)

class NexentaJSONProxy(object):

    retry_exc_tuple = (requests.exceptions.ConnectionError,)

    def __init__(self, scheme, host, port, path, user, password, verify,
                 auto=False, obj=None, method=None, session=None):
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.auth = (user, password)
            self.session.headers.update({'Content-Type': 'application/json'})
        self.scheme = scheme.lower()
        self.host = host
        self.port = port
        self.verify = verify
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
                                self.user, self.password, self.verify,
                                self.auto, obj, method, self.session)

    @property
    def url(self):
        return '%s://%s:%s%s' % (self.scheme, self.host, self.port, self.path)

    def __hash__(self):
        return self.url.__hash__()

    def __repr__(self):
        return 'NMS proxy: %s' % self.url

    @retry(retry_exc_tuple, retries=6)
    def __call__(self, *args):
        if self.obj in NMS_PLUGINS:
            kind, name = 'plugin', NMS_PLUGINS[self.obj]
        else:
            kind, name = 'object', self.obj

        data = jsonutils.dumps({
            kind: name,
            'method': self.method,
            'params': args
        })

        LOG.debug('Sending JSON data: %s', data)
        r = self.session.post(self.url, data=data, timeout=TIMEOUT,
                              verify=self.verify)
        response = r.json()

        LOG.debug('Got response: %s', response)
        if response.get('error') is not None:
            message = response['error'].get('message', '')
            raise exception.NexentaException(message)
        return response.get('result')
