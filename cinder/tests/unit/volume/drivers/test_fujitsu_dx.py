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
import six

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

ISCSI_INITIATOR = 'iqn.1993-08.org.debian:01:8261afe17e4c'
ISCSI_TARGET_IP = '10.0.0.3'
ISCSI_TARGET_IQN = 'iqn.2000-09.com.fujitsu:storage-system.eternus-dxl:0'
FC_TARGET_WWN = ['500000E0DA000001', '500000E0DA000002']
TEST_WWPN = ['0123456789111111', '0123456789222222']
TEST_CONNECTOR = {'initiator': ISCSI_INITIATOR, 'wwpns': TEST_WWPN}


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
# Volume1 in pool abcd1234_TPP
FAKE_LUN_ID1 = '600000E00D2A0000002A011500140000'
FAKE_LUN_NO1 = '0x0014'
# Snapshot1 in pool abcd1234_OSVD
FAKE_LUN_ID2 = '600000E00D2A0000002A0115001E0000'
FAKE_LUN_NO2 = '0x001E'
# Volume2 in pool abcd1234_RG
FAKE_LUN_ID3 = '600000E00D2800000028075301140000'
FAKE_LUN_NO3 = '0x0114'
FAKE_SYSTEM_NAME = 'ET603SA4621302115'
# abcd1234_TPP pool
FAKE_USEGB = 2.0
# abcd1234_RG pool
FAKE_USEGB2 = 1.0
FAKE_POOLS = [{
    'path': {'InstanceID': 'FUJITSU:TPP0004'},
    'pool_name': 'abcd1234_TPP',
    'useable_capacity_gb': (FAKE_CAPACITY / units.Gi) * 20 - FAKE_USEGB,
    'multiattach': False,
    'thick_provisioning_support': False,
    'provisioned_capacity_gb': FAKE_USEGB,
    'total_volumes': 2,
    'thin_provisioning_support': True,
    'free_capacity_gb': FAKE_CAPACITY / units.Gi - FAKE_USEGB,
    'total_capacity_gb': FAKE_CAPACITY / units.Gi,
    'max_over_subscription_ratio': '20.0',
}, {
    'path': {'InstanceID': 'FUJITSU:RSP0005'},
    'pool_name': 'abcd1234_RG',
    'useable_capacity_gb': FAKE_CAPACITY / units.Gi - FAKE_USEGB2,
    'multiattach': False,
    'thick_provisioning_support': True,
    'provisioned_capacity_gb': FAKE_USEGB2,
    'total_volumes': 1,
    'thin_provisioning_support': False,
    'free_capacity_gb': FAKE_CAPACITY / units.Gi - FAKE_USEGB2,
    'total_capacity_gb': FAKE_CAPACITY / units.Gi,
    'max_over_subscription_ratio': 1,
}]

FAKE_STATS = {
    'driver_version': '1.3.0',
    'storage_protocol': 'iSCSI',
    'vendor_name': 'FUJITSU',
    'QoS_support': False,
    'volume_backend_name': 'volume_backend_name',
    'shared_targets': True,
    'backend_state': 'up',
    'pools': FAKE_POOLS,
}
FAKE_STATS2 = {
    'driver_version': '1.3.0',
    'storage_protocol': 'FC',
    'vendor_name': 'FUJITSU',
    'QoS_support': False,
    'volume_backend_name': 'volume_backend_name',
    'shared_targets': True,
    'backend_state': 'up',
    'pools': FAKE_POOLS,
}


# Volume1 in pool abcd1234_TPP
FAKE_KEYBIND1 = {
    'CreationClassName': 'FUJITSU_StorageVolume',
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID1,
    'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
}

# Volume2 in pool abcd1234_RG
FAKE_KEYBIND3 = {
    'CreationClassName': 'FUJITSU_StorageVolume',
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID3,
    'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
}

# Volume1
FAKE_LOCATION1 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND1,
}

# Volume2
FAKE_LOCATION3 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND3,
}

# Volume1 metadata info.
FAKE_LUN_META1 = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO1,
    'FJ_Volume_Name': u'FJosv_0qJ4rpOHgFE8ipcJOMfBmg==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

# Volume2 metadata info.
FAKE_LUN_META3 = {
    'FJ_Pool_Type': 'RAID_GROUP',
    'FJ_Volume_No': FAKE_LUN_NO3,
    'FJ_Volume_Name': u'FJosv_4whcadwDac7ANKHA2O719A==',
    'FJ_Pool_Name': STORAGE_TYPE2,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}
