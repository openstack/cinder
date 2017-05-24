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

import ast
import os.path

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import re
import six
import uuid

from cinder import exception
from cinder import utils as cinder_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.objects.consistencygroup import ConsistencyGroup
from cinder.objects import fields
from cinder.objects.group import Group
from cinder.volume.drivers.dell_emc.vmax import fast
from cinder.volume.drivers.dell_emc.vmax import https
from cinder.volume.drivers.dell_emc.vmax import masking
from cinder.volume.drivers.dell_emc.vmax import provision
from cinder.volume.drivers.dell_emc.vmax import provision_v3
from cinder.volume.drivers.dell_emc.vmax import utils
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
COMPOSITETYPE = 'storagetype:compositetype'
MULTI_POOL_SUPPORT = 'MultiPoolSupport'
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
TRUNCATE_27 = 27
SNAPVX = 7
DISSOLVE_SNAPVX = 9
CREATE_NEW_TARGET = 2
SNAPVX_REPLICATION_TYPE = 6
# Replication
IS_RE = 'replication_enabled'
REPLICATION_DISABLED = fields.ReplicationStatus.DISABLED
REPLICATION_ENABLED = fields.ReplicationStatus.ENABLED
REPLICATION_FAILOVER = fields.ReplicationStatus.FAILED_OVER
FAILOVER_ERROR = fields.ReplicationStatus.FAILOVER_ERROR
REPLICATION_ERROR = fields.ReplicationStatus.ERROR

SUSPEND_SRDF = 22
DETACH_SRDF = 8
MIRROR_SYNC_TYPE = 6

emc_opts = [
    cfg.StrOpt('cinder_emc_config_file',
               default=CINDER_EMC_CONFIG_FILE,
               help='Use this file for cinder emc plugin '
                    'config data'),
    cfg.StrOpt('multi_pool_support',
               default=False,
               help='Use this value to specify '
                    'multi-pool support for VMAX3'),
    cfg.StrOpt('initiator_check',
               default=False,
               help='Use this value to enable '
                    'the initiator_check')]

CONF.register_opts(emc_opts)


