# Copyright 2026 DDN, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""VMstore REST API client for Cinder driver."""

import hashlib
import json
import posixpath
from urllib import parse as urlparse

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import netutils
import requests

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.vmstore import nfs

LOG = logging.getLogger(__name__)

ASYNC_WAIT = 0.25


class VmstoreException(exception.VolumeDriverException):
    """Exception class for VMstore driver errors."""

    def __init__(self, data=None, **kwargs):
        defaults = {
            'typeId': 'VmstoreError',
            'code': 'ERR_API',
            'source': 'CinderDriver',
            'message': 'Unknown error',
            'causeDetails': 'No details'
        }
        if isinstance(data, dict):
            for key in defaults:
                if key in kwargs:
                    continue
                if key in data:
                    kwargs[key] = data[key]
                else:
                    kwargs[key] = defaults[key]
        elif isinstance(data, str):
            if 'causeDetails' not in kwargs:
                kwargs['causeDetails'] = data
        for key in defaults:
            if key not in kwargs:
                kwargs[key] = defaults[key]
        message = ('%(causeDetails)s (source: %(source)s, '
                   'typeId: %(typeId)s, code: %(code)s)') % kwargs
        self.code = kwargs['code']
        del kwargs['causeDetails']
        super(VmstoreException, self).__init__(message)


