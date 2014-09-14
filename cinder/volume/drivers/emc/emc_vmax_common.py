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

import os.path

from oslo.config import cfg
import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.emc import emc_vmax_fast
from cinder.volume.drivers.emc import emc_vmax_masking
from cinder.volume.drivers.emc import emc_vmax_provision
from cinder.volume.drivers.emc import emc_vmax_utils


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

    stats = {'driver_version': '1.0',
             'free_capacity_gb': 0,
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 0,
             'vendor_name': 'EMC',
             'volume_backend_name': None}

    def __init__(self, prtcl, configuration=None):

        if not pywbemAvailable:
            LOG.info(_(
                'Module PyWBEM not installed.  '
                'Install PyWBEM using the python-pywbem package.'))

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

    def create_volume(self, volume):
        """Creates a EMC(VMAX) volume from a pre-existing storage pool.

        For a concatenated compositeType:
        If the volume size is over 240GB then a composite is created
        EMCNumberOfMembers > 1, otherwise it defaults to a non composite

        For a striped compositeType:
        The user must supply an extra spec to determine how many metas
        will make up the striped volume.If the meta size is greater than
        240GB an error is returned to the user. Otherwise the
        EMCNumberOfMembers is what the user specifies.

        :param volume: volume Object
        :returns: volumeInstance, the volume instance
        :raises: VolumeBackendAPIException
        """
        volumeSize = int(self.utils.convert_gb_to_bits(volume['size']))
        volumeName = volume['name']

        extraSpecs = self._initial_setup(volume)
        memberCount, errorDesc = self.utils.determine_member_count(
            volume['size'], extraSpecs[MEMBERCOUNT], extraSpecs[COMPOSITETYPE])
        if errorDesc is not None:
            exceptionMessage = (_("The striped meta count of %(memberCount)s "
                                  "is too small for volume: %(volumeName)s. "
                                  "with size %(volumeSize)s ")
                                % {'memberCount': memberCount,
                                   'volumeName': volumeName,
                                   'volumeSize': volume['size']})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        self.conn = self._get_ecom_connection()

        poolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(extraSpecs))

        LOG.debug("Create Volume: %(volume)s  Pool: %(pool)s  "
                  "Storage System: %(storageSystem)s "
                  "Size: %(size)lu "
                  % {'volume': volumeName,
                     'pool': poolInstanceName,
                     'storageSystem': storageSystemName,
                     'size': volumeSize})

        elementCompositionService = (
            self.utils.find_element_composition_service(self.conn,
                                                        storageSystemName))

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)

        # If FAST is intended to be used we must first check that the pool
        # is associated with the correct storage tier
        if extraSpecs[FASTPOLICY] is not None:
            foundPoolInstanceName = self.fast.get_pool_associated_to_policy(
                self.conn, extraSpecs[FASTPOLICY], extraSpecs[ARRAY],
                storageConfigService, poolInstanceName)
            if foundPoolInstanceName is None:
                exceptionMessage = (_("Pool: %(poolName)s. "
                                      "is not associated to storage tier for "
                                      "fast policy %(fastPolicy)s.")
                                    % {'poolName': extraSpecs[POOL],
                                       'fastPolicy': extraSpecs[FASTPOLICY]})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        compositeType = self.utils.get_composite_type(
            extraSpecs[COMPOSITETYPE])

        volumeDict, rc = self.provision.create_composite_volume(
            self.conn, elementCompositionService, volumeSize, volumeName,
            poolInstanceName, compositeType, memberCount)

        # Now that we have already checked that the pool is associated with
        # the correct storage tier and the volume was successfully created
        # add the volume to the default storage group created for
        # volumes in pools associated with this fast policy
        if extraSpecs[FASTPOLICY]:
            LOG.info(_("Adding volume: %(volumeName)s to default storage group"
                       " for FAST policy: %(fastPolicyName)s ")
                     % {'volumeName': volumeName,
                        'fastPolicyName': extraSpecs[FASTPOLICY]})
            defaultStorageGroupInstanceName = (
                self._get_or_create_default_storage_group(
                    self.conn, storageSystemName, volumeDict,
                    volumeName, extraSpecs[FASTPOLICY]))
            if not defaultStorageGroupInstanceName:
                exceptionMessage = (_(
                    "Unable to create or get default storage group for "
                    "FAST policy: %(fastPolicyName)s. ")
                    % {'fastPolicyName': extraSpecs[FASTPOLICY]})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            self._add_volume_to_default_storage_group_on_create(
                volumeDict, volumeName, storageConfigService,
                storageSystemName, extraSpecs[FASTPOLICY])

        LOG.info(_("Leaving create_volume: %(volumeName)s  "
                   "Return code: %(rc)lu "
                   "volume dict: %(name)s")
                 % {'volumeName': volumeName,
                    'rc': rc,
                    'name': volumeDict})

        return volumeDict

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        For VMAX, replace snapshot with clone.

        :param volume - volume Object
        :param snapshot - snapshot object
        :returns: cloneVolumeDict - the cloned volume dictionary
        """
        return self._create_cloned_volume(volume, snapshot)

    def create_cloned_volume(self, cloneVolume, sourceVolume):
        """Creates a clone of the specified volume.

        :param CloneVolume - clone volume Object
        :param sourceVolume - volume object
        :returns: cloneVolumeDict - the cloned volume dictionary
        """
        return self._create_cloned_volume(cloneVolume, sourceVolume)

    def delete_volume(self, volume):
        """Deletes a EMC(VMAX) volume

        :param volume: volume Object
        """
        LOG.info(_("Deleting Volume: %(volume)s")
                 % {'volume': volume['name']})

        rc, volumeName = self._delete_volume(volume)
        LOG.info(_("Leaving delete_volume: %(volumename)s  Return code: "
                   "%(rc)lu")
                 % {'volumename': volumeName,
                    'rc': rc})

    def create_snapshot(self, snapshot, volume):
        """Creates a snapshot.

        For VMAX, replace snapshot with clone

        :param snapshot: snapshot object
        :param volume: volume Object to create snapshot from
        :returns: cloneVolumeDict,the cloned volume dictionary
        """
        return self._create_cloned_volume(snapshot, volume, True)

    def delete_snapshot(self, snapshot, volume):
        """Deletes a snapshot.

        :param snapshot: snapshot object
        :param volume: volume Object to create snapshot from
        """
        LOG.info(_("Delete Snapshot: %(snapshotName)s ")
                 % {'snapshotName': snapshot['name']})
        rc, snapshotName = self._delete_volume(snapshot)
        LOG.debug("Leaving delete_snapshot: %(snapshotname)s  Return code: "
                  "%(rc)lu "
                  % {'snapshotname': snapshotName,
                     'rc': rc})

    def _remove_members(
            self, controllerConfigService, volumeInstance, extraSpecs):
        """This method unmaps a volume from a host.

        Removes volume from the Device Masking Group that belongs to
        a Masking View.
        Check if fast policy is in the extra specs, if it isn't we do
        not need to do any thing for FAST
        Assume that isTieringPolicySupported is False unless the FAST
        policy is in the extra specs and tiering is enabled on the array

        :param controllerConfigService: instance name of
                                  ControllerConfigurationService
        :param volume: volume Object
        """
        volumeName = volumeInstance['ElementName']
        LOG.debug("Detaching volume %s" % volumeName)
        fastPolicyName = extraSpecs[FASTPOLICY]
        return self.masking.remove_and_reset_members(
            self.conn, controllerConfigService, volumeInstance,
            fastPolicyName, volumeName)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host.

        :param volume: the volume Object
        :param connector: the connector Object
        :raises: VolumeBackendAPIException
        """
        extraSpecs = self._initial_setup(volume)
        volumename = volume['name']
        LOG.info(_("Unmap volume: %(volume)s")
                 % {'volume': volumename})

        device_info = self.find_device_number(volume, connector)
        device_number = device_info['hostlunid']
        if device_number is None:
            LOG.info(_("Volume %s is not mapped. No volume to unmap.")
                     % (volumename))
            return

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        configservice = self.utils.find_controller_configuration_service(
            self.conn, storage_system)
        if configservice is None:
            exception_message = (_("Cannot find Controller Configuration "
                                   "Service for storage system "
                                   "%(storage_system)s")
                                 % {'storage_system': storage_system})
            raise exception.VolumeBackendAPIException(data=exception_message)

        self._remove_members(configservice, vol_instance, extraSpecs)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns device and connection info.

        The volume may be already mapped, if this is so the deviceInfo tuple
        is returned.  If the volume is not already mapped then we need to
        gather information to either 1. Create an new masking view or 2.Add
        the volume to to an existing storage group within an already existing
        maskingview.

        The naming convention is the following:
        initiatorGroupName = OS-<shortHostName>-<shortProtocol>-IG
                             e.g OS-myShortHost-I-IG
        storageGroupName = OS-<shortHostName>-<poolName>-<shortProtocol>-SG
                           e.g OS-myShortHost-SATA_BRONZ1-I-SG
        portGroupName = OS-<target>-PG  The portGroupName will come from
                        the EMC configuration xml file.
                        These are precreated. If the portGroup does not exist
                        then a error will be returned to the user
        maskingView  = OS-<shortHostName>-<poolName>-<shortProtocol>-MV
                       e.g OS-myShortHost-SATA_BRONZ1-I-MV

        :param volume: volume Object
        :param connector: the connector Object
        :returns: deviceInfoDict, device information tuple
        :raises: VolumeBackendAPIException
        """
        extraSpecs = self._initial_setup(volume)

        volumeName = volume['name']
        LOG.info(_("Initialize connection: %(volume)s")
                 % {'volume': volumeName})
        self.conn = self._get_ecom_connection()
        deviceInfoDict = self._wrap_find_device_number(volume, connector)
        if ('hostlunid' in deviceInfoDict and
                deviceInfoDict['hostlunid'] is not None):
            # Device is already mapped so we will leave the state as is
            deviceNumber = deviceInfoDict['hostlunid']
            LOG.info(_("Volume %(volume)s is already mapped. "
                       "The device number is  %(deviceNumber)s ")
                     % {'volume': volumeName,
                        'deviceNumber': deviceNumber})
        else:
            maskingViewDict = self._populate_masking_dict(
                volume, connector, extraSpecs)
            rollbackDict = self.masking.get_or_create_masking_view_and_map_lun(
                self.conn, maskingViewDict)

            # Find host lun id again after the volume is exported to the host
            deviceInfoDict = self.find_device_number(volume, connector)
            if 'hostlunid' not in deviceInfoDict:
                # Did not successfully attach to host,
                # so a rollback for FAST is required
                LOG.error(_("Error Attaching volume %(vol)s ")
                          % {'vol': volumeName})
                if rollbackDict['fastPolicyName'] is not None:
                    (
                        self.masking
                        ._check_if_rollback_action_for_masking_required(
                            self.conn,
                            rollbackDict['controllerConfigService'],
                            rollbackDict['volumeInstance'],
                            rollbackDict['volumeName'],
                            rollbackDict['fastPolicyName'],
                            rollbackDict['defaultStorageGroupInstanceName']))
                exception_message = ("Error Attaching volume %(vol)s"
                                     % {'vol': volumeName})
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        return deviceInfoDict

    def _wrap_find_device_number(self, volume, connector):
        """Aid for unit testing

        :params volume: the volume Object
        :params connector: the connector Object
        :returns: deviceInfoDict
        """
        return self.find_device_number(volume, connector)

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector.

        :params volume: the volume Object
        :params connectorL the connector Object
        """
        self._initial_setup(volume)

        volumename = volume['name']
        LOG.info(_("Terminate connection: %(volume)s")
                 % {'volume': volumename})

        self.conn = self._get_ecom_connection()
        self._unmap_lun(volume, connector)

    def extend_volume(self, volume, newSize):
        """Extends an existing volume.

        Prequisites:
        1. The volume must be composite e.g StorageVolume.EMCIsComposite=True
        2. The volume can only be concatenated
           e.g StorageExtent.IsConcatenated=True

        :params volume: the volume Object
        :params newSize: the new size to increase the volume to
        :raises: VolumeBackendAPIException
        """
        originalVolumeSize = volume['size']
        volumeName = volume['name']
        self._initial_setup(volume)
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

        # is the volume concatenated
        isConcatenated = self.utils.check_if_volume_is_concatenated(
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

        LOG.debug("Extend Volume: %(volume)s  New size: %(newSize)s GBs"
                  % {'volume': volumeName,
                     'newSize': newSize})

        deviceId = volumeInstance['DeviceID']
        storageSystemName = volumeInstance['SystemName']
        LOG.debug(
            "Device ID: %(deviceid)s: Storage System: "
            "%(storagesystem)s"
            % {'deviceid': deviceId,
               'storagesystem': storageSystemName})

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)

        elementCompositionService = (
            self.utils.find_element_composition_service(
                self.conn, storageSystemName))

        # create a volume to the size of the
        # newSize - oldSize = additionalVolumeSize
        unboundVolumeInstance = self._create_and_get_unbound_volume(
            self.conn, storageConfigService, volumeInstance.path,
            additionalVolumeSize)
        if unboundVolumeInstance is None:
            exceptionMessage = (_(
                "Error Creating unbound volume on an Extend operation"))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        # add the new unbound volume to the original composite volume
        rc, modifiedVolumeDict = (
            self._modify_and_get_composite_volume_instance(
                self.conn, elementCompositionService, volumeInstance,
                unboundVolumeInstance.path, volumeName, compositeType))
        if modifiedVolumeDict is None:
            exceptionMessage = (_(
                "On an Extend Operation, error adding volume to composite "
                "volume: %(volumename)s. ")
                % {'volumename': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        # check the occupied space of the new extended volume
        extendedVolumeInstance = self.utils.find_volume_instance(
            self.conn, modifiedVolumeDict, volumeName)
        extendedVolumeSize = self.utils.get_volume_size(
            self.conn, extendedVolumeInstance)
        LOG.debug(
            "The actual volume size of the extended volume: %(volumeName)s "
            "is %(volumeSize)s"
            % {'volumeName': volumeName,
               'volumeSize': extendedVolumeSize})

        # If the requested size and the actual size don't
        # tally throw an exception
        newSizeBits = self.utils.convert_gb_to_bits(newSize)
        diffVolumeSize = self.utils.compare_size(
            newSizeBits, extendedVolumeSize)
        if diffVolumeSize != 0:
            exceptionMessage = (_(
                "The requested size : %(requestedSize)s is not the same as "
                "resulting size: %(resultSize)s")
                % {'requestedSize': newSizeBits,
                   'resultSize': extendedVolumeSize})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug(
            "Leaving extend_volume: %(volumeName)s  "
            "Return code: %(rc)lu "
            "volume dict: %(name)s"
            % {'volumeName': volumeName,
               'rc': rc,
               'name': modifiedVolumeDict})

        return modifiedVolumeDict

    def update_volume_stats(self):
        """Retrieve stats info.
        """
        if hasattr(self.configuration, 'cinder_emc_config_file'):
            emcConfigFileName = self.configuration.cinder_emc_config_file
        else:
            emcConfigFileName = self.configuration.safe_get(
                'cinder_emc_config_file')

        backendName = self.configuration.safe_get('volume_backend_name')
        LOG.debug(
            "Updating volume stats on file %(emcConfigFileName)s on "
            "backend %(backendName)s "
            % {'emcConfigFileName': emcConfigFileName,
               'backendName': backendName})

        poolName = self.utils.parse_pool_name_from_file(emcConfigFileName)
        if poolName is None:
            LOG.error(_(
                "PoolName %(poolName)s must be in the file "
                "%(emcConfigFileName)s ")
                % {'poolName': poolName,
                   'emcConfigFileName': emcConfigFileName})
        arrayName = self.utils.parse_array_name_from_file(emcConfigFileName)
        if arrayName is None:
            LOG.error(_(
                "Array Serial Number %(arrayName)s must be in the file "
                "%(emcConfigFileName)s ")
                % {'arrayName': arrayName,
                   'emcConfigFileName': emcConfigFileName})
        # This value can be None
        fastPolicyName = self.utils.parse_fast_policy_name_from_file(
            emcConfigFileName)
        if fastPolicyName is not None:
            LOG.debug(
                "Fast policy %(fastPolicyName)s is enabled on %(arrayName)s. "
                % {'fastPolicyName': fastPolicyName,
                   'arrayName': arrayName})
        else:
            LOG.debug(
                "No Fast policy for Array:%(arrayName)s "
                "backend:%(backendName)s"
                % {'arrayName': arrayName,
                   'backendName': backendName})

        if self.conn is None:
            self._set_ecom_credentials(emcConfigFileName)

        storageSystemInstanceName = self._find_storageSystem(arrayName)
        isTieringPolicySupported = (
            self.fast.is_tiering_policy_enabled_on_storage_system(
                self.conn, storageSystemInstanceName))

        if (fastPolicyName is not None and
                isTieringPolicySupported is True):  # FAST enabled
            total_capacity_gb, free_capacity_gb = (
                self.fast.get_capacities_associated_to_policy(
                    self.conn, arrayName, fastPolicyName))
            LOG.info(
                "FAST: capacity stats for policy %(fastPolicyName)s on "
                "array %(arrayName)s (total_capacity_gb=%(total_capacity_gb)lu"
                ", free_capacity_gb=%(free_capacity_gb)lu"
                % {'fastPolicyName': fastPolicyName,
                   'arrayName': arrayName,
                   'total_capacity_gb': total_capacity_gb,
                   'free_capacity_gb': free_capacity_gb})
        else:  # NON-FAST
            total_capacity_gb, free_capacity_gb = (
                self.utils.get_pool_capacities(self.conn, poolName, arrayName))
            LOG.info(
                "NON-FAST: capacity stats for pool %(poolName)s on array "
                "%(arrayName)s (total_capacity_gb=%(total_capacity_gb)lu, "
                "free_capacity_gb=%(free_capacity_gb)lu"
                % {'poolName': poolName,
                   'arrayName': arrayName,
                   'total_capacity_gb': total_capacity_gb,
                   'free_capacity_gb': free_capacity_gb})

        if poolName is None:
            LOG.debug("Unable to get the poolName for location_info")
        if arrayName is None:
            LOG.debug("Unable to get the arrayName for location_info")
        if fastPolicyName is None:
            LOG.debug("FAST is not enabled for this configuration: "
                      "%(emcConfigFileName)s"
                      % {'emcConfigFileName': emcConfigFileName})

        location_info = ("%(arrayName)s#%(poolName)s#%(policyName)s"
                         % {'arrayName': arrayName,
                            'poolName': poolName,
                            'policyName': fastPolicyName})

        data = {'total_capacity_gb': total_capacity_gb,
                'free_capacity_gb': free_capacity_gb,
                'reserved_percentage': 0,
                'QoS_support': False,
                'volume_backend_name': backendName or self.__class__.__name__,
                'vendor_name': "EMC",
                'driver_version': '2.0',
                'storage_protocol': 'unknown',
                'location_info': location_info}

        self.stats = data

        return self.stats

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param host: The host dict holding the relevant target(destination)
               information
        :returns: boolean True/False
        :returns: list
        """

        volumeName = volume['name']
        volumeStatus = volume['status']
        LOG.info(_("Migrating using retype Volume: %(volume)s")
                 % {'volume': volumeName})

        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            LOG.error(_("Volume %(name)s not found on the array. "
                        "No volume to migrate using retype.")
                      % {'name': volumeName})
            return False

        storageSystemName = volumeInstance['SystemName']
        isValid, targetPoolName, targetFastPolicyName = (
            self._is_valid_for_storage_assisted_migration(
                volumeInstance.path, host, storageSystemName,
                volumeName, volumeStatus))

        if not isValid:
            LOG.error(_("Volume %(name)s is not suitable for storage "
                        "assisted migration using retype")
                      % {'name': volumeName})
            return False
        if volume['host'] != host['host']:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s"
                % {'name': volumeName,
                   'sourceHost': volume['host'],
                   'targetHost': host['host']})
            return self._migrate_volume(
                volume, volumeInstance, targetPoolName, targetFastPolicyName,
                extraSpecs[FASTPOLICY], new_type)

        return True

    def migrate_volume(self, ctxt, volume, host, new_type=None):
        """Migrate volume to another host

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param host: the host dict holding the relevant target(destination)
               information
        :param new_type: None
        :returns: boolean True/False
        :returns: list
        """
        LOG.warn(_("The VMAX plugin only supports Retype.  "
                   "If a pool based migration is necessary "
                   "this will happen on a Retype "
                   "From the command line: "
                   "cinder --os-volume-api-version 2 retype "
                   "<volumeId> <volumeType> --migration-policy on-demand"))
        return True, {}

    def _migrate_volume(
            self, volume, volumeInstance, targetPoolName,
            targetFastPolicyName, sourceFastPolicyName, new_type=None):
        """Migrate volume to another host

        :param volume: the volume object including the volume_type_id
        :param volumeInstance: the volume instance
        :param targetPoolName: the target poolName
        :param targetFastPolicyName: the target FAST policy name, can be None
        :param sourceFastPolicyName: the source FAST policy name, can be None
        :param new_type: None
        :returns:  boolean True/False
        :returns:  empty list
        """
        volumeName = volume['name']
        storageSystemName = volumeInstance['SystemName']

        sourcePoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstance.path)

        moved, rc = self._migrate_volume_from(
            volume, volumeInstance, targetPoolName, sourceFastPolicyName)

        if moved is False and sourceFastPolicyName is not None:
            # Return the volume to the default source fast policy storage
            # group because the migrate was unsuccessful
            LOG.warn(_("Failed to migrate: %(volumeName)s from "
                       "default source storage group "
                       "for FAST policy: %(sourceFastPolicyName)s "
                       "Attempting cleanup... ")
                     % {'volumeName': volumeName,
                        'sourceFastPolicyName': sourceFastPolicyName})
            if sourcePoolInstanceName == self.utils.get_assoc_pool_from_volume(
                    self.conn, volumeInstance.path):
                self._migrate_cleanup(self.conn, volumeInstance,
                                      storageSystemName, sourceFastPolicyName,
                                      volumeName)
            else:
                # migrate was successful but still issues
                self._migrate_rollback(
                    self.conn, volumeInstance, storageSystemName,
                    sourceFastPolicyName, volumeName, sourcePoolInstanceName)

            return moved

        if targetFastPolicyName == 'None':
            targetFastPolicyName = None

        if moved is True and targetFastPolicyName is not None:
            if not self._migrate_volume_fast_target(
                    volumeInstance, storageSystemName,
                    targetFastPolicyName, volumeName):
                LOG.warn(_("Attempting a rollback of: %(volumeName)s to "
                           "original pool %(sourcePoolInstanceName)s ")
                         % {'volumeName': volumeName,
                            'sourcePoolInstanceName': sourcePoolInstanceName})
                self._migrate_rollback(
                    self.conn, volumeInstance, storageSystemName,
                    sourceFastPolicyName, volumeName, sourcePoolInstanceName)

        if rc == 0:
            moved = True

        return moved

    def _migrate_rollback(self, conn, volumeInstance,
                          storageSystemName, sourceFastPolicyName,
                          volumeName, sourcePoolInstanceName):
        """Full rollback

        Failed on final step on adding migrated volume to new target
        default storage group for the target FAST policy

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name

        :returns: boolean True/False
        :returns: int, the return code from migrate operation
        """

        LOG.warn(_("_migrate_rollback on : %(volumeName)s from ")
                 % {'volumeName': volumeName})

        storageRelocationService = self.utils.find_storage_relocation_service(
            conn, storageSystemName)

        try:
            self.provision.migrate_volume_to_storage_pool(
                conn, storageRelocationService, volumeInstance.path,
                sourcePoolInstanceName)
        except Exception:
            exceptionMessage = (_(
                "Failed to return volume %(volumeName)s to "
                "original storage pool. Please contact your system "
                "administrator to return it to the correct location ")
                % {'volumeName': volumeName})
            LOG.error(exceptionMessage)

        if sourceFastPolicyName is not None:
            self.add_to_default_SG(
                conn, volumeInstance, storageSystemName, sourceFastPolicyName,
                volumeName)

    def _migrate_cleanup(self, conn, volumeInstance,
                         storageSystemName, sourceFastPolicyName,
                         volumeName):
        """If the migrate fails, put volume back to source FAST SG

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name

        :returns: boolean True/False
        :returns: int, the return code from migrate operation
        """

        LOG.warn(_("_migrate_cleanup on : %(volumeName)s from ")
                 % {'volumeName': volumeName})

        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))

        # check to see what SG it is in
        assocStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(conn,
                                                     volumeInstance.path))
        # This is the SG it should be in
        defaultStorageGroupInstanceName = (
            self.fast.get_policy_default_storage_group(
                conn, controllerConfigurationService, sourceFastPolicyName))

        # It is not in any storage group.  Must add it to default source
        if assocStorageGroupInstanceName is None:
            self.add_to_default_SG(conn, volumeInstance,
                                   storageSystemName, sourceFastPolicyName,
                                   volumeName)

        # It is in the incorrect storage group
        if (assocStorageGroupInstanceName is not None and
                (assocStorageGroupInstanceName !=
                    defaultStorageGroupInstanceName)):
            self.provision.remove_device_from_storage_group(
                conn, controllerConfigurationService,
                assocStorageGroupInstanceName, volumeInstance.path, volumeName)

            self.add_to_default_SG(
                conn, volumeInstance, storageSystemName, sourceFastPolicyName,
                volumeName)

    def _migrate_volume_fast_target(
            self, volumeInstance, storageSystemName,
            targetFastPolicyName, volumeName):
        """If the target host is FAST enabled.

        If the target host is FAST enabled then we need to add it to the
        default storage group for that policy

        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param targetFastPolicyName: the target fast policy name
        :param volumeName: the volume name
        :returns: boolean True/False
        """
        falseRet = False
        LOG.info(_("Adding volume: %(volumeName)s to default storage group "
                   "for FAST policy: %(fastPolicyName)s ")
                 % {'volumeName': volumeName,
                    'fastPolicyName': targetFastPolicyName})

        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        defaultStorageGroupInstanceName = (
            self.fast.get_or_create_default_storage_group(
                self.conn, controllerConfigurationService,
                targetFastPolicyName, volumeInstance))
        if defaultStorageGroupInstanceName is None:
            exceptionMessage = (_(
                "Unable to create or get default storage group for FAST policy"
                ": %(fastPolicyName)s. ")
                % {'fastPolicyName': targetFastPolicyName})
            LOG.error(exceptionMessage)

            return falseRet

        defaultStorageGroupInstanceName = (
            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                self.conn, controllerConfigurationService, volumeInstance,
                volumeName, targetFastPolicyName))
        if defaultStorageGroupInstanceName is None:
            exceptionMessage = (_(
                "Failed to verify that volume was added to storage group for "
                "FAST policy: %(fastPolicyName)s. ")
                % {'fastPolicyName': targetFastPolicyName})
            LOG.error(exceptionMessage)
            return falseRet

        return True

    def _migrate_volume_from(self, volume, volumeInstance,
                             targetPoolName, sourceFastPolicyName):
        """Check FAST policies and migrate from source pool

        :param volume: the volume object including the volume_type_id
        :param volumeInstance: the volume instance
        :param targetPoolName: the target poolName
        :param sourceFastPolicyName: the source FAST policy name, can be None
        :returns: boolean True/False
        :returns: int, the return code from migrate operation
        """
        falseRet = (False, -1)
        volumeName = volume['name']
        storageSystemName = volumeInstance['SystemName']

        LOG.debug("sourceFastPolicyName is : %(sourceFastPolicyName)s. "
                  % {'sourceFastPolicyName': sourceFastPolicyName})

        # If the source volume is is FAST enabled it must first be removed
        # from the default storage group for that policy
        if sourceFastPolicyName is not None:
            self.remove_from_default_SG(
                self.conn, volumeInstance, storageSystemName,
                sourceFastPolicyName, volumeName)

        # migrate from one pool to another
        storageRelocationService = self.utils.find_storage_relocation_service(
            self.conn, storageSystemName)

        targetPoolInstanceName = self.utils.get_pool_by_name(
            self.conn, targetPoolName, storageSystemName)
        if targetPoolInstanceName is None:
            exceptionMessage = (_(
                "Error finding targe pool instance name for pool: "
                "%(targetPoolName)s. ")
                % {'targetPoolName': targetPoolName})
            LOG.error(exceptionMessage)
            return falseRet
        try:
            rc = self.provision.migrate_volume_to_storage_pool(
                self.conn, storageRelocationService, volumeInstance.path,
                targetPoolInstanceName)
        except Exception as e:
            # rollback by deleting the volume if adding the volume to the
            # default storage group were to fail
            LOG.error(_("Exception: %s") % six.text_type(e))
            exceptionMessage = (_("Error migrating volume: %(volumename)s. "
                                  "to target pool  %(targetPoolName)s. ")
                                % {'volumename': volumeName,
                                   'targetPoolName': targetPoolName})
            LOG.error(exceptionMessage)
            return falseRet

        # check that the volume is now migrated to the correct storage pool,
        # if it is terminate the migrate session
        foundPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstance.path)

        if (foundPoolInstanceName is None or
                (foundPoolInstanceName['InstanceID'] !=
                    targetPoolInstanceName['InstanceID'])):
            exceptionMessage = (_(
                "Volume : %(volumeName)s. was not successfully migrated to "
                "target pool %(targetPoolName)s.")
                % {'volumeName': volumeName,
                   'targetPoolName': targetPoolName})
            LOG.error(exceptionMessage)
            return falseRet

        else:
            LOG.debug("Terminating migration session on : %(volumeName)s. "
                      % {'volumeName': volumeName})
            self.provision._terminate_migrate_session(
                self.conn, volumeInstance.path)

        if rc == 0:
            moved = True

        return moved, rc

    def remove_from_default_SG(
            self, conn, volumeInstance, storageSystemName,
            sourceFastPolicyName, volumeName):
        """For FAST, remove volume from default storage group

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param sourceFastPolicyName: the source FAST policy name
        :param volumeName: the volume Name

        :returns: boolean True/False
        :returns: int, the return code from migrate operation
        """
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        try:
            defaultStorageGroupInstanceName = (
                self.masking.remove_device_from_default_storage_group(
                    conn, controllerConfigurationService,
                    volumeInstance.path, volumeName, sourceFastPolicyName))
        except Exception as ex:
            LOG.error(_("Exception: %s") % six.text_type(ex))
            exceptionMessage = (_("Failed to remove: %(volumename)s. "
                                  "from the default storage group for "
                                  "FAST policy %(fastPolicyName)s. ")
                                % {'volumename': volumeName,
                                   'fastPolicyName': sourceFastPolicyName})

            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if defaultStorageGroupInstanceName is None:
            warnMessage = (_("The volume: %(volumename)s. "
                             "was not first part of the default storage "
                             "group for FAST policy %(fastPolicyName)s.")
                           % {'volumename': volumeName,
                              'fastPolicyName': sourceFastPolicyName})
            LOG.warn(warnMessage)

    def add_to_default_SG(
            self, conn, volumeInstance, storageSystemName,
            targetFastPolicyName, volumeName):
        """For FAST, add volume to default storage group

        :param conn: connection info to ECOM
        :param volumeInstance: the volume instance
        :param storageSystemName: the storage system name
        :param targetFastPolicyName: the target FAST policy name
        :param volumeName: the volume Name

        :returns: boolean True/False
        :returns: int, the return code from migrate operation
        """
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        assocDefaultStorageGroupName = (
            self.fast
            .add_volume_to_default_storage_group_for_fast_policy(
                conn, controllerConfigurationService, volumeInstance,
                volumeName, targetFastPolicyName))
        if assocDefaultStorageGroupName is None:
            errorMsg = (_(
                "Failed to add %(volumeName)s "
                "to default storage group for fast policy "
                "%(fastPolicyName)s ")
                % {'volumeName': volumeName,
                   'fastPolicyName': targetFastPolicyName})
            LOG.error(errorMsg)

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
        :returns: boolean, True/False
        :returns: string, targetPool
        :returns: string, targetFastPolicy
        """
        falseRet = (False, None, None)
        if 'location_info' not in host['capabilities']:
            LOG.error(_('Error getting target pool name and array'))
            return falseRet
        info = host['capabilities']['location_info']

        LOG.debug("Location info is : %(info)s."
                  % {'info': info})
        try:
            infoDetail = info.split('#')
            targetArraySerialNumber = infoDetail[0]
            targetPoolName = infoDetail[1]
            targetFastPolicy = infoDetail[2]
        except Exception:
            LOG.error(_("Error parsing target pool name, array, "
                        "and fast policy"))

        if targetArraySerialNumber not in sourceArraySerialNumber:
            errorMessage = (_(
                "The source array : %(sourceArraySerialNumber)s does not "
                "match the target array: %(targetArraySerialNumber)s"
                "skipping storage-assisted migration")
                % {'sourceArraySerialNumber': sourceArraySerialNumber,
                   'targetArraySerialNumber': targetArraySerialNumber})
            LOG.error(errorMessage)
            return falseRet

        # get the pool from the source array and check that is is different
        # to the pool in the target array
        assocPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            self.conn, volumeInstanceName)
        assocPoolInstance = self.conn.GetInstance(
            assocPoolInstanceName)
        if assocPoolInstance['ElementName'] == targetPoolName:
            errorMessage = (_("No action required. Volume : %(volumeName)s is "
                              "already part of pool : %(pool)s")
                            % {'volumeName': volumeName,
                               'pool': targetPoolName})
            LOG.error(errorMessage)
            return falseRet

        LOG.info("Volume status is: %s" % volumeStatus)
        if (host['capabilities']['storage_protocol'] != self.protocol and
                (volumeStatus != 'available' and volumeStatus != 'retyping')):
            errorMessage = (_(
                "Only available volumes can be migrated between "
                "different protocols"))
            LOG.error(errorMessage)
            return falseRet

        return (True, targetPoolName, targetFastPolicy)

    def _set_config_file_and_get_extra_specs(self, volume, filename=None):
        """Given the volume object get the associated volumetype.

        Given the volume object get the associated volumetype and the
        extra specs associated with it.
        Based on the name of the config group, register the config file

        :param volume: the volume object including the volume_type_id
        :returns: tuple the extra specs tuple
        :returns: string configuration file
        """
        extraSpecs = self.utils.get_volumetype_extraspecs(volume)
        configGroup = None

        # If there are no extra specs then the default case is assumed
        if extraSpecs:
            configGroup = self.configuration.config_group
            LOG.info("configGroup of current host: %s" % configGroup)

        configurationFile = self._register_config_file_from_config_group(
            configGroup)

        return extraSpecs, configurationFile

    def _get_ecom_connection(self):
        """Get the ecom connection

        :returns: conn,the ecom connection
        """
        conn = pywbem.WBEMConnection(self.url, (self.user, self.passwd),
                                     default_namespace='root/emc')
        if conn is None:
            exception_message = (_("Cannot connect to ECOM server"))
            raise exception.VolumeBackendAPIException(data=exception_message)

        return conn

    def _find_storageSystem(self, arrayStr):
        """Find an array instance name given the array name.

        :param arrayStr: the array Serial number (String)
        :returns: foundPoolInstanceName, the CIM Instance Name of the Pool
        """
        foundStorageSystemInstanceName = None
        storageSystemInstanceNames = self.conn.EnumerateInstanceNames(
            'EMC_StorageSystem')
        for storageSystemInstanceName in storageSystemInstanceNames:
            arrayName = storageSystemInstanceName['Name']
            index = arrayName.find(arrayStr)
            if index > -1:
                foundStorageSystemInstanceName = storageSystemInstanceName

        if foundStorageSystemInstanceName is None:
            exceptionMessage = (_("StorageSystem %(array)s is not found.")
                                % {'storage_array': arrayStr})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug("Array Found: %(array)s.."
                  % {'array': arrayStr})

        return foundStorageSystemInstanceName

    def _find_pool_in_array(self, arrayStr, poolNameInStr):
        """Find a pool based on the pool name on a given array.

        :param arrayStr: the array Serial number (String)
        :parampoolNameInStr: the name of the poolname (String)
        :returns: foundPoolInstanceName, the CIM Instance Name of the Pool
        """
        foundPoolInstanceName = None
        systemNameStr = None

        storageSystemInstanceName = self._find_storageSystem(arrayStr)

        vpools = self.conn.AssociatorNames(
            storageSystemInstanceName,
            resultClass='EMC_VirtualProvisioningPool')

        for vpool in vpools:
            poolinstance = vpool['InstanceID']
            # Example: SYMMETRIX+000195900551+TP+Sol_Innov
            poolnameStr, systemNameStr = self.utils.parse_pool_instance_id(
                poolinstance)
            if poolnameStr is not None and systemNameStr is not None:
                if six.text_type(poolNameInStr) == six.text_type(poolnameStr):
                    foundPoolInstanceName = vpool
                    break

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

        LOG.debug("Pool: %(pool)s  SystemName: %(systemname)s."
                  % {'pool': foundPoolInstanceName,
                     'systemname': systemNameStr})
        return foundPoolInstanceName, systemNameStr

    def _find_lun(self, volume):
        """Given the volume get the instance from it.

        :param conn: connection the the ecom server
        :param volume: volume object
        :returns: foundVolumeinstance
        """
        foundVolumeinstance = None
        volumename = volume['name']

        loc = volume['provider_location']
        if isinstance(loc, six.string_types):
            name = eval(loc)

            instancename = self.utils.get_instance_name(
                name['classname'], name['keybindings'])

            foundVolumeinstance = self.conn.GetInstance(instancename)

        if foundVolumeinstance is None:
            LOG.debug("Volume %(volumename)s not found on the array."
                      % {'volumename': volumename})
        else:
            LOG.debug("Volume name: %(volumename)s  Volume instance: "
                      "%(foundVolumeinstance)s."
                      % {'volumename': volumename,
                         'foundVolumeinstance': foundVolumeinstance})

        return foundVolumeinstance

    def _find_storage_sync_sv_sv(self, snapshot, volume,
                                 waitforsync=True):
        """Find the storage synchronized name

        :param snapshot: snapshot object
        :param volume: volume object
        :returns: foundsyncname (String)
        :returns: storage_system (String)
        """
        snapshotname = snapshot['name']
        volumename = volume['name']
        LOG.debug("Source: %(volumename)s  Target: %(snapshotname)s."
                  % {'volumename': volumename, 'snapshotname': snapshotname})

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
                self.utils.wait_for_sync(self.conn, foundsyncname)

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

        LOG.debug("Found %(name)s: %(initiator)s."
                  % {'name': name,
                     'initiator': foundinitiatornames})
        return foundinitiatornames

    def find_device_number(self, volume, connector):
        """Given the volume dict find a device number.

        Find a device number  that a host can see
        for a volume

        :param volume: the volume dict
        :param connector: the connector dict
        :returns: data, the data dict

        """
        foundNumDeviceNumber = None
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
                break

        if foundNumDeviceNumber is None:
            LOG.debug(
                "Device number not found for volume "
                "%(volumeName)s %(volumeInstance)s."
                % {'volumeName': volumeName,
                   'volumeInstance': volumeInstance.path})

        data = {'hostlunid': foundNumDeviceNumber,
                'storagesystem': storageSystemName}

        LOG.debug("Device info: %(data)s." % {'data': data})

        return data

    def get_target_wwns(self, storageSystem, connector):
        """Find target WWNs.

        :param storageSystem: the storage system name
        :param connector: the connector dict
        :returns: targetWwns, the target WWN list
        """
        targetWwns = []

        storageHardwareService = self.utils.find_storage_hardwareid_service(
            self.conn, storageSystem)

        hardwareIdInstances = self._find_storage_hardwareids(
            connector, storageHardwareService)

        LOG.debug(
            "EMCGetTargetEndpoints: Service: %(service)s  "
            "Storage HardwareIDs: %(hardwareIds)s."
            % {'service': storageHardwareService,
               'hardwareIds': hardwareIdInstances})

        for hardwareIdInstance in hardwareIdInstances:
            LOG.debug("HardwareID instance is  : %(hardwareIdInstance)s  "
                      % {'hardwareIdInstance': hardwareIdInstance})
            try:
                rc, targetEndpoints = self.provision.get_target_endpoints(
                    self.conn, storageHardwareService, hardwareIdInstance)
            except Exception as ex:
                LOG.error(_("Exception: %s") % six.text_type(ex))
                errorMessage = (_(
                    "Unable to get target endpoints for hardwareId "
                    "%(hardwareIdInstance)s")
                    % {'hardwareIdInstance': hardwareIdInstance})
                LOG.error(errorMessage)
                raise exception.VolumeBackendAPIException(data=errorMessage)

            if targetEndpoints:
                endpoints = targetEndpoints['TargetEndpoints']

                LOG.debug("There are  %(len)lu endpoints "
                          % {'len': len(endpoints)})
                for targetendpoint in endpoints:
                    wwn = targetendpoint['Name']
                    # Add target wwn to the list if it is not already there
                    if not any(d == wwn for d in targetWwns):
                        targetWwns.append(wwn)
            else:
                LOG.error(_(
                    "Target end points do not exist for hardware Id : "
                    "%(hardwareIdInstance)s ")
                    % {'hardwareIdInstance': hardwareIdInstance})

        LOG.debug("Target WWNs: : %(targetWwns)s  "
                  % {'targetWwns': targetWwns})

        return targetWwns

    def _find_storage_hardwareids(
            self, connector, hardwareIdManagementService):
        """Find the storage hardware ID instances.

        :param connector: the connector dict
        :param hardwareIdManagementService: the storage Hardware
                                            management service
        :returns: foundInstances, the list of storage hardware ID instances
        """
        foundInstances = []
        wwpns = self._find_initiator_names(connector)

        hardwareIdInstanceNames = (
            self.utils.get_hardware_id_instance_names_from_array(
                self.conn, hardwareIdManagementService))
        for hardwareIdInstanceName in hardwareIdInstanceNames:
            hardwareIdInstance = self.conn.GetInstance(hardwareIdInstanceName)
            storageId = hardwareIdInstance['StorageID']
            for wwpn in wwpns:
                if wwpn.lower() == storageId.lower():
                    foundInstances.append(hardwareIdInstance.path)
                    break

        LOG.debug("Storage Hardware IDs for %(wwpns)s is "
                  "%(foundInstances)s."
                  % {'wwpns': wwpns,
                     'foundInstances': foundInstances})

        return foundInstances

    def _register_config_file_from_config_group(self, configGroupName):
        """Given the config group name register the file.

        :param configGroupName: the config group name
        :returns: string configurationFile
        """
        if configGroupName is None:
            self._set_ecom_credentials(CINDER_EMC_CONFIG_FILE)
            return CINDER_EMC_CONFIG_FILE
        if hasattr(self.configuration, 'cinder_emc_config_file'):
            configurationFile = self.configuration.cinder_emc_config_file
        else:
            configurationFile = (
                CINDER_EMC_CONFIG_FILE_PREFIX + configGroupName +
                CINDER_EMC_CONFIG_FILE_POSTFIX)

        # The file saved in self.configuration may not be the correct one,
        # double check
        if configGroupName not in configurationFile:
            configurationFile = (
                CINDER_EMC_CONFIG_FILE_PREFIX + configGroupName +
                CINDER_EMC_CONFIG_FILE_POSTFIX)

        self._set_ecom_credentials(configurationFile)
        return configurationFile

    def _set_ecom_credentials(self, configurationFile):
        """Given the configuration file set the ecom credentials.

        :param configurationFile: name of the file (String)
        :raises: VolumeBackendAPIException
        """
        if os.path.isfile(configurationFile):
            LOG.debug("Configuration file : %(configurationFile)s exists"
                      % {'configurationFile': configurationFile})
        else:
            exceptionMessage = (_(
                "Configuration file %(configurationFile)s does not exist ")
                % {'configurationFile': configurationFile})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        ip, port = self.utils.get_ecom_server(configurationFile)
        self.user, self.passwd = self.utils.get_ecom_cred(configurationFile)
        self.url = 'http://' + ip + ':' + port
        self.conn = self._get_ecom_connection()

    def _initial_setup(self, volume):
        """Necessary setup to accummulate the relevant information.

        The volume object has a host in which we can parse the
        config group name. The config group name is the key to our EMC
        configuration file. The emc configuration file contains pool name
        and array name which are mandatory fields.
        FastPolicy is optional.
        StripedMetaCount is an extra spec that determines whether
        the composite volume should be concatenated or striped.

        :param volume: the volume Object
        :returns: tuple extra spec tuple
        :returns: string the configuration file
        """
        try:
            extraSpecs, configurationFile = (
                self._set_config_file_and_get_extra_specs(volume))
            poolName = None

            try:
                stripedMetaCount = extraSpecs[STRIPECOUNT]
                extraSpecs[MEMBERCOUNT] = stripedMetaCount
                extraSpecs[COMPOSITETYPE] = STRIPED

                LOG.debug(
                    "There are: %(stripedMetaCount)s striped metas in "
                    "the extra specs"
                    % {'stripedMetaCount': stripedMetaCount})
            except Exception:
                memberCount = '1'
                extraSpecs[MEMBERCOUNT] = memberCount
                extraSpecs[COMPOSITETYPE] = CONCATENATED
                LOG.debug("StripedMetaCount is not in the extra specs")
                pass

            poolName = self.utils.parse_pool_name_from_file(configurationFile)
            if poolName is None:
                exceptionMessage = (_(
                    "The pool cannot be null. The pool must be configured "
                    "either in the extra specs or in the EMC configuration "
                    "file corresponding to the Volume Type. "))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            arrayName = self.utils.parse_array_name_from_file(
                configurationFile)
            if arrayName is None:
                exceptionMessage = (_(
                    "The array cannot be null. The pool must be configured "
                    "either as a cinder extra spec for multi-backend or in "
                    "the EMC configuration file for the default case "))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            # Get the FAST policy from the file this value can be None if the
            # user doesnt want to associate with any FAST policy
            fastPolicyName = self.utils.parse_fast_policy_name_from_file(
                configurationFile)
            if fastPolicyName is not None:
                LOG.debug("The fast policy name is : %(fastPolicyName)s. "
                          % {'fastPolicyName': fastPolicyName})

            extraSpecs[POOL] = poolName
            extraSpecs[ARRAY] = arrayName
            extraSpecs[FASTPOLICY] = fastPolicyName

            LOG.debug("Pool is: %(pool)s "
                      "Array is: %(array)s "
                      "FastPolicy is: %(fastPolicy)s "
                      "CompositeType is: %(compositeType)s "
                      "MemberCount is: %(memberCount)s "
                      % {'pool': extraSpecs[POOL],
                         'array': extraSpecs[ARRAY],
                         'fastPolicy': extraSpecs[FASTPOLICY],
                         'compositeType': extraSpecs[COMPOSITETYPE],
                         'memberCount': extraSpecs[MEMBERCOUNT]})

        except Exception:
            exceptionMessage = (_(
                "Unable to get configuration information necessary to create "
                "a volume. Please check that there is a configuration file "
                "for each config group, if multi-backend is enabled. "
                "The should be in the following format "
                "/etc/cinder/cinder_emc_config_<CONFIG_GROUP>.xml"))
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return extraSpecs

    def _get_pool_and_storage_system(self, extraSpecs):
        """Given the extra specs get the pool and storage system name.

        :params extraSpecs: the extra spec tuple
        :returns: poolInstanceName The pool instance name
        :returns: String  the storage system name
        """

        try:
            array = extraSpecs[ARRAY]
            poolInstanceName, storageSystemStr = self._find_pool_in_array(
                array, extraSpecs[POOL])
        except Exception:
            exceptionMessage = (_(
                "You must supply an array in your EMC configuration file "))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        if poolInstanceName is None or storageSystemStr is None:
            exceptionMessage = (_(
                "Cannot get necessary pool or storage system information "))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return poolInstanceName, storageSystemStr

    def _populate_masking_dict(self, volume, connector, extraSpecs):
        """Get all the names of the maskingView and subComponents.

        :param volume: the volume object
        :param connector: the connector object
        :param extraSpecs: the extra spec tuple
        :returns: tuple maskingViewDict a tuple with masking view information
        """
        maskingViewDict = {}
        hostName = connector['host']
        poolName = extraSpecs[POOL]
        volumeName = volume['name']
        protocol = self.utils.get_short_protocol_type(self.protocol)

        shortHostName = self.utils.get_host_short_name(hostName)

        volumeInstance = self._find_lun(volume)
        storageSystemName = volumeInstance['SystemName']

        maskingViewDict['controllerConfigService'] = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))
        maskingViewDict['sgGroupName'] = (
            'OS-' + shortHostName + '-' + poolName + '-' + protocol + '-SG')
        maskingViewDict['maskingViewName'] = (
            'OS-' + shortHostName + '-' + poolName + '-' + protocol + '-MV')
        # The portGroup is gotten from emc xml config file
        maskingViewDict['pgGroupName'] = (
            self.utils.parse_file_to_get_port_group_name(
                self.configuration.cinder_emc_config_file))

        maskingViewDict['igGroupName'] = (
            'OS-' + shortHostName + '-' + protocol + '-IG')
        maskingViewDict['connector'] = connector
        maskingViewDict['volumeInstance'] = volumeInstance
        maskingViewDict['volumeName'] = volumeName
        maskingViewDict['fastPolicy'] = (
            self.utils.parse_fast_policy_name_from_file(
                self.configuration.cinder_emc_config_file))
        maskingViewDict['storageSystemName'] = storageSystemName

        return maskingViewDict

    def _add_volume_to_default_storage_group_on_create(
            self, volumeDict, volumeName, storageConfigService,
            storageSystemName, fastPolicyName):
        """Add the volume to the default storage group for that policy.

        On a create when fast policy is enable add the volume to the default
        storage group for that policy. If it fails do the necessary rollback

        :param volumeDict: the volume dictionary
        :param volumeName: the volume name (String)
        :param storageConfigService: the storage configuration service
        :param storageSystemName: the storage system name (String)
        :param fastPolicyName: the fast policy name (String)
        :returns: tuple maskingViewDict with masking view information
        """
        try:
            volumeInstance = self.utils.find_volume_instance(
                self.conn, volumeDict, volumeName)
            controllerConfigurationService = (
                self.utils.find_controller_configuration_service(
                    self.conn, storageSystemName))

            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                self.conn, controllerConfigurationService, volumeInstance,
                volumeName, fastPolicyName)
            foundStorageGroupInstanceName = (
                self.utils.get_storage_group_from_volume(
                    self.conn, volumeInstance.path))

            if foundStorageGroupInstanceName is None:
                exceptionMessage = (_(
                    "Error adding Volume: %(volumeName)s.  "
                    "with instance path: %(volumeInstancePath)s. ")
                    % {'volumeName': volumeName,
                       'volumeInstancePath': volumeInstance.path})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        except Exception as e:
            # rollback by deleting the volume if adding the volume to the
            # default storage group were to fail
            LOG.error(_("Exception: %s") % six.text_type(e))
            errorMessage = (_(
                "Rolling back %(volumeName)s by deleting it. ")
                % {'volumeName': volumeName})
            LOG.error(errorMessage)
            self.provision.delete_volume_from_pool(
                self.conn, storageConfigService, volumeInstance.path,
                volumeName)
            raise exception.VolumeBackendAPIException(data=errorMessage)

    def _create_and_get_unbound_volume(
            self, conn, storageConfigService, compositeVolumeInstanceName,
            additionalSize):
        """Create an unbound volume.

        Create an unbound volume so it is in the correct state to add to a
        composite volume

        :param conn: the connection information to the ecom server
        :param storageConfigService: thestorage config service instance name
        :param compositeVolumeInstanceName: the composite volume instance name
        :param additionalSize: the size you want to increase the volume by
        :returns: volume instance modifiedCompositeVolumeInstance
        """
        assocPoolInstanceName = self.utils.get_assoc_pool_from_volume(
            conn, compositeVolumeInstanceName)
        appendVolumeInstance = self._create_and_get_volume_instance(
            conn, storageConfigService, assocPoolInstanceName, 'appendVolume',
            additionalSize)
        isVolumeBound = self.utils.is_volume_bound_to_pool(
            conn, appendVolumeInstance)

        if 'True' in isVolumeBound:
            appendVolumeInstance = (
                self._unbind_and_get_volume_from_storage_pool(
                    conn, storageConfigService, assocPoolInstanceName,
                    appendVolumeInstance.path, 'appendVolume'))

        return appendVolumeInstance

    def _create_and_get_volume_instance(
            self, conn, storageConfigService, poolInstanceName,
            volumeName, volumeSize):
        """Create and get a new volume.

        :params conn: the connection information to the ecom server
        :params storageConfigService: the storage config service instance name
        :params poolInstanceName: the pool instance name
        :params volumeName: the volume name
        :params volumeSize: the size to create the volume
        :returns: volumeInstance the volume instance
        """
        volumeDict, rc = self.provision.create_volume_from_pool(
            self.conn, storageConfigService, volumeName, poolInstanceName,
            volumeSize)
        volumeInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, volumeName)
        return volumeInstance

    def _unbind_and_get_volume_from_storage_pool(
            self, conn, storageConfigService, poolInstanceName,
            volumeInstanceName, volumeName):
        """Unbind a volume from a pool and return the unbound volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage config service instance name
        :param poolInstanceName: the pool instance name
        :param volumeInstanceName: the volume instance name
        :param volumeName: string the volumeName
        :returns: unboundVolumeInstance the unbound volume instance
        """

        rc, job = self.provision.unbind_volume_from_storage_pool(
            conn, storageConfigService, poolInstanceName, volumeInstanceName,
            volumeName)
        volumeDict = self.provision.get_volume_dict_from_job(conn, job['Job'])
        volumeInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, volumeName)
        return volumeInstance

    def _modify_and_get_composite_volume_instance(
            self, conn, elementCompositionServiceInstanceName, volumeInstance,
            appendVolumeInstanceName, volumeName, compositeType):
        """Given an existing composite volume add a new composite volume to it.

        :param conn: the connection information to the ecom server
        :param elementCompositionServiceInstanceName: the storage element
                                                      composition service
                                                      instance name
        :param volumeInstanceName: the volume instance name
        :param appendVolumeInstanceName: the appended volume instance name
        :param volumeName: the volume name
        :param compositeType: concatenated
        :returns: int rc the return code
        :returns: modifiedVolumeDict the modified volume Dict
        """
        isComposite = self.utils.check_if_volume_is_composite(
            self.conn, volumeInstance)
        if 'True' in isComposite:
            rc, job = self.provision.modify_composite_volume(
                conn, elementCompositionServiceInstanceName,
                volumeInstance.path, appendVolumeInstanceName)
        elif 'False' in isComposite:
            rc, job = self.provision.create_new_composite_volume(
                conn, elementCompositionServiceInstanceName,
                volumeInstance.path, appendVolumeInstanceName, compositeType)
        else:
            exception_message = (_(
                "Unable to determine whether %(volumeName)s is "
                "composite or not ")
                % {'volumeName': volumeName})
            LOG.error(exception_message)
            raise

        modifiedVolumeDict = self.provision.get_volume_dict_from_job(
            conn, job['Job'])

        return rc, modifiedVolumeDict

    def _get_or_create_default_storage_group(
            self, conn, storageSystemName, volumeDict, volumeName,
            fastPolicyName):
        """Get or create a default storage group for a fast policy.

        :param conn: the connection information to the ecom server
        :param storageSystemName: the storage system name
        :param volumeDict: the volume dictionary
        :param volumeName: the volume name
        :param fastPolicyName: the fast policy name
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
                volumeInstance))
        return defaultStorageGroupInstanceName

    def _create_cloned_volume(
            self, cloneVolume, sourceVolume, isSnapshot=False):
        """Create a clone volume from the source volume.

        :param cloneVolume: clone volume
        :param sourceVolume: source of the clone volume
        :returns: cloneDict the cloned volume dictionary
        """
        extraSpecs = self._initial_setup(cloneVolume)

        sourceName = sourceVolume['name']
        cloneName = cloneVolume['name']

        LOG.info(_("Create a Clone from Volume: Clone Volume: %(cloneName)s  "
                   "Source Volume: %(sourceName)s")
                 % {'cloneName': cloneName,
                    'sourceName': sourceName})

        self.conn = self._get_ecom_connection()

        sourceInstance = self._find_lun(sourceVolume)
        storageSystem = sourceInstance['SystemName']

        LOG.debug("Create Cloned Volume: Volume: %(cloneName)s  "
                  "Source Volume: %(sourceName)s  Source Instance: "
                  "%(sourceInstance)s  Storage System: %(storageSystem)s."
                  % {'cloneName': cloneName,
                     'sourceName': sourceName,
                     'sourceInstance': sourceInstance.path,
                     'storageSystem': storageSystem})

        repServiceInstanceName = self.utils.find_replication_service(
            self.conn, storageSystem)

        LOG.debug("Create Cloned Volume: Volume: %(cloneName)s  "
                  "Source Volume: %(sourceName)s  "
                  "Method: CreateElementReplica  "
                  "ReplicationService: %(service)s  ElementName: "
                  "%(elementname)s  SyncType: 8  SourceElement: "
                  "%(sourceelement)s"
                  % {'cloneName': cloneName,
                     'sourceName': sourceName,
                     'service': repServiceInstanceName,
                     'elementname': cloneName,
                     'sourceelement': sourceInstance.path})

        # Create a Clone from source volume
        rc, job = self.provision.create_element_replica(
            self.conn, repServiceInstanceName, cloneName, sourceName,
            sourceInstance)

        cloneDict = self.provision.get_volume_dict_from_job(
            self.conn, job['Job'])

        cloneVolume['provider_location'] = six.text_type(cloneDict)
        syncInstanceName, storageSystemName = (
            self._find_storage_sync_sv_sv(cloneVolume, sourceVolume))

        # Remove the Clone relationship so it can be used as a regular lun
        # 8 - Detach operation
        rc, job = self.provision.delete_clone_relationship(
            self.conn, repServiceInstanceName, syncInstanceName, cloneName,
            sourceName)

        # if FAST enabled place clone volume or volume from snapshot to
        # default storage group
        if extraSpecs[FASTPOLICY] is not None:
            LOG.debug("Adding volume: %(cloneName)s to default storage group "
                      "for FAST policy: %(fastPolicyName)s "
                      % {'cloneName': cloneName,
                         'fastPolicyName': extraSpecs[FASTPOLICY]})

            storageConfigService = (
                self.utils.find_storage_configuration_service(
                    self.conn, storageSystemName))

            defaultStorageGroupInstanceName = (
                self._get_or_create_default_storage_group(
                    self.conn, storageSystemName, cloneDict, cloneName,
                    extraSpecs[FASTPOLICY]))
            if defaultStorageGroupInstanceName is None:
                exceptionMessage = (_(
                    "Unable to create or get default storage group for FAST "
                    "policy: %(fastPolicyName)s. ")
                    % {'fastPolicyName': extraSpecs[FASTPOLICY]})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            self._add_volume_to_default_storage_group_on_create(
                cloneDict, cloneName, storageConfigService, storageSystemName,
                extraSpecs[FASTPOLICY])

        LOG.debug("Leaving _create_cloned_volume: Volume: "
                  "%(cloneName)s Source Volume: %(sourceName)s  "
                  "Return code: %(rc)lu."
                  % {'cloneName': cloneName,
                     'sourceName': sourceName,
                     'rc': rc})

        return cloneDict

    def _delete_volume(self, volume):
        """Helper function to delete the specified volume.

        :param volume: volume object to be deleted
        :returns: cloneDict the cloned volume dictionary
        """

        volumeName = volume['name']
        rc = -1
        errorRet = (rc, volumeName)

        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            LOG.error(_("Volume %(name)s not found on the array. "
                        "No volume to delete.")
                      % {'name': volumeName})
            return errorRet

        storageSystemName = volumeInstance['SystemName']

        storageConfigservice = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        deviceId = volumeInstance['DeviceID']

        fastPolicyName = extraSpecs[FASTPOLICY]
        if fastPolicyName is not None:
            defaultStorageGroupInstanceName = (
                self.masking.remove_device_from_default_storage_group(
                    self.conn, controllerConfigurationService,
                    volumeInstance.path, volumeName, fastPolicyName))
            if defaultStorageGroupInstanceName is None:
                warnMessage = (_(
                    "The volume: %(volumename)s. was not first part of the "
                    "default storage group for FAST policy %(fastPolicyName)s"
                    ".")
                    % {'volumename': volumeName,
                       'fastPolicyName': fastPolicyName})
                LOG.warn(warnMessage)
                # check if it is part of another storage group
                self._pre_check_for_deletion(controllerConfigurationService,
                                             volumeInstance.path, volumeName)

        else:
            # check if volume is part of a storage group
            self._pre_check_for_deletion(controllerConfigurationService,
                                         volumeInstance.path, volumeName)

        LOG.debug("Delete Volume: %(name)s  Method: EMCReturnToStoragePool "
                  "ConfigServic: %(service)s  TheElement: %(vol_instance)s "
                  "DeviceId: %(deviceId)s "
                  % {'service': storageConfigservice,
                     'name': volumeName,
                     'vol_instance': volumeInstance.path,
                     'deviceId': deviceId})
        try:
            rc = self.provision.delete_volume_from_pool(
                self.conn, storageConfigservice, volumeInstance.path,
                volumeName)

        except Exception as e:
            # if we cannot successfully delete the volume then we want to
            # return the volume to the default storage group
            if (fastPolicyName is not None and
                    defaultStorageGroupInstanceName is not None and
                    storageSystemName is not None):
                assocDefaultStorageGroupName = (
                    self.fast
                    .add_volume_to_default_storage_group_for_fast_policy(
                        self.conn, controllerConfigurationService,
                        volumeInstance, volumeName, fastPolicyName))
                if assocDefaultStorageGroupName is None:
                    errorMsg = (_(
                        "Failed to Roll back to re-add volume %(volumeName)s "
                        "to default storage group for fast policy "
                        "%(fastPolicyName)s: Please contact your sysadmin to "
                        "get the volume returned to the default storage group")
                        % {'volumeName': volumeName,
                           'fastPolicyName': fastPolicyName})
                    LOG.error(errorMsg)

            LOG.error(_("Exception: %s") % six.text_type(e))
            errorMessage = (_("Failed to delete volume %(volumeName)s")
                            % {'volumeName': volumeName})
            LOG.error(errorMessage)
            raise exception.VolumeBackendAPIException(data=errorMessage)

        return (rc, volumeName)

    def _pre_check_for_deletion(self, controllerConfigurationService,
                                volumeInstanceName, volumeName):
        """Check is volume is part of a storage group prior to delete

        Log a warning if volume is part of storage group

        :param controllerConfigurationService: controller configuration service
        :param volumeInstanceName: volume instance name
        :param volumeName: volume name (string)
        """

        storageGroupInstanceName = (
            self.masking.get_associated_masking_group_from_device(
                self.conn, volumeInstanceName))
        if storageGroupInstanceName is not None:
            LOG.warn(_("Pre check for deletion "
                       "Volume: %(volumeName)s is part of a storage group "
                       "Attempting removal from %(storageGroupInstanceName)s ")
                     % {'volumeName': volumeName,
                        'storageGroupInstanceName': storageGroupInstanceName})
            self.provision.remove_device_from_storage_group(
                self.conn, controllerConfigurationService,
                storageGroupInstanceName,
                volumeInstanceName, volumeName)

    def _find_lunmasking_scsi_protocol_controller(self, storageSystemName,
                                                  connector):
        """Find LunMaskingSCSIProtocolController for the local host

        Find out how many volumes are mapped to a host
        associated to the LunMaskingSCSIProtocolController

        :param connector: volume object to be deleted
        :param storageSystemName: the storage system name
        :returns: foundCtrl
        """

        foundCtrl = None
        initiators = self._find_initiator_names(connector)
        controllers = self.conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for ctrl in controllers:
            if storageSystemName != ctrl['SystemName']:
                continue
            associators = self.conn.Associators(
                ctrl, ResultClass='EMC_StorageHardwareID')
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

        LOG.debug("LunMaskingSCSIProtocolController for storage system "
                  "%(storage_system)s and initiator %(initiator)s is  "
                  "%(ctrl)s."
                  % {'storage_system': storageSystemName,
                     'initiator': initiators,
                     'ctrl': foundCtrl})
        return foundCtrl

    def get_num_volumes_mapped(self, volume, connector):
        """Returns how many volumes are in the same zone as the connector.

        Find out how many volumes are mapped to a host
        associated to the LunMaskingSCSIProtocolController

        :param volume: volume object to be deleted
        :param connector: volume object to be deleted
        :returns: int numVolumesMapped
        """

        volumename = volume['name']
        vol_instance = self._find_lun(volume)
        if vol_instance is None:
            msg = ("Volume %(name)s not found on the array. "
                   "Cannot determine if there are volumes mapped."
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

        # return 0 if masking view does not exist
        if ctrl is None:
            return 0

        associators = self.conn.Associators(
            ctrl,
            ResultClass='EMC_StorageVolume')

        numVolumesMapped = len(associators)

        LOG.debug("Found %(numVolumesMapped)d volumes on storage system "
                  "%(storage)s mapped to %(connector)s."
                  % {'numVolumesMapped': numVolumesMapped,
                     'storage': storage_system,
                     'connector': connector})

        return numVolumesMapped
