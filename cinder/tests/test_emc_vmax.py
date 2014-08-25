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
from cinder.volume.drivers.emc.emc_vmax_common import EMCVMAXCommon
from cinder.volume.drivers.emc.emc_vmax_fast import EMCVMAXFast
from cinder.volume.drivers.emc.emc_vmax_fc import EMCVMAXFCDriver
from cinder.volume.drivers.emc.emc_vmax_iscsi import EMCVMAXISCSIDriver
from cinder.volume.drivers.emc.emc_vmax_masking import EMCVMAXMasking
from cinder.volume.drivers.emc.emc_vmax_utils import EMCVMAXUtils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)
CINDER_EMC_CONFIG_DIR = '/etc/cinder/'


class EMC_StorageVolume(dict):
    pass


class CIM_StorageExtent(dict):
    pass


class SE_InitiatorMaskingGroup(dict):
    pass


class SE_ConcreteJob(dict):
    pass


class SE_StorageHardwareID(dict):
    pass


class Fake_CIMProperty():

    def fake_getCIMProperty(self):
        cimproperty = Fake_CIMProperty()
        cimproperty.value = True
        return cimproperty

    def fake_getBlockSizeCIMProperty(self):
        cimproperty = Fake_CIMProperty()
        cimproperty.value = '512'
        return cimproperty

    def fake_getConsumableBlocksCIMProperty(self):
        cimproperty = Fake_CIMProperty()
        cimproperty.value = '12345'
        return cimproperty

    def fake_getIsConcatenatedCIMProperty(self):
        cimproperty = Fake_CIMProperty()
        cimproperty.value = True
        return cimproperty

    def fake_getIsCompositeCIMProperty(self):
        cimproperty = Fake_CIMProperty()
        cimproperty.value = False
        return cimproperty


class Fake_CIM_TierPolicyServiceCapabilities():

    def fake_getpolicyinstance(self):
        classinstance = Fake_CIM_TierPolicyServiceCapabilities()

        classcimproperty = Fake_CIMProperty()
        cimproperty = classcimproperty.fake_getCIMProperty()

        cimproperties = {u'SupportsTieringPolicies': cimproperty}
        classinstance.properties = cimproperties

        return classinstance


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

    def volume_get(self, context, volume_id):
        conn = FakeEcomConnection()
        objectpath = {}
        objectpath['CreationClassName'] = 'Symm_StorageVolume'

        if volume_id == 'vol1':
            device_id = '1'
            objectpath['DeviceID'] = device_id
        else:
            objectpath['DeviceID'] = volume_id
        return conn.GetInstance(objectpath)


class EMCVMAXCommonData():
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian: 01: 222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost'}
    default_storage_group = (
        u'//10.108.246.202/root/emc: SE_DeviceMaskingGroup.InstanceID='
        '"SYMMETRIX+000198700440+OS_default_GOLD1_SG"')
    storage_system = 'SYMMETRIX+000195900551'
    lunmaskctrl_id =\
        'SYMMETRIX+000195900551+OS-fakehost-gold-MV'
    lunmaskctrl_name =\
        'OS-fakehost-gold-MV'

    initiatorgroup_id =\
        'SYMMETRIX+000195900551+OS-fakehost-IG'
    initiatorgroup_name =\
        'OS-fakehost-IG'
    initiatorgroup_creationclass = 'SE_InitiatorMaskingGroup'

    storageextent_creationclass = 'CIM_StorageExtent'
    initiator1 = 'iqn.1993-08.org.debian: 01: 1a2b3c4d5f6g'
    stconf_service_creationclass = 'Symm_StorageConfigurationService'
    ctrlconf_service_creationclass = 'Symm_ControllerConfigurationService'
    elementcomp_service_creationclass = 'Symm_ElementCompositionService'
    storreloc_service_creationclass = 'Symm_StorageRelocationService'
    replication_service_creationclass = 'EMC_ReplicationService'
    vol_creationclass = 'Symm_StorageVolume'
    pool_creationclass = 'Symm_VirtualProvisioningPool'
    lunmask_creationclass = 'Symm_LunMaskingSCSIProtocolController'
    lunmask_creationclass2 = 'Symm_LunMaskingView'
    hostedservice_creationclass = 'CIM_HostedService'
    policycapability_creationclass = 'CIM_TierPolicyServiceCapabilities'
    policyrule_creationclass = 'Symm_TierPolicyRule'
    assoctierpolicy_creationclass = 'CIM_StorageTier'
    storagepool_creationclass = 'Symm_VirtualProvisioningPool'
    storagegroup_creationclass = 'CIM_DeviceMaskingGroup'
    hardwareid_creationclass = 'SE_StorageHardwareID'
    storagepoolid = 'SYMMETRIX+000195900551+U+gold'
    storagegroupname = 'OS_default_GOLD1_SG'
    storagevolume_creationclass = 'EMC_StorageVolume'
    policyrule = 'gold'
    poolname = 'gold'

    unit_creationclass = 'CIM_ProtocolControllerForUnit'
    storage_type = 'gold'
    keybindings = {'CreationClassName': u'Symm_StorageVolume',
                   'SystemName': u'SYMMETRIX+000195900551',
                   'DeviceID': u'1',
                   'SystemCreationClassName': u'Symm_StorageSystem'}

    keybindings2 = {'CreationClassName': u'Symm_StorageVolume',
                    'SystemName': u'SYMMETRIX+000195900551',
                    'DeviceID': u'99999',
                    'SystemCreationClassName': u'Symm_StorageSystem'}
    provider_location = {'classname': 'Symm_StorageVolume',
                         'keybindings': keybindings}
    provider_location2 = {'classname': 'Symm_StorageVolume',
                          'keybindings': keybindings2}

    properties = {'ConsumableBlocks': '12345',
                  'BlockSize': '512'}

    test_volume = {'name': 'vol1',
                   'size': 1,
                   'volume_name': 'vol1',
                   'id': '1',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'vol1',
                   'display_description': 'test volume',
                   'volume_type_id': 'abc',
                   'provider_location': str(provider_location),
                   'status': 'available',
                   'host': 'fake-host'
                   }
    test_failed_volume = {'name': 'failed_vol',
                          'size': 1,
                          'volume_name': 'failed_vol',
                          'id': '4',
                          'provider_auth': None,
                          'project_id': 'project',
                          'display_name': 'failed_vol',
                          'display_description': 'test failed volume',
                          'volume_type_id': 'abc'}

    failed_delete_vol = {'name': 'failed_delete_vol',
                         'size': '-1',
                         'volume_name': 'failed_delete_vol',
                         'id': '99999',
                         'provider_auth': None,
                         'project_id': 'project',
                         'display_name': 'failed delete vol',
                         'display_description': 'failed delete volume',
                         'volume_type_id': 'abc',
                         'provider_location': str(provider_location2)}

    test_source_volume = {'size': 1,
                          'volume_type_id': 'sourceid',
                          'display_name': 'sourceVolume',
                          'name': 'sourceVolume',
                          'volume_name': 'vmax-154326',
                          'provider_auth': None,
                          'project_id':
                          'project', 'id': '2',
                          'provider_location': str(provider_location),
                          'display_description': 'snapshot source volume'}

    location_info = {'location_info': '000195900551#silver#None',
                     'storage_protocol': 'ISCSI'}
    test_host = {'capabilities': location_info,
                 'host': 'fake_host'}
    test_ctxt = {}
    new_type = {}
    diff = {}


