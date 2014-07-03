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
from cinder.volume.drivers.emc import emc_vmax_utils

LOG = logging.getLogger(__name__)

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3

EMC_ROOT = 'root/emc'
THINPROVISIONINGCOMPOSITE = 32768
THINPROVISIONING = 5


class EMCVMAXProvision(object):
    """Provisioning Class for SMI-S based EMC volume drivers.

    This Provisioning class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl):
        self.protocol = prtcl
        self.utils = emc_vmax_utils.EMCVMAXUtils(prtcl)

    def delete_volume_from_pool(
            self, conn, storageConfigservice, volumeInstanceName, volumeName):
        """Given the volume instance remove it from the pool.

        :param conn: connection the the ecom server
        :param storageConfigservice: volume created from job
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param rc: return code
        """
        rc, job = conn.InvokeMethod(
            'EMCReturnToStoragePool', storageConfigservice,
            TheElements=[volumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Delete Volume: %(volumeName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'volumeName': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc

    def create_volume_from_pool(
            self, conn, storageConfigService, volumeName,
            poolInstanceName, volumeSize):
        """Create the volume in the specified pool.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service
        :param volumeName: the volume name (String)
        :param poolInstanceName: the pool instance name to create
                                 the dummy volume in
        :param volumeSize: volume size (String)
        :returns: volumeDict - the volume dict
        """
        rc, job = conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            storageConfigService, ElementName=volumeName,
            InPool=poolInstanceName,
            ElementType=self.utils.get_num(THINPROVISIONING, '16'),
            Size=self.utils.get_num(volumeSize, '64'),
            EMCBindElements=False)

        LOG.debug("Create Volume: %(volumename)s  Return code: %(rc)lu"
                  % {'volumename': volumeName,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Volume: %(volumeName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'volumeName': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        # Find the newly created volume
        volumeDict = self.get_volume_dict_from_job(conn, job['Job'])

        return volumeDict, rc

    def create_and_get_storage_group(self, conn, controllerConfigService,
                                     storageGroupName, volumeInstanceName):
        """Create a storage group and return it.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupName: the storage group name (String
        :param volumeInstanceName: the volume instance name
        :returns: foundStorageGroupInstanceName - instance name of the
                                                  default storage group
        """
        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=storageGroupName,
            Type=self.utils.get_num(STORAGEGROUPTYPE, '16'),
            Members=[volumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'groupName': storageGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        foundStorageGroupInstanceName = self._find_new_storage_group(
            conn, job, storageGroupName)

        return foundStorageGroupInstanceName

    def create_storage_group_no_members(
            self, conn, controllerConfigService, groupName):
        """Create a new storage group that has no members.

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param groupName: the proposed group name
        :returns: foundStorageGroupInstanceName - the instance Name of
                                                  the storage group
        """
        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=groupName,
            Type=self.utils.get_num(STORAGEGROUPTYPE, '16'),
            DeleteWhenBecomesUnassociated=False)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'groupName': groupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        foundStorageGroupInstanceName = self._find_new_storage_group(
            conn, job, groupName)

        return foundStorageGroupInstanceName

    def _find_new_storage_group(
            self, conn, maskingGroupDict, storageGroupName):
        """After creating an new storage group find it and return it.

        :param conn: connection the ecom server
        :param maskingGroupDict: the maskingGroupDict dict
        :param storageGroupName: storage group name (String)
        :returns: maskingGroupDict['MaskingGroup']
        """
        foundStorageGroupInstanceName = None
        if 'MaskingGroup' in maskingGroupDict:
            foundStorageGroupInstanceName = maskingGroupDict['MaskingGroup']

        return foundStorageGroupInstanceName

    def get_volume_dict_from_job(self, conn, jobInstance):
        """Given the jobInstance determine the volume Instance.

        :param conn: the ecom connection
        :param jobInstance: the instance of a job
        :returns: volumeDict - an instance of a volume
        """
        associators = conn.Associators(
            jobInstance,
            ResultClass='EMC_StorageVolume')
        volpath = associators[0].path
        volumeDict = {}
        volumeDict['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        volumeDict['keybindings'] = keys

        return volumeDict

    def remove_device_from_storage_group(
            self, conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName):
        """Remove a volume from a storage group.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupInstanceName: the instance name of the storage group
        :param volumeInstanceName: the instance name of the volume
        :param volumeName: the volume name (String)
        :returns: rc - the return code of the job
        """
        rc, jobDict = conn.InvokeMethod('RemoveMembers',
                                        controllerConfigService,
                                        MaskingGroup=storageGroupInstanceName,
                                        Members=[volumeInstanceName])
        if rc != 0L:
            rc, errorDesc = self.utils.wait_for_job_complete(conn, jobDict)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error removing volume %(vol)s. %(error)s")
                    % {'vol': volumeName, 'error': errorDesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc

    def add_members_to_masking_group(
            self, conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName):
        """Add a member to a masking group group.
        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupInstanceName: the instance name of the storage group
        :param volumeInstanceName: the instance name of the volume
        :param volumeName: the volume name (String)
        """
        rc, job = conn.InvokeMethod(
            'AddMembers', controllerConfigService,
            MaskingGroup=storageGroupInstanceName,
            Members=[volumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error mapping volume %(vol)s. %(error)s")
                    % {'vol': volumeName, 'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

    def unbind_volume_from_storage_pool(
            self, conn, storageConfigService, poolInstanceName,
            volumeInstanceName, volumeName):
        """Unbind a volume from a pool and return the unbound volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service
                                     instance name
        :param poolInstanceName: the pool instance name
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name
        :returns: unboundVolumeInstance - the unbound volume instance
        """
        rc, job = conn.InvokeMethod(
            'EMCUnBindElement',
            storageConfigService,
            InPool=poolInstanceName,
            TheElement=volumeInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error unbinding volume %(vol)s from pool. %(error)s")
                    % {'vol': volumeName, 'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc, job

    def modify_composite_volume(
            self, conn, elementCompositionService, theVolumeInstanceName,
            inVolumeInstanceName):

        """Given a composite volume add a storage volume to it.

        :param conn: the connection to the ecom
        :param elementCompositionService: the element composition service
        :param theVolumeInstanceName: the existing composite volume
        :param inVolumeInstanceName: the volume you wish to add to the
                                     composite volume
        :returns: rc - return code
        :returns: job - job
        """
        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement',
            elementCompositionService,
            TheElement=theVolumeInstanceName,
            InElements=[inVolumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error adding volume to composite volume. "
                    "Error is: %(error)s")
                    % {'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc, job

    def create_composite_volume(
            self, conn, elementCompositionService, volumeSize, volumeName,
            poolInstanceName, compositeType, numMembers):
        """Create a new volume using the auto meta feature.

        :param conn: the connection the the ecom server
        :param elementCompositionService: the element composition service
        :param volumeSize: the size of the volume
        :param volumeName: user friendly name
        :param poolInstanceName: the pool to bind the composite volume to
        :param compositeType: the proposed composite type of the volume
                              e.g striped/concatenated
        :param numMembers: the number of meta members to make up the composite.
                           If it is 1 then a non composite is created
        :returns: rc
        :returns: errordesc
        """
        newMembers = 2

        LOG.debug(
            "Parameters for CreateOrModifyCompositeElement: "
            "elementCompositionService: %(elementCompositionService)s  "
            "provisioning: %(provisioning)lu "
            "volumeSize: %(volumeSize)s "
            "newMembers: %(newMembers)lu "
            "poolInstanceName: %(poolInstanceName)s "
            "compositeType: %(compositeType)lu "
            "numMembers: %(numMembers)s "
            % {'elementCompositionService': elementCompositionService,
               'provisioning': THINPROVISIONINGCOMPOSITE,
               'volumeSize': volumeSize,
               'newMembers': newMembers,
               'poolInstanceName': poolInstanceName,
               'compositeType': compositeType,
               'numMembers': numMembers})

        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement', elementCompositionService,
            ElementType=self.utils.get_num(THINPROVISIONINGCOMPOSITE, '16'),
            Size=self.utils.get_num(volumeSize, '64'),
            ElementSource=self.utils.get_num(newMembers, '16'),
            EMCInPools=[poolInstanceName],
            CompositeType=self.utils.get_num(compositeType, '16'),
            EMCNumberOfMembers=self.utils.get_num(numMembers, '32'))

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Volume: %(volumename)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'volumename': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        # Find the newly created volume
        volumeDict = self.get_volume_dict_from_job(conn, job['Job'])

        return volumeDict, rc

    def create_new_composite_volume(
            self, conn, elementCompositionService, compositeHeadInstanceName,
            compositeMemberInstanceName, compositeType):
        """Creates a new composite volume.

        Given a bound composite head and an unbound composite member
        create a new composite volume.

        :param conn: the connection the the ecom server
        :param elementCompositionService: the element composition service
        :param compositeHeadInstanceName: the composite head. This can be bound
        :param compositeMemberInstanceName: the composite member.
                                            This must be unbound
        :param compositeType: the composite type e.g striped or concatenated
        :returns: rc - return code
        :returns: errordesc - descriptions of the error
        """
        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement', elementCompositionService,
            ElementType=self.utils.get_num('2', '16'),
            InElements=(
                [compositeHeadInstanceName, compositeMemberInstanceName]),
            CompositeType=self.utils.get_num(compositeType, '16'))

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Creating new composite Volume Return code: %(rc)lu."
                    "Error: %(error)s")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc, job

    def _migrate_volume(
            self, conn, storageRelocationServiceInstanceName,
            volumeInstanceName, targetPoolInstanceName):
        """Migrate a volume to another pool.

        :param conn: the connection to the ecom server
        :param storageRelocationServiceInstanceName: the storage relocation
                                                     service
        :param volumeInstanceName: the volume to be migrated
        :param targetPoolInstanceName: the target pool to migrate the volume to
        :returns: rc - return code
        """
        rc, job = conn.InvokeMethod(
            'RelocateStorageVolumesToStoragePool',
            storageRelocationServiceInstanceName,
            TheElements=[volumeInstanceName],
            TargetPool=targetPoolInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Migrating volume from one pool to another. "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc

    def migrate_volume_to_storage_pool(
            self, conn, storageRelocationServiceInstanceName,
            volumeInstanceName, targetPoolInstanceName):
        """Given the storage system name, get the storage relocation service.

        :param conn: the connection to the ecom server
        :param storageRelocationServiceInstanceName: the storage relocation
                                                     service
        :param volumeInstanceName: the volume to be migrated
        :param targetPoolInstanceName: the target pool to migrate the
                                       volume to.
        :returns: rc
        """
        LOG.debug(
            "Volume instance name is %(volumeInstanceName)s. "
            "Pool instance name is : %(targetPoolInstanceName)s. "
            % {'volumeInstanceName': volumeInstanceName,
               'targetPoolInstanceName': targetPoolInstanceName})
        rc = -1
        try:
            rc = self._migrate_volume(
                conn, storageRelocationServiceInstanceName,
                volumeInstanceName, targetPoolInstanceName)
        except Exception as ex:
            if 'source of a migration session' in six.text_type(ex):
                try:
                    rc = self._terminate_migrate_session(
                        conn, volumeInstanceName)
                except Exception as ex:
                    LOG.error(_("Exception: %s") % six.text_type(ex))
                    exceptionMessage = (_(
                        "Failed to terminate migrate session"))
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)
                try:
                    rc = self._migrate_volume(
                        conn, storageRelocationServiceInstanceName,
                        volumeInstanceName, targetPoolInstanceName)
                except Exception as ex:
                    LOG.error(_("Exception: %s") % six.text_type(ex))
                    exceptionMessage = (_(
                        "Failed to migrate volume for the second time"))
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)

            else:
                LOG.error(_("Exception: %s") % six.text_type(ex))
                exceptionMessage = (_(
                    "Failed to migrate volume for the first time"))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc

    def _terminate_migrate_session(self, conn, volumeInstanceName):
        """Given the volume instance terminate a migrate session.

        :param conn: the connection to the ecom server
        :param volumeInstanceName: the volume to be migrated
        :returns: rc
        """
        rc, job = conn.InvokeMethod(
            'RequestStateChange', volumeInstanceName,
            RequestedState=self.utils.get_num(32769, '16'))
        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Terminating migrate session. "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc

    def create_element_replica(
            self, conn, repServiceInstanceName, cloneName,
            sourceName, sourceInstance):
        """Make SMI-S call to create replica for source element.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param cloneName: replica name
        :param sourceName: source volume name
        :param sourceInstance: source volume instance
        :returns: rc - return code
        :returns: job - job object of the replica creation operation
        """
        rc, job = conn.InvokeMethod(
            'CreateElementReplica', repServiceInstanceName,
            ElementName=cloneName,
            SyncType=self.utils.get_num(8, '16'),
            SourceElement=sourceInstance.path)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Cloned Volume: "
                    "Volume: %(cloneName)s  Source Volume:"
                    "%(sourceName)s.  Return code: %(rc)lu. "
                    "Error: %(error)s")
                    % {'cloneName': cloneName,
                       'sourceName': sourceName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc, job

    def delete_clone_relationship(
            self, conn, repServiceInstanceName, syncInstanceName,
            cloneName, sourceName):
        """Deletes the relationship between the clone and source volume.

        Makes an SMI-S call to break clone relationship between the clone
        volume and the source

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
                                 SE_StorageSynchronized_SV_SV object
        :param cloneName: replica name
        :param sourceName: source volume name
        :param sourceInstance: source volume instance
        :returns: rc - return code
        :returns: job - job object of the replica creation operation
        """

        '''
        8/Detach - Delete the synchronization between two storage objects.
        Treat the objects as independent after the synchronization is deleted.
        '''
        rc, job = conn.InvokeMethod(
            'ModifyReplicaSynchronization', repServiceInstanceName,
            Operation=self.utils.get_num(8, '16'),
            Synchronization=syncInstanceName)

        LOG.debug("Break clone relationship: Volume: %(cloneName)s  "
                  "Source Volume: %(sourceName)s  Return code: %(rc)lu"
                  % {'cloneName': cloneName,
                     'sourceName': sourceName,
                     'rc': rc})

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error break clone relationship: "
                    "Clone Volume: %(cloneName)s  "
                    "Source Volume: %(sourceName)s.  "
                    "Return code: %(rc)lu.  Error: %(error)s")
                    % {'cloneName': cloneName,
                       'sourceName': sourceName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        return rc, job

    def get_target_endpoints(self, conn, storageHardwareService, hardwareId):
        """Given the hardwareId get the

        :param conn: the connection to the ecom server
        :param storageHardwareService: the storage HardwareId Service
        :param hardwareId: the hardware Id
        :returns: rc
        :returns: targetendpoints
        """
        rc, targetEndpoints = conn.InvokeMethod(
            'EMCGetTargetEndpoints', storageHardwareService,
            HardwareId=hardwareId)

        if rc != 0L:
            exceptionMessage = (_("Error finding Target WWNs."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return rc, targetEndpoints
