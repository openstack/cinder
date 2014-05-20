# Copyright (c) 2014 NetApp, Inc.
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
"""
Tests for NetApp e-series iscsi volume driver.
"""

import json
import mock
import re
import requests

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import common
from cinder.volume.drivers.netapp.options import netapp_basicauth_opts
from cinder.volume.drivers.netapp.options import netapp_eseries_opts


LOG = logging.getLogger(__name__)


def create_configuration():
    configuration = conf.Configuration(None)
    configuration.append_config_values(netapp_basicauth_opts)
    configuration.append_config_values(netapp_eseries_opts)
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
                      "code" : "LNX",
                      "name" : "Linux",
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
                    "listOfMappings": [], "sectorOffset": "15",
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
                    "listOfMappings": [], "sectorOffset": "15",
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
    """A fake requests.Session for netapp tests.
    """
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


class NetAppEseriesIscsiDriverTestCase(test.TestCase):
    """Test case for NetApp e-series iscsi driver."""

    volume = {'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
              'volume_name': 'lun1',
              'os_type': 'linux', 'provider_location': 'lun1',
              'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
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
                  'id': 'b6c01641-8955-4917-a5e3-077147478575',
                  'provider_auth': None, 'project_id': 'project',
                  'display_name': None, 'display_description': 'lun1',
                  'volume_type_id': None}
    volume_clone = {'id': 'b4b24b27-c716-4647-b66d-8b93ead770a5', 'size': 3,
                    'volume_name': 'lun1',
                    'os_type': 'linux', 'provider_location': 'cl_sm',
                    'id': 'b4b24b27-c716-4647-b66d-8b93ead770a5',
                    'provider_auth': None,
                    'project_id': 'project', 'display_name': None,
                    'display_description': 'lun1',
                    'volume_type_id': None}
    volume_clone_large = {'id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'size': 6, 'volume_name': 'lun1',
                          'os_type': 'linux', 'provider_location': 'cl_lg',
                          'id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'provider_auth': None,
                          'project_id': 'project', 'display_name': None,
                          'display_description': 'lun1',
                          'volume_type_id': None}
    connector = {'initiator': 'iqn.1998-01.com.vmware:localhost-28a58148'}

    def setUp(self):
        super(NetAppEseriesIscsiDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        configuration = self._set_config(create_configuration())
        self.driver = common.NetAppDriver(configuration=configuration)
        requests.Session = mock.Mock(wraps=FakeEseriesHTTPSession)
        self.driver.do_setup(context='context')
        self.driver.check_for_setup_error()

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'eseries'
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_server_port = '80'
        configuration.netapp_webservice_path = '/devmgr/vn'
        configuration.netapp_controller_ips = '127.0.0.2,127.0.0.3'
        configuration.netapp_sa_password = 'pass1234'
        configuration.netapp_login = 'rw'
        configuration.netapp_password = 'rw'
        configuration.netapp_storage_pools = 'DDP'
        return configuration

    def test_embedded_mode(self):
        configuration = self._set_config(create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1,127.0.0.3'
        driver = common.NetAppDriver(configuration=configuration)
        driver.do_setup(context='context')
        self.assertEqual(driver._client.get_system_id(),
                         '1fa6efb5-f07b-4de4-9f0e-52e5f7ff5d1b')

    def test_check_system_pwd_not_sync(self):
        def list_system():
            if getattr(self, 'test_count', None):
                self.test_count = 1
                return {'status': 'passwordoutofsync'}
            return {'status': 'needsAttention'}

        self.driver._client.list_storage_system = mock.Mock(wraps=list_system)
        result = self.driver._check_storage_system()
        self.assertTrue(result)

    def test_connect(self):
        self.driver.check_for_setup_error()

    def test_create_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)

    def test_create_vol_snapshot_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(self.volume_sec, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_map_unmap(self):
        self.driver.create_volume(self.volume)
        connection_info = self.driver.initialize_connection(self.volume,
                                                            self.connector)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info.get('data')
        self.assertIsNotNone(properties, 'Target portal is none')
        self.driver.terminate_connection(self.volume, self.connector)
        self.driver.delete_volume(self.volume)

    def test_map_already_mapped_same_host(self):
        self.driver.create_volume(self.volume)

        maps = [{'lunMappingRef': 'hdkjsdhjsdh',
                 'mapRef': '8400000060080E500023C73400300381515BFBA3',
                 'volumeRef': 'CFDXJ67BLJH25DXCZFZD4NSF54',
                 'lun': 2}]
        self.driver._get_host_mapping_for_vol_frm_array = mock.Mock(
            return_value=maps)
        self.driver._get_free_lun = mock.Mock()
        info = self.driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(
            self.driver._get_host_mapping_for_vol_frm_array.call_count, 1)
        self.assertEqual(self.driver._get_free_lun.call_count, 0)
        self.assertEqual(info['driver_volume_type'], 'iscsi')
        properties = info.get('data')
        self.assertIsNotNone(properties, 'Target portal is none')
        self.driver.terminate_connection(self.volume, self.connector)
        self.driver.delete_volume(self.volume)

    def test_map_already_mapped_diff_host(self):
        self.driver.create_volume(self.volume)

        maps = [{'lunMappingRef': 'hdkjsdhjsdh',
                 'mapRef': '7400000060080E500023C73400300381515BFBA3',
                 'volumeRef': 'CFDXJ67BLJH25DXCZFZD4NSF54',
                 'lun': 2}]
        self.driver._get_host_mapping_for_vol_frm_array = mock.Mock(
            return_value=maps)
        self.driver._get_vol_mapping_for_host_frm_array = mock.Mock(
            return_value=[])
        self.driver._get_free_lun = mock.Mock(return_value=0)
        self.driver._del_vol_mapping_frm_cache = mock.Mock()
        info = self.driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(
            self.driver._get_vol_mapping_for_host_frm_array.call_count, 1)
        self.assertEqual(
            self.driver._get_host_mapping_for_vol_frm_array.call_count, 1)
        self.assertEqual(self.driver._get_free_lun.call_count, 1)
        self.assertEqual(self.driver._del_vol_mapping_frm_cache.call_count, 1)
        self.assertEqual(info['driver_volume_type'], 'iscsi')
        properties = info.get('data')
        self.assertIsNotNone(properties, 'Target portal is none')
        self.driver.terminate_connection(self.volume, self.connector)
        self.driver.delete_volume(self.volume)

    def test_cloned_volume_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.create_cloned_volume(self.snapshot, self.volume)
        self.driver.delete_volume(self.volume)

    def test_map_by_creating_host(self):
        self.driver.create_volume(self.volume)
        connector_new = {'initiator': 'iqn.1993-08.org.debian:01:1001'}
        connection_info = self.driver.initialize_connection(self.volume,
                                                            connector_new)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info.get('data')
        self.assertIsNotNone(properties, 'Target portal is none')

    def test_vol_stats(self):
        self.driver.get_volume_stats(refresh=True)

    def test_create_vol_snapshot_diff_size_resize(self):
        self.driver.create_volume(self.volume)
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(
            self.volume_clone, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_create_vol_snapshot_diff_size_subclone(self):
        self.driver.create_volume(self.volume)
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(
            self.volume_clone_large, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)
