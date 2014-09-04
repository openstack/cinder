# Copyright (c) 2014 FUJITSU LIMITED
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

import os
import tempfile

import mock

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume.drivers.fujitsu_eternus_dx_common import FJDXCommon
from cinder.volume.drivers.fujitsu_eternus_dx_fc import FJDXFCDriver
from cinder.volume.drivers.fujitsu_eternus_dx_iscsi import FJDXISCSIDriver

CONFIG_FILE_NAME = 'cinder_fujitsu_eternus_dx.xml'
STORAGE_SYSTEM = '172.16.0.2'

LOG = logging.getLogger(__name__)

CONF = """<?xml version='1.0' encoding='UTF-8'?>
<FUJITSU>
<StorageType>abcd1234_TPP</StorageType>
<EcomServerIp>172.16.0.2</EcomServerIp>
<EcomServerPort>5988</EcomServerPort>
<EcomUserName>testuser</EcomUserName>
<EcomPassword>testpass</EcomPassword>
<SnapPool>abcd1234_OSVD</SnapPool>
<Timeout>180</Timeout>
</FUJITSU>"""

TEST_VOLUME = {'id': '3d6eeb5d-109b-4435-b891-d01415178490',
               'name': 'volume1',
               'provider_location': None,
               'provider_auth': None,
               'volume_type_id': None,
               'size': 1}
# result : {volume_name : FJosv_0qJ4rpOHgFE8ipcJOMfBmg==}

TEST_SNAP = {'id': 'f47a8da3-d9e2-46aa-831f-0ef04158d5a1',
             'volume_name': 'volume-3d6eeb5d-109b-4435-b891-d01415178490',
             'name': 'snap1',
             'display_name': 'test_snapshot',
             'volume': TEST_VOLUME}

TEST_CLONE = {'name': 'clone1',
              'size': 1,
              'volume_name': 'vol1',
              'id': '391fb914-8a55-4384-a747-588641db3b15',
              'provider_auth': None,
              'project_id': 'project',
              'display_name': 'clone1',
              'display_description': 'volume created from snapshot',
              'volume_type_id': None}

ISCSI_INITIATOR = 'iqn.1993-08.org.debian:01:8261afe17e4c'
TEST_WWPN = ['0123456789111111', '0123456789222222']
TEST_CONNECTOR = {'initiator': ISCSI_INITIATOR,
                  'wwpns': TEST_WWPN}

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
LUNMASKCTRL_IDS = ['AFG0010_CM00CA00P00', 'AFG0011_CM01CA00P00']

STORAGE_SYSTEM = '172.16.0.2'

MAP_STAT = '0'
VOL_STAT = '0'


class FJ_StorageVolume(dict):
    pass


class FJ_StoragePool(dict):
    pass


class FakeDB():
    def volume_get(self, context, volume_id):
        conn = FakeEcomConnection()
        objectpath = {}
        objectpath['CreationClassName'] = STOR_VOL
        if volume_id == '3d6eeb5d-109b-4435-b891-d01415178490':
            return TEST_VOLUME
        else:
            objectpath['DeviceID'] = volume_id
        return conn.GetInstance(objectpath)


class FakeCIMInstanceName(dict):

    def fake_getinstancename(self, classname, bindings):
        instancename = FakeCIMInstanceName()
        for key in bindings:
            instancename[key] = bindings[key]
        instancename.classname = classname
        instancename.namespace = 'root/eternus'
        return instancename