class VMAXCommon(object):
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
             'vendor_name': 'Dell EMC',
             'volume_backend_name': None,
             'replication_enabled': False,
             'replication_targets': None}

    pool_info = {'backend_name': None,
                 'config_file': None,
                 'arrays_info': {},
                 'max_over_subscription_ratio': None,
                 'reserved_percentage': None,
                 'replication_enabled': False
                 }

    def __init__(self, prtcl, version, configuration=None,
                 active_backend_id=None):

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
        self.masking = masking.VMAXMasking(prtcl)
        self.utils = utils.VMAXUtils(prtcl)
        self.fast = fast.VMAXFast(prtcl)
        self.provision = provision.VMAXProvision(prtcl)
        self.provisionv3 = provision_v3.VMAXProvisionV3(prtcl)
        self.version = version
        # replication
        self.replication_enabled = False
        self.extendReplicatedVolume = False
        self.active_backend_id = active_backend_id
        self.failover = False
        self._get_replication_info()
        self.multiPoolSupportEnabled = False
        self.initiatorCheck = False
        self._gather_info()

    def _gather_info(self):
        """Gather the relevant information for update_volume_stats."""
        if hasattr(self.configuration, 'cinder_emc_config_file'):
            self.pool_info['config_file'] = (
                self.configuration.cinder_emc_config_file)
        else:
            self.pool_info['config_file'] = (
                self.configuration.safe_get('cinder_emc_config_file'))
        if hasattr(self.configuration, 'multi_pool_support'):
            tempMultiPoolSupported = cinder_utils.get_bool_param(
                'multi_pool_support', self.configuration)
            if tempMultiPoolSupported:
                self.multiPoolSupportEnabled = True
        self.pool_info['backend_name'] = (
            self.configuration.safe_get('volume_backend_name'))
        self.pool_info['max_over_subscription_ratio'] = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        self.pool_info['reserved_percentage'] = (
            self.configuration.safe_get('reserved_percentage'))
        LOG.debug(
            "Updating volume stats on file %(emcConfigFileName)s on "
            "backend %(backendName)s.",
            {'emcConfigFileName': self.pool_info['config_file'],
             'backendName': self.pool_info['backend_name']})

        arrayInfoList = self.utils.parse_file_to_get_array_map(
            self.pool_info['config_file'])
        # Assuming that there is a single array info object always
        # Check if Multi pool support is enabled
        if self.multiPoolSupportEnabled is False:
            self.pool_info['arrays_info'] = arrayInfoList
        else:
            finalArrayInfoList = self._get_slo_workload_combinations(
                arrayInfoList)
            self.pool_info['arrays_info'] = finalArrayInfoList

    def _get_replication_info(self):
        """Gather replication information, if provided."""
        self.rep_config = None
        self.replication_targets = None
        if hasattr(self.configuration, 'replication_device'):
            self.rep_devices = self.configuration.safe_get(
                'replication_device')
        if self.rep_devices and len(self.rep_devices) == 1:
            self.rep_config = self.utils.get_replication_config(
                self.rep_devices)
            if self.rep_config:
                self.replication_targets = [self.rep_config['array']]
                if self.active_backend_id == self.rep_config['array']:
                    self.failover = True
                self.extendReplicatedVolume = self.rep_config['allow_extend']
                # use self.replication_enabled for update_volume_stats
                self.replication_enabled = True
                LOG.debug("The replication configuration is %(rep_config)s.",
                          {'rep_config': self.rep_config})
        elif self.rep_devices and len(self.rep_devices) > 1:
            LOG.error(_LE("More than one replication target is configured. "
                          "EMC VMAX only suppports a single replication "
                          "target. Replication will not be enabled."))

    def _get_slo_workload_combinations(self, arrayInfoList):
        """Method to query the array for SLO and Workloads.

        Takes the arrayInfoList object and generates a set which has
        all available SLO & Workload combinations

        :param arrayInfoList:
        :return: finalArrayInfoList
        :raises: Exception
        """
        try:
            sloWorkloadSet = set()
            # Pattern for extracting the SLO & Workload String
            pattern = re.compile("^-S[A-Z]+")
            for arrayInfo in arrayInfoList:
                self._set_ecom_credentials(arrayInfo)
                isV3 = self.utils.isArrayV3(self.conn,
                                            arrayInfo['SerialNumber'])
                # Only if the array is VMAX3
                if isV3:
                    poolInstanceName, storageSystemStr = (
                        self._find_pool_in_array(arrayInfo['SerialNumber'],
                                                 arrayInfo['PoolName'], isV3))
                    # Get the pool capability
                    storagePoolCapability = (
                        self.provisionv3.get_storage_pool_capability(
                            self.conn, poolInstanceName))
                    # Get the pool settings
                    storagePoolSettings = self.conn.AssociatorNames(
                        storagePoolCapability,
                        ResultClass='CIM_storageSetting')
                    for storagePoolSetting in storagePoolSettings:
                        settingInstanceID = storagePoolSetting['InstanceID']
                        settingInstanceDetails = settingInstanceID.split('+')
                        sloWorkloadString = settingInstanceDetails[2]
                        if pattern.match(sloWorkloadString):
                            length = len(sloWorkloadString)
                            tempSloWorkloadString = (
                                sloWorkloadString[2:length - 1])
                            sloWorkloadSet.add(tempSloWorkloadString)
            # Assuming that there is always a single arrayInfo object
            finalArrayInfoList = []
            for sloWorkload in sloWorkloadSet:
                # Doing a shallow copy will work as we are modifying
                # only strings
                temparrayInfo = arrayInfoList[0].copy()
                slo, workload = sloWorkload.split(':')
                # Check if we got SLO and workload from the set (from array)
                # The previous check was done by mistake against the value
                # from XML file
                if slo:
                    temparrayInfo['SLO'] = slo
                if workload:
                    temparrayInfo['Workload'] = workload
                finalArrayInfoList.append(temparrayInfo)
        except Exception:
            exceptionMessage = (_(
                "Unable to get the SLO/Workload combinations from the array"))
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        return finalArrayInfoList

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
        :returns:  model_update, dict
        """
        model_update = {}
        volumeSize = int(self.utils.convert_gb_to_bits(volume['size']))
        volumeId = volume['id']
        extraSpecs = self._initial_setup(volume)
        self.conn = self._get_ecom_connection()

        # VolumeName naming convention is 'OS-UUID'.
        volumeName = self.utils.get_volume_element_name(volumeId)

        if extraSpecs[ISV3]:
            rc, volumeDict, storageSystemName = (
                self._create_v3_volume(volume, volumeName, volumeSize,
                                       extraSpecs))
        else:
            rc, volumeDict, storageSystemName = (
                self._create_composite_volume(volume, volumeName, volumeSize,
                                              extraSpecs))

        # set-up volume replication, if enabled (V3 only)
        if self.utils.is_replication_enabled(extraSpecs):
            try:
                replication_status, replication_driver_data = (
                    self.setup_volume_replication(
                        self.conn, volume, volumeDict, extraSpecs))
            except Exception:
                self._cleanup_replication_source(self.conn, volumeName,
                                                 volumeDict, extraSpecs)
                raise
            model_update.update(
                {'replication_status': replication_status,
                 'replication_driver_data': six.text_type(
                     replication_driver_data)})

        # If volume is created as part of a consistency group.
        if 'consistencygroup_id' in volume and volume['consistencygroup_id']:
            volumeInstance = self.utils.find_volume_instance(
                self.conn, volumeDict, volumeName)
            replicationService = (
                self.utils.find_replication_service(self.conn,
                                                    storageSystemName))
            cgInstanceName, cgName = (
                self._find_consistency_group(
                    replicationService,
                    six.text_type(volume['consistencygroup_id'])))
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

        model_update.update(
            {'provider_location': six.text_type(volumeDict)})

        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        For VMAX, replace snapshot with clone.

        :param volume: volume Object
        :param snapshot: snapshot object
        :returns: model_update, dict
        :raises: VolumeBackendAPIException
        """
        LOG.debug("Entering create_volume_from_snapshot.")
        extraSpecs = self._initial_setup(snapshot, host=volume['host'])
        model_update = {}
        self.conn = self._get_ecom_connection()
        snapshotInstance = self._find_lun(snapshot)

        self._sync_check(snapshotInstance, snapshot['name'], extraSpecs)

        cloneDict = self._create_cloned_volume(volume, snapshot,
                                               extraSpecs, False)
        # set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extraSpecs):
            try:
                replication_status, replication_driver_data = (
                    self.setup_volume_replication(
                        self.conn, volume, cloneDict, extraSpecs))
            except Exception:
                self._cleanup_replication_source(self.conn, snapshot['name'],
                                                 cloneDict, extraSpecs)
                raise
            model_update.update(
                {'replication_status': replication_status,
                 'replication_driver_data': six.text_type(
                     replication_driver_data)})

        cloneDict['version'] = self.version
        model_update.update(
            {'provider_location': six.text_type(cloneDict)})

        return model_update

    def create_cloned_volume(self, cloneVolume, sourceVolume):
        """Creates a clone of the specified volume.

        :param cloneVolume: clone volume Object
        :param sourceVolume: volume object
        :returns: model_update, dict
        """
        model_update = {}
        extraSpecs = self._initial_setup(sourceVolume)
        cloneDict = self._create_cloned_volume(cloneVolume, sourceVolume,
                                               extraSpecs, False)

        # set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extraSpecs):
            try:
                replication_status, replication_driver_data = (
                    self.setup_volume_replication(
                        self.conn, cloneVolume, cloneDict, extraSpecs))
            except Exception:
                self._cleanup_replication_source(
                    self.conn, cloneVolume['name'], cloneDict, extraSpecs)
                raise
            model_update.update(
                {'replication_status': replication_status,
                 'replication_driver_data': six.text_type(
                     replication_driver_data)})

        cloneDict['version'] = self.version
        model_update.update(
            {'provider_location': six.text_type(cloneDict)})

        return model_update

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
        self._delete_snapshot(snapshot, volume['host'])

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
        if self.utils.is_volume_failed_over(volume):
            extraSpecs = self._get_replication_extraSpecs(
                extraSpecs, self.rep_config)
        volumename = volume['name']
        LOG.info(_LI("Unmap volume: %(volume)s."),
                 {'volume': volumename})

        device_info, __, __ = self.find_device_number(
            volume, connector['host'])
        if 'hostlunid' not in device_info:
            LOG.info(_LI("Volume %s is not mapped. No volume to unmap."),
                     volumename)
            return

        vol_instance = self._find_lun(volume)
        storage_system = vol_instance['SystemName']

        if self._is_volume_multiple_masking_views(vol_instance):
            return

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

    def _is_volume_multiple_masking_views(self, vol_instance):
        """Check if volume is in more than one MV.

        :param vol_instance: the volume instance
        :returns: boolean
        """
        storageGroupInstanceNames = (
            self.masking.get_associated_masking_groups_from_device(
                self.conn, vol_instance.path))

        for storageGroupInstanceName in storageGroupInstanceNames:
            mvInstanceNames = self.masking.get_masking_view_from_storage_group(
                self.conn, storageGroupInstanceName)
            if len(mvInstanceNames) > 1:
                return True
        return False

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns device and connection info.

        The volume may be already mapped, if this is so the deviceInfo tuple
        is returned.  If the volume is not already mapped then we need to
        gather information to either 1. Create an new masking view or 2. Add
        the volume to an existing storage group within an already existing
        maskingview.

        The naming convention is the following:

        .. code-block:: none

         initiatorGroupName = OS-<shortHostName>-<shortProtocol>-IG
                              e.g OS-myShortHost-I-IG
         storageGroupName = OS-<shortHostName>-<poolName>-<shortProtocol>-SG
                            e.g OS-myShortHost-SATA_BRONZ1-I-SG
         portGroupName = OS-<target>-PG  The portGroupName will come from
                         the EMC configuration xml file.
                         These are precreated. If the portGroup does not
                         exist then an error will be returned to the user
         maskingView  = OS-<shortHostName>-<poolName>-<shortProtocol>-MV
                        e.g OS-myShortHost-SATA_BRONZ1-I-MV

        :param volume: volume Object
        :param connector: the connector Object
        :returns: dict -- deviceInfoDict - device information dict
        :raises: VolumeBackendAPIException
        """
        portGroupName = None
        extraSpecs = self._initial_setup(volume)
        is_multipath = connector.get('multipath', False)

        volumeName = volume['name']
        LOG.info(_LI("Initialize connection: %(volume)s."),
                 {'volume': volumeName})
        self.conn = self._get_ecom_connection()

        if self.utils.is_volume_failed_over(volume):
            extraSpecs = self._get_replication_extraSpecs(
                extraSpecs, self.rep_config)
        deviceInfoDict, isLiveMigration, sourceInfoDict = (
            self._wrap_find_device_number(
                volume, connector['host']))
        maskingViewDict = self._populate_masking_dict(
            volume, connector, extraSpecs)

        if ('hostlunid' in deviceInfoDict and
                deviceInfoDict['hostlunid'] is not None):
            deviceNumber = deviceInfoDict['hostlunid']
            LOG.info(_LI("Volume %(volume)s is already mapped. "
                         "The device number is  %(deviceNumber)s."),
                     {'volume': volumeName,
                      'deviceNumber': deviceNumber})
            # Special case, we still need to get the iscsi ip address.
            portGroupName = (
                self._get_correct_port_group(
                    deviceInfoDict, maskingViewDict['storageSystemName']))
        else:
            if isLiveMigration:
                maskingViewDict['storageGroupInstanceName'] = (
                    self._get_storage_group_from_source(sourceInfoDict))
                maskingViewDict['portGroupInstanceName'] = (
                    self._get_port_group_from_source(sourceInfoDict))

                deviceInfoDict, portGroupName = self._attach_volume(
                    volume, connector, extraSpecs, maskingViewDict, True)
            else:
                deviceInfoDict, portGroupName = (
                    self._attach_volume(
                        volume, connector, extraSpecs, maskingViewDict))

        if self.protocol.lower() == 'iscsi':
            deviceInfoDict['ip_and_iqn'] = (
                self._find_ip_protocol_endpoints(
                    self.conn, deviceInfoDict['storagesystem'],
                    portGroupName))
            deviceInfoDict['is_multipath'] = is_multipath

        return deviceInfoDict

    def _attach_volume(self, volume, connector, extraSpecs,
                       maskingViewDict, isLiveMigration=False):
        """Attach a volume to a host.

        If live migration is being undertaken then the volume
        remains attached to the source host.

        :params volume: the volume object
        :params connector: the connector object
        :param extraSpecs: extra specifications
        :param maskingViewDict: masking view information
        :param isLiveMigration: boolean, can be None
        :returns: dict -- deviceInfoDict
                  String -- port group name
        :raises: VolumeBackendAPIException
        """
        volumeName = volume['name']
        if isLiveMigration:
            maskingViewDict['isLiveMigration'] = True
        else:
            maskingViewDict['isLiveMigration'] = False

        rollbackDict = self.masking.setup_masking_view(
            self.conn, maskingViewDict, extraSpecs)

        # Find host lun id again after the volume is exported to the host.
        deviceInfoDict, __, __ = self.find_device_number(
            volume, connector['host'])
        if 'hostlunid' not in deviceInfoDict:
            # Did not successfully attach to host,
            # so a rollback for FAST is required.
            LOG.error(_LE("Error Attaching volume %(vol)s."),
                      {'vol': volumeName})
            if ((rollbackDict['fastPolicyName'] is not None) or
                    (rollbackDict['isV3'] is not None)):
                (self.masking._check_if_rollback_action_for_masking_required(
                    self.conn, rollbackDict))
            exception_message = (_("Error Attaching volume %(vol)s.")
                                 % {'vol': volumeName})
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        return deviceInfoDict, rollbackDict['pgGroupName']

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

    def _get_correct_port_group(self, deviceInfoDict, storageSystemName):
        """Get the portgroup name from the existing masking view.

        :params deviceInfoDict: the device info dictionary
        :params storageSystemName: storage system name
        :returns: String port group name
        """
        if ('controller' in deviceInfoDict and
                deviceInfoDict['controller'] is not None):
            maskingViewInstanceName = deviceInfoDict['controller']
            try:
                maskingViewInstance = (
                    self.conn.GetInstance(maskingViewInstanceName))
            except Exception:
                exception_message = (_("Unable to get the name of "
                                       "the masking view."))
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            # Get the portgroup from masking view
            portGroupInstanceName = (
                self.masking._get_port_group_from_masking_view(
                    self.conn,
                    maskingViewInstance['ElementName'],
                    storageSystemName))
            try:
                portGroupInstance = (
                    self.conn.GetInstance(portGroupInstanceName))
                portGroupName = (
                    portGroupInstance['ElementName'])
            except Exception:
                exception_message = (_("Unable to get the name of "
                                       "the portgroup."))
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
        else:
            exception_message = (_("Cannot get the portgroup from "
                                   "the masking view."))
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return portGroupName

    def _get_storage_group_from_source(self, deviceInfoDict):
        """Get the storage group from the existing masking view.

        :params deviceInfoDict: the device info dictionary
        :returns: storage group instance
        """
        storageGroupInstanceName = None
        if ('controller' in deviceInfoDict and
                deviceInfoDict['controller'] is not None):
            maskingViewInstanceName = deviceInfoDict['controller']

            # Get the storage group from masking view
            storageGroupInstanceName = (
                self.masking._get_storage_group_from_masking_view_instance(
                    self.conn,
                    maskingViewInstanceName))
        else:
            exception_message = (_("Cannot get the storage group from "
                                   "the masking view."))
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return storageGroupInstanceName

    def _get_port_group_from_source(self, deviceInfoDict):
        """Get the port group from the existing masking view.

        :params deviceInfoDict: the device info dictionary
        :returns: port group instance
        """
        portGroupInstanceName = None
        if ('controller' in deviceInfoDict and
                deviceInfoDict['controller'] is not None):
            maskingViewInstanceName = deviceInfoDict['controller']

            # Get the port group from masking view
            portGroupInstanceName = (
                self.masking.get_port_group_from_masking_view_instance(
                    self.conn,
                    maskingViewInstanceName))
        else:
            exception_message = (_("Cannot get the port group from "
                                   "the masking view."))
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return portGroupInstanceName

    def check_ig_instance_name(self, initiatorGroupInstanceName):
        """Check if an initiator group instance is on the array.

        :param initiatorGroupInstanceName: initiator group instance name
        :returns: initiator group name, or None if deleted
        """
        return self.utils.check_ig_instance_name(
            self.conn, initiatorGroupInstanceName)

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
        return self._extend_volume(
            volume, volumeInstance, volumeName, newSize,
            originalVolumeSize, extraSpecs)

    def _extend_volume(
            self, volume, volumeInstance, volumeName, newSize,
            originalVolumeSize, extraSpecs):
        """Extends an existing volume.

        :param volume: the volume Object
        :param volumeInstance: the volume instance
        :param volumeName: the volume name
        :param newSize: the new size to increase the volume to
        :param originalVolumeSize:
        :param extraSpecs: extra specifications
        :return: dict -- modifiedVolumeDict - the extended volume Object
        :raises: VolumeBackendAPIException
        """
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

        if extraSpecs[ISV3]:
            if self.utils.is_replication_enabled(extraSpecs):
                # extra logic required if volume is replicated
                rc, modifiedVolumeDict = self.extend_volume_is_replicated(
                    volume, volumeInstance, volumeName, newSize,
                    extraSpecs)
            else:
                rc, modifiedVolumeDict = self._extend_v3_volume(
                    volumeInstance, volumeName, newSize, extraSpecs)
        else:
            # This is V2.
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
        # Dictionary to hold the VMAX3 arrays for which the SRP details
        # have already been queried
        # This only applies to the arrays for which WLP is not enabled
        arrays = {}
        backendName = self.pool_info['backend_name']
        max_oversubscription_ratio = (
            self.pool_info['max_over_subscription_ratio'])
        reservedPercentage = self.pool_info['reserved_percentage']
        array_max_over_subscription = None
        array_reserve_percent = None
        for arrayInfo in self.pool_info['arrays_info']:
            alreadyQueried = False
            self._set_ecom_credentials(arrayInfo)
            # Check what type of array it is
            isV3 = self.utils.isArrayV3(self.conn,
                                        arrayInfo['SerialNumber'])
            if isV3:
                if self.failover:
                    arrayInfo = self.get_secondary_stats_info(
                        self.rep_config, arrayInfo)
                # Report only the SLO name in the pool name for
                # backward compatibility
                if self.multiPoolSupportEnabled is False:
                    (location_info, total_capacity_gb, free_capacity_gb,
                     provisioned_capacity_gb,
                     array_reserve_percent,
                     wlpEnabled) = self._update_srp_stats(arrayInfo)
                    poolName = ("%(slo)s+%(poolName)s+%(array)s"
                                % {'slo': arrayInfo['SLO'],
                                   'poolName': arrayInfo['PoolName'],
                                   'array': arrayInfo['SerialNumber']})
                else:
                    # Add both SLO & Workload name in the pool name
                    # Query the SRP only once if WLP is not enabled
                    # Only insert the array details in the dict once
                    if arrayInfo['SerialNumber'] not in arrays:
                        (location_info, total_capacity_gb, free_capacity_gb,
                         provisioned_capacity_gb,
                         array_reserve_percent,
                         wlpEnabled) = self._update_srp_stats(arrayInfo)
                    else:
                        alreadyQueried = True
                    poolName = ("%(slo)s+%(workload)s+%(poolName)s+%(array)s"
                                % {'slo': arrayInfo['SLO'],
                                   'workload': arrayInfo['Workload'],
                                   'poolName': arrayInfo['PoolName'],
                                   'array': arrayInfo['SerialNumber']})
                    if wlpEnabled is False:
                        arrays[arrayInfo['SerialNumber']] = (
                            [total_capacity_gb, free_capacity_gb,
                             provisioned_capacity_gb, array_reserve_percent])
            else:
                # This is V2
                (location_info, total_capacity_gb, free_capacity_gb,
                 provisioned_capacity_gb, array_max_over_subscription) = (
                    self._update_pool_stats(backendName, arrayInfo))
                poolName = ("%(poolName)s+%(array)s"
                            % {'poolName': arrayInfo['PoolName'],
                               'array': arrayInfo['SerialNumber']})

            if alreadyQueried and self.multiPoolSupportEnabled:
                # The dictionary will only have one key per VMAX3
                # Construct the location info
                temp_location_info = (
                    ("%(arrayName)s#%(poolName)s#%(slo)s#%(workload)s"
                     % {'arrayName': arrayInfo['SerialNumber'],
                        'poolName': arrayInfo['PoolName'],
                        'slo': arrayInfo['SLO'],
                        'workload': arrayInfo['Workload']}))
                pool = {'pool_name': poolName,
                        'total_capacity_gb':
                            arrays[arrayInfo['SerialNumber']][0],
                        'free_capacity_gb':
                            arrays[arrayInfo['SerialNumber']][1],
                        'provisioned_capacity_gb':
                            arrays[arrayInfo['SerialNumber']][2],
                        'QoS_support': True,
                        'location_info': temp_location_info,
                        'consistencygroup_support': True,
                        'thin_provisioning_support': True,
                        'thick_provisioning_support': False,
                        'max_over_subscription_ratio':
                            max_oversubscription_ratio,
                        'replication_enabled': self.replication_enabled
                        }
                if (
                    arrays[arrayInfo['SerialNumber']][3] and
                    (arrays[arrayInfo['SerialNumber']][3] >
                        reservedPercentage)):
                    pool['reserved_percentage'] = (
                        arrays[arrayInfo['SerialNumber']][3])
                else:
                    pool['reserved_percentage'] = reservedPercentage
            else:
                pool = {'pool_name': poolName,
                        'total_capacity_gb': total_capacity_gb,
                        'free_capacity_gb': free_capacity_gb,
                        'provisioned_capacity_gb': provisioned_capacity_gb,
                        'QoS_support': False,
                        'location_info': location_info,
                        'consistencygroup_support': True,
                        'thin_provisioning_support': True,
                        'thick_provisioning_support': False,
                        'max_over_subscription_ratio':
                            max_oversubscription_ratio,
                        'replication_enabled': self.replication_enabled
                        }
                if (
                    array_reserve_percent and
                        (array_reserve_percent > reservedPercentage)):
                    pool['reserved_percentage'] = array_reserve_percent
                else:
                    pool['reserved_percentage'] = reservedPercentage

            if array_max_over_subscription:
                pool['max_over_subscription_ratio'] = (
                    self.utils.override_ratio(
                        max_oversubscription_ratio,
                        array_max_over_subscription))
            pools.append(pool)

        data = {'vendor_name': "Dell EMC",
                'driver_version': self.version,
                'storage_protocol': 'unknown',
                'volume_backend_name': self.pool_info['backend_name'] or
                self.__class__.__name__,
                # Use zero capacities here so we always use a pool.
                'total_capacity_gb': 0,
                'free_capacity_gb': 0,
                'provisioned_capacity_gb': 0,
                'reserved_percentage': 0,
                'replication_enabled': self.replication_enabled,
                'replication_targets': self.replication_targets,
                'pools': pools}

        return data

    def _update_srp_stats(self, arrayInfo):
        """Update SRP stats.

        :param arrayInfo: array information
        :returns: location_info
        :returns: totalManagedSpaceGbs
        :returns: remainingManagedSpaceGbs
        :returns: provisionedManagedSpaceGbs
        :returns: array_reserve_percent
        :returns: wlpEnabled
        """

        (totalManagedSpaceGbs, remainingManagedSpaceGbs,
         provisionedManagedSpaceGbs, array_reserve_percent, wlpEnabled) = (
            self.provisionv3.get_srp_pool_stats(self.conn, arrayInfo))

        LOG.info(_LI(
            "Capacity stats for SRP pool %(poolName)s on array "
            "%(arrayName)s total_capacity_gb=%(total_capacity_gb)lu, "
            "free_capacity_gb=%(free_capacity_gb)lu, "
            "provisioned_capacity_gb=%(provisioned_capacity_gb)lu"),
            {'poolName': arrayInfo['PoolName'],
             'arrayName': arrayInfo['SerialNumber'],
             'total_capacity_gb': totalManagedSpaceGbs,
             'free_capacity_gb': remainingManagedSpaceGbs,
             'provisioned_capacity_gb': provisionedManagedSpaceGbs})

        location_info = ("%(arrayName)s#%(poolName)s#%(slo)s#%(workload)s"
                         % {'arrayName': arrayInfo['SerialNumber'],
                            'poolName': arrayInfo['PoolName'],
                            'slo': arrayInfo['SLO'],
                            'workload': arrayInfo['Workload']})

        return (location_info, totalManagedSpaceGbs,
                remainingManagedSpaceGbs, provisionedManagedSpaceGbs,
                array_reserve_percent, wlpEnabled)

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
            if self.utils.is_replication_enabled(extraSpecs):
                LOG.error(_LE("Volume %(name)s is replicated - "
                              "Replicated volumes are not eligible for "
                              "storage assisted retype. Host assisted "
                              "retype is supported."),
                          {'name': volumeName})
                return False

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
            sourcePoolName, volumeName, volumeStatus, sgName,
            doChangeCompression):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param volumeInstanceName: the volume instance id
        :param host: the host object
        :param sourceArraySerialNumber: the array serial number of
            the original volume
        :param sourcePoolName: the pool name of the original volume
        :param volumeName: the name of the volume to be migrated
        :param volumeStatus: the status of the volume
        :param sgName: storage group name
        :param doChangeCompression: do change compression
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
                # Check if migration is from compression to non compression
                # of vice versa
                if not doChangeCompression:
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
        extraSpecs = self.utils.get_volumetype_extraspecs(
            volume, volumeTypeId)
        qosSpecs = self.utils.get_volumetype_qosspecs(volume, volumeTypeId)
        configGroup = None
        # If there are no extra specs then the default case is assumed.
        if extraSpecs:
            configGroup = self.configuration.config_group
        configurationFile = self._register_config_file_from_config_group(
            configGroup)
        self.multiPoolSupportEnabled = (
            self._get_multi_pool_support_enabled_flag())
        extraSpecs[MULTI_POOL_SUPPORT] = self.multiPoolSupportEnabled
        if extraSpecs.get('replication_enabled') == '<is> True':
            extraSpecs[IS_RE] = True
        return extraSpecs, configurationFile, qosSpecs

    def _get_multi_pool_support_enabled_flag(self):
        """Reads the configuration for multi pool support flag.

        :returns: MultiPoolSupportEnabled flag
        """

        confString = (
            self.configuration.safe_get('multi_pool_support'))
        retVal = False
        stringTrue = "True"
        if confString:
            if confString.lower() == stringTrue.lower():
                retVal = True
        return retVal

    def _get_initiator_check_flag(self):
        """Reads the configuration for initator_check flag.

        :returns:  flag
        """

        confString = (
            self.configuration.safe_get('initiator_check'))
        retVal = False
        stringTrue = "True"
        if confString:
            if confString.lower() == stringTrue.lower():
                retVal = True
        return retVal

    def _get_ecom_connection(self):
        """Get the ecom connection.

        :returns: pywbem.WBEMConnection -- conn, the ecom connection
        :raises: VolumeBackendAPIException
        """
        ecomx509 = None
        if self.ecomUseSSL:
            if (self.configuration.safe_get('driver_client_cert_key') and
                    self.configuration.safe_get('driver_client_cert')):
                ecomx509 = {"key_file":
                            self.configuration.safe_get(
                                'driver_client_cert_key'),
                            "cert_file":
                                self.configuration.safe_get(
                                    'driver_client_cert')}
            pywbem.cim_http.wbem_request = https.wbem_request
            conn = pywbem.WBEMConnection(
                self.url,
                (self.user, self.passwd),
                default_namespace='root/emc',
                x509=ecomx509,
                ca_certs=self.configuration.safe_get('driver_ssl_cert_path'),
                no_verification=not self.configuration.safe_get(
                    'driver_ssl_cert_verify'))

        else:
            conn = pywbem.WBEMConnection(
                self.url,
                (self.user, self.passwd),
                default_namespace='root/emc')

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
        targetVolName = None
        volumename = volume['id']

        loc = volume['provider_location']
        if self.conn is None:
            self.conn = self._get_ecom_connection()

        if isinstance(loc, six.string_types):
            name = ast.literal_eval(loc)
            keys = name['keybindings']
            systemName = keys['SystemName']
            admin_metadata = {}
            if 'admin_metadata' in volume:
                admin_metadata = volume.admin_metadata
            if 'targetVolumeName' in admin_metadata:
                targetVolName = admin_metadata['targetVolumeName']
            prefix1 = 'SYMMETRIX+'
            prefix2 = 'SYMMETRIX-+-'
            smiversion = self.utils.get_smi_version(self.conn)
            if smiversion > SMI_VERSION_8 and prefix1 in systemName:
                keys['SystemName'] = systemName.replace(prefix1, prefix2)
                name['keybindings'] = keys

            instancename = self.utils.get_instance_name(
                name['classname'], name['keybindings'])
            LOG.debug("Volume instance name: %(in)s",
                      {'in': instancename})
            # Allow for an external app to delete the volume.
            try:
                foundVolumeinstance = self.conn.GetInstance(instancename)
                volumeElementName = (self.utils.
                                     get_volume_element_name(volumename))
                if not (volumeElementName ==
                        foundVolumeinstance['ElementName']):
                    # Check if it is a vol created as part of a clone group
                    if not (targetVolName ==
                            foundVolumeinstance['ElementName']):
                        foundVolumeinstance = None
            except Exception as e:
                LOG.info(_LI("Exception in retrieving volume: %(e)s."),
                         {'e': e})
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

    def _wrap_find_device_number(self, volume, host):
        return self.find_device_number(volume, host)

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
        foundController = None
        foundNumDeviceNumber = None
        foundMaskingViewName = None
        volumeName = volume['name']
        volumeInstance = self._find_lun(volume)
        storageSystemName = volumeInstance['SystemName']
        isLiveMigration = False
        source_data = {}

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
                numDeviceNumber = int(unitinstance['DeviceNumber'], 16)
                foundNumDeviceNumber = numDeviceNumber
                foundController = controller
                controllerInstance = self.conn.GetInstance(controller,
                                                           LocalOnly=False)
                propertiesList = controllerInstance.properties.items()
                for properties in propertiesList:
                    if properties[0] == 'ElementName':
                        cimProperties = properties[1]
                        foundMaskingViewName = cimProperties.value

                devicedict = {'hostlunid': foundNumDeviceNumber,
                              'storagesystem': storageSystemName,
                              'maskingview': foundMaskingViewName,
                              'controller': foundController}
                maskedvols.append(devicedict)

        if not maskedvols:
            LOG.debug(
                "Device number not found for volume "
                "%(volumeName)s %(volumeInstance)s.",
                {'volumeName': volumeName,
                 'volumeInstance': volumeInstance.path})
        else:
            host = self.utils.get_host_short_name(host)
            hoststr = ("-%(host)s-"
                       % {'host': host})
            for maskedvol in maskedvols:
                if hoststr.lower() in maskedvol['maskingview'].lower():
                    data = maskedvol
            if not data:
                if len(maskedvols) > 0:
                    source_data = maskedvols[0]
                    LOG.warning(_LW(
                        "Volume is masked but not to host %(host)s as is "
                        "expected. Assuming live migration."),
                        {'host': hoststr})
                    isLiveMigration = True

        LOG.debug("Device info: %(data)s.", {'data': data})
        return data, isLiveMigration, source_data

    def get_target_wwns_list(self, storage_system, volume, connector):
        """Find target WWN list.

        :param storageSystem: the storage system name
        :param connector: the connector dict
        :returns: list -- targetWwns, the target WWN list
        :raises: VolumeBackendAPIException
        """
        targetWwns = set()
        try:
            fc_targets = self.get_target_wwns_from_masking_view(
                storage_system, volume, connector)
        except Exception:
            exception_message = _("Unable to get fc targets.")
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        LOG.debug("There are %(len)lu endpoints.", {'len': len(fc_targets)})
        for fc_target in fc_targets:
            wwn = fc_target
            # Add target wwn to the list if it is not already there.
            targetWwns.add(wwn)

        if not targetWwns:
            exception_message = (_(
                "Unable to get target endpoints."))
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Target WWNs: %(targetWwns)s.",
                  {'targetWwns': targetWwns})

        return list(targetWwns)

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
        self.ecomUseSSL = self.configuration.safe_get('driver_use_ssl')
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

    def _initial_setup(self, volume, volumeTypeId=None, host=None):
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
            extraSpecs, configurationFile, qosSpecs = (
                self._set_config_file_and_get_extra_specs(
                    volume, volumeTypeId))
            pool = self._validate_pool(volume, extraSpecs=extraSpecs,
                                       host=host)
            LOG.debug("Pool returned is %(pool)s.",
                      {'pool': pool})
            arrayInfo = self.utils.parse_file_to_get_array_map(
                configurationFile)
            if arrayInfo is not None:
                if extraSpecs['MultiPoolSupport'] is True:
                    poolRecord = arrayInfo[0]
                elif len(arrayInfo) == 1:
                    poolRecord = arrayInfo[0]
                else:
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
            if (qosSpecs.get('qos_specs')
                    and qosSpecs['qos_specs']['consumer'] != "front-end"):
                extraSpecs['qos'] = qosSpecs['qos_specs']['specs']
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
            maskingViewDict['isCompressionDisabled'] = False
            maskingViewDict['replication_enabled'] = False
            slo = extraSpecs[SLO]
            workload = extraSpecs[WORKLOAD]
            rep_enabled = self.utils.is_replication_enabled(extraSpecs)
            maskingViewDict['slo'] = slo
            maskingViewDict['workload'] = workload
            maskingViewDict['pool'] = uniqueName
            if slo:
                prefix = (
                    ("OS-%(shortHostName)s-%(poolName)s-%(slo)s-"
                     "%(workload)s-%(protocol)s"
                     % {'shortHostName': shortHostName,
                        'poolName': uniqueName,
                        'slo': slo,
                        'workload': workload,
                        'protocol': protocol}))
                doDisableCompression = self.utils.is_compression_disabled(
                    extraSpecs)
                if doDisableCompression:
                    prefix = ("%(prefix)s-CD"
                              % {'prefix': prefix})
                    maskingViewDict['isCompressionDisabled'] = True
            else:
                prefix = (
                    ("OS-%(shortHostName)s-No_SLO-%(protocol)s"
                     % {'shortHostName': shortHostName,
                        'protocol': protocol}))
            if rep_enabled:
                prefix += "-RE"
                maskingViewDict['replication_enabled'] = True
        else:
            maskingViewDict['fastPolicy'] = extraSpecs[FASTPOLICY]
            if maskingViewDict['fastPolicy']:
                uniqueName = self.utils.generate_unique_trunc_fastpolicy(
                    maskingViewDict['fastPolicy']) + '-FP'
            prefix = (
                ("OS-%(shortHostName)s-%(poolName)s-%(protocol)s"
                 % {'shortHostName': shortHostName,
                    'poolName': uniqueName,
                    'protocol': protocol}))

        maskingViewDict['sgGroupName'] = ("%(prefix)s-SG"
                                          % {'prefix': prefix})

        maskingViewDict['maskingViewName'] = ("%(prefix)s-MV"
                                              % {'prefix': prefix})

        maskingViewDict['maskingViewNameLM'] = ("%(prefix)s-%(volid)s-MV"
                                                % {'prefix': prefix,
                                                   'volid': volume['id'][:8]})
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
        if self._get_initiator_check_flag():
            maskingViewDict['initiatorCheck'] = True
        else:
            maskingViewDict['initiatorCheck'] = False

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
            self.conn, repServCapabilityInstanceName, extraSpecs[ISV3])

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

        if not isSnapshot:
            old_size_gbs = self.utils.convert_bits_to_gbs(
                self.utils.get_volume_size(
                    self.conn, sourceInstance))

            if cloneVolume['size'] != old_size_gbs:
                LOG.info(_LI("Extending clone %(cloneName)s to "
                             "%(newSize)d GBs"),
                         {'cloneName': cloneName,
                          'newSize': cloneVolume['size']})
                cloneInstance = self.utils.find_volume_instance(
                    self.conn, cloneDict, cloneName)
                self._extend_volume(
                    cloneVolume, cloneInstance, cloneName,
                    cloneVolume['size'], old_size_gbs, extraSpecs)

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

    def _delete_volume(self, volume, isSnapshot=False, host=None):
        """Helper function to delete the specified volume.

        :param volume: volume object to be deleted
        :returns: tuple -- rc (int return code), volumeName (string vol name)
        """

        volumeName = volume['name']
        rc = -1
        errorRet = (rc, volumeName)

        extraSpecs = self._initial_setup(volume, host=host)
        self.conn = self._get_ecom_connection()

        volumeInstance = self._find_lun(volume)
        if volumeInstance is None:
            LOG.error(_LE(
                "Volume %(name)s not found on the array. "
                "No volume to delete."),
                {'name': volumeName})
            return errorRet

        self._sync_check(volumeInstance, volumeName, extraSpecs)

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, volumeInstance['SystemName'])

        deviceId = volumeInstance['DeviceID']

        if extraSpecs[ISV3]:
            if isSnapshot:
                rc = self._delete_from_pool_v3(
                    storageConfigService, volumeInstance, volumeName,
                    deviceId, extraSpecs)
            else:
                rc = self._delete_from_pool_v3(
                    storageConfigService, volumeInstance, volumeName,
                    deviceId, extraSpecs, volume)
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
                storageGroupInstance = self.conn.GetInstance(
                    storageGroupInstanceName)
                self.masking.remove_device_from_storage_group(
                    self.conn, controllerConfigurationService,
                    storageGroupInstanceName, volumeInstanceName,
                    volumeName, storageGroupInstance['ElementName'],
                    extraSpecs)

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

    def _delete_snapshot(self, snapshot, host=None):
        """Helper function to delete the specified snapshot.

        :param snapshot: snapshot object to be deleted
        :raises: VolumeBackendAPIException
        """
        LOG.debug("Entering _delete_snapshot.")

        self.conn = self._get_ecom_connection()

        # Delete the target device.
        rc, snapshotname = self._delete_volume(snapshot, True, host)
        LOG.info(_LI("Leaving delete_snapshot: %(ssname)s  Return code: "
                     "%(rc)lu."),
                 {'ssname': snapshotname,
                  'rc': rc})

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        :param context: the context
        :param group: the group object to be created
        :returns: dict -- modelUpdate = {'status': 'available'}
        :raises: VolumeBackendAPIException
        """
        LOG.info(_LI("Create Consistency Group: %(group)s."),
                 {'group': group['id']})

        modelUpdate = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        cgName = self._update_consistency_group_name(group)

        self.conn = self._get_ecom_connection()

        # Find storage system.
        try:
            replicationService, storageSystem, __, __ = (
                self._get_consistency_group_utils(self.conn, group))
            interval_retries_dict = self.utils.get_default_intervals_retries()
            self.provision.create_consistency_group(
                self.conn, replicationService, cgName, interval_retries_dict)
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

        modelUpdate = {}
        volumes_model_update = {}
        if not self.conn:
            self.conn = self._get_ecom_connection()

        try:
            replicationService, storageSystem, __, isV3 = (
                self._get_consistency_group_utils(self.conn, group))

            storageConfigservice = (
                self.utils.find_storage_configuration_service(
                    self.conn, storageSystem))
            cgInstanceName, cgName = self._find_consistency_group(
                replicationService, six.text_type(group['id']))
            if cgInstanceName is None:
                LOG.error(_LE("Cannot find CG group %(cgName)s."),
                          {'cgName': six.text_type(group['id'])})
                modelUpdate = {'status': fields.ConsistencyGroupStatus.DELETED}
                volumes_model_update = self.utils.get_volume_model_updates(
                    volumes, group.id,
                    status='deleted')
                return modelUpdate, volumes_model_update

            memberInstanceNames = self._get_members_of_replication_group(
                cgInstanceName)
            interval_retries_dict = self.utils.get_default_intervals_retries()
            self.provision.delete_consistency_group(self.conn,
                                                    replicationService,
                                                    cgInstanceName, cgName,
                                                    interval_retries_dict)

            # Do a bulk delete, a lot faster than single deletes.
            if memberInstanceNames:
                volumes_model_update, modelUpdate = self._do_bulk_delete(
                    storageSystem, memberInstanceNames, storageConfigservice,
                    volumes, group, isV3, interval_retries_dict)

        except Exception:
            exceptionMessage = (_(
                "Failed to delete consistency group: %(cgName)s.")
                % {'cgName': six.text_type(group['id'])})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return modelUpdate, volumes_model_update

    def _do_bulk_delete(self, storageSystem, memberInstanceNames,
                        storageConfigservice, volumes, group, isV3,
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
            modelUpdate = {'status': fields.ConsistencyGroupStatus.DELETED}
        except Exception:
            modelUpdate = {
                'status': fields.ConsistencyGroupStatus.ERROR_DELETING}
        finally:
            volumes_model_update = self.utils.get_volume_model_updates(
                volumes, group['id'], status=modelUpdate['status'])

        return volumes_model_update, modelUpdate

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot.

        :param context: the context
        :param cgsnapshot: the consistency group snapshot to be created
        :param snapshots: snapshots
        :returns: dict -- modelUpdate
        :returns: list -- list of snapshots
        :raises: VolumeBackendAPIException
        """
        consistencyGroup = cgsnapshot.get('consistencygroup')

        snapshots_model_update = []

        LOG.info(_LI(
            "Create snapshot for Consistency Group %(cgId)s "
            "cgsnapshotID: %(cgsnapshot)s."),
            {'cgsnapshot': cgsnapshot['id'],
             'cgId': cgsnapshot['consistencygroup_id']})

        self.conn = self._get_ecom_connection()

        try:
            replicationService, storageSystem, extraSpecsDictList, isV3 = (
                self._get_consistency_group_utils(self.conn, consistencyGroup))

            cgInstanceName, cgName = (
                self._find_consistency_group(
                    replicationService, six.text_type(
                        cgsnapshot['consistencygroup_id'])))
            if cgInstanceName is None:
                exception_message = (_(
                    "Cannot find CG group %s.") % six.text_type(
                        cgsnapshot['consistencygroup_id']))
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            # Create the target consistency group.
            targetCgName = self._update_consistency_group_name(cgsnapshot)
            interval_retries_dict = self.utils.get_default_intervals_retries()
            self.provision.create_consistency_group(
                self.conn, replicationService, targetCgName,
                interval_retries_dict)
            targetCgInstanceName, targetCgName = self._find_consistency_group(
                replicationService, cgsnapshot['id'])
            LOG.info(_LI("Create target consistency group %(targetCg)s."),
                     {'targetCg': targetCgInstanceName})

            for snapshot in snapshots:
                volume = snapshot['volume']
                for extraSpecsDict in extraSpecsDictList:
                    if volume['volume_type_id'] in extraSpecsDict.values():
                        extraSpecs = extraSpecsDict.get('extraSpecs')
                        if 'pool_name' in extraSpecs:
                            extraSpecs = self.utils.update_extra_specs(
                                extraSpecs)
                if 'size' in volume:
                    volumeSizeInbits = int(self.utils.convert_gb_to_bits(
                        volume['size']))
                else:
                    volumeSizeInbits = int(self.utils.convert_gb_to_bits(
                        volume['volume_size']))
                targetVolumeName = 'targetVol'

                if isV3:
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
                          {'memberVol': volume['id'],
                           'targetVol': targetVolumeInstance.path})
                self.provision.add_volume_to_cg(self.conn,
                                                replicationService,
                                                targetCgInstanceName,
                                                targetVolumeInstance.path,
                                                targetCgName,
                                                targetVolumeName,
                                                extraSpecs)

            self._create_group_and_break_relationship(
                isV3, cgsnapshot['id'], replicationService, cgInstanceName,
                targetCgInstanceName, storageSystem, interval_retries_dict)

        except Exception:
            exceptionMessage = (_("Failed to create snapshot for cg:"
                                  " %(cgName)s.")
                                % {'cgName': cgsnapshot['consistencygroup_id']}
                                )
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot['id'],
                 'status': fields.SnapshotStatus.AVAILABLE})
        modelUpdate = {'status': fields.ConsistencyGroupStatus.AVAILABLE}

        return modelUpdate, snapshots_model_update

    def _create_group_and_break_relationship(
            self, isV3, cgsnapshotId, replicationService, cgInstanceName,
            targetCgInstanceName, storageSystem, interval_retries_dict):
        """Creates a cg group and deletes the relationship.

        :param isV3: the context
        :param cgsnapshotId: the consistency group snapshot id
        :param replicationService: replication service
        :param cgInstanceName: cg instance name
        :param targetCgInstanceName: target cg instance name
        :param storageSystem: storage system
        :param interval_retries_dict:
        """
        # Less than 5 characters relationship name.
        relationName = self.utils.truncate_string(cgsnapshotId, 5)
        if isV3:
            self.provisionv3.create_group_replica(
                self.conn, replicationService, cgInstanceName,
                targetCgInstanceName, relationName, interval_retries_dict)
        else:
            self.provision.create_group_replica(
                self.conn, replicationService, cgInstanceName,
                targetCgInstanceName, relationName, interval_retries_dict)
        # Break the replica group relationship.
        rgSyncInstanceName = self.utils.find_group_sync_rg_by_target(
            self.conn, storageSystem, targetCgInstanceName,
            interval_retries_dict, True)
        if rgSyncInstanceName is not None:
            repservice = self.utils.find_replication_service(
                self.conn, storageSystem)
            if repservice is None:
                exception_message = (_(
                    "Cannot find Replication service on system %s.") %
                    storageSystem)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
        if isV3:
            # Operation 7: dissolve for snapVx.
            operation = self.utils.get_num(9, '16')
            self.provisionv3.break_replication_relationship(
                self.conn, repservice, rgSyncInstanceName, operation,
                interval_retries_dict)
        else:
            self.provision.delete_clone_relationship(self.conn, repservice,
                                                     rgSyncInstanceName,
                                                     interval_retries_dict)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Delete a cgsnapshot.

        :param context: the context
        :param cgsnapshot: the consistency group snapshot to be created
        :param snapshots: snapshots
        :returns: dict -- modelUpdate
        :returns: list -- list of snapshots
        :raises: VolumeBackendAPIException
        """
        consistencyGroup = cgsnapshot.get('consistencygroup')
        model_update = {}
        snapshots_model_update = []
        LOG.info(_LI(
            "Delete snapshot for source CG %(cgId)s "
            "cgsnapshotID: %(cgsnapshot)s."),
            {'cgsnapshot': cgsnapshot['id'],
             'cgId': cgsnapshot['consistencygroup_id']})

        model_update['status'] = cgsnapshot['status']

        self.conn = self._get_ecom_connection()

        try:
            replicationService, storageSystem, __, isV3 = (
                self._get_consistency_group_utils(self.conn, consistencyGroup))
            interval_retries_dict = self.utils.get_default_intervals_retries()
            model_update, snapshots = self._delete_cg_and_members(
                storageSystem, cgsnapshot, model_update,
                snapshots, isV3, interval_retries_dict)
            for snapshot in snapshots:
                snapshots_model_update.append(
                    {'id': snapshot['id'],
                     'status': fields.SnapshotStatus.DELETED})
        except Exception:
            exceptionMessage = (_("Failed to delete snapshot for cg: "
                                  "%(cgId)s.")
                                % {'cgId': cgsnapshot['consistencygroup_id']})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return model_update, snapshots_model_update

    def _find_consistency_group(self, replicationService, cgId):
        """Finds a CG given its id.

        :param replicationService: the replication service
        :param cgId: the consistency group id
        :returns: foundCgInstanceName,cg_name
        """
        foundCgInstanceName = None
        cg_name = None
        cgInstanceNames = (
            self.conn.AssociatorNames(replicationService,
                                      ResultClass='CIM_ReplicationGroup'))

        for cgInstanceName in cgInstanceNames:
            instance = self.conn.GetInstance(cgInstanceName, LocalOnly=False)
            if cgId in instance['ElementName']:
                foundCgInstanceName = cgInstanceName
                cg_name = instance['ElementName']
                break

        return foundCgInstanceName, cg_name

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
            # If qos exists, update storage group to reflect qos parameters
            if 'qos' in extraSpecs:
                self.utils.update_storagegroup_qos(
                    self.conn, defaultStorageGroupInstanceName, extraSpecs)

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
        rc = -1
        volumeDict = {}
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

        # Check to see if SLO and Workload are configured on the array.
        storagePoolCapability = self.provisionv3.get_storage_pool_capability(
            self.conn, poolInstanceName)
        if extraSpecs[SLO]:
            if storagePoolCapability:
                storagePoolSetting = self.provisionv3.get_storage_pool_setting(
                    self.conn, storagePoolCapability, extraSpecs[SLO],
                    extraSpecs[WORKLOAD])
                if not storagePoolSetting:
                    exceptionMessage = (_(
                        "The array does not support the storage pool setting "
                        "for SLO %(slo)s or workload %(workload)s. Please "
                        "check the array for valid SLOs and workloads.")
                        % {'slo': extraSpecs[SLO],
                           'workload': extraSpecs[WORKLOAD]})
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)
            else:
                exceptionMessage = (_(
                    "Cannot determine storage pool settings."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("Create Volume: %(volume)s  Pool: %(pool)s "
                  "Storage System: %(storageSystem)s "
                  "Size: %(size)lu.",
                  {'volume': volumeName,
                   'pool': poolInstanceName,
                   'storageSystem': storageSystemName,
                   'size': volumeSize})

        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, storageSystemName)
        doDisableCompression = self.utils.is_compression_disabled(extraSpecs)

        # A volume created without specifying a storage group during
        # creation time is allocated from the default SRP pool and
        # assigned the optimized SLO.
        sgInstanceName = self._get_or_create_storage_group_v3(
            extraSpecs[POOL], extraSpecs[SLO],
            extraSpecs[WORKLOAD], doDisableCompression,
            storageSystemName, extraSpecs)
        try:
            volumeDict, rc = self.provisionv3.create_volume_from_sg(
                self.conn, storageConfigService, volumeName,
                sgInstanceName, volumeSize, extraSpecs)
        except Exception:
            # if the volume create fails, check if the
            # storage group needs to be cleaned up
            volumeInstanceNames = (
                self.masking.get_devices_from_storage_group(
                    self.conn, sgInstanceName))

            if not len(volumeInstanceNames):
                LOG.debug("There are no volumes in the storage group "
                          "%(maskingGroup)s. Deleting storage group",
                          {'maskingGroup': sgInstanceName})
                controllerConfigService = (
                    self.utils.find_controller_configuration_service(
                        self.conn, storageSystemName))
                self.masking.delete_storage_group(
                    self.conn, controllerConfigService,
                    sgInstanceName, extraSpecs)
            raise

        return rc, volumeDict, storageSystemName

    def _get_or_create_storage_group_v3(
            self, poolName, slo, workload, doDisableCompression,
            storageSystemName, extraSpecs, is_re=False):
        """Get or create storage group_v3 (V3).

        :param poolName: the SRP pool nsmr
        :param slo: the SLO
        :param workload: the workload
        :param doDisableCompression: flag for compression
        :param storageSystemName: storage system name
        :param extraSpecs: extra specifications
        :param is_re: flag for replication
        :returns: sgInstanceName
        """
        storageGroupName, controllerConfigService, sgInstanceName = (
            self.utils.get_v3_default_sg_instance_name(
                self.conn, poolName, slo, workload, storageSystemName,
                doDisableCompression, is_re))
        if sgInstanceName is None:
            sgInstanceName = self.provisionv3.create_storage_group_v3(
                self.conn, controllerConfigService, storageGroupName,
                poolName, slo, workload, extraSpecs, doDisableCompression)
        else:
            # Check that SG is not part of a masking view
            mvInstanceName = self.masking.get_masking_view_from_storage_group(
                self.conn, sgInstanceName)
            if mvInstanceName:
                exceptionMessage = (_(
                    "Default storage group %(storageGroupName)s is part of "
                    "masking view %(mvInstanceName)s.  Please remove it "
                    "from this and all masking views")
                    % {'storageGroupName': storageGroupName,
                       'mvInstanceName': mvInstanceName})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        # If qos exists, update storage group to reflect qos parameters
        if 'qos' in extraSpecs:
            self.utils.update_storagegroup_qos(
                self.conn, sgInstanceName, extraSpecs)

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
        isCompressionDisabled = self.utils.is_compression_disabled(extraSpecs)
        storageGroupName = self.utils.get_v3_storage_group_name(
            extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD],
            isCompressionDisabled)
        # Check if old type and new type have different compression types
        doChangeCompression = (
            self.utils.change_compression_type(
                isCompressionDisabled, newType))
        volumeInstanceName = volumeInstance.path
        isValid, targetSlo, targetWorkload = (
            self._is_valid_for_storage_assisted_migration_v3(
                volumeInstanceName, host, extraSpecs[ARRAY],
                extraSpecs[POOL], volumeName, volumeStatus,
                storageGroupName, doChangeCompression))

        storageSystemName = volumeInstance['SystemName']
        if not isValid:
            LOG.error(_LE(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype."),
                {'name': volumeName})
            return False
        if volume['host'] != host['host'] or doChangeCompression:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s. Compression change is %(cc)r.",
                {'name': volumeName,
                 'sourceHost': volume['host'],
                 'targetHost': host['host'],
                 'cc': doChangeCompression})
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
        isCompressionDisabled = self.utils.is_compression_disabled(extraSpecs)
        defaultSgName = self.utils.get_v3_storage_group_name(
            extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD],
            isCompressionDisabled)
        foundStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(
                self.conn, volumeInstance.path, defaultSgName))
        if foundStorageGroupInstanceName is None:
            LOG.warning(_LW(
                "Volume : %(volumeName)s is not currently "
                "belonging to any storage group."),
                {'volumeName': volumeName})
        else:
            self.masking.remove_and_reset_members(
                self.conn, controllerConfigService, volumeInstance,
                volumeName, extraSpecs, None, False)

        targetExtraSpecs = newType['extra_specs']
        isCompressionDisabled = self.utils.is_compression_disabled(
            targetExtraSpecs)

        storageGroupName = self.utils.get_v3_storage_group_name(
            poolName, targetSlo, targetWorkload, isCompressionDisabled)

        targetSgInstanceName = self._get_or_create_storage_group_v3(
            poolName, targetSlo, targetWorkload, isCompressionDisabled,
            storageSystemName, extraSpecs)
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
        :returns: location_info, total_capacity_gb, free_capacity_gb,
        provisioned_capacity_gb
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
            (total_capacity_gb, free_capacity_gb, provisioned_capacity_gb,
             array_max_over_subscription) = (
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
            (total_capacity_gb, free_capacity_gb, provisioned_capacity_gb,
             array_max_over_subscription) = (
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

        return (location_info, total_capacity_gb, free_capacity_gb,
                provisioned_capacity_gb, array_max_over_subscription)

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
        if extraSpecs['MultiPoolSupport'] is True:
            sloFromExtraSpec = None
            workloadFromExtraSpec = None
            if 'pool_name' in extraSpecs:
                try:
                    poolDetails = extraSpecs['pool_name'].split('+')
                    sloFromExtraSpec = poolDetails[0]
                    workloadFromExtraSpec = poolDetails[1]
                except KeyError:
                    LOG.error(_LE("Error parsing SLO, workload from "
                                  "the provided extra_specs."))
            else:
                # Throw an exception as it is compulsory to have
                # pool_name in the extra specs
                exceptionMessage = (_(
                    "Pool_name is not present in the extraSpecs "
                    "and MultiPoolSupport is enabled"))
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
            # If MultiPoolSupport is enabled, we completely
            # ignore any entry for SLO & Workload in the poolRecord
            extraSpecs[SLO] = sloFromExtraSpec
            extraSpecs[WORKLOAD] = workloadFromExtraSpec
        else:
            extraSpecs[SLO] = poolRecord['SLO']
            extraSpecs[WORKLOAD] = poolRecord['Workload']

        extraSpecs[ISV3] = True
        extraSpecs = self._set_common_extraSpecs(extraSpecs, poolRecord)
        if self.utils.is_all_flash(self.conn, extraSpecs[ARRAY]):
            try:
                extraSpecs[self.utils.DISABLECOMPRESSION]
                # If not True remove it.
                if not self.utils.str2bool(
                        extraSpecs[self.utils.DISABLECOMPRESSION]):
                    extraSpecs.pop(self.utils.DISABLECOMPRESSION, None)
            except KeyError:
                pass
        else:
            extraSpecs.pop(self.utils.DISABLECOMPRESSION, None)
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
                             volumeName, deviceId, extraSpecs, volume=None):
        """Delete from pool (v3).

        :param storageConfigService: the storage config service
        :param volumeInstance: the volume instance
        :param volumeName: the volume Name
        :param deviceId: the device ID of the volume
        :param extraSpecs: extra specifications
        :param volume: the cinder volume object
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        storageSystemName = volumeInstance['SystemName']
        controllerConfigurationService = (
            self.utils.find_controller_configuration_service(
                self.conn, storageSystemName))

        # Check if it is part of a storage group and delete it
        # extra logic for case when volume is the last member.
        self.masking.remove_and_reset_members(
            self.conn, controllerConfigurationService, volumeInstance,
            volumeName, extraSpecs, None, False)

        if volume and self.utils.is_replication_enabled(extraSpecs):
            self.cleanup_lun_replication(self.conn, volume, volumeName,
                                         volumeInstance, extraSpecs)

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
            self.masking.return_volume_to_default_storage_group_v3(
                self.conn, controllerConfigurationService,
                volumeInstance, volumeName, extraSpecs)

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
        cloneId = cloneVolume['id']
        cloneName = self.utils.get_volume_element_name(cloneId)

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
                syncInstanceName = self.utils.find_sync_sv_by_volume(
                    self.conn, storageSystem, targetInstance, extraSpecs,
                    False)
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

    def get_initiator_group_from_masking_view(self, maskingViewInstanceName):
        """Get the initiator group in a masking view.

        :param maskingViewInstanceName: masking view instance name
        :returns: initiatorGroupInstanceName
        """
        return self.masking.get_initiator_group_from_masking_view(
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

    def get_masking_views_by_initiator_group(
            self, initiatorGroupInstanceName):
        """Given initiator group, retrieve the masking view instance name.

        :param initiatorGroupInstanceName: initiator group instance name
        :returns: list -- maskingViewInstanceNames
        """
        LOG.debug("Finding Masking Views for initiator group %(ig)s.",
                  {'ig': initiatorGroupInstanceName})
        return self.masking.get_masking_views_by_initiator_group(
            self.conn, initiatorGroupInstanceName)

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
        cloneId = cloneVolume['id']
        cloneName = self.utils.get_volume_element_name(cloneId)
        # SyncType 7: snap, VG3R default snapshot is snapVx.
        syncType = self.utils.get_num(SNAPVX, '16')
        # Operation 9: Dissolve for snapVx.
        operation = self.utils.get_num(DISSOLVE_SNAPVX, '16')
        rsdInstance = None
        targetInstance = None
        copyState = self.utils.get_num(4, '16')
        if isSnapshot:
            rsdInstance = self.utils.set_target_element_supplier_in_rsd(
                self.conn, repServiceInstanceName, SNAPVX_REPLICATION_TYPE,
                CREATE_NEW_TARGET, extraSpecs)
        else:
            targetInstance = self._create_duplicate_volume(
                sourceInstance, cloneName, extraSpecs)

        try:
            rc, job = (
                self.provisionv3.create_element_replica(
                    self.conn, repServiceInstanceName, cloneName, syncType,
                    sourceInstance, extraSpecs, targetInstance, rsdInstance,
                    copyState))
        except Exception:
            LOG.warning(_LW(
                "Clone failed on V3. Cleaning up the target volume. "
                "Clone name: %(cloneName)s "),
                {'cloneName': cloneName})
            if targetInstance:
                self._cleanup_target(
                    repServiceInstanceName, targetInstance, extraSpecs)
                # Re-throw the exception.
                raise

        cloneDict = self.provisionv3.get_volume_dict_from_job(
            self.conn, job['Job'])
        targetVolumeInstance = (
            self.provisionv3.get_volume_from_job(self.conn, job['Job']))
        LOG.info(_LI("The target instance device id is: %(deviceid)s."),
                 {'deviceid': targetVolumeInstance['DeviceID']})

        if not isSnapshot:
            cloneVolume['provider_location'] = six.text_type(cloneDict)

            syncInstanceName, _storageSystem = (
                self._find_storage_sync_sv_sv(cloneVolume, sourceVolume,
                                              extraSpecs, True))

            rc, job = self.provisionv3.break_replication_relationship(
                self.conn, repServiceInstanceName, syncInstanceName,
                operation, extraSpecs)
        return rc, cloneDict

    def _cleanup_target(
            self, repServiceInstanceName, targetInstance, extraSpecs):
        """cleanup target after exception

        :param repServiceInstanceName: the replication service
        :param targetInstance: the target instance
        :param extraSpecs: extra specifications
        """
        storageSystem = targetInstance['SystemName']
        syncInstanceName = self.utils.find_sync_sv_by_volume(
            self.conn, storageSystem, targetInstance, False)
        if syncInstanceName is not None:
            # Break the clone relationship.
            self.provisionv3.break_replication_relationship(
                self.conn, repServiceInstanceName, syncInstanceName,
                DISSOLVE_SNAPVX, extraSpecs, True)
        storageConfigService = (
            self.utils.find_storage_configuration_service(
                self.conn, storageSystem))
        deviceId = targetInstance['DeviceID']
        volumeName = targetInstance['Name']
        self._delete_from_pool_v3(
            storageConfigService, targetInstance, volumeName,
            deviceId, extraSpecs)

    def _delete_cg_and_members(
            self, storageSystem, cgsnapshot, modelUpdate, volumes, isV3,
            extraSpecs):
        """Helper function to delete a consistencygroup and its member volumes.

        :param storageSystem: storage system
        :param cgsnapshot: consistency group snapshot
        :param modelUpdate: dict -- the model update dict
        :param volumes: the list of member volumes
        :param isV3: boolean
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
        cgInstanceName, cgName = self._find_consistency_group(
            replicationService, six.text_type(cgsnapshot['id']))

        if cgInstanceName is None:
            LOG.error(_LE("Cannot find CG group %(cgName)s."),
                      {'cgName': cgsnapshot['id']})
            modelUpdate = {'status': fields.ConsistencyGroupStatus.DELETED}
            return modelUpdate, []

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

    def _validate_pool(self, volume, extraSpecs=None, host=None):
        """Get the pool from volume['host'].

        There may be backward compatibiliy concerns, so putting in a
        check to see if a version has been added to provider_location.
        If it has, we know we are at the current version, if not, we
        assume it was created pre 'Pool Aware Scheduler' feature.

        :param volume: the volume Object
        :param extraSpecs: extraSpecs provided in the volume type
        :returns: string -- pool
        :raises: VolumeBackendAPIException
        """
        pool = None
        # Volume is None in CG ops.
        if volume is None:
            return pool

        if host is None:
            host = volume['host']

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
            pool = volume_utils.extract_host(host, 'pool')
            if pool:
                LOG.debug("Pool from volume['host'] is %(pool)s.",
                          {'pool': pool})
                # Check if it matches with the poolname if it is provided
                #  in the extra specs
                if extraSpecs is not None:
                    if 'pool_name' in extraSpecs:
                        if extraSpecs['pool_name'] != pool:
                            exceptionMessage = (_(
                                "Pool from volume['host'] %(host)s doesn't"
                                " match with pool_name in extraSpecs.")
                                % {'host': volume['host']})
                            raise exception.VolumeBackendAPIException(
                                data=exceptionMessage)
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
                name = ast.literal_eval(loc)
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
        arrayName, deviceId = self.utils.get_array_and_device_id(
            volume, external_ref)

        self.utils.check_volume_no_fast(extraSpecs)

        volumeInstanceName = (
            self.utils.find_volume_by_device_id_on_array(
                arrayName, deviceId))

        self.utils.check_volume_not_in_masking_view(
            self.conn, volumeInstanceName, deviceId)

        cinderPoolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(extraSpecs))

        self.utils.check_volume_not_replication_source(
            self.conn, storageSystemName, deviceId)

        self.utils.check_is_volume_in_cinder_managed_pool(
            self.conn, volumeInstanceName, cinderPoolInstanceName,
            deviceId)

        volumeId = volume.name
        volumeElementName = self.utils.get_volume_element_name(volumeId)
        LOG.debug("Rename volume %(vol)s to %(volumeId)s.",
                  {'vol': volumeInstanceName,
                   'volumeId': volumeElementName})

        volumeInstance = self.utils.rename_volume(self.conn,
                                                  volumeInstanceName,
                                                  volumeElementName)
        keys = {}
        volpath = volumeInstance.path
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']

        provider_location = {}
        provider_location['classname'] = volpath['CreationClassName']
        provider_location['keybindings'] = keys

        model_update = self.set_volume_replication_if_enabled(
            self.conn, extraSpecs, volume, provider_location)

        volumeDisplayName = volume.display_name
        model_update.update(
            {'display_name': volumeDisplayName})
        model_update.update(
            {'provider_location': six.text_type(provider_location)})
        return model_update

    def set_volume_replication_if_enabled(self, conn, extraSpecs,
                                          volume, provider_location):
        """Set volume replication if enabled

        If volume replication is enabled, set relevant
        values in associated model_update dict.

        :param conn: connection to the ecom server
        :param extraSpecs: additional info
        :param volume: the volume object
        :param provider_location: volume classname & keybindings
        :return: updated model_update
        """
        model_update = {}
        if self.utils.is_replication_enabled(extraSpecs):
            replication_status, replication_driver_data = (
                self.setup_volume_replication(
                    conn, volume, provider_location, extraSpecs))
            model_update.update(
                {'replication_status': replication_status})
            model_update.update(
                {'replication_driver_data': six.text_type(
                    replication_driver_data)})

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
            self.utils.find_volume_by_device_id_on_array(arrayName, deviceId))

        try:
            volumeInstance = self.conn.GetInstance(volumeInstanceName)
            byteSize = self.utils.get_volume_size(self.conn, volumeInstance)
            fByteSize = float(byteSize)
            gbSize = int(fByteSize / units.Gi)

        except Exception:
            exceptionMessage = (_("Volume %(deviceID)s not found.")
                                % {'deviceID': deviceId})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug(
            "Size of volume %(deviceID)s is %(volumeSize)s GB",
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
        self.utils.rename_volume(self.conn, volumeInstance, volumeId)

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

        modelUpdate = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        cg_name = self._update_consistency_group_name(group)
        add_vols = [vol for vol in add_volumes] if add_volumes else []
        add_instance_names = self._get_volume_instance_names(add_vols)
        remove_vols = [vol for vol in remove_volumes] if remove_volumes else []
        remove_instance_names = self._get_volume_instance_names(remove_vols)
        self.conn = self._get_ecom_connection()

        try:
            replicationService, storageSystem, __, __ = (
                self._get_consistency_group_utils(self.conn, group))
            cgInstanceName, __ = (
                self._find_consistency_group(
                    replicationService, six.text_type(group['id'])))
            if cgInstanceName is None:
                raise exception.ConsistencyGroupNotFound(
                    consistencygroup_id=cg_name)
            # Add volume(s) to a consistency group
            interval_retries_dict = self.utils.get_default_intervals_retries()
            if add_instance_names:
                self.provision.add_volume_to_cg(
                    self.conn, replicationService, cgInstanceName,
                    add_instance_names, cg_name, None,
                    interval_retries_dict)
            # Remove volume(s) from a consistency group
            if remove_instance_names:
                self.provision.remove_volume_from_cg(
                    self.conn, replicationService, cgInstanceName,
                    remove_instance_names, cg_name, None,
                    interval_retries_dict)
        except exception.ConsistencyGroupNotFound:
            raise
        except Exception as ex:
            LOG.error(_LE("Exception: %(ex)s"), {'ex': ex})
            exceptionMessage = (_("Failed to update consistency group:"
                                  " %(cgName)s.")
                                % {'cgName': group['id']})
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
                                         cgsnapshot, snapshots, source_cg,
                                         source_vols):
        """Creates the consistency group from source.

        :param context: the context
        :param group: the consistency group object to be created
        :param volumes: volumes in the consistency group
        :param cgsnapshot: the source consistency group snapshot
        :param snapshots: snapshots of the source volumes
        :param source_cg: the source consistency group
        :param source_vols: the source vols
        :returns: model_update, volumes_model_update
                  model_update is a dictionary of cg status
                  volumes_model_update is a list of dictionaries of volume
                  update
        """
        if cgsnapshot:
            source_vols_or_snapshots = snapshots
            source_id = cgsnapshot['id']
        elif source_cg:
            source_vols_or_snapshots = source_vols
            source_id = source_cg['id']
        else:
            exceptionMessage = (_("Must supply either CG snaphot or "
                                  "a source CG."))
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        LOG.debug("Enter EMCVMAXCommon::create_consistencygroup_from_src. "
                  "Group to be created: %(cgId)s, "
                  "Source : %(SourceCGId)s.",
                  {'cgId': group['id'],
                   'SourceCGId': source_id})

        self.create_consistencygroup(context, group)

        modelUpdate = {'status': fields.ConsistencyGroupStatus.AVAILABLE}

        try:
            replicationService, storageSystem, extraSpecsDictList, isV3 = (
                self._get_consistency_group_utils(self.conn, group))
            if replicationService is None:
                exceptionMessage = (_(
                    "Cannot find replication service on system %s.") %
                    storageSystem)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
            targetCgInstanceName, targetCgName = self._find_consistency_group(
                replicationService, six.text_type(group['id']))
            LOG.debug("Create CG %(targetCg)s from snapshot.",
                      {'targetCg': targetCgInstanceName})
            dictOfVolumeDicts = {}
            targetVolumeNames = {}
            for volume, source_vol_or_snapshot in zip(
                    volumes, source_vols_or_snapshots):
                if 'size' in source_vol_or_snapshot:
                    volumeSizeInbits = int(self.utils.convert_gb_to_bits(
                        source_vol_or_snapshot['size']))
                else:
                    volumeSizeInbits = int(self.utils.convert_gb_to_bits(
                        source_vol_or_snapshot['volume_size']))
                for extraSpecsDict in extraSpecsDictList:
                    if volume['volume_type_id'] in extraSpecsDict.values():
                        extraSpecs = extraSpecsDict.get('extraSpecs')
                        if 'pool_name' in extraSpecs:
                            extraSpecs = self.utils.update_extra_specs(
                                extraSpecs)
                        # Create a random UUID and use it as volume name
                        targetVolumeName = six.text_type(uuid.uuid4())
                        volumeDict = self._create_vol_and_add_to_cg(
                            volumeSizeInbits, replicationService,
                            targetCgInstanceName, targetCgName,
                            source_vol_or_snapshot['id'],
                            extraSpecs, targetVolumeName)
                        dictOfVolumeDicts[volume['id']] = volumeDict
                        targetVolumeNames[volume['id']] = targetVolumeName

            interval_retries_dict = self.utils.get_default_intervals_retries()
            self._break_replica_group_relationship(
                replicationService, source_id, group['id'],
                targetCgInstanceName, storageSystem, interval_retries_dict,
                isV3)
        except Exception:
            exceptionMessage = (_("Failed to create CG %(cgName)s "
                                  "from source %(cgSnapshot)s.")
                                % {'cgName': group['id'],
                                   'cgSnapshot': source_id})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)
        volumes_model_update = self.utils.get_volume_model_updates(
            volumes, group['id'], modelUpdate['status'])

        # Update the provider_location
        for volume_model_update in volumes_model_update:
            if volume_model_update['id'] in dictOfVolumeDicts:
                volume_model_update.update(
                    {'provider_location': six.text_type(
                        dictOfVolumeDicts[volume_model_update['id']])})

        # Update the volumes_model_update with admin_metadata
        self.update_admin_metadata(volumes_model_update,
                                   key='targetVolumeName',
                                   values=targetVolumeNames)

        return modelUpdate, volumes_model_update

    def update_admin_metadata(
            self, volumes_model_update, key, values):
        """Update the volume_model_updates with admin metadata

        :param volumes_model_update: List of volume model updates
        :param key: Key to be updated in the admin_metadata
        :param values: Dictionary of values per volume id
        """
        for volume_model_update in volumes_model_update:
            volume_id = volume_model_update['id']
            if volume_id in values:
                    admin_metadata = {}
                    admin_metadata.update({key: values[volume_id]})
                    volume_model_update.update(
                        {'admin_metadata': admin_metadata})

    def _break_replica_group_relationship(
            self, replicationService, source_id, group_id,
            targetCgInstanceName, storageSystem, extraSpecs, isV3):
        """Breaks the replica group relationship.

        :param replicationService: replication service
        :param source_id: source identifier
        :param group_id: group identifier
        :param targetCgInstanceName: target CG instance
        :param storageSystem: storage system
        :param extraSpecs: additional info
        """
        sourceCgInstanceName, sourceCgName = self._find_consistency_group(
            replicationService, source_id)
        if sourceCgInstanceName is None:
            exceptionMessage = (_("Cannot find source CG instance. "
                                  "consistencygroup_id: %s.") %
                                source_id)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        relationName = self.utils.truncate_string(group_id, TRUNCATE_5)
        if isV3:
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
            if isV3:
                # Operation 9: dissolve for snapVx
                operation = self.utils.get_num(9, '16')
                self.provisionv3.break_replication_relationship(
                    self.conn, replicationService, rgSyncInstanceName,
                    operation, extraSpecs)
            else:
                self.provision.delete_clone_relationship(
                    self.conn, replicationService,
                    rgSyncInstanceName, extraSpecs)

    def _create_vol_and_add_to_cg(
            self, volumeSizeInbits, replicationService,
            targetCgInstanceName, targetCgName, source_id,
            extraSpecs, targetVolumeName):
        """Creates volume and adds to CG.

        :param context: the context
        :param volumeSizeInbits: volume size in bits
        :param replicationService: replication service
        :param targetCgInstanceName: target cg instance
        :param targetCgName: target cg name
        :param source_id: source identifier
        :param extraSpecs: additional info
        :param targetVolumeName: volume name for the target volume
        :returns volumeDict: volume dictionary for the newly created volume
        """
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
                  "Source : %(snapshot)s, "
                  "Target volume: %(targetVol)s.",
                  {'snapshot': source_id,
                   'targetVol': targetVolumeInstance.path})

        self.provision.add_volume_to_cg(self.conn,
                                        replicationService,
                                        targetCgInstanceName,
                                        targetVolumeInstance.path,
                                        targetCgName,
                                        targetVolumeName,
                                        extraSpecs)
        return volumeDict

    def _find_ip_protocol_endpoints(self, conn, storageSystemName,
                                    portgroupname):
        """Find the IP protocol endpoint for ISCSI.

        :param storageSystemName: the system name
        :param portgroupname: the portgroup name
        :returns: foundIpAddresses
        """
        LOG.debug("The portgroup name for iscsiadm is %(pg)s",
                  {'pg': portgroupname})
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
                endpoint = {}
                for ipendpointinstancename in ipendpointinstancenames:
                    endpoint = self.get_ip_and_iqn(conn, endpoint,
                                                   ipendpointinstancename)
                if bool(endpoint):
                    foundipaddresses.append(endpoint)
        return foundipaddresses

    def _extend_v3_volume(self, volumeInstance, volumeName, newSize,
                          extraSpecs):
        """Extends a VMAX3 volume.

        :param volumeInstance: volume instance
        :param volumeName: volume name
        :param newSize: new size the volume will be increased to
        :param extraSpecs: extra specifications
        :returns: int -- return code
        :returns: volumeDict
        """
        new_size_in_bits = int(self.utils.convert_gb_to_bits(newSize))
        storageConfigService = self.utils.find_storage_configuration_service(
            self.conn, volumeInstance['SystemName'])
        volumeDict, rc = self.provisionv3.extend_volume_in_SG(
            self.conn, storageConfigService, volumeInstance.path,
            volumeName, new_size_in_bits, extraSpecs)

        return rc, volumeDict

    def _create_duplicate_volume(
            self, sourceInstance, cloneName, extraSpecs):
        """Create a volume in the same dimensions of the source volume.

        :param sourceInstance: the source volume instance
        :param cloneName: the user supplied snap name
        :param extraSpecs: additional info
        :returns: targetInstance
        """
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
                  "Source Volume: %(sourceVol)s, "
                  "Target Volume: %(targetVol)s.",
                  {'sourceVol': sourceInstance.path,
                   'targetVol': targetInstance.path})
        return targetInstance

    def get_ip_and_iqn(self, conn, endpoint, ipendpointinstancename):
        """Get ip and iqn from the endpoint.

        :param conn: ecom connection
        :param endpoint: end point
        :param ipendpointinstancename: ip endpoint
        :returns: endpoint
        """
        if ('iSCSIProtocolEndpoint' in six.text_type(
                ipendpointinstancename['CreationClassName'])):
            iqn = self.utils.get_iqn(conn, ipendpointinstancename)
            if iqn:
                endpoint['iqn'] = iqn
        elif ('IPProtocolEndpoint' in six.text_type(
                ipendpointinstancename['CreationClassName'])):
            ipaddress = (
                self.utils.get_iscsi_ip_address(
                    conn, ipendpointinstancename))
            if ipaddress:
                endpoint['ip'] = ipaddress

        return endpoint

    def _get_consistency_group_utils(self, conn, group):
        """Standard utility for consistency group.

        :param conn: ecom connection
        :param group: the consistency group object to be created
        :return: replicationService, storageSystem, extraSpecs, isV3
        """
        storageSystems = set()
        extraSpecsDictList = []
        isV3 = False

        if isinstance(group, Group):
            for volume_type in group.volume_types:
                extraSpecsDict, storageSystems, isV3 = (
                    self._update_extra_specs_list(
                        volume_type.extra_specs, len(group.volume_types),
                        volume_type.id))
                extraSpecsDictList.append(extraSpecsDict)
        elif isinstance(group, ConsistencyGroup):
            volumeTypeIds = group.volume_type_id.split(",")
            volumeTypeIds = list(filter(None, volumeTypeIds))
            for volumeTypeId in volumeTypeIds:
                if volumeTypeId:
                    extraSpecs = self.utils.get_volumetype_extraspecs(
                        None, volumeTypeId)
                    extraSpecsDict, storageSystems, isV3 = (
                        self._update_extra_specs_list(
                            extraSpecs, len(volumeTypeIds),
                            volumeTypeId))
                extraSpecsDictList.append(extraSpecsDict)
        else:
            msg = (_("Unable to get volume type ids."))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if len(storageSystems) != 1:
            if not storageSystems:
                msg = (_("Failed to get a single storage system "
                         "associated with consistencygroup_id: %(groupid)s.")
                       % {'groupid': group.id})
            else:
                msg = (_("There are multiple storage systems "
                         "associated with consistencygroup_id: %(groupid)s.")
                       % {'groupid': group.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        storageSystem = storageSystems.pop()
        replicationService = self.utils.find_replication_service(
            conn, storageSystem)
        return replicationService, storageSystem, extraSpecsDictList, isV3

    def _update_extra_specs_list(
            self, extraSpecs, list_size, volumeTypeId):
        """Update the extra specs list.

        :param extraSpecs: extraSpecs
        :param list_size: the size of volume type list
        :param volumeTypeId: volume type identifier
        :return: extraSpecsDictList, storageSystems, isV3
        """
        storageSystems = set()
        extraSpecsDict = {}
        if 'pool_name' in extraSpecs:
            isV3 = True
            extraSpecs = self.utils.update_extra_specs(
                extraSpecs)
            extraSpecs[ISV3] = True
        else:
            # Without multipool we cannot support multiple volumetypes.
            if list_size == 1:
                extraSpecs = self._initial_setup(None, volumeTypeId)
                isV3 = extraSpecs[ISV3]
            else:
                msg = (_("We cannot support multiple volume types if "
                         "multi pool functionality is not enabled."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        __, storageSystem = (
            self._get_pool_and_storage_system(extraSpecs))
        if storageSystem:
            storageSystems.add(storageSystem)
        extraSpecsDict["volumeTypeId"] = volumeTypeId
        extraSpecsDict["extraSpecs"] = extraSpecs
        return extraSpecsDict, storageSystems, isV3

    def _update_consistency_group_name(self, group):
        """Format id and name consistency group

        :param group: the consistency group object to be created
        :param update_variable: the variable of the group to be used
        :return: cgname -- formatted name + id
        """
        cgName = ""
        if group['name'] is not None:
            cgName = (
                self.utils.truncate_string(group['name'], TRUNCATE_27) + "_")

        cgName += six.text_type(group["id"])
        return cgName

    def _sync_check(self, volumeInstance, volumeName, extraSpecs):
        """Check if volume is part of a snapshot/clone sync process.

        :param volumeInstance: volume instance
        :param volumeName: volume name
        :param extraSpecs: extra specifications
        """
        storageSystem = volumeInstance['SystemName']

        # Wait for it to fully sync in case there is an ongoing
        # create volume from snapshot request.
        syncInstanceName = self.utils.find_sync_sv_by_volume(
            self.conn, storageSystem, volumeInstance, extraSpecs,
            True)

        if syncInstanceName:
            repservice = self.utils.find_replication_service(self.conn,
                                                             storageSystem)

            # Break the replication relationship
            LOG.debug("Deleting snap relationship: Source: %(volume)s "
                      "Synchronization: %(syncName)s.",
                      {'volume': volumeName,
                       'syncName': syncInstanceName})
            if extraSpecs[ISV3]:
                rc, job = self.provisionv3.break_replication_relationship(
                    self.conn, repservice, syncInstanceName,
                    DISSOLVE_SNAPVX, extraSpecs)
            else:
                self.provision.delete_clone_relationship(
                    self.conn, repservice, syncInstanceName, extraSpecs, True)

    def setup_volume_replication(self, conn, sourceVolume, volumeDict,
                                 extraSpecs, targetInstance=None):
        """Setup replication for volume, if enabled.

        Called on create volume, create cloned volume,
        create volume from snapshot, manage_existing,
        and re-establishing a replication relationship after extending.

        :param conn: the connection to the ecom server
        :param sourceVolume: the source volume object
        :param volumeDict: the source volume dict (the provider_location)
        :param extraSpecs: extra specifications
        :param targetInstance: optional, target on secondary array
        :return: rep_update - dict
        """
        isTargetV3 = self.utils.isArrayV3(conn, self.rep_config['array'])
        if not extraSpecs[ISV3] or not isTargetV3:
            exception_message = (_("Replication is not supported on "
                                   "VMAX 2"))
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        sourceName = sourceVolume['name']
        sourceInstance = self.utils.find_volume_instance(
            conn, volumeDict, sourceName)
        LOG.debug('Starting replication setup '
                  'for volume: %s.', sourceVolume['name'])
        storageSystem = sourceInstance['SystemName']
        # get rdf details
        rdfGroupInstance, repServiceInstanceName = (
            self.get_rdf_details(conn, storageSystem))
        rdf_vol_size = sourceVolume['size']

        # give the target volume the same Volume Element Name as the
        # source volume
        targetName = self.utils.get_volume_element_name(
            sourceVolume['id'])

        if not targetInstance:
            # create a target volume on the target array
            # target must be passed in on remote replication
            targetInstance = self.get_target_instance(
                sourceVolume, self.rep_config, rdf_vol_size,
                targetName, extraSpecs)

        LOG.debug("Create volume replica: Remote Volume: %(targetName)s "
                  "Source Volume: %(sourceName)s "
                  "Method: CreateElementReplica "
                  "ReplicationService: %(service)s  ElementName: "
                  "%(elementname)s  SyncType: 6  SourceElement: "
                  "%(sourceelement)s.",
                  {'targetName': targetName,
                   'sourceName': sourceName,
                   'service': repServiceInstanceName,
                   'elementname': targetName,
                   'sourceelement': sourceInstance.path})

        # create the remote replica and establish the link
        rc, rdfDict = self.create_remote_replica(
            conn, repServiceInstanceName, rdfGroupInstance,
            sourceVolume, sourceInstance, targetInstance, extraSpecs,
            self.rep_config)

        LOG.info(_LI('Successfully setup replication for %s.'),
                 sourceVolume['name'])
        replication_status = REPLICATION_ENABLED
        replication_driver_data = rdfDict['keybindings']

        return replication_status, replication_driver_data

    # called on delete volume after remove_and_reset_members
    def cleanup_lun_replication(self, conn, volume, volumeName,
                                sourceInstance, extraSpecs):
        """Cleanup target volume on delete.

        Extra logic if target is last in group.
        :param conn: the connection to the ecom server
        :param volume: the volume object
        :param volumeName: the volume name
        :param sourceInstance: the source volume instance
        :param extraSpecs: extra specification
        """
        LOG.debug('Starting cleanup replication from volume: '
                  '%s.', volumeName)
        try:
            loc = volume['provider_location']
            rep_data = volume['replication_driver_data']

            if (isinstance(loc, six.string_types)
                    and isinstance(rep_data, six.string_types)):
                name = ast.literal_eval(loc)
                replication_keybindings = ast.literal_eval(rep_data)
                storageSystem = replication_keybindings['SystemName']
                rdfGroupInstance, repServiceInstanceName = (
                    self.get_rdf_details(conn, storageSystem))
                repExtraSpecs = self._get_replication_extraSpecs(
                    extraSpecs, self.rep_config)

                targetVolumeDict = {'classname': name['classname'],
                                    'keybindings': replication_keybindings}

                targetInstance = self.utils.find_volume_instance(
                    conn, targetVolumeDict, volumeName)
                # Ensure element name matches openstack id.
                volumeElementName = (self.utils.
                                     get_volume_element_name(volume['id']))
                if volumeElementName != targetInstance['ElementName']:
                    targetInstance = None

                if targetInstance is not None:
                    # clean-up target
                    targetControllerConfigService = (
                        self.utils.find_controller_configuration_service(
                            conn, storageSystem))
                    self.masking.remove_and_reset_members(
                        conn, targetControllerConfigService, targetInstance,
                        volumeName, repExtraSpecs, None, False)
                    self._cleanup_remote_target(
                        conn, repServiceInstanceName, sourceInstance,
                        targetInstance, extraSpecs, repExtraSpecs)
                    LOG.info(_LI('Successfully destroyed replication for '
                                 'volume: %(volume)s'),
                             {'volume': volumeName})
                else:
                    LOG.warning(_LW('Replication target not found for '
                                    'replication-enabled volume: %(volume)s'),
                                {'volume': volumeName})
        except Exception as e:
            LOG.error(_LE('Cannot get necessary information to cleanup '
                          'replication target for volume: %(volume)s. '
                          'The exception received was: %(e)s. Manual '
                          'clean-up may be required. Please contact '
                          'your administrator.'),
                      {'volume': volumeName, 'e': e})

    def _cleanup_remote_target(
            self, conn, repServiceInstanceName, sourceInstance,
            targetInstance, extraSpecs, repExtraSpecs):
        """Clean-up remote replication target after exception or on deletion.

        :param conn: connection to the ecom server
        :param repServiceInstanceName: the replication service
        :param sourceInstance: the source volume instance
        :param targetInstance: the target volume instance
        :param extraSpecs: extra specifications
        :param repExtraSpecs: replication extra specifications
        """
        storageSystem = sourceInstance['SystemName']
        targetStorageSystem = targetInstance['SystemName']
        syncInstanceName = self.utils.find_rdf_storage_sync_sv_sv(
            conn, sourceInstance, storageSystem,
            targetInstance, targetStorageSystem,
            extraSpecs, False)
        if syncInstanceName is not None:
            # Break the sync relationship.
            self.break_rdf_relationship(
                conn, repServiceInstanceName, syncInstanceName, extraSpecs)
        targetStorageConfigService = (
            self.utils.find_storage_configuration_service(
                conn, targetStorageSystem))
        deviceId = targetInstance['DeviceID']
        volumeName = targetInstance['Name']
        self._delete_from_pool_v3(
            targetStorageConfigService, targetInstance, volumeName,
            deviceId, repExtraSpecs)

    def _cleanup_replication_source(
            self, conn, volumeName, volumeDict, extraSpecs):
        """Cleanup a remote replication source volume on failure.

        If replication setup fails at any stage on a new volume create,
        we must clean-up the source instance as the cinder database won't
        be updated with the provider_location. This means the volume can not
        be properly deleted from  the array by cinder.

        :param conn: the connection to the ecom server
        :param volumeName: the name of the volume
        :param volumeDict: the source volume dictionary
        :param extraSpecs: the extra specifications
        """
        LOG.warning(_LW(
            "Replication failed. Cleaning up the source volume. "
            "Volume name: %(sourceName)s "),
            {'sourceName': volumeName})
        sourceInstance = self.utils.find_volume_instance(
            conn, volumeDict, volumeName)
        storageSystem = sourceInstance['SystemName']
        deviceId = sourceInstance['DeviceID']
        volumeName = sourceInstance['Name']
        storageConfigService = (
            self.utils.find_storage_configuration_service(
                conn, storageSystem))
        self._delete_from_pool_v3(
            storageConfigService, sourceInstance, volumeName,
            deviceId, extraSpecs)

    def break_rdf_relationship(self, conn, repServiceInstanceName,
                               syncInstanceName, extraSpecs):
        # Break the sync relationship.
        LOG.debug("Suspending the SRDF relationship...")
        self.provisionv3.break_replication_relationship(
            conn, repServiceInstanceName, syncInstanceName,
            SUSPEND_SRDF, extraSpecs, True)
        LOG.debug("Detaching the SRDF relationship...")
        self.provisionv3.break_replication_relationship(
            conn, repServiceInstanceName, syncInstanceName,
            DETACH_SRDF, extraSpecs, True)

    def get_rdf_details(self, conn, storageSystem):
        """Retrieves an SRDF group instance.

        :param conn: connection to the ecom server
        :param storageSystem: the storage system name
        :return:
        """
        if not self.rep_config:
            exception_message = (_("Replication is not configured on "
                                   "backend: %(backend)s.") %
                                 {'backend': self.configuration.safe_get(
                                     'volume_backend_name')})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        repServiceInstanceName = self.utils.find_replication_service(
            conn, storageSystem)
        RDFGroupName = self.rep_config['rdf_group_label']
        LOG.info(_LI("Replication group: %(RDFGroup)s."),
                 {'RDFGroup': RDFGroupName})
        rdfGroupInstance = self.provisionv3.get_rdf_group_instance(
            conn, repServiceInstanceName, RDFGroupName)
        LOG.info(_LI("Found RDF group instance: %(RDFGroup)s."),
                 {'RDFGroup': rdfGroupInstance})
        if rdfGroupInstance is None:
            exception_message = (_("Cannot find replication group: "
                                   "%(RDFGroup)s.") %
                                 {'RDFGroup': rdfGroupInstance})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        return rdfGroupInstance, repServiceInstanceName

    def failover_host(self, context, volumes, secondary_id=None):
        """Fails over the volume back and forth.

        Driver needs to update following info for failed-over volume:
        1. provider_location: update array details
        2. replication_status: new status for replication-enabled volume
        :param context: the context
        :param volumes: the list of volumes to be failed over
        :param secondary_id: the target backend
        :return: secondary_id, volume_update_list
        """
        volume_update_list = []
        if not self.conn:
            self.conn = self._get_ecom_connection()
        if secondary_id != 'default':
            if not self.failover:
                self.failover = True
                if self.rep_config:
                    secondary_id = self.rep_config['array']
            else:
                exception_message = (_(
                    "Backend %(backend)s is already failed over. "
                    "If you wish to failback, please append "
                    "'--backend_id default' to your command.")
                    % {'backend': self.configuration.safe_get(
                       'volume_backend_name')})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
        else:
            if self.failover:
                self.failover = False
                secondary_id = None
            else:
                exception_message = (_(
                    "Cannot failback backend %(backend)s- backend not "
                    "in failed over state. If you meant to failover, please "
                    "omit the '--backend_id default' from the command")
                    % {'backend': self.configuration.safe_get(
                       'volume_backend_name')})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        def failover_volume(vol, failover):
            loc = vol['provider_location']
            rep_data = vol['replication_driver_data']
            try:
                name = ast.literal_eval(loc)
                replication_keybindings = ast.literal_eval(rep_data)
                keybindings = name['keybindings']
                storageSystem = keybindings['SystemName']
                sourceInstance = self._find_lun(vol)
                volumeDict = {'classname': name['classname'],
                              'keybindings': replication_keybindings}

                targetInstance = self.utils.find_volume_instance(
                    self.conn, volumeDict, vol['name'])
                targetStorageSystem = (
                    replication_keybindings['SystemName'])
                repServiceInstanceName = (
                    self.utils.find_replication_service(
                        self.conn, storageSystem))

                if failover:
                    storageSynchronizationSv = (
                        self.utils.find_rdf_storage_sync_sv_sv(
                            self.conn, sourceInstance, storageSystem,
                            targetInstance, targetStorageSystem,
                            extraSpecs))
                    self.provisionv3.failover_volume(
                        self.conn, repServiceInstanceName,
                        storageSynchronizationSv,
                        extraSpecs)
                    new_status = REPLICATION_FAILOVER

                else:
                    storageSynchronizationSv = (
                        self.utils.find_rdf_storage_sync_sv_sv(
                            self.conn, targetInstance, targetStorageSystem,
                            sourceInstance, storageSystem,
                            extraSpecs, False))
                    self.provisionv3.failback_volume(
                        self.conn, repServiceInstanceName,
                        storageSynchronizationSv,
                        extraSpecs)
                    new_status = REPLICATION_ENABLED

                # Transfer ownership to secondary_backend_id and
                # update provider_location field
                provider_location, replication_driver_data = (
                    self.utils.failover_provider_location(
                        name, replication_keybindings))
                loc = six.text_type(provider_location)
                rep_data = six.text_type(replication_driver_data)

            except Exception as ex:
                msg = _LE(
                    'Failed to failover volume %(volume_id)s. '
                    'Error: %(error)s.')
                LOG.error(msg, {'volume_id': vol['id'],
                                'error': ex}, )
                new_status = FAILOVER_ERROR

            model_update = {'volume_id': vol['id'],
                            'updates':
                                {'replication_status': new_status,
                                 'replication_driver_data': rep_data,
                                 'provider_location': loc}}
            volume_update_list.append(model_update)

        for volume in volumes:
            extraSpecs = self._initial_setup(volume)
            if self.utils.is_replication_enabled(extraSpecs):
                failover_volume(volume, self.failover)
            else:
                if self.failover:
                    # Since the array has been failed-over,
                    # volumes without replication should be in error.
                    volume_update_list.append({
                        'volume_id': volume['id'],
                        'updates': {'status': 'error'}})
                else:
                    # This is a failback, so we will attempt
                    # to recover non-failed over volumes
                    recovery = self.recover_volumes_on_failback(volume)
                    volume_update_list.append(recovery)

        LOG.info(_LI("Failover host complete"))

        return secondary_id, volume_update_list

    def recover_volumes_on_failback(self, volume):
        """Recover volumes on failback.

        On failback, attempt to recover non RE(replication enabled)
        volumes from primary array.

        :param volume:
        :return: volume_update
        """

        # check if volume still exists on the primary
        volume_update = {'volume_id': volume['id']}
        volumeInstance = self._find_lun(volume)
        if not volumeInstance:
            volume_update['updates'] = {'status': 'error'}
        else:
            try:
                maskingview = self._is_volume_in_masking_view(volumeInstance)
            except Exception:
                maskingview = None
                LOG.debug("Unable to determine if volume is in masking view.")
            if not maskingview:
                volume_update['updates'] = {'status': 'available'}
            else:
                volume_update['updates'] = {'status': 'in-use'}
        return volume_update

    def _is_volume_in_masking_view(self, volumeInstance):
        """Helper function to check if a volume is in a masking view.

        :param volumeInstance: the volume instance
        :return: maskingview
        """
        maskingView = None
        volumeInstanceName = volumeInstance.path
        storageGroups = self.utils.get_storage_groups_from_volume(
            self.conn, volumeInstanceName)
        if storageGroups:
            for storageGroup in storageGroups:
                maskingView = self.utils.get_masking_view_from_storage_group(
                    self.conn, storageGroup)
                if maskingView:
                    break
        return maskingView

    def extend_volume_is_replicated(self, volume, volumeInstance,
                                    volumeName, newSize, extraSpecs):
        """Extend a replication-enabled volume.

        Cannot extend volumes in a synchronization pair.
        Must first break the relationship, extend them
        separately, then recreate the pair
        :param volume: the volume objcet
        :param volumeInstance: the volume instance
        :param volumeName: the volume name
        :param newSize: the new size the volume should be
        :param extraSpecs: extra specifications
        :return: rc, volumeDict
        """
        if self.extendReplicatedVolume is True:
            storageSystem = volumeInstance['SystemName']
            loc = volume['provider_location']
            rep_data = volume['replication_driver_data']
            try:
                name = ast.literal_eval(loc)
                replication_keybindings = ast.literal_eval(rep_data)
                targetStorageSystem = replication_keybindings['SystemName']
                targetVolumeDict = {'classname': name['classname'],
                                    'keybindings': replication_keybindings}
                targetVolumeInstance = self.utils.find_volume_instance(
                    self.conn, targetVolumeDict, volumeName)
                repServiceInstanceName = self.utils.find_replication_service(
                    self.conn, targetStorageSystem)
                storageSynchronizationSv = (
                    self.utils.find_rdf_storage_sync_sv_sv(
                        self.conn, volumeInstance, storageSystem,
                        targetVolumeInstance, targetStorageSystem,
                        extraSpecs))

                # volume must be removed from replication (storage) group
                # before the replication relationship can be ended (cannot
                # have a mix of replicated and non-replicated volumes as
                # the SRDF groups become unmanageable).
                controllerConfigService = (
                    self.utils.find_controller_configuration_service(
                        self.conn, storageSystem))
                self.masking.remove_and_reset_members(
                    self.conn, controllerConfigService, volumeInstance,
                    volumeName, extraSpecs, None, False)

                # repeat on target side
                targetControllerConfigService = (
                    self.utils.find_controller_configuration_service(
                        self.conn, targetStorageSystem))
                repExtraSpecs = self._get_replication_extraSpecs(
                    extraSpecs, self.rep_config)
                self.masking.remove_and_reset_members(
                    self.conn, targetControllerConfigService,
                    targetVolumeInstance, volumeName, repExtraSpecs,
                    None, False)

                LOG.info(_LI("Breaking replication relationship..."))
                self.break_rdf_relationship(
                    self.conn, repServiceInstanceName,
                    storageSynchronizationSv, extraSpecs)

                # extend the source volume

                LOG.info(_LI("Extending source volume..."))
                rc, volumeDict = self._extend_v3_volume(
                    volumeInstance, volumeName, newSize, extraSpecs)

                # extend the target volume
                LOG.info(_LI("Extending target volume..."))
                self._extend_v3_volume(targetVolumeInstance, volumeName,
                                       newSize, repExtraSpecs)

                # re-create replication relationship
                LOG.info(_LI("Recreating replication relationship..."))
                self.setup_volume_replication(
                    self.conn, volume, volumeDict,
                    extraSpecs, targetVolumeInstance)

            except Exception as e:
                exception_message = (_("Error extending volume. "
                                       "Error received was %(e)s") %
                                     {'e': e})
                LOG.exception(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            return rc, volumeDict

        else:
            exceptionMessage = (_(
                "Extending a replicated volume is not "
                "permitted on this backend. Please contact "
                "your administrator."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

    def create_remote_replica(self, conn, repServiceInstanceName,
                              rdfGroupInstance, sourceVolume, sourceInstance,
                              targetInstance, extraSpecs, rep_config):
        """Create a replication relationship with a target volume.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: the replication service
        :param rdfGroupInstance: the SRDF group instance
        :param sourceVolume: the source volume object
        :param sourceInstance: the source volume instance
        :param targetInstance: the target volume instance
        :param extraSpecs: extra specifications
        :param rep_config: the replication configuration
        :return: rc, rdfDict - the target volume dictionary
        """
        # remove source and target instances from their default storage groups
        volumeName = sourceVolume['name']
        storageSystemName = sourceInstance['SystemName']
        controllerConfigService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        repExtraSpecs = self._get_replication_extraSpecs(extraSpecs,
                                                         rep_config)
        try:
            self.masking.remove_and_reset_members(
                conn, controllerConfigService, sourceInstance,
                volumeName, extraSpecs, connector=None, reset=False)

            targetStorageSystemName = targetInstance['SystemName']
            targetControllerConfigService = (
                self.utils.find_controller_configuration_service(
                    conn, targetStorageSystemName))
            self.masking.remove_and_reset_members(
                conn, targetControllerConfigService, targetInstance,
                volumeName, repExtraSpecs, connector=None, reset=False)

            # establish replication relationship
            rc, rdfDict = self._create_remote_replica(
                conn, repServiceInstanceName, rdfGroupInstance, volumeName,
                sourceInstance, targetInstance, extraSpecs)

            # add source and target instances to their replication groups
            LOG.debug("Adding sourceInstance to default replication group.")
            self.add_volume_to_replication_group(conn, controllerConfigService,
                                                 sourceInstance, volumeName,
                                                 extraSpecs)
            LOG.debug("Adding targetInstance to default replication group.")
            self.add_volume_to_replication_group(
                conn, targetControllerConfigService, targetInstance,
                volumeName, repExtraSpecs)

        except Exception as e:
            LOG.warning(
                _LW("Remote replication failed. Cleaning up the target "
                    "volume and returning source volume to default storage "
                    "group. Volume name: %(cloneName)s "),
                {'cloneName': volumeName})

            self._cleanup_remote_target(
                conn, repServiceInstanceName, sourceInstance,
                targetInstance, extraSpecs, repExtraSpecs)
            # Re-throw the exception.
            exception_message = (_("Remote replication failed with exception:"
                                   " %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return rc, rdfDict

    def add_volume_to_replication_group(self, conn, controllerConfigService,
                                        volumeInstance, volumeName,
                                        extraSpecs):
        """Add a volume to the default replication group.

        SE_ReplicationGroups are actually VMAX storage groups under
        the covers, so we can use our normal storage group operations.
        :param conn: the connection to the ecom served
        :param controllerConfigService: the controller config service
        :param volumeInstance: the volume instance
        :param volumeName: the name of the volume
        :param extraSpecs: extra specifications
        :return: storageGroupInstanceName
        """
        storageGroupName = self.utils.get_v3_storage_group_name(
            extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD],
            False, True)
        storageSystemName = volumeInstance['SystemName']
        doDisableCompression = self.utils.is_compression_disabled(extraSpecs)
        try:
            storageGroupInstanceName = self._get_or_create_storage_group_v3(
                extraSpecs[POOL], extraSpecs[SLO], extraSpecs[WORKLOAD],
                doDisableCompression, storageSystemName, extraSpecs,
                is_re=True)
        except Exception as e:
            exception_message = (_("Failed to get or create replication"
                                   "group. Exception received: %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        self.masking.add_volume_to_storage_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstance, volumeName, storageGroupName, extraSpecs)

        return storageGroupInstanceName

    def _create_remote_replica(
            self, conn, repServiceInstanceName, rdfGroupInstance,
            volumeName, sourceInstance, targetInstance, extraSpecs):
        """Helper function to establish a replication relationship.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: replication service instance
        :param rdfGroupInstance: rdf group instance
        :param volumeName: volume name
        :param sourceInstance: the source volume instance
        :param targetInstance: the target volume instance
        :param extraSpecs: extra specifications
        :return: rc, rdfDict - the target volume dictionary
        """
        syncType = MIRROR_SYNC_TYPE
        rc, job = self.provisionv3.create_remote_element_replica(
            conn, repServiceInstanceName, volumeName, syncType,
            sourceInstance, targetInstance, rdfGroupInstance, extraSpecs)
        rdfDict = self.provisionv3.get_volume_dict_from_job(
            self.conn, job['Job'])

        return rc, rdfDict

    def get_target_instance(self, sourceVolume, rep_config,
                            rdf_vol_size, targetName, extraSpecs):
        """Create a replication target for a given source volume.

        :param sourceVolume: the source volume
        :param rep_config: the replication configuration
        :param rdf_vol_size: the size of the volume
        :param targetName: the Element Name for the new volume
        :param extraSpecs: the extra specifications
        :return: the target instance
        """
        repExtraSpecs = self._get_replication_extraSpecs(
            extraSpecs, rep_config)
        volumeSize = int(self.utils.convert_gb_to_bits(rdf_vol_size))
        rc, volumeDict, storageSystemName = self._create_v3_volume(
            sourceVolume, targetName, volumeSize, repExtraSpecs)
        targetInstance = self.utils.find_volume_instance(
            self.conn, volumeDict, targetName)
        return targetInstance

    def _get_replication_extraSpecs(self, extraSpecs, rep_config):
        """Get replication extra specifications.

        Called when target array operations are necessary -
        on create, extend, etc and when volume is failed over.
        :param extraSpecs: the extra specifications
        :param rep_config: the replication configuration
        :return: repExtraSpecs - dict
        """
        repExtraSpecs = extraSpecs.copy()
        repExtraSpecs[ARRAY] = rep_config['array']
        repExtraSpecs[POOL] = rep_config['pool']
        repExtraSpecs[PORTGROUPNAME] = rep_config['portgroup']

        # if disable compression is set, check if target array is all flash
        doDisableCompression = self.utils.is_compression_disabled(
            extraSpecs)
        if doDisableCompression:
            if not self.utils.is_all_flash(self.conn, repExtraSpecs[ARRAY]):
                repExtraSpecs.pop(self.utils.DISABLECOMPRESSION, None)

        # Check to see if SLO and Workload are configured on the target array.
        poolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(repExtraSpecs))
        storagePoolCapability = self.provisionv3.get_storage_pool_capability(
            self.conn, poolInstanceName)
        if extraSpecs[SLO]:
            if storagePoolCapability:
                try:
                    self.provisionv3.get_storage_pool_setting(
                        self.conn, storagePoolCapability, extraSpecs[SLO],
                        extraSpecs[WORKLOAD])
                except Exception:
                    LOG.warning(
                        _LW("The target array does not support the storage "
                            "pool setting for SLO %(slo)s or workload "
                            "%(workload)s. Not assigning any SLO or "
                            "workload."),
                        {'slo': extraSpecs[SLO],
                         'workload': extraSpecs[WORKLOAD]})
                    repExtraSpecs[SLO] = None
                    if extraSpecs[WORKLOAD]:
                        repExtraSpecs[WORKLOAD] = None

            else:
                LOG.warning(_LW("Cannot determine storage pool settings of "
                                "target array. Not assigning any SLO or "
                                "workload"))
                repExtraSpecs[SLO] = None
                if extraSpecs[WORKLOAD]:
                    repExtraSpecs[WORKLOAD] = None

        return repExtraSpecs

    def get_secondary_stats_info(self, rep_config, arrayInfo):
        """On failover, report on secondary array statistics.

        :param rep_config: the replication configuration
        :param arrayInfo: the array info
        :return: secondaryInfo - dict
        """
        secondaryInfo = arrayInfo.copy()
        secondaryInfo['SerialNumber'] = six.text_type(rep_config['array'])
        secondaryInfo['PoolName'] = rep_config['pool']
        pool_info_specs = {ARRAY: secondaryInfo['SerialNumber'],
                           POOL: rep_config['pool'],
                           ISV3: True}
        # Check to see if SLO and Workload are configured on the target array.
        poolInstanceName, storageSystemName = (
            self._get_pool_and_storage_system(pool_info_specs))
        storagePoolCapability = self.provisionv3.get_storage_pool_capability(
            self.conn, poolInstanceName)
        if arrayInfo['SLO']:
            if storagePoolCapability:
                try:
                    self.provisionv3.get_storage_pool_setting(
                        self.conn, storagePoolCapability, arrayInfo['SLO'],
                        arrayInfo['Workload'])
                except Exception:
                    LOG.info(
                        _LI("The target array does not support the storage "
                            "pool setting for SLO %(slo)s or workload "
                            "%(workload)s. SLO stats will not be reported."),
                        {'slo': arrayInfo['SLO'],
                         'workload': arrayInfo['Workload']})
                    secondaryInfo['SLO'] = None
                    if arrayInfo['Workload']:
                        secondaryInfo['Workload'] = None
                    if self.multiPoolSupportEnabled:
                        self.multiPoolSupportEnabled = False

            else:
                LOG.info(_LI("Cannot determine storage pool settings of "
                             "target array. SLO stats will not be reported."))
                secondaryInfo['SLO'] = None
                if arrayInfo['Workload']:
                    secondaryInfo['Workload'] = None
                if self.multiPoolSupportEnabled:
                    self.multiPoolSupportEnabled = False
        return secondaryInfo
