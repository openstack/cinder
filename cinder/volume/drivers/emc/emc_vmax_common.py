# Copyright (c) 2012 - 2015 EMC Corporation.
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

import inspect
import os.path

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume.drivers.emc import emc_vmax_fast
from cinder.volume.drivers.emc import emc_vmax_https
from cinder.volume.drivers.emc import emc_vmax_masking
from cinder.volume.drivers.emc import emc_vmax_provision
from cinder.volume.drivers.emc import emc_vmax_provision_v3
from cinder.volume.drivers.emc import emc_vmax_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

try:
    import pywbem
    pywbemAvailable = True
except ImportError:
    pywbemAvailable = False

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_emc_config.xml'
CINDER_EMC_CONFIG_FILE_PREFIX = '/etc/cinder/cinder_emc_config_'
CINDER_EMC_CONFIG_FILE_POSTFIX = '.xml'
BACKENDNAME = 'volume_backend_name'
PREFIXBACKENDNAME = 'capabilities:volume_backend_name'
PORTGROUPNAME = 'portgroupname'
EMC_ROOT = 'root/emc'
POOL = 'storagetype:pool'
ARRAY = 'storagetype:array'
FASTPOLICY = 'storagetype:fastpolicy'
BACKENDNAME = 'volume_backend_name'
COMPOSITETYPE = 'storagetype:compositetype'
STRIPECOUNT = 'storagetype:stripecount'
MEMBERCOUNT = 'storagetype:membercount'
STRIPED = 'striped'
CONCATENATED = 'concatenated'
SMI_VERSION_8 = 800
# V3
SLO = 'storagetype:slo'
WORKLOAD = 'storagetype:workload'
INTERVAL = 'storagetype:interval'
RETRIES = 'storagetype:retries'
ISV3 = 'isV3'
TRUNCATE_5 = 5
TRUNCATE_8 = 8

emc_opts = [
    cfg.StrOpt('cinder_emc_config_file',
               default=CINDER_EMC_CONFIG_FILE,
               help='use this file for cinder emc plugin '
                    'config data'), ]

CONF.register_opts(emc_opts)


