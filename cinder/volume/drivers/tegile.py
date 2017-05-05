# Copyright (c) 2015 by Tegile Systems, Inc.
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
Volume driver for Tegile storage.
"""

import ast
import json
import requests

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)
default_api_service = 'openstack'
TEGILE_API_PATH = 'zebi/api'
TEGILE_DEFAULT_BLOCK_SIZE = '32KB'
TEGILE_LOCAL_CONTAINER_NAME = 'Local'
DEBUG_LOGGING = False

tegile_opts = [
    cfg.StrOpt('tegile_default_pool',
               help='Create volumes in this pool'),
    cfg.StrOpt('tegile_default_project',
               help='Create volumes in this project')]

CONF = cfg.CONF
CONF.register_opts(tegile_opts, group=configuration.SHARED_CONF_GROUP)


def debugger(func):
    """Returns a wrapper that wraps func.

    The wrapper will log the entry and exit points of the function
    """

    def wrapper(*args, **kwds):
        if DEBUG_LOGGING:
            LOG.debug('Entering %(classname)s.%(funcname)s',
                      {'classname': args[0].__class__.__name__,
                       'funcname': func.__name__})
            LOG.debug('Arguments: %(args)s, %(kwds)s',
                      {'args': args[1:],
                       'kwds': kwds})
        f_result = func(*args, **kwds)
        if DEBUG_LOGGING:
            LOG.debug('Exiting %(classname)s.%(funcname)s',
                      {'classname': args[0].__class__.__name__,
                       'funcname': func.__name__})
            LOG.debug('Results: %(result)s',
                      {'result': f_result})
        return f_result

    return wrapper


class TegileAPIExecutor(object):
    def __init__(self, classname, hostname, username, password):
        self._classname = classname
        self._hostname = hostname
        self._username = username
        self._password = password

    @debugger
    @utils.retry(exceptions=(requests.ConnectionError, requests.Timeout))
    def send_api_request(self, method, params=None,
                         request_type='post',
                         api_service=default_api_service,
                         fine_logging=DEBUG_LOGGING):
        if params is not None:
            params = json.dumps(params)

        url = 'https://%s/%s/%s/%s' % (self._hostname,
                                       TEGILE_API_PATH,
                                       api_service,
                                       method)
        if fine_logging:
            LOG.debug('TegileAPIExecutor(%(classname)s) method: %(method)s, '
                      'url: %(url)s', {'classname': self._classname,
                                       'method': method,
                                       'url': url})
        if request_type == 'post':
            if fine_logging:
                LOG.debug('TegileAPIExecutor(%(classname)s) '
                          'method: %(method)s, payload: %(payload)s',
                          {'classname': self._classname,
                           'method': method,
                           'payload': params})
            req = requests.post(url,
                                data=params,
                                auth=(self._username, self._password),
                                verify=False)
        else:
            req = requests.get(url,
                               auth=(self._username, self._password),
                               verify=False)

        if fine_logging:
            LOG.debug('TegileAPIExecutor(%(classname)s) method: %(method)s, '
                      'return code: %(retcode)s',
                      {'classname': self._classname,
                       'method': method,
                       'retcode': req})
        try:
            response = req.json()
            if fine_logging:
                LOG.debug('TegileAPIExecutor(%(classname)s) '
                          'method: %(method)s, response: %(response)s',
                          {'classname': self._classname,
                           'method': method,
                           'response': response})
        except ValueError:
            response = ''
        req.close()

        if req.status_code != 200:
            msg = _('API response: %(response)s') % {'response': response}
            raise exception.TegileAPIException(msg)

        return response


class TegileIntelliFlashVolumeDriver(san.SanDriver):
    """Tegile IntelliFlash Volume Driver."""

    VENDOR = 'Tegile Systems Inc.'
    VERSION = '1.0.0'
    REQUIRED_OPTIONS = ['san_ip', 'san_login',
                        'san_password', 'tegile_default_pool']
    SNAPSHOT_PREFIX = 'Manual-V-'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Tegile_Storage_CI"

    # TODO(smcginnis) Remove driver in Queens if CI issues not fixed
    SUPPORTED = False

    _api_executor = None

    def __init__(self, *args, **kwargs):
        self._context = None
        super(TegileIntelliFlashVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(tegile_opts)
        self._protocol = 'iSCSI'  # defaults to iscsi
        hostname = getattr(self.configuration, 'san_ip')
        username = getattr(self.configuration, 'san_login')
        password = getattr(self.configuration, 'san_password')
        self._default_pool = getattr(self.configuration, 'tegile_default_pool')
        self._default_project = (
            getattr(self.configuration, 'tegile_default_project') or
            'openstack')
        self._api_executor = TegileAPIExecutor(self.__class__.__name__,
                                               hostname,
                                               username,
                                               password)

    @debugger
    def do_setup(self, context):
        super(TegileIntelliFlashVolumeDriver, self).do_setup(context)
        self._context = context
        self._check_ops(self.REQUIRED_OPTIONS, self.configuration)

    @debugger
    def create_volume(self, volume):
        pool = volume_utils.extract_host(volume['host'], level='pool',
                                         default_pool_name=self._default_pool)
        tegile_volume = {'blockSize': TEGILE_DEFAULT_BLOCK_SIZE,
                         'datasetPath': '%s/%s/%s' %
                                        (pool,
                                         TEGILE_LOCAL_CONTAINER_NAME,
                                         self._default_project),
                         'local': 'true',
                         'name': volume['name'],
                         'poolName': '%s' % pool,
                         'projectName': '%s' % self._default_project,
                         'protocol': self._protocol,
                         'thinProvision': 'true',
                         'volSize': volume['size'] * units.Gi}
        params = list()
        params.append(tegile_volume)
        params.append(True)

        self._api_executor.send_api_request(method='createVolume',
                                            params=params)

        LOG.info("Created volume %(volname)s, volume id %(volid)s.",
                 {'volname': volume['name'], 'volid': volume['id']})

        return self.get_additional_info(volume, pool, self._default_project)

    @debugger
    def delete_volume(self, volume):
        """Deletes a snapshot."""
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       volume_name))
        params.append(True)
        params.append(False)

        self._api_executor.send_api_request('deleteVolume', params)

    @debugger
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        snap_name = snapshot['name']
        display_list = [getattr(snapshot, 'display_name', ''),
                        getattr(snapshot, 'display_description', '')]
        snap_description = ':'.join(filter(None, display_list))
        # Limit to 254 characters
        snap_description = snap_description[:254]

        pool, project, volume_name = self._get_pool_project_volume_name(
            snapshot['volume'])

        volume = {'blockSize': TEGILE_DEFAULT_BLOCK_SIZE,
                  'datasetPath': '%s/%s/%s' %
                                 (pool,
                                  TEGILE_LOCAL_CONTAINER_NAME,
                                  project),
                  'local': 'true',
                  'name': volume_name,
                  'poolName': '%s' % pool,
                  'projectName': '%s' % project,
                  'protocol': self._protocol,
                  'thinProvision': 'true',
                  'volSize': snapshot['volume']['size'] * units.Gi}
        params = list()
        params.append(volume)
        params.append(snap_name)
        params.append(False)

        LOG.info('Creating snapshot for volume_name=%(vol)s'
                 ' snap_name=%(name)s snap_description=%(desc)s',
                 {'vol': volume_name,
                  'name': snap_name,
                  'desc': snap_description})

        self._api_executor.send_api_request('createVolumeSnapshot', params)

    @debugger
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(
            snapshot['volume'])
        params.append('%s/%s/%s/%s@%s%s' % (pool,
                                            TEGILE_LOCAL_CONTAINER_NAME,
                                            project,
                                            volume_name,
                                            self.SNAPSHOT_PREFIX,
                                            snapshot['name']))
        params.append(False)

        self._api_executor.send_api_request('deleteVolumeSnapshot', params)

    @debugger
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from snapshot."""
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(
            snapshot['volume'])

        params.append('%s/%s/%s/%s@%s%s' % (pool,
                                            TEGILE_LOCAL_CONTAINER_NAME,
                                            project,
                                            volume_name,
                                            self.SNAPSHOT_PREFIX,
                                            snapshot['name']))
        params.append(volume['name'])
        params.append(True)
        params.append(True)

        self._api_executor.send_api_request('cloneVolumeSnapshot', params)
        return self.get_additional_info(volume, pool, project)

    @debugger
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        pool, project, volume_name = self._get_pool_project_volume_name(
            src_vref)
        data_set_path = '%s/%s/%s' % (pool,
                                      TEGILE_LOCAL_CONTAINER_NAME,
                                      project)
        source_volume = {'blockSize': TEGILE_DEFAULT_BLOCK_SIZE,
                         'datasetPath': data_set_path,
                         'local': 'true',
                         'name': volume_name,
                         'poolName': '%s' % pool,
                         'projectName': '%s' % project,
                         'protocol': self._protocol,
                         'thinProvision': 'true',
                         'volSize': src_vref['size'] * units.Gi}

        dest_volume = {'blockSize': TEGILE_DEFAULT_BLOCK_SIZE,
                       'datasetPath': data_set_path,
                       # clone can reside only in the source project
                       'local': 'true',
                       'name': volume['name'],
                       'poolName': '%s' % pool,
                       'projectName': '%s' % project,
                       'protocol': self._protocol,
                       'thinProvision': 'true',
                       'volSize': volume['size'] * units.Gi}

        params = list()
        params.append(source_volume)
        params.append(dest_volume)

        self._api_executor.send_api_request(method='createClonedVolume',
                                            params=params)
        return self.get_additional_info(volume, pool, project)

    @debugger
    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data
        """
        if refresh:
            try:
                self._update_volume_stats()
            except Exception:
                pass

        return self._stats

    @debugger
    def _update_volume_stats(self):
        """Retrieves stats info from volume group."""

        try:
            data = self._api_executor.send_api_request(method='getArrayStats',
                                                       request_type='get',
                                                       fine_logging=False)
            # fixing values coming back here as String to float
            data['total_capacity_gb'] = float(data.get('total_capacity_gb', 0))
            data['free_capacity_gb'] = float(data.get('free_capacity_gb', 0))
            for pool in data.get('pools', []):
                pool['total_capacity_gb'] = float(
                    pool.get('total_capacity_gb', 0))
                pool['free_capacity_gb'] = float(
                    pool.get('free_capacity_gb', 0))
                pool['allocated_capacity_gb'] = float(
                    pool.get('allocated_capacity_gb', 0))

            data['volume_backend_name'] = getattr(self.configuration,
                                                  'volume_backend_name')
            data['vendor_name'] = self.VENDOR
            data['driver_version'] = self.VERSION
            data['storage_protocol'] = self._protocol

            self._stats = data
        except Exception as e:
            LOG.warning('TegileIntelliFlashVolumeDriver(%(clsname)s) '
                        '_update_volume_stats failed: %(error)s',
                        {'clsname': self.__class__.__name__,
                         'error': e})

    @debugger
    def get_pool(self, volume):
        """Returns pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        pool = volume_utils.extract_host(volume['host'], level='pool',
                                         default_pool_name=self._default_pool)
        return pool

    @debugger
    def extend_volume(self, volume, new_size):
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       volume_name))
        vol_size = six.text_type(new_size)
        params.append(vol_size)
        params.append('GB')
        self._api_executor.send_api_request(method='resizeVolume',
                                            params=params)

    @debugger
    def manage_existing(self, volume, existing_ref):
        volume['name_id'] = existing_ref['name']
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        additional_info = self.get_additional_info(volume, pool, project)
        additional_info['_name_id'] = existing_ref['name'],
        return additional_info

    @debugger
    def manage_existing_get_size(self, volume, existing_ref):
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       existing_ref['name']))
        volume_size = self._api_executor.send_api_request(
            method='getVolumeSizeinGB',
            params=params)

        return volume_size

    @debugger
    def _get_pool_project_volume_name(self, volume):
        pool = volume_utils.extract_host(volume['host'], level='pool',
                                         default_pool_name=self._default_pool)
        try:
            project = volume['metadata']['project']
        except (AttributeError, TypeError, KeyError):
            project = self._default_project

        if volume['_name_id'] is not None:
            volume_name = volume['_name_id']
        else:
            volume_name = volume['name']

        return pool, project, volume_name

    @debugger
    def get_additional_info(self, volume, pool, project):
        try:
            metadata = self._get_volume_metadata(volume)
        except Exception:
            metadata = dict()
        metadata['pool'] = pool
        metadata['project'] = project
        return {'metadata': metadata}

    @debugger
    def _get_volume_metadata(self, volume):
        volume_metadata = {}
        if 'volume_metadata' in volume:
            for metadata in volume['volume_metadata']:
                volume_metadata[metadata['key']] = metadata['value']
        if 'metadata' in volume:
            metadata = volume['metadata']
            for key in metadata:
                volume_metadata[key] = metadata[key]
        return volume_metadata

    @debugger
    def _check_ops(self, required_ops, configuration):
        """Ensures that the options we care about are set."""
        for attr in required_ops:
            if not getattr(configuration, attr, None):
                raise exception.InvalidInput(reason=_('%(attr)s is not '
                                                      'set.') % {'attr': attr})


