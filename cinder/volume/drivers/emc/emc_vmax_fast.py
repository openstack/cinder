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

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume.drivers.emc import emc_vmax_provision
from cinder.volume.drivers.emc import emc_vmax_utils

LOG = logging.getLogger(__name__)

DEFAULT_SG_PREFIX = 'OS_default_'
DEFAULT_SG_POSTFIX = '_SG'


class EMCVMAXFast(object):
    """FAST Class for SMI-S based EMC volume drivers.

    This FAST class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl):
        self.protocol = prtcl
        self.utils = emc_vmax_utils.EMCVMAXUtils(prtcl)
        self.provision = emc_vmax_provision.EMCVMAXProvision(prtcl)

    def _check_if_fast_supported(self, conn, storageSystemInstanceName):
        """Check to see if fast is supported on the array.

        :param conn: the ecom connection
        :param storageSystemInstanceName: the storage system Instance name
        :returns: boolean -- isTieringPolicySupported
        """

        tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
            conn, storageSystemInstanceName)
        isTieringPolicySupported = self.is_tiering_policy_enabled(
            conn, tierPolicyServiceInstanceName)
        if isTieringPolicySupported is None:
            LOG.error(_LE("Cannot determine whether "
                          "Tiering Policy is supported on this array."))

        if isTieringPolicySupported is False:
            LOG.error(_LE("Tiering Policy is not "
                          "supported on this array."))
        return isTieringPolicySupported

    def is_tiering_policy_enabled(self, conn, tierPolicyServiceInstanceName):
        """Checks to see if tiering policy is supported.

        We will only check if there is a fast policy specified in
        the config file.

        :param conn: the connection information to the ecom server
        :param tierPolicyServiceInstanceName: the tier policy service
            instance name
        :returns: boolean -- foundIsSupportsTieringPolicies
        """
        foundIsSupportsTieringPolicies = None
        tierPolicyCapabilityInstanceNames = conn.AssociatorNames(
            tierPolicyServiceInstanceName,
            ResultClass='CIM_TierPolicyServiceCapabilities',
            AssocClass='CIM_ElementCapabilities')

        tierPolicyCapabilityInstanceName = tierPolicyCapabilityInstanceNames[0]
        tierPolicyCapabilityInstance = conn.GetInstance(
            tierPolicyCapabilityInstanceName, LocalOnly=False)
        propertiesList = (tierPolicyCapabilityInstance
                          .properties.items())
        for properties in propertiesList:
            if properties[0] == 'SupportsTieringPolicies':
                cimProperties = properties[1]
                foundIsSupportsTieringPolicies = cimProperties.value
                break

        if foundIsSupportsTieringPolicies is None:
            LOG.error(_LE("Cannot determine if Tiering Policies "
                          "are supported."))

        return foundIsSupportsTieringPolicies

    def get_and_verify_default_storage_group(
            self, conn, controllerConfigService, volumeInstanceName,
            volumeName, fastPolicyName):
        """Retrieves and verifies the default storage group for a volume.

        Given the volumeInstanceName get any associated storage group and
        check that it is the default storage group. The default storage group
        should have been already created. If not found error is logged.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller config service
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param fastPolicyName: the fast policy name (String)
        :returns: foundDefaultStorageGroupInstanceName, defaultSgName
        """
        foundDefaultStorageGroupInstanceName = None
        storageSystemInstanceName = self.utils.find_storage_system(
            conn, controllerConfigService)

        if not self._check_if_fast_supported(conn, storageSystemInstanceName):
            LOG.error(_LE(
                "FAST is not supported on this array."))
            raise

        defaultSgName = self.format_default_sg_string(fastPolicyName)
        assocStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(conn, volumeInstanceName,
                                                     defaultSgName))

        defaultStorageGroupInstanceName = (
            self.utils.find_storage_masking_group(conn,
                                                  controllerConfigService,
                                                  defaultSgName))
        if defaultStorageGroupInstanceName is None:
            LOG.error(_LE(
                "Unable to find default storage group "
                "for FAST policy : %(fastPolicyName)s."),
                {'fastPolicyName': fastPolicyName})
            raise

        if assocStorageGroupInstanceName == defaultStorageGroupInstanceName:
            foundDefaultStorageGroupInstanceName = (
                assocStorageGroupInstanceName)
        else:
            LOG.warning(_LW(
                "Volume: %(volumeName)s Does not belong "
                "to storage group %(defaultSgName)s."),
                {'volumeName': volumeName,
                 'defaultSgName': defaultSgName})
        return foundDefaultStorageGroupInstanceName, defaultSgName

    def format_default_sg_string(self, fastPolicyName):
        """Format the default storage group name

        :param fastPolicyName: the fast policy name
        :returns: defaultSgName
        """
        return ("%(prefix)s%(fastPolicyName)s%(postfix)s"
                % {'prefix': DEFAULT_SG_PREFIX,
                   'fastPolicyName': fastPolicyName,
                   'postfix': DEFAULT_SG_POSTFIX})

    def add_volume_to_default_storage_group_for_fast_policy(
            self, conn, controllerConfigService, volumeInstance,
            volumeName, fastPolicyName, extraSpecs):
        """Add a volume to the default storage group for FAST policy.

        The storage group must pre-exist.  Once added to the storage group,
        check the association to make sure it has been successfully added.

        :param conn: the ecom connection
        :param controllerConfigService: the controller configuration service
        :param volumeInstance: the volume instance
        :param volumeName: the volume name (String)
        :param fastPolicyName: the fast policy name (String)
        :param extraSpecs: additional info
        :returns: assocStorageGroupInstanceName - the storage group
            associated with the volume
        """
        failedRet = None
        defaultSgName = self.format_default_sg_string(fastPolicyName)
        storageGroupInstanceName = self.utils.find_storage_masking_group(
            conn, controllerConfigService, defaultSgName)
        if storageGroupInstanceName is None:
            LOG.error(_LE(
                "Unable to get default storage group %(defaultSgName)s."),
                {'defaultSgName': defaultSgName})
            return failedRet

        self.provision.add_members_to_masking_group(
            conn, controllerConfigService, storageGroupInstanceName,
            volumeInstance.path, volumeName, extraSpecs)
        # Check to see if the volume is in the storage group.
        assocStorageGroupInstanceName = (
            self.utils.get_storage_group_from_volume(conn,
                                                     volumeInstance.path,
                                                     defaultSgName))
        return assocStorageGroupInstanceName

    def _create_default_storage_group(self, conn, controllerConfigService,
                                      fastPolicyName, storageGroupName,
                                      volumeInstance, extraSpecs):
        """Create a first volume for the storage group.

        This is necessary because you cannot remove a volume if it is the
        last in the group. Create the default storage group for the FAST policy
        Associate the storage group with the tier policy rule.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param fastPolicyName: the fast policy name (String)
        :param storageGroupName: the storage group name (String)
        :param volumeInstance: the volume instance
        :param extraSpecs: additional info
        :returns: defaultstorageGroupInstanceName - instance name of the
            default storage group
        """
        failedRet = None
        firstVolumeInstance = self._create_volume_for_default_volume_group(
            conn, controllerConfigService, volumeInstance.path, extraSpecs)
        if firstVolumeInstance is None:
            LOG.error(_LE(
                "Failed to create a first volume for storage "
                "group : %(storageGroupName)s."),
                {'storageGroupName': storageGroupName})
            return failedRet

        defaultStorageGroupInstanceName = (
            self.provision.create_and_get_storage_group(
                conn, controllerConfigService, storageGroupName,
                firstVolumeInstance.path, extraSpecs))
        if defaultStorageGroupInstanceName is None:
            LOG.error(_LE(
                "Failed to create default storage group for "
                "FAST policy : %(fastPolicyName)s."),
                {'fastPolicyName': fastPolicyName})
            return failedRet

        storageSystemInstanceName = (
            self.utils.find_storage_system(conn, controllerConfigService))
        tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
            conn, storageSystemInstanceName)

        # Get the fast policy instance name.
        tierPolicyRuleInstanceName = self._get_service_level_tier_policy(
            conn, tierPolicyServiceInstanceName, fastPolicyName)
        if tierPolicyRuleInstanceName is None:
            LOG.error(_LE(
                "Unable to get policy rule for fast policy: "
                "%(fastPolicyName)s."),
                {'fastPolicyName': fastPolicyName})
            return failedRet

        # Now associate it with a FAST policy.
        self.add_storage_group_to_tier_policy_rule(
            conn, tierPolicyServiceInstanceName,
            defaultStorageGroupInstanceName, tierPolicyRuleInstanceName,
            storageGroupName, fastPolicyName, extraSpecs)

        return defaultStorageGroupInstanceName

    def _create_volume_for_default_volume_group(
            self, conn, controllerConfigService, volumeInstanceName,
            extraSpecs):
        """Creates a volume for the default storage group for a fast policy.

        Creates a small first volume for the default storage group for a
        fast policy.  This is necessary because you cannot remove
        the last volume from a storage group and this scenario is likely.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param volumeInstanceName: the volume instance name
        :param extraSpecs: additional info
        :returns: firstVolumeInstanceName - instance name of the first volume
                                            in the storage group
        """
        failedRet = None
        storageSystemName = self.utils.find_storage_system_name_from_service(
            controllerConfigService)
        storageConfigurationInstanceName = (
            self.utils.find_storage_configuration_service(
                conn, storageSystemName))

        poolInstanceName = self.utils.get_assoc_pool_from_volume(
            conn, volumeInstanceName)
        if poolInstanceName is None:
            LOG.error(_LE("Unable to get associated pool of volume."))
            return failedRet

        volumeName = 'vol1'
        volumeSize = '1'
        volumeDict, _rc = (
            self.provision.create_volume_from_pool(
                conn, storageConfigurationInstanceName, volumeName,
                poolInstanceName, volumeSize, extraSpecs))
        firstVolumeInstanceName = self.utils.find_volume_instance(
            conn, volumeDict, volumeName)
        return firstVolumeInstanceName

    def add_storage_group_to_tier_policy_rule(
            self, conn, tierPolicyServiceInstanceName,
            storageGroupInstanceName, tierPolicyRuleInstanceName,
            storageGroupName, fastPolicyName, extraSpecs):
        """Add the storage group to the tier policy rule.

        :param conn: the connection information to the ecom server
        :param tierPolicyServiceInstanceName: tier policy service
        :param storageGroupInstanceName: storage group instance name
        :param tierPolicyRuleInstanceName: tier policy instance name
        :param storageGroupName: the storage group name (String)
        :param fastPolicyName: the fast policy name (String)
        :param extraSpecs: additional info
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        # 5 is ("Add InElements to Policy").
        modificationType = '5'

        rc, job = conn.InvokeMethod(
            'ModifyStorageTierPolicyRule', tierPolicyServiceInstanceName,
            PolicyRule=tierPolicyRuleInstanceName,
            Operation=self.utils.get_num(modificationType, '16'),
            InElements=[storageGroupInstanceName])
        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0:
                exceptionMessage = (_(
                    "Error associating storage group : %(storageGroupName)s. "
                    "To fast Policy: %(fastPolicyName)s with error "
                    "description: %(errordesc)s.")
                    % {'storageGroupName': storageGroupName,
                       'fastPolicyName': fastPolicyName,
                       'errordesc': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc

    def _get_service_level_tier_policy(
            self, conn, tierPolicyServiceInstanceName, fastPolicyName):
        """Returns the existing tier policies for a storage system instance.

        Given the storage system instance name, get the existing tier
        policies on that array.

        :param conn: the connection information to the ecom server
        :param tierPolicyServiceInstanceName: the policy service
        :param fastPolicyName: the fast policy name e.g BRONZE1
        :returns: foundTierPolicyRuleInstanceName - the short name,
            everything after the :
        """
        foundTierPolicyRuleInstanceName = None

        tierPolicyRuleInstanceNames = self._get_existing_tier_policies(
            conn, tierPolicyServiceInstanceName)

        for tierPolicyRuleInstanceName in tierPolicyRuleInstanceNames:
            policyRuleName = tierPolicyRuleInstanceName['PolicyRuleName']
            if fastPolicyName == policyRuleName:
                foundTierPolicyRuleInstanceName = tierPolicyRuleInstanceName
                break

        return foundTierPolicyRuleInstanceName

    def _get_existing_tier_policies(self, conn, tierPolicyServiceInstanceName):
        """Given the tier policy service, get the existing tier policies.

        :param conn: the connection information to the ecom server
        :param tierPolicyServiceInstanceName: the tier policy service
            instance Name
        :returns: list -- the tier policy rule instance names
        """
        tierPolicyRuleInstanceNames = conn.AssociatorNames(
            tierPolicyServiceInstanceName, ResultClass='Symm_TierPolicyRule')

        return tierPolicyRuleInstanceNames

    def get_associated_tier_policy_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Given the tier policy instance name get the storage groups.

        :param conn: the connection information to the ecom server
        :param storageGroupInstanceName: the storage group instance name
        :returns: list -- the list of tier policy instance names
        """
        tierPolicyInstanceName = None

        tierPolicyInstanceNames = conn.AssociatorNames(
            storageGroupInstanceName,
            AssocClass='CIM_TierPolicySetAppliesToElement',
            ResultClass='CIM_TierPolicyRule')

        if (len(tierPolicyInstanceNames) > 0 and
                len(tierPolicyInstanceNames) < 2):
            tierPolicyInstanceName = tierPolicyInstanceNames[0]

        return tierPolicyInstanceName

    def get_associated_tier_from_tier_policy(
            self, conn, tierPolicyRuleInstanceName):
        """Given the tierPolicyInstanceName get the associated tiers.

        :param conn: the connection information to the ecom server
        :param tierPolicyRuleInstanceName: the tier policy rule instance name
        :returns: list -- a list of storage tier instance names
        """
        storageTierInstanceNames = conn.AssociatorNames(
            tierPolicyRuleInstanceName,
            AssocClass='CIM_AssociatedTierPolicy')

        if len(storageTierInstanceNames) == 0:
            storageTierInstanceNames = None
            LOG.warning(_LW(
                "Unable to get storage tiers from tier policy rule."))

        return storageTierInstanceNames

    def get_policy_default_storage_group(
            self, conn, controllerConfigService, policyName):
        """Returns the default storage group for a tier policy.

        Given the tier policy instance name get the associated default
        storage group.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: ControllerConfigurationService
            instance name
        :param policyName: string value
        :returns: storageGroupInstanceName - instance name of the default
            storage group
        """
        foundStorageMaskingGroupInstanceName = None
        storageMaskingGroupInstances = conn.Associators(
            controllerConfigService, ResultClass='CIM_DeviceMaskingGroup')

        for storageMaskingGroupInstance in storageMaskingGroupInstances:

            if ('_default_' in storageMaskingGroupInstance['ElementName'] and
                    policyName in storageMaskingGroupInstance['ElementName']):
                # Check that it has not been recently deleted.
                instance = self.utils.get_existing_instance(
                    conn, storageMaskingGroupInstance.path)
                if instance is None:
                    # Storage Group doesn't exist any more.
                    foundStorageMaskingGroupInstanceName = None
                else:
                    foundStorageMaskingGroupInstanceName = (
                        storageMaskingGroupInstance.path)

        return foundStorageMaskingGroupInstanceName

    def _get_associated_storage_groups_from_tier_policy(
            self, conn, tierPolicyInstanceName):
        """Given the tier policy instance name get the storage groups.

        :param conn: the connection information to the ecom server
        :param tierPolicyInstanceName: tier policy instance name
        :returns: list -- the list of storage instance names
        """
        managedElementInstanceNames = conn.AssociatorNames(
            tierPolicyInstanceName,
            AssocClass='CIM_TierPolicySetAppliesToElement',
            ResultClass='CIM_DeviceMaskingGroup')

        return managedElementInstanceNames

    def get_associated_pools_from_tier(
            self, conn, storageTierInstanceName):
        """Given the storage tier instance name get the storage pools.

        :param conn: the connection information to the ecom server
        :param storageTierInstanceName: the storage tier instance name
        :returns: list -- a list of storage tier instance names
        """
        storagePoolInstanceNames = conn.AssociatorNames(
            storageTierInstanceName,
            AssocClass='CIM_MemberOfCollection',
            ResultClass='CIM_StoragePool')

        return storagePoolInstanceNames

    def add_storage_group_and_verify_tier_policy_assoc(
            self, conn, controllerConfigService, storageGroupInstanceName,
            storageGroupName, fastPolicyName, extraSpecs):
        """Adds a storage group to a tier policy and verifies success.

        Add a storage group to a tier policy rule and verify that it was
        successful by getting the association.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller config service
        :param storageGroupInstanceName: the storage group instance name
        :param storageGroupName: the storage group name (String)
        :param fastPolicyName: the fast policy name (String)
        :param extraSpecs: additional info
        :returns: assocTierPolicyInstanceName
        """
        failedRet = None
        assocTierPolicyInstanceName = None
        storageSystemInstanceName = self.utils.find_storage_system(
            conn, controllerConfigService)
        tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
            conn, storageSystemInstanceName)
        # Get the fast policy instance name.
        tierPolicyRuleInstanceName = self._get_service_level_tier_policy(
            conn, tierPolicyServiceInstanceName, fastPolicyName)
        if tierPolicyRuleInstanceName is None:
            LOG.error(_LE(
                "Cannot find the fast policy %(fastPolicyName)s."),
                {'fastPolicyName': fastPolicyName})
            return failedRet
        else:
            LOG.debug(
                "Adding storage group %(storageGroupInstanceName)s to "
                "tier policy rule %(tierPolicyRuleInstanceName)s.",
                {'storageGroupInstanceName': storageGroupInstanceName,
                 'tierPolicyRuleInstanceName': tierPolicyRuleInstanceName})

            # Associate the new storage group with the existing fast policy.
            try:
                self.add_storage_group_to_tier_policy_rule(
                    conn, tierPolicyServiceInstanceName,
                    storageGroupInstanceName, tierPolicyRuleInstanceName,
                    storageGroupName, fastPolicyName, extraSpecs)
            except Exception:
                LOG.exception(_LE(
                    "Failed to add storage group %(storageGroupInstanceName)s "
                    "to tier policy rule %(tierPolicyRuleInstanceName)s."),
                    {'storageGroupInstanceName': storageGroupInstanceName,
                     'tierPolicyRuleInstanceName': tierPolicyRuleInstanceName})
                return failedRet

            # Check that the storage group has been associated with with the
            # tier policy rule.
            assocTierPolicyInstanceName = (
                self.get_associated_tier_policy_from_storage_group(
                    conn, storageGroupInstanceName))

            LOG.debug(
                "AssocTierPolicyInstanceName is "
                "%(assocTierPolicyInstanceName)s.",
                {'assocTierPolicyInstanceName': assocTierPolicyInstanceName})
        return assocTierPolicyInstanceName

    def get_associated_policy_from_storage_group(
            self, conn, storageGroupInstanceName):
        """Get the tier policy instance name for a storage group instance name.

        :param conn: the connection information to the ecom server
        :param storageGroupInstanceName: storage group instance name
        :returns: foundTierPolicyInstanceName - instance name of the
            tier policy object
        """
        foundTierPolicyInstanceName = None

        tierPolicyInstanceNames = conn.AssociatorNames(
            storageGroupInstanceName,
            ResultClass='Symm_TierPolicyRule',
            AssocClass='Symm_TierPolicySetAppliesToElement')

        if len(tierPolicyInstanceNames) > 0:
            foundTierPolicyInstanceName = tierPolicyInstanceNames[0]

        return foundTierPolicyInstanceName

    def delete_storage_group_from_tier_policy_rule(
            self, conn, tierPolicyServiceInstanceName,
            storageGroupInstanceName, tierPolicyRuleInstanceName,
            extraSpecs):
        """Disassociate the storage group from its tier policy rule.

        :param conn: connection the ecom server
        :param tierPolicyServiceInstanceName: instance name of the tier policy
            service
        :param storageGroupInstanceName: instance name of the storage group
        :param tierPolicyRuleInstanceName: instance name of the tier policy
            associated with the storage group
        :param extraSpecs: additional information
        """
        modificationType = '6'
        LOG.debug("Invoking ModifyStorageTierPolicyRule %s.",
                  tierPolicyRuleInstanceName)
        try:
            rc, job = conn.InvokeMethod(
                'ModifyStorageTierPolicyRule', tierPolicyServiceInstanceName,
                PolicyRule=tierPolicyRuleInstanceName,
                Operation=self.utils.get_num(modificationType, '16'),
                InElements=[storageGroupInstanceName])
            if rc != 0:
                rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                                 extraSpecs)
                if rc != 0:
                    LOG.error(_LE("Error disassociating storage group from "
                              "policy: %s."), errordesc)
                else:
                    LOG.debug("Disassociated storage group from policy.")
            else:
                LOG.debug("ModifyStorageTierPolicyRule completed.")
        except Exception as e:
            LOG.info(_LI("Storage group not associated with the "
                         "policy. Exception is %s."), e)

    def get_pool_associated_to_policy(
            self, conn, fastPolicyName, arraySN,
            storageConfigService, poolInstanceName):
        """Given a FAST policy check that the pool is linked to the policy.

        If it's associated return the pool instance, if not return None.
        First check if FAST is enabled on the array.

        :param conn: the ecom connection
        :param fastPolicyName: the fast policy name (String)
        :param arraySN: the array serial number (String)
        :param storageConfigService: the storage Config Service
        :param poolInstanceName: the pool instance we want to check for
            association with the fast storage tier
        :returns: foundPoolInstanceName
        """
        storageSystemInstanceName = self.utils.find_storage_system(
            conn, storageConfigService)

        if not self._check_if_fast_supported(conn, storageSystemInstanceName):
            errorMessage = (_(
                "FAST is not supported on this array."))
            LOG.error(errorMessage)
            exception.VolumeBackendAPIException(data=errorMessage)

        tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
            conn, storageSystemInstanceName)

        tierPolicyRuleInstanceName = self._get_service_level_tier_policy(
            conn, tierPolicyServiceInstanceName, fastPolicyName)
        # Get the associated storage tiers from the tier policy rule.
        storageTierInstanceNames = self.get_associated_tier_from_tier_policy(
            conn, tierPolicyRuleInstanceName)

        # For each gold storage tier get the associated pools.
        foundPoolInstanceName = None
        for storageTierInstanceName in storageTierInstanceNames:
            assocStoragePoolInstanceNames = (
                self.get_associated_pools_from_tier(conn,
                                                    storageTierInstanceName))
            for assocStoragePoolInstanceName in assocStoragePoolInstanceNames:
                if poolInstanceName == assocStoragePoolInstanceName:
                    foundPoolInstanceName = poolInstanceName
                    break
            if foundPoolInstanceName is not None:
                break

        return foundPoolInstanceName

    def is_tiering_policy_enabled_on_storage_system(
            self, conn, storageSystemInstanceName):
        """Checks if tiering policy in enabled on a storage system.

        True if FAST policy enabled on the given storage system;
        False otherwise.

        :param conn: the ecom connection
        :param storageSystemInstanceName: a storage system instance name
        :returns: boolean -- isTieringPolicySupported
        """
        try:
            tierPolicyServiceInstanceName = self.utils.get_tier_policy_service(
                conn, storageSystemInstanceName)
            isTieringPolicySupported = self.is_tiering_policy_enabled(
                conn, tierPolicyServiceInstanceName)
        except Exception as e:
            LOG.error(_LE("Exception: %s."), e)
            return False

        return isTieringPolicySupported

    def get_tier_policy_by_name(
            self, conn, arrayName, policyName):
        """Given the name of the policy, get the TierPolicyRule instance name.

        :param conn: the ecom connection
        :param arrayName: the array
        :param policyName: string -- the name of policy rule
        :returns: tier policy instance name. None if not found
        """
        tierPolicyInstanceNames = conn.EnumerateInstanceNames(
            'Symm_TierPolicyRule')
        for policy in tierPolicyInstanceNames:
            if (policyName == policy['PolicyRuleName'] and
                    arrayName in policy['SystemName']):
                return policy
        return None

    def get_capacities_associated_to_policy(self, conn, arrayName, policyName):
        """Gets the total and un-used capacities for all pools in a policy.

        Given the name of the policy, get the total capacity and un-used
        capacity in GB of all the storage pools associated with the policy.

        :param conn: the ecom connection
        :param arrayName: the array
        :param policyName: the name of policy rule, a string value
        :returns: int -- total capacity in GB of all pools associated with
            the policy
        :returns: int  -- (total capacity-EMCSubscribedCapacity) in GB of all
            pools associated with the policy
        """
        policyInstanceName = self.get_tier_policy_by_name(
            conn, arrayName, policyName)

        total_capacity_gb = 0
        allocated_capacity_gb = 0

        tierInstanceNames = self.get_associated_tier_from_tier_policy(
            conn, policyInstanceName)
        for tierInstanceName in tierInstanceNames:
            # Check that tier hasn't suddenly been deleted.
            instance = self.utils.get_existing_instance(conn, tierInstanceName)
            if instance is None:
                # Tier doesn't exist any more.
                break

            poolInstanceNames = self.get_associated_pools_from_tier(
                conn, tierInstanceName)
            for poolInstanceName in poolInstanceNames:
                # Check that pool hasn't suddenly been deleted.
                storagePoolInstance = self.utils.get_existing_instance(
                    conn, poolInstanceName)
                if storagePoolInstance is None:
                    # Pool doesn't exist any more.
                    break
                total_capacity_gb += self.utils.convert_bits_to_gbs(
                    storagePoolInstance['TotalManagedSpace'])
                allocated_capacity_gb += self.utils.convert_bits_to_gbs(
                    storagePoolInstance['EMCSubscribedCapacity'])
                LOG.debug(
                    "PolicyName:%(policyName)s, pool: %(poolInstanceName)s, "
                    "allocated_capacity_gb = %(allocated_capacity_gb)lu.",
                    {'policyName': policyName,
                     'poolInstanceName': poolInstanceName,
                     'allocated_capacity_gb': allocated_capacity_gb})

        free_capacity_gb = total_capacity_gb - allocated_capacity_gb
        return (total_capacity_gb, free_capacity_gb)

    def get_or_create_default_storage_group(
            self, conn, controllerConfigService, fastPolicyName,
            volumeInstance, extraSpecs):
        """Create or get a default storage group for FAST policy.

        :param conn: the ecom connection
        :param controllerConfigService: the controller configuration service
        :param fastPolicyName: the fast policy name (String)
        :param volumeInstance: the volume instance
        :param extraSpecs: additional info
        :returns: defaultStorageGroupInstanceName - the default storage group
                                                    instance name
        """
        defaultSgName = self.format_default_sg_string(fastPolicyName)
        defaultStorageGroupInstanceName = (
            self.utils.find_storage_masking_group(conn,
                                                  controllerConfigService,
                                                  defaultSgName))
        if defaultStorageGroupInstanceName is None:
            # Create it and associate it with the FAST policy in question.
            defaultStorageGroupInstanceName = (
                self._create_default_storage_group(conn,
                                                   controllerConfigService,
                                                   fastPolicyName,
                                                   defaultSgName,
                                                   volumeInstance,
                                                   extraSpecs))

        return defaultStorageGroupInstanceName

    def _get_associated_tier_policy_from_pool(self, conn, poolInstanceName):
        """Given the pool instance name get the associated FAST tier policy.

        :param conn: the connection information to the ecom server
        :param poolInstanceName: the pool instance name
        :returns: the FAST Policy name (if it exists)
        """
        fastPolicyName = None

        storageTierInstanceNames = conn.AssociatorNames(
            poolInstanceName,
            AssocClass='CIM_MemberOfCollection',
            ResultClass='CIM_StorageTier')

        if len(storageTierInstanceNames) > 0:
            tierPolicyInstanceNames = conn.AssociatorNames(
                storageTierInstanceNames[0],
                AssocClass='CIM_AssociatedTierPolicy')

            if len(tierPolicyInstanceNames) > 0:
                tierPolicyInstanceName = tierPolicyInstanceNames[0]
                fastPolicyName = tierPolicyInstanceName['PolicyRuleName']

        return fastPolicyName

    def is_volume_in_default_SG(self, conn, volumeInstanceName):
        """Check if the volume is already part of the default storage group.

        :param conn: the ecom connection
        :param volumeInstanceName: the volume instance
        :returns: boolean -- True if the volume is already in default
            storage group. False otherwise
        """
        sgInstanceNames = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='CIM_DeviceMaskingGroup')
        if len(sgInstanceNames) == 0:
            LOG.debug("volume  %(vol)s is not in default sg.",
                      {'vol': volumeInstanceName})
            return False
        else:
            for sgInstance in sgInstanceNames:
                if DEFAULT_SG_PREFIX in sgInstance['InstanceID']:
                    LOG.debug("volume  %(vol)s already in default sg.",
                              {'vol': volumeInstanceName})
                    return True
        return False
