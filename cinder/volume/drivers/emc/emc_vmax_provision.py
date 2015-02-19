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

from cinder import exception
from cinder.i18n import _, _LE
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
            'EMCReturnToStoragePool', storageConfigservice,
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

        LOG.debug("InvokeMethod EMCReturnToStoragePool took: "
                  "%(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc

    def create_volume_from_pool(
            self, conn, storageConfigService, volumeName,
            poolInstanceName, volumeSize, extraSpecs):
        """Create the volume in the specified pool.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service
        :param volumeName: the volume name (String)
        :param poolInstanceName: the pool instance name to create
            the dummy volume in
        :param volumeSize: volume size (String)
        :param extraSpecs: additional info
        :returns: dict -- the volume dict
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateOrModifyElementFromStoragePool',
            storageConfigService, ElementName=volumeName,
            InPool=poolInstanceName,
            ElementType=self.utils.get_num(THINPROVISIONING, '16'),
            Size=self.utils.get_num(volumeSize, '64'),
            EMCBindElements=False)

        LOG.debug("Create Volume: %(volumename)s  Return code: %(rc)lu.",
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

    def create_and_get_storage_group(self, conn, controllerConfigService,
                                     storageGroupName, volumeInstanceName,
                                     extraSpecs):
        """Create a storage group and return it.

        :param conn: the connection information to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupName: the storage group name (String
        :param volumeInstanceName: the volume instance name
        :param extraSpecs: additional info
        :returns: foundStorageGroupInstanceName - instance name of the
            default storage group
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=storageGroupName,
            Type=self.utils.get_num(STORAGEGROUPTYPE, '16'),
            Members=[volumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'groupName': storageGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateGroup "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})
        foundStorageGroupInstanceName = self._find_new_storage_group(
            conn, job, storageGroupName)

        return foundStorageGroupInstanceName

    def create_storage_group_no_members(
            self, conn, controllerConfigService, groupName, extraSpecs):
        """Create a new storage group that has no members.

        :param conn: connection the ecom server
        :param controllerConfigService: the controller configuration service
        :param groupName: the proposed group name
        :param extraSpecs: additional info
        :returns: foundStorageGroupInstanceName
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateGroup', controllerConfigService, GroupName=groupName,
            Type=self.utils.get_num(STORAGEGROUPTYPE, '16'),
            DeleteWhenBecomesUnassociated=False)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Group: %(groupName)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'groupName': groupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateGroup "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

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

    def remove_device_from_storage_group(
            self, conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName, extraSpecs):
        """Remove a volume from a storage group.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupInstanceName: the instance name of the storage group
        :param volumeInstanceName: the instance name of the volume
        :param volumeName: the volume name (String)
        :param extraSpecs: additional info
        :returns: int -- the return code of the job
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, jobDict = conn.InvokeMethod('RemoveMembers',
                                        controllerConfigService,
                                        MaskingGroup=storageGroupInstanceName,
                                        Members=[volumeInstanceName])
        if rc != 0L:
            rc, errorDesc = self.utils.wait_for_job_complete(conn, jobDict,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error removing volume %(vol)s. %(error)s.")
                    % {'vol': volumeName, 'error': errorDesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod RemoveMembers "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc

    def add_members_to_masking_group(
            self, conn, controllerConfigService, storageGroupInstanceName,
            volumeInstanceName, volumeName, extraSpecs):
        """Add a member to a masking group group.

        :param conn: the connection to the ecom server
        :param controllerConfigService: the controller configuration service
        :param storageGroupInstanceName: the instance name of the storage group
        :param volumeInstanceName: the instance name of the volume
        :param volumeName: the volume name (String)
        :param extraSpecs: additional info
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'AddMembers', controllerConfigService,
            MaskingGroup=storageGroupInstanceName,
            Members=[volumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error mapping volume %(vol)s. %(error)s.")
                    % {'vol': volumeName, 'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod AddMembers "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

    def unbind_volume_from_storage_pool(
            self, conn, storageConfigService, poolInstanceName,
            volumeInstanceName, volumeName, extraSpecs):
        """Unbind a volume from a pool and return the unbound volume.

        :param conn: the connection information to the ecom server
        :param storageConfigService: the storage configuration service
            instance name
        :param poolInstanceName: the pool instance name
        :param volumeInstanceName: the volume instance name
        :param volumeName: the volume name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: the job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'EMCUnBindElement',
            storageConfigService,
            InPool=poolInstanceName,
            TheElement=volumeInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error unbinding volume %(vol)s from pool. %(error)s.")
                    % {'vol': volumeName, 'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod EMCUnBindElement "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def modify_composite_volume(
            self, conn, elementCompositionService, theVolumeInstanceName,
            inVolumeInstanceName, extraSpecs):

        """Given a composite volume add a storage volume to it.

        :param conn: the connection to the ecom
        :param elementCompositionService: the element composition service
        :param theVolumeInstanceName: the existing composite volume
        :param inVolumeInstanceName: the volume you wish to add to the
            composite volume
        :param extraSpecs: additional info
        :returns: int -- rc - return code
        :returns: the job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement',
            elementCompositionService,
            TheElement=theVolumeInstanceName,
            InElements=[inVolumeInstanceName])

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error adding volume to composite volume. "
                    "Error is: %(error)s.")
                    % {'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateOrModifyCompositeElement "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})
        return rc, job

    def create_composite_volume(
            self, conn, elementCompositionService, volumeSize, volumeName,
            poolInstanceName, compositeType, numMembers, extraSpecs):
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
        :param extraSpecs: additional info
        :returns: dict -- volumeDict
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        newMembers = 2
        LOG.debug(
            "Parameters for CreateOrModifyCompositeElement: "
            "elementCompositionService: %(elementCompositionService)s  "
            "provisioning: %(provisioning)lu "
            "volumeSize: %(volumeSize)s "
            "newMembers: %(newMembers)lu "
            "poolInstanceName: %(poolInstanceName)s "
            "compositeType: %(compositeType)lu "
            "numMembers: %(numMembers)s.",
            {'elementCompositionService': elementCompositionService,
             'provisioning': THINPROVISIONINGCOMPOSITE,
             'volumeSize': volumeSize,
             'newMembers': newMembers,
             'poolInstanceName': poolInstanceName,
             'compositeType': compositeType,
             'numMembers': numMembers})

        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement', elementCompositionService,
            ElementName=volumeName,
            ElementType=self.utils.get_num(THINPROVISIONINGCOMPOSITE, '16'),
            Size=self.utils.get_num(volumeSize, '64'),
            ElementSource=self.utils.get_num(newMembers, '16'),
            EMCInPools=[poolInstanceName],
            CompositeType=self.utils.get_num(compositeType, '16'),
            EMCNumberOfMembers=self.utils.get_num(numMembers, '32'))

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Volume: %(volumename)s. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumename': volumeName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateOrModifyCompositeElement "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        # Find the newly created volume.
        volumeDict = self.get_volume_dict_from_job(conn, job['Job'])

        return volumeDict, rc

    def create_new_composite_volume(
            self, conn, elementCompositionService, compositeHeadInstanceName,
            compositeMemberInstanceName, compositeType, extraSpecs):
        """Creates a new composite volume.

        Given a bound composite head and an unbound composite member
        create a new composite volume.

        :param conn: the connection the the ecom server
        :param elementCompositionService: the element composition service
        :param compositeHeadInstanceName: the composite head. This can be bound
        :param compositeMemberInstanceName: the composite member. This must be
            unbound
        :param compositeType: the composite type e.g striped or concatenated
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: the job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateOrModifyCompositeElement', elementCompositionService,
            ElementType=self.utils.get_num('2', '16'),
            InElements=(
                [compositeHeadInstanceName, compositeMemberInstanceName]),
            CompositeType=self.utils.get_num(compositeType, '16'))

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Creating new composite Volume Return code: "
                    "%(rc)lu. Error: %(error)s.")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateOrModifyCompositeElement "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def _migrate_volume(
            self, conn, storageRelocationServiceInstanceName,
            volumeInstanceName, targetPoolInstanceName, extraSpecs):
        """Migrate a volume to another pool.

        :param conn: the connection to the ecom server
        :param storageRelocationServiceInstanceName: the storage relocation
            service
        :param volumeInstanceName: the volume to be migrated
        :param targetPoolInstanceName: the target pool to migrate the volume to
        :param extraSpecs: additional info
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'RelocateStorageVolumesToStoragePool',
            storageRelocationServiceInstanceName,
            TheElements=[volumeInstanceName],
            TargetPool=targetPoolInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Migrating volume from one pool to another. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)
        LOG.debug("InvokeMethod RelocateStorageVolumesToStoragePool "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc

    def migrate_volume_to_storage_pool(
            self, conn, storageRelocationServiceInstanceName,
            volumeInstanceName, targetPoolInstanceName, extraSpecs):
        """Given the storage system name, get the storage relocation service.

        :param conn: the connection to the ecom server
        :param storageRelocationServiceInstanceName: the storage relocation
            service
        :param volumeInstanceName: the volume to be migrated
        :param targetPoolInstanceName: the target pool to migrate the
            volume to.
        :param extraSpecs: additional info
        :returns: int -- rc, return code
        :raises: VolumeBackendAPIException
        """
        LOG.debug(
            "Volume instance name is %(volumeInstanceName)s. "
            "Pool instance name is : %(targetPoolInstanceName)s. ",
            {'volumeInstanceName': volumeInstanceName,
             'targetPoolInstanceName': targetPoolInstanceName})
        rc = -1
        try:
            rc = self._migrate_volume(
                conn, storageRelocationServiceInstanceName,
                volumeInstanceName, targetPoolInstanceName, extraSpecs)
        except Exception as ex:
            if 'source of a migration session' in six.text_type(ex):
                try:
                    rc = self._terminate_migrate_session(
                        conn, volumeInstanceName, extraSpecs)
                except Exception as ex:
                    LOG.error(_LE('Exception: %s.'), ex)
                    exceptionMessage = (_(
                        "Failed to terminate migrate session."))
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)
                try:
                    rc = self._migrate_volume(
                        conn, storageRelocationServiceInstanceName,
                        volumeInstanceName, targetPoolInstanceName,
                        extraSpecs)
                except Exception as ex:
                    LOG.error(_LE('Exception: %s'), ex)
                    exceptionMessage = (_(
                        "Failed to migrate volume for the second time."))
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)

            else:
                LOG.error(_LE('Exception: %s'), ex)
                exceptionMessage = (_(
                    "Failed to migrate volume for the first time."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        return rc

    def _terminate_migrate_session(self, conn, volumeInstanceName,
                                   extraSpecs):
        """Given the volume instance terminate a migrate session.

        :param conn: the connection to the ecom server
        :param volumeInstanceName: the volume to be migrated
        :param extraSpecs: additional info
        :returns: int -- return code
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'RequestStateChange', volumeInstanceName,
            RequestedState=self.utils.get_num(32769, '16'))
        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Terminating migrate session. "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod RequestStateChange "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc

    def create_element_replica(
            self, conn, repServiceInstanceName, cloneName,
            sourceName, sourceInstance, targetInstance, extraSpecs,
            copyOnWrite=False):
        """Make SMI-S call to create replica for source element.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: replication service
        :param cloneName: replica name
        :param sourceName: source volume name
        :param sourceInstance: source volume instance
        :param targetInstance: the target instance
        :param extraSpecs: additional info
        :param copyOnWrite: optional
        :returns: int -- return code
        :returns: job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        if copyOnWrite:
            startTime = time.time()
            repServiceCapabilityInstanceNames = conn.AssociatorNames(
                repServiceInstanceName,
                ResultClass='CIM_ReplicationServiceCapabilities',
                AssocClass='CIM_ElementCapabilities')
            repServiceCapabilityInstanceName = (
                repServiceCapabilityInstanceNames[0])

            # ReplicationType 10 - Synchronous Clone Local.
            rc, rsd = conn.InvokeMethod(
                'GetDefaultReplicationSettingData',
                repServiceCapabilityInstanceName,
                ReplicationType=self.utils.get_num(10, '16'))

            if rc != 0L:
                rc, errordesc = self.utils.wait_for_job_complete(conn, rsd,
                                                                 extraSpecs)
                if rc != 0L:
                    exceptionMessage = (_(
                        "Error creating cloned volume using "
                        "Volume: %(cloneName)s, Source Volume: "
                        "%(sourceName)s. Return code: %(rc)lu. "
                        "Error: %(error)s.")
                        % {'cloneName': cloneName,
                           'sourceName': sourceName,
                           'rc': rc,
                           'error': errordesc})
                    LOG.error(exceptionMessage)
                    raise exception.VolumeBackendAPIException(
                        data=exceptionMessage)

            LOG.debug("InvokeMethod GetDefaultReplicationSettingData "
                      "took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(startTime,
                                                          time.time())})

            # Set DesiredCopyMethodology to Copy-On-Write (6).
            rsdInstance = rsd['DefaultInstance']
            rsdInstance['DesiredCopyMethodology'] = self.utils.get_num(6, '16')

            startTime = time.time()

            # SyncType 8 - Clone.
            # ReplicationSettingData.DesiredCopyMethodology Copy-On-Write (6).
            rc, job = conn.InvokeMethod(
                'CreateElementReplica', repServiceInstanceName,
                ElementName=cloneName, SyncType=self.utils.get_num(8, '16'),
                ReplicationSettingData=rsdInstance,
                SourceElement=sourceInstance.path)
        else:
            startTime = time.time()
            if targetInstance is None:
                rc, job = conn.InvokeMethod(
                    'CreateElementReplica', repServiceInstanceName,
                    ElementName=cloneName,
                    SyncType=self.utils.get_num(8, '16'),
                    SourceElement=sourceInstance.path)
            else:
                rc, job = conn.InvokeMethod(
                    'CreateElementReplica', repServiceInstanceName,
                    ElementName=cloneName,
                    SyncType=self.utils.get_num(8, '16'),
                    SourceElement=sourceInstance.path,
                    TargetElement=targetInstance.path)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error Create Cloned Volume: "
                    "Volume: %(cloneName)s  Source Volume:"
                    "%(sourceName)s.  Return code: %(rc)lu. "
                    "Error: %(error)s.")
                    % {'cloneName': cloneName,
                       'sourceName': sourceName,
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

    def delete_clone_relationship(
            self, conn, repServiceInstanceName, syncInstanceName, extraSpecs,
            force=False):
        """Deletes the relationship between the clone and source volume.

        Makes an SMI-S call to break clone relationship between the clone
        volume and the source.
        8/Detach - Delete the synchronization between two storage objects.
        Treat the objects as independent after the synchronization is deleted.

        :param conn: the connection to the ecom server
        :param repServiceInstanceName: instance name of the replication service
        :param syncInstanceName: instance name of the
            SE_StorageSynchronized_SV_SV object
        :param extraSpecs: additional info
        :param force: optional param
        :returns: int -- return code
        :returns: job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'ModifyReplicaSynchronization', repServiceInstanceName,
            Operation=self.utils.get_num(8, '16'),
            Synchronization=syncInstanceName,
            Force=force)

        LOG.debug("Delete clone relationship: Sync Name: %(syncName)s "
                  "Return code: %(rc)lu.",
                  {'syncName': syncInstanceName,
                   'rc': rc})

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Error break clone relationship: "
                    "Sync Name: %(syncName)s "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'syncName': syncInstanceName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod ModifyReplicaSynchronization "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def get_target_endpoints(self, conn, storageHardwareService, hardwareId):
        """Given the hardwareId get the target endpoints.

        :param conn: the connection to the ecom server
        :param storageHardwareService: the storage HardwareId Service
        :param hardwareId: the hardware Id
        :returns: int -- return code
        :returns: targetEndpoints
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, targetEndpoints = conn.InvokeMethod(
            'EMCGetTargetEndpoints', storageHardwareService,
            HardwareId=hardwareId)

        if rc != 0L:
            exceptionMessage = (_("Error finding Target WWNs."))
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug("InvokeMethod EMCGetTargetEndpoints "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, targetEndpoints

    def create_consistency_group(
            self, conn, replicationService, consistencyGroupName, extraSpecs):
        """Create a new consistency group.

        :param conn: the connection to the ecom server
        :param replicationService: the replication Service
        :param consistencyGroupName: the CG group name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'CreateGroup',
            replicationService,
            GroupName=consistencyGroupName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Failed to create consistency group: "
                    "%(consistencyGroupName)s  "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'consistencyGroupName': consistencyGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod CreateGroup "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def delete_consistency_group(
            self, conn, replicationService, cgInstanceName,
            consistencyGroupName, extraSpecs):

        """Delete a consistency group.

        :param conn: the connection to the ecom server
        :param replicationService: the replication Service
        :param cgInstanceName: the CG instance name
        :param consistencyGroupName: the CG group name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'DeleteGroup',
            replicationService,
            ReplicationGroup=cgInstanceName,
            RemoveElements=True)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Failed to delete consistency group: "
                    "%(consistencyGroupName)s "
                    "Return code: %(rc)lu. Error: %(error)s.")
                    % {'consistencyGroupName': consistencyGroupName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod DeleteGroup "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})

        return rc, job

    def add_volume_to_cg(
            self, conn, replicationService, cgInstanceName,
            volumeInstanceName, cgName, volumeName, extraSpecs):
        """Add a volume to a consistency group.

        :param conn: the connection to the ecom server
        :param replicationService: the replication Service
        :param cgInstanceName: the CG instance name
        :param volumeInstanceName: the volume instance name
        :param cgName: the CG group name
        :param volumeName: the volume name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'AddMembers',
            replicationService,
            Members=[volumeInstanceName],
            ReplicationGroup=cgInstanceName)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Failed to add volume %(volumeName)s: "
                    "to consistency group %(cgName)s "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumeName': volumeName,
                       'cgName': cgName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod AddMembers "
                  "took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(startTime,
                                                      time.time())})
        return rc, job

    def remove_volume_from_cg(
            self, conn, replicationService, cgInstanceName,
            volumeInstanceName, cgName, volumeName, extraSpecs):
        """Remove a volume from a consistency group.

        :param conn: the connection to the ecom server
        :param replicationService: the replication Service
        :param cgInstanceName: the CG instance name
        :param volumeInstanceName: the volume instance name
        :param cgName: the CG group name
        :param volumeName: the volume name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object
        :raises: VolumeBackendAPIException
        """
        startTime = time.time()

        rc, job = conn.InvokeMethod(
            'RemoveMembers',
            replicationService,
            Members=[volumeInstanceName],
            ReplicationGroup=cgInstanceName,
            RemoveElements=True)

        if rc != 0L:
            rc, errordesc = self.utils.wait_for_job_complete(conn, job,
                                                             extraSpecs)
            if rc != 0L:
                exceptionMessage = (_(
                    "Failed to remove volume %(volumeName)s: "
                    "to consistency group %(cgName)s "
                    "Return code: %(rc)lu.  Error: %(error)s.")
                    % {'volumeName': volumeName,
                       'cgName': cgName,
                       'rc': rc,
                       'error': errordesc})
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(
                    data=exceptionMessage)

        LOG.debug("InvokeMethod RemoveMembers "
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
        :param relationName: relation name
        :param extraSpecs: additional info
        :returns: int -- return code
        :returns: job object of the replica creation operation
        :raises: VolumeBackendAPIException
        """
        LOG.debug(
            "Parameters for CreateGroupReplica: "
            "replicationService: %(replicationService)s "
            "RelationName: %(relationName)s "
            "sourceGroup: %(srcGroup)s "
            "targetGroup: %(tgtGroup)s.",
            {'replicationService': replicationService,
             'relationName': relationName,
             'srcGroup': srcGroupInstanceName,
             'tgtGroup': tgtGroupInstanceName})
        # 8 for clone.
        rc, job = conn.InvokeMethod(
            'CreateGroupReplica',
            replicationService,
            RelationshipName=relationName,
            SourceGroup=srcGroupInstanceName,
            TargetGroup=tgtGroupInstanceName,
            SyncType=self.utils.get_num(8, '16'))

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
