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

import json
import requests
import time

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.utils import retry
from oslo_serialization import jsonutils
from requests.cookies import extract_cookies_to_jar
from requests.packages.urllib3 import exceptions

LOG = logging.getLogger(__name__)
TIMEOUT = 60

requests.packages.urllib3.disable_warnings(exceptions.InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(
    exceptions.InsecurePlatformWarning)


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
        kwargs = {'timeout': TIMEOUT, 'verify': self.__proxy.verify}
        data = None
        if len(args) > 1:
            kwargs['json'] = args[1]
            data = args[1]

        LOG.debug('Issuing call to NS: %s %s, data: %s',
                  url, self.__method, data)

        try:
            response = getattr(
                self.__proxy.session, self.__method)(url, **kwargs)
        except requests.exceptions.ConnectionError:
            LOG.warning(_LW("ConnectionError on call to NS: %(url)s"
                            " %(method)s, data: %(data)s"),
                        self.__proxy.url, self.__method, data)
            self.handle_failover()
            url = self.get_full_url(args[0])
            response = getattr(
                self.__proxy.session, self.__method)(url, **kwargs)
        try:
            check_error(response)
        except exception.NexentaException as exc:
            if exc.kwargs['message']['code'] == 'ENOENT':
                LOG.warning(_LW("NexentaException on call to NS:"
                                " %(url)s %(method)s, data: %(data)s,"
                                " returned message: %s"),
                            url, self.__method, data, exc.kwargs['message'])
                self.handle_failover()
                url = self.get_full_url(args[0])
                response = getattr(
                    self.__proxy.session, self.__method)(url, **kwargs)
            else:
                raise
        check_error(response)
        content = json.loads(response.content) if response.content else None
        LOG.debug("Got response: %(code)s %(reason)s %(content)s", {
            'code': response.status_code,
            'reason': response.reason,
            'content': content})

        if response.status_code == 202 and content:
            url = self.get_full_url(content['links'][0]['href'])
            keep_going = True
            while keep_going:
                time.sleep(1)
                response = self.__proxy.session.get(
                    url, verify=self.__proxy.verify)
                try:
                    check_error(response)
                except exception.NexentaException as exc:
                    if exc.kwargs['message']['code'] == 'ENOENT':
                        LOG.debug(
                            'NexentaException on call to NS: %s %s, data: %s'
                            'returned message: %s',
                            url, self.__method, data, exc.kwargs['message'])
                        self.handle_failover()
                        url = self.get_full_url(args[0])
                        response = getattr(
                            self.__proxy.session, self.__method)(url, **kwargs)
                    else:
                        raise
                LOG.debug("Got response: %(code)s %(reason)s", {
                    'code': response.status_code,
                    'reason': response.reason})
                content = response.json() if response.content else None
                keep_going = response.status_code == 202
        return content

    def handle_failover(self):
        if self.__proxy.backup:
            LOG.info('Server %s is unavailable, failing over to %s',
                     self.__proxy.host, self.__proxy.backup)
            host = '%s,%s' % (self.__proxy.backup, self.__proxy.host)
            self.__proxy.__init__(
                host, self.__proxy.port, self.__proxy.user,
                self.__proxy.password, self.__proxy.use_https,
                self.__proxy.verify)
        else:
            raise


class HTTPSAuth(requests.auth.AuthBase):

    def __init__(self, url, username, password, verify):
        self.url = url
        self.username = username
        self.password = password
        self.token = None
        self.verify = verify

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
            LOG.debug('Got [401]. Trying to reauth...')
            self.token = self.https_auth()
            # Consume content and release the original connection
            # to allow our new request to reuse the same one.
            r.content
            r.close()
            prep = r.request.copy()
            extract_cookies_to_jar(prep._cookies, r.request, r.raw)
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
        LOG.debug('Sending auth request to %s.', self.url)
        url = '/'.join((self.url, 'auth/login'))
        headers = {'Content-Type': 'application/json'}
        data = {'username': self.username, 'password': self.password}
        response = requests.post(url, json=data, verify=self.verify,
                                 headers=headers, timeout=TIMEOUT)
        content = json.loads(response.content) if response.content else None
        LOG.debug("NS auth response: %(code)s %(reason)s %(content)s", {
            'code': response.status_code,
            'reason': response.reason,
            'content': content})
        check_error(response)
        response.close()
        if response.content:
            token = content['token']
            del content['token']
            return token
        raise exception.VolumeBackendAPIException(
            data=_(
                'Got bad response: %(code)s %(reason)s') % {
                    'code': response.status_code, 'reason': response.reason})


class NexentaJSONProxy(object):

    def __init__(self, host, port, user, password, use_https, verify):
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.user = user
        self.verify = verify
        self.password = password
        self.use_https = use_https
        parts = host.split(',')
        self.host = parts[0].strip()
        self.backup = parts[1].strip() if len(parts) > 1 else None
        if use_https:
            self.scheme = 'https'
            self.port = port if port else 8443
            self.session.auth = HTTPSAuth(self.url, user, password, verify)
        else:
            self.scheme = 'http'
            self.port = port if port else 8080
            self.session.auth = (user, password)

    @property
    def url(self):
        return '{}://{}:{}'.format(self.scheme, self.host, self.port)

    def __getattr__(self, name):
        if name in ('get', 'post', 'put', 'delete'):
            return RESTCaller(self, name)
        return super(NexentaJSONProxy, self).__getattribute__(name)

    def __repr__(self):
        return 'HTTP JSON proxy: %s' % self.url