class VmstoreRequest(object):
    def __init__(self, proxy, method):
        self.proxy = proxy
        self.method = method
        self.attempts = proxy.retries + 1
        self.refresh_attempts = proxy.refresh_retries + 1
        self.payload = None
        self.error = None
        self.path = None
        self.time = 0
        self.wait = 0
        self.data = []
        self.stat = {}
        self.hooks = {
            'response': self.hook
        }
        self.kwargs = {
            'hooks': self.hooks,
            'timeout': self.proxy.timeout
        }

    def __call__(self, path, payload=None):
        info = '%(method)s %(url)s %(payload)s' % {
            'method': self.method,
            'url': self.proxy.url(path),
            'payload': payload
        }
        LOG.debug('Start request: %(info)s', {'info': info})
        self.path = path
        self.payload = payload
        attempts = self.attempts
        if path == 'cinder/host/refresh':
            attempts = self.refresh_attempts
        for attempt in range(attempts):
            if self.error:
                self.delay(attempt)
                if not self.proxy.update_host():
                    continue
                LOG.debug('Retry request %(info)s after %(attempt)s '
                          'failed attempts, maximum retry attempts '
                          '%(attempts)s, reason: %(error)s',
                          {'info': info, 'attempt': attempt,
                           'attempts': attempts,
                           'error': self.error})
            self.data = []
            try:
                response = self.request(self.method, self.path, self.payload)
            except Exception as error:
                if isinstance(error, VmstoreException):
                    self.error = error
                else:
                    code = 'RESOURCE_NOT_FOUND'
                    message = str(error)
                    self.error = VmstoreException(message, code=code)
                if 'cinder/host/refresh' in response.request.url:
                    raise self.error
                else:
                    LOG.error('Failed request %(info)s: %(error)s',
                              {'info': info, 'error': self.error})
                continue
            count = sum(self.stat.values())
            if 'v310/appliance' not in response.request.url:
                LOG.debug('Finish request %(info)s, '
                          'response time: %(time)s seconds, '
                          'wait time: %(wait)s seconds, '
                          'requests count: %(count)s, '
                          'requests statistics: %(stat)s, '
                          'response content: %(content)s',
                          {'info': info, 'time': self.time,
                           'wait': self.wait, 'count': count,
                           'stat': self.stat,
                           'content': response.content})
            content = None
            if response.content:
                content = json.loads(response.content)
            if not response.ok:
                if (content.get('message') and
                        'does not exist' in content['message']):
                    code = 'RESOURCE_NOT_FOUND'
                    message = str(content['message'])
                    raise VmstoreException(message, code=code)
                if 'cinder/host/refresh' in response.request.url:
                    return VmstoreException(content)
                elif 'live VM is still present' in content.get('causeDetails'):
                    LOG.info(
                        'Could not delete snapshot with existing clones, '
                        'will be cleaned up when the parent volume is deleted')
                else:
                    LOG.error('Failed request %(info)s, '
                              'response content: %(content)s',
                              {'info': info, 'content': content})
                self.error = VmstoreException(content)
                continue
            is_created = response.status_code == requests.codes.created
            if is_created and 'items' in content:
                return content['items']
            if isinstance(content, dict) and 'items' in content:
                return self.data
            return content
        LOG.error('Failed request %(info)s, '
                  'reached maximum retry attempts: '
                  '%(attempts)s, reason: %(error)s',
                  {'info': info, 'attempts': attempts,
                   'error': self.error})
        raise self.error

    def request(self, method, path, payload):
        if self.method not in ['get', 'delete', 'put', 'post']:
            code = 'INVALID_ARGUMENT'
            message = (_('Request method %(method)s not supported')
                       % {'method': self.method})
            raise VmstoreException(code=code, message=message)
        if not path:
            code = 'INVALID_ARGUMENT'
            message = _('Request path is required')
            raise VmstoreException(code=code, message=message)
        url = self.proxy.url(path)
        kwargs = dict(self.kwargs)
        if payload:
            if method in ['put', 'post']:
                kwargs['data'] = json.dumps(payload)
        return self.proxy.session.request(method, url, **kwargs)

    def hook(self, response, **kwargs):
        info = (_('session request %(method)s %(url)s %(body)s '
                  'and session response %(code)s %(content)s')
                % {'method': response.request.method,
                   'url': response.request.url,
                   'body': response.request.body,
                   'code': response.status_code,
                   'content': response.content})
        if 'v310/appliance' not in response.request.url:
            LOG.debug('Start request hook on %(info)s', {'info': info})
        if response.status_code not in self.stat:
            self.stat[response.status_code] = 0
        self.stat[response.status_code] += 1
        self.time += response.elapsed.total_seconds()
        attempt = self.stat[response.status_code]
        limit = self.attempts
        if response.ok and not response.content:
            return response
        try:
            content = json.loads(response.content)
        except (TypeError, ValueError) as error:
            code = 'INVALID_ARGUMENT'
            message = (_('Failed request hook on %(info)s: '
                         'JSON parser error: %(error)s')
                       % {'info': info, 'error': error})
            raise VmstoreException(code=code, message=message)
        if response.ok and (content is None or content == 0):
            return response
        if attempt > limit and not response.ok:
            return response
        method = 'get'
        if response.status_code == requests.codes.unauthorized:
            if not self.auth():
                raise VmstoreException(content)
            request = response.request.copy()
            request.headers.update(self.proxy.session.headers)
            return self.proxy.session.send(request, **kwargs)
        elif response.status_code == requests.codes.not_found:
            if (response.request.method == 'DELETE' and
                    'Failed to lookup' in content.get('causeDetails')):
                message = content.get('causeDetails')
                LOG.info('Did not find volume, ok for delete: %s', message)
                response.status_code = 200
            return response
        elif response.status_code == requests.codes.server_error:
            if 'code' in content and content['code'] == 'RESOURCE_BUSY':
                raise VmstoreException(content)
            return response
        elif response.status_code == requests.codes.ok:
            if 'items' not in content or not content['items']:
                if 'v310/appliance' not in response.request.url:
                    LOG.debug('Finish request hook on %(info)s: '
                              'non-paginated content',
                              {'info': info})
                return response
            data = content['items']
            count = len(data)
            LOG.debug('Continue request hook on %(info)s: '
                      'add %(count)s data items to response',
                      {'info': info, 'count': count})
            if 'token' not in data:
                for item in data:
                    self.data.append(item)
            path, payload = self.parse(content, 'next')
            if not path:
                LOG.debug('Finish request hook on %(info)s: '
                          'no next page found',
                          {'info': info})
                return response
            if self.payload:
                payload.update(self.payload)
            LOG.debug('Continue request hook with new request '
                      '%(method)s %(path)s %(payload)s',
                      {'method': method, 'path': path,
                       'payload': payload})
            return self.request(method, path, payload)

        if 'v310/appliance' not in response.request.url:
            LOG.debug('Finish request hook on %(info)s',
                      {'info': info})
        return response

    def auth(self):
        method = 'post'
        path = '/session/login'
        payload = {
            'username': self.proxy.username,
            "typeId": ("com.tintri.api.rest.vcommon.dto.rbac."
                       "RestApiCredentials"),
            'password': self.proxy.password
        }
        self.proxy.delete_bearer()
        response = self.request(method, path, payload)
        if 'JSESSIONID' in response.cookies:
            token = response.cookies['JSESSIONID']
            if token:
                self.proxy.update_token(token)
                return True
        return False

    def delay(self, attempt, sync=True):
        self.wait += self.proxy.delay(attempt, sync)

    @staticmethod
    def parse(content, name):
        if 'links' in content:
            links = content['links']
            if isinstance(links, list):
                for link in links:
                    if (isinstance(link, dict) and
                            'href' in link and
                            'rel' in link and
                            link['rel'] == name):
                        url = urlparse.urlparse(link['href'])
                        payload = urlparse.parse_qs(url.query)
                        return url.path, payload
        return None, None