# Volume1
FAKE_MODEL_INFO1 = {
    'provider_location': six.text_type(FAKE_LOCATION1),
    'metadata': FAKE_LUN_META1,
}
# Volume2
FAKE_MODEL_INFO3 = {
    'provider_location': six.text_type(FAKE_LOCATION3),
    'metadata': FAKE_LUN_META3,
}

FAKE_KEYBIND2 = {
    'CreationClassName': 'FUJITSU_StorageVolume',
    'SystemName': STORAGE_SYSTEM,
    'DeviceID': FAKE_LUN_ID2,
    'SystemCreationClassName': 'FUJITSU_StorageComputerSystem',
}

FAKE_LOCATION2 = {
    'classname': 'FUJITSU_StorageVolume',
    'keybindings': FAKE_KEYBIND2,
}

FAKE_SNAP_INFO = {
    'provider_location': six.text_type(FAKE_LOCATION2)
}

FAKE_LUN_META2 = {
    'FJ_Pool_Type': 'Thinporvisioning_POOL',
    'FJ_Volume_No': FAKE_LUN_NO1,
    'FJ_Volume_Name': u'FJosv_UkCZqMFZW3SU_JzxjHiKfg==',
    'FJ_Pool_Name': STORAGE_TYPE,
    'FJ_Backend': FAKE_SYSTEM_NAME,
}

FAKE_MODEL_INFO2 = {
    'provider_location': six.text_type(FAKE_LOCATION1),
    'metadata': FAKE_LUN_META2,
}


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