class FakeEcomConnection():
    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, TheElement=None, LUNames=None,
                     Size=None, Type=None, Mode=None, Locality=None,
                     InitiatorPortIDs=None, TargetPortIDs=None,
                     DeviceAccesses=None, SyncType=None,
                     SourceElement=None, TargetElement=None,
                     Operation=None,
                     Synchronization=None, ProtocolControllers=None,
                     TargetPool=None):
        global MAP_STAT, VOL_STAT
        LOG.debug('enter InvokeMethod:MAP_STAT: %s'
                  '  VOL_STAT: %s  Method: %s' %
                  (MAP_STAT, VOL_STAT, MethodName))
        if MethodName == 'CreateOrModifyElementFromStoragePool':
            VOL_STAT = '1'
            rc = 0L
            vol = self._enum_volumes()
            job = {'TheElement': vol[0].path}
        elif MethodName == 'ReturnToStoragePool':
            if MAP_STAT == '1':
                rc = 32787L
            else:
                VOL_STAT = '0'
                rc = 0L
            job = {}
        elif MethodName == 'GetReplicationRelationships':
            rc = 0L
            job = {'Synchronizations': []}
        elif MethodName == 'ExposePaths':
            MAP_STAT = '1'
            rc = 0L
            job = {}
        elif MethodName == 'HidePaths':
            MAP_STAT = '0'
            rc = 0L
            job = {}
        elif MethodName == 'CreateElementReplica':
            rc = 0L
            snap = self._enum_snapshots()
            job = {'TargetElement': snap[0].path}
        elif MethodName == 'CreateReplica':
            rc = 0L
            snap = self._enum_snapshots()
            job = {'TargetElement': snap[0].path}
        elif MethodName == 'ModifyReplicaSynchronization':
            rc = 0L
            job = {}
        else:
            LOG.warn(_('method is not exist '))
            raise exception.VolumeBackendAPIException(data="invoke method")
        LOG.debug('exit InvokeMethod:MAP_STAT: %s  VOL_STAT: %s'
                  '  Method: %s  rc: %d  job: %s' %
                  (MAP_STAT, VOL_STAT, MethodName, rc, job))

        return (rc, job)

    def EnumerateInstanceNames(self, name):
        LOG.debug('enter EnumerateInstanceNames:MAP_STAT: %s'
                  '  VOL_STAT: %s  name: %s' %
                  (MAP_STAT, VOL_STAT, name))
        result = []
        if name == 'FUJITSU_StorageVolume':
            result = self._enum_volumes()
        elif name == 'FUJITSU_StorageConfigurationService':
            result = self._enum_confservice()
        elif name == 'FUJITSU_ReplicationService':
            result = self._enum_repservice()
        elif name == 'FUJITSU_ControllerConfigurationService':
            result = self._enum_ctrlservice()
        elif name == 'FUJITSU_AffinityGrouopController':
            result = self._enum_afntyservice()
        elif name == 'FUJITSU_StorageHardwareIDManagementService':
            result = self._enum_sthwidmngsvc()
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._ref_unitnames()
        elif name == 'CIM_StoragePool':
            result = self._enum_pools()

        LOG.debug('exit EnumerateInstanceNames: %s' % result)

        return result

    def EnumerateInstances(self, name):
        LOG.debug('enter EnumerateInstances:MAP_STAT: %s'
                  '  VOL_STAT: %s  name: %s' %
                  (MAP_STAT, VOL_STAT, name))
        result = None
        if name == 'FUJITSU_StorageProduct':
            result = self._enum_sysnames()
        elif name == STOR_POOL:
            result = self._enum_pool_details('RAID')
        elif name == 'FUJITSU_ThinProvisioningPool':
            result = self._enum_pool_details('TPP')
        elif name == 'FUJITSU_SCSIProtocolEndpoint':
            result = self._enum_scsiprot_endpoint()
        elif name == 'FUJITSU_iSCSIProtocolEndpoint':
            result = self._enum_iscsiprot_endpoint()
        elif name == 'FUJITSU_StorageHardwareID':
            result = self._enum_sthwid()
        elif name == 'CIM_StoragePool':
            result = self._enum_pool_details()
        elif name == 'CIM_SCSIProtocolEndpoint':
            result = self._enum_scsiport_endpoint()
        elif name == 'FUJITSU_StorageHardwareID':
            result = None
        else:
            result = None
        LOG.debug('exit EnumerateInstanceNames: %s' % result)

        return result

    def GetInstance(self, objectpath, LocalOnly=False):
        LOG.debug('enter GetInstance:MAP_STAT: %s  VOL_STAT: %s  obj: %s' %
                  (MAP_STAT, VOL_STAT, objectpath))
        try:
            name = objectpath['CreationClassName']
        except KeyError:
            name = objectpath.classname

        result = None

        if name == 'FUJITSU_StorageVolume':
            result = self._getinstance_storagevolume(objectpath)
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._getinstance_unit(objectpath)

        LOG.debug('exit GetInstance: %s' % result)

        return result

    def Associators(self, objectpath, ResultClass='FUJITSU_StorageHardwareID'):
        result = None
        if ResultClass == 'FUJITSU_StorageHardwareID':
            result = self._assoc_hdwid()
        elif ResultClass == 'FUJITSU_iSCSIProtocolEndpoint':
            result = self._assoc_endpoint()
        elif ResultClass == 'FUJITSU_StorageVolume':
            result = self._assoc_storagevolume(objectpath)
        elif ResultClass == 'FUJITSU_AuthorizedPrivilege':
            result = self._assoc_authpriv()
        else:
            result = self._default_assoc(objectpath)
        LOG.debug('exit Assocs: %s' % result)
        return result

    def AssociatorNames(self, objectpath,
                        ResultClass=SCSI_PROT_CTR):
        result = None
        if ResultClass == SCSI_PROT_CTR:
            result = self._assocnames_lunmaskctrl()
        else:
            result = self._default_assocnames(objectpath)
        LOG.debug('exit AssocNames: %s' % result)
        return result

    def ReferenceNames(self, objectpath,
                       ResultClass='CIM_ProtocolControllerForUnit'):
        result = []
        LOG.debug('ReferenceNames:MAP_STAT: %s' % MAP_STAT)
        if ResultClass == 'CIM_ProtocolControllerForUnit':
            if MAP_STAT == '1':
                result = self._ref_unitnames()
            else:
                result = []
        else:
            result = self._default_ref(objectpath)
        LOG.debug('ReferenceNames %s' % result)
        return result

    def _ref_unitnames(self):
        unitnames = []

        unitname = {}
        dependent = {}
        dependent['CreationClassName'] = STOR_VOL
        dependent['DeviceID'] = '600000E00D2A0000002A011500140000'
        dependent['SystemName'] = STORAGE_SYSTEM

        antecedent = {}
        antecedent['CreationClassName'] = SCSI_PROT_CTR
        antecedent['DeviceID'] = LUNMASKCTRL_IDS[0]
        antecedent['SystemName'] = STORAGE_SYSTEM

        unitname['Dependent'] = dependent
        unitname['Antecedent'] = antecedent
        unitname['CreationClassName'] = PROT_CTRL_UNIT
        unitnames.append(unitname)

        unitname2 = {}
        dependent2 = {}
        dependent2['CreationClassName'] = STOR_VOL
        dependent2['DeviceID'] = '600000E00D2A0000002A011500140000'
        dependent2['SystemName'] = STORAGE_SYSTEM

        antecedent2 = {}
        antecedent2['CreationClassName'] = SCSI_PROT_CTR
        antecedent2['DeviceID'] = LUNMASKCTRL_IDS[1]
        antecedent2['SystemName'] = STORAGE_SYSTEM

        unitname2['Dependent'] = dependent2
        unitname2['Antecedent'] = antecedent2
        unitname2['CreationClassName'] = PROT_CTRL_UNIT
        unitnames.append(unitname2)

        LOG.debug('_ref_unitnames,unitnames: %s' % str(unitnames))
        return unitnames

    def _default_ref(self, objectpath):
        return objectpath

    def _default_assoc(self, objectpath):
        return objectpath

    def _assocnames_lunmaskctrl(self):
        return self._enum_lunmaskctrls()

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

        LOG.debug('exit _assoc_authpriv: %s' % authprivs)

        return authprivs

    def _getinstance_unit(self, objectpath):
        unit = {}
        LOG.debug('enter _getinstance_unit:MAP_STAT: %s' % MAP_STAT)

        if MAP_STAT == '0':
            return unit
        dependent = {}
        dependent['CreationClassName'] = STOR_VOL
        dependent['DeviceID'] = '600000E00D2A0000002A011500140000'
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

        LOG.debug("exit _getinstance_unit,unit: %s" % str(unit))
        return unit

    def _enum_sysnames(self):
        sysnamelist = []
        sysname = {}
        sysname['IdentifyingNumber'] = 'ET603SA4621302115'
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

    def _enum_pool_details(self):
        pools = []

        pool = FJ_StoragePool()
        pool['InstanceID'] = 'FUJITSU:RSP0004'
        pool['CreationClassName'] = 'FUJITSU_RAIDStoragePool'
        pool['ElementName'] = 'abcd1234_OSVD'
        pool['TotalManagedSpace'] = 1170368102400
        pool['RemainingManagedSpace'] = 1170368102400
        pool.path = pool
        pool.path.classname = 'FUJITSU_RAIDStoragePool'
        pools.append(pool)

        pool2 = FJ_StoragePool()
        pool2['InstanceID'] = 'FUJITSU:TPP0004'
        pool2['CreationClassName'] = 'FUJITSU_ThinProvisioningPool'
        pool2['ElementName'] = 'abcd1234_TPP'
        pool2['TotalManagedSpace'] = 1170368102400
        pool2['RemainingManagedSpace'] = 1170368102400
        pool2.path = pool2
        pool2.path.classname = 'FUJITSU_ThinProvisioningPool'
        pools.append(pool2)
        return pools

    def _enum_volumes(self):
        volumes = []
        if VOL_STAT == '0':
            return volumes
        volume = FJ_StorageVolume()
        volume['name'] = TEST_VOLUME['name']
        volume['CreationClassName'] = 'FUJITSU_StorageVolume'
        volume['Name'] = '600000E00D2A0000002A011500140000'
        volume['DeviceID'] = '600000E00D2A0000002A011500140000'
        volume['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        volume['SystemName'] = STORAGE_SYSTEM
        volume['ElementName'] = 'FJosv_0qJ4rpOHgFE8ipcJOMfBmg=='
        volume['volume_type_id'] = None
        volume.path = volume
        volume.path.classname = volume['CreationClassName']

        name = {}
        name['classname'] = 'FUJITSU_StorageVolume'
        keys = {}
        keys['CreationClassName'] = 'FUJITSU_StorageVolume'
        keys['SystemName'] = STORAGE_SYSTEM
        keys['DeviceID'] = volume['DeviceID']
        keys['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        name['keybindings'] = keys
        volume['provider_location'] = str(name)

        volumes.append(volume)

        snap_vol = FJ_StorageVolume()
        snap_vol['name'] = TEST_SNAP['name']
        snap_vol['CreationClassName'] = 'FUJITSU_StorageVolume'
        snap_vol['Name'] = '600000E00D2A0000002A0115001E0000'
        snap_vol['DeviceID'] = '600000E00D2A0000002A0115001E0000'
        snap_vol['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        snap_vol['SystemName'] = STORAGE_SYSTEM
        snap_vol['ElementName'] = 'FJosv_OgEZj1mSvKRvIKOExKktlg=='
        snap_vol.path = snap_vol
        snap_vol.path.classname = snap_vol['CreationClassName']

        name2 = {}
        name2['classname'] = 'FUJITSU_StorageVolume'
        keys2 = {}
        keys2['CreationClassName'] = 'FUJITSU_StorageVolume'
        keys2['SystemName'] = STORAGE_SYSTEM
        keys2['DeviceID'] = snap_vol['DeviceID']
        keys2['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        name2['keybindings'] = keys2
        snap_vol['provider_location'] = str(name2)

        volumes.append(snap_vol)

        clone_vol = FJ_StorageVolume()
        clone_vol['name'] = TEST_CLONE['name']
        clone_vol['CreationClassName'] = 'FUJITSU_StorageVolume'
        clone_vol['ElementName'] = TEST_CLONE['name']
        clone_vol['DeviceID'] = '600000E00D2A0000002A0115001E0000'
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
        snap['DeviceID'] = '600000E00D2A0000002A0115001E0000'
        snap['SystemCreationClassName'] = 'FUJITSU_StorageComputerSystem'
        snap.path = snap
        snap.path.classname = snap['CreationClassName']

        snapshots.append(snap)

        return snapshots

    def _enum_lunmaskctrls(self):
        ctrls = []
        ctrl = {}
        ctrl2 = {}
        LOG.debug('enter _enum_lunmaskctrls:MAP_STAT: %s' % MAP_STAT)
        if MAP_STAT == '1':
            ctrl['CreationClassName'] = SCSI_PROT_CTR
            ctrl['SystemName'] = STORAGE_SYSTEM
            ctrl['DeviceID'] = LUNMASKCTRL_IDS[0]
            ctrls.append(ctrl)

            ctrl2['CreationClassName'] = SCSI_PROT_CTR
            ctrl2['SystemName'] = STORAGE_SYSTEM
            ctrl2['DeviceID'] = LUNMASKCTRL_IDS[1]
            ctrls.append(ctrl2)

        LOG.debug('exit _enum_lunmaskctrls:ctrls: %s' % ctrls)
        return ctrls

    def _enum_scsiport_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['Name'] = '1234567890000021'
        tgtport1['CreationClassName'] = 'FUJITSU_SCSIProtocolEndpoint'
        tgtport1['ConnectionType'] = 2
        tgtport1['RAMode'] = 0
        targetlist.append(tgtport1)

        tgtport2 = {}
        tgtport2['Name'] = '1234567890000031'
        tgtport2['CreationClassName'] = 'FUJITSU_SCSIProtocolEndpoint'
        tgtport2['ConnectionType'] = 2
        tgtport2['RAMode'] = 0
        targetlist.append(tgtport2)

        tgtport3 = {}
        tgtport3['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:0123456789,t,0x0009')
        tgtport3['CreationClassName'] = 'FUJITSU_iSCSIProtocolEndpoint'
        tgtport3['ConnectionType'] = 7
        tgtport3['RAMode'] = 0
        targetlist.append(tgtport3)

        tgtport4 = {}
        tgtport4['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:1234567890,t,0x000A')
        tgtport4['CreationClassName'] = 'FUJITSU_iSCSIProtocolEndpoint'
        tgtport4['ConnectionType'] = 7
        tgtport4['RAMode'] = 0
        targetlist.append(tgtport4)

        return targetlist

    def _enum_iscsiprot_endpoint(self):
        targetlist = []
        tgtport1 = {}
        tgtport1['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:0123456789,t,0x0009')
        tgtport1['ConnectionType'] = 7
        tgtport1['RAMode'] = 0
        targetlist.append(tgtport1)

        tgtport2 = {}
        tgtport2['Name'] = ('iqn.2000-09.com.fujitsu:storage-system.'
                            'eternus-dxl:1234567890,t,0x000A')
        tgtport2['ConnectionType'] = 7
        tgtport2['RAMode'] = 0
        targetlist.append(tgtport2)

        return targetlist

    def _getinstance_storagevolume(self, objpath):
        foundinstance = None
        instance = FJ_StorageVolume()
        volumes = self._enum_volumes()
        for volume in volumes:
            LOG.debug('_getinstance_storagevolume: volume-DeviceID: %s'
                      '  objpath-DeviceID: %s' %
                      (volume['DeviceID'], objpath['DeviceID']))
            if volume['DeviceID'] == objpath['DeviceID']:
                instance = volume
                break
        if not instance:
            foundinstance = None
        else:
            foundinstance = instance
        return foundinstance


class FJFCDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJFCDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJFCDriverTestCase, self).setUp()

        # make fake xml-configuration file
        (handle, self.config_file) = tempfile.mkstemp('.xml')
        os.write(handle, CONF)
        os.close(handle)

        # make fake Object by using mock as configuration object
        self.configuration = mock.Mock()
        self.configuration.cinder_smis_config_file = self.config_file

        #  replace some configuration function with fake
        # self.stubs.Set(self.driver.configuration, 'safe_get',
        #                self.fake_configuration_safe_get)
        self.stubs.Set(FJDXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)

        instancename = FakeCIMInstanceName()
        self.stubs.Set(FJDXCommon, '_getinstancename',
                       instancename.fake_getinstancename)

        # set fc driver to self.driver
        driver = FJDXFCDriver(configuration=self.configuration)
        driver.db = FakeDB()
        self.driver = driver

    def tearDown(self):
        os.remove(self.config_file)
        super(FJFCDriverTestCase, self).tearDown()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def test_get_volume_stats(self):
        self.driver.get_volume_stats(True)

    def test_create_and_delete_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.delete_volume(TEST_VOLUME)

    def test_map_unmap(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.initialize_connection(TEST_VOLUME,
                                          TEST_CONNECTOR)
        self.driver.terminate_connection(TEST_VOLUME,
                                         TEST_CONNECTOR)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_and_delete_snapshot(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_snapshot(TEST_SNAP)
        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_snapshot(TEST_SNAP)
        self.driver.create_volume_from_snapshot(TEST_CLONE, TEST_SNAP)
        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.extend_volume(TEST_VOLUME, '10')


class FJISCSIDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(FJISCSIDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(FJISCSIDriverTestCase, self).setUp()

        # make fake xml-configuration file
        (handle, self.config_file) = tempfile.mkstemp('.xml')
        os.write(handle, CONF)
        os.close(handle)

        # make fake Object by using mock as configuration object
        self.configuration = mock.Mock()
        self.configuration.cinder_smis_config_file = self.config_file
        self.configuration.iscsi_target_prefix = 'iqn.2000-09.com.fujitsu'
        self.configuration.iscsi_ip_address = '192.168.0.22'

        #  replace some configuration function with fake
        # self.stubs.Set(self.driver.configuration, 'safe_get',
        #                self.fake_configuration_safe_get)

        self.stubs.Set(FJDXISCSIDriver, '_do_iscsi_discovery',
                       self.fake_do_iscsi_discovery)

        self.stubs.Set(FJDXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)

        instancename = FakeCIMInstanceName()
        self.stubs.Set(FJDXCommon, '_getinstancename',
                       instancename.fake_getinstancename)

        # set iscsi driver to self.driver
        driver = FJDXISCSIDriver(configuration=self.configuration)
        driver.db = FakeDB()
        self.driver = driver

    def tearDown(self):
        os.remove(self.config_file)
        super(FJISCSIDriverTestCase, self).tearDown()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_do_iscsi_discovery(self, volume):
        output = []
        item = ('10.0.0.3:3260,1 iqn.2000-09.com.fujitsu:storage-system.'
                'eternus-dx400:00040001,t,0x0009')
        item2 = ('10.0.0.4:3260,2 iqn.2000-09.com.fujitsu:storage-system.'
                 'eternus-dx400:00040001,t,0x000A')
        output.append(item)
        output.append(item2)
        return output

    def test_get_volume_stats(self):
        self.driver.get_volume_stats(True)

    def test_create_and_delete_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.delete_volume(TEST_VOLUME)

    def test_map_unmap(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.initialize_connection(TEST_VOLUME,
                                          TEST_CONNECTOR)
        self.driver.terminate_connection(TEST_VOLUME,
                                         TEST_CONNECTOR)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_and_delete_snapshot(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_snapshot(TEST_SNAP)
        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_volume_from_snapshot(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_snapshot(TEST_SNAP)
        self.driver.create_volume_from_snapshot(TEST_CLONE, TEST_SNAP)
        self.driver.delete_snapshot(TEST_SNAP)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_create_cloned_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.create_cloned_volume(TEST_CLONE, TEST_VOLUME)
        self.driver.delete_volume(TEST_CLONE)
        self.driver.delete_volume(TEST_VOLUME)

    def test_extend_volume(self):
        self.driver.create_volume(TEST_VOLUME)
        self.driver.extend_volume(TEST_VOLUME, '10')
