# Copyright 2019 Nexenta Systems, Inc.
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
import posixpath

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils.secretutils import md5
import requests
import six

from cinder import exception
from cinder.i18n import _

LOG = logging.getLogger(__name__)


class NefException(exception.VolumeDriverException):
    def __init__(self, data=None, **kwargs):
        defaults = {
            'name': 'NexentaError',
            'code': 'EBADMSG',
            'source': 'CinderDriver',
            'message': 'Unknown error'
        }
        if isinstance(data, dict):
            for key in defaults:
                if key in kwargs:
                    continue
                if key in data:
                    kwargs[key] = data[key]
                else:
                    kwargs[key] = defaults[key]
        elif isinstance(data, six.string_types):
            if 'message' not in kwargs:
                kwargs['message'] = data
        for key in defaults:
            if key not in kwargs:
                kwargs[key] = defaults[key]
        message = (_('%(message)s (source: %(source)s, '
                     'name: %(name)s, code: %(code)s)')
                   % kwargs)
        self.code = kwargs['code']
        del kwargs['message']
        super(NefException, self).__init__(message, **kwargs)


class NefRequest(object):
    def __init__(self, proxy, method):
        self.proxy = proxy
        self.method = method
        self.path = None
        self.lock = False
        self.time = 0
        self.data = []
        self.payload = {}
        self.stat = {}
        self.hooks = {
            'response': self.hook
        }
        self.kwargs = {
            'hooks': self.hooks,
            'timeout': self.proxy.timeout
        }

    def __call__(self, path, payload=None):
        LOG.debug('NEF request start: %(method)s %(path)s %(payload)s',
                  {'method': self.method, 'path': path, 'payload': payload})
        if self.method not in ['get', 'delete', 'put', 'post']:
            message = (_('NEF API does not support %(method)s method')
                       % {'method': self.method})
            raise NefException(code='EINVAL', message=message)
        if not path:
            message = _('NEF API call requires collection path')
            raise NefException(code='EINVAL', message=message)
        self.path = path
        if payload:
            if not isinstance(payload, dict):
                message = _('NEF API call payload must be a dictionary')
                raise NefException(code='EINVAL', message=message)
            if self.method in ['get', 'delete']:
                self.payload = {'params': payload}
            elif self.method in ['put', 'post']:
                self.payload = {'data': json.dumps(payload)}
        try:
            response = self.request(self.method, self.path, **self.payload)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as error:
            LOG.debug('Failed to %(method)s %(path)s %(payload)s: %(error)s',
                      {'method': self.method, 'path': self.path,
                       'payload': self.payload, 'error': error})
            if not self.failover():
                raise
            LOG.debug('Retry initial request after failover: '
                      '%(method)s %(path)s %(payload)s',
                      {'method': self.method,
                       'path': self.path,
                       'payload': self.payload})
            response = self.request(self.method, self.path, **self.payload)
        LOG.debug('NEF request done: %(method)s %(path)s %(payload)s, '
                  'total response time: %(time)s seconds, '
                  'total requests count: %(count)s, '
                  'requests statistics: %(stat)s',
                  {'method': self.method,
                   'path': self.path,
                   'payload': self.payload,
                   'time': self.time,
                   'count': sum(self.stat.values()),
                   'stat': self.stat})
        if response.ok and not response.content:
            return None
        content = json.loads(response.content)
        if not response.ok:
            raise NefException(content)
        if isinstance(content, dict) and 'data' in content:
            return self.data
        return content

    def request(self, method, path, **kwargs):
        url = self.proxy.url(path)
        LOG.debug('Perform session request: %(method)s %(url)s %(body)s',
                  {'method': method, 'url': url, 'body': kwargs})
        kwargs.update(self.kwargs)
        return self.proxy.session.request(method, url, **kwargs)

    def hook(self, response, **kwargs):
        initial_text = (_('initial request %(method)s %(path)s %(body)s')
                        % {'method': self.method,
                           'path': self.path,
                           'body': self.payload})
        request_text = (_('session request %(method)s %(url)s %(body)s')
                        % {'method': response.request.method,
                           'url': response.request.url,
                           'body': response.request.body})
        response_text = (_('session response %(code)s %(content)s')
                         % {'code': response.status_code,
                            'content': response.content})
        text = (_('%(request_text)s and %(response_text)s')
                % {'request_text': request_text,
                   'response_text': response_text})
        LOG.debug('Hook start on %(text)s', {'text': text})

        if response.status_code not in self.stat:
            self.stat[response.status_code] = 0
        self.stat[response.status_code] += 1
        self.time += response.elapsed.total_seconds()

        if response.ok and not response.content:
            LOG.debug('Hook done on %(text)s: '
                      'empty response content',
                      {'text': text})
            return response

        if not response.content:
            message = (_('There is no response content '
                         'is available for %(text)s')
                       % {'text': text})
            raise NefException(code='ENODATA', message=message)

        try:
            content = json.loads(response.content)
        except (TypeError, ValueError) as error:
            message = (_('Failed to decode JSON for %(text)s: %(error)s')
                       % {'text': text, 'error': error})
            raise NefException(code='ENOMSG', message=message)

        method = 'get'
        if response.status_code == requests.codes.unauthorized:
            if self.stat[response.status_code] > self.proxy.retries:
                raise NefException(content)
            self.auth()
            LOG.debug('Retry %(text)s after authentication',
                      {'text': request_text})
            request = response.request.copy()
            request.headers.update(self.proxy.session.headers)
            return self.proxy.session.send(request, **kwargs)
        elif response.status_code == requests.codes.not_found:
            if self.lock:
                LOG.debug('Hook done on %(text)s: '
                          'nested failover is detected',
                          {'text': text})
                return response
            if self.stat[response.status_code] > self.proxy.retries:
                raise NefException(content)
            if not self.failover():
                LOG.debug('Hook done on %(text)s: '
                          'no valid hosts found',
                          {'text': text})
                return response
            LOG.debug('Retry %(text)s after failover',
                      {'text': initial_text})
            self.data = []
            return self.request(self.method, self.path, **self.payload)
        elif response.status_code == requests.codes.server_error:
            if not (isinstance(content, dict) and
                    'code' in content and
                    content['code'] == 'EBUSY'):
                raise NefException(content)
            if self.stat[response.status_code] > self.proxy.retries:
                raise NefException(content)
            self.proxy.delay(self.stat[response.status_code])
            LOG.debug('Retry %(text)s after delay',
                      {'text': initial_text})
            self.data = []
            return self.request(self.method, self.path, **self.payload)
        elif response.status_code == requests.codes.accepted:
            path = self.getpath(content, 'monitor')
            if not path:
                message = (_('There is no monitor path '
                             'available for %(text)s')
                           % {'text': text})
                raise NefException(code='ENOMSG', message=message)
            self.proxy.delay(self.stat[response.status_code])
            return self.request(method, path)
        elif response.status_code == requests.codes.ok:
            if not (isinstance(content, dict) and 'data' in content):
                LOG.debug('Hook done on %(text)s: there '
                          'is no JSON data available',
                          {'text': text})
                return response
            LOG.debug('Append %(count)s data items to response',
                      {'count': len(content['data'])})
            self.data += content['data']
            path = self.getpath(content, 'next')
            if not path:
                LOG.debug('Hook done on %(text)s: there '
                          'is no next path available',
                          {'text': text})
                return response
            LOG.debug('Perform next session request %(method)s %(path)s',
                      {'method': method, 'path': path})
            return self.request(method, path)
        LOG.debug('Hook done on %(text)s and '
                  'returned original response',
                  {'text': text})
        return response

    def auth(self):
        method = 'post'
        path = 'auth/login'
        payload = {
            'username': self.proxy.username,
            'password': self.proxy.password
        }
        data = json.dumps(payload)
        kwargs = {'data': data}
        self.proxy.delete_bearer()
        response = self.request(method, path, **kwargs)
        content = json.loads(response.content)
        if not (isinstance(content, dict) and 'token' in content):
            message = (_('There is no authentication token available '
                         'for authentication request %(method)s %(url)s '
                         '%(body)s and response %(code)s %(content)s')
                       % {'method': response.request.method,
                          'url': response.request.url,
                          'body': response.request.body,
                          'code': response.status_code,
                          'content': response.content})
            raise NefException(code='ENODATA', message=message)
        token = content['token']
        self.proxy.update_token(token)

    def failover(self):
        result = False
        self.lock = True
        method = 'get'
        root = self.proxy.root
        for host in self.proxy.hosts:
            self.proxy.update_host(host)
            LOG.debug('Try to failover path '
                      '%(root)s to host %(host)s',
                      {'root': root, 'host': host})
            try:
                response = self.request(method, root)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as error:
                LOG.debug('Skip unavailable host %(host)s '
                          'due to error: %(error)s',
                          {'host': host, 'error': error})
                continue
            LOG.debug('Failover result: %(code)s %(content)s',
                      {'code': response.status_code,
                       'content': response.content})
            if response.status_code == requests.codes.ok:
                LOG.debug('Successful failover path '
                          '%(root)s to host %(host)s',
                          {'root': root, 'host': host})
                self.proxy.update_lock()
                result = True
                break
            else:
                LOG.debug('Skip unsuitable host %(host)s: '
                          'there is no %(root)s path found',
                          {'host': host, 'root': root})
        self.lock = False
        return result

    @staticmethod
    def getpath(content, name):
        if isinstance(content, dict) and 'links' in content:
            for link in content['links']:
                if not isinstance(link, dict):
                    continue
                if 'rel' in link and 'href' in link:
                    if link['rel'] == name:
                        return link['href']
        return None


