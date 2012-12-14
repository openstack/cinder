# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 EMC Corporation, Inc.
# Copyright (c) 2012 OpenStack LLC.
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

from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume.drivers.emc import EMCISCSIDriver

LOG = logging.getLogger(__name__)

storage_system = 'CLARiiON+APM00123456789'
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


class EMC_StorageVolume(dict):
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
        job = {'status': 'success'}
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
        else:
            result = self._default_enum()
        return result

    def GetInstance(self, objectpath, LocalOnly=False):
        name = objectpath['CreationClassName']
        result = None
        if name == 'Clar_StorageVolume':
            result = self._getinstance_storagevolume(objectpath)
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._getinstance_unit(objectpath)
        elif name == 'Clar_LunMaskingSCSIProtocolController':
            result = self._getinstance_lunmask()
        else:
            result = self._default_getinstance(objectpath)
        return result

    def Associators(self, objectpath, resultClass='EMC_StorageHardwareID'):
        result = None
        if resultClass == 'EMC_StorageHardwareID':
            result = self._assoc_hdwid()
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

        return vols

    def _enum_syncsvsvs(self):
        syncs = []
        sync = {}

        vols = self._enum_storagevolumes()
        objpath1 = vols[0]
        objpath2 = vols[1]
        sync['SyncedElement'] = objpath2
        sync['SystemElement'] = objpath1
        sync['CreationClassName'] = 'SE_StorageSynchronized_SV_SV'
        syncs.append(sync)

        return syncs

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

    def _default_enum(self):
        names = []
        name = {}
        name['Name'] = 'default'
        names.append(name)
        return names


class EMCISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(EMCISCSIDriverTestCase, self).setUp()
        driver = EMCISCSIDriver()
        self.driver = driver
        self.stubs.Set(EMCISCSIDriver, '_get_iscsi_properties',
                       self.fake_get_iscsi_properties)
        self.stubs.Set(EMCISCSIDriver, '_get_ecom_connection',
                       self.fake_ecom_connection)
        self.stubs.Set(EMCISCSIDriver, '_get_storage_type',
                       self.fake_storage_type)

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_get_iscsi_properties(self, volume):
        LOG.info('Fake _get_iscsi_properties.')
        properties = {}
        properties['target_discovered'] = True
        properties['target_portal'] = '10.10.10.10'
        properties['target_iqn'] = 'iqn.1993-08.org.debian:01:a1b2c3d4e5f6'
        device_number = '000008'
        properties['target_lun'] = device_number
        properties['volume_id'] = volume['id']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret
        LOG.info(_("Fake ISCSI properties: %s") % (properties))
        return properties

    def fake_storage_type(self, filename=None):
        return storage_type

    def test_create_destroy(self):
        self.driver.create_volume(test_volume)
        self.driver.delete_volume(test_volume)

    def test_create_volume_snapshot_destroy(self):
        self.driver.create_volume(test_volume)
        self.driver.create_snapshot(test_snapshot)
        self.driver.create_volume_from_snapshot(
            test_clone, test_snapshot)
        self.driver.delete_volume(test_clone)
        self.driver.delete_snapshot(test_snapshot)
        self.driver.delete_volume(test_volume)

    def test_map_unmap(self):
        self.driver.create_volume(test_volume)
        export = self.driver.create_export(None, test_volume)
        test_volume['provider_location'] = export['provider_location']
        connector = {'initiator': initiator1}
        connection_info = self.driver.initialize_connection(test_volume,
                                                            connector)
        self.driver.terminate_connection(test_volume, connector)
        self.driver.remove_export(None, test_volume)
        self.driver.delete_volume(test_volume)