class FakeEcomConnection():

    def __init__(self, *args, **kwargs):
        self.data = EMCVMAXCommonData()

    def InvokeMethod(self, MethodName, Service, ElementName=None, InPool=None,
                     ElementType=None, Size=None,
                     SyncType=None, SourceElement=None,
                     Operation=None, Synchronization=None,
                     TheElements=None, TheElement=None,
                     LUNames=None, InitiatorPortIDs=None, DeviceAccesses=None,
                     ProtocolControllers=None,
                     MaskingGroup=None, Members=None,
                     HardwareId=None, ElementSource=None, EMCInPools=None,
                     CompositeType=None, EMCNumberOfMembers=None,
                     EMCBindElements=None,
                     InElements=None, TargetPool=None, RequestedState=None):

        rc = 0L
        myjob = SE_ConcreteJob()
        myjob.classname = 'SE_ConcreteJob'
        myjob['InstanceID'] = '9999'
        myjob['status'] = 'success'
        myjob['type'] = ElementName

        if Size == -1073741824 and \
                MethodName == 'CreateOrModifyCompositeElement':
            rc = 0L
            myjob = SE_ConcreteJob()
            myjob.classname = 'SE_ConcreteJob'
            myjob['InstanceID'] = '99999'
            myjob['status'] = 'success'
            myjob['type'] = 'failed_delete_vol'
        elif ElementName is None and \
                MethodName == 'CreateOrModifyCompositeElement':
            rc = 0L
            myjob = SE_ConcreteJob()
            myjob.classname = 'SE_ConcreteJob'
            myjob['InstanceID'] = '9999'
            myjob['status'] = 'success'
            myjob['type'] = 'vol1'

        if ElementName == 'failed_vol' and \
                MethodName == 'CreateOrModifyElementFromStoragePool':
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
        if name == 'EMC_StorageConfigurationService':
            result = self._enum_stconfsvcs()
        elif name == 'EMC_ControllerConfigurationService':
            result = self._enum_ctrlconfsvcs()
        elif name == 'Symm_ElementCompositionService':
            result = self._enum_elemcompsvcs()
        elif name == 'Symm_StorageRelocationService':
            result = self._enum_storrelocsvcs()
        elif name == 'EMC_ReplicationService':
            result = self._enum_replicsvcs()
        elif name == 'EMC_VirtualProvisioningPool':
            result = self._enum_pools()
        elif name == 'EMC_StorageVolume':
            result = self._enum_storagevolumes()
        elif name == 'Symm_StorageVolume':
            result = self._enum_storagevolumes()
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._enum_unitnames()
        elif name == 'EMC_LunMaskingSCSIProtocolController':
            result = self._enum_lunmaskctrls()
        elif name == 'EMC_StorageProcessorSystem':
            result = self._enum_processors()
        elif name == 'EMC_StorageHardwareIDManagementService':
            result = self._enum_hdwidmgmts()
        elif name == 'SE_StorageHardwareID':
            result = self._enum_storhdwids()
        else:
            result = self._default_enum()
        return result

    def EnumerateInstances(self, name):
        result = None
        if name == 'EMC_VirtualProvisioningPool':
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
        if name == 'Symm_StorageVolume':
            result = self._getinstance_storagevolume(objectpath)
        elif name == 'CIM_ProtocolControllerForUnit':
            result = self._getinstance_unit(objectpath)
        elif name == 'SE_ConcreteJob':
            result = self._getinstance_job(objectpath)
        elif name == 'SE_StorageSynchronized_SV_SV':
            result = self._getinstance_syncsvsv(objectpath)
        elif name == 'Symm_TierPolicyServiceCapabilities':
            result = self._getinstance_policycapabilities(objectpath)
        elif name == 'CIM_TierPolicyServiceCapabilities':
            result = self._getinstance_policycapabilities(objectpath)
        elif name == 'SE_InitiatorMaskingGroup':
            result = self._getinstance_initiatormaskinggroup(objectpath)
        elif name == 'SE_StorageHardwareID':
            result = self._getinstance_storagehardwareid(objectpath)
        else:
            result = self._default_getinstance(objectpath)

        return result

    def DeleteInstance(self, objectpath):
        pass

    def Associators(self, objectpath, ResultClass='EMC_StorageHardwareID'):
        result = None
        if ResultClass == 'EMC_StorageHardwareID':
            result = self._assoc_hdwid()
        elif ResultClass == 'EMC_iSCSIProtocolEndpoint':
            result = self._assoc_endpoint()
        elif ResultClass == 'EMC_StorageVolume':
            result = self._assoc_storagevolume(objectpath)
        else:
            result = self._default_assoc(objectpath)
        return result

    def AssociatorNames(self, objectpath,
                        ResultClass='default', AssocClass='default'):
        result = None

        if ResultClass == 'EMC_LunMaskingSCSIProtocolController':
            result = self._assocnames_lunmaskctrl()
        elif AssocClass == 'CIM_HostedService':
            result = self._assocnames_hostedservice()
        elif ResultClass == 'CIM_TierPolicyServiceCapabilities':
            result = self._assocnames_policyCapabilities()
        elif ResultClass == 'Symm_TierPolicyRule':
            result = self._assocnames_policyrule()
        elif AssocClass == 'CIM_AssociatedTierPolicy':
            result = self._assocnames_assoctierpolicy()
        elif ResultClass == 'CIM_StoragePool':
            result = self._assocnames_storagepool()
        elif ResultClass == 'EMC_VirtualProvisioningPool':
            result = self._assocnames_storagepool()
        elif ResultClass == 'CIM_DeviceMaskingGroup':
            result = self._assocnames_storagegroup()
        elif ResultClass == 'EMC_StorageVolume':
            result = self._enum_storagevolumes()
        elif ResultClass == 'Symm_StorageVolume':
            result = self._enum_storagevolumes()
        elif ResultClass == 'SE_InitiatorMaskingGroup':
            result = self._enum_initiatorMaskingGroup()
        elif ResultClass == 'CIM_StorageExtent':
            result = self._enum_storage_extent()
        elif ResultClass == 'SE_StorageHardwareID':
            result = self._enum_storhdwids()

        else:
            result = self._default_assocnames(objectpath)
        return result

    def ReferenceNames(self, objectpath,
                       ResultClass='CIM_ProtocolControllerForUnit'):
        result = None
        if ResultClass == 'CIM_ProtocolControllerForUnit':
            result = self._ref_unitnames2()
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

    def _ref_unitnames2(self):
        unitnames = []
        unitname = {}

        dependent = {}
        dependent['CreationClassName'] = self.data.vol_creationclass
        dependent['DeviceID'] = self.data.test_volume['id']
        dependent['ElementName'] = self.data.test_volume['name']
        dependent['SystemName'] = self.data.storage_system

        antecedent = {}
        antecedent['CreationClassName'] = self.data.lunmask_creationclass2
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
        assoc['Name'] = 'iqn.1992-04.com.emc: 50000973f006dd80'
        assoc['SystemName'] = self.data.storage_system
        assocs.append(assoc)
        return assocs

    # Added test for EMC_StorageVolume associators
    def _assoc_storagevolume(self, objectpath):
        assocs = []
        if 'type' not in objectpath:
            vol = self.data.test_volume
        elif objectpath['type'] == 'failed_delete_vol':
            vol = self.data.failed_delete_vol
        elif objectpath['type'] == 'vol1':
            vol = self.data.test_volume
        elif objectpath['type'] == 'appendVolume':
            vol = self.data.test_volume
        elif objectpath['type'] == 'failed_vol':
            vol = self.data.test_failed_volume
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

    def _assocnames_hostedservice(self):
        return self._enum_hostedservice()

    def _assocnames_policyCapabilities(self):
        return self._enum_policycapabilities()

    def _assocnames_policyrule(self):
        return self._enum_policyrules()

    def _assocnames_assoctierpolicy(self):
        return self._enum_assoctierpolicy()

    def _assocnames_storagepool(self):
        return self._enum_storagepool()

    def _assocnames_storagegroup(self):
        return self._enum_storagegroup()

    def _assocnames_storagevolume(self):
        return self._enum_storagevolume()

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

    def _getinstance_lunmask(self):
        lunmask = {}
        lunmask['CreationClassName'] = self.data.lunmask_creationclass
        lunmask['DeviceID'] = self.data.lunmaskctrl_id
        lunmask['SystemName'] = self.data.storage_system
        return lunmask

    def _getinstance_initiatormaskinggroup(self, objectpath):

        initiatorgroup = SE_InitiatorMaskingGroup()
        initiatorgroup['CreationClassName'] = (
            self.data.initiatorgroup_creationclass)
        initiatorgroup['DeviceID'] = self.data.initiatorgroup_id
        initiatorgroup['SystemName'] = self.data.storage_system
        initiatorgroup.path = initiatorgroup
        return initiatorgroup

    def _getinstance_storagehardwareid(self, objectpath):
        hardwareid = SE_StorageHardwareID()
        hardwareid['CreationClassName'] = self.data.hardwareid_creationclass
        hardwareid['SystemName'] = self.data.storage_system
        hardwareid['StorageID'] = self.data.connector['wwpns'][0]
        hardwareid.path = hardwareid
        return hardwareid

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
        unit['DeviceNumber'] = '1'

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

    def _getinstance_policycapabilities(self, policycapabilitypath):
        instance = Fake_CIM_TierPolicyServiceCapabilities()
        fakeinstance = instance.fake_getpolicyinstance()
        return fakeinstance

    def _default_getinstance(self, objectpath):
        return objectpath

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

    def _enum_elemcompsvcs(self):
        comp_services = []
        comp_service = {}
        comp_service['SystemName'] = self.data.storage_system
        comp_service['CreationClassName'] =\
            self.data.elementcomp_service_creationclass
        comp_services.append(comp_service)
        return comp_services

    def _enum_storrelocsvcs(self):
        reloc_services = []
        reloc_service = {}
        reloc_service['SystemName'] = self.data.storage_system
        reloc_service['CreationClassName'] =\
            self.data.storreloc_service_creationclass
        reloc_services.append(reloc_service)
        return reloc_services

    def _enum_replicsvcs(self):
        replic_services = []
        replic_service = {}
        replic_service['SystemName'] = self.data.storage_system
        replic_service['CreationClassName'] =\
            self.data.replication_service_creationclass
        replic_services.append(replic_service)
        return replic_services

    def _enum_pools(self):
        pools = []
        pool = {}
        pool['InstanceID'] = self.data.storage_system + '+U+' +\
            self.data.storage_type
        pool['CreationClassName'] = 'Symm_VirtualProvisioningPool'
        pool['ElementName'] = 'gold'
        pools.append(pool)
        return pools

    def _enum_pool_details(self):
        pools = []
        pool = {}
        pool['InstanceID'] = self.data.storage_system + '+U+' +\
            self.data.storage_type
        pool['CreationClassName'] = 'Symm_VirtualProvisioningPool'
        pool['TotalManagedSpace'] = 12345678
        pool['RemainingManagedSpace'] = 123456
        pools.append(pool)
        return pools

    def _enum_storagevolumes(self):
        vols = []

        vol = EMC_StorageVolume()
        vol['name'] = self.data.test_volume['name']
        vol['CreationClassName'] = 'Symm_StorageVolume'
        vol['ElementName'] = self.data.test_volume['name']
        vol['DeviceID'] = self.data.test_volume['id']
        vol['SystemName'] = self.data.storage_system

        # Added vol to vol.path
        vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        vol.path = vol
        vol.path.classname = vol['CreationClassName']

        classcimproperty = Fake_CIMProperty()
        blocksizecimproperty = classcimproperty.fake_getBlockSizeCIMProperty()
        consumableBlockscimproperty = (
            classcimproperty.fake_getConsumableBlocksCIMProperty())
        isCompositecimproperty = (
            classcimproperty.fake_getIsCompositeCIMProperty())
        properties = {u'ConsumableBlocks': blocksizecimproperty,
                      u'BlockSize': consumableBlockscimproperty,
                      u'IsComposite': isCompositecimproperty}
        vol.properties = properties

        name = {}
        name['classname'] = 'Symm_StorageVolume'
        keys = {}
        keys['CreationClassName'] = 'Symm_StorageVolume'
        keys['SystemName'] = self.data.storage_system
        keys['DeviceID'] = vol['DeviceID']
        keys['SystemCreationClassName'] = 'Symm_StorageSystem'
        name['keybindings'] = keys

        vol['provider_location'] = str(name)

        vols.append(vol)

        failed_delete_vol = EMC_StorageVolume()
        failed_delete_vol['name'] = 'failed_delete_vol'
        failed_delete_vol['CreationClassName'] = 'Symm_StorageVolume'
        failed_delete_vol['ElementName'] = 'failed_delete_vol'
        failed_delete_vol['DeviceID'] = '99999'
        failed_delete_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_delete_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        failed_delete_vol.path = failed_delete_vol
        failed_delete_vol.path.classname =\
            failed_delete_vol['CreationClassName']
        vols.append(failed_delete_vol)

        failed_vol = EMC_StorageVolume()
        failed_vol['name'] = 'failed__vol'
        failed_vol['CreationClassName'] = 'Symm_StorageVolume'
        failed_vol['ElementName'] = 'failed_vol'
        failed_vol['DeviceID'] = '4'
        failed_vol['SystemName'] = self.data.storage_system
        # Added vol to vol.path
        failed_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        failed_vol.path = failed_vol
        failed_vol.path.classname =\
            failed_vol['CreationClassName']

        name_failed = {}
        name_failed['classname'] = 'Symm_StorageVolume'
        keys_failed = {}
        keys_failed['CreationClassName'] = 'Symm_StorageVolume'
        keys_failed['SystemName'] = self.data.storage_system
        keys_failed['DeviceID'] = failed_vol['DeviceID']
        keys_failed['SystemCreationClassName'] = 'Symm_StorageSystem'
        name_failed['keybindings'] = keys_failed
        failed_vol['provider_location'] = str(name_failed)

        vols.append(failed_vol)

        return vols

    def _enum_initiatorMaskingGroup(self):
        initatorgroups = []
        initatorgroup = {}
        initatorgroup['CreationClassName'] = (
            self.data.initiatorgroup_creationclass)
        initatorgroup['DeviceID'] = self.data.initiatorgroup_id
        initatorgroup['SystemName'] = self.data.storage_system
        initatorgroup['ElementName'] = self.data.initiatorgroup_name
