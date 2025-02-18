# Copyright (c) 2015 FUJITSU LIMITED
# Copyright (c) 2012 EMC Corporation.
# Copyright (c) 2012 OpenStack Foundation
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
#

"""Cinder Volume driver for Fujitsu ETERNUS DX S3 series."""

import base64
import time

from lxml import etree as ET
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils.secretutils import md5
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.fujitsu.eternus_dx import constants as CONSTANTS
from cinder.volume.drivers.fujitsu.eternus_dx import eternus_dx_cli
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

try:
    import pywbem
    pywbemAvailable = True
except ImportError:
    pywbemAvailable = False

FJ_ETERNUS_DX_OPT_opts = [
    cfg.StrOpt('cinder_eternus_config_file',
               default='/etc/cinder/cinder_fujitsu_eternus_dx.xml',
               help='Config file for cinder eternus_dx volume driver.'),
    cfg.BoolOpt('fujitsu_passwordless',
                default=True,
                help='Use SSH key to connect to storage.'),
    cfg.StrOpt('fujitsu_private_key_path',
               default='$state_path/eternus',
               help='Filename of private key for ETERNUS CLI. '
                    'This option must be set when '
                    'the fujitsu_passwordless is True.'),
    cfg.BoolOpt('fujitsu_use_cli_copy',
                default=False,
                help='If True use CLI command to create snapshot.'),
]

CONF.register_opts(FJ_ETERNUS_DX_OPT_opts, group=conf.SHARED_CONF_GROUP)


