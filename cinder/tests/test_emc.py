# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 EMC Corporation, Inc.
# Copyright (c) 2012 OpenStack Foundation
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
from xml.dom.minidom import Document

import mox

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc.emc_smis_common import EMCSMISCommon
from cinder.volume.drivers.emc.emc_smis_iscsi import EMCSMISISCSIDriver


CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_emc_config.xml'
LOG = logging.getLogger(__name__)

config_file_name = 'cinder_emc_config.xml'
storage_system = 'CLARiiON+APM00123456789'
storage_system_vmax = 'SYMMETRIX+000195900551'
lunmaskctrl_id = 'CLARiiON+APM00123456789+00aa11bb22cc33dd44ff55gg66hh77ii88jj'
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
                 'volume_name': 'vol1',
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
                      'volume_name': 'vol1',
                      'volume_size': 1,
                      'project_id': 'project'}
failed_snapshot_replica = {'name': 'failed_snapshot_replica',
                           'size': 1,
                           'volume_name': 'vol1',
                           'id': '5',
                           'provider_auth': None,
                           'project_id': 'project',
                           'display_name': 'vol1',
                           'display_description': 'failed snapshot replica',
                           'volume_type_id': None}
failed_snapshot_sync = {'name': 'failed_snapshot_sync',
                        'size': 1,
                        'volume_name': 'vol1',
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


class EMC_StorageVolume(dict):
    pass


class SE_ConcreteJob(dict):
    pass


class FakeEcomConnection():

    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, Size=None,
                     SyncType=None, SourceElement=None,
                     Operation=None, Synchronization=None,
                     TheElements=None,
                     LUNames=None, InitiatorPortIDs=None, DeviceAccesses=None,
                     ProtocolControllers=None,
                     MaskingGroup=None, Members=None):

        rc = 0L
        myjob = SE_ConcreteJob()
        myjob.classname = 'SE_ConcreteJob'
        myjob['InstanceID'] = '9999'
        myjob['status'] = 'success'
        if ElementName == 'failed_vol' and \
                MethodName == 'CreateOrModifyElementFromStoragePool':
            rc = 10L
            myjob['status'] = 'failure'
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
        else:
            result = self._default_enum()
        return result

    def EnumerateInstances(self, name):
        result = None
        if name == 'EMC_VirtualProvisioningPool':
            result = self._enum_pool_details()
        elif name == 'EMC_UnifiedStoragePool':
            result = self._enum_pool_details()
        else:
            result = self._default_enum()
        return result

    def GetInstance(self, objectpath, LocalOnly=False):
        try:
            name = objectpath['CreationClassName']
        except KeyError:
            name = objectpath.classname
        result = None
        if name == 'Clar_StorageVolume':
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
        units = []
        unit = {}

        dependent = {}
        dependent['CreationClassName'] = vol_creationclass
        dependent['DeviceID'] = test_volume['id']
        dependent['ElementName'] = test_volume['name']
        dependent['SystemName'] = storage_system

        antecedent = {}
        antecedent['CreationClassName'] = lunmask_creationclass
        antecedent['DeviceID'] = lunmaskctrl_id
        antecedent['SystemName'] = storage_system

        unit['Dependent'] = dependent
        unit['Antecedent'] = antecedent
        unit['CreationClassName'] = unit_creationclass
        units.append(unit)

        return units

    def _default_ref(self, objectpath):
        return objectpath

    def _assoc_hdwid(self):
        assocs = []
        assoc = {}
        assoc['StorageID'] = initiator1
        assocs.append(assoc)
        return assocs

    def _assoc_endpoint(self):
        assocs = []
        assoc = {}
        assoc['Name'] = 'iqn.1992-04.com.emc:cx.apm00123907237.a8,t,0x0001'
        assoc['SystemName'] = storage_system + '+SP_A+8'
        assocs.append(assoc)
        return assocs

    def _default_assoc(self, objectpath):
        return objectpath

    def _assocnames_lunmaskctrl(self):
        return self._enum_lunmaskctrls()

    def _default_assocnames(self, objectpath):
        return objectpath

    def _getinstance_storagevolume(self, objectpath):
        instance = EMC_StorageVolume()
        vols = self._enum_storagevolumes()
        for vol in vols:
            if vol['DeviceID'] == objectpath['DeviceID']:
                instance = vol
                break
        return instance

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
        lunmask['CreationClassName'] = lunmask_creationclass
        lunmask['DeviceID'] = lunmaskctrl_id
        lunmask['SystemName'] = storage_system
        return lunmask

    def _getinstance_unit(self, objectpath):
        unit = {}

        dependent = {}
        dependent['CreationClassName'] = vol_creationclass
        dependent['DeviceID'] = test_volume['id']
        dependent['ElementName'] = test_volume['name']
        dependent['SystemName'] = storage_system

        antecedent = {}
        antecedent['CreationClassName'] = lunmask_creationclass
        antecedent['DeviceID'] = lunmaskctrl_id
        antecedent['SystemName'] = storage_system

        unit['Dependent'] = dependent
        unit['Antecedent'] = antecedent
        unit['CreationClassName'] = unit_creationclass
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
        rep_service['SystemName'] = storage_system
        rep_service['CreationClassName'] = rep_service_creationclass
        rep_services.append(rep_service)
        return rep_services

    def _enum_stconfsvcs(self):
        conf_services = []
        conf_service = {}
        conf_service['SystemName'] = storage_system
        conf_service['CreationClassName'] = stconf_service_creationclass
        conf_services.append(conf_service)
        return conf_services

    def _enum_ctrlconfsvcs(self):
        conf_services = []
        conf_service = {}
        conf_service['SystemName'] = storage_system
        conf_service['CreationClassName'] = ctrlconf_service_creationclass
        conf_services.append(conf_service)
        return conf_services

    def _enum_pools(self):
        pools = []
        pool = {}
        pool['InstanceID'] = storage_system + '+U+' + storage_type
        pool['CreationClassName'] = 'Clar_UnifiedStoragePool'
        pools.append(pool)
        return pools

    def _enum_pool_details(self):
        pools = []
        pool = {}
        pool['InstanceID'] = storage_system + '+U+' + storage_type
        pool['CreationClassName'] = 'Clar_UnifiedStoragePool'
        pool['TotalManagedSpace'] = 12345678
        pool['RemainingManagedSpace'] = 123456
        pools.append(pool)
        return pools

    def _enum_storagevolumes(self):
        vols = []
        vol = EMC_StorageVolume()
        vol['CreationClassName'] = 'Clar_StorageVolume'
        vol['ElementName'] = test_volume['name']
        vol['DeviceID'] = test_volume['id']
        vol['SystemName'] = storage_system
        vol.path = {'DeviceID': vol['DeviceID']}
        vols.append(vol)

        snap_vol = EMC_StorageVolume()
        snap_vol['CreationClassName'] = 'Clar_StorageVolume'
        snap_vol['ElementName'] = test_snapshot['name']
        snap_vol['DeviceID'] = test_snapshot['id']
        snap_vol['SystemName'] = storage_system
        snap_vol.path = {'DeviceID': snap_vol['DeviceID']}
        vols.append(snap_vol)

        clone_vol = EMC_StorageVolume()
        clone_vol['CreationClassName'] = 'Clar_StorageVolume'
        clone_vol['ElementName'] = test_clone['name']
        clone_vol['DeviceID'] = test_clone['id']
        clone_vol['SystemName'] = storage_system
        clone_vol.path = {'DeviceID': clone_vol['DeviceID']}
        vols.append(clone_vol)

        clone_vol3 = EMC_StorageVolume()
        clone_vol3['CreationClassName'] = 'Clar_StorageVolume'
        clone_vol3['ElementName'] = test_clone3['name']
        clone_vol3['DeviceID'] = test_clone3['id']
        clone_vol3['SystemName'] = storage_system
        clone_vol3.path = {'DeviceID': clone_vol3['DeviceID']}
        vols.append(clone_vol3)

        snap_vol_vmax = EMC_StorageVolume()
        snap_vol_vmax['CreationClassName'] = 'Symm_StorageVolume'
        snap_vol_vmax['ElementName'] = test_snapshot_vmax['name']
        snap_vol_vmax['DeviceID'] = test_snapshot_vmax['id']
        snap_vol_vmax['SystemName'] = storage_system_vmax
        snap_vol_vmax.path = {'DeviceID': snap_vol_vmax['DeviceID']}
        vols.append(snap_vol_vmax)

        failed_snap_replica = EMC_StorageVolume()
        failed_snap_replica['CreationClassName'] = 'Clar_StorageVolume'
        failed_snap_replica['ElementName'] = failed_snapshot_replica['name']
        failed_snap_replica['DeviceID'] = failed_snapshot_replica['id']
        failed_snap_replica['SystemName'] = storage_system
        failed_snap_replica.path = {
            'DeviceID': failed_snap_replica['DeviceID']}
        vols.append(failed_snap_replica)

        failed_snap_sync = EMC_StorageVolume()
        failed_snap_sync['CreationClassName'] = 'Clar_StorageVolume'
        failed_snap_sync['ElementName'] = failed_snapshot_sync['name']
        failed_snap_sync['DeviceID'] = failed_snapshot_sync['id']
        failed_snap_sync['SystemName'] = storage_system
        failed_snap_sync.path = {
            'DeviceID': failed_snap_sync['DeviceID']}
        vols.append(failed_snap_sync)

        failed_clone_rep = EMC_StorageVolume()
        failed_clone_rep['CreationClassName'] = 'Clar_StorageVolume'
        failed_clone_rep['ElementName'] = failed_clone_replica['name']
        failed_clone_rep['DeviceID'] = failed_clone_replica['id']
        failed_clone_rep['SystemName'] = storage_system
        failed_clone_rep.path = {
            'DeviceID': failed_clone_rep['DeviceID']}
        vols.append(failed_clone_rep)

        failed_clone_s = EMC_StorageVolume()
        failed_clone_s['CreationClassName'] = 'Clar_StorageVolume'
        failed_clone_s['ElementName'] = failed_clone_sync['name']
        failed_clone_s['DeviceID'] = failed_clone_sync['id']
        failed_clone_s['SystemName'] = storage_system
        failed_clone_s.path = {
            'DeviceID': failed_clone_s['DeviceID']}
        vols.append(failed_clone_s)

        failed_delete_vol = EMC_StorageVolume()
        failed_delete_vol['CreationClassName'] = 'Clar_StorageVolume'
        failed_delete_vol['ElementName'] = 'failed_delete_vol'
        failed_delete_vol['DeviceID'] = '99999'
        failed_delete_vol['SystemName'] = storage_system
        failed_delete_vol.path = {'DeviceID': failed_delete_vol['DeviceID']}
        vols.append(failed_delete_vol)

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
        ctrl['CreationClassName'] = lunmask_creationclass
        ctrl['DeviceID'] = lunmaskctrl_id
        ctrl['SystemName'] = storage_system
        ctrls.append(ctrl)
        return ctrls

    def _enum_processors(self):
        ctrls = []
        ctrl = {}
        ctrl['CreationClassName'] = 'Clar_StorageProcessorSystem'
        ctrl['Name'] = storage_system + '+SP_A'
        ctrls.append(ctrl)
        return ctrls

    def _default_enum(self):
        names = []
        name = {}
        name['Name'] = 'default'
        names.append(name)
        return names


class EMCSMISISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(EMCSMISISCSIDriverTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file()

        configuration = mox.MockObject(conf.Configuration)
        configuration.cinder_emc_config_file = self.config_file_path
        configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(EMCSMISISCSIDriver, '_do_iscsi_discovery',
                       self.fake_do_iscsi_discovery)
        self.stubs.Set(EMCSMISCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        driver = EMCSMISISCSIDriver(configuration=configuration)
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

        self.config_file_path = self.tempdir + '/' + config_file_name
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

    def test_get_volume_stats(self):
        self.driver.get_volume_stats(True)

    def test_create_destroy(self):
        self.driver.create_volume(test_volume)
        self.driver.delete_volume(test_volume)

    def test_create_volume_snapshot_destroy(self):
        self.driver.create_volume(test_volume)
        self.driver.create_snapshot(test_snapshot)
        self.driver.create_volume_from_snapshot(
            test_clone, test_snapshot)
        self.driver.create_cloned_volume(
            test_clone3, test_volume)
        self.driver.delete_volume(test_clone)
        self.driver.delete_volume(test_clone3)
        self.driver.delete_snapshot(test_snapshot)
        self.driver.delete_volume(test_volume)

    def test_map_unmap(self):
        self.driver.create_volume(test_volume)
        export = self.driver.create_export(None, test_volume)
        test_volume['provider_location'] = export['provider_location']
        test_volume['EMCCurrentOwningStorageProcessor'] = 'SP_A'
        connector = {'initiator': initiator1}
        connection_info = self.driver.initialize_connection(test_volume,
                                                            connector)
        self.driver.terminate_connection(test_volume, connector)
        self.driver.remove_export(None, test_volume)
        self.driver.delete_volume(test_volume)

    def test_create_volume_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          test_failed_volume)

    def test_create_volume_snapshot_unsupported(self):
        self.driver.create_volume(test_volume)
        self.driver.create_snapshot(test_snapshot_vmax)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone,
                          test_snapshot_vmax)
        self.driver.delete_snapshot(test_snapshot_vmax)
        self.driver.delete_volume(test_volume)

    def test_create_volume_snapshot_replica_failed(self):
        self.driver.create_volume(test_volume)
        self.driver.create_snapshot(test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          failed_snapshot_replica,
                          test_snapshot)
        self.driver.delete_snapshot(test_snapshot)
        self.driver.delete_volume(test_volume)

    def test_create_volume_snapshot_sync_failed(self):
        self.driver.create_volume(test_volume)
        self.driver.create_snapshot(test_snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          failed_snapshot_sync,
                          test_snapshot)
        self.driver.delete_snapshot(test_snapshot)
        self.driver.delete_volume(test_volume)

    def test_create_volume_clone_replica_failed(self):
        self.driver.create_volume(test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          failed_clone_replica,
                          test_volume)
        self.driver.delete_volume(test_volume)

    def test_create_volume_clone_sync_failed(self):
        self.driver.create_volume(test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          failed_clone_sync,
                          test_volume)
        self.driver.delete_volume(test_volume)

    def test_delete_volume_notfound(self):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        self.driver.delete_volume(notfound_delete_vol)

    def test_delete_volume_failed(self):
        self.driver.create_volume(failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          failed_delete_vol)

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCSMISISCSIDriverTestCase, self).tearDown()
