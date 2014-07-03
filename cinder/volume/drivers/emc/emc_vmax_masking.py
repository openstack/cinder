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
import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.emc import emc_vmax_fast
from cinder.volume.drivers.emc import emc_vmax_provision
from cinder.volume.drivers.emc import emc_vmax_utils

LOG = logging.getLogger(__name__)

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3
INITIATORGROUPTYPE = 2

ISCSI = 'iscsi'
FC = 'fc'

EMC_ROOT = 'root/emc'


class EMCVMAXMasking(object):
    """Masking class for SMI-S based EMC volume drivers.

    Masking code to dynamically create a masking view
    This masking class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl):
        self.protocol = prtcl
        self.utils = emc_vmax_utils.EMCVMAXUtils(prtcl)
        self.fast = emc_vmax_fast.EMCVMAXFast(prtcl)
        self.provision = emc_vmax_provision.EMCVMAXProvision(prtcl)

    def get_or_create_masking_view_and_map_lun(self, conn, maskingViewDict):
        """Get or Create a masking view.

        Given a masking view tuple either get or create a masking view and add
        the volume to the associated storage group

        :param conn: the connection to  ecom
        :para maskingViewDict: the masking view tuple
        :returns: dict rollbackDict
        """
        rollbackDict = {}

        controllerConfigService = maskingViewDict['controllerConfigService']
        sgGroupName = maskingViewDict['sgGroupName']
        volumeInstance = maskingViewDict['volumeInstance']
        igGroupName = maskingViewDict['igGroupName']
        connector = maskingViewDict['connector']
        storageSystemName = maskingViewDict['storageSystemName']
        maskingViewName = maskingViewDict['maskingViewName']
        volumeName = maskingViewDict['volumeName']
        pgGroupName = maskingViewDict['pgGroupName']

        fastPolicyName = maskingViewDict['fastPolicy']
        defaultStorageGroupInstanceName = None

        # we need a rollback scenario for FAST.
        # We must make sure that volume is returned to default storage
        # group if anything goes wrong
        if fastPolicyName is not None:
            defaultStorageGroupInstanceName = (
                self.fast.get_and_verify_default_storage_group(
                    conn, controllerConfigService, volumeInstance.path,
                    volumeName, fastPolicyName))
            if defaultStorageGroupInstanceName is None:
                exceptionMessage = (_(
                    "Cannot get the default storage group for FAST policy: "
                    "%(fastPolicyName)s. ")
                    % {'fastPolicyName': fastPolicyName})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

            retStorageGroupInstanceName = (
                self.remove_device_from_default_storage_group(
                    conn, controllerConfigService, volumeInstance.path,
                    volumeName, fastPolicyName))
            if retStorageGroupInstanceName is None:
                exceptionMessage = (_(
                    "Failed to remove volume %(volumeName)s from default SG: "
                    "%(volumeName)s. ")
                    % {'volumeName': volumeName})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        try:
            maskingViewInstanceName = self._find_masking_view(
                conn, maskingViewName, storageSystemName)
            if maskingViewInstanceName is None:
                storageGroupInstanceName = (
                    self._get_storage_group_instance_name(
                        conn, controllerConfigService, volumeInstance,
                        volumeName, sgGroupName, fastPolicyName,
                        storageSystemName, defaultStorageGroupInstanceName))
                if storageGroupInstanceName is None:
                    exceptionMessage = (_(
                        "Cannot get or create a storage group: %(sgGroupName)s"
                        " for volume %(volumeName)s ")
                        % {'sgGroupName': sgGroupName,
                           'volumeName': volumeName})
                    LOG.error(exceptionMessage)
                    raise

                portGroupInstanceName = self._get_port_group_instance_name(
                    conn, controllerConfigService, pgGroupName)
                if portGroupInstanceName is None:
                    exceptionMessage = (_(
                        "Cannot get port group: %(pgGroupName)s. ")
                        % {'pgGroupName': pgGroupName})
                    LOG.error(exceptionMessage)
                    raise

                initiatorGroupInstanceName = (
                    self._get_initiator_group_instance_name(
                        conn, controllerConfigService, igGroupName, connector,
                        storageSystemName))
                if initiatorGroupInstanceName is None:
                    exceptionMessage = (_(
                        "Cannot get or create initiator group: "
                        "%(igGroupName)s. ")
                        % {'igGroupName': igGroupName})
                    LOG.error(exceptionMessage)
                    raise

                maskingViewInstanceName = (
                    self._get_masking_view_instance_name(
                        conn, controllerConfigService, maskingViewName,
                        storageGroupInstanceName, portGroupInstanceName,
                        initiatorGroupInstanceName))
                if maskingViewInstanceName is None:
                    exceptionMessage = (_(
                        "Cannot create masking view: %(maskingViewName)s. ")
                        % {'maskingViewName': maskingViewName})
                    LOG.error(exceptionMessage)
                    raise

            else:
                # first verify that the initiator group matches the initiators
                if not self._verify_initiator_group_from_masking_view(
                        conn, controllerConfigService, maskingViewName,
                        connector, storageSystemName, igGroupName):
                    exceptionMessage = (_(
                        "Unable to verify initiator group: %(igGroupName)s"
                        "in masking view %(maskingViewName)s ")
                        % {'igGroupName': igGroupName,
                           'maskingViewName': maskingViewName})
                    LOG.error(exceptionMessage)
                    raise

                # get the storage from the masking view and add the
                # volume to it.
                storageGroupInstanceName = (
                    self._get_storage_group_from_masking_view(
                        conn, maskingViewName, storageSystemName))

                if storageGroupInstanceName is None:
                    exceptionMessage = (_(
                        "Cannot get storage group from masking view: "
                        "%(maskingViewName)s. ")
                        % {'maskingViewName': maskingViewName})
                    LOG.error(exceptionMessage)
                    raise

                if self._is_volume_in_storage_group(
                        conn, storageGroupInstanceName,
                        volumeInstance):
                    LOG.warn(_(
                        "Volume: %(volumeName)s is already part "
                        "of storage group %(sgGroupName)s ")
                        % {'volumeName': volumeName,
                           'sgGroupName': sgGroupName})
                else:
                    self.add_volume_to_storage_group(
                        conn, controllerConfigService,
                        storageGroupInstanceName, volumeInstance, volumeName,
                        sgGroupName, fastPolicyName, storageSystemName)

        except Exception as e:
            # rollback code if we cannot complete any of the steps above
            # successfully then we must roll back by adding the volume back to
            # the default storage group for that fast policy
            if (fastPolicyName is not None and
                    defaultStorageGroupInstanceName is not None):
                # if the exception happened before the volume was removed from
                # the default storage group no action
                self._check_if_rollback_action_for_masking_required(
                    conn, controllerConfigService, volumeInstance, volumeName,
                    fastPolicyName, defaultStorageGroupInstanceName)

            LOG.error(_("Exception: %s") % six.text_type(e))
            errorMessage = (_(
                "Failed to get or create masking view %(maskingViewName)s ")
                % {'maskingViewName': maskingViewName})
            LOG.error(errorMessage)
            exception.VolumeBackendAPIException(data=errorMessage)

        rollbackDict['controllerConfigService'] = controllerConfigService
        rollbackDict['defaultStorageGroupInstanceName'] = (
            defaultStorageGroupInstanceName)
        rollbackDict['volumeInstance'] = volumeInstance
        rollbackDict['volumeName'] = volumeName
        rollbackDict['fastPolicyName'] = fastPolicyName
        return rollbackDict

    def _is_volume_in_storage_group(
            self, conn, storageGroupInstanceName, volumeInstance):
        """Check if the volume is already part of the storage group.

        Check if the volume is already part of the storage group,
        if it is no need to re-add it.

        :param conn: the connection to  ecom
        :param storageGroupInstanceName: the storage group instance name
        :param volumeInstance: the volume instance
        :returns: boolean True/False
        """
        foundStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(
                conn, volumeInstance.path))

        storageGroupInstance = conn.GetInstance(
            storageGroupInstanceName, LocalOnly=False)

        LOG.debug(
            "The existing storage group instance element name is: "
            "%(existingElement)s. "
            % {'existingElement': storageGroupInstance['ElementName']})

        if foundStorageGroupInstanceName is not None:
            foundStorageGroupInstance = conn.GetInstance(
                foundStorageGroupInstanceName, LocalOnly=False)
            LOG.debug(
                "The found storage group instance element name is: "
                "%(foundElement)s. "
                % {'foundElement': foundStorageGroupInstance['ElementName']})
            if (foundStorageGroupInstance['ElementName'] == (
                    storageGroupInstance['ElementName'])):
                LOG.warn(_(
                    "The volume is already part of storage group: "
                    "%(storageGroupInstanceName)s. ")
                    % {'storageGroupInstanceName': storageGroupInstanceName})
                return True

        return False

    def _find_masking_view(self, conn, maskingViewName, storageSystemName):
        """Given the masking view name get the masking view instance.

        :param conn: connection to the ecom server
        :param maskingViewName: the masking view name
        :param storageSystemName: the storage system name(String)
        :returns: foundMaskingViewInstanceName masking view instance name
        """
        foundMaskingViewInstanceName = None
        maskingViewInstanceNames = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')

        for maskingViewInstanceName in maskingViewInstanceNames:
            if storageSystemName == maskingViewInstanceName['SystemName']:
                instance = conn.GetInstance(
                    maskingViewInstanceName, LocalOnly=False)
                if maskingViewName == instance['ElementName']:
                    foundMaskingViewInstanceName = maskingViewInstanceName
                    break

        if foundMaskingViewInstanceName is not None:
            infoMessage = (_(
                "Found existing masking view: %(maskingViewName)s ")
                % {'maskingViewName': maskingViewName})
            LOG.info(infoMessage)
        return foundMaskingViewInstanceName

    def _create_storage_group(
            self, conn, controllerConfigService, storageGroupName,
            volumeInstance, fastPolicyName, volumeName, storageSystemName,
            defaultStorageGroupInstanceName):
        """Create a new storage group that doesn't already exist.

        If fastPolicyName is not none we attempt to remove it from the
        default storage group of that policy and associate to the new storage
        group that will be part of the masking view.
        Will not handle any exception in this method it will be handled
        up the stack

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupName: the proposed group name (String)
        :param volumeInstance: useful information on the volume
        :param fastPolicyName: the fast policy name (String) can be None
        :param volumeName: the volume name (String)
        :param storageSystemName: the storage system name (String)
        :param defaultStorageGroupInstanceName: the default storage group
                                          instance name (Can be None)
        :returns: foundStorageGroupInstanceName the instance Name of the
                                                storage group
        """
        failedRet = None
        foundStorageGroupInstanceName = (
            self.provision.create_and_get_storage_group(
                conn, controllerConfigService, storageGroupName,
                volumeInstance.path))
        if foundStorageGroupInstanceName is None:
            LOG.error(_(
                "Cannot get storage Group from job : %(storageGroupName)s. ")
                % {'storageGroupName': storageGroupName})
            return failedRet
        else:
            LOG.info(_(
                "Created new storage group: %(storageGroupName)s ")
                % {'storageGroupName': storageGroupName})

        if (fastPolicyName is not None and
                defaultStorageGroupInstanceName is not None):
            assocTierPolicyInstanceName = (
                self.fast.add_storage_group_and_verify_tier_policy_assoc(
                    conn, controllerConfigService,
                    foundStorageGroupInstanceName,
                    storageGroupName, fastPolicyName))
            if assocTierPolicyInstanceName is None:
                LOG.error(_(
                    "Cannot add and verify tier policy association for storage"
                    " group : %(storageGroupName)s to FAST policy : "
                    "%(fastPolicyName)s. ")
                    % {'storageGroupName': storageGroupName,
                       'fastPolicyName': fastPolicyName})
                return failedRet

        return foundStorageGroupInstanceName

    def _find_port_group(self, conn, controllerConfigService, portGroupName):
        """Given the port Group name get the port group instance name.

        :param conn: connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param portGroupName: the name of the port group you are getting
        :returns: foundPortGroup storage group instance name
        """
        foundPortGroupInstanceName = None
        portMaskingGroupInstanceNames = conn.AssociatorNames(
            controllerConfigService, resultClass='CIM_TargetMaskingGroup')

        for portMaskingGroupInstanceName in portMaskingGroupInstanceNames:
            instance = conn.GetInstance(
                portMaskingGroupInstanceName, LocalOnly=False)
            if portGroupName == instance['ElementName']:
                foundPortGroupInstanceName = portMaskingGroupInstanceName
                break

        if foundPortGroupInstanceName is None:
            LOG.error(_(
                "Could not find port group : %(portGroupName)s. Check that the"
                " EMC configuration file has the correct port group name. ")
                % {'portGroupName': portGroupName})

        return foundPortGroupInstanceName

    def _create_or_get_initiator_group(
            self, conn, controllerConfigService, igGroupName,
            connector, storageSystemName):
        """Attempt to create a initiatorGroup.

        If one already exists with the same Initiator/wwns then get it

        Check to see if an initiatorGroup already exists, that matches the
        connector information
        NOTE:  An initiator/wwn can only belong to one initiatorGroup.
        If we were to attempt to create one with an initiator/wwn that
        is already belong to another initiatorGroup, it would fail

        :param conn: connection to the ecom server
        :param controllerConfigService: the controller config Servicer
        :param igGroupName: the proposed name of the initiator group
        :param connector: the connector information to the host
        :param storageSystemName: the storage system name (String)
        :returns: foundInitiatorGroupInstanceName
        """
        failedRet = None
        initiatorNames = self._find_initiator_names(conn, connector)
        LOG.debug("The initiator name(s) are: %(initiatorNames)s "
                  % {'initiatorNames': initiatorNames})

        foundInitiatorGroupInstanceName = self._find_initiator_masking_group(
            conn, controllerConfigService, initiatorNames)

        # If you cannot find an initiatorGroup that matches the connector
        # info create a new initiatorGroup
        if foundInitiatorGroupInstanceName is None:
            # check that our connector information matches the
            # hardwareId(s) on the symm
            storageHardwareIDInstanceNames = (
                self._get_storage_hardware_id_instance_names(
                    conn, initiatorNames, storageSystemName))
            if not storageHardwareIDInstanceNames:
                LOG.error(_(
                    "Initiator Name(s) %(initiatorNames)s are not on array "
                    "%(storageSystemName)s ")
                    % {'initiatorNames': initiatorNames,
                       'storageSystemName': storageSystemName})
                return failedRet

            foundInitiatorGroupInstanceName = self._create_initiator_Group(
                conn, controllerConfigService, igGroupName,
                storageHardwareIDInstanceNames)

            LOG.info("Created new initiator group name: %(igGroupName)s "
                     % {'igGroupName': igGroupName})
        else:
            LOG.info("Using existing initiator group name: %(igGroupName)s "
                     % {'igGroupName': igGroupName})

        return foundInitiatorGroupInstanceName

    def _find_initiator_names(self, conn, connector):
        """check the connector object for initiators(ISCSI) or wwpns(FC).

        :param conn: the connection to the ecom
        :param connector: the connector object
        :returns list foundinitiatornames list of string initiator names
        """
        foundinitiatornames = []
        name = 'initiator name'
        if (self.protocol.lower() == ISCSI and connector['initiator']):
            foundinitiatornames.append(connector['initiator'])
        elif (self.protocol.lower() == FC and connector['wwpns']):
            for wwn in connector['wwpns']:
                foundinitiatornames.append(wwn)
            name = 'world wide port names'

        if (foundinitiatornames is None or len(foundinitiatornames) == 0):
            msg = (_('Error finding %s.') % name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Found %(name)s: %(initiator)s."
                  % {'name': name,
                     'initiator': foundinitiatornames})

        return foundinitiatornames

    def _find_initiator_masking_group(
            self, conn, controllerConfigService, initiatorNames):
        """Check to see if an initiatorGroup already exists.

        NOTE:  An initiator/wwn can only belong to one initiatorGroup.
        If we were to attempt to create one with an initiator/wwn that is
        already belong to another initiatorGroup, it would fail

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param initiatorName: the list of initiator names
        :returns: foundInitiatorMaskingGroup
        """
        foundInitiatorMaskingGroupName = None

        initiatorMaskingGroupNames = (
            conn.AssociatorNames(controllerConfigService,
                                 ResultClass='CIM_InitiatorMaskingGroup'))

        for initiatorMaskingGroupName in initiatorMaskingGroupNames:
            initiatorMaskingGroup = conn.GetInstance(
                initiatorMaskingGroupName, LocalOnly=False)
            associators = (
                conn.Associators(initiatorMaskingGroup.path,
                                 ResultClass='EMC_StorageHardwareID'))
            for assoc in associators:
                # if EMC_StorageHardwareID matches the initiator,
                # we found the existing EMC_LunMaskingSCSIProtocolController
                # (Storage Group for VNX)
                # we can use for masking a new LUN
                hardwareid = assoc['StorageID']
                for initiator in initiatorNames:
                    if six.text_type(hardwareid).lower() == \
                            six.text_type(initiator).lower():
                        foundInitiatorMaskingGroupName = (
                            initiatorMaskingGroupName)
                        break

                if foundInitiatorMaskingGroupName is not None:
                    break

            if foundInitiatorMaskingGroupName is not None:
                break
        return foundInitiatorMaskingGroupName

    def _get_storage_hardware_id_instance_names(
            self, conn, initiatorNames, storageSystemName):
        """Given a list of initiator names find CIM_StorageHardwareID instance.

        :param conn: the connection to the ecom server
        :param initiatorName: the list of initiator names
        :param storageSystemName: the storage system name
        :returns: foundHardwardIDsInstanceNames
        """
        foundHardwardIDsInstanceNames = []

        hardwareIdManagementService = (
            self.utils.find_storage_hardwareid_service(
                conn, storageSystemName))

        hardwareIdInstanceNames = (
            self.utils.get_hardware_id_instance_names_from_array(
                conn, hardwareIdManagementService))

        for hardwareIdInstanceName in hardwareIdInstanceNames:
            hardwareIdInstance = conn.GetInstance(hardwareIdInstanceName)
            storageId = hardwareIdInstance['StorageID']
            for initiatorName in initiatorNames:
                LOG.debug("The storage Id is : %(storageId)s "
                          % {'storageId': storageId.lower()})
                LOG.debug("The initiatorName is : %(initiatorName)s "
                          % {'initiatorName': initiatorName.lower()})
                if storageId.lower() == initiatorName.lower():
                    foundHardwardIDsInstanceNames.append(
                        hardwareIdInstanceName)
                    break

        LOG.debug(
            "The found hardware IDs are : %(foundHardwardIDsInstanceNames)s "
            % {'foundHardwardIDsInstanceNames': foundHardwardIDsInstanceNames})

        return foundHardwardIDsInstanceNames

    def _get_initiator_group_from_job(self, conn, job):
        """After creating an new intiator group find it and return it

        :param conn: the connection to the ecom server
        :param job: the create initiator group job
        :returns: dict initiatorDict
        """
        associators = conn.Associators(
            job['Job'],
            ResultClass='CIM_InitiatorMaskingGroup')
        volpath = associators[0].path
        initiatorDict = {}
        initiatorDict['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        initiatorDict['keybindings'] = keys
        return initiatorDict

    def _create_masking_view(
            self, conn, configService, maskingViewName, deviceMaskingGroup,
            targetMaskingGroup, initiatorMaskingGroup):
        """After creating an new intiator group find it and return it.

        :param conn: the connection to the ecom server
        :param configService: the create initiator group job
        :param maskingViewName: the masking view name string
        :param deviceMaskingGroup: device(storage) masking group (instanceName)
        :param targetMaskingGroup: target(port) masking group (instanceName)
        :param initiatorMaskingGroup: initiator masking group (instanceName)
        :returns: int rc return code
        :returns: dict job
        """
        rc, job = conn.InvokeMethod(
            'CreateMaskingView', configService, ElementName=maskingViewName,
            InitiatorMaskingGroup=initiatorMaskingGroup,
            DeviceMaskingGroup=deviceMaskingGroup,
            TargetMaskingGroup=targetMaskingGroup)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Masking View: %(groupName)s. "
                    "Return code: %(rc)lu. Error: %(error)s")
                    % {'groupName': maskingViewName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.info(_("Created new masking view : %(maskingViewName)s ")
                 % {'maskingViewName': maskingViewName})
        return rc, job

    def find_new_masking_view(self, conn, jobDict):
        """Find the newly created volume

        :param conn: the connection to the ecom server
        :param jobDict: the job tuple
        :returns: instance maskingViewInstance
        """
        associators = conn.Associators(
            jobDict['Job'],
            ResultClass='Symm_LunMaskingView')
        mvpath = associators[0].path
        maskingViewInstance = {}
        maskingViewInstance['classname'] = mvpath.classname
        keys = {}
        keys['CreationClassName'] = mvpath['CreationClassName']
        keys['SystemName'] = mvpath['SystemName']
        keys['DeviceID'] = mvpath['DeviceID']
        keys['SystemCreationClassName'] = mvpath['SystemCreationClassName']
        maskingViewInstance['keybindings'] = keys
        return maskingViewInstance

    def _get_storage_group_from_masking_view(
            self, conn, maskingViewName, storageSystemName):
        """Gets the Device Masking Group from masking view.

        :param conn: the connection to the ecom server
        :param maskingViewName: the masking view name (String)
        :param storageSystemName: storage system name (String)
        :returns: instance name foundStorageGroupInstanceName
        """
        foundStorageGroupInstanceName = None
        maskingviews = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for view in maskingviews:
            if storageSystemName == view['SystemName']:
                instance = conn.GetInstance(view, LocalOnly=False)
                if maskingViewName == instance['ElementName']:
                    foundView = view
                    break

        groups = conn.AssociatorNames(
            foundView,
            ResultClass='CIM_DeviceMaskingGroup')
        if groups[0] > 0:
            foundStorageGroupInstanceName = groups[0]

        LOG.debug("Masking view: %(view)s DeviceMaskingGroup: %(masking)s."
                  % {'view': maskingViewName,
                     'masking': foundStorageGroupInstanceName})

        return foundStorageGroupInstanceName

    def _get_storage_group_instance_name(
            self, conn, controllerConfigService, volumeInstance, volumeName,
            sgGroupName, fastPolicyName, storageSystemName,
            defaultStorageGroupInstanceName):
        """Gets the storage group instance name.

        If fastPolicy name is None
        then NON FAST is assumed.  If it is a valid fastPolicy name
        then associate the new storage group with the fast policy.
        If we are using an existing storage group then we must check that
        it is associated with the correct fast policy

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param volumeInstance: the volume instance
        :param volumeName: the volume name (String)
        :param sgGroupName: the storage group name (String)
        :param fastPolicyName: the fast policy name (String): can be None
        :param storageSystemName: the storage system name (String)
        :param defaultStorageGroupInstanceName: default storage group instance
                                                name (can be None for Non FAST)
        :returns: instance name storageGroupInstanceName
        """
        storageGroupInstanceName = self.utils.find_storage_masking_group(
            conn, controllerConfigService, sgGroupName)

        if storageGroupInstanceName is None:
            storageGroupInstanceName = self._create_storage_group(
                conn, controllerConfigService, sgGroupName, volumeInstance,
                fastPolicyName, volumeName, storageSystemName,
                defaultStorageGroupInstanceName)
            if storageGroupInstanceName is None:
                errorMessage = (_(
                    "Cannot create or find an storage group with name "
                    "%(sgGroupName)s")
                    % {'sgGroupName': sgGroupName})
                LOG.error(errorMessage)
                raise exception.VolumeBackendAPIException(data=errorMessage)
        else:
            if self._is_volume_in_storage_group(
                    conn, storageGroupInstanceName, volumeInstance):
                LOG.warn(_("Volume: %(volumeName)s is already "
                           "part of storage group %(sgGroupName)s ")
                         % {'volumeName': volumeName,
                            'sgGroupName': sgGroupName})
            else:
                self.add_volume_to_storage_group(
                    conn, controllerConfigService, storageGroupInstanceName,
                    volumeInstance, volumeName, sgGroupName, fastPolicyName,
                    storageSystemName)

        return storageGroupInstanceName

    def _get_port_group_instance_name(
            self, conn, controllerConfigService, pgGroupName):
        """Gets the port group instance name.

        The portGroup name has been defined in the EMC Config file if it
        does not exist the operation should fail

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param pgGroupName: the port group name
        :returns: instance name foundPortGroupInstanceName
        """
        foundPortGroupInstanceName = self._find_port_group(
            conn, controllerConfigService, pgGroupName)
        if foundPortGroupInstanceName is None:
            errorMessage = (_(
                "Cannot find a portGroup with name %(pgGroupName)s. "
                "The port group for a masking view must be pre-defined")
                % {'pgGroupName': pgGroupName})
            LOG.error(errorMessage)
            return foundPortGroupInstanceName

        LOG.info(_(
            "Port group instance name is %(foundPortGroupInstanceName)s")
            % {'foundPortGroupInstanceName': foundPortGroupInstanceName})

        return foundPortGroupInstanceName

    def _get_initiator_group_instance_name(
            self, conn, controllerConfigService, igGroupName, connector,
            storageSystemName):
        """Gets the initiator group instance name.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param igGroupName: the port group name
        :param connector: the connector object
        :param storageSystemName = the storage system name
        :returns: instance name foundInitiatorGroupInstanceName
        """
        foundInitiatorGroupInstanceName = (self._create_or_get_initiator_group(
            conn, controllerConfigService, igGroupName, connector,
            storageSystemName))
        if foundInitiatorGroupInstanceName is None:
            errorMessage = (_(
                "Cannot create or find an initiator group with "
                "name %(igGroupName)s")
                % {'igGroupName': igGroupName})
            LOG.error(errorMessage)

        return foundInitiatorGroupInstanceName

    def _get_masking_view_instance_name(
            self, conn, controllerConfigService, maskingViewName,
            storageGroupInstanceName, portGroupInstanceName,
            initiatorGroupInstanceName):
        """Gets the masking view instance name

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param maskingViewName: the masking view name (String)
        :param storageGroupInstanceName: the storage group instance name
        :param portGroupInstanceName: the port group instance name
        :param initiatorGroupInstanceName: the initiator group instance name
        :returns: instance name foundMaskingViewInstanceName
        """
        rc, job = self._create_masking_view(
            conn, controllerConfigService, maskingViewName,
            storageGroupInstanceName, portGroupInstanceName,
            initiatorGroupInstanceName)
        foundMaskingViewInstanceName = self.find_new_masking_view(conn, job)
        if foundMaskingViewInstanceName is None:
            errorMessage = (_(
                "Cannot find the new masking view just created with name "
                "%(maskingViewName)s")
                % {'maskingViewName': maskingViewName})
            LOG.error(errorMessage)

        return foundMaskingViewInstanceName

    def _check_if_rollback_action_for_masking_required(
            self, conn, controllerConfigService, volumeInstance,
            volumeName, fastPolicyName, defaultStorageGroupInstanceName):
        """This is a rollback action for FAST.

        We need to be able to return the volume to the default storage group
        if anything has gone wrong. The volume can also potentially belong to
        a storage group that is not the default depending on where
        the exception occurred.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller config service
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param fastPolicyName: the fast policy name (String)
        :param defaultStorageGroupInstanceName: the default storage group
                                          instance name
        """
        try:
            foundStorageGroupInstanceName = (
                self.utils.get_storage_group_from_volume(
                    conn, volumeInstance.path))
            # volume is not associated with any storage group so add it back
            # to the default
            if len(foundStorageGroupInstanceName) == 0:
                infoMessage = (_(
                    "Performing rollback on Volume: %(volumeName)s "
                    "To return it to the default storage group for FAST policy"
                    " %(fastPolicyName)s. ")
                    % {'volumeName': volumeName,
                       'fastPolicyName': fastPolicyName})
                LOG.warn("No storage group found. " + infoMessage)
                assocDefaultStorageGroupName = (
                    self.fast
                    .add_volume_to_default_storage_group_for_fast_policy(
                        conn, controllerConfigService, volumeInstance,
                        volumeName, fastPolicyName))
                if assocDefaultStorageGroupName is None:
                    errorMsg = (_(
                        "Failed to Roll back to re-add volume %(volumeName)s "
                        "to default storage group for fast policy "
                        "%(fastPolicyName)s: Please contact your sys admin to "
                        "get the volume re-added manually ")
                        % {'volumeName': volumeName,
                           'fastPolicyName': fastPolicyName})
                    LOG.error(errorMsg)
            if len(foundStorageGroupInstanceName) > 0:
                errorMsg = (_(
                    "The storage group found is "
                    "%(foundStorageGroupInstanceName)s: ")
                    % {'foundStorageGroupInstanceName':
                        foundStorageGroupInstanceName})
                LOG.info(errorMsg)

                # check the name see is it the default storage group or another
                if (foundStorageGroupInstanceName !=
                        defaultStorageGroupInstanceName):
                    # remove it from its current masking view and return it
                    # to its default masking view if fast is enabled
                    self.remove_and_reset_members(
                        conn, controllerConfigService, volumeInstance,
                        fastPolicyName, volumeName)
        except Exception as e:
            LOG.error(_("Exception: %s") % six.text_type(e))
            errorMessage = (_(
                "Rollback for Volume: %(volumeName)s has failed. "
                "Please contact your system administrator to manually return "
                "your volume to the default storage group for fast policy "
                "%(fastPolicyName)s failed ")
                % {'volumeName': volumeName,
                   'fastPolicyName': fastPolicyName})
            LOG.error(errorMessage)
            raise exception.VolumeBackendAPIException(data=errorMessage)

    def _find_new_initiator_group(self, conn, maskingGroupDict):
        """After creating an new initiator group find it and return it.

        :param conn: connection the ecom server
        :param maskingGroupDict: the maskingGroupDict dict
        :param storageGroupName: storage group name (String)
        :returns: instance name foundInitiatorGroupInstanceName
        """
        foundInitiatorGroupInstanceName = None

        if 'MaskingGroup' in maskingGroupDict:
            foundInitiatorGroupInstanceName = maskingGroupDict['MaskingGroup']

        return foundInitiatorGroupInstanceName

    def _get_initiator_group_from_masking_view(
            self, conn, maskingViewName, storageSystemName):
        """Given the masking view name get the inititator group from it.

        :param conn: connection the the ecom server
        :param maskingViewName: the name of the masking view
        :param storageSystemName: the storage system name
        :returns: instance name foundInitiatorMaskingGroupInstanceName
        """
        foundInitiatorMaskingGroupInstanceName = None

        maskingviews = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for view in maskingviews:
            if storageSystemName == view['SystemName']:
                instance = conn.GetInstance(view, LocalOnly=False)
                if maskingViewName == instance['ElementName']:
                    foundView = view
                    break

        groups = conn.AssociatorNames(
            foundView,
            ResultClass='CIM_InitiatorMaskingGroup')
        if len(groups):
            foundInitiatorMaskingGroupInstanceName = groups[0]

        LOG.debug(
            "Masking view: %(view)s InitiatorMaskingGroup: %(masking)s."
            % {'view': maskingViewName,
               'masking': foundInitiatorMaskingGroupInstanceName})

        return foundInitiatorMaskingGroupInstanceName

    def _verify_initiator_group_from_masking_view(
            self, conn, controllerConfigService, maskingViewName, connector,
            storageSystemName, igGroupName):
        """Check that the initiator group contains the correct initiators.

        If using an existing masking view check that the initiator group
        contains the correct initiators.  If it does not contain the correct
        initiators then we delete the initiator group from the masking view,
        re-create it with the correct initiators and add it to the masking view
        NOTE:  EMC does not support ModifyMaskingView so we must first
               delete the masking view and recreate it.

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param maskingViewName: maskingview name (String)
        :param connector: the connector dict
        :param storageSystemName: the storage System Name (string)
        :param igGroupName: the initiator group name (String)
        """
        initiatorNames = self._find_initiator_names(conn, connector)
        foundInitiatorGroupFromConnector = self._find_initiator_masking_group(
            conn, controllerConfigService, initiatorNames)

        foundInitiatorGroupFromMaskingView = (
            self._get_initiator_group_from_masking_view(
                conn, maskingViewName, storageSystemName))

        if (foundInitiatorGroupFromConnector !=
                foundInitiatorGroupFromMaskingView):
            if foundInitiatorGroupFromMaskingView is not None:
                maskingViewInstanceName = self._find_masking_view(
                    conn, maskingViewName, storageSystemName)
                if foundInitiatorGroupFromConnector is None:
                    storageHardwareIDInstanceNames = (
                        self._get_storage_hardware_id_instance_names(
                            conn, initiatorNames, storageSystemName))
                    if not storageHardwareIDInstanceNames:
                        LOG.error(_(
                            "Initiator Name(s) %(initiatorNames)s are not on "
                            "array %(storageSystemName)s ")
                            % {'initiatorNames': initiatorNames,
                               'storageSystemName': storageSystemName})
                        return False

                    foundInitiatorGroupFromConnector = (
                        self._create_initiator_Group(
                            conn, controllerConfigService, igGroupName,
                            storageHardwareIDInstanceNames))
                storageGroupInstanceName = (
                    self._get_storage_group_from_masking_view(
                        conn, maskingViewName, storageSystemName))
                portGroupInstanceName = self._get_port_group_from_masking_view(
                    conn, maskingViewName, storageSystemName)
                if (foundInitiatorGroupFromConnector is not None and
                        storageGroupInstanceName is not None and
                        portGroupInstanceName is not None):
                    self._delete_masking_view(
                        conn, controllerConfigService, maskingViewName,
                        maskingViewInstanceName)
                    newMaskingViewInstanceName = (
                        self._get_masking_view_instance_name(
                            conn, controllerConfigService, maskingViewName,
                            storageGroupInstanceName, portGroupInstanceName,
                            foundInitiatorGroupFromConnector))
                    if newMaskingViewInstanceName is not None:
                        LOG.debug(
                            "The old masking view has been replaced: "
                            "%(maskingViewName)s.  "
                            % {'maskingViewName': maskingViewName})
                else:
                    LOG.error(_(
                        "One of the components of the original masking view "
                        "%(maskingViewName)s cannot be retrieved so "
                        "please contact your system administrator to check "
                        "that the correct initiator(s) are part of masking ")
                        % {'maskingViewName': maskingViewName})
                    return False
        return True

    def _create_initiator_Group(
            self, conn, controllerConfigService, igGroupName,
            hardwareIdinstanceNames):
        """Create a new initiator group

        Given a list of hardwareId Instance name create a new
        initiator group

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param igGroupName: the initiator group name (String)
        :param hardwareIdinstanceNames: one or more hardware id instance names
        """
        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=igGroupName,
            Type=self.utils.get_num(INITIATORGROUPTYPE, '16'),
            Members=[hardwareIdinstanceNames[0]])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'groupName': igGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        foundInitiatorGroupInstanceName = self._find_new_initiator_group(
            conn, job)

        numHardwareIDInstanceNames = len(hardwareIdinstanceNames)
        if numHardwareIDInstanceNames > 1:
            for j in range(1, numHardwareIDInstanceNames):
                rc, job = conn.InvokeMethod(
                    'AddMembers', controllerConfigService,
                    MaskingGroup=foundInitiatorGroupInstanceName,
                    Members=[hardwareIdinstanceNames[j]])

                if rc != 0L:
                    rc, errordesc = self.utils.wait_for_job_complete(conn, job)
                    if rc != 0L:
                        exceptionMessage = (_(
                            "Error adding initiator to group : %(groupName)s. "
                            "Return code: %(rc)lu.  Error: %(error)s")
                            % {'groupName': igGroupName,
                               'rc': rc,
                               'error': errordesc})
                        LOG.error(exceptionMessage)
                        raise exception.VolumeBackendAPIException(
                            data=exceptionMessage)
                j = j + 1

        return foundInitiatorGroupInstanceName

    def _get_port_group_from_masking_view(
            self, conn, maskingViewName, storageSystemName):
        """Given the masking view name get the port group from it

        :param conn: connection the the ecom server
        :param maskingViewName: the name of the masking view
        :param storageSystemName: the storage system name
        :returns: instance name foundPortMaskingGroupInstanceName
        """
        foundPortMaskingGroupInstanceName = None

        maskingviews = conn.EnumerateInstanceNames(
            'EMC_LunMaskingSCSIProtocolController')
        for view in maskingviews:
            if storageSystemName == view['SystemName']:
                instance = conn.GetInstance(view, LocalOnly=False)
                if maskingViewName == instance['ElementName']:
                    foundView = view
                    break

        groups = conn.AssociatorNames(
            foundView,
            ResultClass='CIM_TargetMaskingGroup')
        if len(groups) > 0:
            foundPortMaskingGroupInstanceName = groups[0]

        LOG.debug(
            "Masking view: %(view)s InitiatorMaskingGroup: %(masking)s."
            % {'view': maskingViewName,
               'masking': foundPortMaskingGroupInstanceName})

        return foundPortMaskingGroupInstanceName

    def _delete_masking_view(
            self, conn, controllerConfigService, maskingViewName,
            maskingViewInstanceName):
        """Delete a masking view

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param maskingViewName: maskingview name (String)
        :param maskingViewInstanceName: the masking view instance name
        """
        rc, job = conn.InvokeMethod('DeleteMaskingView',
                                    controllerConfigService,
                                    ProtocolController=maskingViewInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Modifying masking view : %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'groupName': maskingViewName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

    def get_masking_view_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Get the associated maskingview instance name

        Given storage group instance name, get the associated masking
        view instance name

        :param conn: connection the ecom server
        :param storageGroupInstanceName: the storage group instance name
        :returns: instance name foundMaskingViewInstanceName
        """
        foundMaskingViewInstanceName = None
        maskingViews = conn.AssociatorNames(
            storageGroupInstanceName,
            ResultClass='Symm_LunMaskingView')
        if len(maskingViews) > 0:
            foundMaskingViewInstanceName = maskingViews[0]

        return foundMaskingViewInstanceName

    def add_volume_to_storage_group(
            self, conn, controllerConfigService, storageGroupInstanceName,
            volumeInstance, volumeName, sgGroupName, fastPolicyName,
            storageSystemName=None):
        """Add a volume to an existing storage group

        :param conn: connection to ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroup: storage group instance
        :param volumeInstance: the volume instance
        :param volumeName: the name of the volume (String)
        :param sgGroupName: the name of the storage group (String)
        :param fastPolicyName: the fast policy name (String) can be None
        :param storageSystemName: the storage system name (Optional Parameter),
                            if None plain operation assumed
        :returns: int rc the return code of the job
        :returns: dict the job dict
        """
        self.provision.add_members_to_masking_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstance.path, volumeName)

        infoMessage = (_(
            "Added volume: %(volumeName)s to existing storage group "
            "%(sgGroupName)s. ")
            % {'volumeName': volumeName,
               'sgGroupName': sgGroupName})
        LOG.info(infoMessage)

    def remove_device_from_default_storage_group(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, fastPolicyName):
        """Remove the volume from the default storage group.

        Remove the volume from the default storage group for the FAST
        policy and return the default storage group instance name

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller config service
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param fastPolicyName: the fast policy name (String)
        :returns: instance name defaultStorageGroupInstanceName
        """
        failedRet = None
        defaultStorageGroupInstanceName = (
            self.fast.get_and_verify_default_storage_group(
                conn, controllerConfigService, volumeInstanceName,
                volumeName, fastPolicyName))

        if defaultStorageGroupInstanceName is None:
            errorMessage = (_(
                "Volume %(volumeName)s was not first part of the default "
                "storage group for the FAST Policy")
                % {'volumeName': volumeName})
            LOG.warn(errorMessage)
            return failedRet

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)

        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "for fast before removing volume %(volumeName)s"
            % {'length': len(assocVolumeInstanceNames),
               'volumeName': volumeName})

        self.provision.remove_device_from_storage_group(
            conn, controllerConfigService, defaultStorageGroupInstanceName,
            volumeInstanceName, volumeName)

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "for fast after removing volume %(volumeName)s"
            % {'length': len(assocVolumeInstanceNames),
               'volumeName': volumeName})

        # required for unit tests
        emptyStorageGroupInstanceName = (
            self._wrap_get_storage_group_from_volume(conn, volumeInstanceName))

        if emptyStorageGroupInstanceName is not None:
            errorMessage = (_(
                "Failed to remove %(volumeName)s from the default storage "
                "group for the FAST Policy")
                % {'volumeName': volumeName})
            LOG.error(errorMessage)
            return failedRet

        return defaultStorageGroupInstanceName

    def _wrap_get_storage_group_from_volume(self, conn, volumeInstanceName):

        """Wrapper for get_storage_group_from_volume.

        Needed for override in tests

        :param conn: the connection to the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: emptyStorageGroupInstanceName
        """
        return self.utils.get_storage_group_from_volume(
            conn, volumeInstanceName)

    def get_devices_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Get the associated volume Instance names

        Given the storage group instance name get the associated volume
        Instance names

        :param conn: connection the the ecom server
        :param storageGroupInstanceName: the storage group instance name
        :returns: list volumeInstanceNames list of volume instance names
        """
        volumeInstanceNames = conn.AssociatorNames(
            storageGroupInstanceName,
            ResultClass='EMC_StorageVolume')

        return volumeInstanceNames

    def get_associated_masking_group_from_device(
            self, conn, volumeInstanceName):
        maskingGroupInstanceNames = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='CIM_DeviceMaskingGroup',
            AssocClass='CIM_OrderedMemberOfCollection')
        if len(maskingGroupInstanceNames) > 0:
            return maskingGroupInstanceNames[0]
        else:
            return None

    def remove_and_reset_members(
            self, conn, controllerConfigService, volumeInstance,
            fastPolicyName, volumeName):
        """Part of unmap device or rollback.

        Removes volume from the Device Masking Group that belongs to a
        Masking View. Check if fast policy is in the extra specs, if it isn't
        we do not need to do any thing for FAST. Assume that
        isTieringPolicySupported is False unless the FAST policy is in
        the extra specs and tiering is enabled on the array

        :param conn: connection the the ecom server
        :param controllerConfigService: the controller configuration service
        :param volumeInstance: the volume Instance
        :param fastPolicyName: the fast policy name (if it exists)
        :param volumeName: the volume name
        :returns: list volumeInstanceNames list of volume instance names
        """
        rc = -1
        maskingGroupInstanceName = (
            self.get_associated_masking_group_from_device(
                conn, volumeInstance.path))

        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, maskingGroupInstanceName)
        storageSystemInstanceName = self.utils.find_storage_system(
            conn, controllerConfigService)

        isTieringPolicySupported = False
        if fastPolicyName is not None:
            tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
                conn, storageSystemInstanceName)

            isTieringPolicySupported = self.fast.is_tiering_policy_enabled(
                conn, tierPolicyServiceInstanceName)
            LOG.debug(
                "FAST policy enabled on %(storageSystem)s: %(isSupported)s"
                % {'storageSystem': storageSystemInstanceName,
                   'isSupported': isTieringPolicySupported})

        numVolInMaskingView = len(volumeInstanceNames)
        LOG.debug(
            "There are %(numVol)d volumes in the masking view %(maskingGroup)s"
            % {'numVol': numVolInMaskingView,
               'maskingGroup': maskingGroupInstanceName})

        if numVolInMaskingView == 1:  # last volume in the storage group
            # delete masking view
            mvInstanceName = self.get_masking_view_from_storage_group(
                conn, maskingGroupInstanceName)
            LOG.debug(
                "Last volume in the storage group, deleting masking view "
                "%(mvInstanceName)s"
                % {'mvInstanceName': mvInstanceName})
            conn.DeleteInstance(mvInstanceName)

            # disassociate storage group from FAST policy
            if fastPolicyName is not None and isTieringPolicySupported is True:
                tierPolicyInstanceName = self.fast.get_tier_policy_by_name(
                    conn, storageSystemInstanceName['Name'], fastPolicyName)

                LOG.info(_(
                    "policy:%(policy)s, policy service:%(service)s, "
                    "masking group=%(maskingGroup)s")
                    % {'policy': tierPolicyInstanceName,
                       'service': tierPolicyServiceInstanceName,
                       'maskingGroup': maskingGroupInstanceName})

                self.fast.delete_storage_group_from_tier_policy_rule(
                    conn, tierPolicyServiceInstanceName,
                    maskingGroupInstanceName, tierPolicyInstanceName)

            rc = self.provision.remove_device_from_storage_group(
                conn, controllerConfigService, maskingGroupInstanceName,
                volumeInstance.path, volumeName)

            LOG.debug(
                "Remove the last volume %(volumeName)s completed successfully."
                % {'volumeName': volumeName})

            # Delete storage group
            conn.DeleteInstance(maskingGroupInstanceName)

            if isTieringPolicySupported:
                self._cleanup_tiering(
                    conn, controllerConfigService, fastPolicyName,
                    volumeInstance, volumeName)
        else:
            # not the last volume
            LOG.debug("start: number of volumes in masking storage group: "
                      "%(numVol)d" % {'numVol': len(volumeInstanceNames)})
            rc = self.provision.remove_device_from_storage_group(
                conn, controllerConfigService, maskingGroupInstanceName,
                volumeInstance.path, volumeName)

            LOG.debug(
                "RemoveMembers for volume %(volumeName)s completed "
                "successfully." % {'volumeName': volumeName})

            # if FAST POLICY enabled, move the volume to the default SG
            if fastPolicyName is not None and isTieringPolicySupported:
                self._cleanup_tiering(
                    conn, controllerConfigService, fastPolicyName,
                    volumeInstance, volumeName)

            # validation
            volumeInstanceNames = self.get_devices_from_storage_group(
                conn, maskingGroupInstanceName)
            LOG.debug(
                "end: number of volumes in masking storage group: %(numVol)d"
                % {'numVol': len(volumeInstanceNames)})

        return rc

    def _cleanup_tiering(
            self, conn, controllerConfigService, fastPolicyName,
            volumeInstance, volumeName):
        """Cleanup tiering

        :param conn: the ecom connection
        :param controllerConfigService: the controller configuration service
        :param fastPolicyName: the fast policy name
        :param volumeInstance: volume instance
        :param volumeName: the volume name
        """
        defaultStorageGroupInstanceName = (
            self.fast.get_policy_default_storage_group(
                conn, controllerConfigService, fastPolicyName))
        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "start: number of volumes in default storage group: %(numVol)d"
            % {'numVol': len(volumeInstanceNames)})
        defaultStorageGroupInstanceName = (
            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                conn, controllerConfigService, volumeInstance, volumeName,
                fastPolicyName))
        # check default storage group number of volumes
        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "end: number of volumes in default storage group: %(numVol)d"
            % {'numVol': len(volumeInstanceNames)})
