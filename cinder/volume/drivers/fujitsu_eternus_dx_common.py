# Copyright (c) 2014 FUJITSU LIMITED
# Copyright (c) 2012 - 2014 EMC Corporation.
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
Common class for SMI-S based FUJITSU ETERNUS DX volume drivers.

This common class is for FUJITSU ETERNUS DX volume drivers based on SMI-S.

"""

import base64
import hashlib
import time
from xml.dom.minidom import parseString

from oslo.config import cfg
import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import units
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

try:
    import pywbem
except ImportError:
    pass

CINDER_CONFIG_FILE = '/etc/cinder/cinder_fujitsu_eternus_dx.xml'
SMIS_ROOT = 'root/eternus'
PROVISIONING = 'storagetype:provisioning'
POOL = 'storagetype:pool'
STOR_CONF_SVC = 'FUJITSU_StorageConfigurationService'
SCSI_PROT_CTR = 'FUJITSU_AffinityGroupController'
STOR_HWID = 'FUJITSU_StorageHardwareID'
CTRL_CONF_SVC = 'FUJITSU_ControllerConfigurationService'
STOR_HWID_MNG_SVC = 'FUJITSU_StorageHardwareIDManagementService'
STOR_VOL = 'FUJITSU_StorageVolume'
REPL_SVC = 'FUJITSU_ReplicationService'
STOR_POOLS = ['FUJITSU_ThinProvisioningPool', 'FUJITSU_RAIDStoragePool']
AUTH_PRIV = 'FUJITSU_AuthorizedPrivilege'
STOR_SYNC = 'FUJITSU_StorageSynchronized'
VOL_PREFIX = 'FJosv_'

drv_opts = [
    cfg.StrOpt('cinder_smis_config_file',
               default=CINDER_CONFIG_FILE,
               help='The configuration file for the Cinder '
                    'SMI-S driver'), ]

CONF.register_opts(drv_opts)

BROKEN = 5
SNAPOPC = 4
OPC = 5
RETURN_TO_RESOURCEPOOL = 19
DETACH = 8
JOB_RETRIES = 60
INTERVAL_10_SEC = 10

OPERATION_dic = {SNAPOPC: RETURN_TO_RESOURCEPOOL,
                 OPC: DETACH
                 }

RETCODE_dic = {'0': 'Success',
               '1': 'Method Not Supported',
               '4': 'Failed',
               '5': 'Invalid Parameter',
               '4097': 'Size Not Supported',
               '32769': 'Maximum number of Logical Volume in'
                        ' a RAID group has been reached',
               '32770': 'Maximum number of Logical Volume in'
                        ' the storage device has been reached',
               '32771': 'Maximum number of registered Host WWN'
                        ' has been reached',
               '32772': 'Maximum number of affinity group has been reached',
               '32773': 'Maximum number of host affinity has been reached',
               '32785': 'The RAID group is in busy state',
               '32786': 'The Logical Volume is in busy state',
               '32787': 'The device is in busy state',
               '32788': 'Element Name is in use',
               '32792': 'No Copy License',
               '32796': 'Quick Format Error',
               '32801': 'The CA port is in invalid setting',
               '32802': 'The Logical Volume is Mainframe volume',
               '32803': 'The RAID group is not operative',
               '32804': 'The Logical Volume is not operative',
               '32808': 'No Thin Provisioning License',
               '32809': 'The Logical Element is ODX volume',
               '32811': 'This operation cannot be performed'
                        ' to the NAS resources',
               '32812': 'This operation cannot be performed'
                        ' to the Storage'
                        ' Cluster resources',
               '32816': 'Fatal error generic',
               '35302': 'Invalid LogicalElement',
               '35304': 'LogicalElement state error',
               '35316': 'Multi-hop error',
               '35318': 'Maximum number of multi-hop has been reached',
               '35324': 'RAID is broken',
               '35331': 'Maximum number of session has been reached'
                        '(per device)',
               '35333': 'Maximum number of session has been reached'
                        '(per SourceElement)',
               '35334': 'Maximum number of session has been reached'
                        '(per TargetElement)',
               '35335': 'Maximum number of Snapshot generation has been'
                        ' reached (per SourceElement)',
               '35346': 'Copy table size is not setup',
               '35347': 'Copy table size is not enough'
               }


class FJDXCommon(object):
    """Common code that can be used by ISCSI and FC drivers."""

    stats = {'driver_version': '1.2',
             'free_capacity_gb': 0,
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 0,
             'vendor_name': 'FUJITSU',
             'volume_backend_name': None}

    def __init__(self, prtcl, configuration=None):

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(drv_opts)

        ip, port = self._get_ecom_server()
        self.user, self.passwd = self._get_ecom_cred()
        self.url = 'http://' + ip + ':' + port
        self.conn = self._get_ecom_connection()

    def create_volume(self, volume):
        """Creates a volume."""
        LOG.debug('Entering create_volume.')
        volumesize = int(volume['size']) * units.Gi
        volumename = self._create_volume_name(volume['id'])

        LOG.info(_('Create Volume: %(volume)s  Size: %(size)lu')
                 % {'volume': volumename,
                    'size': volumesize})

        self.conn = self._get_ecom_connection()

        storage_type = self._get_storage_type(volume)

        LOG.debug('Create Volume: %(volume)s  '
                  'Storage type: %(storage_type)s'
                  % {'volume': volumename,
                     'storage_type': storage_type})

        pool, storage_system = self._find_pool(storage_type[POOL])

        LOG.debug('Create Volume: %(volume)s  Pool: %(pool)s  '
                  'Storage System: %(storage_system)s'
                  % {'volume': volumename,
                     'pool': pool,
                     'storage_system': storage_system})

        configservice = self._find_storage_configuration_service(
            storage_system)
        if configservice is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                   "Storage Configuration Service not found "
                                   "for pool %(storage_type)s.")
                                 % {'volumename': volumename,
                                    'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        provisioning = self._get_provisioning(storage_type)

        LOG.debug('Create Volume: %(name)s  Method: '
                  'CreateOrModifyElementFromStoragePool  ConfigServicie: '
                  '%(service)s  ElementName: %(name)s  InPool: %(pool)s  '
                  'ElementType: %(provisioning)s  Size: %(size)lu'
                  % {'service': configservice,
                     'name': volumename,
                     'pool': pool,
                     'provisioning': provisioning,
                     'size': volumesize})

        rc, job = self.conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            configservice, ElementName=volumename, InPool=pool,
            ElementType=self._getnum(provisioning, '16'),
            Size=self._getnum(volumesize, '64'))

        LOG.debug('Create Volume: %(volumename)s  Return code: %(rc)lu'
                  % {'volumename': volumename,
                     'rc': rc})

        if rc == 5L:
            # for DX S2
            # retry with 16 digit of volume name
            volumename = volumename[:16]
            LOG.debug('Retry with 16 digit of volume name.'
                      'Create Volume: %(name)s  Method: '
                      'CreateOrModifyElementFromStoragePool'
                      '  ConfigServicie: %(service)s'
                      '  ElementName: %(name)s  InPool: %(pool)s  '
                      'ElementType: %(provisioning)s  Size: %(size)lu'
                      % {'service': configservice,
                         'name': volumename,
                         'pool': pool,
                         'provisioning': provisioning,
                         'size': volumesize})

            rc, job = self.conn.InvokeMethod(
                'CreateOrModifyElementFromStoragePool',
                configservice, ElementName=volumename, InPool=pool,
                ElementType=self._getnum(provisioning, '16'),
                Size=self._getnum(volumesize, '64'))

            LOG.debug('Create Volume: %(volumename)s  Return code: %(rc)lu'
                      % {'volumename': volumename,
                         'rc': rc})

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]

            if rc != 0L:
                LOG.error(_('Error Create Volume: %(volumename)s.  '
                          'Return code: %(rc)lu.  Error: %(error)s')
                          % {'volumename': volumename,
                             'rc': rc,
                             'error': errordesc})
                raise exception.VolumeBackendAPIException(data=errordesc)

        # Find the newly created volume
        if "job" in job:
            associators = self.conn.Associators(
                job['Job'],
                resultClass=STOR_VOL)
            volpath = associators[0].path
        else:  # for ETERNUS DX
            volpath = job['TheElement']

        name = {}
        name['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        name['keybindings'] = keys

        LOG.debug('Leaving create_volume: %(volumename)s  '
                  'Return code: %(rc)lu '
                  'volume instance: %(name)s'
                  % {'volumename': volumename,
                     'rc': rc,
                     'name': name})

        return name

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug('Entering create_volume_from_snapshot.')

        snapshotname = snapshot['name']
        volumename = self._create_volume_name(volume['id'])
        vol_instance = None

        LOG.info(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                   'Snapshot: %(snapshotname)s')
                 % {'volumename': volumename,
                    'snapshotname': snapshotname})

        self.conn = self._get_ecom_connection()

        snapshot_instance = self._find_lun(snapshot)
        storage_system = snapshot_instance['SystemName']

        LOG.debug('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Snapshot Instance: '
                  '%(snapshotinstance)s  Storage System: %(storage_system)s.'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'snapshotinstance': snapshot_instance.path,
                     'storage_system': storage_system})

        repservice = self._find_replication_service(storage_system)
        if repservice is None:
            exception_message = (_('Error Create Volume from Snapshot: '
                                   'Volume: %(volumename)s  Snapshot: '
                                   '%(snapshotname)s. Cannot find Replication '
                                   'Service to create volume from snapshot.')
                                 % {'volumename': volumename,
                                    'snapshotname': snapshotname})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Method: CreateElementReplica  '
                  'ReplicationService: %(service)s  ElementName: '
                  '%(elementname)s  SyncType: 8  SourceElement: '
                  '%(sourceelement)s'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'service': repservice,
                     'elementname': volumename,
                     'sourceelement': snapshot_instance.path})

        # Create a Clone from snapshot
        name = self.create_volume(volume)
        instancename = self._getinstancename(name['classname'],
                                             name['keybindings'])
        vol_instance = self.conn.GetInstance(instancename)

        rc, job = self.conn.InvokeMethod(
            'CreateElementReplica', repservice,
            ElementName=volumename,
            SyncType=self._getnum(8, '16'),
            SourceElement=snapshot_instance.path,
            TargetElement=vol_instance.path)

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]

            if rc != 0L:
                exception_message = (_('Error Create Volume from Snapshot: '
                                       'Volume: %(volumename)s  Snapshot:'
                                       '%(snapshotname)s.  '
                                       'Return code: %(rc)lu.'
                                       'Error: %(error)s')
                                     % {'volumename': volumename,
                                        'snapshotname': snapshotname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                volume['provider_location'] = six.text_type(name)
                self.delete_volume(volume)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        # Find the newly created volume
        if "job" in job:
            associators = self.conn.Associators(
                job['Job'],
                resultClass=STOR_VOL)
            volpath = associators[0].path
        else:  # for ETERNUS DX
            volpath = job['TargetElement']

        name = {}
        name['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        name['keybindings'] = keys

        LOG.debug('Leaving create_volume_from_snapshot: Volume: '
                  '%(volumename)s Snapshot: %(snapshotname)s  '
                  'Return code: %(rc)lu.'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        return name

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug('Entering create_cloned_volume.')

        srcname = self._create_volume_name(src_vref['id'])
        volumename = self._create_volume_name(volume['id'])

        LOG.info(_('Create a Clone from Volume: Volume: %(volumename)s  '
                   'Source Volume: %(srcname)s')
                 % {'volumename': volumename,
                    'srcname': srcname})

        self.conn = self._get_ecom_connection()

        src_instance = self._find_lun(src_vref)
        storage_system = src_instance['SystemName']

        LOG.debug('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s  Source Instance: '
                  '%(src_instance)s  Storage System: %(storage_system)s.'
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'src_instance': src_instance.path,
                     'storage_system': storage_system})

        repservice = self._find_replication_service(storage_system)
        if repservice is None:
            exception_message = (_('Error Create Cloned Volume: '
                                   'Volume: %(volumename)s  Source Volume: '
                                   '%(srcname)s. Cannot find Replication '
                                   'Service to create cloned volume.')
                                 % {'volumename': volumename,
                                    'srcname': srcname})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s  Method: CreateElementReplica  '
                  'ReplicationService: %(service)s  ElementName: '
                  '%(elementname)s  SyncType: 8  SourceElement: '
                  '%(sourceelement)s'
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'service': repservice,
                     'elementname': volumename,
                     'sourceelement': src_instance.path})

        # Create a Clone from source volume
        name = self.create_volume(volume)
        instancename = self._getinstancename(name['classname'],
                                             name['keybindings'])
        vol_instance = self.conn.GetInstance(instancename)

        rc, job = self.conn.InvokeMethod(
            'CreateElementReplica', repservice,
            ElementName=volumename,
            SyncType=self._getnum(8, '16'),
            SourceElement=src_instance.path,
            TargetElement=vol_instance.path)

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]

            if rc != 0L:
                exception_message = (_('Error Create Cloned Volume: '
                                       'Volume: %(volumename)s  Source Volume:'
                                       '%(srcname)s.  Return code: %(rc)lu.'
                                       'Error: %(error)s')
                                     % {'volumename': volumename,
                                        'srcname': srcname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                volume['provider_location'] = six.text_type(name)
                self.delete_volume(volume)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        # Find the newly created volume
        if "job" in job:
            associators = self.conn.Associators(
                job['Job'],
                resultClass=STOR_VOL)
            volpath = associators[0].path
        else:  # for ETERNUS DX
            volpath = job['TargetElement']
        name = {}
        name['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        name['keybindings'] = keys

        LOG.debug('Leaving create_cloned_volume: Volume: '
                  '%(volumename)s Source Volume: %(srcname)s  '
                  'Return code: %(rc)lu.'
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'rc': rc})

        return name

    def delete_volume(self, volume):
        """Deletes an volume."""
        LOG.debug('Entering delete_volume.')
        volumename = self._create_volume_name(volume['id'])
        LOG.info(_('Delete Volume: %(volume)s')
                 % {'volume': volumename})

        self.conn = self._get_ecom_connection()

        cpsession, storage_system = self._find_copysession(volume)
        if cpsession is not None:
            LOG.debug('delete_volume,volumename:%(volumename)s,'
                      'volume is using by copysession[%(cpsession)s].'
                      'delete copysession.'
                      % {'volumename': volumename,
                         'cpsession': cpsession})
            self._delete_copysession(storage_system, cpsession)

        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            LOG.error(_('Volume %(name)s not found on the array. '
                        'No volume to delete.')
                      % {'name': volumename})
            return

        configservice =\
            self._find_storage_configuration_service(storage_system)
        if configservice is None:
            exception_message = (_("Error Delete Volume: %(volumename)s. "
                                   "Storage Configuration Service not found.")
                                 % {'volumename': volumename})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        device_id = vol_instance['DeviceID']

        LOG.debug('Delete Volume: %(name)s  DeviceID: %(deviceid)s'
                  % {'name': volumename,
                     'deviceid': device_id})

        LOG.debug('Delete Volume: %(name)s  Method: ReturnToStoragePool '
                  'ConfigServic: %(service)s  TheElement: %(vol_instance)s'
                  % {'service': configservice,
                     'name': volumename,
                     'vol_instance': vol_instance.path})

        rc, job =\
            self.conn.InvokeMethod('ReturnToStoragePool',
                                   configservice,
                                   TheElement=vol_instance.path)

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]
            if rc != 0L:
                exception_message = (_('Error Delete Volume: %(volumename)s.  '
                                       'Return code: %(rc)lu.  '
                                       'Error: %(error)s')
                                     % {'volumename': volumename,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug('Leaving delete_volume: %(volumename)s  Return code: '
                  '%(rc)lu'
                  % {'volumename': volumename,
                     'rc': rc})

    def create_snapshot(self, snapshot, volume):
        """Creates a snapshot."""
        LOG.debug('Entering create_snapshot.')

        snapshotname = self._create_volume_name(snapshot['id'])
        volumename = snapshot['volume_name']
        LOG.info(_('Create snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        self.conn = self._get_ecom_connection()

        vol_instance = self._find_lun(volume)

        device_id = vol_instance['DeviceID']
        snappool = self._get_snappool_conffile()
        pool, storage_system = self._find_pool(snappool)

        LOG.debug('Device ID: %(deviceid)s: Storage System: '
                  '%(storagesystem)s'
                  % {'deviceid': device_id,
                     'storagesystem': storage_system})

        repservice = self._find_replication_service(storage_system)
        if repservice is None:
            LOG.error(_("Cannot find Replication Service to create snapshot "
                        "for volume %s.") % volumename)
            exception_message = (_("Cannot find Replication Service to "
                                   "create snapshot for volume %s.")
                                 % volumename)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Create Snapshot:  Method: CreateElementReplica: "
                  "Target: %(snapshot)s  Source: %(volume)s  Replication "
                  "Service: %(service)s  ElementName: %(elementname)s  Sync "
                  "Type: 7  SourceElement: %(sourceelement)s."
                  % {'snapshot': snapshotname,
                     'volume': volumename,
                     'service': repservice,
                     'elementname': snapshotname,
                     'sourceelement': vol_instance.path})

        rc, job =\
            self.conn.InvokeMethod('CreateElementReplica', repservice,
                                   ElementName=snapshotname,
                                   SyncType=self._getnum(7, '16'),
                                   TargetPool=pool,
                                   SourceElement=vol_instance.path)

        LOG.debug('Create Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Return code: %(rc)lu'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        if rc == 5L:
            # for DX S2
            # retry by CreateReplica
            snapshotname = snapshotname[:16]
            LOG.debug('retry Create Snapshot: '
                      'snapshotname:%(snapshotname)s,'
                      'source volume name:%(volumename)s,'
                      'vol_instance.path:%(vol_instance)s,'
                      'Invoke CreateReplica'
                      % {'snapshotname': snapshotname,
                         'volumename': volumename,
                         'vol_instance': six.text_type(vol_instance.path)})

            configservice = self._find_storage_configuration_service(
                storage_system)
            if configservice is None:
                exception_message = (_("Create Snapshot: %(snapshotname)s. "
                                       "Storage Configuration Service "
                                       "not found")
                                     % {'snapshotname': snapshotname})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            # Invoke method for create snapshot
            rc, job = self.conn.InvokeMethod(
                'CreateReplica',
                configservice,
                ElementName=snapshotname,
                TargetPool=pool,
                CopyType=self._getnum(4, '16'),
                SourceElement=vol_instance.path)

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]
            if rc != 0L:
                exception_message = (_('Error Create Snapshot: %(snapshot)s '
                                       'Volume: %(volume)s '
                                       'Error: %(errordesc)s')
                                     % {'snapshot': snapshotname,
                                        'volume': volumename,
                                        'errordesc': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        # Find the newly created volume
        if "job" in job:
            associators = self.conn.Associators(
                job['Job'],
                resultClass=STOR_VOL)
            volpath = associators[0].path
        else:  # for ETERNUS DX
            volpath = job['TargetElement']

        name = {}
        name['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        name['keybindings'] = keys

        LOG.debug('Leaving create_snapshot: Snapshot: %(snapshot)s '
                  'Volume: %(volume)s  Return code: %(rc)lu.' %
                  {'snapshot': snapshotname, 'volume': volumename, 'rc': rc})

        return name

    def delete_snapshot(self, snapshot, volume):
        """Deletes a snapshot."""
        LOG.debug('Entering delete_snapshot.')

        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        LOG.info(_('Delete Snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        self.conn = self._get_ecom_connection()

        LOG.debug('Delete Snapshot: %(snapshot)s: volume: %(volume)s. '
                  'Finding StorageSychronization_SV_SV.'
                  % {'snapshot': snapshotname,
                     'volume': volumename})

        sync_name, storage_system =\
            self._find_storage_sync_sv_sv(snapshot, volume, False)
        if sync_name is None:
            LOG.error(_('Snapshot: %(snapshot)s: volume: %(volume)s '
                        'not found on the array. No snapshot to delete.')
                      % {'snapshot': snapshotname,
                         'volume': volumename})
            return

        repservice = self._find_replication_service(storage_system)
        if repservice is None:
            exception_message = (_("Cannot find Replication Service to "
                                   "create snapshot for volume %s.")
                                 % volumename)
            raise exception.VolumeBackendAPIException(data=exception_message)

        # Delete snapshot - deletes both the target element
        # and the snap session
        LOG.debug("Delete Snapshot: Target: %(snapshot)s  "
                  "Source: %(volume)s.  Method: "
                  "ModifyReplicaSynchronization:  "
                  "Replication Service: %(service)s  Operation: 19  "
                  "Synchronization: %(sync_name)s."
                  % {'snapshot': snapshotname,
                     'volume': volumename,
                     'service': repservice,
                     'sync_name': sync_name})

        rc, job =\
            self.conn.InvokeMethod('ModifyReplicaSynchronization',
                                   repservice,
                                   Operation=self._getnum(19, '16'),
                                   Synchronization=sync_name)

        LOG.debug('Delete Snapshot: Volume: %(volumename)s  Snapshot: '
                  '%(snapshotname)s  Return code: %(rc)lu'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(self.conn, job)
            if rc != 0L:
                exception_message = (_('Error Delete Snapshot: Volume: '
                                       '%(volumename)s  Snapshot: '
                                       '%(snapshotname)s. '
                                       'Return code: %(rc)lu.'
                                       ' Error: %(error)s')
                                     % {'volumename': volumename,
                                        'snapshotname': snapshotname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        # It takes a while for the relationship between the snapshot
        # and the source volume gets cleaned up.  Needs to wait until
        # it is cleaned up.  Otherwise, the source volume can't be
        # deleted immediately after the snapshot deletion because it
        # still has snapshot.
        wait_timeout = int(self._get_timeout())
        wait_interval = 10
        start = int(time.time())

        def _wait_for_job():
            try:
                sync_name, storage_system =\
                    self._find_storage_sync_sv_sv(snapshot, volume, False)
                if sync_name is None:
                    LOG.info(_('Snapshot: %(snapshot)s: volume: %(volume)s. '
                               'Snapshot is deleted.')
                             % {'snapshot': snapshotname,
                                'volume': volumename})
                    raise loopingcall.LoopingCallDone()
                if int(time.time()) - start >= wait_timeout:
                    LOG.warn(_('Snapshot: %(snapshot)s: volume: %(volume)s. '
                               'Snapshot deleted but cleanup timed out.')
                             % {'snapshot': snapshotname,
                                'volume': volumename})
                    raise loopingcall.LoopingCallDone()
            except Exception as ex:
                if ex.args[0] == 6:
                    # 6 means object not found, so snapshot is deleted cleanly
                    LOG.info(_('Snapshot: %(snapshot)s: volume: %(volume)s. '
                               'Snapshot is deleted.')
                             % {'snapshot': snapshotname,
                                'volume': volumename})
                else:
                    LOG.warn(_('Snapshot: %(snapshot)s: volume: %(volume)s. '
                               'Snapshot deleted but error during cleanup. '
                               'Error: %(error)s')
                             % {'snapshot': snapshotname,
                                'volume': volumename,
                                'error': six.text_type(ex.args)})
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_job)
        timer.start(interval=wait_interval)

        LOG.debug('Leaving delete_snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Return code: %(rc)lu.'
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

    # Mapping method
    def _expose_paths(self, configservice, vol_instance,
                      connector):
        """This method maps a volume to a host.

        It adds a volume and initiator to a Storage Group
        and therefore maps the volume to the host.
        """
        results = []
        volumename = vol_instance['ElementName']
        lun_name = vol_instance['Name']
        initiators = self._find_initiator_names(connector)
        storage_system = vol_instance['SystemName']
        lunmask_ctrls = self._find_lunmasking_scsi_protocol_controller(
            storage_system, connector)
        targets = self.get_target_portid(connector)

        if len(lunmask_ctrls) == 0:
            # create new lunmasking
            for target in targets:
                LOG.debug('ExposePaths: %(vol)s  ConfigServicie: %(service)s  '
                          'LUNames: %(lun_name)s  '
                          'InitiatorPortIDs: %(initiator)s  '
                          'TargetPortIDs: %(target)s  DeviceAccesses: 2'
                          % {'vol': vol_instance.path,
                             'service': configservice,
                             'lun_name': lun_name,
                             'initiator': initiators,
                             'target': target})

                rc, controller =\
                    self.conn.InvokeMethod('ExposePaths',
                                           configservice, LUNames=[lun_name],
                                           InitiatorPortIDs=initiators,
                                           TargetPortIDs=[target],
                                           DeviceAccesses=[self._getnum(2, '16'
                                                                        )])
                results.append(rc)
                if rc != 0L:
                    msg = (_('Error mapping volume %(volumename)s.rc:%(rc)lu')
                           % {'volumename': volumename, 'rc': rc})
                    LOG.warn(msg)

        else:
            # add lun to lunmasking
            for lunmask_ctrl in lunmask_ctrls:
                LOG.debug('ExposePaths parameter '
                          'LunMaskingSCSIProtocolController: '
                          '%(lunmasking)s'
                          % {'lunmasking': lunmask_ctrl})
                rc, controller =\
                    self.conn.InvokeMethod('ExposePaths',
                                           configservice, LUNames=[lun_name],
                                           DeviceAccesses=[
                                               self._getnum(2, '16')],
                                           ProtocolControllers=[lunmask_ctrl])
                results.append(rc)
                if rc != 0L:
                    msg = (_('Error mapping volume %(volumename)s.rc:%(rc)lu')
                           % {'volumename': volumename, 'rc': rc})
                    LOG.warn(msg)

        if 0L not in results:
            msg = (_('Error mapping volume %(volumename)s:%(results)s.')
                   % {'volumename': volumename, 'results': results})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('ExposePaths for volume %s completed successfully.'
                  % volumename)

    # Unmapping method
    def _hide_paths(self, configservice, vol_instance,
                    connector):
        """This method unmaps a volume from the host.

        Removes a volume from the Storage Group
        and therefore unmaps the volume from the host.
        """
        volumename = vol_instance['ElementName']
        lun_name = vol_instance['Name']
        lunmask_ctrls =\
            self._find_lunmasking_scsi_protocol_controller_for_vol(
                vol_instance, connector)

        for lunmask_ctrl in lunmask_ctrls:
            LOG.debug('HidePaths: %(vol)s  ConfigServicie: %(service)s  '
                      'LUNames: %(lun_name)s'
                      '  LunMaskingSCSIProtocolController: '
                      '%(lunmasking)s'
                      % {'vol': vol_instance.path,
                         'service': configservice,
                         'lun_name': lun_name,
                         'lunmasking': lunmask_ctrl})

            rc, controller = self.conn.InvokeMethod(
                'HidePaths', configservice,
                LUNames=[lun_name], ProtocolControllers=[lunmask_ctrl])

            if rc != 0L:
                msg = (_('Error unmapping volume %(volumename)s.rc:%(rc)lu')
                       % {'volumename': volumename, 'rc': rc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('HidePaths for volume %s completed successfully.'
                  % volumename)

    def _map_lun(self, volume, connector):
        """Maps a volume to the host."""
        volumename = self._create_volume_name(volume['id'])
        LOG.info(_('Map volume: %(volume)s')
                 % {'volume': volumename})

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        configservice = self._find_controller_configuration_service(
            storage_system)
        if configservice is None:
            exception_message = (_("Cannot find Controller Configuration "
                                   "Service for storage system %s")
                                 % storage_system)
            raise exception.VolumeBackendAPIException(data=exception_message)

        self._expose_paths(configservice, vol_instance, connector)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host."""
        volumename = self._create_volume_name(volume['id'])
        LOG.info(_('Unmap volume: %(volume)s')
                 % {'volume': volumename})

        device_info = self.find_device_number(volume, connector)
        device_number = device_info['hostlunid']
        if device_number is None:
            LOG.info(_("Volume %s is not mapped. No volume to unmap.")
                     % (volumename))
            return

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        configservice = self._find_controller_configuration_service(
            storage_system)
        if configservice is None:
            exception_message = (_("Cannot find Controller Configuration "
                                   "Service for storage system %s")
                                 % storage_system)
            raise exception.VolumeBackendAPIException(data=exception_message)
        self._hide_paths(configservice, vol_instance, connector)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""
        volumename = self._create_volume_name(volume['id'])
        LOG.info(_('Initialize connection: %(volume)s')
                 % {'volume': volumename})
        self.conn = self._get_ecom_connection()
        device_info = self.find_device_number(volume, connector)
        device_number = device_info['hostlunid']
        if device_number is not None:
            LOG.info(_("Volume %s is already mapped.")
                     % (volumename))
        else:
            self._map_lun(volume, connector)
            # Find host lun id again after the volume is exported to the host
            device_info = self.find_device_number(volume, connector)

        return device_info

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector."""
        volumename = self._create_volume_name(volume['id'])
        LOG.info(_('Terminate connection: %(volume)s')
                 % {'volume': volumename})
        self.conn = self._get_ecom_connection()
        self._unmap_lun(volume, connector)

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']
        ctrl = self._find_lunmasking_scsi_protocol_controller(
            storage_system, connector)
        return ctrl

    def extend_volume(self, volume, new_size):
        """Extends an existing  volume."""
        LOG.debug('Entering extend_volume.')
        volumesize = int(new_size) * units.Gi
        volumename = self._create_volume_name(volume['id'])

        LOG.info(_('Extend Volume: %(volume)s  New size: %(size)lu')
                 % {'volume': volumename,
                    'size': volumesize})

        self.conn = self._get_ecom_connection()

        storage_type = self._get_storage_type(volume)

        vol_instance = self._find_lun(volume)

        device_id = vol_instance['DeviceID']
        storage_system = vol_instance['SystemName']
        LOG.debug('Device ID: %(deviceid)s: Storage System: '
                  '%(storagesystem)s'
                  % {'deviceid': device_id,
                     'storagesystem': storage_system})

        configservice = self._find_storage_configuration_service(
            storage_system)
        if configservice is None:
            exception_message = (_("Error Extend Volume: %(volumename)s. "
                                   "Storage Configuration Service not found.")
                                 % {'volumename': volumename})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        provisioning = self._get_provisioning(storage_type)

        LOG.debug('Extend Volume: %(name)s  Method: '
                  'CreateOrModifyElementFromStoragePool  ConfigServicie: '
                  '%(service)s ElementType: %(provisioning)s  Size: %(size)lu'
                  'Volume path: %(volumepath)s'
                  % {'service': configservice,
                     'name': volumename,
                     'provisioning': provisioning,
                     'size': volumesize,
                     'volumepath': vol_instance.path})

        rc, job = self.conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            configservice,
            ElementType=self._getnum(provisioning, '16'),
            Size=self._getnum(volumesize, '64'),
            TheElement=vol_instance.path)

        LOG.debug('Extend Volume: %(volumename)s  Return code: %(rc)lu'
                  % {'volumename': volumename,
                     'rc': rc})

        if rc != 0L:
            if "job" in job:
                rc, errordesc = self._wait_for_job_complete(self.conn, job)
            else:
                errordesc = RETCODE_dic[six.text_type(rc)]

            if rc != 0L:
                exception_message = (_('Error Extend Volume: %(volumename)s.  '
                                       'Return code: %(rc)lu.  '
                                       'Error: %(error)s')
                                     % {'volumename': volumename,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug('Leaving extend_volume: %(volumename)s  '
                  'Return code: %(rc)lu '
                  % {'volumename': volumename,
                     'rc': rc})

    def update_volume_stats(self):
        """Retrieve stats info."""
        LOG.debug("Updating volume stats")
        self.stats['total_capacity_gb'] = 'unknown'
        self.stats['free_capacity_gb'] = 'unknown'

        return self.stats

    def _get_storage_type(self, volume, filename=None):
        """Get storage type.

        Look for user input volume type first.
        If not available, fall back to finding it in conf file.
        """
        specs = self._get_volumetype_extraspecs(volume)
        if not specs:
            specs = self._get_storage_type_conffile()
        LOG.debug("Storage Type: %s" % (specs))
        return specs

    def _get_storage_type_conffile(self, filename=None):
        """Get the storage type from the config file."""
        if filename is None:
            filename = self.configuration.cinder_smis_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        storageTypes = dom.getElementsByTagName('StorageType')
        if storageTypes is not None and len(storageTypes) > 0:
            storageType = storageTypes[0].toxml()
            storageType = storageType.replace('<StorageType>', '')
            storageType = storageType.replace('</StorageType>', '')
            LOG.debug("Found Storage Type in config file: %s"
                      % (storageType))
            specs = {}
            specs[POOL] = storageType
            return specs
        else:
            exception_message = (_("Storage type not found."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _get_snappool_conffile(self, filename=None):
        """Get the snap pool from the config file."""
        snappool = None
        if filename is None:
            filename = self.configuration.cinder_smis_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        snappools = dom.getElementsByTagName('SnapPool')
        if snappools is not None and len(snappools) > 0:
            snappool = snappools[0].toxml()
            snappool = snappool.replace('<SnapPool>', '')
            snappool = snappool.replace('</SnapPool>', '')
            LOG.debug("Found Snap Pool in config file: [%s]"
                      % (snappool))
            return snappool
        else:
            exception_message = (_("Snap pool not found."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _get_timeout(self, filename=None):
        if filename is None:
            filename = self.configuration.cinder_smis_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        timeouts = dom.getElementsByTagName('Timeout')
        if timeouts is not None and len(timeouts) > 0:
            timeout = timeouts[0].toxml().replace('<Timeout>', '')
            timeout = timeout.replace('</Timeout>', '')
            LOG.debug("Found Timeout: %s" % (timeout))
            return timeout
        else:
            LOG.debug("Timeout not specified.")
            return 10

    def _get_ecom_cred(self, filename=None):
        if filename is None:
            filename = self.configuration.cinder_smis_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        ecomUsers = dom.getElementsByTagName('EcomUserName')
        if ecomUsers is not None and len(ecomUsers) > 0:
            ecomUser = ecomUsers[0].toxml().replace('<EcomUserName>', '')
            ecomUser = ecomUser.replace('</EcomUserName>', '')
        ecomPasswds = dom.getElementsByTagName('EcomPassword')
        if ecomPasswds is not None and len(ecomPasswds) > 0:
            ecomPasswd = ecomPasswds[0].toxml().replace('<EcomPassword>', '')
            ecomPasswd = ecomPasswd.replace('</EcomPassword>', '')
        if ecomUser is not None and ecomPasswd is not None:
            return ecomUser, ecomPasswd
        else:
            LOG.debug("Ecom user not found.")
            return None

    def _get_ecom_server(self, filename=None):
        if filename is None:
            filename = self.configuration.cinder_smis_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        ecomIps = dom.getElementsByTagName('EcomServerIp')
        if ecomIps is not None and len(ecomIps) > 0:
            ecomIp = ecomIps[0].toxml().replace('<EcomServerIp>', '')
            ecomIp = ecomIp.replace('</EcomServerIp>', '')
        ecomPorts = dom.getElementsByTagName('EcomServerPort')
        if ecomPorts is not None and len(ecomPorts) > 0:
            ecomPort = ecomPorts[0].toxml().replace('<EcomServerPort>', '')
            ecomPort = ecomPort.replace('</EcomServerPort>', '')
        if ecomIp is not None and ecomPort is not None:
            LOG.debug("Ecom IP: %(ecomIp)s Port: %(ecomPort)s",
                      {'ecomIp': ecomIp, 'ecomPort': ecomPort})
            return ecomIp, ecomPort
        else:
            LOG.debug("Ecom server not found.")
            return None

    def _get_ecom_connection(self, filename=None):
        conn = pywbem.WBEMConnection(self.url, (self.user, self.passwd),
                                     default_namespace=SMIS_ROOT)
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        return conn

    def _find_replication_service(self, storage_system):
        foundRepService = None
        repservices = self.conn.EnumerateInstanceNames(
            REPL_SVC)
        for repservice in repservices:
            if storage_system == repservice['SystemName']:
                foundRepService = repservice
                LOG.debug("Found Replication Service: %s"
                          % (repservice))
                break

        return foundRepService

    def _find_storage_configuration_service(self, storage_system):
        foundConfigService = None
        configservices = self.conn.EnumerateInstanceNames(
            STOR_CONF_SVC)
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Storage Configuration Service: %s"
                          % (configservice))
                break

        return foundConfigService

    def _find_controller_configuration_service(self, storage_system):
        foundConfigService = None
        configservices = self.conn.EnumerateInstanceNames(
            CTRL_CONF_SVC)
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Controller Configuration Service: %s"
                          % (configservice))
                break

        return foundConfigService

    def _find_storage_hardwareid_service(self, storage_system):
        foundConfigService = None
        configservices = self.conn.EnumerateInstanceNames(
            STOR_HWID_MNG_SVC)
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Storage Hardware ID Management Service: %s"
                          % (configservice))
                break

        return foundConfigService

    # Find pool based on storage_type
    def _find_pool(self, storage_type, details=False):
        foundPool = None
        systemname = None
        poolinstanceid = None
        # Only get instance names if details flag is False;
        # Otherwise get the whole instances

        systemname, port = self._get_ecom_server()
        poolinstanceid = self._get_pool_instance_id(storage_type)

        if details is False:
            pools = self.conn.EnumerateInstanceNames(
                'CIM_StoragePool')
        else:
            pools = self.conn.EnumerateInstances(
                'CIM_StoragePool')

        for pool in pools:
            if six.text_type(pool['InstanceID']) == six.text_type(
                    poolinstanceid):
                foundPool = pool
                break

        if foundPool is None:
            exception_message = (_("Pool %(storage_type)s is not found.")
                                 % {'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        if systemname is None:
            exception_message = (_("Storage system not found for pool "
                                   "%(storage_type)s.")
                                 % {'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Pool: %(pool)s  SystemName: %(systemname)s."
                  % {'pool': foundPool,
                     'systemname': systemname})
        return foundPool, systemname

    def _find_lun(self, volume):
        foundinstance = None

        volumename = self._create_volume_name(volume['id'])
        loc = volume['provider_location']
        try:
            name = eval(loc)
            instancename = self._getinstancename(name['classname'],
                                                 name['keybindings'])
            foundinstance = self.conn.GetInstance(instancename)
        except Exception:
            foundinstance = None

        if foundinstance is None:
            LOG.debug("Volume %(volumename)s not found on the array."
                      "volume instance is None."
                      % {'volumename': volumename})
        else:
            LOG.debug("Volume name: %(volumename)s  Volume instance: "
                      "%(vol_instance)s."
                      % {'volumename': volumename,
                         'vol_instance': foundinstance.path})

        return foundinstance

    def _find_storage_sync_sv_sv(self, snapshot, volume,
                                 waitforsync=True):
        foundsyncname = None
        storage_system = None

        snapshotname = self._create_volume_name(snapshot['id'])
        volumename = self._create_volume_name(volume['id'])
        LOG.debug("Source: %(volumename)s  Target: %(snapshotname)s."
                  % {'volumename': volumename, 'snapshotname': snapshotname})

        snapshot_instance = self._find_lun(snapshot)
        volume_instance = self._find_lun(volume)
        if snapshot_instance is None or volume_instance is None:
            LOG.info(_('Snapshot Volume %(snapshotname)s, '
                       'Source Volume %(volumename)s not found on the array.')
                     % {'snapshotname': snapshotname,
                        'volumename': volumename})
            return None, None

        storage_system = volume_instance['SystemName']
        classname = STOR_SYNC
        bindings = {'SyncedElement': snapshot_instance.path,
                    'SystemElement': volume_instance.path}
        foundsyncname = self._getinstancename(classname, bindings)

        if foundsyncname is None:
            LOG.debug("Source: %(volumename)s  Target: %(snapshotname)s. "
                      "Storage Synchronized not found. "
                      % {'volumename': volumename,
                         'snapshotname': snapshotname})
        else:
            LOG.debug("Storage system: %(storage_system)s  "
                      "Storage Synchronized instance: %(sync)s."
                      % {'storage_system': storage_system,
                         'sync': foundsyncname})
            # Wait for SE_StorageSynchronized_SV_SV to be fully synced
            if waitforsync:
                self.wait_for_sync(self.conn, foundsyncname)

        return foundsyncname, storage_system

    def _find_initiator_names(self, connector):
        foundinitiatornames = []
        iscsi = 'iscsi'
        fc = 'fc'
        name = 'initiator name'
        if self.protocol.lower() == iscsi and connector['initiator']:
            foundinitiatornames.append(connector['initiator'])
        elif self.protocol.lower() == fc and connector['wwpns']:
            for wwn in connector['wwpns']:
                foundinitiatornames.append(wwn)
            name = 'world wide port names'

        if foundinitiatornames is None or len(foundinitiatornames) == 0:
            msg = (_('Error finding %s.') % name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Found %(name)s: %(initiator)s."
                  % {'name': name,
                     'initiator': foundinitiatornames})
        return foundinitiatornames

    def _wait_for_job_complete(self, conn, job):
        """Given the job wait for it to complete.

        :param conn: connection the ecom server
        :param job: the job dict
        """

        def _wait_for_job_complete():
            """Called at an interval until the job is finished"""
            if self._is_job_finished(conn, job):
                raise loopingcall.LoopingCallDone()
            if self.retries > JOB_RETRIES:
                LOG.error(_("_wait_for_job_complete failed after %(retries)d "
                          "tries") % {'retries': self.retries})
                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.wait_for_job_called:
                    if self._is_job_finished(conn, job):
                        self.wait_for_job_called = True
            except Exception as e:
                LOG.error(_("Exception: %s") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for job."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        self.retries = 0
        self.wait_for_job_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=INTERVAL_10_SEC).wait()

        jobInstanceName = job['Job']
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        rc = jobinstance['ErrorCode']
        errordesc = jobinstance['ErrorDescription']

        return rc, errordesc

    def _is_job_finished(self, conn, job):
        """Check if the job is finished.
        :param conn: connection the ecom server
        :param job: the job dict

        :returns: True if finished; False if not finished;
        """
        jobInstanceName = job['Job']
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        jobstate = jobinstance['JobState']
        # From ValueMap of JobState in CIM_ConcreteJob
        # 2L=New, 3L=Starting, 4L=Running, 32767L=Queue Pending
        # ValueMap("2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13..32767,
        # 32768..65535"),
        # Values("New, Starting, Running, Suspended, Shutting Down,
        # Completed, Terminated, Killed, Exception, Service,
        # Query Pending, DMTF Reserved, Vendor Reserved")]
        # NOTE(deva): string matching based on
        #             http://ipmitool.cvs.sourceforge.net/
        #               viewvc/ipmitool/ipmitool/lib/ipmi_chassis.c
        if jobstate in [2L, 3L, 4L, 32767L]:
            return False
        else:
            return True

    def wait_for_sync(self, conn, syncName):
        """Given the sync name wait for it to fully synchronize.
        :param conn: connection the ecom server
        :param syncName: the syncName
        """

        def _wait_for_sync():
            """Called at an interval until the synchronization is finished"""
            if self._is_sync_complete(conn, syncName):
                raise loopingcall.LoopingCallDone()
            if self.retries > JOB_RETRIES:
                LOG.error(_("_wait_for_sync failed after %(retries)d tries")
                          % {'retries': self.retries})
                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.wait_for_sync_called:
                    if self._is_sync_complete(conn, syncName):
                        self.wait_for_sync_called = True
            except Exception as e:
                LOG.error(_("Exception: %s") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for "
                                      "synchronization."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        self.retries = 0
        self.wait_for_sync_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_sync)
        timer.start(interval=INTERVAL_10_SEC).wait()

    def _is_sync_complete(self, conn, syncName):
        """Check if the job is finished.
        :param conn: connection the ecom server
        :param syncName: the sync name

        :returns: True if fully synchronized; False if not;
        """
        syncInstance = conn.GetInstance(syncName,
                                        LocalOnly=False)
        percentSynced = syncInstance['PercentSynced']

        if percentSynced < 100:
            return False
        else:
            return True

    # Find LunMaskingSCSIProtocolController for the local host on the
    # specified storage system
    def _find_lunmasking_scsi_protocol_controller(self, storage_system,
                                                  connector):
        foundCtrls = []
        initiators = self._find_initiator_names(connector)
        controllers = self.conn.EnumerateInstanceNames(
            SCSI_PROT_CTR)
        for ctrl in controllers:
            if storage_system != ctrl['SystemName']:
                continue
            associators =\
                self.conn.Associators(ctrl,
                                      ResultClass=AUTH_PRIV)
            for assoc in associators:
                for initiator in initiators:
                    if initiator.lower() not in assoc['InstanceID'].lower():
                        continue

                    LOG.debug('_find_lunmasking_scsi_protocol_controller,'
                              'AffinityGroup:%(ag)s'
                              % {'ag': ctrl})
                    foundCtrls.append(ctrl)
                    break
                break

        LOG.debug("LunMaskingSCSIProtocolController for storage system "
                  "%(storage_system)s and initiator %(initiator)s is  "
                  "%(ctrl)s."
                  % {'storage_system': storage_system,
                     'initiator': initiators,
                     'ctrl': foundCtrls})
        return foundCtrls

    # Find LunMaskingSCSIProtocolController for the local host and the
    # specified storage volume
    def _find_lunmasking_scsi_protocol_controller_for_vol(self, vol_instance,
                                                          connector):
        foundCtrls = []
        initiators = self._find_initiator_names(connector)
        controllers =\
            self.conn.AssociatorNames(
                vol_instance.path,
                ResultClass=SCSI_PROT_CTR)
        LOG.debug('_find_lunmasking_scsi_protocol_controller_for_vol:'
                  'controllers:%(controllers)s'
                  % {'controllers': controllers})
        for ctrl in controllers:
            associators =\
                self.conn.Associators(
                    ctrl,
                    ResultClass=AUTH_PRIV)
            foundCtrl = None
            for assoc in associators:
                for initiator in initiators:
                    if initiator.lower() not in assoc['InstanceID'].lower():
                        continue

                    LOG.debug('_find_lunmasking_scsi_protocol_controller'
                              '_for_vol,'
                              'AffinityGroup:%(ag)s'
                              % {'ag': ctrl})
                    foundCtrl = ctrl
                    foundCtrls.append(foundCtrl)
                    break
                if foundCtrl is not None:
                    break

        LOG.debug("LunMaskingSCSIProtocolController for storage volume "
                  "%(vol)s and initiator %(initiator)s is  %(ctrl)s."
                  % {'vol': vol_instance.path,
                     'initiator': initiators,
                     'ctrl': foundCtrls})
        return foundCtrls

    # Find out how many volumes are mapped to a host
    # assoociated to the LunMaskingSCSIProtocolController
    def get_num_volumes_mapped(self, volume, connector):
        numVolumesMapped = 0
        volumename = volume['name']
        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            msg = (_('Volume %(name)s not found on the array. '
                     'Cannot determine if there are volumes mapped.')
                   % {'name': volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        storage_system = vol_instance['SystemName']

        ctrl = self._find_lunmasking_scsi_protocol_controller(
            storage_system,
            connector)

        LOG.debug("LunMaskingSCSIProtocolController for storage system "
                  "%(storage)s and %(connector)s is %(ctrl)s."
                  % {'storage': storage_system,
                     'connector': connector,
                     'ctrl': ctrl})

        associators = self.conn.Associators(
            ctrl,
            resultClass=STOR_VOL)

        numVolumesMapped = len(associators)

        LOG.debug("Found %(numVolumesMapped)d volumes on storage system "
                  "%(storage)s mapped to %(connector)s."
                  % {'numVolumesMapped': numVolumesMapped,
                     'storage': storage_system,
                     'connector': connector})
        return numVolumesMapped

    # Find a device number that a host can see for a volume
    def find_device_number(self, volume, connector):
        out_num_device_number = None

        volumename = self._create_volume_name(volume['id'])
        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']
        sp = None

        ctrls = self._find_lunmasking_scsi_protocol_controller_for_vol(
            vol_instance,
            connector)

        LOG.debug("LunMaskingSCSIProtocolController for "
                  "volume %(vol)s and connector %(connector)s "
                  "is %(ctrl)s."
                  % {'vol': vol_instance.path,
                     'connector': connector,
                     'ctrl': ctrls})

        if len(ctrls) != 0:
            unitnames = self.conn.ReferenceNames(
                vol_instance.path,
                ResultClass='CIM_ProtocolControllerForUnit')

            for unitname in unitnames:
                controller = unitname['Antecedent']
                classname = controller['CreationClassName']
                index = classname.find(SCSI_PROT_CTR)
                if index > -1:
                    if ctrls[0]['DeviceID'] != controller['DeviceID']:
                        continue
                    # Get an instance of CIM_ProtocolControllerForUnit
                    unitinstance = self.conn.GetInstance(unitname,
                                                         LocalOnly=False)
                    numDeviceNumber = int(unitinstance['DeviceNumber'], 16)
                    out_num_device_number = numDeviceNumber
                    break

        if out_num_device_number is None:
            LOG.info(_("Device number not found for volume "
                       "%(volumename)s %(vol_instance)s.")
                     % {'volumename': volumename,
                        'vol_instance': vol_instance.path})
        else:
            LOG.debug("Found device number %(device)d for volume "
                      "%(volumename)s %(vol_instance)s." %
                      {'device': out_num_device_number,
                       'volumename': volumename,
                       'vol_instance': vol_instance.path})

        data = {'hostlunid': out_num_device_number,
                'storagesystem': storage_system,
                'owningsp': sp}

        LOG.debug("Device info: %(data)s." % {'data': data})

        return data

    def _getnum(self, num, datatype):
        try:
            result = {
                '8': pywbem.Uint8(num),
                '16': pywbem.Uint16(num),
                '32': pywbem.Uint32(num),
                '64': pywbem.Uint64(num)
            }
            result = result.get(datatype, num)
        except NameError:
            result = num

        return result

    def _getinstancename(self, classname, bindings):
        instancename = None
        try:
            instancename = pywbem.CIMInstanceName(
                classname,
                namespace=SMIS_ROOT,
                keybindings=bindings)
        except NameError:
            instancename = None

        return instancename

    # Find Storage Hardware IDs
    def _find_storage_hardwareids(self, connector):
        foundInstances = []
        wwpns = self._find_initiator_names(connector)
        hardwareids = self.conn.EnumerateInstances(
            STOR_HWID)
        for hardwareid in hardwareids:
            storid = hardwareid['StorageID']
            for wwpn in wwpns:
                if wwpn.lower() == storid.lower():
                    foundInstances.append(hardwareid.path)

        LOG.debug("Storage Hardware IDs for %(wwpns)s is "
                  "%(foundInstances)s."
                  % {'wwpns': wwpns,
                     'foundInstances': foundInstances})

        return foundInstances

    def _get_volumetype_extraspecs(self, volume):
        specs = {}
        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)
            # If specs['storagetype:pool'] not defined,
            # set specs to {} so we can ready from config file later
            if POOL not in specs:
                specs = {}

        return specs

    def _get_provisioning(self, storage_type):
        # provisioning is thin (5) by default
        provisioning = 5
        thick_str = 'thick'
        try:
            type_prov = storage_type[PROVISIONING]
            if type_prov.lower() == thick_str.lower():
                provisioning = 2
        except KeyError:
            # Default to thin if not defined
            pass

        return provisioning

    def _create_volume_name(self, id_code):
        """create volume_name on ETERNUS from id on OpenStack."""

        LOG.debug('_create_volume_name [%s],Enter method.'
                  % id_code)

        if id_code is None:
            msg = (_('_create_volume_name,'
                     'id_code is None.'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # pylint: disable=E1101
        m = hashlib.md5()
        m.update(id_code)
        # pylint: disable=E1121
        volname = base64.urlsafe_b64encode((m.digest()))
        ret = VOL_PREFIX + six.text_type(volname)

        LOG.debug('_create_volume_name:  '
                  '  id:%(id)s'
                  '  volumename:%(ret)s'
                  '  Exit method.'
                  % {'id': id_code, 'ret': ret})

        return ret

    def _get_pool_instance_id(self, poolname):
        """get pool instacne_id from pool name"""
        LOG.debug('_get_pool_instance_id,'
                  'Enter method,poolname:%s'
                  % (poolname))

        poolinstanceid = None
        pool = None
        pools = []
        msg = None

        try:
            pools = self.conn.EnumerateInstances(
                'CIM_StoragePool')
        except Exception:
            msg = (_('_get_pool_instance_id,'
                     'poolname:%(poolname)s,'
                     'EnumerateInstances,'
                     'cannot connect to ETERNUS.')
                   % {'poolname': poolname})

            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for pool in pools:
            pool_elementname = pool['ElementName']
            poolclass = pool.path.classname
            LOG.debug('poolname from file or VolumeType:%s'
                      '  poolname from smis:%s'
                      '  poolclass from smis:%s'
                      % (poolname, pool_elementname, poolclass))

            if six.text_type(poolname) == six.text_type(pool_elementname):
                if poolclass in STOR_POOLS:
                    poolinstanceid = pool['InstanceID']
                    break

        if poolinstanceid is None:
            msg = (_('_get_pool_instance_id,'
                     'poolname:%(poolname)s,'
                     'poolinstanceid is None.')
                   % {'poolname': poolname})
            LOG.info(msg)

        LOG.debug('_get_pool_instance_id,'
                  'Exit method,poolinstanceid:%s'
                  % (poolinstanceid))

        return poolinstanceid

    def get_target_portid(self, connector):
        """return target_portid"""

        LOG.debug('get_target_portid,Enter method')

        target_portidlist = []
        tgtportlist = []
        tgtport = None
        conn_type = {'fc': 2, 'iscsi': 7}

        try:
            tgtportlist = self.conn.EnumerateInstances(
                'CIM_SCSIProtocolEndpoint')
        except Exception:
            msg = (_('get_target_portid,'
                     'connector:%(connector)s,'
                     'EnumerateInstances,'
                     'cannot connect to ETERNUS.')
                   % {'connector': connector})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for tgtport in tgtportlist:
            if tgtport['ConnectionType'] == conn_type[self.protocol.lower()]:
                target_portidlist.append(tgtport['Name'])

                LOG.debug('get_target_portid,'
                          'portid:%(portid)s,'
                          'connection type:%(cont)s,'
                          % {'portid': tgtport['Name'],
                             'cont': tgtport['ConnectionType']})

        LOG.debug('get_target_portid,'
                  'target portid: %(target_portid)s '
                  % {'target_portid': target_portidlist})

        if len(target_portidlist) == 0:
            msg = (_('get_target_portid,'
                     'protcol:%(protocol)s,'
                     'connector:%(connector)s,'
                     'target_portid does not found.')
                   % {'protocol': self.protocol,
                      'connector': connector})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('get_target_portid,Exit method')

        return target_portidlist

    def _find_copysession(self, volume):
        """find copysession from volumename on ETERNUS"""
        LOG.debug('_find_copysession, Enter method')

        cpsession = None
        vol_instance = None
        repservice = None
        rc = 0
        replicarellist = None
        replicarel = None
        snapshot_vol_instance = None
        msg = None
        errordesc = None

        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            return None, None

        volumename = vol_instance['ElementName']
        storage_system = vol_instance['SystemName']
        if vol_instance is not None:
            # find target_volume

            # get copysession list
            repservice = self._find_replication_service(storage_system)
            if repservice is None:
                msg = (_('_find_copysession,'
                         'Cannot find Replication Service to '
                         'find copysession'))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            def _wait_for_job(repservice):
                cpsession_instance = None
                LOG.debug('_find_copysession,source_volume'
                          ' while copysession')
                cpsession = None

                rc, replicarellist = self.conn.InvokeMethod(
                    'GetReplicationRelationships',
                    repservice,
                    Type=self._getnum(2, '16'),
                    Mode=self._getnum(2, '16'),
                    Locality=self._getnum(2, '16'))
                errordesc = RETCODE_dic[six.text_type(rc)]

                if rc != 0L:
                    msg = (_('_find_copysession,'
                             'source_volumename:%(volumename)s,'
                             'Return code:%(rc)lu,'
                             'Error:%(errordesc)s')
                           % {'volumename': volumename,
                              'rc': rc,
                              'errordesc': errordesc})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

                for replicarel in replicarellist['Synchronizations']:
                    LOG.debug('_find_copysession,'
                              'source_volume,'
                              'replicarel:%(replicarel)s'
                              % {'replicarel': replicarel})
                    try:
                        snapshot_vol_instance = self.conn.GetInstance(
                            replicarel['SystemElement'],
                            LocalOnly=False)
                    except Exception:
                        msg = (_('_find_copysession,'
                                 'source_volumename:%(volumename)s,'
                                 'GetInstance,'
                                 'cannot connect to ETERNUS.')
                               % {'volumename': volumename})
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)

                    LOG.debug('_find_copysession,'
                              'snapshot ElementName:%(elementname)s,'
                              'source_volumename:%(volumename)s'
                              % {'elementname':
                                 snapshot_vol_instance['ElementName'],
                                 'volumename': volumename})

                    if volumename == snapshot_vol_instance['ElementName']:
                        # find copysession
                        cpsession = replicarel
                        LOG.debug('_find_copysession,'
                                  'volumename:%(volumename)s,'
                                  'Storage Synchronized instance:%(sync)s'
                                  % {'volumename': volumename,
                                     'sync': six.text_type(cpsession)})
                        msg = (_('_find_copy_session,'
                                 'source_volumename:%(volumename)s,'
                                 'wait for end of copysession')
                               % {'volumename': volumename})
                        LOG.info(msg)

                        try:
                            cpsession_instance = self.conn.GetInstance(
                                replicarel)
                        except Exception:
                            break

                        LOG.debug('_find_copysession,'
                                  'status:%(status)s'
                                  % {'status':
                                     cpsession_instance['CopyState']})
                        if cpsession_instance['CopyState'] == BROKEN:
                            msg = (_('_find_copysession,'
                                     'source_volumename:%(volumename)s,'
                                     'copysession state is BROKEN')
                                   % {'volumename': volumename})
                            LOG.error(msg)
                            raise exception.VolumeBackendAPIException(data=msg)
                        break
                else:
                    LOG.debug('_find_copysession,'
                              'volumename:%(volumename)s,'
                              'Storage Synchronized not found.'
                              % {'volumename': volumename})

                if cpsession is None:
                    raise loopingcall.LoopingCallDone()

            timer = loopingcall.FixedIntervalLoopingCall(
                _wait_for_job, repservice)
            timer.start(interval=10).wait()

            rc, replicarellist = self.conn.InvokeMethod(
                'GetReplicationRelationships',
                repservice,
                Type=self._getnum(2, '16'),
                Mode=self._getnum(2, '16'),
                Locality=self._getnum(2, '16'))
            errordesc = RETCODE_dic[six.text_type(rc)]

            if rc != 0L:
                msg = (_('_find_copysession,'
                         'source_volumename:%(volumename)s,'
                         'Return code:%(rc)lu,'
                         'Error:%(errordesc)s')
                       % {'volumename': volumename,
                          'rc': rc,
                          'errordesc': errordesc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # find copysession for target_volume
            for replicarel in replicarellist['Synchronizations']:
                LOG.debug('_find_copysession,'
                          'replicarel:%(replicarel)s'
                          % {'replicarel': replicarel})

                # target volume
                try:
                    snapshot_vol_instance = self.conn.GetInstance(
                        replicarel['SyncedElement'],
                        LocalOnly=False)
                except Exception:
                    msg = (_('_find_copysession,'
                             'target_volumename:%(volumename)s,'
                             'GetInstance,'
                             'cannot connect to ETERNUS.')
                           % {'volumename': volumename})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                LOG.debug('_find_copysession,'
                          'snapshot ElementName:%(elementname)s,'
                          'volumename:%(volumename)s'
                          % {'elementname':
                             snapshot_vol_instance['ElementName'],
                             'volumename': volumename})

                if volumename == snapshot_vol_instance['ElementName']:
                    # find copysession
                    cpsession = replicarel
                    LOG.debug('_find_copysession,'
                              'volumename:%(volumename)s,'
                              'Storage Synchronized instance:%(sync)s'
                              % {'volumename': volumename,
                                 'sync': six.text_type(cpsession)})
                    break

            else:
                LOG.debug('_find_copysession,'
                          'volumename:%(volumename)s,'
                          'Storage Synchronized not found.'
                          % {'volumename': volumename})

        else:
            # does not find target_volume of copysession
            msg = (_('_find_copysession,'
                     'volumename:%(volumename)s,'
                     'not found.')
                   % {'volumename': volumename})
            LOG.info(msg)

        LOG.debug('_find_copysession,Exit method')

        return cpsession, storage_system

    def _delete_copysession(self, storage_system, cpsession):
        """delete copysession"""
        LOG.debug('_delete_copysession,Entering')
        LOG.debug('_delete_copysession,[%s]' % cpsession)

        snapshot_instance = None
        msg = None
        errordesc = None

        try:
            snapshot_instance = self.conn.GetInstance(
                cpsession,
                LocalOnly=False)
        except Exception:
            msg = (_('_delete_copysession, '
                     'copysession:%(cpsession)s,'
                     'GetInstance,'
                     'cannot connect to ETERNUS.')
                   % {'cpsession': cpsession})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        copytype = snapshot_instance['CopyType']

        # set oparation code
        operation = OPERATION_dic[copytype]

        repservice = self._find_replication_service(storage_system)
        if repservice is None:
            msg = (_('_delete_copysession,'
                     'Cannot find Replication Service to '
                     'delete copysession'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Invoke method for delete copysession
        rc, job = self.conn.InvokeMethod(
            'ModifyReplicaSynchronization',
            repservice,
            Operation=self._getnum(operation, '16'),
            Synchronization=cpsession,
            Force=True,
            WaitForCopyState=self._getnum(15, '16'))

        errordesc = RETCODE_dic[six.text_type(rc)]

        LOG.debug('_delete_copysession,'
                  'copysession:%(cpsession)s,'
                  'operation:%(operation)s,'
                  'Return code:%(rc)lu,'
                  'Error:%(errordesc)s,'
                  'Exit method'
                  % {'cpsession': cpsession,
                     'operation': operation,
                     'rc': rc,
                     'errordesc': errordesc})

        if rc != 0L:
            msg = (_('_delete_copysession,'
                     'copysession:%(cpsession)s,'
                     'operation:%(operation)s,'
                     'Return code:%(rc)lu,'
                     'Error:%(errordesc)s')
                   % {'cpsession': cpsession,
                      'operation': operation,
                      'rc': rc,
                      'errordesc': errordesc})

            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return
