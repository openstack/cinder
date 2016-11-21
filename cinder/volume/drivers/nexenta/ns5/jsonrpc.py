# Copyright 2016 Nexenta Systems, Inc.
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

import requests
import time

from oslo_log import log as logging
from oslo_serialization import jsonutils

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry

LOG = logging.getLogger(__name__)
TIMEOUT = 60


def check_error(response):
    code = response.status_code
    if code not in (200, 201, 202):
        reason = response.reason
        body = response.content
        try:
            content = jsonutils.loads(body) if body else None
        except ValueError:
            raise exception.VolumeBackendAPIException(
                data=_(
                    'Could not parse response: %(code)s %(reason)s '
                    '%(content)s') % {
                        'code': code, 'reason': reason, 'content': body})
        if content and 'code' in content:
            raise exception.NexentaException(content)
        raise exception.VolumeBackendAPIException(
            data=_(
                'Got bad response: %(code)s %(reason)s %(content)s') % {
                    'code': code, 'reason': reason, 'content': content})


class RESTCaller(object):

    retry_exc_tuple = (
        requests.exceptions.ConnectionError,
        requests.exceptions.ConnectTimeout
    )

    def __init__(self, proxy, method):
        self.__proxy = proxy
        self.__method = method

    def get_full_url(self, path):
        return '/'.join((self.__proxy.url, path))

    @retry(retry_exc_tuple, interval=1, retries=6)
    def __call__(self, *args):
        url = self.get_full_url(args[0])
        kwargs = {'timeout': TIMEOUT, 'verify': False}
        data = None
        if len(args) > 1:
            data = args[1]
            kwargs['json'] = data

        LOG.debug('Sending JSON data: %s, method: %s, data: %s',
                  url, self.__method, data)

        response = getattr(self.__proxy.session, self.__method)(url, **kwargs)
        check_error(response)
        content = (jsonutils.loads(response.content)
                   if response.content else None)
        LOG.debug("Got response: %(code)s %(reason)s %(content)s", {
            'code': response.status_code,
            'reason': response.reason,
            'content': content})

        if response.status_code == 202 and content:
            url = self.get_full_url(content['links'][0]['href'])
            keep_going = True
            while keep_going:
                time.sleep(1)
                response = self.__proxy.session.get(url, verify=False)
                check_error(response)
                LOG.debug("Got response: %(code)s %(reason)s", {
                    'code': response.status_code,
                    'reason': response.reason})
                content = response.json() if response.content else None
                keep_going = response.status_code == 202
        return content


class HTTPSAuth(requests.auth.AuthBase):

    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        self.token = None

    def __eq__(self, other):
        return all([
            self.url == getattr(other, 'url', None),
            self.username == getattr(other, 'username', None),
            self.password == getattr(other, 'password', None),
            self.token == getattr(other, 'token', None)
        ])

    def __ne__(self, other):
        return not self == other

    def handle_401(self, r, **kwargs):
        if r.status_code == 401:
            LOG.debug('Got 401. Trying to reauth...')
            self.token = self.https_auth()
            # Consume content and release the original connection
            # to allow our new request to reuse the same one.
            r.content
            r.close()
            prep = r.request.copy()
            requests.cookies.extract_cookies_to_jar(
                prep._cookies, r.request, r.raw)
            prep.prepare_cookies(prep._cookies)

            prep.headers['Authorization'] = 'Bearer %s' % self.token
            _r = r.connection.send(prep, **kwargs)
            _r.history.append(r)
            _r.request = prep

            return _r
        return r

    def __call__(self, r):
        if not self.token:
            self.token = self.https_auth()
        r.headers['Authorization'] = 'Bearer %s' % self.token
        r.register_hook('response', self.handle_401)
        return r

    def https_auth(self):
        LOG.debug('Sending auth request...')
        url = '/'.join((self.url, 'auth/login'))
        headers = {'Content-Type': 'application/json'}
        data = {'username': self.username, 'password': self.password}
        response = requests.post(url, json=data, verify=False,
                                 headers=headers, timeout=TIMEOUT)
        check_error(response)
        response.close()
        if response.content:
            content = jsonutils.loads(response.content)
            token = content['token']
            del content['token']
            LOG.debug("Got response: %(code)s %(reason)s %(content)s", {
                'code': response.status_code,
                'reason': response.reason,
                'content': content})
            return token
        raise exception.VolumeBackendAPIException(
            data=_(
                'Got bad response: %(code)s %(reason)s') % {
                    'code': response.status_code, 'reason': response.reason})


class NexentaJSONProxy(object):

    def __init__(self, host, port, user, password, use_https):
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.host = host
        if use_https:
            self.scheme = 'https'
            self.port = port if port else 8443
            self.session.auth = HTTPSAuth(self.url, user, password)
        else:
            self.scheme = 'http'
            self.port = port if port else 8080
            self.session.auth = (user, password)

    @property
    def url(self):
        return '%(scheme)s://%(host)s:%(port)s' % {
            'scheme': self.scheme,
            'host': self.host,
            'port': self.port}

    def __getattr__(self, name):
        if name in ('get', 'post', 'put', 'delete'):
            return RESTCaller(self, name)
        return super(NexentaJSONProxy, self).__getattribute__(name)

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url