class FakeEternusConnection(object):
    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, TheElement=None, LUNames=None,
                     Size=None, Type=None, Mode=None, Locality=None,
                     InitiatorPortIDs=None, TargetPortIDs=None,
                     DeviceAccesses=None, SyncType=None,
                     SourceElement=None, TargetElement=None,
                     Operation=None, CopyType=None,
                     Synchronization=None, ProtocolControllers=None,
                     TargetPool=None):
        global MAP_STAT, VOL_STAT
        if MethodName == 'CreateOrModifyElementFromStoragePool':
            VOL_STAT = '1'
            rc = 0
            vol = self._enum_volumes()
            if InPool.get('InstanceID') == 'FUJITSU:RSP0005':
                job = {'TheElement': vol[1].path}
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
            pool['TotalManagedSpace'] = 1170368102400
            pool['RemainingManagedSpace'] = 1170368102400 - 1 * units.Gi
            pool.path = FJ_StoragePool()
            pool.path['InstanceID'] = 'FUJITSU:RSP0004'
            pool.path.classname = 'FUJITSU_RAIDStoragePool'
            pools.append(pool)

            pool2['InstanceID'] = 'FUJITSU:RSP0005'
            pool2['CreationClassName'] = 'FUJITSU_RAIDStoragePool'
            pool2['ElementName'] = 'abcd1234_RG'
            pool2['TotalManagedSpace'] = 1170368102400
            pool2['RemainingManagedSpace'] = 1170368102400 - 1 * units.Gi
            pool2.path = FJ_StoragePool()
            pool2.path['InstanceID'] = 'FUJITSU:RSP0005'
            pool2.path.classname = 'FUJITSU_RAIDStoragePool'
            pools.append(pool2)
        else:
            pool['InstanceID'] = 'FUJITSU:TPP0004'
            pool['CreationClassName'] = 'FUJITSU_ThinProvisioningPool'
            pool['ElementName'] = 'abcd1234_TPP'
            pool['TotalManagedSpace'] = 1170368102400
            pool['RemainingManagedSpace'] = 1170368102400 - 2 * units.Gi
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
        volumes.append(snap_vol)

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

        self.mock_object(dx_common.FJDXCommon, '_get_eternus_connection',
                         self.fake_eternus_connection)

        instancename = FakeCIMInstanceName()
        self.mock_object(dx_common.FJDXCommon, '_create_eternus_instance_name',
                         instancename.fake_create_eternus_instance_name)

        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())
        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)
        # Set iscsi driver to self.driver.
        driver = dx_fc.FJDXFCDriver(configuration=self.configuration)
        self.driver = driver

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> show users\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ')
            return ret
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF\r\n0001\tFJosv_UkCZqMFZW3SU_JzxjHiKfg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_OSVD'
                   '\t0000000000200000\t00\t00\t00000000'
                   '\t0050\tFF\t00\tFF\tFF\t20\tFF\tFFFF'
                   '\t00\t600000E00D2A0000002A0115001E0000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
            return ret

    def fake_safe_get(self, str=None):
        return str

    def fake_eternus_connection(self):
        conn = FakeEternusConnection()
        return conn

    def test_get_volume_stats(self):
        ret = self.driver.get_volume_stats(True)

        self.assertEqual(FAKE_STATS2, ret)

    def test_create_and_delete_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_volume(TEST_VOLUME2)
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

    def test_create_and_delete_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        model_info = self.driver.create_volume_from_snapshot(TEST_CLONE,
                                                             TEST_SNAP)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        volume_info = {}
        for key in TEST_VOLUME:
            if key == 'provider_location':
                volume_info[key] = model_info[key]
            elif key == 'metadata':
                volume_info[key] = model_info[key]
            else:
                volume_info[key] = TEST_VOLUME[key]

        self.driver.extend_volume(volume_info, 10)


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

        self.mock_object(dx_common.FJDXCommon, '_get_eternus_connection',
                         self.fake_eternus_connection)

        instancename = FakeCIMInstanceName()
        self.mock_object(dx_common.FJDXCommon, '_create_eternus_instance_name',
                         instancename.fake_create_eternus_instance_name)

        self.mock_object(dx_common.FJDXCommon, '_get_mapdata_iscsi',
                         self.fake_get_mapdata)

        self.mock_object(ssh_utils, 'SSHPool', mock.Mock())
        self.mock_object(eternus_dx_cli.FJDXCLI, '_exec_cli_with_eternus',
                         self.fake_exec_cli_with_eternus)
        # Set iscsi driver to self.driver.
        driver = dx_iscsi.FJDXISCSIDriver(configuration=self.configuration)
        self.driver = driver

    def fake_exec_cli_with_eternus(self, exec_cmdline):
        if exec_cmdline == "show users":
            ret = ('\r\nCLI> show users\r\n00\r\n'
                   '3B\r\nf.ce\tMaintainer\t01\t00'
                   '\t00\t00\r\ntestuser\tSoftware'
                   '\t01\t01\t00\t00\r\nCLI> ')
            return ret
        elif exec_cmdline.startswith('show volumes'):
            ret = ('\r\nCLI> %s\r\n00\r\n0560\r\n0000'
                   '\tFJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_TPP'
                   '\t0000000000200000\t00\t00'
                   '\t00000000\t0050\tFF\t00\tFF'
                   '\tFF\t20\tFF\tFFFF\t00'
                   '\t600000E00D2A0000002A011500140000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF\r\n0001\tFJosv_UkCZqMFZW3SU_JzxjHiKfg=='
                   '\tA001\t0B\t00\t0000\tabcd1234_OSVD'
                   '\t0000000000200000\t00\t00\t00000000'
                   '\t0050\tFF\t00\tFF\tFF\t20\tFF\tFFFF'
                   '\t00\t600000E00D2A0000002A0115001E0000'
                   '\t00\t00\tFF\tFF\tFFFFFFFF\t00'
                   '\t00\tFF' % exec_cmdline)
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

    def test_get_volume_stats(self):
        ret = self.driver.get_volume_stats(True)

        self.assertEqual(FAKE_STATS, ret)

    def test_create_and_delete_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_volume(TEST_VOLUME2)
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

    def test_create_and_delete_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        snap_info = self.driver.create_snapshot(TEST_SNAP)
        self.assertEqual(FAKE_SNAP_INFO, snap_info)

        model_info = self.driver.create_volume_from_snapshot(TEST_CLONE,
                                                             TEST_SNAP)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        model_info = self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO2, model_info)

        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        model_info = self.driver.create_volume(TEST_VOLUME)
        self.assertEqual(FAKE_MODEL_INFO1, model_info)

        volume_info = {}
        for key in TEST_VOLUME:
            if key == 'provider_location':
                volume_info[key] = model_info[key]
            elif key == 'metadata':
                volume_info[key] = model_info[key]
            else:
                volume_info[key] = TEST_VOLUME[key]

        self.driver.extend_volume(volume_info, 10)
