# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 EMC Corporation.
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
Common class for SMI-S based EMC volume drivers.

This common class is for EMC volume drivers based on SMI-S.
It supports VNX and VMAX arrays.

"""

import time

from oslo.config import cfg
from xml.dom.minidom import parseString

from cinder import exception
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

try:
    import pywbem
except ImportError:
    LOG.info(_('Module PyWBEM not installed.  '
               'Install PyWBEM using the python-pywbem package.'))

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_emc_config.xml'


class EMCSMISCommon():
    """Common code that can be used by ISCSI and FC drivers."""

    stats = {'driver_version': '1.0',
             'free_capacity_gb': 0,
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 0,
             'vendor_name': 'EMC',
             'volume_backend_name': None}

    def __init__(self, prtcl, configuration=None):

        opt = cfg.StrOpt('cinder_emc_config_file',
                         default=CINDER_EMC_CONFIG_FILE,
                         help='use this file for cinder emc plugin '
                         'config data')
        CONF.register_opt(opt)
        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values([opt])

        ip, port = self._get_ecom_server()
        self.user, self.passwd = self._get_ecom_cred()
        self.url = 'http://' + ip + ':' + port
        self.conn = self._get_ecom_connection()

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VNX) volume."""

        LOG.debug(_('Entering create_volume.'))
        volumesize = int(volume['size']) * 1073741824
        volumename = volume['name']

        LOG.info(_('Create Volume: %(volume)s  Size: %(size)lu')
                 % {'volume': volumename,
                    'size': volumesize})

        self.conn = self._get_ecom_connection()

        storage_type = self._get_storage_type()

        LOG.debug(_('Create Volume: %(volume)s  '
                  'Storage type: %(storage_type)s')
                  % {'volume': volumename,
                     'storage_type': storage_type})

        pool, storage_system = self._find_pool(storage_type)

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

        rc, job = self.conn.InvokeMethod(
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

        self.conn = self._get_ecom_connection()

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
        rc, job = self.conn.InvokeMethod(
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

        rc, job = self.conn.InvokeMethod(
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

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug(_('Entering create_cloned_volume.'))

        srcname = src_vref['name']
        volumename = volume['name']

        LOG.info(_('Create a Clone from Volume: Volume: %(volumename)s  '
                 'Source Volume: %(srcname)s')
                 % {'volumename': volumename,
                    'srcname': srcname})

        self.conn = self._get_ecom_connection()

        src_instance = self._find_lun(src_vref)
        storage_system = src_instance['SystemName']

        LOG.debug(_('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s  Source Instance: '
                  '%(src_instance)s  Storage System: %(storage_system)s.')
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'src_instance': str(src_instance.path),
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

        LOG.debug(_('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s  Method: CreateElementReplica  '
                  'ReplicationService: %(service)s  ElementName: '
                  '%(elementname)s  SyncType: 8  SourceElement: '
                  '%(sourceelement)s')
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'service': str(repservice),
                     'elementname': volumename,
                     'sourceelement': str(src_instance.path)})

        # Create a Clone from source volume
        rc, job = self.conn.InvokeMethod(
            'CreateElementReplica', repservice,
            ElementName=volumename,
            SyncType=self._getnum(8, '16'),
            SourceElement=src_instance.path)

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
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
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s.  Successfully cloned volume '
                  'from source volume.  Finding the clone relationship.')
                  % {'volumename': volumename,
                     'srcname': srcname})

        sync_name, storage_system = self._find_storage_sync_sv_sv(
            volumename, srcname)

        # Remove the Clone relationshop so it can be used as a regular lun
        # 8 - Detach operation
        LOG.debug(_('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s.  Remove the clone '
                  'relationship. Method: ModifyReplicaSynchronization '
                  'ReplicationService: %(service)s  Operation: 8  '
                  'Synchronization: %(sync_name)s')
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'service': str(repservice),
                     'sync_name': str(sync_name)})

        rc, job = self.conn.InvokeMethod(
            'ModifyReplicaSynchronization',
            repservice,
            Operation=self._getnum(8, '16'),
            Synchronization=sync_name)

        LOG.debug(_('Create Cloned Volume: Volume: %(volumename)s  '
                  'Source Volume: %(srcname)s  Return code: %(rc)lu')
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                exception_message = (_('Error Create Cloned Volume: '
                                     'Volume: %(volumename)s  '
                                     'Source Volume: %(srcname)s.  '
                                     'Return code: %(rc)lu.  Error: %(error)s')
                                     % {'volumename': volumename,
                                        'srcname': srcname,
                                        'rc': rc,
                                        'error': errordesc})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        LOG.debug(_('Leaving create_cloned_volume: Volume: '
                  '%(volumename)s Source Volume: %(srcname)s  '
                  'Return code: %(rc)lu.')
                  % {'volumename': volumename,
                     'srcname': srcname,
                     'rc': rc})

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        LOG.debug(_('Entering delete_volume.'))
        volumename = volume['name']
        LOG.info(_('Delete Volume: %(volume)s')
                 % {'volume': volumename})

        self.conn = self._get_ecom_connection()

        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            LOG.error(_('Volume %(name)s not found on the array. '
                      'No volume to delete.')
                      % {'name': volumename})
            return

        storage_system = vol_instance['SystemName']

        configservice =\
            self._find_storage_configuration_service(storage_system)
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

        rc, job =\
            self.conn.InvokeMethod('EMCReturnToStoragePool',
                                   configservice,
                                   TheElements=[vol_instance.path])

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

        self.conn = self._get_ecom_connection()

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

        rc, job =\
            self.conn.InvokeMethod('CreateElementReplica', repservice,
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
                exception_message = (_('Error Create Snapshot: %(snapshot)s '
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

        self.conn = self._get_ecom_connection()

        LOG.debug(_('Delete Snapshot: %(snapshot)s: volume: %(volume)s. '
                  'Finding StorageSychronization_SV_SV.')
                  % {'snapshot': snapshotname,
                     'volume': volumename})

        sync_name, storage_system =\
            self._find_storage_sync_sv_sv(snapshotname, volumename, False)
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

        rc, job =\
            self.conn.InvokeMethod('ModifyReplicaSynchronization',
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

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        self.conn = self._get_ecom_connection()
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

    # Mapping method for VNX
    def _expose_paths(self, configservice, vol_instance,
                      connector):
        """This method maps a volume to a host.

        It adds a volume and initiator to a Storage Group
        and therefore maps the volume to the host.
        """
        volumename = vol_instance['ElementName']
        lun_name = vol_instance['DeviceID']
        initiators = self._find_initiator_names(connector)
        storage_system = vol_instance['SystemName']
        lunmask_ctrl = self._find_lunmasking_scsi_protocol_controller(
            storage_system, connector)

        LOG.debug(_('ExposePaths: %(vol)s  ConfigServicie: %(service)s  '
                  'LUNames: %(lun_name)s  InitiatorPortIDs: %(initiator)s  '
                  'DeviceAccesses: 2')
                  % {'vol': str(vol_instance.path),
                     'service': str(configservice),
                     'lun_name': lun_name,
                     'initiator': initiators})

        if lunmask_ctrl is None:
            rc, controller =\
                self.conn.InvokeMethod('ExposePaths',
                                       configservice, LUNames=[lun_name],
                                       InitiatorPortIDs=initiators,
                                       DeviceAccesses=[self._getnum(2, '16')])
        else:
            LOG.debug(_('ExposePaths parameter '
                      'LunMaskingSCSIProtocolController: '
                      '%(lunmasking)s')
                      % {'lunmasking': str(lunmask_ctrl)})
            rc, controller =\
                self.conn.InvokeMethod('ExposePaths',
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
    def _hide_paths(self, configservice, vol_instance,
                    connector):
        """This method unmaps a volume from the host.

        Removes a volume from the Storage Group
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

        rc, controller = self.conn.InvokeMethod(
            'HidePaths', configservice,
            LUNames=[device_id], ProtocolControllers=[lunmask_ctrl])

        if rc != 0L:
            msg = (_('Error unmapping volume %s.') % volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('HidePaths for volume %s completed successfully.')
                  % volumename)

    # Mapping method for VMAX
    def _add_members(self, configservice, vol_instance):
        """This method maps a volume to a host.

        Add volume to the Device Masking Group that belongs to
        a Masking View.
        """
        volumename = vol_instance['ElementName']
        masking_group = self._find_device_masking_group()

        LOG.debug(_('AddMembers: ConfigServicie: %(service)s  MaskingGroup: '
                  '%(masking_group)s  Members: %(vol)s')
                  % {'service': str(configservice),
                     'masking_group': str(masking_group),
                     'vol': str(vol_instance.path)})

        rc, job =\
            self.conn.InvokeMethod('AddMembers',
                                   configservice,
                                   MaskingGroup=masking_group,
                                   Members=[vol_instance.path])

        if rc != 0L:
            rc, errordesc = self._wait_for_job_complete(job)
            if rc != 0L:
                msg = (_('Error mapping volume %(vol)s. %(error)s') %
                       {'vol': volumename, 'error': errordesc})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_('AddMembers for volume %s completed successfully.')
                  % volumename)

    # Unmapping method for VMAX
    def _remove_members(self, configservice, vol_instance):
        """This method unmaps a volume from a host.

        Removes volume from the Device Masking Group that belongs to
        a Masking View.
        """
        volumename = vol_instance['ElementName']
        masking_group = self._find_device_masking_group()

        LOG.debug(_('RemoveMembers: ConfigServicie: %(service)s  '
                  'MaskingGroup: %(masking_group)s  Members: %(vol)s')
                  % {'service': str(configservice),
                     'masking_group': str(masking_group),
                     'vol': str(vol_instance.path)})

        rc, job = self.conn.InvokeMethod('RemoveMembers', configservice,
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

    def _map_lun(self, volume, connector):
        """Maps a volume to the host."""
        volumename = volume['name']
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

        isVMAX = storage_system.find('SYMMETRIX')
        if isVMAX > -1:
            self._add_members(configservice, vol_instance)
        else:
            self._expose_paths(configservice, vol_instance, connector)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host."""
        volumename = volume['name']
        LOG.info(_('Unmap volume: %(volume)s')
                 % {'volume': volumename})

        device_info = self.find_device_number(volume)
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

        isVMAX = storage_system.find('SYMMETRIX')
        if isVMAX > -1:
            self._remove_members(configservice, vol_instance)
        else:
            self._hide_paths(configservice, vol_instance, connector)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""
        volumename = volume['name']
        LOG.info(_('Initialize connection: %(volume)s')
                 % {'volume': volumename})
        self.conn = self._get_ecom_connection()
        device_info = self.find_device_number(volume)
        device_number = device_info['hostlunid']
        if device_number is not None:
            LOG.info(_("Volume %s is already mapped.")
                     % (volumename))
        else:
            self._map_lun(volume, connector)
            # Find host lun id again after the volume is exported to the host
            device_info = self.find_device_number(volume)

        return device_info

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector."""
        volumename = volume['name']
        LOG.info(_('Terminate connection: %(volume)s')
                 % {'volume': volumename})
        self.conn = self._get_ecom_connection()
        self._unmap_lun(volume, connector)

    def update_volume_stats(self):
        """Retrieve stats info."""
        LOG.debug(_("Updating volume stats"))
        self.conn = self._get_ecom_connection()
        storage_type = self._get_storage_type()

        pool, storagesystem = self._find_pool(storage_type, True)

        self.stats['total_capacity_gb'] = pool['TotalManagedSpace']
        self.stats['free_capacity_gb'] = pool['RemainingManagedSpace']

        return self.stats

    def _get_storage_type(self, filename=None):
        """Get the storage type from the config file."""
        if filename is None:
            filename = self.configuration.cinder_emc_config_file

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
            exception_message = (_("Storage type not found."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _get_masking_view(self, filename=None):
        if filename is None:
            filename = self.configuration.cinder_emc_config_file

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
        if filename is None:
            filename = self.configuration.cinder_emc_config_file

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
        if filename is None:
            filename = self.configuration.cinder_emc_config_file

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
            LOG.debug(_("Ecom IP: %(ecomIp)s Port: %(ecomPort)s"),
                      {'ecomIp': ecomIp, 'ecomPort': ecomPort})
            return ecomIp, ecomPort
        else:
            LOG.debug(_("Ecom server not found."))
            return None

    def _get_ecom_connection(self, filename=None):
        conn = pywbem.WBEMConnection(self.url, (self.user, self.passwd),
                                     default_namespace='root/emc')
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        return conn

    def _find_replication_service(self, storage_system):
        foundRepService = None
        repservices = self.conn.EnumerateInstanceNames(
            'EMC_ReplicationService')
        for repservice in repservices:
            if storage_system == repservice['SystemName']:
                foundRepService = repservice
                LOG.debug(_("Found Replication Service: %s")
                          % (str(repservice)))
                break

        return foundRepService

    def _find_storage_configuration_service(self, storage_system):
        foundConfigService = None
        configservices = self.conn.EnumerateInstanceNames(
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
        configservices = self.conn.EnumerateInstanceNames(
            'EMC_ControllerConfigurationService')
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug(_("Found Controller Configuration Service: %s")
                          % (str(configservice)))
                break

        return foundConfigService

    def _find_storage_hardwareid_service(self, storage_system):
        foundConfigService = None
        configservices = self.conn.EnumerateInstanceNames(
            'EMC_StorageHardwareIDManagementService')
        for configservice in configservices:
            if storage_system == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug(_("Found Storage Hardware ID Management Service: %s")
                          % (str(configservice)))
                break

        return foundConfigService

    # Find pool based on storage_type
    def _find_pool(self, storage_type, details=False):
        foundPool = None
        systemname = None
        # Only get instance names if details flag is False;
        # Otherwise get the whole instances
        if details is False:
            vpools = self.conn.EnumerateInstanceNames(
                'EMC_VirtualProvisioningPool')
            upools = self.conn.EnumerateInstanceNames(
                'EMC_UnifiedStoragePool')
        else:
            vpools = self.conn.EnumerateInstances(
                'EMC_VirtualProvisioningPool')
            upools = self.conn.EnumerateInstances(
                'EMC_UnifiedStoragePool')

        for upool in upools:
            poolinstance = upool['InstanceID']
            # Example: CLARiiON+APM00115204878+U+Pool 0
            poolname, systemname = self._parse_pool_instance_id(poolinstance)
            if poolname is not None and systemname is not None:
                if str(storage_type) == str(poolname):
                    foundPool = upool
                    break

        if foundPool is None:
            for vpool in vpools:
                poolinstance = vpool['InstanceID']
                # Example: SYMMETRIX+000195900551+TP+Sol_Innov
                poolname, systemname = self._parse_pool_instance_id(
                    poolinstance)
                if poolname is not None and systemname is not None:
                    if str(storage_type) == str(poolname):
                        foundPool = vpool
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
        if len(idarray) > 2:
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

        names = self.conn.EnumerateInstanceNames('EMC_StorageVolume')

        for n in names:
            if device_id is not None:
                if n['DeviceID'] == device_id:
                    vol_instance = self.conn.GetInstance(n)
                    foundinstance = vol_instance
                    break
                else:
                    continue

            else:
                vol_instance = self.conn.GetInstance(n)
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

    def _find_storage_sync_sv_sv(self, snapshotname, volumename,
                                 waitforsync=True):
        foundsyncname = None
        storage_system = None
        percent_synced = 0

        LOG.debug(_("Source: %(volumename)s  Target: %(snapshotname)s.")
                  % {'volumename': volumename, 'snapshotname': snapshotname})

        names = self.conn.EnumerateInstanceNames(
            'SE_StorageSynchronized_SV_SV')

        for n in names:
            snapshot_instance = self.conn.GetInstance(n['SyncedElement'],
                                                      LocalOnly=False)
            if snapshotname != snapshot_instance['ElementName']:
                continue

            vol_instance = self.conn.GetInstance(n['SystemElement'],
                                                 LocalOnly=False)
            if vol_instance['ElementName'] == volumename:
                foundsyncname = n
                storage_system = vol_instance['SystemName']
                if waitforsync:
                    sync_instance = self.conn.GetInstance(n, LocalOnly=False)
                    percent_synced = sync_instance['PercentSynced']
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
            # Wait for SE_StorageSynchronized_SV_SV to be fully synced
            while waitforsync and percent_synced < 100:
                time.sleep(10)
                sync_instance = self.conn.GetInstance(foundsyncname,
                                                      LocalOnly=False)
                percent_synced = sync_instance['PercentSynced']

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

        LOG.debug(_("Found %(name)s: %(initiator)s.")
                  % {'name': name,
                     'initiator': foundinitiatornames})
        return foundinitiatornames

    def _wait_for_job_complete(self, job):
        jobinstancename = job['Job']

        while True:
            jobinstance = self.conn.GetInstance(jobinstancename,
                                                LocalOnly=False)
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
        initiators = self._find_initiator_names(connector)
        controllers = self.conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for ctrl in controllers:
            if storage_system != ctrl['SystemName']:
                continue
            associators =\
                self.conn.Associators(ctrl,
                                      resultClass='EMC_StorageHardwareID')
            for assoc in associators:
                # if EMC_StorageHardwareID matches the initiator,
                # we found the existing EMC_LunMaskingSCSIProtocolController
                # (Storage Group for VNX)
                # we can use for masking a new LUN
                hardwareid = assoc['StorageID']
                for initiator in initiators:
                    if hardwareid.lower() == initiator.lower():
                        foundCtrl = ctrl
                        break

                if foundCtrl is not None:
                    break

            if foundCtrl is not None:
                break

        LOG.debug(_("LunMaskingSCSIProtocolController for storage system "
                  "%(storage_system)s and initiator %(initiator)s is  "
                  "%(ctrl)s.")
                  % {'storage_system': storage_system,
                     'initiator': initiators,
                     'ctrl': str(foundCtrl)})
        return foundCtrl

    # Find LunMaskingSCSIProtocolController for the local host and the
    # specified storage volume
    def _find_lunmasking_scsi_protocol_controller_for_vol(self, vol_instance,
                                                          connector):
        foundCtrl = None
        initiators = self._find_initiator_names(connector)
        controllers =\
            self.conn.AssociatorNames(
                vol_instance.path,
                resultClass='EMC_LunMaskingSCSIProtocolController')

        for ctrl in controllers:
            associators =\
                self.conn.Associators(
                    ctrl,
                    resultClass='EMC_StorageHardwareID')
            for assoc in associators:
                # if EMC_StorageHardwareID matches the initiator,
                # we found the existing EMC_LunMaskingSCSIProtocolController
                # (Storage Group for VNX)
                # we can use for masking a new LUN
                hardwareid = assoc['StorageID']
                for initiator in initiators:
                    if hardwareid.lower() == initiator.lower():
                        foundCtrl = ctrl
                        break

                if foundCtrl is not None:
                    break

            if foundCtrl is not None:
                break

        LOG.debug(_("LunMaskingSCSIProtocolController for storage volume "
                  "%(vol)s and initiator %(initiator)s is  %(ctrl)s.")
                  % {'vol': str(vol_instance.path), 'initiator': initiators,
                     'ctrl': str(foundCtrl)})
        return foundCtrl

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

        LOG.debug(_("LunMaskingSCSIProtocolController for storage system "
                  "%(storage)s and %(connector)s is %(ctrl)s.")
                  % {'storage': storage_system,
                     'connector': connector,
                     'ctrl': str(ctrl)})

        associators = self.conn.Associators(
            ctrl,
            resultClass='EMC_StorageVolume')

        numVolumesMapped = len(associators)

        LOG.debug(_("Found %(numVolumesMapped)d volumes on storage system "
                  "%(storage)s mapped to %(initiator)s.")
                  % {'numVolumesMapped': numVolumesMapped,
                     'storage': storage_system,
                     'connector': connector})

        return numVolumesMapped

    # Find an available device number that a host can see
    def _find_avail_device_number(self, storage_system):
        out_device_number = '000000'
        out_num_device_number = 0
        numlist = []
        myunitnames = []

        unitnames = self.conn.EnumerateInstanceNames(
            'CIM_ProtocolControllerForUnit')
        for unitname in unitnames:
            controller = unitname['Antecedent']
            if storage_system != controller['SystemName']:
                continue
            classname = controller['CreationClassName']
            index = classname.find('LunMaskingSCSIProtocolController')
            if index > -1:
                unitinstance = self.conn.GetInstance(unitname,
                                                     LocalOnly=False)
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
    def find_device_number(self, volume):
        out_num_device_number = None

        volumename = volume['name']
        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']
        sp = None
        try:
            sp = vol_instance['EMCCurrentOwningStorageProcessor']
        except KeyError:
            # VMAX LUN doesn't have this property
            pass

        unitnames = self.conn.ReferenceNames(
            vol_instance.path,
            ResultClass='CIM_ProtocolControllerForUnit')

        for unitname in unitnames:
            controller = unitname['Antecedent']
            classname = controller['CreationClassName']
            index = classname.find('LunMaskingSCSIProtocolController')
            if index > -1:  # VNX
                # Get an instance of CIM_ProtocolControllerForUnit
                unitinstance = self.conn.GetInstance(unitname,
                                                     LocalOnly=False)
                numDeviceNumber = int(unitinstance['DeviceNumber'], 16)
                out_num_device_number = numDeviceNumber
                break
            else:
                index = classname.find('Symm_LunMaskingView')
                if index > -1:  # VMAX
                    unitinstance = self.conn.GetInstance(unitname,
                                                         LocalOnly=False)
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

        data = {'hostlunid': out_num_device_number,
                'storagesystem': storage_system,
                'owningsp': sp}

        LOG.debug(_("Device info: %(data)s.") % {'data': data})

        return data

    def _find_device_masking_group(self):
        """Finds the Device Masking Group in a masking view."""
        foundMaskingGroup = None
        maskingview_name = self._get_masking_view()

        maskingviews = self.conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for view in maskingviews:
            instance = self.conn.GetInstance(view, LocalOnly=False)
            if maskingview_name == instance['ElementName']:
                foundView = view
                break

        groups = self.conn.AssociatorNames(
            foundView,
            ResultClass='SE_DeviceMaskingGroup')
        foundMaskingGroup = groups[0]

        LOG.debug(_("Masking view: %(view)s DeviceMaskingGroup: %(masking)s.")
                  % {'view': maskingview_name,
                     'masking': str(foundMaskingGroup)})

        return foundMaskingGroup

    # Find a StorageProcessorSystem given sp and storage system
    def _find_storage_processor_system(self, owningsp, storage_system):
        foundSystem = None
        systems = self.conn.EnumerateInstanceNames(
            'EMC_StorageProcessorSystem')
        for system in systems:
            # Clar_StorageProcessorSystem.CreationClassName=
            # "Clar_StorageProcessorSystem",Name="CLARiiON+APM00123907237+SP_A"
            idarray = system['Name'].split('+')
            if len(idarray) > 2:
                storsystemname = idarray[0] + '+' + idarray[1]
                sp = idarray[2]

            if (storage_system == storsystemname and
                    owningsp == sp):
                foundSystem = system
                LOG.debug(_("Found Storage Processor System: %s")
                          % (str(system)))
                break

        return foundSystem

    # Find EMC_iSCSIProtocolEndpoint for the specified sp
    def _find_iscsi_protocol_endpoints(self, owningsp, storage_system):
        foundEndpoints = []

        processor = self._find_storage_processor_system(
            owningsp,
            storage_system)

        associators = self.conn.Associators(
            processor,
            resultClass='EMC_iSCSIProtocolEndpoint')
        for assoc in associators:
            # Name = iqn.1992-04.com.emc:cx.apm00123907237.a8,t,0x0001
            # SystemName = CLARiiON+APM00123907237+SP_A+8
            arr = assoc['SystemName'].split('+')
            if len(arr) > 2:
                processor_name = arr[0] + '+' + arr[1] + '+' + arr[2]
                if processor_name == processor['Name']:
                    arr2 = assoc['Name'].split(',')
                    if len(arr2) > 1:
                        foundEndpoints.append(arr2[0])

        LOG.debug(_("iSCSIProtocolEndpoint for storage system "
                  "%(storage_system)s and SP %(sp)s is  "
                  "%(endpoint)s.")
                  % {'storage_system': storage_system,
                     'sp': owningsp,
                     'endpoint': str(foundEndpoints)})
        return foundEndpoints

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

    # Find target WWNs
    def get_target_wwns(self, storage_system, connector):
        target_wwns = []

        configservice = self._find_storage_hardwareid_service(
            storage_system)
        if configservice is None:
            exception_msg = (_("Error finding Storage Hardware ID Service."))
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        hardwareids = self._find_storage_hardwareids(connector)

        LOG.debug(_('EMCGetTargetEndpoints: Service: %(service)s  '
                  'Storage HardwareIDs: %(hardwareids)s.')
                  % {'service': str(configservice),
                     'hardwareids': str(hardwareids)})

        for hardwareid in hardwareids:
            rc, targetendpoints = self.conn.InvokeMethod(
                'EMCGetTargetEndpoints',
                configservice,
                HardwareId=hardwareid)

            if rc != 0L:
                msg = (_('Error finding Target WWNs.'))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            endpoints = targetendpoints['TargetEndpoints']
            for targetendpoint in endpoints:
                wwn = targetendpoint['Name']
                # Add target wwn to the list if it is not already there
                if not any(d.get('wwn', None) == wwn for d in target_wwns):
                    target_wwns.append({'wwn': wwn})
                LOG.debug(_('Add target WWN: %s.') % wwn)

        LOG.debug(_('Target WWNs: %s.') % target_wwns)

        return target_wwns

    # Find Storage Hardware IDs
    def _find_storage_hardwareids(self, connector):
        foundInstances = []
        wwpns = self._find_initiator_names(connector)
        hardwareids = self.conn.EnumerateInstances(
            'SE_StorageHardwareID')
        for hardwareid in hardwareids:
            storid = hardwareid['StorageID']
            for wwpn in wwpns:
                if wwpn.lower() == storid.lower():
                    foundInstances.append(hardwareid.path)

        LOG.debug(_("Storage Hardware IDs for %(wwpns)s is "
                  "%(foundInstances)s.")
                  % {'wwpns': str(wwpns),
                     'foundInstances': str(foundInstances)})

        return foundInstances
