# Copyright 2012 Alyseo.
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
Desc    : Driver to store volumes on Coraid Appliances.
Require : Coraid EtherCloud ESM, Coraid VSX and Coraid SRX.
Author  : Jean-Baptiste RANSY <openstack@alyseo.com>
Author  : Alex Zasimov <azasimov@mirantis.com>
Author  : Nikolay Sobolevsky <nsobolevsky@mirantis.com>
Contrib : Larry Matter <support@coraid.com>
"""

import cookielib
import math
import urllib
import urllib2

from oslo.config import cfg
import six.moves.urllib.parse as urlparse

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import jsonutils
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder.volume import driver
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

coraid_opts = [
    cfg.StrOpt('coraid_esm_address',
               default='',
               help='IP address of Coraid ESM'),
    cfg.StrOpt('coraid_user',
               default='admin',
               help='User name to connect to Coraid ESM'),
    cfg.StrOpt('coraid_group',
               default='admin',
               help='Name of group on Coraid ESM to which coraid_user belongs'
               ' (must have admin privilege)'),
    cfg.StrOpt('coraid_password',
               default='password',
               help='Password to connect to Coraid ESM'),
    cfg.StrOpt('coraid_repository_key',
               default='coraid_repository',
               help='Volume Type key name to store ESM Repository Name'),
]

CONF = cfg.CONF
CONF.register_opts(coraid_opts)


ESM_SESSION_EXPIRED_STATES = ['GeneralAdminFailure',
                              'passwordInactivityTimeout',
                              'passwordAbsoluteTimeout']


class CoraidRESTClient(object):
    """Executes REST RPC requests on Coraid ESM EtherCloud Appliance."""

    def __init__(self, esm_url):
        self._check_esm_url(esm_url)
        self._esm_url = esm_url
        self._cookie_jar = cookielib.CookieJar()
        self._url_opener = urllib2.build_opener(
            urllib2.HTTPCookieProcessor(self._cookie_jar))

    def _check_esm_url(self, esm_url):
        splitted = urlparse.urlsplit(esm_url)
        if splitted.scheme != 'https':
            raise ValueError(
                _('Invalid ESM url scheme "%s". Supported https only.') %
                splitted.scheme)

    @lockutils.synchronized('coraid_rpc', 'cinder-', False)
    def rpc(self, handle, url_params, data, allow_empty_response=False):
        return self._rpc(handle, url_params, data, allow_empty_response)

    def _rpc(self, handle, url_params, data, allow_empty_response):
        """Execute REST RPC using url <esm_url>/handle?url_params.

        Send JSON encoded data in body of POST request.

        Exceptions:
            urllib2.URLError
              1. Name or service not found (e.reason is socket.gaierror)
              2. Socket blocking operation timeout (e.reason is
                 socket.timeout)
              3. Network IO error (e.reason is socket.error)

            urllib2.HTTPError
              1. HTTP 404, HTTP 500 etc.

            CoraidJsonEncodeFailure - bad REST response
        """
        # Handle must be simple path, for example:
        #    /configure
        if '?' in handle or '&' in handle:
            raise ValueError(_('Invalid REST handle name. Expected path.'))

        # Request url includes base ESM url, handle path and optional
        # URL params.
        rest_url = urlparse.urljoin(self._esm_url, handle)
        encoded_url_params = urllib.urlencode(url_params)
        if encoded_url_params:
            rest_url += '?' + encoded_url_params

        if data is None:
            json_request = None
        else:
            json_request = jsonutils.dumps(data)

        request = urllib2.Request(rest_url, json_request)
        response = self._url_opener.open(request).read()

        try:
            if not response and allow_empty_response:
                reply = {}
            else:
                reply = jsonutils.loads(response)
        except (TypeError, ValueError) as exc:
            msg = (_('Call to json.loads() failed: %(ex)s.'
                     ' Response: %(resp)s') %
                   {'ex': exc, 'resp': response})
            raise exception.CoraidJsonEncodeFailure(msg)

        return reply


def to_coraid_kb(gb):
    return math.ceil(float(gb) * units.Gi / 1000)


def coraid_volume_size(gb):
    return '{0}K'.format(to_coraid_kb(gb))


class CoraidAppliance(object):
    def __init__(self, rest_client, username, password, group):
        self._rest_client = rest_client
        self._username = username
        self._password = password
        self._group = group
        self._logined = False

    def _login(self):
        """Login into ESM.

        Perform login request and return available groups.

        :returns: dict -- map with group_name to group_id
        """
        ADMIN_GROUP_PREFIX = 'admin group:'

        url_params = {'op': 'login',
                      'username': self._username,
                      'password': self._password}
        reply = self._rest_client.rpc('admin', url_params, 'Login')
        if reply['state'] != 'adminSucceed':
            raise exception.CoraidESMBadCredentials()

        # Read groups map from login reply.
        groups_map = {}
        for group_info in reply.get('values', []):
            full_group_name = group_info['fullPath']
            if full_group_name.startswith(ADMIN_GROUP_PREFIX):
                group_name = full_group_name[len(ADMIN_GROUP_PREFIX):]
                groups_map[group_name] = group_info['groupId']

        return groups_map

    def _set_effective_group(self, groups_map, group):
        """Set effective group.

        Use groups_map returned from _login method.
        """
        try:
            group_id = groups_map[group]
        except KeyError:
            raise exception.CoraidESMBadGroup(group_name=group)

        url_params = {'op': 'setRbacGroup',
                      'groupId': group_id}
        reply = self._rest_client.rpc('admin', url_params, 'Group')
        if reply['state'] != 'adminSucceed':
            raise exception.CoraidESMBadCredentials()

        self._logined = True

    def _ensure_session(self):
        if not self._logined:
            groups_map = self._login()
            self._set_effective_group(groups_map, self._group)

    def _relogin(self):
        self._logined = False
        self._ensure_session()

    def rpc(self, handle, url_params, data, allow_empty_response=False):
        self._ensure_session()

        relogin_attempts = 3
        # Do action, relogin if needed and repeat action.
        while True:
            reply = self._rest_client.rpc(handle, url_params, data,
                                          allow_empty_response)

            if self._is_session_expired(reply):
                relogin_attempts -= 1
                if relogin_attempts <= 0:
                    raise exception.CoraidESMReloginFailed()
                LOG.debug('Session is expired. Relogin on ESM.')
                self._relogin()
            else:
                return reply

    def _is_session_expired(self, reply):
        return ('state' in reply and
                reply['state'] in ESM_SESSION_EXPIRED_STATES and
                reply['metaCROp'] == 'reboot')

    def _is_bad_config_state(self, reply):
        return (not reply or
                'configState' not in reply or
                reply['configState'] != 'completedSuccessfully')

    def configure(self, json_request):
        reply = self.rpc('configure', {}, json_request)
        if self._is_bad_config_state(reply):
            # Calculate error message
            if not reply:
                reason = _('Reply is empty.')
            else:
                reason = reply.get('message', _('Error message is empty.'))
            raise exception.CoraidESMConfigureError(reason=reason)
        return reply

    def esm_command(self, request):
        request['data'] = jsonutils.dumps(request['data'])
        return self.configure([request])

    def get_volume_info(self, volume_name):
        """Retrieve volume information for a given volume name."""
        url_params = {'shelf': 'cms',
                      'orchStrRepo': '',
                      'lv': volume_name}
        reply = self.rpc('fetch', url_params, None)
        try:
            volume_info = reply[0][1]['reply'][0]
        except (IndexError, KeyError):
            raise exception.VolumeNotFound(volume_id=volume_name)
        return {'pool': volume_info['lv']['containingPool'],
                'repo': volume_info['repoName'],
                'lun': volume_info['lv']['lvStatus']['exportedLun']['lun'],
                'shelf': volume_info['lv']['lvStatus']['exportedLun']['shelf']}

    def get_volume_repository(self, volume_name):
        volume_info = self.get_volume_info(volume_name)
        return volume_info['repo']

    def get_all_repos(self):
        reply = self.rpc('fetch', {'orchStrRepo': ''}, None)
        try:
            return reply[0][1]['reply']
        except (IndexError, KeyError):
            return []

    def ping(self):
        try:
            self.rpc('fetch', {}, None, allow_empty_response=True)
        except Exception as e:
            LOG.debug('Coraid Appliance ping failed: %s', e)
            raise exception.CoraidESMNotAvailable(reason=e)

    def create_lun(self, repository_name, volume_name, volume_size_in_gb):
        request = {'addr': 'cms',
                   'data': {
                       'servers': [],
                       'repoName': repository_name,
                       'lvName': volume_name,
                       'size': coraid_volume_size(volume_size_in_gb)},
                   'op': 'orchStrLun',
                   'args': 'add'}
        esm_result = self.esm_command(request)
        LOG.debug('Volume "%(name)s" created with VSX LUN "%(lun)s"' %
                  {'name': volume_name,
                   'lun': esm_result['firstParam']})
        return esm_result

    def delete_lun(self, volume_name):
        repository_name = self.get_volume_repository(volume_name)
        request = {'addr': 'cms',
                   'data': {
                       'repoName': repository_name,
                       'lvName': volume_name},
                   'op': 'orchStrLun/verified',
                   'args': 'delete'}
        esm_result = self.esm_command(request)
        LOG.debug('Volume "%s" deleted.', volume_name)
        return esm_result

    def resize_volume(self, volume_name, new_volume_size_in_gb):
        LOG.debug('Resize volume "%(name)s" to %(size)s GB.' %
                  {'name': volume_name,
                   'size': new_volume_size_in_gb})
        repository = self.get_volume_repository(volume_name)
        LOG.debug('Repository for volume "%(name)s" found: "%(repo)s"' %
                  {'name': volume_name,
                   'repo': repository})

        request = {'addr': 'cms',
                   'data': {
                       'lvName': volume_name,
                       'newLvName': volume_name + '-resize',
                       'size': coraid_volume_size(new_volume_size_in_gb),
                       'repoName': repository},
                   'op': 'orchStrLunMods',
                   'args': 'resize'}
        esm_result = self.esm_command(request)

        LOG.debug('Volume "%(name)s" resized. New size is %(size)s GB.' %
                  {'name': volume_name,
                   'size': new_volume_size_in_gb})
        return esm_result

    def create_snapshot(self, volume_name, snapshot_name):
        volume_repository = self.get_volume_repository(volume_name)
        request = {'addr': 'cms',
                   'data': {
                       'repoName': volume_repository,
                       'lvName': volume_name,
                       'newLvName': snapshot_name},
                   'op': 'orchStrLunMods',
                   'args': 'addClSnap'}
        esm_result = self.esm_command(request)
        return esm_result

    def delete_snapshot(self, snapshot_name):
        repository_name = self.get_volume_repository(snapshot_name)
        request = {'addr': 'cms',
                   'data': {
                       'repoName': repository_name,
                       'lvName': snapshot_name,
                       # NOTE(novel): technically, the 'newLvName' is not
                       # required for 'delClSnap' command. However, some
                       # versions of ESM have a bug that fails validation
                       # if we don't specify that. Hence, this fake value.
                       'newLvName': "noop"},
                   'op': 'orchStrLunMods',
                   'args': 'delClSnap'}
        esm_result = self.esm_command(request)
        return esm_result

    def create_volume_from_snapshot(self,
                                    snapshot_name,
                                    volume_name,
                                    dest_repository_name):
        snapshot_repo = self.get_volume_repository(snapshot_name)
        request = {'addr': 'cms',
                   'data': {
                       'lvName': snapshot_name,
                       'repoName': snapshot_repo,
                       'newLvName': volume_name,
                       'newRepoName': dest_repository_name},
                   'op': 'orchStrLunMods',
                   'args': 'addClone'}
        esm_result = self.esm_command(request)
        return esm_result

    def clone_volume(self,
                     src_volume_name,
                     dst_volume_name,
                     dst_repository_name):
        src_volume_info = self.get_volume_info(src_volume_name)

        if src_volume_info['repo'] != dst_repository_name:
            raise exception.CoraidException(
                _('Cannot create clone volume in different repository.'))

        request = {'addr': 'cms',
                   'data': {
                       'shelfLun': '{0}.{1}'.format(src_volume_info['shelf'],
                                                    src_volume_info['lun']),
                       'lvName': src_volume_name,
                       'repoName': src_volume_info['repo'],
                       'newLvName': dst_volume_name,
                       'newRepoName': dst_repository_name},
                   'op': 'orchStrLunMods',
                   'args': 'addClone'}
        return self.esm_command(request)


class CoraidDriver(driver.VolumeDriver):
    """This is the Class to set in cinder.conf (volume_driver)."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(CoraidDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(coraid_opts)

        self._stats = {'driver_version': self.VERSION,
                       'free_capacity_gb': 'unknown',
                       'reserved_percentage': 0,
                       'storage_protocol': 'aoe',
                       'total_capacity_gb': 'unknown',
                       'vendor_name': 'Coraid'}
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats['volume_backend_name'] = backend_name or 'EtherCloud ESM'

    @property
    def appliance(self):
        # NOTE(nsobolevsky): This is workaround for bug in the ESM appliance.
        # If there is a lot of request with the same session/cookie/connection,
        # the appliance could corrupt all following request in session.
        # For that purpose we just create a new appliance.
        esm_url = "https://{0}:8443".format(
            self.configuration.coraid_esm_address)

        return CoraidAppliance(CoraidRESTClient(esm_url),
                               self.configuration.coraid_user,
                               self.configuration.coraid_password,
                               self.configuration.coraid_group)

    def check_for_setup_error(self):
        """Return an error if prerequisites aren't met."""
        self.appliance.ping()

    def _get_repository(self, volume_type):
        """Get the ESM Repository from the Volume Type.

        The ESM Repository is stored into a volume_type_extra_specs key.
        """
        volume_type_id = volume_type['id']
        repository_key_name = self.configuration.coraid_repository_key
        repository = volume_types.get_volume_type_extra_specs(
            volume_type_id, repository_key_name)
        # Remove <in> keyword from repository name if needed
        if repository.startswith('<in> '):
            return repository[len('<in> '):]
        else:
            return repository

    def create_volume(self, volume):
        """Create a Volume."""
        repository = self._get_repository(volume['volume_type'])
        self.appliance.create_lun(repository, volume['name'], volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        dst_volume_repository = self._get_repository(volume['volume_type'])

        self.appliance.clone_volume(src_vref['name'],
                                    volume['name'],
                                    dst_volume_repository)

        if volume['size'] != src_vref['size']:
            self.appliance.resize_volume(volume['name'], volume['size'])

    def delete_volume(self, volume):
        """Delete a Volume."""
        try:
            self.appliance.delete_lun(volume['name'])
        except exception.VolumeNotFound:
            self.appliance.ping()

    def create_snapshot(self, snapshot):
        """Create a Snapshot."""
        volume_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        self.appliance.create_snapshot(volume_name, snapshot_name)

    def delete_snapshot(self, snapshot):
        """Delete a Snapshot."""
        snapshot_name = snapshot['name']
        self.appliance.delete_snapshot(snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a Volume from a Snapshot."""
        snapshot_name = snapshot['name']
        repository = self._get_repository(volume['volume_type'])
        self.appliance.create_volume_from_snapshot(snapshot_name,
                                                   volume['name'],
                                                   repository)
        if volume['size'] > snapshot['volume_size']:
            self.appliance.resize_volume(volume['name'], volume['size'])

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        self.appliance.resize_volume(volume['name'], new_size)

    def initialize_connection(self, volume, connector):
        """Return connection information."""
        volume_info = self.appliance.get_volume_info(volume['name'])

        shelf = volume_info['shelf']
        lun = volume_info['lun']

        LOG.debug('Initialize connection %(shelf)s/%(lun)s for %(name)s' %
                  {'shelf': shelf,
                   'lun': lun,
                   'name': volume['name']})

        aoe_properties = {'target_shelf': shelf,
                          'target_lun': lun}

        return {'driver_volume_type': 'aoe',
                'data': aoe_properties}

    def _get_repository_capabilities(self):
        repos_list = map(lambda i: i['profile']['fullName'] + ':' + i['name'],
                         self.appliance.get_all_repos())
        return ' '.join(repos_list)

    def update_volume_stats(self):
        capabilities = self._get_repository_capabilities()
        self._stats[self.configuration.coraid_repository_key] = capabilities

    def get_volume_stats(self, refresh=False):
        """Return Volume Stats."""
        if refresh:
            self.update_volume_stats()
        return self._stats

    def local_path(self, volume):
        pass

    def create_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def ensure_export(self, context, volume):
        pass
