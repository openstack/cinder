# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 EMC Corporation, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
Drivers for EMC volumes.

"""

import os
import time
from xml.dom.minidom import parseString

from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS

try:
    import pywbem
except ImportError:
    LOG.info(_('Module PyWBEM not installed.  PyWBEM can be downloaded '
               'from http://sourceforge.net/apps/mediawiki/pywbem'))

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_emc_config.xml'


def get_iscsi_initiator():
    """Get iscsi initiator name for this machine"""
    # NOTE openiscsi stores initiator name in a file that
    #      needs root permission to read.
    contents = utils.read_file_as_root('/etc/iscsi/initiatorname.iscsi')
    for l in contents.split('\n'):
        if l.startswith('InitiatorName='):
            return l[l.index('=') + 1:].strip()


class EMCISCSIDriver(driver.ISCSIDriver):
    """Drivers for VMAX/VMAXe and VNX"""

    def __init__(self, *args, **kwargs):

        super(EMCISCSIDriver, self).__init__(*args, **kwargs)

        opt = cfg.StrOpt('cinder_emc_config_file',
                         default=CINDER_EMC_CONFIG_FILE,
                         help='use this file for cinder emc plugin '
                         'config data')
        FLAGS.register_opt(opt)

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VMAXe/VNX) volume. """

        LOG.debug(_('Entering create_volume.'))
        volumesize = int(volume['size']) * 1073741824
        volumename = volume['name']

        LOG.info(_('Create Volume: %(volume)s  Size: %(size)lu')
                 % {'volume': volumename,
                    'size': volumesize})

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                 "Cannot connect to ECOM server.")
                                 % {'volumename': volumename})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        storage_type = self._get_storage_type()
        if storage_type is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                 "Storage type %(storage_type)s not found.")
                                 % {'volumename': volumename,
                                    'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug(_('Create Volume: %(volume)s  '
                  'Storage type: %(storage_type)s')
                  % {'volume': volumename,
                     'storage_type': storage_type})

        pool, storage_system = self._find_pool(storage_type)
        if pool is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                 "Pool %(storage_type)s not found.")
                                 % {'volumename': volumename,
                                    'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        if storage_system is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                 "Storage system not found for pool "
                                 "%(storage_type)s.")
                                 % {'volumename': volumename,
                                    'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug(_('Create Volume: %(volume)s  Pool: %(pool)s  '
                  'Storage System: %(storage_system)s')
                  % {'volume': volumename,
                     'pool': str(pool),
                     'storage_system': storage_system})

        configservice = self._find_storage_configuration_service(
                            storage_system)
        if configservice is None:
            exception_message = (_("Error Create Volume: %(volumename)s. "
                                 "Storage Configuration Service not found for "
                                 "pool %(storage_type)s.")
                                 % {'volumename': volumename,
                                    'storage_type': storage_type})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug(_('Create Volume: %(name)s  Method: '
                  'CreateOrModifyElementFromStoragePool  ConfigServicie: '
                  '%(service)s  ElementName: %(name)s  InPool: %(pool)s  '
                  'ElementType: 5  Size: %(size)lu')
                  % {'service': str(configservice),
                     'name': volumename,
                     'pool': str(pool),
                     'size': volumesize})

        rc, job = conn.InvokeMethod(
                    'CreateOrModifyElementFromStoragePool',
                    configservice, ElementName=volumename, InPool=pool,
                    ElementType=self._getnum(5, '16'),
                    Size=self._getnum(volumesize, '64'))

        LOG.debug(_('Create Volume: %(volumename)s  Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                LOG.error(_('Error Create Volume: %(volumename)s.  '
                          'Return code: %(rc)lu.  Error: %(error)s')
                          % {'volumename': volumename,
                             'rc': rc,
                             'error': errordesc})
                raise exception.VolumeBackendAPIException(data=errordesc)

        LOG.debug(_('Leaving create_volume: %(volumename)s  '
                  'Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'rc': rc})

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug(_('Entering create_volume_from_snapshot.'))

        snapshotname = snapshot['name']
        volumename = volume['name']

        LOG.info(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                 'Snapshot: %(snapshotname)s')
                 % {'volumename': volumename,
                    'snapshotname': snapshotname})

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_('Error Create Volume from Snapshot: '
                                 'Volume: %(volumename)s  Snapshot: '
                                 '%(snapshotname)s. Cannot connect to'
                                 ' ECOM server.')
                                 % {'volumename': volumename,
                                    'snapshotname': snapshotname})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        snapshot_instance = self._find_lun(snapshot)
        storage_system = snapshot_instance['SystemName']

        LOG.debug(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Snapshot Instance: '
                  '%(snapshotinstance)s  Storage System: %(storage_system)s.')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'snapshotinstance': str(snapshot_instance.path),
                     'storage_system': storage_system})

        isVMAX = storage_system.find('SYMMETRIX')
        if isVMAX > -1:
            exception_message = (_('Error Create Volume from Snapshot: '
                                 'Volume: %(volumename)s  Snapshot: '
                                 '%(snapshotname)s. Create Volume '
                                 'from Snapshot is NOT supported on VMAX.')
                                 % {'volumename': volumename,
                                    'snapshotname': snapshotname})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

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

        LOG.debug(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Method: CreateElementReplica  '
                  'ReplicationService: %(service)s  ElementName: '
                  '%(elementname)s  SyncType: 8  SourceElement: '
                  '%(sourceelement)s')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'service': str(repservice),
                     'elementname': volumename,
                     'sourceelement': str(snapshot_instance.path)})

        # Create a Clone from snapshot
        rc, job = conn.InvokeMethod(
                    'CreateElementReplica', repservice,
                    ElementName=volumename,
                    SyncType=self._getnum(8, '16'),
                    SourceElement=snapshot_instance.path)

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Create Volume from Snapshot: '
                                     'Volume: %(volumename)s  Snapshot:'
                                     '%(snapshotname)s.  Return code: %(rc)lu.'
                                     'Error: %(error)s')
                                     % {'volumename': volumename,
                                        'snapshotname': snapshotname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s.  Successfully clone volume '
                  'from snapshot.  Finding the clone relationship.')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname})

        sync_name, storage_system = self._find_storage_sync_sv_sv(
            volumename, snapshotname)

        # Remove the Clone relationshop so it can be used as a regular lun
        # 8 - Detach operation
        LOG.debug(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s.  Remove the clone '
                  'relationship. Method: ModifyReplicaSynchronization '
                  'ReplicationService: %(service)s  Operation: 8  '
                  'Synchronization: %(sync_name)s')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'service': str(repservice),
                     'sync_name': str(sync_name)})

        rc, job = conn.InvokeMethod(
                    'ModifyReplicaSynchronization',
                    repservice,
                    Operation=self._getnum(8, '16'),
                    Synchronization=sync_name)

        LOG.debug(_('Create Volume from Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Create Volume from Snapshot: '
                                     'Volume: %(volumename)s  '
                                     'Snapshot: %(snapshotname)s.  '
                                     'Return code: %(rc)lu.  Error: %(error)s')
                                     % {'volumename': volumename,
                                        'snapshotname': snapshotname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Leaving create_volume_from_snapshot: Volume: '
                  '%(volumename)s Snapshot: %(snapshotname)s  '
                  'Return code: %(rc)lu.')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        LOG.debug(_('Entering delete_volume.'))
        volumename = volume['name']
        LOG.info(_('Delete Volume: %(volume)s')
                 % {'volume': volumename})

        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            LOG.error(_('Volume %(name)s not found on the array. '
                      'No volume to delete.')
                      % {'name': volumename})
            return

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Error Delete Volume: %(volumename)s. "
                                 "Cannot connect to ECOM server.")
                                 % {'volumename': volumename})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        storage_system = vol_instance['SystemName']

        configservice = self._find_storage_configuration_service(
                        storage_system)
        if configservice is None:
            exception_message = (_("Error Delete Volume: %(volumename)s. "
                                 "Storage Configuration Service not found.")
                                 % {'volumename': volumename})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        device_id = vol_instance['DeviceID']

        LOG.debug(_('Delete Volume: %(name)s  DeviceID: %(deviceid)s')
                  % {'name': volumename,
                     'deviceid': device_id})

        LOG.debug(_('Delete Volume: %(name)s  Method: EMCReturnToStoragePool '
                  'ConfigServic: %(service)s  TheElement: %(vol_instance)s')
                  % {'service': str(configservice),
                     'name': volumename,
                     'vol_instance': str(vol_instance.path)})

        rc, job = conn.InvokeMethod(
                    'EMCReturnToStoragePool',
                    configservice, TheElements=[vol_instance.path])

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Delete Volume: %(volumename)s.  '
                                     'Return code: %(rc)lu.  Error: %(error)s')
                                     % {'volumename': volumename,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Leaving delete_volume: %(volumename)s  Return code: '
                  '%(rc)lu')
                  % {'volumename': volumename,
                     'rc': rc})

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug(_('Entering create_snapshot.'))

        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        LOG.info(_('Create snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        conn = self._get_ecom_connection()
        if conn is None:
            LOG.error(_('Cannot connect to ECOM server.'))
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        volume = {}
        volume['name'] = volumename
        volume['provider_location'] = None
        vol_instance = self._find_lun(volume)
        device_id = vol_instance['DeviceID']
        storage_system = vol_instance['SystemName']
        LOG.debug(_('Device ID: %(deviceid)s: Storage System: '
                  '%(storagesystem)s')
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

        LOG.debug(_("Create Snapshot:  Method: CreateElementReplica: "
                  "Target: %(snapshot)s  Source: %(volume)s  Replication "
                  "Service: %(service)s  ElementName: %(elementname)s  Sync "
                  "Type: 7  SourceElement: %(sourceelement)s.")
                  % {'snapshot': snapshotname,
                     'volume': volumename,
                     'service': str(repservice),
                     'elementname': snapshotname,
                     'sourceelement': str(vol_instance.path)})

        rc, job = conn.InvokeMethod(
                    'CreateElementReplica', repservice,
                    ElementName=snapshotname,
                    SyncType=self._getnum(7, '16'),
                    SourceElement=vol_instance.path)

        LOG.debug(_('Create Snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Create Snapshot: (snapshot)s '
                                     'Volume: %(volume)s Error: %(errordesc)s')
                                     % {'snapshot': snapshotname, 'volume':
                                        volumename, 'errordesc': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Leaving create_snapshot: Snapshot: %(snapshot)s '
                  'Volume: %(volume)s  Return code: %(rc)lu.') %
                  {'snapshot': snapshotname, 'volume': volumename, 'rc': rc})

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug(_('Entering delete_snapshot.'))

        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        LOG.info(_('Delete Snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug(_('Delete Snapshot: %(snapshot)s: volume: %(volume)s. '
                  'Finding StorageSychronization_SV_SV.')
                  % {'snapshot': snapshotname,
                     'volume': volumename})

        sync_name, storage_system = self._find_storage_sync_sv_sv(
                                    snapshotname, volumename)
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
        LOG.debug(_("Delete Snapshot: Target: %(snapshot)s  "
                  "Source: %(volume)s.  Method: "
                  "ModifyReplicaSynchronization:  "
                  "Replication Service: %(service)s  Operation: 19  "
                  "Synchronization: %(sync_name)s.")
                  % {'snapshot': snapshotname,
                     'volume': volumename,
                     'service': str(repservice),
                     'sync_name': str(sync_name)})

        rc, job = conn.InvokeMethod(
                    'ModifyReplicaSynchronization',
                    repservice,
                    Operation=self._getnum(19, '16'),
                    Synchronization=sync_name)

        LOG.debug(_('Delete Snapshot: Volume: %(volumename)s  Snapshot: '
                  '%(snapshotname)s  Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Delete Snapshot: Volume: '
                                     '%(volumename)s  Snapshot: '
                                     '%(snapshotname)s. Return code: %(rc)lu.'
                                     ' Error: %(error)s')
                                     % {'volumename': volumename,
                                        'snapshotname': snapshotname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Leaving delete_snapshot: Volume: %(volumename)s  '
                  'Snapshot: %(snapshotname)s  Return code: %(rc)lu.')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'rc': rc})

    def _iscsi_location(ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, FLAGS.iscsi_port, target, iqn, lun)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        vol_instance = self._find_lun(volume)
        device_id = vol_instance['DeviceID']
        volumename = volume['name']
        LOG.debug(_('ensure_export: Volume: %(volume)s  Device ID: '
                  '%(device_id)s')
                  % {'volume': volumename,
                     'device_id': device_id})

        return {'provider_location': device_id}

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        volumename = volume['name']
        LOG.info(_('Create export: %(volume)s')
                 % {'volume': volumename})
        vol_instance = self._find_lun(volume)
        device_id = vol_instance['DeviceID']

        LOG.debug(_('create_export: Volume: %(volume)s  Device ID: '
                  '%(device_id)s')
                  % {'volume': volumename,
                     'device_id': device_id})

        return {'provider_location': device_id}

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume.
        """
        pass

    # Mapping method for VNX
    def _expose_paths(self, conn, configservice, vol_instance, connector):
        """Adds a volume and initiator to a Storage Group
        and therefore maps the volume to the host.
        """
        volumename = vol_instance['ElementName']
        lun_name = vol_instance['DeviceID']
        initiator = self._find_initiator_name(connector)
        storage_system = vol_instance['SystemName']
        lunmask_ctrl = self._find_lunmasking_scsi_protocol_controller(
            storage_system, connector)

        LOG.debug(_('ExposePaths: %(vol)s  ConfigServicie: %(service)s  '
                  'LUNames: %(lun_name)s  InitiatorPortIDs: %(initiator)s  '
                  'DeviceAccesses: 2')
                  % {'vol': str(vol_instance.path),
                     'service': str(configservice),
                     'lun_name': lun_name,
                     'initiator': initiator})

        if lunmask_ctrl is None:
            rc, controller = conn.InvokeMethod(
                                'ExposePaths',
                                configservice, LUNames=[lun_name],
                                InitiatorPortIDs=[initiator],
                                DeviceAccesses=[self._getnum(2, '16')])
        else:
            LOG.debug(_('ExposePaths parameter '
                      'LunMaskingSCSIProtocolController: '
                      '%(lunmasking)s')
                      % {'lunmasking': str(lunmask_ctrl)})
            rc, controller = conn.InvokeMethod(
                                'ExposePaths',
                                configservice, LUNames=[lun_name],
                                DeviceAccesses=[self._getnum(2, '16')],
                                ProtocolControllers=[lunmask_ctrl])

        if rc != 0L:
            msg = (_('Error mapping volume %s.') % volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('ExposePaths for volume %s completed successfully.')
                  % volumename)

    # Unmapping method for VNX
    def _hide_paths(self, conn, configservice, vol_instance, connector):
        """Removes a volume from the Storage Group
        and therefore unmaps the volume from the host.
        """
        volumename = vol_instance['ElementName']
        device_id = vol_instance['DeviceID']
        lunmask_ctrl = self._find_lunmasking_scsi_protocol_controller_for_vol(
            vol_instance, connector)

        LOG.debug(_('HidePaths: %(vol)s  ConfigServicie: %(service)s  '
                  'LUNames: %(device_id)s  LunMaskingSCSIProtocolController: '
                  '%(lunmasking)s')
                  % {'vol': str(vol_instance.path),
                     'service': str(configservice),
                     'device_id': device_id,
                     'lunmasking': str(lunmask_ctrl)})

        rc, controller = conn.InvokeMethod(
            'HidePaths', configservice,
            LUNames=[device_id], ProtocolControllers=[lunmask_ctrl])

        if rc != 0L:
            msg = (_('Error unmapping volume %s.') % volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('HidePaths for volume %s completed successfully.')
                  % volumename)

    # Mapping method for VMAX/VMAXe
    def _add_members(self, conn, configservice, vol_instance, connector):
        """Add volume to the Device Masking Group that belongs to
        a Masking View"""
        volumename = vol_instance['ElementName']
        masking_group = self._find_device_masking_group()

        LOG.debug(_('AddMembers: ConfigServicie: %(service)s  MaskingGroup: '
                  '%(masking_group)s  Members: %(vol)s')
                  % {'service': str(configservice),
                     'masking_group': str(masking_group),
                     'vol': str(vol_instance.path)})

        rc, job = conn.InvokeMethod(
                    'AddMembers', configservice,
                    MaskingGroup=masking_group, Members=[vol_instance.path])

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                msg = (_('Error mapping volume %(vol)s. %(error)s') %
                       {'vol': volumename, 'error': errordesc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('AddMembers for volume %s completed successfully.')
                  % volumename)

    # Unmapping method for VMAX/VMAXe
    def _remove_members(self, conn, configservice, vol_instance, connector):
        """Removes an export for a volume."""
        volumename = vol_instance['ElementName']
        masking_group = self._find_device_masking_group()

        LOG.debug(_('RemoveMembers: ConfigServicie: %(service)s  '
                  'MaskingGroup: %(masking_group)s  Members: %(vol)s')
                  % {'service': str(configservice),
                     'masking_group': str(masking_group),
                     'vol': str(vol_instance.path)})

        rc, job = conn.InvokeMethod('RemoveMembers', configservice,
                                    MaskingGroup=masking_group,
                                    Members=[vol_instance.path])

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                msg = (_('Error unmapping volume %(vol)s. %(error)s')
                       % {'vol': volumename, 'error': errordesc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('RemoveMembers for volume %s completed successfully.')
                  % volumename)

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def _map_lun(self, volume, connector):
        """Maps a volume to the host."""
        volumename = volume['name']
        LOG.info(_('Map volume: %(volume)s')
                 % {'volume': volumename})

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        configservice = self._find_controller_configuration_service(
            storage_system)
        if configservice is None:
            exception_message = (_("Cannot find Controller Configuration "
                                 "Service for storage system %s")
                                 % storage_system)
            raise exception.VolumeBackendAPIException(data=exception_message)

        isVMAX = storage_system.find('SYMMETRIX')
        if isVMAX > -1:
            self._add_members(conn, configservice, vol_instance, connector)
        else:
            self._expose_paths(conn, configservice, vol_instance, connector)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host."""
        volumename = volume['name']
        LOG.info(_('Unmap volume: %(volume)s')
                 % {'volume': volumename})

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        device_number = self._find_device_number(volume)
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

        isVMAX = storage_system.find('SYMMETRIX')
        if isVMAX > -1:
            self._remove_members(conn, configservice, vol_instance, connector)
        else:
            self._hide_paths(conn, configservice, vol_instance, connector)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        the iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                }
            }

        """
        volumename = volume['name']
        LOG.info(_('Initialize connection: %(volume)s')
                 % {'volume': volumename})
        device_number = self._find_device_number(volume)
        if device_number is not None:
            LOG.info(_("Volume %s is already mapped.")
                     % (volumename))
        else:
            self._map_lun(volume, connector)

        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def _do_iscsi_discovery(self, volume):

        LOG.warn(_("ISCSI provider_location not stored, using discovery"))

        (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p',
                                    FLAGS.iscsi_ip_address,
                                    run_as_root=True)
        for target in out.splitlines():
            return target
        return None

    def _get_iscsi_properties(self, volume):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the id of the volume (currently used by xen)

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        """
        properties = {}

        location = self._do_iscsi_discovery(volume)
        if not location:
            raise exception.InvalidVolume(_("Could not find iSCSI export "
                                          " for volume %s") %
                                          (volume['name']))

        LOG.debug(_("ISCSI Discovery: Found %s") % (location))
        properties['target_discovered'] = True

        results = location.split(" ")
        properties['target_portal'] = results[0].split(",")[0]
        properties['target_iqn'] = results[1]

        device_number = self._find_device_number(volume)
        if device_number is None:
            exception_message = (_("Cannot find device number for volume %s")
                                 % volume['name'])
            raise exception.VolumeBackendAPIException(data=exception_message)

        properties['target_lun'] = device_number

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        LOG.debug(_("ISCSI properties: %s") % (properties))

        return properties

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector"""
        volumename = volume['name']
        LOG.info(_('Terminate connection: %(volume)s')
                 % {'volume': volumename})
        self._unmap_lun(volume, connector)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug(_('copy_image_to_volume %s.') % volume['name'])
        initiator = get_iscsi_initiator()
        connector = {}
        connector['initiator'] = initiator

        iscsi_properties, volume_path = self._attach_volume(
            context, volume, connector)

        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path, "wb") as image_file:
                image_service.download(context, image_id, image_file)

        self.terminate_connection(volume, connector)

    def _attach_volume(self, context, volume, connector):
        """Attach the volume."""
        iscsi_properties = None
        host_device = None
        init_conn = self.initialize_connection(volume, connector)
        iscsi_properties = init_conn['data']

        self._run_iscsiadm(iscsi_properties, ("--login",),
                           check_exit_code=[0, 255])

        self._iscsiadm_update(iscsi_properties, "node.startup", "automatic")

        host_device = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-%s" %
                       (iscsi_properties['target_portal'],
                        iscsi_properties['target_iqn'],
                        iscsi_properties.get('target_lun', 0)))

        tries = 0
        while not os.path.exists(host_device):
            if tries >= FLAGS.num_iscsi_scan_tries:
                raise exception.CinderException(
                    _("iSCSI device not found at %s") % (host_device))

            LOG.warn(_("ISCSI volume not yet found at: %(host_device)s. "
                     "Will rescan & retry.  Try number: %(tries)s") %
                     locals())

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

            tries = tries + 1
            if not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(host_device)s "
                      "(after %(tries)s rescans)") %
                      locals())

        return iscsi_properties, host_device

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        LOG.debug(_('copy_volume_to_image %s.') % volume['name'])
        initiator = get_iscsi_initiator()
        connector = {}
        connector['initiator'] = initiator

        iscsi_properties, volume_path = self._attach_volume(
            context, volume, connector)

        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path) as volume_file:
                image_service.update(context, image_id, {}, volume_file)

        self.terminate_connection(volume, connector)

    def _get_storage_type(self, filename=None):
        """Get the storage type from the config file
        """
        if filename == None:
            filename = FLAGS.cinder_emc_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        storageTypes = dom.getElementsByTagName('StorageType')
        if storageTypes is not None and len(storageTypes) > 0:
            storageType = storageTypes[0].toxml()
            storageType = storageType.replace('<StorageType>', '')
            storageType = storageType.replace('</StorageType>', '')
            LOG.debug(_("Found Storage Type: %s") % (storageType))
            return storageType
        else:
            LOG.debug(_("Storage Type not found."))
            return None

    def _get_masking_view(self, filename=None):
        if filename == None:
            filename = FLAGS.cinder_emc_config_file

        file = open(filename, 'r')
        data = file.read()
        file.close()
        dom = parseString(data)
        views = dom.getElementsByTagName('MaskingView')
        if views is not None and len(views) > 0:
            view = views[0].toxml().replace('<MaskingView>', '')
            view = view.replace('</MaskingView>', '')
            LOG.debug(_("Found Masking View: %s") % (view))
            return view
        else:
            LOG.debug(_("Masking View not found."))
            return None

    def _get_ecom_cred(self, filename=None):
        if filename == None:
            filename = FLAGS.cinder_emc_config_file

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
            LOG.debug(_("Ecom user not found."))
            return None

    def _get_ecom_server(self, filename=None):
        if filename == None:
            filename = FLAGS.cinder_emc_config_file

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
            LOG.debug(_("Ecom IP: %(ecomIp)s Port: %(ecomPort)s") % (locals()))
            return ecomIp, ecomPort
        else:
            LOG.debug(_("Ecom server not found."))
            return None

    def _get_ecom_connection(self, filename=None):
        ip, port = self._get_ecom_server()
        user, passwd = self._get_ecom_cred()
        url = 'http://' + ip + ':' + port
        conn = pywbem.WBEMConnection(url, (user, passwd),
                                     default_namespace='root/emc')

        return conn

    def _find_replication_service(self, storage_system):
        foundRepService = None
        conn = self._get_ecom_connection()
        repservices = conn.EnumerateInstanceNames('EMC_ReplicationService')
        for repservice in repservices:
            if storage_system == repservice['SystemName']:
                foundRepService = repservice
                LOG.debug(_("Found Replication Service: %s")
                          % (str(repservice)))
                break

        return foundRepService

    def _find_storage_configuration_service(self, storage_system):
        foundConfigService = None
        conn = self._get_ecom_connection()
        configservices = conn.EnumerateInstanceNames(
            'EMC_StorageConfigurationService')
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug(_("Found Storage Configuration Service: %s")
                          % (str(configservice)))
                break

        return foundConfigService

    def _find_controller_configuration_service(self, storage_system):
        foundConfigService = None
        conn = self._get_ecom_connection()
        configservices = conn.EnumerateInstanceNames(
            'EMC_ControllerConfigurationService')
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug(_("Found Controller Configuration Service: %s")
                          % (str(configservice)))
                break

        return foundConfigService

     # Find pool based on storage_type
    def _find_pool(self, storage_type):
        foundPool = None
        systemname = None
        conn = self._get_ecom_connection()
        vpools = conn.EnumerateInstanceNames('EMC_VirtualProvisioningPool')
        upools = conn.EnumerateInstanceNames('EMC_UnifiedStoragePool')
        for upool in upools:
            poolinstance = upool['InstanceID']
            # Example: CLARiiON+APM00115204878+U+Pool 0
            poolname, systemname = self._parse_pool_instance_id(poolinstance)
            if poolname is not None and systemname is not None:
                if storage_type == poolname:
                    foundPool = upool
                    break
        if foundPool is not None and systemname is not None:
            return foundPool, systemname

        for vpool in vpools:
            poolinstance = vpool['InstanceID']
            # Example: SYMMETRIX+000195900551+TP+Sol_Innov
            poolname, systemname = self._parse_pool_instance_id(poolinstance)
            if poolname is not None and systemname is not None:
                if storage_type == poolname:
                    foundPool = vpool
                    break

        LOG.debug(_("Pool: %(pool)s  SystemName: %(systemname)s.")
                  % {'pool': str(foundPool), 'systemname': systemname})
        return foundPool, systemname

    def _parse_pool_instance_id(self, instanceid):
        # Example of pool InstanceId: CLARiiON+APM00115204878+U+Pool 0
        poolname = None
        systemname = None
        endp = instanceid.rfind('+')
        if endp > -1:
            poolname = instanceid[endp + 1:]

        idarray = instanceid.split('+')
        if len > 2:
            systemname = idarray[0] + '+' + idarray[1]

        LOG.debug(_("Pool name: %(poolname)s  System name: %(systemname)s.")
                  % {'poolname': poolname, 'systemname': systemname})
        return poolname, systemname

    def _find_lun(self, volume):
        foundinstance = None
        try:
            device_id = volume['provider_location']
        except Exception:
            device_id = None

        volumename = volume['name']
        conn = self._get_ecom_connection()

        names = conn.EnumerateInstanceNames('EMC_StorageVolume')

        for n in names:
            if device_id is not None:
                if n['DeviceID'] == device_id:
                    vol_instance = conn.GetInstance(n)
                    foundinstance = vol_instance
                    break
                else:
                    continue

            else:
                vol_instance = conn.GetInstance(n)
                if vol_instance['ElementName'] == volumename:
                    foundinstance = vol_instance
                    volume['provider_location'] = foundinstance['DeviceID']
                    break

        if foundinstance is None:
            LOG.debug(_("Volume %(volumename)s not found on the array.")
                      % {'volumename': volumename})
        else:
            LOG.debug(_("Volume name: %(volumename)s  Volume instance: "
                      "%(vol_instance)s.")
                      % {'volumename': volumename,
                         'vol_instance': str(foundinstance.path)})

        return foundinstance

    def _find_storage_sync_sv_sv(self, snapshotname, volumename):
        foundsyncname = None
        storage_system = None

        LOG.debug(_("Source: %(volumename)s  Target: %(snapshotname)s.")
                  % {'volumename': volumename, 'snapshotname': snapshotname})

        conn = self._get_ecom_connection()

        names = conn.EnumerateInstanceNames('SE_StorageSynchronized_SV_SV')

        for n in names:
            snapshot_instance = conn.GetInstance(n['SyncedElement'],
                                                 LocalOnly=False)
            if snapshotname != snapshot_instance['ElementName']:
                continue

            vol_instance = conn.GetInstance(n['SystemElement'],
                                            LocalOnly=False)
            if vol_instance['ElementName'] == volumename:
                foundsyncname = n
                storage_system = vol_instance['SystemName']
                break

        if foundsyncname is None:
            LOG.debug(_("Source: %(volumename)s  Target: %(snapshotname)s. "
                      "Storage Synchronized not found. ")
                      % {'volumename': volumename,
                         'snapshotname': snapshotname})
        else:
            LOG.debug(_("Storage system: %(storage_system)s  "
                      "Storage Synchronized instance: %(sync)s.")
                      % {'storage_system': storage_system,
                         'sync': str(foundsyncname)})
        return foundsyncname, storage_system

    def _find_initiator_name(self, connector):
        """ Get initiator name from connector['initiator']
        """
        foundinitiatorname = None
        if connector['initiator']:
            foundinitiatorname = connector['initiator']

        LOG.debug(_("Initiator name: %(initiator)s.")
                  % {'initiator': foundinitiatorname})
        return foundinitiatorname

    def _wait_for_job_complete(self, job):
        jobinstancename = job['Job']

        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        while True:
            jobinstance = conn.GetInstance(jobinstancename, LocalOnly=False)
            jobstate = jobinstance['JobState']
            # From ValueMap of JobState in CIM_ConcreteJob
            # 2L=New, 3L=Starting, 4L=Running, 32767L=Queue Pending
            # ValueMap("2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13..32767,
            # 32768..65535"),
            # Values("New, Starting, Running, Suspended, Shutting Down,
            # Completed, Terminated, Killed, Exception, Service,
            # Query Pending, DMTF Reserved, Vendor Reserved")]
            if jobstate in [2L, 3L, 4L, 32767L]:
                time.sleep(10)
            else:
                break

        rc = jobinstance['ErrorCode']
        errordesc = jobinstance['ErrorDescription']

        return rc, errordesc

    # Find LunMaskingSCSIProtocolController for the local host on the
    # specified storage system
    def _find_lunmasking_scsi_protocol_controller(self, storage_system,
                                                  connector):
        foundCtrl = None
        conn = self._get_ecom_connection()
        initiator = self._find_initiator_name(connector)
        controllers = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for ctrl in controllers:
            if storage_system != ctrl['SystemName']:
                continue
            associators = conn.Associators(ctrl,
                                           resultClass='EMC_StorageHardwareID')
            for assoc in associators:
                # if EMC_StorageHardwareID matches the initiator,
                # we found the existing EMC_LunMaskingSCSIProtocolController
                # (Storage Group for VNX)
                # we can use for masking a new LUN
                if assoc['StorageID'] == initiator:
                    foundCtrl = ctrl
                    break

            if foundCtrl is not None:
                break

        LOG.debug(_("LunMaskingSCSIProtocolController for storage system "
                  "%(storage_system)s and initiator %(initiator)s is  "
                  "%(ctrl)s.")
                  % {'storage_system': storage_system,
                     'initiator': initiator,
                     'ctrl': str(foundCtrl)})
        return foundCtrl

    # Find LunMaskingSCSIProtocolController for the local host and the
    # specified storage volume
    def _find_lunmasking_scsi_protocol_controller_for_vol(self, vol_instance,
                                                          connector):
        foundCtrl = None
        conn = self._get_ecom_connection()
        initiator = self._find_initiator_name(connector)
        controllers = conn.AssociatorNames(
                        vol_instance.path,
                        resultClass='EMC_LunMaskingSCSIProtocolController')

        for ctrl in controllers:
            associators = conn.Associators(
                            ctrl,
                            resultClass='EMC_StorageHardwareID')
            for assoc in associators:
                # if EMC_StorageHardwareID matches the initiator,
                # we found the existing EMC_LunMaskingSCSIProtocolController
                # (Storage Group for VNX)
                # we can use for masking a new LUN
                if assoc['StorageID'] == initiator:
                    foundCtrl = ctrl
                    break

            if foundCtrl is not None:
                break

        LOG.debug(_("LunMaskingSCSIProtocolController for storage volume "
                  "%(vol)s and initiator %(initiator)s is  %(ctrl)s.")
                  % {'vol': str(vol_instance.path), 'initiator': initiator,
                     'ctrl': str(foundCtrl)})
        return foundCtrl

    # Find an available device number that a host can see
    def _find_avail_device_number(self, storage_system):
        out_device_number = '000000'
        out_num_device_number = 0
        numlist = []
        myunitnames = []

        conn = self._get_ecom_connection()
        unitnames = conn.EnumerateInstanceNames(
            'CIM_ProtocolControllerForUnit')
        for unitname in unitnames:
            controller = unitname['Antecedent']
            if storage_system != controller['SystemName']:
                continue
            classname = controller['CreationClassName']
            index = classname.find('LunMaskingSCSIProtocolController')
            if index > -1:
                unitinstance = conn.GetInstance(unitname, LocalOnly=False)
                numDeviceNumber = int(unitinstance['DeviceNumber'])
                numlist.append(numDeviceNumber)
                myunitnames.append(unitname)

        maxnum = max(numlist)
        out_num_device_number = maxnum + 1

        out_device_number = '%06d' % out_num_device_number

        LOG.debug(_("Available device number on %(storage)s: %(device)s.")
                  % {'storage': storage_system, 'device': out_device_number})
        return out_device_number

    # Find a device number that a host can see for a volume
    def _find_device_number(self, volume):
        out_num_device_number = None

        conn = self._get_ecom_connection()
        volumename = volume['name']
        vol_instance = self._find_lun(volume)

        unitnames = conn.ReferenceNames(
                        vol_instance.path,
                        ResultClass='CIM_ProtocolControllerForUnit')

        for unitname in unitnames:
            controller = unitname['Antecedent']
            classname = controller['CreationClassName']
            index = classname.find('LunMaskingSCSIProtocolController')
            if index > -1:  # VNX
                # Get an instance of CIM_ProtocolControllerForUnit
                unitinstance = conn.GetInstance(unitname, LocalOnly=False)
                numDeviceNumber = int(unitinstance['DeviceNumber'], 16)
                out_num_device_number = numDeviceNumber
                break
            else:
                index = classname.find('Symm_LunMaskingView')
                if index > -1:  # VMAX/VMAXe
                    unitinstance = conn.GetInstance(unitname, LocalOnly=False)
                    numDeviceNumber = int(unitinstance['DeviceNumber'], 16)
                    out_num_device_number = numDeviceNumber
                    break

        if out_num_device_number is None:
            LOG.info(_("Device number not found for volume "
                     "%(volumename)s %(vol_instance)s.") %
                     {'volumename': volumename,
                      'vol_instance': str(vol_instance.path)})
        else:
            LOG.debug(_("Found device number %(device)d for volume "
                      "%(volumename)s %(vol_instance)s.") %
                      {'device': out_num_device_number,
                       'volumename': volumename,
                       'vol_instance': str(vol_instance.path)})

        return out_num_device_number

    def _find_device_masking_group(self):
        """Finds the Device Masking Group in a masking view."""
        foundMaskingGroup = None
        maskingview_name = self._get_masking_view()
        conn = self._get_ecom_connection()
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        maskingviews = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for view in maskingviews:
            instance = conn.GetInstance(view, LocalOnly=False)
            if maskingview_name == instance['ElementName']:
                foundView = view
                break

        groups = conn.AssociatorNames(foundView,
                                      ResultClass='SE_DeviceMaskingGroup')
        foundMaskingGroup = groups[0]

        LOG.debug(_("Masking view: %(view)s DeviceMaskingGroup: %(masking)s.")
                  % {'view': maskingview_name,
                     'masking': str(foundMaskingGroup)})

        return foundMaskingGroup

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