class FJDXCommon(object):
    """Common code that does not depend on protocol.

    Version history:

    1.0   - Initial driver
    1.3.0 - Community base version
    1.4.0 - Add support for QoS.
    1.4.1 - Add the method for expanding RAID volumes by CLI.
    1.4.2 - Add the secondary check for copy-sessions when deleting volumes.
    1.4.3 - Add fragment capacity information of RAID Group.
    1.4.4 - Add support for update migrated volume.
    1.4.5 - Add metadata for snapshot.
    1.4.6 - Add parameter fujitsu_use_cli_copy.
    1.4.7 - Add support for revert-to-snapshot.
    1.4.8 - Improve the processing flow of CLI error messages.(bug #2048850)
          - Add support connect to storage using SSH key.

    """

    VERSION = "1.4.8"
    stats = {
        'driver_version': VERSION,
        'storage_protocol': None,
        'vendor_name': 'FUJITSU',
        'QoS_support': True,
        'volume_backend_name': None,
    }

    def __init__(self, prtcl, configuration=None):

        self.pywbemAvailable = pywbemAvailable

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(FJ_ETERNUS_DX_OPT_opts)

        self.conn = None
        self.passwordless = self.configuration.fujitsu_passwordless
        self.private_key_path = self.configuration.fujitsu_private_key_path
        self.use_cli_copy = self.configuration.fujitsu_use_cli_copy
        self.fjdxcli = {}
        self.model_name = self._get_eternus_model()
        self._check_user()

    @staticmethod
    def get_driver_options():
        return FJ_ETERNUS_DX_OPT_opts

    def create_volume(self, volume):
        """Create volume on ETERNUS."""
        LOG.debug('create_volume, '
                  'volume id: %(vid)s, volume size: %(vsize)s.',
                  {'vid': volume['id'], 'vsize': volume['size']})

        d_metadata = self.get_metadata(volume)

        element_path, metadata = self._create_volume(volume)

        d_metadata.update(metadata)

        model_update = {
            'provider_location': str(element_path),
            'metadata': d_metadata
        }

        # Set qos to created volume.
        try:
            self._set_qos(volume, use_id=True)
        except Exception as ex:
            LOG.error('create_volume, '
                      'error occurred while setting volume qos. '
                      'Error information: %s', ex)
            # While set qos failed, delete volume from backend
            volumename = metadata['FJ_Volume_Name']
            self._delete_volume_after_error(volumename)

        return model_update

    def _create_volume(self, volume):
        LOG.debug('_create_volume, '
                  'volume id: %(vid)s, volume size: %(vsize)s.',
                  {'vid': volume['id'], 'vsize': volume['size']})

        self.conn = self._get_eternus_connection()
        volumesize = volume['size'] * units.Gi
        volumename = self._get_volume_name(volume, use_id=True)

        LOG.debug('_create_volume, volumename: %(volumename)s, '
                  'volumesize: %(volumesize)u.',
                  {'volumename': volumename,
                   'volumesize': volumesize})

        configservice = self._find_eternus_service(CONSTANTS.STOR_CONF)
        if not configservice:
            msg = (_('_create_volume, volume: %(volume)s, '
                     'volumename: %(volumename)s, '
                     'eternus_pool: %(eternus_pool)s, '
                     'Storage Configuration Service not found.')
                   % {'volume': volume,
                      'volumename': volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Get all pools information on ETERNUS.
        pools_instance_list = self._find_all_pools_instances(self.conn)

        if 'host' in volume:
            eternus_pool = volume_utils.extract_host(volume['host'], 'pool')

            for pool, ptype in pools_instance_list:
                if eternus_pool == pool['ElementName']:
                    pool_instance = pool
                    if ptype == 'RAID':
                        pooltype = CONSTANTS.RAIDGROUP
                    else:
                        pooltype = CONSTANTS.TPPOOL
                    break
            else:
                msg = (_('_create_volume, volume: %(volume)s, '
                         'volumename: %(volumename)s, '
                         'poolname: %(poolname)s, '
                         'Cannot find this pool on ETERNUS.')
                       % {'volume': volume,
                          'volumename': volumename,
                          'poolname': eternus_pool})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            LOG.debug('_create_volume, '
                      'CreateOrModifyElementFromStoragePool, '
                      'ConfigService: %(service)s, '
                      'ElementName: %(volumename)s, '
                      'InPool: %(eternus_pool)s, '
                      'ElementType: %(pooltype)u, '
                      'Size: %(volumesize)u.',
                      {'service': configservice,
                       'volumename': volumename,
                       'eternus_pool': eternus_pool,
                       'pooltype': pooltype,
                       'volumesize': volumesize})

            # Invoke method for create volume.
            rc, errordesc, job = self._exec_eternus_service(
                'CreateOrModifyElementFromStoragePool',
                configservice,
                ElementName=volumename,
                InPool=pool_instance.path,
                ElementType=self._pywbem_uint(pooltype, '16'),
                Size=self._pywbem_uint(volumesize, '64'))

        else:
            msg = (_('create_volume, volume id: %(vid)s, '
                     'volume size: %(vsize)s, '
                     'Cannot find volume host.')
                   % {'vid': volume['id'], 'vsize': volume['size']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if rc == CONSTANTS.VOLUMENAME_IN_USE:  # Element Name is in use.
            LOG.warning('_create_volume, '
                        'volumename: %(volumename)s, '
                        'Element Name is in use.',
                        {'volumename': volumename})
            element = self._find_lun(volume)
        elif rc != CONSTANTS.RC_OK:
            msg = (_('_create_volume, '
                     'volumename: %(volumename)s, '
                     'poolname: %(eternus_pool)s, '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s.')
                   % {'volumename': volumename,
                      'eternus_pool': eternus_pool,
                      'rc': rc,
                      'errordesc': errordesc})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            element = job['TheElement']

        # Get eternus model name.
        try:
            systemnamelist = self._enum_eternus_instances(
                'FUJITSU_StorageProduct',
                conn=self.conn)
        except Exception:
            msg = (_('_create_volume, '
                     'volume: %(volume)s, '
                     'EnumerateInstances, '
                     'cannot connect to ETERNUS.')
                   % {'volume': volume})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_create_volume, '
                  'volumename: %(volumename)s, '
                  'Backend: %(backend)s, '
                  'Pool Name: %(eternus_pool)s, '
                  'Pool Type: %(pooltype)s.',
                  {'volumename': volumename,
                   'backend': systemnamelist[0]['IdentifyingNumber'],
                   'eternus_pool': eternus_pool,
                   'pooltype': CONSTANTS.POOL_TYPE_dic[pooltype]})

        # Create return value.
        element_path = {
            'classname': element.classname,
            'keybindings': {
                'SystemName': element['SystemName'],
                'DeviceID': element['DeviceID'],
            },
            'vol_name': volumename,
        }

        volume_no = self._get_volume_number(element)
        metadata = {
            'FJ_Backend': systemnamelist[0]['IdentifyingNumber'],
            'FJ_Volume_Name': volumename,
            'FJ_Volume_No': volume_no,
            'FJ_Pool_Name': eternus_pool,
            'FJ_Pool_Type': CONSTANTS.POOL_TYPE_dic[pooltype],
        }

        return element_path, metadata

    def create_pool_info(self, pool_instance, volume_count, pool_type,
                         **kwargs):
        """Create pool information from pool instance."""
        LOG.debug('create_pool_info, pool_instance: %(pool)s, '
                  'volume_count: %(volcount)s, pool_type: %(ptype)s.',
                  {'pool': pool_instance,
                   'volcount': volume_count, 'ptype': pool_type})

        if pool_type not in CONSTANTS.POOL_TYPE_list:
            msg = (_('Invalid pool type was specified : %s.') % pool_type)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        total_mb = pool_instance['TotalManagedSpace'] * 1.0 / units.Mi
        free_mb = pool_instance['RemainingManagedSpace'] * 1.0 / units.Mi
        fragment_mb = free_mb

        if kwargs.get('provisioned_capacity_mb'):
            prov_mb = kwargs.get('provisioned_capacity_mb')
        else:
            prov_mb = total_mb - free_mb

        if pool_type == 'RAID':
            useable_mb = free_mb
            if kwargs.get('fragment_size'):
                if kwargs.get('fragment_size') != -1:
                    fragment_mb = kwargs.get('fragment_size') / (2 * 1024)
                else:
                    fragment_mb = useable_mb
        else:
            max_capacity_mb = total_mb * float(
                self.configuration.max_over_subscription_ratio)
            useable_mb = max_capacity_mb - prov_mb

        pool = {
            'name': pool_instance['ElementName'],
            'path': pool_instance.path,
            'total_capacity_gb': int(total_mb / 1024),
            'free_capacity_gb': int(free_mb / 1024),
            'type': pool_type,
            'volume_count': volume_count,
            'provisioned_capacity_gb': int(prov_mb / 1024),
            'useable_capacity_gb': int(useable_mb / 1024),
            'useable_capacity_mb': useable_mb,
            'fragment_capacity_mb': fragment_mb,
        }

        LOG.debug('create_pool_info, pool: %s.', pool)
        return pool

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.debug('create_volume_from_snapshot, '
                  'volume id: %(vid)s, volume size: %(vsize)s, '
                  'snapshot id: %(sid)s.',
                  {'vid': volume['id'], 'vsize': volume['size'],
                   'sid': snapshot['id']})

        self.conn = self._get_eternus_connection()
        source_volume_instance = self._find_lun(snapshot)

        # Check the existence of source volume.
        if source_volume_instance is None:
            msg = _('create_volume_from_snapshot, '
                    'Source Volume does not exist in ETERNUS.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create volume for the target volume.
        model_update = self.create_volume(volume)
        element_path = eval(model_update.get('provider_location'))
        metadata = model_update.get('metadata')
        target_volume_instancename = self._create_eternus_instance_name(
            element_path['classname'], element_path['keybindings'].copy())

        try:
            target_volume_instance = (
                self._get_eternus_instance(target_volume_instancename))
        except Exception:
            msg = (_('create_volume_from_snapshot, '
                     'target volume instancename: %(volume_instancename)s, '
                     'Get Instance Failed.')
                   % {'volume_instancename': target_volume_instancename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self._create_local_cloned_volume(target_volume_instance,
                                         source_volume_instance)

        return (element_path, metadata)

    def create_cloned_volume(self, volume, src_vref):
        """Create clone of the specified volume."""
        LOG.debug('create_cloned_volume, '
                  'tgt: (%(tid)s, %(tsize)s), src: (%(sid)s, %(ssize)s).',
                  {'tid': volume['id'], 'tsize': volume['size'],
                   'sid': src_vref['id'], 'ssize': src_vref['size']})

        self.conn = self._get_eternus_connection()
        source_volume_instance = self._find_lun(src_vref)

        if source_volume_instance is None:
            msg = _('create_cloned_volume, '
                    'Source Volume does not exist in ETERNUS.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        model_update = self.create_volume(volume)
        element_path = eval(model_update.get('provider_location'))
        metadata = model_update.get('metadata')
        target_volume_instancename = self._create_eternus_instance_name(
            element_path['classname'], element_path['keybindings'].copy())

        try:
            target_volume_instance = (
                self._get_eternus_instance(target_volume_instancename))
        except Exception:
            msg = (_('create_cloned_volume, '
                     'target volume instancename: %(volume_instancename)s, '
                     'Get Instance Failed.')
                   % {'volume_instancename': target_volume_instancename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self._create_local_cloned_volume(target_volume_instance,
                                         source_volume_instance)

        return (element_path, metadata)

    @lockutils.synchronized('ETERNUS-vol', 'cinder-', True)
    def _create_local_cloned_volume(self, tgt_vol_instance, src_vol_instance):
        """Create local clone of the specified volume."""
        s_volumename = src_vol_instance['ElementName']
        t_volumename = tgt_vol_instance['ElementName']

        LOG.debug('_create_local_cloned_volume, '
                  'tgt volume name: %(t_volumename)s, '
                  'src volume name: %(s_volumename)s, ',
                  {'t_volumename': t_volumename,
                   's_volumename': s_volumename})

        # Get replication service for CreateElementReplica.
        repservice = self._find_eternus_service(CONSTANTS.REPL)

        if repservice is None:
            msg = _('_create_local_cloned_volume, '
                    'Replication Service not found.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Invoke method for create cloned volume from volume.
        rc, errordesc, job = self._exec_eternus_service(
            'CreateElementReplica',
            repservice,
            SyncType=self._pywbem_uint(8, '16'),
            SourceElement=src_vol_instance.path,
            TargetElement=tgt_vol_instance.path)

        if rc != CONSTANTS.RC_OK:
            msg = (_('_create_local_cloned_volume, '
                     'volumename: %(volumename)s, '
                     'sourcevolumename: %(sourcevolumename)s, '
                     'source volume instance: %(source_volume)s, '
                     'target volume instance: %(target_volume)s, '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s.')
                   % {'volumename': t_volumename,
                      'sourcevolumename': s_volumename,
                      'source_volume': src_vol_instance.path,
                      'target_volume': tgt_vol_instance.path,
                      'rc': rc,
                      'errordesc': errordesc})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_create_local_cloned_volume, out: %(rc)s, %(job)s.',
                  {'rc': rc, 'job': job})

    def delete_volume(self, volume):
        """Delete volume on ETERNUS."""
        LOG.debug('delete_volume, volume id: %(vid)s.',
                  {'vid': volume['id']})

        vol_exist = self._delete_volume_setting(volume)

        if not vol_exist:
            LOG.debug('delete_volume, volume not found in 1st check.')
            return

        try:
            self._delete_volume(volume)
        except Exception as ex:
            msg = (_('delete_volume, '
                     'delete volume failed, '
                     'Error information: %s.')
                   % ex)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    @lockutils.synchronized('ETERNUS-vol', 'cinder-', True)
    def _delete_volume_setting(self, volume):
        """Delete volume setting (HostAffinity, CopySession) on ETERNUS."""
        LOG.debug('_delete_volume_setting, '
                  'volume id: %(vid)s.',
                  {'vid': volume['id']})

        # Check the existence of volume.
        volumename = self._get_volume_name(volume)
        vol_instance = self._find_lun(volume)

        if not vol_instance:
            LOG.info('_delete_volume_setting, volumename:%(volumename)s, '
                     'volume not found on ETERNUS.',
                     {'volumename': volumename})
            return False

        # Delete host-affinity setting remained by unexpected error.
        self._unmap_lun(volume, None, force=True)

        # Check copy session relating to target volume.
        cpsessionlist = self._find_copysession(vol_instance)
        delete_copysession_list = []
        wait_copysession_list = []

        for cpsession in cpsessionlist:
            LOG.debug('_delete_volume_setting, '
                      'volumename: %(volumename)s, '
                      'cpsession: %(cpsession)s.',
                      {'volumename': volumename,
                       'cpsession': cpsession})

            if cpsession['SyncedElement'] == vol_instance.path:
                # Copy target : other_volume --(copy)--> vol_instance
                delete_copysession_list.append(cpsession)
            elif cpsession['SystemElement'] == vol_instance.path:
                # Copy source : vol_instance --(copy)--> other volume
                wait_copysession_list.append(cpsession)

        LOG.debug('_delete_volume_setting, '
                  'wait_cpsession: %(wait_cpsession)s, '
                  'delete_cpsession: %(delete_cpsession)s.',
                  {'wait_cpsession': wait_copysession_list,
                   'delete_cpsession': delete_copysession_list})

        for cpsession in wait_copysession_list:
            self._wait_for_copy_complete(cpsession)

        for cpsession in delete_copysession_list:
            self._delete_copysession(cpsession)

        volume_no = self._get_volume_number(vol_instance)

        cp_session_list = self._get_copy_sessions_list()
        for cp in cp_session_list:
            if cp['Dest Num'] != int(volume_no, 16):
                continue
            if cp['Type'] == 'Snap':
                session_id = cp['Session ID']

                param_dict = ({'session-id': session_id})
                rc, emsg, clidata = self._exec_eternus_cli(
                    'stop_copy_session',
                    **param_dict)

                if rc != CONSTANTS.RC_OK:
                    msg = (_('_delete_volume_setting, '
                             'stop_copy_session failed. '
                             'Return code: %(rc)lu, '
                             'Error: %(errormsg)s, '
                             'Message: %(clidata)s.')
                           % {'rc': rc,
                              'errormsg': emsg,
                              'clidata': clidata})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                break

        LOG.debug('_delete_volume_setting, '
                  'wait_cpsession: %(wait_cpsession)s, '
                  'delete_cpsession: %(delete_cpsession)s, complete.',
                  {'wait_cpsession': wait_copysession_list,
                   'delete_cpsession': delete_copysession_list})
        return True

    @lockutils.synchronized('ETERNUS-vol', 'cinder-', True)
    def _delete_volume(self, volume):
        """Delete volume on ETERNUS."""
        LOG.debug('_delete_volume, volume id: %(vid)s.',
                  {'vid': volume['id']})

        vol_instance = self._find_lun(volume)

        if not vol_instance:
            LOG.debug('_delete_volume, volume not found in 2nd check, '
                      'but no problem.')
            return

        volumename = vol_instance['ElementName']

        configservice = self._find_eternus_service(CONSTANTS.STOR_CONF)
        if not configservice:
            msg = (_('_delete_volume, volumename: %(volumename)s, '
                     'Storage Configuration Service not found.')
                   % {'volumename': volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_delete_volume, volumename: %(volumename)s, '
                  'vol_instance: %(vol_instance)s, '
                  'Method: ReturnToStoragePool.',
                  {'volumename': volumename,
                   'vol_instance': vol_instance.path})

        # Invoke method for delete volume
        rc, errordesc, job = self._exec_eternus_service(
            'ReturnToStoragePool',
            configservice,
            TheElement=vol_instance.path)

        if rc != CONSTANTS.RC_OK:
            msg = (_('_delete_volume, volumename: %(volumename)s, '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s.')
                   % {'volumename': volumename,
                      'rc': rc,
                      'errordesc': errordesc})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_delete_volume, volumename: %(volumename)s, '
                  'Return code: %(rc)lu, '
                  'Error: %(errordesc)s.',
                  {'volumename': volumename,
                   'rc': rc,
                   'errordesc': errordesc})

    def _delete_volume_after_error(self, volumename):
        # If error occures while set qos after create a volume,then delete
        # the created volume.
        LOG.debug('_delete_volume_after_error, '
                  'volume name: %(volumename)s.',
                  {'volumename': volumename})

        param_dict = {'volume-name': volumename}
        rc, errordesc, data = self._exec_eternus_cli(
            'delete_volume',
            **param_dict)

        if rc == CONSTANTS.RC_OK:
            msg = (_('_delete_volume_after_error, '
                     'volumename: %(volumename)s, '
                     'Delete Successed.')
                   % {'volumename': volumename})
        else:
            msg = (_('_delete_volume_after_error, '
                     'volumename: %(volumename)s, '
                     'Delete Failed.')
                   % {'volumename': volumename})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def create_snapshot(self, snapshot):
        """Create snapshot using SnapOPC."""
        LOG.debug('create_snapshot, '
                  'snapshot id: %(sid)s, volume id: %(vid)s.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        volume = snapshot['volume']
        s_volumename = self._get_volume_name(volume)
        vol_instance = self._find_lun(volume)

        # Check the existence of volume.
        if not vol_instance:
            # Volume not found on ETERNUS.
            msg = (_('create_snapshot, '
                     'volumename: %(s_volumename)s, '
                     'source volume not found on ETERNUS.')
                   % {'s_volumename': s_volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        model_update = self._create_snapshot(snapshot)

        return model_update

    @lockutils.synchronized('ETERNUS-vol', 'cinder-', True)
    def _create_snapshot(self, snapshot):

        LOG.debug('_create_snapshot, '
                  'snapshot id: %(sid)s, volume id: %(vid)s.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        snapshotname = snapshot['name']
        volume = snapshot['volume']
        volumename = snapshot['volume_name']
        d_volumename = self._get_volume_name(snapshot, use_id=True)
        vol_instance = self._find_lun(volume)
        service_name = (CONSTANTS.REPL
                        if self.model_name != CONSTANTS.DX_S2
                        else CONSTANTS.STOR_CONF)

        volume_size = snapshot['volume']['size'] * 1024

        smis_service = self._find_eternus_service(service_name)

        if not smis_service:
            msg = (_('_create_snapshot, '
                     'volumename: %(volumename)s, '
                     '%(servicename)s not found.')
                   % {'volumename': volumename,
                      'servicename': service_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Get all pools information on ETERNUS.
        pools_instance_list = self._find_all_pools_instances(self.conn)
        # Get the user specified pool name.
        pool_name_list = self._get_drvcfg('EternusSnapPool', multiple=True)

        poollen = len(pool_name_list)
        for i in range(poollen):
            # Traverse the user specified pool one by one.
            pool_instances, notfound_poolnames = self._find_pools(
                [pool_name_list[i]], self.conn,
                poolinstances_list=pools_instance_list)

            if pool_instances['pools']:
                useable = pool_instances['pools'][0]['useable_capacity_mb']
                poolname = pool_instances['pools'][0]['pool_name']
                istpp = pool_instances['pools'][0]['thin_provisioning_support']
                if useable < 24 + volume_size:
                    continue
                if not istpp:
                    # If it is a RAID Group pool, we need to determine
                    # the number of volumes and fragmentation capacity.
                    # The number of RAID Group pool volumes cannot exceed 128.
                    # The minimum space required for snapshot is 24MB.
                    fragment = pool_instances['pools'][0][
                        'fragment_capacity_mb']
                    volcnt = pool_instances['pools'][0]['total_volumes']
                    if volcnt >= 128 or fragment < 24 + volume_size:
                        LOG.debug('_create_volume, The pool: %(poolname)s '
                                  'can not create volume. '
                                  'Volume Count: %(volcnt)s, '
                                  'Maximum fragment capacity: %(frag)s.',
                                  {'poolname': poolname,
                                   'volcnt': volcnt, 'frag': fragment})
                        continue

                pool_instance = pool_instances['pools'][0]
                eternus_pool = pool_instance['pool_name']
                pool = pool_instance['path']
                if 'RSP' in pool['InstanceID']:
                    pooltype = CONSTANTS.RAIDGROUP
                else:
                    pooltype = CONSTANTS.TPPOOL

                if self.use_cli_copy is False:
                    LOG.debug('_create_snapshot, '
                              'snapshotname: %(snapshotname)s, '
                              'source volume name: %(volumename)s, '
                              'vol_instance.path: %(vol_instance)s, '
                              'dest_volumename: %(d_volumename)s, '
                              'pool: %(pool)s, '
                              'Invoke CreateElementReplica.',
                              {'snapshotname': snapshotname,
                               'volumename': volumename,
                               'vol_instance': vol_instance.path,
                               'd_volumename': d_volumename,
                               'pool': eternus_pool})

                    if self.model_name != CONSTANTS.DX_S2:
                        smis_method = 'CreateElementReplica'
                        params = {
                            'ElementName': d_volumename,
                            'TargetPool': pool,
                            'SyncType': self._pywbem_uint(7, '16'),
                            'SourceElement': vol_instance.path
                        }
                    else:
                        smis_method = 'CreateReplica'
                        params = {
                            'ElementName': d_volumename,
                            'TargetPool': pool,
                            'CopyType': self._pywbem_uint(4, '16'),
                            'SourceElement': vol_instance.path
                        }
                    # Invoke method for create snapshot.
                    rc, errordesc, job = self._exec_eternus_service(
                        smis_method, smis_service,
                        **params)

                    if rc != CONSTANTS.RC_OK:
                        LOG.warning('_create_snapshot, '
                                    'snapshotname: %(snapshotname)s, '
                                    'source volume name: %(volumename)s, '
                                    'vol_instance.path: %(vol_instance)s, '
                                    'dest volume name: %(d_volumename)s, '
                                    'pool: %(pool)s, Return code: %(rc)lu, '
                                    'Error: %(errordesc)s.',
                                    {'snapshotname': snapshotname,
                                     'volumename': volumename,
                                     'vol_instance': vol_instance.path,
                                     'd_volumename': d_volumename,
                                     'pool': eternus_pool,
                                     'rc': rc,
                                     'errordesc': errordesc})
                        continue
                    else:
                        element = job['TargetElement']
                        d_volume_no = self._get_volume_number(element)
                        break

                else:
                    if pooltype == CONSTANTS.RAIDGROUP:
                        LOG.warning('_create_snapshot, '
                                    'Can not create SDV by SMI-S.')
                        continue
                    configservice = self._find_eternus_service(
                        CONSTANTS.STOR_CONF)
                    vol_size = snapshot['volume']['size'] * units.Gi

                    LOG.debug('_create_snapshot, '
                              'CreateOrModifyElementFromStoragePool, '
                              'ConfigService: %(service)s, '
                              'ElementName: %(volumename)s, '
                              'InPool: %(eternus_pool)s, '
                              'ElementType: %(pooltype)u, '
                              'Size: %(volumesize)u.',
                              {'service': configservice,
                               'volumename': d_volumename,
                               'eternus_pool': pool,
                               'pooltype': pooltype,
                               'volumesize': vol_size})

                    # Invoke method for create volume.
                    rc, errordesc, job = self._exec_eternus_service(
                        'CreateOrModifyElementFromStoragePool',
                        configservice,
                        ElementName=d_volumename,
                        InPool=pool,
                        ElementType=self._pywbem_uint(pooltype, '16'),
                        Size=self._pywbem_uint(vol_size, '64'))

                    if rc == CONSTANTS.RG_VOLNUM_MAX:
                        LOG.warning('_create_snapshot, RAID Group pool: %s. '
                                    'Maximum number of Logical Volume in a '
                                    'RAID Group has been reached. '
                                    'Try other pool.',
                                    pool)
                        continue
                    elif rc != CONSTANTS.RC_OK:
                        msg = (_('_create_volume, '
                                 'volumename: %(volumename)s, '
                                 'poolname: %(eternus_pool)s, '
                                 'Return code: %(rc)lu, '
                                 'Error: %(errordesc)s.')
                               % {'volumename': volumename,
                                  'eternus_pool': pool,
                                  'rc': rc,
                                  'errordesc': errordesc})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    else:
                        element = job['TheElement']
                        d_volume_no = self._get_volume_number(element)
                        volume_no = self._get_volume_number(vol_instance)
                        volume_lba = int(vol_size / 512)
                        param_dict = (
                            {'mode': 'normal',
                             'source-volume-number': int(volume_no, 16),
                             'destination-volume-number': int(d_volume_no, 16),
                             'source-lba': 0,
                             'destination-lba': 0,
                             'size': volume_lba})

                        rc, emsg, clidata = self._exec_eternus_cli(
                            'start_copy_snap_opc',
                            **param_dict)

                        if rc != CONSTANTS.RC_OK:
                            msg = (_('_create_snapshot, '
                                     'create_volume failed. '
                                     'Return code: %(rc)lu, '
                                     'Error: %(errormsg)s, '
                                     'Message: %(clidata)s.')
                                   % {'rc': rc,
                                      'errormsg': emsg,
                                      'clidata': clidata})
                            LOG.error(msg)
                            raise exception.VolumeBackendAPIException(data=msg)
                        break
            else:
                if notfound_poolnames:
                    LOG.warning('_create_snapshot, '
                                'pool names: %(notfound_poolnames)s '
                                'are not found.',
                                {'notfound_poolnames': notfound_poolnames})
        else:
            # It means that all RAID Group pools do not meet
            # the volume limit (<128), and the creation request of
            # this volume will be rejected.
            # If there is a thin pool available, it will not enter this branch.
            msg = (_('_create_snapshot, volume id: %(sid)s, '
                     'All pools cannot create this volume.')
                   % {'sid': snapshot['id']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create return value.
        element_path = {
            'classname': element.classname,
            'keybindings': {
                'SystemName': element['SystemName'],
                'DeviceID': element['DeviceID'],
            },
            'vol_name': d_volumename,
        }

        metadata = {
            'FJ_SDV_Name': d_volumename,
            'FJ_SDV_No': d_volume_no,
            'FJ_Pool_Name': eternus_pool,
            'FJ_Pool_Type': pooltype
        }
        d_metadata = self.get_metadata(snapshot)
        d_metadata.update(metadata)

        model_update = {
            'provider_location': str(element_path),
            'metadata': d_metadata,
        }
        return model_update

    def delete_snapshot(self, snapshot):
        """Delete snapshot."""
        LOG.debug('delete_snapshot, '
                  'snapshot id: %(sid)s, volume id: %(vid)s.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        self.delete_volume(snapshot)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        LOG.debug('initialize_connection, '
                  'volume id: %(vid)s, protocol: %(prtcl)s.',
                  {'vid': volume['id'], 'prtcl': self.protocol})

        self.conn = self._get_eternus_connection()
        vol_instance = self._find_lun(volume)
        # Check the existence of volume
        if vol_instance is None:
            # Volume not found
            msg = (_('initialize_connection, '
                     'volume: %(volume)s, '
                     'Volume not found.')
                   % {'volume': volume['name']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        target_portlist = self._get_target_port()
        mapdata = self._get_mapdata(vol_instance, connector, target_portlist)

        if mapdata:
            # volume is already mapped
            target_lun = mapdata.get('target_lun', None)
            target_luns = mapdata.get('target_luns', None)

            LOG.info('initialize_connection, '
                     'volume: %(volume)s, '
                     'target_lun: %(target_lun)s, '
                     'target_luns: %(target_luns)s, '
                     'Volume is already mapped.',
                     {'volume': volume['name'],
                      'target_lun': target_lun,
                      'target_luns': target_luns})
        else:
            self._map_lun(vol_instance, connector, target_portlist)
            mapdata = self._get_mapdata(vol_instance,
                                        connector, target_portlist)

        mapdata['target_discovered'] = True
        mapdata['volume_id'] = volume['id']

        if self.protocol == 'fc':
            device_info = {'driver_volume_type': 'fibre_channel',
                           'data': mapdata}
        elif self.protocol == 'iSCSI':
            device_info = {'driver_volume_type': 'iscsi',
                           'data': mapdata}

        LOG.debug('initialize_connection, '
                  'device_info:%(info)s.',
                  {'info': device_info})
        return device_info

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Disallow connection from connector."""
        LOG.debug('terminate_connection, '
                  'volume id: %(vid)s, protocol: %(prtcl)s, force: %(frc)s.',
                  {'vid': volume['id'], 'prtcl': self.protocol, 'frc': force})

        self.conn = self._get_eternus_connection()
        force = True if not connector else force
        map_exist = self._unmap_lun(volume, connector, force)

        LOG.debug('terminate_connection, map_exist: %s.', map_exist)
        return map_exist

    def build_fc_init_tgt_map(self, connector, target_wwn=None):
        """Build parameter for Zone Manager"""
        LOG.debug('build_fc_init_tgt_map, target_wwn: %s.', target_wwn)

        initiatorlist = self._find_initiator_names(connector)

        if target_wwn is None:
            target_wwn = []
            target_portlist = self._get_target_port()
            for target_port in target_portlist:
                target_wwn.append(target_port['Name'])

        init_tgt_map = {initiator: target_wwn for initiator in initiatorlist}

        LOG.debug('build_fc_init_tgt_map, '
                  'initiator target mapping: %s.', init_tgt_map)
        return init_tgt_map

    def check_attached_volume_in_zone(self, connector):
        """Check Attached Volume in Same FC Zone or not"""
        LOG.debug('check_attached_volume_in_zone, connector: %s.', connector)

        aglist = self._find_affinity_group(connector)
        if not aglist:
            attached = False
        else:
            attached = True

        LOG.debug('check_attached_volume_in_zone, attached: %s.', attached)
        return attached

    @lockutils.synchronized('ETERNUS-vol', 'cinder-', True)
    def extend_volume(self, volume, new_size):
        """Extend volume on ETERNUS."""
        LOG.debug('extend_volume, volume id: %(vid)s, '
                  'size: %(size)s, new_size: %(nsize)s.',
                  {'vid': volume['id'],
                   'size': volume['size'], 'nsize': new_size})

        self.conn = self._get_eternus_connection()
        volumename = self._get_volume_name(volume)

        # Get volume instance.
        volume_instance = self._find_lun(volume)
        if not volume_instance:
            msg = (_('extend_volume, '
                     'volumename: %(volumename)s, '
                     'not found.')
                   % {'volumename': volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('extend_volume, volumename: %(volumename)s, '
                  'volumesize: %(volumesize)u, '
                  'volume instance: %(volume_instance)s.',
                  {'volumename': volumename,
                   'volumesize': new_size,
                   'volume_instance': volume_instance.path})

        # Get poolname from driver configuration file.
        pool_name, pool = self._find_pool_from_volume(volume_instance)

        # Check the existence of pool.
        if not pool:
            msg = (_('extend_volume, '
                     'eternus_pool: %(eternus_pool)s, '
                     'not found.')
                   % {'eternus_pool': pool_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Set pooltype.
        if 'RSP' in pool['InstanceID']:
            pooltype = CONSTANTS.RAIDGROUP
        else:
            pooltype = CONSTANTS.TPPOOL

        if pooltype == CONSTANTS.RAIDGROUP:
            extend_size = str(new_size - volume['size']) + 'gb'
            param_dict = {
                'volume-name': volumename,
                'rg-name': pool_name,
                'size': extend_size
            }
            rc, errordesc, data = self._exec_eternus_cli(
                'expand_volume',
                **param_dict)

            if rc != CONSTANTS.RC_OK:
                msg = (_('extend_volume, '
                         'volumename: %(volumename)s, '
                         'Return code: %(rc)lu, '
                         'Error: %(errordesc)s, '
                         'Message: %(job)s, '
                         'PoolType: %(pooltype)s.')
                       % {'volumename': volumename,
                          'rc': rc,
                          'errordesc': errordesc,
                          'pooltype': CONSTANTS.POOL_TYPE_dic[pooltype],
                          'job': data})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        else:  # Pooltype is TPPOOL.
            volumesize = new_size * units.Gi
            configservice = self._find_eternus_service(CONSTANTS.STOR_CONF)
            if not configservice:
                msg = (_('extend_volume, volume: %(volume)s, '
                         'volumename: %(volumename)s, '
                         'eternus_pool: %(eternus_pool)s, '
                         'Storage Configuration Service not found.')
                       % {'volume': volume,
                          'volumename': volumename,
                          'eternus_pool': pool_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            LOG.debug('extend_volume, '
                      'CreateOrModifyElementFromStoragePool, '
                      'ConfigService: %(service)s, '
                      'ElementName: %(volumename)s, '
                      'InPool: %(eternus_pool)s, '
                      'ElementType: %(pooltype)u, '
                      'Size: %(volumesize)u, '
                      'TheElement: %(vol_instance)s.',
                      {'service': configservice,
                       'volumename': volumename,
                       'eternus_pool': pool_name,
                       'pooltype': pooltype,
                       'volumesize': volumesize,
                       'vol_instance': volume_instance.path})

            # Invoke method for extend volume.
            rc, errordesc, _x = self._exec_eternus_service(
                'CreateOrModifyElementFromStoragePool',
                configservice,
                ElementName=volumename,
                InPool=pool,
                ElementType=self._pywbem_uint(pooltype, '16'),
                Size=self._pywbem_uint(volumesize, '64'),
                TheElement=volume_instance.path)

            if rc != CONSTANTS.RC_OK:
                msg = (_('extend_volume, '
                         'volumename: %(volumename)s, '
                         'Return code: %(rc)lu, '
                         'Error: %(errordesc)s, '
                         'PoolType: %(pooltype)s.')
                       % {'volumename': volumename,
                          'rc': rc,
                          'errordesc': errordesc,
                          'pooltype': CONSTANTS.POOL_TYPE_dic[pooltype]})

                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('extend_volume, '
                  'volumename: %(volumename)s, '
                  'Return code: %(rc)lu, '
                  'Error: %(errordesc)s, '
                  'Pool Name: %(eternus_pool)s, '
                  'Pool Type: %(pooltype)s.',
                  {'volumename': volumename,
                   'rc': rc,
                   'errordesc': errordesc,
                   'eternus_pool': pool_name,
                   'pooltype': CONSTANTS.POOL_TYPE_dic[pooltype]})

        return pool_name

    @lockutils.synchronized('ETERNUS-update', 'cinder-', True)
    def update_volume_stats(self):
        """Get pool capacity."""

        self.conn = self._get_eternus_connection()

        poolname_list = self._get_drvcfg('EternusPool', multiple=True)
        self._find_pools(poolname_list, self.conn)

        return (self.stats, poolname_list)

    def _get_mapdata(self, vol_instance, connector, target_portlist):
        """return mapping information."""
        mapdata = None
        multipath = connector.get('multipath', False)

        LOG.debug('_get_mapdata, volume name: %(vname)s, '
                  'protocol: %(prtcl)s, multipath: %(mpath)s.',
                  {'vname': vol_instance['ElementName'],
                   'prtcl': self.protocol, 'mpath': multipath})

        # find affinity group
        # attach the connector and include the volume
        aglist = self._find_affinity_group(connector, vol_instance)
        if not aglist:
            LOG.debug('_get_mapdata, ag_list:%s.', aglist)
        else:
            if self.protocol == 'fc':
                mapdata = self._get_mapdata_fc(aglist, vol_instance,
                                               target_portlist)
            elif self.protocol == 'iSCSI':
                mapdata = self._get_mapdata_iscsi(aglist, vol_instance,
                                                  multipath)

        LOG.debug('_get_mapdata, mapdata: %s.', mapdata)
        return mapdata

    def _get_mapdata_fc(self, aglist, vol_instance, target_portlist):
        """_get_mapdata for FibreChannel."""
        target_wwn = []

        try:
            ag_volmaplist = self._reference_eternus_names(
                aglist[0],
                ResultClass='CIM_ProtocolControllerForUnit')
            vo_volmaplist = self._reference_eternus_names(
                vol_instance.path,
                ResultClass='CIM_ProtocolControllerForUnit')
        except pywbem.CIM_Error:
            msg = (_('_get_mapdata_fc, '
                     'getting host-affinity from aglist/vol_instance failed, '
                     'affinitygroup: %(ag)s, '
                     'ReferenceNames, '
                     'cannot connect to ETERNUS.')
                   % {'ag': aglist[0]})
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        volmap = None
        for vo_volmap in vo_volmaplist:
            if vo_volmap in ag_volmaplist:
                volmap = vo_volmap
                break

        try:
            volmapinstance = self._get_eternus_instance(
                volmap,
                LocalOnly=False)
        except pywbem.CIM_Error:
            msg = (_('_get_mapdata_fc, '
                     'getting host-affinity instance failed, '
                     'volmap: %(volmap)s, '
                     'GetInstance, '
                     'cannot connect to ETERNUS.')
                   % {'volmap': volmap})
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        target_lun = int(volmapinstance['DeviceNumber'], 16)

        for target_port in target_portlist:
            target_wwn.append(target_port['Name'])

        mapdata = {'target_wwn': target_wwn,
                   'target_lun': target_lun}
        LOG.debug('_get_mapdata_fc, mapdata: %s.', mapdata)
        return mapdata

    def _get_mapdata_iscsi(self, aglist, vol_instance, multipath):
        """_get_mapdata for iSCSI."""
        target_portals = []
        target_iqns = []
        target_luns = []

        try:
            vo_volmaplist = self._reference_eternus_names(
                vol_instance.path,
                ResultClass='CIM_ProtocolControllerForUnit')
        except Exception:
            msg = (_('_get_mapdata_iscsi, '
                     'vol_instance: %(vol_instance)s, '
                     'ReferenceNames: CIM_ProtocolControllerForUnit, '
                     'cannot connect to ETERNUS.')
                   % {'vol_instance': vol_instance})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        target_properties_list = self._get_eternus_iscsi_properties()
        target_list = [prop[0] for prop in target_properties_list]
        properties_list = (
            [(prop[1], prop[2]) for prop in target_properties_list])

        for ag in aglist:
            try:
                iscsi_endpointlist = (
                    self._assoc_eternus_names(
                        ag,
                        AssocClass='FUJITSU_SAPAvailableForElement',
                        ResultClass='FUJITSU_iSCSIProtocolEndpoint'))
            except Exception:
                msg = (_('_get_mapdata_iscsi, '
                         'Associators: FUJITSU_SAPAvailableForElement, '
                         'cannot connect to ETERNUS.'))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            iscsi_endpoint = iscsi_endpointlist[0]
            if iscsi_endpoint not in target_list:
                continue

            idx = target_list.index(iscsi_endpoint)
            target_portal, target_iqn = properties_list[idx]

            try:
                ag_volmaplist = self._reference_eternus_names(
                    ag,
                    ResultClass='CIM_ProtocolControllerForUnit')
            except Exception:
                msg = (_('_get_mapdata_iscsi, '
                         'affinitygroup: %(ag)s, '
                         'ReferenceNames, '
                         'cannot connect to ETERNUS.')
                       % {'ag': ag})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            volmap = None
            for vo_volmap in vo_volmaplist:
                if vo_volmap in ag_volmaplist:
                    volmap = vo_volmap
                    break

            if volmap is None:
                continue

            try:
                volmapinstance = self._get_eternus_instance(
                    volmap,
                    LocalOnly=False)
            except Exception:
                msg = (_('_get_mapdata_iscsi, '
                         'volmap: %(volmap)s, '
                         'GetInstance, '
                         'cannot connect to ETERNUS.')
                       % {'volmap': volmap})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            target_lun = int(volmapinstance['DeviceNumber'], 16)

            target_portals.append(target_portal)
            target_iqns.append(target_iqn)
            target_luns.append(target_lun)

        if multipath:
            mapdata = {'target_portals': target_portals,
                       'target_iqns': target_iqns,
                       'target_luns': target_luns}
        else:
            mapdata = {'target_portal': target_portals[0],
                       'target_iqn': target_iqns[0],
                       'target_lun': target_luns[0]}

        LOG.debug('_get_mapdata_iscsi, mapdata: %s.', mapdata)
        return mapdata

    def _get_drvcfg(self, tagname, filename=None, multiple=False):
        """Read from driver configuration file."""
        if not filename:
            # Set default configuration file name.
            filename = self.configuration.cinder_eternus_config_file

        LOG.debug("_get_drvcfg, input[%(filename)s][%(tagname)s].",
                  {'filename': filename, 'tagname': tagname})

        tree = ET.parse(filename)
        elem = tree.getroot()

        if not multiple:
            ret = elem.findtext(".//" + tagname)
        else:
            ret = []
            for e in elem.findall(".//" + tagname):
                if e.text and (e.text not in ret):
                    ret.append(e.text)

        if not ret:
            msg = (_('_get_drvcfg, '
                     'filename: %(filename)s, '
                     'tagname: %(tagname)s, '
                     'data is None!! '
                     'Please edit driver configuration file and correct.')
                   % {'filename': filename,
                      'tagname': tagname})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return ret

    def _get_eternus_connection(self, filename=None):
        """return WBEM connection."""
        LOG.debug('_get_eternus_connection, filename: %s.', filename)

        ip = self._get_drvcfg('EternusIP', filename)
        port = self._get_drvcfg('EternusPort', filename)
        user = self._get_drvcfg('EternusUser', filename)
        passwd = self._get_drvcfg('EternusPassword', filename)
        url = 'http://' + ip + ':' + port

        conn = pywbem.WBEMConnection(url, (user, passwd),
                                     default_namespace='root/eternus')

        if conn is None:
            msg = (_('_get_eternus_connection, '
                     'filename: %(filename)s, '
                     'ip: %(ip)s, '
                     'port: %(port)s, '
                     'user: %(user)s, '
                     'passwd: ****, '
                     'url: %(url)s, '
                     'FAILED!!.')
                   % {'filename': filename,
                      'ip': ip,
                      'port': port,
                      'user': user,
                      'url': url})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_get_eternus_connection, conn: %s.', conn)
        return conn

    def _get_volume_name(self, volume, use_id=False):
        """Get volume_name on ETERNUS from volume on OpenStack."""
        LOG.debug('_get_volume_name, volume_id: %s.', volume['id'])

        if not use_id and volume['provider_location']:
            location = eval(volume['provider_location'])
            if 'vol_name' in location:
                LOG.debug('_get_volume_name, by provider_location, '
                          'vol_name: %s.', location['vol_name'])
                return location['vol_name']

        id_code = volume['id']

        m = md5(usedforsecurity=False)
        m.update(id_code.encode('utf-8'))

        # Pylint: disable=E1121.
        volumename = base64.urlsafe_b64encode(m.digest()).decode()
        vol_name = CONSTANTS.VOL_PREFIX + str(volumename)

        if self.model_name == CONSTANTS.DX_S2:
            LOG.debug('_get_volume_name, volume name is 16 digit.')
            vol_name = vol_name[:16]

        LOG.debug('_get_volume_name, by volume id, '
                  'vol_name: %s.', vol_name)
        return vol_name

    def _find_pool(self, eternus_pool, detail=False):
        """find Instance or InstanceName of pool by pool name on ETERNUS."""
        LOG.debug('_find_pool, pool name: %s.', eternus_pool)

        tppoollist = []
        rgpoollist = []

        # Get pools info form CIM instance(include info about instance path).
        try:
            tppoollist = self._enum_eternus_instances(
                'FUJITSU_ThinProvisioningPool')
            rgpoollist = self._enum_eternus_instances(
                'FUJITSU_RAIDStoragePool')
        except Exception:
            msg = (_('_find_pool, '
                     'eternus_pool:%(eternus_pool)s, '
                     'EnumerateInstances, '
                     'cannot connect to ETERNUS.')
                   % {'eternus_pool': eternus_pool})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Make total pools list.
        poollist = tppoollist + rgpoollist

        # One eternus backend has only one special pool name
        # so just use pool name can get the target pool.
        for pool in poollist:
            if pool['ElementName'] == eternus_pool:
                poolinstance = pool
                break
        else:
            poolinstance = None

        if poolinstance is None:
            ret = None
        elif detail is True:
            ret = poolinstance
        else:
            ret = poolinstance.path

        LOG.debug('_find_pool, pool: %s.', ret)
        return ret

    def _find_all_pools_instances(self, conn):
        LOG.debug('_find_all_pools_instances, conn: %s', conn)

        try:
            tppoollist = self._enum_eternus_instances(
                'FUJITSU_ThinProvisioningPool', conn=conn)
            rgpoollist = self._enum_eternus_instances(
                'FUJITSU_RAIDStoragePool', conn=conn)
        except Exception:
            msg = _('_find_pool, '
                    'eternus_pool:%(eternus_pool)s, '
                    'EnumerateInstances, '
                    'cannot connect to ETERNUS.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Make total pools list.
        tppools = [(tppool, 'TPP') for tppool in tppoollist]
        rgpools = [(rgpool, 'RAID') for rgpool in rgpoollist]
        poollist = tppools + rgpools

        LOG.debug('_find_all_pools_instances, poollist: %s', len(poollist))
        return poollist

    def _find_pools(self, poolname_list, conn,
                    poolinstances_list=None):
        """Find pool instances by using pool name on ETERNUS."""
        LOG.debug('_find_pools, pool names: %s.', poolname_list)

        target_poolname = list(poolname_list)
        pools = []

        # Get pools info from CIM instance(include info about instance path).
        if not poolinstances_list:
            poollist = self._find_all_pools_instances(conn)
            is_create = False
        else:
            poollist = poolinstances_list
            is_create = True

        for pool, ptype in poollist:
            poolname = pool['ElementName']

            LOG.debug('_find_pools, '
                      'pool: %(pool)s, ptype: %(ptype)s.',
                      {'pool': poolname, 'ptype': ptype})
            volume_count = None
            provisioned_capacity_mb = None
            fragment_size = None
            if poolname in target_poolname:
                if ptype == 'TPP':
                    param_dict = {
                        'pool-name': poolname
                    }
                    rc, errordesc, data = self._exec_eternus_cli(
                        'show_pool_provision',
                        **param_dict)

                    if rc != CONSTANTS.RC_OK:
                        msg = (_('_find_pools, show_pool_provision, '
                                 'pool name: %(pool_name)s, '
                                 'Return code: %(rc)lu, '
                                 'Error: %(errordesc)s, '
                                 'Message: %(job)s.')
                               % {'pool_name': poolname,
                                  'rc': rc,
                                  'errordesc': errordesc,
                                  'job': data})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                    provisioned_capacity_mb = data
                elif ptype == 'RAID':
                    # Get volume number and fragment capacity information
                    # only at creation time.
                    try:
                        volume_list = self._assoc_eternus_names(
                            pool.path,
                            conn=conn,
                            AssocClass='FUJITSU_AllocatedFromStoragePool',
                            ResultClass='FUJITSU_StorageVolume')

                        volume_count = len(volume_list)
                    except Exception:
                        msg = (_('_find_pools, '
                                 'poolname: %(poolname)s, '
                                 'pooltype: %(ptype)s, '
                                 'Associator Names, '
                                 'cannot connect to ETERNUS.')
                               % {'ptype': ptype,
                                  'poolname': poolname})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)

                    try:
                        sdpv_list = self._assoc_eternus_names(
                            pool.path,
                            conn=conn,
                            AssocClass='FUJITSU_AllocatedFromStoragePool',
                            ResultClass='FUJITSU_SDPVPool')
                        volume_count += len(sdpv_list)
                    except Exception:
                        msg = (_('_find_pools, '
                                 'pool name: %(poolname)s, '
                                 'Associator Names FUJITSU_SDPVPool, '
                                 'cannot connect to ETERNUS.')
                               % {'poolname': poolname})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)

                    try:
                        fragment_list = self._assoc_eternus(
                            pool.path,
                            conn=conn,
                            PropertyList=['NumberOfBlocks'],
                            AssocClass='FUJITSU_AssociatedRemainingExtent',
                            ResultClass='FUJITSU_FreeExtent')

                        if fragment_list:
                            fragment_size = max(
                                fragment_list,
                                key=lambda x: x['NumberOfBlocks'])
                        else:
                            fragment_size = {'NumberOfBlocks': 0}
                    except Exception:
                        # S2 models do not support this query.
                        fragment_size = {'NumberOfBlocks': -1}
                    fragment_size = fragment_size['NumberOfBlocks']

                poolinfo = self.create_pool_info(
                    pool,
                    volume_count,
                    ptype,
                    provisioned_capacity_mb=provisioned_capacity_mb,
                    fragment_size=fragment_size)

                target_poolname.remove(poolname)
                pools.append((poolinfo, poolname))

            if not target_poolname:
                break

        if not pools:
            LOG.warning('_find_pools, all the EternusPools in driver '
                        'configuration file are not exist. '
                        'Please edit driver configuration file.')

        # Sort pools in the order defined in driver configuration file.
        sorted_pools = (
            [pool for name in poolname_list for pool, pname in pools
             if name == pname])

        LOG.debug('_find_pools, '
                  'pools: %(pools)s, '
                  'notfound_pools: %(notfound_pools)s.',
                  {'pools': pools,
                   'notfound_pools': target_poolname})
        pools_stats = {'pools': []}
        for pool in sorted_pools:
            single_pool = {}
            if pool['type'] == 'TPP':
                thin_enabled = True
                max_ratio = self.configuration.max_over_subscription_ratio
            else:
                thin_enabled = False
                max_ratio = 1
                single_pool['total_volumes'] = pool['volume_count']
                single_pool['fragment_capacity_mb'] = \
                    pool['fragment_capacity_mb']

            single_pool.update(dict(
                path=pool['path'],
                pool_name=pool['name'],
                total_capacity_gb=pool['total_capacity_gb'],
                free_capacity_gb=pool['free_capacity_gb'],
                provisioned_capacity_gb=pool['provisioned_capacity_gb'],
                useable_capacity_gb=pool['useable_capacity_gb'],
                thin_provisioning_support=thin_enabled,
                thick_provisioning_support=not thin_enabled,
                max_over_subscription_ratio=max_ratio,
            ))

            if is_create:
                single_pool['useable_capacity_mb'] = \
                    pool['useable_capacity_mb']
            single_pool['multiattach'] = True
            pools_stats['pools'].append(single_pool)

        self.stats['shared_targets'] = True
        self.stats['backend_state'] = 'up'
        self.stats['pools'] = pools_stats['pools']

        return self.stats, target_poolname

    def _find_eternus_service(self, classname):
        """find CIM instance about service information."""
        LOG.debug('_find_eternus_service, '
                  'classname: %s.', classname)

        try:
            services = self._enum_eternus_instance_names(str(classname))
        except Exception:
            msg = (_('_find_eternus_service, '
                     'classname: %(classname)s, '
                     'EnumerateInstanceNames, '
                     'cannot connect to ETERNUS.')
                   % {'classname': classname})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        ret = services[0]
        LOG.debug('_find_eternus_service, '
                  'classname: %(classname)s, '
                  'ret: %(ret)s.',
                  {'classname': classname, 'ret': ret})
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-exec', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _exec_eternus_service(self, classname, instanceNameList, **param_dict):
        """Execute SMI-S Method."""
        LOG.debug('_exec_eternus_service, '
                  'classname: %(a)s, '
                  'instanceNameList: %(b)s, '
                  'parameters: %(c)s.',
                  {'a': classname,
                   'b': instanceNameList,
                   'c': param_dict})
        rc = None
        retdata = None
        # Use InvokeMethod.
        try:
            rc, retdata = self.conn.InvokeMethod(
                classname,
                instanceNameList,
                **param_dict)
        except Exception:
            if rc is None:
                msg = (_('_exec_eternus_service, '
                         'classname: %(classname)s, '
                         'InvokeMethod, '
                         'cannot connect to ETERNUS.')
                       % {'classname': classname})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # If the result has job information, wait for job complete
        if "Job" in retdata:
            rc = self._wait_for_job_complete(self.conn, retdata)

        if rc == CONSTANTS.DEVICE_IS_BUSY:
            msg = _('Device is in Busy state')
            raise exception.VolumeBackendAPIException(data=msg)

        errordesc = CONSTANTS.RETCODE_dic.get(str(rc),
                                              CONSTANTS.UNDEF_MSG)

        ret = (rc, errordesc, retdata)

        LOG.debug('_exec_eternus_service, '
                  'classname: %(a)s, '
                  'instanceNameList: %(b)s, '
                  'parameters: %(c)s, '
                  'Return code: %(rc)s, '
                  'Error: %(errordesc)s, '
                  'Return data: %(retdata)s.',
                  {'a': classname,
                   'b': instanceNameList,
                   'c': param_dict,
                   'rc': rc,
                   'errordesc': errordesc,
                   'retdata': retdata})
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-other', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _enum_eternus_instances(self, classname, conn=None, **param_dict):
        """Enumerate Instances."""
        LOG.debug('_enum_eternus_instances, classname: %s.', classname)

        if not conn:
            conn = self.conn

        ret = conn.EnumerateInstances(classname, **param_dict)

        LOG.debug('_enum_eternus_instances, enum %d instances.', len(ret))
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-other', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _enum_eternus_instance_names(self, classname):
        """Enumerate Instance Names."""
        LOG.debug('_enum_eternus_instance_names, classname: %s.', classname)

        ret = self.conn.EnumerateInstanceNames(classname)

        LOG.debug('_enum_eternus_instance_names, enum %d names.', len(ret))
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-getinstance', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _get_eternus_instance(self, classname, AllowNone=False, **param_dict):
        """Get Instance."""
        LOG.debug('_get_eternus_instance, '
                  'classname: %(cls)s, param: %(param)s.',
                  {'cls': classname, 'param': param_dict})

        ret = None
        try:
            ret = self.conn.GetInstance(classname, **param_dict)
        except Exception as e:
            if e.args[0] == 6 and AllowNone:
                return ret
            else:
                msg = _('_get_eternus_instance, Error:%s.') % e
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_get_eternus_instance, ret: %s.', ret)
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-other', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _assoc_eternus(self, classname, conn=None, **param_dict):
        """Associator."""
        LOG.debug('_assoc_eternus, '
                  'classname: %(cls)s, param: %(param)s.',
                  {'cls': classname, 'param': param_dict})

        if not conn:
            conn = self.conn

        ret = conn.Associators(classname, **param_dict)

        LOG.debug('_assoc_eternus, enum %d instances.', len(ret))
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-other', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _assoc_eternus_names(self, classname, conn=None, **param_dict):
        """Associator Names."""
        LOG.debug('_assoc_eternus_names, '
                  'classname: %(cls)s, param: %(param)s.',
                  {'cls': classname, 'param': param_dict})

        if not conn:
            conn = self.conn

        ret = conn.AssociatorNames(classname, **param_dict)

        LOG.debug('_assoc_eternus_names, enum %d names.', len(ret))
        return ret

    @lockutils.synchronized('ETERNUS-SMIS-other', 'cinder-', True)
    @utils.retry(exception.VolumeBackendAPIException)
    def _reference_eternus_names(self, classname, **param_dict):
        """Refference Names."""
        LOG.debug('_reference_eternus_names, '
                  'classname: %(cls)s, param: %(param)s.',
                  {'cls': classname, 'param': param_dict})

        ret = self.conn.ReferenceNames(classname, **param_dict)

        LOG.debug('_reference_eternus_names, enum %d names.', len(ret))
        return ret

    def _create_eternus_instance_name(self, classname, bindings):
        """create CIM InstanceName from classname and bindings."""
        LOG.debug('_create_eternus_instance_name, '
                  'classname: %(cls)s, bindings: %(bind)s.',
                  {'cls': classname, 'bind': bindings})

        bindings['CreationClassName'] = classname
        bindings['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'

        try:
            instancename = pywbem.CIMInstanceName(
                classname,
                namespace='root/eternus',
                keybindings=bindings)
        except NameError:
            instancename = None

        LOG.debug('_create_eternus_instance_name, ret: %s.', instancename)
        return instancename

    def _find_lun(self, volume):
        """Find lun instance from volume class or volumename on ETERNUS."""
        LOG.debug('_find_lun, volume id: %s.', volume['id'])
        volumeinstance = None
        volumename = self._get_volume_name(volume)

        try:
            location = eval(volume['provider_location'])
            classname = location['classname']
            bindings = location['keybindings']
            isSuccess = True

            if classname and bindings:
                LOG.debug('_find_lun, '
                          'classname: %(classname)s, '
                          'bindings: %(bindings)s.',
                          {'classname': classname,
                           'bindings': bindings})
                volume_instance_name = (
                    self._create_eternus_instance_name(classname, bindings))

                LOG.debug('_find_lun, '
                          'volume_insatnce_name: %(volume_instance_name)s.',
                          {'volume_instance_name': volume_instance_name})

                vol_instance = self._get_eternus_instance(volume_instance_name,
                                                          AllowNone=True)

                if vol_instance and vol_instance['ElementName'] == volumename:
                    volumeinstance = vol_instance
        except Exception:
            isSuccess = False
            LOG.debug('_find_lun, '
                      'Cannot get volume instance from provider location, '
                      'Search all volume using EnumerateInstanceNames.')

        if not isSuccess and self.model_name == CONSTANTS.DX_S2:
            # For old version.
            LOG.debug('_find_lun, '
                      'volumename: %(volumename)s.',
                      {'volumename': volumename})

            vol_name = {
                'source-name': volumename
            }
            # Get volume instance from volumename on ETERNUS.
            volumeinstance = self._find_lun_with_listup(**vol_name)

        LOG.debug('_find_lun, ret: %s.', volumeinstance)
        return volumeinstance

    def _find_copysession(self, vol_instance):
        """find copysession from volumename on ETERNUS."""
        LOG.debug('_find_copysession, volume name: %s.',
                  vol_instance['ElementName'])

        try:
            cpsessionlist = self.conn.ReferenceNames(
                vol_instance.path,
                ResultClass='FUJITSU_StorageSynchronized')
        except Exception:
            msg = (_('_find_copysession, '
                     'ReferenceNames, '
                     'vol_instance: %(vol_instance_path)s, '
                     'Cannot connect to ETERNUS.')
                   % {'vol_instance_path': vol_instance.path})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_find_copysession, '
                  'cpsessionlist: %(cpsessionlist)s.',
                  {'cpsessionlist': cpsessionlist})

        LOG.debug('_find_copysession, ret: %s.', cpsessionlist)
        return cpsessionlist

    def _wait_for_copy_complete(self, cpsession):
        """Wait for the completion of copy."""
        LOG.debug('_wait_for_copy_complete, cpsession: %s.', cpsession)

        cpsession_instance = None

        while True:
            try:
                cpsession_instance = self.conn.GetInstance(
                    cpsession,
                    LocalOnly=False)
            except Exception:
                cpsession_instance = None

            # if copy session is none,
            # it means copy session was finished,break and return
            if cpsession_instance is None:
                break

            LOG.debug('_wait_for_copy_complete, '
                      'find target copysession, '
                      'wait for end of copysession.')

            if cpsession_instance['CopyState'] == CONSTANTS.BROKEN:
                msg = (_('_wait_for_copy_complete, '
                         'cpsession: %(cpsession)s, '
                         'copysession state is BROKEN.')
                       % {'cpsession': cpsession})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            time.sleep(10)

    @utils.retry(exception.VolumeBackendAPIException)
    def _delete_copysession(self, cpsession):
        """delete copysession."""
        LOG.debug('_delete_copysession: cpssession: %s.', cpsession)

        try:
            cpsession_instance = self._get_eternus_instance(
                cpsession, LocalOnly=False)
        except Exception:
            LOG.info('_delete_copysession, '
                     'the copysession was already completed.')
            return

        copytype = cpsession_instance['CopyType']

        # set oparation code
        # SnapOPC: 19 (Return To ResourcePool)
        # OPC:8 (Detach)
        # EC/REC:8 (Detach)
        operation = CONSTANTS.OPERATION_dic.get(copytype, None)
        if operation is None:
            msg = (_('_delete_copysession, '
                     'copy session type is undefined! '
                     'copy session: %(cpsession)s, '
                     'copy type: %(copytype)s.')
                   % {'cpsession': cpsession,
                      'copytype': copytype})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        repservice = self._find_eternus_service(CONSTANTS.REPL)
        if repservice is None:
            msg = (_('_delete_copysession, '
                     'Cannot find Replication Service'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Invoke method for delete copysession
        rc, errordesc, job = self._exec_eternus_service(
            'ModifyReplicaSynchronization',
            repservice,
            Operation=self._pywbem_uint(operation, '16'),
            Synchronization=cpsession,
            Force=True,
            WaitForCopyState=self._pywbem_uint(15, '16'))

        LOG.debug('_delete_copysession, '
                  'copysession: %(cpsession)s, '
                  'operation: %(operation)s, '
                  'Return code: %(rc)lu, '
                  'Error: %(errordesc)s.',
                  {'cpsession': cpsession,
                   'operation': operation,
                   'rc': rc,
                   'errordesc': errordesc})

        if rc == CONSTANTS.COPYSESSION_NOT_EXIST:
            LOG.debug('_delete_copysession, '
                      'cpsession: %(cpsession)s, '
                      'copysession is not exist.',
                      {'cpsession': cpsession})
        elif rc == CONSTANTS.VOLUME_IS_BUSY:
            msg = (_('_delete_copysession, '
                     'copysession: %(cpsession)s, '
                     'operation: %(operation)s, '
                     'Error: Volume is in Busy state')
                   % {'cpsession': cpsession,
                      'operation': operation})
            raise exception.VolumeIsBusy(msg)
        elif rc != CONSTANTS.RC_OK:
            msg = (_('_delete_copysession, '
                     'copysession: %(cpsession)s, '
                     'operation: %(operation)s, '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s.')
                   % {'cpsession': cpsession,
                      'operation': operation,
                      'rc': rc,
                      'errordesc': errordesc})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_target_port(self):
        """return target portid."""
        LOG.debug('_get_target_port, protocol: %s.', self.protocol)

        target_portlist = []
        if self.protocol == 'fc':
            prtcl_endpoint = 'FUJITSU_SCSIProtocolEndpoint'
            connection_type = 2
        elif self.protocol == 'iSCSI':
            prtcl_endpoint = 'FUJITSU_iSCSIProtocolEndpoint'
            connection_type = 7

        try:
            tgtportlist = self._enum_eternus_instances(prtcl_endpoint)
        except Exception:
            msg = (_('_get_target_port, '
                     'EnumerateInstances, '
                     'cannot connect to ETERNUS.'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for tgtport in tgtportlist:
            # Check : protocol of tgtport
            if tgtport['ConnectionType'] != connection_type:
                continue

            # Check : if port is for remote copy, continue
            if (tgtport['RAMode'] & 0x7B) != 0x00:
                continue

            # Check : if port is for StorageCluster, continue
            if 'SCGroupNo' in tgtport:
                continue

            target_portlist.append(tgtport)

            LOG.debug('_get_target_port, '
                      'connection type: %(cont)s, '
                      'ramode: %(ramode)s.',
                      {'cont': tgtport['ConnectionType'],
                       'ramode': tgtport['RAMode']})

        LOG.debug('_get_target_port, '
                  'target port: %(target_portid)s.',
                  {'target_portid': target_portlist})

        if len(target_portlist) == 0:
            msg = (_('_get_target_port, '
                     'protcol: %(protocol)s, '
                     'target_port not found.')
                   % {'protocol': self.protocol})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_get_target_port, ret: %s.', target_portlist)
        return target_portlist

    @lockutils.synchronized('ETERNUS-connect', 'cinder-', True)
    def _map_lun(self, vol_instance, connector, targetlist=None):
        """map volume to host."""
        volumename = vol_instance['ElementName']
        LOG.debug('_map_lun, '
                  'volume name: %(vname)s, connector: %(connector)s.',
                  {'vname': volumename, 'connector': connector})

        volume_uid = vol_instance['Name']
        initiatorlist = self._find_initiator_names(connector)
        aglist = self._find_affinity_group(connector)
        configservice = self._find_eternus_service(CONSTANTS.CTRL_CONF)

        if targetlist is None:
            targetlist = self._get_target_port()

        if configservice is None:
            msg = (_('_map_lun, '
                     'vol_instance.path:%(vol)s, '
                     'volumename: %(volumename)s, '
                     'volume_uid: %(uid)s, '
                     'initiator: %(initiator)s, '
                     'target: %(tgt)s, '
                     'aglist: %(aglist)s, '
                     'Storage Configuration Service not found.')
                   % {'vol': vol_instance.path,
                      'volumename': volumename,
                      'uid': volume_uid,
                      'initiator': initiatorlist,
                      'tgt': targetlist,
                      'aglist': aglist})

            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_map_lun, '
                  'vol_instance.path: %(vol_instance)s, '
                  'volumename:%(volumename)s, '
                  'initiator:%(initiator)s, '
                  'target:%(tgt)s.',
                  {'vol_instance': vol_instance.path,
                   'volumename': [volumename],
                   'initiator': initiatorlist,
                   'tgt': targetlist})

        if not aglist:
            # Create affinity group and set host-affinity.
            for target in targetlist:
                LOG.debug('_map_lun, '
                          'lun_name: %(volume_uid)s, '
                          'Initiator: %(initiator)s, '
                          'target: %(target)s.',
                          {'volume_uid': [volume_uid],
                           'initiator': initiatorlist,
                           'target': target['Name']})

                rc, errordesc, job = self._exec_eternus_service(
                    'ExposePaths',
                    configservice,
                    LUNames=[volume_uid],
                    InitiatorPortIDs=initiatorlist,
                    TargetPortIDs=[target['Name']],
                    DeviceAccesses=[self._pywbem_uint(2, '16')])

                LOG.debug('_map_lun, '
                          'Error: %(errordesc)s, '
                          'Return code: %(rc)lu, '
                          'Create affinitygroup and set host-affinity.',
                          {'errordesc': errordesc,
                           'rc': rc})

                if rc != CONSTANTS.RC_OK and rc != CONSTANTS.LUNAME_IN_USE:
                    LOG.warning('_map_lun, '
                                'lun_name: %(volume_uid)s, '
                                'Initiator: %(initiator)s, '
                                'target: %(target)s, '
                                'Return code: %(rc)lu, '
                                'Error: %(errordesc)s.',
                                {'volume_uid': [volume_uid],
                                 'initiator': initiatorlist,
                                 'target': target['Name'],
                                 'rc': rc,
                                 'errordesc': errordesc})
        else:
            # Add lun to affinity group
            for ag in aglist:
                LOG.debug('_map_lun, '
                          'ag: %(ag)s, lun_name: %(volume_uid)s.',
                          {'ag': ag,
                           'volume_uid': volume_uid})

                rc, errordesc, job = self._exec_eternus_service(
                    'ExposePaths',
                    configservice, LUNames=[volume_uid],
                    DeviceAccesses=[self._pywbem_uint(2, '16')],
                    ProtocolControllers=[ag])

                LOG.debug('_map_lun, '
                          'Error: %(errordesc)s, '
                          'Return code: %(rc)lu, '
                          'Add lun to affinity group.',
                          {'errordesc': errordesc,
                           'rc': rc})

                if rc != CONSTANTS.RC_OK and rc != CONSTANTS.LUNAME_IN_USE:
                    LOG.warning('_map_lun, '
                                'lun_name: %(volume_uid)s, '
                                'Initiator: %(initiator)s, '
                                'ag: %(ag)s, '
                                'Return code: %(rc)lu, '
                                'Error: %(errordesc)s.',
                                {'volume_uid': [volume_uid],
                                 'initiator': initiatorlist,
                                 'ag': ag,
                                 'rc': rc,
                                 'errordesc': errordesc})

    def _find_initiator_names(self, connector):
        """return initiator names."""

        initiatornamelist = []

        if self.protocol == 'fc' and connector['wwpns']:
            LOG.debug('_find_initiator_names, wwpns: %s.',
                      connector['wwpns'])
            initiatornamelist = connector['wwpns']
        elif self.protocol == 'iSCSI' and connector['initiator']:
            LOG.debug('_find_initiator_names, initiator: %s.',
                      connector['initiator'])
            initiatornamelist.append(connector['initiator'])

        if not initiatornamelist:
            msg = (_('_find_initiator_names, '
                     'connector: %(connector)s, '
                     'initiator not found.')
                   % {'connector': connector})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_find_initiator_names, '
                  'initiator list: %(initiator)s.',
                  {'initiator': initiatornamelist})

        return initiatornamelist

    def _find_affinity_group(self, connector, vol_instance=None):
        """find affinity group from connector."""
        LOG.debug('_find_affinity_group, vol_instance: %s.', vol_instance)

        affinity_grouplist = []
        initiatorlist = self._find_initiator_names(connector)

        if vol_instance is None:
            try:
                aglist = self._enum_eternus_instance_names(
                    'FUJITSU_AffinityGroupController')
            except Exception:
                msg = (_('_find_affinity_group, '
                         'connector: %(connector)s, '
                         'EnumerateInstanceNames, '
                         'cannot connect to ETERNUS.')
                       % {'connector': connector})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            LOG.debug('_find_affinity_group,'
                      'affinity_groups:%s', aglist)
        else:
            try:
                aglist = self._assoc_eternus_names(
                    vol_instance.path,
                    AssocClass='FUJITSU_ProtocolControllerForUnit',
                    ResultClass='FUJITSU_AffinityGroupController')
            except Exception:
                msg = (_('_find_affinity_group,'
                         'connector: %(connector)s,'
                         'AssocNames: FUJITSU_ProtocolControllerForUnit, '
                         'cannot connect to ETERNUS.')
                       % {'connector': connector})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            LOG.debug('_find_affinity_group, '
                      'vol_instance.path: %(volume)s, '
                      'affinity_groups: %(aglist)s.',
                      {'volume': vol_instance.path,
                       'aglist': aglist})

        for ag in aglist:
            try:
                hostaglist = self._assoc_eternus(
                    ag,
                    AssocClass='FUJITSU_AuthorizedTarget',
                    ResultClass='FUJITSU_AuthorizedPrivilege')
            except Exception:
                msg = (_('_find_affinity_group, '
                         'connector: %(connector)s, '
                         'Associators: FUJITSU_AuthorizedTarget, '
                         'cannot connect to ETERNUS.')
                       % {'connector': connector})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            for hostag in hostaglist:
                for initiator in initiatorlist:
                    if initiator.lower() not in hostag['InstanceID'].lower():
                        continue

                    LOG.debug('_find_affinity_group, '
                              'AffinityGroup: %(ag)s.', {'ag': ag})
                    affinity_grouplist.append(ag)
                    break
                break

        LOG.debug('_find_affinity_group, '
                  'initiators: %(initiator)s, '
                  'affinity_group: %(affinity_group)s.',
                  {'initiator': initiatorlist,
                   'affinity_group': affinity_grouplist})
        return affinity_grouplist

    @lockutils.synchronized('ETERNUS-connect', 'cinder-', True)
    def _unmap_lun(self, volume, connector, force=False):
        """unmap volume from host."""
        LOG.debug('_map_lun, volume id: %(vid)s, '
                  'connector: %(connector)s, force: %(frc)s.',
                  {'vid': volume['id'],
                   'connector': connector, 'frc': force})

        volumename = self._get_volume_name(volume)
        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            LOG.info('_unmap_lun, '
                     'volumename:%(volumename)s, '
                     'volume not found.',
                     {'volumename': volumename})
            return False

        volume_uid = vol_instance['Name']

        if not force:
            aglist = self._find_affinity_group(connector, vol_instance)
            if not aglist:
                LOG.info('_unmap_lun, '
                         'volumename: %(volumename)s, '
                         'volume is not mapped.',
                         {'volumename': volumename})
                return False
        else:
            try:
                aglist = self._assoc_eternus_names(
                    vol_instance.path,
                    AssocClass='CIM_ProtocolControllerForUnit',
                    ResultClass='FUJITSU_AffinityGroupController')
            except Exception:
                msg = (_('_unmap_lun,'
                         'vol_instance.path: %(volume)s, '
                         'AssociatorNames: CIM_ProtocolControllerForUnit, '
                         'cannot connect to ETERNUS.')
                       % {'volume': vol_instance.path})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            LOG.debug('_unmap_lun, '
                      'vol_instance.path: %(volume)s, '
                      'affinity_groups: %(aglist)s.',
                      {'volume': vol_instance.path,
                       'aglist': aglist})

        configservice = self._find_eternus_service(CONSTANTS.CTRL_CONF)
        if configservice is None:
            msg = (_('_unmap_lun, '
                     'vol_instance.path: %(volume)s, '
                     'volumename: %(volumename)s, '
                     'volume_uid: %(uid)s, '
                     'aglist: %(aglist)s, '
                     'Controller Configuration Service not found.')
                   % {'vol': vol_instance.path,
                      'volumename': [volumename],
                      'uid': [volume_uid],
                      'aglist': aglist})

            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for ag in aglist:
            LOG.debug('_unmap_lun, '
                      'volumename: %(volumename)s, '
                      'volume_uid: %(volume_uid)s, '
                      'AffinityGroup: %(ag)s.',
                      {'volumename': volumename,
                       'volume_uid': volume_uid,
                       'ag': ag})

            rc, errordesc, job = self._exec_eternus_service(
                'HidePaths',
                configservice,
                LUNames=[volume_uid],
                ProtocolControllers=[ag])

            LOG.debug('_unmap_lun, '
                      'Error: %(errordesc)s, '
                      'Return code: %(rc)lu.',
                      {'errordesc': errordesc,
                       'rc': rc})

            if rc == CONSTANTS.LUNAME_NOT_EXIST:
                LOG.debug('_unmap_lun, '
                          'volumename: %(volumename)s, '
                          'Invalid LUNames.',
                          {'volumename': volumename})
            elif rc != CONSTANTS.RC_OK:
                msg = (_('_unmap_lun, '
                         'volumename: %(volumename)s, '
                         'volume_uid: %(volume_uid)s, '
                         'AffinityGroup: %(ag)s, '
                         'Return code: %(rc)lu, '
                         'Error: %(errordesc)s.')
                       % {'volumename': volumename,
                          'volume_uid': volume_uid,
                          'ag': ag,
                          'rc': rc,
                          'errordesc': errordesc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_unmap_lun, '
                  'volumename: %(volumename)s.',
                  {'volumename': volumename})
        return True

    def _get_eternus_iscsi_properties(self):
        """get target port iqns and target_portals."""

        iscsi_properties_list = []
        iscsiip_list = self._get_drvcfg('EternusISCSIIP', multiple=True)
        iscsi_port = self.configuration.target_port

        LOG.debug('_get_eternus_iscsi_properties, iplist: %s.', iscsiip_list)

        try:
            ip_endpointlist = self._enum_eternus_instance_names(
                'FUJITSU_IPProtocolEndpoint')
        except Exception:
            msg = (_('_get_eternus_iscsi_properties, '
                     'iscsiip: %(iscsiip)s, '
                     'EnumerateInstanceNames, '
                     'cannot connect to ETERNUS.')
                   % {'iscsiip': iscsiip_list})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for ip_endpoint in ip_endpointlist:
            try:
                ip_endpoint_instance = self._get_eternus_instance(
                    ip_endpoint)
                ip_address = ip_endpoint_instance['IPv4Address']
                LOG.debug('_get_eternus_iscsi_properties, '
                          'instanceip: %(ip)s, '
                          'iscsiip: %(iscsiip)s.',
                          {'ip': ip_address,
                           'iscsiip': iscsiip_list})
            except Exception:
                msg = (_('_get_eternus_iscsi_properties, '
                         'iscsiip: %(iscsiip)s, '
                         'GetInstance, '
                         'cannot connect to ETERNUS.')
                       % {'iscsiip': iscsiip_list})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            if ip_address not in iscsiip_list:
                continue

            LOG.debug('_get_eternus_iscsi_properties, '
                      'find iscsiip: %(ip)s.', {'ip': ip_address})
            try:
                tcp_endpointlist = self._assoc_eternus_names(
                    ip_endpoint,
                    AssocClass='CIM_BindsTo',
                    ResultClass='FUJITSU_TCPProtocolEndpoint')
            except Exception:
                msg = (_('_get_eternus_iscsi_properties, '
                         'iscsiip: %(iscsiip)s, '
                         'AssociatorNames: CIM_BindsTo, '
                         'cannot connect to ETERNUS.')
                       % {'iscsiip': ip_address})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            for tcp_endpoint in tcp_endpointlist:
                try:
                    iscsi_endpointlist = (
                        self._assoc_eternus(tcp_endpoint,
                                            AssocClass='CIM_BindsTo',
                                            ResultClass='FUJITSU_iSCSI'
                                            'ProtocolEndpoint'))
                except Exception:
                    msg = (_('_get_eternus_iscsi_properties, '
                             'iscsiip: %(iscsiip)s, '
                             'AssociatorNames: CIM_BindsTo, '
                             'cannot connect to ETERNUS.')
                           % {'iscsiip': ip_address})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

                for iscsi_endpoint in iscsi_endpointlist:
                    target_portal = "%s:%s" % (ip_address, iscsi_port)
                    iqn = iscsi_endpoint['Name'].split(',')[0]
                    iscsi_properties_list.append((iscsi_endpoint.path,
                                                  target_portal,
                                                  iqn))
                    LOG.debug('_get_eternus_iscsi_properties, '
                              'target_portal: %(target_portal)s, '
                              'iqn: %(iqn)s.',
                              {'target_portal': target_portal,
                               'iqn': iqn})

        if len(iscsi_properties_list) == 0:
            msg = (_('_get_eternus_iscsi_properties, '
                     'iscsiip list: %(iscsiip_list)s, '
                     'iqn not found.')
                   % {'iscsiip_list': iscsiip_list})

            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.debug('_get_eternus_iscsi_properties, '
                  'iscsi_properties_list: %(iscsi_properties_list)s.',
                  {'iscsi_properties_list': iscsi_properties_list})

        return iscsi_properties_list

    def _wait_for_job_complete(self, conn, job):
        """Given the job wait for it to complete."""
        self.retries = 0
        self.wait_for_job_called = False

        def _wait_for_job_complete():
            """Called at an interval until the job is finished."""
            if self._is_job_finished(conn, job):
                raise loopingcall.LoopingCallDone()
            if self.retries > CONSTANTS.JOB_RETRIES:
                LOG.error("_wait_for_job_complete, "
                          "failed after %(retries)d tries.",
                          {'retries': self.retries})
                raise loopingcall.LoopingCallDone()

            try:
                self.retries += 1
                if not self.wait_for_job_called:
                    if self._is_job_finished(conn, job):
                        self.wait_for_job_called = True
            except Exception:
                exceptionMessage = _("Issue encountered waiting for job.")
                LOG.exception(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        self.wait_for_job_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=CONSTANTS.JOB_INTERVAL_SEC).wait()

        jobInstanceName = job['Job']
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)

        rc = jobinstance['ErrorCode']

        LOG.debug('_wait_for_job_complete, rc: %s.', rc)
        return rc

    def _is_job_finished(self, conn, job):
        """Check if the job is finished."""
        jobInstanceName = job['Job']
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        jobstate = jobinstance['JobState']
        LOG.debug('_is_job_finished,'
                  'state: %(state)s', {'state': jobstate})
        # From ValueMap of JobState in CIM_ConcreteJob
        # 2=New, 3=Starting, 4=Running, 32767=Queue Pending
        # ValueMap("2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13..32767,
        # 32768..65535"),
        # Values("New, Starting, Running, Suspended, Shutting Down,
        # Completed, Terminated, Killed, Exception, Service,
        # Query Pending, DMTF Reserved, Vendor Reserved")]
        # NOTE(deva): string matching based on
        #             http://ipmitool.cvs.sourceforge.net/
        #               viewvc/ipmitool/ipmitool/lib/ipmi_chassis.c

        if jobstate in [2, 3, 4]:
            job_finished = False
        else:
            job_finished = True

        LOG.debug('_is_job_finished, finish: %s.', job_finished)
        return job_finished

    @staticmethod
    def _pywbem_uint(num, datatype):
        try:
            if datatype == '8':
                result = pywbem.Uint8(num)
            elif datatype == '16':
                result = pywbem.Uint16(num)
            elif datatype == '32':
                result = pywbem.Uint32(num)
            elif datatype == '64':
                result = pywbem.Uint64(num)
        except NameError:
            result = num

        return result

    def _find_lun_with_listup(self, conn=None, **kwargs):
        """Find lun instance with source name or source id on ETERNUS."""
        LOG.debug('_find_lun_with_listup start.')

        volumeinstance = None
        src_id = kwargs.get('source-id', None)
        src_name = kwargs.get('source-name', None)

        if not src_id and not src_name:
            msg = (_('_find_lun_with_listup, '
                     'source-name or source-id: %s, '
                     'Must specify source-name or source-id.')
                   % kwargs)
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(data=msg)

        if src_id and src_name:
            msg = (_('_find_lun_with_listup, '
                     'source-name or source-id: %s, '
                     'Must only specify source-name or source-id.')
                   % kwargs)
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(data=msg)

        if src_id and not src_id.isdigit():
            msg = (_('_find_lun_with_listup, '
                     'the specified source-id(%s) must be a decimal number.')
                   % src_id)
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(data=msg)

        # Get volume instance by volumename or volumeno on ETERNUS.
        try:
            propertylist = [
                'SystemName',
                'DeviceID',
                'ElementName',
                'Purpose',
                'BlockSize',
                'NumberOfBlocks',
                'Name',
                'OtherUsageDescription',
                'IsCompressed',
                'IsDeduplicated'
            ]
            vollist = self._enum_eternus_instances(
                'FUJITSU_StorageVolume',
                conn=conn,
                PropertyList=propertylist)
        except Exception:
            msg = (_('_find_lun_with_listup, '
                     'source-name or source-id: %s, '
                     'EnumerateVolumeInstance.')
                   % kwargs)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for vol_instance in vollist:
            if src_id:
                volume_no = self._get_volume_number(vol_instance)
                try:
                    # Skip hidden tppv volumes.
                    if int(src_id) == int(volume_no, 16):
                        volumeinstance = vol_instance
                        break
                except ValueError:
                    continue
            if src_name:
                if vol_instance['ElementName'] == src_name:
                    volumeinstance = vol_instance
                    break
        else:
            LOG.debug('_find_lun_with_listup, '
                      'source-name or source-id: %s, '
                      'volume not found on ETERNUS.', kwargs)

        LOG.debug('_find_lun_with_listup end, '
                  'volume instance: %s.', volumeinstance)
        return volumeinstance

    def _find_pool_from_volume(self, vol_instance, manage_type='volume'):
        """Find Instance or InstanceName of pool by volume instance."""
        LOG.debug('_find_pool_from_volume, volume: %(volume)s.',
                  {'volume': vol_instance})
        poolname = None
        target_pool = None
        filename = None
        conn = self.conn

        # Get poolname of volume on Eternus.
        try:
            pools = self._assoc_eternus(
                vol_instance.path,
                conn=conn,
                AssocClass='FUJITSU_AllocatedFromStoragePool',
                ResultClass='CIM_StoragePool')
        except Exception:
            msg = (_('_find_pool_from_volume, '
                     'vol_instance: %s, '
                     'Associators: FUJITSU_AllocatedFromStoragePool, '
                     'cannot connect to ETERNUS.')
                   % vol_instance.path)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if not pools:
            msg = (_('_find_pool_from_volume, '
                     'vol_instance: %s, '
                     'pool not found.')
                   % vol_instance.path)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Get poolname from driver configuration file.
        if manage_type == 'volume':
            cfgpool_list = list(self._get_drvcfg('EternusPool',
                                                 filename=filename,
                                                 multiple=True))
        elif manage_type == 'snapshot':
            cfgpool_list = list(self._get_drvcfg('EternusSnapPool',
                                                 filename=filename,
                                                 multiple=True))
        LOG.debug('_find_pool_from_volume, cfgpool_list: %(cfgpool_list)s.',
                  {'cfgpool_list': cfgpool_list})
        for pool in pools:
            if pool['ElementName'] in cfgpool_list:
                poolname = pool['ElementName']
                target_pool = pool.path
                break

        if not target_pool:
            msg = (_('_find_pool_from_volume, '
                     'vol_instance: %s, '
                     'the pool of volume not in driver configuration file.')
                   % vol_instance.path)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_find_pool_from_volume, poolname: %(poolname)s, '
                  'target_pool: %(target_pool)s.',
                  {'poolname': poolname, 'target_pool': target_pool})
        return poolname, target_pool

    def update_migrated_volume(self, ctxt, volume, new_volume):
        """Update migrated volume."""
        LOG.debug('update_migrated_volume, '
                  'source volume id: %(s_id)s, '
                  'target volume id: %(t_id)s.',
                  {'s_id': volume['id'], 't_id': new_volume['id']})

        model_update = None

        dst_metadata = self.get_metadata(new_volume)
        src_metadata = self.get_metadata(volume)

        LOG.debug('source: (%(src_meta)s)(%(src_loc)s), '
                  'target: (%(dst_meta)s)(%(dst_loc)s).',
                  {'src_meta': src_metadata,
                   'src_loc': volume['provider_location'],
                   'dst_meta': dst_metadata,
                   'dst_loc': new_volume['provider_location']})

        if volume['provider_location']:
            dst_location = new_volume['provider_location']
            model_update = {'_name_id': new_volume['id'],
                            'provider_location': dst_location}

        LOG.debug('update_migrated_volume, model_update: %s.',
                  model_update)
        return model_update

    def _get_eternus_model(self):
        """Get ENTERNUS model."""
        self.conn = self._get_eternus_connection()
        ret = CONSTANTS.DX_S3
        try:
            systemnamelist = self._enum_eternus_instances(
                'FUJITSU_StorageProduct', conn=self.conn)
        except Exception:
            msg = _('_get_eternus_model, EnumerateInstances, '
                    'cannot connect to ETERNUS.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        systemname = systemnamelist[0]['IdentifyingNumber']

        LOG.debug('_get_eternus_model, '
                  'systemname: %(systemname)s, '
                  'storage is DX S%(model)s.',
                  {'systemname': systemname,
                   'model': systemname[4]})

        if str(systemname[4]) == '2':
            ret = CONSTANTS.DX_S2

        return ret

    def _get_volume_number(self, vol):
        """Get volume no(return a hex string)."""
        if self.model_name == CONSTANTS.DX_S2:
            volume_number = "0x%04X" % int(vol['DeviceID'][-5:])
        else:
            volume_number = "0x" + vol['DeviceID'][24:28]

        LOG.debug('_get_volume_number: %s.', volume_number)
        return volume_number

    def _exec_eternus_smis_ReferenceNames(self, classname,
                                          conn=None,
                                          **param_dict):
        ret = conn.ReferenceNames(classname, **param_dict)
        return ret

    def _check_user(self):
        """Check whether user's role is accessible to ETERNUS and Software."""
        ret = True
        rc, errordesc, job = self._exec_eternus_cli('check_user_role')
        if rc != CONSTANTS.RC_OK:
            msg = (_('_check_user, '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s, '
                     'Message: %(job)s.')
                   % {'rc': rc,
                      'errordesc': errordesc,
                      'job': job})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if job != 'Software':
            msg = (_('_check_user, '
                     'Specified user(%(user)s) does not have '
                     'Software role: %(role)s.')
                   % {'user': self._get_drvcfg('EternusUser'),
                      'role': job})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return ret

    def _exec_eternus_cli(self, command, retry=CONSTANTS.TIMES_MIN,
                          retry_interval=CONSTANTS.RETRY_INTERVAL,
                          retry_code=['E0060'], filename=None,
                          **param_dict):
        """Execute ETERNUS CLI."""
        LOG.debug('_exec_eternus_cli, '
                  'command: %(a)s, '
                  'filename: %(f)s, '
                  'parameters: %(b)s.',
                  {'a': command,
                   'f': filename,
                   'b': param_dict})

        out = None
        rc = None
        retdata = None
        errordesc = None
        filename = self.configuration.cinder_eternus_config_file
        storage_ip = self._get_drvcfg('EternusIP', filename)
        if not self.fjdxcli.get(filename):
            user = self._get_drvcfg('EternusUser', filename)
            if self.passwordless:
                self.fjdxcli[filename] = (
                    eternus_dx_cli.FJDXCLI(user,
                                           storage_ip,
                                           keyfile=self.private_key_path))
            else:
                password = self._get_drvcfg('EternusPassword', filename)
                self.fjdxcli[filename] = (
                    eternus_dx_cli.FJDXCLI(user, storage_ip,
                                           password=password))

        for retry_num in range(retry):
            # Execute ETERNUS CLI and get return value.
            try:
                out = self.fjdxcli[filename].done(command, **param_dict)
                out_dict = out
                rc_str = out_dict.get('rc')
                retdata = out_dict.get('message')
            except Exception as ex:
                msg = (_('_exec_eternus_cli, '
                         'stdout: %(out)s, '
                         'unexpected error: %(ex)s.')
                       % {'out': out,
                          'ex': ex})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            if rc_str.startswith('E'):
                errordesc = rc_str
                rc = CONSTANTS.RC_FAILED
                if rc_str in retry_code:
                    LOG.info('_exec_eternus_cli, retry, '
                             'ip: %(ip)s, '
                             'RetryCode: %(rc)s, '
                             'TryNum: %(rn)s.',
                             {'ip': storage_ip,
                              'rc': rc_str,
                              'rn': (retry_num + 1)})
                    time.sleep(retry_interval)
                    continue
                else:
                    LOG.warning('_exec_eternus_cli, '
                                'WARNING!! '
                                'ip: %(ip)s, '
                                'ReturnCode: %(rc_str)s, '
                                'ReturnData: %(retdata)s.',
                                {'ip': storage_ip,
                                 'rc_str': rc_str,
                                 'retdata': retdata})
                    break
            else:
                if rc_str == str(CONSTANTS.RC_FAILED):
                    errordesc = rc_str
                    rc = CONSTANTS.RC_FAILED
                    if ('Authentication failed' in retdata and
                            retry_num + 1 < retry):
                        LOG.warning('_exec_eternus_cli, retry, ip: %(ip)s, '
                                    'Message: %(message)s, '
                                    'TryNum: %(rn)s.',
                                    {'ip': storage_ip,
                                     'message': retdata,
                                     'rn': (retry_num + 1)})
                        time.sleep(1)
                        continue
                else:
                    errordesc = None
                    rc = CONSTANTS.RC_OK
                break
        else:
            LOG.warning('_exec_eternus_cli, Retry was exceeded.')

        ret = (rc, errordesc, retdata)

        LOG.debug('_exec_eternus_cli, '
                  'command: %(a)s, '
                  'parameters: %(b)s, '
                  'ip: %(ip)s, '
                  'Return code: %(rc)s, '
                  'Error: %(errordesc)s.',
                  {'a': command,
                   'b': param_dict,
                   'ip': storage_ip,
                   'rc': rc,
                   'errordesc': errordesc})
        return ret

    @staticmethod
    def get_metadata(volume):
        """Get metadata using volume information."""
        LOG.debug('get_metadata, volume id: %s.',
                  volume['id'])

        d_metadata = {}

        metadata = volume.get('volume_metadata')

        # value={} enters the if branch, value=None enters the else.
        if metadata is not None:
            d_metadata = {
                data['key']: data['value'] for data in metadata
            }
        else:
            metadata = volume.get('metadata')
            if metadata:
                d_metadata = {
                    key: metadata[key] for key in metadata
                }

        LOG.debug('get_metadata, metadata is: %s.', d_metadata)
        return d_metadata

    def _set_qos(self, volume, use_id=False):
        """Set volume qos using ETERNUS CLI."""
        LOG.debug('_set_qos, volumeid: %(volumeid)s.',
                  {'volumeid': volume['id']})

        qos_support = self._is_qos_or_format_support('QOS setting')
        # Storage is DX S2 series, qos is not supported.
        if not qos_support:
            return

        qos_specs_dict = self._get_qos_specs(volume)
        if not qos_specs_dict:
            # Can not get anything from 'qos_specs_id'.
            return

        # Get storage version information.
        rc, emsg, clidata = self._exec_eternus_cli('show_enclosure_status')
        if rc != CONSTANTS.RC_OK:
            msg = (_('_set_qos, '
                     'show_enclosure_status failed. '
                     'Return code: %(rc)lu, '
                     'Error: %(errormsg)s, '
                     'Message: %(clidata)s.')
                   % {'rc': rc,
                      'errormsg': emsg,
                      'clidata': clidata})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        category_dict = {}
        unsupport = []

        # If storage version is before V11L30.
        if clidata['version'] < CONSTANTS.QOS_VERSION:
            for key, value in qos_specs_dict.items():
                if (key in CONSTANTS.FJ_QOS_KEY_BYTES_list or
                        key in CONSTANTS.FJ_QOS_KEY_IOPS_list):
                    msg = (_('_set_qos, Can not support QoS '
                             'parameter "%(key)s" on firmware version '
                             '%(version)s.')
                           % {'key': key,
                              'version': clidata['version']})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                if key in CONSTANTS.FJ_QOS_KEY_list:
                    category_dict = self._get_qos_category_by_value(
                        key, value)
                else:
                    unsupport.append(key)
            if unsupport:
                LOG.warning('_set_qos, '
                            'Can not support QoS parameter "%s".',
                            unsupport)

        # If storage version is after V11L30.
        if clidata['version'] >= 'V11L30-0000':
            key_dict = self._get_param(qos_specs_dict)
            if not key_dict:
                return

            # Get total/read/write bandwidth limit.
            category_dict = self._get_qos_category(key_dict)

        if category_dict:
            # Set volume qos.
            volumename = self._get_volume_name(volume, use_id=use_id)
            category_dict['volume-name'] = volumename
            rc, errordesc, job = self._exec_eternus_cli(
                'set_volume_qos',
                **category_dict)
            if rc != CONSTANTS.RC_OK:
                msg = (_('_set_qos, '
                         'set_volume_qos failed. '
                         'Return code: %(rc)lu, '
                         'Error: %(errordesc)s, '
                         'Message: %(job)s.')
                       % {'rc': rc,
                          'errordesc': errordesc,
                          'job': job})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    @staticmethod
    def _get_qos_specs(volume):
        """Get qos specs information from volume information."""
        LOG.debug('_get_qos_specs, volume id: %s.', volume['id'])

        qos_specs_dict = {}
        qos_specs_id = None
        ctxt = None

        volume_type_id = volume.get('volume_type_id')

        if volume_type_id:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, volume_type_id)
            qos_specs_id = volume_type.get('qos_specs_id')

        if qos_specs_id:
            qos_specs_dict = (
                qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs'])

        LOG.debug('_get_qos_specs, qos_specs_dict: %s.', qos_specs_dict)
        return qos_specs_dict

    def _is_qos_or_format_support(self, func_name):
        """If storage is DX S2 series, qos or format is not supported."""
        is_support = True

        if self.model_name == CONSTANTS.DX_S2:
            is_support = False
            LOG.warning('%s is not supported for DX S2, '
                        'Skip this process.', func_name)
        return is_support

    @staticmethod
    def _get_qos_category_by_value(key, value):
        """Get qos category using value."""
        LOG.debug('_get_qos_category_by_value, '
                  'key: %(key)s, value: %(value)s.',
                  {'key': key, 'value': value})

        ret = 0

        # Log error method.
        def _get_qos_category_by_value_error():
            """Input value is invalid, log error and raise exception."""
            msg = (_('_get_qos_category_by_value, '
                     'Invalid value is input, '
                     'key: %(key)s, '
                     'value: %(value)s.')
                   % {'key': key,
                      'value': value})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if key == "maxBWS":
            try:
                digit = int(float(value))
            except Exception:
                _get_qos_category_by_value_error()

            if digit >= 800:
                ret = 1
            elif digit >= 700:
                ret = 2
            elif digit >= 600:
                ret = 3
            elif digit >= 500:
                ret = 4
            elif digit >= 400:
                ret = 5
            elif digit >= 300:
                ret = 6
            elif digit >= 200:
                ret = 7
            elif digit >= 100:
                ret = 8
            elif digit >= 70:
                ret = 9
            elif digit >= 40:
                ret = 10
            elif digit >= 25:
                ret = 11
            elif digit >= 20:
                ret = 12
            elif digit >= 15:
                ret = 13
            elif digit >= 10:
                ret = 14
            elif digit > 0:
                ret = 15
            else:
                _get_qos_category_by_value_error()

        LOG.debug('_get_qos_category_by_value (%s).', ret)

        category_dict = {}
        if ret > 0:
            category_dict = {'bandwidth-limit': ret}

        return category_dict

    def _get_param(self, qos_specs_dict):
        # Get all keys which have been set and its value.
        LOG.debug('_get_param, '
                  'qos_specs_dict: %(qos_specs_dict)s.',
                  {'qos_specs_dict': qos_specs_dict})
        key_dict = {}
        unsupport = []
        for key, value in qos_specs_dict.items():
            if key in CONSTANTS.FJ_QOS_KEY_list:
                msg = (_('_get_param, Can not support QoS '
                         'parameter "%(key)s" on firmware version '
                         'V11L30-0000 or above.')
                       % {'key': key})
                LOG.warning(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            if key in CONSTANTS.FJ_QOS_KEY_BYTES_list:
                key_dict[key] = self._check_throughput(key, value)
                # Example: When "read_bytes_sec" is specified,
                # the corresponding "read_iops_sec" also needs to be specified.
                # If not, it is specified as the maximum.
                iopsStr = key.replace('bytes', 'iops')
                if iopsStr not in qos_specs_dict.keys():
                    key_dict[iopsStr] = CONSTANTS.MAX_IOPS
            elif key in CONSTANTS.FJ_QOS_KEY_IOPS_list:
                key_dict[key] = self._check_iops(key, value)
                # If can not get the corresponding bytes,
                # the bytes is set to the maximum value.
                throughputStr = key.replace('iops', 'bytes')
                if throughputStr not in qos_specs_dict.keys():
                    key_dict[throughputStr] = CONSTANTS.MAX_THROUGHPUT
            else:
                unsupport.append(key)
        if unsupport:
            LOG.warning('_get_param, '
                        'Can not support QoS parameter "%s".', unsupport)

        return key_dict

    def _check_iops(self, key, value):
        """Check input value of IOPS."""
        LOG.debug('_check_iops, key: %(key)s, value: %(value)s.',
                  {'key': key, 'value': value})
        value = int(float(value))
        if value < CONSTANTS.MIN_IOPS or value > CONSTANTS.MAX_IOPS:
            msg = (_('_check_iops, '
                     '%(key)s is out of range.')
                   % {'key': key})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return value

    def _check_throughput(self, key, value):
        LOG.debug('_check_throughput, key: %(key)s, value: %(value)s.',
                  {'key': key, 'value': value})
        value = float(value) / units.Mi
        if (value < CONSTANTS.MIN_THROUGHPUT or
                value > CONSTANTS.MAX_THROUGHPUT):
            msg = (_('_check_throughput, '
                     '%(key)s is out of range.')
                   % {'key': key})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return int(value)

    def _get_qos_category(self, key_dict):
        """Get qos category by parameters according to the specific volume."""
        LOG.debug('_get_qos_category, '
                  'key_dict: %(key_dict)s.',
                  {'key_dict': key_dict})

        # Get all the bandwidth limits.
        rc, errordesc, bandwidthlist = self._exec_eternus_cli(
            'show_qos_bandwidth_limit')
        if rc != CONSTANTS.RC_OK:
            msg = (_('_get_qos_category, '
                     'show_qos_bandwidth_limit failed. '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s, '
                     'Message: %(clidata)s.')
                   % {'rc': rc,
                      'errordesc': errordesc,
                      'clidata': bandwidthlist})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        ret_dict = {}
        for bw in bandwidthlist:
            if 'total_iops_sec' in key_dict.keys():
                if (bw['total_iops_sec'] == key_dict['total_iops_sec'] and
                        bw['total_bytes_sec'] == key_dict['total_bytes_sec']):
                    ret_dict['bandwidth-limit'] = bw['total_limit']
            if 'read_iops_sec' in key_dict.keys():
                if (bw['read_iops_sec'] == key_dict['read_iops_sec'] and
                        bw['read_bytes_sec'] == key_dict['read_bytes_sec']):
                    ret_dict['read-bandwidth-limit'] = bw['read_limit']
            if 'write_iops_sec' in key_dict.keys():
                if (bw['write_iops_sec'] == key_dict['write_iops_sec'] and
                        bw['write_bytes_sec'] == key_dict['write_bytes_sec']):
                    ret_dict['write-bandwidth-limit'] = bw['write_limit']

        # If find all available pairs.
        # len(key_dict) must be 2, 4 or 6
        if len(key_dict) / 2 == len(ret_dict):
            return ret_dict

        rc, errordesc, vqosdatalist = self._exec_eternus_cli('show_volume_qos')
        if rc != CONSTANTS.RC_OK:
            msg = (_('_get_qos_category, '
                     'show_volume_qos failed. '
                     'Return code: %(rc)lu, '
                     'Error: %(errordesc)s, '
                     'Message: %(clidata)s.')
                   % {'rc': rc,
                      'errordesc': errordesc,
                      'clidata': vqosdatalist})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Get used total/read/write bandwidth limit.
        totalusedlimits = set()
        readusedlimits = set()
        writeusedlimits = set()
        for vqos in vqosdatalist:
            totalusedlimits.add(vqos['total_limit'])
            readusedlimits.add(vqos['read_limit'])
            writeusedlimits.add(vqos['write_limit'])

        # Get unused total/read/write bandwidth limit.
        totalunusedlimits = list(set(range(1, 16)) - totalusedlimits)
        readunusedlimits = list(set(range(1, 16)) - readusedlimits)
        writeunusedlimits = list(set(range(1, 16)) - writeusedlimits)

        # If there is no same couple, set new qos bandwidth limit.
        if 'total_iops_sec' in key_dict.keys():
            if 'bandwidth-limit' not in ret_dict.keys():
                if len(totalunusedlimits) == 0:
                    msg = _('_get_qos_category, '
                            'There is no available total bandwidth limit.')
                    LOG.warning(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                else:
                    self._set_limit('volume-qos',
                                    totalunusedlimits[0],
                                    key_dict['total_iops_sec'],
                                    key_dict['total_bytes_sec'])
                    ret_dict['bandwidth-limit'] = totalunusedlimits[0]
        else:
            ret_dict['bandwidth-limit'] = 0

        if 'read_iops_sec' in key_dict.keys():
            if 'read-bandwidth-limit' not in ret_dict.keys():
                if len(readunusedlimits) == 0:
                    msg = _('_get_qos_category, '
                            'There is no available read bandwidth limit.')
                    LOG.warning(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                else:
                    self._set_limit('volume-qos-read',
                                    readunusedlimits[0],
                                    key_dict['read_iops_sec'],
                                    key_dict['read_bytes_sec'])
                    ret_dict['read-bandwidth-limit'] = readunusedlimits[0]
        else:
            ret_dict['read-bandwidth-limit'] = 0

        if 'write_bytes_sec' in key_dict.keys():
            if 'write-bandwidth-limit' not in ret_dict.keys():
                if len(writeunusedlimits) == 0:
                    msg = _('_get_qos_category, '
                            'There is no available write bandwidth limit.')
                    LOG.warning(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                else:
                    self._set_limit('volume-qos-write',
                                    writeunusedlimits[0],
                                    key_dict['write_iops_sec'],
                                    key_dict['write_bytes_sec'])
                    ret_dict['write-bandwidth-limit'] = writeunusedlimits[0]
        else:
            ret_dict['write-bandwidth-limit'] = 0

        return ret_dict

    def _set_limit(self, mode, limit, iops, throughput):
        """Register a new qos scheme at the specified bandwidth"""
        LOG.debug('_set_limit, mode: %(mode)s, '
                  'limit: %(limit)s, iops:%(iops)s, '
                  'throughput: %(throughput)s.',
                  {'mode': mode, 'limit': limit,
                   'iops': iops, 'throughput': throughput})
        param_dict = ({'mode': mode,
                       'bandwidth-limit': limit,
                       'iops': iops,
                       'throughput': throughput})

        rc, emsg, clidata = self._exec_eternus_cli(
            'set_qos_bandwidth_limit', **param_dict)

        if rc != CONSTANTS.RC_OK:
            msg = (_('_set_limit, '
                     'set_qos_bandwidth_limit failed. '
                     'Return code: %(rc)lu, '
                     'Error: %(errormsg)s, '
                     'Message: %(clidata)s.')
                   % {'rc': rc,
                      'errormsg': emsg,
                      'clidata': clidata})
            LOG.warning(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def revert_to_snapshot(self, volume, snapshot):
        """Revert volume to snapshot."""
        LOG.debug('revert_to_snapshot, Enter method, '
                  'volume id: %(vid)s, '
                  'snapshot id: %(sid)s. ',
                  {'vid': volume['id'], 'sid': snapshot['id']})

        vol_instance = self._find_lun(volume)
        sdv_instance = self._find_lun(snapshot)
        volume_no = self._get_volume_number(vol_instance)
        snapshot_no = self._get_volume_number(sdv_instance)

        # Check the existence of volume.
        if not vol_instance:
            msg = (_('revert_to_snapshot, '
                     'source volume not found on ETERNUS, '
                     'volume: %(volume)s. ')
                   % {'volume': volume})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Check the existence of sdv.
        if not sdv_instance:
            msg = (_('revert_to_snapshot, '
                     'snapshot volume not found on ETERNUS. '
                     'snapshot: %(snapshot)s. ')
                   % {'snapshot': snapshot})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        sdvsession = None
        cpsessionlist = self._find_copysession(vol_instance)

        LOG.debug('revert_to_snapshot, '
                  'cpsessionlist: %(cpsessionlist)s. ',
                  {'cpsessionlist': cpsessionlist})

        for cpsession in cpsessionlist:
            if (cpsession['SystemElement'].keybindings.get('DeviceID') ==
                    vol_instance.path.keybindings.get('DeviceID')):
                if (cpsession['SyncedElement'].keybindings.get('DeviceID') ==
                        sdv_instance.path.keybindings.get('DeviceID')):
                    sdvsession = cpsession
                    break

        if sdvsession:
            LOG.debug('revert_to_snapshot, '
                      'sdvsession: %(sdvsession)s. ',
                      {'sdvsession': sdvsession})

            repservice = self._find_eternus_service(
                "FUJITSU_ReplicationService")

            if repservice is None:
                msg = _('revert_to_snapshot, '
                        'Replication Service not found. ')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Invoke method for revert to snapshot
            rc, errordesc, job = self._exec_eternus_service(
                'ModifyReplicaSynchronization',
                repservice,
                Operation=self._pywbem_uint(15, '16'),
                WaitForCopyState=self._pywbem_uint(8, '16'),
                Synchronization=sdvsession)

            if rc != CONSTANTS.RC_OK:
                msg = (_('revert_to_snapshot, '
                         '_exec_eternus_service error, '
                         'volume: %(volume)s, '
                         'Return code: %(rc)lu, '
                         'Error: %(errordesc)s, '
                         'Message: %(job)s.')
                       % {'volume': volume['id'],
                          'rc': rc,
                          'errordesc': errordesc,
                          'job': job})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.debug('revert_to_snapshot, '
                          'successfully. ')
        else:
            is_find = False
            cp_session_list = self._get_copy_sessions_list()
            for cp in cp_session_list:
                if (cp['Source Num'] == int(volume_no, 16) and
                    cp['Dest Num'] == int(snapshot_no, 16) and
                        cp['Type'] == 'Snap'):
                    is_find = True
                    break

            if is_find is True:
                param_dict = (
                    {'source-volume-number': int(snapshot_no, 16),
                     'destination-volume-number': int(volume_no, 16)})

                rc, emsg, clidata = self._exec_eternus_cli(
                    'start_copy_opc',
                    **param_dict)

                if rc != CONSTANTS.RC_OK:
                    msg = (_('revert_to_snapshot, '
                             'start_copy_opc failed. '
                             'Return code: %(rc)lu, '
                             'Error: %(errormsg)s, '
                             'Message: %(clidata)s.')
                           % {'rc': rc,
                              'errormsg': emsg,
                              'clidata': clidata})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = (_('revert_to_snapshot, '
                         'snapshot volume not found on ETERNUS. '
                         'snapshot: %(snapshot)s. ')
                       % {'snapshot': snapshot})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('revert_to_snapshot, Exit method. ')

    def _get_copy_sessions_list(self, **param):
        """Get copy sessions list."""
        LOG.debug('_get_copy_sessions_list, Enter method.')

        rc, emsg, clidata = self._exec_eternus_cli(
            'show_copy_sessions',
            **param
        )

        if rc != CONSTANTS.RC_OK:
            msg = (_('_get_copy_sessions_list, '
                     'get copy sessions failed. '
                     'Return code: %(rc)lu, '
                     'Error: %(emsg)s, '
                     'Message: %(clidata)s.')
                   % {'rc': rc,
                      'emsg': emsg,
                      'clidata': clidata})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_get_copy_sessions_list, Exit method, '
                  'copy sessions list: %(clidata)s. ',
                  {'clidata': clidata})

        return clidata