@interface.volumedriver
class TegileISCSIDriver(TegileIntelliFlashVolumeDriver, san.SanISCSIDriver):
    """Tegile ISCSI Driver."""

    def __init__(self, *args, **kwargs):
        super(TegileISCSIDriver, self).__init__(*args, **kwargs)
        self._protocol = 'iSCSI'

    @debugger
    def do_setup(self, context):
        super(TegileISCSIDriver, self).do_setup(context)

    @debugger
    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance."""

        if getattr(self.configuration, 'use_chap_auth', False):
            chap_username = getattr(self.configuration, 'chap_username', '')
            chap_password = getattr(self.configuration, 'chap_password', '')
        else:
            chap_username = ''
            chap_password = ''

        if volume['provider_location'] is None:
            params = list()
            pool, project, volume_name = (
                self._get_pool_project_volume_name(volume))
            params.append('%s/%s/%s/%s' % (pool,
                                           TEGILE_LOCAL_CONTAINER_NAME,
                                           project,
                                           volume_name))
            initiator_info = {
                'initiatorName': connector['initiator'],
                'chapUserName': chap_username,
                'chapSecret': chap_password
            }
            params.append(initiator_info)
            mapping_info = self._api_executor.send_api_request(
                method='getISCSIMappingForVolume',
                params=params)
            target_portal = mapping_info['target_portal']
            target_iqn = mapping_info['target_iqn']
            target_lun = mapping_info['target_lun']
        else:
            (target_portal, target_iqn, target_lun) = (
                volume['provider_location'].split())

        connection_data = dict()
        connection_data['target_portal'] = target_portal
        connection_data['target_iqn'] = target_iqn
        connection_data['target_lun'] = int(target_lun)
        connection_data['target_discovered'] = False,
        connection_data['volume_id'] = volume['id'],
        connection_data['discard'] = False
        if getattr(self.configuration, 'use_chap_auth', False):
            connection_data['auth_method'] = 'CHAP'
            connection_data['auth_username'] = chap_username
            connection_data['auth_password'] = chap_password
        return {
            'driver_volume_type': 'iscsi',
            'data': connection_data
        }

    @debugger
    def terminate_connection(self, volume, connector, **kwargs):
        pass

    @debugger
    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       volume_name))
        if getattr(self.configuration, 'use_chap_auth', False):
            chap_username = getattr(self.configuration, 'chap_username', '')
            chap_password = getattr(self.configuration, 'chap_password', '')
        else:
            chap_username = ''
            chap_password = ''

        initiator_info = {
            'initiatorName': connector['initiator'],
            'chapUserName': chap_username,
            'chapSecret': chap_password
        }
        params.append(initiator_info)
        mapping_info = self._api_executor.send_api_request(
            method='getISCSIMappingForVolume',
            params=params)
        target_portal = mapping_info['target_portal']
        target_iqn = mapping_info['target_iqn']
        target_lun = int(mapping_info['target_lun'])

        provider_location = '%s %s %s' % (target_portal,
                                          target_iqn,
                                          target_lun)
        if getattr(self.configuration, 'use_chap_auth', False):
            provider_auth = ('CHAP %s %s' % (chap_username,
                                             chap_password))
        else:
            provider_auth = None
        return (
            {'provider_location': provider_location,
             'provider_auth': provider_auth})


@interface.volumedriver
class TegileFCDriver(TegileIntelliFlashVolumeDriver,
                     driver.FibreChannelDriver):
    """Tegile FC driver."""

    def __init__(self, *args, **kwargs):
        super(TegileFCDriver, self).__init__(*args, **kwargs)
        self._protocol = 'FC'

    @debugger
    def do_setup(self, context):
        super(TegileFCDriver, self).do_setup(context)

    @fczm_utils.add_fc_zone
    @debugger
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""

        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       volume_name))
        wwpns = connector['wwpns']

        connectors = ','.join(wwpns)

        params.append(connectors)
        target_info = self._api_executor.send_api_request(
            method='getFCPortsForVolume',
            params=params)
        initiator_target_map = target_info['initiator_target_map']
        connection_data = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'encrypted': False,
                'target_discovered': False,
                'target_lun': int(target_info['target_lun']),
                'target_wwn': ast.literal_eval(target_info['target_wwn']),
                'initiator_target_map': ast.literal_eval(initiator_target_map)
            }
        }

        return connection_data

    @fczm_utils.remove_fc_zone
    @debugger
    def terminate_connection(self, volume, connector, force=False, **kwargs):

        params = list()
        pool, project, volume_name = self._get_pool_project_volume_name(volume)
        params.append('%s/%s/%s/%s' % (pool,
                                       TEGILE_LOCAL_CONTAINER_NAME,
                                       project,
                                       volume_name))
        wwpns = connector['wwpns']

        connectors = ','.join(wwpns)

        params.append(connectors)
        target_info = self._api_executor.send_api_request(
            method='getFCPortsForVolume',
            params=params)
        initiator_target_map = target_info['initiator_target_map']

        connection_data = {
            'data': {
                'target_wwn': ast.literal_eval(target_info['target_wwn']),
                'initiator_target_map': ast.literal_eval(initiator_target_map)
            }
        }

        return connection_data
