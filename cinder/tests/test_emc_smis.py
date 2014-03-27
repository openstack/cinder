# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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
import shutil
import tempfile
import time
from xml.dom.minidom import Document

import mock

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder import units
from cinder.volume.drivers.emc.emc_smis_common import EMCSMISCommon
from cinder.volume.drivers.emc.emc_smis_fc import EMCSMISFCDriver
from cinder.volume.drivers.emc.emc_smis_iscsi import EMCSMISISCSIDriver
from cinder.volume import volume_types

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_emc_config.xml'
LOG = logging.getLogger(__name__)


class EMC_StorageVolume(dict):
    pass


class SE_ConcreteJob(dict):
    pass


class SE_StorageHardwareID(dict):
    pass


class FakeCIMInstanceName(dict):

    def fake_getinstancename(self, classname, bindings):
        instancename = FakeCIMInstanceName()
        for key in bindings:
            instancename[key] = bindings[key]
        instancename.classname = classname
        instancename.namespace = 'root/emc'
        return instancename


class FakeDB():
    def volume_update(self, context, volume_id, model_update):
        pass

    def snapshot_update(self, context, snapshot_id, model_update):
        pass

    def volume_get(self, context, volume_id):
        conn = FakeEcomConnection()
        objectpath = {}
        objectpath['CreationClassName'] = 'Clar_StorageVolume'
        if volume_id == 'vol1':
            device_id = '1'
            objectpath['DeviceID'] = device_id
        else:
            objectpath['DeviceID'] = volume_id
        return conn.GetInstance(objectpath)


class EMCSMISCommonData():
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost'}

    config_file_name = 'cinder_emc_config.xml'
    storage_system = 'CLARiiON+APM00123456789'
    storage_system_vmax = 'SYMMETRIX+000195900551'
    lunmaskctrl_id =\
        'CLARiiON+APM00123456789+00aa11bb22cc33dd44ff55gg66hh77ii88jj'
    initiator1 = 'iqn.1993-08.org.debian:01:1a2b3c4d5f6g'
    stconf_service_creationclass = 'Clar_StorageConfigurationService'
    ctrlconf_service_creationclass = 'Clar_ControllerConfigurationService'
    rep_service_creationclass = 'Clar_ReplicationService'
    vol_creationclass = 'Clar_StorageVolume'
    pool_creationclass = 'Clar_UnifiedStoragePool'
    lunmask_creationclass = 'Clar_LunMaskingSCSIProtocolController'
    unit_creationclass = 'CIM_ProtocolControllerForUnit'
    storage_type = 'gold'

    test_volume = {'name': 'vol1',
                   'size': 1,
                   'volume_name': 'vol1',
                   'id': '1',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'vol1',
                   'display_description': 'test volume',
                   'volume_type_id': None}
    test_failed_volume = {'name': 'failed_vol',
                          'size': 1,
                          'volume_name': 'failed_vol',
                          'id': '4',
                          'provider_auth': None,
                          'project_id': 'project',
                          'display_name': 'failed_vol',
                          'display_description': 'test failed volume',
                          'volume_type_id': None}
    test_snapshot = {'name': 'snapshot1',
                     'size': 1,
                     'id': '4444',
                     'volume_name': 'vol-vol1',
                     'volume_size': 1,
                     'project_id': 'project'}
    test_clone = {'name': 'clone1',
                  'size': 1,
                  'volume_name': 'vol1',
                  'id': '2',
                  'provider_auth': None,
                  'project_id': 'project',
                  'display_name': 'clone1',
                  'display_description': 'volume created from snapshot',
                  'volume_type_id': None}
    test_clone3 = {'name': 'clone3',
                   'size': 1,
                   'volume_name': 'vol1',
                   'id': '3',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'clone3',
                   'display_description': 'cloned volume',
                   'volume_type_id': None}
    test_snapshot_vmax = {'name': 'snapshot_vmax',
                          'size': 1,
                          'id': '4445',
                          'volume_name': 'vol-vol1',
                          'volume_size': 1,
                          'project_id': 'project'}
    failed_snapshot_replica = {'name': 'failed_snapshot_replica',
                               'size': 1,
                               'volume_name': 'vol-vol1',
                               'id': '5',
                               'provider_auth': None,
                               'project_id': 'project',
                               'display_name': 'vol1',
                               'display_description':
                               'failed snapshot replica',
                               'volume_type_id': None}
    failed_snapshot_sync = {'name': 'failed_snapshot_sync',
                            'size': 1,
                            'volume_name': 'vol-vol1',
                            'id': '6',
                            'provider_auth': None,
                            'project_id': 'project',
                            'display_name': 'failed_snapshot_sync',
                            'display_description': 'failed snapshot sync',
                            'volume_type_id': None}
    failed_clone_replica = {'name': 'failed_clone_replica',
                            'size': 1,
                            'volume_name': 'vol1',
                            'id': '7',
                            'provider_auth': None,
                            'project_id': 'project',
                            'display_name': 'vol1',
                            'display_description': 'failed clone replica',
                            'volume_type_id': None}
    failed_clone_sync = {'name': 'failed_clone_sync',
                         'size': 1,
                         'volume_name': 'vol1',
                         'id': '8',
                         'provider_auth': None,
                         'project_id': 'project',
                         'display_name': 'vol1',
                         'display_description': 'failed clone sync',
                         'volume_type_id': None}
    failed_delete_vol = {'name': 'failed_delete_vol',
                         'size': 1,
                         'volume_name': 'failed_delete_vol',
                         'id': '99999',
                         'provider_auth': None,
                         'project_id': 'project',
                         'display_name': 'failed delete vol',
                         'display_description': 'failed delete volume',
                         'volume_type_id': None}
    failed_extend_vol = {'name': 'failed_extend_vol',
                         'size': 1,
                         'volume_name': 'failed_extend_vol',
                         'id': '9',
                         'provider_auth': None,
                         'project_id': 'project',
                         'display_name': 'failed_extend_vol',
                         'display_description': 'test failed extend volume',
                         'volume_type_id': None}