class VmstoreCollections(object):
    def __init__(self, proxy):
        self.proxy = proxy
        self.namespace = 'vmstore'
        self.prefix = 'instance'
        self.root = '/collections'
        self.subj = 'collection'
        self.properties = []

    def path(self, name):
        quoted_name = urlparse.quote_plus(name)
        return posixpath.join(self.root, quoted_name)

    def key(self, name):
        return '%s:%s_%s' % (self.namespace, self.prefix, name)

    def get(self, payload):
        LOG.debug('Get properties of %(subj)s %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = self.root
        return self.proxy.get(path, payload)

    def set(self, payload=None):
        LOG.debug('Modify properties of %(subj)s %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = self.root
        return self.proxy.put(path, payload)

    def list(self, payload=None):
        LOG.debug('Getting list of %(subj)s: %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = self.root
        return self.proxy.get(path, payload)

    def create(self, payload=None):
        LOG.debug('Create %(subj)s: %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = self.root
        try:
            return self.proxy.post(path, payload)
        except VmstoreException as error:
            if error.code != 'RESOURCE_EXIST':
                raise

    def delete(self, payload):
        LOG.debug('Delete %(subj)s %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = self.path(payload)
        try:
            return self.proxy.delete(path, payload)
        except VmstoreException as error:
            if error.code == 'RESOURCE_NOT_FOUND':
                LOG.debug('Resource not found during delete, treating as '
                          'success: %(payload)s', {'payload': payload})
                return
            raise


class VmstoreClones(VmstoreCollections):
    def __init__(self, proxy):
        super(VmstoreClones, self).__init__(proxy)
        self.root = 'cinder/clone'
        self.subj = 'Clones'


class VmstoreVirtualDisks(VmstoreCollections):
    def __init__(self, proxy):
        super(VmstoreVirtualDisks, self).__init__(proxy)
        self.root = 'virtualDisk'
        self.subj = 'VirtualDisk'

    def get(self, uuid):
        path = '%s?uuid=%s' % (self.root, uuid)
        return self.proxy.get(path)


class VmstoreSnapshots(VmstoreCollections):
    def __init__(self, proxy):
        super(VmstoreSnapshots, self).__init__(proxy)
        self.root = 'snapshot'
        self.subj = 'VolumeSnapshot'

    def create(self, payload=None):
        LOG.debug('Create %(subj)s: %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        path = posixpath.join('cinder', self.root)
        try:
            return self.proxy.post(path, payload)
        except VmstoreException as error:
            if error.code != 'RESOURCE_EXIST':
                raise


class VmstoreAppliance(VmstoreCollections):
    def __init__(self, proxy):
        super(VmstoreAppliance, self).__init__(proxy)
        self.root = 'appliance'
        self.subj = 'appliance'


class VmstoreCinderRefresh(VmstoreCollections):
    def __init__(self, proxy):
        super(VmstoreCinderRefresh, self).__init__(proxy)
        self.root = 'cinder/host/refresh'
        self.subj = 'cinderRefresh'


class VmstoreProxy(object):
    def __init__(
            self, proto, backend, conf):
        self.clones = VmstoreClones(self)
        self.virtual_disk = VmstoreVirtualDisks(self)
        self.snapshots = VmstoreSnapshots(self)
        self.appliance = VmstoreAppliance(self)
        self.cinder_refresh = VmstoreCinderRefresh(self)
        self.version = None
        self.lock = None
        client_version = (
            'Tintri-Cinder-Driver-%s' % nfs.VmstoreNfsDriver.VERSION)
        self.headers = {
            'Content-Type': 'application/json',
            'X-XSS-Protection': '1',
            'Tintri-Api-Client': client_version
        }
        self.scheme = conf.vmstore_rest_protocol
        self.host = conf.vmstore_rest_address
        self.port = conf.vmstore_rest_port
        self.username = conf.vmstore_user
        self.password = conf.vmstore_password
        self.backend = backend
        self.retries = conf.vmstore_rest_retry_count
        self.refresh_retries = conf.vmstore_refresh_retry_count
        self.backoff = conf.vmstore_rest_backoff_factor
        self.timeout = (conf.vmstore_rest_connect_timeout,
                        conf.vmstore_rest_read_timeout)
        self.session = requests.Session()
        self.session.verify = conf.driver_ssl_cert_verify
        self.session.auth = (self.username, self.password)
        if self.session.verify and conf.driver_ssl_cert_path:
            self.session.verify = conf.driver_ssl_cert_path
        self.session.headers.update(self.headers)
        if not conf.driver_ssl_cert_verify:
            requests.packages.urllib3.disable_warnings()
        self.token = ""
        self.update_lock()

    def __getattr__(self, name):
        return VmstoreRequest(self, name)

    def delete_bearer(self):
        if 'Authorization' in self.session.headers:
            del self.session.headers['Authorization']

    def update_bearer(self, token):
        bearer = 'JSESSIONID=%s' % token
        self.session.headers['cookie'] = bearer

    def update_token(self, token):
        self.token = token
        self.update_bearer(token)

    def update_host(self):
        self.update_lock()
        self.update_bearer(self.token)

    def update_lock(self):
        try:
            uuid = self.get('appliance')[0]['uuid']
        except Exception:
            return False

        lock = '%s:%s' % (uuid, self.project)
        lock = lock.encode('utf-8')
        self.lock = hashlib.md5(lock, usedforsecurity=False).hexdigest()
        LOG.info('Coordination lock for group %(backend)s: %(lock)s',
                 {'backend': self.backend, 'lock': self.lock})
        return True

    def url(self, path=None):
        if not path:
            path = ''
        host = netutils.escape_ipv6(self.host)
        netloc = '%s:%d/api/v310' % (host, self.port)
        components = (self.scheme, netloc, path, None, None)
        url = urlparse.urlunsplit(components)
        return url

    def delay(self, attempt, sync=True):
        backoff = self.backoff
        if not sync:
            backoff = ASYNC_WAIT
        if self.retries > 0:
            attempt %= self.retries
            if attempt == 0:
                attempt = self.retries
        interval = float(backoff * (2 ** (attempt - 1)))
        LOG.debug('Waiting for %(interval)s seconds',
                  {'interval': interval})
        greenthread.sleep(interval)
        return interval
