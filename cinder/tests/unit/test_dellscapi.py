#    Copyright (c) 2015 Dell Inc.
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

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume.drivers.dell import dell_storagecenter_api

import mock
from requests import models

import uuid

LOG = logging.getLogger(__name__)

# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.


@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   '__init__',
                   return_value=None)
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'open_connection')
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'close_connection')
class DellSCSanAPITestCase(test.TestCase):

    '''DellSCSanAPITestCase

    Class to test the Storage Center API using Mock.
    '''

    SC = {u'IPv6ManagementIPPrefix': 128,
          u'connectionError': u'',
          u'instanceId': u'64702',
          u'scSerialNumber': 64702,
          u'dataProgressionRunning': False,
          u'hostOrIpAddress': u'192.168.0.80',
          u'userConnected': True,
          u'portsBalanced': True,
          u'managementIp': u'192.168.0.80',
          u'version': u'6.5.1.269',
          u'location': u'',
          u'objectType': u'StorageCenter',
          u'instanceName': u'Storage Center 64702',
          u'statusMessage': u'',
          u'status': u'Up',
          u'flashOptimizedConfigured': False,
          u'connected': True,
          u'operationMode': u'Normal',
          u'userName': u'Admin',
          u'nonFlashOptimizedConfigured': True,
          u'name': u'Storage Center 64702',
          u'scName': u'Storage Center 64702',
          u'notes': u'',
          u'serialNumber': 64702,
          u'raidRebalanceRunning': False,
          u'userPasswordExpired': False,
          u'contact': u'',
          u'IPv6ManagementIP': u'::'}

    VOLUME = {u'instanceId': u'64702.3494',
              u'scSerialNumber': 64702,
              u'replicationSource': False,
              u'liveVolume': False,
              u'vpdId': 3496,
              u'objectType': u'ScVolume',
              u'index': 3494,
              u'volumeFolderPath': u'devstackvol/fcvm/',
              u'hostCacheEnabled': False,
              u'usedByLegacyFluidFsNasVolume': False,
              u'inRecycleBin': False,
              u'volumeFolderIndex': 17,
              u'instanceName': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
              u'statusMessage': u'',
              u'status': u'Up',
              u'storageType': {u'instanceId': u'64702.1',
                               u'instanceName': u'Assigned - Redundant - 2 MB',
                               u'objectType': u'ScStorageType'},
              u'cmmDestination': False,
              u'replicationDestination': False,
              u'volumeFolder': {u'instanceId': u'64702.17',
                                u'instanceName': u'fcvm',
                                u'objectType': u'ScVolumeFolder'},
              u'deviceId': u'6000d31000fcbe000000000000000da8',
              u'active': True,
              u'portableVolumeDestination': False,
              u'deleteAllowed': True,
              u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
              u'scName': u'Storage Center 64702',
              u'secureDataUsed': False,
              u'serialNumber': u'0000fcbe-00000da8',
              u'replayAllowed': True,
              u'flashOptimized': False,
              u'configuredSize': u'1.073741824E9 Bytes',
              u'mapped': False,
              u'cmmSource': False}

    VOLUME_LIST = [{u'instanceId': u'64702.3494',
                    u'scSerialNumber': 64702,
                    u'replicationSource': False,
                    u'liveVolume': False,
                    u'vpdId': 3496,
                    u'objectType': u'ScVolume',
                    u'index': 3494,
                    u'volumeFolderPath': u'devstackvol/fcvm/',
                    u'hostCacheEnabled': False,
                    u'usedByLegacyFluidFsNasVolume': False,
                    u'inRecycleBin': False,
                    u'volumeFolderIndex': 17,
                    u'instanceName':
                        u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
                    u'statusMessage': u'',
                    u'status': u'Up',
                    u'storageType': {u'instanceId': u'64702.1',
                                     u'instanceName':
                                     u'Assigned - Redundant - 2 MB',
                                     u'objectType': u'ScStorageType'},
                    u'cmmDestination': False,
                    u'replicationDestination': False,
                    u'volumeFolder': {u'instanceId': u'64702.17',
                                      u'instanceName': u'fcvm',
                                      u'objectType': u'ScVolumeFolder'},
                    u'deviceId': u'6000d31000fcbe000000000000000da8',
                    u'active': True,
                    u'portableVolumeDestination': False,
                    u'deleteAllowed': True,
                    u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
                    u'scName': u'Storage Center 64702',
                    u'secureDataUsed': False,
                    u'serialNumber': u'0000fcbe-00000da8',
                    u'replayAllowed': True,
                    u'flashOptimized': False,
                    u'configuredSize': u'1.073741824E9 Bytes',
                    u'mapped': False,
                    u'cmmSource': False}]

    # Volume list that contains multiple volumes
    VOLUME_LIST_MULTI_VOLS = [
        {u'instanceId': u'64702.3494',
         u'scSerialNumber': 64702,
         u'replicationSource': False,
         u'liveVolume': False,
         u'vpdId': 3496,
         u'objectType': u'ScVolume',
         u'index': 3494,
         u'volumeFolderPath': u'devstackvol/fcvm/',
         u'hostCacheEnabled': False,
         u'usedByLegacyFluidFsNasVolume': False,
         u'inRecycleBin': False,
         u'volumeFolderIndex': 17,
         u'instanceName':
                        u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
         u'statusMessage': u'',
         u'status': u'Up',
                    u'storageType': {u'instanceId': u'64702.1',
                                     u'instanceName':
                                     u'Assigned - Redundant - 2 MB',
                                     u'objectType': u'ScStorageType'},
                    u'cmmDestination': False,
                    u'replicationDestination': False,
                    u'volumeFolder': {u'instanceId': u'64702.17',
                                      u'instanceName': u'fcvm',
                                      u'objectType': u'ScVolumeFolder'},
                    u'deviceId': u'6000d31000fcbe000000000000000da8',
                    u'active': True,
                    u'portableVolumeDestination': False,
                    u'deleteAllowed': True,
                    u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
                    u'scName': u'Storage Center 64702',
                    u'secureDataUsed': False,
                    u'serialNumber': u'0000fcbe-00000da8',
                    u'replayAllowed': True,
                    u'flashOptimized': False,
                    u'configuredSize': u'1.073741824E9 Bytes',
                    u'mapped': False,
                    u'cmmSource': False},
        {u'instanceId': u'64702.3495',
         u'scSerialNumber': 64702,
         u'replicationSource': False,
         u'liveVolume': False,
         u'vpdId': 3496,
         u'objectType': u'ScVolume',
         u'index': 3495,
         u'volumeFolderPath': u'devstackvol/fcvm/',
         u'hostCacheEnabled': False,
         u'usedByLegacyFluidFsNasVolume': False,
         u'inRecycleBin': False,
         u'volumeFolderIndex': 17,
         u'instanceName':
         u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
         u'statusMessage': u'',
         u'status': u'Up',
         u'storageType': {u'instanceId': u'64702.1',
                          u'instanceName':
                          u'Assigned - Redundant - 2 MB',
                          u'objectType': u'ScStorageType'},
         u'cmmDestination': False,
         u'replicationDestination': False,
         u'volumeFolder': {u'instanceId': u'64702.17',
                           u'instanceName': u'fcvm',
                           u'objectType': u'ScVolumeFolder'},
         u'deviceId': u'6000d31000fcbe000000000000000da9',
         u'active': True,
         u'portableVolumeDestination': False,
         u'deleteAllowed': True,
         u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
         u'scName': u'Storage Center 64702',
         u'secureDataUsed': False,
         u'serialNumber': u'0000fcbe-00000da8',
         u'replayAllowed': True,
         u'flashOptimized': False,
         u'configuredSize': u'1.073741824E9 Bytes',
         u'mapped': False,
         u'cmmSource': False}]

    VOLUME_CONFIG = \
        {u'instanceId': u'64702.3494',
         u'scSerialNumber': 64702,
         u'maximumSiblingCount': 100,
         u'writeCacheStatus': u'Up',
         u'objectType': u'ScVolumeConfiguration',
         u'currentSiblingConfiguredSize': u'2.147483648E9 Bytes',
         u'compressionPaused': False,
         u'enforceConsumptionLimit': False,
         u'volumeSpaceConsumptionLimit': u'2.147483648E9 Bytes',
         u'readCacheEnabled': True,
         u'writeCacheEnabled': True,
         u'instanceName': u'volume-ff9589d3-2d41-48d5-9ef5-2713a875e85b',
         u'dateModified': u'04/03/2015 12:01:08 AM',
         u'modifyUser': u'Admin',
         u'replayExpirationPaused': False,
         u'currentSiblingCount': 1,
         u'replayCreationPaused': False,
         u'replayProfileList': [{u'instanceId': u'64702.2',
                                 u'instanceName': u'Daily',
                                 u'objectType': u'ScReplayProfile'}],
         u'dateCreated': u'04/04/2014 03:54:26 AM',
         u'volume': {u'instanceId': u'64702.3494',
                     u'instanceName':
                     u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
                     u'objectType': u'ScVolume'},
         u'controller': {u'instanceId': u'64702.64703',
                         u'instanceName': u'SN 64703',
                         u'objectType': u'ScController'},
         u'coalesceIntoActive': False,
         u'createUser': u'Admin',
         u'importToLowestTier': False,
         u'readCacheStatus': u'Up',
         u'maximumSiblingConfiguredSpace': u'5.49755813888E14 Bytes',
         u'storageProfile': {u'instanceId': u'64702.1',
                             u'instanceName': u'Recommended',
                             u'objectType': u'ScStorageProfile'},
         u'scName': u'Storage Center 64702',
         u'notes': u'',
         u'diskFolder': {u'instanceId': u'64702.3',
                         u'instanceName': u'Assigned',
                         u'objectType': u'ScDiskFolder'},
         u'openVmsUniqueDiskId': 48,
         u'compressionEnabled': False}

    INACTIVE_VOLUME = \
        {u'instanceId': u'64702.3494',
         u'scSerialNumber': 64702,
         u'replicationSource': False,
         u'liveVolume': False,
         u'vpdId': 3496,
         u'objectType': u'ScVolume',
         u'index': 3494,
         u'volumeFolderPath': u'devstackvol/fcvm/',
         u'hostCacheEnabled': False,
         u'usedByLegacyFluidFsNasVolume': False,
         u'inRecycleBin': False,
         u'volumeFolderIndex': 17,
         u'instanceName': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
         u'statusMessage': u'',
         u'status': u'Up',
         u'storageType': {u'instanceId': u'64702.1',
                          u'instanceName': u'Assigned - Redundant - 2 MB',
                          u'objectType': u'ScStorageType'},
         u'cmmDestination': False,
         u'replicationDestination': False,
         u'volumeFolder': {u'instanceId': u'64702.17',
                           u'instanceName': u'fcvm',
                           u'objectType': u'ScVolumeFolder'},
         u'deviceId': u'6000d31000fcbe000000000000000da8',
         u'active': False,
         u'portableVolumeDestination': False,
         u'deleteAllowed': True,
         u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
         u'scName': u'Storage Center 64702',
         u'secureDataUsed': False,
         u'serialNumber': u'0000fcbe-00000da8',
         u'replayAllowed': True,
         u'flashOptimized': False,
         u'configuredSize': u'1.073741824E9 Bytes',
         u'mapped': False,
         u'cmmSource': False}

    SCSERVER = {u'scName': u'Storage Center 64702',
                u'volumeCount': 0,
                u'removeHbasAllowed': True,
                u'legacyFluidFs': False,
                u'serverFolderIndex': 4,
                u'alertOnConnectivity': True,
                u'objectType': u'ScPhysicalServer',
                u'instanceName': u'Server_21000024ff30441d',
                u'instanceId': u'64702.47',
                u'serverFolderPath': u'devstacksrv/',
                u'portType': [u'FibreChannel'],
                u'type': u'Physical',
                u'statusMessage': u'Only 5 of 6 expected paths are up',
                u'status': u'Degraded',
                u'scSerialNumber': 64702,
                u'serverFolder': {u'instanceId': u'64702.4',
                                  u'instanceName': u'devstacksrv',
                                  u'objectType': u'ScServerFolder'},
                u'parentIndex': 0,
                u'connectivity': u'Partial',
                u'hostCacheIndex': 0,
                u'deleteAllowed': True,
                u'pathCount': 5,
                u'name': u'Server_21000024ff30441d',
                u'hbaPresent': True,
                u'hbaCount': 2,
                u'notes': u'Created by Dell Cinder Driver',
                u'mapped': False,
                u'operatingSystem': {u'instanceId': u'64702.38',
                                     u'instanceName': u'Red Hat Linux 6.x',
                                     u'objectType': u'ScServerOperatingSystem'}
                }

    # ScServer where deletedAllowed=False (not allowed to be deleted)
    SCSERVER_NO_DEL = {u'scName': u'Storage Center 64702',
                       u'volumeCount': 0,
                       u'removeHbasAllowed': True,
                       u'legacyFluidFs': False,
                       u'serverFolderIndex': 4,
                       u'alertOnConnectivity': True,
                       u'objectType': u'ScPhysicalServer',
                       u'instanceName': u'Server_21000024ff30441d',
                       u'instanceId': u'64702.47',
                       u'serverFolderPath': u'devstacksrv/',
                       u'portType': [u'FibreChannel'],
                       u'type': u'Physical',
                       u'statusMessage': u'Only 5 of 6 expected paths are up',
                       u'status': u'Degraded',
                       u'scSerialNumber': 64702,
                       u'serverFolder': {u'instanceId': u'64702.4',
                                         u'instanceName': u'devstacksrv',
                                         u'objectType': u'ScServerFolder'},
                       u'parentIndex': 0,
                       u'connectivity': u'Partial',
                       u'hostCacheIndex': 0,
                       u'deleteAllowed': False,
                       u'pathCount': 5,
                       u'name': u'Server_21000024ff30441d',
                       u'hbaPresent': True,
                       u'hbaCount': 2,
                       u'notes': u'Created by Dell Cinder Driver',
                       u'mapped': False,
                       u'operatingSystem':
                           {u'instanceId': u'64702.38',
                            u'instanceName': u'Red Hat Linux 6.x',
                            u'objectType': u'ScServerOperatingSystem'}
                       }

    SCSERVERS = [{u'scName': u'Storage Center 64702',
                  u'volumeCount': 5,
                  u'removeHbasAllowed': True,
                  u'legacyFluidFs': False,
                  u'serverFolderIndex': 0,
                  u'alertOnConnectivity': True,
                  u'objectType': u'ScPhysicalServer',
                  u'instanceName': u'openstack4',
                  u'instanceId': u'64702.1',
                  u'serverFolderPath': u'',
                  u'portType': [u'Iscsi'],
                  u'type': u'Physical',
                  u'statusMessage': u'',
                  u'status': u'Up',
                  u'scSerialNumber': 64702,
                  u'serverFolder': {u'instanceId': u'64702.0',
                                    u'instanceName': u'Servers',
                                    u'objectType': u'ScServerFolder'},
                  u'parentIndex': 0,
                  u'connectivity': u'Up',
                  u'hostCacheIndex': 0,
                  u'deleteAllowed': True,
                  u'pathCount': 0,
                  u'name': u'openstack4',
                  u'hbaPresent': True,
                  u'hbaCount': 1,
                  u'notes': u'',
                  u'mapped': True,
                  u'operatingSystem':
                      {u'instanceId': u'64702.3',
                       u'instanceName': u'Other Multipath',
                       u'objectType': u'ScServerOperatingSystem'}},
                 {u'scName': u'Storage Center 64702',
                  u'volumeCount': 1,
                  u'removeHbasAllowed': True,
                  u'legacyFluidFs': False,
                  u'serverFolderIndex': 0,
                  u'alertOnConnectivity': True,
                  u'objectType': u'ScPhysicalServer',
                  u'instanceName': u'openstack5',
                  u'instanceId': u'64702.2',
                  u'serverFolderPath': u'',
                  u'portType': [u'Iscsi'],
                  u'type': u'Physical',
                  u'statusMessage': u'',
                  u'status': u'Up',
                  u'scSerialNumber': 64702,
                  u'serverFolder': {u'instanceId': u'64702.0',
                                    u'instanceName': u'Servers',
                                    u'objectType': u'ScServerFolder'},
                  u'parentIndex': 0,
                  u'connectivity': u'Up',
                  u'hostCacheIndex': 0,
                  u'deleteAllowed': True,
                  u'pathCount': 0, u'name': u'openstack5',
                  u'hbaPresent': True,
                  u'hbaCount': 1,
                  u'notes': u'',
                  u'mapped': True,
                  u'operatingSystem':
                      {u'instanceId': u'64702.2',
                       u'instanceName': u'Other Singlepath',
                       u'objectType': u'ScServerOperatingSystem'}}]

    # ScServers list where status = Down
    SCSERVERS_DOWN = \
        [{u'scName': u'Storage Center 64702',
          u'volumeCount': 5,
          u'removeHbasAllowed': True,
          u'legacyFluidFs': False,
          u'serverFolderIndex': 0,
          u'alertOnConnectivity': True,
          u'objectType': u'ScPhysicalServer',
          u'instanceName': u'openstack4',
          u'instanceId': u'64702.1',
          u'serverFolderPath': u'',
          u'portType': [u'Iscsi'],
          u'type': u'Physical',
          u'statusMessage': u'',
          u'status': u'Down',
          u'scSerialNumber': 64702,
          u'serverFolder': {u'instanceId': u'64702.0',
                            u'instanceName': u'Servers',
                            u'objectType': u'ScServerFolder'},
          u'parentIndex': 0,
          u'connectivity': u'Up',
          u'hostCacheIndex': 0,
          u'deleteAllowed': True,
          u'pathCount': 0,
          u'name': u'openstack4',
          u'hbaPresent': True,
          u'hbaCount': 1,
          u'notes': u'',
          u'mapped': True,
          u'operatingSystem':
          {u'instanceId': u'64702.3',
           u'instanceName': u'Other Multipath',
           u'objectType': u'ScServerOperatingSystem'}}]

    MAP_PROFILES = [{u'instanceId': u'64702.2941',
                     u'scName': u'Storage Center 64702',
                     u'scSerialNumber': 64702,
                     u'controller': {u'instanceId': u'64702.64703',
                                     u'instanceName': u'SN 64703',
                                     u'objectType': u'ScController'},
                     u'lunUsed': [1],
                     u'server': {u'instanceId': u'64702.47',
                                 u'instanceName': u'Server_21000024ff30441d',
                                 u'objectType': u'ScPhysicalServer'},
                     u'volume':
                         {u'instanceId': u'64702.6025',
                          u'instanceName': u'Server_21000024ff30441d Test Vol',
                          u'objectType': u'ScVolume'},
                     u'connectivity': u'Up',
                     u'readOnly': False,
                     u'objectType': u'ScMappingProfile',
                     u'hostCache': False,
                     u'mappedVia': u'Server',
                     u'mapCount': 3,
                     u'instanceName': u'6025-47',
                     u'lunRequested': u'N/A'}]

    MAP_PROFILE = {u'instanceId': u'64702.2941',
                   u'scName': u'Storage Center 64702',
                   u'scSerialNumber': 64702,
                   u'controller': {u'instanceId': u'64702.64703',
                                   u'instanceName': u'SN 64703',
                                   u'objectType': u'ScController'},
                   u'lunUsed': [1],
                   u'server': {u'instanceId': u'64702.47',
                               u'instanceName': u'Server_21000024ff30441d',
                               u'objectType': u'ScPhysicalServer'},
                   u'volume':
                       {u'instanceId': u'64702.6025',
                        u'instanceName': u'Server_21000024ff30441d Test Vol',
                        u'objectType': u'ScVolume'},
                   u'connectivity': u'Up',
                   u'readOnly': False,
                   u'objectType': u'ScMappingProfile',
                   u'hostCache': False,
                   u'mappedVia': u'Server',
                   u'mapCount': 3,
                   u'instanceName': u'6025-47',
                   u'lunRequested': u'N/A'}

    MAPPINGS = [{u'profile': {u'instanceId': u'64702.104',
                              u'instanceName': u'92-30',
                              u'objectType': u'ScMappingProfile'},
                 u'status': u'Down',
                 u'statusMessage': u'',
                 u'instanceId': u'64702.969.64702',
                 u'scName': u'Storage Center 64702',
                 u'scSerialNumber': 64702,
                 u'controller': {u'instanceId': u'64702.64702',
                                 u'instanceName': u'SN 64702',
                                 u'objectType': u'ScController'},
                 u'server': {u'instanceId': u'64702.30',
                             u'instanceName':
                             u'Server_iqn.1993-08.org.debian:01:3776df826e4f',
                             u'objectType': u'ScPhysicalServer'},
                 u'volume': {u'instanceId': u'64702.92',
                             u'instanceName':
                             u'volume-74a21934-60ad-4cf2-b89b-1f0dda309ddf',
                             u'objectType': u'ScVolume'},
                 u'readOnly': False,
                 u'lun': 1,
                 u'lunUsed': [1],
                 u'serverHba': {u'instanceId': u'64702.3454975614',
                                u'instanceName':
                                u'iqn.1993-08.org.debian:01:3776df826e4f',
                                u'objectType': u'ScServerHba'},
                 u'path': {u'instanceId': u'64702.64702.64702.31.8',
                           u'instanceName':
                           u'iqn.1993-08.org.debian:'
                           '01:3776df826e4f-5000D31000FCBE43',
                           u'objectType': u'ScServerHbaPath'},
                 u'controllerPort': {u'instanceId':
                                     u'64702.5764839588723736131.91',
                                     u'instanceName': u'5000D31000FCBE43',
                                     u'objectType': u'ScControllerPort'},
                 u'instanceName': u'64702-969',
                 u'transport': u'Iscsi',
                 u'objectType': u'ScMapping'}]

    # Multiple mappings to test find_iscsi_properties with multiple portals
    MAPPINGS_MULTI_PORTAL = \
        [{u'profile': {u'instanceId': u'64702.104',
                       u'instanceName': u'92-30',
                       u'objectType': u'ScMappingProfile'},
          u'status': u'Down',
          u'statusMessage': u'',
          u'instanceId': u'64702.969.64702',
          u'scName': u'Storage Center 64702',
          u'scSerialNumber': 64702,
          u'controller': {u'instanceId': u'64702.64702',
                          u'instanceName': u'SN 64702',
                          u'objectType': u'ScController'},
          u'server': {u'instanceId': u'64702.30',
                      u'instanceName':
                      u'Server_iqn.1993-08.org.debian:01:3776df826e4f',
                      u'objectType': u'ScPhysicalServer'},
          u'volume': {u'instanceId': u'64702.92',
                      u'instanceName':
                      u'volume-74a21934-60ad-4cf2-b89b-1f0dda309ddf',
                      u'objectType': u'ScVolume'},
          u'readOnly': False,
          u'lun': 1,
          u'lunUsed': [1],
          u'serverHba': {u'instanceId': u'64702.3454975614',
                         u'instanceName':
                         u'iqn.1993-08.org.debian:01:3776df826e4f',
                         u'objectType': u'ScServerHba'},
          u'path': {u'instanceId': u'64702.64702.64702.31.8',
                    u'instanceName':
                    u'iqn.1993-08.org.debian:'
                    '01:3776df826e4f-5000D31000FCBE43',
                    u'objectType': u'ScServerHbaPath'},
          u'controllerPort': {u'instanceId':
                              u'64702.5764839588723736131.91',
                              u'instanceName': u'5000D31000FCBE43',
                              u'objectType': u'ScControllerPort'},
          u'instanceName': u'64702-969',
          u'transport': u'Iscsi',
          u'objectType': u'ScMapping'},
         {u'profile': {u'instanceId': u'64702.104',
                       u'instanceName': u'92-30',
                       u'objectType': u'ScMappingProfile'},
          u'status': u'Down',
          u'statusMessage': u'',
          u'instanceId': u'64702.969.64702',
          u'scName': u'Storage Center 64702',
          u'scSerialNumber': 64702,
          u'controller': {u'instanceId': u'64702.64702',
                          u'instanceName': u'SN 64702',
                          u'objectType': u'ScController'},
          u'server': {u'instanceId': u'64702.30',
                      u'instanceName':
                      u'Server_iqn.1993-08.org.debian:01:3776df826e4f',
                      u'objectType': u'ScPhysicalServer'},
          u'volume': {u'instanceId': u'64702.92',
                      u'instanceName':
                      u'volume-74a21934-60ad-4cf2-b89b-1f0dda309ddf',
                      u'objectType': u'ScVolume'},
          u'readOnly': False,
          u'lun': 1,
          u'lunUsed': [1],
          u'serverHba': {u'instanceId': u'64702.3454975614',
                         u'instanceName':
                         u'iqn.1993-08.org.debian:01:3776df826e4f',
                         u'objectType': u'ScServerHba'},
          u'path': {u'instanceId': u'64702.64702.64702.31.8',
                    u'instanceName':
                    u'iqn.1993-08.org.debian:'
                    '01:3776df826e4f-5000D31000FCBE43',
                    u'objectType': u'ScServerHbaPath'},
          u'controllerPort': {u'instanceId':
                              u'64702.5764839588723736131.91',
                              u'instanceName': u'5000D31000FCBE43',
                              u'objectType': u'ScControllerPort'},
          u'instanceName': u'64702-969',
          u'transport': u'Iscsi',
          u'objectType': u'ScMapping'}]

    MAPPINGS_READ_ONLY = \
        [{u'profile': {u'instanceId': u'64702.104',
                       u'instanceName': u'92-30',
                       u'objectType': u'ScMappingProfile'},
          u'status': u'Down',
          u'statusMessage': u'',
          u'instanceId': u'64702.969.64702',
          u'scName': u'Storage Center 64702',
          u'scSerialNumber': 64702,
          u'controller': {u'instanceId': u'64702.64702',
                          u'instanceName': u'SN 64702',
                                           u'objectType': u'ScController'},
          u'server': {u'instanceId': u'64702.30',
                      u'instanceName':
                      u'Server_iqn.1993-08.org.debian:01:3776df826e4f',
                      u'objectType': u'ScPhysicalServer'},
          u'volume': {u'instanceId': u'64702.92',
                      u'instanceName':
                      u'volume-74a21934-60ad-4cf2-b89b-1f0dda309ddf',
                      u'objectType': u'ScVolume'},
          u'readOnly': True,
          u'lun': 1,
          u'lunUsed': [1],
          u'serverHba': {u'instanceId': u'64702.3454975614',
                         u'instanceName':
                         u'iqn.1993-08.org.debian:01:3776df826e4f',
                         u'objectType': u'ScServerHba'},
          u'path': {u'instanceId': u'64702.64702.64702.31.8',
                    u'instanceName':
                    u'iqn.1993-08.org.debian:'
                    '01:3776df826e4f-5000D31000FCBE43',
                    u'objectType': u'ScServerHbaPath'},
          u'controllerPort': {u'instanceId':
                              u'64702.5764839588723736131.91',
                              u'instanceName':
                              u'5000D31000FCBE43',
                              u'objectType': u'ScControllerPort'},
          u'instanceName': u'64702-969',
                           u'transport': u'Iscsi',
                           u'objectType': u'ScMapping'}]

    FC_MAPPINGS = [{u'profile': {u'instanceId': u'64702.2941',
                                 u'instanceName': u'6025-47',
                                 u'objectType': u'ScMappingProfile'},
                    u'status': u'Up',
                    u'statusMessage': u'',
                    u'instanceId': u'64702.7639.64702',
                    u'scName': u'Storage Center 64702',
                    u'scSerialNumber': 64702,
                    u'controller': {u'instanceId': u'64702.64703',
                                    u'instanceName': u'SN 64703',
                                    u'objectType': u'ScController'},
                    u'server': {u'instanceId': u'64702.47',
                                u'instanceName': u'Server_21000024ff30441d',
                                u'objectType': u'ScPhysicalServer'},
                    u'volume': {u'instanceId': u'64702.6025',
                                u'instanceName':
                                    u'Server_21000024ff30441d Test Vol',
                                u'objectType': u'ScVolume'},
                    u'readOnly': False,
                    u'lun': 1,
                    u'serverHba': {u'instanceId': u'64702.3282218607',
                                   u'instanceName': u'21000024FF30441C',
                                   u'objectType': u'ScServerHba'},
                    u'path': {u'instanceId': u'64702.64702.64703.27.73',
                              u'instanceName':
                                  u'21000024FF30441C-5000D31000FCBE36',
                              u'objectType': u'ScServerHbaPath'},
                    u'controllerPort':
                        {u'instanceId': u'64702.5764839588723736118.50',
                         u'instanceName': u'5000D31000FCBE36',
                         u'objectType': u'ScControllerPort'},
                    u'instanceName': u'64702-7639',
                    u'transport': u'FibreChannel',
                    u'objectType': u'ScMapping'},
                   {u'profile': {u'instanceId': u'64702.2941',
                                 u'instanceName': u'6025-47',
                                 u'objectType': u'ScMappingProfile'},
                    u'status': u'Up',
                    u'statusMessage': u'',
                    u'instanceId': u'64702.7640.64702',
                    u'scName': u'Storage Center 64702',
                    u'scSerialNumber': 64702,
                    u'controller': {u'instanceId': u'64702.64703',
                                    u'instanceName': u'SN 64703',
                                    u'objectType': u'ScController'},
                    u'server': {u'instanceId': u'64702.47',
                                u'instanceName': u'Server_21000024ff30441d',
                                u'objectType': u'ScPhysicalServer'},
                    u'volume':
                        {u'instanceId': u'64702.6025',
                         u'instanceName': u'Server_21000024ff30441d Test Vol',
                         u'objectType': u'ScVolume'},
                    u'readOnly': False,
                    u'lun': 1,
                    u'serverHba': {u'instanceId': u'64702.3282218606',
                                   u'instanceName': u'21000024FF30441D',
                                   u'objectType': u'ScServerHba'},
                    u'path':
                    {u'instanceId': u'64702.64702.64703.27.78',
                       u'instanceName': u'21000024FF30441D-5000D31000FCBE36',
                       u'objectType': u'ScServerHbaPath'},
                    u'controllerPort':
                        {u'instanceId': u'64702.5764839588723736118.50',
                         u'instanceName': u'5000D31000FCBE36',
                         u'objectType': u'ScControllerPort'},
                    u'instanceName': u'64702-7640',
                    u'transport': u'FibreChannel',
                    u'objectType': u'ScMapping'},
                   {u'profile': {u'instanceId': u'64702.2941',
                                 u'instanceName': u'6025-47',
                                 u'objectType': u'ScMappingProfile'},
                    u'status': u'Up',
                    u'statusMessage': u'',
                    u'instanceId': u'64702.7638.64702',
                    u'scName': u'Storage Center 64702',
                    u'scSerialNumber': 64702,
                    u'controller': {u'instanceId': u'64702.64703',
                                    u'instanceName': u'SN 64703',
                                    u'objectType': u'ScController'},
                    u'server': {u'instanceId': u'64702.47',
                                u'instanceName': u'Server_21000024ff30441d',
                                u'objectType': u'ScPhysicalServer'},
                    u'volume': {u'instanceId': u'64702.6025',
                                u'instanceName':
                                    u'Server_21000024ff30441d Test Vol',
                                u'objectType': u'ScVolume'},
                    u'readOnly': False,
                    u'lun': 1,
                    u'serverHba': {u'instanceId': u'64702.3282218606',
                                   u'instanceName': u'21000024FF30441D',
                                   u'objectType': u'ScServerHba'},
                    u'path':
                        {u'instanceId': u'64702.64702.64703.28.76',
                         u'instanceName': u'21000024FF30441D-5000D31000FCBE3E',
                         u'objectType': u'ScServerHbaPath'},
                    u'controllerPort': {u'instanceId':
                                        u'64702.5764839588723736126.60',
                                        u'instanceName': u'5000D31000FCBE3E',
                                        u'objectType': u'ScControllerPort'},
                    u'instanceName': u'64702-7638',
                    u'transport': u'FibreChannel',
                    u'objectType': u'ScMapping'}]

    FC_MAPPINGS_LUN_MISMATCH = \
        [{u'profile': {u'instanceId': u'64702.2941',
                       u'instanceName': u'6025-47',
                       u'objectType': u'ScMappingProfile'},
          u'status': u'Up',
          u'statusMessage': u'',
          u'instanceId': u'64702.7639.64702',
          u'scName': u'Storage Center 64702',
          u'scSerialNumber': 64702,
          u'controller': {u'instanceId': u'64702.64703',
                          u'instanceName': u'SN 64703',
                          u'objectType': u'ScController'},
          u'server': {u'instanceId': u'64702.47',
                      u'instanceName': u'Server_21000024ff30441d',
                      u'objectType': u'ScPhysicalServer'},
          u'volume': {u'instanceId': u'64702.6025',
                      u'instanceName':
                      u'Server_21000024ff30441d Test Vol',
                      u'objectType': u'ScVolume'},
          u'readOnly': False,
          u'lun': 1,
          u'serverHba': {u'instanceId': u'64702.3282218607',
                         u'instanceName': u'21000024FF30441C',
                         u'objectType': u'ScServerHba'},
          u'path': {u'instanceId': u'64702.64702.64703.27.73',
                    u'instanceName':
                    u'21000024FF30441C-5000D31000FCBE36',
                    u'objectType': u'ScServerHbaPath'},
          u'controllerPort':
          {u'instanceId': u'64702.5764839588723736118.50',
           u'instanceName': u'5000D31000FCBE36',
           u'objectType': u'ScControllerPort'},
          u'instanceName': u'64702-7639',
          u'transport': u'FibreChannel',
          u'objectType': u'ScMapping'},
         {u'profile': {u'instanceId': u'64702.2941',
                       u'instanceName': u'6025-47',
                       u'objectType': u'ScMappingProfile'},
          u'status': u'Up',
          u'statusMessage': u'',
          u'instanceId': u'64702.7640.64702',
          u'scName': u'Storage Center 64702',
          u'scSerialNumber': 64702,
          u'controller': {u'instanceId': u'64702.64703',
                          u'instanceName': u'SN 64703',
                          u'objectType': u'ScController'},
          u'server': {u'instanceId': u'64702.47',
                      u'instanceName': u'Server_21000024ff30441d',
                      u'objectType': u'ScPhysicalServer'},
          u'volume':
          {u'instanceId': u'64702.6025',
           u'instanceName': u'Server_21000024ff30441d Test Vol',
           u'objectType': u'ScVolume'},
          u'readOnly': False,
          u'lun': 1,
          u'serverHba': {u'instanceId': u'64702.3282218606',
                         u'instanceName': u'21000024FF30441D',
                         u'objectType': u'ScServerHba'},
          u'path':
          {u'instanceId': u'64702.64702.64703.27.78',
           u'instanceName': u'21000024FF30441D-5000D31000FCBE36',
           u'objectType': u'ScServerHbaPath'},
          u'controllerPort':
          {u'instanceId': u'64702.5764839588723736118.50',
           u'instanceName': u'5000D31000FCBE36',
           u'objectType': u'ScControllerPort'},
          u'instanceName': u'64702-7640',
          u'transport': u'FibreChannel',
          u'objectType': u'ScMapping'},
            {u'profile': {u'instanceId': u'64702.2941',
                          u'instanceName': u'6025-47',
                          u'objectType': u'ScMappingProfile'},
             u'status': u'Up',
             u'statusMessage': u'',
             u'instanceId': u'64702.7638.64702',
             u'scName': u'Storage Center 64702',
             u'scSerialNumber': 64702,
             u'controller': {u'instanceId': u'64702.64703',
                             u'instanceName': u'SN 64703',
                             u'objectType': u'ScController'},
             u'server': {u'instanceId': u'64702.47',
                         u'instanceName': u'Server_21000024ff30441d',
                         u'objectType': u'ScPhysicalServer'},
             u'volume': {u'instanceId': u'64702.6025',
                         u'instanceName':
                         u'Server_21000024ff30441d Test Vol',
                         u'objectType': u'ScVolume'},
             u'readOnly': False,
             u'lun': 2,
             u'serverHba': {u'instanceId': u'64702.3282218606',
                            u'instanceName': u'21000024FF30441D',
                            u'objectType': u'ScServerHba'},
             u'path':
                        {u'instanceId': u'64702.64702.64703.28.76',
                         u'instanceName': u'21000024FF30441D-5000D31000FCBE3E',
                         u'objectType': u'ScServerHbaPath'},
             u'controllerPort': {u'instanceId':
                                 u'64702.5764839588723736126.60',
                                 u'instanceName': u'5000D31000FCBE3E',
                                 u'objectType': u'ScControllerPort'},
             u'instanceName': u'64702-7638',
             u'transport': u'FibreChannel',
             u'objectType': u'ScMapping'}]

    RPLAY = {u'scSerialNumber': 64702,
             u'globalIndex': u'64702-46-250',
             u'description': u'Cinder Clone Replay',
             u'parent': {u'instanceId': u'64702.46.249',
                         u'instanceName': u'64702-46-249',
                         u'objectType': u'ScReplay'},
             u'instanceId': u'64702.46.250',
             u'scName': u'Storage Center 64702',
             u'consistent': False,
             u'expires': True,
             u'freezeTime': u'12/09/2014 03:52:08 PM',
             u'createVolume': {u'instanceId': u'64702.46',
                               u'instanceName':
                               u'volume-ff9589d3-2d41-48d5-9ef5-2713a875e85b',
                               u'objectType': u'ScVolume'},
             u'expireTime': u'12/09/2014 04:52:08 PM',
             u'source': u'Manual',
             u'spaceRecovery': False,
             u'writesHeldDuration': 7910,
             u'active': False,
             u'markedForExpiration': False,
             u'objectType': u'ScReplay',
             u'instanceName': u'12/09/2014 03:52:08 PM',
             u'size': u'0.0 Bytes'
             }

    RPLAYS = [{u'scSerialNumber': 64702,
               u'globalIndex': u'64702-6025-5',
               u'description': u'Manually Created',
               u'parent': {u'instanceId': u'64702.6025.4',
                           u'instanceName': u'64702-6025-4',
                           u'objectType': u'ScReplay'},
               u'instanceId': u'64702.6025.5',
               u'scName': u'Storage Center 64702',
               u'consistent': False,
               u'expires': True,
               u'freezeTime': u'02/02/2015 08:23:55 PM',
               u'createVolume': {u'instanceId': u'64702.6025',
                                 u'instanceName':
                                     u'Server_21000024ff30441d Test Vol',
                                 u'objectType': u'ScVolume'},
               u'expireTime': u'02/02/2015 09:23:55 PM',
               u'source': u'Manual',
               u'spaceRecovery': False,
               u'writesHeldDuration': 7889,
               u'active': False,
               u'markedForExpiration': False,
               u'objectType': u'ScReplay',
               u'instanceName': u'02/02/2015 08:23:55 PM',
               u'size': u'0.0 Bytes'},
              {u'scSerialNumber': 64702,
               u'globalIndex': u'64702-6025-4',
               u'description': u'Cinder Test Replay012345678910',
               u'parent': {u'instanceId': u'64702.6025.3',
                           u'instanceName': u'64702-6025-3',
                           u'objectType': u'ScReplay'},
               u'instanceId': u'64702.6025.4',
               u'scName': u'Storage Center 64702',
               u'consistent': False,
               u'expires': True,
               u'freezeTime': u'02/02/2015 08:23:47 PM',
               u'createVolume': {u'instanceId': u'64702.6025',
                                 u'instanceName':
                                     u'Server_21000024ff30441d Test Vol',
                                 u'objectType': u'ScVolume'},
               u'expireTime': u'02/02/2015 09:23:47 PM',
               u'source': u'Manual',
               u'spaceRecovery': False,
               u'writesHeldDuration': 7869,
               u'active': False,
               u'markedForExpiration': False,
               u'objectType': u'ScReplay',
               u'instanceName': u'02/02/2015 08:23:47 PM',
               u'size': u'0.0 Bytes'}]

    TST_RPLAY = {u'scSerialNumber': 64702,
                 u'globalIndex': u'64702-6025-4',
                 u'description': u'Cinder Test Replay012345678910',
                 u'parent': {u'instanceId': u'64702.6025.3',
                             u'instanceName': u'64702-6025-3',
                             u'objectType': u'ScReplay'},
                 u'instanceId': u'64702.6025.4',
                 u'scName': u'Storage Center 64702',
                 u'consistent': False,
                 u'expires': True,
                 u'freezeTime': u'02/02/2015 08:23:47 PM',
                 u'createVolume': {u'instanceId': u'64702.6025',
                                   u'instanceName':
                                       u'Server_21000024ff30441d Test Vol',
                                   u'objectType': u'ScVolume'},
                 u'expireTime': u'02/02/2015 09:23:47 PM',
                 u'source': u'Manual',
                 u'spaceRecovery': False,
                 u'writesHeldDuration': 7869,
                 u'active': False,
                 u'markedForExpiration': False,
                 u'objectType': u'ScReplay',
                 u'instanceName': u'02/02/2015 08:23:47 PM',
                 u'size': u'0.0 Bytes'}

    FLDR = {u'status': u'Up',
            u'instanceName': u'opnstktst',
            u'name': u'opnstktst',
            u'parent':
                {u'instanceId': u'64702.0',
                 u'instanceName': u'Volumes',
                 u'objectType': u'ScVolumeFolder'},
            u'instanceId': u'64702.43',
            u'scName': u'Storage Center 64702',
            u'notes': u'Folder for OpenStack Cinder Driver',
            u'scSerialNumber': 64702,
            u'parentIndex': 0,
            u'okToDelete': True,
            u'folderPath': u'',
            u'root': False,
            u'statusMessage': u'',
            u'objectType': u'ScVolumeFolder'}

    SVR_FLDR = {u'status': u'Up',
                u'instanceName': u'devstacksrv',
                u'name': u'devstacksrv',
                u'parent': {u'instanceId': u'64702.0',
                            u'instanceName': u'Servers',
                            u'objectType': u'ScServerFolder'},
                u'instanceId': u'64702.4',
                u'scName': u'Storage Center 64702',
                u'notes': u'Folder for OpenStack Cinder Driver',
                u'scSerialNumber': 64702,
                u'parentIndex': 0,
                u'okToDelete': False,
                u'folderPath': u'',
                u'root': False,
                u'statusMessage': u'',
                u'objectType': u'ScServerFolder'}

    ISCSI_HBA = {u'portWwnList': [],
                 u'iscsiIpAddress': u'0.0.0.0',
                 u'pathCount': 1,
                 u'name': u'iqn.1993-08.org.debian:01:52332b70525',
                 u'connectivity': u'Down',
                 u'instanceId': u'64702.3786433166',
                 u'scName': u'Storage Center 64702',
                 u'notes': u'',
                 u'scSerialNumber': 64702,
                 u'server':
                     {u'instanceId': u'64702.38',
                      u'instanceName':
                          u'Server_iqn.1993-08.org.debian:01:52332b70525',
                      u'objectType': u'ScPhysicalServer'},
                 u'remoteStorageCenter': False,
                 u'iscsiName': u'',
                 u'portType': u'Iscsi',
                 u'instanceName': u'iqn.1993-08.org.debian:01:52332b70525',
                 u'objectType': u'ScServerHba'}

    FC_HBAS = [{u'portWwnList': [],
                u'iscsiIpAddress': u'0.0.0.0',
                u'pathCount': 2,
                u'name': u'21000024FF30441C',
                u'connectivity': u'Up',
                u'instanceId': u'64702.3282218607',
                u'scName': u'Storage Center 64702',
                u'notes': u'',
                u'scSerialNumber': 64702,
                u'server': {u'instanceId': u'64702.47',
                            u'instanceName': u'Server_21000024ff30441d',
                            u'objectType': u'ScPhysicalServer'},
                u'remoteStorageCenter': False,
                u'iscsiName': u'',
                u'portType': u'FibreChannel',
                u'instanceName': u'21000024FF30441C',
                u'objectType': u'ScServerHba'},
               {u'portWwnList': [],
                u'iscsiIpAddress': u'0.0.0.0',
                u'pathCount': 3,
                u'name': u'21000024FF30441D',
                u'connectivity': u'Partial',
                u'instanceId': u'64702.3282218606',
                u'scName': u'Storage Center 64702',
                u'notes': u'',
                u'scSerialNumber': 64702,
                u'server': {u'instanceId': u'64702.47',
                            u'instanceName': u'Server_21000024ff30441d',
                            u'objectType': u'ScPhysicalServer'},
                u'remoteStorageCenter': False,
                u'iscsiName': u'',
                u'portType': u'FibreChannel',
                u'instanceName': u'21000024FF30441D',
                u'objectType': u'ScServerHba'}]

    FC_HBA = {u'portWwnList': [],
              u'iscsiIpAddress': u'0.0.0.0',
              u'pathCount': 3,
              u'name': u'21000024FF30441D',
              u'connectivity': u'Partial',
              u'instanceId': u'64702.3282218606',
              u'scName': u'Storage Center 64702',
              u'notes': u'',
              u'scSerialNumber': 64702,
              u'server': {u'instanceId': u'64702.47',
                          u'instanceName': u'Server_21000024ff30441d',
                          u'objectType': u'ScPhysicalServer'},
              u'remoteStorageCenter': False,
              u'iscsiName': u'',
              u'portType': u'FibreChannel',
              u'instanceName': u'21000024FF30441D',
              u'objectType': u'ScServerHba'}

    SVR_OS_S = [{u'allowsLunGaps': True,
                 u'product': u'Red Hat Linux',
                 u'supportsActiveMappingDeletion': True,
                 u'version': u'6.x',
                 u'requiresLunZero': False,
                 u'scName': u'Storage Center 64702',
                 u'virtualMachineGuest': True,
                 u'virtualMachineHost': False,
                 u'allowsCrossTransportMapping': False,
                 u'objectType': u'ScServerOperatingSystem',
                 u'instanceId': u'64702.38',
                 u'lunCanVaryAcrossPaths': False,
                 u'scSerialNumber': 64702,
                 u'maximumVolumeSize': u'0.0 Bytes',
                 u'multipath': True,
                 u'instanceName': u'Red Hat Linux 6.x',
                 u'supportsActiveMappingCreation': True,
                 u'name': u'Red Hat Linux 6.x'}]

    ISCSI_FLT_DOMAINS = [{u'headerDigestEnabled': False,
                          u'classOfServicePriority': 0,
                          u'wellKnownIpAddress': u'192.168.0.21',
                          u'scSerialNumber': 64702,
                          u'iscsiName':
                          u'iqn.2002-03.com.compellent:5000d31000fcbe42',
                          u'portNumber': 3260,
                          u'subnetMask': u'255.255.255.0',
                          u'gateway': u'192.168.0.1',
                          u'objectType': u'ScIscsiFaultDomain',
                          u'chapEnabled': False,
                          u'instanceId': u'64702.6.5.3',
                          u'childStatus': u'Up',
                          u'defaultTimeToRetain': u'SECONDS_20',
                          u'dataDigestEnabled': False,
                          u'instanceName': u'iSCSI 10G 2',
                          u'statusMessage': u'',
                          u'status': u'Up',
                          u'transportType': u'Iscsi',
                          u'vlanId': 0,
                          u'windowSize': u'131072.0 Bytes',
                          u'defaultTimeToWait': u'SECONDS_2',
                          u'scsiCommandTimeout': u'MINUTES_1',
                          u'deleteAllowed': False,
                          u'name': u'iSCSI 10G 2',
                          u'immediateDataWriteEnabled': False,
                          u'scName': u'Storage Center 64702',
                          u'notes': u'',
                          u'mtu': u'MTU_1500',
                          u'bidirectionalChapSecret': u'',
                          u'keepAliveTimeout': u'SECONDS_30'}]

    # For testing find_iscsi_properties where multiple portals are found
    ISCSI_FLT_DOMAINS_MULTI_PORTALS = \
        [{u'headerDigestEnabled': False,
          u'classOfServicePriority': 0,
          u'wellKnownIpAddress': u'192.168.0.21',
          u'scSerialNumber': 64702,
          u'iscsiName':
          u'iqn.2002-03.com.compellent:5000d31000fcbe42',
          u'portNumber': 3260,
          u'subnetMask': u'255.255.255.0',
          u'gateway': u'192.168.0.1',
          u'objectType': u'ScIscsiFaultDomain',
          u'chapEnabled': False,
          u'instanceId': u'64702.6.5.3',
          u'childStatus': u'Up',
          u'defaultTimeToRetain': u'SECONDS_20',
          u'dataDigestEnabled': False,
          u'instanceName': u'iSCSI 10G 2',
          u'statusMessage': u'',
          u'status': u'Up',
          u'transportType': u'Iscsi',
          u'vlanId': 0,
          u'windowSize': u'131072.0 Bytes',
          u'defaultTimeToWait': u'SECONDS_2',
          u'scsiCommandTimeout': u'MINUTES_1',
          u'deleteAllowed': False,
          u'name': u'iSCSI 10G 2',
          u'immediateDataWriteEnabled': False,
          u'scName': u'Storage Center 64702',
          u'notes': u'',
          u'mtu': u'MTU_1500',
          u'bidirectionalChapSecret': u'',
          u'keepAliveTimeout': u'SECONDS_30'},
         {u'headerDigestEnabled': False,
          u'classOfServicePriority': 0,
          u'wellKnownIpAddress': u'192.168.0.25',
          u'scSerialNumber': 64702,
          u'iscsiName':
          u'iqn.2002-03.com.compellent:5000d31000fcbe42',
          u'portNumber': 3260,
          u'subnetMask': u'255.255.255.0',
          u'gateway': u'192.168.0.1',
          u'objectType': u'ScIscsiFaultDomain',
          u'chapEnabled': False,
          u'instanceId': u'64702.6.5.3',
          u'childStatus': u'Up',
          u'defaultTimeToRetain': u'SECONDS_20',
          u'dataDigestEnabled': False,
          u'instanceName': u'iSCSI 10G 2',
          u'statusMessage': u'',
          u'status': u'Up',
          u'transportType': u'Iscsi',
          u'vlanId': 0,
          u'windowSize': u'131072.0 Bytes',
          u'defaultTimeToWait': u'SECONDS_2',
          u'scsiCommandTimeout': u'MINUTES_1',
          u'deleteAllowed': False,
          u'name': u'iSCSI 10G 2',
          u'immediateDataWriteEnabled': False,
          u'scName': u'Storage Center 64702',
          u'notes': u'',
          u'mtu': u'MTU_1500',
          u'bidirectionalChapSecret': u'',
          u'keepAliveTimeout': u'SECONDS_30'}]

    ISCSI_FLT_DOMAIN = {u'headerDigestEnabled': False,
                        u'classOfServicePriority': 0,
                        u'wellKnownIpAddress': u'192.168.0.21',
                        u'scSerialNumber': 64702,
                        u'iscsiName':
                            u'iqn.2002-03.com.compellent:5000d31000fcbe42',
                        u'portNumber': 3260,
                        u'subnetMask': u'255.255.255.0',
                        u'gateway': u'192.168.0.1',
                        u'objectType': u'ScIscsiFaultDomain',
                        u'chapEnabled': False,
                        u'instanceId': u'64702.6.5.3',
                        u'childStatus': u'Up',
                        u'defaultTimeToRetain': u'SECONDS_20',
                        u'dataDigestEnabled': False,
                        u'instanceName': u'iSCSI 10G 2',
                        u'statusMessage': u'',
                        u'status': u'Up',
                        u'transportType': u'Iscsi',
                        u'vlanId': 0,
                        u'windowSize': u'131072.0 Bytes',
                        u'defaultTimeToWait': u'SECONDS_2',
                        u'scsiCommandTimeout': u'MINUTES_1',
                        u'deleteAllowed': False,
                        u'name': u'iSCSI 10G 2',
                        u'immediateDataWriteEnabled': False,
                        u'scName': u'Storage Center 64702',
                        u'notes': u'',
                        u'mtu': u'MTU_1500',
                        u'bidirectionalChapSecret': u'',
                        u'keepAliveTimeout': u'SECONDS_30'}

    CTRLR_PORT = {u'status': u'Up',
                  u'iscsiIpAddress': u'0.0.0.0',
                  u'WWN': u'5000D31000FCBE06',
                  u'name': u'5000D31000FCBE06',
                  u'iscsiGateway': u'0.0.0.0',
                  u'instanceId': u'64702.5764839588723736070.51',
                  u'scName': u'Storage Center 64702',
                  u'scSerialNumber': 64702,
                  u'transportType': u'FibreChannel',
                  u'virtual': False,
                  u'controller': {u'instanceId': u'64702.64702',
                                  u'instanceName': u'SN 64702',
                                  u'objectType': u'ScController'},
                  u'iscsiName': u'',
                  u'purpose': u'FrontEnd',
                  u'iscsiSubnetMask': u'0.0.0.0',
                  u'faultDomain':
                      {u'instanceId': u'64702.4.3',
                       u'instanceName': u'Domain 1',
                       u'objectType': u'ScControllerPortFaultDomain'},
                  u'instanceName': u'5000D31000FCBE06',
                  u'statusMessage': u'',
                  u'objectType': u'ScControllerPort'}

    ISCSI_CTRLR_PORT = {u'preferredParent':
                        {u'instanceId': u'64702.5764839588723736074.69',
                         u'instanceName': u'5000D31000FCBE0A',
                         u'objectType': u'ScControllerPort'},
                        u'status': u'Up',
                        u'iscsiIpAddress': u'10.23.8.235',
                        u'WWN': u'5000D31000FCBE43',
                        u'name': u'5000D31000FCBE43',
                        u'parent':
                            {u'instanceId': u'64702.5764839588723736074.69',
                             u'instanceName': u'5000D31000FCBE0A',
                             u'objectType': u'ScControllerPort'},
                        u'iscsiGateway': u'0.0.0.0',
                        u'instanceId': u'64702.5764839588723736131.91',
                        u'scName': u'Storage Center 64702',
                        u'scSerialNumber': 64702,
                        u'transportType': u'Iscsi',
                        u'virtual': True,
                        u'controller': {u'instanceId': u'64702.64702',
                                        u'instanceName': u'SN 64702',
                                        u'objectType': u'ScController'},
                        u'iscsiName':
                            u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                        u'purpose': u'FrontEnd',
                        u'iscsiSubnetMask': u'0.0.0.0',
                        u'faultDomain':
                            {u'instanceId': u'64702.6.5',
                             u'instanceName': u'iSCSI 10G 2',
                             u'objectType': u'ScControllerPortFaultDomain'},
                        u'instanceName': u'5000D31000FCBE43',
                        u'childStatus': u'Up',
                        u'statusMessage': u'',
                        u'objectType': u'ScControllerPort'}

    FC_CTRLR_PORT = {u'preferredParent':
                     {u'instanceId': u'64702.5764839588723736093.57',
                         u'instanceName': u'5000D31000FCBE1D',
                                          u'objectType': u'ScControllerPort'},
                     u'status': u'Up',
                     u'iscsiIpAddress': u'0.0.0.0',
                     u'WWN': u'5000D31000FCBE36',
                     u'name': u'5000D31000FCBE36',
                     u'parent':
                         {u'instanceId': u'64702.5764839588723736093.57',
                             u'instanceName': u'5000D31000FCBE1D',
                          u'objectType': u'ScControllerPort'},
                     u'iscsiGateway': u'0.0.0.0',
                     u'instanceId': u'64702.5764839588723736118.50',
                     u'scName': u'Storage Center 64702',
                     u'scSerialNumber': 64702,
                     u'transportType': u'FibreChannel',
                     u'virtual': True,
                     u'controller': {u'instanceId': u'64702.64703',
                                     u'instanceName': u'SN 64703',
                                     u'objectType': u'ScController'},
                     u'iscsiName': u'',
                     u'purpose': u'FrontEnd',
                     u'iscsiSubnetMask': u'0.0.0.0',
                     u'faultDomain':
                         {u'instanceId': u'64702.1.0',
                          u'instanceName': u'Domain 0',
                          u'objectType': u'ScControllerPortFaultDomain'},
                     u'instanceName': u'5000D31000FCBE36',
                     u'childStatus': u'Up',
                     u'statusMessage': u'',
                     u'objectType': u'ScControllerPort'}

    FC_CTRLR_PORT_WWN_ERROR = \
        {u'preferredParent':
         {u'instanceId': u'64702.5764839588723736093.57',
          u'instanceName': u'5000D31000FCBE1D',
          u'objectType': u'ScControllerPort'},
         u'status': u'Up',
         u'iscsiIpAddress': u'0.0.0.0',
         u'Wwn': u'5000D31000FCBE36',
         u'name': u'5000D31000FCBE36',
         u'parent':
         {u'instanceId': u'64702.5764839588723736093.57',
          u'instanceName': u'5000D31000FCBE1D',
          u'objectType': u'ScControllerPort'},
         u'iscsiGateway': u'0.0.0.0',
         u'instanceId': u'64702.5764839588723736118.50',
         u'scName': u'Storage Center 64702',
         u'scSerialNumber': 64702,
         u'transportType': u'FibreChannel',
         u'virtual': True,
         u'controller': {u'instanceId': u'64702.64703',
                         u'instanceName': u'SN 64703',
                         u'objectType': u'ScController'},
         u'iscsiName': u'',
         u'purpose': u'FrontEnd',
         u'iscsiSubnetMask': u'0.0.0.0',
         u'faultDomain':
         {u'instanceId': u'64702.1.0',
          u'instanceName': u'Domain 0',
          u'objectType': u'ScControllerPortFaultDomain'},
         u'instanceName': u'5000D31000FCBE36',
         u'childStatus': u'Up',
         u'statusMessage': u'',
         u'objectType': u'ScControllerPort'}

    STRG_USAGE = {u'systemSpace': u'7.38197504E8 Bytes',
                  u'freeSpace': u'1.297659461632E13 Bytes',
                  u'oversubscribedSpace': u'0.0 Bytes',
                  u'instanceId': u'64702',
                  u'scName': u'Storage Center 64702',
                  u'savingVsRaidTen': u'1.13737990144E11 Bytes',
                  u'allocatedSpace': u'1.66791217152E12 Bytes',
                  u'usedSpace': u'3.25716017152E11 Bytes',
                  u'configuredSpace': u'9.155796533248E12 Bytes',
                  u'alertThresholdSpace': u'1.197207956992E13 Bytes',
                  u'availableSpace': u'1.3302310633472E13 Bytes',
                  u'badSpace': u'0.0 Bytes',
                  u'time': u'02/02/2015 02:23:39 PM',
                  u'scSerialNumber': 64702,
                  u'instanceName': u'Storage Center 64702',
                  u'storageAlertThreshold': 10,
                  u'objectType': u'StorageCenterStorageUsage'}

    IQN = 'iqn.2002-03.com.compellent:5000D31000000001'
    WWN = u'21000024FF30441C'

    WWNS = [u'21000024FF30441C',
            u'21000024FF30441D']

    # Used to test finding no match in find_wwns
    WWNS_NO_MATCH = [u'21000024FF30451C',
                     u'21000024FF30451D']

    FLDR_PATH = 'StorageCenter/ScVolumeFolder/'

    # Create a Response object that indicates OK
    response_ok = models.Response()
    response_ok.status_code = 200
    response_ok.reason = u'ok'
    RESPONSE_200 = response_ok

    # Create a Response object that indicates created
    response_created = models.Response()
    response_created.status_code = 201
    response_created.reason = u'created'
    RESPONSE_201 = response_created

    # Create a Response object that indicates a failure (no content)
    response_nc = models.Response()
    response_nc.status_code = 204
    response_nc.reason = u'duplicate'
    RESPONSE_204 = response_nc

    def setUp(self):
        super(DellSCSanAPITestCase, self).setUp()

        # Configuration is a mock.  A mock is pretty much a blank
        # slate.  I believe mock's done in setup are not happy time
        # mocks.  So we just do a few things like driver config here.
        self.configuration = mock.Mock()

        self.configuration.san_is_local = False
        self.configuration.san_ip = "192.168.0.1"
        self.configuration.san_login = "admin"
        self.configuration.san_password = "mmm"
        self.configuration.dell_sc_ssn = 12345
        self.configuration.dell_sc_server_folder = 'opnstktst'
        self.configuration.dell_sc_volume_folder = 'opnstktst'
        # Note that we set this to True even though we do not
        # test this functionality.  This is sent directly to
        # the requests calls as the verify parameter and as
        # that is a third party library deeply stubbed out is
        # not directly testable by this code.  Note that in the
        # case that this fails the driver fails to even come
        # up.
        self.configuration.dell_sc_verify_cert = True
        self.configuration.dell_sc_api_port = 3033
        self.configuration.iscsi_ip_address = '192.168.1.1'
        self.configuration.iscsi_port = 3260
        self._context = context.get_admin_context()

        # Set up the StorageCenterApi
        self.scapi = dell_storagecenter_api.StorageCenterApi(
            self.configuration.san_ip,
            self.configuration.dell_sc_api_port,
            self.configuration.san_login,
            self.configuration.san_password,
            self.configuration.dell_sc_verify_cert)

        # Set up the scapi configuration vars
        self.scapi.ssn = self.configuration.dell_sc_ssn
        self.scapi.sfname = self.configuration.dell_sc_server_folder
        self.scapi.vfname = self.configuration.dell_sc_volume_folder

        self.volid = str(uuid.uuid4())
        self.volume_name = "volume" + self.volid

    def test_path_to_array(self,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._path_to_array(u'folder1/folder2/folder3')
        expected = [u'folder1', u'folder2', u'folder3']
        self.assertEqual(expected, res, 'Unexpected folder path')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_result',
                       return_value=SC)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_sc(self,
                     mock_get,
                     mock_get_result,
                     mock_close_connection,
                     mock_open_connection,
                     mock_init):
        res = self.scapi.find_sc()
        mock_get.assert_called_once_with('StorageCenter/StorageCenter')
        self.assertTrue(mock_get_result.called)
        self.assertEqual(u'64702', res, 'Unexpected SSN')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_result',
                       return_value=None)
    def test_find_sc_failure(self,
                             mock_get_result,
                             mock_get,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_sc)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_folder(self,
                           mock_post,
                           mock_first_result,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._create_folder(
            'StorageCenter/ScVolumeFolder',
            '',
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_folder_with_parent(self,
                                       mock_post,
                                       mock_first_result,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where parent folder name is specified
        res = self.scapi._create_folder(
            'StorageCenter/ScVolumeFolder', 'parentFolder',
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_create_folder_failure(self,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi._create_folder(
            'StorageCenter/ScVolumeFolder', '',
            self.configuration.dell_sc_volume_folder)
        self.assertIsNone(res, 'Test Create folder - None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_path_to_array',
                       return_value=['Cinder_Test_Folder'])
    def test_create_folder_path(self,
                                mock_path_to_array,
                                mock_find_folder,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        res = self.scapi._create_folder_path(
            'StorageCenter/ScVolumeFolder',
            self.configuration.dell_sc_volume_folder)
        mock_path_to_array.assert_called_once_with(
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_find_folder.called)
        self.assertEqual(self.FLDR, res, 'Unexpected ScFolder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_create_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_path_to_array',
                       return_value=['Cinder_Test_Folder'])
    def test_create_folder_path_create_fldr(self,
                                            mock_path_to_array,
                                            mock_find_folder,
                                            mock_create_folder,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        # Test case where folder is not found and must be created
        res = self.scapi._create_folder_path(
            'StorageCenter/ScVolumeFolder',
            self.configuration.dell_sc_volume_folder)
        mock_path_to_array.assert_called_once_with(
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_find_folder.called)
        self.assertTrue(mock_create_folder.called)
        self.assertEqual(self.FLDR, res, 'Unexpected ScFolder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_create_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_path_to_array',
                       return_value=['Cinder_Test_Folder'])
    def test_create_folder_path_failure(self,
                                        mock_path_to_array,
                                        mock_find_folder,
                                        mock_create_folder,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        # Test case where folder is not found, must be created
        # and creation fails
        res = self.scapi._create_folder_path(
            'StorageCenter/ScVolumeFolder',
            self.configuration.dell_sc_volume_folder)
        mock_path_to_array.assert_called_once_with(
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_find_folder.called)
        self.assertTrue(mock_create_folder.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_result',
                       return_value=u'devstackvol/fcvm/')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder(self,
                         mock_post,
                         mock_get_result,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.scapi._find_folder(
            'StorageCenter/ScVolumeFolder',
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_result.called)
        self.assertEqual(u'devstackvol/fcvm/', res, 'Unexpected folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_result',
                       return_value=u'devstackvol/fcvm/')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder_multi_fldr(self,
                                    mock_post,
                                    mock_get_result,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case for folder path with multiple folders
        res = self.scapi._find_folder(
            'StorageCenter/ScVolumeFolder',
            u'testParentFolder/opnstktst')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_result.called)
        self.assertEqual(u'devstackvol/fcvm/', res, 'Unexpected folder')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_find_folder_failure(self,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        res = self.scapi._find_folder(
            'StorageCenter/ScVolumeFolder',
            self.configuration.dell_sc_volume_folder)
        self.assertIsNone(res, 'Test find folder - None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    def test_find_volume_folder_fail(self,
                                     mock_find_folder,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where _find_volume_folder returns none
        res = self.scapi._find_volume_folder(
            False)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            self.configuration.dell_sc_volume_folder)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=FLDR)
    def test_find_volume_folder(self,
                                mock_find_folder,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        res = self.scapi._find_volume_folder(
            False)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            self.configuration.dell_sc_volume_folder)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_create_folder_path',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    def test_find_volume_folder_create_folder(self,
                                              mock_find_folder,
                                              mock_create_folder_path,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case where _find_volume_folder returns none and folder must be
        # created
        res = self.scapi._find_volume_folder(
            True)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            self.configuration.dell_sc_volume_folder)
        self.assertTrue(mock_create_folder_path.called)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=SCSERVERS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_init_volume(self,
                         mock_post,
                         mock_get_json,
                         mock_map_volume,
                         mock_unmap_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        self.scapi._init_volume(self.VOLUME)
        self.assertTrue(mock_map_volume.called)
        self.assertTrue(mock_unmap_volume.called)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_init_volume_failure(self,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test case where ScServer list fails
        self.scapi._init_volume(self.VOLUME)
        self.assertTrue(mock_post.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=SCSERVERS_DOWN)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_init_volume_servers_down(self,
                                      mock_post,
                                      mock_get_json,
                                      mock_map_volume,
                                      mock_unmap_volume,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case where ScServer Status = Down
        self.scapi._init_volume(self.VOLUME)
        self.assertFalse(mock_map_volume.called)
        self.assertFalse(mock_unmap_volume.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_volume(self,
                           mock_post,
                           mock_find_volume_folder,
                           mock_get_json,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.create_volume(
            self.volume_name,
            1)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_volume_retry_find(self,
                                      mock_post,
                                      mock_find_volume_folder,
                                      mock_get_json,
                                      mock_find_volume,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case where find_volume is used to do a retry of finding the
        # created volume
        res = self.scapi.create_volume(
            self.volume_name,
            1)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(mock_find_volume.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_vol_folder_fail(self,
                                    mock_post,
                                    mock_find_volume_folder,
                                    mock_get_json,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test calling create_volume where volume folder does not exist and
        # fails to be created
        res = self.scapi.create_volume(
            self.volume_name,
            1)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_create_volume_failure(self,
                                   mock_post,
                                   mock_find_volume_folder,
                                   mock_get_json,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.create_volume(
            self.volume_name,
            1)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=VOLUME_LIST)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test__get_volume_list_enforce_vol_fldr(self,
                                               mock_post,
                                               mock_get_json,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        # Test case to find volume in the configured volume folder
        res = self.scapi._get_volume_list(self.volume_name, True)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.VOLUME_LIST, res, 'Unexpected volume list')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=VOLUME_LIST)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test__get_volume_list_any_fldr(self,
                                       mock_post,
                                       mock_get_json,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case to find volume anywhere in the configured SC
        res = self.scapi._get_volume_list(self.volume_name, False)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.VOLUME_LIST, res, 'Unexpected volume list')

    def test__get_volume_list_no_name(self,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case specified volume name is None
        res = self.scapi._get_volume_list(None, True)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test__get_volume_list_failure(self,
                                      mock_post,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case to find volume in the configured volume folder
        res = self.scapi._get_volume_list(self.volume_name, True)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_volume_list',
                       return_value=VOLUME_LIST)
    def test_find_volume(self,
                         mock_get_vol_list,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        # Test case to find volume by name
        res = self.scapi.find_volume(self.volume_name)
        self.assertTrue(mock_get_vol_list.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected volume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_volume_list',
                       return_value=None)
    def test_find_volume_no_name(self,
                                 mock_get_volume_list,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test calling find_volume with no name or instanceid
        res = self.scapi.find_volume(None)
        self.assertEqual(res, None, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_volume_list')
    def test_find_volume_not_found(self,
                                   mock_get_volume_list,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test calling find_volume with result of no volume found
        mock_get_volume_list.side_effect = [[], []]
        res = self.scapi.find_volume(self.volume_name)
        self.assertEqual(None, res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_volume_list',
                       return_value=VOLUME_LIST_MULTI_VOLS)
    def test_find_volume_multi_vols_found(self,
                                          mock_get_volume_list,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        # Test case where multiple volumes are found
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_volume, self.volume_name)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_delete_volume(self,
                           mock_find_volume,
                           mock_delete,
                           mock_get_json,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.delete_volume(self.volume_name)
        self.assertTrue(mock_delete.called)
        mock_find_volume.assert_called_once_with(self.volume_name)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_204)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_delete_volume_failure(self,
                                   mock_find_volume,
                                   mock_delete,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.delete_volume, self.volume_name)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    def test_delete_volume_no_vol_found(self,
                                        mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        # Test case where volume to be deleted does not exist
        res = self.scapi.delete_volume(self.volume_name)
        self.assertTrue(res, 'Expected True')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=SVR_FLDR)
    def test_find_server_folder(self,
                                mock_find_folder,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        res = self.scapi._find_server_folder(False)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScServerFolder/GetList',
            self.configuration.dell_sc_server_folder)
        self.assertEqual(self.SVR_FLDR, res, 'Unexpected server folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_create_folder_path',
                       return_value=SVR_FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    def test_find_server_folder_create_folder(self,
                                              mock_find_folder,
                                              mock_create_folder_path,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case where specified server folder is not found and must be
        # created
        res = self.scapi._find_server_folder(True)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScServerFolder/GetList',
            self.configuration.dell_sc_server_folder)
        self.assertTrue(mock_create_folder_path.called)
        self.assertEqual(self.SVR_FLDR, res, 'Unexpected server folder')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_folder',
                       return_value=None)
    def test_find_server_folder_fail(self,
                                     mock_find_folder,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where _find_server_folder returns none
        res = self.scapi._find_server_folder(
            False)
        mock_find_folder.assert_called_once_with(
            'StorageCenter/ScServerFolder/GetList',
            self.configuration.dell_sc_volume_folder)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_add_hba(self,
                     mock_post,
                     mock_close_connection,
                     mock_open_connection,
                     mock_init):
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.IQN,
                                  False)
        self.assertTrue(mock_post.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_add_hba_fc(self,
                        mock_post,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.WWN,
                                  True)
        self.assertTrue(mock_post.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_add_hba_failure(self,
                             mock_post,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.IQN,
                                  False)
        self.assertTrue(mock_post.called)
        self.assertFalse(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=SVR_OS_S)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_serveros(self,
                           mock_post,
                           mock_get_json,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._find_serveros('Red Hat Linux 6.x')
        self.assertTrue(mock_get_json.called)
        self.assertTrue(mock_post.called)
        self.assertEqual('64702.38', res, 'Wrong InstanceId')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=SVR_OS_S)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_serveros_not_found(self,
                                     mock_post,
                                     mock_get_json,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test requesting a Server OS that will not be found
        res = self.scapi._find_serveros('Non existent OS')
        self.assertTrue(mock_get_json.called)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_find_serveros_failed(self,
                                  mock_post,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi._find_serveros('Red Hat Linux 6.x')
        self.assertEqual(None, res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=FC_HBA)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server',
                       return_value=SCSERVER)
    def test_create_server_multiple_hbas(self,
                                         mock_create_server,
                                         mock_add_hba,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.create_server_multiple_hbas(
            self.WWNS)
        self.assertTrue(mock_create_server.called)
        self.assertTrue(mock_add_hba.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_server(self,
                           mock_post,
                           mock_find_serveros,
                           mock_find_server_folder,
                           mock_first_result,
                           mock_add_hba,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertTrue(mock_find_serveros.called)
        self.assertTrue(mock_find_server_folder.called)
        self.assertTrue(mock_first_result.called)
        self.assertTrue(mock_add_hba.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_server_os_not_found(self,
                                        mock_post,
                                        mock_find_serveros,
                                        mock_find_server_folder,
                                        mock_first_result,
                                        mock_add_hba,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertTrue(mock_find_serveros.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_server_fldr_not_found(self,
                                          mock_post,
                                          mock_find_serveros,
                                          mock_find_server_folder,
                                          mock_first_result,
                                          mock_add_hba,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertTrue(mock_find_server_folder.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_create_server_failure(self,
                                   mock_post,
                                   mock_find_serveros,
                                   mock_find_server_folder,
                                   mock_first_result,
                                   mock_add_hba,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_server_not_found(self,
                                     mock_post,
                                     mock_find_serveros,
                                     mock_find_server_folder,
                                     mock_first_result,
                                     mock_add_hba,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test create server where _first_result is None
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_delete_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_add_hba',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_server_addhba_fail(self,
                                       mock_post,
                                       mock_find_serveros,
                                       mock_find_server_folder,
                                       mock_first_result,
                                       mock_add_hba,
                                       mock_delete_server,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Tests create server where add hba fails
        res = self.scapi.create_server(
            self.IQN,
            False)
        self.assertTrue(mock_delete_server.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serverhba',
                       return_value=ISCSI_HBA)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_server(self,
                         mock_post,
                         mock_find_serverhba,
                         mock_first_result,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.scapi.find_server(self.IQN)
        self.assertTrue(mock_find_serverhba.called)
        self.assertTrue(mock_first_result.called)
        self.assertIsNotNone(res, 'Expected ScServer')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serverhba',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_server_no_hba(self,
                                mock_post,
                                mock_find_serverhba,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # Test case where a ScServer HBA does not exist with the specified IQN
        # or WWN
        res = self.scapi.find_server(self.IQN)
        self.assertTrue(mock_find_serverhba.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_serverhba',
                       return_value=ISCSI_HBA)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_find_server_failure(self,
                                 mock_post,
                                 mock_find_serverhba,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test case where a ScServer does not exist with the specified
        # ScServerHba
        res = self.scapi.find_server(self.IQN)
        self.assertTrue(mock_find_serverhba.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=ISCSI_HBA)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_serverhba(self,
                            mock_post,
                            mock_first_result,
                            mock_close_connection,
                            mock_open_connection,
                            mock_init):
        res = self.scapi.find_server(self.IQN)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertIsNotNone(res, 'Expected ScServerHba')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_find_serverhba_failure(self,
                                    mock_post,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where a ScServer does not exist with the specified
        # ScServerHba
        res = self.scapi.find_server(self.IQN)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_domains(self,
                          mock_get,
                          mock_get_json,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        res = self.scapi._find_domains(u'64702.5764839588723736074.69')
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(
            self.ISCSI_FLT_DOMAINS, res, 'Unexpected ScIscsiFaultDomain')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_domains_error(self,
                                mock_get,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # Test case where get of ScControllerPort FaultDomainList fails
        res = self.scapi._find_domains(u'64702.5764839588723736074.69')
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_domain(self,
                         mock_get,
                         mock_get_json,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.scapi._find_domain(u'64702.5764839588723736074.69',
                                      u'192.168.0.21')
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNotNone(res, 'Expected ScIscsiFaultDomain')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_domain_error(self,
                               mock_get,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        # Test case where get of ScControllerPort FaultDomainList fails
        res = self.scapi._find_domain(u'64702.5764839588723736074.69',
                                      u'192.168.0.21')
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_domain_not_found(self,
                                   mock_get,
                                   mock_get_json,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where domainip does not equal any WellKnownIpAddress
        # of the fault domains
        res = self.scapi._find_domain(u'64702.5764839588723736074.69',
                                      u'192.168.0.22')
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=FC_HBAS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_fc_initiators(self,
                                mock_get,
                                mock_get_json,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        res = self.scapi._find_fc_initiators(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNotNone(res, 'Expected WWN list')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_fc_initiators_error(self,
                                      mock_get,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case where get of ScServer HbaList fails
        res = self.scapi._find_fc_initiators(self.SCSERVER)
        self.assertListEqual([], res, 'Expected empty list')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_get_volume_count(self,
                              mock_get,
                              mock_get_json,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        res = self.scapi.get_volume_count(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(len(self.MAPPINGS), res, 'Mapping count mismatch')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_get_volume_count_failure(self,
                                      mock_get,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case of where get of ScServer MappingList fails
        res = self.scapi.get_volume_count(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertEqual(-1, res, 'Mapping count not -1')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_get_volume_count_no_volumes(self,
                                         mock_get,
                                         mock_get_json,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.get_volume_count(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(len([]), res, 'Mapping count mismatch')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_mappings(self,
                           mock_get,
                           mock_get_json,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._find_mappings(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.MAPPINGS, res, 'Mapping mismatch')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_mappings_inactive_vol(self,
                                        mock_get,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        # Test getting volume mappings on inactive volume
        res = self.scapi._find_mappings(self.INACTIVE_VOLUME)
        self.assertFalse(mock_get.called)
        self.assertEqual([], res, 'No mappings expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_mappings_failure(self,
                                   mock_get,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case of where get of ScVolume MappingList fails
        res = self.scapi._find_mappings(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertEqual([], res, 'Mapping count not empty')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_mappings_no_mappings(self,
                                       mock_get,
                                       mock_get_json,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where ScVolume has no mappings
        res = self.scapi._find_mappings(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual([], res, 'Mapping count mismatch')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_controller_port(self,
                                  mock_get,
                                  mock_first_result,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi._find_controller_port(u'64702.5764839588723736070.51')
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.CTRLR_PORT, res, 'ScControllerPort mismatch')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_controller_port_failure(self,
                                          mock_get,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        # Test case where get of ScVolume MappingList fails
        res = self.scapi._find_controller_port(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=WWNS)
    def test_find_wwns(self,
                       mock_find_fc_initiators,
                       mock_find_mappings,
                       mock_find_controller_port,
                       mock_close_connection,
                       mock_open_connection,
                       mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        # The _find_controller_port is Mocked, so all mapping pairs
        # will have the same WWN for the ScControllerPort
        itmapCompare = {u'21000024FF30441C': [u'5000D31000FCBE36'],
                        u'21000024FF30441D':
                        [u'5000D31000FCBE36', u'5000D31000FCBE36']}
        self.assertEqual(1, lun, 'Incorrect LUN')
        self.assertIsNotNone(wwns, 'WWNs is None')
        self.assertEqual(itmapCompare, itmap, 'WWN mapping incorrect')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=[])
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=FC_HBAS)
    def test_find_wwns_no_mappings(self,
                                   mock_find_fc_initiators,
                                   mock_find_mappings,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where there are no ScMapping(s)
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertEqual(None, lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=WWNS)
    def test_find_wwns_no_ctlr_port(self,
                                    mock_find_fc_initiators,
                                    mock_find_mappings,
                                    mock_find_controller_port,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where ScControllerPort is none
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)
        self.assertEqual(None, lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT_WWN_ERROR)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=WWNS)
    def test_find_wwns_wwn_error(self,
                                 mock_find_fc_initiators,
                                 mock_find_mappings,
                                 mock_find_controller_port,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test case where ScControllerPort object has WWn instead of wwn for a
        # property
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        self.assertEqual(None, lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=WWNS_NO_MATCH)
    # Test case where HBA name is not found in list of initiators
    def test_find_wwns_hbaname_not_found(self,
                                         mock_find_fc_initiators,
                                         mock_find_mappings,
                                         mock_find_controller_port,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        self.assertEqual(None, lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS_LUN_MISMATCH)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_fc_initiators',
                       return_value=WWNS)
    # Test case where FC mappings contain a LUN mismatch
    def test_find_wwns_lun_mismatch(self,
                                    mock_find_fc_initiators,
                                    mock_find_mappings,
                                    mock_find_controller_port,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_fc_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)
        # The _find_controller_port is Mocked, so all mapping pairs
        # will have the same WWN for the ScControllerPort
        itmapCompare = {u'21000024FF30441C': [u'5000D31000FCBE36'],
                        u'21000024FF30441D':
                        [u'5000D31000FCBE36', u'5000D31000FCBE36']}
        self.assertEqual(1, lun, 'Incorrect LUN')
        self.assertIsNotNone(wwns, 'WWNs is None')
        self.assertEqual(itmapCompare, itmap, 'WWN mapping incorrect')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=VOLUME_CONFIG)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_active_controller(self,
                                    mock_get,
                                    mock_first_result,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        res = self.scapi._find_active_controller(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual('64702.64703', res, 'Unexpected Active Controller')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_active_controller_failure(self,
                                            mock_get,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        # Test case of where get of ScVolume MappingList fails
        res = self.scapi._find_active_controller(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertEqual(None, res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.5764839588723736131.91')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    def test_find_iscsi_properties_mappings(self,
                                            mock_find_mappings,
                                            mock_find_domain,
                                            mock_find_ctrl_port,
                                            mock_find_active_controller,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        res = self.scapi.find_iscsi_properties(self.VOLUME)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'access_mode': 'rw',
                    'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    def test_find_iscsi_properties_by_address(self,
                                              mock_find_mappings,
                                              mock_find_domain,
                                              mock_find_ctrl_port,
                                              mock_find_active_controller,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case to find iSCSI mappings by IP Address & port
        res = self.scapi.find_iscsi_properties(
            self.VOLUME, '192.168.0.21', 3260)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'access_mode': 'rw',
                    'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    def test_find_iscsi_properties_by_address_not_found(self,
                                                        mock_find_mappings,
                                                        mock_find_domain,
                                                        mock_find_ctrl_port,
                                                        mock_find_active_ctrl,
                                                        mock_close_connection,
                                                        mock_open_connection,
                                                        mock_init):
        # Test case to find iSCSI mappings by IP Address & port are not found
        res = self.scapi.find_iscsi_properties(
            self.VOLUME, '192.168.1.21', 3260)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_ctrl.called)
        expected = {'access_mode': 'rw',
                    'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=[])
    def test_find_iscsi_properties_no_mapping(self,
                                              mock_find_mappings,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case where there are no ScMapping(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME)
        self.assertTrue(mock_find_mappings.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    def test_find_iscsi_properties_no_domain(self,
                                             mock_find_mappings,
                                             mock_find_domain,
                                             mock_find_ctrl_port,
                                             mock_find_active_controller,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        # Test case where there are no ScFaultDomain(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    def test_find_iscsi_properties_no_ctrl_port(self,
                                                mock_find_mappings,
                                                mock_find_domain,
                                                mock_find_ctrl_port,
                                                mock_find_active_controller,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        # Test case where there are no ScFaultDomain(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS_READ_ONLY)
    def test_find_iscsi_properties_ro(self,
                                      mock_find_mappings,
                                      mock_find_domain,
                                      mock_find_ctrl_port,
                                      mock_find_active_controller,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case where Read Only mappings are found
        res = self.scapi.find_iscsi_properties(self.VOLUME)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'access_mode': 'ro',
                    'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS_MULTI_PORTALS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_mappings',
                       return_value=MAPPINGS_MULTI_PORTAL)
    def test_find_iscsi_properties_multi_portals(self,
                                                 mock_find_mappings,
                                                 mock_find_domain,
                                                 mock_find_ctrl_port,
                                                 mock_find_active_controller,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        # Test case where there are multiple portals
        res = self.scapi.find_iscsi_properties(self.VOLUME)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domain.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'access_mode': 'rw',
                    'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1, 1, 1, 1],
                    'target_portal': u'192.168.0.25:3260',
                    'target_portals': [u'192.168.0.21:3260',
                                       u'192.168.0.25:3260',
                                       u'192.168.0.21:3260',
                                       u'192.168.0.25:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=MAP_PROFILE)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_map_volume(self,
                        mock_post,
                        mock_first_result,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.MAP_PROFILE, res, 'Incorrect ScMappingProfile')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_id')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post')
    def test_map_volume_no_vol_id(self,
                                  mock_post,
                                  mock_first_result,
                                  mock_get_id,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        # Test case where ScVolume instanceId is None
        mock_get_id.side_effect = [None, '64702.47']
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertFalse(mock_post.called)
        self.assertFalse(mock_first_result.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_id')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post')
    def test_map_volume_no_server_id(self,
                                     mock_post,
                                     mock_first_result,
                                     mock_get_id,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where ScVolume instanceId is None
        mock_get_id.side_effect = ['64702.3494', None]
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertFalse(mock_post.called)
        self.assertFalse(mock_first_result.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_map_volume_failure(self,
                                mock_post,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # Test case where mapping volume to server fails
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAP_PROFILES)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_unmap_volume(self,
                          mock_get,
                          mock_get_json,
                          mock_delete,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_unmap_volume_failure(self,
                                  mock_get,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertFalse(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_unmap_volume_no_map_profile(self,
                                         mock_get,
                                         mock_get_json,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_204)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAP_PROFILES)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_unmap_volume_del_fail(self,
                                   mock_get,
                                   mock_get_json,
                                   mock_delete,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(mock_delete.called)
        self.assertFalse(res, False)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_id')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAP_PROFILES)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_unmap_volume_no_vol_id(self,
                                    mock_get,
                                    mock_get_json,
                                    mock_delete,
                                    mock_get_id,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where ScVolume instanceId = None
        mock_get_id.side_effect = [None, '64702.47']
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertFalse(mock_get.called)
        self.assertFalse(mock_get_json.called)
        self.assertFalse(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_id')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=MAP_PROFILES)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_unmap_volume_no_server_id(self,
                                       mock_get,
                                       mock_get_json,
                                       mock_delete,
                                       mock_get_id,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where ScVolume instanceId = None
        mock_get_id.side_effect = ['64702.3494', None]
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertFalse(mock_get.called)
        self.assertFalse(mock_get_json.called)
        self.assertFalse(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=STRG_USAGE)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_get_storage_usage(self,
                               mock_get,
                               mock_get_json,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        res = self.scapi.get_storage_usage()
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.STRG_USAGE, res, 'Unexpected ScStorageUsage')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_get_storage_usage_no_ssn(self,
                                      mock_get,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case where SSN is none
        self.scapi.ssn = None
        res = self.scapi.get_storage_usage()
        self.scapi.ssn = 12345
        self.assertFalse(mock_get.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    # Test case where get of Storage Usage fails
    def test_get_storage_usage_failure(self,
                                       mock_get,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        res = self.scapi.get_storage_usage()
        self.assertTrue(mock_get.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_replay(self,
                           mock_post,
                           mock_first_result,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.create_replay(self.VOLUME,
                                       'Test Replay',
                                       60)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.RPLAY, res, 'Unexpected ScReplay')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_init_volume')
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_replay_inact_vol(self,
                                     mock_post,
                                     mock_init_volume,
                                     mock_first_result,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where the specified volume is inactive
        res = self.scapi.create_replay(self.INACTIVE_VOLUME,
                                       'Test Replay',
                                       60)
        self.assertTrue(mock_post.called)
        mock_init_volume.assert_called_once_with(self.INACTIVE_VOLUME)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.RPLAY, res, 'Unexpected ScReplay')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_replay_no_expire(self,
                                     mock_post,
                                     mock_first_result,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        res = self.scapi.create_replay(self.VOLUME,
                                       'Test Replay',
                                       0)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.RPLAY, res, 'Unexpected ScReplay')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_replay_no_volume(self,
                                     mock_post,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where no ScVolume is specified
        res = self.scapi.create_replay(None,
                                       'Test Replay',
                                       60)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_create_replay_failure(self,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where create ScReplay fails
        res = self.scapi.create_replay(self.VOLUME,
                                       'Test Replay',
                                       60)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=RPLAYS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_replay(self,
                         mock_post,
                         mock_get_json,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.scapi.find_replay(self.VOLUME,
                                     u'Cinder Test Replay012345678910')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.TST_RPLAY, res, 'Unexpected ScReplay')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_replay_no_replays(self,
                                    mock_post,
                                    mock_get_json,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where no replays are found
        res = self.scapi.find_replay(self.VOLUME,
                                     u'Cinder Test Replay012345678910')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_204)
    def test_find_replay_failure(self,
                                 mock_post,
                                 mock_get_json,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test case where None is returned for replays
        res = self.scapi.find_replay(self.VOLUME,
                                     u'Cinder Test Replay012345678910')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value=RPLAYS)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_delete_replay(self,
                           mock_post,
                           mock_find_replay,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        replayId = u'Cinder Test Replay012345678910'
        res = self.scapi.delete_replay(self.VOLUME,
                                       replayId)
        self.assertTrue(mock_post.called)
        mock_find_replay.assert_called_once_with(self.VOLUME, replayId)
        self.assertTrue(res, 'Expected True')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_delete_replay_no_replay(self,
                                     mock_post,
                                     mock_find_replay,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where specified ScReplay does not exist
        replayId = u'Cinder Test Replay012345678910'
        res = self.scapi.delete_replay(self.VOLUME,
                                       replayId)
        self.assertFalse(mock_post.called)
        mock_find_replay.assert_called_once_with(self.VOLUME, replayId)
        self.assertTrue(res, 'Expected True')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value=TST_RPLAY)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_delete_replay_failure(self,
                                   mock_post,
                                   mock_find_replay,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where delete ScReplay results in an error
        replayId = u'Cinder Test Replay012345678910'
        res = self.scapi.delete_replay(self.VOLUME,
                                       replayId)
        self.assertTrue(mock_post.called)
        mock_find_replay.assert_called_once_with(self.VOLUME, replayId)
        self.assertFalse(res, 'Expected False')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_view_volume(self,
                                mock_post,
                                mock_find_volume_folder,
                                mock_first_result,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        vol_name = u'Test_create_vol'
        res = self.scapi.create_view_volume(
            vol_name,
            self.TST_RPLAY)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_view_volume_create_fldr(self,
                                            mock_post,
                                            mock_find_volume_folder,
                                            mock_first_result,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        # Test case where volume folder does not exist and must be created
        vol_name = u'Test_create_vol'
        res = self.scapi.create_view_volume(
            vol_name,
            self.TST_RPLAY)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_view_volume_no_vol_fldr(self,
                                            mock_post,
                                            mock_find_volume_folder,
                                            mock_first_result,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        # Test case where volume folder does not exist and cannot be created
        vol_name = u'Test_create_vol'
        res = self.scapi.create_view_volume(
            vol_name,
            self.TST_RPLAY)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_create_view_volume_failure(self,
                                        mock_post,
                                        mock_find_volume_folder,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        # Test case where view volume create fails
        vol_name = u'Test_create_vol'
        res = self.scapi.create_view_volume(
            vol_name,
            self.TST_RPLAY)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_view_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay',
                       return_value=RPLAY)
    def test_create_cloned_volume(self,
                                  mock_create_replay,
                                  mock_create_view_volume,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        vol_name = u'Test_create_clone_vol'
        res = self.scapi.create_cloned_volume(
            vol_name,
            self.VOLUME)
        mock_create_replay.assert_called_once_with(self.VOLUME,
                                                   'Cinder Clone Replay',
                                                   60)
        mock_create_view_volume.assert_called_once_with(
            vol_name,
            self.RPLAY)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay',
                       return_value=None)
    def test_create_cloned_volume_failure(self,
                                          mock_create_replay,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        # Test case where create cloned volumes fails because create_replay
        # fails
        vol_name = u'Test_create_clone_vol'
        res = self.scapi.create_cloned_volume(
            vol_name,
            self.VOLUME)
        mock_create_replay.assert_called_once_with(self.VOLUME,
                                                   'Cinder Clone Replay',
                                                   60)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_expand_volume(self,
                           mock_post,
                           mock_get_json,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.expand_volume(self.VOLUME, 550)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_expand_volume_failure(self,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.expand_volume(self.VOLUME, 550)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_rename_volume(self,
                           mock_post,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.rename_volume(self.VOLUME, 'newname')
        self.assertTrue(mock_post.called)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_rename_volume_failure(self,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.rename_volume(self.VOLUME, 'newname')
        self.assertTrue(mock_post.called)
        self.assertFalse(res)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    def test_delete_server(self,
                           mock_delete,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._delete_server(self.SCSERVER)
        self.assertTrue(mock_delete.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    def test_delete_server_del_not_allowed(self,
                                           mock_delete,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        # Test case where delete of ScServer not allowed
        res = self.scapi._delete_server(self.SCSERVER_NO_DEL)
        self.assertFalse(mock_delete.called)
        self.assertIsNone(res, 'Expected None')


class DellSCSanAPIConnectionTestCase(test.TestCase):

    '''DellSCSanAPIConnectionTestCase

    Class to test the Storage Center API connection using Mock.
    '''

    # Create a Response object that indicates OK
    response_ok = models.Response()
    response_ok.status_code = 200
    response_ok.reason = u'ok'
    RESPONSE_200 = response_ok

    # Create a Response object that indicates a failure (no content)
    response_nc = models.Response()
    response_nc.status_code = 204
    response_nc.reason = u'duplicate'
    RESPONSE_204 = response_nc

    def setUp(self):
        super(DellSCSanAPIConnectionTestCase, self).setUp()

        # Configuration is a mock.  A mock is pretty much a blank
        # slate.  I believe mock's done in setup are not happy time
        # mocks.  So we just do a few things like driver config here.
        self.configuration = mock.Mock()

        self.configuration.san_is_local = False
        self.configuration.san_ip = "192.168.0.1"
        self.configuration.san_login = "admin"
        self.configuration.san_password = "mmm"
        self.configuration.dell_sc_ssn = 12345
        self.configuration.dell_sc_server_folder = 'openstack'
        self.configuration.dell_sc_volume_folder = 'openstack'
        # Note that we set this to True even though we do not
        # test this functionality.  This is sent directly to
        # the requests calls as the verify parameter and as
        # that is a third party library deeply stubbed out is
        # not directly testable by this code.  Note that in the
        # case that this fails the driver fails to even come
        # up.
        self.configuration.dell_sc_verify_cert = True
        self.configuration.dell_sc_api_port = 3033
        self.configuration.iscsi_ip_address = '192.168.1.1'
        self.configuration.iscsi_port = 3260
        self._context = context.get_admin_context()

        # Set up the StorageCenterApi
        self.scapi = dell_storagecenter_api.StorageCenterApi(
            self.configuration.san_ip,
            self.configuration.dell_sc_api_port,
            self.configuration.san_login,
            self.configuration.san_password,
            self.configuration.dell_sc_verify_cert)

        # Set up the scapi configuration vars
        self.scapi.ssn = self.configuration.dell_sc_ssn
        self.scapi.sfname = self.configuration.dell_sc_server_folder
        self.scapi.vfname = self.configuration.dell_sc_volume_folder

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_open_connection(self,
                             mock_post):
        self.scapi.open_connection()
        self.assertTrue(mock_post.called)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_open_connection_failure(self,
                                     mock_post):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.open_connection)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_close_connection(self,
                              mock_post):
        self.scapi.close_connection()
        self.assertTrue(mock_post.called)

    @mock.patch.object(dell_storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_close_connection_failure(self,
                                      mock_post):
        self.scapi.close_connection()
        self.assertTrue(mock_post.called)
