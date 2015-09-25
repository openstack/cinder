# Copyright (c) 2014 NetApp, Inc.
# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
# Copyright (c) 2015 Rushil Chugh.  All Rights Reserved.
# Copyright (c) 2015 Navneet Singh.  All Rights Reserved.
# Copyright (c) 2015 Michael Price.  All Rights Reserved.
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
"""Tests for NetApp e-series iscsi volume driver."""

import copy
import ddt
import json
import re
import socket

import mock
import requests

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import common
from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp.eseries import library
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import options
import cinder.volume.drivers.netapp.utils as na_utils


def create_configuration():
    configuration = conf.Configuration(None)
    configuration.append_config_values(options.netapp_basicauth_opts)
    configuration.append_config_values(options.netapp_eseries_opts)
    configuration.append_config_values(options.netapp_san_opts)
    return configuration


class FakeEseriesResponse(object):
    """Fake response to requests."""

    def __init__(self, code=None, text=None):
        self.status_code = code
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeEseriesServerHandler(object):
    """HTTP handler that fakes enough stuff to allow the driver to run."""

    def do_GET(self, path, params, data, headers):
        """Respond to a GET request."""

        response = FakeEseriesResponse()
        if "/devmgr/vn" not in path:
            response.status_code = 404

        (__, ___, path) = path.partition("/devmgr/vn")
        if re.match("^/storage-systems/[0-9a-zA-Z]+/volumes$", path):
            response.status_code = 200
            response.text = """[{"extremeProtection": false,
                    "pitBaseVolume": false,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "2126008832", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023C73400000AAA52D11677",
                    "listOfMappings": [], "sectorOffset": "6",
                    "id": "0200000060080E500023C73400000AAA52D11677",
                    "wwn": "60080E500023C73400000AAA52D11677",
                    "capacity": "2126008832", "mgmtClientAttribute": 0,
                    "label": "repos_0006", "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000002",
                    "currentManager": "070000000000000000000002",
                    "applicationTagOwned": true, "status": "optimal",
                    "segmentSize": 131072, "volumeUse":
                    "freeRepositoryVolume", "action": "none",
                    "name": "repos_0006", "worldWideName":
                    "60080E500023C73400000AAA52D11677", "currentControllerId"
                    : "070000000000000000000002",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType": "type0Protection"}
                    ,
                    {"extremeProtection": false, "pitBaseVolume": true,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "2147483648", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023BB3400001FC352D14CB2",
                    "listOfMappings": [], "sectorOffset": "15",
                    "id": "0200000060080E500023BB3400001FC352D14CB2",
                    "wwn": "60080E500023BB3400001FC352D14CB2",
                    "capacity": "2147483648", "mgmtClientAttribute": 0,
                    "label": "bdm-vc-test-1", "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000001",
                    "currentManager": "070000000000000000000001",
                    "applicationTagOwned": false, "status": "optimal",
                    "segmentSize": 131072, "volumeUse": "standardVolume",
                    "action": "none", "preferredManager":
                    "070000000000000000000001", "volumeHandle": 15,
                    "offline": false, "preReadRedundancyCheckEnabled": false,
                    "dssPreallocEnabled": false, "name": "bdm-vc-test-1",
                    "worldWideName": "60080E500023BB3400001FC352D14CB2",
                    "currentControllerId": "070000000000000000000001",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType":
                    "type1Protection"},
                    {"extremeProtection": false, "pitBaseVolume": true,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "1073741824", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "listOfMappings": [{
                    "lunMappingRef":"8800000000000000000000000000000000000000",
                    "lun": 0,
                    "ssid": 16384,
                    "perms": 15,
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "type": "all",
                    "mapRef": "8400000060080E500023C73400300381515BFBA3"
                    }], "sectorOffset": "15",
                    "id": "0200000060080E500023BB34000003FB515C2293",
                    "wwn": "60080E500023BB3400001FC352D14CB2",
                    "capacity": "2147483648", "mgmtClientAttribute": 0,
                    "label": "CFDXJ67BLJH25DXCZFZD4NSF54",
                    "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000001",
                    "currentManager": "070000000000000000000001",
                    "applicationTagOwned": false, "status": "optimal",
                    "segmentSize": 131072, "volumeUse": "standardVolume",
                    "action": "none", "preferredManager":
                    "070000000000000000000001", "volumeHandle": 15,
                    "offline": false, "preReadRedundancyCheckEnabled": false,
                    "dssPreallocEnabled": false, "name": "bdm-vc-test-1",
                    "worldWideName": "60080E500023BB3400001FC352D14CB2",
                    "currentControllerId": "070000000000000000000001",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType":
                    "type1Protection"}]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volumes/[0-9A-Za-z]+$",
                      path):
            response.status_code = 200
            response.text = """{"extremeProtection": false,
                    "pitBaseVolume": true,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "2147483648", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023BB3400001FC352D14CB2",
                    "listOfMappings": [], "sectorOffset": "15",
                    "id": "0200000060080E500023BB3400001FC352D14CB2",
                    "wwn": "60080E500023BB3400001FC352D14CB2",
                    "capacity": "2147483648", "mgmtClientAttribute": 0,
                    "label": "bdm-vc-test-1", "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000001",
                    "currentManager": "070000000000000000000001",
                    "applicationTagOwned": false, "status": "optimal",
                    "segmentSize": 131072, "volumeUse": "standardVolume",
                    "action": "none", "preferredManager":
                    "070000000000000000000001", "volumeHandle": 15,
                    "offline": false, "preReadRedundancyCheckEnabled": false,
                    "dssPreallocEnabled": false, "name": "bdm-vc-test-1",
                    "worldWideName": "60080E500023BB3400001FC352D14CB2",
                    "currentControllerId": "070000000000000000000001",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType":
                    "type1Protection"}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/hardware-inventory$",
                      path):
            response.status_code = 200
            response.text = """
                   {"iscsiPorts": [{"controllerId":
                   "070000000000000000000002", "ipv4Enabled": true,
                   "ipv4Data": {"ipv4Address":
                   "0.0.0.0", "ipv4AddressConfigMethod": "configStatic",
                   "ipv4VlanId": {"isEnabled": false, "value": 0},
                   "ipv4AddressData": {"ipv4Address": "172.20.123.66",
                   "ipv4SubnetMask": "255.255.255.0", "configState":
                   "configured", "ipv4GatewayAddress": "0.0.0.0"}},
                   "tcpListenPort": 3260,
                   "interfaceRef": "2202040000000000000000000000000000000000"
                   ,"iqn":
                   "iqn.1992-01.com.lsi:2365.60080e500023c73400000000515af323"
                   }]}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/hosts$", path):
            response.status_code = 200
            response.text = """[{"isSAControlled": false,
            "confirmLUNMappingCreation"
            : false, "label": "stlrx300s7-55", "isLargeBlockFormatHost":
            false, "clusterRef": "8500000060080E500023C7340036035F515B78FC",
            "protectionInformationCapableAccessMethod": false,
            "ports": [], "hostRef":
            "8400000060080E500023C73400300381515BFBA3", "hostTypeIndex": 6,
            "hostSidePorts": [{"label": "NewStore", "type": "iscsi",
            "address": "iqn.1998-01.com.vmware:localhost-28a58148"}]}]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/host-types$", path):
            response.status_code = 200
            response.text = """[{
                      "id" : "4",
                      "code" : "AIX",
                      "name" : "AIX",
                      "index" : 4
                    }, {
                      "id" : "5",
                      "code" : "IRX",
                      "name" : "IRX",
                      "index" : 5
                    }, {
                      "id" : "6",
                      "code" : "LnxALUA",
                      "name" : "LnxALUA",
                      "index" : 6
                    }]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-groups$", path):
            response.status_code = 200
            response.text = """[]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-images$", path):
            response.status_code = 200
            response.text = """[]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/storage-pools$", path):
            response.status_code = 200
            response.text = """[ {"protectionInformationCapabilities":
            {"protectionInformationCapable": true, "protectionType":
            "type2Protection"}, "raidLevel": "raidDiskPool", "reserved1":
            "000000000000000000000000", "reserved2": "", "isInaccessible":
            false, "label": "DDP", "state": "complete", "usage":
            "standard", "offline": false, "drawerLossProtection": false,
            "trayLossProtection": false, "securityType": "capable",
            "volumeGroupRef": "0400000060080E500023BB3400001F9F52CECC3F",
            "driveBlockFormat": "__UNDEFINED", "usedSpace": "81604378624",
            "volumeGroupData": {"type": "diskPool", "diskPoolData":
            {"criticalReconstructPriority": "highest",
            "poolUtilizationState": "utilizationOptimal",
            "reconstructionReservedDriveCountCurrent": 3, "allocGranularity":
            "4294967296", "degradedReconstructPriority": "high",
            "backgroundOperationPriority": "low",
            "reconstructionReservedAmt": "897111293952", "unusableCapacity":
            "0", "reconstructionReservedDriveCount": 1,
            "poolUtilizationWarningThreshold": 50,
            "poolUtilizationCriticalThreshold": 85}}, "spindleSpeed": 10000,
            "worldWideName": "60080E500023BB3400001F9F52CECC3F",
            "spindleSpeedMatch": true, "totalRaidedSpace": "17273253317836",
            "sequenceNum": 2, "protectionInformationCapable": false}]"""
        elif re.match("^/storage-systems$", path):
            response.status_code = 200
            response.text = """[ {"freePoolSpace": 11142431623168,
                "driveCount": 24,
                "hostSparesUsed": 0, "id":
                "1fa6efb5-f07b-4de4-9f0e-52e5f7ff5d1b",
                "hotSpareSizeAsString": "0", "wwn":
                "60080E500023C73400000000515AF323", "parameters":
                {"minVolSize": 1048576, "maxSnapshotsPerBase": 16,
                "maxDrives": 192, "maxVolumes": 512, "maxVolumesPerGroup":
                256, "maxMirrors": 0, "maxMappingsPerVolume": 1,
                "maxMappableLuns": 256, "maxVolCopys": 511,
                "maxSnapshots":
                256}, "hotSpareCount": 0, "hostSpareCountInStandby": 0,
                "status": "needsattn", "trayCount": 1,
                "usedPoolSpaceAsString": "5313000380416",
                "ip2": "10.63.165.216", "ip1": "10.63.165.215",
                "freePoolSpaceAsString": "11142431623168",
                "types": "SAS",
                "name": "stle2600-7_8", "hotSpareSize": 0,
                "usedPoolSpace":
                5313000380416, "driveTypes": ["sas"],
                "unconfiguredSpaceByDriveType": {},
                "unconfiguredSpaceAsStrings": "0", "model": "2650",
                "unconfiguredSpace": 0}]"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+$", path):
            response.status_code = 200
            response.text = """{"freePoolSpace": 11142431623168,
                "driveCount": 24,
                "hostSparesUsed": 0, "id":
                "1fa6efb5-f07b-4de4-9f0e-52e5f7ff5d1b",
                "hotSpareSizeAsString": "0", "wwn":
                "60080E500023C73400000000515AF323", "parameters":
                {"minVolSize": 1048576, "maxSnapshotsPerBase": 16,
                "maxDrives": 192, "maxVolumes": 512, "maxVolumesPerGroup":
                256, "maxMirrors": 0, "maxMappingsPerVolume": 1,
                "maxMappableLuns": 256, "maxVolCopys": 511,
                "maxSnapshots":
                256}, "hotSpareCount": 0, "hostSpareCountInStandby": 0,
                "status": "needsattn", "trayCount": 1,
                "usedPoolSpaceAsString": "5313000380416",
                "ip2": "10.63.165.216", "ip1": "10.63.165.215",
                "freePoolSpaceAsString": "11142431623168",
                "types": "SAS",
                "name": "stle2600-7_8", "hotSpareSize": 0,
                "usedPoolSpace":
                5313000380416, "driveTypes": ["sas"],
                "unconfiguredSpaceByDriveType": {},
                "unconfiguredSpaceAsStrings": "0", "model": "2650",
                "unconfiguredSpace": 0}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-copy-jobs"
                      "/[0-9a-zA-Z]+$", path):
            response.status_code = 200
            response.text = """{"status": "complete",
            "cloneCopy": true, "pgRef":
            "3300000060080E500023C73400000ACA52D29454", "volcopyHandle":49160
            , "idleTargetWriteProt": true, "copyPriority": "priority2",
            "volcopyRef": "1800000060080E500023C73400000ACF52D29466",
            "worldWideName": "60080E500023C73400000ACF52D29466",
            "copyCompleteTime": "0", "sourceVolume":
            "3500000060080E500023C73400000ACE52D29462", "currentManager":
            "070000000000000000000002", "copyStartTime": "1389551671",
            "reserved1": "00000000", "targetVolume":
            "0200000060080E500023C73400000A8C52D10675"}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-mappings$", path):
            response.status_code = 200
            response.text = """[
                  {
                    "lunMappingRef":"8800000000000000000000000000000000000000",
                    "lun": 0,
                    "ssid": 16384,
                    "perms": 15,
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "type": "all",
                    "mapRef": "8400000060080E500023C73400300381515BFBA3"
                    }]
                  """
        else:
            # Unknown API
            response.status_code = 500

        return response

    def do_POST(self, path, params, data, headers):
        """Respond to a POST request."""

        response = FakeEseriesResponse()
        if "/devmgr/vn" not in path:
            response.status_code = 404
        data = json.loads(data) if data else None
        (__, ___, path) = path.partition("/devmgr/vn")
        if re.match("^/storage-systems/[0-9a-zA-Z]+/volumes$", path):
            response.status_code = 200
            text_json = json.loads("""
                    {"extremeProtection": false, "pitBaseVolume": true,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "1073741824", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "listOfMappings": [{
                    "lunMappingRef":"8800000000000000000000000000000000000000",
                    "lun": 0,
                    "ssid": 16384,
                    "perms": 15,
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "type": "all",
                    "mapRef": "8400000060080E500023C73400300381515BFBA3"
                    }], "sectorOffset": "15",
                    "id": "0200000060080E500023BB34000003FB515C2293",
                    "wwn": "60080E500023BB3400001FC352D14CB2",
                    "capacity": "2147483648", "mgmtClientAttribute": 0,
                    "label": "CFDXJ67BLJH25DXCZFZD4NSF54",
                    "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000001",
                    "currentManager": "070000000000000000000001",
                    "applicationTagOwned": false, "status": "optimal",
                    "segmentSize": 131072, "volumeUse": "standardVolume",
                    "action": "none", "preferredManager":
                    "070000000000000000000001", "volumeHandle": 15,
                    "offline": false, "preReadRedundancyCheckEnabled": false,
                    "dssPreallocEnabled": false, "name": "bdm-vc-test-1",
                    "worldWideName": "60080E500023BB3400001FC352D14CB2",
                    "currentControllerId": "070000000000000000000001",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType":
                    "type1Protection"}""")
            text_json['label'] = data['name']
            text_json['name'] = data['name']
            text_json['volumeRef'] = data['name']
            text_json['id'] = data['name']
            response.text = json.dumps(text_json)
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-mappings$", path):
            response.status_code = 200
            text_json = json.loads("""
                  {
                    "lunMappingRef":"8800000000000000000000000000000000000000",
                    "lun": 0,
                    "ssid": 16384,
                    "perms": 15,
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "type": "all",
                    "mapRef": "8400000060080E500023C73400300381515BFBA3"
                    }
                  """)
            text_json['volumeRef'] = data['mappableObjectId']
            text_json['mapRef'] = data['targetId']
            response.text = json.dumps(text_json)
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/hosts$", path):
            response.status_code = 200
            response.text = """{"isSAControlled": false,
            "confirmLUNMappingCreation"
            : false, "label": "stlrx300s7-55", "isLargeBlockFormatHost":
            false, "clusterRef": "8500000060080E500023C7340036035F515B78FC",
            "protectionInformationCapableAccessMethod": false,
            "ports": [], "hostRef":
            "8400000060080E500023C73400300381515BFBA3", "hostTypeIndex": 10,
            "hostSidePorts": [{"label": "NewStore", "type": "iscsi",
            "address": "iqn.1998-01.com.vmware:localhost-28a58148"}]}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-groups$", path):
            response.status_code = 200
            text_json = json.loads("""{"status": "optimal",
                "autoDeleteLimit": 0,
                "maxRepositoryCapacity": "-65536", "rollbackStatus": "none"
                , "unusableRepositoryCapacity": "0", "pitGroupRef":
                "3300000060080E500023C7340000098D5294AC9A", "clusterSize":
                65536, "label": "C6JICISVHNG2TFZX4XB5ZWL7O",
                "maxBaseCapacity":
                "476187142128128", "repositoryVolume":
                "3600000060080E500023BB3400001FA952CEF12C",
                "fullWarnThreshold": 99, "repFullPolicy": "purgepit",
                "action": "none", "rollbackPriority": "medium",
                "creationPendingStatus": "none", "consistencyGroupRef":
                "0000000000000000000000000000000000000000", "volumeHandle":
                49153, "consistencyGroup": false, "baseVolume":
                "0200000060080E500023C734000009825294A534"}""")
            text_json['label'] = data['name']
            text_json['name'] = data['name']
            text_json['pitGroupRef'] = data['name']
            text_json['id'] = data['name']
            text_json['baseVolume'] = data['baseMappableObjectId']
            response.text = json.dumps(text_json)
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-images$", path):
            response.status_code = 200
            text_json = json.loads("""{"status": "optimal",
            "pitCapacity": "2147483648",
            "pitTimestamp": "1389315375", "pitGroupRef":
            "3300000060080E500023C7340000098D5294AC9A", "creationMethod":
            "user", "repositoryCapacityUtilization": "2818048",
            "activeCOW": true, "isRollbackSource": false, "pitRef":
            "3400000060080E500023BB3400631F335294A5A8",
            "pitSequenceNumber": "19"}""")
            text_json['label'] = data['groupId']
            text_json['name'] = data['groupId']
            text_json['id'] = data['groupId']
            text_json['pitGroupRef'] = data['groupId']
            response.text = json.dumps(text_json)
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-volumes$",
                      path):
            response.status_code = 200
            text_json = json.loads("""{"unusableRepositoryCapacity": "0",
            "totalSizeInBytes":
            "-1", "worldWideName": "60080E500023BB3400001FAD52CEF2F5",
            "boundToPIT": true, "wwn":
            "60080E500023BB3400001FAD52CEF2F5", "id":
            "3500000060080E500023BB3400001FAD52CEF2F5",
            "baseVol": "0200000060080E500023BB3400001FA352CECCAE",
            "label": "bdm-pv-1", "volumeFull": false,
            "preferredControllerId": "070000000000000000000001", "offline":
            false, "viewSequenceNumber": "10", "status": "optimal",
            "viewRef": "3500000060080E500023BB3400001FAD52CEF2F5",
            "mapped": false, "accessMode": "readOnly", "viewTime":
            "1389315613", "repositoryVolume":
            "0000000000000000000000000000000000000000", "preferredManager":
            "070000000000000000000001", "volumeHandle": 16385,
            "currentManager": "070000000000000000000001",
            "maxRepositoryCapacity": "0", "name": "bdm-pv-1",
            "fullWarnThreshold": 0, "currentControllerId":
            "070000000000000000000001", "basePIT":
            "3400000060080E500023BB3400631F335294A5A8", "clusterSize":
            0, "mgmtClientAttribute": 0}""")
            text_json['label'] = data['name']
            text_json['name'] = data['name']
            text_json['id'] = data['name']
            text_json['basePIT'] = data['snapshotImageId']
            text_json['baseVol'] = data['baseMappableObjectId']
            response.text = json.dumps(text_json)
        elif re.match("^/storage-systems$", path):
            response.status_code = 200
            response.text = """{"freePoolSpace": "17055871480319",
            "driveCount": 24,
            "wwn": "60080E500023C73400000000515AF323", "id": "1",
            "hotSpareSizeAsString": "0", "hostSparesUsed": 0, "types": "",
            "hostSpareCountInStandby": 0, "status": "optimal", "trayCount":
            1, "usedPoolSpaceAsString": "37452115456", "ip2":
            "10.63.165.216", "ip1": "10.63.165.215",
            "freePoolSpaceAsString": "17055871480319", "hotSpareCount": 0,
            "hotSpareSize": "0", "name": "stle2600-7_8", "usedPoolSpace":
            "37452115456", "driveTypes": ["sas"],
            "unconfiguredSpaceByDriveType": {}, "unconfiguredSpaceAsStrings":
            "0", "model": "2650", "unconfiguredSpace": "0"}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+$",
                      path):
            response.status_code = 200
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-copy-jobs$",
                      path):
            response.status_code = 200
            response.text = """{"status": "complete", "cloneCopy": true,
            "pgRef":
            "3300000060080E500023C73400000ACA52D29454", "volcopyHandle":49160
            , "idleTargetWriteProt": true, "copyPriority": "priority2",
            "volcopyRef": "1800000060080E500023C73400000ACF52D29466",
            "worldWideName": "60080E500023C73400000ACF52D29466",
            "copyCompleteTime": "0", "sourceVolume":
            "3500000060080E500023C73400000ACE52D29462", "currentManager":
            "070000000000000000000002", "copyStartTime": "1389551671",
            "reserved1": "00000000", "targetVolume":
            "0200000060080E500023C73400000A8C52D10675"}"""
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volumes/[0-9A-Za-z]+$",
                      path):
            response.status_code = 200
            response.text = """{"extremeProtection": false,
                    "pitBaseVolume": true,
                    "dssMaxSegmentSize": 131072,
                    "totalSizeInBytes": "1073741824", "raidLevel": "raid6",
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "listOfMappings": [{
                    "lunMappingRef":"8800000000000000000000000000000000000000",
                    "lun": 0,
                    "ssid": 16384,
                    "perms": 15,
                    "volumeRef": "0200000060080E500023BB34000003FB515C2293",
                    "type": "all",
                    "mapRef": "8400000060080E500023C73400300381515BFBA3"
                    }], "sectorOffset": "15",
                    "id": "0200000060080E500023BB34000003FB515C2293",
                    "wwn": "60080E500023BB3400001FC352D14CB2",
                    "capacity": "2147483648", "mgmtClientAttribute": 0,
                    "label": "rename",
                    "volumeFull": false,
                    "blkSize": 512, "volumeCopyTarget": false,
                    "volumeGroupRef":
                    "0400000060080E500023BB3400001F9F52CECC3F",
                    "preferredControllerId": "070000000000000000000001",
                    "currentManager": "070000000000000000000001",
                    "applicationTagOwned": false, "status": "optimal",
                    "segmentSize": 131072, "volumeUse": "standardVolume",
                    "action": "none", "preferredManager":
                    "070000000000000000000001", "volumeHandle": 15,
                    "offline": false, "preReadRedundancyCheckEnabled": false,
                    "dssPreallocEnabled": false, "name": "bdm-vc-test-1",
                    "worldWideName": "60080E500023BB3400001FC352D14CB2",
                    "currentControllerId": "070000000000000000000001",
                    "protectionInformationCapable": false, "mapped": false,
                    "reconPriority": 1, "protectionType":
                    "type1Protection"}"""
        else:
            # Unknown API
            response.status_code = 500

        return response

    def do_DELETE(self, path, params, data, headers):
        """Respond to a DELETE request."""

        response = FakeEseriesResponse()
        if "/devmgr/vn" not in path:
            response.status_code = 500

        (__, ___, path) = path.partition("/devmgr/vn")
        if re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-images"
                    "/[0-9A-Za-z]+$", path):
            code = 204
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-groups"
                      "/[0-9A-Za-z]+$", path):
            code = 204
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/snapshot-volumes"
                      "/[0-9A-Za-z]+$", path):
            code = 204
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-copy-jobs"
                      "/[0-9A-Za-z]+$", path):
            code = 204
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volumes"
                      "/[0-9A-Za-z]+$", path):
            code = 204
        elif re.match("^/storage-systems/[0-9a-zA-Z]+/volume-mappings/"
                      "[0-9a-zA-Z]+$", path):
            code = 204
        else:
            code = 500

        response.status_code = code
        return response


