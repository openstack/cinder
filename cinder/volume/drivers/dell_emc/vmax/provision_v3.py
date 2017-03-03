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
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _, _LE, _LW
from cinder.volume.drivers.dell_emc.vmax import utils

LOG = logging.getLogger(__name__)

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3

EMC_ROOT = 'root/emc'
THINPROVISIONINGCOMPOSITE = 32768
THINPROVISIONING = 5
INFO_SRC_V3 = 3
ACTIVATESNAPVX = 4
DEACTIVATESNAPVX = 19
SNAPSYNCTYPE = 7
RDF_FAILOVER = 10
RDF_FAILBACK = 11
RDF_RESYNC = 14
RDF_SYNC_MODE = 2
RDF_SYNCHRONIZED = 6
RDF_FAILEDOVER = 12


class VMAXProvisionV3(object):
    """Provisioning Class for SMI-S based EMC volume drivers.

    This Provisioning class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl):
        self.protocol = prtcl
        self.utils = utils.VMAXUtils(prtcl)

    def delete_volume_from_pool(
            self, conn, storageConfigservice, volumeInstanceName, volumeName,
            extraSpecs):
        """Given the volume instance remove it from the pool.

        :param conn: connection to the ecom server
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

        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0:
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
        try:
            storageGroupInstance = conn.GetInstance(sgInstanceName)
        except Exception:
            exceptionMessage = (_(
                "Unable to get the name of the storage group"))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        sgName = storageGroupInstance['ElementName']

        @coordination.synchronized("emc-sg-{storageGroup}")
        def do_create_volume_from_sg(storageGroup):
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

            if rc != 0:
                rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                                 extraSpecs)
                if rc != 0:
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

        return do_create_volume_from_sg(sgName)

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
        if len(associators) > 0:
            return self.create_volume_dict(associators[0].path)
        else:
            exceptionMessage = (_(
                "Unable to get storage volume from job."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

    def get_volume_from_job(self, conn, jobInstance):
        """Given the jobInstance determine the volume Instance.

        :param conn: the ecom connection
        :param jobInstance: the instance of a job
        :returns: dict -- volumeDict - an instance of a volume
        """
        associators = conn.Associators(
            jobInstance,
            ResultClass='EMC_StorageVolume')
        if len(associators) > 0:
            return associators[0]
        else:
            exceptionMessage = (_(
                "Unable to get storage volume from job."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

    def create_volume_dict(self, volumeInstanceName):
        """Create volume dictionary

        :param volumeInstanceName: the instance of a job
        :returns: dict -- volumeDict - an instance of a volume
        """
        volpath = volumeInstanceName
        volumeDict = {}
        volumeDict['classname'] = volpath.classname
        keys = {}
        keys['CreationClassName'] = volpath['CreationClassName']
        keys['SystemName'] = volpath['SystemName']
        keys['DeviceID'] = volpath['DeviceID']
        keys['SystemCreationClassName'] = volpath['SystemCreationClassName']
        volumeDict['keybindings'] = keys

        return volumeDict

    def get_or_create_default_sg(self, conn, extraSpecs, storageSystemName,
                                 doDisableCompression):
        """Get or create default storage group for a replica.

        :param conn: the connection to the ecom server
        :param extraSpecs: the extra specifications
        :param storageSystemName: the storage system name
        :param doDisableCompression: flag for compression
        :returns: sgInstanceName, instance of storage group
        """
        pool = extraSpecs[self.utils.POOL]
        slo = extraSpecs[self.utils.SLO]
        workload = extraSpecs[self.utils.WORKLOAD]
        storageGroupName, controllerConfigService, sgInstanceName = (
            self.utils.get_v3_default_sg_instance_name(
                conn, pool, slo, workload, storageSystemName,
                doDisableCompression))
        if sgInstanceName is None:
            sgInstanceName = self.create_storage_group_v3(
                conn, controllerConfigService, storageGroupName,
                pool, slo, workload, extraSpecs, doDisableCompression)
        return sgInstanceName

    def create_element_replica(
            self, conn, repServiceInstanceName,
            cloneName, syncType, sourceInstance, extraSpecs,
            targetInstance=None, rsdInstance=None, copyState=None):
        """Make SMI-S call to create replica for source element.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: replication service
        :param cloneName: clone volume name
        :param syncType: 7=snapshot, 8=clone
        :param sourceInstance: source volume instance
        :param extraSpecs: additional info
        :param targetInstance: Target volume instance. Default None
        :param rsdInstance: replication settingdata instance. Default None
        :returns: int -- rc - return code
        :returns: job - job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()
        LOG.debug("Create replica: %(clone)s "
                  "syncType: %(syncType)s  Source: %(source)s.",
                  {'clone': cloneName,
                   'syncType': syncType,
                   'source': sourceInstance.path})
        storageSystemName = sourceInstance['SystemName']
        doDisableCompression = self.utils.is_compression_disabled(extraSpecs)
        sgInstanceName = (
            self.get_or_create_default_sg(
                conn, extraSpecs, storageSystemName, doDisableCompression))
        try:
            storageGroupInstance = conn.GetInstance(sgInstanceName)
        except Exception:
            exceptionMessage = (_(
                "Unable to get the name of the storage group"))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)

        @coordination.synchronized("emc-sg-{storageGroupName}")
        def do_create_element_replica(storageGroupName):
            if targetInstance is None and rsdInstance is None:
                rc, job = conn.InvokeMethod(
                    'CreateElementReplica', repServiceInstanceName,
                    ElementName=cloneName,
                    SyncType=self.utils.get_num(syncType, '16'),
                    SourceElement=sourceInstance.path,
                    Collections=[sgInstanceName])
            else:
                rc, job = self._create_element_replica_extra_params(
                    conn, repServiceInstanceName, cloneName, syncType,
                    sourceInstance, targetInstance, rsdInstance,
                    sgInstanceName, copyState=copyState)

            if rc != 0:
                rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                                 extraSpecs)
                if rc != 0:
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
        return do_create_element_replica(storageGroupInstance['ElementName'])

    def create_remote_element_replica(
            self, conn, repServiceInstanceName, cloneName, syncType,
            sourceInstance, targetInstance, rdfGroupInstance, extraSpecs):
        """Create a replication relationship between source and target.

        :param conn: the ecom connection
        :param repServiceInstanceName: the replication service
        :param cloneName: the name of the target volume
        :param syncType: the synchronization type
        :param sourceInstance: the source volume instance
        :param targetInstance: the target volume instance
        :param rdfGroupInstance: the rdf group instance
        :param extraSpecs: additional info
        :return: rc, job
        """
        startTime = time.time()
        LOG.debug("Setup replication relationship: %(source)s "
                  "syncType: %(syncType)s  Source: %(target)s.",
                  {'source': sourceInstance.path,
                   'syncType': syncType,
                   'target': targetInstance.path})
        rc, job = self._create_element_replica_extra_params(
            conn, repServiceInstanceName, cloneName, syncType,
            sourceInstance, targetInstance, None, None, rdfGroupInstance)
        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0:
                exceptionMessage = (
                    _("Error Create Cloned Volume: %(cloneName)s "
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

    def _create_element_replica_extra_params(
            self, conn, repServiceInstanceName, cloneName, syncType,
            sourceInstance, targetInstance, rsdInstance, sgInstanceName,
            rdfGroupInstance=None, copyState=None):
        """CreateElementReplica using extra parameters.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: replication service
        :param cloneName: clone volume name
        :param syncType: 7=snapshot, 8=clone
        :param sourceInstance: source volume instance
        :param targetInstance: Target volume instance. Default None
        :param rsdInstance: replication settingdata instance. Default None
        :param sgInstanceName: pool instance name
        :returns: int -- rc - return code
        :returns: job - job object of the replica creation operation
        """
        syncType = self.utils.get_num(syncType, '16')
        modeType = self.utils.get_num(RDF_SYNC_MODE, '16')
        if targetInstance and rsdInstance:
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName,
                SyncType=syncType,
                SourceElement=sourceInstance.path,
                TargetElement=targetInstance.path,
                ReplicationSettingData=rsdInstance)
        elif targetInstance and rdfGroupInstance:
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                SyncType=syncType,
                Mode=modeType,
                SourceElement=sourceInstance.path,
                TargetElement=targetInstance.path,
                ConnectivityCollection=rdfGroupInstance)
        elif rsdInstance:
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName,
                SyncType=syncType,
                SourceElement=sourceInstance.path,
                ReplicationSettingData=rsdInstance,
                Collections=[sgInstanceName],
                WaitForCopyState=copyState)
        elif targetInstance and copyState:
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName,
                SyncType=syncType,
                SourceElement=sourceInstance.path,
                TargetElement=targetInstance.path,
                WaitForCopyState=copyState)
        elif targetInstance:
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName,
                SyncType=syncType,
                SourceElement=sourceInstance.path,
                TargetElement=targetInstance.path)
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
                                groupName, srp, slo, workload, extraSpecs,
                                doDisableCompression):
        """Create the volume in the specified pool.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param groupName: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param extraSpecs: additional info
        :param doDisableCompression: disable compression flag
        :returns: storageGroupInstanceName - storage group instance name
        """
        startTime = time.time()

        @coordination.synchronized("emc-sg-{sgGroupName}")
        def do_create_storage_group_v3(sgGroupName):
            if doDisableCompression:
                if slo and workload:
                    rc, job = conn.InvokeMethod(
                        'CreateGroup',
                        controllerConfigService,
                        GroupName=groupName,
                        Type=self.utils.get_num(4, '16'),
                        EMCSRP=srp,
                        EMCSLO=slo,
                        EMCWorkload=workload,
                        EMCDisableCompression=True)
            else:
                if slo and workload:
                    rc, job = conn.InvokeMethod(
                        'CreateGroup',
                        controllerConfigService,
                        GroupName=groupName,
                        Type=self.utils.get_num(4, '16'),
                        EMCSRP=srp,
                        EMCSLO=slo,
                        EMCWorkload=workload)
                else:
                    rc, job = conn.InvokeMethod(
                        'CreateGroup',
                        controllerConfigService,
                        GroupName=groupName,
                        Type=self.utils.get_num(4, '16'))
            if rc != 0:
                rc, errordesc = self.utils.wait_for_job_complete(
                    conn, job, extraSpecs)
                if rc != 0:
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

        return do_create_storage_group_v3(groupName)

    def get_storage_pool_capability(self, conn, poolInstanceName):
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

    def get_storage_pool_setting(
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
        if foundStoragePoolSetting is None:
            exceptionMessage = (_(
                "The array does not support the storage pool setting "
                "for SLO %(slo)s and workload %(workload)s.  Please "
                "check the array for valid SLOs and workloads.")
                % {'slo': slo,
                   'workload': workload})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
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

        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(
                conn, supportedSizeDict, extraSpecs)
            if rc != 0:
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
        :returns: supportedSizeDict
        """
        supportedSizeDict = {}
        storagePoolCapabilityInstanceName = self.get_storage_pool_capability(
            conn, poolInstanceName)
        if storagePoolCapabilityInstanceName:
            storagePoolSettingInstanceName = self.get_storage_pool_setting(
                conn, storagePoolCapabilityInstanceName, slo, workload)
            supportedSizeDict = self._get_supported_size_range_for_SLO(
                conn, storageConfigService, poolInstanceName,
                storagePoolSettingInstanceName, extraSpecs)
        return supportedSizeDict

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
        operation = ACTIVATESNAPVX

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
        operation = DEACTIVATESNAPVX

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
            Operation=self.utils.get_num(operation, '16'),
            Synchronization=syncInstanceName,
            Force=force)

        LOG.debug("_modify_replica_synchronization: %(sv)s "
                  "operation: %(operation)s  Return code: %(rc)lu.",
                  {'sv': syncInstanceName, 'operation': operation, 'rc': rc})

        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0:
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
        rc, job = conn.InvokeMethod(
            'CreateGroupReplica',
            replicationService,
            RelationshipName=relationName,
            SourceGroup=srcGroupInstanceName,
            TargetGroup=tgtGroupInstanceName,
            SyncType=self.utils.get_num(SNAPSYNCTYPE, '16'),
            WaitForCopyState=self.utils.get_num(4, '16'))

        if rc != 0:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0:
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

    def get_srp_pool_stats(self, conn, arrayInfo):
        """Get the totalManagedSpace, remainingManagedSpace.

        :param conn: the connection to the ecom server
        :param arrayInfo: the array dict
        :returns: totalCapacityGb
        :returns: remainingCapacityGb
        :returns: subscribedCapacityGb
        :returns: array_reserve_percent
        :returns: wlpEnabled
        """
        totalCapacityGb = -1
        remainingCapacityGb = -1
        subscribedCapacityGb = -1
        array_reserve_percent = -1
        wlpEnabled = False
        storageSystemInstanceName = self.utils.find_storageSystem(
            conn, arrayInfo['SerialNumber'])

        srpPoolInstanceNames = conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='Symm_SRPStoragePool')

        for srpPoolInstanceName in srpPoolInstanceNames:
            poolnameStr = self.utils.get_pool_name(conn, srpPoolInstanceName)

            if six.text_type(arrayInfo['PoolName']) == (
                    six.text_type(poolnameStr)):
                try:
                    # Check that pool hasn't suddently been deleted.
                    srpPoolInstance = conn.GetInstance(srpPoolInstanceName)
                    propertiesList = srpPoolInstance.properties.items()
                    for properties in propertiesList:
                        if properties[0] == 'TotalManagedSpace':
                            cimProperties = properties[1]
                            totalManagedSpace = cimProperties.value
                            totalCapacityGb = self.utils.convert_bits_to_gbs(
                                totalManagedSpace)
                        elif properties[0] == 'RemainingManagedSpace':
                            cimProperties = properties[1]
                            remainingManagedSpace = cimProperties.value
                            remainingCapacityGb = (
                                self.utils.convert_bits_to_gbs(
                                    remainingManagedSpace))
                        elif properties[0] == 'EMCSubscribedCapacity':
                            cimProperties = properties[1]
                            subscribedManagedSpace = cimProperties.value
                            subscribedCapacityGb = (
                                self.utils.convert_bits_to_gbs(
                                    subscribedManagedSpace))
                        elif properties[0] == 'EMCPercentReservedCapacity':
                            cimProperties = properties[1]
                            array_reserve_percent = int(cimProperties.value)
                except Exception:
                    pass
                remainingSLOCapacityGb = (
                    self._get_remaining_slo_capacity_wlp(
                        conn, srpPoolInstanceName, arrayInfo,
                        storageSystemInstanceName['Name']))
                if remainingSLOCapacityGb != -1:
                    remainingCapacityGb = remainingSLOCapacityGb
                    wlpEnabled = True
                else:
                    LOG.warning(_LW(
                        "Remaining capacity %(remainingCapacityGb)s "
                        "GBs is determined from SRP pool capacity "
                        "and not the SLO capacity. Performance may "
                        "not be what you expect."),
                        {'remainingCapacityGb': remainingCapacityGb})

        return (totalCapacityGb, remainingCapacityGb, subscribedCapacityGb,
                array_reserve_percent, wlpEnabled)

    def _get_remaining_slo_capacity_wlp(self, conn, srpPoolInstanceName,
                                        arrayInfo, systemName):
        """Get the remaining SLO capacity.

        This is derived from the WLP portion of Unisphere. Please
        see the SMIProvider doc and the readme doc for details.

        :param conn: the connection to the ecom server
        :param srpPoolInstanceName: SRP instance name
        :param arrayInfo: the array dict
        :param systemName: the system name
        :returns: remainingCapacityGb
        """
        remainingCapacityGb = -1
        if arrayInfo['SLO']:
            storageConfigService = (
                self.utils.find_storage_configuration_service(
                    conn, systemName))

            supportedSizeDict = (
                self.get_volume_range(
                    conn, storageConfigService, srpPoolInstanceName,
                    arrayInfo['SLO'], arrayInfo['Workload'],
                    None))
            try:
                if supportedSizeDict['EMCInformationSource'] == INFO_SRC_V3:
                    remainingCapacityGb = self.utils.convert_bits_to_gbs(
                        supportedSizeDict['EMCRemainingSLOCapacity'])
                    LOG.debug("Received remaining SLO Capacity "
                              "%(remainingCapacityGb)s GBs for SLO "
                              "%(SLO)s and workload %(workload)s.",
                              {'remainingCapacityGb': remainingCapacityGb,
                               'SLO': arrayInfo['SLO'],
                               'workload': arrayInfo['Workload']})
            except KeyError:
                pass
        return remainingCapacityGb

    def extend_volume_in_SG(
            self, conn, storageConfigService, volumeInstanceName,
            volumeName, volumeSize, extraSpecs):
        """Extend a volume instance.

        :param conn: connection to the ecom server
        :param storageConfigservice: the storage configuration service
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name (String)
        :param volumeSize: the volume size
        :param extraSpecs: additional info
        :returns: volumeDict
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            storageConfigService, TheElement=volumeInstanceName,
            Size=self.utils.get_num(volumeSize, '64'))

        LOG.debug("Extend Volume: %(volumename)s. Return code: %(rc)lu.",
                  {'volumename': volumeName,
                   'rc': rc})

        if rc != 0:
            rc, error_desc = self.utils.wait_for_job_complete(conn, job,
                                                              extraSpecs)
            if rc != 0:
                exceptionMessage = (_(
                    "Error Extend Volume: %(volumeName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumeName': volumeName,
                       'rc': rc,
                       'error': error_desc})
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

    def get_rdf_group_instance(self, conn, repServiceInstanceName,
                               RDFGroupName):
        """Get the SRDF group instance.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: the replication service
        :param RDFGroupName: the element name of the RDF group
        :return: foundRDFGroupInstanceName
        """
        foundRDFGroupInstanceName = None

        RDFGroupInstances = (
            conn.Associators(repServiceInstanceName,
                             ResultClass='CIM_ConnectivityCollection'))

        for RDFGroupInstance in RDFGroupInstances:

            if RDFGroupName == (
                    six.text_type(RDFGroupInstance['ElementName'])):
                # Check that it has not been deleted recently.
                instance = self.utils.get_existing_instance(
                    conn, RDFGroupInstance.path)
                if instance is None:
                    # SRDF group not found.
                    foundRDFGroupInstanceName = None
                else:
                    foundRDFGroupInstanceName = (
                        RDFGroupInstance.path)
                break
        return foundRDFGroupInstanceName

    def failover_volume(self, conn, repServiceInstanceName,
                        storageSynchronizationSv,
                        extraSpecs):
        """Failover a volume to its target device.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: the replication service
        :param storageSynchronizationSv: the storage synchronized object
        :param extraSpecs: the extra specifications
        """
        operation = RDF_FAILOVER
        # check if volume already in failover state
        syncState = self._check_sync_state(conn, storageSynchronizationSv)
        if syncState == RDF_FAILEDOVER:
            return

        else:
            LOG.debug("Failover: %(sv)s  operation: %(operation)s.",
                      {'sv': storageSynchronizationSv, 'operation': operation})

            return self._modify_replica_synchronization(
                conn, repServiceInstanceName, storageSynchronizationSv,
                operation, extraSpecs)

    def failback_volume(self, conn, repServiceInstanceName,
                        storageSynchronizationSv,
                        extraSpecs):
        """Failback a volume to the source device.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: the replication service
        :param storageSynchronizationSv: the storage synchronized object
        :param extraSpecs: the extra specifications
        """
        failback_operation = RDF_FAILBACK
        # check if volume already in failback state
        syncState = self._check_sync_state(conn, storageSynchronizationSv)
        if syncState == RDF_SYNCHRONIZED:
            return

        else:
            LOG.debug("Failback: %(sv)s  operation: %(operation)s.",
                      {'sv': storageSynchronizationSv,
                       'operation': failback_operation})

            return self._modify_replica_synchronization(
                conn, repServiceInstanceName, storageSynchronizationSv,
                failback_operation, extraSpecs)

    def _check_sync_state(self, conn, syncName):
        """Get the copy state of a sync name.

        :param conn: the connection to the ecom server
        :param syncName: the storage sync sv name
        :return: the copy state
        """
        try:
            syncInstance = conn.GetInstance(syncName,
                                            LocalOnly=False)
            syncState = syncInstance['syncState']
            LOG.debug("syncState is %(syncState)lu.",
                      {'syncState': syncState})
            return syncState
        except Exception as ex:
            exceptionMessage = (
                _("Getting sync instance failed with: %(ex)s.")
                % {'ex': six.text_type(ex)})
            LOG.exception(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