class FakeEcomConnection():

    def __init__(self, *args, **kwargs):
        self.data = EMCSMISCommonData()

    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, Size=None,
                     SyncType=None, SourceElement=None,
                     Operation=None, Synchronization=None,
                     TheElements=None, TheElement=None,
                     LUNames=None, InitiatorPortIDs=None, DeviceAccesses=None,
                     ProtocolControllers=None,
                     MaskingGroup=None, Members=None,
                     HardwareId=None):

        rc = 0L
        myjob = SE_ConcreteJob()
        myjob.classname = 'SE_ConcreteJob'
        myjob['InstanceID'] = '9999'
        myjob['status'] = 'success'
        myjob['type'] = ElementName
        if ElementName == 'failed_vol' and \
                MethodName == 'CreateOrModifyElementFromStoragePool':
            rc = 10L
            myjob['status'] = 'failure'
        elif TheElement and TheElement['ElementName'] == 'failed_extend_vol' \
                and MethodName == 'CreateOrModifyElementFromStoragePool':
            rc = 10L
            myjob['status'] = 'failure'
        elif MethodName == 'CreateOrModifyElementFromStoragePool':
            rc = 0L
            myjob['status'] = 'success'
        elif ElementName == 'failed_snapshot_replica' and \
                MethodName == 'CreateElementReplica':
            rc = 10L
            myjob['status'] = 'failure'
        elif Synchronization and \
                Synchronization['SyncedElement']['ElementName'] \
                == 'failed_snapshot_sync' and \
                MethodName == 'ModifyReplicaSynchronization':
            rc = 10L
            myjob['status'] = 'failure'
        elif ElementName == 'failed_clone_replica' and \
                MethodName == 'CreateElementReplica':
            rc = 10L
            myjob['status'] = 'failure'
        elif Synchronization and \
                Synchronization['SyncedElement']['ElementName'] \
                == 'failed_clone_sync' and \
                MethodName == 'ModifyReplicaSynchronization':
            rc = 10L
            myjob['status'] = 'failure'
        elif TheElements and \
                TheElements[0]['DeviceID'] == '99999' and \
                MethodName == 'EMCReturnToStoragePool':
            rc = 10L
            myjob['status'] = 'failure'
        elif HardwareId:
            rc = 0L
            targetendpoints = {}
            endpoints = []
            endpoint = {}
            endpoint['Name'] = '1234567890123'
            endpoints.append(endpoint)
            endpoint2 = {}
            endpoint2['Name'] = '0987654321321'
            endpoints.append(endpoint2)
            targetendpoints['TargetEndpoints'] = endpoints
            return rc, targetendpoints

        job = {'Job': myjob}
        return rc, job

    def EnumerateInstanceNames(self, name):
        result = None
        if name == 'EMC_ReplicationService':
            result = self._enum_replicationservices()
        elif name == 'EMC_StorageConfigurationService':
            result = self._enum_stconfsvcs()
        elif name == 'EMC_ControllerConfigurationService':
            result = self._enum_ctrlconfsvcs()
        elif name == 'EMC_VirtualProvisioningPool':
            result = self._enum_pools()
        elif name == 'EMC_UnifiedStoragePool':
            result = self._enum_pools()
        elif name == 'EMC_StorageVolume':
            result = self._enum_storagevolumes()
        elif name == 'Clar_StorageVolume':
            result = self._enum_storagevolumes()
        elif name == 'SE_StorageSynchronized_SV_SV':
            result = self._enum_syncsvsvs()
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._enum_unitnames()
        elif name == 'EMC_LunMaskingSCSIProtocolController':
            result = self._enum_lunmaskctrls()
        elif name == 'EMC_StorageProcessorSystem':
            result = self._enum_processors()
        elif name == 'EMC_StorageHardwareIDManagementService':
            result = self._enum_hdwidmgmts()
        else:
            result = self._default_enum()
        return result

    def EnumerateInstances(self, name):
        result = None
        if name == 'EMC_VirtualProvisioningPool':
            result = self._enum_pool_details()
        elif name == 'EMC_UnifiedStoragePool':
            result = self._enum_pool_details()
        elif name == 'SE_StorageHardwareID':
            result = self._enum_storhdwids()
        else:
            result = self._default_enum()
        return result

    def GetInstance(self, objectpath, LocalOnly=False):
        try:
            name = objectpath['CreationClassName']
        except KeyError:
            name = objectpath.classname
        result = None
        if name == 'Clar_StorageVolume' or name == 'Symm_StorageVolume':
            result = self._getinstance_storagevolume(objectpath)
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._getinstance_unit(objectpath)
        elif name == 'Clar_LunMaskingSCSIProtocolController':
            result = self._getinstance_lunmask()
        elif name == 'SE_ConcreteJob':
            result = self._getinstance_job(objectpath)
        elif name == 'SE_StorageSynchronized_SV_SV':
            result = self._getinstance_syncsvsv(objectpath)
        else:
            result = self._default_getinstance(objectpath)
        return result

    def Associators(self, objectpath, resultClass='EMC_StorageHardwareID'):
        result = None
        if resultClass == 'EMC_StorageHardwareID':
            result = self._assoc_hdwid()
        elif resultClass == 'EMC_iSCSIProtocolEndpoint':
            result = self._assoc_endpoint()
        # Added test for EMC_StorageVolume
        elif resultClass == 'EMC_StorageVolume':
            result = self._assoc_storagevolume(objectpath)
        else:
            result = self._default_assoc(objectpath)
        return result

    def AssociatorNames(self, objectpath,
                        resultClass='EMC_LunMaskingSCSIProtocolController'):
        result = None
        if resultClass == 'EMC_LunMaskingSCSIProtocolController':
            result = self._assocnames_lunmaskctrl()
        else:
            result = self._default_assocnames(objectpath)
        return result

    def ReferenceNames(self, objectpath,
                       ResultClass='CIM_ProtocolControllerForUnit'):
        result = None
        if ResultClass == 'CIM_ProtocolControllerForUnit':
            result = self._ref_unitnames()
        else:
            result = self._default_ref(objectpath)
        return result

    def _ref_unitnames(self):
        unitnames = []
        unitname = {}

        dependent = {}
        dependent['CreationClassName'] = self.data.vol_creationclass
        dependent['DeviceID'] = self.data.test_volume['id']
        dependent['ElementName'] = self.data.test_volume['name']
        dependent['SystemName'] = self.data.storage_system

        antecedent = {}
        antecedent['CreationClassName'] = self.data.lunmask_creationclass
        antecedent['DeviceID'] = self.data.lunmaskctrl_id
        antecedent['SystemName'] = self.data.storage_system

        unitname['Dependent'] = dependent
        unitname['Antecedent'] = antecedent
        unitname['CreationClassName'] = self.data.unit_creationclass
        unitnames.append(unitname)

        return unitnames

    def _default_ref(self, objectpath):
        return objectpath

    def _assoc_hdwid(self):
        assocs = []
        assoc = {}
        assoc['StorageID'] = self.data.connector['initiator']
        assocs.append(assoc)
        for wwpn in self.data.connector['wwpns']:
            assoc2 = {}
            assoc2['StorageID'] = wwpn
            assocs.append(assoc2)
        return assocs

    def _assoc_endpoint(self):
        assocs = []
        assoc = {}
        assoc['Name'] = 'iqn.1992-04.com.emc:cx.apm00123907237.a8,t,0x0001'
        assoc['SystemName'] = self.data.storage_system + '+SP_A+8'
        assocs.append(assoc)
        return assocs

    # Added test for EMC_StorageVolume associators
    def _assoc_storagevolume(self, objectpath):
        assocs = []
        if objectpath['type'] == 'failed_delete_vol':
            vol = self.data.failed_delete_vol
        elif objectpath['type'] == 'vol1':
            vol = self.data.test_volume
        elif objectpath['type'] == 'failed_vol':
            vol = self.data.test_failed_volume
        elif objectpath['type'] == 'failed_clone_sync':
            vol = self.data.failed_clone_sync
        elif objectpath['type'] == 'failed_clone_replica':
            vol = self.data.failed_clone_replica
        elif objectpath['type'] == 'failed_snapshot_replica':
            vol = self.data.failed_snapshot_replica
        elif objectpath['type'] == 'failed_snapshot_sync':
            vol = self.data.failed_snapshot_sync
        elif objectpath['type'] == 'clone1':
            vol = self.data.test_clone
        elif objectpath['type'] == 'clone3':
            vol = self.data.test_clone3
        elif objectpath['type'] == 'snapshot1':
            vol = self.data.test_snapshot
        elif objectpath['type'] == 'snapshot_vmax':
            vol = self.data.test_snapshot_vmax
        elif objectpath['type'] == 'failed_extend_vol':
            vol = self.data.failed_extend_vol
        else:
            return None

        vol['DeviceID'] = vol['id']
        assoc = self._getinstance_storagevolume(vol)
        assocs.append(assoc)
        return assocs

    def _default_assoc(self, objectpath):
        return objectpath

    def _assocnames_lunmaskctrl(self):
        return self._enum_lunmaskctrls()

    def _default_assocnames(self, objectpath):
        return objectpath

    def _getinstance_storagevolume(self, objectpath):
        foundinstance = None
        instance = EMC_StorageVolume()
        vols = self._enum_storagevolumes()
        for vol in vols:
            if vol['DeviceID'] == objectpath['DeviceID']:
                instance = vol
                break
        if not instance:
            foundinstance = None
        else:
            foundinstance = instance
        return foundinstance

    def _getinstance_syncsvsv(self, objectpath):
        foundsync = None
        syncs = self._enum_syncsvsvs()
        for sync in syncs:
            if (sync['SyncedElement'] == objectpath['SyncedElement'] and
                    sync['SystemElement'] == objectpath['SystemElement']):
                foundsync = sync
                break
        return foundsync

    def _getinstance_lunmask(self):
        lunmask = {}
        lunmask['CreationClassName'] = self.data.lunmask_creationclass
        lunmask['DeviceID'] = self.data.lunmaskctrl_id
        lunmask['SystemName'] = self.data.storage_system
        return lunmask

    def _getinstance_unit(self, objectpath):
        unit = {}

        dependent = {}
        dependent['CreationClassName'] = self.data.vol_creationclass
        dependent['DeviceID'] = self.data.test_volume['id']
        dependent['ElementName'] = self.data.test_volume['name']
        dependent['SystemName'] = self.data.storage_system

        antecedent = {}
        antecedent['CreationClassName'] = self.data.lunmask_creationclass
        antecedent['DeviceID'] = self.data.lunmaskctrl_id
        antecedent['SystemName'] = self.data.storage_system

        unit['Dependent'] = dependent
        unit['Antecedent'] = antecedent
        unit['CreationClassName'] = self.data.unit_creationclass
        unit['DeviceNumber'] = '0'

        return unit

    def _getinstance_job(self, jobpath):
        jobinstance = {}
        jobinstance['InstanceID'] = '9999'
        if jobpath['status'] == 'failure':
            jobinstance['JobState'] = 10
            jobinstance['ErrorCode'] = 99
            jobinstance['ErrorDescription'] = 'Failure'
        else:
            jobinstance['JobState'] = 7
            jobinstance['ErrorCode'] = 0
            jobinstance['ErrorDescription'] = ''
        return jobinstance

    def _default_getinstance(self, objectpath):
        return objectpath

    def _enum_replicationservices(self):
        rep_services = []
        rep_service = {}
        rep_service['SystemName'] = self.data.storage_system
        rep_service['CreationClassName'] = self.data.rep_service_creationclass
        rep_services.append(rep_service)
        return rep_services

    def _enum_stconfsvcs(self):
        conf_services = []
        conf_service = {}
        conf_service['SystemName'] = self.data.storage_system
        conf_service['CreationClassName'] =\
            self.data.stconf_service_creationclass
        conf_services.append(conf_service)
        return conf_services

    def _enum_ctrlconfsvcs(self):
        conf_services = []
        conf_service = {}
        conf_service['SystemName'] = self.data.storage_system
        conf_service['CreationClassName'] =\
            self.data.ctrlconf_service_creationclass
        conf_services.append(conf_service)
        return conf_services

    def _enum_pools(self):
        pools = []
        pool = {}
        pool['InstanceID'] = self.data.storage_system + '+U+' +\
            self.data.storage_type
        pool['CreationClassName'] = 'Clar_UnifiedStoragePool'
        pools.append(pool)
        return pools

    def _enum_pool_details(self):
        pools = []
        pool = {}
        pool['InstanceID'] = self.data.storage_system + '+U+' +\
            self.data.storage_type
        pool['CreationClassName'] = 'Clar_UnifiedStoragePool'
        pool['TotalManagedSpace'] = 12345678
        pool['RemainingManagedSpace'] = 123456
        pools.append(pool)
        return pools

    def _enum_storagevolumes(self):
        vols = []

        vol = EMC_StorageVolume()
        vol['name'] = self.data.test_volume['name']
        vol['CreationClassName'] = 'Clar_StorageVolume'
        vol['ElementName'] = self.data.test_volume['name']
        vol['DeviceID'] = self.data.test_volume['id']
        vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        vol.path = vol
        vol.path.classname = vol['CreationClassName']

        name = {}
        name['classname'] = 'Clar_StorageVolume'
        keys = {}
        keys['CreationClassName'] = 'Clar_StorageVolume'
        keys['SystemName'] = self.data.storage_system
        keys['DeviceID'] = vol['DeviceID']
        keys['SystemCreationClassName'] = 'Clar_StorageSystem'
        name['keybindings'] = keys
        vol['provider_location'] = str(name)

        vols.append(vol)

        snap_vol = EMC_StorageVolume()
        snap_vol['name'] = self.data.test_snapshot['name']
        snap_vol['CreationClassName'] = 'Clar_StorageVolume'
        snap_vol['ElementName'] = self.data.test_snapshot['name']
        snap_vol['DeviceID'] = self.data.test_snapshot['id']
        snap_vol['SystemName'] = self.data.storage_system
        # Added vol to path
        snap_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        snap_vol.path = snap_vol
        snap_vol.path.classname = snap_vol['CreationClassName']

        name2 = {}
        name2['classname'] = 'Clar_StorageVolume'
        keys2 = {}
        keys2['CreationClassName'] = 'Clar_StorageVolume'
        keys2['SystemName'] = self.data.storage_system
        keys2['DeviceID'] = snap_vol['DeviceID']
        keys2['SystemCreationClassName'] = 'Clar_StorageSystem'
        name2['keybindings'] = keys2
        snap_vol['provider_location'] = str(name2)

        vols.append(snap_vol)

        clone_vol = EMC_StorageVolume()
        clone_vol['name'] = self.data.test_clone['name']
        clone_vol['CreationClassName'] = 'Clar_StorageVolume'
        clone_vol['ElementName'] = self.data.test_clone['name']
        clone_vol['DeviceID'] = self.data.test_clone['id']
        clone_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        clone_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        clone_vol.path = clone_vol
        clone_vol.path.classname = clone_vol['CreationClassName']
        vols.append(clone_vol)

        clone_vol3 = EMC_StorageVolume()
        clone_vol3['name'] = self.data.test_clone3['name']
        clone_vol3['CreationClassName'] = 'Clar_StorageVolume'
        clone_vol3['ElementName'] = self.data.test_clone3['name']
        clone_vol3['DeviceID'] = self.data.test_clone3['id']
        clone_vol3['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        clone_vol3['SystemCreationClassName'] = 'Clar_StorageSystem'
        clone_vol3.path = clone_vol3
        clone_vol3.path.classname = clone_vol3['CreationClassName']
        vols.append(clone_vol3)

        snap_vol_vmax = EMC_StorageVolume()
        snap_vol_vmax['name'] = self.data.test_snapshot_vmax['name']
        snap_vol_vmax['CreationClassName'] = 'Symm_StorageVolume'
        snap_vol_vmax['ElementName'] = self.data.test_snapshot_vmax['name']
        snap_vol_vmax['DeviceID'] = self.data.test_snapshot_vmax['id']
        snap_vol_vmax['SystemName'] = self.data.storage_system_vmax
        # Added vol to vol.path
        snap_vol_vmax['SystemCreationClassName'] = 'Symm_StorageSystem'
        snap_vol_vmax.path = snap_vol_vmax
        snap_vol_vmax.path.classname = snap_vol_vmax['CreationClassName']

        name3 = {}
        name3['classname'] = 'Clar_StorageVolume'
        keys3 = {}
        keys3['CreationClassName'] = 'Clar_StorageVolume'
        keys3['SystemName'] = self.data.storage_system
        keys3['DeviceID'] = snap_vol_vmax['DeviceID']
        keys3['SystemCreationClassName'] = 'Clar_StorageSystem'
        name3['keybindings'] = keys3
        snap_vol_vmax['provider_location'] = str(name3)

        vols.append(snap_vol_vmax)

        failed_snap_replica = EMC_StorageVolume()
        failed_snap_replica['name'] = self.data.failed_snapshot_replica['name']
        failed_snap_replica['CreationClassName'] = 'Clar_StorageVolume'
        failed_snap_replica['ElementName'] =\
            self.data.failed_snapshot_replica['name']
        failed_snap_replica['DeviceID'] =\
            self.data.failed_snapshot_replica['id']
        failed_snap_replica['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_snap_replica['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_snap_replica.path = failed_snap_replica
        failed_snap_replica.path.classname =\
            failed_snap_replica['CreationClassName']

        name4 = {}
        name4['classname'] = 'Clar_StorageVolume'
        keys4 = {}
        keys4['CreationClassName'] = 'Clar_StorageVolume'
        keys4['SystemName'] = self.data.storage_system
        keys4['DeviceID'] = failed_snap_replica['DeviceID']
        keys4['SystemCreationClassName'] = 'Clar_StorageSystem'
        name4['keybindings'] = keys4
        failed_snap_replica['provider_location'] = str(name4)

        vols.append(failed_snap_replica)

        failed_snap_sync = EMC_StorageVolume()
        failed_snap_sync['name'] = self.data.failed_snapshot_sync['name']
        failed_snap_sync['CreationClassName'] = 'Clar_StorageVolume'
        failed_snap_sync['ElementName'] =\
            self.data.failed_snapshot_sync['name']
        failed_snap_sync['DeviceID'] = self.data.failed_snapshot_sync['id']
        failed_snap_sync['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_snap_sync['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_snap_sync.path = failed_snap_sync
        failed_snap_sync.path.classname =\
            failed_snap_sync['CreationClassName']

        name5 = {}
        name5['classname'] = 'Clar_StorageVolume'
        keys5 = {}
        keys5['CreationClassName'] = 'Clar_StorageVolume'
        keys5['SystemName'] = self.data.storage_system
        keys5['DeviceID'] = failed_snap_sync['DeviceID']
        keys5['SystemCreationClassName'] = 'Clar_StorageSystem'
        name5['keybindings'] = keys5
        failed_snap_sync['provider_location'] = str(name5)

        vols.append(failed_snap_sync)

        failed_clone_rep = EMC_StorageVolume()
        failed_clone_rep['name'] = self.data.failed_clone_replica['name']
        failed_clone_rep['CreationClassName'] = 'Clar_StorageVolume'
        failed_clone_rep['ElementName'] =\
            self.data.failed_clone_replica['name']
        failed_clone_rep['DeviceID'] = self.data.failed_clone_replica['id']
        failed_clone_rep['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_clone_rep['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_clone_rep.path = failed_clone_rep
        failed_clone_rep.path.classname =\
            failed_clone_rep['CreationClassName']
        vols.append(failed_clone_rep)

        failed_clone_s = EMC_StorageVolume()
        failed_clone_s['name'] = self.data.failed_clone_sync['name']
        failed_clone_s['CreationClassName'] = 'Clar_StorageVolume'
        failed_clone_s['ElementName'] = self.data.failed_clone_sync['name']
        failed_clone_s['DeviceID'] = self.data.failed_clone_sync['id']
        failed_clone_s['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_clone_s['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_clone_s.path = failed_clone_s
        failed_clone_s.path.classname =\
            failed_clone_s['CreationClassName']
        vols.append(failed_clone_s)

        failed_delete_vol = EMC_StorageVolume()
        failed_delete_vol['name'] = 'failed_delete_vol'
        failed_delete_vol['CreationClassName'] = 'Clar_StorageVolume'
        failed_delete_vol['ElementName'] = 'failed_delete_vol'
        failed_delete_vol['DeviceID'] = '99999'
        failed_delete_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_delete_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_delete_vol.path = failed_delete_vol
        failed_delete_vol.path.classname =\
            failed_delete_vol['CreationClassName']
        vols.append(failed_delete_vol)

        failed_vol = EMC_StorageVolume()
        failed_vol['name'] = 'failed__vol'
        failed_vol['CreationClassName'] = 'Clar_StorageVolume'
        failed_vol['ElementName'] = 'failed_vol'
        failed_vol['DeviceID'] = '4'
        failed_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_vol.path = failed_vol
        failed_vol.path.classname =\
            failed_vol['CreationClassName']

        name_failed = {}
        name_failed['classname'] = 'Clar_StorageVolume'
        keys_failed = {}
        keys_failed['CreationClassName'] = 'Clar_StorageVolume'
        keys_failed['SystemName'] = self.data.storage_system
        keys_failed['DeviceID'] = failed_vol['DeviceID']
        keys_failed['SystemCreationClassName'] = 'Clar_StorageSystem'
        name_failed['keybindings'] = keys_failed
        failed_vol['provider_location'] = str(name_failed)

        vols.append(failed_vol)

        failed_extend_vol = EMC_StorageVolume()
        failed_extend_vol['name'] = 'failed_extend_vol'
        failed_extend_vol['CreationClassName'] = 'Clar_StorageVolume'
        failed_extend_vol['ElementName'] = 'failed_extend_vol'
        failed_extend_vol['DeviceID'] = '9'
        failed_extend_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_extend_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        failed_extend_vol.path = failed_extend_vol
        failed_extend_vol.path.classname =\
            failed_extend_vol['CreationClassName']

        name_extend_failed = {}
        name_extend_failed['classname'] = 'Clar_StorageVolume'
        keys_extend_failed = {}
        keys_extend_failed['CreationClassName'] = 'Clar_StorageVolume'
        keys_extend_failed['SystemName'] = self.data.storage_system
        keys_extend_failed['DeviceID'] = failed_extend_vol['DeviceID']
        keys_extend_failed['SystemCreationClassName'] = 'Clar_StorageSystem'
        name_extend_failed['keybindings'] = keys_extend_failed
        failed_extend_vol['provider_location'] = str(name_extend_failed)

        vols.append(failed_extend_vol)

        return vols

    def _enum_syncsvsvs(self):
        syncs = []

        vols = self._enum_storagevolumes()

        sync = self._create_sync(vols[0], vols[1], 100)
        syncs.append(sync)

        sync2 = self._create_sync(vols[1], vols[2], 100)
        syncs.append(sync2)

        sync3 = self._create_sync(vols[0], vols[3], 100)
        syncs.append(sync3)

        objpath1 = vols[1]
        for vol in vols:
            if vol['ElementName'] == 'failed_snapshot_sync':
                objpath2 = vol
                break
        sync4 = self._create_sync(objpath1, objpath2, 100)
        syncs.append(sync4)

        objpath1 = vols[0]
        for vol in vols:
            if vol['ElementName'] == 'failed_clone_sync':
                objpath2 = vol
                break
        sync5 = self._create_sync(objpath1, objpath2, 100)
        syncs.append(sync5)

        return syncs

    def _create_sync(self, objpath1, objpath2, percentsynced):
        sync = {}
        sync['SyncedElement'] = objpath2
        sync['SystemElement'] = objpath1
        sync['CreationClassName'] = 'SE_StorageSynchronized_SV_SV'
        sync['PercentSynced'] = percentsynced
        return sync

    def _enum_unitnames(self):
        return self._ref_unitnames()

    def _enum_lunmaskctrls(self):
        ctrls = []
        ctrl = {}
        ctrl['CreationClassName'] = self.data.lunmask_creationclass
        ctrl['DeviceID'] = self.data.lunmaskctrl_id
        ctrl['SystemName'] = self.data.storage_system
        ctrls.append(ctrl)
        return ctrls

    def _enum_processors(self):
        ctrls = []
        ctrl = {}
        ctrl['CreationClassName'] = 'Clar_StorageProcessorSystem'
        ctrl['Name'] = self.data.storage_system + '+SP_A'
        ctrls.append(ctrl)
        return ctrls

    def _enum_hdwidmgmts(self):
        services = []
        srv = {}
        srv['SystemName'] = self.data.storage_system
        services.append(srv)
        return services

    def _enum_storhdwids(self):
        storhdwids = []
        hdwid = SE_StorageHardwareID()
        hdwid['StorageID'] = self.data.connector['wwpns'][0]

        hdwid.path = hdwid
        storhdwids.append(hdwid)
        return storhdwids

    def _default_enum(self):
        names = []
        name = {}
        name['Name'] = 'default'
        names.append(name)
        return names


class EMCSMISISCSIDriverTestCase(test.TestCase):

    def setUp(self):

        self.data = EMCSMISCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCSMISISCSIDriverTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file()

        configuration = mock.Mock()
        configuration.cinder_emc_config_file = self.config_file_path

        self.stubs.Set(EMCSMISISCSIDriver, '_do_iscsi_discovery',
                       self.fake_do_iscsi_discovery)
        self.stubs.Set(EMCSMISCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCSMISCommon, '_getinstancename',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)
        driver = EMCSMISISCSIDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        storagetype = doc.createElement("StorageType")
        storagetypetext = doc.createTextNode("gold")
        emc.appendChild(storagetype)
        storagetype.appendChild(storagetypetext)

        ecomserverip = doc.createElement("EcomServerIp")
        ecomserveriptext = doc.createTextNode("1.1.1.1")
        emc.appendChild(ecomserverip)
        ecomserverip.appendChild(ecomserveriptext)

        ecomserverport = doc.createElement("EcomServerPort")
        ecomserverporttext = doc.createTextNode("10")
        emc.appendChild(ecomserverport)
        ecomserverport.appendChild(ecomserverporttext)

        ecomusername = doc.createElement("EcomUserName")
        ecomusernametext = doc.createTextNode("user")
        emc.appendChild(ecomusername)
        ecomusername.appendChild(ecomusernametext)

        ecompassword = doc.createElement("EcomPassword")
        ecompasswordtext = doc.createTextNode("pass")
        emc.appendChild(ecompassword)
        ecompassword.appendChild(ecompasswordtext)

        timeout = doc.createElement("Timeout")
        timeouttext = doc.createTextNode("0")
        emc.appendChild(timeout)
        timeout.appendChild(timeouttext)

        self.config_file_path = self.tempdir + '/' + self.data.config_file_name
        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_do_iscsi_discovery(self, volume):
        output = []
        item = '10.0.0.3:3260,1 iqn.1992-04.com.emc:cx.apm00123907237.a8'
        item2 = '10.0.0.4:3260,2 iqn.1992-04.com.emc:cx.apm00123907237.b8'
        output.append(item)
        output.append(item2)
        return output

    def fake_sleep(self, seconds):
        return

    def test_get_volume_stats(self):
        self.driver.get_volume_stats(True)

    def test_create_destroy(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_destroy(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.create_volume_from_snapshot(
            self.data.test_clone, self.data.test_snapshot)
        self.driver.create_cloned_volume(
            self.data.test_clone3, self.data.test_volume)
        self.driver.delete_volume(self.data.test_clone)
        self.driver.delete_volume(self.data.test_clone3)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_map_unmap(self):
        self.driver.create_volume(self.data.test_volume)
        self.data.test_volume['EMCCurrentOwningStorageProcessor'] = 'SP_A'
        connection_info = self.driver.initialize_connection(
            self.data.test_volume,
            self.data.connector)
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    def test_create_volume_snapshot_unsupported(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot_vmax)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_clone,
                          self.data.test_snapshot_vmax)
        self.driver.delete_snapshot(self.data.test_snapshot_vmax)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_replica_failed(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.failed_snapshot_replica,
                          self.data.test_snapshot)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_sync_failed(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.failed_snapshot_sync,
                          self.data.test_snapshot)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_clone_replica_failed(self):
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.failed_clone_replica,
                          self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_clone_sync_failed(self):
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.failed_clone_sync,
                          self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_delete_volume_notfound(self):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Clar_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        name = {}
        name['classname'] = 'Clar_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys
        notfound_delete_vol['provider_location'] = str(name)
        self.driver.delete_volume(notfound_delete_vol)

    def test_delete_volume_failed(self):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    def test_extend_volume(self):
        self.driver.create_volume(self.data.test_volume)
        self.driver.extend_volume(self.data.test_volume, '10')
        self.driver.create_volume(self.data.failed_extend_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.failed_extend_vol,
                          '10')

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCSMISISCSIDriverTestCase, self).tearDown()


class EMCSMISFCDriverTestCase(test.TestCase):

    def setUp(self):

        self.data = EMCSMISCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCSMISFCDriverTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file()

        configuration = mock.Mock()
        configuration.cinder_emc_config_file = self.config_file_path

        self.stubs.Set(EMCSMISCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCSMISCommon, '_getinstancename',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)
        driver = EMCSMISFCDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        storagetype = doc.createElement("StorageType")
        storagetypetext = doc.createTextNode("gold")
        emc.appendChild(storagetype)
        storagetype.appendChild(storagetypetext)

        ecomserverip = doc.createElement("EcomServerIp")
        ecomserveriptext = doc.createTextNode("1.1.1.1")
        emc.appendChild(ecomserverip)
        ecomserverip.appendChild(ecomserveriptext)

        ecomserverport = doc.createElement("EcomServerPort")
        ecomserverporttext = doc.createTextNode("10")
        emc.appendChild(ecomserverport)
        ecomserverport.appendChild(ecomserverporttext)

        ecomusername = doc.createElement("EcomUserName")
        ecomusernametext = doc.createTextNode("user")
        emc.appendChild(ecomusername)
        ecomusername.appendChild(ecomusernametext)

        ecompassword = doc.createElement("EcomPassword")
        ecompasswordtext = doc.createTextNode("pass")
        emc.appendChild(ecompassword)
        ecompassword.appendChild(ecompasswordtext)

        timeout = doc.createElement("Timeout")
        timeouttext = doc.createTextNode("0")
        emc.appendChild(timeout)
        timeout.appendChild(timeouttext)

        self.config_file_path = self.tempdir + '/' + self.data.config_file_name
        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_sleep(self, seconds):
        return

    def test_get_volume_stats(self):
        self.driver.get_volume_stats(True)

    def test_create_destroy(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_destroy(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.create_volume_from_snapshot(
            self.data.test_clone, self.data.test_snapshot)
        self.driver.create_cloned_volume(
            self.data.test_clone3, self.data.test_volume)
        self.driver.delete_volume(self.data.test_clone)
        self.driver.delete_volume(self.data.test_clone3)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_map_unmap(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)

        output = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_lun': 0,
                'target_wwn': ['1234567890123', '0987654321321'],
                'target_discovered': True,
                'initiator_target_map': {'123456789012345':
                                         ['1234567890123', '0987654321321'],
                                         '123456789054321':
                                         ['1234567890123', '0987654321321'],
                                         }}}

        connection_info = self.driver.initialize_connection(
            self.data.test_volume,
            self.data.connector)
        self.assertEqual(connection_info, output)

        connection_info = self.driver.terminate_connection(
            self.data.test_volume,
            self.data.connector)

        # Verify calls in terminate_connection are executed
        conf_service = {}
        conf_service['SystemName'] = self.data.storage_system
        conf_service['CreationClassName'] =\
            self.data.ctrlconf_service_creationclass

        vol_instance = self.driver.common._find_lun(self.data.test_volume)

        expected = [
            mock.call._get_ecom_connection(),
            mock.call.find_device_number(self.data.test_volume),
            mock.call._find_lun(self.data.test_volume),
            mock.call.self._find_controller_configuration_service(
                self.data.storage_system),
            mock.call._remove_members(conf_service, vol_instance),
            mock.call.get_target_wwns(
                self.data.storage_system,
                self.data.connector)]

        output = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_wwn': ['1234567890123', '0987654321321'],
                'initiator_target_map': {'123456789012345':
                                         ['1234567890123', '0987654321321'],
                                         '123456789054321':
                                         ['1234567890123', '0987654321321'],
                                         }}}

        self.assertEqual(connection_info, output)

        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    def test_create_volume_snapshot_unsupported(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot_vmax)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_clone,
                          self.data.test_snapshot_vmax)
        self.driver.delete_snapshot(self.data.test_snapshot_vmax)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_replica_failed(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.failed_snapshot_replica,
                          self.data.test_snapshot)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_snapshot_sync_failed(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.failed_snapshot_sync,
                          self.data.test_snapshot)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_clone_replica_failed(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.failed_clone_replica,
                          self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_clone_sync_failed(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.failed_clone_sync,
                          self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_delete_volume_notfound(self):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Clar_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Clar_StorageSystem'
        name = {}
        name['classname'] = 'Clar_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys
        notfound_delete_vol['provider_location'] = str(name)
        self.driver.delete_volume(notfound_delete_vol)

    def test_delete_volume_failed(self):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    def test_extend_volume(self):
        self.data.test_volume['volume_type_id'] = None
        self.driver.create_volume(self.data.test_volume)
        self.driver.extend_volume(self.data.test_volume, '10')
        self.driver.create_volume(self.data.failed_extend_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.failed_extend_vol,
                          '10')

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:pool': 'gold',
                      'storagetype:provisioning': 'thick'})
    def test_create_volume_with_volume_type(self, _mock_volume_type):
        volume_with_vt = self.data.test_volume
        volume_with_vt['volume_type_id'] = 1
        self.driver.create_volume(volume_with_vt)

        configservice = {'CreationClassName':
                         'Clar_StorageConfigurationService',
                         'SystemName': 'CLARiiON+APM00123456789'}

        pool = {'InstanceID': 'CLARiiON+APM00123456789+U+gold',
                'CreationClassName': 'Clar_UnifiedStoragePool'}

        volumesize = int(volume_with_vt['size']) * units.GiB

        storage_type = {'storagetype:provisioning': 'thick',
                        'storagetype:pool': 'gold'}

        expected = [
            mock.call._get_storage_type(volume_with_vt),
            mock.call._find_pool('gold'),
            mock.call.get_provisioning(storage_type),
            mock.call.InvokeMethod('CreateOrModifyElementFromStoragePool',
                                   configservice, volume_with_vt['name'],
                                   pool,
                                   self.driver.common._getnum(2, '16'),
                                   self.driver.common._getnum(volumesize,
                                                              '64'))]

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCSMISFCDriverTestCase, self).tearDown()