class NefCollections(object):
    subj = 'collection'
    root = '/collections'

    def __init__(self, proxy):
        self.proxy = proxy

    def path(self, name):
        quoted_name = six.moves.urllib.parse.quote_plus(name)
        return posixpath.join(self.root, quoted_name)

    def get(self, name, payload=None):
        LOG.debug('Get properties of %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = self.path(name)
        return self.proxy.get(path, payload)

    def set(self, name, payload=None):
        LOG.debug('Modify properties of %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = self.path(name)
        return self.proxy.put(path, payload)

    def list(self, payload=None):
        LOG.debug('List of %(subj)ss: %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        return self.proxy.get(self.root, payload)

    def create(self, payload=None):
        LOG.debug('Create %(subj)s: %(payload)s',
                  {'subj': self.subj, 'payload': payload})
        try:
            return self.proxy.post(self.root, payload)
        except NefException as error:
            if error.code != 'EEXIST':
                raise

    def delete(self, name, payload=None):
        LOG.debug('Delete %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = self.path(name)
        try:
            return self.proxy.delete(path, payload)
        except NefException as error:
            if error.code != 'ENOENT':
                raise


class NefSettings(NefCollections):
    subj = 'setting'
    root = '/settings/properties'

    def create(self, payload=None):
        return NotImplemented

    def delete(self, name, payload=None):
        return NotImplemented


class NefDatasets(NefCollections):
    subj = 'dataset'
    root = '/storage/datasets'

    def rename(self, name, payload=None):
        LOG.debug('Rename %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'rename')
        return self.proxy.post(path, payload)


class NefSnapshots(NefDatasets, NefCollections):
    subj = 'snapshot'
    root = '/storage/snapshots'

    def clone(self, name, payload=None):
        LOG.debug('Clone %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'clone')
        return self.proxy.post(path, payload)


class NefVolumeGroups(NefDatasets, NefCollections):
    subj = 'volume group'
    root = 'storage/volumeGroups'

    def rollback(self, name, payload=None):
        LOG.debug('Rollback %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'rollback')
        return self.proxy.post(path, payload)


class NefVolumes(NefVolumeGroups, NefDatasets, NefCollections):
    subj = 'volume'
    root = '/storage/volumes'

    def promote(self, name, payload=None):
        LOG.debug('Promote %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'promote')
        return self.proxy.post(path, payload)


class NefFilesystems(NefVolumes, NefVolumeGroups, NefDatasets, NefCollections):
    subj = 'filesystem'
    root = '/storage/filesystems'

    def mount(self, name, payload=None):
        LOG.debug('Mount %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'mount')
        return self.proxy.post(path, payload)

    def unmount(self, name, payload=None):
        LOG.debug('Unmount %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'unmount')
        return self.proxy.post(path, payload)

    def acl(self, name, payload=None):
        LOG.debug('Set %(subj)s %(name)s ACL: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'acl')
        return self.proxy.post(path, payload)


class NefHpr(NefCollections):
    subj = 'HPR service'
    root = '/hpr'

    def activate(self, payload=None):
        LOG.debug('Activate %(payload)s',
                  {'payload': payload})
        path = posixpath.join(self.root, 'activate')
        return self.proxy.post(path, payload)

    def start(self, name, payload=None):
        LOG.debug('Start %(subj)s %(name)s: %(payload)s',
                  {'subj': self.subj, 'name': name, 'payload': payload})
        path = posixpath.join(self.path(name), 'start')
        return self.proxy.post(path, payload)


class NefServices(NefCollections):
    subj = 'service'
    root = '/services'


class NefNfs(NefCollections):
    subj = 'NFS'
    root = '/nas/nfs'


class NefTargets(NefCollections):
    subj = 'iSCSI target'
    root = '/san/iscsi/targets'


class NefHostGroups(NefCollections):
    subj = 'host group'
    root = '/san/hostgroups'


class NefTargetsGroups(NefCollections):
    subj = 'target group'
    root = '/san/targetgroups'


class NefLunMappings(NefCollections):
    subj = 'LUN mapping'
    root = '/san/lunMappings'


class NefLogicalUnits(NefCollections):
    subj = 'LU'
    root = 'san/logicalUnits'


class NefNetAddresses(NefCollections):
    subj = 'network address'
    root = '/network/addresses'


class NefProxy(object):
    def __init__(self, proto, path, conf):
        self.session = requests.Session()
        self.settings = NefSettings(self)
        self.filesystems = NefFilesystems(self)
        self.volumegroups = NefVolumeGroups(self)
        self.volumes = NefVolumes(self)
        self.snapshots = NefSnapshots(self)
        self.services = NefServices(self)
        self.hpr = NefHpr(self)
        self.nfs = NefNfs(self)
        self.targets = NefTargets(self)
        self.hostgroups = NefHostGroups(self)
        self.targetgroups = NefTargetsGroups(self)
        self.mappings = NefLunMappings(self)
        self.logicalunits = NefLogicalUnits(self)
        self.netaddrs = NefNetAddresses(self)
        self.lock = None
        self.tokens = {}
        self.headers = {
            'Content-Type': 'application/json',
            'X-XSS-Protection': '1'
        }
        if conf.nexenta_use_https:
            self.scheme = 'https'
        else:
            self.scheme = 'http'
        self.username = conf.nexenta_user
        self.password = conf.nexenta_password
        self.hosts = []
        if conf.nexenta_rest_address:
            for host in conf.nexenta_rest_address.split(','):
                self.hosts.append(host.strip())
        if proto == 'nfs':
            self.root = self.filesystems.path(path)
            if not self.hosts:
                self.hosts.append(conf.nas_host)
        elif proto == 'iscsi':
            self.root = self.volumegroups.path(path)
            if not self.hosts:
                self.hosts.append(conf.nexenta_host)
        else:
            message = (_('Storage protocol %(proto)s not supported')
                       % {'proto': proto})
            raise NefException(code='EPROTO', message=message)
        self.host = self.hosts[0]
        if conf.nexenta_rest_port:
            self.port = conf.nexenta_rest_port
        else:
            if conf.nexenta_use_https:
                self.port = 8443
            else:
                self.port = 8080
        self.proto = proto
        self.path = path
        self.backoff_factor = conf.nexenta_rest_backoff_factor
        self.retries = len(self.hosts) * conf.nexenta_rest_retry_count
        self.timeout = requests.packages.urllib3.util.timeout.Timeout(
            connect=conf.nexenta_rest_connect_timeout,
            read=conf.nexenta_rest_read_timeout)
        max_retries = requests.packages.urllib3.util.retry.Retry(
            total=conf.nexenta_rest_retry_count,
            backoff_factor=conf.nexenta_rest_backoff_factor)
        adapter = requests.adapters.HTTPAdapter(max_retries=max_retries)
        self.session.verify = conf.driver_ssl_cert_verify
        self.session.headers.update(self.headers)
        self.session.mount('%s://' % self.scheme, adapter)
        if not conf.driver_ssl_cert_verify:
            requests.packages.urllib3.disable_warnings()
        self.update_lock()

    def __getattr__(self, name):
        return NefRequest(self, name)

    def delete_bearer(self):
        if 'Authorization' in self.session.headers:
            del self.session.headers['Authorization']

    def update_bearer(self, token):
        bearer = 'Bearer %s' % token
        self.session.headers['Authorization'] = bearer

    def update_token(self, token):
        self.tokens[self.host] = token
        self.update_bearer(token)

    def update_host(self, host):
        self.host = host
        if host in self.tokens:
            token = self.tokens[host]
            self.update_bearer(token)

    def update_lock(self):
        prop = self.settings.get('system.guid')
        guid = prop.get('value')
        path = '%s:%s' % (guid, self.path)
        if isinstance(path, six.text_type):
            path = path.encode('utf-8')
        self.lock = md5(path, usedforsecurity=False).hexdigest()

    def url(self, path):
        netloc = '%s:%d' % (self.host, int(self.port))
        components = (self.scheme, netloc, str(path), None, None)
        url = six.moves.urllib.parse.urlunsplit(components)
        return url

    def delay(self, attempt):
        interval = int(self.backoff_factor * (2 ** (attempt - 1)))
        LOG.debug('Waiting for %(interval)s seconds',
                  {'interval': interval})
        greenthread.sleep(interval)