#         initatorgroup.path = initatorgroup
#         initatorgroup.path.classname = initatorgroup['CreationClassName']
        initatorgroups.append(initatorgroup)
        return initatorgroups

    def _enum_storage_extent(self):
        storageExtents = []
        storageExtent = CIM_StorageExtent()
        storageExtent['CreationClassName'] = (
            self.data.storageextent_creationclass)

        classcimproperty = Fake_CIMProperty()
        isConcatenatedcimproperty = (
            classcimproperty.fake_getIsConcatenatedCIMProperty())
        properties = {u'IsConcatenated': isConcatenatedcimproperty}
        storageExtent.properties = properties

        storageExtents.append(storageExtent)
        return storageExtents

    def _enum_lunmaskctrls(self):
        ctrls = []
        ctrl = {}
        ctrl['CreationClassName'] = self.data.lunmask_creationclass
        ctrl['DeviceID'] = self.data.lunmaskctrl_id
        ctrl['SystemName'] = self.data.storage_system
        ctrl['ElementName'] = self.data.lunmaskctrl_name
        ctrls.append(ctrl)
        return ctrls

    def _enum_hostedservice(self):
        hostedservices = []
        hostedservice = {}
        hostedservice['CreationClassName'] = (
            self.data.hostedservice_creationclass)
        hostedservice['SystemName'] = self.data.storage_system
        hostedservices.append(hostedservice)
        return hostedservices

    def _enum_policycapabilities(self):
        policycapabilities = []
        policycapability = {}
        policycapability['CreationClassName'] = (
            self.data.policycapability_creationclass)
        policycapability['SystemName'] = self.data.storage_system

        propertiesList = []
        CIMProperty = {'is_array': True}
        properties = {u'SupportedTierFeatures': CIMProperty}
        propertiesList.append(properties)
        policycapability['Properties'] = propertiesList

        policycapabilities.append(policycapability)

        return policycapabilities

    def _enum_policyrules(self):
        policyrules = []
        policyrule = {}
        policyrule['CreationClassName'] = self.data.policyrule_creationclass
        policyrule['SystemName'] = self.data.storage_system
        policyrule['PolicyRuleName'] = self.data.policyrule
        policyrules.append(policyrule)
        return policyrules

    def _enum_assoctierpolicy(self):
        assoctierpolicies = []
        assoctierpolicy = {}
        assoctierpolicy['CreationClassName'] = (
            self.data.assoctierpolicy_creationclass)
        assoctierpolicies.append(assoctierpolicy)
        return assoctierpolicies

    def _enum_storagepool(self):
        storagepools = []
        storagepool = {}
        storagepool['CreationClassName'] = self.data.storagepool_creationclass
        storagepool['InstanceID'] = self.data.storagepoolid
        storagepool['ElementName'] = 'gold'
        storagepools.append(storagepool)
        return storagepools

    def _enum_storagegroup(self):
        storagegroups = []
        storagegroup = {}
        storagegroup['CreationClassName'] = (
            self.data.storagegroup_creationclass)
        storagegroup['ElementName'] = self.data.storagegroupname
        storagegroups.append(storagegroup)
        return storagegroups

    def _enum_storagevolume(self):
        storagevolumes = []
        storagevolume = {}
        storagevolume['CreationClassName'] = (
            self.data.storagevolume_creationclass)
        storagevolumes.append(storagevolume)
        return storagevolumes

    def _enum_hdwidmgmts(self):
        services = []
        srv = {}
        srv['SystemName'] = self.data.storage_system
        services.append(srv)
        return services

    def _enum_storhdwids(self):
        storhdwids = []
        hdwid = SE_StorageHardwareID()
        hdwid['CreationClassName'] = self.data.hardwareid_creationclass
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


