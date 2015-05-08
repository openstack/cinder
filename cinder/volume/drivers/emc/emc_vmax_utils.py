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

import datetime
import random
import re
from xml.dom import minidom

from oslo_log import log as logging
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
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
CLONE_REPLICATION_TYPE = 10

EMC_ROOT = 'root/emc'
CONCATENATED = 'concatenated'
CINDER_EMC_CONFIG_FILE_PREFIX = '/etc/cinder/cinder_emc_config_'
CINDER_EMC_CONFIG_FILE_POSTFIX = '.xml'
ISCSI = 'iscsi'
FC = 'fc'
JOB_RETRIES = 60
INTERVAL_10_SEC = 10
INTERVAL = 'storagetype:interval'
RETRIES = 'storagetype:retries'
CIM_ERR_NOT_FOUND = 6


class EMCVMAXUtils(object):
    """Utility class for SMI-S based EMC volume drivers.

    This Utility class is for EMC volume drivers based on SMI-S.
    It supports VMAX arrays.
    """

    def __init__(self, prtcl):
        if not pywbemAvailable:
            LOG.info(_LI(
                "Module PyWBEM not installed. "
                "Install PyWBEM using the python-pywbem package."))
        self.protocol = prtcl

    def find_storage_configuration_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage configuration
        service.

        :param conn: connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundConfigService
        :raises: VolumeBackendAPIException
        """
        foundConfigService = None
        configservices = conn.EnumerateInstanceNames(
            'EMC_StorageConfigurationService')
        for configservice in configservices:
            if storageSystemName == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Storage Configuration Service: "
                          "%(configservice)s.",
                          {'configservice': configservice})
                break

        if foundConfigService is None:
            exceptionMessage = (_("Storage Configuration Service not found "
                                  "on %(storageSystemName)s.")
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
        :raises: VolumeBackendAPIException
        """
        foundConfigService = None
        configservices = conn.EnumerateInstanceNames(
            'EMC_ControllerConfigurationService')
        for configservice in configservices:
            if storageSystemName == configservice['SystemName']:
                foundConfigService = configservice
                LOG.debug("Found Controller Configuration Service: "
                          "%(configservice)s.",
                          {'configservice': configservice})
                break

        if foundConfigService is None:
            exceptionMessage = (_("Controller Configuration Service not found "
                                  "on %(storageSystemName)s.")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundConfigService

    def find_element_composition_service(self, conn, storageSystemName):
        """Given the storage system name, get the element composition service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundElementCompositionService
        :raises: VolumeBackendAPIException
        """
        foundElementCompositionService = None
        elementCompositionServices = conn.EnumerateInstanceNames(
            'Symm_ElementCompositionService')
        for elementCompositionService in elementCompositionServices:
            if storageSystemName == elementCompositionService['SystemName']:
                foundElementCompositionService = elementCompositionService
                LOG.debug("Found Element Composition Service:"
                          "%(elementCompositionService)s."
                          % {'elementCompositionService':
                              elementCompositionService})
                break
        if foundElementCompositionService is None:
            exceptionMessage = (_("Element Composition Service not found "
                                  "on %(storageSystemName)s.")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundElementCompositionService

    def find_storage_relocation_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage relocation service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundStorageRelocationService
        :raises: VolumeBackendAPIException
        """
        foundStorageRelocationService = None
        storageRelocationServices = conn.EnumerateInstanceNames(
            'Symm_StorageRelocationService')
        for storageRelocationService in storageRelocationServices:
            if storageSystemName == storageRelocationService['SystemName']:
                foundStorageRelocationService = storageRelocationService
                LOG.debug(
                    "Found Element Composition Service: "
                    "%(storageRelocationService)s.",
                    {'storageRelocationService': storageRelocationService})
                break

        if foundStorageRelocationService is None:
            exceptionMessage = (_("Storage Relocation Service not found "
                                  "on %(storageSystemName)s.")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundStorageRelocationService

    def find_storage_hardwareid_service(self, conn, storageSystemName):
        """Given the storage system name, get the storage hardware service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundStorageRelocationService
        :raises: VolumeBackendAPIException
        """
        foundHardwareService = None
        storageHardwareservices = conn.EnumerateInstanceNames(
            'EMC_StorageHardwareIDManagementService')
        for storageHardwareservice in storageHardwareservices:
            if storageSystemName == storageHardwareservice['SystemName']:
                foundHardwareService = storageHardwareservice
                LOG.debug("Found Storage Hardware ID Management Service:"
                          "%(storageHardwareservice)s.",
                          {'storageHardwareservice': storageHardwareservice})
                break

        if foundHardwareService is None:
            exceptionMessage = (_("Storage HardwareId mgmt Service not found "
                                  "on %(storageSystemName)s.")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundHardwareService

    def find_replication_service(self, conn, storageSystemName):
        """Given the storage system name, get the replication service.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundRepService
        :raises: VolumeBackendAPIException
        """
        foundRepService = None
        repservices = conn.EnumerateInstanceNames(
            'EMC_ReplicationService')
        for repservice in repservices:
            if storageSystemName == repservice['SystemName']:
                foundRepService = repservice
                LOG.debug("Found Replication Service:"
                          "%(repservice)s",
                          {'repservice': repservice})
                break
        if foundRepService is None:
            exceptionMessage = (_("Replication Service not found "
                                  "on %(storageSystemName)s.")
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
        :raises: VolumeBackendAPIException
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
                "for %(storageSystemName)s.")
                % {'storageSystemName': storageSystemInstanceName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundTierPolicyService

    def wait_for_job_complete(self, conn, job, extraSpecs=None):
        """Given the job wait for it to complete.

        :param conn: connection to the ecom server
        :param job: the job dict
        :param extraSpecs: the extraSpecs dict. Defaults to None
        :returns: int -- the return code
        :returns: errorDesc - the error description string
        """

        jobInstanceName = job['Job']
        if extraSpecs and (INTERVAL in extraSpecs or RETRIES in extraSpecs):
            self._wait_for_job_complete(conn, job, extraSpecs)
        else:
            self._wait_for_job_complete(conn, job)
        jobinstance = conn.GetInstance(jobInstanceName,
                                       LocalOnly=False)
        rc = jobinstance['ErrorCode']
        errorDesc = jobinstance['ErrorDescription']
        LOG.debug("Return code is: %(rc)lu. "
                  "Error Description is: %(errorDesc)s.",
                  {'rc': rc,
                   'errorDesc': errorDesc})

        return rc, errorDesc

    def _wait_for_job_complete(self, conn, job, extraSpecs=None):
        """Given the job wait for it to complete.

        :param conn: connection to the ecom server
        :param job: the job dict
        :param extraSpecs: the extraSpecs dict. Defaults to None
        :raises: loopingcall.LoopingCallDone
        :raises: VolumeBackendAPIException
        """

        def _wait_for_job_complete():
            # Called at an interval until the job is finished.
            maxJobRetries = self._get_max_job_retries(extraSpecs)
            retries = kwargs['retries']
            wait_for_job_called = kwargs['wait_for_job_called']
            if self._is_job_finished(conn, job):
                raise loopingcall.LoopingCallDone()
            if retries > maxJobRetries:
                LOG.error(_LE("_wait_for_job_complete "
                              "failed after %(retries)d "
                              "tries."),
                          {'retries': retries})

                raise loopingcall.LoopingCallDone()
            try:
                kwargs['retries'] = retries + 1
                if not wait_for_job_called:
                    if self._is_job_finished(conn, job):
                        kwargs['wait_for_job_called'] = True
            except Exception as e:
                LOG.error(_LE("Exception: %s.") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for job."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        kwargs = {'retries': 0,
                  'wait_for_job_called': False}

        intervalInSecs = self._get_interval_in_secs(extraSpecs)

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=intervalInSecs).wait()

    def _get_max_job_retries(self, extraSpecs):
        """Get max job retries either default or user defined

        :param extraSpecs: extraSpecs dict
        :returns: JOB_RETRIES or user defined
        """
        if extraSpecs and RETRIES in extraSpecs:
            jobRetries = extraSpecs[RETRIES]
        else:
            jobRetries = JOB_RETRIES
        return int(jobRetries)

    def _get_interval_in_secs(self, extraSpecs):
        """Get interval in secs, either default or user defined

        :param extraSpecs: extraSpecs dict
        :returns: INTERVAL_10_SEC or user defined
        """
        if extraSpecs and INTERVAL in extraSpecs:
            intervalInSecs = extraSpecs[INTERVAL]
        else:
            intervalInSecs = INTERVAL_10_SEC
        return int(intervalInSecs)

    def _is_job_finished(self, conn, job):
        """Check if the job is finished.

        :param conn: connection to the ecom server
        :param job: the job dict
        :returns: boolean -- True if finished; False if not finished;
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
        if jobstate in [2L, 3L, 4L, 32767L]:
            return False
        else:
            return True

    def wait_for_sync(self, conn, syncName):
        """Given the sync name wait for it to fully synchronize.

        :param conn: connection to the ecom server
        :param syncName: the syncName
        :raises: loopingcall.LoopingCallDone
        :raises: VolumeBackendAPIException
        """

        def _wait_for_sync():
            """Called at an interval until the synchronization is finished.

            :raises: loopingcall.LoopingCallDone
            :raises: VolumeBackendAPIException
            """
            retries = kwargs['retries']
            wait_for_sync_called = kwargs['wait_for_sync_called']
            if self._is_sync_complete(conn, syncName):
                raise loopingcall.LoopingCallDone()
            if retries > JOB_RETRIES:
                LOG.error(_LE("_wait_for_sync failed after %(retries)d "
                              "tries."),
                          {'retries': retries})
                raise loopingcall.LoopingCallDone()
            try:
                kwargs['retries'] = retries + 1
                if not wait_for_sync_called:
                    if self._is_sync_complete(conn, syncName):
                        kwargs['wait_for_sync_called'] = True
            except Exception as e:
                LOG.error(_LE("Exception: %s") % six.text_type(e))
                exceptionMessage = (_("Issue encountered waiting for "
                                      "synchronization."))
                LOG.error(exceptionMessage)
                raise exception.VolumeBackendAPIException(exceptionMessage)

        kwargs = {'retries': 0,
                  'wait_for_sync_called': False}
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

        LOG.debug("Percent synced is %(percentSynced)lu.",
                  {'percentSynced': percentSynced})

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
        :param configService: the storage configuration service
        :returns: int -- rc - the return code of the job
        :returns: dict -- jobDict - the job dict
        """
        foundStorageSystemInstanceName = None
        groups = conn.AssociatorNames(
            configService,
            AssocClass='CIM_HostedService')

        if len(groups) > 0:
            foundStorageSystemInstanceName = groups[0]
        else:
            LOG.error(_LE("Cannot get storage system."))
            raise

        return foundStorageSystemInstanceName

    def get_storage_group_from_volume(self, conn, volumeInstanceName):
        """Returns the storage group for a particular volume.

        Given the volume instance name get the associated storage group if it
        is belong to one.

        :param conn: connection to the ecom server
        :param volumeInstanceName: the volume instance name
        :returns: foundStorageGroupInstanceName
        """
        foundStorageGroupInstanceName = None

        storageGroupInstanceNames = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='CIM_DeviceMaskingGroup')

        if len(storageGroupInstanceNames) > 0:
            foundStorageGroupInstanceName = storageGroupInstanceNames[0]

        return foundStorageGroupInstanceName

    def wrap_get_storage_group_from_volume(self, conn, volumeInstanceName):
        """Unit test aid"""
        return self.get_storage_group_from_volume(conn, volumeInstanceName)

    def find_storage_masking_group(self, conn, controllerConfigService,
                                   storageGroupName):
        """Given the storage group name get the storage group.

        :param conn: connection to the ecom server
        :param controllerConfigService: the controllerConfigService
        :param storageGroupName: the name of the storage group you are getting
        :returns: foundStorageMaskingGroupInstanceName
        """
        foundStorageMaskingGroupInstanceName = None

        storageMaskingGroupInstances = (
            conn.Associators(controllerConfigService,
                             ResultClass='CIM_DeviceMaskingGroup'))

        for storageMaskingGroupInstance in \
                storageMaskingGroupInstances:

            if storageGroupName == storageMaskingGroupInstance['ElementName']:
                # Check that it has not been deleted recently.
                instance = self.get_existing_instance(
                    conn, storageMaskingGroupInstance.path)
                if instance is None:
                    # Storage group not found.
                    foundStorageMaskingGroupInstanceName = None
                else:
                    foundStorageMaskingGroupInstanceName = (
                        storageMaskingGroupInstance.path)

                break
        return foundStorageMaskingGroupInstanceName

    def find_storage_system_name_from_service(self, configService):
        """Given any service get the storage system name from it.

        :param configService: the configuration service
        :returns: string -- configService['SystemName'] - storage system name
        """
        return configService['SystemName']

    def find_volume_instance(self, conn, volumeDict, volumeName):
        """Given the volumeDict get the instance from it.

        :param conn: connection to the ecom server
        :param volumeDict: the volume Dict
        :param volumeName: the user friendly name of the volume
        :returns: foundVolumeInstance - the found volume instance
        """
        volumeInstanceName = self.get_instance_name(volumeDict['classname'],
                                                    volumeDict['keybindings'])
        foundVolumeInstance = conn.GetInstance(volumeInstanceName)

        if foundVolumeInstance is None:
            LOG.debug("Volume %(volumeName)s not found on the array.",
                      {'volumeName': volumeName})
        else:
            LOG.debug("Volume name: %(volumeName)s  Volume instance: "
                      "%(vol_instance)s.",
                      {'volumeName': volumeName,
                       'vol_instance': foundVolumeInstance.path})

        return foundVolumeInstance

    def get_host_short_name(self, hostName):
        """Returns the short name for a given qualified host name.

        Checks the host name to see if it is the fully qualified host name
        and returns part before the dot. If there is no dot in the hostName
        the full hostName is returned.

        :param hostName: the fully qualified host name ()
        :returns: string -- the short hostName
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

        :param classname: class name for the volume instance
        :param bindings: volume created from job
        :returns: pywbem.CIMInstanceName -- instanceName
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
            LOG.debug("Ecom IP: %(ecomIp)s Port: %(ecomPort)s.",
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

    def get_ecom_cred_SSL(self, filename):
        """Given the filename get the ecomUser and ecomPasswd.

        :param filename: the path and filename of the emc configuration file
        :returns: string -- ecomUseSSL
        :returns: string -- ecomCACert
        :returns: string -- ecomNoVerification
        """
        ecomUseSSL = self._parse_from_file(filename, 'EcomUseSSL')
        ecomCACert = self._parse_from_file(filename, 'EcomCACert')
        ecomNoVerification = self._parse_from_file(
            filename, 'EcomNoVerification')
        if ecomUseSSL is not None and ecomUseSSL == 'True':
            ecomUseSSL = True
            if ecomNoVerification is not None and ecomNoVerification == 'True':
                ecomNoVerification = True
            return ecomUseSSL, ecomCACert, ecomNoVerification
        else:
            ecomUseSSL = False
            ecomNoVerification = False
            return ecomUseSSL, ecomCACert, ecomNoVerification

    def parse_file_to_get_port_group_name(self, fileName):
        """Parses a file and chooses a port group randomly.

        Given a file, parse it to get all the possible
        portGroupElements and choose one randomly.

        :param fileName: the path and name of the file
        :returns: string -- portGroupName - the name of the port group chosen
        :raises: VolumeBackendAPIException
        """
        portGroupName = None
        myFile = open(fileName, 'r')
        data = myFile.read()
        myFile.close()
        dom = minidom.parseString(data)
        portGroupElements = dom.getElementsByTagName('PortGroup')

        if portGroupElements is not None and len(portGroupElements) > 0:
            portGroupNames = []
            for portGroupElement in portGroupElements:
                if portGroupElement.hasChildNodes():
                    portGroupName = portGroupElement.childNodes[0].nodeValue
                    portGroupName = portGroupName.replace('\n', '')
                    portGroupName = portGroupName.replace('\r', '')
                    portGroupName = portGroupName.replace('\t', '')
                    portGroupName = portGroupName.strip()
                    if portGroupName:
                        portGroupNames.append(portGroupName)

            LOG.debug("portGroupNames: %(portGroupNames)s.",
                      {'portGroupNames': portGroupNames})
            numPortGroups = len(portGroupNames)
            if numPortGroups > 0:
                selectedPortGroupName = (
                    portGroupNames[random.randint(0, numPortGroups - 1)])
                LOG.debug("Returning Selected Port Group: "
                          "%(selectedPortGroupName)s.",
                          {'selectedPortGroupName': selectedPortGroupName})
                return selectedPortGroupName

        # If reaches here without returning yet, raise exception.
        exception_message = (_("No Port Group elements found in config file."))
        LOG.error(exception_message)
        raise exception.VolumeBackendAPIException(data=exception_message)

    def _parse_from_file(self, fileName, stringToParse):
        """Parse the string from XML.

        Remove newlines, tabs and trailing spaces.

        :param fileName: the path and name of the file
        :param stringToParse: the name of the tag to get the value for
        :returns: string -- the returned string; value of the tag
        """
        retString = None
        myFile = open(fileName, 'r')
        data = myFile.read()
        myFile.close()
        dom = minidom.parseString(data)
        tag = dom.getElementsByTagName(stringToParse)
        if tag is not None and len(tag) > 0:
            strXml = tag[0].toxml()
            strXml = strXml.replace('<%s>' % stringToParse, '')
            strXml = strXml.replace('\n', '')
            strXml = strXml.replace('\r', '')
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
            LOG.debug("File %(fileName)s: Fast Policy is %(fastPolicyName)s.",
                      {'fileName': fileName,
                       'fastPolicyName': fastPolicyName})
            return fastPolicyName
        else:
            LOG.info(_LI("Fast Policy not found."))
            return None

    def parse_array_name_from_file(self, fileName):
        """Parse the array name from config file.

        If it is not there then there should only be one array configured to
        the ecom. If there is more than one then erroneous results can occur.

        :param fileName: the path and name of the file
        :returns: string -- arrayName - the array name
        """
        arrayName = self._parse_from_file(fileName, 'Array')
        if arrayName:
            return arrayName
        else:
            LOG.debug("Array not found from config file.")
            return None

    def parse_pool_name_from_file(self, fileName):
        """Parse the pool name from config file.

        If it is not there then we will attempt to get it from extra specs.

        :param fileName: the path and name of the file
        :returns: string -- poolName - the pool name
        """
        poolName = self._parse_from_file(fileName, 'Pool')
        if poolName:
            return poolName
        else:
            LOG.debug("Pool not found from config file.")
            return None

    def parse_slo_from_file(self, fileName):
        """Parse the slo from config file.

        Please note that the string 'NONE' is returned if it is not found.

        :param fileName: the path and name of the file
        :returns: string -- the slo or 'NONE'
        """
        slo = self._parse_from_file(fileName, 'SLO')
        if slo:
            return slo
        else:
            LOG.debug("SLO not in config file. "
                      "Defaulting to NONE.")
            return 'NONE'

    def parse_workload_from_file(self, fileName):
        """Parse the workload from config file.

        Please note that the string 'NONE' is returned if it is not found.

        :param fileName: the path and name of the file
        :returns: string -- the workload or 'NONE'
        """
        workload = self._parse_from_file(fileName, 'Workload')
        if workload:
            return workload
        else:
            LOG.debug("Workload not in config file. "
                      "Defaulting to NONE.")
            return 'NONE'

    def parse_interval_from_file(self, fileName):
        """Parse the interval from config file.

        If it is not there then the default will be used.

        :param fileName: the path and name of the file
        :returns: interval - the interval in seconds
        """
        interval = self._parse_from_file(fileName, 'Interval')
        if interval:
            return interval
        else:
            LOG.debug("Interval not overridden, default of 10 assumed.")
            return None

    def parse_retries_from_file(self, fileName):
        """Parse the retries from config file.

        If it is not there then the default will be used.

        :param fileName: the path and name of the file
        :returns: retries - the max number of retries
        """
        retries = self._parse_from_file(fileName, 'Retries')
        if retries:
            return retries
        else:
            LOG.debug("Retries not overridden, default of 60 assumed.")
            return None

    def parse_pool_instance_id(self, poolInstanceId):
        """Given the instance Id parse the pool name and system name from it.

        Example of pool InstanceId: Symmetrix+0001233455555+U+Pool 0

        :param poolInstanceId: the path and name of the file
        :returns: string -- poolName - the pool name
        :returns: string -- systemName - the system name
        """
        poolName = None
        systemName = None
        endp = poolInstanceId.rfind('+')
        if endp > -1:
            poolName = poolInstanceId[endp + 1:]

        idarray = poolInstanceId.split('+')
        if len(idarray) > 2:
            systemName = self._format_system_name(idarray[0], idarray[1], '+')

        LOG.debug("Pool name: %(poolName)s  System name: %(systemName)s.",
                  {'poolName': poolName, 'systemName': systemName})
        return poolName, systemName

    def _format_system_name(self, part1, part2, sep):
        """Join to make up system name

        :param part1: the prefix
        :param sep: the separator
        :param part2: the postfix
        :returns: systemName
        """
        return ("%(part1)s%(sep)s%(part2)s"
                % {'part1': part1,
                   'sep': sep,
                   'part2': part2})

    def parse_pool_instance_id_v3(self, poolInstanceId):
        """Given the instance Id parse the pool name and system name from it.

        Example of pool InstanceId: Symmetrix+0001233455555+U+Pool 0

        :param poolInstanceId: the path and name of the file
        :returns: poolName - the pool name
        :returns: systemName - the system name
        """
        poolName = None
        systemName = None
        endp = poolInstanceId.rfind('-+-')
        if endp > -1:
            poolName = poolInstanceId[endp + 3:]

        idarray = poolInstanceId.split('-+-')
        if len(idarray) > 2:
            systemName = (
                self._format_system_name(idarray[0], idarray[1], '-+-'))

        LOG.debug("Pool name: %(poolName)s  System name: %(systemName)s.",
                  {'poolName': poolName, 'systemName': systemName})
        return poolName, systemName

    def convert_gb_to_bits(self, strGbSize):
        """Convert GB(string) to bytes(string).

        :param strGB: string -- The size in GB
        :returns: string -- The size in bytes
        """
        strBitsSize = six.text_type(int(strGbSize) * 1024 * 1024 * 1024)

        LOG.debug("Converted %(strGbSize)s GBs to %(strBitsSize)s Bits.",
                  {'strGbSize': strGbSize, 'strBitsSize': strBitsSize})

        return strBitsSize

    def check_if_volume_is_composite(self, conn, volumeInstance):
        """Check if the volume is composite.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: string -- 'True', 'False' or 'Undetermined'
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

    def check_if_volume_is_extendable(self, conn, volumeInstance):
        """Checks if a volume is extendable or not.

        Check underlying CIM_StorageExtent to see if the volume is
        concatenated or not.
        If isConcatenated is true then it is a concatenated and
        extendable.
        If isConcatenated is False and isVolumeComposite is True then
        it is striped and not extendable.
        If isConcatenated is False and isVolumeComposite is False then
        it has one member only but is still extendable.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume instance
        :returns: string -- 'True', 'False' or 'Undetermined'
        """
        isConcatenated = None

        isVolumeComposite = self.check_if_volume_is_composite(
            conn, volumeInstance)

        storageExtentInstances = conn.Associators(
            volumeInstance.path,
            ResultClass='CIM_StorageExtent')

        if len(storageExtentInstances) > 0:
            storageExtentInstance = storageExtentInstances[0]
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
        :returns: int -- compositeType = 2 for concatenated, or 3 for striped
        """
        compositeType = 2
        stripedStr = 'striped'
        try:
            if compositeTypeStr.lower() == stripedStr.lower():
                compositeType = 3
        except KeyError:
            # Default to concatenated if not defined.
            pass

        return compositeType

    def is_volume_bound_to_pool(self, conn, volumeInstance):
        """Check if volume is bound to a pool.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume instance
        :returns: string -- 'True' 'False' or 'Undetermined'
        """
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
        """Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: spaceConsumed
        """
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
        """Get the volume size which is ConsumableBlocks * BlockSize.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: string -- volumeSizeOut
        """
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
        """Determines how many members a volume should contain.

        Based on the size of the proposed volume, the compositeType and the
        memberCount, determine (or validate) how many meta members there
        should be in a volume.

        :param sizeStr: the size in GBs of the proposed volume
        :param memberCount: the initial member count
        :param compositeType: the composite type
        :returns: string -- memberCount
        :returns: string -- errorDesc - the error description
        """
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
        object associated with the volume type.

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
        capacity in GB.

        :param conn: connection to the ecom server
        :param poolName: string value of the storage pool name
        :param storageSystemName: the storage system name
        :returns: tuple -- (total_capacity_gb, free_capacity_gb)
        """
        LOG.debug(
            "Retrieving capacity for pool %(poolName)s on array %(array)s.",
            {'poolName': poolName,
             'array': storageSystemName})

        poolInstanceName = self.get_pool_by_name(
            conn, poolName, storageSystemName)
        if poolInstanceName is None:
            LOG.error(_LE(
                "Unable to retrieve pool instance of %(poolName)s on "
                "array %(array)s."),
                {'poolName': poolName, 'array': storageSystemName})
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
        :returns: foundPoolInstanceName - instance name of storage pool
        """
        foundPoolInstanceName = None
        LOG.debug(
            "storagePoolName: %(poolName)s, storageSystemName: %(array)s.",
            {'poolName': storagePoolName, 'array': storageSystemName})
        poolInstanceNames = conn.EnumerateInstanceNames(
            'EMC_VirtualProvisioningPool')
        for poolInstanceName in poolInstanceNames:
            poolName, systemName = (
                self.parse_pool_instance_id(poolInstanceName['InstanceID']))
            if (poolName == storagePoolName and
                    storageSystemName in systemName):
                # Check that the pool hasn't been recently deleted.
                instance = self.get_existing_instance(conn, poolInstanceName)
                if instance is None:
                    foundPoolInstanceName = None
                else:
                    foundPoolInstanceName = poolInstanceName
                break

        return foundPoolInstanceName

    def convert_bits_to_gbs(self, strBitSize):
        """Convert bytes(string) to GB(string).

        :param strBitSize: string -- The size in bytes
        :returns: int -- The size in GB
        """
        gbSize = int(strBitSize) / 1024 / 1024 / 1024
        return gbSize

    def compare_size(self, size1Str, size2Str):
        """Compare the bit sizes to an approximate.

        :param size1Str: the first bit size (String)
        :param size2Str: the second bit size (String)
        :returns: int -- size1GBs - size2GBs
        """
        size1GBs = self.convert_bits_to_gbs(size1Str)
        size2GBs = self.convert_bits_to_gbs(size2Str)

        return size1GBs - size2GBs

    def get_volumetype_extraspecs(self, volume, volumeTypeId=None):
        """Compare the bit sizes to an approximate.

        :param volume: the volume dictionary
        :param volumeTypeId: Optional override for volume['volume_type_id']
        :returns: dict -- extraSpecs - the extra specs
        """
        extraSpecs = {}

        try:
            if volumeTypeId:
                type_id = volumeTypeId
            else:
                type_id = volume['volume_type_id']
            if type_id is not None:
                extraSpecs = volume_types.get_volume_type_extra_specs(type_id)

        except Exception:
            pass

        return extraSpecs

    def get_volume_type_name(self, volume):
        """Get the volume type name.

        :param volume: the volume dictionary
        :returns: string -- volumeTypeName - the volume type name
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
        """Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param poolInstanceName: the pool instance name
        :returns: the volumes in the pool
        """
        return conn.AssociatorNames(
            poolInstanceName, AssocClass='CIM_AllocatedFromStoragePool',
            ResultClass='CIM_StorageVolume')

    def check_is_volume_bound_to_pool(self, conn, volumeInstance):
        """Check the space consumed of a volume.

        :param conn: the connection information to the ecom server
        :param volumeInstance: the volume Instance
        :returns: string -- 'True', 'False' or 'Undetermined'
        """
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
        """Given the protocol type, return I for iscsi and F for fc.

        :param protocol: iscsi or fc
        :returns: string -- 'I' for iscsi or 'F' for fc
        """
        if protocol.lower() == ISCSI.lower():
            return 'I'
        elif protocol.lower() == FC.lower():
            return 'F'
        else:
            return protocol

    def get_hardware_id_instances_from_array(
            self, conn, hardwareIdManagementService):
        """Get all the hardware ids from an array.

        :param conn: connection to the ecom server
        :param: hardwareIdManagementService - hardware id management service
        :returns: hardwareIdInstances - the list of hardware
            id instances
        """
        hardwareIdInstances = (
            conn.Associators(hardwareIdManagementService,
                             ResultClass='EMC_StorageHardwareID'))

        return hardwareIdInstances

    def truncate_string(self, strToTruncate, maxNum):
        """Truncate a string by taking first and last characters.

        :param strToTruncate: the string to be truncated
        :param maxNum: the maximum number of characters
        :returns: string -- truncated string or original string
        """
        if len(strToTruncate) > maxNum:
            newNum = len(strToTruncate) - maxNum / 2
            firstChars = strToTruncate[:maxNum / 2]
            lastChars = strToTruncate[newNum:]
            strToTruncate = firstChars + lastChars

        return strToTruncate

    def get_array(self, host):
        """Extract the array from the host capabilites.

        :param host: the host object
        :returns: storageSystem - storage system represents the array
        """

        try:
            if '@' in host:
                infoDetail = host.split('@')
            storageSystem = 'SYMMETRIX+' + infoDetail[0]
        except Exception:
            LOG.error(_LE("Error parsing array from host capabilities."))

        return storageSystem

    def get_time_delta(self, startTime, endTime):
        """Get the delta between start and end time.

        :param startTime: the start time
        :param endTime: the end time
        :returns: string -- delta in string H:MM:SS
        """
        delta = endTime - startTime
        return six.text_type(datetime.timedelta(seconds=int(delta)))

    def find_sync_sv_by_target(
            self, conn, storageSystem, target, waitforsync=True):
        """Find the storage synchronized name by target device ID.

        :param conn: connection to the ecom server
        :param storageSystem: the storage system name
        :param target: target volume object
        :param waitforsync: wait for the synchronization to complete if True
        :returns: foundSyncInstanceName
        """
        foundSyncInstanceName = None
        syncInstanceNames = conn.EnumerateInstanceNames(
            'SE_StorageSynchronized_SV_SV')
        for syncInstanceName in syncInstanceNames:
            syncSvTarget = syncInstanceName['SyncedElement']
            if storageSystem != syncSvTarget['SystemName']:
                continue
            if syncSvTarget['DeviceID'] == target['DeviceID']:
                # Check that it hasn't recently been deleted.
                try:
                    conn.GetInstance(syncInstanceName)
                    foundSyncInstanceName = syncInstanceName
                    LOG.debug("Found sync Name: "
                              "%(syncName)s.",
                              {'syncName': foundSyncInstanceName})
                except Exception:
                    foundSyncInstanceName = None
                break

        if foundSyncInstanceName is None:
            LOG.warning(_LW(
                "Storage sync name not found for target %(target)s "
                "on %(storageSystem)s."),
                {'target': target['DeviceID'], 'storageSystem': storageSystem})
        else:
            # Wait for SE_StorageSynchronized_SV_SV to be fully synced.
            if waitforsync:
                self.wait_for_sync(conn, foundSyncInstanceName)

        return foundSyncInstanceName

    def find_group_sync_rg_by_target(
            self, conn, storageSystem, targetRgInstanceName, waitforsync=True):
        """Find the SE_GroupSynchronized_RG_RG instance name by target group.

        :param conn: connection to the ecom server
        :param storageSystem: the storage system name
        :param targetRgInstanceName: target group instance name
        :param waitforsync: wait for synchronization to complete
        :returns: foundSyncInstanceName
        """
        foundSyncInstanceName = None
        groupSyncRgInstanceNames = conn.EnumerateInstanceNames(
            'SE_GroupSynchronized_RG_RG')
        for rgInstanceName in groupSyncRgInstanceNames:
            rgTarget = rgInstanceName['SyncedElement']
            if targetRgInstanceName['InstanceID'] == rgTarget['InstanceID']:
                # Check that it has not recently been deleted.
                try:
                    conn.GetInstance(rgInstanceName)
                    foundSyncInstanceName = rgInstanceName
                    LOG.debug("Found group sync name: "
                              "%(syncName)s.",
                              {'syncName': foundSyncInstanceName})
                except Exception:
                    foundSyncInstanceName = None
                break

        if foundSyncInstanceName is None:
            LOG.warning(_LW(
                "Group sync name not found for target group %(target)s "
                "on %(storageSystem)s."),
                {'target': targetRgInstanceName['InstanceID'],
                 'storageSystem': storageSystem})
        else:
            # Wait for SE_StorageSynchronized_SV_SV to be fully synced.
            if waitforsync:
                self.wait_for_sync(conn, foundSyncInstanceName)

        return foundSyncInstanceName

    def populate_cgsnapshot_status(
            self, context, db, cgsnapshot_id, status='available'):
        """Update cgsnapshot status in the cinder database.

        :param context: the context
        :param db: cinder database
        :param cgsnapshot_id: cgsnapshot id
        :param status: string value reflects the status of the member snapshot
        :returns: snapshots - updated snapshots
        """
        snapshots = db.snapshot_get_all_for_cgsnapshot(context, cgsnapshot_id)
        LOG.info(_LI(
            "Populating status for cgsnapshot: %(id)s."),
            {'id': cgsnapshot_id})
        if snapshots:
            for snapshot in snapshots:
                snapshot['status'] = status
        else:
            LOG.info(_LI("No snapshot found for %(cgsnapshot)s."),
                     {'cgsnapshot': cgsnapshot_id})
        return snapshots

    def get_firmware_version(self, conn, arrayName):
        """Get the firmware version of array.

        :param conn: the connection to the ecom server
        :param arrayName: the array name
        :returns: string -- firmwareVersion
        """
        firmwareVersion = None
        softwareIdentities = conn.EnumerateInstanceNames(
            'symm_storageSystemsoftwareidentity')

        for softwareIdentity in softwareIdentities:
            if arrayName in softwareIdentity['InstanceID']:
                softwareIdentityInstance = conn.GetInstance(softwareIdentity)
                propertiesList = softwareIdentityInstance.properties.items()
                for properties in propertiesList:
                    if properties[0] == 'VersionString':
                        cimProperties = properties[1]
                        firmwareVersion = cimProperties.value
                        break

        return firmwareVersion

    def get_srp_pool_stats(self, conn, arrayName, poolName):
        """Get the totalManagedSpace, remainingManagedSpace.

        :param conn: the connection to the ecom server
        :param arrayName: the array name
        :param poolName: the pool name
        :returns: totalCapacityGb
        :returns: remainingCapacityGb
        """
        totalCapacityGb = -1
        remainingCapacityGb = -1
        storageSystemInstanceName = self.find_storageSystem(conn, arrayName)

        srpPoolInstanceNames = conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='Symm_SRPStoragePool')

        for srpPoolInstanceName in srpPoolInstanceNames:
            poolInstanceID = srpPoolInstanceName['InstanceID']
            poolnameStr, _systemName = (
                self.parse_pool_instance_id_v3(poolInstanceID))

            if six.text_type(poolName) == six.text_type(poolnameStr):
                try:
                    # Check that pool hasnt suddently been deleted.
                    srpPoolInstance = conn.GetInstance(srpPoolInstanceName)
                    propertiesList = srpPoolInstance.properties.items()
                    for properties in propertiesList:
                        if properties[0] == 'TotalManagedSpace':
                            cimProperties = properties[1]
                            totalManagedSpace = cimProperties.value
                            totalCapacityGb = self.convert_bits_to_gbs(
                                totalManagedSpace)
                        elif properties[0] == 'RemainingManagedSpace':
                            cimProperties = properties[1]
                            remainingManagedSpace = cimProperties.value
                            remainingCapacityGb = self.convert_bits_to_gbs(
                                remainingManagedSpace)
                except Exception:
                    pass

        return totalCapacityGb, remainingCapacityGb

    def isArrayV3(self, conn, arrayName):
        """Check if the array is V2 or V3.

        :param conn: the connection to the ecom server
        :param arrayName: the array name
        :returns: boolean
        """
        firmwareVersion = self.get_firmware_version(conn, arrayName)

        m = re.search('^(\d+)', firmwareVersion)
        majorVersion = m.group(0)

        if int(majorVersion) >= 5900:
            return True
        else:
            return False

    def get_pool_and_system_name_v2(
            self, conn, storageSystemInstanceName, poolNameInStr):
        """Get pool instance and system name string for V2.

        :param conn: the connection to the ecom server
        :param storageSystemInstanceName: the storage system instance name
        :param poolNameInStr: the pool name
        :returns: foundPoolInstanceName
        :returns: string -- systemNameStr
        """
        foundPoolInstanceName = None
        vpoolInstanceNames = conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='EMC_VirtualProvisioningPool')

        for vpoolInstanceName in vpoolInstanceNames:
            poolInstanceId = vpoolInstanceName['InstanceID']
            # Example: SYMMETRIX+000195900551+TP+Sol_Innov
            poolnameStr, systemNameStr = self.parse_pool_instance_id(
                poolInstanceId)
            if poolnameStr is not None and systemNameStr is not None:
                if six.text_type(poolNameInStr) == six.text_type(poolnameStr):
                    # check that the pool hasnt recently been deleted.
                    try:
                        conn.GetInstance(vpoolInstanceName)
                        foundPoolInstanceName = vpoolInstanceName
                    except Exception:
                        foundPoolInstanceName = None
                    break

        return foundPoolInstanceName, systemNameStr

    def get_pool_and_system_name_v3(
            self, conn, storageSystemInstanceName, poolNameInStr):
        """Get pool instance and system name string for V2.

        :param conn: the connection to the ecom server
        :param storageSystemInstanceName: the storage system instance name
        :param poolNameInStr: the pool name
        :returns: foundPoolInstanceName
        :returns: string -- systemNameStr
        """
        foundPoolInstanceName = None
        srpPoolInstanceNames = conn.AssociatorNames(
            storageSystemInstanceName,
            ResultClass='Symm_SRPStoragePool')

        for srpPoolInstanceName in srpPoolInstanceNames:
            poolInstanceID = srpPoolInstanceName['InstanceID']
            # Example: SYMMETRIX-+-000196700535-+-SR-+-SRP_1
            poolnameStr, systemNameStr = self.parse_pool_instance_id_v3(
                poolInstanceID)
            if poolnameStr is not None and systemNameStr is not None:
                if six.text_type(poolNameInStr) == six.text_type(poolnameStr):
                    try:
                        conn.GetInstance(srpPoolInstanceName)
                        foundPoolInstanceName = srpPoolInstanceName
                    except Exception:
                        foundPoolInstanceName = None
                    break

        return foundPoolInstanceName, systemNameStr

    def find_storageSystem(self, conn, arrayStr):
        """Find an array instance name given the array name.

        :param conn: the ecom connection
        :param arrayStr: the array Serial number (string)
        :returns: foundPoolInstanceName, the CIM Instance Name of the Pool
        :raises: VolumeBackendAPIException
        """
        foundStorageSystemInstanceName = None
        storageSystemInstanceNames = conn.EnumerateInstanceNames(
            'EMC_StorageSystem')
        for storageSystemInstanceName in storageSystemInstanceNames:
            arrayName = storageSystemInstanceName['Name']
            index = arrayName.find(arrayStr)
            if index > -1:
                foundStorageSystemInstanceName = storageSystemInstanceName

        if foundStorageSystemInstanceName is None:
            exceptionMessage = (_("StorageSystem %(array)s is not found.")
                                % {'array': arrayStr})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        LOG.debug("Array Found: %(array)s.",
                  {'array': arrayStr})

        return foundStorageSystemInstanceName

    def is_in_range(self, volumeSize, maximumVolumeSize, minimumVolumeSize):
        """Check that volumeSize is in range.

        :param volumeSize: volume size
        :param maximumVolumeSize: the max volume size
        :param minimumVolumeSize: the min volume size
        :returns: boolean
        """

        if (long(volumeSize) < long(maximumVolumeSize)) and (
                long(volumeSize) >= long(minimumVolumeSize)):
            return True
        else:
            return False

    def verify_slo_workload(self, slo, workload):
        """Check if SLO and workload values are valid.

        :param slo: Service Level Object e.g bronze
        :param workload: workload e.g DSS
        :returns: boolean
        """
        isValidSLO = False
        isValidWorkload = False

        validSLOs = ['Bronze', 'Silver', 'Gold',
                     'Platinum', 'Diamond', 'Optimized',
                     'NONE']
        validWorkloads = ['DSS_REP', 'DSS', 'OLTP',
                          'OLTP_REP', 'NONE']

        for validSLO in validSLOs:
            if slo == validSLO:
                isValidSLO = True
                break

        for validWorkload in validWorkloads:
            if workload == validWorkload:
                isValidWorkload = True
                break

        if not isValidSLO:
            LOG.error(_LE(
                "SLO: %(slo)s is not valid. Valid values are Bronze, Silver, "
                "Gold, Platinum, Diamond, Optimized, NONE."), {'slo': slo})

        if not isValidWorkload:
            LOG.error(_LE(
                "Workload: %(workload)s is not valid. Valid values are "
                "DSS_REP, DSS, OLTP, OLTP_REP, NONE."), {'workload': workload})

        return isValidSLO, isValidWorkload

    def get_v3_storage_group_name(self, poolName, slo, workload):
        """Determine default v3 storage group from extraSpecs.

        :param poolName: the poolName
        :param slo: the SLO string e.g Bronze
        :param workload: the workload string e.g DSS
        :returns: storageGroupName
        """
        storageGroupName = ("OS-%(poolName)s-%(slo)s-%(workload)s-SG"
                            % {'poolName': poolName,
                               'slo': slo,
                               'workload': workload})
        return storageGroupName

    def strip_short_host_name(self, storageGroupName):
        tempList = storageGroupName.split("-")
        if len(tempList) == 6:
            shorthostName = tempList.pop(1)
            updatedStorageGroup = "-".join(tempList)
            return updatedStorageGroup, shorthostName
        else:
            shorthostName = None
            return storageGroupName, shorthostName

    def _get_fast_settings_from_storage_group(self, storageGroupInstance):
        """Get the emc FAST setting from the storage group.

        :param storageGroupInstance: the storage group instance
        :returns: emcFastSetting
        """
        emcFastSetting = None
        propertiesList = storageGroupInstance.properties.items()
        for properties in propertiesList:
            if properties[0] == 'EMCFastSetting':
                cimProperties = properties[1]
                emcFastSetting = cimProperties.value
                break
        return emcFastSetting

    def get_volume_meta_head(self, conn, volumeInstanceName):
        """Get the head of a meta volume.

        :param conn: the ecom connection
        :param volumeInstanceName: the composite volume instance name
        :returns: the instance name of the meta volume head
        """
        metaHeadInstanceName = None
        metaHeads = conn.AssociatorNames(
            volumeInstanceName,
            ResultClass='EMC_Meta')

        if len(metaHeads) > 0:
            metaHeadInstanceName = metaHeads[0]
        if metaHeadInstanceName is None:
            LOG.info(_LI(
                "Volume  %(volume)s does not have meta device members."),
                {'volume': volumeInstanceName})

        return metaHeadInstanceName

    def get_meta_members_of_composite_volume(
            self, conn, metaHeadInstanceName):
        """Get the member volumes of a composite volume.

        :param conn: the ecom connection
        :param metaHeadInstanceName: head of the composite volume
        :returns: an array containing instance names of member volumes
        """
        metaMembers = conn.AssociatorNames(
            metaHeadInstanceName,
            AssocClass='CIM_BasedOn',
            ResultClass='EMC_PartialAllocOfConcreteExtent')
        LOG.debug("metaMembers: %(members)s.", {'members': metaMembers})
        return metaMembers

    def get_meta_members_capacity_in_bit(self, conn, volumeInstanceNames):
        """Get the capacity in bits of all meta device member volumes.

        :param conn: the ecom connection
        :param volumeInstanceNames: array contains meta device member volumes
        :returns: array contains capacities of each member device in bits
        """
        capacitiesInBit = []
        for volumeInstanceName in volumeInstanceNames:
            volumeInstance = conn.GetInstance(volumeInstanceName)
            numOfBlocks = volumeInstance['ConsumableBlocks']
            blockSize = volumeInstance['BlockSize']
            volumeSizeInbits = numOfBlocks * blockSize
            capacitiesInBit.append(volumeSizeInbits)
        return capacitiesInBit

    def get_existing_instance(self, conn, instanceName):
        """Check that the instance name still exists and return the instance.

        :param conn: the connection to the ecom server
        :param instanceName: the instanceName to be checked
        :returns: instance or None
        """
        instance = None
        try:
            instance = conn.GetInstance(instanceName, LocalOnly=False)
        except pywbem.cim_operations.CIMError as arg:
            instance = self.process_exception_args(arg, instanceName)
        return instance

    def process_exception_args(self, arg, instanceName):
        """Process exception arguments.

        :param arg: the arg list
        :param instanceName: the instance name
        :returns: None
        :raises: VolumeBackendAPIException
        """
        instance = None
        code, desc = arg[0], arg[1]
        if code == CIM_ERR_NOT_FOUND:
            # Object doesn't exist any more.
            instance = None
        else:
            # Something else that we cannot recover from has happened.
            LOG.error(_LE("Exception: %s"), six.text_type(desc))
            exceptionMessage = (_(
                "Cannot verify the existence of object:"
                "%(instanceName)s.")
                % {'instanceName': instanceName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(
                data=exceptionMessage)
        return instance

    def find_replication_service_capabilities(self, conn, storageSystemName):
        """Find the replication service capabilities instance name.

        :param conn: the connection to the ecom server
        :param storageSystemName: the storage system name
        :returns: foundRepServCapability
        """
        foundRepServCapability = None
        repservices = conn.EnumerateInstanceNames(
            'CIM_ReplicationServiceCapabilities')
        for repservCap in repservices:
            if storageSystemName in repservCap['InstanceID']:
                foundRepServCapability = repservCap
                LOG.debug("Found Replication Service Capabilities: "
                          "%(repservCap)s",
                          {'repservCap': repservCap})
                break
        if foundRepServCapability is None:
            exceptionMessage = (_("Replication Service Capability not found "
                                  "on %(storageSystemName)s.")
                                % {'storageSystemName': storageSystemName})
            LOG.error(exceptionMessage)
            raise exception.VolumeBackendAPIException(data=exceptionMessage)

        return foundRepServCapability

    def is_clone_licensed(self, conn, capabilityInstanceName):
        """Check if the clone feature is licensed and enabled.

        :param conn: the connection to the ecom server
        :param capabilityInstanceName: the replication service capabilities
        instance name
        :returns: True if licensed and enabled; False otherwise.
        """
        capabilityInstance = conn.GetInstance(capabilityInstanceName)
        propertiesList = capabilityInstance.properties.items()
        for properties in propertiesList:
            if properties[0] == 'SupportedReplicationTypes':
                cimProperties = properties[1]
                repTypes = cimProperties.value
                LOG.debug("Found supported replication types: "
                          "%(repTypes)s",
                          {'repTypes': repTypes})
                if CLONE_REPLICATION_TYPE in repTypes:
                    # Clone is a supported replication type.
                    LOG.debug("Clone is licensed and enabled.")
                    return True
        return False

    def create_storage_hardwareId_instance_name(
            self, conn, hardwareIdManagementService, initiator):
        """Create storage hardware ID instance name based on the WWPN/IQN.

        :param conn: connection to the ecom server
        :param hardwareIdManagementService: the hardware ID management service
        :param initiator: initiator(IQN or WWPN) to create the hardware ID
            instance
        :returns: hardwareIdList
        """
        hardwareIdList = None
        hardwareIdType = self._get_hardware_type(initiator)
        rc, ret = conn.InvokeMethod(
            'CreateStorageHardwareID',
            hardwareIdManagementService,
            StorageID=initiator,
            IDType=self.get_num(hardwareIdType, '16'))

        if 'HardwareID' in ret:
            LOG.debug("Created hardware ID instance for initiator:"
                      "%(initiator)s rc=%(rc)d, ret=%(ret)s",
                      {'initiator': initiator, 'rc': rc, 'ret': ret})
            hardwareIdList = ret['HardwareID']
        else:
            LOG.warn(_LW("CreateStorageHardwareID failed. initiator: "
                         "%(initiator)s, rc=%(rc)d, ret=%(ret)s."),
                     {'initiator': initiator, 'rc': rc, 'ret': ret})
        return hardwareIdList

    def _get_hardware_type(
            self, initiator):
        """Determine the hardware type based on the initiator.

        :param initiator: initiator(IQN or WWPN)
        :returns: hardwareTypeId
        """
        hardwareTypeId = 0
        try:
            int(initiator, 16)
            hardwareTypeId = 2
        except Exception:
            if 'iqn' in initiator.lower():
                hardwareTypeId = 5
        if hardwareTypeId == 0:
            LOG.warn(_LW("Cannot determine the hardware type."))
        return hardwareTypeId
