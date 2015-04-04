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

from oslo_concurrency import lockutils
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume.drivers.emc import emc_vmax_fast
from cinder.volume.drivers.emc import emc_vmax_provision
from cinder.volume.drivers.emc import emc_vmax_provision_v3
from cinder.volume.drivers.emc import emc_vmax_utils

LOG = logging.getLogger(__name__)

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3
INITIATORGROUPTYPE = 2

ISCSI = 'iscsi'
FC = 'fc'

EMC_ROOT = 'root/emc'
FASTPOLICY = 'storagetype:fastpolicy'
ISV3 = 'isV3'


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
        self.provisionv3 = emc_vmax_provision_v3.EMCVMAXProvisionV3(prtcl)

    def setup_masking_view(self, conn, maskingViewDict, extraSpecs):

        @lockutils.synchronized(maskingViewDict['maskingViewName'],
                                "emc-mv-", True)
        def do_get_or_create_masking_view_and_map_lun():
            return self.get_or_create_masking_view_and_map_lun(conn,
                                                               maskingViewDict,
                                                               extraSpecs)
        do_get_or_create_masking_view_and_map_lun()

    def get_or_create_masking_view_and_map_lun(self, conn, maskingViewDict,
                                               extraSpecs):
        """Get or Create a masking view and add a volume to the storage group.

        Given a masking view tuple either get or create a masking view and add
        the volume to the associated storage group.
        If it is a live migration operation then we do not need to remove
        the volume from any storage group (default or otherwise).

        :param conn: the connection to  ecom
        :param maskingViewDict: the masking view dict
        :param extraSpecs: additional info
        :returns: dict -- rollbackDict
        :raises: VolumeBackendAPIException
        """
        rollbackDict = {}

        controllerConfigService = maskingViewDict['controllerConfigService']
        volumeInstance = maskingViewDict['volumeInstance']
        maskingViewName = maskingViewDict['maskingViewName']
        volumeName = maskingViewDict['volumeName']
        isV3 = maskingViewDict['isV3']
        isLiveMigration = maskingViewDict['isLiveMigration']
        maskingViewDict['extraSpecs'] = extraSpecs
        defaultStorageGroupInstanceName = None
        fastPolicyName = None
        assocStorageGroupName = None
        if isLiveMigration is False:
            if isV3:
                assocStorageGroupInstanceName = (
                    self.utils.get_storage_group_from_volume(
                        conn, volumeInstance.path))
                instance = conn.GetInstance(
                    assocStorageGroupInstanceName, LocalOnly=False)
                assocStorageGroupName = instance['ElementName']
                defaultSgGroupName = self.utils.get_v3_storage_group_name(
                    maskingViewDict['pool'],
                    maskingViewDict['slo'],
                    maskingViewDict['workload'])

                if assocStorageGroupName != defaultSgGroupName:
                    LOG.warn(_LW(
                        "Volume: %(volumeName)s Does not belong "
                        "to storage storage group %(defaultSgGroupName)s."),
                        {'volumeName': volumeName,
                         'defaultSgGroupName': defaultSgGroupName})
                defaultStorageGroupInstanceName = assocStorageGroupInstanceName

                self._get_and_remove_from_storage_group_v3(
                    conn, controllerConfigService, volumeInstance.path,
                    volumeName, maskingViewDict,
                    defaultStorageGroupInstanceName)
            else:
                fastPolicyName = maskingViewDict['fastPolicy']
                # If FAST is enabled remove the volume from the default SG.
                if fastPolicyName is not None:
                    defaultStorageGroupInstanceName = (
                        self._get_and_remove_from_storage_group_v2(
                            conn, controllerConfigService,
                            volumeInstance.path,
                            volumeName, fastPolicyName,
                            extraSpecs))

        maskingViewInstanceName, storageGroupInstanceName, errorMessage = (
            self._validate_masking_view(conn, maskingViewDict,
                                        defaultStorageGroupInstanceName))

        LOG.debug(
            "The masking view in the attach operation is "
            "%(maskingViewInstanceName)s.",
            {'maskingViewInstanceName': maskingViewInstanceName})

        if not errorMessage:
            # Only after the masking view has been validated, add the
            # volume to the storage group and recheck that it has been
            # successfully added.
            errorMessage = self._check_adding_volume_to_storage_group(
                conn, maskingViewDict, storageGroupInstanceName)

        rollbackDict['controllerConfigService'] = controllerConfigService
        rollbackDict['defaultStorageGroupInstanceName'] = (
            defaultStorageGroupInstanceName)
        rollbackDict['volumeInstance'] = volumeInstance
        rollbackDict['volumeName'] = volumeName
        rollbackDict['fastPolicyName'] = fastPolicyName
        rollbackDict['isV3'] = isV3
        rollbackDict['extraSpecs'] = extraSpecs

        if errorMessage:
            # Rollback code if we cannot complete any of the steps above
            # successfully then we must roll back by adding the volume back to
            # the default storage group for that fast policy.
            if (fastPolicyName is not None):
                # If the errorMessage was returned before the volume
                # was removed from the default storage group no action.
                self._check_if_rollback_action_for_masking_required(
                    conn, rollbackDict)
            if isV3:
                rollbackDict['sgGroupName'] = assocStorageGroupName
                rollbackDict['storageSystemName'] = (
                    maskingViewDict['storageSystemName'])
                self._check_if_rollback_action_for_masking_required(
                    conn, rollbackDict)

            exceptionMessage = (_(
                "Failed to get, create or add volume %(volumeName)s "
                "to masking view %(maskingViewName)s. "
                "The error message received was %(errorMessage)s.")
                % {'maskingViewName': maskingViewName,
                   'volumeName': volumeName,
                   'errorMessage': errorMessage})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return rollbackDict

    def _validate_masking_view(self, conn, maskingViewDict,
                               defaultStorageGroupInstanceName):
        """Validate all the individual pieces of the masking view.

        :param conn: the ecom connection
        :param maskingViewDict: the masking view dictionary
        :param defaultStorageGroupInstanceName: the default SG
        :returns: maskingViewInstanceName
        :returns: storageGroupInstanceName,
        :returns: string -- errorMessage
        """
        storageSystemName = maskingViewDict['storageSystemName']
        maskingViewName = maskingViewDict['maskingViewName']

        maskingViewInstanceName = self._find_masking_view(
            conn, maskingViewName, storageSystemName)
        if maskingViewInstanceName is None:
            maskingViewInstanceName, storageGroupInstanceName, errorMessage = (
                self._validate_new_masking_view(
                    conn, maskingViewDict, defaultStorageGroupInstanceName))

        else:
            storageGroupInstanceName, errorMessage = (
                self._validate_existing_masking_view(
                    conn, maskingViewDict, maskingViewInstanceName))

        return maskingViewInstanceName, storageGroupInstanceName, errorMessage

    def _validate_new_masking_view(self, conn, maskingViewDict,
                                   defaultStorageGroupInstanceName):
        """Validate the creation of a new masking view.

        :param conn: the ecom connection
        :param maskingViewDict: the masking view dictionary
        :param defaultStorageGroupInstanceName: the default SG
        :returns: maskingViewInstanceName
        :returns: storageGroupInstanceName,
        :returns: string -- errorMessage
        """
        controllerConfigService = maskingViewDict['controllerConfigService']
        igGroupName = maskingViewDict['igGroupName']
        connector = maskingViewDict['connector']
        storageSystemName = maskingViewDict['storageSystemName']
        maskingViewName = maskingViewDict['maskingViewName']
        pgGroupName = maskingViewDict['pgGroupName']

        storageGroupInstanceName, errorMessage = (
            self._check_storage_group(
                conn, maskingViewDict, defaultStorageGroupInstanceName))
        if errorMessage:
            return None, storageGroupInstanceName, errorMessage

        portGroupInstanceName, errorMessage = (
            self._check_port_group(conn, controllerConfigService,
                                   pgGroupName))
        if errorMessage:
            return None, storageGroupInstanceName, errorMessage

        initiatorGroupInstanceName, errorMessage = (
            self._check_initiator_group(conn, controllerConfigService,
                                        igGroupName, connector,
                                        storageSystemName))
        if errorMessage:
            return None, storageGroupInstanceName, errorMessage

        # Only after the components of the MV have been validated,
        # add the volume to the storage group and recheck that it
        # has been successfully added.  This is necessary before
        # creating a new masking view.
        errorMessage = self._check_adding_volume_to_storage_group(
            conn, maskingViewDict, storageGroupInstanceName)
        if errorMessage:
            return None, storageGroupInstanceName, errorMessage

        maskingViewInstanceName, errorMessage = (
            self._check_masking_view(
                conn, controllerConfigService,
                maskingViewName, storageGroupInstanceName,
                portGroupInstanceName, initiatorGroupInstanceName))

        return maskingViewInstanceName, storageGroupInstanceName, errorMessage

    def _validate_existing_masking_view(self,
                                        conn, maskingViewDict,
                                        maskingViewInstanceName):
        """Validate the components of an existing masking view.

        :param conn: the ecom connection
        :param maskingViewDict: the masking view dictionary
        :param maskingViewInstanceName: the masking view instance name
        :returns: storageGroupInstanceName
        :returns: string -- errorMessage
        """
        storageGroupInstanceName = None
        controllerConfigService = maskingViewDict['controllerConfigService']
        sgGroupName = maskingViewDict['sgGroupName']
        igGroupName = maskingViewDict['igGroupName']
        connector = maskingViewDict['connector']
        storageSystemName = maskingViewDict['storageSystemName']
        maskingViewName = maskingViewDict['maskingViewName']

        # First verify that the initiator group matches the initiators.
        errorMessage = self._check_existing_initiator_group(
            conn, controllerConfigService, maskingViewName,
            connector, storageSystemName, igGroupName)

        if errorMessage:
            return storageGroupInstanceName, errorMessage

        storageGroupInstanceName, errorMessage = (
            self._check_existing_storage_group(
                conn, controllerConfigService, sgGroupName,
                maskingViewInstanceName))

        return storageGroupInstanceName, errorMessage

    def _check_storage_group(self, conn,
                             maskingViewDict, storageGroupInstanceName):
        """Get the storage group and return it.

        :param conn: the ecom connection
        :param maskingViewDict: the masking view dictionary
        :param storageGroupInstanceName: default storage group instance name
        :returns: storageGroupInstanceName
        :returns: string -- msg, the error message
        """
        msg = None
        storageGroupInstanceName = (
            self._get_storage_group_instance_name(
                conn, maskingViewDict, storageGroupInstanceName))
        if storageGroupInstanceName is None:
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Cannot get or create a storage group: %(sgGroupName)s"
                " for volume %(volumeName)s ") %
                {'sgGroupName': maskingViewDict['sgGroupName'],
                 'volumeName': maskingViewDict['volumeName']})
            LOG.error(msg)
        return storageGroupInstanceName, msg

    def _check_existing_storage_group(
            self, conn, controllerConfigService,
            sgGroupName, maskingViewInstanceName):
        """Check that we can get the existing storage group.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param sgGroupName: the storage group name
        :param maskingViewInstanceName: the masking view instance name
        :returns: storageGroupInstanceName
        :returns: string -- msg, the error message
        """
        msg = None

        sgFromMvInstanceName = (
            self._get_storage_group_from_masking_view_instance(
                conn, maskingViewInstanceName))

        if sgFromMvInstanceName is None:
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Cannot get storage group: %(sgGroupName)s "
                "from masking view %(maskingViewInstanceName)s. ") %
                {'sgGroupName': sgGroupName,
                 'maskingViewInstanceName': maskingViewInstanceName})
            LOG.error(msg)
        return sgFromMvInstanceName, msg

    def _check_port_group(self, conn,
                          controllerConfigService, pgGroupName):
        """Check that you can either get or create a port group.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param pgGroupName: the port group Name
        :returns: portGroupInstanceName
        :returns: string -- msg, the error message
        """
        msg = None
        portGroupInstanceName = self._get_port_group_instance_name(
            conn, controllerConfigService, pgGroupName)
        if portGroupInstanceName is None:
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Cannot get port group: %(pgGroupName)s. ") %
                {'pgGroupName': pgGroupName})
            LOG.error(msg)

        return portGroupInstanceName, msg

    def _check_initiator_group(
            self, conn, controllerConfigService, igGroupName,
            connector, storageSystemName):
        """Check that initiator group can be either retrieved or created.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param igGroupName: the initiator group Name
        :param connector: the connector object
        :param storageSystemName: the storage system name
        :returns: initiatorGroupInstanceName
        :returns: string -- the error message
        """
        msg = None
        initiatorGroupInstanceName = (
            self._get_initiator_group_instance_name(
                conn, controllerConfigService, igGroupName, connector,
                storageSystemName))
        if initiatorGroupInstanceName is None:
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Cannot get or create initiator group: "
                "%(igGroupName)s. ") %
                {'igGroupName': igGroupName})
            LOG.error(msg)

        return initiatorGroupInstanceName, msg

    def _check_existing_initiator_group(
            self, conn, controllerConfigService, maskingViewName,
            connector, storageSystemName, igGroupName):
        """Check that existing initiator group in the masking view.

        Check if the initiators in the initiator group match those in the
        system.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param maskingViewName: the masking view name
        :param connector: the connector object
        :param storageSystemName: the storage system name
        :param igGroupName: the initiator group name
        :returns: string -- msg, the error message
        """
        msg = None
        if not self._verify_initiator_group_from_masking_view(
                conn, controllerConfigService, maskingViewName,
                connector, storageSystemName, igGroupName):
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Unable to verify initiator group: %(igGroupName)s "
                "in masking view %(maskingViewName)s. ") %
                {'igGroupName': igGroupName,
                 'maskingViewName': maskingViewName})
            LOG.error(msg)
        return msg

    def _check_masking_view(
            self, conn, controllerConfigService,
            maskingViewName, storageGroupInstanceName,
            portGroupInstanceName, initiatorGroupInstanceName):
        """Check that masking view can be either got or created.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param maskingViewName: the masking view name
        :param storageGroupInstanceName: storage group instance name
        :param portGroupInstanceName: port group instance name
        :param initiatorGroupInstanceName: the initiator group instance name
        :returns: maskingViewInstanceName
        :returns: string -- msg, the error message
        """
        msg = None
        maskingViewInstanceName = (
            self._get_masking_view_instance_name(
                conn, controllerConfigService, maskingViewName,
                storageGroupInstanceName, portGroupInstanceName,
                initiatorGroupInstanceName))
        if maskingViewInstanceName is None:
            # This may be used in exception hence _ instead of _LE.
            msg = (_(
                "Cannot create masking view: %(maskingViewName)s. ") %
                {'maskingViewName': maskingViewName})
            LOG.error(msg)

        return maskingViewInstanceName, msg

    def _check_adding_volume_to_storage_group(
            self, conn, maskingViewDict, storageGroupInstanceName):
        """Add the volume to the storage group and double check it is there.

        :param conn: the ecom connection
        :param maskingViewDict: the masking view dictionary
        :param storageGroupInstanceName: storage group instance name
        :returns: string -- the error message
        """
        controllerConfigService = maskingViewDict['controllerConfigService']
        sgGroupName = maskingViewDict['sgGroupName']
        volumeInstance = maskingViewDict['volumeInstance']
        volumeName = maskingViewDict['volumeName']
        msg = None
        if self._is_volume_in_storage_group(
                conn, storageGroupInstanceName,
                volumeInstance):
            LOG.warn(_LW(
                "Volume: %(volumeName)s is already part "
                "of storage group %(sgGroupName)s."),
                {'volumeName': volumeName,
                 'sgGroupName': sgGroupName})
        else:
            self.add_volume_to_storage_group(
                conn, controllerConfigService,
                storageGroupInstanceName, volumeInstance, volumeName,
                sgGroupName, maskingViewDict['extraSpecs'])
            if not self._is_volume_in_storage_group(
                    conn, storageGroupInstanceName,
                    volumeInstance):
                # This may be used in exception hence _ instead of _LE.
                msg = (_(
                    "Volume: %(volumeName)s was not added "
                    "to storage group %(sgGroupName)s. ") %
                    {'volumeName': volumeName,
                     'sgGroupName': sgGroupName})
                LOG.error(msg)
            else:
                LOG.debug("Successfully added %(volumeName)s to "
                          "%(sgGroupName)s.",
                          {'volumeName': volumeName,
                           'sgGroupName': sgGroupName})

        return msg

    def _get_and_remove_from_storage_group_v2(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, fastPolicyName, extraSpecs):
        """Get the storage group and remove volume from it.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param volumeInstanceName: volume instance name
        :param volumeName: volume name
        :param fastPolicyName: fast name
        :param extraSpecs: additional info
        :returns: defaultStorageGroupInstanceName
        :raises: VolumeBackendAPIException
        """
        defaultStorageGroupInstanceName = (
            self.fast.get_and_verify_default_storage_group(
                conn, controllerConfigService, volumeInstanceName,
                volumeName, fastPolicyName))
        if defaultStorageGroupInstanceName is None:
            exceptionMessage = (_(
                "Cannot get the default storage group for FAST policy: "
                "%(fastPolicyName)s.")
                % {'fastPolicyName': fastPolicyName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        retStorageGroupInstanceName = (
            self.remove_device_from_default_storage_group(
                conn, controllerConfigService, volumeInstanceName,
                volumeName, fastPolicyName, extraSpecs))
        if retStorageGroupInstanceName is None:
            exceptionMessage = (_(
                "Failed to remove volume %(volumeName)s from default SG: "
                "%(volumeName)s.")
                % {'volumeName': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        return defaultStorageGroupInstanceName

    def _get_and_remove_from_storage_group_v3(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, maskingViewDict, storageGroupInstanceName):
        """Get the storage group and remove volume from it.

        :param conn: the ecom connection
        :param controllerConfigService: controller configuration service
        :param volumeInstanceName: volume instance name
        :param volumeName: volume name
        :param maskingViewDict: the masking view dictionary
        :param storageGroupInstanceName: storage group instance name
        :raises: VolumeBackendAPIException
        """

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, storageGroupInstanceName)
        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "before removing volume %(volumeName)s.",
            {'length': len(assocVolumeInstanceNames),
             'volumeName': volumeName})

        self.provision.remove_device_from_storage_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName, maskingViewDict['extraSpecs'])

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, storageGroupInstanceName)
        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "after removing volume %(volumeName)s.",
            {'length': len(assocVolumeInstanceNames),
             'volumeName': volumeName})

        # Required for unit tests.
        emptyStorageGroupInstanceName = (
            self._wrap_get_storage_group_from_volume(conn, volumeInstanceName))

        if emptyStorageGroupInstanceName is not None:
            exceptionMessage = (_(
                "Failed to remove volume %(volumeName)s from default SG: "
                "%(volumeName)s.")
                % {'volumeName': volumeName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

    def _is_volume_in_storage_group(
            self, conn, storageGroupInstanceName, volumeInstance):
        """Check if the volume is already part of the storage group.

        Check if the volume is already part of the storage group,
        if it is no need to re-add it.

        :param conn: the connection to  ecom
        :param storageGroupInstanceName: the storage group instance name
        :param volumeInstance: the volume instance
        :returns: boolean
        """
        foundStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(
                conn, volumeInstance.path))

        if foundStorageGroupInstanceName is not None:
            storageGroupInstance = conn.GetInstance(
                storageGroupInstanceName, LocalOnly=False)
            LOG.debug(
                "The existing storage group instance element name is: "
                "%(existingElement)s.",
                {'existingElement': storageGroupInstance['ElementName']})
            foundStorageGroupInstance = conn.GetInstance(
                foundStorageGroupInstanceName, LocalOnly=False)
            LOG.debug(
                "The found storage group instance element name is: "
                "%(foundElement)s.",
                {'foundElement': foundStorageGroupInstance['ElementName']})
            if (foundStorageGroupInstance['ElementName'] == (
                    storageGroupInstance['ElementName'])):
                return True

        return False

    def _find_masking_view(self, conn, maskingViewName, storageSystemName):
        """Given the masking view name get the masking view instance.

        :param conn: connection to the ecom server
        :param maskingViewName: the masking view name
        :param storageSystemName: the storage system name(String)
        :returns: dict -- foundMaskingViewInstanceName
        """
        foundMaskingViewInstanceName = None

        storageSystemInstanceName = self.utils.find_storageSystem(
            conn, storageSystemName)
        maskingViewInstances = conn.Associators(
            storageSystemInstanceName,
            ResultClass='EMC_LunMaskingSCSIProtocolController')

        for maskingViewInstance in maskingViewInstances:
            if maskingViewName == maskingViewInstance['ElementName']:
                foundMaskingViewInstanceName = maskingViewInstance.path
                break

        if foundMaskingViewInstanceName is not None:
            # Now check that is has not been deleted.
            instance = self.utils.get_existing_instance(
                conn, foundMaskingViewInstanceName)
            if instance is None:
                foundMaskingViewInstanceName = None
                LOG.error(_LE(
                    "Looks like masking view: %(maskingViewName)s "
                    "has recently been deleted."),
                    {'maskingViewName': maskingViewName})
            else:
                LOG.info(_LI(
                    "Found existing masking view: %(maskingViewName)s."),
                    {'maskingViewName': maskingViewName})

        return foundMaskingViewInstanceName

    def _create_storage_group(
            self, conn, maskingViewDict, defaultStorageGroupInstanceName):
        """Create a new storage group that doesn't already exist.

        If fastPolicyName is not none we attempt to remove it from the
        default storage group of that policy and associate to the new storage
        group that will be part of the masking view.
        Will not handle any exception in this method it will be handled
        up the stack.

        :param conn: connection the ecom server
        :param maskingViewDict: the masking view dictionary
        :param defaultStorageGroupInstanceName: the default storage group
            instance name (Can be None)
        :returns: foundStorageGroupInstanceName the instance Name of the
            storage group
        """
        failedRet = None
        controllerConfigService = maskingViewDict['controllerConfigService']
        storageGroupName = maskingViewDict['sgGroupName']
        isV3 = maskingViewDict['isV3']

        if isV3:
            workload = maskingViewDict['workload']
            pool = maskingViewDict['pool']
            slo = maskingViewDict['slo']
            foundStorageGroupInstanceName = (
                self.provisionv3.create_storage_group_v3(
                    conn, controllerConfigService, storageGroupName,
                    pool, slo, workload, maskingViewDict['extraSpecs']))
        else:
            fastPolicyName = maskingViewDict['fastPolicy']
            volumeInstance = maskingViewDict['volumeInstance']
            foundStorageGroupInstanceName = (
                self.provision.create_and_get_storage_group(
                    conn, controllerConfigService, storageGroupName,
                    volumeInstance.path, maskingViewDict['extraSpecs']))
            if (fastPolicyName is not None and
                    defaultStorageGroupInstanceName is not None):
                assocTierPolicyInstanceName = (
                    self.fast.add_storage_group_and_verify_tier_policy_assoc(
                        conn, controllerConfigService,
                        foundStorageGroupInstanceName,
                        storageGroupName, fastPolicyName,
                        maskingViewDict['extraSpecs']))
                if assocTierPolicyInstanceName is None:
                    LOG.error(_LE(
                        "Cannot add and verify tier policy association for "
                        "storage group : %(storageGroupName)s to "
                        "FAST policy : %(fastPolicyName)s."),
                        {'storageGroupName': storageGroupName,
                         'fastPolicyName': fastPolicyName})
                    return failedRet
        if foundStorageGroupInstanceName is None:
            LOG.error(_LE(
                "Cannot get storage Group from job : %(storageGroupName)s."),
                {'storageGroupName': storageGroupName})
            return failedRet
        else:
            LOG.info(_LI(
                "Created new storage group: %(storageGroupName)s."),
                {'storageGroupName': storageGroupName})

        return foundStorageGroupInstanceName

    def _find_port_group(self, conn, controllerConfigService, portGroupName):
        """Given the port Group name get the port group instance name.

        :param conn: connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param portGroupName: the name of the port group you are getting
        :returns: foundPortGroupInstanceName
        """
        foundPortGroupInstanceName = None
        portMaskingGroupInstances = conn.Associators(
            controllerConfigService, ResultClass='CIM_TargetMaskingGroup')

        for portMaskingGroupInstance in portMaskingGroupInstances:
            if portGroupName == portMaskingGroupInstance['ElementName']:
                # Check to see if it has been recently deleted.
                instance = self.utils.get_existing_instance(
                    conn, portMaskingGroupInstance.path)
                if instance is None:
                    foundPortGroupInstanceName = None
                else:
                    foundPortGroupInstanceName = instance.path
                break

        if foundPortGroupInstanceName is None:
            LOG.error(_LE(
                "Could not find port group : %(portGroupName)s. Check that "
                "the EMC configuration file has the correct port group name."),
                {'portGroupName': portGroupName})

        return foundPortGroupInstanceName

    def _create_or_get_initiator_group(
            self, conn, controllerConfigService, igGroupName,
            connector, storageSystemName):
        """Attempt to create a initiatorGroup.

        If one already exists with the same Initiator/wwns then get it.
        Check to see if an initiatorGroup already exists, that matches the
        connector information.
        NOTE:  An initiator/wwn can only belong to one initiatorGroup.
        If we were to attempt to create one with an initiator/wwn that
        is already belong to another initiatorGroup, it would fail.

        :param conn: connection to the ecom server
        :param controllerConfigService: the controller config Servicer
        :param igGroupName: the proposed name of the initiator group
        :param connector: the connector information to the host
        :param storageSystemName: the storage system name (String)
        :returns: foundInitiatorGroupInstanceName
        """
        initiatorNames = self._find_initiator_names(conn, connector)
        LOG.debug("The initiator name(s) are: %(initiatorNames)s.",
                  {'initiatorNames': initiatorNames})

        foundInitiatorGroupInstanceName = self._find_initiator_masking_group(
            conn, controllerConfigService, initiatorNames)

        # If you cannot find an initiatorGroup that matches the connector
        # info create a new initiatorGroup.
        if foundInitiatorGroupInstanceName is None:
            # Check that our connector information matches the
            # hardwareId(s) on the vmax.
            storageHardwareIDInstanceNames = (
                self._get_storage_hardware_id_instance_names(
                    conn, initiatorNames, storageSystemName))
            if not storageHardwareIDInstanceNames:
                LOG.info(_LI(
                    "Initiator Name(s) %(initiatorNames)s are not on array "
                    "%(storageSystemName)s."),
                    {'initiatorNames': initiatorNames,
                     'storageSystemName': storageSystemName})
                storageHardwareIDInstanceNames = (
                    self._create_hardware_ids(conn, initiatorNames,
                                              storageSystemName))
                if not storageHardwareIDInstanceNames:
                    msg = (_("Failed to create hardware id(s) on "
                             "%(storageSystemName)s.")
                           % {'storageSystemName': storageSystemName})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            foundInitiatorGroupInstanceName = self._create_initiator_Group(
                conn, controllerConfigService, igGroupName,
                storageHardwareIDInstanceNames)

            LOG.info(_LI(
                "Created new initiator group name: %(igGroupName)s."),
                {'igGroupName': igGroupName})
        else:
            LOG.info(_LI(
                "Using existing initiator group name: %(igGroupName)s."),
                {'igGroupName': igGroupName})

        return foundInitiatorGroupInstanceName

    def _find_initiator_names(self, conn, connector):
        """Check the connector object for initiators(ISCSI) or wwpns(FC).

        :param conn: the connection to the ecom
        :param connector: the connector object
        :returns: list -- list of found initiator names
        :raises: VolumeBackendAPIException
        """
        foundinitiatornames = []
        name = 'initiator name'
        if (self.protocol.lower() == ISCSI and connector['initiator']):
            foundinitiatornames.append(connector['initiator'])
        elif self.protocol.lower() == FC:
            if ('wwpns' in connector and connector['wwpns']):
                for wwn in connector['wwpns']:
                    foundinitiatornames.append(wwn)
                name = 'world wide port names'
            else:
                msg = (_("FC is the protocol but wwpns are "
                         "not supplied by Openstack."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        if (foundinitiatornames is None or len(foundinitiatornames) == 0):
            msg = (_("Error finding %(name)s.")
                   % {'name': name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Found %(name)s: %(initiator)s.",
                  {'name': name,
                   'initiator': foundinitiatornames})

        return foundinitiatornames

    def _find_initiator_masking_group(
            self, conn, controllerConfigService, initiatorNames):
        """Check to see if an initiatorGroup already exists.

        NOTE:  An initiator/wwn can only belong to one initiatorGroup.
        If we were to attempt to create one with an initiator/wwn that is
        already belong to another initiatorGroup, it would fail.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param initiatorNames: the list of initiator names
        :returns: foundInitiatorMaskingGroup
        """
        foundInitiatorMaskingGroupInstanceName = None

        initiatorMaskingGroupInstanceNames = (
            conn.AssociatorNames(controllerConfigService,
                                 ResultClass='CIM_InitiatorMaskingGroup'))

        for initiatorMaskingGroupInstanceName in \
                initiatorMaskingGroupInstanceNames:
            # Check that it hasn't been deleted. If it has, break out
            # of the for loop.
            instance = self.utils.get_existing_instance(
                conn, initiatorMaskingGroupInstanceName)
            if instance is None:
                # MaskingGroup doesn't exist any more.
                break

            storageHardwareIdInstances = (
                conn.Associators(initiatorMaskingGroupInstanceName,
                                 ResultClass='EMC_StorageHardwareID'))
            for storageHardwareIdInstance in storageHardwareIdInstances:
                # If EMC_StorageHardwareID matches the initiator,
                # we found the existing CIM_InitiatorMaskingGroup.
                hardwareid = storageHardwareIdInstance['StorageID']
                for initiator in initiatorNames:
                    if six.text_type(hardwareid).lower() == \
                            six.text_type(initiator).lower():
                        foundInitiatorMaskingGroupInstanceName = (
                            initiatorMaskingGroupInstanceName)
                        break

                if foundInitiatorMaskingGroupInstanceName is not None:
                    break

            if foundInitiatorMaskingGroupInstanceName is not None:
                break
        return foundInitiatorMaskingGroupInstanceName

    def _get_storage_hardware_id_instance_names(
            self, conn, initiatorNames, storageSystemName):
        """Given a list of initiator names find CIM_StorageHardwareID instance.

        :param conn: the connection to the ecom server
        :param initiatorNames: the list of initiator names
        :param storageSystemName: the storage system name
        :returns: list -- foundHardwardIDsInstanceNames
        """
        foundHardwardIDsInstanceNames = []

        hardwareIdManagementService = (
            self.utils.find_storage_hardwareid_service(
                conn, storageSystemName))

        hardwareIdInstances = (
            self.utils.get_hardware_id_instances_from_array(
                conn, hardwareIdManagementService))

        for hardwareIdInstance in hardwareIdInstances:
            storageId = hardwareIdInstance['StorageID']
            for initiatorName in initiatorNames:
                if storageId.lower() == initiatorName.lower():
                    # Check that the found hardwareId has been deleted.
                    # If it has, we don't want to add it to the list.
                    instance = self.utils.get_existing_instance(
                        conn, hardwareIdInstance.path)
                    if instance is None:
                        # HardwareId doesn't exist. Skip it.
                        break

                    foundHardwardIDsInstanceNames.append(
                        hardwareIdInstance.path)
                    break

        LOG.debug(
            "The found hardware IDs are : %(foundHardwardIDsInstanceNames)s.",
            {'foundHardwardIDsInstanceNames': foundHardwardIDsInstanceNames})

        return foundHardwardIDsInstanceNames

    def _get_initiator_group_from_job(self, conn, job):
        """After creating an new initiator group find it and return it.

        :param conn: the connection to the ecom server
        :param job: the create initiator group job
        :returns: dict -- initiatorDict
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
        """After creating an new initiator group find it and return it.

        :param conn: the connection to the ecom server
        :param configService: the create initiator group job
        :param maskingViewName: the masking view name string
        :param deviceMaskingGroup: device(storage) masking group (instanceName)
        :param targetMaskingGroup: target(port) masking group (instanceName)
        :param initiatorMaskingGroup: initiator masking group (instanceName)
        :returns: int -- return code
        :returns: dict -- job
        :raises: VolumeBackendAPIException
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
                    "Return code: %(rc)lu. Error: %(error)s.")
                    % {'groupName': maskingViewName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.info(_LI("Created new masking view : %(maskingViewName)s."),
                 {'maskingViewName': maskingViewName})
        return rc, job

    def find_new_masking_view(self, conn, jobDict):
        """Find the newly created volume.

        :param conn: the connection to the ecom server
        :param jobDict: the job dictionary
        :returns: dict -- maskingViewInstance
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
        foundView = self._find_masking_view(
            conn, maskingViewName, storageSystemName)
        if foundView is not None:
            foundStorageGroupInstanceName = (
                self._get_storage_group_from_masking_view_instance(
                    conn, foundView))

            LOG.debug(
                "Masking view: %(view)s DeviceMaskingGroup: %(masking)s.",
                {'view': maskingViewName,
                 'masking': foundStorageGroupInstanceName})
        else:
            LOG.warn(_LW("Unable to find Masking view: %(view)s."),
                     {'view': maskingViewName})

        return foundStorageGroupInstanceName

    def _get_storage_group_from_masking_view_instance(
            self, conn, maskingViewInstance):
        """Gets the Device Masking Group from masking view instance.

        :param conn: the connection to the ecom server
        :param maskingViewInstance: the masking view instance
        :returns: instance name foundStorageGroupInstanceName
        """
        foundStorageGroupInstanceName = None
        groups = conn.AssociatorNames(
            maskingViewInstance,
            ResultClass='CIM_DeviceMaskingGroup')
        if groups[0] > 0:
            foundStorageGroupInstanceName = groups[0]

        return foundStorageGroupInstanceName

    def _get_storage_group_instance_name(
            self, conn, maskingViewDict,
            defaultStorageGroupInstanceName):
        """Gets the storage group instance name.

        If fastPolicy name is None then NON FAST is assumed.
        If it is a valid fastPolicy name then associate the new storage
        group with the fast policy.
        If we are using an existing storage group then we must check that
        it is associated with the correct fast policy.

        :param conn: the connection to the ecom server
        :param maskingViewDict: the masking view dictionary
        :param defaultStorageGroupInstanceName: default storage group instance
            name (can be None for Non FAST)
        :returns: instance name storageGroupInstanceName
        :raises: VolumeBackendAPIException
        """
        storageGroupInstanceName = self.utils.find_storage_masking_group(
            conn, maskingViewDict['controllerConfigService'],
            maskingViewDict['sgGroupName'])

        if storageGroupInstanceName is None:
            storageGroupInstanceName = self._create_storage_group(
                conn, maskingViewDict,
                defaultStorageGroupInstanceName)
            if storageGroupInstanceName is None:
                errorMessage = (_(
                    "Cannot create or find an storage group with name "
                    "%(sgGroupName)s.")
                    % {'sgGroupName': maskingViewDict['sgGroupName']})
                LOG.error(errorMessage)
                raise exception.VolumeBackendAPIException(data=errorMessage)

        return storageGroupInstanceName

    def _get_port_group_instance_name(
            self, conn, controllerConfigService, pgGroupName):
        """Gets the port group instance name.

        The portGroup name has been defined in the EMC Config file if it
        does not exist the operation should fail.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param pgGroupName: the port group name
        :returns: instance name foundPortGroupInstanceName
        """
        foundPortGroupInstanceName = self._find_port_group(
            conn, controllerConfigService, pgGroupName)
        if foundPortGroupInstanceName is None:
            LOG.error(_LE(
                "Cannot find a portGroup with name %(pgGroupName)s. "
                "The port group for a masking view must be pre-defined."),
                {'pgGroupName': pgGroupName})
            return foundPortGroupInstanceName

        LOG.info(_LI(
            "Port group instance name is %(foundPortGroupInstanceName)s."),
            {'foundPortGroupInstanceName': foundPortGroupInstanceName})

        return foundPortGroupInstanceName

    def _get_initiator_group_instance_name(
            self, conn, controllerConfigService, igGroupName, connector,
            storageSystemName):
        """Gets the initiator group instance name.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param igGroupName: the port group name
        :param connector: the connector object
        :param storageSystemName: the storage system name
        :returns: foundInitiatorGroupInstanceName
        """
        foundInitiatorGroupInstanceName = (self._create_or_get_initiator_group(
            conn, controllerConfigService, igGroupName, connector,
            storageSystemName))
        if foundInitiatorGroupInstanceName is None:
            LOG.error(_LE(
                "Cannot create or find an initiator group with "
                "name %(igGroupName)s."),
                {'igGroupName': igGroupName})
        return foundInitiatorGroupInstanceName

    def _get_masking_view_instance_name(
            self, conn, controllerConfigService, maskingViewName,
            storageGroupInstanceName, portGroupInstanceName,
            initiatorGroupInstanceName):
        """Gets the masking view instance name.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration server
        :param maskingViewName: the masking view name (String)
        :param storageGroupInstanceName: the storage group instance name
        :param portGroupInstanceName: the port group instance name
        :param initiatorGroupInstanceName: the initiator group instance name
        :returns: instance name foundMaskingViewInstanceName
        """
        _rc, job = (
            self._create_masking_view(
                conn, controllerConfigService, maskingViewName,
                storageGroupInstanceName, portGroupInstanceName,
                initiatorGroupInstanceName))
        foundMaskingViewInstanceName = self.find_new_masking_view(conn, job)
        if foundMaskingViewInstanceName is None:
            LOG.error(_LE(
                "Cannot find the new masking view just created with name "
                "%(maskingViewName)s."),
                {'maskingViewName': maskingViewName})

        return foundMaskingViewInstanceName

    def _check_if_rollback_action_for_masking_required(
            self, conn, rollbackDict):
        """This is a rollback action for FAST.

        We need to be able to return the volume to the default storage group
        if anything has gone wrong. The volume can also potentially belong to
        a storage group that is not the default depending on where
        the exception occurred.

        :param conn: the connection to the ecom server
        :param rollbackDict: the rollback dictionary
        :raises: VolumeBackendAPIException
        """
        try:
            if rollbackDict['isV3']:
                errorMessage = self._check_adding_volume_to_storage_group(
                    conn, rollbackDict,
                    rollbackDict['defaultStorageGroupInstanceName'])
                if errorMessage:
                    LOG.error(errorMessage)

            else:
                foundStorageGroupInstanceName = (
                    self.utils.get_storage_group_from_volume(
                        conn, rollbackDict['volumeInstance'].path))
                # Volume is not associated with any storage group so add
                # it back to the default.
                if len(foundStorageGroupInstanceName) == 0:
                    LOG.warn(_LW(
                        "No storage group found. "
                        "Performing rollback on Volume: %(volumeName)s "
                        "To return it to the default storage group for FAST "
                        "policy %(fastPolicyName)s."),
                        {'volumeName': rollbackDict['volumeName'],
                         'fastPolicyName': rollbackDict['fastPolicyName']})
                    assocDefaultStorageGroupName = (
                        self.fast
                        .add_volume_to_default_storage_group_for_fast_policy(
                            conn,
                            rollbackDict['controllerConfigService'],
                            rollbackDict['volumeInstance'],
                            rollbackDict['volumeName'],
                            rollbackDict['fastPolicyName'],
                            rollbackDict['extraSpecs']))
                    if assocDefaultStorageGroupName is None:
                        LOG.error(_LE(
                            "Failed to Roll back to re-add volume "
                            "%(volumeName)s "
                            "to default storage group for fast policy "
                            "%(fastPolicyName)s: Please contact your sys "
                            "admin to get the volume re-added manually."),
                            {'volumeName': rollbackDict['volumeName'],
                             'fastPolicyName': rollbackDict['fastPolicyName']})
                if len(foundStorageGroupInstanceName) > 0:
                    LOG.info(_LI(
                        "The storage group found is "
                        "%(foundStorageGroupInstanceName)s."),
                        {'foundStorageGroupInstanceName':
                         foundStorageGroupInstanceName})

                # Check the name, see is it the default storage group
                # or another.
                if (foundStorageGroupInstanceName !=
                        rollbackDict['defaultStorageGroupInstanceName']):
                    # Remove it from its current masking view and return it
                    # to its default masking view if fast is enabled.
                    self.remove_and_reset_members(
                        conn,
                        rollbackDict['controllerConfigService'],
                        rollbackDict['volumeInstance'],
                        rollbackDict['fastPolicyName'],
                        rollbackDict['volumeName'], rollbackDict['extraSpecs'],
                        False)
        except Exception as e:
            LOG.error(_LE("Exception: %s."), e)
            errorMessage = (_(
                "Rollback for Volume: %(volumeName)s has failed. "
                "Please contact your system administrator to manually return "
                "your volume to the default storage group for fast policy "
                "%(fastPolicyName)s failed.")
                % {'volumeName': rollbackDict['volumeName'],
                   'fastPolicyName': rollbackDict['fastPolicyName']})
            LOG.error(errorMessage)
            raise exception.VolumeBackendAPIException(data=errorMessage)

    def _find_new_initiator_group(self, conn, maskingGroupDict):
        """After creating an new initiator group find it and return it.

        :param conn: connection the ecom server
        :param maskingGroupDict: the maskingGroupDict dict
        :returns: instance name foundInitiatorGroupInstanceName
        """
        foundInitiatorGroupInstanceName = None

        if 'MaskingGroup' in maskingGroupDict:
            foundInitiatorGroupInstanceName = maskingGroupDict['MaskingGroup']

        return foundInitiatorGroupInstanceName

    def _get_initiator_group_from_masking_view(
            self, conn, maskingViewName, storageSystemName):
        """Given the masking view name get the initiator group from it.

        :param conn: connection the the ecom server
        :param maskingViewName: the name of the masking view
        :param storageSystemName: the storage system name
        :returns: instance name foundInitiatorMaskingGroupInstanceName
        """
        foundInitiatorMaskingGroupInstanceName = None
        foundView = self._find_masking_view(
            conn, maskingViewName, storageSystemName)
        if foundView is not None:
            groups = conn.AssociatorNames(
                foundView,
                ResultClass='CIM_InitiatorMaskingGroup')
            if len(groups):
                foundInitiatorMaskingGroupInstanceName = groups[0]

            LOG.debug(
                "Masking view: %(view)s InitiatorMaskingGroup: %(masking)s.",
                {'view': maskingViewName,
                 'masking': foundInitiatorMaskingGroupInstanceName})
        else:
            LOG.warn(_LW("Unable to find Masking view: %(view)s."),
                     {'view': maskingViewName})

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
        :returns: boolean
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
                        LOG.info(_LI(
                            "Initiator Name(s) %(initiatorNames)s are not on "
                            "array %(storageSystemName)s. "),
                            {'initiatorNames': initiatorNames,
                             'storageSystemName': storageSystemName})
                        storageHardwareIDInstanceNames = (
                            self._create_hardware_ids(conn, initiatorNames,
                                                      storageSystemName))
                        if not storageHardwareIDInstanceNames:
                            LOG.error(_LE(
                                "Failed to create hardware id(s) on "
                                "%(storageSystemName)s."),
                                {'storageSystemName': storageSystemName})
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
                            "%(maskingViewName)s.",
                            {'maskingViewName': maskingViewName})
                else:
                    LOG.error(_LE(
                        "One of the components of the original masking view "
                        "%(maskingViewName)s cannot be retrieved so "
                        "please contact your system administrator to check "
                        "that the correct initiator(s) are part of masking."),
                        {'maskingViewName': maskingViewName})
                    return False
        return True

    def _create_initiator_Group(
            self, conn, controllerConfigService, igGroupName,
            hardwareIdinstanceNames):
        """Create a new initiator group.

        Given a list of hardwareId Instance name create a new
        initiator group.

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param igGroupName: the initiator group name (String)
        :param hardwareIdinstanceNames: one or more hardware id instance names
        :returns: foundInitiatorGroupInstanceName
        :raises: VolumeBackendAPIException
        """
        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=igGroupName,
            Type=self.utils.get_num(INITIATORGROUPTYPE, '16'),
            Members=[hardwareIdinstanceNames[0]])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
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
                            "Return code: %(rc)lu.  Error: %(error)s.")
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
        """Given the masking view name get the port group from it.

        :param conn: connection the the ecom server
        :param maskingViewName: the name of the masking view
        :param storageSystemName: the storage system name
        :returns: instance name foundPortMaskingGroupInstanceName
        """

        foundPortMaskingGroupInstanceName = None
        foundView = self._find_masking_view(
            conn, maskingViewName, storageSystemName)
        if foundView:
            groups = conn.AssociatorNames(
                foundView,
                ResultClass='CIM_TargetMaskingGroup')
            if len(groups) > 0:
                foundPortMaskingGroupInstanceName = groups[0]

            LOG.debug(
                "Masking view: %(view)s InitiatorMaskingGroup: %(masking)s.",
                {'view': maskingViewName,
                 'masking': foundPortMaskingGroupInstanceName})

        return foundPortMaskingGroupInstanceName

    def _delete_masking_view(
            self, conn, controllerConfigService, maskingViewName,
            maskingViewInstanceName):
        """Delete a masking view.

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param maskingViewName: maskingview name (String)
        :param maskingViewInstanceName: the masking view instance name
        :raises: VolumeBackendAPIException
        """
        rc, job = conn.InvokeMethod('DeleteMaskingView',
                                    controllerConfigService,
                                    ProtocolController=maskingViewInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Modifying masking view : %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'groupName': maskingViewName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

    def get_masking_view_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Get the associated maskingview instance name.

        Given storage group instance name, get the associated masking
        view instance name.

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
            volumeInstance, volumeName, sgGroupName, extraSpecs):
        """Add a volume to an existing storage group.

        :param conn: connection to ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupInstanceName: storage group instance name
        :param volumeInstance: the volume instance
        :param volumeName: the name of the volume (String)
        :param sgGroupName: the name of the storage group (String)
        :param extraSpecs: additional info
        :returns: int -- rc the return code of the job
        :returns: dict -- the job dict
        """
        self.provision.add_members_to_masking_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstance.path, volumeName, extraSpecs)

        LOG.info(_LI(
            "Added volume: %(volumeName)s to existing storage group "
            "%(sgGroupName)s."),
            {'volumeName': volumeName,
             'sgGroupName': sgGroupName})

    def remove_device_from_default_storage_group(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, fastPolicyName, extraSpecs):
        """Remove the volume from the default storage group.

        Remove the volume from the default storage group for the FAST
        policy and return the default storage group instance name.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller config service
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param fastPolicyName: the fast policy name (String)
        :param extraSpecs: additional info
        :returns: instance name defaultStorageGroupInstanceName
        """
        failedRet = None
        defaultStorageGroupInstanceName = (
            self.fast.get_and_verify_default_storage_group(
                conn, controllerConfigService, volumeInstanceName,
                volumeName, fastPolicyName))

        if defaultStorageGroupInstanceName is None:
            LOG.warn(_LW(
                "Volume %(volumeName)s was not first part of the default "
                "storage group for the FAST Policy."),
                {'volumeName': volumeName})
            return failedRet

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)

        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "for fast before removing volume %(volumeName)s.",
            {'length': len(assocVolumeInstanceNames),
             'volumeName': volumeName})

        self.provision.remove_device_from_storage_group(
            conn, controllerConfigService, defaultStorageGroupInstanceName,
            volumeInstanceName, volumeName, extraSpecs)

        assocVolumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "There are %(length)lu associated with the default storage group "
            "for fast after removing volume %(volumeName)s.",
            {'length': len(assocVolumeInstanceNames),
             'volumeName': volumeName})

        # Required for unit tests.
        emptyStorageGroupInstanceName = (
            self._wrap_get_storage_group_from_volume(conn, volumeInstanceName))

        if emptyStorageGroupInstanceName is not None:
            LOG.error(_LE(
                "Failed to remove %(volumeName)s from the default storage "
                "group for the FAST Policy."),
                {'volumeName': volumeName})
            return failedRet

        return defaultStorageGroupInstanceName

    def _wrap_get_storage_group_from_volume(self, conn, volumeInstanceName):
        """Wrapper for get_storage_group_from_volume.

        Needed for override in tests.

        :param conn: the connection to the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: emptyStorageGroupInstanceName
        """

        return self.utils.get_storage_group_from_volume(
            conn, volumeInstanceName)

    def get_devices_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Get the associated volume Instance names.

        Given the storage group instance name get the associated volume
        Instance names.

        :param conn: connection the the ecom server
        :param storageGroupInstanceName: the storage group instance name
        :returns: list -- volumeInstanceNames list of volume instance names
        """
        volumeInstanceNames = conn.AssociatorNames(
            storageGroupInstanceName,
            ResultClass='EMC_StorageVolume')

        return volumeInstanceNames

    def get_associated_masking_groups_from_device(
            self, conn, volumeInstanceName):
        """Get the associated storage groups from the volume Instance name.

        Given the volume instance name get the associated storage group
        instance names.

        :param conn: connection the the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: list -- list of storage group instance names
        """
        maskingGroupInstanceNames = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='CIM_DeviceMaskingGroup',
            AssocClass='CIM_OrderedMemberOfCollection')
        if len(maskingGroupInstanceNames) > 0:
            return maskingGroupInstanceNames
        else:
            LOG.info(_LI("Volume %(volumeName)s not in any storage group."),
                     {'volumeName': volumeInstanceName})
            return None

    def remove_and_reset_members(
            self, conn, controllerConfigService, volumeInstance,
            volumeName, extraSpecs, connector=None, noReset=None):
        """Part of unmap device or rollback.

        Removes volume from the Device Masking Group that belongs to a
        Masking View. Check if fast policy is in the extra specs, if it isn't
        we do not need to do any thing for FAST. Assume that
        isTieringPolicySupported is False unless the FAST policy is in
        the extra specs and tiering is enabled on the array.

        :param conn: connection the the ecom server
        :param controllerConfigService: the controller configuration service
        :param volumeInstance: the volume Instance
        :param volumeName: the volume name
        :param extraSpecs: additional info
        :param connector: optional
        :param noReset: optional, if none, then reset
        :returns: storageGroupInstanceName
        """
        fastPolicyName = extraSpecs.get(FASTPOLICY, None)
        isV3 = extraSpecs[ISV3]
        storageGroupInstanceName = None
        if connector is not None:
            storageGroupInstanceName = self._get_sg_associated_with_connector(
                conn, controllerConfigService, volumeInstance.path,
                volumeName, connector)
            if storageGroupInstanceName is None:
                return None
        else:  # Connector is None in V3 volume deletion case.
            storageGroupInstanceNames = (
                self.get_associated_masking_groups_from_device(
                    conn, volumeInstance.path))
            if storageGroupInstanceNames:
                storageGroupInstanceName = storageGroupInstanceNames[0]
            else:
                return None
        instance = conn.GetInstance(storageGroupInstanceName, LocalOnly=False)
        storageGroupName = instance['ElementName']

        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, storageGroupInstanceName)
        storageSystemInstanceName = self.utils.find_storage_system(
            conn, controllerConfigService)

        numVolInMaskingView = len(volumeInstanceNames)
        LOG.debug(
            "There are %(numVol)d volumes in the storage group "
            "%(maskingGroup)s.",
            {'numVol': numVolInMaskingView,
             'maskingGroup': storageGroupInstanceName})

        if not isV3:
            isTieringPolicySupported, __ = (
                self._get_tiering_info(conn, storageSystemInstanceName,
                                       fastPolicyName))

        if numVolInMaskingView == 1:
            # Last volume in the storage group.
            LOG.warn(_LW("Only one volume remains in storage group "
                     "%(sgname)s. Driver will attempt cleanup."),
                     {'sgname': storageGroupName})
            mvInstanceName = self.get_masking_view_from_storage_group(
                conn, storageGroupInstanceName)
            if mvInstanceName is None:
                LOG.warn(_LW("Unable to get masking view %(maskingView)s "
                         "from storage group."),
                         {'maskingView': mvInstanceName})
            else:
                maskingViewInstance = conn.GetInstance(
                    mvInstanceName, LocalOnly=False)
                maskingViewName = maskingViewInstance['ElementName']

            maskingViewInstance = conn.GetInstance(
                mvInstanceName, LocalOnly=False)
            maskingViewName = maskingViewInstance['ElementName']

            @lockutils.synchronized(maskingViewName,
                                    "emc-mv-", True)
            def do_delete_mv_and_sg():
                return self._delete_mv_and_sg(
                    conn, controllerConfigService, mvInstanceName,
                    maskingViewName, storageGroupInstanceName,
                    storageGroupName, volumeInstance, volumeName, extraSpecs)
            do_delete_mv_and_sg()
        else:
            # Not the last volume so remove it from storage group in
            # the masking view.
            LOG.debug("Start: number of volumes in masking storage group: "
                      "%(numVol)d", {'numVol': len(volumeInstanceNames)})
            self.provision.remove_device_from_storage_group(
                conn, controllerConfigService, storageGroupInstanceName,
                volumeInstance.path, volumeName, extraSpecs)

            LOG.debug(
                "RemoveMembers for volume %(volumeName)s completed "
                "successfully.", {'volumeName': volumeName})

            # Add it back to the default storage group.
            if isV3:
                self._return_volume_to_default_storage_group_v3(
                    conn, controllerConfigService, storageGroupName,
                    volumeInstance, volumeName, storageSystemInstanceName,
                    extraSpecs)
            else:
                # V2 if FAST POLICY enabled, move the volume to the default SG.
                if fastPolicyName is not None and isTieringPolicySupported:
                    self._cleanup_tiering(
                        conn, controllerConfigService, fastPolicyName,
                        volumeInstance, volumeName, extraSpecs)

            volumeInstanceNames = self.get_devices_from_storage_group(
                conn, storageGroupInstanceName)
            LOG.debug(
                "End: number of volumes in masking storage group: %(numVol)d.",
                {'numVol': len(volumeInstanceNames)})

        return storageGroupInstanceName

    def _delete_mv_and_sg(self, conn, controllerConfigService, mvInstanceName,
                          maskingViewName, storageGroupInstanceName,
                          storageGroupName, volumeInstance, volumeName,
                          extraSpecs):
        """Delete the Masking view and the Storage Group.

        Also does necessary cleanup like removing the policy from the
        storage group for V2 and returning the volume to the default
        storage group.

        :param conn: connection the the ecom server
        :param controllerConfigService: the controller configuration service
        :param mvInstanceName: masking view instance name
        :param maskingViewName: masking view name
        :param storageGroupInstanceName: storage group instance name
        :param maskingViewName: masking view name
        :param volumeInstance: the volume Instance
        :param volumeName: the volume name
        :param extraSpecs: extra specs
        """
        isV3 = extraSpecs[ISV3]
        fastPolicyName = extraSpecs.get(FASTPOLICY, None)

        storageSystemInstanceName = self.utils.find_storage_system(
            conn, controllerConfigService)

        self._last_volume_delete_masking_view(
            conn, controllerConfigService, mvInstanceName,
            maskingViewName)
        if not isV3:
            isTieringPolicySupported, tierPolicyServiceInstanceName = (
                self._get_tiering_info(conn, storageSystemInstanceName,
                                       fastPolicyName))
            self._get_and_remove_rule_association(
                conn, fastPolicyName,
                isTieringPolicySupported,
                tierPolicyServiceInstanceName,
                storageSystemInstanceName['Name'],
                storageGroupInstanceName, extraSpecs)
            # Remove the last volume and delete the storage group.
            self._remove_last_vol_and_delete_sg(
                conn, controllerConfigService, storageGroupInstanceName,
                storageGroupName, volumeInstance.path, volumeName,
                extraSpecs)

        # Add it back to the default storage group.
        if isV3:
            self._return_volume_to_default_storage_group_v3(
                conn, controllerConfigService, storageGroupName,
                volumeInstance, volumeName, storageSystemInstanceName,
                extraSpecs)
        else:
            # V2 if FAST POLICY enabled, move the volume to the default
            # SG.
            if fastPolicyName is not None and isTieringPolicySupported:
                self._cleanup_tiering(
                    conn, controllerConfigService, fastPolicyName,
                    volumeInstance, volumeName, extraSpecs)

    def _get_sg_associated_with_connector(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, connector):
        """Get storage group associated with connector.

        If the connector gets passed then extra logic required to
        get storage group.

        :param conn: the ecom connection
        :param controllerConfigService: storage system instance name
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param connector: the connector object
        :returns: storageGroupInstanceName(can be None)
        """
        return self._get_sg_or_mv_associated_with_initiator(
            conn, controllerConfigService, volumeInstanceName,
            volumeName, connector, True)

    def _get_tiering_info(
            self, conn, storageSystemInstanceName, fastPolicyName):
        """Get tiering specifics.

        :param conn: the ecom connection
        :param storageSystemInstanceName: storage system instance name
        :param fastPolicyName:
        :returns: boolean -- isTieringPolicySupported
        :returns: tierPolicyServiceInstanceName
        """
        isTieringPolicySupported = False
        tierPolicyServiceInstanceName = None
        if fastPolicyName is not None:
            tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
                conn, storageSystemInstanceName)

            isTieringPolicySupported = self.fast.is_tiering_policy_enabled(
                conn, tierPolicyServiceInstanceName)
            LOG.debug(
                "FAST policy enabled on %(storageSystem)s: %(isSupported)s",
                {'storageSystem': storageSystemInstanceName,
                 'isSupported': isTieringPolicySupported})

        return isTieringPolicySupported, tierPolicyServiceInstanceName

    def _last_volume_delete_masking_view(
            self, conn, controllerConfigService, mvInstanceName,
            maskingViewName):
        """Delete the masking view.

        Delete the masking view if the volume is the last one in the
        storage group.

        :param conn: the ecom connection
        :param controllerConfigService: controller config service
        :param mvInstanceName: masking view instance name
        :param maskingViewName: masking view name
        """
        LOG.debug(
            "Last volume in the storage group, deleting masking view "
            "%(maskingViewName)s.",
            {'maskingViewName': maskingViewName})
        self._delete_masking_view(
            conn, controllerConfigService, maskingViewName,
            mvInstanceName)

        mvInstance = self.utils.get_existing_instance(
            conn, mvInstanceName)
        if mvInstance:
            exceptionMessage = (_(
                "Masking view %(maskingViewName)s "
                "was not deleted successfully") %
                {'maskingViewName': maskingViewName})

            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        else:
            LOG.debug("Masking view %(maskingViewName)s "
                      "successfully deleted.",
                      {'maskingViewName': maskingViewName})

    def _get_and_remove_rule_association(
            self, conn, fastPolicyName, isTieringPolicySupported,
            tierPolicyServiceInstanceName, storageSystemName,
            storageGroupInstanceName, extraSpecs):
        """Remove the storage group from the policy rule.

        :param conn: the ecom connection
        :param fastPolicyName: the fast policy name
        :param isTieringPolicySupported: boolean
        :param tierPolicyServiceInstanceName: the tier policy instance name
        :param storageSystemName: storage system name
        :param storageGroupInstanceName: the storage group instance name
        :param extraSpecs: additional info
        """
        # Disassociate storage group from FAST policy.
        if fastPolicyName is not None and isTieringPolicySupported is True:
            tierPolicyInstanceName = self.fast.get_tier_policy_by_name(
                conn, storageSystemName, fastPolicyName)

            LOG.info(_LI(
                "Policy: %(policy)s, policy service:%(service)s, "
                "masking group: %(maskingGroup)s."),
                {'policy': tierPolicyInstanceName,
                 'service': tierPolicyServiceInstanceName,
                 'maskingGroup': storageGroupInstanceName})

            self.fast.delete_storage_group_from_tier_policy_rule(
                conn, tierPolicyServiceInstanceName,
                storageGroupInstanceName, tierPolicyInstanceName, extraSpecs)

    def _return_volume_to_default_storage_group_v3(
            self, conn, controllerConfigService, storageGroupName,
            volumeInstance, volumeName, storageSystemInstanceName,
            extraSpecs):
        """Return volume to the default storage group in v3.

        :param conn: the ecom connection
        :param controllerConfigService: controller config service
        :param storageGroupName: storage group name
        :param volumeInstance: volumeInstance
        :param volumeName: the volume name
        :param storageSystemInstanceName: the storage system instance name
        :param extraSpecs: additional info
        :raises: VolumeBackendAPIException
        """
        # First strip the shortHostname from the storage group name.
        defaultStorageGroupName, shorthostName = (
            self.utils.strip_short_host_name(storageGroupName))

        # Check if host name exists which signifies detach operation.
        if shorthostName is not None:
            # Populate maskingViewDict and storageGroupInstanceName.
            maskingViewDict = {}
            maskingViewDict['sgGroupName'] = defaultStorageGroupName
            maskingViewDict['volumeInstance'] = volumeInstance
            maskingViewDict['volumeName'] = volumeName
            maskingViewDict['controllerConfigService'] = \
                controllerConfigService
            maskingViewDict['storageSystemName'] = \
                storageSystemInstanceName
            sgInstanceName = self.utils.find_storage_masking_group(
                conn, controllerConfigService, defaultStorageGroupName)
            if sgInstanceName is not None:
                errorMessage = (
                    self._check_adding_volume_to_storage_group(
                        conn, maskingViewDict,
                        sgInstanceName))
            else:
                errorMessage = (_(
                    "Storage group %(sgGroupName) "
                    "does not exist.")
                    % {'StorageGroup': defaultStorageGroupName})
                LOG.error(errorMessage)
                raise exception.VolumeBackendAPIException(
                    data=errorMessage)

    def _cleanup_tiering(
            self, conn, controllerConfigService, fastPolicyName,
            volumeInstance, volumeName, extraSpecs):
        """Clean up tiering.

        :param conn: the ecom connection
        :param controllerConfigService: the controller configuration service
        :param fastPolicyName: the fast policy name
        :param volumeInstance: volume instance
        :param volumeName: the volume name
        :param extraSpecs: additional info
        """
        defaultStorageGroupInstanceName = (
            self.fast.get_policy_default_storage_group(
                conn, controllerConfigService, fastPolicyName))
        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "Start: number of volumes in default storage group: %(numVol)d.",
            {'numVol': len(volumeInstanceNames)})
        defaultStorageGroupInstanceName = (
            self.fast.add_volume_to_default_storage_group_for_fast_policy(
                conn, controllerConfigService, volumeInstance, volumeName,
                fastPolicyName, extraSpecs))
        # Check default storage group number of volumes.
        volumeInstanceNames = self.get_devices_from_storage_group(
            conn, defaultStorageGroupInstanceName)
        LOG.debug(
            "End: number of volumes in default storage group: %(numVol)d.",
            {'numVol': len(volumeInstanceNames)})

    def get_target_wwns(self, conn, mvInstanceName):
        """Get the DA ports wwns.

        :param conn: the ecom connection
        :param mvInstanceName: masking view instance name
        :returns: list -- the list of target wwns for the masking view
        """
        targetWwns = []
        targetPortInstanceNames = conn.AssociatorNames(
            mvInstanceName,
            ResultClass='Symm_FCSCSIProtocolEndpoint')
        numberOfPorts = len(targetPortInstanceNames)
        if numberOfPorts <= 0:
            LOG.warn(_LW("No target ports found in "
                     "masking view %(maskingView)s."),
                     {'numPorts': len(targetPortInstanceNames),
                      'maskingView': mvInstanceName})
        for targetPortInstanceName in targetPortInstanceNames:
            targetWwns.append(targetPortInstanceName['Name'])
        return targetWwns

    def get_masking_view_by_volume(self, conn, volumeInstance, connector):
        """Given volume, retrieve the masking view instance name.

        :param conn: the ecom connection
        :param volumeInstance: the volume instance
        :param connector: the connector object
        :returns: masking view instance name
        """

        storageSystemName = volumeInstance['SystemName']
        controllerConfigService = (
            self.utils.find_controller_configuration_service(
                conn, storageSystemName))
        volumeName = volumeInstance['ElementName']
        mvInstanceName = (
            self._get_sg_or_mv_associated_with_initiator(
                conn, controllerConfigService, volumeInstance.path,
                volumeName, connector, False))
        return mvInstanceName

    def get_masking_views_by_port_group(self, conn, portGroupInstanceName):
        """Given port group, retrieve the masking view instance name.

        :param conn: the ecom connection
        :param portGroupInstanceName: the instance name of the port group
        :returns: masking view instance names
        """
        mvInstanceNames = conn.AssociatorNames(
            portGroupInstanceName, ResultClass='Symm_LunMaskingView')
        return mvInstanceNames

    def get_port_group_from_masking_view(self, conn, maskingViewInstanceName):
        """Get the port group in a masking view.

        :param conn: the ecom connection
        :param maskingViewInstanceName: masking view instance name
        :returns: portGroupInstanceName
        """
        portGroupInstanceNames = conn.AssociatorNames(
            maskingViewInstanceName, ResultClass='SE_TargetMaskingGroup')
        if len(portGroupInstanceNames) > 0:
            LOG.debug("Found port group %(pg)s in masking view %(mv)s.",
                      {'pg': portGroupInstanceNames[0],
                       'mv': maskingViewInstanceName})
            return portGroupInstanceNames[0]
        else:
            LOG.warn(_LW("No port group found in masking view %(mv)s."),
                     {'mv': maskingViewInstanceName})

    def get_initiator_group_from_masking_view(
            self, conn, maskingViewInstanceName):
        """Get initiator group in a masking view.

        :param conn: the ecom connection
        :param maskingViewInstanceName: masking view instance name
        :returns: initiatorGroupInstanceName or None if it is not found
        """
        initiatorGroupInstanceNames = conn.AssociatorNames(
            maskingViewInstanceName, ResultClass='SE_InitiatorMaskingGroup')
        if len(initiatorGroupInstanceNames) > 0:
            LOG.debug("Found initiator group %(pg)s in masking view %(mv)s.",
                      {'pg': initiatorGroupInstanceNames[0],
                       'mv': maskingViewInstanceName})
            return initiatorGroupInstanceNames[0]
        else:
            LOG.warn(_LW("No port group found in masking view %(mv)s."),
                     {'mv': maskingViewInstanceName})

    def _get_sg_or_mv_associated_with_initiator(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, connector, getSG=True):
        """Get storage group or masking view associated with connector.

        If the connector gets passed then extra logic required to
        get storage group.

        :param conn: the ecom connection
        :param controllerConfigService: storage system instance name
        :param volumeInstanceName: volume instance name
        :param volumeName: volume element name
        :param connector: the connector object
        :param getSG: True if to get storage group; otherwise get masking
        :returns: foundInstanceName(can be None)
        """
        foundInstanceName = None
        initiatorNames = self._find_initiator_names(conn, connector)
        igInstanceNameFromConnector = self._find_initiator_masking_group(
            conn, controllerConfigService, initiatorNames)
        # Device can be shared by multi-SGs in a multi-host attach case.
        storageGroupInstanceNames = (
            self.get_associated_masking_groups_from_device(
                conn, volumeInstanceName))
        LOG.debug("Found storage groups volume "
                  "%(volumeName)s is in: %(storageGroups)s",
                  {'volumeName': volumeName,
                   'storageGroups': storageGroupInstanceNames})
        if storageGroupInstanceNames:  # not empty
            # Get the SG by IGs.
            for sgInstanceName in storageGroupInstanceNames:
                # Get maskingview from storage group.
                mvInstanceName = self.get_masking_view_from_storage_group(
                    conn, sgInstanceName)
                LOG.debug("Found masking view associated with SG "
                          "%(storageGroup)s: %(maskingview)s",
                          {'maskingview': mvInstanceName,
                           'storageGroup': sgInstanceName})
                # Get initiator group from masking view.
                igInstanceName = (
                    self.get_initiator_group_from_masking_view(
                        conn, mvInstanceName))
                LOG.debug("Initiator Group in masking view %(ig)s: "
                          "IG associated with connector%(igFromConnector)s",
                          {'ig': igInstanceName,
                           'igFromConnector': igInstanceNameFromConnector})
                if igInstanceName == igInstanceNameFromConnector:
                    if getSG is True:
                        foundInstanceName = sgInstanceName
                        LOG.debug("Found the storage group associated with "
                                  "initiator %(initiator)s: %(storageGroup)s",
                                  {'initiator': initiatorNames,
                                   'storageGroup': foundInstanceName})
                    else:
                        foundInstanceName = mvInstanceName
                        LOG.debug("Found the masking view associated with "
                                  "initiator %(initiator)s: %(maskingview)s.",
                                  {'initiator': initiatorNames,
                                   'maskingview': foundInstanceName})

                    break
        return foundInstanceName

    def _remove_last_vol_and_delete_sg(self, conn, controllerConfigService,
                                       storageGroupInstanceName,
                                       storageGroupName, volumeInstanceName,
                                       volumeName, extraSpecs):
        """Remove the last volume and delete the storage group

        :param conn: the ecom connection
        :param controllerConfigService: controller config service
        :param storageGroupInstanceName: storage group instance name
        :param storageGroupName: storage group name
        :param volumeInstanceName: volume instance name
        :param volumeName: volume name
        :param extrSpecs: additional info
        """
        self.provision.remove_device_from_storage_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName, extraSpecs)

        LOG.debug(
            "Remove the last volume %(volumeName)s completed "
            "successfully.",
            {'volumeName': volumeName})

        # Delete storage group.
        self._delete_storage_group(conn, controllerConfigService,
                                   storageGroupInstanceName,
                                   storageGroupName)
        storageGroupInstance = self.utils.get_existing_instance(
            conn, storageGroupInstanceName)
        if storageGroupInstance:
            exceptionMessage = (_(
                "Storage group %(storageGroupName)s "
                "was not deleted successfully") %
                {'storageGroupName': storageGroupName})

            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        else:
            LOG.debug("Storage Group %(storageGroupName)s "
                      "successfully deleted.",
                      {'storageGroupName': storageGroupName})

    def _delete_storage_group(self, conn, controllerConfigService,
                              storageGroupInstanceName, storageGroupName):
        """Delete empty storage group

        :param conn: the ecom connection
        :param controllerConfigService: controller config service
        :param storageGroupInstanceName: storage group instance name
        :param storageGroupName: storage group name
        """
        rc, job = conn.InvokeMethod(
            'DeleteGroup',
            controllerConfigService,
            MaskingGroup=storageGroupInstanceName,
            Force=True)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Deleting Group: %(storageGroupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'storageGroupName': storageGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

    def _create_hardware_ids(
            self, conn, initiatorNames, storageSystemName):
        """Create hardwareIds for initiator(s).

        :param conn: the connection to the ecom server
        :param initiatorNames: the list of initiator names
        :param storageSystemName: the storage system name
        :returns: list -- foundHardwareIDsInstanceNames
        """
        foundHardwareIDsInstanceNames = []

        hardwareIdManagementService = (
            self.utils.find_storage_hardwareid_service(
                conn, storageSystemName))
        for initiatorName in initiatorNames:
            hardwareIdInstanceName = (
                self.utils.create_storage_hardwareId_instance_name(
                    conn, hardwareIdManagementService, initiatorName))
            LOG.debug(
                "Created hardwareId Instance: %(hardwareIdInstanceName)s.",
                {'hardwareIdInstanceName': hardwareIdInstanceName})
            foundHardwareIDsInstanceNames.append(hardwareIdInstanceName)

        return foundHardwareIDsInstanceNames