class EMCVMAXISCSIDriverNoFastTestCase(test.TestCase):
    def setUp(self):

        self.data = EMCVMAXCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCVMAXISCSIDriverNoFastTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file_no_fast()

        configuration = mock.Mock()
        configuration.safe_get.return_value = 'ISCSINoFAST'
        configuration.cinder_emc_config_file = self.config_file_path
        configuration.config_group = 'ISCSINoFAST'

        self.stubs.Set(EMCVMAXISCSIDriver, 'smis_do_iscsi_discovery',
                       self.fake_do_iscsi_discovery)
        self.stubs.Set(EMCVMAXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCVMAXUtils, 'get_instance_name',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)

        driver = EMCVMAXISCSIDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file_no_fast(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("1234567891011")
        emc.appendChild(array)
        array.appendChild(arraytext)

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

        portgroup = doc.createElement("PortGroup")
        portgrouptext = doc.createTextNode("myPortGroup")
        portgroup.appendChild(portgrouptext)

        portgroups = doc.createElement("PortGroups")
        portgroups.appendChild(portgroup)
        emc.appendChild(portgroups)

        pool = doc.createElement("Pool")
        pooltext = doc.createTextNode("gold")
        emc.appendChild(pool)
        pool.appendChild(pooltext)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("0123456789")
        emc.appendChild(array)
        array.appendChild(arraytext)

        timeout = doc.createElement("Timeout")
        timeouttext = doc.createTextNode("0")
        emc.appendChild(timeout)
        timeout.appendChild(timeouttext)

        filename = 'cinder_emc_config_ISCSINoFAST.xml'

        self.config_file_path = self.tempdir + '/' + filename

        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_do_iscsi_discovery(self, volume, ipAddress):
        output = []
        item = '10.10.0.50: 3260,1 iqn.1992-04.com.emc: 50000973f006dd80'
        output.append(item)
        return output

    def fake_sleep(self, seconds):
        return

    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storageSystem',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'is_tiering_policy_enabled',
        return_value=False)
    @mock.patch.object(
        EMCVMAXUtils,
        'get_pool_capacities',
        return_value=(1234, 1200))
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_array_name_from_file',
        return_value="123456789")
    def test_get_volume_stats_no_fast(self, mock_storage_system,
                                      mock_is_fast_enabled,
                                      mock_capacity, mock_array):
        self.driver.get_volume_stats(True)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_create_volume_no_fast_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: stripedmetacount': '4',
                      'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_create_volume_no_fast_striped_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_delete_volume_no_fast_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_no_fast_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    def test_delete_volume_no_fast_notfound(self, _mock_volume_type):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Symmm_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        notfound_delete_vol['volume_type_id'] = 'abc'
        notfound_delete_vol['provider_location'] = None
        name = {}
        name['classname'] = 'Symm_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys

        self.driver.delete_volume(notfound_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_delete_volume_failed(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'hostlunid': 1,
                      'storagesystem': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_ip_protocol_endpoint',
        return_value='10.10.10.10')
    def test_map_no_fast_success(self, _mock_volume_type, mock_wrap_group,
                                 mock_wrap_device, mock_find_ip):
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)

    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'storagesystem': EMCVMAXCommonData.storage_system})
    def test_map_no_fast_failed(self, mock_wrap_group, mock_wrap_device):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_no_fast_success(self, mock_volume_type,
                                    mock_storage_group):

        self.driver.terminate_connection(
            self.data.test_volume, self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXUtils, 'find_storage_system',
        return_value={'Name': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_no_fast_last_volume_success(
            self, mock_volume_type,
            mock_storage_system, mock_storage_group):
        self.driver.terminate_connection(
            self.data.test_volume, self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'get_volume_size',
        return_value='2147483648')
    def test_extend_volume_no_fast_success(
            self, _mock_volume_type, mock_volume_size):
        newSize = '2'
        self.driver.extend_volume(self.data.test_volume, newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: stripedmetacount': '4',
                      'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'check_if_volume_is_concatenated',
        return_value='False')
    def test_extend_volume_striped_no_fast_failed(
            self, _mock_volume_type, _mock_is_concatenated):
        newSize = '2'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.test_volume,
                          newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_snapshot_no_fast_success(
            self, mock_volume_type,
            mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_snapshot(self.data.test_volume)

    def test_create_snapshot_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_volume_from_snapshot_no_fast_success(
            self, mock_volume_type,
            mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_volume_from_snapshot(
            self.data.test_volume, EMCVMAXCommonData.test_source_volume)

    def test_create_volume_from_snapshot_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_clone_no_fast_success(self, mock_volume_type,
                                          mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_cloned_volume(self.data.test_volume,
                                         EMCVMAXCommonData.test_source_volume)

    def test_create_clone_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    def test_migrate_volume_no_fast_success(self, _mock_volume_type):
        self.driver.migrate_volume(self.data.test_ctxt, self.data.test_volume,
                                   self.data.test_host)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSINoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_pool_instance_id',
        return_value=('silver', 'SYMMETRIX+000195900551'))
    def test_retype_volume_no_fast_success(
            self, _mock_volume_type, mock_values):
        self.driver.retype(
            self.data.test_ctxt, self.data.test_volume, self.data.new_type,
            self.data.diff, self.data.test_host)

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCVMAXISCSIDriverNoFastTestCase, self).tearDown()


class EMCVMAXISCSIDriverFastTestCase(test.TestCase):

    def setUp(self):

        self.data = EMCVMAXCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCVMAXISCSIDriverFastTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file_fast()

        configuration = mock.Mock()
        configuration.cinder_emc_config_file = self.config_file_path
        configuration.safe_get.return_value = 'ISCSIFAST'
        configuration.config_group = 'ISCSIFAST'

        self.stubs.Set(EMCVMAXISCSIDriver, 'smis_do_iscsi_discovery',
                       self.fake_do_iscsi_discovery)
        self.stubs.Set(EMCVMAXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCVMAXUtils, 'get_instance_name',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)
        driver = EMCVMAXISCSIDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file_fast(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("1234567891011")
        emc.appendChild(array)
        array.appendChild(arraytext)

        fastPolicy = doc.createElement("FastPolicy")
        fastPolicyText = doc.createTextNode("GOLD1")
        emc.appendChild(fastPolicy)
        fastPolicy.appendChild(fastPolicyText)

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

        portgroup = doc.createElement("PortGroup")
        portgrouptext = doc.createTextNode("myPortGroup")
        portgroup.appendChild(portgrouptext)

        pool = doc.createElement("Pool")
        pooltext = doc.createTextNode("gold")
        emc.appendChild(pool)
        pool.appendChild(pooltext)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("0123456789")
        emc.appendChild(array)
        array.appendChild(arraytext)

        portgroups = doc.createElement("PortGroups")
        portgroups.appendChild(portgroup)
        emc.appendChild(portgroups)

        filename = 'cinder_emc_config_ISCSIFAST.xml'

        self.config_file_path = self.tempdir + '/' + filename

        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_do_iscsi_discovery(self, volume, ipAddress):
        output = []
        item = '10.10.0.50: 3260,1 iqn.1992-04.com.emc: 50000973f006dd80'
        output.append(item)
        return output

    def fake_sleep(self, seconds):
        return

    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storageSystem',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'is_tiering_policy_enabled',
        return_value=True)
    @mock.patch.object(
        EMCVMAXFast,
        'get_tier_policy_by_name',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'get_capacities_associated_to_policy',
        return_value=(1234, 1200))
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_array_name_from_file',
        return_value="123456789")
    def test_get_volume_stats_fast(self, mock_storage_system,
                                   mock_is_fast_enabled,
                                   mock_get_policy, mock_capacity, mock_array):
        self.driver.get_volume_stats(True)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_create_volume_fast_success(
            self, _mock_volume_type, mock_storage_system, mock_pool_policy):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: stripedmetacount': '4',
                      'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_create_volume_fast_striped_success(
            self, _mock_volume_type, mock_storage_system, mock_pool_policy):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    def test_delete_volume_fast_success(
            self, _mock_volume_type, mock_storage_group):
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_fast_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    def test_delete_volume_fast_notfound(
            self, _mock_volume_type, mock_wrapper):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Symmm_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        name = {}
        name['classname'] = 'Symm_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys
        notfound_delete_vol['volume_type_id'] = 'abc'
        notfound_delete_vol['provider_location'] = None
        self.driver.delete_volume(notfound_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_delete_volume_fast_failed(
            self, _mock_volume_type, _mock_storage_group,
            mock_storage_system, mock_policy_pool):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'hostlunid': 1,
                      'storagesystem': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_ip_protocol_endpoint',
        return_value='10.10.10.10')
    def test_map_fast_success(self, _mock_volume_type, mock_wrap_group,
                              mock_wrap_device, mock_find_ip):
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)

    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'storagesystem': EMCVMAXCommonData.storage_system})
    def test_map_fast_failed(self, mock_wrap_group, mock_wrap_device):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_fast_success(self, mock_volume_type,
                                 mock_storage_group):

        self.driver.terminate_connection(
            self.data.test_volume, self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXUtils, 'find_storage_system',
        return_value={'Name': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_fast_last_volume_success(
            self, mock_volume_type,
            mock_storage_system, mock_storage_group):
        self.driver.terminate_connection(
            self.data.test_volume, self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'get_volume_size',
        return_value='2147483648')
    def test_extend_volume_fast_success(
            self, _mock_volume_type, mock_volume_size):
        newSize = '2'
        self.driver.extend_volume(self.data.test_volume, newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'check_if_volume_is_concatenated',
        return_value='False')
    def test_extend_volume_striped_fast_failed(
            self, _mock_volume_type, _mock_is_concatenated):
        newSize = '2'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.test_volume,
                          newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_snapshot_fast_success(
            self, mock_volume_type, mock_storage_group, mock_volume,
            mock_sync_sv, mock_storage_config_service, mock_controller_service,
            mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_snapshot(self.data.test_volume)

    def test_create_snapshot_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_volume_from_snapshot_fast_success(
            self, mock_volume_type, mock_storage_group, mock_volume,
            mock_sync_sv, mock_storage_config_service, mock_controller_service,
            mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_volume_from_snapshot(
            self.data.test_volume, EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_replication_service',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_volume_from_snapshot_fast_failed(
            self, mock_volume_type,
            mock_rep_service, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_clone_fast_success(self, mock_volume_type,
                                       mock_storage_group, mock_volume,
                                       mock_sync_sv,
                                       mock_storage_config_service,
                                       mock_controller_service,
                                       mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_cloned_volume(self.data.test_volume,
                                         EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_clone_fast_failed(self, mock_volume_type,
                                      mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    def test_migrate_volume_fast_success(self, _mock_volume_type):
        self.driver.migrate_volume(self.data.test_ctxt, self.data.test_volume,
                                   self.data.test_host)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'ISCSIFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_pool_instance_id',
        return_value=('silver', 'SYMMETRIX+000195900551'))
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    def test_retype_volume_fast_success(
            self, _mock_volume_type, mock_values, mock_wrap):
        self.driver.retype(
            self.data.test_ctxt, self.data.test_volume, self.data.new_type,
            self.data.diff, self.data.test_host)

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCVMAXISCSIDriverFastTestCase, self).tearDown()


class EMCVMAXFCDriverNoFastTestCase(test.TestCase):
    def setUp(self):

        self.data = EMCVMAXCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCVMAXFCDriverNoFastTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file_no_fast()

        configuration = mock.Mock()
        configuration.cinder_emc_config_file = self.config_file_path
        configuration.safe_get.return_value = 'FCNoFAST'
        configuration.config_group = 'FCNoFAST'

        self.stubs.Set(EMCVMAXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCVMAXUtils, 'get_instance_name',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)

        driver = EMCVMAXFCDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file_no_fast(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("1234567891011")
        emc.appendChild(array)
        array.appendChild(arraytext)

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

        portgroup = doc.createElement("PortGroup")
        portgrouptext = doc.createTextNode("myPortGroup")
        portgroup.appendChild(portgrouptext)

        portgroups = doc.createElement("PortGroups")
        portgroups.appendChild(portgroup)
        emc.appendChild(portgroups)

        pool = doc.createElement("Pool")
        pooltext = doc.createTextNode("gold")
        emc.appendChild(pool)
        pool.appendChild(pooltext)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("0123456789")
        emc.appendChild(array)
        array.appendChild(arraytext)

        timeout = doc.createElement("Timeout")
        timeouttext = doc.createTextNode("0")
        emc.appendChild(timeout)
        timeout.appendChild(timeouttext)

        filename = 'cinder_emc_config_FCNoFAST.xml'

        self.config_file_path = self.tempdir + '/' + filename

        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_sleep(self, seconds):
        return

    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storageSystem',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'is_tiering_policy_enabled',
        return_value=False)
    @mock.patch.object(
        EMCVMAXUtils,
        'get_pool_capacities',
        return_value=(1234, 1200))
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_array_name_from_file',
        return_value="123456789")
    def test_get_volume_stats_no_fast(self,
                                      mock_storage_system,
                                      mock_is_fast_enabled,
                                      mock_capacity,
                                      mock_array):
        self.driver.get_volume_stats(True)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_create_volume_no_fast_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: stripedmetacount': '4',
                      'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_create_volume_no_fast_striped_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_delete_volume_no_fast_success(
            self, _mock_volume_type, mock_storage_system):
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_no_fast_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    def test_delete_volume_no_fast_notfound(self, _mock_volume_type):
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Symmm_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        name = {}
        name['classname'] = 'Symm_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys
        notfound_delete_vol['volume_type_id'] = 'abc'
        notfound_delete_vol['provider_location'] = None
        self.driver.delete_volume(notfound_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    def test_delete_volume_failed(
            self, _mock_volume_type, mock_storage_system):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'hostlunid': 1,
                      'storagesystem': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_ip_protocol_endpoint',
        return_value='10.10.10.10')
    def test_map_no_fast_success(self, _mock_volume_type, mock_wrap_group,
                                 mock_wrap_device, mock_find_ip):
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)

    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'storagesystem': EMCVMAXCommonData.storage_system})
    def test_map_no_fast_failed(self, mock_wrap_group, mock_wrap_device):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_no_fast_success(self, mock_volume_type,
                                    mock_storage_group):

        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXUtils, 'find_storage_system',
        return_value={'Name': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_no_fast_last_volume_success(self, mock_volume_type,
                                                mock_storage_system,
                                                mock_storage_group):
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'get_volume_size',
        return_value='2147483648')
    def test_extend_volume_no_fast_success(self, _mock_volume_type,
                                           _mock_volume_size):
        newSize = '2'
        self.driver.extend_volume(self.data.test_volume, newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'check_if_volume_is_concatenated',
        return_value='False')
    def test_extend_volume_striped_no_fast_failed(
            self, _mock_volume_type, _mock_is_concatenated):
        newSize = '2'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.test_volume,
                          newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_snapshot_no_fast_success(
            self, mock_volume_type,
            mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_snapshot(self.data.test_volume)

    def test_create_snapshot_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_volume_from_snapshot_no_fast_success(
            self, mock_volume_type,
            mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_volume_from_snapshot(
            self.data.test_volume, EMCVMAXCommonData.test_source_volume)

    def test_create_volume_from_snapshot_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_clone_no_fast_success(self, mock_volume_type,
                                          mock_volume, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_cloned_volume(self.data.test_volume,
                                         EMCVMAXCommonData.test_source_volume)

    def test_create_clone_no_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    def test_migrate_volume_no_fast_success(self, _mock_volume_type):
        self.driver.migrate_volume(self.data.test_ctxt, self.data.test_volume,
                                   self.data.test_host)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCNoFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_pool_instance_id',
        return_value=('silver', 'SYMMETRIX+000195900551'))
    def test_retype_volume_no_fast_success(
            self, _mock_volume_type, mock_values):
        self.driver.retype(
            self.data.test_ctxt, self.data.test_volume, self.data.new_type,
            self.data.diff, self.data.test_host)

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCVMAXFCDriverNoFastTestCase, self).tearDown()


class EMCVMAXFCDriverFastTestCase(test.TestCase):

    def setUp(self):

        self.data = EMCVMAXCommonData()

        self.tempdir = tempfile.mkdtemp()
        super(EMCVMAXFCDriverFastTestCase, self).setUp()
        self.config_file_path = None
        self.create_fake_config_file_fast()

        configuration = mock.Mock()
        configuration.cinder_emc_config_file = self.config_file_path
        configuration.safe_get.return_value = 'FCFAST'
        configuration.config_group = 'FCFAST'

        self.stubs.Set(EMCVMAXCommon, '_get_ecom_connection',
                       self.fake_ecom_connection)
        instancename = FakeCIMInstanceName()
        self.stubs.Set(EMCVMAXUtils, 'get_instance_name',
                       instancename.fake_getinstancename)
        self.stubs.Set(time, 'sleep',
                       self.fake_sleep)

        driver = EMCVMAXFCDriver(configuration=configuration)
        driver.db = FakeDB()
        self.driver = driver

    def create_fake_config_file_fast(self):

        doc = Document()
        emc = doc.createElement("EMC")
        doc.appendChild(emc)

        fastPolicy = doc.createElement("FastPolicy")
        fastPolicyText = doc.createTextNode("GOLD1")
        emc.appendChild(fastPolicy)
        fastPolicy.appendChild(fastPolicyText)

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

        portgroup = doc.createElement("PortGroup")
        portgrouptext = doc.createTextNode("myPortGroup")
        portgroup.appendChild(portgrouptext)

        pool = doc.createElement("Pool")
        pooltext = doc.createTextNode("gold")
        emc.appendChild(pool)
        pool.appendChild(pooltext)

        array = doc.createElement("Array")
        arraytext = doc.createTextNode("0123456789")
        emc.appendChild(array)
        array.appendChild(arraytext)

        portgroups = doc.createElement("PortGroups")
        portgroups.appendChild(portgroup)
        emc.appendChild(portgroups)

        timeout = doc.createElement("Timeout")
        timeouttext = doc.createTextNode("0")
        emc.appendChild(timeout)
        timeout.appendChild(timeouttext)

        filename = 'cinder_emc_config_FCFAST.xml'

        self.config_file_path = self.tempdir + '/' + filename

        f = open(self.config_file_path, 'w')
        doc.writexml(f)
        f.close()

    def fake_ecom_connection(self):
        conn = FakeEcomConnection()
        return conn

    def fake_sleep(self, seconds):
        return

    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storageSystem',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'is_tiering_policy_enabled',
        return_value=True)
    @mock.patch.object(
        EMCVMAXFast,
        'get_tier_policy_by_name',
        return_value=None)
    @mock.patch.object(
        EMCVMAXFast,
        'get_capacities_associated_to_policy',
        return_value=(1234, 1200))
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_array_name_from_file',
        return_value="123456789")
    def test_get_volume_stats_fast(self,
                                   mock_storage_system,
                                   mock_is_fast_enabled,
                                   mock_get_policy,
                                   mock_capacity,
                                   mock_array):
        self.driver.get_volume_stats(True)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_create_volume_fast_success(
            self, _mock_volume_type, mock_storage_system, mock_pool_policy):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: stripedmetacount': '4',
                      'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_create_volume_fast_striped_success(
            self, _mock_volume_type, mock_storage_system, mock_pool_policy):
        self.driver.create_volume(self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    def test_delete_volume_fast_success(self, _mock_volume_type,
                                        mock_storage_group):
        self.driver.delete_volume(self.data.test_volume)

    def test_create_volume_fast_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.data.test_failed_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    def test_delete_volume_fast_notfound(self, _mock_volume_type):
        """We do not set the provider location.
        """
        notfound_delete_vol = {}
        notfound_delete_vol['name'] = 'notfound_delete_vol'
        notfound_delete_vol['id'] = '10'
        notfound_delete_vol['CreationClassName'] = 'Symmm_StorageVolume'
        notfound_delete_vol['SystemName'] = self.data.storage_system
        notfound_delete_vol['DeviceID'] = notfound_delete_vol['id']
        notfound_delete_vol['SystemCreationClassName'] = 'Symm_StorageSystem'
        name = {}
        name['classname'] = 'Symm_StorageVolume'
        keys = {}
        keys['CreationClassName'] = notfound_delete_vol['CreationClassName']
        keys['SystemName'] = notfound_delete_vol['SystemName']
        keys['DeviceID'] = notfound_delete_vol['DeviceID']
        keys['SystemCreationClassName'] =\
            notfound_delete_vol['SystemCreationClassName']
        name['keybindings'] = keys
        notfound_delete_vol['volume_type_id'] = 'abc'
        notfound_delete_vol['provider_location'] = None

        self.driver.delete_volume(notfound_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_pool_and_storage_system',
        return_value=(None, EMCVMAXCommonData.storage_system))
    @mock.patch.object(
        EMCVMAXFast,
        'get_pool_associated_to_policy',
        return_value=1)
    def test_delete_volume_fast_failed(
            self, _mock_volume_type, mock_wrapper,
            mock_storage_system, mock_pool_policy):
        self.driver.create_volume(self.data.failed_delete_vol)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.data.failed_delete_vol)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'hostlunid': 1,
                      'storagesystem': EMCVMAXCommonData.storage_system})
    def test_map_fast_success(self, _mock_volume_type, mock_wrap_group,
                              mock_wrap_device):
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)

    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_wrap_find_device_number',
        return_value={'storagesystem': EMCVMAXCommonData.storage_system})
    def test_map_fast_failed(self, mock_wrap_group, mock_wrap_device):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_fast_success(self, mock_volume_type,
                                 mock_storage_group):

        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils, 'find_storage_system',
        return_value={'Name': EMCVMAXCommonData.storage_system})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    def test_detach_fast_last_volume_success(
            self, mock_volume_type,
            mock_storage_system, mock_storage_group):
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'get_volume_size',
        return_value='2147483648')
    def test_extend_volume_fast_success(self, _mock_volume_type,
                                        _mock_volume_size):
        newSize = '2'
        self.driver.extend_volume(self.data.test_volume, newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'check_if_volume_is_concatenated',
        return_value='False')
    def test_extend_volume_striped_fast_failed(self, _mock_volume_type,
                                               _mock_is_concatenated):
        newSize = '2'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.data.test_volume,
                          newSize)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_snapshot_fast_success(self, mock_volume_type,
                                          mock_storage_group, mock_volume,
                                          mock_sync_sv,
                                          mock_storage_config_service,
                                          mock_controller_config_service,
                                          mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_snapshot(self.data.test_volume)

    def test_create_snapshot_fast_failed(self):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_volume_from_snapshot_fast_success(
            self, mock_volume_type, mock_storage_group, mock_volume,
            mock_sync_sv, mock_storage_config_service,
            mock_controller_config_service, mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_volume_from_snapshot(
            self.data.test_volume, EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype: pool': 'gold',
                      'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_replication_service',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_volume_from_snapshot_fast_failed(self, mock_volume_type,
                                                     mock_rep_service,
                                                     mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST',
                      'FASTPOLICY': 'FC_GOLD1'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_masking_group',
        return_value=EMCVMAXCommonData.storagegroupname)
    @mock.patch.object(
        FakeDB,
        'volume_get',
        return_value=EMCVMAXCommonData.test_source_volume)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    @mock.patch.object(
        EMCVMAXUtils,
        'find_storage_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXUtils,
        'find_controller_configuration_service',
        return_value=1)
    @mock.patch.object(
        EMCVMAXCommon,
        '_get_or_create_default_storage_group',
        return_value=1)
    def test_create_clone_fast_success(self, mock_volume_type,
                                       mock_storage_group, mock_volume,
                                       mock_sync_sv,
                                       mock_storage_config_service,
                                       mock_controller_config_service,
                                       mock_default_sg):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.driver.create_cloned_volume(self.data.test_volume,
                                         EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'find_replication_service',
        return_value=None)
    @mock.patch.object(
        EMCVMAXCommon,
        '_find_storage_sync_sv_sv',
        return_value=(None, None))
    def test_create_clone_fast_failed(self, mock_volume_type,
                                      mock_rep_service, mock_sync_sv):
        self.data.test_volume['volume_name'] = "vmax-1234567"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.data.test_volume,
                          EMCVMAXCommonData.test_source_volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    def test_migrate_volume_fast_success(self, _mock_volume_type):
        self.driver.migrate_volume(self.data.test_ctxt, self.data.test_volume,
                                   self.data.test_host)

    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'volume_backend_name': 'FCFAST'})
    @mock.patch.object(
        EMCVMAXUtils,
        'parse_pool_instance_id',
        return_value=('silver', 'SYMMETRIX+000195900551'))
    @mock.patch.object(
        EMCVMAXMasking,
        '_wrap_get_storage_group_from_volume',
        return_value=None)
    def test_retype_volume_fast_success(
            self, _mock_volume_type, mock_values, mock_wrap):
        self.driver.retype(
            self.data.test_ctxt, self.data.test_volume, self.data.new_type,
            self.data.diff, self.data.test_host)

    def _cleanup(self):
        bExists = os.path.exists(self.config_file_path)
        if bExists:
            os.remove(self.config_file_path)
        shutil.rmtree(self.tempdir)

    def tearDown(self):
        self._cleanup()
        super(EMCVMAXFCDriverFastTestCase, self).tearDown()