class FakeEseriesHTTPSession(object):
    """A fake requests.Session for netapp tests."""
    def __init__(self):
        self.handler = FakeEseriesServerHandler()

    def request(self, method, url, params, data, headers, timeout, verify):
        address = '127.0.0.1:80'
        (__, ___, path) = url.partition(address)
        if method.upper() == 'GET':
            return self.handler.do_GET(path, params, data, headers)
        elif method.upper() == 'POST':
            return self.handler.do_POST(path, params, data, headers)
        elif method.upper() == 'DELETE':
            return self.handler.do_DELETE(path, params, data, headers)
        else:
            raise exception.Invalid()


@ddt.ddt
class NetAppEseriesISCSIDriverTestCase(test.TestCase):
    """Test case for NetApp e-series iscsi driver."""

    volume = {'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
              'volume_name': 'lun1', 'host': 'hostname@backend#DDP',
              'os_type': 'linux', 'provider_location': 'lun1',
              'name_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
              'provider_auth': 'provider a b', 'project_id': 'project',
              'display_name': None, 'display_description': 'lun1',
              'volume_type_id': None}
    snapshot = {'id': '17928122-553b-4da9-9737-e5c3dcd97f75',
                'volume_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
                'size': 2, 'volume_name': 'lun1',
                'volume_size': 2, 'project_id': 'project',
                'display_name': None, 'display_description': 'lun1',
                'volume_type_id': None}
    volume_sec = {'id': 'b6c01641-8955-4917-a5e3-077147478575',
                  'size': 2, 'volume_name': 'lun1',
                  'os_type': 'linux', 'provider_location': 'lun1',
                  'name_id': 'b6c01641-8955-4917-a5e3-077147478575',
                  'provider_auth': None, 'project_id': 'project',
                  'display_name': None, 'display_description': 'lun1',
                  'volume_type_id': None}
    volume_clone = {'id': 'b4b24b27-c716-4647-b66d-8b93ead770a5', 'size': 3,
                    'volume_name': 'lun1',
                    'os_type': 'linux', 'provider_location': 'cl_sm',
                    'name_id': 'b4b24b27-c716-4647-b66d-8b93ead770a5',
                    'provider_auth': None,
                    'project_id': 'project', 'display_name': None,
                    'display_description': 'lun1',
                    'volume_type_id': None}
    volume_clone_large = {'id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'size': 6, 'volume_name': 'lun1',
                          'os_type': 'linux', 'provider_location': 'cl_lg',
                          'name_id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'provider_auth': None,
                          'project_id': 'project', 'display_name': None,
                          'display_description': 'lun1',
                          'volume_type_id': None}
    fake_eseries_volume_label = utils.convert_uuid_to_es_fmt(volume['id'])
    connector = {'initiator': 'iqn.1998-01.com.vmware:localhost-28a58148'}
    fake_size_gb = volume['size']
    fake_eseries_pool_label = 'DDP'
    fake_ref = {'source-name': 'CFDGJSLS'}
    fake_ret_vol = {'id': 'vol_id', 'label': 'label',
                    'worldWideName': 'wwn', 'capacity': '2147583648'}

    def setUp(self):
        super(NetAppEseriesISCSIDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.mock_object(na_utils, 'OpenStackInfo')

        configuration = self._set_config(create_configuration())
        self.driver = common.NetAppDriver(configuration=configuration)
        self.library = self.driver.library
        self.mock_object(requests, 'Session', FakeEseriesHTTPSession)
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(self.driver.library, '_check_storage_system')
        self.driver.do_setup(context='context')
        self.driver.library._client._endpoint = fakes.FAKE_ENDPOINT_HTTP

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'eseries'
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_server_port = None
        configuration.netapp_webservice_path = '/devmgr/vn'
        configuration.netapp_controller_ips = '127.0.0.2,127.0.0.3'
        configuration.netapp_sa_password = 'pass1234'
        configuration.netapp_login = 'rw'
        configuration.netapp_password = 'rw'
        configuration.netapp_storage_pools = 'DDP'
        configuration.netapp_enable_multiattach = False
        return configuration

    def test_embedded_mode(self):
        self.mock_object(self.driver.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(client.RestClient, '_init_features')
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1,127.0.0.3'

        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(client.RestClient, 'list_storage_systems', mock.Mock(
            return_value=[fakes.STORAGE_SYSTEM]))
        driver.do_setup(context='context')

        self.assertEqual('1fa6efb5-f07b-4de4-9f0e-52e5f7ff5d1b',
                         driver.library._client.get_system_id())

    def test_check_system_pwd_not_sync(self):
        def list_system():
            if getattr(self, 'test_count', None):
                self.test_count = 1
                return {'status': 'passwordoutofsync'}
            return {'status': 'needsAttention'}

        self.library._client.list_storage_system = mock.Mock(wraps=list_system)
        result = self.library._check_storage_system()
        self.assertTrue(result)

    def test_create_destroy(self):
        self.mock_object(client.RestClient, 'delete_volume',
                         mock.Mock(return_value='None'))
        self.mock_object(self.driver.library, 'create_volume',
                         mock.Mock(return_value=self.volume))
        self.mock_object(self.library._client, 'list_volume', mock.Mock(
            return_value=fakes.VOLUME))

        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)

    def test_vol_stats(self):
        self.driver.get_volume_stats(refresh=False)

    def test_get_pool(self):
        self.mock_object(self.library, '_get_volume',
                         mock.Mock(return_value={
                             'volumeGroupRef': 'fake_ref'}))
        self.mock_object(self.library._client, "get_storage_pool",
                         mock.Mock(return_value={'volumeGroupRef': 'fake_ref',
                                                 'label': 'ddp1'}))

        pool = self.driver.get_pool({'name_id': 'fake-uuid'})

        self.assertEqual('ddp1', pool)

    def test_get_pool_no_pools(self):
        self.mock_object(self.library, '_get_volume',
                         mock.Mock(return_value={
                             'volumeGroupRef': 'fake_ref'}))
        self.mock_object(self.library._client, "get_storage_pool",
                         mock.Mock(return_value=None))

        pool = self.driver.get_pool({'name_id': 'fake-uuid'})

        self.assertEqual(None, pool)

    @mock.patch.object(library.NetAppESeriesLibrary, '_create_volume',
                       mock.Mock())
    def test_create_volume(self):

        self.driver.create_volume(self.volume)

        self.library._create_volume.assert_called_with(
            'DDP', self.fake_eseries_volume_label, self.volume['size'], {})

    def test_create_volume_no_pool_provided_by_scheduler(self):
        volume = copy.deepcopy(self.volume)
        volume['host'] = "host@backend"  # missing pool
        self.assertRaises(exception.InvalidHost, self.driver.create_volume,
                          volume)

    @mock.patch.object(client.RestClient, 'list_storage_pools')
    def test_helper_create_volume_fail(self, fake_list_pools):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        fake_list_pools.return_value = fake_pools
        wrong_eseries_pool_label = 'hostname@backend'
        self.assertRaises(exception.NetAppDriverException,
                          self.library._create_volume,
                          wrong_eseries_pool_label,
                          self.fake_eseries_volume_label,
                          self.fake_size_gb)

    @mock.patch.object(library.LOG, 'info')
    @mock.patch.object(client.RestClient, 'list_storage_pools')
    @mock.patch.object(client.RestClient, 'create_volume',
                       mock.MagicMock(return_value='CorrectVolume'))
    def test_helper_create_volume(self, storage_pools, log_info):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        storage_pools.return_value = fake_pools
        storage_vol = self.library._create_volume(
            self.fake_eseries_pool_label,
            self.fake_eseries_volume_label,
            self.fake_size_gb)
        log_info.assert_called_once_with("Created volume with label %s.",
                                         self.fake_eseries_volume_label)
        self.assertEqual('CorrectVolume', storage_vol)

    @mock.patch.object(client.RestClient, 'list_storage_pools')
    @mock.patch.object(client.RestClient, 'create_volume',
                       mock.MagicMock(
                           side_effect=exception.NetAppDriverException))
    @mock.patch.object(library.LOG, 'info', mock.Mock())
    def test_create_volume_check_exception(self, fake_list_pools):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        fake_list_pools.return_value = fake_pools
        self.assertRaises(exception.NetAppDriverException,
                          self.library._create_volume,
                          self.fake_eseries_pool_label,
                          self.fake_eseries_volume_label, self.fake_size_gb)

    def test_portal_for_vol_controller(self):
        volume = {'id': 'vol_id', 'currentManager': 'ctrl1'}
        vol_nomatch = {'id': 'vol_id', 'currentManager': 'ctrl3'}
        portals = [{'controller': 'ctrl2', 'iqn': 'iqn2'},
                   {'controller': 'ctrl1', 'iqn': 'iqn1'}]
        portal = self.library._get_iscsi_portal_for_vol(volume, portals)
        self.assertEqual({'controller': 'ctrl1', 'iqn': 'iqn1'}, portal)
        portal = self.library._get_iscsi_portal_for_vol(vol_nomatch, portals)
        self.assertEqual({'controller': 'ctrl2', 'iqn': 'iqn2'}, portal)

    def test_portal_for_vol_any_false(self):
        vol_nomatch = {'id': 'vol_id', 'currentManager': 'ctrl3'}
        portals = [{'controller': 'ctrl2', 'iqn': 'iqn2'},
                   {'controller': 'ctrl1', 'iqn': 'iqn1'}]
        self.assertRaises(exception.NetAppDriverException,
                          self.library._get_iscsi_portal_for_vol,
                          vol_nomatch, portals, False)

    def test_setup_error_unsupported_host_type(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_host_type = 'garbage'
        driver = common.NetAppDriver(configuration=configuration)
        self.assertRaises(exception.NetAppDriverException,
                          driver.library.check_for_setup_error)

    def test_check_host_type_default(self):
        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_host_type()
        self.assertEqual('LnxALUA', driver.library.host_type)

    def test_do_setup_all_default(self):
        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        mock_invoke.assert_called_with(**fakes.FAKE_CLIENT_PARAMS)

    def test_do_setup_http_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'http'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        mock_invoke.assert_called_with(**fakes.FAKE_CLIENT_PARAMS)

    def test_do_setup_https_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=8443,
                                    scheme='https')
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_do_setup_http_non_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_server_port = 81
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=81)
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_do_setup_https_non_default_port(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        configuration.netapp_server_port = 446
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=446,
                                    scheme='https')
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_setup_good_controller_ip(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system

    def test_setup_good_controller_ips(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '127.0.0.2,127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system

    def test_setup_missing_controller_ip(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = None
        driver = common.NetAppDriver(configuration=configuration)
        self.assertRaises(exception.InvalidInput,
                          driver.do_setup, context='context')

    def test_setup_error_invalid_controller_ip(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         mock.Mock(side_effect=socket.gaierror))

        self.assertRaises(
            exception.NoValidHost,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_first_controller_ip(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '987.65.43.21,127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         mock.Mock(side_effect=socket.gaierror))

        self.assertRaises(
            exception.NoValidHost,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_second_controller_ip(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1,987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         mock.Mock(side_effect=socket.gaierror))

        self.assertRaises(
            exception.NoValidHost,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_both_controller_ips(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '564.124.1231.1,987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         mock.Mock(side_effect=socket.gaierror))

        self.assertRaises(
            exception.NoValidHost,
            driver.library._check_mode_get_or_register_storage_system)

    def test_manage_existing_get_size(self):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        size = self.driver.manage_existing_get_size(self.volume, self.fake_ref)
        self.assertEqual(3, size)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)

    def test_get_exist_vol_source_name_missing(self):
        self.library._client.list_volume = mock.Mock(
            side_effect=exception.InvalidInput)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.library._get_existing_vol_with_manage_ref,
                          {'id': '1234'})

    @ddt.data('source-id', 'source-name')
    def test_get_exist_vol_source_not_found(self, attr_name):
        def _get_volume(v_id):
            d = {'id': '1', 'name': 'volume1', 'worldWideName': '0'}
            return d[v_id]

        self.library._client.list_volume = mock.Mock(wraps=_get_volume)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.library._get_existing_vol_with_manage_ref,
                          {attr_name: 'name2'})

        self.library._client.list_volume.assert_called_once_with(
            'name2')

    def test_get_exist_vol_with_manage_ref(self):
        fake_ret_vol = {'id': 'right'}
        self.library._client.list_volume = mock.Mock(return_value=fake_ret_vol)

        actual_vol = self.library._get_existing_vol_with_manage_ref(
            {'source-name': 'name2'})

        self.library._client.list_volume.assert_called_once_with('name2')
        self.assertEqual(fake_ret_vol, actual_vol)

    @mock.patch.object(utils, 'convert_uuid_to_es_fmt')
    def test_manage_existing_same_label(self, mock_convert_es_fmt):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        mock_convert_es_fmt.return_value = 'label'
        self.driver.manage_existing(self.volume, self.fake_ref)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)
        mock_convert_es_fmt.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')

    @mock.patch.object(utils, 'convert_uuid_to_es_fmt')
    def test_manage_existing_new(self, mock_convert_es_fmt):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        mock_convert_es_fmt.return_value = 'vol_label'
        self.library._client.update_volume = mock.Mock(
            return_value={'id': 'update', 'worldWideName': 'wwn'})
        self.driver.manage_existing(self.volume, self.fake_ref)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)
        mock_convert_es_fmt.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')
        self.library._client.update_volume.assert_called_once_with(
            'vol_id', 'vol_label')

    @mock.patch.object(library.LOG, 'info')
    def test_unmanage(self, log_info):
        self.library._get_volume = mock.Mock(return_value=self.fake_ret_vol)
        self.driver.unmanage(self.volume)
        self.library._get_volume.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')
        self.assertEqual(1, log_info.call_count)