class EMCVMAXCommon(object):
    """Common class for SMI-S based EMC volume drivers.

    This common class is for EMC volume drivers based on SMI-S.
    It supports VNX and VMAX arrays.

    """
    VERSION = "2.0.0"

    stats = {'driver_version': '1.0',
             'free_capacity_gb': 0,
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 0,
             'vendor_name': 'EMC',
             'volume_backend_name': None}

    pool_info = {'backend_name': None,
                 'config_file': None,
                 'arrays_info': {}}

    def __init__(self, prtcl, version, configuration=None):

        if not pywbemAvailable:
            LOG.info(_LI(
                "Module PyWBEM not installed. "
                "Install PyWBEM using the python-pywbem package."))

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(emc_opts)
        self.conn = None
        self.url = None
        self.user = None
        self.passwd = None
        self.masking = emc_vmax_masking.EMCVMAXMasking(prtcl)
        self.utils = emc_vmax_utils.EMCVMAXUtils(prtcl)
        self.fast = emc_vmax_fast.EMCVMAXFast(prtcl)
        self.provision = emc_vmax_provision.EMCVMAXProvision(prtcl)
        self.provisionv3 = emc_vmax_provision_v3.EMCVMAXProvisionV3(prtcl)
        self.version = version
        self._gather_info()

    def _gather_info(self):
        """Gather the relevant information for update_volume_stats."""
        if hasattr(self.configuration, 'cinder_emc_config_file'):
            self.pool_info['config_file'] = (
                self.configuration.cinder_emc_config_file)
        else:
            self.pool_info['config_file'] = (
                self.configuration.safe_get('cinder_emc_config_file'))

        self.pool_info['backend_name'] = (
            self.configuration.safe_get('volume_backend_name'))
        LOG.debug(
            "Updating volume stats on file %(emcConfigFileName)s on "
            "backend %(backendName)s.",
            {'emcConfigFileName': self.pool_info['config_file'],
             'backendName': self.pool_info['backend_name']})

        self.pool_info['arrays_info'] = (
            self.utils.parse_file_to_get_array_map(
                self.pool_info['config_file']))

    def create_volume(self, volume):
        """Creates a EMC(VMAX) volume from a pre-existing storage pool.

        For a concatenated compositeType:
        If the volume size is over 240GB then a composite is created
        EMCNumberOfMembers > 1, otherwise it defaults to a non composite

        For a striped compositeType:
        The user must supply an extra spec to determine how many metas
        will make up the striped volume. If the meta size is greater
        than 240GB an error is returned to the user. Otherwise the
        EMCNumberOfMembers is what the user specifies.

        :param volume: volume Object
        :returns: dict -- volumeDict - the volume dictionary
        """
        volumeSize = int(self.utils.convert_gb_to_bits(volume['size']))
        volumeName = volume['id']
        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        if extraSpecs[ISV3]:
            rc, volumeDict, storageSystemName = (
                self._create_v3_volume(volume, volumeName, volumeSize,
                                       extraSpecs))
        else:
            rc, volumeDict, storageSystemName = (
                self._create_composite_volume(volume, volumeName, volumeSize,
                                              extraSpecs))

        # If volume is created as part of a consistency group.
        if 'consistencygroup_id' in volume and volume['consistencygroup_id']:
            cgName = self.utils.truncate_string(
                volume['consistencygroup_id'], 8)
            volumeInstance = self.utils.find_volume_instance(
                self.conn, volumeDict, volumeName)
            replicationService = (
                self.utils.find_replication_service(self.conn,
                                                    storageSystemName))
            cgInstanceName = (
                self._find_consistency_group(replicationService, cgName))
            self.provision.add_volume_to_cg(self.conn,
                                            replicationService,
                                            cgInstanceName,
                                            volumeInstance.path,
                                            cgName,
                                            volumeName,
                                            extraSpecs)

        LOG.info(_LI("Leaving create_volume: %(volumeName)s  "
                     "Return code: %(rc)lu "
                     "volume dict: %(name)s."),
                 {'volumeName': volumeName,
                  'rc': rc,
                  'name': volumeDict})
        # Adding version information
        volumeDict['version'] = self.version

        return volumeDict

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        For VMAX, replace snapshot with clone.

        :param volume: volume Object
        :param snapshot: snapshot object
        :returns: dict -- the cloned volume dictionary
        :raises: VolumeBackendAPIException
        """
        LOG.debug("Entering create_volume_from_snapshot.")
        snapshot['host'] = volume['host']
        extraSpecs = self._initial_setup(snapshot)
        self.conn = self._get_ecom_connection()
        snapshotInstance = self._find_lun(snapshot)
        storageSystem = snapshotInstance['SystemName']

        syncName = self.utils.find_sync_sv_by_target(
            self.conn, storageSystem, snapshotInstance, extraSpecs, True)
        if syncName is not None:
            repservice = self.utils.find_replication_service(self.conn,
                                                             storageSystem)
            if repservice is None:
                exception_message = (_("Cannot find Replication Service to "
                                       "create volume for snapshot %s.")
                                     % snapshotInstance)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            self.provision.delete_clone_relationship(
                self.conn, repservice, syncName, extraSpecs)

        snapshot['host'] = volume['host']
        return self._create_cloned_volume(volume, snapshot, extraSpecs, False)

    def create_cloned_volume(self, cloneVolume, sourceVolume):
        """Creates a clone of the specified volume.

        :param cloneVolume: clone volume Object
        :param sourceVolume: volume object
        :returns: cloneVolumeDict -- the cloned volume dictionary
        """
        extraSpecs = self._initial_setup(sourceVolume)
        return self._create_cloned_volume(cloneVolume, sourceVolume,
                                          extraSpecs, False)

    def delete_volume(self, volume):
        """Deletes a EMC(VMAX) volume.

        :param volume: volume Object
        """
        LOG.info(_LI("Deleting Volume: %(volume)s"),
                 {'volume': volume['name']})

        rc, volumeName = self._delete_volume(volume)
        LOG.info(_LI("Leaving delete_volume: %(volumename)s  Return code: "
                     "%(rc)lu."),
                 {'volumename': volumeName,
                  'rc': rc})

    def create_snapshot(self, snapshot, volume):
        """Creates a snapshot.

        For VMAX, replace snapshot with clone.

        :param snapshot: snapshot object
        :param volume: volume Object to create snapshot from
        :returns: dict -- the cloned volume dictionary
        """
        extraSpecs = self._initial_setup(volume)
        return self._create_cloned_volume(snapshot, volume, extraSpecs, True)

    def delete_snapshot(self, snapshot, volume):
        """Deletes a snapshot.

        :param snapshot: snapshot object
        :param volume: volume Object to create snapshot from
        """
        LOG.info(_LI("Delete Snapshot: %(snapshotName)s."),
                 {'snapshotName': snapshot['name']})
        snapshot['host'] = volume['host']
        self._delete_snapshot(snapshot)

    def _remove_members(self, controllerConfigService,
                        volumeInstance, connector, extraSpecs):
        """This method unmaps a volume from a host.

        Removes volume from the Device Masking Group that belongs to
        a Masking View.
        Check if fast policy is in the extra specs. If it isn't we do
        not need to do any thing for FAST.
        Assume that isTieringPolicySupported is False unless the FAST
        policy is in the extra specs and tiering is enabled on the array.

        :param controllerConfigService: instance name of
            ControllerConfigurationService
        :param volumeInstance: volume Object
        :param connector: the connector object
        :param extraSpecs: extra specifications
        :returns: storageGroupInstanceName
        """
        volumeName = volumeInstance['ElementName']
        LOG.debug("Detaching volume %s.", volumeName)
        return self.masking.remove_and_reset_members(
            self.conn, controllerConfigService, volumeInstance,
            volumeName, extraSpecs, connector)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host.

        :param volume: the volume Object
        :param connector: the connector Object
        :raises: VolumeBackendAPIException
        """
        extraSpecs = self._initial_setup(volume)
        volumename = volume['name']
        LOG.info(_LI("Unmap volume: %(volume)s."),
                 {'volume': volumename})

        device_info = self.find_device_number(volume, connector['host'])
        device_number = device_info['hostlunid']
        if device_number is None:
            LOG.info(_LI("Volume %s is not mapped. No volume to unmap."),
                     volumename)
            return

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        configservice = self.utils.find_controller_configuration_service(
            self.conn, storage_system)
        if configservice is None:
            exception_message = (_("Cannot find Controller Configuration "
                                   "Service for storage system "
                                   "%(storage_system)s.")
                                 % {'storage_system': storage_system})
            raise exception.VolumeBackendAPIException(data=exception_message)

        self._remove_members(configservice, vol_instance, connector,
                             extraSpecs)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns device and connection info.

        The volume may be already mapped, if this is so the deviceInfo tuple
        is returned.  If the volume is not already mapped then we need to
        gather information to either 1. Create an new masking view or 2. Add
        the volume to an existing storage group within an already existing
        maskingview.

        The naming convention is the following:
        initiatorGroupName = OS-<shortHostName>-<shortProtocol>-IG
                             e.g OS-myShortHost-I-IG
        storageGroupName = OS-<shortHostName>-<poolName>-<shortProtocol>-SG
                           e.g OS-myShortHost-SATA_BRONZ1-I-SG
        portGroupName = OS-<target>-PG  The portGroupName will come from
                        the EMC configuration xml file.
                        These are precreated. If the portGroup does not exist
                        then an error will be returned to the user
        maskingView  = OS-<shortHostName>-<poolName>-<shortProtocol>-MV
                       e.g OS-myShortHost-SATA_BRONZ1-I-MV

        :param volume: volume Object
        :param connector: the connector Object
        :returns: dict -- deviceInfoDict - device information dict
        :raises: VolumeBackendAPIException
        """
        extraSpecs = self._initial_setup(volume)

        volumeName = volume['name']
        LOG.info(_LI("Initialize connection: %(volume)s."),
                 {'volume': volumeName})
        self.conn = self._get_ecom_connection()
        deviceInfoDict = self.find_device_number(volume, connector['host'])
        maskingViewDict = self._populate_masking_dict(
            volume, connector, extraSpecs)

        if ('hostlunid' in deviceInfoDict and
                deviceInfoDict['hostlunid'] is not None):
            isSameHost = self._is_same_host(connector, deviceInfoDict)
            if isSameHost:
                # Device is already mapped to same host so we will leave
                # the state as is.

                deviceNumber = deviceInfoDict['hostlunid']
                LOG.info(_LI("Volume %(volume)s is already mapped. "
                             "The device number is  %(deviceNumber)s."),
                         {'volume': volumeName,
                          'deviceNumber': deviceNumber})
            else:
                deviceInfoDict = self._attach_volume(
                    volume, connector, extraSpecs, maskingViewDict, True)
        else:
            deviceInfoDict = self._attach_volume(
                volume, connector, extraSpecs, maskingViewDict)

        if self.protocol.lower() == 'iscsi':
            return self._find_ip_protocol_endpoints(
                self.conn, deviceInfoDict['storagesystem'],
                maskingViewDict['pgGroupName'])
        else:
            return deviceInfoDict

    def _attach_volume(self, volume, connector, extraSpecs,
                       maskingViewDict, isLiveMigration=None):
        """Attach a volume to a host.

        If live migration is being undertaken then the volume
        remains attached to the source host.

        :params volume: the volume object
        :params connector: the connector object
        :param extraSpecs: extra specifications
        :param maskingViewDict: masking view information
        :param isLiveMigration: boolean, can be None
        :returns: dict -- deviceInfoDict
        :raises: VolumeBackendAPIException
        """
        volumeName = volume['name']
        maskingViewDict = self._populate_masking_dict(
            volume, connector, extraSpecs)
        if isLiveMigration:
            maskingViewDict['isLiveMigration'] = True
        else:
            maskingViewDict['isLiveMigration'] = False

        rollbackDict = self.masking.setup_masking_view(
            self.conn, maskingViewDict, extraSpecs)

        # Find host lun id again after the volume is exported to the host.
        deviceInfoDict = self.find_device_number(volume, connector['host'])
        if 'hostlunid' not in deviceInfoDict:
            # Did not successfully attach to host,
            # so a rollback for FAST is required.
            LOG.error(_LE("Error Attaching volume %(vol)s."),
                      {'vol': volumeName})
            if ((rollbackDict['fastPolicyName'] is not None) or
                    (rollbackDict['isV3'] is not None)):
                (self.masking
                    ._check_if_rollback_action_for_masking_required(
                        self.conn, rollbackDict))
            exception_message = (_("Error Attaching volume %(vol)s.")
                                 % {'vol': volumeName})
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        return deviceInfoDict

    def _is_same_host(self, connector, deviceInfoDict):
        """Check if the host is the same.

        Check if the host to attach to is the same host
        that is already attached. This is necessary for
        live migration.

        :params connector: the connector object
        :params deviceInfoDict: the device information dictionary
        :returns: boolean -- True if the host is the same, False otherwise.
        """
        if 'host' in connector:
            currentHost = connector['host']
            if ('maskingview' in deviceInfoDict and
                    deviceInfoDict['maskingview'] is not None):
                if currentHost in deviceInfoDict['maskingview']:
                    return True
        return False

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector.

        :params volume: the volume Object
        :params connector: the connector Object
        """
        volumename = volume['name']
        LOG.info(_LI("Terminate connection: %(volume)s."),
                 {'volume': volumename})

        self._unmap_lun(volume, connector)

    def extend_volume(self, volume, newSize):
        """Extends an existing volume.

        Prequisites:
        1. The volume must be composite e.g StorageVolume.EMCIsComposite=True
        2. The volume can only be concatenated
           e.g StorageExtent.IsConcatenated=True

        :params volume: the volume Object
        :params newSize: the new size to increase the volume to
        :returns: dict -- modifiedVolumeDict - the extended volume Object
        :raises: VolumeBackendAPIException
        """
        originalVolumeSize = volume['size']
        volumeName = volume['name']
        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()
        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            exceptionMessage = (_("Cannot find Volume: %(volumename)s. "
                                  "Extend operation.  Exiting....")
                                % {'volumename': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if int(originalVolumeSize) > int(newSize):
            exceptionMessage = (_(
                "Your original size: %(originalVolumeSize)s GB is greater "
                "than: %(newSize)s GB. Only Extend is supported. Exiting...")
                % {'originalVolumeSize': originalVolumeSize,
                   'newSize': newSize})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        additionalVolumeSize = six.text_type(
            int(newSize) - int(originalVolumeSize))
        additionalVolumeSize = self.utils.convert_gb_to_bits(
            additionalVolumeSize)

        # This is V2
        rc, modifiedVolumeDict = self._extend_composite_volume(
            volumeInstance, volumeName, newSize, additionalVolumeSize,
            extraSpecs)

        # Check the occupied space of the new extended volume.
        extendedVolumeInstance = self.utils.find_volume_instance(
            self.conn, modifiedVolumeDict, volumeName)
        extendedVolumeSize = self.utils.get_volume_size(
            self.conn, extendedVolumeInstance)
        LOG.debug(
            "The actual volume size of the extended volume: %(volumeName)s "
            "is %(volumeSize)s.",
            {'volumeName': volumeName,
             'volumeSize': extendedVolumeSize})

        # If the requested size and the actual size don't
        # tally throw an exception.
        newSizeBits = self.utils.convert_gb_to_bits(newSize)
        diffVolumeSize = self.utils.compare_size(
            newSizeBits, extendedVolumeSize)
        if diffVolumeSize != 0:
            exceptionMessage = (_(
                "The requested size : %(requestedSize)s is not the same as "
                "resulting size: %(resultSize)s.")
                % {'requestedSize': newSizeBits,
                   'resultSize': extendedVolumeSize})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug(
            "Leaving extend_volume: %(volumeName)s. "
            "Return code: %(rc)lu, "
            "volume dict: %(name)s.",
            {'volumeName': volumeName,
             'rc': rc,
             'name': modifiedVolumeDict})

        return modifiedVolumeDict

    def update_volume_stats(self):
        """Retrieve stats info."""
        pools = []
        backendName = self.pool_info['backend_name']
        for arrayInfo in self.pool_info['arrays_info']:
            self._set_ecom_credentials(arrayInfo)
            # Check what type of array it is
            isV3 = self.utils.isArrayV3(self.conn, arrayInfo['SerialNumber'])
            if isV3:
                location_info, total_capacity_gb, free_capacity_gb = (
                    self._update_srp_stats(arrayInfo))
                poolName = ("%(slo)s+%(poolName)s+%(array)s"
                            % {'slo': arrayInfo['SLO'],
                               'poolName': arrayInfo['PoolName'],
                               'array': arrayInfo['SerialNumber']})
            else:
                # This is V2
                location_info, total_capacity_gb, free_capacity_gb = (
                    self._update_pool_stats(backendName, arrayInfo))
                poolName = ("%(poolName)s+%(array)s"
                            % {'poolName': arrayInfo['PoolName'],
                               'array': arrayInfo['SerialNumber']})

            pool = {'pool_name': poolName,
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'reserved_percentage': 0,
                    'QoS_support': False,
                    'location_info': location_info,
                    'consistencygroup_support': True}
            pools.append(pool)

        data = {'vendor_name': "EMC",
                'driver_version': self.version,
                'storage_protocol': 'unknown',
                'volume_backend_name': self.pool_info['backend_name'] or
                self.__class__.__name__,
                # Use zero capacities here so we always use a pool.
                'total_capacity_gb': 0,
                'free_capacity_gb': 0,
                'reserved_percentage': 0,
                'pools': pools}

        return data

    def _update_srp_stats(self, arrayInfo):
        """Update SRP stats.

        :param arrayInfo: array information
        :returns: location_info
        :returns: totalManagedSpaceGbs
        :returns: remainingManagedSpaceGbs
        """

        totalManagedSpaceGbs, remainingManagedSpaceGbs = (
            self.provisionv3.get_srp_pool_stats(self.conn,
                                                arrayInfo))

        LOG.info(_LI(
            "Capacity stats for SRP pool %(poolName)s on array "
            "%(arrayName)s total_capacity_gb=%(total_capacity_gb)lu, "
            "free_capacity_gb=%(free_capacity_gb)lu"),
            {'poolName': arrayInfo['PoolName'],
             'arrayName': arrayInfo['SerialNumber'],
             'total_capacity_gb': totalManagedSpaceGbs,
             'free_capacity_gb': remainingManagedSpaceGbs})

        location_info = ("%(arrayName)s#%(poolName)s#%(slo)s#%(workload)s"
                         % {'arrayName': arrayInfo['SerialNumber'],
                            'poolName': arrayInfo['PoolName'],
                            'slo': arrayInfo['SLO'],
                            'workload': arrayInfo['Workload']})

        return location_info, totalManagedSpaceGbs, remainingManagedSpaceGbs

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param diff: Unused parameter.
        :param host: The host dict holding the relevant target(destination)
            information
        :returns: boolean -- True if retype succeeded, False if error
        """

        volumeName = volume['name']
        volumeStatus = volume['status']
        LOG.info(_LI("Migrating using retype Volume: %(volume)s."),
                 {'volume': volumeName})

        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            LOG.error(_LE("Volume %(name)s not found on the array. "
                          "No volume to migrate using retype."),
                      {'name': volumeName})
            return False

        if extraSpecs[ISV3]:
            return self._slo_workload_migration(volumeInstance, volume, host,
                                                volumeName, volumeStatus,
                                                new_type, extraSpecs)
        else:
            return self._pool_migration(volumeInstance, volume, host,
                                        volumeName, volumeStatus,
                                        extraSpecs[FASTPOLICY],
                                        new_type, extraSpecs)

    def migrate_volume(self, ctxt, volume, host, new_type=None):
        """Migrate volume to another host.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param host: the host dict holding the relevant target(destination)
            information
        :param new_type: None
        :returns: boolean -- Always returns True
        :returns: dict -- Empty dict {}
        """
        LOG.warning(_LW("The VMAX plugin only supports Retype. "
                        "If a pool based migration is necessary "
                        "this will happen on a Retype "
                        "From the command line: "
                        "cinder --os-volume-api-version 2 retype <volumeId> "
                        "<volumeType> --migration-policy on-demand"))
        return True, {}

    def _migrate_volume(
            self, volume, volumeInstance, targetPoolName,
            targetFastPolicyName, sourceFastPolicyName, extraSpecs,
            new_type=None):
        """Migrate volume to another host.

        :param volume: the volume object including the volume_type_id
        :param volumeInstance: the volume instance
        :param targetPoolName: the target poolName
        :param targetFastPolicyName: the target FAST policy name, can be None
        :param sourceFastPolicyName: the source FAST policy name, can be None
        :param extraSpecs: extra specifications
        :param new_type: None
        :returns: boolean -- True/False
        :returns: list -- empty list
        """
        volumeName = volume['name']
        storageSystemName = volumeInstance['SystemName']

        sourcePoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstance.path)

        moved, rc = self._migrate_volume_from(
            volume, volumeInstance, targetPoolName, sourceFastPolicyName,
            extraSpecs)

        if moved is False and sourceFastPolicyName is not None:
            # Return the volume to the default source fast policy storage
            # group because the migrate was unsuccessful.
            LOG.warning(_LW(
                "Failed to migrate: %(volumeName)s from "
                "default source storage group "
                "for FAST policy: %(sourceFastPolicyName)s. "
                "Attempting cleanup... "),
                {'volumeName': volumeName,
                 'sourceFastPolicyName': sourceFastPolicyName})
            if sourcePoolInstanceName == self.utils.get_assoc_pool_from_volume(
                    self.conn, volumeInstance.path):
                self._migrate_cleanup(self.conn, volumeInstance,
                                      storageSystemName, sourceFastPolicyName,
                                      volumeName, extraSpecs)
            else:
                # Migrate was successful but still issues.
                self._migrate_rollback(
                    self.conn, volumeInstance, storageSystemName,
                    sourceFastPolicyName, volumeName, sourcePoolInstanceName,
                    extraSpecs)

            return moved

        if targetFastPolicyName == 'None':
            targetFastPolicyName = None

        if moved is True and targetFastPolicyName is not None:
            if not self._migrate_volume_fast_target(
                    volumeInstance, storageSystemName,
                    targetFastPolicyName, volumeName, extraSpecs):
                LOG.warning(_LW(
                    "Attempting a rollback of: %(volumeName)s to "
                    "original pool %(sourcePoolInstanceName)s."),
                    {'volumeName': volumeName,
                     'sourcePoolInstanceName': sourcePoolInstanceName})
                self._migrate_rollback(
                    self.conn, volumeInstance, storageSystemName,
                    sourceFastPolicyName, volumeName, sourcePoolInstanceName,
                    extraSpecs)

        if rc == 0:
            moved = True

        return moved

    def _migrate_rollback(self, conn, volumeInstance,
                          storageSystemName, sourceFastPolicyName,
                          volumeName, sourcePoolInstanceName, extraSpecs):
        """Full rollback.

        Failed on final step on adding migrated volume to new target
        default storage group for the target FAST policy.

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name
        :param sourcePoolInstanceName: the instance name of the source pool
        :param extraSpecs: extra specifications
        """

        LOG.warning(_LW("_migrate_rollback on : %(volumeName)s."),
                    {'volumeName': volumeName})

        storageRelocationService = self.utils.find_storage_relocation_service(
            conn, storageSystemName)

        try:
            self.provision.migrate_volume_to_storage_pool(
                conn, storageRelocationService, volumeInstance.path,
                sourcePoolInstanceName, extraSpecs)
        except Exception:
            LOG.error(_LE(
                "Failed to return volume %(volumeName)s to "
                "original storage pool. Please contact your system "
                "administrator to return it to the correct location."),
                {'volumeName': volumeName})

        if sourceFastPolicyName is not None:
            self.add_to_default_SG(
                conn, volumeInstance, storageSystemName, sourceFastPolicyName,
                volumeName, extraSpecs)

    def _migrate_cleanup(self, conn, volumeInstance,
                         storageSystemName, sourceFastPolicyName,
                         volumeName, extraSpecs):
        """If the migrate fails, put volume back to source FAST SG.

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name
        :param extraSpecs: extra specifications
        :returns: boolean -- True/False
        """

        LOG.warning(_LW("_migrate_cleanup on : %(volumeName)s."),
                    {'volumeName': volumeName})
        return_to_default = True
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))

        # Check to see what SG it is in.
        assocStorageGroupInstanceNames = (
            self.utils.get_storage_groups_from_volume(conn,
                                                      volumeInstance.path))
        # This is the SG it should be in.
        defaultStorageGroupInstanceName = (
            self.fast.get_policy_default_storage_group(
                conn, controllerConfigurationService, sourceFastPolicyName))

        for assocStorageGroupInstanceName in assocStorageGroupInstanceNames:
            # It is in the incorrect storage group.
            if (assocStorageGroupInstanceName !=
                    defaultStorageGroupInstanceName):
                self.provision.remove_device_from_storage_group(
                    conn, controllerConfigurationService,
                    assocStorageGroupInstanceName,
                    volumeInstance.path, volumeName, extraSpecs)
            else:
                # The volume is already in the default.
                return_to_default = False
        if return_to_default:
            self.add_to_default_SG(
                conn, volumeInstance, storageSystemName, sourceFastPolicyName,
                volumeName, extraSpecs)
        return return_to_default

    def _migrate_volume_fast_target(
            self, volumeInstance, storageSystemName,
            targetFastPolicyName, volumeName, extraSpecs):
        """If the target host is FAST enabled.

        If the target host is FAST enabled then we need to add it to the
        default storage group for that policy.

        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param targetFastPolicyName: the target fast policy name
        :param volumeName: the volume name
        :param extraSpecs: extra specifications
        :returns: boolean -- True/False
        """
        falseRet = False
        LOG.info(_LI(
            "Adding volume: %(volumeName)s to default storage group "
            "for FAST policy: %(fastPolicyName)s."),
            {'volumeName': volumeName,
             'fastPolicyName': targetFastPolicyName})

        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        defaultStorageGroupInstanceName = (
            self.fast.get_or_create_default_storage_group(
                self.conn, controllerConfigurationService,
                targetFastPolicyName, volumeInstance, extraSpecs))
        if defaultStorageGroupInstanceName is None:
            LOG.error(_LE(
                "Unable to create or get default storage group for FAST policy"
                ": %(fastPolicyName)s."),
                {'fastPolicyName': targetFastPolicyName})

            return falseRet

        defaultStorageGroupInstanceName = (
            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                self.conn, controllerConfigurationService, volumeInstance,
                volumeName, targetFastPolicyName, extraSpecs))
        if defaultStorageGroupInstanceName is None:
            LOG.error(_LE(
                "Failed to verify that volume was added to storage group for "
                "FAST policy: %(fastPolicyName)s."),
                {'fastPolicyName': targetFastPolicyName})
            return falseRet

        return True

    def _migrate_volume_from(self, volume, volumeInstance,
                             targetPoolName, sourceFastPolicyName,
                             extraSpecs):
        """Check FAST policies and migrate from source pool.

        :param volume: the volume object including the volume_type_id
        :param volumeInstance: the volume instance
        :param targetPoolName: the target poolName
        :param sourceFastPolicyName: the source FAST policy name, can be None
        :param extraSpecs: extra specifications
        :returns: boolean -- True/False
        :returns: int -- the return code from migrate operation
        """
        falseRet = (False, -1)
        volumeName = volume['name']
        storageSystemName = volumeInstance['SystemName']

        LOG.debug("sourceFastPolicyName is : %(sourceFastPolicyName)s.",
                  {'sourceFastPolicyName': sourceFastPolicyName})

        # If the source volume is FAST enabled it must first be removed
        # from the default storage group for that policy.
        if sourceFastPolicyName is not None:
            self.remove_from_default_SG(
                self.conn, volumeInstance, storageSystemName,
                sourceFastPolicyName, volumeName, extraSpecs)

        # Migrate from one pool to another.
        storageRelocationService = self.utils.find_storage_relocation_service(
            self.conn, storageSystemName)

        targetPoolInstanceName = self.utils.get_pool_by_name(
            self.conn, targetPoolName, storageSystemName)
        if targetPoolInstanceName is None:
            LOG.error(_LE(
                "Error finding target pool instance name for pool: "
                "%(targetPoolName)s."),
                {'targetPoolName': targetPoolName})
            return falseRet
        try:
            rc = self.provision.migrate_volume_to_storage_pool(
                self.conn, storageRelocationService, volumeInstance.path,
                targetPoolInstanceName, extraSpecs)
        except Exception:
            # Rollback by deleting the volume if adding the volume to the
            # default storage group were to fail.
            LOG.exception(_LE(
                "Error migrating volume: %(volumename)s. "
                "to target pool %(targetPoolName)s."),
                {'volumename': volumeName,
                 'targetPoolName': targetPoolName})
            return falseRet

        # Check that the volume is now migrated to the correct storage pool,
        # if it is terminate the migrate session.
        foundPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstance.path)

        if (foundPoolInstanceName is None or
                (foundPoolInstanceName['InstanceID'] !=
                    targetPoolInstanceName['InstanceID'])):
            LOG.error(_LE(
                "Volume : %(volumeName)s. was not successfully migrated to "
                "target pool %(targetPoolName)s."),
                {'volumeName': volumeName,
                 'targetPoolName': targetPoolName})
            return falseRet

        else:
            LOG.debug("Terminating migration session on: %(volumeName)s.",
                      {'volumeName': volumeName})
            self.provision._terminate_migrate_session(
                self.conn, volumeInstance.path, extraSpecs)

        if rc == 0:
            moved = True

        return moved, rc

    def remove_from_default_SG(
            self, conn, volumeInstance, storageSystemName,
            sourceFastPolicyName, volumeName, extraSpecs):
        """For FAST, remove volume from default storage group.

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name
        :param extraSpecs: extra specifications
        :raises: VolumeBackendAPIException
        """
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        try:
            defaultStorageGroupInstanceName = (
                self.masking.remove_device_from_default_storage_group(
                    conn, controllerConfigurationService,
                    volumeInstance.path, volumeName, sourceFastPolicyName,
                    extraSpecs))
        except Exception:
            exceptionMessage = (_(
                "Failed to remove: %(volumename)s. "
                "from the default storage group for "
                "FAST policy %(fastPolicyName)s.")
                % {'volumename': volumeName,
                   'fastPolicyName': sourceFastPolicyName})

            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if defaultStorageGroupInstanceName is None:
            LOG.warning(_LW(
                "The volume: %(volumename)s "
                "was not first part of the default storage "
                "group for FAST policy %(fastPolicyName)s."),
                {'volumename': volumeName,
                 'fastPolicyName': sourceFastPolicyName})

    def add_to_default_SG(
            self, conn, volumeInstance, storageSystemName,
            targetFastPolicyName, volumeName, extraSpecs):
        """For FAST, add volume to default storage group.

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param targetFastPolicyName: the target FAST policy name
        :param volumeName: the volume Name
        :param extraSpecs: extra specifications
        """
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        assocDefaultStorageGroupName = (
            self.fast
            .add_volume_to_default_storage_group_for_fast_policy(
                conn, controllerConfigurationService, volumeInstance,
                volumeName, targetFastPolicyName, extraSpecs))
        if assocDefaultStorageGroupName is None:
            LOG.error(_LE(
                "Failed to add %(volumeName)s "
                "to default storage group for fast policy "
                "%(fastPolicyName)s."),
                {'volumeName': volumeName,
                 'fastPolicyName': targetFastPolicyName})

    def _is_valid_for_storage_assisted_migration_v3(
            self, volumeInstanceName, host, sourceArraySerialNumber,
            sourcePoolName, volumeName, volumeStatus, sgName):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param volumeInstanceName: the volume instance id
        :param host: the host object
        :param sourceArraySerialNumber: the array serial number of
            the original volume
        :param sourcePoolName: the pool name of the original volume
        :param volumeName: the name of the volume to be migrated
        :param volumeStatus: the status of the volume
        :param sgName: storage group name
        :returns: boolean -- True/False
        :returns: string -- targetSlo
        :returns: string -- targetWorkload
        """
        falseRet = (False, None, None)
        if 'location_info' not in host['capabilities']:
            LOG.error(_LE('Error getting array, pool, SLO and workload.'))
            return falseRet
        info = host['capabilities']['location_info']

        LOG.debug("Location info is : %(info)s.",
                  {'info': info})
        try:
            infoDetail = info.split('#')
            targetArraySerialNumber = infoDetail[0]
            targetPoolName = infoDetail[1]
            targetSlo = infoDetail[2]
            targetWorkload = infoDetail[3]
        except KeyError:
            LOG.error(_LE("Error parsing array, pool, SLO and workload."))

        if targetArraySerialNumber not in sourceArraySerialNumber:
            LOG.error(_LE(
                "The source array : %(sourceArraySerialNumber)s does not "
                "match the target array: %(targetArraySerialNumber)s "
                "skipping storage-assisted migration."),
                {'sourceArraySerialNumber': sourceArraySerialNumber,
                 'targetArraySerialNumber': targetArraySerialNumber})
            return falseRet

        if targetPoolName not in sourcePoolName:
            LOG.error(_LE(
                "Only SLO/workload migration within the same SRP Pool "
                "is supported in this version "
                "The source pool : %(sourcePoolName)s does not "
                "match the target array: %(targetPoolName)s. "
                "Skipping storage-assisted migration."),
                {'sourcePoolName': sourcePoolName,
                 'targetPoolName': targetPoolName})
            return falseRet

        foundStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(
                self.conn, volumeInstanceName, sgName))
        if foundStorageGroupInstanceName is None:
            LOG.warning(_LW(
                "Volume: %(volumeName)s is not currently "
                "belonging to any storage group."),
                {'volumeName': volumeName})

        else:
            storageGroupInstance = self.conn.GetInstance(
                foundStorageGroupInstanceName)
            emcFastSetting = self.utils._get_fast_settings_from_storage_group(
                storageGroupInstance)
            targetCombination = ("%(targetSlo)s+%(targetWorkload)s"
                                 % {'targetSlo': targetSlo,
                                    'targetWorkload': targetWorkload})
            if targetCombination in emcFastSetting:
                LOG.error(_LE(
                    "No action required. Volume: %(volumeName)s is "
                    "already part of slo/workload combination: "
                    "%(targetCombination)s."),
                    {'volumeName': volumeName,
                     'targetCombination': targetCombination})
                return falseRet

        return (True, targetSlo, targetWorkload)

    def _is_valid_for_storage_assisted_migration(
            self, volumeInstanceName, host, sourceArraySerialNumber,
            volumeName, volumeStatus):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param volumeInstanceName: the volume instance id
        :param host: the host object
        :param sourceArraySerialNumber: the array serial number of
            the original volume
        :param volumeName: the name of the volume to be migrated
        :param volumeStatus: the status of the volume e.g
        :returns: boolean -- True/False
        :returns: string -- targetPool
        :returns: string -- targetFastPolicy
        """
        falseRet = (False, None, None)
        if 'location_info' not in host['capabilities']:
            LOG.error(_LE("Error getting target pool name and array."))
            return falseRet
        info = host['capabilities']['location_info']

        LOG.debug("Location info is : %(info)s.",
                  {'info': info})
        try:
            infoDetail = info.split('#')
            targetArraySerialNumber = infoDetail[0]
            targetPoolName = infoDetail[1]
            targetFastPolicy = infoDetail[2]
        except KeyError:
            LOG.error(_LE(
                "Error parsing target pool name, array, and fast policy."))

        if targetArraySerialNumber not in sourceArraySerialNumber:
            LOG.error(_LE(
                "The source array : %(sourceArraySerialNumber)s does not "
                "match the target array: %(targetArraySerialNumber)s, "
                "skipping storage-assisted migration."),
                {'sourceArraySerialNumber': sourceArraySerialNumber,
                 'targetArraySerialNumber': targetArraySerialNumber})
            return falseRet

        # Get the pool from the source array and check that is different
        # to the pool in the target array.
        assocPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstanceName)
        assocPoolInstance = self.conn.GetInstance(
            assocPoolInstanceName)
        if assocPoolInstance['ElementName'] == targetPoolName:
            LOG.error(_LE(
                "No action required. Volume: %(volumeName)s is "
                "already part of pool: %(pool)s."),
                {'volumeName': volumeName,
                 'pool': targetPoolName})
            return falseRet

        LOG.info(_LI("Volume status is: %s."), volumeStatus)
        if (host['capabilities']['storage_protocol'] != self.protocol and
                (volumeStatus != 'available' and volumeStatus != 'retyping')):
            LOG.error(_LE(
                "Only available volumes can be migrated between "
                "different protocols."))
            return falseRet

        return (True, targetPoolName, targetFastPolicy)

    def _set_config_file_and_get_extra_specs(self, volume, volumeTypeId=None):
        """Given the volume object get the associated volumetype.

        Given the volume object get the associated volumetype and the
        extra specs associated with it.
        Based on the name of the config group, register the config file

        :param volume: the volume object including the volume_type_id
        :param volumeTypeId: Optional override of volume['volume_type_id']
        :returns: dict -- the extra specs dict
        :returns: string -- configuration file
        """
        extraSpecs = self.utils.get_volumetype_extraspecs(volume, volumeTypeId)
        configGroup = None

        # If there are no extra specs then the default case is assumed.
        if extraSpecs:
            configGroup = self.configuration.config_group
        configurationFile = self._register_config_file_from_config_group(
            configGroup)

        return extraSpecs, configurationFile

    def _get_ecom_connection(self):
        """Get the ecom connection.

        :returns: pywbem.WBEMConnection -- conn, the ecom connection
        :raises: VolumeBackendAPIException
        """

        if self.ecomUseSSL:
            argspec = inspect.getargspec(pywbem.WBEMConnection.__init__)
            if any("ca_certs" in s for s in argspec.args):
                updatedPywbem = True
            else:
                updatedPywbem = False
            pywbem.cim_http.wbem_request = emc_vmax_https.wbem_request
            if updatedPywbem:
                conn = pywbem.WBEMConnection(
                    self.url,
                    (self.user, self.passwd),
                    default_namespace='root/emc',
                    x509={"key_file":
                          self.configuration.safe_get(
                              'driver_client_cert_key'),
                          "cert_file":
                          self.configuration.safe_get('driver_client_cert')},
                    ca_certs=self.ecomCACert,
                    no_verification=self.ecomNoVerification)
            else:
                conn = pywbem.WBEMConnection(
                    self.url,
                    (self.user, self.passwd),
                    default_namespace='root/emc',
                    x509={"key_file":
                          self.configuration.safe_get(
                              'driver_client_cert_key'),
                          "cert_file":
                          self.configuration.safe_get('driver_client_cert')})

        else:
            conn = pywbem.WBEMConnection(
                self.url,
                (self.user, self.passwd),
                default_namespace='root/emc')

        conn.debug = True
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server."))
            raise exception.VolumeBackendAPIException(data=exception_message)

        return conn

    def _find_pool_in_array(self, arrayStr, poolNameInStr, isV3):
        """Find a pool based on the pool name on a given array.

        :param arrayStr: the array Serial number (String)
        :param poolNameInStr: the name of the poolname (String)
        :param isv3: True/False
        :returns: foundPoolInstanceName - the CIM Instance Name of the Pool
        :returns: string -- systemNameStr
        :raises: VolumeBackendAPIException
        """
        foundPoolInstanceName = None
        systemNameStr = None

        storageSystemInstanceName = self.utils.find_storageSystem(
            self.conn, arrayStr)

        if isV3:
            foundPoolInstanceName, systemNameStr = (
                self.utils.get_pool_and_system_name_v3(
                    self.conn, storageSystemInstanceName, poolNameInStr))
        else:
            foundPoolInstanceName, systemNameStr = (
                self.utils.get_pool_and_system_name_v2(
                    self.conn, storageSystemInstanceName, poolNameInStr))

        if foundPoolInstanceName is None:
            exceptionMessage = (_("Pool %(poolNameInStr)s is not found.")
                                % {'poolNameInStr': poolNameInStr})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if systemNameStr is None:
            exception_message = (_("Storage system not found for pool "
                                   "%(poolNameInStr)s.")
                                 % {'poolNameInStr': poolNameInStr})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Pool: %(pool)s  SystemName: %(systemname)s.",
                  {'pool': foundPoolInstanceName,
                   'systemname': systemNameStr})
        return foundPoolInstanceName, systemNameStr

    def _find_lun(self, volume):
        """Given the volume get the instance from it.

        :param volume: volume object
        :returns: foundVolumeinstance
        """
        foundVolumeinstance = None
        volumename = volume['name']

        loc = volume['provider_location']
        if self.conn is None:
            self.conn = self._get_ecom_connection()

        if isinstance(loc, six.string_types):
            name = eval(loc)
            keys = name['keybindings']
            systemName = keys['SystemName']

            prefix1 = 'SYMMETRIX+'
            prefix2 = 'SYMMETRIX-+-'
            smiversion = self.utils.get_smi_version(self.conn)
            if smiversion > SMI_VERSION_8 and prefix1 in systemName:
                keys['SystemName'] = systemName.replace(prefix1, prefix2)
                name['keybindings'] = keys

            instancename = self.utils.get_instance_name(
                name['classname'], name['keybindings'])
            # Allow for an external app to delete the volume.
            LOG.debug("Volume instance name: %(in)s",
                      {'in': instancename})
            try:
                foundVolumeinstance = self.conn.GetInstance(instancename)
            except Exception:
                foundVolumeinstance = None

        if foundVolumeinstance is None:
            LOG.debug("Volume %(volumename)s not found on the array.",
                      {'volumename': volumename})
        else:
            LOG.debug("Volume name: %(volumename)s  Volume instance: "
                      "%(foundVolumeinstance)s.",
                      {'volumename': volumename,
                       'foundVolumeinstance': foundVolumeinstance})

        return foundVolumeinstance

    def _find_storage_sync_sv_sv(self, snapshot, volume, extraSpecs,
                                 waitforsync=True):
        """Find the storage synchronized name.

        :param snapshot: snapshot object
        :param volume: volume object
        :param extraSpecs: extra specifications
        :param waitforsync: boolean -- Wait for Solutions Enabler sync.
        :returns: string -- foundsyncname
        :returns: string -- storage_system
        """
        snapshotname = snapshot['name']
        volumename = volume['name']
        LOG.debug("Source: %(volumename)s  Target: %(snapshotname)s.",
                  {'volumename': volumename, 'snapshotname': snapshotname})

        snapshot_instance = self._find_lun(snapshot)
        volume_instance = self._find_lun(volume)
        storage_system = volume_instance['SystemName']
        classname = 'SE_StorageSynchronized_SV_SV'
        bindings = {'SyncedElement': snapshot_instance.path,
                    'SystemElement': volume_instance.path}
        foundsyncname = self.utils.get_instance_name(classname, bindings)

        if foundsyncname is None:
            LOG.debug(
                "Source: %(volumename)s  Target: %(snapshotname)s. "
                "Storage Synchronized not found.",
                {'volumename': volumename,
                 'snapshotname': snapshotname})
        else:
            LOG.debug("Storage system: %(storage_system)s. "
                      "Storage Synchronized instance: %(sync)s.",
                      {'storage_system': storage_system,
                       'sync': foundsyncname})
            # Wait for SE_StorageSynchronized_SV_SV to be fully synced.
            if waitforsync:
                self.utils.wait_for_sync(self.conn, foundsyncname,
                                         extraSpecs)

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
            msg = (_("Error finding %s.") % name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Found %(name)s: %(initiator)s.",
                  {'name': name,
                   'initiator': foundinitiatornames})
        return foundinitiatornames

    def find_device_number(self, volume, host):
        """Given the volume dict find a device number.

        Find a device number that a host can see
        for a volume.

        :param volume: the volume dict
        :param host: host from connector
        :returns: dict -- the data dict
        """
        maskedvols = []
        data = {}
        foundNumDeviceNumber = None
        foundMaskingViewName = None
        volumeName = volume['name']
        volumeInstance = self._find_lun(volume)
        storageSystemName = volumeInstance['SystemName']

        unitnames = self.conn.ReferenceNames(
            volumeInstance.path,
            ResultClass='CIM_ProtocolControllerForUnit')

        for unitname in unitnames:
            controller = unitname['Antecedent']
            classname = controller['CreationClassName']
            index = classname.find('Symm_LunMaskingView')
            if index > -1:
                unitinstance = self.conn.GetInstance(unitname,
                                                     LocalOnly=False)
                numDeviceNumber = int(unitinstance['DeviceNumber'],
                                      16)
                foundNumDeviceNumber = numDeviceNumber
                controllerInstance = self.conn.GetInstance(controller,
                                                           LocalOnly=False)
                propertiesList = controllerInstance.properties.items()
                for properties in propertiesList:
                    if properties[0] == 'ElementName':
                        cimProperties = properties[1]
                        foundMaskingViewName = cimProperties.value

                devicedict = {'hostlunid': foundNumDeviceNumber,
                              'storagesystem': storageSystemName,
                              'maskingview': foundMaskingViewName}
                maskedvols.append(devicedict)

        if not maskedvols:
            LOG.debug(
                "Device number not found for volume "
                "%(volumeName)s %(volumeInstance)s.",
                {'volumeName': volumeName,
                 'volumeInstance': volumeInstance.path})
        else:
            hoststr = ("-%(host)s-"
                       % {'host': host})

            for maskedvol in maskedvols:
                if hoststr.lower() in maskedvol['maskingview'].lower():
                    data = maskedvol
                    break
            if not data:
                LOG.warning(_LW(
                    "Volume is masked but not to host %(host)s as "
                    "expected. Returning empty dictionary."),
                    {'host': hoststr})

        LOG.debug("Device info: %(data)s.", {'data': data})
        return data

    def get_target_wwns(self, storageSystem, connector):
        """Find target WWNs.

        :param storageSystem: the storage system name
        :param connector: the connector dict
        :returns: list -- targetWwns, the target WWN list
        :raises: VolumeBackendAPIException
        """
        targetWwns = []

        storageHardwareService = self.utils.find_storage_hardwareid_service(
            self.conn, storageSystem)

        hardwareIdInstances = self._find_storage_hardwareids(
            connector, storageHardwareService)

        LOG.debug(
            "EMCGetTargetEndpoints: Service: %(service)s, "
            "Storage HardwareIDs: %(hardwareIds)s.",
            {'service': storageHardwareService,
             'hardwareIds': hardwareIdInstances})

        for hardwareIdInstance in hardwareIdInstances:
            LOG.debug("HardwareID instance is: %(hardwareIdInstance)s.",
                      {'hardwareIdInstance': hardwareIdInstance})
            try:
                _rc, targetEndpoints = (
                    self.provision.get_target_endpoints(
                        self.conn, storageHardwareService, hardwareIdInstance))
            except Exception:
                errorMessage = (_(
                    "Unable to get target endpoints for hardwareId "
                    "%(hardwareIdInstance)s.")
                    % {'hardwareIdInstance': hardwareIdInstance})
                LOG.exception(errorMessage)
                raise exception.VolumeBackendAPIException(data=errorMessage)

            if targetEndpoints:
                endpoints = targetEndpoints['TargetEndpoints']

                LOG.debug("There are %(len)lu endpoints.",
                          {'len': len(endpoints)})
                for targetendpoint in endpoints:
                    wwn = targetendpoint['Name']
                    # Add target wwn to the list if it is not already there.
                    if not any(d == wwn for d in targetWwns):
                        targetWwns.append(wwn)
            else:
                LOG.error(_LE(
                    "Target end points do not exist for hardware Id: "
                    "%(hardwareIdInstance)s."),
                    {'hardwareIdInstance': hardwareIdInstance})

        LOG.debug("Target WWNs: %(targetWwns)s.",
                  {'targetWwns': targetWwns})

        return targetWwns

    def _find_storage_hardwareids(
            self, connector, hardwareIdManagementService):
        """Find the storage hardware ID instances.

        :param connector: the connector dict
        :param hardwareIdManagementService: the storage Hardware
            management service
        :returns: list -- the list of storage hardware ID instances
        """
        foundHardwareIdList = []
        wwpns = self._find_initiator_names(connector)

        hardwareIdInstances = (
            self.utils.get_hardware_id_instances_from_array(
                self.conn, hardwareIdManagementService))
        for hardwareIdInstance in hardwareIdInstances:
            storageId = hardwareIdInstance['StorageID']
            for wwpn in wwpns:
                if wwpn.lower() == storageId.lower():
                    # Check that the found hardwareId has not been
                    # deleted. If it has, we don't want to add it to the list.
                    instance = self.utils.get_existing_instance(
                        self.conn, hardwareIdInstance.path)
                    if instance is None:
                        # HardwareId doesn't exist any more. Skip it.
                        break
                    foundHardwareIdList.append(hardwareIdInstance.path)
                    break

        LOG.debug("Storage Hardware IDs for %(wwpns)s is "
                  "%(foundInstances)s.",
                  {'wwpns': wwpns,
                   'foundInstances': foundHardwareIdList})

        return foundHardwareIdList

    def _register_config_file_from_config_group(self, configGroupName):
        """Given the config group name register the file.

        :param configGroupName: the config group name
        :returns: string -- configurationFile - name of the configuration file
        """
        if configGroupName is None:
            return CINDER_EMC_CONFIG_FILE
        if hasattr(self.configuration, 'cinder_emc_config_file'):
            configurationFile = self.configuration.cinder_emc_config_file
        else:
            configurationFile = (
                ("%(prefix)s%(configGroupName)s%(postfix)s"
                 % {'prefix': CINDER_EMC_CONFIG_FILE_PREFIX,
                    'configGroupName': configGroupName,
                    'postfix': CINDER_EMC_CONFIG_FILE_POSTFIX}))

        # The file saved in self.configuration may not be the correct one,
        # double check.
        if configGroupName not in configurationFile:
            configurationFile = (
                ("%(prefix)s%(configGroupName)s%(postfix)s"
                 % {'prefix': CINDER_EMC_CONFIG_FILE_PREFIX,
                    'configGroupName': configGroupName,
                    'postfix': CINDER_EMC_CONFIG_FILE_POSTFIX}))

        if os.path.isfile(configurationFile):
            LOG.debug("Configuration file : %(configurationFile)s exists.",
                      {'configurationFile': configurationFile})
        else:
            exceptionMessage = (_(
                "Configuration file %(configurationFile)s does not exist.")
                % {'configurationFile': configurationFile})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return configurationFile

    def _set_ecom_credentials(self, arrayInfo):
        """Given the array record set the ecom credentials.

        :param arrayInfo: record
        :raises: VolumeBackendAPIException
        """
        ip = arrayInfo['EcomServerIp']
        port = arrayInfo['EcomServerPort']
        self.user = arrayInfo['EcomUserName']
        self.passwd = arrayInfo['EcomPassword']
        self.ecomUseSSL = arrayInfo['EcomUseSSL']
        self.ecomCACert = arrayInfo['EcomCACert']
        self.ecomNoVerification = arrayInfo['EcomNoVerification']
        ip_port = ("%(ip)s:%(port)s"
                   % {'ip': ip,
                      'port': port})
        if self.ecomUseSSL:
            self.url = ("https://%(ip_port)s"
                        % {'ip_port': ip_port})
        else:
            self.url = ("http://%(ip_port)s"
                        % {'ip_port': ip_port})
        self.conn = self._get_ecom_connection()

    def _initial_setup(self, volume, volumeTypeId=None):
        """Necessary setup to accumulate the relevant information.

        The volume object has a host in which we can parse the
        config group name. The config group name is the key to our EMC
        configuration file. The emc configuration file contains pool name
        and array name which are mandatory fields.
        FastPolicy is optional.
        StripedMetaCount is an extra spec that determines whether
        the composite volume should be concatenated or striped.

        :param volume: the volume Object
        :param volumeTypeId: Optional override of volume['volume_type_id']
        :returns: dict -- extra spec dict
        :raises: VolumeBackendAPIException
        """
        try:
            extraSpecs, configurationFile = (
                self._set_config_file_and_get_extra_specs(
                    volume, volumeTypeId))

            pool = self._validate_pool(volume)
            LOG.debug("Pool returned is %(pool)s.",
                      {'pool': pool})
            arrayInfo = self.utils.parse_file_to_get_array_map(
                configurationFile)
            poolRecord = self.utils.extract_record(arrayInfo, pool)

            if not poolRecord:
                exceptionMessage = (_(
                    "Unable to get corresponding record for pool."))
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            self._set_ecom_credentials(poolRecord)
            isV3 = self.utils.isArrayV3(
                self.conn, poolRecord['SerialNumber'])

            if isV3:
                extraSpecs = self._set_v3_extra_specs(extraSpecs, poolRecord)
            else:
                # V2 extra specs
                extraSpecs = self._set_v2_extra_specs(extraSpecs, poolRecord)
        except Exception:
            import sys
            exceptionMessage = (_(
                "Unable to get configuration information necessary to "
                "create a volume: %(errorMessage)s.")
                % {'errorMessage': sys.exc_info()[1]})
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return extraSpecs

    def _get_pool_and_storage_system(self, extraSpecs):
        """Given the extra specs get the pool and storage system name.

        :param extraSpecs: extra specifications
        :returns: poolInstanceName The pool instance name
        :returns: string -- the storage system name
        :raises: VolumeBackendAPIException
        """

        try:
            array = extraSpecs[ARRAY]
            poolInstanceName, storageSystemStr = self._find_pool_in_array(
                array, extraSpecs[POOL], extraSpecs[ISV3])
        except Exception:
            exceptionMessage = (_(
                "You must supply an array in your EMC configuration file."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if poolInstanceName is None or storageSystemStr is None:
            exceptionMessage = (_(
                "Cannot get necessary pool or storage system information."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return poolInstanceName, storageSystemStr

    def _populate_masking_dict(self, volume, connector, extraSpecs):
        """Get all the names of the maskingView and subComponents.

        :param volume: the volume object
        :param connector: the connector object
        :param extraSpecs: extra specifications
        :returns: dict -- a dictionary with masking view information
        """
        maskingViewDict = {}
        hostName = connector['host']
        uniqueName = self.utils.generate_unique_trunc_pool(extraSpecs[POOL])
        isV3 = extraSpecs[ISV3]
        maskingViewDict['isV3'] = isV3
        protocol = self.utils.get_short_protocol_type(self.protocol)
        shortHostName = self.utils.get_host_short_name(hostName)
        if isV3:
            slo = extraSpecs[SLO]
            workload = extraSpecs[WORKLOAD]
            maskingViewDict['slo'] = slo
            maskingViewDict['workload'] = workload
            maskingViewDict['pool'] = uniqueName
            prefix = (
                ("OS-%(shortHostName)s-%(poolName)s-%(slo)s-%(workload)s"
                 % {'shortHostName': shortHostName,
                    'poolName': uniqueName,
                    'slo': slo,
                    'workload': workload}))
        else:
            prefix = (
                ("OS-%(shortHostName)s-%(poolName)s-%(protocol)s"
                 % {'shortHostName': shortHostName,
                    'poolName': uniqueName,
                    'protocol': protocol}))
            maskingViewDict['fastPolicy'] = extraSpecs[FASTPOLICY]

        maskingViewDict['sgGroupName'] = ("%(prefix)s-SG"
                                          % {'prefix': prefix})

        maskingViewDict['maskingViewName'] = ("%(prefix)s-MV"
                                              % {'prefix': prefix})
        volumeName = volume['name']
        volumeInstance = self._find_lun(volume)
        storageSystemName = volumeInstance['SystemName']

        maskingViewDict['controllerConfigService'] = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))
        # The portGroup is gotten from emc xml config file.
        maskingViewDict['pgGroupName'] = extraSpecs[PORTGROUPNAME]

        maskingViewDict['igGroupName'] = (
            ("OS-%(shortHostName)s-%(protocol)s-IG"
             % {'shortHostName': shortHostName,
                'protocol': protocol}))
        maskingViewDict['connector'] = connector
        maskingViewDict['volumeInstance'] = volumeInstance
        maskingViewDict['volumeName'] = volumeName
        maskingViewDict['storageSystemName'] = storageSystemName

        return maskingViewDict

    def _add_volume_to_default_storage_group_on_create(
            self, volumeDict, volumeName, storageConfigService,
            storageSystemName, fastPolicyName, extraSpecs):
        """Add the volume to the default storage group for that policy.

        On a create when fast policy is enable add the volume to the default
        storage group for that policy. If it fails do the necessary rollback.

        :param volumeDict: the volume dictionary
        :param volumeName: the volume name (String)
        :param storageConfigService: the storage configuration service
        :param storageSystemName: the storage system name (String)
        :param fastPolicyName: the fast policy name (String)
        :param extraSpecs: extra specifications
        :returns: dict -- maskingViewDict with masking view information
        :raises: VolumeBackendAPIException
        """
        try:
            volumeInstance = self.utils.find_volume_instance(
                self.conn, volumeDict, volumeName)
            controllerConfigurationService = (
                self.utils.find_controller_configuration_service(
                    self.conn, storageSystemName))
            defaultSgName = self.fast.format_default_sg_string(fastPolicyName)

            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                self.conn, controllerConfigurationService, volumeInstance,
                volumeName, fastPolicyName, extraSpecs)
            foundStorageGroupInstanceName = (
                self.utils.get_storage_group_from_volume(
                    self.conn, volumeInstance.path, defaultSgName))

            if foundStorageGroupInstanceName is None:
                exceptionMessage = (_(
                    "Error adding Volume: %(volumeName)s "
                    "with instance path: %(volumeInstancePath)s.")
                    % {'volumeName': volumeName,
                       'volumeInstancePath': volumeInstance.path})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        except Exception:
            # Rollback by deleting the volume if adding the volume to the
            # default storage group were to fail.
            errorMessage = (_(
                "Rolling back %(volumeName)s by deleting it.")
                % {'volumeName': volumeName})
            LOG.exception(errorMessage)
            self.provision.delete_volume_from_pool(
                self.conn, storageConfigService, volumeInstance.path,
                volumeName, extraSpecs)
            raise exception.VolumeBackendAPIException(data=errorMessage)

    def _create_and_get_unbound_volume(
            self, conn, storageConfigService, compositeVolumeInstanceName,
            additionalSize, extraSpecs):
        """Create an unbound volume.

        Create an unbound volume so it is in the correct state to add to a
        composite volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage config service instance name
        :param compositeVolumeInstanceName: the composite volume instance name
        :param additionalSize: the size you want to increase the volume by
        :param extraSpecs: extra specifications
        :returns: volume instance modifiedCompositeVolumeInstance
        """
        assocPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            conn, compositeVolumeInstanceName)
        appendVolumeInstance = self._create_and_get_volume_instance(
            conn, storageConfigService, assocPoolInstanceName, 'appendVolume',
            additionalSize, extraSpecs)
        isVolumeBound = self.utils.is_volume_bound_to_pool(
            conn, appendVolumeInstance)

        if 'True' in isVolumeBound:
            appendVolumeInstance = (
                self._unbind_and_get_volume_from_storage_pool(
                    conn, storageConfigService,
                    appendVolumeInstance.path, 'appendVolume', extraSpecs))

        return appendVolumeInstance

    def _create_and_get_volume_instance(
            self, conn, storageConfigService, poolInstanceName,
            volumeName, volumeSize, extraSpecs):
        """Create and get a new volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage config service instance name
        :param poolInstanceName: the pool instance name
        :param volumeName: the volume name
        :param volumeSize: the size to create the volume
        :param extraSpecs: extra specifications
        :returns: volumeInstance -- the volume instance
        """
        volumeDict, _rc = (
            self.provision.create_volume_from_pool(
                self.conn, storageConfigService, volumeName, poolInstanceName,
                volumeSize, extraSpecs))
        volumeInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, volumeName)
        return volumeInstance

    def _unbind_and_get_volume_from_storage_pool(
            self, conn, storageConfigService,
            volumeInstanceName, volumeName, extraSpecs):
        """Unbind a volume from a pool and return the unbound volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage config service instance name
        :param volumeInstanceName: the volume instance name
        :param volumeName: string the volumeName
        :param extraSpecs: extra specifications
        :returns: unboundVolumeInstance -- the unbound volume instance
        """
        _rc, _job = (
            self.provision.unbind_volume_from_storage_pool(
                conn, storageConfigService, volumeInstanceName,
                volumeName, extraSpecs))
        # Check that the volume in unbound
        volumeInstance = conn.GetInstance(volumeInstanceName)
        isVolumeBound = self.utils.is_volume_bound_to_pool(
            conn, volumeInstance)
        if 'False' not in isVolumeBound:
            exceptionMessage = (_(
                "Failed to unbind volume %(volume)s")
                % {'volume': volumeInstanceName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return volumeInstance

    def _modify_and_get_composite_volume_instance(
            self, conn, elementCompositionServiceInstanceName, volumeInstance,
            appendVolumeInstanceName, volumeName, compositeType, extraSpecs):
        """Given an existing composite volume add a new composite volume to it.

        :param conn: the connection information to the ecom server
        :param elementCompositionServiceInstanceName: the storage element
            composition service instance name
        :param volumeInstance: the volume instance
        :param appendVolumeInstanceName: the appended volume instance name
        :param volumeName: the volume name
        :param compositeType: concatenated
        :param extraSpecs: extra specifications
        :returns: int -- the return code
        :returns: dict -- modifiedVolumeDict - the modified volume dict
        """
        isComposite = self.utils.check_if_volume_is_composite(
            self.conn, volumeInstance)
        if 'True' in isComposite:
            rc, job = self.provision.modify_composite_volume(
                conn, elementCompositionServiceInstanceName,
                volumeInstance.path, appendVolumeInstanceName, extraSpecs)
        elif 'False' in isComposite:
            rc, job = self.provision.create_new_composite_volume(
                conn, elementCompositionServiceInstanceName,
                volumeInstance.path, appendVolumeInstanceName, compositeType,
                extraSpecs)
        else:
            LOG.error(_LE(
                "Unable to determine whether %(volumeName)s is "
                "composite or not."),
                {'volumeName': volumeName})
            raise

        modifiedVolumeDict = self.provision.get_volume_dict_from_job(
            conn, job['Job'])

        return rc, modifiedVolumeDict

    def _get_or_create_default_storage_group(
            self, conn, storageSystemName, volumeDict, volumeName,
            fastPolicyName, extraSpecs):
        """Get or create a default storage group for a fast policy.

        :param conn: the connection information to the ecom server
        :param storageSystemName: the storage system name
        :param volumeDict: the volume dictionary
        :param volumeName: the volume name
        :param fastPolicyName: the fast policy name
        :param extraSpecs: extra specifications
        :returns: defaultStorageGroupInstanceName
        """
        controllerConfigService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        volumeInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, volumeName)
        defaultStorageGroupInstanceName = (
            self.fast.get_or_create_default_storage_group(
                self.conn, controllerConfigService, fastPolicyName,
                volumeInstance, extraSpecs))
        return defaultStorageGroupInstanceName

    def _create_cloned_volume(
            self, cloneVolume, sourceVolume, extraSpecs, isSnapshot=False):
        """Create a clone volume from the source volume.

        :param cloneVolume: clone volume
        :param sourceVolume: source of the clone volume
        :param extraSpecs: extra specs
        :param isSnapshot: boolean -- Defaults to False
        :returns: dict -- cloneDict the cloned volume dictionary
        :raises: VolumeBackendAPIException
        """
        sourceName = sourceVolume['name']
        cloneName = cloneVolume['name']

        LOG.info(_LI(
            "Create a replica from Volume: Clone Volume: %(cloneName)s "
            "Source Volume: %(sourceName)s."),
            {'cloneName': cloneName,
             'sourceName': sourceName})

        self.conn = self._get_ecom_connection()

        sourceInstance = self._find_lun(sourceVolume)
        storageSystem = sourceInstance['SystemName']
        repServCapabilityInstanceName = (
            self.utils.find_replication_service_capabilities(self.conn,
                                                             storageSystem))
        is_clone_license = self.utils.is_clone_licensed(
            self.conn, repServCapabilityInstanceName)

        if is_clone_license is False:
            exceptionMessage = (_(
                "Clone feature is not licensed on %(storageSystem)s.")
                % {'storageSystem': storageSystem})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        repServiceInstanceName = self.utils.find_replication_service(
            self.conn, storageSystem)

        LOG.debug("Create volume replica: Volume: %(cloneName)s "
                  "Source Volume: %(sourceName)s "
                  "Method: CreateElementReplica "
                  "ReplicationService: %(service)s  ElementName: "
                  "%(elementname)s  SyncType: 8  SourceElement: "
                  "%(sourceelement)s.",
                  {'cloneName': cloneName,
                   'sourceName': sourceName,
                   'service': repServiceInstanceName,
                   'elementname': cloneName,
                   'sourceelement': sourceInstance.path})

        if extraSpecs[ISV3]:
            rc, cloneDict = self._create_replica_v3(repServiceInstanceName,
                                                    cloneVolume,
                                                    sourceVolume,
                                                    sourceInstance,
                                                    isSnapshot,
                                                    extraSpecs)
        else:
            rc, cloneDict = self._create_clone_v2(repServiceInstanceName,
                                                  cloneVolume,
                                                  sourceVolume,
                                                  sourceInstance,
                                                  isSnapshot,
                                                  extraSpecs)
        LOG.debug("Leaving _create_cloned_volume: Volume: "
                  "%(cloneName)s Source Volume: %(sourceName)s "
                  "Return code: %(rc)lu.",
                  {'cloneName': cloneName,
                   'sourceName': sourceName,
                   'rc': rc})
        # Adding version information
        cloneDict['version'] = self.version

        return cloneDict

    def _add_clone_to_default_storage_group(
            self, fastPolicyName, storageSystemName, cloneDict, cloneName,
            extraSpecs):
        """Helper function to add clone to the default storage group.

        :param fastPolicyName: the fast policy name
        :param storageSystemName: the storage system name
        :param cloneDict: clone dictionary
        :param cloneName: clone name
        :param extraSpecs: extra specifications
        :raises: VolumeBackendAPIException
        """
        # Check if the clone/snapshot volume already part of the default sg.
        cloneInstance = self.utils.find_volume_instance(
            self.conn, cloneDict, cloneName)
        if self.fast.is_volume_in_default_SG(self.conn, cloneInstance.path):
            return

        # If FAST enabled place clone volume or volume from snapshot to
        # default storage group.
        LOG.debug("Adding volume: %(cloneName)s to default storage group "
                  "for FAST policy: %(fastPolicyName)s.",
                  {'cloneName': cloneName,
                   'fastPolicyName': fastPolicyName})

        storageConfigService = (
            self.utils.find_storage_configuration_service(
                self.conn, storageSystemName))

        defaultStorageGroupInstanceName = (
            self._get_or_create_default_storage_group(
                self.conn, storageSystemName, cloneDict, cloneName,
                fastPolicyName, extraSpecs))
        if defaultStorageGroupInstanceName is None:
            exceptionMessage = (_(
                "Unable to create or get default storage group for FAST "
                "policy: %(fastPolicyName)s.")
                % {'fastPolicyName': fastPolicyName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        self._add_volume_to_default_storage_group_on_create(
            cloneDict, cloneName, storageConfigService, storageSystemName,
            fastPolicyName, extraSpecs)

    def _delete_volume(self, volume):
        """Helper function to delete the specified volume.

        :param volume: volume object to be deleted
        :returns: tuple -- rc (int return code), volumeName (string vol name)
        """

        volumeName = volume['name']
        rc = -1
        errorRet = (rc, volumeName)

        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            LOG.error(_LE(
                "Volume %(name)s not found on the array. "
                "No volume to delete."),
                {'name': volumeName})
            return errorRet

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, volumeInstance['SystemName'])

        deviceId = volumeInstance['DeviceID']

        if extraSpecs[ISV3]:
            storageGroupName = self.utils.get_v3_storage_group_name(
                extraSpecs[POOL], extraSpecs[SLO],
                extraSpecs[WORKLOAD])
            rc = self._delete_from_pool_v3(
                storageConfigService, volumeInstance, volumeName,
                deviceId, storageGroupName, extraSpecs)
        else:
            rc = self._delete_from_pool(storageConfigService, volumeInstance,
                                        volumeName, deviceId,
                                        extraSpecs[FASTPOLICY],
                                        extraSpecs)
        return (rc, volumeName)

    def _remove_device_from_storage_group(
            self, controllerConfigurationService, volumeInstanceName,
            volumeName, extraSpecs):
        """Check if volume is part of a storage group prior to delete.

        Log a warning if volume is part of storage group.

        :param controllerConfigurationService: controller configuration service
        :param volumeInstanceName: volume instance name
        :param volumeName: volume name (string)
        :param extraSpecs: extra specifications
        """
        storageGroupInstanceNames = (
            self.masking.get_associated_masking_groups_from_device(
                self.conn, volumeInstanceName))
        if storageGroupInstanceNames:
            LOG.warning(_LW(
                "Pre check for deletion. "
                "Volume: %(volumeName)s is part of a storage group. "
                "Attempting removal from %(storageGroupInstanceNames)s."),
                {'volumeName': volumeName,
                 'storageGroupInstanceNames': storageGroupInstanceNames})
            for storageGroupInstanceName in storageGroupInstanceNames:
                self.provision.remove_device_from_storage_group(
                    self.conn, controllerConfigurationService,
                    storageGroupInstanceName,
                    volumeInstanceName, volumeName, extraSpecs)

    def _find_lunmasking_scsi_protocol_controller(self, storageSystemName,
                                                  connector):
        """Find LunMaskingSCSIProtocolController for the local host.

        Find out how many volumes are mapped to a host
        associated to the LunMaskingSCSIProtocolController.

        :param storageSystemName: the storage system name
        :param connector: volume object to be deleted
        :returns: foundControllerInstanceName
        """

        foundControllerInstanceName = None
        initiators = self._find_initiator_names(connector)

        storageSystemInstanceName = self.utils.find_storageSystem(
            self.conn, storageSystemName)
        controllerInstanceNames = self.conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='EMC_LunMaskingSCSIProtocolController')

        for controllerInstanceName in controllerInstanceNames:
            try:
                # This is a check to see if the controller has
                # been deleted.
                self.conn.GetInstance(controllerInstanceName)
                storageHardwareIdInstances = self.conn.Associators(
                    controllerInstanceName,
                    ResultClass='EMC_StorageHardwareID')
                for storageHardwareIdInstance in storageHardwareIdInstances:
                    # If EMC_StorageHardwareID matches the initiator, we
                    # found the existing EMC_LunMaskingSCSIProtocolController.
                    hardwareid = storageHardwareIdInstance['StorageID']
                    for initiator in initiators:
                        if hardwareid.lower() == initiator.lower():
                            # This is a check to see if the controller
                            # has been deleted.
                            instance = self.utils.get_existing_instance(
                                self.conn, controllerInstanceName)
                            if instance is None:
                                # Skip this controller as it doesn't exist
                                # any more.
                                pass
                            else:
                                foundControllerInstanceName = (
                                    controllerInstanceName)
                            break

                if foundControllerInstanceName is not None:
                    break
            except pywbem.cim_operations.CIMError as arg:
                instance = self.utils.process_exception_args(
                    arg, controllerInstanceName)
                if instance is None:
                    # Skip this controller as it doesn't exist any more.
                    pass

            if foundControllerInstanceName is not None:
                break

        LOG.debug("LunMaskingSCSIProtocolController for storage system "
                  "%(storage_system)s and initiator %(initiator)s is "
                  "%(ctrl)s.",
                  {'storage_system': storageSystemName,
                   'initiator': initiators,
                   'ctrl': foundControllerInstanceName})
        return foundControllerInstanceName

    def get_num_volumes_mapped(self, volume, connector):
        """Returns how many volumes are in the same zone as the connector.

        Find out how many volumes are mapped to a host
        associated to the LunMaskingSCSIProtocolController.

        :param volume: volume object to be deleted
        :param connector: volume object to be deleted
        :returns: int -- numVolumesMapped
        :raises: VolumeBackendAPIException
        """

        volumename = volume['name']
        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            msg = (_("Volume %(name)s not found on the array. "
                     "Cannot determine if there are volumes mapped.")
                   % {'name': volumename})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        storage_system = vol_instance['SystemName']

        ctrl = self._find_lunmasking_scsi_protocol_controller(
            storage_system,
            connector)

        LOG.debug("LunMaskingSCSIProtocolController for storage system "
                  "%(storage)s and %(connector)s is %(ctrl)s.",
                  {'storage': storage_system,
                   'connector': connector,
                   'ctrl': ctrl})

        # Return 0 if masking view does not exist.
        if ctrl is None:
            return 0

        associators = self.conn.Associators(
            ctrl,
            ResultClass='EMC_StorageVolume')

        numVolumesMapped = len(associators)

        LOG.debug("Found %(numVolumesMapped)d volumes on storage system "
                  "%(storage)s mapped to %(connector)s.",
                  {'numVolumesMapped': numVolumesMapped,
                   'storage': storage_system,
                   'connector': connector})

        return numVolumesMapped

    def _delete_snapshot(self, snapshot):
        """Helper function to delete the specified snapshot.

        :param snapshot: snapshot object to be deleted
        :raises: VolumeBackendAPIException
        """
        LOG.debug("Entering delete_snapshot.")

        snapshotname = snapshot['name']
        LOG.info(_LI("Delete Snapshot: %(snapshot)s."),
                 {'snapshot': snapshotname})

        extraSpecs = self._initial_setup(snapshot)
        self.conn = self._get_ecom_connection()

        if not extraSpecs[ISV3]:
            snapshotInstance = self._find_lun(snapshot)
            storageSystem = snapshotInstance['SystemName']

            # Wait for it to fully sync in case there is an ongoing
            # create volume from snapshot request.
            syncName = self.utils.find_sync_sv_by_target(
                self.conn, storageSystem, snapshotInstance, extraSpecs,
                True)

            if syncName is None:
                LOG.info(_LI(
                    "Snapshot: %(snapshot)s: not found on the array."),
                    {'snapshot': snapshotname})
            else:
                repservice = self.utils.find_replication_service(self.conn,
                                                                 storageSystem)
                if repservice is None:
                    exception_message = _(
                        "Cannot find Replication Service to"
                        " delete snapshot %s.") % snapshotname
                    raise exception.VolumeBackendAPIException(
                        data=exception_message)
                # Break the replication relationship
                LOG.debug("Deleting snap relationship: Target: %(snapshot)s "
                          "Method: ModifyReplicaSynchronization "
                          "Replication Service: %(service)s  Operation: 8  "
                          "Synchronization: %(syncName)s.",
                          {'snapshot': snapshotname,
                           'service': repservice,
                           'syncName': syncName})

                self.provision.delete_clone_relationship(
                    self.conn, repservice, syncName, extraSpecs, True)

        # Delete the target device.
        self._delete_volume(snapshot)

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        :param context: the context
        :param group: the group object to be created
        :returns: dict -- modelUpdate = {'status': 'available'}
        :raises: VolumeBackendAPIException
        """
        LOG.info(_LI("Create Consistency Group: %(group)s."),
                 {'group': group['id']})

        modelUpdate = {'status': 'available'}
        volumeTypeId = group['volume_type_id'].replace(",", "")

        cgName = self.utils.truncate_string(group['id'], 8)

        extraSpecs = self._initial_setup(None, volumeTypeId)

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))

        self.conn = self._get_ecom_connection()

        # Find storage system.
        try:
            replicationService = self.utils.find_replication_service(
                self.conn, storageSystem)
            self.provision.create_consistency_group(
                self.conn, replicationService, cgName, extraSpecs)
        except Exception:
            exceptionMessage = (_("Failed to create consistency group:"
                                  " %(cgName)s.")
                                % {'cgName': cgName})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return modelUpdate

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group.

        :param context: the context
        :param group: the group object to be deleted
        :param volumes: the list of volumes in the consisgroup to be deleted
        :returns: dict -- modelUpdate
        :returns: list -- list of volume objects
        :raises: VolumeBackendAPIException
        """
        LOG.info(_LI("Delete Consistency Group: %(group)s."),
                 {'group': group['id']})

        cgName = self.utils.truncate_string(group['id'], 8)

        modelUpdate = {}
        modelUpdate['status'] = group['status']
        volumeTypeId = group['volume_type_id'].replace(",", "")

        extraSpecs = self._initial_setup(None, volumeTypeId)

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))

        try:
            replicationService = self.utils.find_replication_service(
                self.conn, storageSystem)

            storageConfigservice = (
                self.utils.find_storage_configuration_service(
                    self.conn, storageSystem))
            cgInstanceName = self._find_consistency_group(
                replicationService, cgName)
            if cgInstanceName is None:
                exception_message = (_("Cannot find CG group %s.") %
                                     cgName)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            memberInstanceNames = self._get_members_of_replication_group(
                cgInstanceName)

            self.provision.delete_consistency_group(self.conn,
                                                    replicationService,
                                                    cgInstanceName, cgName,
                                                    extraSpecs)

            # Do a bulk delete, a lot faster than single deletes.
            if memberInstanceNames:
                volumes, modelUpdate = self._do_bulk_delete(
                    storageSystem, memberInstanceNames, storageConfigservice,
                    volumes, modelUpdate, extraSpecs[ISV3], extraSpecs)

        except Exception:
            exceptionMessage = (_(
                "Failed to delete consistency group: %(cgName)s.")
                % {'cgName': cgName})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return modelUpdate, volumes

    def _do_bulk_delete(self, storageSystem, memberInstanceNames,
                        storageConfigservice, volumes, modelUpdate, isV3,
                        extraSpecs):
        """Do a bulk delete.

        :param storageSystem: storage system name
        :param memberInstanceNames: volume Instance names
        :param storageConfigservice: storage config service
        :param volumes: volume objects
        :param modelUpdate: dict
        :param isV3: boolean
        :param extraSpecs: extra specifications
        :returns: list -- list of volume objects
        :returns: dict -- modelUpdate
        """
        try:
            controllerConfigurationService = (
                self.utils.find_controller_configuration_service(
                    self.conn, storageSystem))
            for memberInstanceName in memberInstanceNames:
                self._remove_device_from_storage_group(
                    controllerConfigurationService, memberInstanceName,
                    'Member Volume', extraSpecs)
            if isV3:
                self.provisionv3.delete_volume_from_pool(
                    self.conn, storageConfigservice,
                    memberInstanceNames, None, extraSpecs)
            else:
                self.provision.delete_volume_from_pool(
                    self.conn, storageConfigservice,
                    memberInstanceNames, None, extraSpecs)
            for volumeRef in volumes:
                volumeRef['status'] = 'deleted'
        except Exception:
            for volumeRef in volumes:
                volumeRef['status'] = 'error_deleting'
                modelUpdate['status'] = 'error_deleting'
        return volumes, modelUpdate

    def create_cgsnapshot(self, context, cgsnapshot, db):
        """Creates a cgsnapshot.

        :param context: the context
        :param cgsnapshot: the consistency group snapshot to be created
        :param db: cinder database
        :returns: dict -- modelUpdate
        :returns: list -- list of snapshots
        :raises: VolumeBackendAPIException
        """
        consistencyGroup = db.consistencygroup_get(
            context, cgsnapshot['consistencygroup_id'])

        LOG.info(_LI(
            "Create snapshot for Consistency Group %(cgId)s "
            "cgsnapshotID: %(cgsnapshot)s."),
            {'cgsnapshot': cgsnapshot['id'],
             'cgId': cgsnapshot['consistencygroup_id']})

        cgName = self.utils.truncate_string(
            cgsnapshot['consistencygroup_id'], 8)

        modelUpdate = {'status': 'available'}

        volumeTypeId = consistencyGroup['volume_type_id'].replace(",", "")
        extraSpecs = self._initial_setup(None, volumeTypeId)
        self.conn = self._get_ecom_connection()

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))

        try:
            replicationService = self.utils.find_replication_service(
                self.conn, storageSystem)

            cgInstanceName = (
                self._find_consistency_group(replicationService, cgName))
            if cgInstanceName is None:
                exception_message = (_("Cannot find CG group %s.") % cgName)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            memberInstanceNames = self._get_members_of_replication_group(
                cgInstanceName)

            # Create the target consistency group.
            targetCgName = self.utils.truncate_string(cgsnapshot['id'], 8)
            self.provision.create_consistency_group(
                self.conn, replicationService, targetCgName, extraSpecs)
            targetCgInstanceName = self._find_consistency_group(
                replicationService, targetCgName)
            LOG.info(_LI("Create target consistency group %(targetCg)s."),
                     {'targetCg': targetCgInstanceName})

            for memberInstanceName in memberInstanceNames:
                volInstance = self.conn.GetInstance(
                    memberInstanceName, LocalOnly=False)
                numOfBlocks = volInstance['NumberOfBlocks']
                blockSize = volInstance['BlockSize']
                volumeSizeInbits = numOfBlocks * blockSize

                targetVolumeName = 'targetVol'
                volume = {'size': int(self.utils.convert_bits_to_gbs(
                    volumeSizeInbits))}

                if extraSpecs[ISV3]:
                    _rc, volumeDict, _storageSystemName = (
                        self._create_v3_volume(
                            volume, targetVolumeName, volumeSizeInbits,
                            extraSpecs))
                else:
                    _rc, volumeDict, _storageSystemName = (
                        self._create_composite_volume(
                            volume, targetVolumeName, volumeSizeInbits,
                            extraSpecs))
                targetVolumeInstance = self.utils.find_volume_instance(
                    self.conn, volumeDict, targetVolumeName)
                LOG.debug("Create target volume for member volume "
                          "Source volume: %(memberVol)s "
                          "Target volume %(targetVol)s.",
                          {'memberVol': memberInstanceName,
                           'targetVol': targetVolumeInstance.path})
                self.provision.add_volume_to_cg(self.conn,
                                                replicationService,
                                                targetCgInstanceName,
                                                targetVolumeInstance.path,
                                                targetCgName,
                                                targetVolumeName,
                                                extraSpecs)

            # Less than 5 characters relationship name.
            relationName = self.utils.truncate_string(cgsnapshot['id'], 5)
            if extraSpecs[ISV3]:
                self.provisionv3.create_group_replica(
                    self.conn, replicationService, cgInstanceName,
                    targetCgInstanceName, relationName, extraSpecs)
            else:
                self.provision.create_group_replica(
                    self.conn, replicationService, cgInstanceName,
                    targetCgInstanceName, relationName, extraSpecs)
            # Break the replica group relationship.
            rgSyncInstanceName = self.utils.find_group_sync_rg_by_target(
                self.conn, storageSystem, targetCgInstanceName, extraSpecs,
                True)
            if rgSyncInstanceName is not None:
                repservice = self.utils.find_replication_service(
                    self.conn, storageSystem)
                if repservice is None:
                    exception_message = (_(
                        "Cannot find Replication service on system %s.") %
                        storageSystem)
                    raise exception.VolumeBackendAPIException(
                        data=exception_message)
            if extraSpecs[ISV3]:
                # Operation 7: dissolve for snapVx.
                operation = self.utils.get_num(9, '16')
                self.provisionv3.break_replication_relationship(
                    self.conn, repservice, rgSyncInstanceName, operation,
                    extraSpecs)
            else:
                self.provision.delete_clone_relationship(self.conn, repservice,
                                                         rgSyncInstanceName,
                                                         extraSpecs)

        except Exception:
            modelUpdate['status'] = 'error'
            self.utils.populate_cgsnapshot_status(
                context, db, cgsnapshot['id'], modelUpdate['status'])
            exceptionMessage = (_("Failed to create snapshot for cg:"
                                  " %(cgName)s.")
                                % {'cgName': cgName})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        snapshots = self.utils.populate_cgsnapshot_status(
            context, db, cgsnapshot['id'], modelUpdate['status'])
        return modelUpdate, snapshots

    def delete_cgsnapshot(self, context, cgsnapshot, db):
        """Delete a cgsnapshot.

        :param context: the context
        :param cgsnapshot: the consistency group snapshot to be created
        :param db: cinder database
        :returns: dict -- modelUpdate
        :returns: list -- list of snapshots
        :raises: VolumeBackendAPIException
        """
        consistencyGroup = db.consistencygroup_get(
            context, cgsnapshot['consistencygroup_id'])
        snapshots = db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot['id'])

        LOG.info(_LI(
            "Delete snapshot for source CG %(cgId)s "
            "cgsnapshotID: %(cgsnapshot)s."),
            {'cgsnapshot': cgsnapshot['id'],
             'cgId': cgsnapshot['consistencygroup_id']})

        modelUpdate = {'status': 'deleted'}
        volumeTypeId = consistencyGroup['volume_type_id'].replace(",", "")
        extraSpecs = self._initial_setup(None, volumeTypeId)
        self.conn = self._get_ecom_connection()

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))

        try:
            targetCgName = self.utils.truncate_string(cgsnapshot['id'], 8)
            modelUpdate, snapshots = self._delete_cg_and_members(
                storageSystem, targetCgName, modelUpdate,
                snapshots, extraSpecs)
        except Exception:
            modelUpdate['status'] = 'error_deleting'
            self.utils.populate_cgsnapshot_status(
                context, db, cgsnapshot['id'], modelUpdate['status'])
            exceptionMessage = (_("Failed to delete snapshot for cg: "
                                  "%(cgId)s.")
                                % {'cgId': cgsnapshot['consistencygroup_id']})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        snapshots = self.utils.populate_cgsnapshot_status(
            context, db, cgsnapshot['id'], modelUpdate['status'])
        return modelUpdate, snapshots

    def _find_consistency_group(self, replicationService, cgName):
        """Finds a CG given its name.

        :param replicationService: the replication service
        :param cgName: the consistency group name
        :returns: foundCgInstanceName
        """
        foundCgInstanceName = None
        cgInstanceNames = (
            self.conn.AssociatorNames(replicationService,
                                      ResultClass='CIM_ReplicationGroup'))

        for cgInstanceName in cgInstanceNames:
            instance = self.conn.GetInstance(cgInstanceName, LocalOnly=False)
            if cgName == instance['ElementName']:
                foundCgInstanceName = cgInstanceName
                break

        return foundCgInstanceName

    def _get_members_of_replication_group(self, cgInstanceName):
        """Get the members of consistency group.

        :param cgInstanceName: the CG instance name
        :returns: list -- memberInstanceNames
        """
        memberInstanceNames = self.conn.AssociatorNames(
            cgInstanceName,
            AssocClass='CIM_OrderedMemberOfCollection')

        return memberInstanceNames

    def _create_composite_volume(
            self, volume, volumeName, volumeSize, extraSpecs,
            memberCount=None):
        """Create a composite volume (V2).

        :param volume: the volume object
        :param volumeName: the name of the volume
        :param volumeSize: the size of the volume
        :param extraSpecs: extra specifications
        :param memberCount: the number of meta members in a composite volume
        :returns: int -- return code
        :returns: dict -- volumeDict
        :returns: string -- storageSystemName
        :raises: VolumeBackendAPIException
        """
        if not memberCount:
            memberCount, errorDesc = self.utils.determine_member_count(
                volume['size'], extraSpecs[MEMBERCOUNT],
                extraSpecs[COMPOSITETYPE])
            if errorDesc is not None:
                exceptionMessage = (_("The striped meta count of "
                                      "%(memberCount)s is too small for "
                                      "volume: %(volumeName)s, "
                                      "with size %(volumeSize)s.")
                                    % {'memberCount': memberCount,
                                       'volumeName': volumeName,
                                       'volumeSize': volume['size']})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        poolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(extraSpecs))

        LOG.debug("Create Volume: %(volume)s  Pool: %(pool)s "
                  "Storage System: %(storageSystem)s "
                  "Size: %(size)lu  MemberCount: %(memberCount)s.",
                  {'volume': volumeName,
                   'pool': poolInstanceName,
                   'storageSystem': storageSystemName,
                   'size': volumeSize,
                   'memberCount': memberCount})

        elementCompositionService = (
            self.utils.find_element_composition_service(self.conn,
                                                        storageSystemName))

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)

        # If FAST is intended to be used we must first check that the pool
        # is associated with the correct storage tier.
        if extraSpecs[FASTPOLICY] is not None:
            foundPoolInstanceName = self.fast.get_pool_associated_to_policy(
                self.conn, extraSpecs[FASTPOLICY], extraSpecs[ARRAY],
                storageConfigService, poolInstanceName)
            if foundPoolInstanceName is None:
                exceptionMessage = (_("Pool: %(poolName)s. "
                                      "is not associated to storage tier for "
                                      "fast policy %(fastPolicy)s.")
                                    % {'poolName': extraSpecs[POOL],
                                       'fastPolicy':
                                        extraSpecs[FASTPOLICY]})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        compositeType = self.utils.get_composite_type(
            extraSpecs[COMPOSITETYPE])

        volumeDict, rc = self.provision.create_composite_volume(
            self.conn, elementCompositionService, volumeSize, volumeName,
            poolInstanceName, compositeType, memberCount, extraSpecs)

        # Now that we have already checked that the pool is associated with
        # the correct storage tier and the volume was successfully created
        # add the volume to the default storage group created for
        # volumes in pools associated with this fast policy.
        if extraSpecs[FASTPOLICY]:
            LOG.info(_LI(
                "Adding volume: %(volumeName)s to default storage group"
                " for FAST policy: %(fastPolicyName)s."),
                {'volumeName': volumeName,
                 'fastPolicyName': extraSpecs[FASTPOLICY]})
            defaultStorageGroupInstanceName = (
                self._get_or_create_default_storage_group(
                    self.conn, storageSystemName, volumeDict,
                    volumeName, extraSpecs[FASTPOLICY], extraSpecs))
            if not defaultStorageGroupInstanceName:
                exceptionMessage = (_(
                    "Unable to create or get default storage group for "
                    "FAST policy: %(fastPolicyName)s.")
                    % {'fastPolicyName': extraSpecs[FASTPOLICY]})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            self._add_volume_to_default_storage_group_on_create(
                volumeDict, volumeName, storageConfigService,
                storageSystemName, extraSpecs[FASTPOLICY], extraSpecs)
        return rc, volumeDict, storageSystemName

    def _create_v3_volume(
            self, volume, volumeName, volumeSize, extraSpecs):
        """Create a volume (V3).

        :param volume: the volume object
        :param volumeName: the volume name
        :param volumeSize: the volume size
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :returns: dict -- volumeDict
        :returns: string -- storageSystemName
        :raises: VolumeBackendAPIException
        """
        isValidSLO, isValidWorkload = self.utils.verify_slo_workload(
            extraSpecs[SLO], extraSpecs[WORKLOAD])

        if not isValidSLO or not isValidWorkload:
            exceptionMessage = (_(
                "Either SLO: %(slo)s or workload %(workload)s is invalid. "
                "Examine previous error statement for valid values.")
                % {'slo': extraSpecs[SLO],
                   'workload': extraSpecs[WORKLOAD]})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        poolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(extraSpecs))

        LOG.debug("Create Volume: %(volume)s  Pool: %(pool)s "
                  "Storage System: %(storageSystem)s "
                  "Size: %(size)lu.",
                  {'volume': volumeName,
                   'pool': poolInstanceName,
                   'storageSystem': storageSystemName,
                   'size': volumeSize})

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)

        # A volume created without specifying a storage group during
        # creation time is allocated from the default SRP pool and
        # assigned the optimized SLO.
        sgInstanceName = self._get_or_create_storage_group_v3(
            extraSpecs[POOL], extraSpecs[SLO],
            extraSpecs[WORKLOAD], storageSystemName, extraSpecs)
        volumeDict, rc = self.provisionv3.create_volume_from_sg(
            self.conn, storageConfigService, volumeName,
            sgInstanceName, volumeSize, extraSpecs)

        return rc, volumeDict, storageSystemName

    def _get_or_create_storage_group_v3(
            self, poolName, slo, workload, storageSystemName, extraSpecs):
        """Get or create storage group_v3 (V3).

        :param poolName: the SRP pool nsmr
        :param slo: the SLO
        :param workload: the workload
        :param storageSystemName: storage system name
        :param extraSpecs: extra specifications
        :returns: sgInstanceName
        """
        storageGroupName = self.utils.get_v3_storage_group_name(
            poolName, slo, workload)
        controllerConfigService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))
        sgInstanceName = self.utils.find_storage_masking_group(
            self.conn, controllerConfigService, storageGroupName)
        if sgInstanceName is None:
            sgInstanceName = self.provisionv3.create_storage_group_v3(
                self.conn, controllerConfigService, storageGroupName,
                poolName, slo, workload, extraSpecs)

        return sgInstanceName

    def _extend_composite_volume(self, volumeInstance, volumeName,
                                 newSize, additionalVolumeSize, extraSpecs):
        """Extend a composite volume (V2).

        :param volumeInstance: the volume instance
        :param volumeName: the name of the volume
        :param newSize: in GBs
        :param additionalVolumeSize: additional volume size
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :returns: dict -- modifiedVolumeDict
        :raises: VolumeBackendAPIException
        """
        # Is the volume extendable.
        isConcatenated = self.utils.check_if_volume_is_extendable(
            self.conn, volumeInstance)
        if 'True' not in isConcatenated:
            exceptionMessage = (_(
                "Volume: %(volumeName)s is not a concatenated volume. "
                "You can only perform extend on concatenated volume. "
                "Exiting...")
                % {'volumeName': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)
        else:
            compositeType = self.utils.get_composite_type(CONCATENATED)

        LOG.debug("Extend Volume: %(volume)s  New size: %(newSize)s GBs.",
                  {'volume': volumeName,
                   'newSize': newSize})

        deviceId = volumeInstance['DeviceID']
        storageSystemName = volumeInstance['SystemName']
        LOG.debug(
            "Device ID: %(deviceid)s: Storage System: "
            "%(storagesystem)s.",
            {'deviceid': deviceId,
             'storagesystem': storageSystemName})

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)

        elementCompositionService = (
            self.utils.find_element_composition_service(
                self.conn, storageSystemName))

        # Create a volume to the size of the
        # newSize - oldSize = additionalVolumeSize.
        unboundVolumeInstance = self._create_and_get_unbound_volume(
            self.conn, storageConfigService, volumeInstance.path,
            additionalVolumeSize, extraSpecs)
        if unboundVolumeInstance is None:
            exceptionMessage = (_(
                "Error Creating unbound volume on an Extend operation."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        # Add the new unbound volume to the original composite volume.
        rc, modifiedVolumeDict = (
            self._modify_and_get_composite_volume_instance(
                self.conn, elementCompositionService, volumeInstance,
                unboundVolumeInstance.path, volumeName, compositeType,
                extraSpecs))
        if modifiedVolumeDict is None:
            exceptionMessage = (_(
                "On an Extend Operation, error adding volume to composite "
                "volume: %(volumename)s.")
                % {'volumename': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return rc, modifiedVolumeDict

    def _slo_workload_migration(self, volumeInstance, volume, host,
                                volumeName, volumeStatus, newType,
                                extraSpecs):
        """Migrate from SLO/Workload combination to another (V3).

        :param volumeInstance: the volume instance
        :param volume: the volume object
        :param host: the host object
        :param volumeName: the name of the volume
        :param volumeStatus: the volume status
        :param newType: the type to migrate to
        :param extraSpecs: extra specifications
        :returns: boolean -- True if migration succeeded, False if error.
        """
        storageGroupName = self.utils.get_v3_storage_group_name(
            extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD])
        volumeInstanceName = volumeInstance.path
        isValid, targetSlo, targetWorkload = (
            self._is_valid_for_storage_assisted_migration_v3(
                volumeInstanceName, host, extraSpecs[ARRAY],
                extraSpecs[POOL], volumeName, volumeStatus,
                storageGroupName))

        storageSystemName = volumeInstance['SystemName']
        if not isValid:
            LOG.error(_LE(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype."),
                {'name': volumeName})
            return False
        if volume['host'] != host['host']:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s.",
                {'name': volumeName,
                 'sourceHost': volume['host'],
                 'targetHost': host['host']})
            return self._migrate_volume_v3(
                volume, volumeInstance, extraSpecs[POOL], targetSlo,
                targetWorkload, storageSystemName, newType, extraSpecs)

        return False

    def _migrate_volume_v3(
            self, volume, volumeInstance, poolName, targetSlo,
            targetWorkload, storageSystemName, newType, extraSpecs):
        """Migrate from one slo/workload combination to another (V3).

        This requires moving the volume from its current SG to a
        new or existing SG that has the target attributes.

        :param volume: the volume object
        :param volumeInstance: the volume instance
        :param poolName: the SRP Pool Name
        :param targetSlo: the target SLO
        :param targetWorkload: the target workload
        :param storageSystemName: the storage system name
        :param newType: the type to migrate to
        :param extraSpecs: extra specifications
        :returns: boolean -- True if migration succeeded, False if error.
        """
        volumeName = volume['name']

        controllerConfigService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        defaultSgName = self.utils.get_v3_storage_group_name(
            extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD])

        foundStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(
                self.conn, volumeInstance.path, defaultSgName))
        if foundStorageGroupInstanceName is None:
            LOG.warning(_LW(
                "Volume : %(volumeName)s is not currently "
                "belonging to any storage group."),
                {'volumeName': volumeName})
        else:
            self.provision.remove_device_from_storage_group(
                self.conn,
                controllerConfigService,
                foundStorageGroupInstanceName,
                volumeInstance.path,
                volumeName, extraSpecs)
            # Check that it has been removed.
            sgFromVolRemovedInstanceName = (
                self.utils.wrap_get_storage_group_from_volume(
                    self.conn, volumeInstance.path, defaultSgName))
            if sgFromVolRemovedInstanceName is not None:
                LOG.error(_LE(
                    "Volume : %(volumeName)s has not been "
                    "removed from source storage group %(storageGroup)s."),
                    {'volumeName': volumeName,
                     'storageGroup': sgFromVolRemovedInstanceName})
                return False

        storageGroupName = self.utils.get_v3_storage_group_name(
            poolName, targetSlo, targetWorkload)

        targetSgInstanceName = self._get_or_create_storage_group_v3(
            poolName, targetSlo, targetWorkload, storageSystemName,
            extraSpecs)
        if targetSgInstanceName is None:
            LOG.error(_LE(
                "Failed to get or create storage group %(storageGroupName)s."),
                {'storageGroupName': storageGroupName})
            return False

        self.masking.add_volume_to_storage_group(
            self.conn, controllerConfigService, targetSgInstanceName,
            volumeInstance, volumeName, storageGroupName, extraSpecs)
        # Check that it has been added.
        sgFromVolAddedInstanceName = (
            self.utils.get_storage_group_from_volume(
                self.conn, volumeInstance.path, storageGroupName))
        if sgFromVolAddedInstanceName is None:
            LOG.error(_LE(
                "Volume : %(volumeName)s has not been "
                "added to target storage group %(storageGroup)s."),
                {'volumeName': volumeName,
                 'storageGroup': targetSgInstanceName})
            return False

        return True

    def _pool_migration(self, volumeInstance, volume, host,
                        volumeName, volumeStatus,
                        fastPolicyName, newType, extraSpecs):
        """Migrate from one pool to another (V2).

        :param volumeInstance: the volume instance
        :param volume: the volume object
        :param host: the host object
        :param volumeName: the name of the volume
        :param volumeStatus: the volume status
        :param fastPolicyName: the FAST policy Name
        :param newType: the type to migrate to
        :param extraSpecs: extra specifications
        :returns: boolean -- True if migration succeeded, False if error.
        """
        storageSystemName = volumeInstance['SystemName']
        isValid, targetPoolName, targetFastPolicyName = (
            self._is_valid_for_storage_assisted_migration(
                volumeInstance.path, host, storageSystemName,
                volumeName, volumeStatus))

        if not isValid:
            LOG.error(_LE(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype."),
                {'name': volumeName})
            return False
        if volume['host'] != host['host']:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s.",
                {'name': volumeName,
                 'sourceHost': volume['host'],
                 'targetHost': host['host']})
            return self._migrate_volume(
                volume, volumeInstance, targetPoolName, targetFastPolicyName,
                fastPolicyName, extraSpecs, newType)

        return False

    def _update_pool_stats(
            self, backendName, arrayInfo):
        """Update pool statistics (V2).

        :param backendName: the backend name
        :param arrayInfo: the arrayInfo
        :returns: location_info, total_capacity_gb, free_capacity_gb
        """

        if arrayInfo['FastPolicy']:
            LOG.debug(
                "Fast policy %(fastPolicyName)s is enabled on %(arrayName)s.",
                {'fastPolicyName': arrayInfo['FastPolicy'],
                 'arrayName': arrayInfo['SerialNumber']})
        else:
            LOG.debug(
                "No Fast policy for Array:%(arrayName)s "
                "backend:%(backendName)s.",
                {'arrayName': arrayInfo['SerialNumber'],
                 'backendName': backendName})

        storageSystemInstanceName = self.utils.find_storageSystem(
            self.conn, arrayInfo['SerialNumber'])
        isTieringPolicySupported = (
            self.fast.is_tiering_policy_enabled_on_storage_system(
                self.conn, storageSystemInstanceName))

        if (arrayInfo['FastPolicy'] is not None and
                isTieringPolicySupported is True):  # FAST enabled
            total_capacity_gb, free_capacity_gb = (
                self.fast.get_capacities_associated_to_policy(
                    self.conn, arrayInfo['SerialNumber'],
                    arrayInfo['FastPolicy']))
            LOG.info(_LI(
                "FAST: capacity stats for policy %(fastPolicyName)s on array "
                "%(arrayName)s. total_capacity_gb=%(total_capacity_gb)lu, "
                "free_capacity_gb=%(free_capacity_gb)lu."),
                {'fastPolicyName': arrayInfo['FastPolicy'],
                 'arrayName': arrayInfo['SerialNumber'],
                 'total_capacity_gb': total_capacity_gb,
                 'free_capacity_gb': free_capacity_gb})
        else:  # NON-FAST
            total_capacity_gb, free_capacity_gb = (
                self.utils.get_pool_capacities(self.conn,
                                               arrayInfo['PoolName'],
                                               arrayInfo['SerialNumber']))
            LOG.info(_LI(
                "NON-FAST: capacity stats for pool %(poolName)s on array "
                "%(arrayName)s total_capacity_gb=%(total_capacity_gb)lu, "
                "free_capacity_gb=%(free_capacity_gb)lu."),
                {'poolName': arrayInfo['PoolName'],
                 'arrayName': arrayInfo['SerialNumber'],
                 'total_capacity_gb': total_capacity_gb,
                 'free_capacity_gb': free_capacity_gb})

        location_info = ("%(arrayName)s#%(poolName)s#%(policyName)s"
                         % {'arrayName': arrayInfo['SerialNumber'],
                            'poolName': arrayInfo['PoolName'],
                            'policyName': arrayInfo['FastPolicy']})

        return location_info, total_capacity_gb, free_capacity_gb

    def _set_v2_extra_specs(self, extraSpecs, poolRecord):
        """Set the VMAX V2 extra specs.

        :param extraSpecs: extra specifications
        :param poolRecord: pool record
        :returns: dict -- the extraSpecs
        :raises: VolumeBackendAPIException
        """
        try:
            stripedMetaCount = extraSpecs[STRIPECOUNT]
            extraSpecs[MEMBERCOUNT] = stripedMetaCount
            extraSpecs[COMPOSITETYPE] = STRIPED

            LOG.debug(
                "There are: %(stripedMetaCount)s striped metas in "
                "the extra specs.",
                {'stripedMetaCount': stripedMetaCount})
        except KeyError:
            memberCount = '1'
            extraSpecs[MEMBERCOUNT] = memberCount
            extraSpecs[COMPOSITETYPE] = CONCATENATED
            LOG.debug("StripedMetaCount is not in the extra specs.")

        # Get the FAST policy from the file. This value can be None if the
        # user doesn't want to associate with any FAST policy.
        if poolRecord['FastPolicy']:
            LOG.debug("The fast policy name is: %(fastPolicyName)s.",
                      {'fastPolicyName': poolRecord['FastPolicy']})
        extraSpecs[FASTPOLICY] = poolRecord['FastPolicy']
        extraSpecs[ISV3] = False
        extraSpecs = self._set_common_extraSpecs(extraSpecs, poolRecord)

        LOG.debug("Pool is: %(pool)s "
                  "Array is: %(array)s "
                  "FastPolicy is: %(fastPolicy)s "
                  "CompositeType is: %(compositeType)s "
                  "MemberCount is: %(memberCount)s.",
                  {'pool': extraSpecs[POOL],
                   'array': extraSpecs[ARRAY],
                   'fastPolicy': extraSpecs[FASTPOLICY],
                   'compositeType': extraSpecs[COMPOSITETYPE],
                   'memberCount': extraSpecs[MEMBERCOUNT]})
        return extraSpecs

    def _set_v3_extra_specs(self, extraSpecs, poolRecord):
        """Set the VMAX V3 extra specs.

        If SLO or workload are not specified then the default
        values are NONE and the Optimized SLO will be assigned to the
        volume.

        :param extraSpecs: extra specifications
        :param poolRecord: pool record
        :returns: dict -- the extra specifications dictionary
        """
        extraSpecs[SLO] = poolRecord['SLO']
        extraSpecs[WORKLOAD] = poolRecord['Workload']
        extraSpecs[ISV3] = True
        extraSpecs = self._set_common_extraSpecs(extraSpecs, poolRecord)
        LOG.debug("Pool is: %(pool)s "
                  "Array is: %(array)s "
                  "SLO is: %(slo)s "
                  "Workload is: %(workload)s.",
                  {'pool': extraSpecs[POOL],
                   'array': extraSpecs[ARRAY],
                   'slo': extraSpecs[SLO],
                   'workload': extraSpecs[WORKLOAD]})
        return extraSpecs

    def _set_common_extraSpecs(self, extraSpecs, poolRecord):
        """Set common extra specs.

        The extraSpecs are common to v2 and v3

        :param extraSpecs: extra specifications
        :param poolRecord: pool record
        :returns: dict -- the extra specifications dictionary
        """
        extraSpecs[POOL] = poolRecord['PoolName']
        extraSpecs[ARRAY] = poolRecord['SerialNumber']
        extraSpecs[PORTGROUPNAME] = poolRecord['PortGroup']
        if 'Interval' in poolRecord and poolRecord['Interval']:
            extraSpecs[INTERVAL] = poolRecord['Interval']
            LOG.debug("The user defined interval is : %(intervalInSecs)s.",
                      {'intervalInSecs': poolRecord['Interval']})
        else:
            LOG.debug("Interval not overridden, default of 10 assumed.")
        if 'Retries' in poolRecord and poolRecord['Retries']:
            extraSpecs[RETRIES] = poolRecord['Retries']
            LOG.debug("The user defined retries is : %(retries)s.",
                      {'retries': poolRecord['Retries']})
        else:
            LOG.debug("Retries not overridden, default of 60 assumed.")
        return extraSpecs

    def _delete_from_pool(self, storageConfigService, volumeInstance,
                          volumeName, deviceId, fastPolicyName, extraSpecs):
        """Delete from pool (v2).

        :param storageConfigService: the storage config service
        :param volumeInstance: the volume instance
        :param volumeName: the volume Name
        :param deviceId: the device ID of the volume
        :param fastPolicyName: the FAST policy name(if it exists)
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        storageSystemName = volumeInstance['SystemName']
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))
        if fastPolicyName is not None:
            defaultStorageGroupInstanceName = (
                self.masking.remove_device_from_default_storage_group(
                    self.conn, controllerConfigurationService,
                    volumeInstance.path, volumeName, fastPolicyName,
                    extraSpecs))
            if defaultStorageGroupInstanceName is None:
                LOG.warning(_LW(
                    "The volume: %(volumename)s. was not first part of the "
                    "default storage group for FAST policy %(fastPolicyName)s"
                    "."),
                    {'volumename': volumeName,
                     'fastPolicyName': fastPolicyName})
                # Check if it is part of another storage group.
                self._remove_device_from_storage_group(
                    controllerConfigurationService,
                    volumeInstance.path, volumeName, extraSpecs)

        else:
            # Check if volume is part of a storage group.
            self._remove_device_from_storage_group(
                controllerConfigurationService,
                volumeInstance.path, volumeName, extraSpecs)

        LOG.debug("Delete Volume: %(name)s Method: EMCReturnToStoragePool "
                  "ConfigService: %(service)s TheElement: %(vol_instance)s "
                  "DeviceId: %(deviceId)s.",
                  {'service': storageConfigService,
                   'name': volumeName,
                   'vol_instance': volumeInstance.path,
                   'deviceId': deviceId})
        try:
            rc = self.provision.delete_volume_from_pool(
                self.conn, storageConfigService, volumeInstance.path,
                volumeName, extraSpecs)

        except Exception:
            # If we cannot successfully delete the volume then we want to
            # return the volume to the default storage group.
            if (fastPolicyName is not None and
                    defaultStorageGroupInstanceName is not None and
                    storageSystemName is not None):
                assocDefaultStorageGroupName = (
                    self.fast
                    .add_volume_to_default_storage_group_for_fast_policy(
                        self.conn, controllerConfigurationService,
                        volumeInstance, volumeName, fastPolicyName,
                        extraSpecs))
                if assocDefaultStorageGroupName is None:
                    LOG.error(_LE(
                        "Failed to Roll back to re-add volume %(volumeName)s "
                        "to default storage group for fast policy "
                        "%(fastPolicyName)s. Please contact your sysadmin to "
                        "get the volume returned to the default "
                        "storage group."),
                        {'volumeName': volumeName,
                         'fastPolicyName': fastPolicyName})

            errorMessage = (_("Failed to delete volume %(volumeName)s.") %
                            {'volumeName': volumeName})
            LOG.exception(errorMessage)
            raise exception.VolumeBackendAPIException(data=errorMessage)
        return rc

    def _delete_from_pool_v3(self, storageConfigService, volumeInstance,
                             volumeName, deviceId, storageGroupName,
                             extraSpecs):
        """Delete from pool (v3).

        :param storageConfigService: the storage config service
        :param volumeInstance: the volume instance
        :param volumeName: the volume Name
        :param deviceId: the device ID of the volume
        :param storageGroupName: the name of the default SG
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        storageSystemName = volumeInstance['SystemName']
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        # Check if it is part of a storage group and delete it
        # extra logic for case when volume is the last member.
        sgFromVolInstanceName = self.masking.remove_and_reset_members(
            self.conn, controllerConfigurationService, volumeInstance,
            volumeName, extraSpecs, None, 'noReset')

        LOG.debug("Delete Volume: %(name)s  Method: EMCReturnToStoragePool "
                  "ConfigServic: %(service)s  TheElement: %(vol_instance)s "
                  "DeviceId: %(deviceId)s.",
                  {'service': storageConfigService,
                   'name': volumeName,
                   'vol_instance': volumeInstance.path,
                   'deviceId': deviceId})
        try:
            rc = self.provisionv3.delete_volume_from_pool(
                self.conn, storageConfigService, volumeInstance.path,
                volumeName, extraSpecs)

        except Exception:
            # If we cannot successfully delete the volume, then we want to
            # return the volume to the default storage group,
            # which should be the SG it previously belonged to.
            storageGroupInstanceName = self.utils.find_storage_masking_group(
                self.conn, controllerConfigurationService, storageGroupName)

            if sgFromVolInstanceName is not storageGroupInstanceName:
                LOG.debug(
                    "Volume: %(volumeName)s was not previously part of "
                    " %(storageGroupInstanceName)s. "
                    "Returning to %(storageGroupName)s.",
                    {'volumeName': volumeName,
                     'storageGroupInstanceName': storageGroupInstanceName,
                     'storageGroupName': storageGroupName})

            if storageGroupInstanceName is not None:
                self.masking.add_volume_to_storage_group(
                    self.conn, controllerConfigurationService,
                    storageGroupInstanceName, volumeInstance, volumeName,
                    storageGroupName, extraSpecs)

            errorMessage = (_("Failed to delete volume %(volumeName)s.") %
                            {'volumeName': volumeName})
            LOG.exception(errorMessage)
            raise exception.VolumeBackendAPIException(data=errorMessage)

        return rc

    def _create_clone_v2(self, repServiceInstanceName, cloneVolume,
                         sourceVolume, sourceInstance, isSnapshot,
                         extraSpecs):
        """Create a clone (v2).

        :param repServiceInstanceName: the replication service
        :param cloneVolume: the clone volume object
        :param sourceVolume: the source volume object
        :param sourceInstance: the device ID of the volume
        :param isSnapshot: check to see if it is a snapshot
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        # Check if the source volume contains any meta devices.
        metaHeadInstanceName = self.utils.get_volume_meta_head(
            self.conn, sourceInstance.path)

        if metaHeadInstanceName is None:  # Simple volume.
            return self._create_v2_replica_and_delete_clone_relationship(
                repServiceInstanceName, cloneVolume, sourceVolume,
                sourceInstance, None, extraSpecs, isSnapshot)
        else:  # Composite volume with meta device members.
            # Check if the meta members capacity.
            metaMemberInstanceNames = (
                self.utils.get_composite_elements(
                    self.conn, sourceInstance))
            volumeCapacities = self.utils.get_meta_members_capacity_in_byte(
                self.conn, metaMemberInstanceNames)
            LOG.debug("Volume capacities:  %(metasizes)s.",
                      {'metasizes': volumeCapacities})
            if len(set(volumeCapacities)) == 1:
                LOG.debug("Meta volume all of the same size.")
                return self._create_v2_replica_and_delete_clone_relationship(
                    repServiceInstanceName, cloneVolume, sourceVolume,
                    sourceInstance, None, extraSpecs, isSnapshot)

            LOG.debug("Meta volumes are of different sizes, "
                      "%d different sizes.", len(set(volumeCapacities)))

            baseTargetVolumeInstance = None
            for volumeSizeInbits in volumeCapacities:
                if baseTargetVolumeInstance is None:  # Create base volume.
                    baseVolumeName = "TargetBaseVol"
                    volume = {'size': int(self.utils.convert_bits_to_gbs(
                        volumeSizeInbits))}
                    _rc, baseVolumeDict, storageSystemName = (
                        self._create_composite_volume(
                            volume, baseVolumeName, volumeSizeInbits,
                            extraSpecs, 1))
                    baseTargetVolumeInstance = self.utils.find_volume_instance(
                        self.conn, baseVolumeDict, baseVolumeName)
                    LOG.debug("Base target volume %(targetVol)s created. "
                              "capacity in bits: %(capInBits)lu.",
                              {'capInBits': volumeSizeInbits,
                               'targetVol': baseTargetVolumeInstance.path})
                else:  # Create append volume
                    targetVolumeName = "MetaVol"
                    volume = {'size': int(self.utils.convert_bits_to_gbs(
                        volumeSizeInbits))}
                    storageConfigService = (
                        self.utils.find_storage_configuration_service(
                            self.conn, storageSystemName))
                    unboundVolumeInstance = (
                        self._create_and_get_unbound_volume(
                            self.conn, storageConfigService,
                            baseTargetVolumeInstance.path, volumeSizeInbits,
                            extraSpecs))
                    if unboundVolumeInstance is None:
                        exceptionMessage = (_(
                            "Error Creating unbound volume."))
                        LOG.error(exceptionMessage)
                        # Remove target volume
                        self._delete_target_volume_v2(storageConfigService,
                                                      baseTargetVolumeInstance,
                                                      extraSpecs)
                        raise exception.VolumeBackendAPIException(
                            data=exceptionMessage)

                    # Append the new unbound volume to the
                    # base target composite volume.
                    baseTargetVolumeInstance = self.utils.find_volume_instance(
                        self.conn, baseVolumeDict, baseVolumeName)
                    try:
                        elementCompositionService = (
                            self.utils.find_element_composition_service(
                                self.conn, storageSystemName))
                        compositeType = self.utils.get_composite_type(
                            extraSpecs[COMPOSITETYPE])
                        _rc, modifiedVolumeDict = (
                            self._modify_and_get_composite_volume_instance(
                                self.conn,
                                elementCompositionService,
                                baseTargetVolumeInstance,
                                unboundVolumeInstance.path,
                                targetVolumeName,
                                compositeType,
                                extraSpecs))
                        if modifiedVolumeDict is None:
                            exceptionMessage = (_(
                                "Error appending volume %(volumename)s to "
                                "target base volume.")
                                % {'volumename': targetVolumeName})
                            LOG.error(exceptionMessage)
                            raise exception.VolumeBackendAPIException(
                                data=exceptionMessage)
                    except Exception:
                        exceptionMessage = (_(
                            "Exception appending meta volume to target volume "
                            "%(volumename)s.")
                            % {'volumename': baseVolumeName})
                        LOG.error(exceptionMessage)
                        # Remove append volume and target base volume
                        self._delete_target_volume_v2(
                            storageConfigService, unboundVolumeInstance,
                            extraSpecs)
                        self._delete_target_volume_v2(
                            storageConfigService, baseTargetVolumeInstance,
                            extraSpecs)

                        raise exception.VolumeBackendAPIException(
                            data=exceptionMessage)

            LOG.debug("Create V2 replica for meta members of different sizes.")
            return self._create_v2_replica_and_delete_clone_relationship(
                repServiceInstanceName, cloneVolume, sourceVolume,
                sourceInstance, baseTargetVolumeInstance, extraSpecs,
                isSnapshot)

    def _create_v2_replica_and_delete_clone_relationship(
            self, repServiceInstanceName, cloneVolume, sourceVolume,
            sourceInstance, targetInstance, extraSpecs, isSnapshot=False):
        """Create a replica and delete the clone relationship.

        :param repServiceInstanceName: the replication service
        :param cloneVolume: the clone volume object
        :param sourceVolume: the source volume object
        :param sourceInstance: the source volume instance
        :param targetInstance: the target volume instance
        :param extraSpecs: extra specifications
        :param isSnapshot: check to see if it is a snapshot
        :returns: int -- return code
        :returns: dict -- cloneDict
        """
        sourceName = sourceVolume['name']
        cloneName = cloneVolume['name']

        try:
            rc, job = self.provision.create_element_replica(
                self.conn, repServiceInstanceName, cloneName, sourceName,
                sourceInstance, targetInstance, extraSpecs)
        except Exception:
            exceptionMessage = (_(
                "Exception during create element replica. "
                "Clone name: %(cloneName)s "
                "Source name: %(sourceName)s "
                "Extra specs: %(extraSpecs)s ")
                % {'cloneName': cloneName,
                   'sourceName': sourceName,
                   'extraSpecs': extraSpecs})
            LOG.error(exceptionMessage)

            if targetInstance is not None:
                # Check if the copy session exists.
                storageSystem = targetInstance['SystemName']
                syncInstanceName = self.utils.find_sync_sv_by_target(
                    self.conn, storageSystem, targetInstance, False)
                if syncInstanceName is not None:
                    # Remove the Clone relationship.
                    rc, job = self.provision.delete_clone_relationship(
                        self.conn, repServiceInstanceName, syncInstanceName,
                        extraSpecs, True)
                storageConfigService = (
                    self.utils.find_storage_configuration_service(
                        self.conn, storageSystem))
                self._delete_target_volume_v2(
                    storageConfigService, targetInstance, extraSpecs)

            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        cloneDict = self.provision.get_volume_dict_from_job(
            self.conn, job['Job'])

        fastPolicyName = extraSpecs[FASTPOLICY]
        if isSnapshot:
            if fastPolicyName is not None:
                storageSystemName = sourceInstance['SystemName']
                self._add_clone_to_default_storage_group(
                    fastPolicyName, storageSystemName, cloneDict, cloneName,
                    extraSpecs)
            LOG.info(_LI("Snapshot creation %(cloneName)s completed. "
                     "Source Volume: %(sourceName)s."),
                     {'cloneName': cloneName,
                      'sourceName': sourceName})

            return rc, cloneDict

        cloneVolume['provider_location'] = six.text_type(cloneDict)
        syncInstanceName, storageSystemName = (
            self._find_storage_sync_sv_sv(cloneVolume, sourceVolume,
                                          extraSpecs))

        # Remove the Clone relationship so it can be used as a regular lun.
        # 8 - Detach operation.
        rc, job = self.provision.delete_clone_relationship(
            self.conn, repServiceInstanceName, syncInstanceName,
            extraSpecs)
        if fastPolicyName is not None:
            self._add_clone_to_default_storage_group(
                fastPolicyName, storageSystemName, cloneDict, cloneName,
                extraSpecs)

        return rc, cloneDict

    def get_target_wwns_from_masking_view(
            self, storageSystem, volume, connector):
        """Find target WWNs via the masking view.

        :param storageSystem: the storage system name
        :param volume: volume to be attached
        :param connector: the connector dict
        :returns: list -- the target WWN list
        """
        targetWwns = []
        mvInstanceName = self.get_masking_view_by_volume(volume, connector)
        if mvInstanceName is not None:
            targetWwns = self.masking.get_target_wwns(
                self.conn, mvInstanceName)
            LOG.info(_LI("Target wwns in masking view %(maskingView)s: "
                     "%(targetWwns)s."),
                     {'maskingView': mvInstanceName,
                      'targetWwns': six.text_type(targetWwns)})
        return targetWwns

    def get_port_group_from_masking_view(self, maskingViewInstanceName):
        """Get the port groups in a masking view.

        :param maskingViewInstanceName: masking view instance name
        :returns: portGroupInstanceName
        """
        return self.masking.get_port_group_from_masking_view(
            self.conn, maskingViewInstanceName)

    def get_masking_view_by_volume(self, volume, connector):
        """Given volume, retrieve the masking view instance name.

        :param volume: the volume
        :param connector: the connector object
        :returns: maskingviewInstanceName
        """
        LOG.debug("Finding Masking View for volume %(volume)s.",
                  {'volume': volume})
        volumeInstance = self._find_lun(volume)
        return self.masking.get_masking_view_by_volume(
            self.conn, volumeInstance, connector)

    def get_masking_views_by_port_group(self, portGroupInstanceName):
        """Given port group, retrieve the masking view instance name.

        :param portGroupInstanceName: port group instance name
        :returns: list -- maskingViewInstanceNames
        """
        LOG.debug("Finding Masking Views for port group %(pg)s.",
                  {'pg': portGroupInstanceName})
        return self.masking.get_masking_views_by_port_group(
            self.conn, portGroupInstanceName)

    def _create_replica_v3(
            self, repServiceInstanceName, cloneVolume,
            sourceVolume, sourceInstance, isSnapshot, extraSpecs):
        """Create a replica.

        V3 specific function, create replica for source volume,
        including clone and snapshot.

        :param repServiceInstanceName: the replication service
        :param cloneVolume: the clone volume object
        :param sourceVolume: the source volume object
        :param sourceInstance: the device ID of the volume
        :param isSnapshot: boolean -- check to see if it is a snapshot
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :returns: dict -- cloneDict
        """
        cloneName = cloneVolume['name']
        # Default syncType 8: clone.
        syncType = self.utils.get_num(8, '16')
        # Default operation 8: Detach for clone.
        operation = self.utils.get_num(8, '16')

        numOfBlocks = sourceInstance['NumberOfBlocks']
        blockSize = sourceInstance['BlockSize']
        volumeSizeInbits = numOfBlocks * blockSize

        volume = {'size':
                  int(self.utils.convert_bits_to_gbs(volumeSizeInbits))}
        _rc, volumeDict, _storageSystemName = (
            self._create_v3_volume(
                volume, cloneName, volumeSizeInbits, extraSpecs))
        targetInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, cloneName)
        LOG.debug("Create replica target volume "
                  "source volume: %(sourceVol)s, "
                  "target volume: %(targetVol)s.",
                  {'sourceVol': sourceInstance.path,
                   'targetVol': targetInstance.path})
        if isSnapshot:
            # SyncType 7: snap, VG3R default snapshot is snapVx.
            syncType = self.utils.get_num(7, '16')
            # Operation 9: Dissolve for snapVx.
            operation = self.utils.get_num(9, '16')

        try:
            _rc, job = (
                self.provisionv3.create_element_replica(
                    self.conn, repServiceInstanceName, cloneName, syncType,
                    sourceInstance, extraSpecs, targetInstance))
        except Exception:
            LOG.warning(_LW(
                "Clone failed on V3. Cleaning up the target volume. "
                "Clone name: %(cloneName)s "),
                {'cloneName': cloneName})
            # Check if the copy session exists.
            storageSystem = targetInstance['SystemName']
            syncInstanceName = self.utils.find_sync_sv_by_target(
                self.conn, storageSystem, targetInstance, False)
            if syncInstanceName is not None:
                # Break the clone relationship.
                rc, job = self.provisionv3.break_replication_relationship(
                    self.conn, repServiceInstanceName, syncInstanceName,
                    operation, extraSpecs, True)
            storageConfigService = (
                self.utils.find_storage_configuration_service(
                    self.conn, storageSystem))
            deviceId = targetInstance['DeviceID']
            volumeName = targetInstance['Name']
            storageGroupName = self.utils.get_v3_storage_group_name(
                extraSpecs[POOL], extraSpecs[SLO],
                extraSpecs[WORKLOAD])
            rc = self._delete_from_pool_v3(
                storageConfigService, targetInstance, volumeName,
                deviceId, storageGroupName, extraSpecs)
            # Re-throw the exception.
            raise

        cloneDict = self.provisionv3.get_volume_dict_from_job(
            self.conn, job['Job'])

        cloneVolume['provider_location'] = six.text_type(cloneDict)

        syncInstanceName, _storageSystem = (
            self._find_storage_sync_sv_sv(cloneVolume, sourceVolume,
                                          extraSpecs, True))

        # Detach/dissolve the clone/snap relationship.
        # 8 - Detach operation.
        # 9 - Dissolve operation.
        if isSnapshot:
            # Operation 9: dissolve for snapVx.
            operation = self.utils.get_num(9, '16')
        else:
            # Operation 8: detach for clone.
            operation = self.utils.get_num(8, '16')

        rc, job = self.provisionv3.break_replication_relationship(
            self.conn, repServiceInstanceName, syncInstanceName,
            operation, extraSpecs)
        return rc, cloneDict

    def _delete_cg_and_members(
            self, storageSystem, cgName, modelUpdate, volumes, extraSpecs):
        """Helper function to delete a consistencygroup and its member volumes.

        :param storageSystem: storage system
        :param cgName: consistency group name
        :param modelUpdate: dict -- the model update dict
        :param volumes: the list of member volumes
        :param extraSpecs: extra specifications
        :returns: dict -- modelUpdate
        :returns: list -- the updated list of member volumes
        :raises: VolumeBackendAPIException
        """
        replicationService = self.utils.find_replication_service(
            self.conn, storageSystem)

        storageConfigservice = (
            self.utils.find_storage_configuration_service(
                self.conn, storageSystem))
        cgInstanceName = self._find_consistency_group(
            replicationService, cgName)

        if cgInstanceName is None:
            exception_message = (_("Cannot find CG group %s.") % cgName)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        memberInstanceNames = self._get_members_of_replication_group(
            cgInstanceName)

        self.provision.delete_consistency_group(
            self.conn, replicationService, cgInstanceName, cgName,
            extraSpecs)

        if memberInstanceNames:
            try:
                controllerConfigurationService = (
                    self.utils.find_controller_configuration_service(
                        self.conn, storageSystem))
                for memberInstanceName in memberInstanceNames:
                    self._remove_device_from_storage_group(
                        controllerConfigurationService,
                        memberInstanceName, 'Member Volume', extraSpecs)
                LOG.debug("Deleting CG members. CG: %(cg)s "
                          "%(numVols)lu member volumes: %(memVols)s.",
                          {'cg': cgInstanceName,
                           'numVols': len(memberInstanceNames),
                           'memVols': memberInstanceNames})
                if extraSpecs[ISV3]:
                    self.provisionv3.delete_volume_from_pool(
                        self.conn, storageConfigservice,
                        memberInstanceNames, None, extraSpecs)
                else:
                    self.provision.delete_volume_from_pool(
                        self.conn, storageConfigservice,
                        memberInstanceNames, None, extraSpecs)
                    for volumeRef in volumes:
                        volumeRef['status'] = 'deleted'
            except Exception:
                for volumeRef in volumes:
                    volumeRef['status'] = 'error_deleting'
                    modelUpdate['status'] = 'error_deleting'
        return modelUpdate, volumes

    def _delete_target_volume_v2(
            self, storageConfigService, targetVolumeInstance, extraSpecs):
        """Helper function to delete the clone target volume instance.

        :param storageConfigService: storage configuration service instance
        :param targetVolumeInstance: clone target volume instance
        :param extraSpecs: extra specifications
        """
        deviceId = targetVolumeInstance['DeviceID']
        volumeName = targetVolumeInstance['Name']
        rc = self._delete_from_pool(storageConfigService,
                                    targetVolumeInstance,
                                    volumeName, deviceId,
                                    extraSpecs[FASTPOLICY],
                                    extraSpecs)
        return rc

    def _validate_pool(self, volume):
        """Get the pool from volume['host'].

        There may be backward compatibiliy concerns, so putting in a
        check to see if a version has been added to provider_location.
        If it has, we know we are at the current version, if not, we
        assume it was created pre 'Pool Aware Scheduler' feature.

        :param volume: the volume Object
        :returns: string -- pool
        :raises: VolumeBackendAPIException
        """
        pool = None
        # Volume is None in CG ops.
        if volume is None:
            return pool

        # This check is for all operations except a create.
        # On a create provider_location is None
        try:
            if volume['provider_location']:
                version = self._get_version_from_provider_location(
                    volume['provider_location'])
                if not version:
                    return pool
        except KeyError:
            return pool
        try:
            pool = volume_utils.extract_host(volume['host'], 'pool')
            if pool:
                LOG.debug("Pool from volume['host'] is %(pool)s.",
                          {'pool': pool})
            else:
                exceptionMessage = (_(
                    "Pool from volume['host'] %(host)s not found.")
                    % {'host': volume['host']})
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        except Exception as ex:
            exceptionMessage = (_(
                "Pool from volume['host'] failed with: %(ex)s.")
                % {'ex': ex})
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        return pool

    def _get_version_from_provider_location(self, loc):
        """Get the version from the provider location.

        :param loc: the provider_location dict
        :returns: version or None
        """
        version = None
        try:
            if isinstance(loc, six.string_types):
                name = eval(loc)
                version = name['version']
        except KeyError:
            pass
        return version

    def manage_existing(self, volume, external_ref):
        """Manages an existing VMAX Volume (import to Cinder).

        Renames the existing volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.

        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: dict -- model_update
        :raises: VolumeBackendAPIException
        """
        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()
        arrayName, deviceId = self.utils.get_array_and_device_id(volume,
                                                                 external_ref)

        # Manage existing volume is not supported if fast enabled.
        if extraSpecs[FASTPOLICY]:
            LOG.warning(_LW(
                "FAST is enabled. Policy: %(fastPolicyName)s."),
                {'fastPolicyName': extraSpecs[FASTPOLICY]})
            exceptionMessage = (_(
                "Manage volume is not supported if FAST is enable. "
                "FAST policy: %(fastPolicyName)s.")
                % {'fastPolicyName': extraSpecs[FASTPOLICY]})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        # Check if the volume is attached by checking if in any masking view.
        volumeInstanceName = (
            self.utils.find_volume_by_device_id_on_array(self.conn,
                                                         arrayName, deviceId))
        sgInstanceNames = (
            self.utils.get_storage_groups_from_volume(
                self.conn, volumeInstanceName))

        for sgInstanceName in sgInstanceNames:
            mvInstanceName = self.masking.get_masking_view_from_storage_group(
                self.conn, sgInstanceName)
            if mvInstanceName:
                exceptionMessage = (_(
                    "Unable to import volume %(deviceId)s to cinder. "
                    "Volume is in masking view %(mv)s.")
                    % {'deviceId': deviceId,
                       'mv': mvInstanceName})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        # Check if there is any associated snapshots with the volume.
        cinderPoolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(extraSpecs))
        repSessionInstanceName = (
            self.utils.get_associated_replication_from_source_volume(
                self.conn, storageSystemName, deviceId))
        if repSessionInstanceName:
            exceptionMessage = (_(
                "Unable to import volume %(deviceId)s to cinder. "
                "It is the source volume of replication session %(sync)s.")
                % {'deviceId': deviceId,
                   'sync': repSessionInstanceName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        # Make sure the existing external volume is in the same storage pool.
        volumePoolInstanceName = (
            self.utils.get_assoc_pool_from_volume(self.conn,
                                                  volumeInstanceName))
        volumePoolName = volumePoolInstanceName['InstanceID']
        cinderPoolName = cinderPoolInstanceName['InstanceID']
        LOG.debug("Storage pool of existing volume: %(volPool)s, "
                  "Storage pool currently managed by cinder: %(cinderPool)s.",
                  {'volPool': volumePoolName,
                   'cinderPool': cinderPoolName})
        if volumePoolName != cinderPoolName:
            exceptionMessage = (_(
                "Unable to import volume %(deviceId)s to cinder. The external "
                "volume is not in the pool managed by current cinder host.")
                % {'deviceId': deviceId})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        # Rename the volume
        volumeId = volume['name']
        volumeElementName = self.utils.get_volume_element_name(volumeId)
        LOG.debug("Rename volume %(vol)s to %(elementName)s.",
                  {'vol': volumeInstanceName,
                   'elementName': volumeElementName})
        volumeInstance = self.utils.rename_volume(self.conn,
                                                  volumeInstanceName,
                                                  volumeElementName)
        keys = {}
        volpath = volumeInstance.path
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']

        model_update = {}
        provider_location = {}
        provider_location['classname'] = volpath['CreationClassName']
        provider_location['keybindings'] = keys

        model_update.update({'display_name': volumeElementName})
        volume['provider_location'] = six.text_type(provider_location)
        model_update.update({'provider_location': volume['provider_location']})
        return model_update

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing VMAX volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        LOG.debug("Volume in manage_existing_get_size: %(volume)s.",
                  {'volume': volume})
        arrayName, deviceId = self.utils.get_array_and_device_id(volume,
                                                                 external_ref)
        volumeInstanceName = (
            self.utils.find_volume_by_device_id_on_array(self.conn,
                                                         arrayName, deviceId))
        volumeInstance = self.conn.GetInstance(volumeInstanceName)
        byteSize = self.utils.get_volume_size(self.conn, volumeInstance)
        gbSize = int(byteSize) / units.Gi
        LOG.debug(
            "Size of volume %(deviceID)s is %(volumeSize)s GB.",
            {'deviceID': deviceId,
             'volumeSize': gbSize})
        return gbSize

    def unmanage(self, volume):
        """Export VMAX volume from Cinder.

        Leave the volume intact on the backend array.

        :param volume: the volume object
        :raises: VolumeBackendAPIException
        """
        volumeName = volume['name']
        volumeId = volume['id']
        LOG.debug("Unmanage volume %(name)s, id=%(id)s",
                  {'name': volumeName,
                   'id': volumeId})
        self._initial_setup(volume)
        self.conn = self._get_ecom_connection()
        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            exceptionMessage = (_("Cannot find Volume: %(id)s. "
                                  "unmanage operation.  Exiting...")
                                % {'id': volumeId})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        # Rename the volume to volumeId, thus remove the 'OS-' prefix.
        volumeInstance = self.utils.rename_volume(self.conn,
                                                  volumeInstance,
                                                  volumeId)

    def update_consistencygroup(self, group, add_volumes,
                                remove_volumes):
        """Updates LUNs in consistency group.

        :param group: storage configuration service instance
        :param add_volumes: the volumes uuids you want to add to the CG
        :param remove_volumes: the volumes uuids you want to remove from
                               the CG
        """
        LOG.info(_LI("Update Consistency Group: %(group)s. "
                     "This adds and/or removes volumes from a CG."),
                 {'group': group['id']})

        modelUpdate = {'status': 'available'}
        volumeTypeId = group['volume_type_id'].replace(",", "")

        cg_name = self.utils.truncate_string(group['id'], 8)

        extraSpecs = self._initial_setup(None, volumeTypeId)

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))
        add_vols = [vol for vol in add_volumes] if add_volumes else []
        add_instance_names = self._get_volume_instance_names(add_vols)
        remove_vols = [vol for vol in remove_volumes] if remove_volumes else []
        remove_instance_names = self._get_volume_instance_names(remove_vols)
        self.conn = self._get_ecom_connection()

        try:
            replicationService = self.utils.find_replication_service(
                self.conn, storageSystem)
            cgInstanceName = (
                self._find_consistency_group(replicationService, cg_name))
            if cgInstanceName is None:
                raise exception.ConsistencyGroupNotFound(
                    consistencygroup_id=cg_name)
            # Add volume(s) to a consistency group
            if add_instance_names:
                self.provision.add_volume_to_cg(
                    self.conn, replicationService, cgInstanceName,
                    add_instance_names, cg_name, None,
                    extraSpecs)
            # Remove volume(s) from a consistency group
            if remove_instance_names:
                self.provision.remove_volume_from_cg(
                    self.conn, replicationService, cgInstanceName,
                    remove_instance_names, cg_name, None,
                    extraSpecs)
        except exception.ConsistencyGroupNotFound:
            raise
        except Exception as ex:
            LOG.error(_LE("Exception: %(ex)s"), {'ex': ex})
            exceptionMessage = (_("Failed to update consistency group:"
                                  " %(cgName)s.")
                                % {'cgName': cg_name})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return modelUpdate, None, None

    def _get_volume_instance_names(self, volumes):
        """Get volume instance names from volume.

        :param volumes: volume objects
        :returns: volume instance names
        """
        volumeInstanceNames = []
        for volume in volumes:
            volumeInstance = self._find_lun(volume)
            if volumeInstance is None:
                LOG.error(_LE("Volume %(name)s not found on the array."),
                          {'name': volume['name']})
            else:
                volumeInstanceNames.append(volumeInstance.path)
        return volumeInstanceNames

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot, snapshots, db):
        """Creates the consistency group from source.

        Currently the source can only be a cgsnapshot.

        :param context: the context
        :param group: the consistency group object to be created
        :param volumes: volumes in the consistency group
        :param cgsnapshot: the source consistency group snapshot
        :param snapshots: snapshots of the source volumes
        :param db: database
        :returns: model_update, volumes_model_update
                  model_update is a dictionary of cg status
                  volumes_model_update is a list of dictionaries of volume
                  update
        """
        LOG.debug("Enter EMCVMAXCommon::create_consistencygroup_from_src. "
                  "Group to be created: %(cgId)s, "
                  "Source snapshot: %(cgSnapshot)s.",
                  {'cgId': group['id'],
                   'cgSnapshot': cgsnapshot['consistencygroup_id']})

        volumeTypeId = group['volume_type_id'].replace(",", "")
        extraSpecs = self._initial_setup(None, volumeTypeId)

        self.create_consistencygroup(context, group)
        targetCgName = self.utils.truncate_string(group['id'], TRUNCATE_8)

        if not snapshots:
            exceptionMessage = (_("No source snapshots provided to create "
                                  "consistency group %s.") % targetCgName)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        modelUpdate = {'status': 'available'}

        _poolInstanceName, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))
        try:
            replicationService = self.utils.find_replication_service(
                self.conn, storageSystem)
            if replicationService is None:
                exceptionMessage = (_(
                    "Cannot find replication service on system %s.") %
                    storageSystem)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
            targetCgInstanceName = self._find_consistency_group(
                replicationService, targetCgName)
            LOG.debug("Create CG %(targetCg)s from snapshot.",
                      {'targetCg': targetCgInstanceName})

            for volume, snapshot in zip(volumes, snapshots):
                volumeSizeInbits = int(self.utils.convert_gb_to_bits(
                    snapshot['volume_size']))
                targetVolumeName = 'targetVol'
                volume = {'size': int(self.utils.convert_bits_to_gbs(
                    volumeSizeInbits))}
                if extraSpecs[ISV3]:
                    _rc, volumeDict, _storageSystemName = (
                        self._create_v3_volume(
                            volume, targetVolumeName, volumeSizeInbits,
                            extraSpecs))
                else:
                    _rc, volumeDict, _storageSystemName = (
                        self._create_composite_volume(
                            volume, targetVolumeName, volumeSizeInbits,
                            extraSpecs))
                targetVolumeInstance = self.utils.find_volume_instance(
                    self.conn, volumeDict, targetVolumeName)
                LOG.debug("Create target volume for member snapshot. "
                          "Source snapshot: %(snapshot)s, "
                          "Target volume: %(targetVol)s.",
                          {'snapshot': snapshot['id'],
                           'targetVol': targetVolumeInstance.path})

                self.provision.add_volume_to_cg(self.conn,
                                                replicationService,
                                                targetCgInstanceName,
                                                targetVolumeInstance.path,
                                                targetCgName,
                                                targetVolumeName,
                                                extraSpecs)

            sourceCgName = self.utils.truncate_string(cgsnapshot['id'],
                                                      TRUNCATE_8)
            sourceCgInstanceName = self._find_consistency_group(
                replicationService, sourceCgName)
            if sourceCgInstanceName is None:
                exceptionMessage = (_("Cannot find source CG instance. "
                                      "consistencygroup_id: %s.") %
                                    cgsnapshot['consistencygroup_id'])
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
            relationName = self.utils.truncate_string(group['id'], TRUNCATE_5)
            if extraSpecs[ISV3]:
                self.provisionv3.create_group_replica(
                    self.conn, replicationService, sourceCgInstanceName,
                    targetCgInstanceName, relationName, extraSpecs)
            else:
                self.provision.create_group_replica(
                    self.conn, replicationService, sourceCgInstanceName,
                    targetCgInstanceName, relationName, extraSpecs)
            # Break the replica group relationship.
            rgSyncInstanceName = self.utils.find_group_sync_rg_by_target(
                self.conn, storageSystem, targetCgInstanceName, extraSpecs,
                True)

            if rgSyncInstanceName is not None:
                if extraSpecs[ISV3]:
                    # Operation 9: dissolve for snapVx
                    operation = self.utils.get_num(9, '16')
                    self.provisionv3.break_replication_relationship(
                        self.conn, replicationService, rgSyncInstanceName,
                        operation, extraSpecs)
                else:
                    self.provision.delete_clone_relationship(
                        self.conn, replicationService,
                        rgSyncInstanceName, extraSpecs)
        except Exception as ex:
            modelUpdate['status'] = 'error'
            cgSnapshotId = cgsnapshot['consistencygroup_id']
            volumes_model_update = self.utils.get_volume_model_updates(
                context, db, group['id'], modelUpdate['status'])
            LOG.error(_LE("Exception: %(ex)s."), {'ex': ex})
            exceptionMessage = (_("Failed to create CG %(cgName)s "
                                  "from snapshot %(cgSnapshot)s.")
                                % {'cgName': targetCgName,
                                   'cgSnapshot': cgSnapshotId})
            LOG.error(exceptionMessage)
            return modelUpdate, volumes_model_update

        volumes_model_update = self.utils.get_volume_model_updates(
            context, db, group['id'], modelUpdate['status'])

        return modelUpdate, volumes_model_update

    def _find_ip_protocol_endpoints(self, conn, storageSystemName,
                                    portgroupname):
        """Find the IP protocol endpoint for ISCSI

        :param storageSystemName: the system name
        :param portgroupname: the portgroup name
        :returns: foundIpAddresses
        """
        foundipaddresses = []
        configservice = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        portgroupinstancename = (
            self.masking.find_port_group(conn, configservice, portgroupname))
        iscsiendpointinstancenames = (
            self.utils.get_iscsi_protocol_endpoints(
                conn, portgroupinstancename))

        for iscsiendpointinstancename in iscsiendpointinstancenames:
            tcpendpointinstancenames = (
                self.utils.get_tcp_protocol_endpoints(
                    conn, iscsiendpointinstancename))
            for tcpendpointinstancename in tcpendpointinstancenames:
                ipendpointinstancenames = (
                    self.utils.get_ip_protocol_endpoints(
                        conn, tcpendpointinstancename))
                for ipendpointinstancename in ipendpointinstancenames:
                    ipaddress = (
                        self.utils.get_iscsi_ip_address(
                            conn, ipendpointinstancename))
                    foundipaddresses.append(ipaddress)
        return foundipaddresses
