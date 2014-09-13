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

import random
import re
from xml.dom.minidom import parseString

import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

try:
    import pywbem
    pywbemAvailable = True
except ImportError:
    pywbemAvailable = False

STORAGEGROUPTYPE = 4
POSTGROUPTYPE = 3

EMC_ROOT = 'root/emc'
CONCATENATED = 'concatenated'
CINDER_EMC_CONFIG_FILE_PREFIX = '/etc/cinder/cinder_emc_config_'
CINDER_EMC_CONFIG_FILE_POSTFIX = '.xml'
ISCSI = 'iscsi'
FC = 'fc'
JOB_RETRIES = 60
INTERVAL_10_SEC = 10


class EMCVMAXUtils(object):
    """Utility class for SMI-S based EMC volume drivers.

    This Utility class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """

    def __init__(self, prtcl):
        if not pywbemAvailable:
            LOG.info(_(
                'Module PyWBEM not installed.  '
                'Install PyWBEM using the python-pywbem package.'))
        self.protocol = prtcl

    def find_storage_configuration_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage configuration service

        :param conn: connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundconfigService
        """
        foundConfigService = None
        configservices = conn.EnumerateInstanceNames(
            'EMC_StorageConfigurationService')
        for configservice in configservices:
            if storageSystemName == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Storage Configuration Service: "
                          "%(configservice)s"
                          % {'configservice': configservice})
                break

        if foundConfigService is None:
            exceptionMessage = (_("Storage Configuration Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundConfigService

    def find_controller_configuration_service(self, conn, storageSystemName):
        """Get the controller config by using the storage service name.

        Given the storage system name, get the controller configuration
        service.

        :param conn: connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundconfigService
        """
        foundConfigService = None
        configservices = conn.EnumerateInstanceNames(
            'EMC_ControllerConfigurationService')
        for configservice in configservices:
            if storageSystemName == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Controller Configuration Service: "
                          "%(configservice)s"
                          % {'configservice': configservice})
                break

        if foundConfigService is None:
            exceptionMessage = (_("Controller Configuration Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundConfigService

    def find_element_composition_service(self, conn, storageSystemName):
        """Given the storage system name, get the element composition service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundElementCompositionService
        """
        foundElementCompositionService = None
        elementCompositionServices = conn.EnumerateInstanceNames(
            'Symm_ElementCompositionService')
        for elementCompositionService in elementCompositionServices:
            if storageSystemName == elementCompositionService['SystemName']:
                foundElementCompositionService = elementCompositionService
                LOG.debug("Found Element Composition Service:"
                          "%(elementCompositionService)s"
                          % {'elementCompositionService':
                              elementCompositionService})
                break
        if foundElementCompositionService is None:
            exceptionMessage = (_("Element Composition Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundElementCompositionService

    def find_storage_relocation_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage relocation service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundStorageRelocationService
        """
        foundStorageRelocationService = None
        storageRelocationServices = conn.EnumerateInstanceNames(
            'Symm_StorageRelocationService')
        for storageRelocationService in storageRelocationServices:
            if storageSystemName == storageRelocationService['SystemName']:
                foundStorageRelocationService = storageRelocationService
                LOG.debug("Found Element Composition Service:"
                          "%(storageRelocationService)s"
                          % {'storageRelocationService':
                             storageRelocationService})
                break

        if foundStorageRelocationService is None:
            exceptionMessage = (_("Storage Relocation Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundStorageRelocationService

    def find_storage_hardwareid_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage hardware service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundStorageRelocationService
        """
        foundHardwareService = None
        storageHardwareservices = conn.EnumerateInstanceNames(
            'EMC_StorageHardwareIDManagementService')
        for storageHardwareservice in storageHardwareservices:
            if storageSystemName == storageHardwareservice['SystemName']:
                foundHardwareService = storageHardwareservice
                LOG.debug("Found Storage Hardware ID Management Service:"
                          "%(storageHardwareservice)s"
                          % {'storageHardwareservice': storageHardwareservice})
                break

        if foundHardwareService is None:
            exceptionMessage = (_("Storage HardwareId mgmt Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundHardwareService

    def find_replication_service(self, conn, storageSystemName):
        """Given the storage system name, get the replication service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundRepService
        """
        foundRepService = None
        repservices = conn.EnumerateInstanceNames(
            'EMC_ReplicationService')
        for repservice in repservices:
            if storageSystemName == repservice['SystemName']:
                foundRepService = repservice
                LOG.debug("Found Replication Service:"
                          "%(repservice)s"
                          % {'repservice': repservice})
                break
        if foundRepService is None:
            exceptionMessage = (_("Replication Service not found "
                                  "on %(storageSystemName)s")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundRepService

    def get_tier_policy_service(self, conn, storageSystemInstanceName):
        """Gets the tier policy service for a given storage system instance.

        Given the storage system instance name, get the existing tier
        policy service.

        :param conn: the connection information to the ecom server
        :param storageSystemInstanceName: the storageSystem instance Name
        :returns: foundTierPolicyService - the tier policy
                                                  service instance name
        """
        foundTierPolicyService = None
        groups = conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='Symm_TierPolicyService',
            AssocClass='CIM_HostedService')

        if len(groups) > 0:
            foundTierPolicyService = groups[0]
        if foundTierPolicyService is None:
            exceptionMessage = (_(
                "Tier Policy Service not found "
                "for %(storageSystemName)s")
                % {'storageSystemName': storageSystemInstanceName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundTierPolicyService

    def wait_for_job_complete(self, conn, job):
        """Given the job wait for it to complete.

        :param conn: connection to the ecom server
        :param job: the job dict
        :returns: rc - the return code
        :returns: errorDesc - the error description string
        """

        jobInstanceName = job['Job']
        self._wait_for_job_complete(conn, job)
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        rc = jobinstance['ErrorCode']
        errorDesc = jobinstance['ErrorDescription']
        LOG.debug('Return code is: %(rc)lu'
                  'Error Description is: %(errorDesc)s'
                  % {'rc': rc,
                     'errorDesc': errorDesc})

        return rc, errorDesc

    def _wait_for_job_complete(self, conn, job):
        """Given the job wait for it to complete.

        :param conn: connection to the ecom server
        :param job: the job dict
        """

        def _wait_for_job_complete():
            """Called at an interval until the job is finished"""
            if self._is_job_finished(conn, job):
                raise loopingcall.LoopingCallDone()
            if self.retries > JOB_RETRIES:
                LOG.error(_("_wait_for_job_complete failed after %(retries)d "
                          "tries") % {'retries': self.retries})

                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.wait_for_job_called:
                    if self._is_job_finished(conn, job):
                        self.wait_for_job_called = True
            except Exception as e:
                LOG.error(_("Exception: %s") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for job."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        self.retries = 0
        self.wait_for_job_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=INTERVAL_10_SEC).wait()

    def _is_job_finished(self, conn, job):
        """Check if the job is finished.
        :param conn: connection to the ecom server
        :param job: the job dict

        :returns: True if finished; False if not finished;
        """

        jobInstanceName = job['Job']
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        jobstate = jobinstance['JobState']
        # From ValueMap of JobState in CIM_ConcreteJob
        # 2L=New, 3L=Starting, 4L=Running, 32767L=Queue Pending
        # ValueMap("2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13..32767,
        # 32768..65535"),
        # Values("New, Starting, Running, Suspended, Shutting Down,
        # Completed, Terminated, Killed, Exception, Service,
        # Query Pending, DMTF Reserved, Vendor Reserved")]
        # NOTE(deva): string matching based on
        #             http://ipmitool.cvs.sourceforge.net/
        #               viewvc/ipmitool/ipmitool/lib/ipmi_chassis.c
        if jobstate in [2L, 3L, 4L, 32767L]:
            return False
        else:
            return True

    def wait_for_sync(self, conn, syncName):
        """Given the sync name wait for it to fully synchronize.

        :param conn: connection to the ecom server
        :param syncName: the syncName
        """

        def _wait_for_sync():
            """Called at an interval until the synchronization is finished"""
            if self._is_sync_complete(conn, syncName):
                raise loopingcall.LoopingCallDone()
            if self.retries > JOB_RETRIES:
                LOG.error(_("_wait_for_sync failed after %(retries)d tries")
                          % {'retries': self.retries})
                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.wait_for_sync_called:
                    if self._is_sync_complete(conn, syncName):
                        self.wait_for_sync_called = True
            except Exception as e:
                LOG.error(_("Exception: %s") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for "
                                      "synchronization."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        self.retries = 0
        self.wait_for_sync_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_sync)
        timer.start(interval=INTERVAL_10_SEC).wait()

    def _is_sync_complete(self, conn, syncName):
        """Check if the job is finished.
        :param conn: connection to the ecom server
        :param syncName: the sync name

        :returns: True if fully synchronized; False if not;
        """
        syncInstance = conn.GetInstance(syncName,
                                        LocalOnly=False)
        percentSynced = syncInstance['PercentSynced']

        if percentSynced < 100:
            return False
        else:
            return True

    def get_num(self, numStr, datatype):
        """Get the ecom int from the number.

        :param numStr: the number in string format
        :param datatype: the type to convert it to
        :returns: result
        """
        try:
            result = {
                '8': pywbem.Uint8(numStr),
                '16': pywbem.Uint16(numStr),
                '32': pywbem.Uint32(numStr),
                '64': pywbem.Uint64(numStr)
            }
            result = result.get(datatype, numStr)
        except NameError:
            result = numStr

        return result

    def find_storage_system(self, conn, configService):
        """Finds the storage system for a particular config service.

        Given the storage configuration service get the CIM_StorageSystem
        from it.

        :param conn: the connection to the ecom server
        :param storageConfigService: the storage configuration service
        :returns: rc - the return code of the job
        :returns: jobDict - the job dict
        """
        foundStorageSystemInstanceName = None
        groups = conn.AssociatorNames(
            configService,
            AssocClass='CIM_HostedService')

        if len(groups) > 0:
            foundStorageSystemInstanceName = groups[0]
        else:
            exception_message = (_("Cannot get storage system"))
            LOG.error(exception_message)
            raise

        return foundStorageSystemInstanceName

    def get_storage_group_from_volume(self, conn, volumeInstanceName):
        """Returns the storage group for a particular volume.

        Given the volume instance name get the associated storage group if it
        is belong to one

        :param conn: connection to the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: foundStorageGroupInstanceName - the storage group
                                                  instance name
        """
        foundStorageGroupInstanceName = None

        storageGroupInstanceNames = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='CIM_DeviceMaskingGroup')

        if len(storageGroupInstanceNames) > 0:
            foundStorageGroupInstanceName = storageGroupInstanceNames[0]

        return foundStorageGroupInstanceName

    def find_storage_masking_group(self, conn, controllerConfigService,
                                   storageGroupName):
        """Given the storage group name get the storage group.

        :param conn: connection to the ecom server
        :param controllerConfigService: the controllerConfigService
        :param storageGroupName: the name of the storage group you are getting
        :param foundStorageGroup: storage group instance name
        """
        foundStorageMaskingGroupInstanceName = None

        storageMaskingGroupInstanceNames = (
            conn.AssociatorNames(controllerConfigService,
                                 ResultClass='CIM_DeviceMaskingGroup'))

        for storageMaskingGroupInstanceName in \
                storageMaskingGroupInstanceNames:
            storageMaskingGroupInstance = conn.GetInstance(
                storageMaskingGroupInstanceName)
            if storageGroupName == storageMaskingGroupInstance['ElementName']:
                foundStorageMaskingGroupInstanceName = (
                    storageMaskingGroupInstanceName)
                break
        return foundStorageMaskingGroupInstanceName

    def find_storage_system_name_from_service(self, configService):
        """Given any service get the storage system name from it.

        :param configService: the configuration service
        :returns: configService['SystemName'] - storage system name (String)
        """
        return configService['SystemName']

    def find_volume_instance(self, conn, volumeDict, volumeName):
        """Given the volumeDict get the instance from it.

        :param conn: connection to the ecom server
        :param volumeDict: the volume Dict
        :param volumeName: the user friendly name of the volume
        :returns: foundVolumeInstance - the volume instance
        """
        volumeInstanceName = self.get_instance_name(volumeDict['classname'],
                                                    volumeDict['keybindings'])
        foundVolumeInstance = conn.GetInstance(volumeInstanceName)

        if foundVolumeInstance is None:
            LOG.debug("Volume %(volumeName)s not found on the array."
                      % {'volumeName': volumeName})
        else:
            LOG.debug("Volume name: %(volumeName)s  Volume instance: "
                      "%(vol_instance)s."
                      % {'volumeName': volumeName,
                         'vol_instance': foundVolumeInstance.path})

        return foundVolumeInstance

    def get_host_short_name(self, hostName):
        """Returns the short name for a given qualified host name.

        Checks the host name to see if it is the fully qualified host name
        and returns part before the dot. If there is no dot in the hostName
        the full hostName is returned.

        :param hostName: the fully qualified host name ()
        :param shortHostName: the short hostName
        """
        shortHostName = None

        hostArray = hostName.split('.')
        if len(hostArray) > 2:
            shortHostName = hostArray[0]
        else:
            shortHostName = hostName

        return shortHostName

    def get_instance_name(self, classname, bindings):
        """Get the instance from the classname and bindings.

        NOTE:  This exists in common too...will be moving it to other file
        where both common and masking can access it

        :param classname: class name for the volume instance
        :param bindings: volume created from job
        :returns: foundVolumeInstance - the volume instance

        """
        instanceName = None
        try:
            instanceName = pywbem.CIMInstanceName(
                classname,
                namespace=EMC_ROOT,
                keybindings=bindings)
        except NameError:
            instanceName = None

        return instanceName

    def get_ecom_server(self, filename):
        """Given the file name get the ecomPort and ecomIP from it.

        :param filename: the path and file name of the emc configuration file
        :returns: ecomIp - the ecom IP address
        :returns: ecomPort - the ecom port
        """

        ecomIp = self._parse_from_file(filename, 'EcomServerIp')
        ecomPort = self._parse_from_file(filename, 'EcomServerPort')
        if ecomIp is not None and ecomPort is not None:
            LOG.debug("Ecom IP: %(ecomIp)s Port: %(ecomPort)s",
                      {'ecomIp': ecomIp, 'ecomPort': ecomPort})
            return ecomIp, ecomPort
        else:
            LOG.debug("Ecom server not found.")
            return None

    def get_ecom_cred(self, filename):
        """Given the filename get the ecomUser and ecomPasswd.

        :param filename: the path and filename of the emc configuration file
        :returns: ecomUser - the ecom user
        :returns: ecomPasswd - the ecom password
        """

        ecomUser = self._parse_from_file(filename, 'EcomUserName')
        ecomPasswd = self._parse_from_file(filename, 'EcomPassword')
        if ecomUser is not None and ecomPasswd is not None:
            return ecomUser, ecomPasswd
        else:
            LOG.debug("Ecom user not found.")
            return None

    def parse_file_to_get_port_group_name(self, fileName):
        """Parses a file and chooses a port group randomly.

        Given a file, parse it to get all the possible portGroups and choose
        one randomly.

        :param fileName: the path and name of the file
        :returns: portGroupName - the name of the port group chosen
        """
        portGroupName = None
        myFile = open(fileName, 'r')
        data = myFile.read()
        myFile.close()
        dom = parseString(data)
        portGroups = dom.getElementsByTagName('PortGroups')
        if portGroups is not None and len(portGroups) > 0:
            portGroupsXml = portGroups[0].toxml()
            portGroupsXml = portGroupsXml.replace('<PortGroups>', '')
            portGroupsXml = portGroupsXml.replace('</PortGroups>', '')
            portGroupsXml = portGroupsXml.replace('<PortGroup>', '|')
            portGroupsXml = portGroupsXml.replace('</PortGroup>', '')
            portGroupsXml = portGroupsXml.replace('\n', '')
            portGroupsXml = portGroupsXml.replace('\t', '')
            portGroupsXml = portGroupsXml[1:]
            # convert the | separated string to a list
            portGroupNames = (
                [s.strip() for s in portGroupsXml.split('|') if s])

            numPortGroups = len(portGroupNames)

            portGroupName = (
                portGroupNames[random.randint(0, numPortGroups - 1)])

            return portGroupName
        else:
            exception_message = (_("Port Group name not found."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _parse_from_file(self, fileName, stringToParse):
        """Parse the string from XML.

        Remove newlines, tabs, and trailing spaces.

        :param fileName: the path and name of the file
        :returns: retString - the returned string
        """
        retString = None
        myFile = open(fileName, 'r')
        data = myFile.read()
        myFile.close()
        dom = parseString(data)
        tag = dom.getElementsByTagName(stringToParse)
        if tag is not None and len(tag) > 0:
            strXml = tag[0].toxml()
            strXml = strXml.replace('<%s>' % stringToParse, '')
            strXml = strXml.replace('\n', '')
            strXml = strXml.replace('\t', '')
            retString = strXml.replace('</%s>' % stringToParse, '')
            retString = retString.strip()
        return retString

    def parse_fast_policy_name_from_file(self, fileName):
        """Parse the fast policy name from config file.

        If it is not there, then NON FAST is assumed.

        :param fileName: the path and name of the file
        :returns: fastPolicyName - the fast policy name
        """

        fastPolicyName = self._parse_from_file(fileName, 'FastPolicy')
        if fastPolicyName:
            LOG.debug("File %(fileName)s: Fast Policy is %(fastPolicyName)s"
                      % {'fileName': fileName,
                         'fastPolicyName': fastPolicyName})
        else:
            LOG.info(_("Fast Policy not found."))
        return fastPolicyName

    def parse_array_name_from_file(self, fileName):
        """Parse the array name from config file.

        If it is not there then there should only be one array configured to
        the ecom. If there is more than one then erroneous results can occur.

        :param fileName: the path and name of the file
        :returns: arrayName - the array name
        """
        arrayName = self._parse_from_file(fileName, 'Array')
        if not arrayName:
            LOG.debug("Array not found from config file.")
        return arrayName

    def parse_pool_name_from_file(self, fileName):
        """Parse the pool name from config file.

        If it is not there then we will attempt to get it from extra specs.

        :param fileName: the path and name of the file
        :returns: poolName - the pool name
        """
        poolName = self._parse_from_file(fileName, 'Pool')
        if not poolName:
            LOG.debug("Pool not found from config file.")

        return poolName

    def parse_pool_instance_id(self, poolInstanceId):
        """Given the instance Id parse the pool name and system name from it.

        Example of pool InstanceId: Symmetrix+0001233455555+U+Pool 0

        :param poolInstanceId: the path and name of the file
        :returns: poolName - the pool name
        :returns: systemName - the system name
        """
        poolName = None
        systemName = None
        endp = poolInstanceId.rfind('+')
        if endp > -1:
            poolName = poolInstanceId[endp + 1:]

        idarray = poolInstanceId.split('+')
        if len(idarray) > 2:
            systemName = idarray[0] + '+' + idarray[1]

        LOG.debug("Pool name: %(poolName)s  System name: %(systemName)s."
                  % {'poolName': poolName, 'systemName': systemName})
        return poolName, systemName

    def convert_gb_to_bits(self, strGbSize):
        """Convert GB(string) to bits(string).

        :param strGB: string -- The size in GB
        :returns: strBitsSize string -- The size in bits
        """
        strBitsSize = six.text_type(int(strGbSize) * 1024 * 1024 * 1024)

        LOG.debug("Converted %(strGbSize)s GBs to %(strBitsSize)s Bits"
                  % {'strGbSize': strGbSize, 'strBitsSize': strBitsSize})

        return strBitsSize

    def check_if_volume_is_composite(self, conn, volumeInstance):
        """Check if the volume is composite.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: 'True', 'False' or 'Undetermined'
        """
        propertiesList = volumeInstance.properties.items()
        for properties in propertiesList:
            if properties[0] == 'IsComposite':
                cimProperties = properties[1]

                if 'True' in six.text_type(cimProperties.value):
                    return 'True'
                elif 'False' in six.text_type(cimProperties.value):
                    return 'False'
                else:
                    return 'Undetermined'
        return 'Undetermined'

    def get_assoc_pool_from_volume(self, conn, volumeInstanceName):
        """Give the volume instance get the associated pool instance

        :param conn: connection to the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: foundPoolInstanceName
        """
        foundPoolInstanceName = None
        foundPoolInstanceNames = (
            conn.AssociatorNames(volumeInstanceName,
                                 ResultClass='EMC_VirtualProvisioningPool'))
        if len(foundPoolInstanceNames) > 0:
            foundPoolInstanceName = foundPoolInstanceNames[0]
        return foundPoolInstanceName

    def check_if_volume_is_concatenated(self, conn, volumeInstance):
        """Checks if a volume is concatenated or not.

        Check underlying CIM_StorageExtent to see if the volume is
        concatenated or not.
        If isConcatenated is true then it is a composite
        If isConcatenated is False and isVolumeComposite is True then
            it is a striped
        If isConcatenated is False and isVolumeComposite is False then
            it has no composite type and we can proceed.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume instance
        :returns: 'True', 'False' or 'Undetermined'
        """
        isConcatenated = None

        isVolumeComposite = self.check_if_volume_is_composite(
            conn, volumeInstance)

        storageExtentInstanceNames = conn.AssociatorNames(
            volumeInstance.path,
            ResultClass='CIM_StorageExtent')

        if len(storageExtentInstanceNames) > 0:
            storageExtentInstanceName = storageExtentInstanceNames[0]
            storageExtentInstance = conn.GetInstance(storageExtentInstanceName)

            propertiesList = storageExtentInstance.properties.items()
            for properties in propertiesList:
                if properties[0] == 'IsConcatenated':
                    cimProperties = properties[1]
                    isConcatenated = six.text_type(cimProperties.value)

                if isConcatenated is not None:
                    break

        if 'True' in isConcatenated:
            return 'True'
        elif 'False' in isConcatenated and 'True' in isVolumeComposite:
            return 'False'
        elif 'False' in isConcatenated and 'False' in isVolumeComposite:
            return 'True'
        else:
            return 'Undetermined'

    def get_composite_type(self, compositeTypeStr):
        """Get the int value of composite type.

        The default is '2' concatenated.

        :param compositeTypeStr: 'concatenated' or 'striped'. Cannot be None
        :returns: compositeType = 2 or 3
        """
        compositeType = 2
        stripedStr = 'striped'
        try:
            if compositeTypeStr.lower() == stripedStr.lower():
                compositeType = 3
        except KeyError:
            # Default to concatenated if not defined
            pass

        return compositeType

    def is_volume_bound_to_pool(self, conn, volumeInstance):
        '''Check if volume is bound to a pool.

        :param conn: the connection information to the ecom server
        :param storageServiceInstanceName: the storageSystem instance Name
        :returns: foundIsSupportsTieringPolicies - true/false
        '''
        propertiesList = volumeInstance.properties.items()
        for properties in propertiesList:
            if properties[0] == 'EMCIsBound':
                cimProperties = properties[1]

                if 'True' in six.text_type(cimProperties.value):
                    return 'True'
                elif 'False' in six.text_type(cimProperties.value):
                    return 'False'
                else:
                    return 'Undetermined'
        return 'Undetermined'

    def get_space_consumed(self, conn, volumeInstance):
        '''Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: spaceConsumed
        '''
        foundSpaceConsumed = None
        unitnames = conn.References(
            volumeInstance, ResultClass='CIM_AllocatedFromStoragePool',
            Role='Dependent')

        for unitname in unitnames:
            propertiesList = unitname.properties.items()
            for properties in propertiesList:
                if properties[0] == 'SpaceConsumed':
                    cimProperties = properties[1]
                    foundSpaceConsumed = cimProperties.value
                    break
            if foundSpaceConsumed is not None:
                break

        return foundSpaceConsumed

    def get_volume_size(self, conn, volumeInstance):
        '''Get the volume size.

        ConsumableBlocks * BlockSize

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: volumeSizeOut
        '''
        volumeSizeOut = 'Undetermined'
        numBlocks = 0
        blockSize = 0

        propertiesList = volumeInstance.properties.items()
        for properties in propertiesList:
            if properties[0] == 'ConsumableBlocks':
                cimProperties = properties[1]
                numBlocks = int(cimProperties.value)
            if properties[0] == 'BlockSize':
                cimProperties = properties[1]
                blockSize = int(cimProperties.value)
            if blockSize > 0 and numBlocks > 0:
                break
        if blockSize > 0 and numBlocks > 0:
            volumeSizeOut = six.text_type(numBlocks * blockSize)

        return volumeSizeOut

    def determine_member_count(self, sizeStr, memberCount, compositeType):
        '''Determines how many members a volume should contain.

        Based on the size of the proposed volume, the compositeType and the
        memberCount, determine (or validate) how many meta members there
        should be in a volume.

        :param sizeStr: the size in GBs of the proposed volume
        :param memberCount: the initial member count
        :param compositeType: the composite type
        :returns: memberCount - string
        :returns: errorDesc - the error description
        '''
        errorDesc = None
        if compositeType in 'concatenated' and int(sizeStr) > 240:
            newMemberCount = int(sizeStr) / 240
            modular = int(sizeStr) % 240
            if modular > 0:
                newMemberCount += 1
            memberCount = six.text_type(newMemberCount)

        if compositeType in 'striped':
            metaSize = int(sizeStr) / int(memberCount)
            modular = int(sizeStr) % int(memberCount)
            metaSize = metaSize + modular
            if metaSize > 240:
                errorDesc = ('Meta Size is greater than maximum allowed meta '
                             'size')

        return memberCount, errorDesc

    def get_extra_specs_by_volume_type_name(self, volumeTypeName):
        """Gets the extra specs associated with a volume type.

        Given the string value of the volume type name, get the extra specs
        object associated with the volume type

        :param volumeTypeName: string value of the volume type name
        :returns: extra_specs - extra specs object
        """
        ctxt = context.get_admin_context()
        volume_type = volume_types.get_volume_type_by_name(
            ctxt, volumeTypeName)
        extra_specs = volume_type['extra_specs']
        return extra_specs

    def get_pool_capacities(self, conn, poolName, storageSystemName):
        """Get the total and remaining capacity in GB for a storage pool.

        Given the storage pool name, get the total capacity and remaining
        capacity in GB

        :param conn: connection to the ecom server
        :param storagePoolName: string value of the storage pool name
        :returns: total_capacity_gb - total capacity of the storage pool in GB
        :returns: free_capacity_gb - remaining capacity of the
                                     storage pool in GB
        """
        LOG.debug("Retrieving capacity for pool %(poolName)s on array "
                  "%(array)s"
                  % {'poolName': poolName,
                     'array': storageSystemName})

        poolInstanceName = self.get_pool_by_name(
            conn, poolName, storageSystemName)
        if poolInstanceName is None:
            LOG.error("Unable to retrieve pool instance of %(poolName)s on "
                      "array %(array)s"
                      % {'poolName': poolName,
                         'array': storageSystemName})
            return (0, 0)
        storagePoolInstance = conn.GetInstance(
            poolInstanceName, LocalOnly=False)
        total_capacity_gb = self.convert_bits_to_gbs(
            storagePoolInstance['TotalManagedSpace'])
        allocated_capacity_gb = self.convert_bits_to_gbs(
            storagePoolInstance['EMCSubscribedCapacity'])
        free_capacity_gb = total_capacity_gb - allocated_capacity_gb
        return (total_capacity_gb, free_capacity_gb)

    def get_pool_by_name(self, conn, storagePoolName, storageSystemName):
        """Returns the instance name associated with a storage pool name.

        :param conn: connection to the ecom server
        :param storagePoolName: string value of the storage pool name
        :param storageSystemName: string value of array
        :returns: poolInstanceName - instance name of storage pool
        """
        poolInstanceName = None
        LOG.debug("storagePoolName: %(poolName)s, storageSystemName: %(array)s"
                  % {'poolName': storagePoolName,
                     'array': storageSystemName})
        poolInstanceNames = conn.EnumerateInstanceNames(
            'EMC_VirtualProvisioningPool')
        for pool in poolInstanceNames:
            poolName, systemName = (
                self.parse_pool_instance_id(pool['InstanceID']))
            if (poolName == storagePoolName and
                    storageSystemName in systemName):
                poolInstanceName = pool

        return poolInstanceName

    def convert_bits_to_gbs(self, strBitSize):
        """Convert Bits(string) to GB(string).

        :param strBitSize: string -- The size in bits
        :returns: gbSize string -- The size in GB
        """
        gbSize = int(strBitSize) / 1024 / 1024 / 1024
        return gbSize

    def compare_size(self, size1Str, size2Str):
        """Compare the bit sizes to an approximate.

        :param size1Str: the first bit size (String)
        :param size2Str: the second bit size (String)
        :returns: size1GBs - size2GBs (int)
        """
        size1GBs = self.convert_bits_to_gbs(size1Str)
        size2GBs = self.convert_bits_to_gbs(size2Str)

        return size1GBs - size2GBs

    def get_volumetype_extraspecs(self, volume):
        """Compare the bit sizes to an approximate.

        :param volume: the volume dictionary
        :returns: extraSpecs - the extra specs
        """
        extraSpecs = {}

        try:
            type_id = volume['volume_type_id']
            if type_id is not None:
                extraSpecs = volume_types.get_volume_type_extra_specs(type_id)

        except Exception:
            pass

        return extraSpecs

    def get_volume_type_name(self, volume):
        """Get the volume type name.

        :param volume: the volume dictionary
        :returns: volumeTypeName - the volume type name
        """
        volumeTypeName = None

        ctxt = context.get_admin_context()
        typeId = volume['volume_type_id']
        if typeId is not None:
            volumeType = volume_types.get_volume_type(ctxt, typeId)
            volumeTypeName = volumeType['name']

        return volumeTypeName

    def parse_volume_type_from_filename(self, emcConfigFile):
        """Parse the volume type from the file (if it exists).

        :param emcConfigFile: the EMC configuration file
        :returns: volumeTypeName - the volume type name
        """
        volumeTypeName = None

        m = re.search('/etc/cinder/cinder_emc_config_(.+?).xml', emcConfigFile)
        if m:
            volumeTypeName = m.group(1)

        return volumeTypeName

    def get_volumes_from_pool(self, conn, poolInstanceName):
        '''Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: spaceConsumed
        '''
        return conn.AssociatorNames(
            poolInstanceName, AssocClass='CIM_AllocatedFromStoragePool',
            ResultClass='CIM_StorageVolume')

    def check_is_volume_bound_to_pool(self, conn, volumeInstance):
        '''Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: spaceConsumed
        '''
        foundSpaceConsumed = None
        unitnames = conn.References(
            volumeInstance, ResultClass='CIM_AllocatedFromStoragePool',
            Role='Dependent')

        for unitname in unitnames:
            propertiesList = unitname.properties.items()
            for properties in propertiesList:
                if properties[0] == 'EMCBoundToThinStoragePool':
                    cimProperties = properties[1]
                    foundSpaceConsumed = cimProperties.value
                    break
            if foundSpaceConsumed is not None:
                break
        if 'True' in six.text_type(cimProperties.value):
            return 'True'
        elif 'False' in six.text_type(cimProperties.value):
            return 'False'
        else:
            return 'Undetermined'

    def get_short_protocol_type(self, protocol):
        '''Given the protocol type, return I for iscsi and F for fc

        :param protocol: iscsi or fc
        :returns: 'I' or 'F'
        '''
        if protocol.lower() == ISCSI.lower():
            return 'I'
        elif protocol.lower() == FC.lower():
            return 'F'
        else:
            return protocol

    def get_hardware_id_instance_names_from_array(
            self, conn, hardwareIdManagementService):
        """Get all the hardware ids from an array.

        :param conn: connection to the ecom server
        :param: hardwareIdManagementService - hardware id management service
        :returns: hardwareIdInstanceNames - the list of hardware
                                            id instance names
        """
        hardwareIdInstanceNames = (
            conn.AssociatorNames(hardwareIdManagementService,
                                 ResultClass='SE_StorageHardwareID'))

        return hardwareIdInstanceNames

    def find_ip_protocol_endpoint(self, conn, storageSystemName):
        '''Find the IP protocol endpoint for ISCSI.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundIpAddress
        '''
        foundIpAddress = None
        ipProtocolEndpointInstances = conn.EnumerateInstances(
            'CIM_IPProtocolEndpoint')

        for ipProtocolEndpointInstance in ipProtocolEndpointInstances:
            ipStorageSystemName = (
                ipProtocolEndpointInstance.path['SystemName'])
            if storageSystemName in ipStorageSystemName:
                propertiesList = (
                    ipProtocolEndpointInstance.properties.items())
                for properties in propertiesList:
                    if properties[0] == 'IPv4Address':
                        cimProperties = properties[1]
                        foundIpAddress = cimProperties.value
                        if (foundIpAddress == '127.0.0.1'
                                or foundIpAddress == '0.0.0.0'):
                            foundIpAddress = None
                        else:
                            break
            if foundIpAddress is not None:
                break

        return foundIpAddress
