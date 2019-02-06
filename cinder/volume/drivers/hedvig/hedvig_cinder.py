# Copyright (c) 2018 Hedvig, Inc.
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
Volume driver for Hedvig Block Storage.

"""

import socket

from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.hedvig import config
from cinder.volume.drivers.hedvig import rest_client
from cinder.volume.drivers.san import san
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


@interface.volumedriver
class HedvigISCSIDriver(driver.ISCSIDriver, san.SanDriver):
    """OpenStack Cinder driver to enable Hedvig storage.

    .. code-block:: none

     Version history:

        1.0 - Initial driver

    """
    DEFAULT_VOL_BLOCK_SIZE = 4 * units.Ki
    DEFAULT_CREATEDBY = "OpenStack"
    DEFAULT_EXPORT_BLK_SIZE = 4096
    DEFAULT_CAPACITY = units.Gi
    DEFAULT_ISCSI_PORT = 3260
    DEFAULT_TARGET_NAME = "iqn.2012-05.com.hedvig:storage."
    VERSION = "1.0.0"
    CI_WIKI_NAME = "Hedvig_CI"

    def __init__(self, *args, **kwargs):
        super(HedvigISCSIDriver, self).__init__(*args, **kwargs)
        self.group_stats = {}
        self.hrs = None

    @staticmethod
    def get_driver_options():
        return []

    def check_for_setup_error(self):
        self.hrs.connect()
        LOG.info("Initialization complete")

    def do_setup(self, context):
        # Ensure that the data required by hedvig are provided
        required_config = ['san_login', 'san_password', 'san_ip',
                           'san_clustername']
        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                msg = _('Hedvig param %s is not set.') % attr
                LOG.error(msg)
                raise exception.VolumeDriverException(msg)
        self.san_ip = self.configuration.san_ip
        self.san_login = self.configuration.san_login
        self.san_password = self.configuration.san_password
        self.san_clustername = self.configuration.san_clustername
        LOG.info('Initializing hedvig cinder driver with '
                 'server: %s', self.san_ip)
        self.hrs = rest_client.RestClient(self.san_ip,
                                          self.san_login,
                                          self.san_password,
                                          self.san_clustername)

    def get_volume_stats(self, refresh=False):
        # we need to get get stats for server.
        if refresh is True:
            total_capacity, free_capacity = self.update_volume_stats()
            stats = dict()
            stats["volume_backend_name"] = "hedvig"
            stats["vendor_name"] = "Hedvig Inc"
            stats["driver_version"] = self.VERSION
            stats["storage_protocol"] = "iSCSI"
            stats["total_capacity_gb"] = total_capacity
            stats["free_capacity_gb"] = free_capacity
            stats["QoS_support"] = True
            self.group_stats = stats
        return self.group_stats

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        try:
            qos_specs = None
            name, description, size = self.get_hedvig_volume_details(volume)
            vol_type_id = volume.volume_type_id
            if vol_type_id is not None:
                qos = volume_types.get_volume_type_qos_specs(vol_type_id)
                qos_specs = qos['qos_specs']
            self.hedvig_create_virtualdisk(name, description, size, qos_specs)
        except exception.VolumeDriverException:
            msg = _('Failed to create volume %s. Rest API failed'
                    ) % volume.name
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to create volume: %s') % volume.name
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def delete_volume(self, volume):
        """Driver entry point for deleting volume."""
        LOG.debug("Deleting volume: %s", volume.name)
        name = volume.name
        try:
            self.hedvig_delete_virtualdisk(name)
        except exception.VolumeDriverException:
            msg = _('Failed to delete volume %s. Rest API failed'
                    ) % volume.name
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to delete volume: %s') % volume.name
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume."""
        try:
            LOG.debug('Create cloned volume called '
                      'volume_id = %(volume)s and src_vol_id = %(src_vol_id)s',
                      {'volume': volume.id, 'src_vol_id': src_vref.id})
            name, desc, size = self.get_hedvig_volume_details(volume)
            self.hrs.clone_vdisk(srcVolName=src_vref.name, dstVolName=name,
                                 size=size)
        except exception.VolumeDriverException:
            msg = _('Failed to create cloned volume. Rest API failed')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to create cloned volume')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance.

        Assign any created volume to a compute node/controllerVM so
        that it can be attached to a instance.
        This driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined as follows -- similar
        to _get_iscsi_properties.
        """
        LOG.debug('Initializing connection. volume: %s, '
                  'connector: %s', volume, connector)
        try:
            computeHost = self.get_compute_host(connector)
            volName = volume.name
            tgtHost = self.hedvig_lookup_tgt(computeHost)
            if tgtHost is None:
                LOG.warning("No target registered for compute host %s",
                            computeHost)
                tgtHost = self.hedvig_lookup_tgt()
            lunnum = self.hedvig_get_lun(tgtHost, volName)
            if lunnum == -1:
                LOG.error('Failed to get lun for volume: %s, '
                          'hedvig controller: %s', volume, tgtHost)
                raise exception.VolumeDriverException()

            # Add access to the mgmt interface addr and iqn of compute host
            LOG.debug("Calling add access %(host)s : %(vol)s : %(iqn)s ",
                      {'host': tgtHost, 'vol': volName,
                       'iqn': connector['initiator']})
            self.hedvig_add_access(tgtHost, volName, connector['initiator'])

            # Add access to both storage and mgmt interface addrs for
            # iscsi discovery to succeed
            LOG.debug("Calling hedvig_get_iqn %s", socket.getfqdn())
            controller_host_iqn = self.hedvig_get_iqn(socket.getfqdn())

            LOG.debug("Calling add access with %s : %s : %s ", tgtHost,
                      volName, controller_host_iqn)
            self.hedvig_add_access(tgtHost, volName, controller_host_iqn)
            targetName = ("%s%s-%s" % (self.DEFAULT_TARGET_NAME, tgtHost,
                                       lunnum))
            portal = ("%s:%s" % (socket.gethostbyname(tgtHost),
                                 self.DEFAULT_ISCSI_PORT))
            iscsi_properties = ({'target_discovered': True,
                                 'target_iqn': targetName,
                                 'target_portal': portal,
                                 'target_lun': lunnum})
            LOG.debug("iscsi_properties: %s", iscsi_properties)
            return {'driver_volume_type': 'iscsi', 'data': iscsi_properties}
        except exception.VolumeDriverException:
            msg = _('Volume assignment to connect failed. volume: %s '
                    'Rest API failed') % volume
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Volume assignment to connect failed. volume: %s') % volume
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach volume from instance."""
        LOG.debug("Terminating connection. volume: %s, connector: %s",
                  volume, connector)
        try:
            volName = volume.name
            if connector is None:
                LOG.debug("Removing ALL host connections for volume %s",
                          volume)
                targetList = self.hrs.list_targets(computeHost=None)
                for target in targetList:
                    self.hedvig_delete_lun(target, volName)
                return
            computeHost = self.get_compute_host(connector)
            tgtHost = self.hedvig_lookup_tgt(computeHost)
            if tgtHost is None:
                LOG.debug("No target registered for compute host %s",
                          computeHost)
                tgtHost = self.hedvig_lookup_tgt()
            if tgtHost is None:
                msg = _('Failed to get hedvig controller')
                LOG.error(msg)
                raise exception.VolumeDriverException(msg)
            self.hedvig_delete_lun(tgtHost, volName)
        except exception.VolumeDriverException:
            msg = _('Failed to terminate connection. volume: %s '
                    'Rest API failed') % volume
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to terminate connection. volume: %s') % volume
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot."""
        try:
            volName = snapshot.volume_name
            snapshotName = snapshot.name
            project = snapshot.project_id
            snapshotId = snapshot.id
            LOG.info("Creating snapshot. volName: %s, snapshotName: %s, "
                     "project: %s, snapshotId: %s", volName,
                     snapshotName, project, snapshotId)
            self.hedvig_create_snapshot(volName, snapshotId)
        except exception.VolumeDriverException:
            msg = (_('Failed to create snapshot. snapshotName: %s '
                     'Rest API failed') % snapshotName)
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = (_('Failed to create snapshot. snapshotName: %s')
                   % snapshotName)
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        try:
            volName = snapshot.volume_name
            snapshotName = snapshot.display_name
            project = snapshot.project_id
            snapshotId = snapshot.id
            LOG.info("Deleting snapshot. volName: %s, snapshotName: %s, "
                     "project: %s", volName, snapshotName, project)
            self.hrs.delete_snapshot(snapshotName, volName, snapshotId)
        except exception.VolumeDriverException:
            msg = _('Failed to delete snapshot: %s, '
                    'Rest API failed') % snapshotName
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to delete snapshot: %s') % snapshotName
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for creating a new volume from a snapshot.

        This is the same as cloning.
        """
        name, description, size = self.get_hedvig_volume_details(volume)
        snapshotName = snapshot.display_name
        snapshotId = snapshot.id
        srcVolName = snapshot.volume_name
        try:
            LOG.info('Creating volume from snapshot. Name: %(volname)s,'
                     ' SrcVolName: %(src)s, Snap_id: %(sid)s',
                     {'volname': name, 'src': srcVolName, 'sid': snapshotId})
            self.hedvig_clone_snapshot(name, snapshotId, srcVolName, size)
        except exception.VolumeDriverException:
            msg = _('Failed to create volume from snapshot %s'
                    ' Rest API failed') % snapshotName
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to create volume from snapshot %s') % snapshotName
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def extend_volume(self, volume, newSize):
        """Resizes virtual disk.

        newSize should be greater than current size.
        """
        try:
            name, description, size = self.get_hedvig_volume_details(volume)
            LOG.info('Resizing virtual disk. name: %s, '
                     'newSize: %s', name, newSize)
            if (size / units.Gi) >= newSize:
                err = _("Shrinking of volumes are not allowed")
                LOG.error(err)
                raise exception.VolumeDriverException(err)
            self.hrs.resize_vdisk(
                name,
                newSize)
        except exception.VolumeDriverException:
            msg = _('Failed to extend volume. Rest API failed')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to extend volume')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def check_for_export(self, context, volume_id):
        """Not relevant to Hedvig"""
        pass

    def get_export(self, volume):
        """Get the iSCSI export details for a volume."""
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume.

        Irrelevant for Hedvig. Export is created during attachment to instance.
        """
        pass

    def create_export(self, context, volume, properties):
        """Driver entry point to get the export info for a new volume.

        Irrelevant for Hedvig. Export is created during attachment to instance.
        """
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.

        Irrelevant for Hedvig. Export should be deleted on detachment.
        """
        pass

    def detach_volume(self, context, volume, attachment):
        pass

    def hedvig_create_snapshot(self, vDiskName, snapshotId=None):
        """Hedvig call to create snapshot of vdisk."""
        LOG.debug("Creating snapshot..%s , %s.", vDiskName, snapshotId)
        try:
            snapshotName = self.hrs.create_snapshot(vDiskName, snapshotId)
            LOG.debug("Received snapshotName %s from rest call",
                      snapshotName)
            return snapshotName
        except exception.VolumeDriverException:
            msg = _('Failed to create snapshot for vdisk %s '
                    'Rest API failed') % vDiskName
            LOG.exception(msg)
            raise exception.VolumeDriverException()
        except Exception:
            msg = _('Failed to create snapshot for vdisk %s') % vDiskName
            LOG.exception(msg)
            raise exception.VolumeDriverException()

    def update_volume_stats(self):
        LOG.debug('Update volume stats called')
        try:
            total_capacity, free_capacity = self.hrs.update_volume_stats()
        except exception.VolumeDriverException:
            msg = _('Unable to fetch volume stats. Rest API failed')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Unable to fetch volume stats')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        return (total_capacity, free_capacity)

    def get_hedvig_volume_details(self, volume):
        volName = volume.name
        project = volume.project_id
        displayName = volume.display_name
        displayDescription = volume.display_description
        description = ("%s\n%s\n%s" % (project, displayName,
                                       displayDescription))
        size = volume.size * units.Gi
        return volName, description, size

    def get_compute_host(self, connector):
        connectorHost = socket.getfqdn(connector['host'])
        localHost = socket.gethostname()
        computeHost = localHost
        if connectorHost != localHost:
            computeHost = connectorHost
        return computeHost

    def hedvig_lookup_tgt(self, host=None):
        """Get the tgt instance associated with the compute host"""
        LOG.debug("Looking up hedvig controller for compute host: %s",
                  host)
        try:
            targetList = self.hrs.list_targets(computeHost=host)
            tgt = None
            if len(targetList) > 0:
                tgt = targetList[0]

            LOG.debug("Found hedvig controller: %s, for host: %s", tgt, host)
            return tgt
        except exception.VolumeDriverException:
            msg = _('Failed to get hedvig controller for compute %s '
                    'Rest API failed') % host
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)
        except Exception:
            msg = _('Failed to get hedvig controller for compute %s ') % host
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_delete_lun(self, tgtHost, vDiskName):
        try:
            LOG.debug("Deleting lun. hedvig controller: %s, vDiskName: %s,",
                      tgtHost, vDiskName)
            self.hrs.unmap_lun(tgtHost, vDiskName)
        except Exception:
            msg = _('Failed to delete lun')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_get_lun(self, tgtHost, vDiskName):
        """Looks up lun based on tgthost and vDiskName.

        If lun does not exist then call add_lun and return the lun number.
        If lun exists, just return the lun number.
        """
        LOG.debug("Getting lun. hedvig controller: %s, vDiskName: %s",
                  tgtHost, vDiskName)
        try:
            lunNo = self.hrs.get_lun(tgtHost, vDiskName)
            if lunNo > -1:
                return lunNo

            # If the lun is not found, add lun for the vdisk
            LOG.debug("Calling add lun on target : %s vdisk %s", tgtHost,
                      vDiskName)
            self.hrs.add_lun(tgtHost, vDiskName, False)
            lunNo = self.hrs.get_lun(tgtHost, vDiskName)
            return lunNo

        except Exception:
            msg = _('Failed to get lun for vdisk: %s') % vDiskName
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_get_iqn(self, hostname):
        """Looks up the iqn for the given host."""
        try:
            iqn = self.hrs.get_iqn(hostname)
            LOG.debug("Got IQN: %s, for hostname: %s", iqn, hostname)
            return iqn
        except Exception:
            msg = _('Failed to get iqn for hostname: %s') % hostname
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_add_access(self, tgtHost, volName, initiator):
        """Adds access to LUN for initiator's ip/iqn."""
        try:
            LOG.info("Adding access. hedvig controller: %s, vol name  %s, "
                     "initiator: %s", tgtHost, volName, initiator)
            self.hrs.add_access(tgtHost, volName, "iqn", initiator)
        except Exception:
            msg = _('Failed to add access. hedvig controller: %s') % tgtHost
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_create_virtualdisk(self, name, description, size, qos_specs):
        try:
            LOG.info('Creating virtual disk. name: %s, description: %s,'
                     'size: %s', name, description, size)
            vDiskInfo = {
                'name': name.encode('utf-8'),
                'blockSize': HedvigISCSIDriver.DEFAULT_VOL_BLOCK_SIZE,
                'size': size,
                'createdBy':
                    HedvigISCSIDriver.DEFAULT_CREATEDBY,
                'description': description.encode('utf-8'),
                'residence': config.Config.DiskResidence[1],
                'replicationFactor': 3,
                'replicationPolicy': 'Agnostic',
                'clusteredFileSystem': False,
                'exportedBlockSize': HedvigISCSIDriver.DEFAULT_EXPORT_BLK_SIZE,
                'cacheEnabled': config.Config.defaultCinderCacheEnable,
                'diskType': 'BLOCK',
                'immutable': False,
                'deduplication': config.Config.defaultCinderDedupEnable,
                'compressed': config.Config.defaultCinderCompressEnable,
                'cloudEnabled': False,
                'cloudProvider': 0,
                'isClone': False,
                'consistency': 'STRONG',
                'scsi3pr': False
            }
            if qos_specs:
                kvs = qos_specs['specs']
                for key, value in kvs.items():
                    if "dedup_enable" == key:
                        val = self.parse_and_get_boolean_entry(
                            value)
                        if val:
                            vDiskInfo['deduplication'] = val
                    elif "compressed_enable" == key:
                        val = self.parse_and_get_boolean_entry(
                            value)
                        if val:
                            vDiskInfo['compressed'] = True
                    elif "cache_enable" == key:
                        val = self.parse_and_get_boolean_entry(
                            value.encode('utf-8'))
                        if val:
                            vDiskInfo['cacheEnabled'] = val
                    elif "encryption" == key:
                        val = self.parse_and_get_boolean_entry(
                            value.encode('utf-8'))
                        if val:
                            vDiskInfo['encryption'] = val
                    elif "replication_factor" == key:
                        val = int(value)
                        if val > 0:
                            vDiskInfo['replicationFactor'] = val
                    elif "replication_policy" == key:
                        val = value.strip(" \n\t").lower()
                        if val:
                            vDiskInfo['replicationPolicy'] = val
                    elif "disk_residence" == key:
                        val = value.strip(" \n\t").lower()
                        if val:
                            vDiskInfo['residence'] = val
                    elif "replication_policy_info" == key:
                        val = value.split(',')
                        if len(val) != 0:
                            dcList = []
                            for dataCenter in val:
                                dcList.append(dataCenter.encode('utf-8'))
                            vDiskInfo['dataCenters'] = dcList

            if vDiskInfo['deduplication'] and (
                    vDiskInfo['compressed'] is False):
                LOG.error('Cannot create dedup enabled disk without'
                          ' compression enabled')
                raise exception.VolumeDriverException()
            self.hrs.create_vdisk(vDiskInfo)
        except Exception:
            msg = _('Failed to create volume')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_delete_virtualdisk(self, name):
        LOG.info('Deleting virtual disk. name - %s', name)
        try:
            self.hrs.delete_vdisk(name)
        except Exception:
            msg = _('Failed to delete Vdisk')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def hedvig_clone_snapshot(self, dstVolName,
                              openstackSID, srcVolName, size):
        LOG.info("Cloning a snapshot.dstVolName: %s,openstackSID:%s,"
                 "srcVolName: %s", dstVolName, openstackSID, srcVolName)
        try:
            self.hrs.clone_hedvig_snapshot(
                dstVolName=dstVolName,
                snapshotID=openstackSID,
                srcVolName=srcVolName,
                size=size)
        except Exception:
            msg = _('Failed to clone snapshot')
            LOG.exception(msg)
            raise exception.VolumeDriverException(msg)

    def parse_and_get_boolean_entry(self, entry):
        entry = entry.strip(" \t\n")
        return strutils.bool_from_string(entry)
