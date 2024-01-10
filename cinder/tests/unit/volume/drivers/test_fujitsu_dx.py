# Copyright (c) 2015 FUJITSU LIMITED
# Copyright (c) 2012 EMC Corporation, Inc.
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

import tempfile
from unittest import mock

from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import ssh_utils
from cinder.tests.unit import test
from cinder.volume import configuration as conf

with mock.patch.dict('sys.modules', pywbem=mock.Mock()):
    from cinder.volume.drivers.fujitsu.eternus_dx \
        import eternus_dx_cli
    from cinder.volume.drivers.fujitsu.eternus_dx \
        import eternus_dx_common as dx_common
    from cinder.volume.drivers.fujitsu.eternus_dx \
        import eternus_dx_fc as dx_fc
    from cinder.volume.drivers.fujitsu.eternus_dx \
        import eternus_dx_iscsi as dx_iscsi

CONFIG_FILE_NAME = 'cinder_fujitsu_eternus_dx.xml'
STORAGE_SYSTEM = '172.16.0.2'

CONF = """<?xml version='1.0' encoding='UTF-8'?>
<FUJITSU>
<EternusIP>172.16.0.2</EternusIP>
<EternusPort>5988</EternusPort>
<EternusUser>testuser</EternusUser>
<EternusPassword>testpass</EternusPassword>
<EternusISCSIIP>10.0.0.3</EternusISCSIIP>
<EternusPool>abcd1234_TPP</EternusPool>
<EternusPool>abcd1234_RG</EternusPool>
<EternusSnapPool>abcd1234_OSVD</EternusSnapPool>
<EternusSnapPool>abcd1234_TPP</EternusSnapPool>
</FUJITSU>"""

TEST_VOLUME = {
    'id': '3d6eeb5d-109b-4435-b891-d01415178490',
    'name': 'volume1',
    'display_name': 'volume1',
    'provider_location': None,
    'metadata': {},
    'size': 1,
    'host': 'controller@113#abcd1234_TPP'
}

TEST_VOLUME2 = {
    'id': '98179912-2495-42e9-97f0-6a0d3511700a',
    'name': 'volume2',
    'display_name': 'volume2',
    'provider_location': None,
    'metadata': {},
    'size': 1,
    'host': 'controller@113#abcd1234_RG'
}

TEST_SNAP = {
    'id': 'f47a8da3-d9e2-46aa-831f-0ef04158d5a1',
    'volume_name': 'volume-3d6eeb5d-109b-4435-b891-d01415178490',
    'name': 'snap1',
    'display_name': 'test_snapshot',
    'volume': TEST_VOLUME,
    'volume_id': '3d6eeb5d-109b-4435-b891-d01415178490',
}

TEST_CLONE = {
    'name': 'clone1',
    'size': 1,
    'volume_name': 'vol1',
    'id': '391fb914-8a55-4384-a747-588641db3b15',
    'project_id': 'project',
    'display_name': 'clone1',
    'display_description': 'volume created from snapshot',
    'metadata': {},
    'host': 'controller@113#abcd1234_TPP'
}

TEST_VOLUME_QOS = {
    'id': '7bd8b81f-137d-4140-85ce-d00281c91c84',
    'name': 'qos',
    'display_name': 'qos',
    'provider_location': None,
    'metadata': {},
    'size': 1,
    'host': 'controller@113#abcd1234_TPP'
}

ISCSI_INITIATOR = 'iqn.1993-08.org.debian:01:8261afe17e4c'
ISCSI_TARGET_IP = '10.0.0.3'
ISCSI_TARGET_IQN = 'iqn.2000-09.com.fujitsu:storage-system.eternus-dxl:0'
FC_TARGET_WWN = ['500000E0DA000001', '500000E0DA000002']
TEST_WWPN = ['0123456789111111', '0123456789222222']
TEST_CONNECTOR = {'initiator': ISCSI_INITIATOR, 'wwpns': TEST_WWPN}

STORAGE_IP = '172.16.0.2'
TEST_USER = 'testuser'
TEST_PASSWORD = 'testpassword'

STOR_CONF_SVC = 'FUJITSU_StorageConfigurationService'
CTRL_CONF_SVC = 'FUJITSU_ControllerConfigurationService'
REPL_SVC = 'FUJITSU_ReplicationService'
STOR_VOL = 'FUJITSU_StorageVolume'
SCSI_PROT_CTR = 'FUJITSU_AffinityGroupController'
STOR_HWID = 'FUJITSU_StorageHardwareID'
STOR_HWID_MNG_SVC = 'FUJITSU_StorageHardwareIDManagementService'
STOR_POOL = 'FUJITSU_RAIDStoragePool'
STOR_POOLS = ['FUJITSU_ThinProvisioningPool', 'FUJITSU_RAIDStoragePool']
AUTH_PRIV = 'FUJITSU_AuthorizedPrivilege'
STOR_SYNC = 'FUJITSU_StorageSynchronized'
PROT_CTRL_UNIT = 'CIM_ProtocolControllerForUnit'
STORAGE_TYPE = 'abcd1234_TPP'
STORAGE_TYPE2 = 'abcd1234_RG'
LUNMASKCTRL_IDS = ['AFG0010_CM00CA00P00', 'AFG0011_CM01CA00P00']

MAP_STAT = '0'
VOL_STAT = '0'

FAKE_CAPACITY = 1170368102400
FAKE_REMAIN = 1168220618752
FAKE_PROVISION = 1024
# Volume1 in pool abcd1234_TPP
FAKE_LUN_ID1 = '600000E00D2A0000002A011500140000'
FAKE_LUN_NO1 = '0x0014'
# Snapshot1 in pool abcd1234_OSVD
FAKE_LUN_ID2 = '600000E00D2A0000002A0115001E0000'
FAKE_LUN_NO2 = '0x001E'
FAKE_SDV_NO = '0x001E'
# Volume2 in pool abcd1234_RG
FAKE_LUN_ID3 = '600000E00D2800000028075301140000'
FAKE_LUN_NO3 = '0x0114'
# VolumeQoS in pool abcd1234_TPP
FAKE_LUN_ID_QOS = '600000E00D2A0000002A011500140000'
FAKE_LUN_NO_QOS = '0x0014'
FAKE_SYSTEM_NAME = 'ET603SA4621302115'
# abcd1234_TPP pool
FAKE_USEGB = 1
# abcd1234_RG pool
FAKE_USEGB2 = 2
FAKE_POOLS = [{
    'path': {'InstanceID': 'FUJITSU:TPP0004'},
    'pool_name': 'abcd1234_TPP',
    'useable_capacity_gb': int(
        (FAKE_CAPACITY / units.Mi * 20 - FAKE_PROVISION) / 1024),
    'multiattach': True,
    'thick_provisioning_support': False,
    'provisioned_capacity_gb': FAKE_USEGB,
    'thin_provisioning_support': True,
    'free_capacity_gb': int(FAKE_CAPACITY / units.Gi - FAKE_USEGB),
    'total_capacity_gb': int(FAKE_CAPACITY / units.Gi),
    'max_over_subscription_ratio': '20.0',
}, {
    'path': {'InstanceID': 'FUJITSU:RSP0005'},
    'pool_name': 'abcd1234_RG',
    'useable_capacity_gb': int(FAKE_CAPACITY / units.Gi - FAKE_USEGB2),
    'multiattach': True,
    'thick_provisioning_support': True,
    'provisioned_capacity_gb': FAKE_USEGB2,
    'total_volumes': 2,
    'thin_provisioning_support': False,
    'free_capacity_gb': int((FAKE_REMAIN * 1.0 / units.Mi) / 1024),
    'total_capacity_gb': int(FAKE_CAPACITY / units.Gi),
    'fragment_capacity_mb': FAKE_REMAIN * 1.0 / units.Mi,
    'max_over_subscription_ratio': 1,
}]

FAKE_STATS = {
    'driver_version': '1.4.7',
    'storage_protocol': 'iSCSI',
    'vendor_name': 'FUJITSU',
    'QoS_support': True,
    'volume_backend_name': 'volume_backend_name',
    'shared_targets': True,
    'backend_state': 'up',
    'pools': FAKE_POOLS,
}
FAKE_STATS2 = {
    'driver_version': '1.4.7',
    'storage_protocol': 'FC',
    'vendor_name': 'FUJITSU',
    'QoS_support': True,
    'volume_backend_name': 'volume_backend_name',
    'shared_targets': True,
    'backend_state': 'up',
    'pools': FAKE_POOLS,
}

# Volume1 in pool abcd1234_TPP
FAKE_KEYBIND1 = {
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID1,
}

# Volume2 in pool abcd1234_RG
FAKE_KEYBIND3 = {
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID3,
}

# Volume QOS in pool abcd1234_TPP
FAKE_KEYBIND_QOS = {
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID_QOS,
}

# Volume1
FAKE_LOCATION1 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND1,
    'vol_name': 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
}

# Clone Volume
FAKE_CLONE_LOCATION = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND1,
    'vol_name': 'FJosv_UkCZqMFZW3SU_JzxjHiKfg=='
}

# Volume2
FAKE_LOCATION3 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND3,
    'vol_name': 'FJosv_4whcadwDac7ANKHA2O719A=='
}

# VolumeQOS
FAKE_LOCATION_QOS = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND_QOS,
    'vol_name': 'FJosv_mIsapeuZOaSXz4LYTqFcug=='
}

# Volume1 metadata info.
# Here is a misspelling, and the right value should be "Thinprovisioning_POOL".
# It would not be compatible with the metadata of the legacy volumes,
# so this spelling mistake needs to be retained.
FAKE_LUN_META1 = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO1,
    'FJ_Volume_Name': 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

