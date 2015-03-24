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

import time

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LE
from cinder.volume.drivers.emc import emc_vmax_utils

LOG = logging.getLogger(__name__)

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3

EMC_ROOT = 'root/emc'
THINPROVISIONINGCOMPOSITE = 32768
THINPROVISIONING = 5


class EMCVMAXProvisionV3(object):
    """Provisioning Class for SMI-S based EMC volume drivers.

    This Provisioning class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl):
        self.protocol = prtcl
        self.utils = emc_vmax_utils.EMCVMAXUtils(prtcl)

    def delete_volume_from_pool(
            self, conn, storageConfigservice, volumeInstanceName, volumeName,
            extraSpecs):
        """Given the volume instance remove it from the pool.

        :param conn: connection the the ecom server
        :param storageConfigservice: volume created from job
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param extraSpecs: additional info
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        if isinstance(volumeInstanceName, list):
            theElements = volumeInstanceName
            volumeName = 'Bulk Delete'
        else:
            theElements = [volumeInstanceName]

        rc, job = conn.InvokeMethod(
            'ReturnElementsToStoragePool', storageConfigservice,
            TheElements=theElements)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Delete Volume: %(volumeName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumeName': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod ReturnElementsToStoragePool took: "
                  "%(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc

    def create_volume_from_sg(
            self, conn, storageConfigService, volumeName,
            sgInstanceName, volumeSize, extraSpecs):
        """Create the volume and associate it with a storage group.

        We use EMCCollections parameter to supply a Device Masking Group
        to contain a newly created storage volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service
        :param volumeName: the volume name (String)
        :param sgInstanceName: the storage group instance name
            associated with an SLO
        :param volumeSize: volume size (String)
        :param extraSpecs: additional info
        :returns: dict -- volumeDict - the volume dict
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            storageConfigService, ElementName=volumeName,
            EMCCollections=[sgInstanceName],
            ElementType=self.utils.get_num(THINPROVISIONING, '16'),
            Size=self.utils.get_num(volumeSize, '64'))

        LOG.debug("Create Volume: %(volumename)s. Return code: %(rc)lu.",
                  {'volumename': volumeName,
                   'rc': rc})

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Volume: %(volumeName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumeName': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateOrModifyElementFromStoragePool "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        # Find the newly created volume.
        volumeDict = self.get_volume_dict_from_job(conn, job['Job'])
        return volumeDict, rc

    def _find_new_storage_group(
            self, conn, maskingGroupDict, storageGroupName):
        """After creating an new storage group find it and return it.

        :param conn: connection to the ecom server
        :param maskingGroupDict: the maskingGroupDict dict
        :param storageGroupName: storage group name (String)
        :returns: maskingGroupDict['MaskingGroup'] or None
        """
        foundStorageGroupInstanceName = None
        if 'MaskingGroup' in maskingGroupDict:
            foundStorageGroupInstanceName = maskingGroupDict['MaskingGroup']

        return foundStorageGroupInstanceName

    def get_volume_dict_from_job(self, conn, jobInstance):
        """Given the jobInstance determine the volume Instance.

        :param conn: the ecom connection
        :param jobInstance: the instance of a job
        :returns: dict -- volumeDict - an instance of a volume
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

    def create_element_replica(
            self, conn, repServiceInstanceName,
            cloneName, syncType, sourceInstance, extraSpecs,
            targetInstance=None):
        """Make SMI-S call to create replica for source element.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: replication service
        :param cloneName: clone volume name
        :param syncType: 7=snapshot, 8=clone
        :param sourceInstance: source volume instance
        :param extraSpecs: additional info
        :param targetInstance: target volume instance. Defaults to None
        :returns: int -- rc - return code
        :returns: job - job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        if targetInstance is None:
            LOG.debug("Create targetless replica: %(clone)s "
                      "syncType: %(syncType)s  Source: %(source)s.",
                      {'clone': cloneName,
                       'syncType': syncType,
                       'source': sourceInstance.path})
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName, SyncType=syncType,
                SourceElement=sourceInstance.path)
        else:
            LOG.debug(
                "Create replica: %(clone)s syncType: %(syncType)s "
                "Source: %(source)s target: %(target)s.",
                {'clone': cloneName,
                 'syncType': syncType,
                 'source': sourceInstance.path,
                 'target': targetInstance.path})
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName, SyncType=syncType,
                SourceElement=sourceInstance.path,
                TargetElement=targetInstance.path)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Cloned Volume: %(cloneName)s "
                    "Return code: %(rc)lu. Error: %(error)s.")
                    % {'cloneName': cloneName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateElementReplica "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})
        return rc, job

    def break_replication_relationship(
            self, conn, repServiceInstanceName, syncInstanceName,
            operation, extraSpecs, force=False):
        """Deletes the relationship between the clone/snap and source volume.

        Makes an SMI-S call to break clone relationship between the clone
        volume and the source.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
            SE_StorageSynchronized_SV_SV object
        :param operation: operation code
        :param extraSpecs: additional info
        :param force: force to break replication relationship if True
        :returns: rc - return code
        :returns: job - job object of the replica creation operation
        """
        LOG.debug("Break replication relationship: %(sv)s "
                  "operation: %(operation)s.",
                  {'sv': syncInstanceName, 'operation': operation})

        return self._modify_replica_synchronization(
            conn, repServiceInstanceName, syncInstanceName, operation,
            extraSpecs, force)

    def create_storage_group_v3(self, conn, controllerConfigService,
                                groupName, srp, slo, workload, extraSpecs):
        """Create the volume in the specified pool.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param groupName: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param extraSpecs: additional info
        :returns: storageGroupInstanceName - storage group instance name
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateGroup',
            controllerConfigService,
            GroupName=groupName,
            Type=self.utils.get_num(4, '16'),
            EMCSRP=srp,
            EMCSLO=slo,
            EMCWorkload=workload)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                LOG.error(_LE(
                    "Error Create Group: %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s."),
                    {'groupName': groupName,
                     'rc': rc,
                     'error': errordesc})
                raise

        LOG.debug("InvokeMethod CreateGroup "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        foundStorageGroupInstanceName = self._find_new_storage_group(
            conn, job, groupName)

        return foundStorageGroupInstanceName

    def _get_storage_pool_capability(self, conn, poolInstanceName):
        """Get the pool capability.

        :param conn: the connection information to the ecom server
        :param poolInstanceName: the pool instance
        :returns: the storage pool capability instance. None if not found
        """
        storagePoolCapability = None

        associators = (
            conn.AssociatorNames(poolInstanceName,
                                 ResultClass='Symm_StoragePoolCapabilities'))

        if len(associators) > 0:
            storagePoolCapability = associators[0]

        return storagePoolCapability

    def _get_storage_pool_setting(
            self, conn, storagePoolCapability, slo, workload):
        """Get the pool setting for pool capability.

        :param conn: the connection information to the ecom server
        :param storagePoolCapability: the storage pool capability instance
        :param slo: the slo string e.g Bronze
        :param workload: the workload string e.g DSS_REP
        :returns: the storage pool setting instance
        """

        foundStoragePoolSetting = None
        storagePoolSettings = (
            conn.AssociatorNames(storagePoolCapability,
                                 ResultClass='CIM_storageSetting'))

        for storagePoolSetting in storagePoolSettings:
            settingInstanceID = storagePoolSetting['InstanceID']
            matchString = ("%(slo)s:%(workload)s"
                           % {'slo': slo,
                              'workload': workload})
            if matchString in settingInstanceID:
                foundStoragePoolSetting = storagePoolSetting
                break
        return foundStoragePoolSetting

    def _get_supported_size_range_for_SLO(
            self, conn, storageConfigService,
            srpPoolInstanceName, storagePoolSettingInstanceName, extraSpecs):
        """Gets available performance capacity per SLO.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service instance
        :param srpPoolInstanceName: the SRP storage pool instance
        :param storagePoolSettingInstanceName: the SLO type, e.g Bronze
        :param extraSpecs: additional info
        :returns: dict -- supportedSizeDict - the supported size dict
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, supportedSizeDict = conn.InvokeMethod(
            'GetSupportedSizeRange',
            srpPoolInstanceName,
            ElementType=self.utils.get_num(3, '16'),
            Goal=storagePoolSettingInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(
                conn, supportedSizeDict, extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Cannot get supported size range for %(sps)s "
                    "Return code: %(rc)lu. Error: %(error)s.")
                    % {'sps': storagePoolSettingInstanceName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod GetSupportedSizeRange "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return supportedSizeDict

    def get_volume_range(
            self, conn, storageConfigService, poolInstanceName, slo, workload,
            extraSpecs):
        """Get upper and lower range for volume for slo/workload combination.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage config service
        :param poolInstanceName: the pool instance
        :param slo: slo string e.g Bronze
        :param workload: workload string e.g DSS
        :param extraSpecs: additional info
        :returns: maximumVolumeSize - the maximum volume size supported
        :returns: minimumVolumeSize - the minimum volume size supported
        """
        maximumVolumeSize = None
        minimumVolumeSize = None

        storagePoolCapabilityInstanceName = self._get_storage_pool_capability(
            conn, poolInstanceName)
        if storagePoolCapabilityInstanceName:
            storagePoolSettingInstanceName = self._get_storage_pool_setting(
                conn, storagePoolCapabilityInstanceName, slo, workload)
            if storagePoolCapabilityInstanceName:
                supportedSizeDict = self._get_supported_size_range_for_SLO(
                    conn, storageConfigService, poolInstanceName,
                    storagePoolSettingInstanceName, extraSpecs)

                maximumVolumeSize = supportedSizeDict['MaximumVolumeSize']
                minimumVolumeSize = supportedSizeDict['MinimumVolumeSize']

        return maximumVolumeSize, minimumVolumeSize

    def activate_snap_relationship(
            self, conn, repServiceInstanceName, syncInstanceName, extraSpecs):
        """Activate snap relationship and start copy operation.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
            SE_StorageSynchronized_SV_SV object
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object of the replica creation operation
        """
        # Operation 4: activate the snapVx.
        operation = self.utils.get_num(4, '16')

        LOG.debug("Activate snap: %(sv)s  operation: %(operation)s.",
                  {'sv': syncInstanceName, 'operation': operation})

        return self._modify_replica_synchronization(
            conn, repServiceInstanceName, syncInstanceName, operation,
            extraSpecs)

    def return_to_resource_pool(self, conn, repServiceInstanceName,
                                syncInstanceName, extraSpecs):
        """Return the snap target resources back to the pool.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
        :param extraSpecs: additional info
        :returns: rc - return code
        :returns: job object of the replica creation operation
        """
        # Operation 4: activate the snapVx.
        operation = self.utils.get_num(19, '16')

        LOG.debug("Return snap resource back to pool: "
                  "%(sv)s  operation: %(operation)s.",
                  {'sv': syncInstanceName, 'operation': operation})

        return self._modify_replica_synchronization(
            conn, repServiceInstanceName, syncInstanceName, operation,
            extraSpecs)

    def _modify_replica_synchronization(
            self, conn, repServiceInstanceName, syncInstanceName,
            operation, extraSpecs, force=False):
        """Modify the relationship between the clone/snap and source volume.

        Helper function that makes an SMI-S call to break clone relationship
        between the clone volume and the source.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
            SE_StorageSynchronized_SV_SV object
        :param operation: operation code
        :param extraSpecs: additional info
        :param force: force to modify replication synchronization if True
        :returns: int -- return code
        :returns: job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'ModifyReplicaSynchronization', repServiceInstanceName,
            Operation=operation,
            Synchronization=syncInstanceName,
            Force=force)

        LOG.debug("_modify_replica_synchronization: %(sv)s "
                  "operation: %(operation)s  Return code: %(rc)lu.",
                  {'sv': syncInstanceName, 'operation': operation, 'rc': rc})

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error modify replica synchronization: %(sv)s "
                    "operation: %(operation)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'sv': syncInstanceName, 'operation': operation,
                       'rc': rc, 'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod ModifyReplicaSynchronization "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def create_group_replica(
            self, conn, replicationService,
            srcGroupInstanceName, tgtGroupInstanceName, relationName,
            extraSpecs):
        """Make SMI-S call to create replica for source group.

        :param conn: the connection to the ecom server
        :param replicationService: replication service
        :param srcGroupInstanceName: source group instance name
        :param tgtGroupInstanceName: target group instance name
        :param relationName: replica relationship name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        LOG.debug(
            "Creating CreateGroupReplica V3: "
            "replicationService: %(replicationService)s  "
            "RelationName: %(relationName)s "
            "sourceGroup: %(srcGroup)s "
            "targetGroup: %(tgtGroup)s.",
            {'replicationService': replicationService,
             'relationName': relationName,
             'srcGroup': srcGroupInstanceName,
             'tgtGroup': tgtGroupInstanceName})
        # 7 for snap.
        syncType = 7
        rc, job = conn.InvokeMethod(
            'CreateGroupReplica',
            replicationService,
            RelationshipName=relationName,
            SourceGroup=srcGroupInstanceName,
            TargetGroup=tgtGroupInstanceName,
            SyncType=self.utils.get_num(syncType, '16'))

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMsg = (_("Error CreateGroupReplica: "
                                  "source: %(source)s target: %(target)s. "
                                  "Return code: %(rc)lu. Error: %(error)s.")
                                % {'source': srcGroupInstanceName,
                                   'target': tgtGroupInstanceName,
                                   'rc': rc,
                                   'error': errordesc})
                LOG.error(exceptionMsg)
                raise exception.VolumeBackendAPIException(data=exceptionMsg)
        return rc, job
