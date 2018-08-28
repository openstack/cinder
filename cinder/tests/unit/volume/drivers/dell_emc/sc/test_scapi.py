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

import ddt
import eventlet
import json
import mock
import requests
from requests import models
import uuid

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.volume.drivers.dell_emc.sc import storagecenter_api


# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.
@ddt.ddt
@mock.patch.object(storagecenter_api.SCApi,
                   '__init__',
                   return_value=None)
@mock.patch.object(storagecenter_api.SCApi,
                   'open_connection')
@mock.patch.object(storagecenter_api.SCApi,
                   'close_connection')
class DellSCSanAPITestCase(test.TestCase):

    """DellSCSanAPITestCase

    Class to test the Storage Center API using Mock.
    """

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
                u'notes': u'Created by Dell EMC Cinder Driver',
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
                       u'notes': u'Created by Dell EMC Cinder Driver',
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

    MAP_PROFILES = [MAP_PROFILE]

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
                                   u'instanceName': u'21000024ff30441c',
                                   u'objectType': u'ScServerHba'},
                    u'path': {u'instanceId': u'64702.64702.64703.27.73',
                              u'instanceName':
                                  u'21000024ff30441c-5000d31000fcbe36',
                              u'objectType': u'ScServerHbaPath'},
                    u'controllerPort':
                        {u'instanceId': u'64702.5764839588723736118.50',
                         u'instanceName': u'5000d31000fcbe36',
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
                                   u'instanceName': u'21000024ff30441d',
                                   u'objectType': u'ScServerHba'},
                    u'path':
                    {u'instanceId': u'64702.64702.64703.27.78',
                       u'instanceName': u'21000024ff30441d-5000d31000fcbe36',
                       u'objectType': u'ScServerHbaPath'},
                    u'controllerPort':
                        {u'instanceId': u'64702.5764839588723736118.50',
                         u'instanceName': u'5000d31000fcbe36',
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
                                   u'instanceName': u'21000024ff30441d',
                                   u'objectType': u'ScServerHba'},
                    u'path':
                        {u'instanceId': u'64702.64702.64703.28.76',
                         u'instanceName': u'21000024ff30441d-5000D31000FCBE3E',
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
                         u'instanceName': u'21000024ff30441c',
                         u'objectType': u'ScServerHba'},
          u'path': {u'instanceId': u'64702.64702.64703.27.73',
                    u'instanceName':
                    u'21000024ff30441c-5000d31000fcbe36',
                    u'objectType': u'ScServerHbaPath'},
          u'controllerPort':
          {u'instanceId': u'64702.5764839588723736118.50',
           u'instanceName': u'5000d31000fcbe36',
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
                         u'instanceName': u'21000024ff30441d',
                         u'objectType': u'ScServerHba'},
          u'path':
          {u'instanceId': u'64702.64702.64703.27.78',
           u'instanceName': u'21000024ff30441d-5000d31000fcbe36',
           u'objectType': u'ScServerHbaPath'},
          u'controllerPort':
          {u'instanceId': u'64702.5764839588723736118.50',
           u'instanceName': u'5000d31000fcbe36',
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
                            u'instanceName': u'21000024ff30441d',
                            u'objectType': u'ScServerHba'},
             u'path':
                        {u'instanceId': u'64702.64702.64703.28.76',
                         u'instanceName': u'21000024ff30441d-5000D31000FCBE3E',
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
                u'name': u'21000024ff30441c',
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
                u'instanceName': u'21000024ff30441c',
                u'objectType': u'ScServerHba'},
               {u'portWwnList': [],
                u'iscsiIpAddress': u'0.0.0.0',
                u'pathCount': 3,
                u'name': u'21000024ff30441d',
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
                u'instanceName': u'21000024ff30441d',
                u'objectType': u'ScServerHba'}]

    FC_HBA = {u'portWwnList': [],
              u'iscsiIpAddress': u'0.0.0.0',
              u'pathCount': 3,
              u'name': u'21000024ff30441d',
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
              u'instanceName': u'21000024ff30441d',
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
                     u'WWN': u'5000d31000fcbe36',
                     u'name': u'5000d31000fcbe36',
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
                     u'instanceName': u'5000d31000fcbe36',
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
         u'wWN': u'5000d31000fcbe36',
         u'name': u'5000d31000fcbe36',
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
         u'instanceName': u'5000d31000fcbe36',
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

    RPLAY_PROFILE = {u'name': u'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                     u'type': u'Consistent',
                     u'notes': u'Created by Dell EMC Cinder Driver',
                     u'volumeCount': 0,
                     u'expireIncompleteReplaySets': True,
                     u'replayCreationTimeout': 20,
                     u'enforceReplayCreationTimeout': False,
                     u'ruleCount': 0,
                     u'userCreated': True,
                     u'scSerialNumber': 64702,
                     u'scName': u'Storage Center 64702',
                     u'objectType': u'ScReplayProfile',
                     u'instanceId': u'64702.11',
                     u'instanceName': u'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
    STORAGE_PROFILE_LIST = [
        {u'allowedForFlashOptimized': False,
         u'allowedForNonFlashOptimized': True,
         u'index': 1,
         u'instanceId': u'64158.1',
         u'instanceName': u'Recommended',
         u'name': u'Recommended',
         u'notes': u'',
         u'objectType': u'ScStorageProfile',
         u'raidTypeDescription': u'RAID 10 Active, RAID 5 or RAID 6 Replay',
         u'raidTypeUsed': u'Mixed',
         u'scName': u'Storage Center 64158',
         u'scSerialNumber': 64158,
         u'tiersUsedDescription': u'Tier 1, Tier 2, Tier 3',
         u'useTier1Storage': True,
         u'useTier2Storage': True,
         u'useTier3Storage': True,
         u'userCreated': False,
         u'volumeCount': 125},
        {u'allowedForFlashOptimized': False,
         u'allowedForNonFlashOptimized': True,
         u'index': 2,
         u'instanceId': u'64158.2',
         u'instanceName': u'High Priority',
         u'name': u'High Priority',
         u'notes': u'',
         u'objectType': u'ScStorageProfile',
         u'raidTypeDescription': u'RAID 10 Active, RAID 5 or RAID 6 Replay',
         u'raidTypeUsed': u'Mixed',
         u'scName': u'Storage Center 64158',
         u'scSerialNumber': 64158,
         u'tiersUsedDescription': u'Tier 1',
         u'useTier1Storage': True,
         u'useTier2Storage': False,
         u'useTier3Storage': False,
         u'userCreated': False,
         u'volumeCount': 0},
        {u'allowedForFlashOptimized': False,
         u'allowedForNonFlashOptimized': True,
         u'index': 3,
         u'instanceId': u'64158.3',
         u'instanceName': u'Medium Priority',
         u'name': u'Medium Priority',
         u'notes': u'',
         u'objectType': u'ScStorageProfile',
         u'raidTypeDescription': u'RAID 10 Active, RAID 5 or RAID 6 Replay',
         u'raidTypeUsed': u'Mixed',
         u'scName': u'Storage Center 64158',
         u'scSerialNumber': 64158,
         u'tiersUsedDescription': u'Tier 2',
         u'useTier1Storage': False,
         u'useTier2Storage': True,
         u'useTier3Storage': False,
         u'userCreated': False,
         u'volumeCount': 0},
        {u'allowedForFlashOptimized': True,
         u'allowedForNonFlashOptimized': True,
         u'index': 4,
         u'instanceId': u'64158.4',
         u'instanceName': u'Low Priority',
         u'name': u'Low Priority',
         u'notes': u'',
         u'objectType': u'ScStorageProfile',
         u'raidTypeDescription': u'RAID 10 Active, RAID 5 or RAID 6 Replay',
         u'raidTypeUsed': u'Mixed',
         u'scName': u'Storage Center 64158',
         u'scSerialNumber': 64158,
         u'tiersUsedDescription': u'Tier 3',
         u'useTier1Storage': False,
         u'useTier2Storage': False,
         u'useTier3Storage': True,
         u'userCreated': False,
         u'volumeCount': 0}]

    CGS = [{u'profile':
            {u'instanceId': u'65690.4',
             u'instanceName': u'0869559e-6881-454e-ba18-15c6726d33c1',
             u'objectType': u'ScReplayProfile'},
            u'scSerialNumber': 65690,
            u'globalIndex': u'65690-4-2',
            u'description': u'GUID1-0869559e-6881-454e-ba18-15c6726d33c1',
            u'instanceId': u'65690.65690.4.2',
            u'scName': u'Storage Center 65690',
            u'expires': False,
            u'freezeTime': u'2015-09-28T14:00:59-05:00',
            u'expireTime': u'1969-12-31T18:00:00-06:00',
            u'expectedReplayCount': 2,
            u'writesHeldDuration': 19809,
            u'replayCount': 2,
            u'instanceName': u'Name1',
            u'objectType': u'ScReplayConsistencyGroup'},
           {u'profile':
            {u'instanceId': u'65690.4',
             u'instanceName': u'0869559e-6881-454e-ba18-15c6726d33c1',
             u'objectType': u'ScReplayProfile'},
            u'scSerialNumber': 65690,
            u'globalIndex': u'65690-4-3',
            u'description': u'GUID2-0869559e-6881-454e-ba18-15c6726d33c1',
            u'instanceId': u'65690.65690.4.3',
            u'scName': u'Storage Center 65690',
            u'expires': False,
            u'freezeTime': u'2015-09-28T14:00:59-05:00',
            u'expireTime': u'1969-12-31T18:00:00-06:00',
            u'expectedReplayCount': 2,
            u'writesHeldDuration': 19809,
            u'replayCount': 2,
            u'instanceName': u'Name2',
            u'objectType': u'ScReplayConsistencyGroup'}
           ]

    ISCSI_CONFIG = {
        u'initialReadyToTransfer': True,
        u'scSerialNumber': 64065,
        u'macAddress': u'00c0dd-1da173',
        u'instanceId': u'64065.5764839588723573038.6',
        u'vlanTagging': False,
        u'mapCount': 8,
        u'cardModel': u'Qle4062',
        u'portNumber': 3260,
        u'firstBurstSize': 256,
        u'deviceName': u'PCIDEV09',
        u'subnetMask': u'255.255.255.0',
        u'speed': u'1 Gbps',
        u'maximumVlanCount': 0,
        u'gatewayIpAddress': u'192.168.0.1',
        u'slot': 4,
        u'sfpData': u'',
        u'dataDigest': False,
        u'chapEnabled': False,
        u'firmwareVersion': u'03.00.01.77',
        u'preferredControllerIndex': 64066,
        u'defaultTimeToRetain': 20,
        u'objectType': u'ScControllerPortIscsiConfiguration',
        u'instanceName': u'5000d31000FCBE43',
        u'scName': u'sc64065',
        u'revision': u'0',
        u'controllerPortIndex': 5764839588723573038,
        u'maxBurstSize': 512,
        u'targetCount': 20,
        u'description': u'QLogic QLE4062 iSCSI Adapter Rev 0 Copper',
        u'vlanSupported': True,
        u'chapName': u'iqn.2002-03.com.compellent:5000d31000fcbe43',
        u'windowSize': 128,
        u'vlanId': 0,
        u'defaultTimeToWait': 2,
        u'headerDigest': False,
        u'slotPort': 2,
        u'immediateDataWrite': False,
        u'storageCenterTargetCount': 20,
        u'vlanCount': 0,
        u'scsiCommandTimeout': 60,
        u'slotType': u'PCI4',
        u'ipAddress': u'192.168.0.21',
        u'vlanUserPriority': 0,
        u'bothCount': 0,
        u'initiatorCount': 33,
        u'keepAliveTimeout': 30,
        u'homeControllerIndex': 64066,
        u'chapSecret': u'',
        u'maximumTransmissionUnit': 1500}

    SCQOS = {u'linkSpeed': u'1 Gbps',
             u'numberDevices': 1,
             u'bandwidthLimited': False,
             u'name': u'Cinder QoS',
             u'instanceId': u'64702.2',
             u'scName': u'Storage Center 64702',
             u'scSerialNumber': 64702,
             u'instanceName': u'Cinder QoS',
             u'advancedSettings': {u'globalMaxSectorPerIo': 512,
                                   u'destinationMaxSectorCount': 65536,
                                   u'queuePassMaxSectorCount': 65536,
                                   u'destinationMaxIoCount': 18,
                                   u'globalMaxIoCount': 32,
                                   u'queuePassMaxIoCount': 8},
             u'objectType': u'ScReplicationQosNode'}

    SCREPL = [{u'destinationVolume': {u'instanceId': u'65495.167',
                                      u'instanceName': u'Cinder repl of abcd9'
                                                       u'5b2-1284-4cf0-a397-9'
                                                       u'70fa6c68092',
                                      u'objectType': u'ScVolume'},
               u'instanceId': u'64702.9',
               u'scSerialNumber': 64702,
               u'syncStatus': u'NotApplicable',
               u'objectType': u'ScReplication',
               u'sourceStorageCenter': {u'instanceId': u'64702',
                                        u'instanceName': u'Storage Center '
                                                         '64702',
                                        u'objectType': u'StorageCenter'},
               u'secondaryTransportTypes': [],
               u'dedup': False,
               u'state': u'Up',
               u'replicateActiveReplay': False,
               u'qosNode': {u'instanceId': u'64702.2',
                            u'instanceName': u'Cinder QoS',
                            u'objectType': u'ScReplicationQosNode'},
               u'sourceVolume': {u'instanceId': u'64702.13108',
                                 u'instanceName': u'abcd95b2-1284-4cf0-a397-'
                                                  u'970fa6c68092',
                                 u'objectType': u'ScVolume'},
               u'type': u'Asynchronous',
               u'statusMessage': u'',
               u'status': u'Up',
               u'syncMode': u'None',
               u'stateMessage': u'',
               u'managedByLiveVolume': False,
               u'destinationScSerialNumber': 65495,
               u'pauseAllowed': True,
               u'instanceName': u"Replication of 'abcd95b2-1284-4cf0-"
                                u"a397-970fa6c68092'",
               u'simulation': False,
               u'transportTypes': [u'FibreChannel'],
               u'replicateStorageToLowestTier': True,
               u'scName': u'Storage Center 64702',
               u'destinationStorageCenter': {u'instanceId': u'65495',
                                             u'instanceName': u'Storage Center'
                                                              u' 65495',
                                             u'objectType': u'StorageCenter'}}]

    IQN = 'iqn.2002-03.com.compellent:5000D31000000001'
    WWN = u'21000024ff30441c'

    WWNS = [u'21000024ff30441c',
            u'21000024ff30441d']

    # Used to test finding no match in find_wwns
    WWNS_NO_MATCH = [u'21000024FF30451C',
                     u'21000024FF30451D']

    FLDR_PATH = 'StorageCenter/ScVolumeFolder/'

    # Create a Response object that indicates OK

    response_ok = models.Response()
    response_ok.status_code = 200
    response_ok.reason = u'ok'
    response_ok._content = ''
    response_ok._content_consumed = True
    RESPONSE_200 = response_ok

    # Create a Response object that indicates created
    response_created = models.Response()
    response_created.status_code = 201
    response_created.reason = u'created'
    response_created._content = ''
    response_created._content_consumed = True
    RESPONSE_201 = response_created

    # Create a Response object that can indicate a failure. Although
    # 204 can be a success with no return.  (Know your calls!)
    response_nc = models.Response()
    response_nc.status_code = 204
    response_nc.reason = u'duplicate'
    response_nc._content = ''
    response_nc._content_consumed = True
    RESPONSE_204 = response_nc

    # Create a Response object is a pure error.
    response_bad = models.Response()
    response_bad.status_code = 400
    response_bad.reason = u'bad request'
    response_bad._content = ''
    response_bad._content_consumed = True
    RESPONSE_400 = response_bad

    # Create a Response object is a pure error.
    response_bad = models.Response()
    response_bad.status_code = 404
    response_bad.reason = u'not found'
    response_bad._content = ''
    response_bad._content_consumed = True
    RESPONSE_404 = response_bad

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
        self.configuration.target_ip_address = '192.168.1.1'
        self.configuration.target_port = 3260
        self._context = context.get_admin_context()
        self.apiversion = '2.0'
        self.asynctimeout = 15
        self.synctimeout = 30

        # Set up the SCApi
        self.scapi = storagecenter_api.SCApi(
            self.configuration.san_ip,
            self.configuration.dell_sc_api_port,
            self.configuration.san_login,
            self.configuration.san_password,
            self.configuration.dell_sc_verify_cert,
            self.asynctimeout,
            self.synctimeout,
            self.apiversion)

        # Set up the scapi configuration vars
        self.scapi.ssn = self.configuration.dell_sc_ssn
        self.scapi.sfname = self.configuration.dell_sc_server_folder
        self.scapi.vfname = self.configuration.dell_sc_volume_folder
        # Note that we set this to True (or not) on the replication tests.
        self.scapi.failed_over = False
        # Legacy folder names are still current so we default this to true.
        self.scapi.legacyfoldernames = True

        self.volid = str(uuid.uuid4())
        self.volume_name = "volume" + self.volid
        self.repl_name = "Cinder repl of volume" + self.volid

    def test_path_to_array(self,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi._path_to_array(u'folder1/folder2/folder3')
        expected = [u'folder1', u'folder2', u'folder3']
        self.assertEqual(expected, res, 'Unexpected folder path')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result',
                       return_value=SC)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_create_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_create_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder(self,
                         mock_post,
                         mock_get_result,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        self.scapi._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                'devstackvol/fcvm', 12345)
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'fcvm'},
            {'filterType': 'Equals', 'attributeName': 'folderPath',
             'attributeValue': 'devstackvol/'}]}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            expected_payload)
        self.assertTrue(mock_get_result.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder_not_legacy(self,
                                    mock_post,
                                    mock_get_result,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        self.scapi.legacyfoldernames = False
        self.scapi._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                'devstackvol/fcvm', 12345)
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'fcvm'},
            {'filterType': 'Equals', 'attributeName': 'folderPath',
             'attributeValue': '/devstackvol/'}]}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            expected_payload)
        self.assertTrue(mock_get_result.called)
        self.scapi.legacyfoldernames = True

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder_legacy_root(self,
                                     mock_post,
                                     mock_get_result,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        self.scapi._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                'devstackvol', 12345)
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'devstackvol'},
            {'filterType': 'Equals', 'attributeName': 'folderPath',
             'attributeValue': ''}]}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            expected_payload)
        self.assertTrue(mock_get_result.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_folder_non_legacy_root(self,
                                         mock_post,
                                         mock_get_result,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        self.scapi.legacyfoldernames = False
        self.scapi._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                'devstackvol', 12345)
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'devstackvol'},
            {'filterType': 'Equals', 'attributeName': 'folderPath',
             'attributeValue': '/'}]}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScVolumeFolder/GetList',
            expected_payload)
        self.assertTrue(mock_get_result.called)
        self.scapi.legacyfoldernames = True

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_result',
                       return_value=u'devstackvol/fcvm/')
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_volume_folder, -1)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_volume_folder, -1)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=STORAGE_PROFILE_LIST)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_storage_profile_fail(self,
                                       mock_json,
                                       mock_find_folder,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where _find_volume_folder returns none
        res = self.scapi._find_storage_profile("Blah")
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=STORAGE_PROFILE_LIST)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_storage_profile_none(self,
                                       mock_json,
                                       mock_find_folder,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where _find_storage_profile returns none
        res = self.scapi._find_storage_profile(None)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=STORAGE_PROFILE_LIST)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @ddt.data('HighPriority', 'highpriority', 'High Priority')
    def test_find_storage_profile(self,
                                  value,
                                  mock_json,
                                  mock_find_folder,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi._find_storage_profile(value)
        self.assertIsNotNone(res, 'Expected matching storage profile!')
        self.assertEqual(self.STORAGE_PROFILE_LIST[1]['instanceId'],
                         res.get('instanceId'))

    @mock.patch.object(storagecenter_api.SCApi,
                       '_create_folder_path',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_volume_folder, -1)
        self.assertTrue(mock_create_folder_path.called)
        self.assertEqual(self.FLDR, res, 'Unexpected Folder')

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCSERVERS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_init_volume(self,
                         mock_post,
                         mock_get_json,
                         mock_map_volume,
                         mock_unmap_volume,
                         mock_get_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        self.scapi._init_volume(self.VOLUME)
        self.assertTrue(mock_map_volume.called)
        self.assertTrue(mock_unmap_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_init_volume_retry(self,
                               mock_post,
                               mock_get_json,
                               mock_map_volume,
                               mock_unmap_volume,
                               mock_get_volume,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        mock_get_json.return_value = [{'name': 'srv1', 'status': 'up',
                                       'type': 'physical'},
                                      {'name': 'srv2', 'status': 'up',
                                       'type': 'physical'}]
        mock_get_volume.side_effect = [{'name': 'guid', 'active': False,
                                        'instanceId': '12345.1'},
                                       {'name': 'guid', 'active': True,
                                        'instanceId': '12345.1'}]
        self.scapi._init_volume(self.VOLUME)
        # First return wasn't active. So try second.
        self.assertEqual(2, mock_map_volume.call_count)
        self.assertEqual(2, mock_unmap_volume.call_count)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_init_volume_failure(self,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # Test case where ScServer list fails
        self.scapi._init_volume(self.VOLUME)
        self.assertTrue(mock_post.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCSERVERS_DOWN)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_storage_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    def test_create_volume_with_profiles(self,
                                         mock_find_replay_profiles,
                                         mock_find_storage_profile,
                                         mock_find_data_reduction_profile,
                                         mock_find_qos_profile,
                                         mock_post,
                                         mock_find_volume_folder,
                                         mock_get_json,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        mock_find_replay_profiles.return_value = (['12345.4'], [])
        mock_get_json.return_value = self.VOLUME
        mock_find_volume_folder.return_value = {'instanceId': '12345.200'}
        mock_post.return_value = self.RESPONSE_201
        mock_find_storage_profile.return_value = {'instanceId': '12345.0'}
        mock_find_data_reduction_profile.return_value = {'instanceId':
                                                         '12345.1'}
        mock_find_qos_profile.side_effect = [{'instanceId': '12345.2'},
                                             {'instanceId': '12345.3'}]
        res = self.scapi.create_volume(self.volume_name, 1, 'storage_profile',
                                       'replay_profile_string', 'volume_qos',
                                       'group_qos', 'datareductionprofile')
        expected_payload = {'Name': self.volume_name,
                            'Notes': 'Created by Dell EMC Cinder Driver',
                            'Size': '1 GB',
                            'StorageCenter': 12345,
                            'VolumeFolder': '12345.200',
                            'StorageProfile': '12345.0',
                            'VolumeQosProfile': '12345.2',
                            'GroupQosProfile': '12345.3',
                            'DataReductionProfile': '12345.1',
                            'ReplayProfileList': ['12345.4']}
        mock_find_volume_folder.assert_called_once_with(True)
        mock_post.assert_called_once_with('StorageCenter/ScVolume',
                                          expected_payload, True)
        self.assertEqual(self.VOLUME, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_storage_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    def test_create_volume_profile_not_found(self,
                                             mock_find_replay_profiles,
                                             mock_find_storage_profile,
                                             mock_find_qos_profile,
                                             mock_find_volume_folder,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        mock_find_replay_profiles.return_value = (['12345.4'], [])
        mock_find_volume_folder.return_value = self.FLDR
        mock_find_storage_profile.return_value = [{'instanceId': '12345.0'}]
        # Failure is on the volumeqosprofile.
        mock_find_qos_profile.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_volume, self.volume_name, 1,
                          'storage_profile', 'replay_profile_string',
                          'volume_qos', 'group_qos', 'datareductionprofile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_storage_profile',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    def test_create_volume_storage_profile_missing(self,
                                                   mock_find_volume_folder,
                                                   mock_find_storage_profile,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_volume,
                          self.volume_name,
                          1,
                          'Blah')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_storage_profile',
                       return_value=STORAGE_PROFILE_LIST[0])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_volume_storage_profile(self,
                                           mock_post,
                                           mock_find_volume_folder,
                                           mock_find_storage_profile,
                                           mock_get_json,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        self.scapi.create_volume(
            self.volume_name,
            1,
            'Recommended')
        actual = mock_post.call_args[0][1]['StorageProfile']
        expected = self.STORAGE_PROFILE_LIST[0]['instanceId']
        self.assertEqual(expected, actual)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_search_for_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_volume_retry_find(self,
                                      mock_post,
                                      mock_find_volume_folder,
                                      mock_get_json,
                                      mock_search_for_volume,
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
        mock_search_for_volume.assert_called_once_with(self.volume_name)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME_LIST)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test__get_volume_list_enforce_vol_fldr(self,
                                               mock_post,
                                               mock_get_json,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        # Test case to find volume in the configured volume folder
        res = self.scapi._get_volume_list(self.volume_name, None, True)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.VOLUME_LIST, res, 'Unexpected volume list')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME_LIST)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test__get_volume_list_any_fldr(self,
                                       mock_post,
                                       mock_get_json,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case to find volume anywhere in the configured SC
        res = self.scapi._get_volume_list(self.volume_name, None, False)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.VOLUME_LIST, res, 'Unexpected volume list')

    def test_get_volume_list_no_name_no_id(self,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        # Test case specified volume name is None and device id is None.
        res = self.scapi._get_volume_list(None, None, True)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test__get_volume_list_failure(self,
                                      mock_post,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case to find volume in the configured volume folder
        res = self.scapi._get_volume_list(self.volume_name, None, True)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_search_for_volume',
                       return_value=VOLUME)
    def test_find_volume(self,
                         mock_search_for_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        # Test case to find volume by name
        res = self.scapi.find_volume(self.volume_name, None)
        mock_search_for_volume.assert_called_once_with(self.volume_name)
        self.assertEqual(self.VOLUME, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_search_for_volume',
                       return_value=None)
    def test_find_volume_not_found(self,
                                   mock_search_for_volume,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case to find volume by name
        res = self.scapi.find_volume(self.volume_name, None)
        mock_search_for_volume.assert_called_once_with(self.volume_name)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    def test_find_volume_with_provider_id(self,
                                          mock_get_volume,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        res = self.scapi.find_volume(self.volume_name, provider_id)
        mock_get_volume.assert_called_once_with(provider_id)
        self.assertEqual(self.VOLUME, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_search_for_volume',
                       return_value=VOLUME)
    def test_find_volume_with_invalid_provider_id(self,
                                                  mock_search_for_volume,
                                                  mock_get_volume,
                                                  mock_close_connection,
                                                  mock_open_connection,
                                                  mock_init):
        provider_id = 'WrongSSN.1'
        res = self.scapi.find_volume(self.volume_name, provider_id)
        mock_search_for_volume.assert_called_once_with(self.volume_name)
        self.assertFalse(mock_get_volume.called)
        self.assertEqual(self.VOLUME, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=None)
    def test_find_volume_with_provider_id_not_found(self,
                                                    mock_get_volume,
                                                    mock_close_connection,
                                                    mock_open_connection,
                                                    mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        res = self.scapi.find_volume(self.volume_name, provider_id)
        mock_get_volume.assert_called_once_with(provider_id)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_import_one',
                       return_value=VOLUME)
    def test_find_volume_with_provider_id_complete_replication(
            self,
            mock_import_one,
            mock_get_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        # Configure to middle of failover.
        self.scapi.failed_over = True
        mock_get_volume.return_value = {'name': self.repl_name}
        res = self.scapi.find_volume(self.volume_name, provider_id)
        self.scapi.failed_over = False
        mock_import_one.assert_called_once_with(mock_get_volume.return_value,
                                                self.volume_name)
        mock_get_volume.assert_called_once_with(provider_id)
        self.assertEqual(self.VOLUME, res, 'Unexpected volume')

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_import_one',
                       return_value=None)
    def test_find_volume_with_provider_id_import_fail(self,
                                                      mock_import_one,
                                                      mock_get_volume,
                                                      mock_close_connection,
                                                      mock_open_connection,
                                                      mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        # Configure to middle of failover.
        self.scapi.failed_over = True
        mock_get_volume.return_value = {'name': self.repl_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_volume, self.volume_name,
                          provider_id)
        self.scapi.failed_over = False
        mock_import_one.assert_called_once_with(mock_get_volume.return_value,
                                                self.volume_name)
        mock_get_volume.assert_called_once_with(provider_id)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=None)
    def test_search_for_volume_no_name(self,
                                       mock_get_volume_list,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test calling find_volume with no name or instanceid
        res = self.scapi._search_for_volume(None)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list')
    def test_search_for_volume_not_found(self,
                                         mock_get_volume_list,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        # Test calling find_volume with result of no volume found
        mock_get_volume_list.side_effect = [[], []]
        res = self.scapi._search_for_volume(self.volume_name)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=VOLUME_LIST_MULTI_VOLS)
    def test_search_for_volume_multi_vols_found(self,
                                                mock_get_volume_list,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        # Test case where multiple volumes are found
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._search_for_volume, self.volume_name)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    def test_get_volume(self,
                        mock_get_json,
                        mock_get,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        res = self.scapi.get_volume(provider_id)
        mock_get.assert_called_once_with(
            'StorageCenter/ScVolume/' + provider_id)
        self.assertEqual(self.VOLUME, res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_get_volume_error(self,
                              mock_get,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        res = self.scapi.get_volume(provider_id)
        mock_get.assert_called_once_with(
            'StorageCenter/ScVolume/' + provider_id)
        self.assertIsNone(res)

    def test_get_volume_no_id(self,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        provider_id = None
        res = self.scapi.get_volume(provider_id)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=True)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
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
        mock_find_volume.assert_called_once_with(self.volume_name, None)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=True)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_delete_volume_with_provider_id(self,
                                            mock_find_volume,
                                            mock_delete,
                                            mock_get_json,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        res = self.scapi.delete_volume(self.volume_name, provider_id)
        mock_find_volume.assert_called_once_with(self.volume_name, provider_id)
        self.assertTrue(mock_delete.called)
        self.assertTrue(mock_get_json.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_delete_volume_failure(self,
                                   mock_find_volume,
                                   mock_delete,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        provider_id = str(self.scapi.ssn) + '.1'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.delete_volume, self.volume_name,
                          provider_id)
        mock_find_volume.assert_called_once_with(self.volume_name, provider_id)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    def test_delete_volume_no_vol_found(self,
                                        mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        # Test case where volume to be deleted does not exist
        res = self.scapi.delete_volume(self.volume_name, None)
        mock_find_volume.assert_called_once_with(self.volume_name, None)
        self.assertTrue(res, 'Expected True')

    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_server_folder, 12345)
        self.assertEqual(self.SVR_FLDR, res, 'Unexpected server folder')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_create_folder_path',
                       return_value=SVR_FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_server_folder, 12345)
        self.assertTrue(mock_create_folder_path.called)
        self.assertEqual(self.SVR_FLDR, res, 'Unexpected server folder')

    @mock.patch.object(storagecenter_api.SCApi,
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
            self.configuration.dell_sc_volume_folder, 12345)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_add_hba(self,
                     mock_post,
                     mock_close_connection,
                     mock_open_connection,
                     mock_init):
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.IQN)
        self.assertTrue(mock_post.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_add_hba_fc(self,
                        mock_post,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        saveproto = self.scapi.protocol
        self.scapi.protocol = 'FibreChannel'
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.WWN)
        self.assertTrue(mock_post.called)
        self.assertTrue(res)
        self.scapi.protocol = saveproto

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_add_hba_failure(self,
                             mock_post,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        res = self.scapi._add_hba(self.SCSERVER,
                                  self.IQN)
        self.assertTrue(mock_post.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SVR_OS_S)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SVR_OS_S)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_find_serveros_failed(self,
                                  mock_post,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi._find_serveros('Red Hat Linux 6.x')
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=FC_HBA)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_create_server',
                       return_value=SCSERVER)
    def test_create_server_multiple_hbas(self,
                                         mock_create_server,
                                         mock_add_hba,
                                         mock_find_server_folder,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.create_server(self.WWNS, 'Red Hat Linux 6.x')
        self.assertTrue(mock_create_server.called)
        self.assertTrue(mock_add_hba.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(storagecenter_api.HttpClient,
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
        res = self.scapi.create_server(self.IQN, 'Red Hat Linux 6.x')
        self.assertTrue(mock_find_serveros.called)
        self.assertTrue(mock_find_server_folder.called)
        self.assertTrue(mock_first_result.called)
        self.assertTrue(mock_add_hba.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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
        res = self.scapi.create_server(self.IQN, 'Red Hat Binux 6.x')
        self.assertTrue(mock_find_serveros.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(storagecenter_api.HttpClient,
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
        res = self.scapi.create_server(self.IQN, 'Red Hat Linux 6.x')
        self.assertTrue(mock_find_server_folder.called)
        self.assertEqual(self.SCSERVER, res, 'Unexpected ScServer')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_create_server_failure(self,
                                   mock_post,
                                   mock_find_serveros,
                                   mock_find_server_folder,
                                   mock_first_result,
                                   mock_add_hba,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.create_server(self.IQN, 'Red Hat Linux 6.x')
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(storagecenter_api.HttpClient,
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
        res = self.scapi.create_server(self.IQN, 'Red Hat Linux 6.x')
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_delete_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_hba',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_server_folder',
                       return_value=SVR_FLDR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serveros',
                       return_value='64702.38')
    @mock.patch.object(storagecenter_api.HttpClient,
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
        res = self.scapi.create_server(self.IQN, 'Red Hat Linux 6.x')
        self.assertTrue(mock_delete_server.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serverhba',
                       return_value=ISCSI_HBA)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serverhba',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_serverhba',
                       return_value=ISCSI_HBA)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=ISCSI_HBA)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=FC_HBAS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_initiators(self,
                             mock_get,
                             mock_get_json,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        res = self.scapi._find_initiators(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNotNone(res, 'Expected WWN list')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_initiators_error(self,
                                   mock_get,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where get of ScServer HbaList fails
        res = self.scapi._find_initiators(self.SCSERVER)
        self.assertListEqual([], res, 'Expected empty list')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_get_volume_count_failure(self,
                                      mock_get,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Test case of where get of ScServer MappingList fails
        res = self.scapi.get_volume_count(self.SCSERVER)
        self.assertTrue(mock_get.called)
        self.assertEqual(-1, res, 'Mapping count not -1')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_mappings_failure(self,
                                   mock_get,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case of where get of ScVolume MappingList fails
        res = self.scapi._find_mappings(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertEqual([], res, 'Mapping count not empty')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=MAP_PROFILES)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_mapping_profiles(self,
                                   mock_get,
                                   mock_get_json,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where ScVolume has no mappings
        res = self.scapi._find_mapping_profiles(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.MAP_PROFILES, res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_mapping_profiles_error(self,
                                         mock_get,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        # Test case where ScVolume has no mappings
        res = self.scapi._find_mapping_profiles(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertEqual([], res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=CTRLR_PORT)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=WWNS)
    def test_find_wwns(self,
                       mock_find_initiators,
                       mock_find_mappings,
                       mock_find_controller_port,
                       mock_close_connection,
                       mock_open_connection,
                       mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        # The _find_controller_port is Mocked, so all mapping pairs
        # will have the same WWN for the ScControllerPort
        itmapCompare = {u'21000024ff30441c': [u'5000d31000fcbe36'],
                        u'21000024ff30441d':
                        [u'5000d31000fcbe36', u'5000d31000fcbe36']}
        self.assertEqual(1, lun, 'Incorrect LUN')
        self.assertIsNotNone(wwns, 'WWNs is None')
        self.assertEqual(itmapCompare, itmap, 'WWN mapping incorrect')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=[])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=FC_HBAS)
    def test_find_wwns_no_mappings(self,
                                   mock_find_initiators,
                                   mock_find_mappings,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Test case where there are no ScMapping(s)
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertIsNone(lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=WWNS)
    def test_find_wwns_no_ctlr_port(self,
                                    mock_find_initiators,
                                    mock_find_mappings,
                                    mock_find_controller_port,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where ScControllerPort is none
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)
        self.assertIsNone(lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT_WWN_ERROR)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=WWNS)
    def test_find_wwns_wwn_resilient(self,
                                     mock_find_initiators,
                                     mock_find_mappings,
                                     mock_find_controller_port,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where ScControllerPort object has wWN instead of wwn (as
        # seen in some cases) for a property but we are still able to find it.
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        self.assertEqual(1, lun, 'Incorrect LUN')
        expected_wwn = ['5000d31000fcbe36', '5000d31000fcbe36',
                        '5000d31000fcbe36']
        self.assertEqual(expected_wwn, wwns, 'WWNs incorrect')
        expected_itmap = {'21000024ff30441c': ['5000d31000fcbe36'],
                          '21000024ff30441d': ['5000d31000fcbe36',
                                               '5000d31000fcbe36']}
        self.assertEqual(expected_itmap, itmap, 'WWN mapping incorrect')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=WWNS_NO_MATCH)
    # Test case where HBA name is not found in list of initiators
    def test_find_wwns_hbaname_not_found(self,
                                         mock_find_initiators,
                                         mock_find_mappings,
                                         mock_find_controller_port,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)

        self.assertIsNone(lun, 'Incorrect LUN')
        self.assertEqual([], wwns, 'WWNs is not empty')
        self.assertEqual({}, itmap, 'WWN mapping not empty')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=FC_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=FC_MAPPINGS_LUN_MISMATCH)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_initiators',
                       return_value=WWNS)
    # Test case where FC mappings contain a LUN mismatch
    def test_find_wwns_lun_mismatch(self,
                                    mock_find_initiators,
                                    mock_find_mappings,
                                    mock_find_controller_port,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        lun, wwns, itmap = self.scapi.find_wwns(self.VOLUME,
                                                self.SCSERVER)
        self.assertTrue(mock_find_initiators.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_controller_port.called)
        # The _find_controller_port is Mocked, so all mapping pairs
        # will have the same WWN for the ScControllerPort
        itmapCompare = {u'21000024ff30441c': [u'5000d31000fcbe36'],
                        u'21000024ff30441d':
                        [u'5000d31000fcbe36', u'5000d31000fcbe36']}
        self.assertEqual(1, lun, 'Incorrect LUN')
        self.assertIsNotNone(wwns, 'WWNs is None')
        self.assertEqual(itmapCompare, itmap, 'WWN mapping incorrect')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=VOLUME_CONFIG)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_active_controller_failure(self,
                                            mock_get,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        # Test case of where get of ScVolume MappingList fails
        res = self.scapi._find_active_controller(self.VOLUME)
        self.assertTrue(mock_get.called)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.5764839588723736131.91')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_mappings(self,
                                            mock_is_virtualport_mode,
                                            mock_find_mappings,
                                            mock_find_domains,
                                            mock_find_ctrl_port,
                                            mock_find_active_controller,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        scserver = {'instanceId': '64702.30'}
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.5764839588723736131.91')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_multiple_servers_mapped(
            self, mock_is_virtualport_mode, mock_find_mappings,
            mock_find_domains, mock_find_ctrl_port,
            mock_find_active_controller, mock_close_connection,
            mock_open_connection, mock_init):
        mappings = [{'instanceId': '64702.970.64702',
                     'server': {'instanceId': '64702.47'},
                     'volume': {'instanceId': '64702.92'}}]
        mappings.append(self.MAPPINGS[0].copy())
        scserver = {'instanceId': '64702.30'}
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=[])
    def test_find_iscsi_properties_no_mapping(self,
                                              mock_find_mappings,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        scserver = {'instanceId': '64702.30'}
        # Test case where there are no ScMapping(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME,
                          scserver)
        self.assertTrue(mock_find_mappings.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_no_domain(self,
                                             mock_is_virtualport_mode,
                                             mock_find_mappings,
                                             mock_find_domains,
                                             mock_find_ctrl_port,
                                             mock_find_active_controller,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        scserver = {'instanceId': '64702.30'}
        # Test case where there are no ScFaultDomain(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_no_ctrl_port(self,
                                                mock_is_virtualport_mode,
                                                mock_find_mappings,
                                                mock_find_ctrl_port,
                                                mock_find_active_controller,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        scserver = {'instanceId': '64702.30'}
        # Test case where there are no ScFaultDomain(s)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS_READ_ONLY)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_ro(self,
                                      mock_is_virtualport_mode,
                                      mock_find_mappings,
                                      mock_find_domains,
                                      mock_find_ctrl_port,
                                      mock_find_active_controller,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        scserver = {'instanceId': '64702.30'}
        # Test case where Read Only mappings are found
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS_MULTI_PORTALS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS_MULTI_PORTAL)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_multi_portals(self,
                                                 mock_is_virtualport_mode,
                                                 mock_find_mappings,
                                                 mock_find_domains,
                                                 mock_find_ctrl_port,
                                                 mock_find_active_controller,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        # Test case where there are multiple portals
        mock_find_ctrl_port.side_effect = [
            {'iscsiName': 'iqn.2002-03.com.compellent:5000d31000fcbe43'},
            {'iscsiName': 'iqn.2002-03.com.compellent:5000d31000fcbe44'}]
        scserver = {'instanceId': '64702.30'}
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        self.assertTrue(mock_is_virtualport_mode.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe44',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe44',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe44'],
                    'target_lun': 1,
                    'target_luns': [1, 1, 1, 1],
                    'target_portal': u'192.168.0.25:3260',
                    'target_portals': [u'192.168.0.25:3260',
                                       u'192.168.0.21:3260',
                                       u'192.168.0.25:3260',
                                       u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_domains',
                       return_value=ISCSI_FLT_DOMAINS_MULTI_PORTALS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS_MULTI_PORTAL)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=True)
    def test_find_iscsi_properties_multi_portals_duplicates(
            self,
            mock_is_virtualport_mode,
            mock_find_mappings,
            mock_find_domains,
            mock_find_ctrl_port,
            mock_find_active_controller,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # Test case where there are multiple portals and
        mock_find_ctrl_port.return_value = {
            'iscsiName': 'iqn.2002-03.com.compellent:5000d31000fcbe43'}
        scserver = {'instanceId': '64702.30'}
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_domains.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        self.assertTrue(mock_is_virtualport_mode.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1, 1],
                    'target_portal': u'192.168.0.25:3260',
                    'target_portals': [u'192.168.0.25:3260',
                                       u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.5764839588723736131.91')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port_iscsi_config',
                       return_value=ISCSI_CONFIG)
    def test_find_iscsi_properties_mappings_legacy(
            self,
            mock_find_controller_port_iscsi_config,
            mock_is_virtualport_mode,
            mock_find_mappings,
            mock_find_ctrl_port,
            mock_find_active_controller,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        scserver = {'instanceId': '64702.30'}
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_controller_port_iscsi_config.called)
        self.assertTrue(mock_find_active_controller.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.5764839588723736131.91')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port_iscsi_config',
                       return_value=None)
    def test_find_iscsi_properties_mappings_legacy_no_iscsi_config(
            self,
            mock_find_controller_port_iscsi_config,
            mock_is_virtualport_mode,
            mock_find_mappings,
            mock_find_ctrl_port,
            mock_find_active_controller,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        scserver = {'instanceId': '64702.30'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_iscsi_properties,
                          self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_controller_port_iscsi_config.called)
        self.assertTrue(mock_find_active_controller.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port',
                       return_value=ISCSI_CTRLR_PORT)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS_READ_ONLY)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port_iscsi_config',
                       return_value=ISCSI_CONFIG)
    def test_find_iscsi_properties_ro_legacy(self,
                                             mock_find_iscsi_config,
                                             mock_is_virtualport_mode,
                                             mock_find_mappings,
                                             mock_find_ctrl_port,
                                             mock_find_active_controller,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        scserver = {'instanceId': '64702.30'}
        # Test case where Read Only mappings are found
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        self.assertTrue(mock_find_iscsi_config.called)
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_active_controller',
                       return_value='64702.64702')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=MAPPINGS_MULTI_PORTAL)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_is_virtualport_mode',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_controller_port_iscsi_config',
                       return_value=ISCSI_CONFIG)
    def test_find_iscsi_properties_multi_portals_legacy(
            self,
            mock_find_controller_port_iscsi_config,
            mock_is_virtualport_mode,
            mock_find_mappings,
            mock_find_ctrl_port,
            mock_find_active_controller,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        mock_find_ctrl_port.side_effect = [
            {'iscsiName': 'iqn.2002-03.com.compellent:5000d31000fcbe43'},
            {'iscsiName': 'iqn.2002-03.com.compellent:5000d31000fcbe44'}]
        scserver = {'instanceId': '64702.30'}
        # Test case where there are multiple portals
        res = self.scapi.find_iscsi_properties(self.VOLUME, scserver)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_find_ctrl_port.called)
        self.assertTrue(mock_find_active_controller.called)
        self.assertTrue(mock_is_virtualport_mode.called)
        self.assertTrue(mock_find_controller_port_iscsi_config.called)
        # We're feeding the same info back multiple times the information
        # will be scrubbed to a single item.
        expected = {'target_discovered': False,
                    'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe44',
                    'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe44',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                    'target_lun': 1,
                    'target_luns': [1, 1],
                    'target_portal': u'192.168.0.21:3260',
                    'target_portals': [u'192.168.0.21:3260',
                                       u'192.168.0.21:3260']}
        self.assertEqual(expected, res, 'Wrong Target Info')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=MAP_PROFILE)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=[])
    def test_map_volume(self,
                        mock_find_mapping_profiles,
                        mock_post,
                        mock_first_result,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.MAP_PROFILE, res, 'Incorrect ScMappingProfile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=MAP_PROFILE)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    def test_map_volume_existing_mapping(self,
                                         mock_find_mappings,
                                         mock_post,
                                         mock_first_result,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertTrue(mock_find_mappings.called)
        self.assertFalse(mock_post.called)
        self.assertFalse(mock_first_result.called)
        self.assertEqual(self.MAP_PROFILE, res, 'Incorrect ScMappingProfile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=MAP_PROFILE)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=[])
    def test_map_volume_existing_mapping_not_us(self,
                                                mock_find_mappings,
                                                mock_post,
                                                mock_first_result,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        server = {'instanceId': 64702.48, 'name': 'Server X'}
        res = self.scapi.map_volume(self.VOLUME,
                                    server)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.MAP_PROFILE, res, 'Incorrect ScMappingProfile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result')
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result')
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=[])
    def test_map_volume_failure(self,
                                mock_find_mapping_profiles,
                                mock_post,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # Test case where mapping volume to server fails
        res = self.scapi.map_volume(self.VOLUME,
                                    self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value={'result': True})
    def test_unmap_volume(self,
                          mock_get_json,
                          mock_find_mapping_profiles,
                          mock_delete,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_204)
    def test_unmap_volume_failure(self,
                                  mock_delete,
                                  mock_find_mapping_profiles,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(mock_delete.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=[])
    def test_unmap_volume_no_map_profile(self,
                                         mock_find_mapping_profiles,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_204)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    def test_unmap_volume_del_fail(self,
                                   mock_find_mapping_profiles,
                                   mock_delete,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertTrue(mock_find_mapping_profiles.called)
        self.assertTrue(mock_delete.called)
        self.assertFalse(res, False)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    def test_unmap_volume_no_vol_id(self,
                                    mock_find_mapping_profiles,
                                    mock_delete,
                                    mock_get_id,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        # Test case where ScVolume instanceId = None
        mock_get_id.side_effect = [None, '64702.47']
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertFalse(mock_find_mapping_profiles.called)
        self.assertFalse(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles',
                       return_value=MAP_PROFILES)
    def test_unmap_volume_no_server_id(self,
                                       mock_find_mapping_profiles,
                                       mock_delete,
                                       mock_get_id,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        # Test case where ScVolume instanceId = None
        mock_get_id.side_effect = ['64702.3494', None]
        res = self.scapi.unmap_volume(self.VOLUME,
                                      self.SCSERVER)
        self.assertFalse(mock_find_mapping_profiles.called)
        self.assertFalse(mock_delete.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test_unmap_all(self, mock_get_json, mock_find_mapping_profiles,
                       mock_get, mock_delete, mock_close_connection,
                       mock_open_connection, mock_init):
        mock_delete.return_value = self.RESPONSE_200
        mock_get.return_value = self.RESPONSE_200
        mock_find_mapping_profiles.return_value = [
            {'instanceId': '12345.0.1',
             'server': {'instanceId': '12345.100', 'instanceName': 'Srv1'}},
            {'instanceId': '12345.0.2',
             'server': {'instanceId': '12345.101', 'instanceName': 'Srv2'}},
            {'instanceId': '12345.0.3',
             'server': {'instanceId': '12345.102', 'instanceName': 'Srv3'}},
        ]
        # server, result pairs
        mock_get_json.side_effect = [
            {'instanceId': '12345.100', 'instanceName': 'Srv1',
             'type': 'Physical'},
            {'result': True},
            {'instanceId': '12345.101', 'instanceName': 'Srv2',
             'type': 'Physical'},
            {'result': True},
            {'instanceId': '12345.102', 'instanceName': 'Srv3',
             'type': 'Physical'},
            {'result': True}
        ]
        vol = {'instanceId': '12345.0', 'name': 'vol1'}
        res = self.scapi.unmap_all(vol)
        # Success and 3 delete calls
        self.assertTrue(res)
        self.assertEqual(3, mock_delete.call_count)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test_unmap_all_with_remote(self, mock_get_json,
                                   mock_find_mapping_profiles, mock_get,
                                   mock_delete, mock_close_connection,
                                   mock_open_connection, mock_init):
        mock_delete.return_value = self.RESPONSE_200
        mock_get.return_value = self.RESPONSE_200
        mock_find_mapping_profiles.return_value = [
            {'instanceId': '12345.0.1',
             'server': {'instanceId': '12345.100', 'instanceName': 'Srv1'}},
            {'instanceId': '12345.0.2',
             'server': {'instanceId': '12345.101', 'instanceName': 'Srv2'}},
            {'instanceId': '12345.0.3',
             'server': {'instanceId': '12345.102', 'instanceName': 'Srv3'}},
        ]
        # server, result pairs
        mock_get_json.side_effect = [
            {'instanceId': '12345.100', 'instanceName': 'Srv1',
             'type': 'Physical'},
            {'result': True},
            {'instanceId': '12345.101', 'instanceName': 'Srv2',
             'type': 'RemoteStorageCenter'},
            {'instanceId': '12345.102', 'instanceName': 'Srv3',
             'type': 'Physical'},
            {'result': True}
        ]
        vol = {'instanceId': '12345.0', 'name': 'vol1'}
        res = self.scapi.unmap_all(vol)
        # Should succeed but call delete only twice
        self.assertTrue(res)
        self.assertEqual(2, mock_delete.call_count)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test_unmap_all_fail(self, mock_get_json, mock_find_mapping_profiles,
                            mock_get, mock_delete, mock_close_connection,
                            mock_open_connection, mock_init):
        mock_delete.return_value = self.RESPONSE_400
        mock_get.return_value = self.RESPONSE_200
        mock_find_mapping_profiles.return_value = [
            {'instanceId': '12345.0.1',
             'server': {'instanceId': '12345.100', 'instanceName': 'Srv1'}},
            {'instanceId': '12345.0.2',
             'server': {'instanceId': '12345.101', 'instanceName': 'Srv2'}},
            {'instanceId': '12345.0.3',
             'server': {'instanceId': '12345.102', 'instanceName': 'Srv3'}},
        ]
        # server, result pairs
        mock_get_json.side_effect = [
            {'instanceId': '12345.100', 'instanceName': 'Srv1',
             'type': 'Physical'}
        ]
        vol = {'instanceId': '12345.0', 'name': 'vol1'}
        res = self.scapi.unmap_all(vol)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mapping_profiles')
    def test_unmap_all_no_profiles(self, mock_find_mapping_profiles,
                                   mock_close_connection, mock_open_connection,
                                   mock_init):
        mock_find_mapping_profiles.return_value = []
        vol = {'instanceId': '12345.0', 'name': 'vol1'}
        res = self.scapi.unmap_all(vol)
        # Should exit with success.
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[{'a': 1}, {'a': 2}])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_controller_port_iscsi_config(self,
                                               mock_get,
                                               mock_get_json,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        # Not much to test here.  Just make sure we call our stuff and
        # that we return the first item returned to us.
        res = self.scapi._find_controller_port_iscsi_config('guid')
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual({'a': 1}, res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_controller_port_iscsi_config_err(self,
                                                   mock_get,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        res = self.scapi._find_controller_port_iscsi_config('guid')
        self.assertTrue(mock_get.called)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=STRG_USAGE)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_create_replay_inact_vol(self,
                                     mock_post,
                                     mock_get_volume,
                                     mock_init_volume,
                                     mock_first_result,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        # Test case where the specified volume is inactive
        mock_get_volume.return_value = self.VOLUME
        res = self.scapi.create_replay(self.INACTIVE_VOLUME,
                                       'Test Replay',
                                       60)
        self.assertTrue(mock_post.called)
        mock_init_volume.assert_called_once_with(self.INACTIVE_VOLUME)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.RPLAY, res, 'Unexpected ScReplay')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    def test_create_replay_inact_vol_init_fail(
            self, mock_get_volume, mock_init_volume, mock_close_connection,
            mock_open_connection, mock_init):
        # Test case where the specified volume is inactive
        mock_get_volume.return_value = self.INACTIVE_VOLUME
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_replay,
                          self.INACTIVE_VOLUME, 'Test Replay', 60)
        mock_init_volume.assert_called_once_with(self.INACTIVE_VOLUME)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=RPLAY)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=RPLAYS)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value=RPLAYS)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value=TST_RPLAY)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
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
            vol_name, self.TST_RPLAY, None, None, None, None)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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
            vol_name, self.TST_RPLAY, None, None, None, None)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
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
            vol_name, self.TST_RPLAY, None, None, None, None)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.VOLUME, res, 'Unexpected ScVolume')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder',
                       return_value=FLDR)
    @mock.patch.object(storagecenter_api.HttpClient,
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
            vol_name, self.TST_RPLAY, None, None, None, None)
        self.assertTrue(mock_post.called)
        mock_find_volume_folder.assert_called_once_with(True)
        self.assertIsNone(res, 'Expected None')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_datareduction_profile')
    def test_create_view_volume_with_profiles(
            self, mock_update_datareduction_profile, mock_find_replay_profiles,
            mock_find_qos_profile, mock_post, mock_find_volume_folder,
            mock_first_result, mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_replay_profiles.return_value = (['12345.4'], [])
        mock_first_result.return_value = {'name': 'name'}
        mock_post.return_value = self.RESPONSE_200
        mock_find_volume_folder.return_value = {'instanceId': '12345.200'}
        mock_find_qos_profile.side_effect = [{'instanceId': '12345.2'},
                                             {'instanceId': '12345.3'}]
        screplay = {'instanceId': '12345.100.1'}
        res = self.scapi.create_view_volume(
            'name', screplay, 'replay_profile_string', 'volume_qos',
            'group_qos', 'datareductionprofile')
        expected_payload = {'Name': 'name',
                            'Notes': 'Created by Dell EMC Cinder Driver',
                            'VolumeFolder': '12345.200',
                            'ReplayProfileList': ['12345.4'],
                            'VolumeQosProfile': '12345.2',
                            'GroupQosProfile': '12345.3'}
        mock_find_volume_folder.assert_called_once_with(True)
        mock_post.assert_called_once_with(
            'StorageCenter/ScReplay/12345.100.1/CreateView', expected_payload,
            True)
        mock_update_datareduction_profile.assert_called_once_with(
            {'name': 'name'}, 'datareductionprofile')
        self.assertEqual({'name': 'name'}, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_datareduction_profile')
    def test_create_view_volume_with_profiles_no_dr(
            self, mock_update_datareduction_profile, mock_find_replay_profiles,
            mock_find_qos_profile, mock_post, mock_find_volume_folder,
            mock_first_result, mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_replay_profiles.return_value = (['12345.4'], [])
        mock_first_result.return_value = {'name': 'name'}
        mock_post.return_value = self.RESPONSE_200
        mock_find_volume_folder.return_value = {'instanceId': '12345.200'}
        mock_find_qos_profile.side_effect = [{'instanceId': '12345.2'},
                                             {'instanceId': '12345.3'}]
        screplay = {'instanceId': '12345.100.1'}
        res = self.scapi.create_view_volume('name', screplay,
                                            'replay_profile_string',
                                            'volume_qos',
                                            'group_qos',
                                            None)
        expected_payload = {'Name': 'name',
                            'Notes': 'Created by Dell EMC Cinder Driver',
                            'VolumeFolder': '12345.200',
                            'ReplayProfileList': ['12345.4'],
                            'VolumeQosProfile': '12345.2',
                            'GroupQosProfile': '12345.3'}
        mock_find_volume_folder.assert_called_once_with(True)
        mock_post.assert_called_once_with(
            'StorageCenter/ScReplay/12345.100.1/CreateView', expected_payload,
            True)
        mock_update_datareduction_profile.assert_not_called()
        self.assertEqual({'name': 'name'}, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_create_view_volume_with_profiles_no_replayprofiles(
            self, mock_find_qos_profile, mock_post, mock_find_volume_folder,
            mock_first_result, mock_close_connection, mock_open_connection,
            mock_init):
        mock_first_result.return_value = {'name': 'name'}
        mock_post.return_value = self.RESPONSE_200
        mock_find_volume_folder.return_value = {'instanceId': '12345.200'}
        mock_find_qos_profile.side_effect = [{'instanceId': '12345.2'},
                                             {'instanceId': '12345.3'}]
        screplay = {'instanceId': '12345.100.1'}
        res = self.scapi.create_view_volume('name', screplay,
                                            None,
                                            'volume_qos',
                                            'group_qos',
                                            None)
        expected_payload = {'Name': 'name',
                            'Notes': 'Created by Dell EMC Cinder Driver',
                            'VolumeFolder': '12345.200',
                            'VolumeQosProfile': '12345.2',
                            'GroupQosProfile': '12345.3'}
        mock_find_volume_folder.assert_called_once_with(True)
        mock_post.assert_called_once_with(
            'StorageCenter/ScReplay/12345.100.1/CreateView', expected_payload,
            True)
        self.assertEqual({'name': 'name'}, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    def test_create_view_volume_with_profiles_not_found(
            self, mock_find_replay_profiles, mock_find_qos_profile,
            mock_find_volume_folder, mock_close_connection,
            mock_open_connection, mock_init):
        mock_find_replay_profiles.return_value = (['12345.4'], [])
        mock_find_volume_folder.return_value = {'instanceId': '12345.200'}
        # Our qos profile isn't found.
        mock_find_qos_profile.return_value = None
        screplay = {'instanceId': '12345.100.1'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_view_volume,
                          'name', screplay, 'replay_profile_string',
                          'volume_qos', 'group_qos', 'datareductionprofile')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test__expire_all_replays(self,
                                 mock_get_json,
                                 mock_get,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        scvolume = {'instanceId': '12345.1'}
        mock_get.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'instanceId': '12345.100',
                                       'active': False},
                                      {'instanceId': '12345.101',
                                       'active': True}]
        self.scapi._expire_all_replays(scvolume)
        mock_get.assert_called_once_with(
            'StorageCenter/ScVolume/12345.1/ReplayList')
        mock_post.assert_called_once_with(
            'StorageCenter/ScReplay/12345.100/Expire', {}, True)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    def test__expire_all_replays_error(self,
                                       mock_get,
                                       mock_post,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        scvolume = {'instanceId': '12345.1'}
        mock_get.return_value = self.RESPONSE_400
        self.scapi._expire_all_replays(scvolume)
        mock_get.assert_called_once_with(
            'StorageCenter/ScVolume/12345.1/ReplayList')
        self.assertFalse(mock_post.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test__expire_all_replays_no_replays(self,
                                            mock_get_json,
                                            mock_get,
                                            mock_post,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        scvolume = {'instanceId': '12345.1'}
        mock_get.return_value = self.RESPONSE_200
        mock_get_json.return_value = None
        self.scapi._expire_all_replays(scvolume)
        mock_get.assert_called_once_with(
            'StorageCenter/ScVolume/12345.1/ReplayList')
        self.assertFalse(mock_post.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test__wait_for_cmm(
            self,
            mock_get_json,
            mock_get,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        cmm = {'instanceId': '12345.300'}
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1'}
        replayid = '12345.200'
        mock_get.return_value = self.RESPONSE_200
        mock_get_json.return_value = {'instanceId': '12345.300',
                                      'state': 'Finished'}
        ret = self.scapi._wait_for_cmm(cmm, scvolume, replayid)
        self.assertTrue(ret)
        mock_get_json.return_value['state'] = 'Erred'
        ret = self.scapi._wait_for_cmm(cmm, scvolume, replayid)
        self.assertFalse(ret)
        mock_get_json.return_value['state'] = 'Paused'
        ret = self.scapi._wait_for_cmm(cmm, scvolume, replayid)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay')
    def test__wait_for_cmm_404(
            self,
            mock_find_replay,
            mock_get,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        cmm = {'instanceId': '12345.300'}
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1'}
        replayid = '12345.200'
        mock_get.return_value = self.RESPONSE_404
        mock_find_replay.return_value = {'instanceId': '12345.200'}
        ret = self.scapi._wait_for_cmm(cmm, scvolume, replayid)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay')
    @mock.patch.object(eventlet, 'sleep')
    def test__wait_for_cmm_timeout(
            self,
            mock_sleep,
            mock_find_replay,
            mock_get,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        cmm = {'instanceId': '12345.300'}
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1'}
        replayid = '12345.200'
        mock_get.return_value = self.RESPONSE_404
        mock_find_replay.return_value = None
        ret = self.scapi._wait_for_cmm(cmm, scvolume, replayid)
        self.assertFalse(ret)
        self.assertEqual(21, mock_sleep.call_count)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_wait_for_cmm')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_expire_all_replays')
    def test_create_cloned_volume(
            self,
            mock_expire_all_replays,
            mock_wait_for_cmm,
            mock_get_json,
            mock_post,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'
        cmm = {'state': 'Running'}

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = cmm
        mock_create_replay.return_value = {'instanceId': '12345.100'}
        mock_create_volume.return_value = newvol
        mock_wait_for_cmm.return_value = True

        # our call
        res = self.scapi.create_cloned_volume(
            vol_name, scvolume, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        expected_payload = {}
        expected_payload['CopyReplays'] = True
        expected_payload['DestinationVolume'] = '12345.2'
        expected_payload['SourceVolume'] = '12345.1'
        expected_payload['StorageCenter'] = 12345
        expected_payload['Priority'] = 'High'
        mock_post.assert_called_once_with(
            'StorageCenter/ScCopyMirrorMigrate/Copy', expected_payload, True)
        mock_wait_for_cmm.assert_called_once_with(cmm, newvol, str(replayuuid))
        mock_expire_all_replays.assert_called_once_with(newvol)
        self.assertEqual(newvol, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    def test_create_cloned_volume_create_vol_fail(
            self,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = None
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'

        # our call returns
        mock_create_volume.return_value = newvol

        # our call
        res = self.scapi.create_cloned_volume(
            vol_name, scvolume, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_replay_fail(
            self,
            mock_delete_volume,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_create_replay.return_value = None
        mock_create_volume.return_value = newvol

        # our call
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_cloned_volume, vol_name,
                          scvolume, storage_profile, replay_profile_list,
                          volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        mock_delete_volume.assert_called_once_with(vol_name, '12345.2')

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_copy_fail(
            self,
            mock_delete_volume,
            mock_post,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_post.return_value = self.RESPONSE_400
        mock_create_replay.return_value = {'instanceId': '12345.100'}
        mock_create_volume.return_value = newvol

        # our call
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_cloned_volume, vol_name,
                          scvolume, storage_profile, replay_profile_list,
                          volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        expected_payload = {}
        expected_payload['CopyReplays'] = True
        expected_payload['DestinationVolume'] = '12345.2'
        expected_payload['SourceVolume'] = '12345.1'
        expected_payload['StorageCenter'] = 12345
        expected_payload['Priority'] = 'High'
        mock_post.assert_called_once_with(
            'StorageCenter/ScCopyMirrorMigrate/Copy', expected_payload, True)
        mock_delete_volume.assert_called_once_with(vol_name, '12345.2')

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_cmm_erred(
            self,
            mock_delete_volume,
            mock_get_json,
            mock_post,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'
        cmm = {'state': 'Erred'}

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = cmm
        mock_create_replay.return_value = {'instanceId': '12345.100'}
        mock_create_volume.return_value = newvol

        # our call
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_cloned_volume, vol_name,
                          scvolume, storage_profile, replay_profile_list,
                          volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        expected_payload = {}
        expected_payload['CopyReplays'] = True
        expected_payload['DestinationVolume'] = '12345.2'
        expected_payload['SourceVolume'] = '12345.1'
        expected_payload['StorageCenter'] = 12345
        expected_payload['Priority'] = 'High'
        mock_post.assert_called_once_with(
            'StorageCenter/ScCopyMirrorMigrate/Copy', expected_payload, True)
        mock_delete_volume.assert_called_once_with(vol_name, '12345.2')

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_cmm_paused(
            self,
            mock_delete_volume,
            mock_get_json,
            mock_post,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'
        cmm = {'state': 'Paused'}

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = cmm
        mock_create_replay.return_value = {'instanceId': '12345.100'}
        mock_create_volume.return_value = newvol

        # our call
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_cloned_volume, vol_name,
                          scvolume, storage_profile, replay_profile_list,
                          volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        expected_payload = {}
        expected_payload['CopyReplays'] = True
        expected_payload['DestinationVolume'] = '12345.2'
        expected_payload['SourceVolume'] = '12345.1'
        expected_payload['StorageCenter'] = 12345
        expected_payload['Priority'] = 'High'
        mock_post.assert_called_once_with(
            'StorageCenter/ScCopyMirrorMigrate/Copy', expected_payload, True)
        mock_delete_volume.assert_called_once_with(vol_name, '12345.2')

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_wait_for_cmm')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_cmm_wait_for_cmm_fail(
            self,
            mock_delete_volume,
            mock_wait_for_cmm,
            mock_get_json,
            mock_post,
            mock_uuid4,
            mock_create_replay,
            mock_create_volume,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        # our state.
        vol_name = fake.VOLUME_ID
        scvolume = {'name': fake.VOLUME2_ID,
                    'instanceId': '12345.1',
                    'configuredSize': '1073741824 Bytes'}
        newvol = {'instanceId': '12345.2',
                  'configuredSize': '1073741824 Bytes'}
        storage_profile = 'profile1'
        replay_profile_list = ['profile2']
        volume_qos = 'vqos'
        group_qos = 'gqos'
        dr_profile = 'dqos'
        cmm = {'state': 'Running'}

        # our call returns
        replayuuid = uuid.uuid4()
        mock_uuid4.return_value = replayuuid
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = cmm
        mock_create_replay.return_value = {'instanceId': '12345.100'}
        mock_create_volume.return_value = newvol
        mock_wait_for_cmm.return_value = False

        # our call
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.create_cloned_volume, vol_name,
                          scvolume, storage_profile, replay_profile_list,
                          volume_qos, group_qos, dr_profile)

        # assert expected
        mock_create_volume.assert_called_once_with(
            vol_name, 1, storage_profile, replay_profile_list,
            volume_qos, group_qos, dr_profile)
        mock_create_replay.assert_called_once_with(
            scvolume, str(replayuuid), 60)
        expected_payload = {}
        expected_payload['CopyReplays'] = True
        expected_payload['DestinationVolume'] = '12345.2'
        expected_payload['SourceVolume'] = '12345.1'
        expected_payload['StorageCenter'] = 12345
        expected_payload['Priority'] = 'High'
        mock_post.assert_called_once_with(
            'StorageCenter/ScCopyMirrorMigrate/Copy', expected_payload, True)
        mock_wait_for_cmm.assert_called_once_with(cmm, newvol, str(replayuuid))
        mock_delete_volume.assert_called_once_with(vol_name, '12345.2')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    def test_rename_volume(self,
                           mock_put,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        res = self.scapi.rename_volume(self.VOLUME, 'newname')
        self.assertTrue(mock_put.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_400)
    def test_rename_volume_failure(self,
                                   mock_put,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.rename_volume(self.VOLUME, 'newname')
        self.assertTrue(mock_put.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.HttpClient,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value={'test': 'test'})
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_get_user_preferences(self,
                                  mock_get,
                                  mock_get_json,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        # Not really testing anything other than the ability to mock, but
        # including for completeness.
        res = self.scapi._get_user_preferences()
        self.assertEqual({'test': 'test'}, res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_get_user_preferences_failure(self,
                                          mock_get,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        res = self.scapi._get_user_preferences()
        self.assertEqual({}, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences',
                       return_value=None)
    def test_update_storage_profile_noprefs(self,
                                            mock_prefs,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        res = self.scapi.update_storage_profile(None, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences',
                       return_value={'allowStorageProfileSelection': False})
    def test_update_storage_profile_not_allowed(self,
                                                mock_prefs,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        LOG = self.mock_object(storagecenter_api, "LOG")
        res = self.scapi.update_storage_profile(None, None)
        self.assertFalse(res)
        self.assertEqual(1, LOG.error.call_count)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_storage_profile',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences',
                       return_value={'allowStorageProfileSelection': True})
    def test_update_storage_profile_prefs_not_found(self,
                                                    mock_profile,
                                                    mock_prefs,
                                                    mock_close_connection,
                                                    mock_open_connection,
                                                    mock_init):
        LOG = self.mock_object(storagecenter_api, "LOG")
        res = self.scapi.update_storage_profile(None, 'Fake')
        self.assertFalse(res)
        self.assertEqual(1, LOG.error.call_count)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences',
                       return_value={'allowStorageProfileSelection': True,
                                     'storageProfile': None})
    def test_update_storage_profile_default_not_found(self,
                                                      mock_prefs,
                                                      mock_close_connection,
                                                      mock_open_connection,
                                                      mock_init):
        LOG = self.mock_object(storagecenter_api, "LOG")
        res = self.scapi.update_storage_profile(None, None)
        self.assertFalse(res)
        self.assertEqual(1, LOG.error.call_count)

    @mock.patch.object(
        storagecenter_api.SCApi,
        '_get_user_preferences',
        return_value={'allowStorageProfileSelection': True,
                      'storageProfile': {'name': 'Fake',
                                         'instanceId': 'fakeId'}})
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    def test_update_storage_profile(self,
                                    mock_put,
                                    mock_prefs,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        LOG = self.mock_object(storagecenter_api, "LOG")
        fake_scvolume = {'name': 'name', 'instanceId': 'id'}
        res = self.scapi.update_storage_profile(fake_scvolume, None)
        self.assertTrue(res)
        self.assertIn('fakeId', repr(mock_put.call_args_list[0]))
        self.assertEqual(1, LOG.info.call_count)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[RPLAY_PROFILE])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_replay_profile(self,
                                 mock_post,
                                 mock_get_json,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        res = self.scapi.find_replay_profile('guid')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertEqual(self.RPLAY_PROFILE, res, 'Unexpected Profile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[RPLAY_PROFILE, RPLAY_PROFILE])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_replay_profile_more_than_one(self,
                                               mock_post,
                                               mock_get_json,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.find_replay_profile,
                          'guid')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_find_replay_profile_empty_list(self,
                                            mock_post,
                                            mock_get_json,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        res = self.scapi.find_replay_profile('guid')
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNone(res, 'Unexpected return')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_find_replay_profile_error(self,
                                       mock_post,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        res = self.scapi.find_replay_profile('guid')
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'Unexpected return')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=RPLAY_PROFILE)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_201)
    def test_create_replay_profile(self,
                                   mock_post,
                                   mock_first_result,
                                   mock_find_replay_profile,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        res = self.scapi.create_replay_profile('guid')
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_first_result.called)
        self.assertEqual(self.RPLAY_PROFILE, res, 'Unexpected Profile')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=RPLAY_PROFILE)
    def test_create_replay_profile_exists(self,
                                          mock_find_replay_profile,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        res = self.scapi.create_replay_profile('guid')
        self.assertTrue(mock_find_replay_profile.called)
        self.assertEqual(self.RPLAY_PROFILE, res, 'Unexpected Profile')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_create_replay_profile_fail(self,
                                        mock_post,
                                        mock_find_replay_profile,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        res = self.scapi.create_replay_profile('guid')
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_post.called)
        self.assertIsNone(res, 'Unexpected return')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_delete_replay_profile(self,
                                   mock_get_id,
                                   mock_delete,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        profile = {'name': 'guid'}
        self.scapi.delete_replay_profile(profile)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_delete.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_delete_replay_profile_fail(self,
                                        mock_get_id,
                                        mock_delete,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        profile = {'name': 'guid'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.delete_replay_profile,
                          profile)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_delete.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_first_result',
                       return_value=VOLUME_CONFIG)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_get_volume_configuration(self,
                                      mock_get_id,
                                      mock_get,
                                      mock_first_result,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        res = self.scapi._get_volume_configuration({})
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get.called)
        self.assertEqual(self.VOLUME_CONFIG, res, 'Unexpected config')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_get_volume_configuration_bad_response(self,
                                                   mock_get_id,
                                                   mock_get,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        res = self.scapi._get_volume_configuration({})
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get.called)
        self.assertIsNone(res, 'Unexpected result')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_configuration',
                       return_value=VOLUME_CONFIG)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_update_volume_profiles(self,
                                    mock_get_id,
                                    mock_put,
                                    mock_get_volume_configuration,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        scvolume = {'instanceId': '1'}
        existingid = self.VOLUME_CONFIG[u'replayProfileList'][0][u'instanceId']
        vcid = self.VOLUME_CONFIG[u'instanceId']
        # First get_id is for our existing replay profile id and the second
        # is for the volume config and the last is for the volume id.  And
        # then we do this again for the second call below.
        mock_get_id.side_effect = [existingid,
                                   vcid,
                                   scvolume['instanceId'],
                                   existingid,
                                   vcid,
                                   scvolume['instanceId']]
        newid = '64702.1'
        expected_payload = {'ReplayProfileList': [newid, existingid]}
        expected_url = 'StorageCenter/ScVolumeConfiguration/' + vcid
        res = self.scapi._update_volume_profiles(scvolume, newid, None)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get_volume_configuration.called)
        mock_put.assert_called_once_with(expected_url, expected_payload, True)
        self.assertTrue(res)

        # Now do a remove.  (Restarting with the original config so this will
        # end up as an empty list.)
        expected_payload['ReplayProfileList'] = []
        res = self.scapi._update_volume_profiles(scvolume, None, existingid)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get_volume_configuration.called)
        mock_put.assert_called_with(expected_url, expected_payload, True)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_configuration',
                       return_value=VOLUME_CONFIG)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_400)
    # We set this to 1 so we can check our payload
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id')
    def test_update_volume_profiles_bad_response(self,
                                                 mock_get_id,
                                                 mock_put,
                                                 mock_get_volume_configuration,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        scvolume = {'instanceId': '1'}
        existingid = self.VOLUME_CONFIG[u'replayProfileList'][0][u'instanceId']
        vcid = self.VOLUME_CONFIG[u'instanceId']
        # First get_id is for our existing replay profile id and the second
        # is for the volume config and the last is for the volume id.  And
        # then we do this again for the second call below.
        mock_get_id.side_effect = [existingid,
                                   vcid,
                                   scvolume['instanceId'],
                                   existingid,
                                   vcid,
                                   scvolume['instanceId']]
        newid = '64702.1'
        expected_payload = {'ReplayProfileList': [newid, existingid]}
        expected_url = 'StorageCenter/ScVolumeConfiguration/' + vcid
        res = self.scapi._update_volume_profiles(scvolume, newid, None)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get_volume_configuration.called)
        mock_put.assert_called_once_with(expected_url, expected_payload, True)
        self.assertFalse(res)

        # Now do a remove.  (Restarting with the original config so this will
        # end up as an empty list.)
        expected_payload['ReplayProfileList'] = []
        res = self.scapi._update_volume_profiles(scvolume, None, existingid)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_get_volume_configuration.called)
        mock_put.assert_called_with(expected_url, expected_payload, True)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_configuration',
                       return_value=None)
    def test_update_volume_profiles_no_config(self,
                                              mock_get_volume_configuration,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        scvolume = {'instanceId': '1'}
        res = self.scapi._update_volume_profiles(scvolume, '64702.2', None)
        self.assertTrue(mock_get_volume_configuration.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=999)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_update_volume_profiles',
                       return_value=True)
    def test_add_cg_volumes(self,
                            mock_update_volume_profiles,
                            mock_find_volume,
                            mock_close_connection,
                            mock_open_connection,
                            mock_init):
        profileid = '100'
        add_volumes = [{'id': '1', 'provider_id': '1'}]
        res = self.scapi._add_cg_volumes(profileid, add_volumes)
        self.assertTrue(mock_find_volume.called)
        mock_update_volume_profiles.assert_called_once_with(999,
                                                            addid=profileid,
                                                            removeid=None)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=999)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_update_volume_profiles',
                       return_value=False)
    def test_add_cg_volumes_fail(self,
                                 mock_update_volume_profiles,
                                 mock_find_volume,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        profileid = '100'
        add_volumes = [{'id': '1', 'provider_id': '1'}]
        res = self.scapi._add_cg_volumes(profileid, add_volumes)
        self.assertTrue(mock_find_volume.called)
        mock_update_volume_profiles.assert_called_once_with(999,
                                                            addid=profileid,
                                                            removeid=None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=999)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_update_volume_profiles',
                       return_value=True)
    def test_remove_cg_volumes(self,
                               mock_update_volume_profiles,
                               mock_find_volume,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        profileid = '100'
        remove_volumes = [{'id': '1', 'provider_id': '1'}]
        res = self.scapi._remove_cg_volumes(profileid, remove_volumes)
        self.assertTrue(mock_find_volume.called)
        mock_update_volume_profiles.assert_called_once_with(999,
                                                            addid=None,
                                                            removeid=profileid)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=999)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_update_volume_profiles',
                       return_value=False)
    def test_remove_cg_volumes_false(self,
                                     mock_update_volume_profiles,
                                     mock_find_volume,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        profileid = '100'
        remove_volumes = [{'id': '1', 'provider_id': '1'}]
        res = self.scapi._remove_cg_volumes(profileid, remove_volumes)
        self.assertTrue(mock_find_volume.called)
        mock_update_volume_profiles.assert_called_once_with(999,
                                                            addid=None,
                                                            removeid=profileid)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_remove_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_update_cg_volumes(self,
                               mock_get_id,
                               mock_add_cg_volumes,
                               mock_remove_cg_volumes,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        profile = {'name': 'guid'}
        add_volumes = [{'id': '1'}]
        remove_volumes = [{'id': '2'}]
        res = self.scapi.update_cg_volumes(profile,
                                           add_volumes,
                                           remove_volumes)
        self.assertTrue(mock_get_id.called)
        mock_add_cg_volumes.assert_called_once_with('100', add_volumes)
        mock_remove_cg_volumes.assert_called_once_with('100',
                                                       remove_volumes)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_remove_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_update_cg_volumes_no_remove(self,
                                         mock_get_id,
                                         mock_add_cg_volumes,
                                         mock_remove_cg_volumes,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        profile = {'name': 'guid'}
        add_volumes = [{'id': '1'}]
        remove_volumes = []
        res = self.scapi.update_cg_volumes(profile,
                                           add_volumes,
                                           remove_volumes)
        self.assertTrue(mock_get_id.called)
        mock_add_cg_volumes.assert_called_once_with('100', add_volumes)
        self.assertFalse(mock_remove_cg_volumes.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_remove_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_update_cg_volumes_no_add(self,
                                      mock_get_id,
                                      mock_add_cg_volumes,
                                      mock_remove_cg_volumes,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        profile = {'name': 'guid'}
        add_volumes = []
        remove_volumes = [{'id': '1'}]
        res = self.scapi.update_cg_volumes(profile,
                                           add_volumes,
                                           remove_volumes)
        self.assertTrue(mock_get_id.called)
        mock_remove_cg_volumes.assert_called_once_with('100', remove_volumes)
        self.assertFalse(mock_add_cg_volumes.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_remove_cg_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_cg_volumes',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_update_cg_volumes_add_fail(self,
                                        mock_get_id,
                                        mock_add_cg_volumes,
                                        mock_remove_cg_volumes,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        profile = {'name': 'guid'}
        add_volumes = [{'id': '1'}]
        remove_volumes = [{'id': '2'}]
        res = self.scapi.update_cg_volumes(profile,
                                           add_volumes,
                                           remove_volumes)
        self.assertTrue(mock_get_id.called)
        mock_add_cg_volumes.assert_called_once_with('100', add_volumes)
        self.assertTrue(not mock_remove_cg_volumes.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_remove_cg_volumes',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_add_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_update_cg_volumes_remove_fail(self,
                                           mock_get_id,
                                           mock_add_cg_volumes,
                                           mock_remove_cg_volumes,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        profile = {'name': 'guid'}
        add_volumes = [{'id': '1'}]
        remove_volumes = [{'id': '2'}]
        res = self.scapi.update_cg_volumes(profile,
                                           add_volumes,
                                           remove_volumes)
        self.assertTrue(mock_get_id.called)
        mock_add_cg_volumes.assert_called_once_with('100', add_volumes)
        mock_remove_cg_volumes.assert_called_once_with('100',
                                                       remove_volumes)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[INACTIVE_VOLUME])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_volume')
    def test_init_cg_volumes_inactive(self,
                                      mock_init_volume,
                                      mock_get_json,
                                      mock_get,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        profileid = 100
        self.scapi._init_cg_volumes(profileid)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        mock_init_volume.assert_called_once_with(self.INACTIVE_VOLUME)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[VOLUME])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_volume')
    def test_init_cg_volumes_active(self,
                                    mock_init_volume,
                                    mock_get_json,
                                    mock_get,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        profileid = 100
        self.scapi._init_cg_volumes(profileid)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_get_json.called)
        self.assertFalse(mock_init_volume.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_cg_volumes')
    def test_snap_cg_replay(self,
                            mock_init_cg_volumes,
                            mock_get_id,
                            mock_post,
                            mock_close_connection,
                            mock_open_connection,
                            mock_init):
        replayid = 'guid'
        expire = 0
        profile = {'instanceId': '100'}
        # See the 100 from get_id above?
        expected_url = 'StorageCenter/ScReplayProfile/100/CreateReplay'
        expected_payload = {'description': replayid, 'expireTime': expire}
        res = self.scapi.snap_cg_replay(profile, replayid, expire)
        mock_post.assert_called_once_with(expected_url, expected_payload, True)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_init_cg_volumes.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_init_cg_volumes')
    def test_snap_cg_replay_bad_return(self,
                                       mock_init_cg_volumes,
                                       mock_get_id,
                                       mock_post,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        replayid = 'guid'
        expire = 0
        profile = {'instanceId': '100'}
        # See the 100 from get_id above?
        expected_url = 'StorageCenter/ScReplayProfile/100/CreateReplay'
        expected_payload = {'description': replayid, 'expireTime': expire}
        res = self.scapi.snap_cg_replay(profile, replayid, expire)
        mock_post.assert_called_once_with(expected_url, expected_payload, True)
        self.assertTrue(mock_get_id.called)
        self.assertTrue(mock_init_cg_volumes.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=CGS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_sc_cg(self,
                        mock_get,
                        mock_get_json,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        res = self.scapi._find_sc_cg(
            {},
            'GUID1-0869559e-6881-454e-ba18-15c6726d33c1')
        self.assertEqual(self.CGS[0], res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=CGS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_find_sc_cg_not_found(self,
                                  mock_get,
                                  mock_get_json,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        res = self.scapi._find_sc_cg(
            {},
            'GUID3-0869559e-6881-454e-ba18-15c6726d33c1')
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_find_sc_cg_fail(self,
                             mock_get,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        res = self.scapi._find_sc_cg(
            {},
            'GUID1-0869559e-6881-454e-ba18-15c6726d33c1')
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_sc_cg',
                       return_value={'instanceId': 101})
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=RPLAYS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    def test_find_cg_replays(self,
                             mock_get,
                             mock_get_json,
                             mock_find_sc_cg,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        profile = {'instanceId': '100'}
        replayid = 'Cinder Test Replay012345678910'
        res = self.scapi._find_cg_replays(profile, replayid)
        expected_url = 'StorageCenter/ScReplayConsistencyGroup/101/ReplayList'
        mock_get.assert_called_once_with(expected_url)
        self.assertTrue(mock_find_sc_cg.called)
        self.assertTrue(mock_get_json.called)
        # We should fine RPLAYS
        self.assertEqual(self.RPLAYS, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_sc_cg',
                       return_value=None)
    def test_find_cg_replays_no_cg(self,
                                   mock_find_sc_cg,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        profile = {'instanceId': '100'}
        replayid = 'Cinder Test Replay012345678910'
        res = self.scapi._find_cg_replays(profile, replayid)
        self.assertTrue(mock_find_sc_cg.called)
        # We should return an empty list.
        self.assertEqual([], res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_sc_cg',
                       return_value={'instanceId': 101})
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=None)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    def test_find_cg_replays_bad_json(self,
                                      mock_get,
                                      mock_get_json,
                                      mock_find_sc_cg,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        profile = {'instanceId': '100'}
        replayid = 'Cinder Test Replay012345678910'
        res = self.scapi._find_cg_replays(profile, replayid)
        expected_url = 'StorageCenter/ScReplayConsistencyGroup/101/ReplayList'
        mock_get.assert_called_once_with(expected_url)
        self.assertTrue(mock_find_sc_cg.called)
        self.assertTrue(mock_get_json.called)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_cg_replays',
                       return_value=RPLAYS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_delete_cg_replay(self,
                              mock_post,
                              mock_find_cg_replays,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        res = self.scapi.delete_cg_replay({}, '')
        expected_url = ('StorageCenter/ScReplay/' +
                        self.RPLAYS[0]['instanceId'] +
                        '/Expire')
        mock_post.assert_any_call(expected_url, {}, True)
        expected_url = ('StorageCenter/ScReplay/' +
                        self.RPLAYS[1]['instanceId'] +
                        '/Expire')
        mock_post.assert_any_call(expected_url, {}, True)
        self.assertTrue(mock_find_cg_replays.called)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_cg_replays',
                       return_value=RPLAYS)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_delete_cg_replay_error(self,
                                    mock_post,
                                    mock_find_cg_replays,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        expected_url = ('StorageCenter/ScReplay/' +
                        self.RPLAYS[0]['instanceId'] +
                        '/Expire')
        res = self.scapi.delete_cg_replay({}, '')
        mock_post.assert_called_once_with(expected_url, {}, True)
        self.assertTrue(mock_find_cg_replays.called)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_cg_replays',
                       return_value=[])
    def test_delete_cg_replay_cant_find(self,
                                        mock_find_cg_replays,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        res = self.scapi.delete_cg_replay({}, '')
        self.assertTrue(mock_find_cg_replays.called)
        self.assertTrue(res)

    def test_size_to_gb(self,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        gb, rem = self.scapi.size_to_gb('1.073741824E9 Byte')
        self.assertEqual(1, gb)
        self.assertEqual(0, rem)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.size_to_gb,
                          'banana')
        gb, rem = self.scapi.size_to_gb('1.073741924E9 Byte')
        self.assertEqual(1, gb)
        self.assertEqual(100, rem)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_volume_folder')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=VOLUME)
    def test_import_one(self,
                        mock_get_json,
                        mock_put,
                        mock_find_volume_folder,
                        mock_close_connection,
                        mock_open_connection,
                        mock_init):
        newname = 'guid'
        # First test is folder found.  Second ist is not found.
        mock_find_volume_folder.side_effect = [{'instanceId': '1'}, None]
        expected_url = 'StorageCenter/ScVolume/100'
        expected_payload = {'Name': newname,
                            'VolumeFolder': '1'}
        self.scapi._import_one({'instanceId': '100'}, newname)
        mock_put.assert_called_once_with(expected_url, expected_payload, True)
        self.assertTrue(mock_find_volume_folder.called)
        expected_payload = {'Name': newname}
        self.scapi._import_one({'instanceId': '100'}, newname)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741824E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 0))
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=[])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_import_one',
                       return_value=VOLUME)
    def test_manage_existing(self,
                             mock_import_one,
                             mock_find_mappings,
                             mock_size_to_gb,
                             mock_get_volume_list,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.scapi.manage_existing(newname, existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'), None, False)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_size_to_gb.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[])
    def test_manage_existing_vol_not_found(self,
                                           mock_get_volume_list,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):

        # Same as above only we don't have a volume folder.
        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.scapi.manage_existing,
                          newname,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{}, {}, {}])
    def test_manage_existing_vol_multiple_found(self,
                                                mock_get_volume_list,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):

        # Same as above only we don't have a volume folder.
        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.scapi.manage_existing,
                          newname,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741924E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 100))
    def test_manage_existing_bad_size(self,
                                      mock_size_to_gb,
                                      mock_get_volume_list,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):

        # Same as above only we don't have a volume folder.
        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.manage_existing,
                          newname,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)
        self.assertTrue(mock_size_to_gb.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741824E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 0))
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=[{}, {}])
    def test_manage_existing_already_mapped(self,
                                            mock_find_mappings,
                                            mock_size_to_gb,
                                            mock_get_volume_list,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):

        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.manage_existing,
                          newname,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_size_to_gb.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741824E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 0))
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_mappings',
                       return_value=[])
    @mock.patch.object(storagecenter_api.SCApi,
                       '_import_one',
                       return_value=None)
    def test_manage_existing_import_fail(self,
                                         mock_import_one,
                                         mock_find_mappings,
                                         mock_size_to_gb,
                                         mock_get_volume_list,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        # We fail on the _find_volume_folder to make this easier.
        newname = 'guid'
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.manage_existing,
                          newname,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)
        self.assertTrue(mock_find_mappings.called)
        self.assertTrue(mock_size_to_gb.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741824E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 0))
    def test_get_unmanaged_volume_size(self,
                                       mock_size_to_gb,
                                       mock_get_volume_list,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        existing = {'source-name': 'scvolname'}
        res = self.scapi.get_unmanaged_volume_size(existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)
        self.assertTrue(mock_size_to_gb.called)
        self.assertEqual(1, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[])
    def test_get_unmanaged_volume_size_not_found(self,
                                                 mock_get_volume_list,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.scapi.get_unmanaged_volume_size,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{}, {}, {}])
    def test_get_unmanaged_volume_size_many_found(self,
                                                  mock_get_volume_list,
                                                  mock_close_connection,
                                                  mock_open_connection,
                                                  mock_init):
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.scapi.get_unmanaged_volume_size,
                          existing)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_volume_list',
                       return_value=[{'configuredSize':
                                      '1.073741924E9 Bytes'}])
    @mock.patch.object(storagecenter_api.SCApi,
                       'size_to_gb',
                       return_value=(1, 100))
    def test_get_unmanaged_volume_size_bad_size(self,
                                                mock_size_to_gb,
                                                mock_get_volume_list,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        existing = {'source-name': 'scvolname'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.get_unmanaged_volume_size,
                          existing)
        self.assertTrue(mock_size_to_gb.called)
        mock_get_volume_list.assert_called_once_with(
            existing.get('source-name'),
            existing.get('source-id'),
            False)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_unmanage(self,
                      mock_get_id,
                      mock_put,
                      mock_close_connection,
                      mock_open_connection,
                      mock_init):
        # Same as above only we don't have a volume folder.
        scvolume = {'name': 'guid'}
        expected_url = 'StorageCenter/ScVolume/100'
        newname = 'Unmanaged_' + scvolume['name']
        expected_payload = {'Name': newname}
        self.scapi.unmanage(scvolume)
        self.assertTrue(mock_get_id.called)
        mock_put.assert_called_once_with(expected_url, expected_payload, True)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_id',
                       return_value='100')
    def test_unmanage_fail(self,
                           mock_get_id,
                           mock_put,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        # Same as above only we don't have a volume folder.
        scvolume = {'name': 'guid'}
        expected_url = 'StorageCenter/ScVolume/100'
        newname = 'Unmanaged_' + scvolume['name']
        expected_payload = {'Name': newname}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.unmanage,
                          scvolume)
        self.assertTrue(mock_get_id.called)
        mock_put.assert_called_once_with(expected_url, expected_payload, True)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[SCQOS])
    # def _find_qos(self, qosnode):
    def test__find_qos(self,
                       mock_get_json,
                       mock_post,
                       mock_close_connection,
                       mock_open_connection,
                       mock_init):
        ret = self.scapi._find_qos('Cinder QoS')
        self.assertDictEqual(self.SCQOS, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    # def _find_qos(self, qosnode):
    def test__find_qos_not_found(self,
                                 mock_get_json,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        # set side effect for posts.
        # first empty second returns qosnode
        mock_get_json.side_effect = [[], self.SCQOS]
        ret = self.scapi._find_qos('Cinder QoS')
        self.assertDictEqual(self.SCQOS, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    # def _find_qos(self, qosnode):
    def test__find_qos_find_fail(self,
                                 mock_post,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._find_qos,
                          'Cinder QoS')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    # def _find_qos(self, qosnode):
    def test__find_qos_create_fail(self,
                                   mock_get_json,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_post.side_effect = [self.RESPONSE_200, self.RESPONSE_400]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._find_qos,
                          'Cinder QoS')

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL)
    def test_update_replicate_active_replay_fail(self,
                                                 mock_get_json,
                                                 mock_get,
                                                 mock_put,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        ret = self.scapi.update_replicate_active_replay({'instanceId': '1'},
                                                        True)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL)
    def test_update_replicate_active_replay_nothing_to_do(
            self, mock_get_json, mock_get, mock_close_connection,
            mock_open_connection, mock_init):
        ret = self.scapi.update_replicate_active_replay({'instanceId': '1'},
                                                        False)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    def test_update_replicate_active_replay_not_found(self,
                                                      mock_get_json,
                                                      mock_get,
                                                      mock_close_connection,
                                                      mock_open_connection,
                                                      mock_init):
        ret = self.scapi.update_replicate_active_replay({'instanceId': '1'},
                                                        True)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    def test_update_replicate_active_replay_not_found2(self,
                                                       mock_get_json,
                                                       mock_get,
                                                       mock_close_connection,
                                                       mock_open_connection,
                                                       mock_init):
        ret = self.scapi.update_replicate_active_replay({'instanceId': '1'},
                                                        True)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[{'instanceId': '12345.1'}])
    def test_get_disk_folder(self,
                             mock_get_json,
                             mock_post,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        ret = self.scapi._get_disk_folder(12345, 'name')
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'name',
             'attributeValue': 'name'}]}}
        mock_post.assert_called_once_with('StorageCenter/ScDiskFolder/GetList',
                                          expected_payload)
        self.assertEqual({'instanceId': '12345.1'}, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_get_disk_folder_fail(self,
                                  mock_post,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        ret = self.scapi._get_disk_folder(12345, 'name')
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'name',
             'attributeValue': 'name'}]}}
        mock_post.assert_called_once_with('StorageCenter/ScDiskFolder/GetList',
                                          expected_payload)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test_get_disk_folder_fail_bad_json(self,
                                           mock_get_json,
                                           mock_post,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        mock_get_json.side_effect = (exception.VolumeBackendAPIException(''))
        ret = self.scapi._get_disk_folder(12345, 'name')
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'scSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'name',
             'attributeValue': 'name'}]}}
        mock_post.assert_called_once_with('StorageCenter/ScDiskFolder/GetList',
                                          expected_payload)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL)
    def test_get_screplication(self,
                               mock_get_json,
                               mock_get,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        ret = self.scapi.get_screplication({'instanceId': '1'}, 65495)
        self.assertDictEqual(self.SCREPL[0], ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    def test_get_screplication_not_found(self,
                                         mock_get_json,
                                         mock_get,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        ret = self.scapi.get_screplication({'instanceId': '1'}, 65496)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_get_screplication_error(self,
                                     mock_get,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        ret = self.scapi.get_screplication({'instanceId': '1'}, 65495)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_screplication',
                       return_value=SCREPL[0])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_200)
    def test_delete_replication(self,
                                mock_delete,
                                mock_get_screplication,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        destssn = 65495
        expected = 'StorageCenter/ScReplication/%s' % (
            self.SCREPL[0]['instanceId'])
        expected_payload = {'DeleteDestinationVolume': True,
                            'RecycleDestinationVolume': True,
                            'DeleteRestorePoint': True}
        ret = self.scapi.delete_replication(self.VOLUME, destssn)
        mock_delete.assert_any_call(expected, payload=expected_payload,
                                    async_call=True)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_screplication',
                       return_value=None)
    def test_delete_replication_not_found(self,
                                          mock_get_screplication,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        destssn = 65495
        ret = self.scapi.delete_replication(self.VOLUME, destssn)
        self.assertFalse(ret)
        ret = self.scapi.delete_replication(self.VOLUME, destssn)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_screplication',
                       return_value=SCREPL[0])
    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete',
                       return_value=RESPONSE_400)
    def test_delete_replication_error(self,
                                      mock_delete,
                                      mock_get_screplication,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        destssn = 65495
        expected = 'StorageCenter/ScReplication/%s' % (
            self.SCREPL[0]['instanceId'])
        expected_payload = {'DeleteDestinationVolume': True,
                            'RecycleDestinationVolume': True,
                            'DeleteRestorePoint': True}
        ret = self.scapi.delete_replication(self.VOLUME, destssn)
        mock_delete.assert_any_call(expected, payload=expected_payload,
                                    async_call=True)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos',
                       return_value=SCQOS)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL[0])
    def test_create_replication(self,
                                mock_get_json,
                                mock_post,
                                mock_find_sc,
                                mock_find_qos,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # We don't test diskfolder. If one is found we include it. If not
        # then we leave it out. Checking for disk folder is tested elsewhere.
        ssn = 64702
        destssn = 65495
        qosnode = 'Cinder QoS'
        notes = 'Created by Dell EMC Cinder Driver'
        repl_prefix = 'Cinder repl of '

        mock_find_sc.side_effect = [destssn, ssn, destssn, ssn, destssn, ssn]
        payload = {'DestinationStorageCenter': destssn,
                   'QosNode': self.SCQOS['instanceId'],
                   'SourceVolume': self.VOLUME['instanceId'],
                   'StorageCenter': ssn,
                   'ReplicateActiveReplay': False,
                   'Type': 'Asynchronous',
                   'DestinationVolumeAttributes':
                       {'CreateSourceVolumeFolderPath': True,
                        'Notes': notes,
                        'Name': repl_prefix + self.VOLUME['name']}
                   }
        ret = self.scapi.create_replication(self.VOLUME,
                                            str(destssn),
                                            qosnode,
                                            False,
                                            None,
                                            False)
        mock_post.assert_any_call('StorageCenter/ScReplication', payload, True)
        self.assertDictEqual(self.SCREPL[0], ret)
        payload['Type'] = 'Synchronous'
        payload['ReplicateActiveReplay'] = True
        payload['SyncMode'] = 'HighAvailability'
        ret = self.scapi.create_replication(self.VOLUME,
                                            str(destssn),
                                            qosnode,
                                            True,
                                            None,
                                            False)
        mock_post.assert_any_call('StorageCenter/ScReplication', payload, True)
        self.assertDictEqual(self.SCREPL[0], ret)
        ret = self.scapi.create_replication(self.VOLUME,
                                            str(destssn),
                                            qosnode,
                                            True,
                                            None,
                                            True)
        mock_post.assert_any_call('StorageCenter/ScReplication', payload, True)
        self.assertDictEqual(self.SCREPL[0], ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos',
                       return_value=SCQOS)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL[0])
    def test_create_replication_error(self,
                                      mock_get_json,
                                      mock_post,
                                      mock_find_sc,
                                      mock_find_qos,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        ssn = 64702
        destssn = 65495
        qosnode = 'Cinder QoS'
        notes = 'Created by Dell EMC Cinder Driver'
        repl_prefix = 'Cinder repl of '

        mock_find_sc.side_effect = [destssn, ssn, destssn, ssn]
        mock_post.side_effect = [self.RESPONSE_400, self.RESPONSE_400,
                                 self.RESPONSE_400, self.RESPONSE_400]
        payload = {'DestinationStorageCenter': destssn,
                   'QosNode': self.SCQOS['instanceId'],
                   'SourceVolume': self.VOLUME['instanceId'],
                   'StorageCenter': ssn,
                   'ReplicateActiveReplay': False,
                   'Type': 'Asynchronous',
                   'DestinationVolumeAttributes':
                       {'CreateSourceVolumeFolderPath': True,
                        'Notes': notes,
                        'Name': repl_prefix + self.VOLUME['name']}
                   }
        ret = self.scapi.create_replication(self.VOLUME,
                                            str(destssn),
                                            qosnode,
                                            False,
                                            None,
                                            False)
        mock_post.assert_any_call('StorageCenter/ScReplication', payload, True)
        self.assertIsNone(ret)

        payload['Type'] = 'Synchronous'
        payload['ReplicateActiveReplay'] = True
        payload['SyncMode'] = 'HighAvailability'
        ret = self.scapi.create_replication(self.VOLUME,
                                            str(destssn),
                                            qosnode,
                                            True,
                                            None,
                                            True)
        mock_post.assert_any_call('StorageCenter/ScReplication', payload, True)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=SCREPL)
    def test_find_repl_volume(self,
                              mock_get_json,
                              mock_post,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        ret = self.scapi.find_repl_volume('guid', 65495)
        self.assertDictEqual(self.SCREPL[0], ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[])
    def test_find_repl_volume_empty_list(self,
                                         mock_get_json,
                                         mock_post,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        ret = self.scapi.find_repl_volume('guid', 65495)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=[{'instanceId': '1'}, {'instanceId': '2'}])
    def test_find_repl_volume_multiple_results(self,
                                               mock_get_json,
                                               mock_post,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        ret = self.scapi.find_repl_volume('guid', 65495)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_find_repl_volume_error(self,
                                    mock_post,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        ret = self.scapi.find_repl_volume('guid', 65495)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_screplication')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_repl_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'remove_mappings')
    def test_break_replication(self,
                               mock_remove_mappings,
                               mock_find_volume,
                               mock_find_repl_volume,
                               mock_get_screplication,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        # Find_volume doesn't actually matter.  We do not gate on this.
        # Switch it up just to prove that.
        mock_find_volume.side_effect = [self.VOLUME,    # 1
                                        self.VOLUME,    # 2
                                        None,           # 3
                                        None]           # 4
        # Much like find volume we do not gate on this.
        mock_get_screplication.side_effect = [self.SCREPL[0],  # 1
                                              None]            # 2
        # This
        mock_find_repl_volume.side_effect = [self.VOLUME,   # 1
                                             self.VOLUME,   # 2
                                             self.VOLUME,   # 3
                                             self.VOLUME]   # 4
        mock_remove_mappings.side_effect = [True,   # 1
                                            True,
                                            True,   # 2
                                            False,
                                            True,   # 3
                                            True,
                                            False]  # 4
        # Good path.
        ret = self.scapi.break_replication('name', None, 65495)
        self.assertEqual(self.VOLUME, ret)
        # Source found, screpl not found.
        ret = self.scapi.break_replication('name', None, 65495)
        self.assertEqual(self.VOLUME, ret)
        # No source vol good path.
        ret = self.scapi.break_replication('name', None, 65495)
        self.assertEqual(self.VOLUME, ret)
        # fail remove mappings
        ret = self.scapi.break_replication('name', None, 65495)
        self.assertEqual(self.VOLUME, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    def test__find_user_replay_profiles(self,
                                        mock_get_user_preferences,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        mock_get_user_preferences.return_value = {}
        ret = self.scapi._find_user_replay_profiles()
        self.assertEqual([], ret)
        mock_get_user_preferences.return_value = {'test': 'test',
                                                  'replayProfileList': []}
        ret = self.scapi._find_user_replay_profiles()
        self.assertEqual([], ret)
        mock_get_user_preferences.return_value = {
            'test': 'test', 'replayProfileList': [{'instanceId': 'a'},
                                                  {'instanceId': 'b'}]}
        ret = self.scapi._find_user_replay_profiles()
        self.assertEqual(['a', 'b'], ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test__find_daily_replay_profile(self,
                                        mock_get_json,
                                        mock_post,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'instanceId': 'a'}]
        ret = self.scapi._find_daily_replay_profile()
        self.assertEqual('a', ret)
        mock_get_json.return_value = []
        ret = self.scapi._find_daily_replay_profile()
        self.assertIsNone(ret)
        mock_get_json.return_value = None
        ret = self.scapi._find_daily_replay_profile()
        self.assertIsNone(ret)
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi._find_daily_replay_profile()
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test__find_replay_profiles(self,
                                   mock_get_json,
                                   mock_post,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Good run.
        rps = 'a,b'
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'name': 'a', 'instanceId': 'a'},
                                      {'name': 'b', 'instanceId': 'b'},
                                      {'name': 'c', 'instanceId': 'c'}]
        reta, retb = self.scapi._find_replay_profiles(rps)
        self.assertEqual(['a', 'b'], reta)
        self.assertEqual(['c'], retb)
        # Looking for profile that doesn't exist.
        rps = 'a,b,d'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._find_replay_profiles,
                          rps)
        # Looking for nothing.
        rps = ''
        reta, retb = self.scapi._find_replay_profiles(rps)
        self.assertEqual([], reta)
        self.assertEqual([], retb)
        # Still Looking for nothing.
        rps = None
        reta, retb = self.scapi._find_replay_profiles(rps)
        self.assertEqual([], reta)
        self.assertEqual([], retb)
        # Bad call.
        rps = 'a,b'
        mock_post.return_value = self.RESPONSE_400
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._find_replay_profiles,
                          rps)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_replay_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_user_replay_profiles')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_daily_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_update_volume_profiles')
    def test_update_replay_profiles(self,
                                    mock_update_volume_profiles,
                                    mock_find_daily_replay_profile,
                                    mock_find_user_replay_profiles,
                                    mock_find_replay_profiles,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        scvol = {}
        mock_find_replay_profiles.return_value = (['a', 'b'], ['c'])
        mock_update_volume_profiles.side_effect = [
            True, True, True,
            False,
            True, True, False,
            True, True, True, True, True,
            True, True, True, True,
            False]
        ret = self.scapi.update_replay_profiles(scvol, 'a,b')
        # Two adds and one remove
        self.assertEqual(3, mock_update_volume_profiles.call_count)
        self.assertTrue(ret)
        # Now update fails.
        ret = self.scapi.update_replay_profiles(scvol, 'a,b')
        # 1 failed update plus 3 from before.
        self.assertEqual(4, mock_update_volume_profiles.call_count)
        self.assertFalse(ret)
        # Fail adding Ids..
        ret = self.scapi.update_replay_profiles(scvol, 'a,b')
        # 3 more 4 from before.
        self.assertEqual(7, mock_update_volume_profiles.call_count)
        self.assertFalse(ret)
        # User clearing profiles.
        mock_find_replay_profiles.return_value = ([], ['a', 'b', 'c'])
        mock_find_user_replay_profiles.return_value = ['d', 'u']
        ret = self.scapi.update_replay_profiles(scvol, '')
        # 3 removes and 2 adds plus 7 from before
        self.assertEqual(12, mock_update_volume_profiles.call_count)
        self.assertTrue(ret)
        # User clearing profiles and no defaults. (Probably not possible.)
        mock_find_user_replay_profiles.return_value = []
        mock_find_daily_replay_profile.return_value = 'd'
        ret = self.scapi.update_replay_profiles(scvol, '')
        # 3 removes and 1 add plus 12 from before.
        self.assertEqual(16, mock_update_volume_profiles.call_count)
        self.assertTrue(ret)
        # _find_replay_profiles blows up so we do too.
        mock_find_replay_profiles.side_effect = (
            exception.VolumeBackendAPIException('aaa'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.update_replay_profiles,
                          scvol,
                          'a,b')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume(self,
                             mock_get_live_volumes,
                             mock_sc_live_volumes,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        # Basic check
        retlv = self.scapi.get_live_volume(None)
        self.assertIsNone(retlv)
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1'}}
        lv2 = {'primaryVolume': {'instanceId': '12345.2'}}
        mock_sc_live_volumes.return_value = [lv1, lv2]
        # Good Run
        retlv = self.scapi.get_live_volume('12345.2')
        self.assertEqual(lv2, retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        self.assertFalse(mock_get_live_volumes.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_on_secondary(self,
                                          mock_get_live_volumes,
                                          mock_sc_live_volumes,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        # Basic check
        retlv = self.scapi.get_live_volume(None)
        self.assertIsNone(retlv)
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1'}}
        lv2 = {'primaryVolume': {'instanceId': '12345.2'}}
        mock_sc_live_volumes.return_value = []
        mock_get_live_volumes.return_value = [lv1, lv2]
        # Good Run
        retlv = self.scapi.get_live_volume('12345.2')
        self.assertEqual(lv2, retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        mock_get_live_volumes.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_not_found(self,
                                       mock_get_live_volumes,
                                       mock_sc_live_volumes,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1'}}
        lv2 = {'primaryVolume': {'instanceId': '12345.2'},
               'secondaryVolume': {'instanceId': '67890.2'}}
        mock_get_live_volumes.return_value = [lv1, lv2]
        mock_sc_live_volumes.return_value = []
        retlv = self.scapi.get_live_volume('12345.3')
        self.assertIsNone(retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        mock_get_live_volumes.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_swapped(self,
                                     mock_get_live_volumes,
                                     mock_sc_live_volumes,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1'}}
        lv2 = {'primaryVolume': {'instanceId': '67890.2'},
               'secondaryVolume': {'instanceId': '12345.2'}}
        mock_get_live_volumes.return_value = [lv1, lv2]
        mock_sc_live_volumes.return_value = []
        retlv = self.scapi.get_live_volume('12345.2')
        self.assertEqual(lv2, retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        mock_get_live_volumes.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_error(self,
                                   mock_get_live_volumes,
                                   mock_sc_live_volumes,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_get_live_volumes.return_value = []
        mock_sc_live_volumes.return_value = []
        retlv = self.scapi.get_live_volume('12345.2')
        self.assertIsNone(retlv)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_by_name(self,
                                     mock_get_live_volumes,
                                     mock_sc_live_volumes,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1',
                                   'instanceName': fake.VOLUME2_ID},
               'instanceName': 'Live volume of ' + fake.VOLUME2_ID}
        lv2 = {'primaryVolume': {'instanceId': '67890.2'},
               'secondaryVolume': {'instanceId': '12345.2',
                                   'instanceName': fake.VOLUME_ID},
               'instanceName': 'Live volume of ' + fake.VOLUME_ID}
        mock_get_live_volumes.return_value = [lv1, lv2]
        mock_sc_live_volumes.return_value = []
        retlv = self.scapi.get_live_volume('12345.2', fake.VOLUME_ID)
        self.assertEqual(lv2, retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        mock_get_live_volumes.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       '_sc_live_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_live_volumes')
    def test_get_live_volume_by_name_unknown(self,
                                             mock_get_live_volumes,
                                             mock_sc_live_volumes,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        lv1 = {'primaryVolume': {'instanceId': '12345.1'},
               'secondaryVolume': {'instanceId': '67890.1',
                                   'instanceName': fake.VOLUME2_ID},
               'instanceName': 'Live volume of ' + fake.VOLUME2_ID}
        lv2 = {'secondaryVolume': {'instanceId': '12345.2',
                                   'instanceName': fake.VOLUME_ID},
               'instanceName': 'unknown'}
        mock_get_live_volumes.return_value = [lv1, lv2]
        mock_sc_live_volumes.return_value = []
        retlv = self.scapi.get_live_volume('12345.3', fake.VOLUME_ID)
        self.assertEqual(lv2, retlv)
        mock_sc_live_volumes.assert_called_once_with('12345')
        mock_get_live_volumes.assert_called_once_with()

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    def test_map_secondary_volume(self,
                                  mock_get_json,
                                  mock_post,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101'},
                     'secondaryScSerialNumber': 102}
        scdestsrv = {'instanceId': '102.1000'}
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = {'instanceId': '102.101.1'}
        ret = self.scapi.map_secondary_volume(sclivevol, scdestsrv)
        expected_payload = {'Server': '102.1000',
                            'Advanced': {'MapToDownServerHbas': True}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScLiveVolume/101.101/MapSecondaryVolume',
            expected_payload, True
        )
        self.assertEqual({'instanceId': '102.101.1'}, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test_map_secondary_volume_err(self,
                                      mock_post,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101'},
                     'secondaryScSerialNumber': 102}
        scdestsrv = {'instanceId': '102.1000'}
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi.map_secondary_volume(sclivevol, scdestsrv)
        expected_payload = {'Server': '102.1000',
                            'Advanced': {'MapToDownServerHbas': True}}
        mock_post.assert_called_once_with(
            'StorageCenter/ScLiveVolume/101.101/MapSecondaryVolume',
            expected_payload, True
        )
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume(self,
                                mock_find_sc,
                                mock_find_qos,
                                mock_get_json,
                                mock_post,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101'},
                     'secondaryScSerialNumber': 102}

        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.side_effect = [{'instanceId': '101.1001'},
                                     {'instanceId': '102.1001'}]
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = sclivevol
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            False, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertEqual(sclivevol, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume_autofailover(self,
                                             mock_find_sc,
                                             mock_find_qos,
                                             mock_get_json,
                                             mock_post,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101'},
                     'secondaryScSerialNumber': 102}

        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.side_effect = [{'instanceId': '101.1001'},
                                     {'instanceId': '102.1001'}]
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = sclivevol
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            True, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertEqual(sclivevol, ret)
        # Make sure sync flipped and that we set HighAvailability.
        expected = {'SyncMode': 'HighAvailability',
                    'SwapRolesAutomaticallyEnabled': False,
                    'SecondaryStorageCenter': 102,
                    'FailoverAutomaticallyEnabled': True,
                    'StorageCenter': 12345,
                    'RestoreAutomaticallyEnabled': True,
                    'SecondaryQosNode': '102.1001',
                    'ReplicateActiveReplay': True,
                    'PrimaryQosNode': '101.1001',
                    'Type': 'Synchronous',
                    'PrimaryVolume': '101.1',
                    'SecondaryVolumeAttributes':
                        {'Notes': 'Created by Dell EMC Cinder Driver',
                         'CreateSourceVolumeFolderPath': True,
                         'Name': 'name'}
                    }
        mock_post.assert_called_once_with('StorageCenter/ScLiveVolume',
                                          expected, True)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume_error(self,
                                      mock_find_sc,
                                      mock_find_qos,
                                      mock_post,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.side_effect = [{'instanceId': '101.1001'},
                                     {'instanceId': '102.1001'}]
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            False, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume_no_dest(self,
                                        mock_find_sc,
                                        mock_find_qos,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.return_value = {}
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            False, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume_no_qos(self,
                                       mock_find_sc,
                                       mock_find_qos,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.return_value = None
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            False, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_create_live_volume_no_secondary_qos(self,
                                                 mock_find_sc,
                                                 mock_find_qos,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        scvol = {'instanceId': '101.1',
                 'name': 'name'}
        remotessn = '102'
        active = True
        sync = False
        primaryqos = 'fast'
        secondaryqos = 'slow'
        mock_find_sc.return_value = 102
        mock_find_qos.side_effect = [{'instanceId': '101.1001'},
                                     None]
        ret = self.scapi.create_live_volume(scvol, remotessn, active, sync,
                                            False, primaryqos, secondaryqos)
        mock_find_sc.assert_called_once_with(102)
        mock_find_qos.assert_any_call(primaryqos)
        mock_find_qos.assert_any_call(secondaryqos, 102)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    def test_manage_replay(self,
                           mock_put,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        screplay = {'description': 'notguid',
                    'instanceId': 1}
        payload = {'description': 'guid',
                   'expireTime': 0}
        mock_put.return_value = self.RESPONSE_200
        ret = self.scapi.manage_replay(screplay, 'guid')
        self.assertTrue(ret)
        mock_put.assert_called_once_with('StorageCenter/ScReplay/1', payload,
                                         True)
        mock_put.return_value = self.RESPONSE_400
        ret = self.scapi.manage_replay(screplay, 'guid')
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    def test_unmanage_replay(self,
                             mock_put,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        screplay = {'description': 'guid',
                    'instanceId': 1}
        payload = {'expireTime': 1440}
        mock_put.return_value = self.RESPONSE_200
        ret = self.scapi.unmanage_replay(screplay)
        self.assertTrue(ret)
        mock_put.assert_called_once_with('StorageCenter/ScReplay/1', payload,
                                         True)
        mock_put.return_value = self.RESPONSE_400
        ret = self.scapi.unmanage_replay(screplay)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_replay_list')
    def test_find_common_replay(self,
                                mock_get_replay_list,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        dreplays = [{'globalIndex': '11111.113'},
                    {'globalIndex': '11111.112'},
                    {'globalIndex': '11111.111'}]
        sreplays = [{'globalIndex': '12345.112'},
                    {'globalIndex': '12345.111'},
                    {'globalIndex': '11111.112'},
                    {'globalIndex': '11111.111'}]
        xreplays = [{'globalIndex': '12345.112'},
                    {'globalIndex': '12345.111'}]
        mock_get_replay_list.side_effect = [dreplays, sreplays,
                                            dreplays, xreplays]
        ret = self.scapi.find_common_replay({'instanceId': '12345.1'},
                                            {'instanceId': '11111.1'})
        self.assertEqual({'globalIndex': '11111.112'}, ret)
        ret = self.scapi.find_common_replay(None, {'instanceId': '11111.1'})
        self.assertIsNone(ret)
        ret = self.scapi.find_common_replay({'instanceId': '12345.1'}, None)
        self.assertIsNone(ret)
        ret = self.scapi.find_common_replay({'instanceId': '12345.1'},
                                            {'instanceId': '11111.1'})
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test_start_replication(self,
                               mock_post,
                               mock_get_json,
                               mock_find_qos,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        svolume = {'name': 'guida', 'instanceId': '12345.101',
                   'scSerialNumber': 12345}
        dvolume = {'name': 'guidb', 'instanceId': '11111.101',
                   'scSerialNumber': 11111}
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = {'instanceId': '12345.201'}
        mock_find_qos.return_value = {'instanceId': '12345.1'}
        expected = {'QosNode': '12345.1',
                    'SourceVolume': '12345.101',
                    'StorageCenter': 12345,
                    'ReplicateActiveReplay': False,
                    'Type': 'Asynchronous',
                    'DestinationVolume': '11111.101',
                    'DestinationStorageCenter': 11111}
        ret = self.scapi.start_replication(svolume, dvolume, 'Asynchronous',
                                           'cinderqos', False)
        self.assertEqual(mock_get_json.return_value, ret)
        mock_post.assert_called_once_with('StorageCenter/ScReplication',
                                          expected, True)
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi.start_replication(svolume, dvolume, 'Asynchronous',
                                           'cinderqos', False)
        self.assertIsNone(ret)
        mock_post.return_value = self.RESPONSE_200
        mock_find_qos.return_value = None
        ret = self.scapi.start_replication(svolume, dvolume, 'Asynchronous',
                                           'cinderqos', False)
        self.assertIsNone(ret)
        mock_find_qos.return_value = {'instanceId': '12345.1'}
        ret = self.scapi.start_replication(None, dvolume, 'Asynchronous',
                                           'cinderqos', False)
        self.assertIsNone(ret)
        ret = self.scapi.start_replication(svolume, None, 'Asynchronous',
                                           'cinderqos', False)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_common_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'start_replication')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test_replicate_to_common(self,
                                 mock_post,
                                 mock_get_json,
                                 mock_start_replication,
                                 mock_create_replay,
                                 mock_find_common_replay,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        creplay = {'instanceId': '11111.201'}
        svolume = {'name': 'guida'}
        dvolume = {'name': 'guidb', 'volumeFolder': {'instanceId': '11111.1'}}
        vvolume = {'name': 'guidc'}
        mock_find_common_replay.return_value = creplay
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = vvolume
        mock_create_replay.return_value = {'instanceId': '12345.202'}
        mock_start_replication.return_value = {'instanceId': '12345.203'}
        # Simple common test.
        ret = self.scapi.replicate_to_common(svolume, dvolume, 'cinderqos')
        self.assertEqual(mock_start_replication.return_value, ret)
        mock_post.assert_called_once_with(
            'StorageCenter/ScReplay/11111.201/CreateView',
            {'Name': 'fback:guidb',
             'Notes': 'Created by Dell EMC Cinder Driver',
             'VolumeFolder': '11111.1'},
            True)
        mock_create_replay.assert_called_once_with(svolume, 'failback', 600)
        mock_start_replication.assert_called_once_with(svolume, vvolume,
                                                       'Asynchronous',
                                                       'cinderqos',
                                                       False)
        mock_create_replay.return_value = None
        # Unable to create a replay.
        ret = self.scapi.replicate_to_common(svolume, dvolume, 'cinderqos')
        self.assertIsNone(ret)
        mock_create_replay.return_value = {'instanceId': '12345.202'}
        mock_get_json.return_value = None
        # Create view volume fails.
        ret = self.scapi.replicate_to_common(svolume, dvolume, 'cinderqos')
        self.assertIsNone(ret)
        mock_get_json.return_value = vvolume
        mock_post.return_value = self.RESPONSE_400
        # Post call returns an error.
        ret = self.scapi.replicate_to_common(svolume, dvolume, 'cinderqos')
        self.assertIsNone(ret)
        mock_post.return_value = self.RESPONSE_200
        mock_find_common_replay.return_value = None
        # No common replay found.
        ret = self.scapi.replicate_to_common(svolume, dvolume, 'cinderqos')
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replication')
    @mock.patch.object(storagecenter_api.SCApi,
                       'start_replication')
    @mock.patch.object(storagecenter_api.SCApi,
                       'rename_volume')
    def test_flip_replication(self,
                              mock_rename_volume,
                              mock_start_replication,
                              mock_delete_replication,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        svolume = {'scSerialNumber': '12345.1'}
        dvolume = {'scSerialNumber': '11111.1'}
        name = 'guid'
        replicationtype = 'Synchronous'
        qosnode = 'cinderqos'
        activereplay = True
        mock_delete_replication.return_value = True
        mock_start_replication.return_value = {'instanceId': '11111.101'}
        mock_rename_volume.return_value = True
        # Good run.
        ret = self.scapi.flip_replication(svolume, dvolume, name,
                                          replicationtype, qosnode,
                                          activereplay)
        self.assertTrue(ret)
        mock_delete_replication.assert_called_once_with(svolume, '11111.1',
                                                        False)
        mock_start_replication.assert_called_once_with(dvolume, svolume,
                                                       replicationtype,
                                                       qosnode, activereplay)
        mock_rename_volume.assert_any_call(svolume, 'Cinder repl of guid')
        mock_rename_volume.assert_any_call(dvolume, 'guid')
        mock_rename_volume.return_value = False
        # Unable to rename volumes.
        ret = self.scapi.flip_replication(svolume, dvolume, name,
                                          replicationtype, qosnode,
                                          activereplay)
        self.assertFalse(ret)
        mock_rename_volume.return_value = True
        mock_start_replication.return_value = None
        # Start replication call fails.
        ret = self.scapi.flip_replication(svolume, dvolume, name,
                                          replicationtype, qosnode,
                                          activereplay)
        self.assertFalse(ret)
        mock_delete_replication.return_value = False
        mock_start_replication.return_value = {'instanceId': '11111.101'}
        # Delete old replication call fails.
        ret = self.scapi.flip_replication(svolume, dvolume, name,
                                          replicationtype, qosnode,
                                          activereplay)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    def test_replication_progress(self,
                                  mock_get,
                                  mock_get_json,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        mock_get.return_value = self.RESPONSE_200
        mock_get_json.return_value = {'synced': True,
                                      'amountRemaining': '0 Bytes'}
        # Good run
        retbool, retnum = self.scapi.replication_progress('11111.101')
        self.assertTrue(retbool)
        self.assertEqual(0.0, retnum)
        # SC replication ID is None.
        retbool, retnum = self.scapi.replication_progress(None)
        self.assertIsNone(retbool)
        self.assertIsNone(retnum)
        mock_get.return_value = self.RESPONSE_400
        # Get progress call fails.
        retbool, retnum = self.scapi.replication_progress('11111.101')
        self.assertIsNone(retbool)
        self.assertIsNone(retnum)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'delete')
    def test_delete_live_volume(self,
                                mock_delete,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        mock_delete.return_value = self.RESPONSE_200
        ret = self.scapi.delete_live_volume({'instanceId': '12345.101'},
                                            True)
        self.assertTrue(ret)
        mock_delete.return_value = self.RESPONSE_400
        ret = self.scapi.delete_live_volume({'instanceId': '12345.101'},
                                            True)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test_swap_roles_live_volume(self,
                                    mock_post,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        mock_post.return_value = self.RESPONSE_200
        lv = {'instanceId': '12345.0'}
        ret = self.scapi.swap_roles_live_volume(lv)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test_swap_roles_live_volume_fail(self,
                                         mock_post,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        mock_post.return_value = self.RESPONSE_400
        lv = {'instanceId': '12345.0'}
        ret = self.scapi.swap_roles_live_volume(lv)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_qos_profile(self,
                               mock_post,
                               mock_get_json,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'instanceId': '12345.0'}]
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'ScSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'Default'},
            {'filterType': 'Equals', 'attributeName': 'profileType',
             'attributeValue': 'VolumeQosProfile'}]}}
        ret = self.scapi._find_qos_profile('Default', False)
        self.assertEqual({'instanceId': '12345.0'}, ret)
        mock_post.assert_called_once_with('StorageCenter/ScQosProfile/GetList',
                                          expected_payload)

    def test__find_qos_no_qosprofile(self,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        ret = self.scapi._find_qos_profile('', False)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_qos_error(self,
                             mock_post,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi._find_qos_profile('Default', False)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_qos_profile_empty_list(self,
                                          mock_post,
                                          mock_get_json,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = []
        ret = self.scapi._find_qos_profile('Default', False)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_qos_profile_group(self,
                                     mock_post,
                                     mock_get_json,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'instanceId': '12345.0'}]
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'ScSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'Name',
             'attributeValue': 'Default'},
            {'filterType': 'Equals', 'attributeName': 'profileType',
             'attributeValue': 'GroupQosProfile'}]}}
        ret = self.scapi._find_qos_profile('Default', True)
        self.assertEqual({'instanceId': '12345.0'}, ret)
        mock_post.assert_called_once_with('StorageCenter/ScQosProfile/GetList',
                                          expected_payload)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_datareduction_profile(self,
                                         mock_post,
                                         mock_get_json,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = [{'instanceId': '12345.0'}]
        expected_payload = {'filter': {'filterType': 'AND', 'filters': [
            {'filterType': 'Equals', 'attributeName': 'ScSerialNumber',
             'attributeValue': 12345},
            {'filterType': 'Equals', 'attributeName': 'type',
             'attributeValue': 'Compression'}]}}
        ret = self.scapi._find_data_reduction_profile('Compression')
        self.assertEqual({'instanceId': '12345.0'}, ret)
        mock_post.assert_called_once_with(
            'StorageCenter/ScDataReductionProfile/GetList', expected_payload)

    def test__find_datareduction_profile_no_drprofile(self,
                                                      mock_close_connection,
                                                      mock_open_connection,
                                                      mock_init):
        ret = self.scapi._find_data_reduction_profile('')
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_datareduction_profile_error(self,
                                               mock_post,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        mock_post.return_value = self.RESPONSE_400
        ret = self.scapi._find_data_reduction_profile('Compression')
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post')
    def test__find_datareduction_profile_empty_list(self,
                                                    mock_post,
                                                    mock_get_json,
                                                    mock_close_connection,
                                                    mock_open_connection,
                                                    mock_init):
        mock_post.return_value = self.RESPONSE_200
        mock_get_json.return_value = []
        ret = self.scapi._find_data_reduction_profile('Compression')
        self.assertIsNone(ret)

    def test__check_add_profile_payload(self,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        payload = {}
        profile = {'instanceId': '12345.0'}
        self.scapi._check_add_profile_payload(payload, profile,
                                              'Profile1', 'GroupQosProfile')
        self.assertEqual({'GroupQosProfile': '12345.0'}, payload)

    def test__check_add_profile_payload_no_name(self,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        payload = {}
        profile = {'instanceId': '12345.0'}
        self.scapi._check_add_profile_payload(payload, profile,
                                              None, 'GroupQosProfile')
        self.assertEqual({}, payload)

    def test__check_add_profile_payload_no_profile(self,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        payload = {}
        profile = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi._check_add_profile_payload,
                          payload, profile, 'Profile1',
                          'VolumeQosProfile')

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile(
            self, mock_find_datareduction_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_datareduction_profile.return_value = {}
        mock_prefs.return_value = {
            'allowDataReductionSelection': True,
            'dataReductionProfile': {'name': 'Default',
                                     'instanceId': '12345.0'}}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        mock_put.return_value = self.RESPONSE_200
        expected = {'dataReductionProfile': '12345.0'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertTrue(res)
        mock_put.assert_called_once_with(
            'StorageCenter/ScVolumeConfiguration/12345.101', expected, True)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_error(
            self, mock_find_datareduction_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_datareduction_profile.return_value = {}
        mock_prefs.return_value = {
            'allowDataReductionSelection': True,
            'dataReductionProfile': {'name': 'Default',
                                     'instanceId': '12345.0'}}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        mock_put.return_value = self.RESPONSE_400
        expected = {'dataReductionProfile': '12345.0'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertFalse(res)
        mock_put.assert_called_once_with(
            'StorageCenter/ScVolumeConfiguration/12345.101', expected, True)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_not_found(
            self, mock_find_datareduction_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_datareduction_profile.return_value = None
        mock_prefs.return_value = {'allowDataReductionSelection': True}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_datareduction_profile(scvolume, 'Profile')
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_not_allowed(
            self, mock_find_datareduction_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_datareduction_profile.return_value = None
        mock_prefs.return_value = {'allowDataReductionSelection': False}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_prefs_not_found(
            self, mock_find_datareduction_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_datareduction_profile.return_value = None
        mock_prefs.return_value = None
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_default_not_found(
            self, mock_find_datareduction_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_datareduction_profile.return_value = None
        mock_prefs.return_value = {'allowDataReductionSelection': True}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_datareduction_profile_default(
            self, mock_find_datareduction_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_datareduction_profile.return_value = None
        mock_prefs.return_value = {
            'allowDataReductionSelection': True,
            'dataReductionProfile': {'name': 'Default',
                                     'instanceId': '12345.0'}}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_datareduction_profile(scvolume, None)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile(
            self, mock_find_qos_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_qos_profile.return_value = {}
        mock_prefs.return_value = {
            'allowQosProfileSelection': True,
            'volumeQosProfile': {'name': 'Default',
                                 'instanceId': '12345.0'}}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        mock_put.return_value = self.RESPONSE_200
        expected = {'volumeQosProfile': '12345.0'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertTrue(res)
        mock_put.assert_called_once_with(
            'StorageCenter/ScVolumeConfiguration/12345.101', expected, True)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_data_reduction_profile')
    def test_update_qos_profile_error(
            self, mock_find_qos_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_qos_profile.return_value = {}
        mock_prefs.return_value = {
            'allowQosProfileSelection': True,
            'volumeQosProfile': {'name': 'Default',
                                 'instanceId': '12345.0'}}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        mock_put.return_value = self.RESPONSE_400
        expected = {'volumeQosProfile': '12345.0'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertFalse(res)
        mock_put.assert_called_once_with(
            'StorageCenter/ScVolumeConfiguration/12345.101', expected, True)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile_not_found(
            self, mock_find_qos_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_qos_profile.return_value = None
        mock_prefs.return_value = {'allowQosProfileSelection': True}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_qos_profile(scvolume, 'Profile')
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile_not_allowed(
            self, mock_find_qos_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_qos_profile.return_value = None
        mock_prefs.return_value = {'allowQosProfileSelection': False}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile_prefs_not_found(
            self, mock_find_qos_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_qos_profile.return_value = None
        mock_prefs.return_value = None
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile_default_not_found(
            self, mock_find_qos_profile, mock_prefs,
            mock_close_connection, mock_open_connection,
            mock_init):
        mock_find_qos_profile.return_value = None
        mock_prefs.return_value = {'allowQosProfileSelection': True}
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_user_preferences')
    @mock.patch.object(storagecenter_api.HttpClient,
                       'put')
    @mock.patch.object(storagecenter_api.SCApi,
                       '_find_qos_profile')
    def test_update_qos_profile_default(
            self, mock_find_qos_profile, mock_put, mock_prefs,
            mock_close_connection, mock_open_connection, mock_init):
        # Test we get and set our default
        mock_find_qos_profile.return_value = None
        mock_prefs.return_value = {
            'allowQosProfileSelection': True,
            'volumeQosProfile': {'name': 'Default',
                                 'instanceId': '12345.0'}}
        mock_put.return_value = self.RESPONSE_200
        scvolume = {'name': fake.VOLUME_ID, 'instanceId': '12345.101'}
        res = self.scapi.update_qos_profile(scvolume, None)
        self.assertTrue(res)


class DellSCSanAPIConnectionTestCase(test.TestCase):

    """DellSCSanAPIConnectionTestCase

    Class to test the Storage Center API connection using Mock.
    """

    # Create a Response object that indicates OK
    response_ok = models.Response()
    response_ok.status_code = 200
    response_ok.reason = u'ok'
    RESPONSE_200 = response_ok

    # Create a Response object with no content
    response_nc = models.Response()
    response_nc.status_code = 204
    response_nc.reason = u'duplicate'
    RESPONSE_204 = response_nc

    # Create a Response object is a pure error.
    response_bad = models.Response()
    response_bad.status_code = 400
    response_bad._content = ''
    response_bad._content_consumed = True
    response_bad.reason = u'bad request'
    response_bad._content = ''
    response_bad._content_consumed = True
    RESPONSE_400 = response_bad

    APIDICT = {u'instanceId': u'0',
               u'hostName': u'192.168.0.200',
               u'userId': 434226,
               u'connectionKey': u'',
               u'minApiVersion': u'0.1',
               u'webServicesPort': 3033,
               u'locale': u'en_US',
               u'objectType': u'ApiConnection',
               u'secureString': u'',
               u'applicationVersion': u'2.0.1',
               u'source': u'REST',
               u'commandLine': False,
               u'application': u'Cinder REST Driver',
               u'sessionKey': 1436460614863,
               u'provider': u'EnterpriseManager',
               u'instanceName': u'ApiConnection',
               u'connected': True,
               u'userName': u'Admin',
               u'useHttps': False,
               u'providerVersion': u'15.3.1.186',
               u'apiVersion': u'2.2',
               u'apiBuild': 199}

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
        self.configuration.target_ip_address = '192.168.1.1'
        self.configuration.target_port = 3260
        self._context = context.get_admin_context()
        self.asynctimeout = 15
        self.synctimeout = 30
        self.apiversion = '2.0'

        # Set up the SCApi
        self.scapi = storagecenter_api.SCApi(
            self.configuration.san_ip,
            self.configuration.dell_sc_api_port,
            self.configuration.san_login,
            self.configuration.san_password,
            self.configuration.dell_sc_verify_cert,
            self.asynctimeout,
            self.synctimeout,
            self.apiversion)

        # Set up the scapi configuration vars
        self.scapi.ssn = self.configuration.dell_sc_ssn
        self.scapi.sfname = self.configuration.dell_sc_server_folder
        self.scapi.vfname = self.configuration.dell_sc_volume_folder

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=APIDICT)
    def test_open_connection(self,
                             mock_get_json,
                             mock_post):
        self.scapi.open_connection()
        self.assertTrue(mock_post.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_check_version_fail',
                       return_value=RESPONSE_400)
    def test_open_connection_failure(self,
                                     mock_check_version_fail,
                                     mock_post):

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.scapi.open_connection)
        self.assertTrue(mock_check_version_fail.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       '_check_version_fail',
                       return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.SCApi,
                       '_get_json',
                       return_value=APIDICT)
    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_400)
    def test_open_connection_sc(self,
                                mock_post,
                                mock_get_json,
                                mock_check_version_fail):
        self.scapi.open_connection()
        self.assertTrue(mock_check_version_fail.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_204)
    def test_close_connection(self,
                              mock_post):
        self.scapi.close_connection()
        self.assertTrue(mock_post.called)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'post',
                       return_value=RESPONSE_200)
    def test_close_connection_failure(self,
                                      mock_post):
        self.scapi.close_connection()
        self.assertTrue(mock_post.called)


class DellHttpClientTestCase(test.TestCase):

    """DellSCSanAPIConnectionTestCase

    Class to test the Storage Center API connection using Mock.
    """

    ASYNCTASK = {"state": "Running",
                 "methodName": "GetScUserPreferencesDefaults",
                 "error": "",
                 "started": True,
                 "userName": "",
                 "localizedError": "",
                 "returnValue": "https://localhost:3033/api/rest/"
                                "ApiConnection/AsyncTask/1418394170395",
                 "storageCenter": 0,
                 "errorState": "None",
                 "successful": False,
                 "stepMessage": "Running Method [Object: ScUserPreferences] "
                                "[Method: GetScUserPreferencesDefaults]",
                 "localizedStepMessage": "",
                 "warningList": [],
                 "totalSteps": 2,
                 "timeFinished": "1969-12-31T18:00:00-06:00",
                 "timeStarted": "2015-01-07T14:07:10-06:00",
                 "currentStep": 1,
                 "objectTypeName": "ScUserPreferences",
                 "objectType": "AsyncTask",
                 "instanceName": "1418394170395",
                 "instanceId": "1418394170395"}

    # Create a Response object that indicates OK
    response_ok = models.Response()
    response_ok.status_code = 200
    response_ok.reason = u'ok'
    response_ok._content = ''
    response_ok._content_consumed = True
    RESPONSE_200 = response_ok

    # Create a Response object with no content
    response_nc = models.Response()
    response_nc.status_code = 204
    response_nc.reason = u'duplicate'
    response_nc._content = ''
    response_nc._content_consumed = True
    RESPONSE_204 = response_nc

    # Create a Response object is a pure error.
    response_bad = models.Response()
    response_bad.status_code = 400
    response_bad.reason = u'bad request'
    response_bad._content = ''
    response_bad._content_consumed = True
    RESPONSE_400 = response_bad

    def setUp(self):
        super(DellHttpClientTestCase, self).setUp()
        self.host = 'localhost'
        self.port = '3033'
        self.user = 'johnnyuser'
        self.password = 'password'
        self.verify = False
        self.asynctimeout = 15
        self.synctimeout = 30
        self.apiversion = '3.1'
        self.httpclient = storagecenter_api.HttpClient(
            self.host, self.port, self.user, self.password, self.verify,
            self.asynctimeout, self.synctimeout, self.apiversion)

    def test_get_async_url(self):
        url = self.httpclient._get_async_url(self.ASYNCTASK)
        self.assertEqual('api/rest/ApiConnection/AsyncTask/1418394170395', url)

    def test_get_async_url_no_id_on_url(self):
        badTask = self.ASYNCTASK.copy()
        badTask['returnValue'] = ('https://localhost:3033/api/rest/'
                                  'ApiConnection/AsyncTask/')
        url = self.httpclient._get_async_url(badTask)
        self.assertEqual('api/rest/ApiConnection/AsyncTask/1418394170395', url)

    def test_get_async_url_none(self):
        self.assertRaises(AttributeError, self.httpclient._get_async_url, None)

    def test_get_async_url_no_id(self):
        badTask = self.ASYNCTASK.copy()
        badTask['returnValue'] = ('https://localhost:3033/api/rest/'
                                  'ApiConnection/AsyncTask/')
        badTask['instanceId'] = ''
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.httpclient._get_async_url, badTask)

    def test_get_async_url_no_returnvalue(self):
        badTask = self.ASYNCTASK.copy()
        badTask['returnValue'] = None
        url = self.httpclient._get_async_url(badTask)
        self.assertEqual('api/rest/ApiConnection/AsyncTask/1418394170395', url)

    def test_get_async_url_no_blank_returnvalue(self):
        badTask = self.ASYNCTASK.copy()
        badTask['returnValue'] = ''
        url = self.httpclient._get_async_url(badTask)
        self.assertEqual('api/rest/ApiConnection/AsyncTask/1418394170395', url)

    def test_get_async_url_xml_returnvalue(self):
        badTask = self.ASYNCTASK.copy()
        badTask['returnValue'] = ('<compapi><ApiMethodReturn><Error></Error>'
                                  '<ErrorCode>1</ErrorCode>'
                                  '<ErrorDetail></ErrorDetail>'
                                  '<Locale>1</Locale>'
                                  '<LocalizedError></LocalizedError>'
                                  '<ObjectType>ApiMethodReturn</ObjectType>'
                                  '<ReturnObjectEncode>1</ReturnObjectEncode>'
                                  '<Successful>True</Successful>'
                                  '</ApiMethodReturn>'
                                  '<ReturnBool>false</ReturnBool></compapi>')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.httpclient._get_async_url, badTask)

    def test_rest_ret(self):
        rest_response = self.RESPONSE_200
        response = self.httpclient._rest_ret(rest_response, False)
        self.assertEqual(self.RESPONSE_200, response)

    @mock.patch.object(storagecenter_api.HttpClient,
                       '_wait_for_async_complete',
                       return_value=RESPONSE_200)
    def test_rest_ret_async(self,
                            mock_wait_for_async_complete):
        mock_rest_response = mock.MagicMock()
        mock_rest_response.status_code = 202
        response = self.httpclient._rest_ret(mock_rest_response, True)
        self.assertEqual(self.RESPONSE_200, response)
        self.assertTrue(mock_wait_for_async_complete.called)

    def test_rest_ret_async_error(self):
        mock_rest_response = mock.MagicMock()
        mock_rest_response.status_code = 400
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.httpclient._rest_ret, mock_rest_response, True)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_wait_for_async_complete(self,
                                     mock_get):
        ret = self.httpclient._wait_for_async_complete(self.ASYNCTASK)
        self.assertEqual(self.RESPONSE_200, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       '_get_async_url',
                       return_value=None)
    def test_wait_for_async_complete_bad_url(self,
                                             mock_get_async_url):
        ret = self.httpclient._wait_for_async_complete(self.ASYNCTASK)
        self.assertIsNone(ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_400)
    def test_wait_for_async_complete_bad_result(self,
                                                mock_get):
        ret = self.httpclient._wait_for_async_complete(self.ASYNCTASK)
        self.assertEqual(self.RESPONSE_400, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get',
                       return_value=RESPONSE_200)
    def test_wait_for_async_complete_loop(self,
                                          mock_get):
        mock_response = mock.MagicMock()
        mock_response.content = mock.MagicMock()
        mock_response.json = mock.MagicMock()
        mock_response.json.side_effect = [self.ASYNCTASK,
                                          {'objectType': 'ScVol'}]
        ret = self.httpclient._wait_for_async_complete(self.ASYNCTASK)
        self.assertEqual(self.RESPONSE_200, ret)

    @mock.patch.object(storagecenter_api.HttpClient,
                       'get')
    def test_wait_for_async_complete_get_raises(self,
                                                mock_get):
        mock_get.side_effect = (exception.DellDriverRetryableException())
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.httpclient._wait_for_async_complete,
                          self.ASYNCTASK)

    @mock.patch.object(requests.Session,
                       'get',
                       return_value=RESPONSE_200)
    def test_get(self,
                 mock_get):
        ret = self.httpclient.get('url')
        self.assertEqual(self.RESPONSE_200, ret)
        expected_headers = self.httpclient.header.copy()
        mock_get.assert_called_once_with('https://localhost:3033/api/rest/url',
                                         headers=expected_headers,
                                         timeout=30,
                                         verify=False)

    @mock.patch.object(requests.Session, 'post', return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.HttpClient, '_rest_ret')
    def test_post(self, mock_rest_ret, mock_post):
        payload = {'payload': 'payload'}
        self.httpclient.post('url', payload, True)
        expected_headers = self.httpclient.header.copy()
        expected_headers['async'] = 'True'
        mock_post.assert_called_once_with(
            'https://localhost:3033/api/rest/url',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=expected_headers,
            timeout=15,
            verify=False)

    @mock.patch.object(requests.Session, 'post', return_value=RESPONSE_200)
    @mock.patch.object(storagecenter_api.HttpClient, '_rest_ret')
    def test_post_sync(self, mock_rest_ret, mock_post):
        payload = {'payload': 'payload'}
        self.httpclient.post('url', payload, False)
        expected_headers = self.httpclient.header.copy()
        mock_post.assert_called_once_with(
            'https://localhost:3033/api/rest/url',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=expected_headers,
            timeout=30,
            verify=False)


class DellStorageCenterApiHelperTestCase(test.TestCase):

    """DellStorageCenterApiHelper test case

    Class to test the Storage Center API helper using Mock.
    """

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection(self,
                              mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(12345, ret.primaryssn)
        self.assertEqual(12345, ret.ssn)
        self.assertEqual('FibreChannel', ret.protocol)
        mock_open_connection.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_excluded1(self,
                                        mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        config.excluded_domain_ip = ['192.168.0.1']
        config.excluded_domain_ips = ['192.168.0.2', '192.168.0.3']
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(set(ret.excluded_domain_ips), set(['192.168.0.2',
                         '192.168.0.3', '192.168.0.1']))
        self.assertEqual(12345, ret.primaryssn)
        self.assertEqual(12345, ret.ssn)
        self.assertEqual('FibreChannel', ret.protocol)
        mock_open_connection.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_excluded2(self,
                                        mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        config.excluded_domain_ip = None
        config.excluded_domain_ips = ['192.168.0.2', '192.168.0.3']
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(set(ret.excluded_domain_ips), set(['192.168.0.2',
                         '192.168.0.3']))

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_excluded3(self,
                                        mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        config.excluded_domain_ip = ['192.168.0.1']
        config.excluded_domain_ips = []
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(ret.excluded_domain_ips, ['192.168.0.1'])

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_excluded4(self,
                                        mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        config.excluded_domain_ip = None
        config.excluded_domain_ips = []
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(ret.excluded_domain_ips, [])

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_excluded5(self,
                                        mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        config.excluded_domain_ip = ['192.168.0.1']
        config.excluded_domain_ips = ['192.168.0.1', '192.168.0.2']
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        ret = helper._setup_connection()
        self.assertEqual(set(ret.excluded_domain_ips), set(['192.168.0.2',
                         '192.168.0.1']))
        self.assertEqual(12345, ret.primaryssn)
        self.assertEqual(12345, ret.ssn)
        self.assertEqual('FibreChannel', ret.protocol)
        mock_open_connection.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_iscsi(self,
                                    mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        helper = storagecenter_api.SCApiHelper(config, None, 'iSCSI')
        ret = helper._setup_connection()
        self.assertEqual(12345, ret.primaryssn)
        self.assertEqual(12345, ret.ssn)
        self.assertEqual('Iscsi', ret.protocol)
        mock_open_connection.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       'open_connection')
    def test_setup_connection_failover(self,
                                       mock_open_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.dell_sc_volume_folder = 'a'
        config.dell_sc_server_folder = 'a'
        config.dell_sc_verify_cert = False
        config.san_port = 3033
        helper = storagecenter_api.SCApiHelper(config, '67890', 'iSCSI')
        ret = helper._setup_connection()
        self.assertEqual(12345, ret.primaryssn)
        self.assertEqual(67890, ret.ssn)
        self.assertEqual('Iscsi', ret.protocol)
        mock_open_connection.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApiHelper,
                       '_setup_connection')
    def test_open_connection(self,
                             mock_setup_connection):
        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.san_port = 3033
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        mock_connection = mock.MagicMock()
        mock_connection.apiversion = '3.1'
        mock_setup_connection.return_value = mock_connection
        ret = helper.open_connection()
        self.assertEqual('3.1', ret.apiversion)
        self.assertEqual('192.168.0.101', helper.san_ip)
        self.assertEqual('username', helper.san_login)
        self.assertEqual('password', helper.san_password)

    @mock.patch.object(storagecenter_api.SCApiHelper,
                       '_setup_connection')
    def test_open_connection_fail_no_secondary(self,
                                               mock_setup_connection):

        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.san_port = 3033
        config.secondary_san_ip = ''
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        mock_setup_connection.side_effect = (
            exception.VolumeBackendAPIException('abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          helper.open_connection)
        mock_setup_connection.assert_called_once_with()
        self.assertEqual('192.168.0.101', helper.san_ip)
        self.assertEqual('username', helper.san_login)
        self.assertEqual('password', helper.san_password)

    @mock.patch.object(storagecenter_api.SCApiHelper,
                       '_setup_connection')
    def test_open_connection_secondary(self,
                                       mock_setup_connection):

        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.san_port = 3033
        config.secondary_san_ip = '192.168.0.102'
        config.secondary_san_login = 'username2'
        config.secondary_san_password = 'password2'
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        mock_connection = mock.MagicMock()
        mock_connection.apiversion = '3.1'
        mock_setup_connection.side_effect = [
            (exception.VolumeBackendAPIException('abc')), mock_connection]
        ret = helper.open_connection()
        self.assertEqual('3.1', ret.apiversion)
        self.assertEqual(2, mock_setup_connection.call_count)
        self.assertEqual('192.168.0.102', helper.san_ip)
        self.assertEqual('username2', helper.san_login)
        self.assertEqual('password2', helper.san_password)

    @mock.patch.object(storagecenter_api.SCApiHelper,
                       '_setup_connection')
    def test_open_connection_fail_partial_secondary_config(
            self, mock_setup_connection):

        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.san_port = 3033
        config.secondary_san_ip = '192.168.0.102'
        config.secondary_san_login = 'username2'
        config.secondary_san_password = ''
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        mock_setup_connection.side_effect = (
            exception.VolumeBackendAPIException('abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          helper.open_connection)
        mock_setup_connection.assert_called_once_with()
        self.assertEqual('192.168.0.101', helper.san_ip)
        self.assertEqual('username', helper.san_login)
        self.assertEqual('password', helper.san_password)

    @mock.patch.object(storagecenter_api.SCApiHelper,
                       '_setup_connection')
    def test_open_connection_to_secondary_and_back(self,
                                                   mock_setup_connection):

        config = mock.MagicMock()
        config.dell_sc_ssn = 12345
        config.san_ip = '192.168.0.101'
        config.san_login = 'username'
        config.san_password = 'password'
        config.san_port = 3033
        config.secondary_san_ip = '192.168.0.102'
        config.secondary_san_login = 'username2'
        config.secondary_san_password = 'password2'
        helper = storagecenter_api.SCApiHelper(config, None, 'FC')
        mock_connection = mock.MagicMock()
        mock_connection.apiversion = '3.1'
        mock_setup_connection.side_effect = [
            (exception.VolumeBackendAPIException('abc')), mock_connection,
            (exception.VolumeBackendAPIException('abc')), mock_connection]
        helper.open_connection()
        self.assertEqual('192.168.0.102', helper.san_ip)
        self.assertEqual('username2', helper.san_login)
        self.assertEqual('password2', helper.san_password)
        self.assertEqual(2, mock_setup_connection.call_count)
        helper.open_connection()
        self.assertEqual('192.168.0.101', helper.san_ip)
        self.assertEqual('username', helper.san_login)
        self.assertEqual('password', helper.san_password)