# Volume2 metadata info.
FAKE_LUN_META3 = {
    'FJ_Pool_Type': 'RAID_GROUP',
    'FJ_Volume_No': FAKE_LUN_NO3,
    'FJ_Volume_Name': 'FJosv_4whcadwDac7ANKHA2O719A==',
    'FJ_Pool_Name': STORAGE_TYPE2,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

# VolumeQOS metadata info
FAKE_LUN_META_QOS = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO_QOS,
    'FJ_Volume_Name': 'FJosv_mIsapeuZOaSXz4LYTqFcug==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

# Volume1
FAKE_MODEL_INFO1 = {
    'provider_location': str(FAKE_LOCATION1),
    'metadata': FAKE_LUN_META1,
}
# Volume2
FAKE_MODEL_INFO3 = {
    'provider_location': str(FAKE_LOCATION3),
    'metadata': FAKE_LUN_META3,
}
# VoluemQOS
FAKE_MODEL_INFO_QOS = {
    'provider_location': str(FAKE_LOCATION_QOS),
    'metadata': FAKE_LUN_META_QOS,
}

FAKE_KEYBIND2 = {
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID2,
}

FAKE_LOCATION2 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND2,
    'vol_name': 'FJosv_OgEZj1mSvKRvIKOExKktlg=='
}

FAKE_SNAP_META = {
    'FJ_Pool_Name': 'abcd1234_OSVD',
    'FJ_SDV_Name': u'FJosv_OgEZj1mSvKRvIKOExKktlg==',
    'FJ_SDV_No': FAKE_SDV_NO,
    'FJ_Pool_Type': 2
}

# Snapshot created on controller@113#abcd1234_TPP
FAKE_SNAP_META2 = {
    'FJ_Pool_Name': 'abcd1234_TPP',
    'FJ_SDV_Name': 'FJosv_OgEZj1mSvKRvIKOExKktlg==',
    'FJ_SDV_No': FAKE_SDV_NO,
    'FJ_Pool_Type': 5
}

FAKE_SNAP_INFO = {
    'metadata': FAKE_SNAP_META,
    'provider_location': str(FAKE_LOCATION2)
}

# Snapshot created on controller@113#abcd1234_TPP
FAKE_SNAP_INFO2 = {
    'metadata': FAKE_SNAP_META2,
    'provider_location': str(FAKE_LOCATION2)
}

FAKE_LUN_META2 = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO1,
    'FJ_Volume_Name': 'FJosv_OgEZj1mSvKRvIKOExKktlg==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

FAKE_CLONE_LUN_META = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO1,
    'FJ_Volume_Name': 'FJosv_UkCZqMFZW3SU_JzxjHiKfg==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

FAKE_MODEL_INFO2 = {
    'provider_location': str(FAKE_CLONE_LOCATION),
    'metadata': FAKE_CLONE_LUN_META,
}

FAKE_CLI_OUTPUT = {
    "result": 0,
    'rc': '0',
    "message": 'TEST_MESSAGE'
}

# Constants for QOS
MAX_IOPS = 4294967295
MAX_THROUGHPUT = 2097151
MIN_IOPS = 1
MIN_THROUGHPUT = 1


class FJ_StorageVolume(dict):
    pass


class FJ_StoragePool(dict):
    pass


class FJ_AffinityGroupController(dict):
    pass


class FakeCIMInstanceName(dict):

    def fake_create_eternus_instance_name(self, classname, bindings):
        instancename = FakeCIMInstanceName()
        for key in bindings:
            instancename[key] = bindings[key]
        instancename.classname = classname
        instancename.namespace = 'root/eternus'
        return instancename

    def fake_enumerateinstances(self):
        instancename_1 = FakeCIMInstanceName()

        ret = []
        instancename_1['ElementName'] = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        instancename_1['Purpose'] = '00228+0x06'
        instancename_1['Name'] = None
        instancename_1['DeviceID'] = FAKE_LUN_ID1
        instancename_1['SystemName'] = STORAGE_SYSTEM
        ret.append(instancename_1)
        instancename_1.path = ''
        instancename_1.classname = 'FUJITSU_StorageVolume'

        snaps = FakeCIMInstanceName()
        snaps['ElementName'] = 'FJosv_OgEZj1mSvKRvIKOExKktlg=='
        snaps['Name'] = None
        snaps['DeviceID'] = FAKE_LUN_ID2
        snaps['SystemName'] = STORAGE_SYSTEM
        ret.append(snaps)
        snaps.path = ''
        snaps.classname = 'FUJITSU_StorageVolume'

        map = FakeCIMInstanceName()
        map['ElementName'] = 'FJosv_hhJsV9lcMBvAPADrGqucwg=='
        map['Name'] = None
        ret.append(map)
        map.path = ''
        return ret


class FakeEternusConnection(object):
    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, TheElement=None, LUNames=None,
                     Size=None, Type=None, Mode=None, Locality=None,
                     InitiatorPortIDs=None, TargetPortIDs=None,
                     DeviceAccesses=None, SyncType=None,
                     SourceElement=None, TargetElement=None,
                     Operation=None, CopyType=None,
                     Synchronization=None, ProtocolControllers=None,
                     TargetPool=None, WaitForCopyState=None):
        global MAP_STAT, VOL_STAT
        if MethodName == 'CreateOrModifyElementFromStoragePool':
            VOL_STAT = '1'
            rc = 0
            vol = self._enum_volumes()
            if InPool.get('InstanceID') == 'FUJITSU:RSP0005':
                job = {'TheElement': vol[1].path}
            else:
                if ElementName == 'FJosv_OgEZj1mSvKRvIKOExKktlg==':
                    job = {'TheElement': vol[3].path}
                else:
                    job = {'TheElement': vol[0].path}
        elif MethodName == 'ReturnToStoragePool':
            VOL_STAT = '0'
            rc = 0
            job = {}
        elif MethodName == 'GetReplicationRelationships':
            rc = 0
            job = {'Synchronizations': []}
        elif MethodName == 'ExposePaths':
            MAP_STAT = '1'
            rc = 0
            job = {}
        elif MethodName == 'HidePaths':
            MAP_STAT = '0'
            rc = 0
            job = {}
        elif MethodName == 'CreateElementReplica':
            rc = 0
            snap = self._enum_snapshots()
            job = {'TargetElement': snap[0].path}
        elif MethodName == 'CreateReplica':
            rc = 0
            snap = self._enum_snapshots()
            job = {'TargetElement': snap[0].path}
        elif MethodName == 'ModifyReplicaSynchronization':
            rc = 0
            job = {}
        else:
            raise exception.VolumeBackendAPIException(data="invoke method")

        return (rc, job)

    def EnumerateInstanceNames(self, name):
        result = []
        if name == 'FUJITSU_StorageVolume':
            result = self._enum_volumes()
        elif name == 'FUJITSU_StorageConfigurationService':
            result = self._enum_confservice()
        elif name == 'FUJITSU_ReplicationService':
            result = self._enum_repservice()
        elif name == 'FUJITSU_ControllerConfigurationService':
            result = self._enum_ctrlservice()
        elif name == 'FUJITSU_AffinityGroupController':
            result = self._enum_afntyservice()
        elif name == 'FUJITSU_StorageHardwareIDManagementService':
            result = self._enum_sthwidmngsvc()
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._ref_unitnames()
        elif name == 'CIM_StoragePool':
            result = self._enum_pools()
        elif name == 'FUJITSU_SCSIProtocolEndpoint':
            result = self._enum_scsiport_endpoint()
        elif name == 'FUJITSU_IPProtocolEndpoint':
            result = self._enum_ipproto_endpoint()

        return result

    def EnumerateInstances(self, name, **param_dict):
        result = None
        if name == 'FUJITSU_StorageProduct':
            result = self._enum_sysnames()
        elif name == 'FUJITSU_RAIDStoragePool':
            result = self._enum_pool_details('RAID')
        elif name == 'FUJITSU_ThinProvisioningPool':
            result = self._enum_pool_details('TPP')
        elif name == 'FUJITSU_SCSIProtocolEndpoint':
            result = self._enum_scsiport_endpoint()
        elif name == 'FUJITSU_iSCSIProtocolEndpoint':
            result = self._enum_iscsiprot_endpoint()
        elif name == 'FUJITSU_StorageHardwareID':
            result = self._enum_sthwid()
        elif name == 'CIM_SCSIProtocolEndpoint':
            result = self._enum_scsiport_endpoint()
        elif name == 'FUJITSU_StorageHardwareID':
            result = None
        elif name == 'FUJITSU_StorageVolume':
            instancename_1 = FakeCIMInstanceName()
            result = instancename_1.fake_enumerateinstances()
        else:
            result = None

        return result

    def GetInstance(self, objectpath, LocalOnly=False):
        try:
            name = objectpath['CreationClassName']
        except KeyError:
            name = objectpath.classname

        result = None

        if name == 'FUJITSU_StorageVolume':
            result = self._getinstance_storagevolume(objectpath)
        elif name == 'FUJITSU_IPProtocolEndpoint':
            result = self._getinstance_ipprotocolendpoint(objectpath)
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._getinstance_unit(objectpath)
        elif name == 'FUJITSU_AffinityGroupController':
            result = self._getinstance_unit(objectpath)

        return result

    def Associators(self, objectpath, AssocClass=None,
                    ResultClass='FUJITSU_StorageHardwareID'):
        result = None
        if ResultClass == 'FUJITSU_StorageHardwareID':
            result = self._assoc_hdwid()
        elif ResultClass == 'FUJITSU_iSCSIProtocolEndpoint':
            result = self._assoc_endpoint(objectpath)
        elif ResultClass == 'FUJITSU_StorageVolume':
            result = self._assoc_storagevolume(objectpath)
        elif ResultClass == 'FUJITSU_AuthorizedPrivilege':
            result = self._assoc_authpriv()
        elif AssocClass == 'FUJITSU_AllocatedFromStoragePool':
            result = self._assocnames_pool(objectpath)
        else:
            result = self._default_assoc(objectpath)

        return result

    def AssociatorNames(self, objectpath, AssocClass=None,
                        ResultClass=SCSI_PROT_CTR):
        result = None
        if ResultClass == SCSI_PROT_CTR:
            result = self._assocnames_lunmaskctrl()
        elif ResultClass == 'FUJITSU_TCPProtocolEndpoint':
            result = self._assocnames_tcp_endpoint()
        elif ResultClass == 'FUJITSU_AffinityGroupController':
            result = self._assocnames_afngroup()
        elif (ResultClass == 'FUJITSU_StorageVolume' and
              AssocClass == 'FUJITSU_AllocatedFromStoragePool'):
            result = self._assocnames_volumelist(objectpath)
        else:
            result = self._default_assocnames(objectpath)

        return result

    def ReferenceNames(self, objectpath,
                       ResultClass='CIM_ProtocolControllerForUnit'):
        result = []
        if ResultClass == 'CIM_ProtocolControllerForUnit':
            if MAP_STAT == '1':
                result = self._ref_unitnames()
            else:
                result = []
        elif ResultClass == 'FUJITSU_StorageSynchronized':
            result = self._ref_storage_sync()
        else:
            result = self._default_ref(objectpath)

        return result

    def _ref_unitnames(self):
        unitnames = []

        unitname = FJ_AffinityGroupController()
        dependent = {}
        dependent['CreationClassName'] = STOR_VOL
        dependent['DeviceID'] = FAKE_LUN_ID1
        dependent['SystemName'] = STORAGE_SYSTEM

        antecedent = {}
        antecedent['CreationClassName'] = SCSI_PROT_CTR
        antecedent['DeviceID'] = LUNMASKCTRL_IDS[0]
        antecedent['SystemName'] = STORAGE_SYSTEM

        unitname['Dependent'] = dependent
        unitname['Antecedent'] = antecedent
        unitname['CreationClassName'] = PROT_CTRL_UNIT
        unitname.path = unitname
        unitnames.append(unitname)

        unitname2 = FJ_AffinityGroupController()
        dependent2 = {}
        dependent2['CreationClassName'] = STOR_VOL
        dependent2['DeviceID'] = FAKE_LUN_ID1
        dependent2['SystemName'] = STORAGE_SYSTEM

        antecedent2 = {}
        antecedent2['CreationClassName'] = SCSI_PROT_CTR
        antecedent2['DeviceID'] = LUNMASKCTRL_IDS[1]
        antecedent2['SystemName'] = STORAGE_SYSTEM

        unitname2['Dependent'] = dependent2
        unitname2['Antecedent'] = antecedent2
        unitname2['CreationClassName'] = PROT_CTRL_UNIT
        unitname2.path = unitname2
        unitnames.append(unitname2)

        return unitnames

    def _ref_storage_sync(self):
        syncnames = []

        cpsessions = {}

        synced = FakeCIMInstanceName()
        synced_keybindings = {}
        synced_keybindings['CreationClassName'] = STOR_VOL
        synced_keybindings['DeviceID'] = FAKE_LUN_ID2
        synced_keybindings['SystemCreationClassName'] = \
            'FUJITSU_StorageComputerSystem'
        synced_keybindings['SystemName'] = STORAGE_SYSTEM
        synced['ClassName'] = STOR_VOL
        synced.keybindings = synced_keybindings
        cpsessions['SyncedElement'] = synced

        system = FakeCIMInstanceName()
        system_keybindings = {}
        system_keybindings['CreationClassName'] = STOR_VOL
        system_keybindings['DeviceID'] = FAKE_LUN_ID1
        system_keybindings['SystemCreationClassName'] = \
            'FUJITSU_StorageComputerSystem'
        system_keybindings['SystemName'] = STORAGE_SYSTEM
        system['ClassName'] = STOR_VOL
        system.keybindings = system_keybindings
        cpsessions['SystemElement'] = system

        cpsessions['classname'] = STOR_SYNC

        syncnames.append(cpsessions)

        return syncnames

    def _default_ref(self, objectpath):
        return objectpath

    def _default_assoc(self, objectpath):
        return objectpath

    def _assocnames_lunmaskctrl(self):
        return self._enum_lunmaskctrls()

    def _assocnames_tcp_endpoint(self):
        return self._enum_tcp_endpoint()

    def _assocnames_afngroup(self):
        return self._enum_afntyservice()

    def _assocnames_volumelist(self, poolpath):
        volumelist = self._enum_volumes(force=True)
        inpool = []
        for vol in volumelist:
            vol_pool = vol.get('poolpath')
            if poolpath['InstanceID'] == vol_pool:
                inpool.append(vol)

        return inpool

    def _assocnames_pool(self, volumepath):
        poollist = self._enum_pool_details('RAID')
        poollist += self._enum_pool_details('TPP')
        volpool = []
        for pool in poollist:
            if volumepath['poolpath'] == pool['InstanceID']:
                volpool.append(pool)

        return volpool

    def _default_assocnames(self, objectpath):
        return objectpath

    def _assoc_authpriv(self):
        authprivs = []
        iscsi = {}
        iscsi['InstanceID'] = ISCSI_INITIATOR
        authprivs.append(iscsi)

        fc = {}
        fc['InstanceID'] = TEST_WWPN[0]
        authprivs.append(fc)

        fc1 = {}
        fc1['InstanceID'] = TEST_WWPN[1]
        authprivs.append(fc1)

        return authprivs

    def _assoc_endpoint(self, objectpath):
        targetlist = []
        tgtport1 = {}
        tgtport1['CreationClassName'] = 'FUJITSU_IPProtocolEndpoint'
        tgtport1['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:0123456789,t,0x0009')
        targetlist.append(tgtport1)

        return targetlist

    def _getinstance_unit(self, objectpath):
        unit = FJ_AffinityGroupController()
        unit.path = None

        if MAP_STAT == '0':
            return unit
        dependent = {}
        dependent['CreationClassName'] = STOR_VOL
        dependent['DeviceID'] = FAKE_LUN_ID1
        dependent['ElementName'] = TEST_VOLUME['name']
        dependent['SystemName'] = STORAGE_SYSTEM

        antecedent = {}
        antecedent['CreationClassName'] = SCSI_PROT_CTR
        antecedent['DeviceID'] = LUNMASKCTRL_IDS[0]
        antecedent['SystemName'] = STORAGE_SYSTEM

        unit['Dependent'] = dependent
        unit['Antecedent'] = antecedent
        unit['CreationClassName'] = PROT_CTRL_UNIT
        unit['DeviceNumber'] = '0'
        unit.path = unit

        return unit

    def _enum_sysnames(self):
        sysnamelist = []
        sysname = {}
        sysname['IdentifyingNumber'] = FAKE_SYSTEM_NAME
        sysnamelist.append(sysname)
        return sysnamelist

    def _enum_confservice(self):
        services = []
        service = {}
        service['Name'] = 'FUJITSU:ETERNUS SMI-S Agent'
        service['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        service['SystemName'] = STORAGE_SYSTEM
        service['CreationClassName'] = 'FUJITSU_StorageConfigurationService'
        services.append(service)
        return services

    def _enum_ctrlservice(self):
        services = []
        service = {}
        service['SystemName'] = STORAGE_SYSTEM
        service['CreationClassName'] = 'FUJITSU_ControllerConfigurationService'
        services.append(service)
        return services

    def _enum_afntyservice(self):
        services = []
        service = {}
        service['SystemName'] = STORAGE_SYSTEM
        service['CreationClassName'] = 'FUJITSU_AffinityGroupController'
        services.append(service)
        return services

    def _enum_repservice(self):
        services = []
        service = {}
        service['Name'] = 'FUJITSU:ETERNUS SMI-S Agent'
        service['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        service['SystemName'] = STORAGE_SYSTEM
        service['CreationClassName'] = 'FUJITSU_ReplicationService'
        services.append(service)
        return services

    def _enum_pools(self):
        pools = []
        pool = {}
        pool['InstanceID'] = 'FUJITSU:RSP0004'
        pool['CreationClassName'] = 'FUJITSU_RAIDStoragePool'
        pools.append(pool)

        pool2 = {}
        pool2['InstanceID'] = 'FUJITSU:TPP0004'
        pool2['CreationClassName'] = 'FUJITSU_ThinProvisioningPool'
        pools.append(pool2)
        return pools

    def _enum_pool_details(self, pooltype):
        pools = []
        pool = FJ_StoragePool()
        pool2 = FJ_StoragePool()

        if pooltype == 'RAID':
            pool['InstanceID'] = 'FUJITSU:RSP0004'
            pool['CreationClassName'] = 'FUJITSU_RAIDStoragePool'
            pool['ElementName'] = 'abcd1234_OSVD'
            pool['TotalManagedSpace'] = FAKE_CAPACITY
            pool['RemainingManagedSpace'] = FAKE_CAPACITY - 1 * units.Gi
            pool.path = FJ_StoragePool()
            pool.path['InstanceID'] = 'FUJITSU:RSP0004'
            pool.path.classname = 'FUJITSU_RAIDStoragePool'
            pools.append(pool)

            pool2['InstanceID'] = 'FUJITSU:RSP0005'
            pool2['CreationClassName'] = 'FUJITSU_RAIDStoragePool'
            pool2['ElementName'] = 'abcd1234_RG'
            pool2['TotalManagedSpace'] = FAKE_CAPACITY
            pool2['RemainingManagedSpace'] = FAKE_CAPACITY - 2 * units.Gi
            pool2.path = FJ_StoragePool()
            pool2.path['InstanceID'] = 'FUJITSU:RSP0005'
            pool2.path.classname = 'FUJITSU_RAIDStoragePool'
            pools.append(pool2)
        else:
            pool['InstanceID'] = 'FUJITSU:TPP0004'
            pool['CreationClassName'] = 'FUJITSU_ThinProvisioningPool'
            pool['ElementName'] = 'abcd1234_TPP'
            pool['TotalManagedSpace'] = FAKE_CAPACITY
            pool['RemainingManagedSpace'] = FAKE_CAPACITY - 1 * units.Gi
            pool.path = FJ_StoragePool()
            pool.path['InstanceID'] = 'FUJITSU:TPP0004'
            pool.path.classname = 'FUJITSU_ThinProvisioningPool'
            pools.append(pool)

        return pools

    def _enum_volumes(self, force=False):
        volumes = []
        if VOL_STAT == '0' and not force:
            return volumes
        volume = FJ_StorageVolume()
        volume['name'] = TEST_VOLUME['name']
        volume['poolpath'] = 'FUJITSU:TPP0004'
        volume['CreationClassName'] = 'FUJITSU_StorageVolume'
        volume['Name'] = FAKE_LUN_ID1
        volume['DeviceID'] = FAKE_LUN_ID1
        volume['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        volume['SystemName'] = STORAGE_SYSTEM
        volume['ElementName'] = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        volume['volume_type_id'] = None
        volume.path = volume
        volume.path.classname = volume['CreationClassName']

        name = {
            'classname': 'FUJITSU_StorageVolume',
            'keybindings': {
                'CreationClassName': 'FUJITSU_StorageVolume',
                'SystemName': STORAGE_SYSTEM,
                'DeviceID': volume['DeviceID'],
                'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
            },
        }
        volume['provider_location'] = str(name)
        volume.path.keybindings = name['keybindings']
        volumes.append(volume)

        volume3 = FJ_StorageVolume()
        volume3['name'] = TEST_VOLUME2['name']
        volume3['poolpath'] = 'FUJITSU:RSP0005'
        volume3['CreationClassName'] = 'FUJITSU_StorageVolume'
        volume3['Name'] = FAKE_LUN_ID3
        volume3['DeviceID'] = FAKE_LUN_ID3
        volume3['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        volume3['SystemName'] = STORAGE_SYSTEM
        volume3['ElementName'] = 'FJosv_4whcadwDac7ANKHA2O719A=='
        volume3['volume_type_id'] = None
        volume3.path = volume3
        volume3.path.classname = volume3['CreationClassName']

        name3 = {
            'classname': 'FUJITSU_StorageVolume',
            'keybindings': {
                'CreationClassName': 'FUJITSU_StorageVolume',
                'SystemName': STORAGE_SYSTEM,
                'DeviceID': volume3['DeviceID'],
                'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
            },
        }
        volume3['provider_location'] = str(name3)
        volume3.path.keybindings = name3['keybindings']
        volumes.append(volume3)

        snap_vol = FJ_StorageVolume()
        snap_vol['name'] = TEST_SNAP['name']
        snap_vol['poolpath'] = 'FUJITSU:RSP0004'
        snap_vol['CreationClassName'] = 'FUJITSU_StorageVolume'
        snap_vol['Name'] = FAKE_LUN_ID2
        snap_vol['DeviceID'] = FAKE_LUN_ID2
        snap_vol['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        snap_vol['SystemName'] = STORAGE_SYSTEM
        snap_vol['ElementName'] = 'FJosv_OgEZj1mSvKRvIKOExKktlg=='
        snap_vol.path = snap_vol
        snap_vol.path.classname = snap_vol['CreationClassName']

        name2 = {
            'classname': 'FUJITSU_StorageVolume',
            'keybindings': {
                'CreationClassName': 'FUJITSU_StorageVolume',
                'SystemName': STORAGE_SYSTEM,
                'DeviceID': snap_vol['DeviceID'],
                'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
            },
        }
        snap_vol['provider_location'] = str(name2)
        snap_vol.path.keybindings = name2['keybindings']
        volumes.append(snap_vol)

        snap_vol2 = FJ_StorageVolume()
        snap_vol2['name'] = TEST_SNAP['name']
        snap_vol2['poolpath'] = 'FUJITSU:TPP0004'
        snap_vol2['CreationClassName'] = 'FUJITSU_StorageVolume'
        snap_vol2['Name'] = FAKE_LUN_ID2
        snap_vol2['DeviceID'] = FAKE_LUN_ID2
        snap_vol2['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        snap_vol2['SystemName'] = STORAGE_SYSTEM
        snap_vol2['ElementName'] = 'FJosv_OgEZj1mSvKRvIKOExKktlg=='
        snap_vol2.path = snap_vol
        snap_vol2.path.classname = snap_vol['CreationClassName']

        name4 = {
            'classname': 'FUJITSU_StorageVolume',
            'keybindings': {
                'CreationClassName': 'FUJITSU_StorageVolume',
                'SystemName': STORAGE_SYSTEM,
                'DeviceID': snap_vol['DeviceID'],
                'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
            },
        }
        snap_vol2['provider_location'] = str(name4)
        volumes.append(snap_vol2)

        clone_vol = FJ_StorageVolume()
        clone_vol['name'] = TEST_CLONE['name']
        clone_vol['poolpath'] = 'FUJITSU:TPP0004'
        clone_vol['CreationClassName'] = 'FUJITSU_StorageVolume'
        clone_vol['ElementName'] = TEST_CLONE['name']
        clone_vol['DeviceID'] = FAKE_LUN_ID2
        clone_vol['SystemName'] = STORAGE_SYSTEM
        clone_vol['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        clone_vol.path = clone_vol
        clone_vol.path.classname = clone_vol['CreationClassName']

        name_clone = {
            'classname': 'FUJITSU_StorageVolume',
            'keybindings': {
                'CreationClassName': 'FUJITSU_StorageVolume',
                'SystemName': STORAGE_SYSTEM,
                'DeviceID': clone_vol['DeviceID'],
                'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
            },
        }
        clone_vol['provider_location'] = str(name_clone)
        clone_vol.path.keybindings = name_clone['keybindings']
        volumes.append(clone_vol)

        return volumes

    def _enum_snapshots(self):
        snapshots = []
        snap = FJ_StorageVolume()
        snap['CreationClassName'] = 'FUJITSU_StorageVolume'
        snap['SystemName'] = STORAGE_SYSTEM
        snap['DeviceID'] = FAKE_LUN_ID2
        snap['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        snap.path = snap
        snap.path.classname = snap['CreationClassName']

        snapshots.append(snap)

        return snapshots

    def _enum_lunmaskctrls(self):
        ctrls = []
        ctrl = {}
        ctrl2 = {}
        if MAP_STAT == '1':
            ctrl['CreationClassName'] = SCSI_PROT_CTR
            ctrl['SystemName'] = STORAGE_SYSTEM
            ctrl['DeviceID'] = LUNMASKCTRL_IDS[0]
            ctrls.append(ctrl)

            ctrl2['CreationClassName'] = SCSI_PROT_CTR
            ctrl2['SystemName'] = STORAGE_SYSTEM
            ctrl2['DeviceID'] = LUNMASKCTRL_IDS[1]
            ctrls.append(ctrl2)

        return ctrls

    def _enum_scsiport_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['Name'] = '1234567890000021'
        tgtport1['CreationClassName'] = 'FUJITSU_SCSIProtocolEndpoint'
        tgtport1['ConnectionType'] = 2
        tgtport1['RAMode'] = 0
        targetlist.append(tgtport1)

        return targetlist

    def _enum_ipproto_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['CreationClassName'] = 'FUJITSU_IPProtocolEndpoint'
        tgtport1['NAME'] = 'IP_CM01CA00P00_00'
        targetlist.append(tgtport1)

        return targetlist

    def _enum_tcp_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['CreationClassName'] = 'FUJITSU_TCPProtocolEndpoint'
        tgtport1['NAME'] = 'TCP_CM01CA00P00_00'
        targetlist.append(tgtport1)

        return targetlist

    def _enum_iscsiprot_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:0123456789,t,0x0009')
        tgtport1['ConnectionType'] = 7
        tgtport1['RAMode'] = 0
        targetlist.append(tgtport1)

        return targetlist

    def _getinstance_storagevolume(self, objpath):
        instance = FJ_StorageVolume()
        volumes = self._enum_volumes()
        for volume in volumes:
            if volume['DeviceID'] == objpath['DeviceID']:
                instance = volume
                break
        if not instance:
            foundinstance = None
        else:
            foundinstance = instance
        return foundinstance

    def _getinstance_ipprotocolendpoint(self, objpath):
        instance = {}
        instance['IPv4Address'] = '10.0.0.3'
        return instance


class FJFCDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJFCDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJFCDriverTestCase, self).setUp()

        # Make fake xml-configuration file.
        self.config_file = tempfile.NamedTemporaryFile("w+", suffix='.xml')
        self.addCleanup(self.config_file.close)
        self.config_file.write(CONF)
        self.config_file.flush()

        # Make fake Object by using mock as configuration object.
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_eternus_config_file = self.config_file.name
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.max_over_subscription_ratio = '20.0'
        self.configuration.fujitsu_use_cli_copy = False

        self.mock_object(dx_common.FJDXCommon, '_get_eternus_connection',
                         self.fake_eternus_connection)

        instancename = FakeCIMInstanceName()
        self.mock_object(dx_common.FJDXCommon, '_create_eternus_instance_name',
                         instancename.fake_create_eternus_instance_name)

        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())

        self.mock_object(dx_common.FJDXCommon, '_get_qos_specs',
                         return_value={})

        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)
        # Set fc driver to self.driver.
        driver = dx_fc.FJDXFCDriver(configuration=self.configuration)
        self.driver = driver

        self.context = context.get_admin_context()

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('expand volume'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('set volume-qos'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
        elif exec_cmdline.startswith('show enclosure-status'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   'ETDX200S3_1\t01\tET203ACU\t4601417434\t280753\t20'
                   '\t00\t00\t01\t02\t01001000\tV10L87-9000\t91\r\n02'
                   '\r\n70000000\t30\r\nD0000100\t30\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show volume-qos'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '0002\t\r\n0000\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg==\t0F'
                   '\t\r\n0001\tFJosv_OgEZj1mSvKRvIKOExKktlg==\t0D'
                   '\t\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show copy-sessions'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n'
                   '0001\tFFFF\t01\t08\tFF\tFF\t03\t02\tFF\tFF\t05ABD7D2\t'
                   '########################################\t'
                   '########################################\t'
                   '00000281\t00000286\t0001\t00\tFF\t0000000000000800\t'
                   '0000000000000000\t0000000000000100\t0000000000000800\t'
                   '04\t00\t00000000\t2020101009341400\t01\t10\tFFFF\tFFFF\t'
                   '0000000000000000\tFFFFFFFFFFFFFFFF\tFFFFFFFFFFFFFFFF\tFF\t'
                   'FF\t64\t00\t07\t00\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show qos-bandwidth-limit'):
            ret = ('\r\nCLI> %s\r\n00\r\n0010\t\r\n00\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff\r\n'
                   '01\t00000001\t00000001\t00000001\t00000001\t00000001'
                   '\t00000001\t00000001\t00000001\t00000001\t00000001'
                   '\t00000001\t00000001\r\n02\t00000002\t00000002\t00000002'
                   '\t00000002\t00000002\t00000002\t00000002\t00000002'
                   '\t00000002\t00000002\t00000002\t00000002\r\n03\t00000003'
                   '\t00000003\t00000003\t00000003\t00000003\t00000003'
                   '\t00000003\t00000003\t00000003\t00000003\t00000003'
                   '\t00000003\r\n04\t00000004\t00000004\t00000004\t00000004'
                   '\t00000004\t00000004\t00000004\t00000004\t00000004'
                   '\t00000004\t00000004\t00000004\r\n05\t00000005\t00000005'
                   '\t00000005\t00000005\t00000005\t00000005\t00000005'
                   '\t00000005\t00000005\t00000005\t00000005\t00000005\r\n06'
                   '\t00000006\t00000006\t00000006\t00000006\t00000006'
                   '\t00000006\t00000006\t00000006\t00000006\t00000006'
                   '\t00000006\t00000006\r\n07\t00000007\t00000007\t00000007'
                   '\t00000007\t00000007\t00000007\t00000007\t00000007'
                   '\t00000007\t00000007\t00000007\t00000007\r\n08\t00000008'
                   '\t00000008\t00000008\t00000008\t00000008\t00000008'
                   '\t00000008\t00000008\t00000008\t00000008\t00000008'
                   '\t00000008\r\n09\t00000009\t00000009\t00000009\t00000009'
                   '\t00000009\t00000009\t00000009\t00000009\t00000009'
                   '\t00000009\t00000009\t00000009\r\n0a\t0000000a\t0000000a'
                   '\t0000000a\t0000000a\t0000000a\t0000000a\t0000000a'
                   '\t0000000a\t0000000a\t0000000a\t0000000a\t0000000a\r\n0b'
                   '\t0000000b\t0000000b\t0000000b\t0000000b\t0000000b'
                   '\t0000000b\t0000000b\t0000000b\t0000000b\t0000000b'
                   '\t0000000b\t0000000b\r\n0c\t0000000c\t0000000c\t0000000c'
                   '\t0000000c\t0000000c\t0000000c\t0000000c\t0000000c'
                   '\t0000000c\t0000000c\t0000000c\t0000000c\r\n0d\t0000000d'
                   '\t0000000d\t0000000d\t0000000d\t0000000d\t0000000d'
                   '\t0000000d\t0000000d\t0000000d\t0000000d\t0000000d'
                   '\t0000000d\r\n0e\t0000000e\t0000000e\t0000000e\t0000000e'
                   '\t0000000e\t0000000e\t0000000e\t0000000e\t0000000e'
                   '\t0000000e\t0000000e\t0000000e\r\n0f\t0000000f\t0000000f'
                   '\t0000000f\t0000000f\t0000000f\t0000000f\t0000000f'
                   '\t0000000f\t0000000f\t0000000f\t0000000f\t0000000f'
                   '\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('set qos-bandwidth-limit'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('stop copy-session'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('start copy-snap-opc'):
            ret = '%s\r\n00\r\n0019\r\nCLI> ' % exec_cmdline
        else:
            ret = None
        return ret

    def fake_safe_get(self, str=None):
        return str

    def fake_eternus_connection(self):
        conn = FakeEternusConnection()
        return conn

    def volume_update(self, volume, diction):
        for key, value in diction.items():
            volume[key] = value

    def test_get_volume_stats(self):
        ret = self.driver.get_volume_stats(True)

        self.assertEqual(FAKE_STATS2, ret)

    def test_create_and_delete_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_volume(TEST_VOLUME2)
        self.volume_update(TEST_VOLUME2, model_info)
        self.assertEqual(FAKE_MODEL_INFO3, model_info)

        self.driver.delete_volume(TEST_VOLUME)
        self.driver.delete_volume(TEST_VOLUME2)

    @mock.patch.object(dx_common.FJDXCommon, '_get_mapdata')
    def test_map_unmap(self, mock_mapdata):
        fake_data = {'target_wwn': FC_TARGET_WWN,
                     'target_lun': 0}

        mock_mapdata.return_value = fake_data
        fake_mapdata = dict(fake_data)
        fake_mapdata['initiator_target_map'] = {
            initiator: FC_TARGET_WWN for initiator in TEST_WWPN
        }

        fake_mapdata['volume_id'] = TEST_VOLUME['id']
        fake_mapdata['target_discovered'] = True
        fake_info = {'driver_volume_type': 'fibre_channel',
                     'data': fake_mapdata}

        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        info = self.driver.initialize_connection(TEST_VOLUME,
                                                 TEST_CONNECTOR)
        self.assertEqual(fake_info, info)
        # Call terminate_connection with connector.
        self.driver.terminate_connection(TEST_VOLUME,
                                         TEST_CONNECTOR)

        info = self.driver.initialize_connection(TEST_VOLUME,
                                                 TEST_CONNECTOR)
        self.assertEqual(fake_info, info)
        # Call terminate_connection without connector.
        self.driver.terminate_connection(TEST_VOLUME,
                                         None)

        self.driver.delete_volume(TEST_VOLUME)

    def test_create_and_delete_snapshot_using_smis(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    @mock.patch.object(dx_common, 'LOG')
    def test_create_and_delete_snapshot_using_cli(self, mock_log):
        self.configuration.fujitsu_use_cli_copy = True
        driver = dx_fc.FJDXFCDriver(configuration=self.configuration)
        self.driver = driver

        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        warning_msg = '_create_snapshot, Can not create SDV by SMI-S.'
        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO2, snap_info)
        mock_log.warning.assert_called_with(warning_msg)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        model_info = self.driver.create_volume_from_snapshot(TEST_CLONE,
                                                             TEST_SNAP)
        self.volume_update(TEST_CLONE, model_info)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.volume_update(TEST_CLONE, model_info)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        # Test the extension of volume created on RaidGroup and
        # ThinProvisioningPool separately.
        TEST_VOLUME_LIST = [TEST_VOLUME, TEST_VOLUME2]
        FAKE_MODEL_INFO_LIST = [FAKE_MODEL_INFO1, FAKE_MODEL_INFO3]
        for i in range(len(TEST_VOLUME_LIST)):
            model_info = self.driver.create_volume(TEST_VOLUME_LIST[i])
            self.volume_update(TEST_VOLUME_LIST[i], model_info)
            self.assertEqual(FAKE_MODEL_INFO_LIST[i], model_info)

            self.driver.extend_volume(TEST_VOLUME_LIST[i], 10)

    def test_create_volume_with_qos(self):
        self.driver.common._get_qos_specs = mock.Mock()
        self.driver.common._get_qos_specs.return_value = {'maxBWS': '700'}
        self.driver.common._set_qos = mock.Mock()
        model_info = self.driver.create_volume(TEST_VOLUME_QOS)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO_QOS, model_info)
        self.driver.common._set_qos.assert_called()

    def test_update_migrated_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info2 = self.driver.create_volume(TEST_VOLUME2)
        self.volume_update(TEST_VOLUME2, model_info2)
        self.assertEqual(FAKE_MODEL_INFO3, model_info2)

        model_update = self.driver.update_migrated_volume(self.context,
                                                          TEST_VOLUME,
                                                          TEST_VOLUME2,
                                                          'available')

        FAKE_MIGRATED_MODEL_UPDATE = {
            '_name_id': TEST_VOLUME2['id'],
            'provider_location': model_info2['provider_location']
        }
        self.assertEqual(FAKE_MIGRATED_MODEL_UPDATE, model_update)

    def test_revert_to_snapshot(self):
        self.driver.common.revert_to_snapshot = mock.Mock()
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.revert_to_snapshot(self.context,
                                       TEST_VOLUME,
                                       TEST_SNAP)

        self.driver.common.revert_to_snapshot.assert_called_with(TEST_VOLUME,
                                                                 TEST_SNAP)


class FJISCSIDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJISCSIDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJISCSIDriverTestCase, self).setUp()

        # Make fake xml-configuration file.
        self.config_file = tempfile.NamedTemporaryFile("w+", suffix='.xml')
        self.addCleanup(self.config_file.close)
        self.config_file.write(CONF)
        self.config_file.flush()

        # Make fake Object by using mock as configuration object.
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_eternus_config_file = self.config_file.name
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.max_over_subscription_ratio = '20.0'
        self.configuration.fujitsu_use_cli_copy = False

        self.mock_object(dx_common.FJDXCommon, '_get_eternus_connection',
                         self.fake_eternus_connection)

        instancename = FakeCIMInstanceName()
        self.mock_object(dx_common.FJDXCommon, '_create_eternus_instance_name',
                         instancename.fake_create_eternus_instance_name)

        self.mock_object(dx_common.FJDXCommon, '_get_mapdata_iscsi',
                         self.fake_get_mapdata)

        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())

        self.mock_object(dx_common.FJDXCommon, '_get_qos_specs',
                         return_value={})

        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)
        # Set iscsi driver to self.driver.
        driver = dx_iscsi.FJDXISCSIDriver(configuration=self.configuration)
        self.driver = driver

        self.context = context.get_admin_context()

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('expand volume'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('set volume-qos'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
        elif exec_cmdline.startswith('show enclosure-status'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   'ETDX200S3_1\t01\tET203ACU\t4601417434\t280753\t20'
                   '\t00\t00\t01\t02\t01001000\tV10L87-9000\t91\r\n02'
                   '\r\n70000000\t30\r\nD0000100\t30\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show volume-qos'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '0002\t\r\n0000\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg==\t0F'
                   '\t\r\n0001\tFJosv_OgEZj1mSvKRvIKOExKktlg==\t0D'
                   '\t\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show copy-sessions'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n'
                   '0001\tFFFF\t01\t08\tFF\tFF\t03\t02\tFF\tFF\t05ABD7D2\t'
                   '########################################\t'
                   '########################################\t'
                   '00000281\t00000286\t0001\t00\tFF\t0000000000000800\t'
                   '0000000000000000\t0000000000000100\t0000000000000800\t'
                   '04\t00\t00000000\t2020101009341400\t01\t10\tFFFF\tFFFF\t'
                   '0000000000000000\tFFFFFFFFFFFFFFFF\tFFFFFFFFFFFFFFFF\tFF\t'
                   'FF\t64\t00\t07\t00\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show qos-bandwidth-limit'):
            ret = ('\r\nCLI> %s\r\n00\r\n0010\t\r\n00\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff\r\n'
                   '01\t00000001\t00000001\t00000001\t00000001\t00000001'
                   '\t00000001\t00000001\t00000001\t00000001\t00000001'
                   '\t00000001\t00000001\r\n02\t00000002\t00000002\t00000002'
                   '\t00000002\t00000002\t00000002\t00000002\t00000002'
                   '\t00000002\t00000002\t00000002\t00000002\r\n03\t00000003'
                   '\t00000003\t00000003\t00000003\t00000003\t00000003'
                   '\t00000003\t00000003\t00000003\t00000003\t00000003'
                   '\t00000003\r\n04\t00000004\t00000004\t00000004\t00000004'
                   '\t00000004\t00000004\t00000004\t00000004\t00000004'
                   '\t00000004\t00000004\t00000004\r\n05\t00000005\t00000005'
                   '\t00000005\t00000005\t00000005\t00000005\t00000005'
                   '\t00000005\t00000005\t00000005\t00000005\t00000005\r\n06'
                   '\t00000006\t00000006\t00000006\t00000006\t00000006'
                   '\t00000006\t00000006\t00000006\t00000006\t00000006'
                   '\t00000006\t00000006\r\n07\t00000007\t00000007\t00000007'
                   '\t00000007\t00000007\t00000007\t00000007\t00000007'
                   '\t00000007\t00000007\t00000007\t00000007\r\n08\t00000008'
                   '\t00000008\t00000008\t00000008\t00000008\t00000008'
                   '\t00000008\t00000008\t00000008\t00000008\t00000008'
                   '\t00000008\r\n09\t00000009\t00000009\t00000009\t00000009'
                   '\t00000009\t00000009\t00000009\t00000009\t00000009'
                   '\t00000009\t00000009\t00000009\r\n0a\t0000000a\t0000000a'
                   '\t0000000a\t0000000a\t0000000a\t0000000a\t0000000a'
                   '\t0000000a\t0000000a\t0000000a\t0000000a\t0000000a\r\n0b'
                   '\t0000000b\t0000000b\t0000000b\t0000000b\t0000000b'
                   '\t0000000b\t0000000b\t0000000b\t0000000b\t0000000b'
                   '\t0000000b\t0000000b\r\n0c\t0000000c\t0000000c\t0000000c'
                   '\t0000000c\t0000000c\t0000000c\t0000000c\t0000000c'
                   '\t0000000c\t0000000c\t0000000c\t0000000c\r\n0d\t0000000d'
                   '\t0000000d\t0000000d\t0000000d\t0000000d\t0000000d'
                   '\t0000000d\t0000000d\t0000000d\t0000000d\t0000000d'
                   '\t0000000d\r\n0e\t0000000e\t0000000e\t0000000e\t0000000e'
                   '\t0000000e\t0000000e\t0000000e\t0000000e\t0000000e'
                   '\t0000000e\t0000000e\t0000000e\r\n0f\t0000000f\t0000000f'
                   '\t0000000f\t0000000f\t0000000f\t0000000f\t0000000f'
                   '\t0000000f\t0000000f\t0000000f\t0000000f\t0000000f'
                   '\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('set qos-bandwidth-limit'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('start copy-snap-opc'):
            ret = '%s\r\n00\r\n0019\r\nCLI> ' % exec_cmdline
        else:
            ret = None
        return ret

    def fake_safe_get(self, str=None):
        return str

    def fake_eternus_connection(self):
        conn = FakeEternusConnection()
        return conn

    def fake_get_mapdata(self, vol_instance, connector, target_portlist):
        multipath = connector.get('multipath', False)
        if multipath:
            return {'target_portals': [ISCSI_TARGET_IP],
                    'target_iqns': [ISCSI_TARGET_IQN],
                    'target_luns': [0]}
        else:
            return {'target_portal': ISCSI_TARGET_IP,
                    'target_iqns': ISCSI_TARGET_IQN,
                    'target_lun': 0}

    def volume_update(self, volume, diction):
        for key, value in diction.items():
            volume[key] = value

    def test_get_volume_stats(self):
        ret = self.driver.get_volume_stats(True)

        self.assertEqual(FAKE_STATS, ret)

    def test_create_and_delete_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_volume(TEST_VOLUME2)
        self.volume_update(TEST_VOLUME2, model_info)
        self.assertEqual(FAKE_MODEL_INFO3, model_info)

        self.driver.delete_volume(TEST_VOLUME)
        self.driver.delete_volume(TEST_VOLUME2)

    def test_map_unmap(self):
        fake_mapdata = self.fake_get_mapdata(None, {}, None)
        fake_mapdata['volume_id'] = TEST_VOLUME['id']
        fake_mapdata['target_discovered'] = True
        fake_info = {'driver_volume_type': 'iscsi',
                     'data': fake_mapdata}

        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        info = self.driver.initialize_connection(TEST_VOLUME,
                                                 TEST_CONNECTOR)
        self.assertEqual(fake_info, info)
        # Call terminate_connection with connector.
        self.driver.terminate_connection(TEST_VOLUME,
                                         TEST_CONNECTOR)

        info = self.driver.initialize_connection(TEST_VOLUME,
                                                 TEST_CONNECTOR)
        self.assertEqual(fake_info, info)
        # Call terminate_connection without connector.
        self.driver.terminate_connection(TEST_VOLUME,
                                         None)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_and_delete_snapshot_using_smis(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    @mock.patch.object(dx_common, 'LOG')
    def test_create_and_delete_snapshot_using_cli(self, mock_log):
        self.configuration.fujitsu_use_cli_copy = True
        driver = dx_fc.FJDXFCDriver(configuration=self.configuration)
        self.driver = driver

        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        warning_msg = '_create_snapshot, Can not create SDV by SMI-S.'
        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO2, snap_info)
        mock_log.warning.assert_called_with(warning_msg)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        model_info = self.driver.create_volume_from_snapshot(TEST_CLONE,
                                                             TEST_SNAP)
        self.volume_update(TEST_CLONE, model_info)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.volume_update(TEST_CLONE, model_info)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        # Test the extension of volume created on RaidGroup and
        # ThinProvisioningPool separately.
        TEST_VOLUME_LIST = [TEST_VOLUME, TEST_VOLUME2]
        FAKE_MODEL_INFO_LIST = [FAKE_MODEL_INFO1, FAKE_MODEL_INFO3]
        for i in range(len(TEST_VOLUME_LIST)):
            model_info = self.driver.create_volume(TEST_VOLUME_LIST[i])
            self.volume_update(TEST_VOLUME_LIST[i], model_info)
            self.assertEqual(FAKE_MODEL_INFO_LIST[i], model_info)

            self.driver.extend_volume(TEST_VOLUME_LIST[i], 10)

    def test_create_volume_with_qos(self):
        self.driver.common._get_qos_specs = mock.Mock()
        self.driver.common._get_qos_specs.return_value = {'maxBWS': '700'}
        self.driver.common._set_qos = mock.Mock()
        model_info = self.driver.create_volume(TEST_VOLUME_QOS)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO_QOS, model_info)
        self.driver.common._set_qos.assert_called()

    def test_update_migrated_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info2 = self.driver.create_volume(TEST_VOLUME2)
        self.volume_update(TEST_VOLUME2, model_info2)
        self.assertEqual(FAKE_MODEL_INFO3, model_info2)

        model_update = self.driver.update_migrated_volume(self.context,
                                                          TEST_VOLUME,
                                                          TEST_VOLUME2,
                                                          'available')

        FAKE_MIGRATED_MODEL_UPDATE = {
            '_name_id': TEST_VOLUME2['id'],
            'provider_location': model_info2['provider_location']
        }
        self.assertEqual(FAKE_MIGRATED_MODEL_UPDATE, model_update)

    def test_revert_to_snapshot(self):
        self.driver.common.revert_to_snapshot = mock.Mock()
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.volume_update(TEST_SNAP, snap_info)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.revert_to_snapshot(self.context,
                                       TEST_VOLUME,
                                       TEST_SNAP)

        self.driver.common.revert_to_snapshot.assert_called_with(TEST_VOLUME,
                                                                 TEST_SNAP)


class FJCLITestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJCLITestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJCLITestCase, self).setUp()
        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())
        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)

        cli = eternus_dx_cli.FJDXCLI(user=TEST_USER,
                                     storage_ip=STORAGE_IP,
                                     password=TEST_PASSWORD)
        self.cli = cli

    def create_fake_options(self, **kwargs):
        # Create options for CLI command.
        FAKE_OPTION_DICT = {}
        for key, value in kwargs.items():
            processed_key = key.replace('_', '-')
            FAKE_OPTION_DICT[processed_key] = value
        FAKE_OPTION = {**FAKE_OPTION_DICT}
        return FAKE_OPTION

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('expand volume'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('set volume-qos'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF\r\n0001\tFJosv_OgEZj1mSvKRvIKOExKktlg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_OSVD'
                   '\t0000000000200000\t00\t00\t00000000'
                   '\t0050\tFF\t00\tFF\tFF\t20\tFF\tFFFF'
                   '\t00\t600000E00D2A0000002A0115001E0000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
        elif exec_cmdline.startswith('show enclosure-status'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   'ETDX200S3_1\t01\tET203ACU\t4601417434\t280753\t20'
                   '\t00\t00\t01\t02\t01001000\tV10L87-9000\t91\r\n02'
                   '\r\n70000000\t30\r\nD0000100\t30\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show volume-qos'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '0001\r\n0000\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg==\t01\t00\t00'
                   '\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show copy-sessions'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n'
                   '0001\tFFFF\t01\t08\tFF\tFF\t03\t02\tFF\tFF\t05ABD7D2\t'
                   '########################################\t'
                   '########################################\t'
                   '00000281\t00000286\t0001\t00\tFF\t0000000000000800\t'
                   '0000000000000000\t0000000000000100\t0000000000000800\t'
                   '04\t00\t00000000\t2020101009341400\t01\t10\tFFFF\tFFFF\t'
                   '0000000000000000\tFFFFFFFFFFFFFFFF\tFFFFFFFFFFFFFFFF\tFF\t'
                   'FF\t64\t00\t07\t00\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show qos-bandwidth-limit'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n00\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff\r\n'
                   'CLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('set qos-bandwidth-limit'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('stop copy-session'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('delete volume'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('start copy-snap-opc'):
            ret = '%s\r\n00\r\n0019\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('start copy-opc'):
            ret = '%s\r\n00\r\n0019\r\nCLI> ' % exec_cmdline
        else:
            ret = None
        return ret

    @mock.patch.object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus')
    def test_create_error_message(self, mock_exec_cli_with_eternus):
        expected_error_value = {'message': ['-bandwidth-limit', 'asdf'],
                                'rc': 'E8101',
                                'result': 0}

        FAKE_VOLUME_NAME = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        FAKE_BANDWIDTH_LIMIT = 'abcd'
        FAKE_QOS_OPTION = self.create_fake_options(
            volume_name=FAKE_VOLUME_NAME,
            bandwidth_limit=FAKE_BANDWIDTH_LIMIT)

        error_cli_output = ('\r\nCLI> set volume-qos -volume-name %s '
                            '-bandwidth-limit %s\r\n'
                            '01\r\n8101\r\n-bandwidth-limit\r\nasdf\r\n'
                            'CLI> ' % (FAKE_VOLUME_NAME, FAKE_BANDWIDTH_LIMIT))
        mock_exec_cli_with_eternus.return_value = error_cli_output

        error_qos_output = self.cli._set_volume_qos(**FAKE_QOS_OPTION)

        self.assertEqual(expected_error_value, error_qos_output)

    def test_get_options(self):
        expected_option = " -bandwidth-limit 2"
        option = {"bandwidth-limit": 2}
        ret = self.cli._get_option(**option)
        self.assertEqual(expected_option, ret)

    def test_done_and_default_func(self):
        # Test function 'done' and '_default_func' in CLI file.
        self.cli.CMD_dic['check_user_role'] = mock.Mock()
        self.cli._default_func = mock.Mock(
            side_effect=Exception('Invalid function is specified'))

        cmd1 = 'check_user_role'
        self.cli.done(cmd1)
        self.cli.CMD_dic['check_user_role'].assert_called_with()

        cmd2 = 'test_run_cmd'
        cli_ex = None
        try:
            self.cli.done(cmd2)
        except Exception as ex:
            cli_ex = ex
        finally:
            self.cli._default_func.assert_called()
            self.assertEqual(str(cli_ex), "Invalid function is specified")

    def test_check_user_role(self):
        FAKE_ROLE = {**FAKE_CLI_OUTPUT, 'message': 'Software'}

        role = self.cli._check_user_role()
        self.assertEqual(FAKE_ROLE, role)

    def test_expand_volume(self):
        FAKE_VOLME_NAME = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        FAKE_RG_NAME = 'abcd1234_RG'
        FAKE_SIZE = '10gb'
        FAKE_EXPAND_OPTION = self.create_fake_options(
            volume_name=FAKE_VOLME_NAME,
            rg_name=FAKE_RG_NAME,
            size=FAKE_SIZE)

        EXPAND_OUTPUT = self.cli._expand_volume(**FAKE_EXPAND_OPTION)
        FAKE_EXPAND_OUTPUT = {**FAKE_CLI_OUTPUT, 'message': []}
        self.assertEqual(FAKE_EXPAND_OUTPUT, EXPAND_OUTPUT)

    def test_set_volume_qos(self):
        FAKE_VOLUME_NAME = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        FAKE_BANDWIDTH_LIMIT = 2
        FAKE_QOS_OPTION = self.create_fake_options(
            volume_name=FAKE_VOLUME_NAME,
            bandwidth_limit=FAKE_BANDWIDTH_LIMIT)

        FAKE_VOLUME_NUMBER = ['0001']
        FAKE_QOS_OUTPUT = {**FAKE_CLI_OUTPUT, 'message': FAKE_VOLUME_NUMBER}

        volume_number = self.cli._set_volume_qos(**FAKE_QOS_OPTION)
        self.assertEqual(FAKE_QOS_OUTPUT, volume_number)

    def test_show_copy_sessions(self):
        FAKE_COPY_SESSION = [{
            'Source Num': 641,
            'Dest Num': 646,
            'Type': 'Snap',
            'Status': 'Active',
            'Phase': 'Tracking',
            'Session ID': 1,
        }]
        FAKE_COPY_SESSION_OUTPUT = {**FAKE_CLI_OUTPUT,
                                    'message': FAKE_COPY_SESSION}

        cpdatalist = self.cli._show_copy_sessions()
        self.assertEqual(FAKE_COPY_SESSION_OUTPUT, cpdatalist)

    def test_show_pool_provision(self):
        FAKE_POOL_PROVIOSN_OPTION = self.create_fake_options(
            pool_name='abcd1234_TPP')

        FAKE_PROVISION = {**FAKE_CLI_OUTPUT, 'message': 2048.0}

        proviosn = self.cli._show_pool_provision(**FAKE_POOL_PROVIOSN_OPTION)
        self.assertEqual(FAKE_PROVISION, proviosn)

    def test_show_qos_bandwidth_limit(self):
        FAKE_QOS_BANDWIDTH_LIMIT = {'read_bytes_sec': 65535,
                                    'read_iops_sec': 65535,
                                    'read_limit': 0,
                                    'total_bytes_sec': 65535,
                                    'total_iops_sec': 65535,
                                    'total_limit': 0,
                                    'write_bytes_sec': 65535,
                                    'write_iops_sec': 65535,
                                    'write_limit': 0}
        FAKE_QOS_LIST = {**FAKE_CLI_OUTPUT,
                         'message': [FAKE_QOS_BANDWIDTH_LIMIT]}

        qos_list = self.cli._show_qos_bandwidth_limit()
        self.assertEqual(FAKE_QOS_LIST, qos_list)

    def test_set_qos_bandwidth_limit(self):
        FAKE_VOLUME_NAME = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        FAKE_READ_BANDWIDTH_LIMIT = 2
        FAKE_WRITE_BANDWIDTH_LIMIT = 3
        FAKE_QOS_OPTION = self.create_fake_options(
            volume_name=FAKE_VOLUME_NAME,
            read_bandwidth_limit=FAKE_READ_BANDWIDTH_LIMIT,
            write_bandwidth_limit=FAKE_WRITE_BANDWIDTH_LIMIT)

        FAKE_VOLUME_NUMBER = ['0001']
        FAKE_QOS_OUTPUT = {**FAKE_CLI_OUTPUT, 'message': FAKE_VOLUME_NUMBER}

        volume_number = self.cli._set_qos_bandwidth_limit(**FAKE_QOS_OPTION)
        self.assertEqual(FAKE_QOS_OUTPUT, volume_number)

    def test_show_volume_qos(self):
        FAKE_VOLUME_QOS = {'total_limit': 1,
                           'read_limit': 0,
                           'write_limit': 0}
        FAKE_VQOS_DATA_LIST = {**FAKE_CLI_OUTPUT,
                               'message': [FAKE_VOLUME_QOS]}

        vqos_datalist = self.cli._show_volume_qos()
        self.assertEqual(FAKE_VQOS_DATA_LIST, vqos_datalist)

    def test_show_enclosure_status(self):
        FAKE_VERSION = 'V10L87-9000'
        FAKE_VERSION_INFO = {**FAKE_CLI_OUTPUT,
                             'message': {'version': FAKE_VERSION}}

        versioninfo = self.cli._show_enclosure_status()
        self.assertEqual(FAKE_VERSION_INFO, versioninfo)

    def test_start_copy_snap_opc(self):
        FAKE_SNAP_OPC_OPTION = self.create_fake_options(
            mode='normal',
            source_volume_number=31,
            destination_volume_number=39,
            source_lba=0,
            destination=0,
            size=1
        )

        FAKE_OPC_ID = '0019'
        FAKE_OPC_INFO = {**FAKE_CLI_OUTPUT,
                         'message': [FAKE_OPC_ID]}

        opc_id = self.cli._start_copy_snap_opc(**FAKE_SNAP_OPC_OPTION)
        self.assertEqual(FAKE_OPC_INFO, opc_id)

    def test_stop_copy_session(self):
        FAKE_SESSION_ID = '0001'
        FAKE_STOP_OUTPUT = {**FAKE_CLI_OUTPUT, 'message': []}
        FAKE_STOP_COPY_SESSION_OPTION = self.create_fake_options(
            session_id=FAKE_SESSION_ID)
        stop_output = self.cli._stop_copy_session(
            **FAKE_STOP_COPY_SESSION_OPTION)
        self.assertEqual(FAKE_STOP_OUTPUT, stop_output)

    def test_start_copy_opc(self):
        FAKE_SNAP_OPC_OPTION = self.create_fake_options(
            source_volume_number=31,
            destination_volume_number=39,
        )

        FAKE_OPC_ID = '0019'
        FAKE_OPC_INFO = {**FAKE_CLI_OUTPUT,
                         'message': [FAKE_OPC_ID]}

        opc_id = self.cli._start_copy_opc(**FAKE_SNAP_OPC_OPTION)
        self.assertEqual(FAKE_OPC_INFO, opc_id)

    def test_delete_volume(self):
        FAKE_VOLUME_NAME = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        FAKE_DELETE_OUTPUT = {**FAKE_CLI_OUTPUT, 'message': []}
        FAKE_DELETE_VOLUME_OPTION = self.create_fake_options(
            volume_name=FAKE_VOLUME_NAME)

        delete_output = self.cli._delete_volume(**FAKE_DELETE_VOLUME_OPTION)
        self.assertEqual(FAKE_DELETE_OUTPUT, delete_output)


class FJCommonTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJCommonTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJCommonTestCase, self).setUp()

        # Make fake xml-configuration file.
        self.config_file = tempfile.NamedTemporaryFile("w+", suffix='.xml')
        self.addCleanup(self.config_file.close)
        self.config_file.write(CONF)
        self.config_file.flush()

        # Make fake Object by using mock as configuration object.
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_eternus_config_file = self.config_file.name
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.max_over_subscription_ratio = '20.0'
        self.configuration.fujitsu_use_cli_copy = False

        self.mock_object(dx_common.FJDXCommon, '_get_eternus_connection',
                         self.fake_eternus_connection)

        instancename = FakeCIMInstanceName()
        self.mock_object(dx_common.FJDXCommon, '_create_eternus_instance_name',
                         instancename.fake_create_eternus_instance_name)

        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())

        self.mock_object(dx_common.FJDXCommon, '_get_qos_specs',
                         return_value={})

        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)
        # Set iscsi driver to self.driver.
        driver = dx_iscsi.FJDXISCSIDriver(configuration=self.configuration)
        self.driver = driver

        self.context = context.get_admin_context()

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('set volume-qos'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF\r\n0001\tFJosv_OgEZj1mSvKRvIKOExKktlg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_OSVD'
                   '\t0000000000200000\t00\t00\t00000000'
                   '\t0050\tFF\t00\tFF\tFF\t20\tFF\tFFFF'
                   '\t00\t600000E00D2A0000002A0115001E0000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
        elif exec_cmdline.startswith('show enclosure-status'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   'ETDX200S3_1\t01\tET203ACU\t4601417434\t280753\t20'
                   '\t00\t00\t01\t02\t01001000\tV10L87-9000\t91\r\n02'
                   '\r\n70000000\t30\r\nD0000100\t30\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show volume-qos'):
            ret = ('\r\nCLI> %s\r\n00\r\n'
                   '0001\r\n0000\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg==\t01\t00\t00'
                   '\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show copy-sessions'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n'
                   '0001\tFFFF\t01\t08\tFF\tFF\t03\t02\tFF\tFF\t05ABD7D2\t'
                   '########################################\t'
                   '########################################\t'
                   '00000281\t00000286\t0001\t00\tFF\t0000000000000800\t'
                   '0000000000000000\t0000000000000100\t0000000000000800\t'
                   '04\t00\t00000000\t2020101009341400\t01\t10\tFFFF\tFFFF\t'
                   '0000000000000000\tFFFFFFFFFFFFFFFF\tFFFFFFFFFFFFFFFF\tFF\t'
                   'FF\t64\t00\t07\t00\t00\t00\r\nCLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('show qos-bandwidth-limit'):
            ret = ('\r\nCLI> %s\r\n00\r\n0001\t\r\n00\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff'
                   '\t0000ffff\t0000ffff\t0000ffff\t0000ffff\t0000ffff\r\n'
                   'CLI> ' % exec_cmdline)
        elif exec_cmdline.startswith('set qos-bandwidth-limit'):
            ret = '%s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        elif exec_cmdline.startswith('stop copy-session'):
            ret = '%s\r\n00\r\nCLI> ' % exec_cmdline
        else:
            ret = None
        return ret

    def fake_safe_get(self, str=None):
        return str

    def fake_eternus_connection(self):
        conn = FakeEternusConnection()
        return conn

    def test_get_volume_number(self):
        vol_instance = FakeCIMInstanceName()
        vol_instance['ElementName'] = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        vol_instance['Purpose'] = '00228+0x06'
        vol_instance['Name'] = None
        vol_instance['DeviceID'] = FAKE_LUN_ID1
        vol_instance['SystemName'] = STORAGE_SYSTEM
        vol_instance.path = ''
        vol_instance.classname = 'FUJITSU_StorageVolume'

        volume_no = self.driver.common._get_volume_number(vol_instance)
        self.assertEqual(FAKE_LUN_NO1, volume_no)

    def volume_update(self, volume, diction):
        for key, value in diction.items():
            volume[key] = value

    def test_get_eternus_model(self):
        ETERNUS_MODEL = self.driver.common._get_eternus_model()
        self.assertEqual(3, ETERNUS_MODEL)

    def test_get_matadata(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        TEST_METADATA = self.driver.common.get_metadata(TEST_VOLUME)
        self.assertEqual(FAKE_LUN_META1, TEST_METADATA)

    def test_is_qos_or_format_support(self):
        QOS_SUPPORT = \
            self.driver.common._is_qos_or_format_support('QOS setting')
        self.assertTrue(QOS_SUPPORT)

    def test_get_qos_category_by_value(self):
        FAKE_QOS_KEY = 'maxBWS'
        FAKE_QOS_VALUE = 700
        FAKE_QOS_DICT = {'bandwidth-limit': 2}
        QOS_Category_Dict = self.driver.common._get_qos_category_by_value(
            FAKE_QOS_KEY, FAKE_QOS_VALUE)
        self.assertEqual(FAKE_QOS_DICT, QOS_Category_Dict)

    def test_get_param(self):
        FAKE_QOS_SPEC_DICT = {'total_bytes_sec': 2137152,
                              'read_bytes_sec': 1068576,
                              'unspport_key': 1234}
        EXPECTED_KEY_DICT = {'read_bytes_sec': int(FAKE_QOS_SPEC_DICT
                                                   ['read_bytes_sec'] /
                                                   units.Mi),
                             'read_iops_sec': MAX_IOPS,
                             'total_bytes_sec': int(FAKE_QOS_SPEC_DICT
                                                    ['total_bytes_sec'] /
                                                    units.Mi),
                             'total_iops_sec': MAX_IOPS}
        KEY_DICT = self.driver.common._get_param(FAKE_QOS_SPEC_DICT)
        self.assertEqual(EXPECTED_KEY_DICT, KEY_DICT)

    def test_check_iops(self):
        FAKE_QOS_KEY = 'total_iops_sec'
        FAKE_QOS_VALUE = 2137152
        QOS_VALUE = self.driver.common._check_iops(FAKE_QOS_KEY,
                                                   FAKE_QOS_VALUE)
        self.assertEqual(FAKE_QOS_VALUE, QOS_VALUE)

    def test_check_throughput(self):
        FAKE_QOS_KEY = 'total_bytes_sec'
        FAKE_QOS_VALUE = 2137152
        QOS_VALUE = self.driver.common._check_throughput(FAKE_QOS_KEY,
                                                         FAKE_QOS_VALUE)
        self.assertEqual(int(FAKE_QOS_VALUE / units.Mi),
                         QOS_VALUE)

    def test_get_qos_category(self):
        FAKE_QOS_SPEC_DICT = {'total_bytes_sec': 2137152,
                              'read_bytes_sec': 1068576}
        FAKE_KEY_DICT = {'read_bytes_sec': int(FAKE_QOS_SPEC_DICT
                                               ['read_bytes_sec'] /
                                               units.Mi),
                         'read_iops_sec': MAX_IOPS,
                         'total_bytes_sec': int(FAKE_QOS_SPEC_DICT
                                                ['total_bytes_sec'] /
                                                units.Mi),
                         'total_iops_sec': MAX_IOPS}
        FAKE_RET_DICT = {'bandwidth-limit': FAKE_KEY_DICT['total_bytes_sec'],
                         'read-bandwidth-limit':
                             FAKE_KEY_DICT['read_bytes_sec'],
                         'write-bandwidth-limit': 0}
        RET_DICT = self.driver.common._get_qos_category(FAKE_KEY_DICT)
        self.assertEqual(FAKE_RET_DICT, RET_DICT)

    @mock.patch.object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus')
    def test_set_limit(self, mock_exec_cli_with_eternus):
        exec_cmdline = 'set qos-bandwidth-limit -mode volume-qos ' \
                       '-bandwidth-limit 5 -iops 10000 -throughput 450'
        mock_exec_cli_with_eternus.return_value = \
            '\r\nCLI> %s\r\n00\r\n0001\r\nCLI> ' % exec_cmdline
        FAKE_MODE = 'volume-qos'
        FAKE_LIMIT = 5
        FAKE_IOPS = 10000
        FAKE_THROUGHOUTPUT = 450
        self.driver.common._set_limit(FAKE_MODE, FAKE_LIMIT,
                                      FAKE_IOPS, FAKE_THROUGHOUTPUT)
        mock_exec_cli_with_eternus.assert_called_with(exec_cmdline)

    def test_get_copy_sessions_list(self):
        FAKE_COPY_SESSION = [{
            'Source Num': 641,
            'Dest Num': 646,
            'Type': 'Snap',
            'Status': 'Active',
            'Phase': 'Tracking',
            'Session ID': 1,
        }]
        copy_session_list = self.driver.common._get_copy_sessions_list()
        self.assertEqual(FAKE_COPY_SESSION, copy_session_list)

    def test_update_migrated_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info2 = self.driver.create_volume(TEST_VOLUME2)
        self.volume_update(TEST_VOLUME2, model_info2)
        self.assertEqual(FAKE_MODEL_INFO3, model_info2)

        model_update = self.driver.common.update_migrated_volume(self.context,
                                                                 TEST_VOLUME,
                                                                 TEST_VOLUME2)

        FAKE_MIGRATED_MODEL_UPDATE = {
            '_name_id': TEST_VOLUME2['id'],
            'provider_location': model_info2['provider_location']
        }
        self.assertEqual(FAKE_MIGRATED_MODEL_UPDATE, model_update)

    def test_create_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.volume_update(TEST_VOLUME, model_info)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.common._create_snapshot(TEST_SNAP)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.delete_volume(TEST_VOLUME)
