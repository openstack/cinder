# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

import ast
from copy import deepcopy
import datetime
import platform
import time

from ddt import data
from ddt import ddt
import mock
import requests
import six

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.objects import group
from cinder.objects import group_snapshot
from cinder.objects import volume_attachment
from cinder.objects import volume_type
from cinder import test
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as test_utils
from cinder import version as openstack_version
from cinder.volume.drivers.dell_emc.vmax import common
from cinder.volume.drivers.dell_emc.vmax import fc
from cinder.volume.drivers.dell_emc.vmax import iscsi
from cinder.volume.drivers.dell_emc.vmax import masking
from cinder.volume.drivers.dell_emc.vmax import metadata
from cinder.volume.drivers.dell_emc.vmax import provision
from cinder.volume.drivers.dell_emc.vmax import rest
from cinder.volume.drivers.dell_emc.vmax import utils
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils


CINDER_EMC_CONFIG_DIR = '/etc/cinder/'


class VMAXCommonData(object):
    # array info
    array = '000197800123'
    uni_array = u'000197800123'
    array_herc = '000197900123'
    srp = 'SRP_1'
    srp2 = 'SRP_2'
    slo = 'Diamond'
    workload = 'DSS'
    port_group_name_f = 'OS-fibre-PG'
    port_group_name_i = 'OS-iscsi-PG'
    masking_view_name_f = 'OS-HostX-F-OS-fibre-PG-MV'
    masking_view_name_i = 'OS-HostX-SRP_1-I-OS-iscsi-PG-MV'
    initiatorgroup_name_f = 'OS-HostX-F-IG'
    initiatorgroup_name_i = 'OS-HostX-I-IG'
    parent_sg_f = 'OS-HostX-F-OS-fibre-PG-SG'
    parent_sg_i = 'OS-HostX-I-OS-iscsi-PG-SG'
    storagegroup_name_f = 'OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG'
    storagegroup_name_i = 'OS-HostX-SRP_1-Diamond-DSS-OS-iscsi-PG'
    defaultstoragegroup_name = 'OS-SRP_1-Diamond-DSS-SG'
    storagegroup_list = [defaultstoragegroup_name]
    default_sg_no_slo = 'OS-no_SLO-SG'
    default_sg_compr_disabled = 'OS-SRP_1-Diamond-DSS-CD-SG'
    default_sg_re_enabled = 'OS-SRP_1-Diamond-DSS-RE-SG'
    failed_resource = 'OS-failed-resource'
    fake_host = 'HostX@Backend#Diamond+DSS+SRP_1+000197800123'
    new_host = 'HostX@Backend#Silver+OLTP+SRP_1+000197800123'
    none_host = 'HostX@Backend#Diamond+None+SRP_1+000197800123'
    version = '3.1.0'
    volume_wwn = '600000345'
    remote_array = '000197800124'
    device_id = '00001'
    device_id2 = '00002'
    device_id3 = '00003'
    rdf_group_name = '23_24_007'
    rdf_group_no = '70'
    u4v_version = '84'
    storagegroup_name_source = 'Grp_source_sg'
    storagegroup_name_target = 'Grp_target_sg'
    group_snapshot_name = 'Grp_snapshot'
    target_group_name = 'Grp_target'
    storagegroup_name_with_id = 'GrpId_group_name'
    rdf_managed_async_grp = "OS-%s-Asynchronous-rdf-sg" % rdf_group_name
    volume_id = '2b06255d-f5f0-4520-a953-b029196add6a'
    no_slo_sg_name = 'OS-HostX-No_SLO-OS-fibre-PG'

    # connector info
    wwpn1 = "123456789012345"
    wwpn2 = "123456789054321"
    wwnn1 = "223456789012345"
    initiator = 'iqn.1993-08.org.debian: 01: 222'
    ip, ip2 = u'123.456.7.8', u'123.456.7.9'
    iqn = u'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000001,t,0x0001'
    iqn2 = u'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000002,t,0x0001'
    connector = {'ip': ip,
                 'initiator': initiator,
                 'wwpns': [wwpn1, wwpn2],
                 'wwnns': [wwnn1],
                 'host': 'HostX'}

    fabric_name_prefix = "fakeFabric"
    end_point_map = {connector['wwpns'][0]: [wwnn1],
                     connector['wwpns'][1]: [wwnn1]}
    target_wwns = [wwnn1]
    zoning_mappings = {
        'array': u'000197800123',
        'init_targ_map': end_point_map,
        'initiator_group': initiatorgroup_name_f,
        'port_group': port_group_name_f,
        'target_wwns': target_wwns}
    zoning_mappings_metro = deepcopy(zoning_mappings)
    zoning_mappings_metro.update({'metro_port_group': port_group_name_f,
                                  'metro_ig': initiatorgroup_name_f,
                                  'metro_array': remote_array})

    device_map = {}
    for wwn in connector['wwpns']:
        fabric_name = ''.join([fabric_name_prefix,
                              wwn[-2:]])
        target_wwn = wwn[::-1]
        fabric_map = {'initiator_port_wwn_list': [wwn],
                      'target_port_wwn_list': [target_wwn]
                      }
        device_map[fabric_name] = fabric_map

    iscsi_device_info = {'maskingview': masking_view_name_i,
                         'ip_and_iqn': [{'ip': ip,
                                         'iqn': initiator}],
                         'is_multipath': True,
                         'array': array,
                         'controller': {'host': '10.00.00.00'},
                         'hostlunid': 3}
    iscsi_device_info_metro = deepcopy(iscsi_device_info)
    iscsi_device_info_metro['metro_ip_and_iqn'] = [{'ip': ip2, 'iqn': iqn2}]
    iscsi_device_info_metro['metro_hostlunid'] = 2

    fc_device_info = {'maskingview': masking_view_name_f,
                      'array': array,
                      'controller': {'host': '10.00.00.00'},
                      'hostlunid': 3}

    # cinder volume info
    ctx = context.RequestContext('admin', 'fake', True)
    provider_location = {'array': array,
                         'device_id': device_id}

    provider_location2 = {'array': six.text_type(array),
                          'device_id': device_id2}

    provider_location3 = {'array': six.text_type(remote_array),
                          'device_id': device_id2}

    provider_location4 = {'array': six.text_type(uni_array),
                          'device_id': device_id}

    legacy_provider_location = {
        'classname': 'Symm_StorageVolume',
        'keybindings': {'CreationClassName': u'Symm_StorageVolume',
                        'SystemName': u'SYMMETRIX+000197800123',
                        'DeviceID': device_id,
                        'SystemCreationClassName': u'Symm_StorageSystem'}}

    legacy_provider_location2 = {
        'classname': 'Symm_StorageVolume',
        'keybindings': {'CreationClassName': u'Symm_StorageVolume',
                        'SystemName': u'SYMMETRIX+000197800123',
                        'DeviceID': device_id2,
                        'SystemCreationClassName': u'Symm_StorageSystem'}}

    test_volume_type = fake_volume.fake_volume_type_obj(
        context=ctx
    )

    test_volume = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(provider_location),
        volume_type=test_volume_type, host=fake_host,
        replication_driver_data=six.text_type(provider_location3))

    test_attached_volume = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(provider_location), host=fake_host,
        volume_type=test_volume_type, attach_status="attached",
        replication_driver_data=six.text_type(provider_location3))

    test_legacy_vol = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(legacy_provider_location),
        replication_driver_data=six.text_type(legacy_provider_location2),
        host=fake_host, volume_type=test_volume_type)

    snapshot_id = '390eeb4d-0f56-4a02-ba14-167167967014'

    test_clone_volume = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(provider_location2),
        host=fake_host, source_volid=test_volume.id,
        snapshot_id=snapshot_id, _name_id=test_volume.id)

    test_volume_snap_manage = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        display_name='vol1',
        provider_location=six.text_type(provider_location),
        volume_type=test_volume_type, host=fake_host,
        replication_driver_data=six.text_type(provider_location4))

    snapshot_display_id = 'my_snap'
    managed_snap_id = 'OS-390eeb4d-0f56-4a02-ba14-167167967014'
    test_snapshot_snap_name = 'OS-' + snapshot_id[:6] + snapshot_id[-9:]

    snap_location = {'snap_name': test_snapshot_snap_name,
                     'source_id': device_id}

    test_snapshot = fake_snapshot.fake_snapshot_obj(
        context=ctx, id=snapshot_id,
        name='my_snap', size=2,
        provider_location=six.text_type(snap_location),
        host=fake_host, volume=test_volume)

    test_legacy_snapshot = fake_snapshot.fake_snapshot_obj(
        context=ctx, id=test_volume.id, name='my_snap', size=2,
        provider_location=six.text_type(legacy_provider_location),
        host=fake_host, volume=test_volume)

    test_failed_snap = fake_snapshot.fake_snapshot_obj(
        context=ctx,
        id='4732de9b-98a4-4b6d-ae4b-3cafb3d34220',
        name=failed_resource,
        size=2,
        provider_location=six.text_type(snap_location),
        host=fake_host, volume=test_volume)

    test_snapshot_manage = fake_snapshot.fake_snapshot_obj(
        context=ctx, id=snapshot_id,
        name='my_snap', size=2,
        provider_location=six.text_type(snap_location),
        host=fake_host, volume=test_volume_snap_manage,
        display_name='my_snap')

    test_volume_attachment = volume_attachment.VolumeAttachment(
        id='2b06255d-f5f0-4520-a953-b029196add6b', volume_id=test_volume.id,
        connector=connector)

    location_info = {'location_info': '000197800123#SRP_1#Diamond#DSS',
                     'storage_protocol': 'FC'}
    test_host = {'capabilities': location_info,
                 'host': fake_host}

    # extra-specs
    vol_type_extra_specs = {'pool_name': u'Diamond+DSS+SRP_1+000197800123'}
    vol_type_extra_specs_compr_disabled = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'storagetype:disablecompression': "true"}
    vol_type_extra_specs_rep_enabled = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'replication_enabled': '<is> True'}
    extra_specs = {'pool_name': u'Diamond+DSS+SRP_1+000197800123',
                   'slo': slo,
                   'workload': workload,
                   'srp': srp,
                   'array': array,
                   'interval': 3,
                   'retries': 120}
    extra_specs_disable_compression = deepcopy(extra_specs)
    extra_specs_disable_compression[utils.DISABLECOMPRESSION] = "true"
    extra_specs_intervals_set = deepcopy(extra_specs)
    extra_specs_intervals_set['interval'] = 1
    extra_specs_intervals_set['retries'] = 1
    extra_specs_rep_enabled = deepcopy(extra_specs)
    extra_specs_rep_enabled['replication_enabled'] = True
    rep_extra_specs = deepcopy(extra_specs_rep_enabled)
    rep_extra_specs['array'] = remote_array
    rep_extra_specs['interval'] = 1
    rep_extra_specs['retries'] = 1
    rep_extra_specs['srp'] = srp2
    rep_extra_specs['rep_mode'] = 'Synchronous'
    rep_extra_specs2 = deepcopy(rep_extra_specs)
    rep_extra_specs2[utils.PORTGROUPNAME] = port_group_name_f
    test_volume_type_1 = volume_type.VolumeType(
        id='2b06255d-f5f0-4520-a953-b029196add6a', name='abc',
        extra_specs=extra_specs
    )
    test_volume_type_list = volume_type.VolumeTypeList(
        objects=[test_volume_type_1])

    test_vol_grp_name_id_only = 'ec870a2f-6bf7-4152-aa41-75aad8e2ea96'
    test_vol_grp_name = 'Grp_source_sg_%s' % test_vol_grp_name_id_only
    test_fo_vol_group = 'fo_vol_group_%s' % test_vol_grp_name_id_only

    test_group_1 = group.Group(
        context=None, name=storagegroup_name_source,
        group_id='abc', size=1,
        id=test_vol_grp_name_id_only, status='available',
        provider_auth=None, volume_type_ids=['abc'],
        group_type_id='grptypeid',
        volume_types=test_volume_type_list,
        host=fake_host, provider_location=six.text_type(provider_location))

    test_group_failed = group.Group(
        context=None, name=failed_resource,
        group_id='14b8894e-54ec-450a-b168-c172a16ed166',
        size=1,
        id='318c721c-51ad-4160-bfe1-ebde2273836f',
        status='available',
        provider_auth=None, volume_type_ids=['abc'],
        group_type_id='grptypeid',
        volume_types=test_volume_type_list,
        host=fake_host, provider_location=six.text_type(provider_location),
        replication_status=fields.ReplicationStatus.DISABLED)

    test_rep_group = fake_group.fake_group_obj(
        context=ctx, name=storagegroup_name_source,
        id=test_vol_grp_name_id_only, host=fake_host,
        replication_status=fields.ReplicationStatus.ENABLED)

    test_group = fake_group.fake_group_obj(
        context=ctx, name=storagegroup_name_source,
        id=test_vol_grp_name_id_only, host=fake_host)

    test_group_without_name = fake_group.fake_group_obj(
        context=ctx, name=None,
        id=test_vol_grp_name_id_only, host=fake_host)

    test_group_snapshot_1 = group_snapshot.GroupSnapshot(
        context=None, id='6560405d-b89a-4f79-9e81-ad1752f5a139',
        group_id='876d9fbb-de48-4948-9f82-15c913ed05e7',
        name=group_snapshot_name,
        group_type_id='c6934c26-dde8-4bf8-a765-82b3d0130e9f',
        status='available',
        group=test_group_1)

    test_group_snapshot_failed = group_snapshot.GroupSnapshot(
        context=None, id='0819dd5e-9aa1-4ec7-9dda-c78e51b2ad76',
        group_id='1fc735cb-d36c-4352-8aa6-dc1e16b5a0a7',
        name=failed_resource,
        group_type_id='6b70de13-98c5-46b2-8f24-e4e96a8988fa',
        status='available',
        group=test_group_failed)

    test_volume_group_member = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(provider_location),
        volume_type=test_volume_type, host=fake_host,
        replication_driver_data=six.text_type(provider_location3),
        group_id=test_vol_grp_name_id_only)

    # masking view dict
    masking_view_dict = {
        'array': array,
        'connector': connector,
        'device_id': device_id,
        'init_group_name': initiatorgroup_name_f,
        'initiator_check': None,
        'maskingview_name': masking_view_name_f,
        'parent_sg_name': parent_sg_f,
        'srp': srp,
        'storagetype:disablecompression': False,
        utils.PORTGROUPNAME: port_group_name_f,
        'slo': slo,
        'storagegroup_name': storagegroup_name_f,
        'volume_name': test_volume.name,
        'workload': workload,
        'replication_enabled': False}

    masking_view_dict_no_slo = deepcopy(masking_view_dict)
    masking_view_dict_no_slo.update(
        {'slo': None, 'workload': None,
         'storagegroup_name': no_slo_sg_name})

    masking_view_dict_compression_disabled = deepcopy(masking_view_dict)
    masking_view_dict_compression_disabled.update(
        {'storagetype:disablecompression': True,
         'storagegroup_name': 'OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG-CD'})

    masking_view_dict_replication_enabled = deepcopy(masking_view_dict)
    masking_view_dict_replication_enabled.update(
        {'replication_enabled': True,
         'storagegroup_name': 'OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG-RE'})

    masking_view_dict_multiattach = deepcopy(masking_view_dict)
    masking_view_dict_multiattach.update(
        {utils.EXTRA_SPECS: extra_specs, utils.IS_MULTIATTACH: True,
         utils.OTHER_PARENT_SG: parent_sg_i, utils.FAST_SG:
             storagegroup_name_i, utils.NO_SLO_SG: no_slo_sg_name})

    # vmax data
    # sloprovisioning
    compression_info = {"symmetrixId": ["000197800128"]}
    inititiatorgroup = [{"initiator": [wwpn1],
                         "hostId": initiatorgroup_name_f,
                         "maskingview": [masking_view_name_f]},
                        {"initiator": [initiator],
                         "hostId": initiatorgroup_name_i,
                         "maskingview": [masking_view_name_i]}]

    initiator_list = [{"host": initiatorgroup_name_f,
                       "initiatorId": wwpn1,
                       "maskingview": [masking_view_name_f]},
                      {"host": initiatorgroup_name_i,
                       "initiatorId": initiator,
                       "maskingview": [masking_view_name_i]},
                      {"initiatorId": [
                          "FA-1D:4:" + wwpn1,
                          "SE-4E:0:" + initiator]}]

    maskingview = [{"maskingViewId": masking_view_name_f,
                    "portGroupId": port_group_name_f,
                    "storageGroupId": storagegroup_name_f,
                    "hostId": initiatorgroup_name_f,
                    "maskingViewConnection": [
                        {"host_lun_address": "0003"}]},
                   {"maskingViewId": masking_view_name_i,
                    "portGroupId": port_group_name_i,
                    "storageGroupId": storagegroup_name_i,
                    "hostId": initiatorgroup_name_i,
                    "maskingViewConnection": [
                        {"host_lun_address": "0003"}]},
                   {}]

    portgroup = [{"portGroupId": port_group_name_f,
                  "symmetrixPortKey": [
                      {"directorId": "FA-1D",
                       "portId": "FA-1D:4"}],
                  "maskingview": [masking_view_name_f]},
                 {"portGroupId": port_group_name_i,
                  "symmetrixPortKey": [
                      {"directorId": "SE-4E",
                       "portId": "SE-4E:0"}],
                  "maskingview": [masking_view_name_i]}]

    port_list = [
        {"symmetrixPort": {"num_of_masking_views": 1,
                           "maskingview": [masking_view_name_f],
                           "identifier": wwnn1,
                           "symmetrixPortKey": {
                               "directorId": "FA-1D",
                               "portId": "4"},
                           "portgroup": [port_group_name_f]}},
        {"symmetrixPort": {"identifier": initiator,
                           "symmetrixPortKey": {
                               "directorId": "SE-4E",
                               "portId": "0"},
                           "ip_addresses": [ip],
                           "num_of_masking_views": 1,
                           "maskingview": [masking_view_name_i],
                           "portgroup": [port_group_name_i]}}]

    sg_details = [{"srp": srp,
                   "num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": defaultstoragegroup_name,
                   "slo": slo,
                   "workload": workload},
                  {"srp": srp,
                   "num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": storagegroup_name_f,
                   "slo": slo,
                   "workload": workload,
                   "maskingview": [masking_view_name_f],
                   "parent_storage_group": [parent_sg_f]},
                  {"srp": srp,
                   "num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": storagegroup_name_i,
                   "slo": slo,
                   "workload": workload,
                   "maskingview": [masking_view_name_i],
                   "parent_storage_group": [parent_sg_i]},
                  {"num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": parent_sg_f,
                   "num_of_child_sgs": 1,
                   "child_storage_group": [storagegroup_name_f],
                   "maskingview": [masking_view_name_f]},
                  {"num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": parent_sg_i,
                   "num_of_child_sgs": 1,
                   "child_storage_group": [storagegroup_name_i],
                   "maskingview": [masking_view_name_i], },
                  {"srp": srp,
                   "num_of_vols": 2,
                   "cap_gb": 2,
                   "storageGroupId": no_slo_sg_name,
                   "slo": None,
                   "workload": None,
                   "maskingview": [masking_view_name_i],
                   "parent_storage_group": [parent_sg_i]}
                  ]

    sg_details_rep = [{"childNames": [],
                       "numDevicesNonGk": 2,
                       "isLinkTarget": False,
                       "rdf": True,
                       "capacityGB": 2.0,
                       "name": storagegroup_name_source,
                       "snapVXSnapshots": ['6560405d-752f5a139'],
                       "symmetrixId": array,
                       "numSnapVXSnapshots": 1}]

    sg_rdf_details = [{"storageGroupName": test_vol_grp_name,
                       "symmetrixId": array,
                       "modes": ["Synchronous"],
                       "rdfGroupNumber": rdf_group_no,
                       "states": ["Synchronized"]},
                      {"storageGroupName": test_fo_vol_group,
                       "symmetrixId": array,
                       "modes": ["Synchronous"],
                       "rdfGroupNumber": rdf_group_no,
                       "states": ["Failed Over"]}]

    sg_list = {"storageGroupId": [storagegroup_name_f,
                                  defaultstoragegroup_name]}

    sg_list_rep = [storagegroup_name_with_id]

    srp_details = {"srpSloDemandId": ["Bronze", "Diamond", "Gold",
                                      "None", "Optimized", "Silver"],
                   "srpId": srp,
                   "total_used_cap_gb": 5244.7,
                   "total_usable_cap_gb": 20514.4,
                   "total_subscribed_cap_gb": 84970.1,
                   "fba_used_capacity": 5244.7,
                   "reserved_cap_percent": 10}

    array_info_wl = {'RestServerIp': '1.1.1.1', 'RestServerPort': 3448,
                     'RestUserName': 'smc', 'RestPassword': 'smc',
                     'SSLVerify': False, 'SerialNumber': array,
                     'srpName': 'SRP_1', 'PortGroup': port_group_name_i,
                     'SLO': 'Diamond', 'Workload': 'OLTP'}

    array_info_no_wl = {'RestServerIp': '1.1.1.1', 'RestServerPort': 3448,
                        'RestUserName': 'smc', 'RestPassword': 'smc',
                        'SSLVerify': False, 'SerialNumber': array,
                        'srpName': 'SRP_1', 'PortGroup': port_group_name_i,
                        'SLO': 'Diamond'}

    volume_details = [{"cap_gb": 2,
                       "num_of_storage_groups": 1,
                       "volumeId": device_id,
                       "volume_identifier": "OS-%s" % test_volume.id,
                       "wwn": volume_wwn,
                       "snapvx_target": 'false',
                       "snapvx_source": 'false',
                       "storageGroupId": [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {"cap_gb": 1,
                       "num_of_storage_groups": 1,
                       "volumeId": device_id2,
                       "volume_identifier": "OS-%s" % test_volume.id,
                       "wwn": '600012345',
                       "storageGroupId": [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {"cap_gb": 1,
                       "num_of_storage_groups": 0,
                       "volumeId": device_id3,
                       "volume_identifier": '123',
                       "wwn": '600012345'}]

    volume_list = [
        {"resultList": {"result": [{"volumeId": device_id}]}},
        {"resultList": {"result": [{"volumeId": device_id2}]}},
        {"resultList": {"result": [{"volumeId": device_id},
                                   {"volumeId": device_id2}]}}]

    private_vol_details = {
        "resultList": {
            "result": [{
                "timeFinderInfo": {
                    "snapVXSession": [
                        {"srcSnapshotGenInfo": [
                            {"snapshotHeader": {
                                "snapshotName": "temp-1",
                                "device": device_id,
                                "generation": "0"},
                                "lnkSnapshotGenInfo": [
                                    {"targetDevice": device_id2,
                                     "state": "Copied"}]}]},
                        {"tgtSrcSnapshotGenInfo": {
                            "snapshotName": "temp-1",
                            "targetDevice": device_id2,
                            "sourceDevice": device_id,
                            "generation": "0",
                            "state": "Copied"}}],
                    "snapVXSrc": 'true',
                    "snapVXTgt": 'true'},
                "rdfInfo": {"RDFSession": [
                    {"SRDFStatus": "Ready",
                     "pairState": "Synchronized",
                     "remoteDeviceID": device_id2,
                     "remoteSymmetrixID": remote_array}]}}]}}

    # Service Levels / Workloads
    workloadtype = {"workloadId": ["OLTP", "OLTP_REP", "DSS", "DSS_REP"]}
    srp_slo_details = {"serviceLevelDemand": [
        {"serviceLevelId": "None"}, {"serviceLevelId": "Diamond"},
        {"serviceLevelId": "Gold"}, {"serviceLevelId": "Optimized"}]}
    slo_details = ['None', 'Diamond', 'Gold', 'Optimized']
    powermax_slo_details = {"sloId": ["Bronze", "Diamond", "Gold",
                                      "Optimized", "Platinum", "Silver"]}
    powermax_model_details = {"symmetrixId": array,
                              "model": "PowerMax_2000",
                              "ucode": "5978.1091.1092"}
    vmax_slo_details = {"sloId": ["Diamond", "Optimized"]}
    vmax_model_details = {"model": "VMAX450F"}

    # replication
    volume_snap_vx = {"snapshotLnks": [],
                      "snapshotSrcs": [
                          {"generation": 0,
                           "linkedDevices": [
                               {"targetDevice": device_id2,
                                "percentageCopied": 100,
                                "state": "Copied",
                                "copy": True,
                                "defined": True,
                                "linked": True}],
                           "snapshotName": test_snapshot_snap_name,
                           "state": "Established"}]}
    capabilities = {"symmetrixCapability": [{"rdfCapable": True,
                                             "snapVxCapable": True,
                                             "symmetrixId": "0001111111"},
                                            {"symmetrixId": array,
                                             "snapVxCapable": True,
                                             "rdfCapable": True}]}
    group_snap_vx = {"generation": 0,
                     "isLinked": False,
                     "numUniqueTracks": 0,
                     "isRestored": False,
                     "name": group_snapshot_name,
                     "numStorageGroupVolumes": 1,
                     "state": ["Established"],
                     "timeToLiveExpiryDate": "N/A",
                     "isExpired": False,
                     "numSharedTracks": 0,
                     "timestamp": "00:30:50 Fri, 02 Jun 2017 IST +0100",
                     "numSourceVolumes": 1
                     }
    group_snap_vx_1 = {"generation": 0,
                       "isLinked": False,
                       "numUniqueTracks": 0,
                       "isRestored": False,
                       "name": group_snapshot_name,
                       "numStorageGroupVolumes": 1,
                       "state": ["Copied"],
                       "timeToLiveExpiryDate": "N/A",
                       "isExpired": False,
                       "numSharedTracks": 0,
                       "timestamp": "00:30:50 Fri, 02 Jun 2017 IST +0100",
                       "numSourceVolumes": 1,
                       "linkedStorageGroup":
                           {"name": target_group_name,
                            "percentageCopied": 100},
                       }
    grp_snapvx_links = [{"name": target_group_name,
                         "percentageCopied": 100},
                        {"name": "another-target",
                         "percentageCopied": 90}]

    rdf_group_list = {"rdfGroupID": [{"rdfgNumber": rdf_group_no,
                                      "label": rdf_group_name}]}
    rdf_group_details = {"modes": ["Synchronous"],
                         "remoteSymmetrix": remote_array,
                         "label": rdf_group_name,
                         "type": "Dynamic",
                         "numDevices": 1,
                         "remoteRdfgNumber": rdf_group_no,
                         "rdfgNumber": rdf_group_no}
    rdf_group_vol_details = {"remoteRdfGroupNumber": rdf_group_no,
                             "localSymmetrixId": array,
                             "volumeConfig": "RDF1+TDEV",
                             "localRdfGroupNumber": rdf_group_no,
                             "localVolumeName": device_id,
                             "rdfpairState": "Synchronized",
                             "remoteVolumeName": device_id2,
                             "localVolumeState": "Ready",
                             "rdfMode": "Synchronous",
                             "remoteVolumeState": "Write Disabled",
                             "remoteSymmetrixId": remote_array}

    # system
    job_list = [{"status": "SUCCEEDED",
                 "jobId": "12345",
                 "result": "created",
                 "resourceLink": "storagegroup/%s" % storagegroup_name_f},
                {"status": "RUNNING", "jobId": "55555"},
                {"status": "FAILED", "jobId": "09999"}]
    symmetrix = [{"symmetrixId": array,
                  "model": "VMAX250F",
                  "ucode": "5977.1091.1092"},
                 {"symmetrixId": array_herc,
                  "model": "VMAXHERC",
                  "ucode": "5978.1091.1092"}]
    version_details = {"version": "V9.0.0.1"}

    headroom = {"headroom": [{"headroomCapacity": 20348.29}]}

    private_vol_rest_response_single = {
        "id": "f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0", "count": 1,
        "expirationTime": 1521650650793, "maxPageSize": 1000,
        "resultList": {"to": 1, "from": 1, "result": [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
                "status": "Ready", "configuration": "TDEV"}}]}}
    private_vol_rest_response_none = {
        "id": "f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0", "count": 0,
        "expirationTime": 1521650650793, "maxPageSize": 1000,
        "resultList": {"to": 0, "from": 0, "result": []}}
    private_vol_rest_response_iterator_first = {
        "id": "f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0", "count": 1500,
        "expirationTime": 1521650650793, "maxPageSize": 1000,
        "resultList": {"to": 1, "from": 1, "result": [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00002",
                "status": "Ready", "configuration": "TDEV"}}]}}
    private_vol_rest_response_iterator_second = {
        "to": 2000, "from": 1001, "result": [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
                "status": "Ready", "configuration": "TDEV"}}]}
    rest_iterator_resonse_one = {
        "to": 1000, "from": 1, "result": [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
                "status": "Ready", "configuration": "TDEV"}}]}
    rest_iterator_resonse_two = {
        "to": 1500, "from": 1001, "result": [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00002",
                "status": "Ready", "configuration": "TDEV"}}]}

    # COMMON.PY
    priv_vol_func_response_single = [
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 1026.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00001", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00001",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {
                "mirror": False, "snapVXTgt": False,
                "cloneTarget": False, "cloneSrc": False,
                "snapVXSrc": True, "snapVXSession": [
                    {"srcSnapshotGenInfo": [
                        {"snapshotHeader": {
                            "timestamp": 1512763278000, "expired": False,
                            "secured": False, "snapshotName": "testSnap1",
                            "device": "00001", "generation": 0, "timeToLive": 0
                        }}]}]}}]

    priv_vol_func_response_multi = [
        {"volumeHeader": {
            "private": False, "capGB": 100.0, "capMB": 102400.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00001", "status": "Ready", "numStorageGroups": 0,
            "reservationInfo": {"reserved": False}, "mapped": False,
            "encapsulated": False, "formattedName": "00001",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "maskingInfo": {"masked": False},
            "timeFinderInfo": {
                "mirror": False, "snapVXTgt": False,
                "cloneTarget": False, "cloneSrc": False,
                "snapVXSrc": True, "snapVXSession": [
                    {"srcSnapshotGenInfo": [
                        {"snapshotHeader": {
                            "timestamp": 1512763278000, "expired": False,
                            "secured": False, "snapshotName": "testSnap1",
                            "device": "00001", "generation": 0, "timeToLive": 0
                        }}]}]}},
        {"volumeHeader": {
            "private": False, "capGB": 200.0, "capMB": 204800.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00002", "status": "Ready", "numStorageGroups": 0,
            "reservationInfo": {"reserved": False}, "mapped": False,
            "encapsulated": False, "formattedName": "00002",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "maskingInfo": {"masked": False},
            "timeFinderInfo": {
                "mirror": False, "snapVXTgt": False,
                "cloneTarget": False, "cloneSrc": False,
                "snapVXSrc": True, "snapVXSession": [
                    {"srcSnapshotGenInfo": [
                        {"snapshotHeader": {
                            "timestamp": 1512763278000, "expired": False,
                            "secured": False, "snapshotName": "testSnap2",
                            "device": "00002", "generation": 0, "timeToLive": 0
                        }}]}]}},
        {"volumeHeader": {
            "private": False, "capGB": 300.0, "capMB": 307200.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00003", "status": "Ready", "numStorageGroups": 0,
            "reservationInfo": {"reserved": False}, "mapped": False,
            "encapsulated": False, "formattedName": "00003",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "maskingInfo": {"masked": False},
            "timeFinderInfo": {
                "mirror": False, "snapVXTgt": False,
                "cloneTarget": False, "cloneSrc": False,
                "snapVXSrc": True, "snapVXSession": [
                    {"srcSnapshotGenInfo": [
                        {"snapshotHeader": {
                            "timestamp": 1512763278000, "expired": False,
                            "secured": False, "snapshotName": "testSnap3",
                            "device": "00003", "generation": 0, "timeToLive": 0
                        }}]}]}},
        {"volumeHeader": {
            "private": False, "capGB": 400.0, "capMB": 409600.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00004", "status": "Ready", "numStorageGroups": 0,
            "reservationInfo": {"reserved": False}, "mapped": False,
            "encapsulated": False, "formattedName": "00004",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "maskingInfo": {"masked": False},
            "timeFinderInfo": {
                "mirror": False, "snapVXTgt": False,
                "cloneTarget": False, "cloneSrc": False,
                "snapVXSrc": True, "snapVXSession": [
                    {"srcSnapshotGenInfo": [
                        {"snapshotHeader": {
                            "timestamp": 1512763278000, "expired": False,
                            "secured": False, "snapshotName": "testSnap4",
                            "device": "00004", "generation": 0, "timeToLive": 0
                        }}]}]}}]

    priv_vol_func_response_multi_invalid = [
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 10.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00001", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00001",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {"snapVXTgt": False, "snapVXSrc": False}},
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 1026.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00002", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00002",
            "system_resource": False, "numSymDevMaskingViews": 1,
            "nameModifier": "", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {"snapVXTgt": False, "snapVXSrc": False}},
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 1026.0,
            "serviceState": "Normal", "emulationType": "CKD",
            "volumeId": "00003", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00003",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {"snapVXTgt": False, "snapVXSrc": False}},
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 1026.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00004", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00004",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {"snapVXTgt": True, "snapVXSrc": False}},
        {"volumeHeader": {
            "private": False, "capGB": 1.0, "capMB": 1026.0,
            "serviceState": "Normal", "emulationType": "FBA",
            "volumeId": "00005", "status": "Ready", "mapped": False,
            "numStorageGroups": 0, "reservationInfo": {"reserved": False},
            "encapsulated": False, "formattedName": "00005",
            "system_resource": False, "numSymDevMaskingViews": 0,
            "nameModifier": "OS-vol", "configuration": "TDEV"},
            "maskingInfo": {"masked": False},
            "rdfInfo": {
                "dynamicRDF": False, "RDF": False,
                "concurrentRDF": False,
                "getDynamicRDFCapability": "RDF1_Capable", "RDFA": False},
            "timeFinderInfo": {"snapVXTgt": False, "snapVXSrc": False}}]

    volume_info_dict = {
        'volume_id': volume_id,
        'service_level': 'Diamond',
        'masking_view': 'OS-HostX-F-OS-fibre-PG-MV',
        'host': fake_host,
        'display_name': 'attach_vol_name',
        'volume_updated_time': '2018-03-05 20:32:41',
        'port_group': 'OS-fibre-PG',
        'operation': 'attach', 'srp': 'SRP_1',
        'initiator_group': 'OS-HostX-F-IG',
        'serial_number': '000197800123',
        'parent_storage_group': 'OS-HostX-F-OS-fibre-PG-SG',
        'workload': 'DSS',
        'child_storage_group': 'OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG'}

    data_dict = {volume_id: volume_info_dict}
    platform = 'Linux-4.4.0-104-generic-x86_64-with-Ubuntu-16.04-xenial'
    unisphere_version = u'V9.0.0.1'
    openstack_release = '12.0.0.0b3.dev401'
    openstack_version = '12.0.0'
    python_version = '2.7.12'
    vmax_driver_version = '3.1'
    vmax_firmware_version = u'5977.1125.1125'
    vmax_model = u'VMAX250F'

    version_dict = {
        'unisphere_version': unisphere_version,
        'openstack_release': openstack_release,
        'openstack_version': openstack_version,
        'python_version': python_version,
        'vmax_driver_version': vmax_driver_version,
        'platform': platform,
        'vmax_firmware_version': vmax_firmware_version,
        'serial_number': array,
        'vmax_model': vmax_model}


class FakeLookupService(object):
    def get_device_mapping_from_network(self, initiator_wwns, target_wwns):
        return VMAXCommonData.device_map


class FakeResponse(object):

    def __init__(self, status_code, return_object):
        self.status_code = status_code
        self.return_object = return_object

    def json(self):
        if self.return_object:
            return self.return_object
        else:
            raise ValueError


class FakeRequestsSession(object):

    def __init__(self, *args, **kwargs):
        self.data = VMAXCommonData()

    def request(self, method, url, params=None, data=None):
        return_object = ''
        status_code = 200
        if method == 'GET':
            status_code, return_object = self._get_request(url, params)

        elif method == 'POST' or method == 'PUT':
            status_code, return_object = self._post_or_put(url, data)

        elif method == 'DELETE':
            status_code, return_object = self._delete(url)

        elif method == 'TIMEOUT':
            raise requests.Timeout

        elif method == 'EXCEPTION':
            raise Exception

        return FakeResponse(status_code, return_object)

    def _get_request(self, url, params):
        status_code = 200
        return_object = None
        if self.data.failed_resource in url:
            status_code = 500
            return_object = self.data.job_list[2]
        elif 'sloprovisioning' in url:
            if 'volume' in url:
                return_object = self._sloprovisioning_volume(url, params)
            elif 'storagegroup' in url:
                return_object = self._sloprovisioning_sg(url)
            elif 'maskingview' in url:
                return_object = self._sloprovisioning_mv(url)
            elif 'portgroup' in url:
                return_object = self._sloprovisioning_pg(url)
            elif 'director' in url:
                return_object = self._sloprovisioning_port(url)
            elif 'host' in url:
                return_object = self._sloprovisioning_ig(url)
            elif 'initiator' in url:
                return_object = self._sloprovisioning_initiator(url)
            elif 'service_level_demand_report' in url:
                return_object = self.data.srp_slo_details
            elif 'srp' in url:
                return_object = self.data.srp_details
            elif 'workloadtype' in url:
                return_object = self.data.workloadtype
            elif 'compressionCapable' in url:
                return_object = self.data.compression_info
            elif 'slo' in url:
                return_object = self.data.powermax_slo_details

        elif 'replication' in url:
            return_object = self._replication(url)

        elif 'system' in url:
            return_object = self._system(url)

        elif 'headroom' in url:
            return_object = self.data.headroom

        return status_code, return_object

    def _sloprovisioning_volume(self, url, params):
        return_object = self.data.volume_list[2]
        if '/private' in url:
            return_object = self.data.private_vol_details
        elif params:
            if '1' in params.values():
                return_object = self.data.volume_list[0]
            elif '2' in params.values():
                return_object = self.data.volume_list[1]
        else:
            for vol in self.data.volume_details:
                if vol['volumeId'] in url:
                    return_object = vol
                    break
        return return_object

    def _sloprovisioning_sg(self, url):
        return_object = self.data.sg_list
        for sg in self.data.sg_details:
            if sg['storageGroupId'] in url:
                return_object = sg
                break
        return return_object

    def _sloprovisioning_mv(self, url):
        if self.data.masking_view_name_i in url:
            return_object = self.data.maskingview[1]
        else:
            return_object = self.data.maskingview[0]
        return return_object

    def _sloprovisioning_pg(self, url):
        return_object = None
        for pg in self.data.portgroup:
            if pg['portGroupId'] in url:
                return_object = pg
                break
        return return_object

    def _sloprovisioning_port(self, url):
        return_object = None
        for port in self.data.port_list:
            if port['symmetrixPort']['symmetrixPortKey']['directorId'] in url:
                return_object = port
                break
        return return_object

    def _sloprovisioning_ig(self, url):
        return_object = None
        for ig in self.data.inititiatorgroup:
            if ig['hostId'] in url:
                return_object = ig
                break
        return return_object

    def _sloprovisioning_initiator(self, url):
        return_object = self.data.initiator_list[2]
        if self.data.wwpn1 in url:
            return_object = self.data.initiator_list[0]
        elif self.data.initiator in url:
            return_object = self.data.initiator_list[1]
        return return_object

    def _replication(self, url):
        return_object = None
        if 'storagegroup' in url:
            return_object = self._replication_sg(url)
        elif 'rdf_group' in url:
            if self.data.device_id in url:
                return_object = self.data.rdf_group_vol_details
            elif self.data.rdf_group_no in url:
                return_object = self.data.rdf_group_details
            else:
                return_object = self.data.rdf_group_list
        elif 'snapshot' in url:
            return_object = self.data.volume_snap_vx
        elif 'capabilities' in url:
            return_object = self.data.capabilities
        return return_object

    def _replication_sg(self, url):
        return_object = None
        if 'generation' in url:
            return_object = self.data.group_snap_vx
        elif 'rdf_group' in url:
            for sg in self.data.sg_rdf_details:
                if sg['storageGroupName'] in url:
                    return_object = sg
                    break
        elif 'storagegroup' in url:
            return_object = self.data.sg_details_rep[0]
        return return_object

    def _system(self, url):
        return_object = None
        if 'job' in url:
            for job in self.data.job_list:
                if job['jobId'] in url:
                    return_object = job
                    break
        elif 'version' in url:
            return_object = self.data.version_details
        else:
            for symm in self.data.symmetrix:
                if symm['symmetrixId'] in url:
                    return_object = symm
                    break
        return return_object

    def _post_or_put(self, url, payload):
        return_object = self.data.job_list[0]
        status_code = 201
        if self.data.failed_resource in url:
            status_code = 500
            return_object = self.data.job_list[2]
        elif payload:
            payload = ast.literal_eval(payload)
            if self.data.failed_resource in payload.values():
                status_code = 500
                return_object = self.data.job_list[2]
            if payload.get('executionOption'):
                status_code = 202
        return status_code, return_object

    def _delete(self, url):
        if self.data.failed_resource in url:
            status_code = 500
            return_object = self.data.job_list[2]
        else:
            status_code = 204
            return_object = None
        return status_code, return_object

    def session(self):
        return FakeRequestsSession()


class FakeConfiguration(object):

    def __init__(self, emc_file=None, volume_backend_name=None,
                 interval=0, retries=0, replication_device=None, **kwargs):
        self.cinder_dell_emc_config_file = emc_file
        self.interval = interval
        self.retries = retries
        self.volume_backend_name = volume_backend_name
        self.config_group = volume_backend_name
        self.san_is_local = False
        if replication_device:
            self.replication_device = [replication_device]
        for key, value in kwargs.items():
            if key == 'san_login':
                self.san_login = value
            elif key == 'san_password':
                self.san_password = value
            elif key == 'san_ip':
                self.san_ip = value
            elif key == 'san_api_port':
                self.san_api_port = value
            elif key == 'san_rest_port':
                self.san_rest_port = value
            elif key == 'vmax_srp':
                self.vmax_srp = value
            elif key == 'vmax_service_level':
                self.vmax_service_level = value
            elif key == 'vmax_workload':
                self.vmax_workload = value
            elif key == 'vmax_port_groups':
                self.vmax_port_groups = value
            elif key == 'vmax_array':
                self.vmax_array = value
            elif key == 'use_chap_auth':
                self.use_chap_auth = value
            elif key == 'chap_username':
                self.chap_username = value
            elif key == 'chap_password':
                self.chap_password = value
            elif key == 'driver_ssl_cert_verify':
                self.driver_ssl_cert_verify = value
            elif key == 'driver_ssl_cert_path':
                self.driver_ssl_cert_path = value

    def safe_get(self, key):
        try:
            return getattr(self, key)
        except Exception:
            return None

    def append_config_values(self, values):
        pass


@ddt
class VMAXUtilsTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        super(VMAXUtilsTest, self).setUp()
        configuration = FakeConfiguration(
            None, 'UtilsTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = iscsi.VMAXISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.utils = self.common.utils

    def test_get_volumetype_extra_specs(self):
        with mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                               return_value={'specs'}) as type_mock:
            # path 1: volume_type_id not passed in
            self.data.test_volume.volume_type_id = (
                self.data.test_volume_type.id)
            self.utils.get_volumetype_extra_specs(self.data.test_volume)
            volume_types.get_volume_type_extra_specs.assert_called_once_with(
                self.data.test_volume_type.id)
            type_mock.reset_mock()
            # path 2: volume_type_id passed in
            self.utils.get_volumetype_extra_specs(self.data.test_volume, '123')
            volume_types.get_volume_type_extra_specs.assert_called_once_with(
                '123')
            type_mock.reset_mock()
            # path 3: no type_id
            self.utils.get_volumetype_extra_specs(self.data.test_clone_volume)
            (volume_types.get_volume_type_extra_specs.
             assert_not_called())

    def test_get_volumetype_extra_specs_exception(self):
        extra_specs = self.utils.get_volumetype_extra_specs(
            {'name': 'no_type_id'})
        self.assertEqual({}, extra_specs)

    def test_get_host_short_name(self):
        host_under_16_chars = 'host_13_chars'
        host1 = self.utils.get_host_short_name(
            host_under_16_chars)
        self.assertEqual(host_under_16_chars, host1)

        host_over_16_chars = (
            'host_over_16_chars_host_over_16_chars_host_over_16_chars')
        # Check that the same md5 value is retrieved from multiple calls
        host2 = self.utils.get_host_short_name(
            host_over_16_chars)
        host3 = self.utils.get_host_short_name(
            host_over_16_chars)
        self.assertEqual(host2, host3)
        host_with_period = 'hostname.with.many.parts'
        ref_host_name = self.utils.generate_unique_trunc_host('hostname')
        host4 = self.utils.get_host_short_name(host_with_period)
        self.assertEqual(ref_host_name, host4)

    def test_get_volume_element_name(self):
        volume_id = 'ea95aa39-080b-4f11-9856-a03acf9112ad'
        volume_element_name = self.utils.get_volume_element_name(volume_id)
        expect_vol_element_name = ('OS-' + volume_id)
        self.assertEqual(expect_vol_element_name, volume_element_name)

    def test_truncate_string(self):
        # string is less than max number
        str_to_truncate = 'string'
        response = self.utils.truncate_string(str_to_truncate, 10)
        self.assertEqual(str_to_truncate, response)

    def test_get_default_oversubscription_ratio(self):
        default_ratio = 20.0
        max_over_sub_ratio1 = 30.0
        returned_max = self.utils.get_default_oversubscription_ratio(
            max_over_sub_ratio1)
        self.assertEqual(max_over_sub_ratio1, returned_max)
        max_over_sub_ratio2 = 0.5
        returned_max = self.utils.get_default_oversubscription_ratio(
            max_over_sub_ratio2)
        self.assertEqual(default_ratio, returned_max)

    def test_get_default_storage_group_name_slo_workload(self):
        srp_name = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload)
        self.assertEqual(self.data.defaultstoragegroup_name, sg_name)

    def test_get_default_storage_group_name_no_slo(self):
        srp_name = self.data.srp
        slo = None
        workload = None
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload)
        self.assertEqual(self.data.default_sg_no_slo, sg_name)

    def test_get_default_storage_group_name_compr_disabled(self):
        srp_name = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        sg_name = self.utils.get_default_storage_group_name(
            srp_name, slo, workload, True)
        self.assertEqual(self.data.default_sg_compr_disabled, sg_name)

    def test_get_time_delta(self):
        start_time = 1487781721.09
        end_time = 1487781758.16
        delta = end_time - start_time
        ref_delta = six.text_type(datetime.timedelta(seconds=int(delta)))
        time_delta = self.utils.get_time_delta(start_time, end_time)
        self.assertEqual(ref_delta, time_delta)

    def test_get_short_protocol_type(self):
        # iscsi
        short_i_protocol = self.utils.get_short_protocol_type('iscsi')
        self.assertEqual('I', short_i_protocol)
        # fc
        short_f_protocol = self.utils.get_short_protocol_type('FC')
        self.assertEqual('F', short_f_protocol)
        # else
        other_protocol = self.utils.get_short_protocol_type('OTHER')
        self.assertEqual('OTHER', other_protocol)

    def test_get_temp_snap_name(self):
        source_device_id = self.data.device_id
        ref_name = "temp-00001-snapshot_for_clone"
        snap_name = self.utils.get_temp_snap_name(source_device_id)
        self.assertEqual(ref_name, snap_name)

    def test_get_array_and_device_id(self):
        volume = deepcopy(self.data.test_volume)
        external_ref = {u'source-name': u'00002'}
        array, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        self.assertEqual(self.data.array, array)
        self.assertEqual('00002', device_id)

    def test_get_array_and_device_id_exception(self):
        volume = deepcopy(self.data.test_volume)
        external_ref = {u'source-name': None}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    @data({u'source-name': u'000001'}, {u'source-name': u'00028A'})
    def test_get_array_and_device_id_invalid_long_id(self, external_ref):
        volume = deepcopy(self.data.test_volume)
        # Test for device id more than 5 digits
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    @data({u'source-name': u'01'}, {u'source-name': u'028A'},
          {u'source-name': u'0001'})
    def test_get_array_and_device_id_invalid_short_id(self, external_ref):
        volume = deepcopy(self.data.test_volume)
        # Test for device id less than 5 digits
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_array_and_device_id,
                          volume, external_ref)

    def test_get_pg_short_name(self):
        pg_under_12_chars = 'pg_11_chars'
        pg1 = self.utils.get_pg_short_name(pg_under_12_chars)
        self.assertEqual(pg_under_12_chars, pg1)

        pg_over_12_chars = 'portgroup_over_12_characters'
        # Check that the same md5 value is retrieved from multiple calls
        pg2 = self.utils.get_pg_short_name(pg_over_12_chars)
        pg3 = self.utils.get_pg_short_name(pg_over_12_chars)
        self.assertEqual(pg2, pg3)

    def test_is_compression_disabled_true(self):
        extra_specs = self.data.extra_specs_disable_compression
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        self.assertTrue(do_disable_compression)

    def test_is_compression_disabled_false(self):
        # Path 1: no compression extra spec set
        extra_specs = self.data.extra_specs
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        self.assertFalse(do_disable_compression)
        # Path 2: compression extra spec set to false
        extra_specs2 = deepcopy(extra_specs)
        extra_specs2.update({utils.DISABLECOMPRESSION: 'false'})
        do_disable_compression2 = self.utils.is_compression_disabled(
            extra_specs)
        self.assertFalse(do_disable_compression2)

    def test_change_compression_type_true(self):
        source_compr_disabled_true = 'true'
        new_type_compr_disabled = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'no'}}
        ans = self.utils.change_compression_type(
            source_compr_disabled_true, new_type_compr_disabled)
        self.assertTrue(ans)

    def test_change_compression_type_false(self):
        source_compr_disabled_true = True
        new_type_compr_disabled = {
            'extra_specs': {utils.DISABLECOMPRESSION: 'true'}}
        ans = self.utils.change_compression_type(
            source_compr_disabled_true, new_type_compr_disabled)
        self.assertFalse(ans)

    def test_is_replication_enabled(self):
        is_re = self.utils.is_replication_enabled(
            self.data.vol_type_extra_specs_rep_enabled)
        self.assertTrue(is_re)
        is_re2 = self.utils.is_replication_enabled(self.data.extra_specs)
        self.assertFalse(is_re2)

    def test_get_replication_config(self):
        # Success, allow_extend false
        rep_device_list1 = [{'target_device_id': self.data.remote_array,
                             'remote_pool': self.data.srp,
                             'remote_port_group': self.data.port_group_name_f,
                             'rdf_group_label': self.data.rdf_group_name}]
        rep_config1 = self.utils.get_replication_config(rep_device_list1)
        self.assertEqual(self.data.remote_array, rep_config1['array'])
        # Success, allow_extend true
        rep_device_list2 = rep_device_list1
        rep_device_list2[0]['allow_extend'] = 'true'
        rep_config2 = self.utils.get_replication_config(rep_device_list2)
        self.assertTrue(rep_config2['allow_extend'])
        # No rep_device_list
        rep_device_list3 = []
        rep_config3 = self.utils.get_replication_config(rep_device_list3)
        self.assertIsNone(rep_config3)
        # Exception
        rep_device_list4 = [{'target_device_id': self.data.remote_array,
                             'remote_pool': self.data.srp}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.utils.get_replication_config, rep_device_list4)
        # Success, mode is async
        rep_device_list5 = rep_device_list2
        rep_device_list5[0]['mode'] = 'async'
        rep_config5 = self.utils.get_replication_config(rep_device_list5)
        self.assertEqual(utils.REP_ASYNC, rep_config5['mode'])
        # Success, mode is metro - no other options set
        rep_device_list6 = rep_device_list5
        rep_device_list6[0]['mode'] = 'metro'
        rep_config6 = self.utils.get_replication_config(rep_device_list6)
        self.assertFalse(rep_config6['metro_bias'])
        self.assertFalse(rep_config6['allow_delete_metro'])
        # Success, mode is metro - metro options true
        rep_device_list7 = rep_device_list6
        rep_device_list6[0].update(
            {'allow_delete_metro': 'true', 'metro_use_bias': 'true'})
        rep_config7 = self.utils.get_replication_config(rep_device_list7)
        self.assertTrue(rep_config7['metro_bias'])
        self.assertTrue(rep_config7['allow_delete_metro'])

    def test_is_volume_failed_over(self):
        vol = deepcopy(self.data.test_volume)
        vol.replication_status = fields.ReplicationStatus.FAILED_OVER
        is_fo1 = self.utils.is_volume_failed_over(vol)
        self.assertTrue(is_fo1)
        is_fo2 = self.utils.is_volume_failed_over(self.data.test_volume)
        self.assertFalse(is_fo2)
        is_fo3 = self.utils.is_volume_failed_over(None)
        self.assertFalse(is_fo3)

    def test_add_legacy_pools(self):
        pools = [{'pool_name': "Diamond+None+SRP_1+000197800111"},
                 {'pool_name': "Diamond+OLTP+SRP_1+000197800111"}]
        new_pools = self.utils.add_legacy_pools(pools)
        ref_pools = [{'pool_name': "Diamond+None+SRP_1+000197800111"},
                     {'pool_name': "Diamond+OLTP+SRP_1+000197800111"},
                     {'pool_name': "Diamond+SRP_1+000197800111"}]
        self.assertEqual(ref_pools, new_pools)

    def test_update_volume_group_name(self):
        group = self.data.test_group_1
        ref_group_name = self.data.test_vol_grp_name
        vol_grp_name = self.utils.update_volume_group_name(group)
        self.assertEqual(ref_group_name, vol_grp_name)

    def test_update_volume_group_name_id_only(self):
        group = self.data.test_group_without_name
        ref_group_name = self.data.test_vol_grp_name_id_only
        vol_grp_name = self.utils.update_volume_group_name(group)
        self.assertEqual(ref_group_name, vol_grp_name)

    def test_get_volume_group_utils(self):
        array, intervals_retries = self.utils.get_volume_group_utils(
            self.data.test_group_1, interval=1, retries=1)
        ref_array = self.data.array
        self.assertEqual(ref_array, array)

    def test_update_volume_model_updates(self):
        volume_model_updates = [{'id': '1', 'status': 'available'}]
        volumes = [self.data.test_volume]
        ref_val = {'id': self.data.test_volume.id,
                   'status': 'error_deleting'}
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc', status='error_deleting')
        self.assertEqual(ref_val, ret_val[1])

    def test_update_volume_model_updates_empty_update_list(self):
        volume_model_updates = []
        volumes = [self.data.test_volume]
        ref_val = [{'id': self.data.test_volume.id,
                   'status': 'available'}]
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc')
        self.assertEqual(ref_val, ret_val)

    def test_update_volume_model_updates_empty_vol_list(self):
        volume_model_updates = []
        volumes = []
        ref_val = []
        ret_val = self.utils.update_volume_model_updates(
            volume_model_updates, volumes, 'abc')
        self.assertEqual(ref_val, ret_val)

    def test_check_replication_matched(self):
        # Check 1: Volume is not part of a group
        self.utils.check_replication_matched(
            self.data.test_volume, self.data.extra_specs)
        group_volume = deepcopy(self.data.test_volume)
        group_volume.group = self.data.test_group
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            # Check 2: Both volume and group have the same rep status
            self.utils.check_replication_matched(
                group_volume, self.data.extra_specs)
            # Check 3: Volume and group have different rep status
            with mock.patch.object(self.utils, 'is_replication_enabled',
                                   return_value=True):
                self.assertRaises(exception.InvalidInput,
                                  self.utils.check_replication_matched,
                                  group_volume, self.data.extra_specs)

    def test_check_rep_status_enabled(self):
        # Check 1: not replication enabled
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.utils.check_rep_status_enabled(self.data.test_group)
        # Check 2: replication enabled, status enabled
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            self.utils.check_rep_status_enabled(self.data.test_rep_group)
        # Check 3: replication enabled, status disabled
            self.assertRaises(exception.InvalidInput,
                              self.utils.check_rep_status_enabled,
                              self.data.test_group)

    def test_get_replication_prefix(self):
        async_prefix = self.utils.get_replication_prefix(utils.REP_ASYNC)
        self.assertEqual('-RA', async_prefix)
        sync_prefix = self.utils.get_replication_prefix(utils.REP_SYNC)
        self.assertEqual('-RE', sync_prefix)
        metro_prefix = self.utils.get_replication_prefix(utils.REP_METRO)
        self.assertEqual('-RM', metro_prefix)

    def test_get_async_rdf_managed_grp_name(self):
        rep_config = {'rdf_group_label': self.data.rdf_group_name,
                      'mode': utils.REP_ASYNC}
        grp_name = self.utils.get_async_rdf_managed_grp_name(rep_config)
        self.assertEqual(self.data.rdf_managed_async_grp, grp_name)

    def test_is_metro_device(self):
        rep_config = {'mode': utils.REP_METRO}
        is_metro = self.utils.is_metro_device(
            rep_config, self.data.rep_extra_specs)
        self.assertTrue(is_metro)
        rep_config2 = {'mode': utils.REP_ASYNC}
        is_metro2 = self.utils.is_metro_device(
            rep_config2, self.data.rep_extra_specs)
        self.assertFalse(is_metro2)

    def test_does_vol_need_rdf_management_group(self):
        self.assertFalse(self.utils.does_vol_need_rdf_management_group(
            self.data.rep_extra_specs))
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        self.assertTrue(self.utils.does_vol_need_rdf_management_group(
            extra_specs))

    def test_modify_snapshot_prefix_manage(self):
        snap_name = self.data.snapshot_id
        expected_snap_name = self.data.managed_snap_id

        updated_name = self.utils.modify_snapshot_prefix(
            snap_name, manage=True)

        self.assertEqual(expected_snap_name, updated_name)

    def test_modify_snapshot_prefix_unmanage(self):
        snap_name = self.data.managed_snap_id
        expected_snap_name = self.data.snapshot_id

        updated_name = self.utils.modify_snapshot_prefix(
            snap_name, unmanage=True)

        self.assertEqual(expected_snap_name, updated_name)

    def test_change_replication(self):
        new_type = {'extra_specs': self.data.extra_specs_rep_enabled}
        self.assertFalse(self.utils.change_replication(True, new_type))
        self.assertTrue(self.utils.change_replication(False, new_type))

    def test_get_child_sg_name(self):
        host_name = 'HostX'
        # Slo and rep enabled
        extra_specs1 = self.data.extra_specs_rep_enabled
        extra_specs1[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs1))
        re_name = self.data.storagegroup_name_f + '-RE'
        self.assertEqual(re_name, child_sg_name)
        # Disable compression
        extra_specs2 = self.data.extra_specs_disable_compression
        extra_specs2[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs2))
        cd_name = self.data.storagegroup_name_f + '-CD'
        self.assertEqual(cd_name, child_sg_name)
        # No slo
        extra_specs3 = deepcopy(self.data.extra_specs)
        extra_specs3[utils.SLO] = None
        extra_specs3[utils.PORTGROUPNAME] = self.data.port_group_name_f
        child_sg_name, do_disable_compression, rep_enabled, pg_name = (
            self.utils.get_child_sg_name(host_name, extra_specs3))
        self.assertEqual(self.data.no_slo_sg_name, child_sg_name)

    def test_change_multiattach(self):
        extra_specs_ma_true = {'multiattach': '<is> True'}
        extra_specs_ma_false = {'multiattach': '<is> False'}
        self.assertTrue(self.utils.change_multiattach(
            extra_specs_ma_true, extra_specs_ma_false))
        self.assertFalse(self.utils.change_multiattach(
            extra_specs_ma_true, extra_specs_ma_true))
        self.assertFalse(self.utils.change_multiattach(
            extra_specs_ma_false, extra_specs_ma_false))

    def test_is_volume_manageable(self):
        for volume in self.data.priv_vol_func_response_multi:
            self.assertTrue(
                self.utils.is_volume_manageable(volume))
        for volume in self.data.priv_vol_func_response_multi_invalid:
            self.assertFalse(
                self.utils.is_volume_manageable(volume))

    def test_is_snapshot_manageable(self):
        for volume in self.data.priv_vol_func_response_multi:
            self.assertTrue(
                self.utils.is_snapshot_manageable(volume))
        for volume in self.data.priv_vol_func_response_multi_invalid:
            self.assertFalse(
                self.utils.is_snapshot_manageable(volume))


class VMAXRestTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXRestTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = FakeConfiguration(
            None, 'RestTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = fc.VMAXFCDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.rest = self.common.rest
        self.utils = self.common.utils

    def test_rest_request_exception(self):
        sc, msg = self.rest.request('/fake_url', 'TIMEOUT')
        self.assertIsNone(sc)
        self.assertIsNone(msg)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.request, '', 'EXCEPTION')

    def test_wait_for_job_complete(self):
        rc, job, status, task = self.rest.wait_for_job_complete(
            {'status': 'created', 'jobId': '12345'}, self.data.extra_specs)
        self.assertEqual(0, rc)

    def test_wait_for_job_complete_failed(self):
        with mock.patch.object(self.rest, '_is_job_finished',
                               side_effect=exception.BadHTTPResponseStatus):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.wait_for_job_complete,
                              self.data.job_list[0], self.data.extra_specs)

    def test_is_job_finished_false(self):
        job_id = "55555"
        complete, response, rc, status, task = self.rest._is_job_finished(
            job_id)
        self.assertFalse(complete)

    def test_is_job_finished_failed(self):
        job_id = "55555"
        complete, response, rc, status, task = self.rest._is_job_finished(
            job_id)
        self.assertFalse(complete)
        with mock.patch.object(self.rest, 'request',
                               return_value=(200, {'status': 'FAILED'})):
            complete, response, rc, status, task = (
                self.rest._is_job_finished(job_id))
            self.assertTrue(complete)
            self.assertEqual(-1, rc)

    def test_check_status_code_success(self):
        status_code = 200
        self.rest.check_status_code_success(
            'test success', status_code, "")

    def test_check_status_code_not_success(self):
        status_code = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.check_status_code_success,
                          'test exception', status_code, "")

    def test_wait_for_job_success(self):
        operation = 'test'
        status_code = 202
        job = self.data.job_list[0]
        extra_specs = self.data.extra_specs
        self.rest.wait_for_job(
            operation, status_code, job, extra_specs)

    def test_wait_for_job_failed(self):
        operation = 'test'
        status_code = 202
        job = self.data.job_list[2]
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'wait_for_job_complete',
                               return_value=(-1, '', '', '')):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.wait_for_job,
                              operation, status_code, job, extra_specs)

    def test_get_resource_present(self):
        array = self.data.array
        category = 'sloprovisioning'
        resource_type = 'storagegroup'
        resource = self.rest.get_resource(array, category, resource_type)
        self.assertEqual(self.data.sg_list, resource)

    def test_get_resource_not_present(self):
        array = self.data.array
        category = 'sloprovisioning'
        resource_type = self.data.failed_resource
        resource = self.rest.get_resource(array, category, resource_type)
        self.assertIsNone(resource)

    def test_create_resource_success(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': 'someValue'}
        status_code, message = self.rest.create_resource(
            array, category, resource_type, payload)
        self.assertEqual(self.data.job_list[0], message)

    def test_create_resource_failed(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': self.data.failed_resource}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.create_resource, array, category,
            resource_type, payload)

    def test_modify_resource(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': 'someValue'}
        status_code, message = self.rest.modify_resource(
            array, category, resource_type, payload)
        self.assertEqual(self.data.job_list[0], message)

    def test_modify_resource_failed(self):
        array = self.data.array
        category = ''
        resource_type = ''
        payload = {'someKey': self.data.failed_resource}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.modify_resource, array, category,
            resource_type, payload)

    def test_delete_resource(self):
        operation = 'delete res resource'
        status_code = 204
        message = None
        array = self.data.array
        category = 'cat'
        resource_type = 'res'
        resource_name = 'name'
        with mock.patch.object(self.rest, 'check_status_code_success'):
            self.rest.delete_resource(
                array, category, resource_type, resource_name)
            self.rest.check_status_code_success.assert_called_with(
                operation, status_code, message)

    def test_delete_resource_failed(self):
        array = self.data.array
        category = self.data.failed_resource
        resource_type = self.data.failed_resource
        resource_name = self.data.failed_resource
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.modify_resource, array, category,
            resource_type, resource_name)

    def test_get_array_serial(self):
        ref_details = self.data.symmetrix[0]
        array_details = self.rest.get_array_serial(self.data.array)
        self.assertEqual(ref_details, array_details)

    def test_get_array_serial_failed(self):
        array_details = self.rest.get_array_serial(self.data.failed_resource)
        self.assertIsNone(array_details)

    def test_get_uni_version(self):
        version, major_version = self.rest.get_uni_version()
        self.assertEqual('90', major_version)
        with mock.patch.object(self.rest, '_get_request', return_value=None):
            version, major_version = self.rest.get_uni_version()
            self.assertIsNone(major_version)

    def test_get_srp_by_name(self):
        ref_details = self.data.srp_details
        srp_details = self.rest.get_srp_by_name(
            self.data.array, self.data.srp)
        self.assertEqual(ref_details, srp_details)

    def test_get_slo_list_powermax(self):
        ref_settings = self.data.powermax_slo_details['sloId']
        slo_settings = self.rest.get_slo_list(self.data.array)
        self.assertEqual(ref_settings, slo_settings)

    def test_get_slo_list_vmax(self):
        ref_settings = ['Diamond']
        with mock.patch.object(self.rest, 'get_resource',
                               return_value=self.data.vmax_slo_details):
            slo_settings = self.rest.get_slo_list(self.data.array)
            self.assertEqual(ref_settings, slo_settings)

    def test_get_workload_settings(self):
        ref_settings = self.data.workloadtype['workloadId']
        wl_settings = self.rest.get_workload_settings(
            self.data.array)
        self.assertEqual(ref_settings, wl_settings)

    def test_get_workload_settings_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            wl_settings = self.rest.get_workload_settings(
                self.data.array_herc)
            self.assertEqual(['None'], wl_settings)

    def test_get_workload_settings_failed(self):
        wl_settings = self.rest.get_workload_settings(
            self.data.failed_resource)
        self.assertEqual([], wl_settings)

    def test_is_compression_capable_true(self):
        compr_capable = self.rest.is_compression_capable('000197800128')
        self.assertTrue(compr_capable)

    def test_is_compression_capable_false(self):
        compr_capable = self.rest.is_compression_capable(self.data.array)
        self.assertFalse(compr_capable)
        with mock.patch.object(self.rest, 'request', return_value=(200, {})):
            compr_capable = self.rest.is_compression_capable(self.data.array)
            self.assertFalse(compr_capable)

    def test_get_storage_group(self):
        ref_details = self.data.sg_details[0]
        sg_details = self.rest.get_storage_group(
            self.data.array, self.data.defaultstoragegroup_name)
        self.assertEqual(ref_details, sg_details)

    def test_get_storage_group_list(self):
        sg_list = self.rest.get_storage_group_list(self.data.array)
        self.assertEqual(self.data.sg_list, sg_list)

    def test_create_storage_group(self):
        with mock.patch.object(self.rest, 'create_resource'):
            payload = {'someKey': 'someValue'}
            self.rest._create_storagegroup(self.data.array, payload)
            self.rest.create_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'storagegroup', payload)

    def test_create_storage_group_success(self):
        sg_name = self.rest.create_storage_group(
            self.data.array, self.data.storagegroup_name_f, self.data.srp,
            self.data.slo, self.data.workload, self.data.extra_specs)
        self.assertEqual(self.data.storagegroup_name_f, sg_name)

    def test_create_storage_group_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            with mock.patch.object(self.rest, '_create_storagegroup',
                                   return_value=(200, self.data.job_list[0])):
                self.rest.create_storage_group(
                    self.data.array, self.data.storagegroup_name_f,
                    self.data.srp, self.data.slo, self.data.workload,
                    self.data.extra_specs)
                payload = {"srpId": self.data.srp,
                           "storageGroupId": self.data.storagegroup_name_f,
                           "emulation": "FBA",
                           "sloBasedStorageGroupParam": [
                               {"num_of_vols": 0,
                                "sloId": self.data.slo,
                                "workloadSelection": 'NONE',
                                "volumeAttribute": {
                                    "volume_size": "0",
                                    "capacityUnit": "GB"}}]}
                self.rest._create_storagegroup.assert_called_once_with(
                    self.data.array, payload)

    def test_create_storage_group_failed(self):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.create_storage_group, self.data.array,
            self.data.failed_resource, self.data.srp, self.data.slo,
            self.data.workload, self.data.extra_specs)

    def test_create_storage_group_no_slo(self):
        sg_name = self.rest.create_storage_group(
            self.data.array, self.data.default_sg_no_slo, self.data.srp,
            None, None, self.data.extra_specs)
        self.assertEqual(self.data.default_sg_no_slo, sg_name)

    def test_create_storage_group_compression_disabled(self):
        with mock.patch.object(self.rest, '_create_storagegroup',
                               return_value=(200, self.data.job_list[0])):
            self.rest.create_storage_group(
                self.data.array, self.data.default_sg_compr_disabled,
                self.data.srp, self.data.slo, self.data.workload,
                self.data.extra_specs, True)
            payload = {"srpId": self.data.srp,
                       "storageGroupId": self.data.default_sg_compr_disabled,
                       "emulation": "FBA",
                       "sloBasedStorageGroupParam": [
                           {"num_of_vols": 0,
                            "sloId": self.data.slo,
                            "workloadSelection": self.data.workload,
                            "volumeAttribute": {
                                "volume_size": "0",
                                "capacityUnit": "GB"},
                            "noCompression": "true"}]}
            self.rest._create_storagegroup.assert_called_once_with(
                self.data.array, payload)

    def test_modify_storage_group(self):
        array = self.data.array
        storagegroup = self.data.defaultstoragegroup_name
        payload = {'someKey': 'someValue'}
        version = self.data.u4v_version
        with mock.patch.object(self.rest, 'modify_resource'):
            self.rest.modify_storage_group(array, storagegroup, payload)
            self.rest.modify_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'storagegroup',
                payload, version, resource_name=storagegroup)

    def test_create_volume_from_sg_success(self):
        volume_name = self.data.volume_details[0]['volume_identifier']
        ref_dict = self.data.provider_location
        volume_dict = self.rest.create_volume_from_sg(
            self.data.array, volume_name, self.data.defaultstoragegroup_name,
            self.data.test_volume.size, self.data.extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    def test_create_volume_from_sg_failed(self):
        volume_name = self.data.volume_details[0]['volume_identifier']
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.create_volume_from_sg, self.data.array,
            volume_name, self.data.failed_resource,
            self.data.test_volume.size, self.data.extra_specs)

    def test_create_volume_from_sg_cannot_retrieve_device_id(self):
        with mock.patch.object(self.rest, 'find_volume_device_id',
                               return_value=None):
            volume_name = self.data.volume_details[0]['volume_identifier']
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.rest.create_volume_from_sg, self.data.array,
                volume_name, self.data.failed_resource,
                self.data.test_volume.size, self.data.extra_specs)

    def test_add_vol_to_sg_success(self):
        operation = 'Add volume to sg'
        status_code = 202
        message = self.data.job_list[0]
        with mock.patch.object(self.rest, 'wait_for_job'):
            device_id = self.data.device_id
            self.rest.add_vol_to_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                self.data.extra_specs)
            self.rest.wait_for_job.assert_called_with(
                operation, status_code, message, self.data.extra_specs)

    def test_add_vol_to_sg_failed(self):
        device_id = [self.data.device_id]
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.add_vol_to_sg, self.data.array,
            self.data.failed_resource, device_id,
            self.data.extra_specs)

    def test_remove_vol_from_sg_success(self):
        operation = 'Remove vol from sg'
        status_code = 202
        message = self.data.job_list[0]
        with mock.patch.object(self.rest, 'wait_for_job'):
            device_id = self.data.device_id
            self.rest.remove_vol_from_sg(
                self.data.array, self.data.storagegroup_name_f, device_id,
                self.data.extra_specs)
            self.rest.wait_for_job.assert_called_with(
                operation, status_code, message, self.data.extra_specs)

    @mock.patch.object(time, 'sleep')
    def test_remove_vol_from_sg_failed(self, mock_sleep):
        device_id = [self.data.volume_details[0]['volumeId']]
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest.remove_vol_from_sg, self.data.array,
            self.data.failed_resource, device_id,
            self.data.extra_specs)

    def test_get_vmax_default_storage_group(self):
        ref_storage_group = self.data.sg_details[0]
        ref_sg_name = self.data.defaultstoragegroup_name
        storagegroup, storagegroup_name = (
            self.rest.get_vmax_default_storage_group(
                self.data.array, self.data.srp,
                self.data.slo, self.data.workload))
        self.assertEqual(ref_sg_name, storagegroup_name)
        self.assertEqual(ref_storage_group, storagegroup)

    def test_get_vmax_default_storage_group_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            __, storagegroup_name = self.rest.get_vmax_default_storage_group(
                self.data.array, self.data.srp,
                self.data.slo, self.data.workload)
            self.assertEqual('OS-SRP_1-Diamond-NONE-SG', storagegroup_name)

    def test_delete_storage_group(self):
        operation = 'delete storagegroup resource'
        status_code = 204
        message = None
        with mock.patch.object(self.rest, 'check_status_code_success'):
            self.rest.delete_storage_group(
                self.data.array, self.data.storagegroup_name_f)
            self.rest.check_status_code_success.assert_called_with(
                operation, status_code, message)

    def test_is_child_sg_in_parent_sg(self):
        is_child1 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f)
        is_child2 = self.rest.is_child_sg_in_parent_sg(
            self.data.array, self.data.defaultstoragegroup_name,
            self.data.parent_sg_f)
        self.assertTrue(is_child1)
        self.assertFalse(is_child2)

    def test_add_child_sg_to_parent_sg(self):
        payload = {"editStorageGroupActionParam": {
            "addExistingStorageGroupParam": {
                "storageGroupId": [self.data.storagegroup_name_f]}}}
        with mock.patch.object(self.rest, 'modify_storage_group',
                               return_value=(202, self.data.job_list[0])):
            self.rest.add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_f,
                self.data.parent_sg_f, self.data.extra_specs)
            self.rest.modify_storage_group.assert_called_once_with(
                self.data.array, self.data.parent_sg_f, payload, version='83')

    def test_remove_child_sg_from_parent_sg(self):
        payload = {"editStorageGroupActionParam": {
            "removeStorageGroupParam": {
                "storageGroupId": [self.data.storagegroup_name_f],
                "force": 'true'}}}
        with mock.patch.object(self.rest, 'modify_storage_group',
                               return_value=(202, self.data.job_list[0])):
            self.rest.remove_child_sg_from_parent_sg(
                self.data.array, self.data.storagegroup_name_f,
                self.data.parent_sg_f, self.data.extra_specs)
            self.rest.modify_storage_group.assert_called_once_with(
                self.data.array, self.data.parent_sg_f, payload)

    def test_get_volume_list(self):
        ref_volumes = [self.data.device_id, self.data.device_id2]
        volumes = self.rest.get_volume_list(self.data.array, {})
        self.assertEqual(ref_volumes, volumes)

    def test_get_volume(self):
        ref_volumes = self.data.volume_details[0]
        device_id = self.data.device_id
        volumes = self.rest.get_volume(self.data.array, device_id)
        self.assertEqual(ref_volumes, volumes)

    def test_get_private_volume(self):
        device_id = self.data.device_id
        ref_volume = self.data.private_vol_details['resultList']['result'][0]
        volume = self.rest._get_private_volume(self.data.array, device_id)
        self.assertEqual(ref_volume, volume)

    def test_get_private_volume_exception(self):
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={}):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest._get_private_volume,
                              self.data.array, device_id)

    def test_modify_volume_success(self):
        array = self.data.array
        device_id = self.data.device_id
        payload = {'someKey': 'someValue'}
        with mock.patch.object(self.rest, 'modify_resource'):
            self.rest._modify_volume(array, device_id, payload)
            self.rest.modify_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'volume',
                payload, resource_name=device_id)

    def test_modify_volume_failed(self):
        payload = {'someKey': self.data.failed_resource}
        device_id = self.data.device_id
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest._modify_volume, self.data.array,
            device_id, payload)

    def test_extend_volume(self):
        device_id = self.data.device_id
        new_size = '3'
        extend_vol_payload = {"executionOption": "ASYNCHRONOUS",
                              "editVolumeActionParam": {
                                  "expandVolumeParam": {
                                      "volumeAttribute": {
                                          "volume_size": new_size,
                                          "capacityUnit": "GB"}}}}
        with mock.patch.object(self.rest, '_modify_volume',
                               return_value=(202, self.data.job_list[0])):
            self.rest.extend_volume(self.data.array, device_id, new_size,
                                    self.data.extra_specs)
            self.rest._modify_volume.assert_called_once_with(
                self.data.array, device_id, extend_vol_payload)

    def test_delete_volume(self):
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'delete_resource'),\
            mock.patch.object(
                self.rest, '_modify_volume', side_effect=[
                    None, None, None, exception.VolumeBackendAPIException]):
                for x in range(0, 2):
                    self.rest.delete_volume(self.data.array, device_id)
                mod_call_count = self.rest._modify_volume.call_count
                self.assertEqual(4, mod_call_count)
                self.rest.delete_resource.assert_called_once_with(
                    self.data.array, 'sloprovisioning', 'volume', device_id)

    def test_rename_volume(self):
        device_id = self.data.device_id
        payload = {"editVolumeActionParam": {
            "modifyVolumeIdentifierParam": {
                "volumeIdentifier": {
                    "identifier_name": 'new_name',
                    "volumeIdentifierChoice": "identifier_name"}}}}
        payload2 = {"editVolumeActionParam": {"modifyVolumeIdentifierParam": {
            "volumeIdentifier": {"volumeIdentifierChoice": "none"}}}}
        with mock.patch.object(self.rest, '_modify_volume') as mock_mod:
            self.rest.rename_volume(self.data.array, device_id, 'new_name')
            mock_mod.assert_called_once_with(
                self.data.array, device_id, payload)
            mock_mod.reset_mock()
            self.rest.rename_volume(self.data.array, device_id, None)
            self.rest._modify_volume.assert_called_once_with(
                self.data.array, device_id, payload2)

    def test_check_volume_device_id(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        found_dev_id = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id, element_name)
        self.assertEqual(self.data.device_id, found_dev_id)
        found_dev_id2 = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id3, element_name)
        self.assertIsNone(found_dev_id2)

    def test_check_volume_device_id_host_migration_case(self):
        element_name = self.utils.get_volume_element_name(
            self.data.test_clone_volume.id)
        found_dev_id = self.rest.check_volume_device_id(
            self.data.array, self.data.device_id, element_name,
            name_id=self.data.test_clone_volume._name_id)
        self.assertEqual(self.data.device_id, found_dev_id)

    def test_find_mv_connections_for_vol(self):
        device_id = self.data.device_id
        ref_lun_id = int((self.data.maskingview[0]['maskingViewConnection']
                          [0]['host_lun_address']), 16)
        host_lun_id = self.rest.find_mv_connections_for_vol(
            self.data.array, self.data.masking_view_name_f, device_id)
        self.assertEqual(ref_lun_id, host_lun_id)

    def test_find_mv_connections_for_vol_failed(self):
        # no masking view info retrieved
        device_id = self.data.volume_details[0]['volumeId']
        host_lun_id = self.rest.find_mv_connections_for_vol(
            self.data.array, self.data.failed_resource, device_id)
        self.assertIsNone(host_lun_id)
        # no connection info received
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={'no_conn': 'no_info'}):
            host_lun_id2 = self.rest.find_mv_connections_for_vol(
                self.data.array, self.data.masking_view_name_f, device_id)
            self.assertIsNone(host_lun_id2)

    def test_get_storage_groups_from_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_list = self.data.volume_details[0]['storageGroupId']
        sg_list = self.rest.get_storage_groups_from_volume(array, device_id)
        self.assertEqual(ref_list, sg_list)

    def test_get_num_vols_in_sg(self):
        num_vol = self.rest.get_num_vols_in_sg(
            self.data.array, self.data.defaultstoragegroup_name)
        self.assertEqual(2, num_vol)

    def test_get_num_vols_in_sg_no_num(self):
        with mock.patch.object(self.rest, 'get_storage_group',
                               return_value={}):
            num_vol = self.rest.get_num_vols_in_sg(
                self.data.array, self.data.defaultstoragegroup_name)
            self.assertEqual(0, num_vol)

    def test_is_volume_in_storagegroup(self):
        # True
        array = self.data.array
        device_id = self.data.device_id
        storagegroup = self.data.defaultstoragegroup_name
        is_vol1 = self.rest.is_volume_in_storagegroup(
            array, device_id, storagegroup)
        # False
        with mock.patch.object(self.rest, 'get_storage_groups_from_volume',
                               return_value=[]):
            is_vol2 = self.rest.is_volume_in_storagegroup(
                array, device_id, storagegroup)
        self.assertTrue(is_vol1)
        self.assertFalse(is_vol2)

    def test_find_volume_device_number(self):
        array = self.data.array
        volume_name = self.data.volume_details[0]['volume_identifier']
        ref_device = self.data.device_id
        device_number = self.rest.find_volume_device_id(array, volume_name)
        self.assertEqual(ref_device, device_number)

    def test_find_volume_device_number_failed(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_volume_list',
                               return_value=[]):
            device_number = self.rest.find_volume_device_id(
                array, 'name')
            self.assertIsNone(device_number)

    def test_get_volume_success(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_volume = self.data.volume_details[0]
        volume = self.rest.get_volume(array, device_id)
        self.assertEqual(ref_volume, volume)

    def test_get_volume_failed(self):
        array = self.data.array
        device_id = self.data.failed_resource
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.get_volume,
                          array, device_id)

    def test_find_volume_identifier(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_name = self.data.volume_details[0]['volume_identifier']
        vol_name = self.rest.find_volume_identifier(array, device_id)
        self.assertEqual(ref_name, vol_name)

    def test_get_volume_size(self):
        array = self.data.array
        device_id = self.data.device_id
        ref_size = self.data.test_volume.size
        size = self.rest.get_size_of_device_on_array(array, device_id)
        self.assertEqual(ref_size, size)

    def test_get_volume_size_exception(self):
        array = self.data.array
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=None):
            size = self.rest.get_size_of_device_on_array(
                array, device_id)
            self.assertIsNone(size)

    def test_get_portgroup(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_pg = self.data.portgroup[0]
        portgroup = self.rest.get_portgroup(array, pg_name)
        self.assertEqual(ref_pg, portgroup)

    def test_get_port_ids(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_ports = ["FA-1D:4"]
        port_ids = self.rest.get_port_ids(array, pg_name)
        self.assertEqual(ref_ports, port_ids)

    def test_get_port_ids_no_portgroup(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_portgroup',
                               return_value=None):
            port_ids = self.rest.get_port_ids(array, pg_name)
            self.assertEqual([], port_ids)

    def test_get_port(self):
        array = self.data.array
        port_id = "FA-1D:4"
        ref_port = self.data.port_list[0]
        port = self.rest.get_port(array, port_id)
        self.assertEqual(ref_port, port)

    def test_get_iscsi_ip_address_and_iqn(self):
        array = self.data.array
        port_id = "SE-4E:0"
        ref_ip = [self.data.ip]
        ref_iqn = self.data.initiator
        ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
            array, port_id)
        self.assertEqual(ref_ip, ip_addresses)
        self.assertEqual(ref_iqn, iqn)

    def test_get_iscsi_ip_address_and_iqn_no_port(self):
        array = self.data.array
        port_id = "SE-4E:0"
        with mock.patch.object(self.rest, 'get_port', return_value=None):
            ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
                array, port_id)
            self.assertIsNone(ip_addresses)
            self.assertIsNone(iqn)

    def test_get_target_wwns(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        ref_wwns = [self.data.wwnn1]
        target_wwns = self.rest.get_target_wwns(array, pg_name)
        self.assertEqual(ref_wwns, target_wwns)

    def test_get_target_wwns_failed(self):
        array = self.data.array
        pg_name = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_port',
                               return_value=None):
            target_wwns = self.rest.get_target_wwns(array, pg_name)
            self.assertEqual([], target_wwns)

    def test_get_initiator_group(self):
        array = self.data.array
        ig_name = self.data.initiatorgroup_name_f
        ref_ig = self.data.inititiatorgroup[0]
        response_ig = self.rest.get_initiator_group(array, ig_name)
        self.assertEqual(ref_ig, response_ig)

    def test_get_initiator(self):
        array = self.data.array
        initiator_name = self.data.initiator
        ref_initiator = self.data.initiator_list[1]
        response_initiator = self.rest.get_initiator(array, initiator_name)
        self.assertEqual(ref_initiator, response_initiator)

    def test_get_initiator_list(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_resource',
                               return_value={'initiatorId': '1234'}):
            init_list = self.rest.get_initiator_list(array)
            self.assertIsNotNone(init_list)

    def test_get_initiator_list_none(self):
        array = self.data.array
        with mock.patch.object(self.rest, 'get_resource', return_value={}):
            init_list = self.rest.get_initiator_list(array)
            self.assertEqual([], init_list)

    def test_get_initiator_group_from_initiator(self):
        initiator = self.data.wwpn1
        ref_group = self.data.initiatorgroup_name_f
        init_group = self.rest.get_initiator_group_from_initiator(
            self.data.array, initiator)
        self.assertEqual(ref_group, init_group)

    def test_get_initiator_group_from_initiator_failed(self):
        initiator = self.data.wwpn1
        with mock.patch.object(self.rest, 'get_initiator',
                               return_value=None):
            init_group = self.rest.get_initiator_group_from_initiator(
                self.data.array, initiator)
            self.assertIsNone(init_group)
        with mock.patch.object(self.rest, 'get_initiator',
                               return_value={'name': 'no_host'}):
            init_group = self.rest.get_initiator_group_from_initiator(
                self.data.array, initiator)
            self.assertIsNone(init_group)

    def test_create_initiator_group(self):
        init_group_name = self.data.initiatorgroup_name_f
        init_list = [self.data.wwpn1]
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'create_resource',
                               return_value=(202, self.data.job_list[0])):
            payload = ({"executionOption": "ASYNCHRONOUS",
                        "hostId": init_group_name, "initiatorId": init_list})
            self.rest.create_initiator_group(
                self.data.array, init_group_name, init_list, extra_specs)
            self.rest.create_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'host', payload)

    def test_delete_initiator_group(self):
        with mock.patch.object(self.rest, 'delete_resource'):
            self.rest.delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_f)
            self.rest.delete_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'host',
                self.data.initiatorgroup_name_f)

    def test_get_masking_view(self):
        array = self.data.array
        masking_view_name = self.data.masking_view_name_f
        ref_mask_view = self.data.maskingview[0]
        masking_view = self.rest.get_masking_view(array, masking_view_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_from_storage_group(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        ref_mask_view = [self.data.masking_view_name_f]
        masking_view = self.rest.get_masking_views_from_storage_group(
            array, storagegroup_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_by_initiator_group(self):
        array = self.data.array
        initiatorgroup_name = self.data.initiatorgroup_name_f
        ref_mask_view = [self.data.masking_view_name_f]
        masking_view = self.rest.get_masking_views_by_initiator_group(
            array, initiatorgroup_name)
        self.assertEqual(ref_mask_view, masking_view)

    def test_get_masking_views_by_initiator_group_failed(self):
        array = self.data.array
        initiatorgroup_name = self.data.initiatorgroup_name_f
        with mock.patch.object(self.rest, 'get_initiator_group',
                               return_value=None):
            masking_view = self.rest.get_masking_views_by_initiator_group(
                array, initiatorgroup_name)
            self.assertEqual([], masking_view)
        with mock.patch.object(self.rest, 'get_initiator_group',
                               return_value={'name': 'no_mv'}):
            masking_view = self.rest.get_masking_views_by_initiator_group(
                array, initiatorgroup_name)
            self.assertEqual([], masking_view)

    def test_get_element_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        # storage group
        ref_sg = self.data.storagegroup_name_f
        storagegroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, storagegroup=True)
        self.assertEqual(ref_sg, storagegroup)
        # initiator group
        ref_ig = self.data.initiatorgroup_name_f
        initiatorgroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, host=True)
        self.assertEqual(ref_ig, initiatorgroup)
        # portgroup
        ref_pg = self.data.port_group_name_f
        portgroup = self.rest.get_element_from_masking_view(
            array, maskingview_name, portgroup=True)
        self.assertEqual(ref_pg, portgroup)

    def test_get_element_from_masking_view_failed(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        # no element chosen
        element = self.rest.get_element_from_masking_view(
            array, maskingview_name)
        self.assertIsNone(element)
        # cannot retrieve maskingview
        with mock.patch.object(self.rest, 'get_masking_view',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.get_element_from_masking_view,
                              array, maskingview_name)

    def test_get_common_masking_views(self):
        array = self.data.array
        initiatorgroup = self.data.initiatorgroup_name_f
        portgroup = self.data.port_group_name_f
        ref_maskingview = self.data.masking_view_name_f
        maskingview_list = self.rest.get_common_masking_views(
            array, portgroup, initiatorgroup)
        self.assertEqual(ref_maskingview, maskingview_list)

    def test_get_common_masking_views_none(self):
        array = self.data.array
        initiatorgroup = self.data.initiatorgroup_name_f
        portgroup = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'get_masking_view_list',
                               return_value=[]):
            maskingview_list = self.rest.get_common_masking_views(
                array, portgroup, initiatorgroup)
            self.assertEqual([], maskingview_list)

    def test_create_masking_view(self):
        maskingview_name = self.data.masking_view_name_f
        storagegroup_name = self.data.storagegroup_name_f
        port_group_name = self.data.port_group_name_f
        init_group_name = self.data.initiatorgroup_name_f
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'create_resource',
                               return_value=(202, self.data.job_list[0])):
            payload = ({"executionOption": "ASYNCHRONOUS",
                        "portGroupSelection": {
                            "useExistingPortGroupParam": {
                                "portGroupId": port_group_name}},
                        "maskingViewId": maskingview_name,
                        "hostOrHostGroupSelection": {
                            "useExistingHostParam": {
                                "hostId": init_group_name}},
                        "storageGroupSelection": {
                            "useExistingStorageGroupParam": {
                                "storageGroupId": storagegroup_name}}})
            self.rest.create_masking_view(
                self.data.array, maskingview_name, storagegroup_name,
                port_group_name, init_group_name, extra_specs)
            self.rest.create_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'maskingview', payload)

    def test_delete_masking_view(self):
        with mock.patch.object(self.rest, 'delete_resource'):
            self.rest.delete_masking_view(
                self.data.array, self.data.masking_view_name_f)
            self.rest.delete_resource.assert_called_once_with(
                self.data.array, 'sloprovisioning', 'maskingview',
                self.data.masking_view_name_f)

    def test_get_replication_capabilities(self):
        ref_response = self.data.capabilities['symmetrixCapability'][1]
        capabilities = self.rest.get_replication_capabilities(self.data.array)
        self.assertEqual(ref_response, capabilities)

    def test_is_clone_licenced(self):
        licence = self.rest.is_snapvx_licensed(self.data.array)
        self.assertTrue(licence)
        false_response = {'rdfCapable': True,
                          'snapVxCapable': False,
                          'symmetrixId': '000197800123'}
        with mock.patch.object(self.rest, 'get_replication_capabilities',
                               return_value=false_response):
            licence2 = self.rest.is_snapvx_licensed(self.data.array)
            self.assertFalse(licence2)

    def test_is_clone_licenced_error(self):
        with mock.patch.object(self.rest, 'get_replication_capabilities',
                               return_value=None):
            licence3 = self.rest.is_snapvx_licensed(self.data.array)
            self.assertFalse(licence3)

    def test_create_volume_snap(self):
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        payload = {"deviceNameListSource": [{"name": device_id}],
                   "bothSides": 'false', "star": 'false',
                   "force": 'false'}
        resource_type = 'snapshot/%(snap)s' % {'snap': snap_name}
        with mock.patch.object(self.rest, 'create_resource',
                               return_value=(202, self.data.job_list[0])):
            self.rest.create_volume_snap(
                self.data.array, snap_name, device_id, extra_specs)
            self.rest.create_resource.assert_called_once_with(
                self.data.array, 'replication', resource_type,
                payload, private='/private')
        ttl = 1
        payload = {"deviceNameListSource": [{"name": device_id}],
                   "bothSides": 'false', "star": 'false',
                   "force": 'false', "timeToLive": ttl,
                   "timeInHours": "true"}
        with mock.patch.object(self.rest, 'create_resource',
                               return_value=(202, self.data.job_list[0])):
            self.rest.create_volume_snap(
                self.data.array, snap_name, device_id, extra_specs, ttl)
            self.rest.create_resource.assert_called_once_with(
                self.data.array, 'replication', resource_type,
                payload, private='/private')

    def test_modify_volume_snap(self):
        array = self.data.array
        source_id = self.data.device_id
        target_id = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['linkedDevices'][0]['targetDevice'])
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        extra_specs = self.data.extra_specs
        payload = {"deviceNameListSource": [{"name": source_id}],
                   "deviceNameListTarget": [
                       {"name": target_id}],
                   "copy": 'true', "action": "",
                   "star": 'false', "force": 'false',
                   "exact": 'false', "remote": 'false',
                   "symforce": 'false', "nocopy": 'false',
                   "generation": 0}
        payload_restore = {"deviceNameListSource": [{"name": source_id}],
                           "deviceNameListTarget": [{"name": source_id}],
                           "action": "Restore",
                           "star": 'false', "force": 'false'}
        with mock.patch.object(
            self.rest, 'modify_resource', return_value=(
                202, self.data.job_list[0])) as mock_modify:
            # link
            payload["action"] = "Link"
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name, extra_specs, link=True)
            self.rest.modify_resource.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # unlink
            mock_modify.reset_mock()
            payload["action"] = "Unlink"
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name,
                extra_specs, unlink=True)
            self.rest.modify_resource.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # restore
            mock_modify.reset_mock()
            payload["action"] = "Restore"
            self.rest.modify_volume_snap(
                array, source_id, "", snap_name,
                extra_specs, unlink=False, restore=True)
            self.rest.modify_resource.assert_called_once_with(
                array, 'replication', 'snapshot', payload_restore,
                resource_name=snap_name, private='/private')
            # link or unlink, list of volumes
            mock_modify.reset_mock()
            payload["action"] = "Link"
            self.rest.modify_volume_snap(
                array, "", "", snap_name,
                extra_specs, unlink=False, link=True,
                list_volume_pairs=[(source_id, target_id)])
            self.rest.modify_resource.assert_called_once_with(
                array, 'replication', 'snapshot', payload,
                resource_name=snap_name, private='/private')
            # none selected
            mock_modify.reset_mock()
            self.rest.modify_volume_snap(
                array, source_id, target_id, snap_name,
                extra_specs)
            self.rest.modify_resource.assert_not_called()

    def test_delete_volume_snap(self):
        array = self.data.array
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        source_device_id = self.data.device_id
        payload = {"deviceNameListSource": [{"name": source_device_id}],
                   "generation": 0}
        generation = 0
        with mock.patch.object(self.rest, 'delete_resource'):
            self.rest.delete_volume_snap(
                array, snap_name, source_device_id, generation)
            self.rest.delete_resource.assert_called_once_with(
                array, 'replication', 'snapshot', snap_name,
                payload=payload, private='/private')

    def test_delete_volume_snap_restore(self):
        array = self.data.array
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        source_device_id = self.data.device_id
        payload = {"deviceNameListSource": [{"name": source_device_id}],
                   "restore": True, "generation": 0}
        with mock.patch.object(self.rest, 'delete_resource'):
            self.rest.delete_volume_snap(
                array, snap_name, source_device_id, restored=True)
            self.rest.delete_resource.assert_called_once_with(
                array, 'replication', 'snapshot', snap_name,
                payload=payload, private='/private')

    def test_get_volume_snap_info(self):
        array = self.data.array
        source_device_id = self.data.device_id
        ref_snap_info = self.data.volume_snap_vx
        snap_info = self.rest.get_volume_snap_info(array, source_device_id)
        self.assertEqual(ref_snap_info, snap_info)

    def test_get_volume_snap(self):
        array = self.data.array
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        device_id = self.data.device_id
        ref_snap = self.data.volume_snap_vx['snapshotSrcs'][0]
        snap = self.rest.get_volume_snap(array, device_id, snap_name)
        self.assertEqual(ref_snap, snap)

    def test_get_volume_snap_none(self):
        array = self.data.array
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        device_id = self.data.device_id
        with mock.patch.object(self.rest, 'get_volume_snap_info',
                               return_value=None):
            snap = self.rest.get_volume_snap(array, device_id, snap_name)
            self.assertIsNone(snap)
        with mock.patch.object(self.rest, 'get_volume_snap_info',
                               return_value={'snapshotSrcs': []}):
            snap = self.rest.get_volume_snap(array, device_id, snap_name)
            self.assertIsNone(snap)

    def test_get_snap_linked_device_dict_list(self):
        array = self.data.array
        snap_name = "temp-snapshot"
        device_id = self.data.device_id
        snap_list = [{'linked_vols': [
            {'target_device': device_id, 'state': "Copied"}],
            'snap_name': snap_name, 'generation': "0"}]
        ref_snap_list = [{'generation': '0', 'linked_vols': [
            {'state': 'Copied', 'target_device': '00001'}]}]
        with mock.patch.object(self.rest, '_find_snap_vx_source_sessions',
                               return_value=snap_list):
            snap_dict_list = self.rest._get_snap_linked_device_dict_list(
                array, device_id, snap_name)
            self.assertEqual(ref_snap_list, snap_dict_list)

    def test_get_sync_session(self):
        array = self.data.array
        source_id = self.data.device_id
        generation = 0
        target_id = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['linkedDevices'][0]['targetDevice'])
        snap_name = (self.data.volume_snap_vx
                     ['snapshotSrcs'][0]['snapshotName'])
        ref_sync = (self.data.volume_snap_vx
                    ['snapshotSrcs'][0]['linkedDevices'][0])
        sync = self.rest.get_sync_session(
            array, source_id, snap_name, target_id, generation)
        self.assertEqual(ref_sync, sync)

    def test_find_snap_vx_sessions(self):
        array = self.data.array
        source_id = self.data.device_id
        ref_sessions = [{'generation': '0',
                         'snap_name': 'temp-1',
                         'source_vol': self.data.device_id,
                         'target_vol_list':
                             [(self.data.device_id2, "Copied")]},
                        {'generation': '0',
                         'snap_name': 'temp-1',
                         'source_vol': self.data.device_id,
                         'target_vol_list':
                             [(self.data.device_id2, "Copied")]}]
        sessions = self.rest.find_snap_vx_sessions(array, source_id)
        self.assertEqual(ref_sessions, sessions)

    def test_find_snap_vx_sessions_tgt_only(self):
        array = self.data.array
        source_id = self.data.device_id
        ref_sessions = [{'generation': '0',
                         'snap_name': 'temp-1',
                         'source_vol': self.data.device_id,
                         'target_vol_list':
                             [(self.data.device_id2, "Copied")]}]
        sessions = self.rest.find_snap_vx_sessions(
            array, source_id, tgt_only=True)
        self.assertEqual(ref_sessions, sessions)

    def test_update_storagegroup_qos(self):
        sg_qos = {"srp": self.data.srp, "num_of_vols": 2, "cap_gb": 2,
                  "storageGroupId": "OS-QOS-SG",
                  "slo": self.data.slo, "workload": self.data.workload,
                  "hostIOLimit": {"host_io_limit_io_sec": "4000",
                                  "dynamicDistribution": "Always",
                                  "host_io_limit_mb_sec": "4000"}}
        self.data.sg_details.append(sg_qos)
        array = self.data.array
        extra_specs = self.data.extra_specs
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        return_value = self.rest.update_storagegroup_qos(
            array, "OS-QOS-SG", extra_specs)
        self.assertEqual(False, return_value)
        extra_specs['qos'] = {
            'DistributionType': 'onFailure', 'total_bytes_sec': '419430400'}
        return_value = self.rest.update_storagegroup_qos(
            array, "OS-QOS-SG", extra_specs)
        self.assertTrue(return_value)

    def test_update_storagegroup_qos_exception(self):
        array = self.data.array
        storage_group = self.data.defaultstoragegroup_name
        extra_specs = self.data.extra_specs
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Wrong',
            'total_bytes_sec': '4194304000'}
        with mock.patch.object(self.rest, 'check_status_code_success',
                               side_effect=[None, None, None, Exception]):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.rest.update_storagegroup_qos, array,
                              storage_group, extra_specs)
            extra_specs['qos']['DistributionType'] = 'Always'
            return_value = self.rest.update_storagegroup_qos(
                array, "OS-QOS-SG", extra_specs)
            self.assertFalse(return_value)

    def test_validate_qos_input_exception(self):
        qos_extra_spec = {
            'total_iops_sec': 90, 'DistributionType': 'Wrong',
            'total_bytes_sec': 100}
        input_key = 'total_iops_sec'
        sg_value = 4000
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.validate_qos_input, input_key, sg_value,
                          qos_extra_spec, {})
        input_key = 'total_bytes_sec'
        sg_value = 4000
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.validate_qos_input, input_key, sg_value,
                          qos_extra_spec, {})

    def test_validate_qos_distribution_type(self):
        qos_extra_spec = {
            'total_iops_sec': 4000, 'DistributionType': 'Always',
            'total_bytes_sec': 4194304000}
        input_prop_dict = {'total_iops_sec': 4000}
        sg_value = 'Always'
        ret_prop_dict = self.rest.validate_qos_distribution_type(
            sg_value, qos_extra_spec, input_prop_dict)
        self.assertEqual(input_prop_dict, ret_prop_dict)

    @mock.patch.object(rest.VMAXRest, 'modify_storage_group',
                       return_value=(202, VMAXCommonData.job_list[0]))
    def test_set_storagegroup_srp(self, mock_mod):
        self.rest.set_storagegroup_srp(
            self.data.array, self.data.test_vol_grp_name,
            self.data.srp2, self.data.extra_specs)
        mock_mod.assert_called_once()

    def test_get_rdf_group(self):
        with mock.patch.object(self.rest, 'get_resource') as mock_get:
            self.rest.get_rdf_group(self.data.array, self.data.rdf_group_no)
            mock_get.assert_called_once_with(
                self.data.array, 'replication', 'rdf_group',
                self.data.rdf_group_no)

    def test_get_rdf_group_list(self):
        rdf_list = self.rest.get_rdf_group_list(self.data.array)
        self.assertEqual(self.data.rdf_group_list, rdf_list)

    def test_get_rdf_group_volume(self):
        vol_details = self.data.private_vol_details['resultList']['result'][0]
        with mock.patch.object(
                self.rest, '_get_private_volume', return_value=vol_details
        ) as mock_get:
            self.rest.get_rdf_group_volume(
                self.data.array, self.data.device_id)
            mock_get.assert_called_once_with(
                self.data.array, self.data.device_id)

    def test_are_vols_rdf_paired(self):
        are_vols1, local_state, pair_state = self.rest.are_vols_rdf_paired(
            self.data.array, self.data.remote_array, self.data.device_id,
            self.data.device_id2)
        self.assertTrue(are_vols1)
        are_vols2, local_state, pair_state = self.rest.are_vols_rdf_paired(
            self.data.array, "00012345", self.data.device_id,
            self.data.device_id2)
        self.assertFalse(are_vols2)
        with mock.patch.object(self.rest, "get_rdf_group_volume",
                               return_value=None):
            are_vols3, local, pair = self.rest.are_vols_rdf_paired(
                self.data.array, self.data.remote_array, self.data.device_id,
                self.data.device_id2)
            self.assertFalse(are_vols3)

    def test_get_rdf_group_number(self):
        rdfg_num = self.rest.get_rdf_group_number(
            self.data.array, self.data.rdf_group_name)
        self.assertEqual(self.data.rdf_group_no, rdfg_num)
        with mock.patch.object(self.rest, 'get_rdf_group_list',
                               return_value=None):
            rdfg_num2 = self.rest.get_rdf_group_number(
                self.data.array, self.data.rdf_group_name)
            self.assertIsNone(rdfg_num2)
        with mock.patch.object(self.rest, 'get_rdf_group',
                               return_value=None):
            rdfg_num3 = self.rest.get_rdf_group_number(
                self.data.array, self.data.rdf_group_name)
            self.assertIsNone(rdfg_num3)

    def test_create_rdf_device_pair(self):
        ref_dict = {'array': self.data.remote_array,
                    'device_id': self.data.device_id2}
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_SYNC
        rdf_dict = self.rest.create_rdf_device_pair(
            self.data.array, self.data.device_id, self.data.rdf_group_no,
            self.data.device_id2, self.data.remote_array, extra_specs)
        self.assertEqual(ref_dict, rdf_dict)

    def test_create_rdf_device_pair_async(self):
        ref_dict = {'array': self.data.remote_array,
                    'device_id': self.data.device_id2}
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        rdf_dict = self.rest.create_rdf_device_pair(
            self.data.array, self.data.device_id, self.data.rdf_group_no,
            self.data.device_id2, self.data.remote_array, extra_specs)
        self.assertEqual(ref_dict, rdf_dict)

    def test_create_rdf_device_pair_metro(self):
        ref_dict = {'array': self.data.remote_array,
                    'device_id': self.data.device_id2}
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_METRO
        extra_specs[utils.METROBIAS] = True
        rdf_dict = self.rest.create_rdf_device_pair(
            self.data.array, self.data.device_id, self.data.rdf_group_no,
            self.data.device_id2, self.data.remote_array, extra_specs)
        self.assertEqual(ref_dict, rdf_dict)

    @mock.patch.object(rest.VMAXRest, 'get_rdf_group',
                       side_effect=[{'numDevices': 0}, {'numDevices': 0},
                                    {'numDevices': 1}])
    def test_get_metro_payload_info(self, mock_rdfg):
        ref_payload = {"establish": 'true', "rdfType": 'RDF1'}
        payload1 = self.rest.get_metro_payload_info(
            self.data.array, ref_payload, self.data.rdf_group_no, {})
        self.assertEqual(ref_payload, payload1)
        payload2 = self.rest.get_metro_payload_info(
            self.data.array, ref_payload, self.data.rdf_group_no,
            {'metro_bias': True})
        self.assertEqual('true', payload2['metroBias'])
        ref_payload2 = {"establish": 'true', "rdfType": 'RDF1'}
        payload3 = self.rest.get_metro_payload_info(
            self.data.array, ref_payload2, self.data.rdf_group_no, {})
        ref_payload3 = {"rdfType": 'NA', "format": 'true'}
        self.assertEqual(ref_payload3, payload3)

    def test_modify_rdf_device_pair(self):
        resource_name = "70/volume/00001"
        common_opts = {"force": 'false',
                       "symForce": 'false',
                       "star": 'false',
                       "hop2": 'false',
                       "bypass": 'false'}
        suspend_payload = {"action": "Suspend",
                           'executionOption': 'ASYNCHRONOUS',
                           "suspend": common_opts}

        failover_opts = deepcopy(common_opts)
        failover_opts.update({"establish": 'true',
                              "restore": 'false',
                              "remote": 'false',
                              "immediate": 'false'})
        failover_payload = {"action": "Failover",
                            'executionOption': 'ASYNCHRONOUS',
                            "failover": failover_opts}
        with mock.patch.object(
                self.rest, "modify_resource",
                return_value=(200, self.data.job_list[0])) as mock_mod:
            self.rest.modify_rdf_device_pair(
                self.data.array, self.data.device_id, self.data.rdf_group_no,
                self.data.extra_specs, suspend=True)
            mock_mod.assert_called_once_with(
                self.data.array, 'replication', 'rdf_group',
                suspend_payload, resource_name=resource_name,
                private='/private')
            mock_mod.reset_mock()
            self.rest.modify_rdf_device_pair(
                self.data.array, self.data.device_id, self.data.rdf_group_no,
                self.data.extra_specs, suspend=False)
            mock_mod.assert_called_once_with(
                self.data.array, 'replication', 'rdf_group',
                failover_payload, resource_name=resource_name,
                private='/private')

    @mock.patch.object(rest.VMAXRest, 'delete_resource')
    def test_delete_rdf_pair(self, mock_del):
        self.rest.delete_rdf_pair(
            self.data.array, self.data.device_id, self.data.rdf_group_no)
        mock_del.assert_called_once()

    def test_get_storage_group_rep(self):
        array = self.data.array
        source_group_name = self.data.storagegroup_name_source
        ref_details = self.data.sg_details_rep[0]
        volume_group = self.rest.get_storage_group_rep(array,
                                                       source_group_name)
        self.assertEqual(volume_group, ref_details)

    def test_get_volumes_in_storage_group(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_source
        ref_volumes = [self.data.device_id, self.data.device_id2]
        volume_list = self.rest.get_volumes_in_storage_group(
            array, storagegroup_name)
        self.assertEqual(ref_volumes, volume_list)

    def test_create_storagegroup_snap(self):
        array = self.data.array
        extra_specs = self.data.extra_specs
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                self.rest, "create_storagegroup_snap") as mock_create:
            self.rest.create_storagegroup_snap(
                array, source_group, snap_name, extra_specs)
            mock_create.assert_called_once_with(array,
                                                source_group,
                                                snap_name,
                                                extra_specs)

    def test_get_storagegroup_rdf_details(self):
        details = self.rest.get_storagegroup_rdf_details(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no)
        self.assertEqual(self.data.sg_rdf_details[0], details)

    def test_verify_rdf_state(self):
        verify1 = self.rest._verify_rdf_state(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no, 'Failover')
        self.assertTrue(verify1)
        verify2 = self.rest._verify_rdf_state(
            self.data.array, self.data.test_fo_vol_group,
            self.data.rdf_group_no, 'Establish')
        self.assertTrue(verify2)

    def test_modify_storagegroup_rdf(self):
        with mock.patch.object(
                self.rest, 'modify_resource',
                return_value=(202, self.data.job_list[0])) as mock_mod:
            self.rest.modify_storagegroup_rdf(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, 'Failover',
                self.data.extra_specs)
            mock_mod.assert_called_once()

    def test_delete_storagegroup_rdf(self):
        with mock.patch.object(
                self.rest, 'delete_resource') as mock_del:
            self.rest.delete_storagegroup_rdf(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no)
            mock_del.assert_called_once()

    def test_is_next_gen_array(self):
        is_next_gen = self.rest.is_next_gen_array(self.data.array)
        self.assertFalse(is_next_gen)
        is_next_gen2 = self.rest.is_next_gen_array(self.data.array_herc)
        self.assertTrue(is_next_gen2)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    @mock.patch.object(rest.VMAXRest, 'are_vols_rdf_paired',
                       side_effect=[('', '', 'syncinprog'),
                                    ('', '', 'consistent'),
                                    exception.CinderException])
    def test_wait_for_rdf_consistent_state(self, mock_paired):
        self.rest.wait_for_rdf_consistent_state(
            self.data.array, self.data.remote_array,
            self.data.device_id, self.data.device_id2,
            self.data.extra_specs)
        self.assertEqual(2, mock_paired.call_count)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest.wait_for_rdf_consistent_state,
                          self.data.array, self.data.remote_array,
                          self.data.device_id, self.data.device_id2,
                          self.data.extra_specs)

    @mock.patch.object(rest.VMAXRest, 'modify_resource',
                       return_value=('200', 'JobComplete'))
    def test_modify_volume_snap_rename(self, mock_modify):
        array = self.data.array
        source_id = self.data.device_id
        old_snap_backend_name = self.data.snapshot_id
        new_snap_backend_name = self.data.managed_snap_id
        self.rest.modify_volume_snap(
            array, source_id, source_id, old_snap_backend_name,
            self.data.extra_specs, link=False, unlink=False,
            rename=True, new_snap_name=new_snap_backend_name)
        mock_modify.assert_called_once()

    def test_get_private_volume_list_pass(self):
        array_id = self.data.array
        response = [{"volumeHeader": {
            "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
            "status": "Ready", "configuration": "TDEV"}}]

        with mock.patch.object(
                self.rest, 'get_resource',
                return_value=self.data.private_vol_rest_response_single):
            volume = self.rest.get_private_volume_list(array_id)
            self.assertEqual(response, volume)

    def test_get_private_volume_list_none(self):
        array_id = self.data.array
        response = []
        with mock.patch.object(
                self.rest, 'get_resource', return_value=
                VMAXCommonData.private_vol_rest_response_none):
            vol_list = self.rest.get_private_volume_list(array_id)
            self.assertEqual(response, vol_list)

    @mock.patch.object(
        rest.VMAXRest, 'get_iterator_page_list', return_value=
        VMAXCommonData.private_vol_rest_response_iterator_second['result'])
    @mock.patch.object(
        rest.VMAXRest, 'get_resource', return_value=
        deepcopy(VMAXCommonData.private_vol_rest_response_iterator_first))
    def test_get_private_volume_list_iterator(self, mock_get_resource,
                                              mock_iterator):
        array_id = self.data.array
        response = [
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00002",
                "status": "Ready", "configuration": "TDEV"}},
            {"volumeHeader": {
                "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
                "status": "Ready", "configuration": "TDEV"}}]
        volume = self.rest.get_private_volume_list(array_id)
        self.assertEqual(response, volume)

    def test_get_iterator_list(self):
        with mock.patch.object(
                self.rest, '_get_request', side_effect=[
                    self.data.rest_iterator_resonse_one,
                    self.data.rest_iterator_resonse_two]):

            expected_response = [
                {"volumeHeader": {
                    "capGB": 1.0, "capMB": 1026.0, "volumeId": "00001",
                    "status": "Ready", "configuration": "TDEV"}},
                {"volumeHeader": {
                    "capGB": 1.0, "capMB": 1026.0, "volumeId": "00002",
                    "status": "Ready", "configuration": "TDEV"}}]
            iterator_id = 'test_iterator_id'
            result_count = 1500
            start_position = 1
            end_position = 1000
            max_page_size = 1000

            actual_response = self.rest.get_iterator_page_list(
                iterator_id, result_count, start_position, end_position,
                max_page_size)
            self.assertEqual(expected_response, actual_response)

    def test_set_rest_credentials(self):
        array_info = {
            'RestServerIp': '10.10.10.10',
            'RestServerPort': '8443',
            'RestUserName': 'user_test',
            'RestPassword': 'pass_test',
            'SSLVerify': True,
        }
        self.rest.set_rest_credentials(array_info)
        self.assertEqual('user_test', self.rest.user)
        self.assertEqual('pass_test', self.rest.passwd)
        self.assertTrue(self.rest.verify)
        self.assertEqual('https://10.10.10.10:8443/univmax/restapi',
                         self.rest.base_uri)

    @mock.patch.object(
        rest.VMAXRest, 'get_iterator_page_list', return_value=
        VMAXCommonData.private_vol_rest_response_iterator_second['result'])
    def test_list_pagination(self, mock_iter):
        result_list = self.rest.list_pagination(
            deepcopy(self.data.private_vol_rest_response_iterator_first))
        # reflects sample data, 1 from first iterator page and 1 from
        # second iterator page
        self.assertTrue(2 == len(result_list))

    def test_get_vmax_model(self):
        reference = 'PowerMax_2000'
        with mock.patch.object(self.rest, '_get_request',
                               return_value=self.data.powermax_model_details):
            self.assertEqual(self.rest.get_vmax_model(self.data.array),
                             reference)


class VMAXProvisionTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXProvisionTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = FakeConfiguration(
            None, 'ProvisionTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = iscsi.VMAXISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.provision = self.common.provision
        self.utils = self.common.utils
        self.rest = self.common.rest

    @mock.patch.object(rest.VMAXRest, 'create_storage_group',
                       return_value=VMAXCommonData.storagegroup_name_f)
    @mock.patch.object(rest.VMAXRest, 'get_storage_group',
                       side_effect=[
                           VMAXCommonData.storagegroup_name_f, None])
    def test_create_storage_group(self, mock_get_sg, mock_create):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        srp = self.data.srp
        slo = self.data.slo
        workload = self.data.workload
        extra_specs = self.data.extra_specs
        for x in range(0, 2):
            storagegroup = self.provision.create_storage_group(
                array, storagegroup_name, srp, slo, workload, extra_specs)
            self.assertEqual(storagegroup_name, storagegroup)
        mock_create.assert_called_once()

    def test_create_volume_from_sg(self):
        array = self.data.array
        storagegroup_name = self.data.storagegroup_name_f
        volumeId = self.data.test_volume.id
        volume_name = self.utils.get_volume_element_name(volumeId)
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        volume_dict = self.provision.create_volume_from_sg(
            array, volume_name, storagegroup_name, volume_size, extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    def test_delete_volume_from_srp(self):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.volume_details[0]['volume_identifier']
        with mock.patch.object(self.provision.rest, 'delete_volume'):
            self.provision.delete_volume_from_srp(
                array, device_id, volume_name)
            self.provision.rest.delete_volume.assert_called_once_with(
                array, device_id)

    def test_create_volume_snap_vx(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        ttl = 0
        with mock.patch.object(self.provision.rest, 'create_volume_snap'):
            self.provision.create_volume_snapvx(
                array, source_device_id, snap_name, extra_specs)
            self.provision.rest.create_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, extra_specs, ttl)

    def test_create_volume_replica_create_snap_true(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        # TTL of 1 hours
        ttl = 1
        with mock.patch.object(self.provision, 'create_volume_snapvx'):
            with mock.patch.object(self.provision.rest, 'modify_volume_snap'):
                self.provision.create_volume_replica(
                    array, source_device_id, target_device_id,
                    snap_name, extra_specs, create_snap=True)
                self.provision.rest.modify_volume_snap.assert_called_once_with(
                    array, source_device_id, target_device_id, snap_name,
                    extra_specs, link=True)
                self.provision.create_volume_snapvx.assert_called_once_with(
                    array, source_device_id, snap_name, extra_specs, ttl=ttl)

    def test_create_volume_replica_create_snap_false(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.provision, 'create_volume_snapvx'):
            with mock.patch.object(self.provision.rest, 'modify_volume_snap'):
                self.provision.create_volume_replica(
                    array, source_device_id, target_device_id,
                    snap_name, extra_specs, create_snap=False)
                self.provision.rest.modify_volume_snap.assert_called_once_with(
                    array, source_device_id, target_device_id, snap_name,
                    extra_specs, link=True)
                self.provision.create_volume_snapvx.assert_not_called()

    def test_break_replication_relationship(self):
        array = self.data.array
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.provision.rest, 'modify_volume_snap'):
            self.provision.break_replication_relationship(
                array, target_device_id, source_device_id, snap_name,
                extra_specs)
            (self.provision.rest.modify_volume_snap.
                assert_called_once_with(
                    array, source_device_id, target_device_id,
                    snap_name, extra_specs,
                    list_volume_pairs=None, unlink=True, generation=0))

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_unlink_volume(self):
        with mock.patch.object(self.rest, 'modify_volume_snap') as mock_mod:
            self.provision._unlink_volume(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs)
            mock_mod.assert_called_once_with(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs,
                list_volume_pairs=None, unlink=True, generation=0)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_unlink_volume_exception(self):
        with mock.patch.object(
                self.rest, 'modify_volume_snap', side_effect=[
                    exception.VolumeBackendAPIException(data=''), '']
        ) as mock_mod:
            self.provision._unlink_volume(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.snap_location['snap_name'], self.data.extra_specs)
            self.assertEqual(2, mock_mod.call_count)

    def test_delete_volume_snap(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        generation = 0
        with mock.patch.object(self.provision.rest, 'delete_volume_snap'):
            self.provision.delete_volume_snap(
                array, snap_name, source_device_id)
            self.provision.rest.delete_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, False, generation)

    def test_delete_volume_snap_restore(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        restored = True
        generation = 0
        with mock.patch.object(self.provision.rest, 'delete_volume_snap'):
            self.provision.delete_volume_snap(
                array, snap_name, source_device_id, restored)
            self.provision.rest.delete_volume_snap.assert_called_once_with(
                array, snap_name, source_device_id, True, generation)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=test_utils.ZeroIntervalLoopingCall)
    def test_restore_complete(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, '_is_restore_complete',
                return_value=True):
            isrestored = self.provision.is_restore_complete(
                array, source_device_id, snap_name, extra_specs)
            self.assertTrue(isrestored)
        with mock.patch.object(
                self.provision, '_is_restore_complete',
                side_effect=exception.CinderException):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.provision.is_restore_complete,
                              array, source_device_id, snap_name, extra_specs)

    def test_is_restore_complete(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        snap_details = {
            'linkedDevices':
            [{'targetDevice': source_device_id, 'state': "Restored"}]}
        with mock.patch.object(self.provision.rest,
                               'get_volume_snap', return_value=snap_details):
            isrestored = self.provision._is_restore_complete(
                array, source_device_id, snap_name)
            self.assertTrue(isrestored)
        snap_details['linkedDevices'][0]['state'] = "Restoring"
        with mock.patch.object(self.provision.rest,
                               'get_volume_snap', return_value=snap_details):
            isrestored = self.provision._is_restore_complete(
                array, source_device_id, snap_name)
            self.assertFalse(isrestored)

    def test_revert_volume_snapshot(self):
        array = self.data.array
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision.rest, 'modify_volume_snap', return_value=None):
            self.provision.revert_volume_snapshot(
                array, source_device_id, snap_name, extra_specs)
            self.provision.rest.modify_volume_snap.assert_called_once_with(
                array, source_device_id, "", snap_name,
                extra_specs, restore=True)

    def test_extend_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        new_size = '3'
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.provision.rest, 'extend_volume'
                               ) as mock_ex:
            self.provision.extend_volume(array, device_id, new_size,
                                         extra_specs)
            mock_ex.assert_called_once_with(
                array, device_id, new_size, extra_specs)
            mock_ex.reset_mock()
            # Pass in rdf group
            self.provision.extend_volume(array, device_id, new_size,
                                         extra_specs, self.data.rdf_group_no)
            mock_ex.assert_called_once_with(
                array, device_id, new_size, extra_specs)

    def test_get_srp_pool_stats(self):
        array = self.data.array
        array_info = self.common.pool_info['arrays_info'][0]
        ref_stats = (self.data.srp_details['total_usable_cap_gb'],
                     float(self.data.srp_details['total_usable_cap_gb']
                           - self.data.srp_details['total_used_cap_gb']),
                     self.data.srp_details['total_subscribed_cap_gb'],
                     self.data.srp_details['reserved_cap_percent'])
        stats = self.provision.get_srp_pool_stats(array, array_info)
        self.assertEqual(ref_stats, stats)

    def test_get_srp_pool_stats_errors(self):
        # cannot retrieve srp
        array = self.data.array
        array_info = {'srpName': self.data.failed_resource}
        ref_stats = (0, 0, 0, 0, False)
        stats = self.provision.get_srp_pool_stats(array, array_info)
        self.assertEqual(ref_stats, stats)
        # cannot report on all stats
        with mock.patch.object(self.provision.rest, 'get_srp_by_name',
                               return_value={'total_usable_cap_gb': 33}):
            ref_stats = (33, 0, 0, 0)
            stats = self.provision.get_srp_pool_stats(array, array_info)
            self.assertEqual(ref_stats, stats)

    def test_verify_slo_workload_true(self):
        # with slo and workload
        array = self.data.array
        slo = self.data.slo
        workload = self.data.workload
        srp = self.data.srp
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, slo, workload, srp)
        self.assertTrue(valid_slo)
        self.assertTrue(valid_workload)
        # slo and workload = none
        slo2 = None
        workload2 = None
        valid_slo2, valid_workload2 = self.provision.verify_slo_workload(
            array, slo2, workload2, srp)
        self.assertTrue(valid_slo2)
        self.assertTrue(valid_workload2)
        slo2 = None
        workload2 = 'None'
        valid_slo2, valid_workload2 = self.provision.verify_slo_workload(
            array, slo2, workload2, srp)
        self.assertTrue(valid_slo2)
        self.assertTrue(valid_workload2)

    def test_verify_slo_workload_false(self):
        # Both wrong
        array = self.data.array
        slo = 'Diamante'
        workload = 'DSSS'
        srp = self.data.srp
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, slo, workload, srp)
        self.assertFalse(valid_slo)
        self.assertFalse(valid_workload)
        # Workload set, no slo set
        valid_slo, valid_workload = self.provision.verify_slo_workload(
            array, None, self.data.workload, srp)
        self.assertTrue(valid_slo)
        self.assertFalse(valid_workload)

    def test_get_slo_workload_settings_from_storage_group(self):
        ref_settings = "Diamond+DSS"
        sg_slo_settings = (
            self.provision.get_slo_workload_settings_from_storage_group(
                self.data.array, self.data.defaultstoragegroup_name))
        self.assertEqual(ref_settings, sg_slo_settings)
        # No workload
        with mock.patch.object(self.provision.rest, 'get_storage_group',
                               return_value={'slo': 'Silver'}):
            ref_settings2 = "Silver+NONE"
            sg_slo_settings2 = (
                self.provision.get_slo_workload_settings_from_storage_group(
                    self.data.array, 'no_workload_sg'))
            self.assertEqual(ref_settings2, sg_slo_settings2)
        # NextGen Array
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            ref_settings3 = "Diamond+NONE"
            sg_slo_settings3 = (
                self.provision.get_slo_workload_settings_from_storage_group(
                    self.data.array, self.data.defaultstoragegroup_name))
            self.assertEqual(ref_settings3, sg_slo_settings3)

    @mock.patch.object(rest.VMAXRest, 'wait_for_rdf_consistent_state')
    @mock.patch.object(rest.VMAXRest, 'delete_rdf_pair')
    @mock.patch.object(rest.VMAXRest, 'modify_rdf_device_pair')
    def test_break_rdf_relationship(self, mock_mod, mock_del, mock_wait):
        array = self.data.array
        device_id = self.data.device_id
        target_device = self.data.device_id2
        rdf_group_name = self.data.rdf_group_name
        rep_extra_specs = self.data.rep_extra_specs
        # State is suspended
        self.provision.break_rdf_relationship(
            array, device_id, target_device,
            rdf_group_name, rep_extra_specs, "Suspended")
        mock_mod.assert_not_called()
        mock_del.assert_called_once_with(
            array, device_id, rdf_group_name)
        mock_del.reset_mock()
        # State is synchronized
        self.provision.break_rdf_relationship(
            array, device_id, target_device,
            rdf_group_name, rep_extra_specs, "Synchronized")
        mock_mod.assert_called_once_with(
            array, device_id, rdf_group_name, rep_extra_specs,
            suspend=True)
        mock_del.assert_called_once_with(
            array, device_id, rdf_group_name)
        # sync still in progress
        self.provision.break_rdf_relationship(
            array, device_id, target_device,
            rdf_group_name, rep_extra_specs, "SyncInProg")
        mock_wait.assert_called_once()

    @mock.patch.object(provision.VMAXProvision, 'disable_group_replication')
    @mock.patch.object(provision.VMAXProvision, 'delete_rdf_pair')
    def test_break_metro_rdf_pair(self, mock_del, mock_disable):
        self.provision.break_metro_rdf_pair(
            self.data.array, self.data.device_id, self.data.device_id2,
            self.data.rdf_group_no, self.data.rep_extra_specs, 'metro_grp')
        mock_del.assert_called_once()

    def test_delete_rdf_pair_async(self):
        with mock.patch.object(
                self.provision.rest, 'delete_rdf_pair') as mock_del_rdf:
            extra_specs = deepcopy(self.data.extra_specs)
            extra_specs[utils.REP_MODE] = utils.REP_ASYNC
            self.provision.delete_rdf_pair(
                self.data.array, self.data.device_id,
                self.data.rdf_group_no, self.data.device_id2, extra_specs)
            mock_del_rdf.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'get_storage_group',
                       return_value=None)
    def test_create_volume_group_success(self, mock_get_sg):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        extra_specs = self.data.extra_specs
        ref_value = self.data.storagegroup_name_source
        storagegroup = self.provision.create_volume_group(
            array, group_name, extra_specs)
        self.assertEqual(ref_value, storagegroup)

    def test_create_group_replica(self):
        array = self.data.array
        source_group = self.data.storagegroup_name_source
        snap_name = self.data.group_snapshot_name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision,
                'create_group_replica') as mock_create_replica:
            self.provision.create_group_replica(
                array, source_group, snap_name, extra_specs)
            mock_create_replica.assert_called_once_with(
                array, source_group, snap_name, extra_specs)

    def test_delete_group_replica(self):
        array = self.data.array
        snap_name = self.data.group_snapshot_name
        source_group_name = self.data.storagegroup_name_source
        with mock.patch.object(
                self.provision,
                'delete_group_replica') as mock_delete_replica:
            self.provision.delete_group_replica(array,
                                                snap_name,
                                                source_group_name)
            mock_delete_replica.assert_called_once_with(
                array, snap_name, source_group_name)

    def test_link_and_break_replica(self):
        array = self.data.array
        source_group_name = self.data.storagegroup_name_source
        target_group_name = self.data.target_group_name
        snap_name = self.data.group_snapshot_name
        extra_specs = self.data.extra_specs
        deleteSnapshot = False
        with mock.patch.object(
                self.provision,
                'link_and_break_replica') as mock_link_and_break_replica:
            self.provision.link_and_break_replica(
                array, source_group_name,
                target_group_name, snap_name,
                extra_specs, deleteSnapshot)
            mock_link_and_break_replica.assert_called_once_with(
                array, source_group_name,
                target_group_name, snap_name,
                extra_specs, deleteSnapshot)

    @mock.patch.object(rest.VMAXRest, 'get_storage_group',
                       side_effect=[None, VMAXCommonData.sg_details[1]])
    @mock.patch.object(provision.VMAXProvision, 'create_volume_group')
    def test_get_or_create_volume_group(self, mock_create, mock_sg):
        for x in range(0, 2):
            self.provision.get_or_create_volume_group(
                self.data.array, self.data.test_group, self.data.extra_specs)
        self.assertEqual(2, mock_sg.call_count)
        self.assertEqual(1, mock_create.call_count)

    @mock.patch.object(rest.VMAXRest, 'create_resource',
                       return_value=(202, VMAXCommonData.job_list[0]))
    def test_replicate_group(self, mock_create):
        self.rest.replicate_group(
            self.data.array, self.data.test_rep_group,
            self.data.rdf_group_no, self.data.remote_array,
            self.data.extra_specs)
        mock_create.assert_called_once()

    def test_enable_group_replication(self):
        with mock.patch.object(self.rest,
                               'modify_storagegroup_rdf') as mock_mod:
            self.provision.enable_group_replication(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, self.data.extra_specs)
            mock_mod.assert_called_once()

    def test_disable_group_replication(self):
        with mock.patch.object(self.rest,
                               'modify_storagegroup_rdf') as mock_mod:
            self.provision.disable_group_replication(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, self.data.extra_specs)
            mock_mod.assert_called_once()

    def test_failover_group(self):
        with mock.patch.object(self.rest,
                               'modify_storagegroup_rdf') as mock_fo:
            # Failover
            self.provision.failover_group(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, self.data.extra_specs)
            mock_fo.assert_called_once_with(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, 'Failover', self.data.extra_specs)
            mock_fo.reset_mock()
            # Failback
            self.provision.failover_group(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, self.data.extra_specs, False)
            mock_fo.assert_called_once_with(
                self.data.array, self.data.test_vol_grp_name,
                self.data.rdf_group_no, 'Failback', self.data.extra_specs)

    @mock.patch.object(rest.VMAXRest, 'modify_storagegroup_rdf')
    @mock.patch.object(rest.VMAXRest, 'delete_storagegroup_rdf')
    def test_delete_group_replication(self, mock_mod, mock_del):
        self.provision.delete_group_replication(
            self.data.array, self.data.test_vol_grp_name,
            self.data.rdf_group_no, self.data.extra_specs)
        mock_mod.assert_called_once()
        mock_del.assert_called_once()

    @mock.patch.object(
        rest.VMAXRest, 'get_snap_linked_device_list',
        side_effect=[[{'targetDevice': VMAXCommonData.device_id2}],
                     [{'targetDevice': VMAXCommonData.device_id2},
                      {'targetDevice': VMAXCommonData.device_id3}]])
    @mock.patch.object(provision.VMAXProvision, '_unlink_volume')
    def test_delete_volume_snap_check_for_links(self, mock_unlink, mock_tgts):
        self.provision.delete_volume_snap_check_for_links(
            self.data.array, self.data.test_snapshot_snap_name,
            self.data.device_id, self.data.extra_specs)
        mock_unlink.assert_called_once_with(
            self.data.array, "", "", self.data.test_snapshot_snap_name,
            self.data.extra_specs, list_volume_pairs=[
                (self.data.device_id, VMAXCommonData.device_id2)],
            generation=0)
        mock_unlink.reset_mock()
        self.provision.delete_volume_snap_check_for_links(
            self.data.array, self.data.test_snapshot_snap_name,
            self.data.device_id, self.data.extra_specs)
        self.assertEqual(2, mock_unlink.call_count)


class VMAXCommonTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXCommonTest, self).setUp()
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1.0)
        configuration = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_f])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = fc.VMAXFCDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.provision = self.common.provision
        self.rest = self.common.rest
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))

    @mock.patch.object(rest.VMAXRest,
                       'set_rest_credentials')
    @mock.patch.object(common.VMAXCommon,
                       '_get_slo_workload_combinations',
                       return_value=[])
    @mock.patch.object(common.VMAXCommon,
                       'get_attributes_from_cinder_config',
                       return_value=[])
    def test_gather_info_no_opts(self, mock_parse, mock_combo, mock_rest):
        configuration = FakeConfiguration(None, 'config_group', None, None)
        fc.VMAXFCDriver(configuration=configuration)

    @mock.patch.object(rest.VMAXRest, 'is_next_gen_array',
                       return_value=True)
    @mock.patch.object(rest.VMAXRest, 'set_rest_credentials')
    @mock.patch.object(common.VMAXCommon, '_get_slo_workload_combinations',
                       return_value=[])
    @mock.patch.object(common.VMAXCommon, 'get_attributes_from_cinder_config',
                       return_value=VMAXCommonData.array_info_wl)
    def test_gather_info_next_gen(self, mock_parse, mock_combo, mock_rest,
                                  mock_nextgen):
        self.common._gather_info()
        self.assertTrue(self.common.nextGen)

    def test_get_slo_workload_combinations_powermax(self):
        array_info = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_info)
        self.assertTrue(len(finalarrayinfolist) > 1)

    @mock.patch.object(rest.VMAXRest, 'get_vmax_model',
                       return_value=VMAXCommonData.vmax_model_details['model'])
    @mock.patch.object(rest.VMAXRest, 'get_slo_list',
                       return_value=VMAXCommonData.vmax_slo_details['sloId'])
    def test_get_slo_workload_combinations_vmax(self, mck_slo, mck_model):
        array_info = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_info)
        self.assertTrue(len(finalarrayinfolist) > 1)

    @mock.patch.object(rest.VMAXRest, 'get_vmax_model',
                       return_value=VMAXCommonData.powermax_model_details[
                           'model'])
    @mock.patch.object(rest.VMAXRest, 'get_workload_settings',
                       return_value=[])
    @mock.patch.object(rest.VMAXRest, 'get_slo_list',
                       return_value=VMAXCommonData.powermax_slo_details[
                           'sloId'])
    def test_get_slo_workload_combinations_next_gen(self, mck_slo, mck_wl,
                                                    mck_model):
        self.common.nextGen = True
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            self.data.array_info_no_wl)
        self.assertTrue(len(finalarrayinfolist) == 14)

    @mock.patch.object(rest.VMAXRest, 'get_vmax_model',
                       return_value=VMAXCommonData.vmax_model_details[
                           'model'])
    @mock.patch.object(rest.VMAXRest, 'get_workload_settings',
                       return_value=[])
    @mock.patch.object(rest.VMAXRest, 'get_slo_list',
                       return_value=VMAXCommonData.powermax_slo_details[
                           'sloId'])
    def test_get_slo_workload_combinations_next_gen_vmax(
            self, mck_slo, mck_wl, mck_model):
        self.common.nextGen = True
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            self.data.array_info_no_wl)
        self.assertTrue(len(finalarrayinfolist) == 18)

    def test_get_slo_workload_combinations_failed(self):
        array_info = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._get_slo_workload_combinations,
                          array_info)

    def test_create_volume(self):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location)})
        model_update = self.common.create_volume(self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    def test_create_volume_qos(self):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location)})
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                               return_value=extra_specs):
            model_update = self.common.create_volume(self.data.test_volume)
            self.assertEqual(ref_model_update, model_update)

    def test_create_volume_from_snapshot(self):
        ref_model_update = (
            {'provider_location': six.text_type(
                self.data.provider_location)})
        model_update = self.common.create_volume_from_snapshot(
            self.data.test_clone_volume, self.data.test_snapshot)
        self.assertEqual(ref_model_update, model_update)
        # Test from legacy snapshot
        model_update = self.common.create_volume_from_snapshot(
            self.data.test_clone_volume, self.data.test_legacy_snapshot)
        self.assertEqual(ref_model_update, model_update)

    def test_cloned_volume(self):
        ref_model_update = (
            {'provider_location': six.text_type(
                self.data.provider_location)})
        model_update = self.common.create_cloned_volume(
            self.data.test_clone_volume, self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    def test_delete_volume(self):
        with mock.patch.object(self.common, '_delete_volume'):
            self.common.delete_volume(self.data.test_volume)
            self.common._delete_volume.assert_called_once_with(
                self.data.test_volume)

    def test_create_snapshot(self):
        ref_model_update = (
            {'provider_location': six.text_type(
                self.data.snap_location)})
        model_update = self.common.create_snapshot(
            self.data.test_snapshot, self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    def test_delete_snapshot(self):
        snap_name = self.data.snap_location['snap_name']
        sourcedevice_id = self.data.snap_location['source_id']
        generation = 0
        with mock.patch.object(self.provision, 'delete_volume_snap'):
            self.common.delete_snapshot(self.data.test_snapshot,
                                        self.data.test_volume)
            self.provision.delete_volume_snap.assert_called_once_with(
                self.data.array, snap_name, [sourcedevice_id],
                restored=False, generation=generation)

    def test_delete_snapshot_not_found(self):
        with mock.patch.object(self.common, '_parse_snap_info',
                               return_value=(None, 'Something')):
            with mock.patch.object(self.provision, 'delete_volume_snap'):
                self.common.delete_snapshot(self.data.test_snapshot,
                                            self.data.test_volume)
                self.provision.delete_volume_snap.assert_not_called()

    def test_delete_legacy_snap(self):
        with mock.patch.object(self.common, '_delete_volume') as mock_del:
            self.common.delete_snapshot(self.data.test_legacy_snapshot,
                                        self.data.test_legacy_vol)
            mock_del.assert_called_once_with(self.data.test_legacy_snapshot)

    @mock.patch.object(masking.VMAXMasking,
                       'return_volume_to_fast_managed_group')
    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_remove_members(self, mock_rm, mock_return):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        self.common._remove_members(
            array, volume, device_id, extra_specs, self.data.connector, False)
        mock_rm.assert_called_once_with(
            array, volume, device_id, volume_name,
            extra_specs, True, self.data.connector, async_grp=None)

    @mock.patch.object(masking.VMAXMasking,
                       'return_volume_to_fast_managed_group')
    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_remove_members_multiattach_case(self, mock_rm, mock_return):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        self.common._remove_members(
            array, volume, device_id, extra_specs, self.data.connector, True)
        mock_rm.assert_called_once_with(
            array, volume, device_id, volume_name,
            extra_specs, False, self.data.connector, async_grp=None)
        mock_return.assert_called_once()

    def test_unmap_lun(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        connector = self.data.connector
        with mock.patch.object(self.common, '_remove_members'):
            self.common._unmap_lun(volume, connector)
            self.common._remove_members.assert_called_once_with(
                array, volume, device_id, extra_specs,
                connector, False, async_grp=None)

    @mock.patch.object(common.VMAXCommon, '_remove_members')
    def test_unmap_lun_attachments(self, mock_rm):
        volume1 = deepcopy(self.data.test_volume)
        volume1.volume_attachment.objects = [self.data.test_volume_attachment]
        connector = self.data.connector
        self.common._unmap_lun(volume1, connector)
        mock_rm.assert_called_once()
        mock_rm.reset_mock()
        volume2 = deepcopy(volume1)
        volume2.volume_attachment.objects.append(
            self.data.test_volume_attachment)
        self.common._unmap_lun(volume2, connector)
        mock_rm.assert_not_called()

    def test_unmap_lun_qos(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs['qos'] = {
            'total_iops_sec': '4000', 'DistributionType': 'Always'}
        connector = self.data.connector
        with mock.patch.object(self.common, '_remove_members'):
            with mock.patch.object(self.utils, 'get_volumetype_extra_specs',
                                   return_value=extra_specs):
                self.common._unmap_lun(volume, connector)
                self.common._remove_members.assert_called_once_with(
                    array, volume, device_id, extra_specs,
                    connector, False, async_grp=None)

    def test_unmap_lun_not_mapped(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(self.common, 'find_host_lun_id',
                               return_value=({}, False)):
            with mock.patch.object(self.common, '_remove_members'):
                self.common._unmap_lun(volume, connector)
                self.common._remove_members.assert_not_called()

    def test_unmap_lun_connector_is_none(self):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['storagetype:portgroupname'] = (
            self.data.port_group_name_f)
        with mock.patch.object(self.common, '_remove_members'):
            self.common._unmap_lun(volume, None)
            self.common._remove_members.assert_called_once_with(
                array, volume, device_id, extra_specs, None,
                False, async_grp=None)

    def test_initialize_connection_already_mapped(self):
        volume = self.data.test_volume
        connector = self.data.connector
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0]
                    ['host_lun_address'])
        ref_dict = {'hostlunid': int(host_lun, 16),
                    'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array,
                    'device_id': self.data.device_id}
        device_info_dict = self.common.initialize_connection(volume, connector)
        self.assertEqual(ref_dict, device_info_dict)

    def test_initialize_connection_already_mapped_next_gen(self):
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            volume = self.data.test_volume
            connector = self.data.connector
            host_lun = (self.data.maskingview[0]['maskingViewConnection'][0]
                        ['host_lun_address'])
            ref_dict = {'hostlunid': int(host_lun, 16),
                        'maskingview': self.data.masking_view_name_f,
                        'array': self.data.array,
                        'device_id': self.data.device_id}
            device_info_dict = self.common.initialize_connection(volume,
                                                                 connector)
            self.assertEqual(ref_dict, device_info_dict)

    @mock.patch.object(common.VMAXCommon, 'find_host_lun_id',
                       return_value=({}, False))
    @mock.patch.object(common.VMAXCommon, '_attach_volume',
                       return_value=({}, VMAXCommonData.port_group_name_f))
    def test_initialize_connection_not_mapped(self, mock_attach, mock_id):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        masking_view_dict[utils.IS_MULTIATTACH] = False
        device_info_dict = self.common.initialize_connection(
            volume, connector)
        self.assertEqual({}, device_info_dict)
        mock_attach.assert_called_once_with(
            volume, connector, extra_specs, masking_view_dict)

    @mock.patch.object(rest.VMAXRest, 'is_next_gen_array',
                       return_value=True)
    @mock.patch.object(common.VMAXCommon, 'find_host_lun_id',
                       return_value=({}, False))
    @mock.patch.object(common.VMAXCommon, '_attach_volume',
                       return_value=({}, VMAXCommonData.port_group_name_f))
    def test_initialize_connection_not_mapped_next_gen(self, mock_attach,
                                                       mock_id, mck_gen):
        volume = self.data.test_volume
        connector = self.data.connector
        device_info_dict = self.common.initialize_connection(
            volume, connector)
        self.assertEqual({}, device_info_dict)

    @mock.patch.object(
        masking.VMAXMasking, 'pre_multiattach',
        return_value=VMAXCommonData.masking_view_dict_multiattach)
    @mock.patch.object(common.VMAXCommon, 'find_host_lun_id',
                       return_value=({}, True))
    @mock.patch.object(common.VMAXCommon, '_attach_volume',
                       return_value=({}, VMAXCommonData.port_group_name_f))
    def test_initialize_connection_multiattach_case(
            self, mock_attach, mock_id, mock_pre):
        volume = self.data.test_volume
        connector = self.data.connector
        self.common.initialize_connection(volume, connector)
        mock_attach.assert_called_once()
        mock_pre.assert_called_once()

    def test_attach_volume_success(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0]
                    ['host_lun_address'])
        ref_dict = {'hostlunid': int(host_lun, 16),
                    'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array,
                    'device_id': self.data.device_id}
        with mock.patch.object(self.masking, 'setup_masking_view',
                               return_value={
                                   utils.PORTGROUPNAME:
                                       self.data.port_group_name_f}):
            device_info_dict, pg = self.common._attach_volume(
                volume, connector, extra_specs, masking_view_dict)
        self.assertEqual(ref_dict, device_info_dict)

    @mock.patch.object(masking.VMAXMasking,
                       'check_if_rollback_action_for_masking_required')
    @mock.patch.object(masking.VMAXMasking, 'setup_masking_view',
                       return_value={})
    @mock.patch.object(common.VMAXCommon, 'find_host_lun_id',
                       return_value=({}, False))
    def test_attach_volume_failed(self, mock_lun, mock_setup, mock_rollback):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._attach_volume, volume,
                          connector, extra_specs,
                          masking_view_dict)
        device_id = self.data.device_id
        (mock_rollback.assert_called_once_with(
            self.data.array, volume, device_id, {}))

    def test_terminate_connection(self):
        volume = self.data.test_volume
        connector = self.data.connector
        with mock.patch.object(self.common, '_unmap_lun'):
            self.common.terminate_connection(volume, connector)
            self.common._unmap_lun.assert_called_once_with(
                volume, connector)

    @mock.patch.object(rest.VMAXRest, 'is_next_gen_array', return_value=True)
    @mock.patch.object(common.VMAXCommon, '_sync_check')
    @mock.patch.object(provision.VMAXProvision, 'extend_volume')
    def test_extend_volume_success(self, mock_extend, mock_sync, mock_newgen):
        volume = self.data.test_volume
        array = self.data.array
        device_id = self.data.device_id
        new_size = self.data.test_volume.size
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               side_effect=[(False, False, None),
                                            (False, True, None)]):
            self.common.extend_volume(volume, new_size)
            mock_extend.assert_called_once_with(
                array, device_id, new_size, ref_extra_specs)
        # Success, with snapshot, on new VMAX array
            mock_extend.reset_mock()
            self.common.extend_volume(volume, new_size)
            mock_extend.assert_called_once_with(
                array, device_id, new_size, ref_extra_specs)

    def test_extend_volume_failed_snap_src(self):
        volume = self.data.test_volume
        new_size = self.data.test_volume.size
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(False, True, None)):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume, volume, new_size)

    def test_extend_volume_failed_no_device_id(self):
        volume = self.data.test_volume
        new_size = self.data.test_volume.size
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume, volume, new_size)

    def test_extend_volume_failed_wrong_size(self):
        volume = self.data.test_volume
        new_size = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.extend_volume, volume, new_size)

    def test_update_volume_stats(self):
        data = self.common.update_volume_stats()
        self.assertEqual('CommonTests', data['volume_backend_name'])

    def test_update_volume_stats_no_wlp(self):
        with mock.patch.object(self.common, '_update_srp_stats',
                               return_value=('123s#SRP_1#None#None',
                                             100, 90, 90, 10)):
            data = self.common.update_volume_stats()
            self.assertEqual('CommonTests', data['volume_backend_name'])

    def test_update_srp_stats_with_wl(self):
        with mock.patch.object(self.rest, 'get_srp_by_name',
                               return_value=self.data.srp_details):
            location_info, __, __, __, __ = self.common._update_srp_stats(
                self.data.array_info_wl)
            self.assertEqual(location_info, '000197800123#SRP_1#Diamond#OLTP')

    def test_update_srp_stats_no_wl(self):
        with mock.patch.object(self.rest, 'get_srp_by_name',
                               return_value=self.data.srp_details):
            location_info, __, __, __, __ = self.common._update_srp_stats(
                self.data.array_info_no_wl)
            self.assertEqual(location_info, '000197800123#SRP_1#Diamond')

    def test_find_device_on_array_success(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_device_id = self.data.device_id
        founddevice_id = self.common._find_device_on_array(volume, extra_specs)
        self.assertEqual(ref_device_id, founddevice_id)

    def test_find_device_on_array_provider_location_not_string(self):
        volume = fake_volume.fake_volume_obj(
            context='cxt', provider_location=None)
        extra_specs = self.data.extra_specs
        founddevice_id = self.common._find_device_on_array(
            volume, extra_specs)
        self.assertIsNone(founddevice_id)

    def test_find_legacy_device_on_array(self):
        volume = self.data.test_legacy_vol
        extra_specs = self.data.extra_specs
        ref_device_id = self.data.device_id
        founddevice_id = self.common._find_device_on_array(volume, extra_specs)
        self.assertEqual(ref_device_id, founddevice_id)

    def test_find_host_lun_id_attached(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host = 'HostX'
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0]
                    ['host_lun_address'])
        ref_masked = {'hostlunid': int(host_lun, 16),
                      'maskingview': self.data.masking_view_name_f,
                      'array': self.data.array,
                      'device_id': self.data.device_id}
        maskedvols, __ = self.common.find_host_lun_id(
            volume, host, extra_specs)
        self.assertEqual(ref_masked, maskedvols)

    def test_find_host_lun_id_not_attached(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host = 'HostX'
        with mock.patch.object(self.rest, 'find_mv_connections_for_vol',
                               return_value=None):
            maskedvols, __ = self.common.find_host_lun_id(
                volume, host, extra_specs)
            self.assertEqual({}, maskedvols)

    @mock.patch.object(
        common.VMAXCommon, '_get_masking_views_from_volume',
        return_value=([], [VMAXCommonData.masking_view_name_f]))
    def test_find_host_lun_id_multiattach(self, mock_mask):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        __, is_multiattach = self.common.find_host_lun_id(
            volume, 'HostX', extra_specs)
        self.assertTrue(is_multiattach)

    @mock.patch.object(common.VMAXCommon, 'get_remote_target_device',
                       return_value=VMAXCommonData.device_id2)
    def test_find_host_lun_id_rep_extra_specs(self, mock_tgt):
        self.common.find_host_lun_id(
            self.data.test_volume, 'HostX',
            self.data.extra_specs, self.data.rep_extra_specs)
        mock_tgt.assert_called_once()

    def test_get_masking_views_from_volume(self):
        array = self.data.array
        device_id = self.data.device_id
        host = 'HostX'
        ref_mv_list = [self.data.masking_view_name_f]
        maskingview_list, __ = self.common.get_masking_views_from_volume(
            array, self.data.test_volume, device_id, host)
        self.assertEqual(ref_mv_list, maskingview_list)
        # is metro
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            __, is_metro = self.common.get_masking_views_from_volume(
                array, self.data.test_volume, device_id, host)
            self.assertTrue(is_metro)

    def test_get_masking_views_from_volume_wrong_host(self):
        array = self.data.array
        device_id = self.data.device_id
        host = 'DifferentHost'
        maskingview_list, __ = self.common.get_masking_views_from_volume(
            array, self.data.test_volume, device_id, host)
        self.assertEqual([], maskingview_list)

    def test_find_host_lun_id_no_host_check(self):
        volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        host_lun = (self.data.maskingview[0]['maskingViewConnection'][0]
                    ['host_lun_address'])
        ref_masked = {'hostlunid': int(host_lun, 16),
                      'maskingview': self.data.masking_view_name_f,
                      'array': self.data.array,
                      'device_id': self.data.device_id}
        maskedvols, __ = self.common.find_host_lun_id(
            volume, None, extra_specs)
        self.assertEqual(ref_masked, maskedvols)

    def test_initial_setup_success(self):
        volume = self.data.test_volume
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs = self.common._initial_setup(volume)
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_initial_setup_failed(self):
        volume = self.data.test_volume
        with mock.patch.object(
                self.common, 'get_attributes_from_cinder_config',
                return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._initial_setup, volume)

    @mock.patch.object(common.VMAXCommon, 'get_remote_target_device',
                       return_value=VMAXCommonData.device_id2)
    def test_populate_masking_dict(self, mock_tgt):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.WORKLOAD] = self.data.workload
        ref_mv_dict = self.data.masking_view_dict
        self.common.nextGen = False
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)
        # Metro volume, pass in rep_extra_specs and retrieve target device
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common._populate_masking_dict(
            volume, connector, extra_specs, rep_extra_specs)
        mock_tgt.assert_called_once()
        # device_id is None
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._populate_masking_dict,
                              volume, connector, extra_specs)

    def test_populate_masking_dict_no_slo(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = {
            'slo': None,
            'workload': None,
            'srp': self.data.srp,
            'array': self.data.array,
            utils.PORTGROUPNAME: self.data.port_group_name_f}
        ref_mv_dict = self.data.masking_view_dict_no_slo
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)

    def test_populate_masking_dict_compr_disabled(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.DISABLECOMPRESSION] = "true"
        ref_mv_dict = self.data.masking_view_dict_compression_disabled
        extra_specs[utils.WORKLOAD] = self.data.workload
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual(ref_mv_dict, masking_view_dict)

    def test_populate_masking_dict_next_gen(self):
        volume = self.data.test_volume
        connector = self.data.connector
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common.nextGen = True
        masking_view_dict = self.common._populate_masking_dict(
            volume, connector, extra_specs)
        self.assertEqual('NONE', masking_view_dict[utils.WORKLOAD])

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_is_snapshot(self):
        volume = self.data.test_snapshot
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        ref_dict = self.data.snap_location
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs, True, False)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_snapshot
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        clone_dict = self.common._create_cloned_volume(
            volume, source_volume, extra_specs, False, True)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_cloned_volume_not_licenced(self):
        volume = self.data.test_clone_volume
        source_volume = self.data.test_volume
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'is_snapvx_licensed',
                               return_value=False):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_cloned_volume,
                              volume, source_volume, extra_specs)

    def test_parse_snap_info_found(self):
        ref_device_id = self.data.device_id
        ref_snap_name = self.data.snap_location['snap_name']
        sourcedevice_id, foundsnap_name = self.common._parse_snap_info(
            self.data.array, self.data.test_snapshot)
        self.assertEqual(ref_device_id, sourcedevice_id)
        self.assertEqual(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_not_found(self):
        ref_snap_name = None
        with mock.patch.object(self.rest, 'get_volume_snap',
                               return_value=None):
            __, foundsnap_name = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(ref_snap_name, foundsnap_name)

    def test_parse_snap_info_exception(self):
        with mock.patch.object(
                self.rest, 'get_volume_snap',
                side_effect=exception.VolumeBackendAPIException):
            __, foundsnap_name = self.common._parse_snap_info(
                self.data.array, self.data.test_snapshot)
            self.assertIsNone(foundsnap_name)

    def test_parse_snap_info_provider_location_not_string(self):
        snapshot = fake_snapshot.fake_snapshot_obj(
            context='ctxt', provider_loaction={'not': 'string'})
        sourcedevice_id, foundsnap_name = self.common._parse_snap_info(
            self.data.array, snapshot)
        self.assertIsNone(foundsnap_name)

    def test_create_snapshot_success(self):
        array = self.data.array
        snapshot = self.data.test_snapshot
        source_device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        ref_dict = {'snap_name': self.data.test_snapshot_snap_name,
                    'source_id': self.data.device_id}
        snap_dict = self.common._create_snapshot(
            array, snapshot, source_device_id, extra_specs)
        self.assertEqual(ref_dict, snap_dict)

    def test_create_snapshot_exception(self):
        array = self.data.array
        snapshot = self.data.test_snapshot
        source_device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, 'create_volume_snapvx',
                side_effect=exception.VolumeBackendAPIException):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_snapshot,
                              array, snapshot, source_device_id, extra_specs)

    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    def test_delete_volume_from_srp(self, mock_rm):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_extra_specs = self.data.extra_specs_intervals_set
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_sync_check'):
            with mock.patch.object(self.common, '_delete_from_srp'):
                self.common._delete_volume(volume)
                self.common._delete_from_srp.assert_called_once_with(
                    array, device_id, volume_name, ref_extra_specs)

    def test_delete_volume_not_found(self):
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            with mock.patch.object(self.common, '_delete_from_srp'):
                self.common._delete_volume(volume)
                self.common._delete_from_srp.assert_not_called()

    def test_create_volume_success(self):
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        ref_dict = self.data.provider_location
        volume_dict = self.common._create_volume(
            volume_name, volume_size, extra_specs)
        self.assertEqual(ref_dict, volume_dict)

    def test_create_volume_success_next_gen(self):
        volume_name = '1'
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        self.common.nextGen = True
        with mock.patch.object(self.utils, 'is_compression_disabled',
                               return_value=True):
            with mock.patch.object(self.rest, 'is_next_gen_array',
                                   return_value=True):
                with mock.patch.object(self.masking,
                                       'get_or_create_default_storage_group'):
                    self.common._create_volume(
                        volume_name, volume_size, extra_specs)
                    (self.masking.get_or_create_default_storage_group
                        .assert_called_once_with(extra_specs['array'],
                                                 extra_specs[utils.SRP],
                                                 extra_specs[utils.SLO],
                                                 'NONE', extra_specs, True))

    def test_create_volume_failed(self):
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.masking,
                               'get_or_create_default_storage_group',
                               return_value=self.data.failed_resource):
            with mock.patch.object(self.rest, 'delete_storage_group'):
                # path 1: not last vol in sg
                with mock.patch.object(self.rest, 'get_num_vols_in_sg',
                                       return_value=2):
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.common._create_volume,
                                      volume_name, volume_size, extra_specs)
                    self.rest.delete_storage_group.assert_not_called()
                # path 2: last vol in sg, delete sg
                with mock.patch.object(self.rest, 'get_num_vols_in_sg',
                                       return_value=0):
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.common._create_volume,
                                      volume_name, volume_size, extra_specs)
                    (self.rest.delete_storage_group.
                     assert_called_once_with(self.data.array,
                                             self.data.failed_resource))

    def test_create_volume_incorrect_slo(self):
        volume_name = self.data.test_volume.name
        volume_size = self.data.test_volume.size
        extra_specs = {'slo': 'Diamondz',
                       'workload': 'DSSSS',
                       'srp': self.data.srp,
                       'array': self.data.array}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common._create_volume,
            volume_name, volume_size, extra_specs)

    def test_set_vmax_extra_specs(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_no_srp_name(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        with mock.patch.object(self.rest, 'get_slo_list',
                               return_value=[]):
            extra_specs = self.common._set_vmax_extra_specs({}, srp_record)
            self.assertIsNone(extra_specs['slo'])

    def test_set_vmax_extra_specs_compr_disabled(self):
        with mock.patch.object(self.rest, 'is_compression_capable',
                               return_value=True):
            srp_record = self.common.get_attributes_from_cinder_config()
            extra_specs = self.common._set_vmax_extra_specs(
                self.data.vol_type_extra_specs_compr_disabled, srp_record)
            ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
            ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
            ref_extra_specs[utils.DISABLECOMPRESSION] = "true"
            self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_compr_disabled_not_compr_capable(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs_compr_disabled, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual(ref_extra_specs, extra_specs)

    def test_set_vmax_extra_specs_portgroup_as_spec(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        extra_specs = self.common._set_vmax_extra_specs(
            {utils.PORTGROUPNAME: 'extra_spec_pg'}, srp_record)
        self.assertEqual('extra_spec_pg', extra_specs[utils.PORTGROUPNAME])

    def test_set_vmax_extra_specs_no_portgroup_set(self):
        srp_record = {'srpName': 'SRP_1',
                      'RestServerIp': '1.1.1.1',
                      'RestPassword': 'smc',
                      'SSLCert': None,
                      'RestServerPort': 8443,
                      'SSLVerify': False,
                      'RestUserName': 'smc',
                      'SerialNumber': '000197800123'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._set_vmax_extra_specs,
                          {}, srp_record)

    def test_set_vmax_extra_specs_next_gen(self):
        srp_record = self.common.get_attributes_from_cinder_config()
        self.common.nextGen = True
        extra_specs = self.common._set_vmax_extra_specs(
            self.data.vol_type_extra_specs, srp_record)
        ref_extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        ref_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.assertEqual('NONE', extra_specs[utils.WORKLOAD])

    def test_delete_volume_from_srp_success(self):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.provision, 'delete_volume_from_srp') as mock_del:
            self.common._delete_from_srp(array, device_id, volume_name,
                                         extra_specs)
            mock_del.assert_called_once_with(array, device_id, volume_name)

    def test_delete_volume_from_srp_failed(self):
        array = self.data.array
        device_id = self.data.failed_resource
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.masking,
                               'add_volume_to_default_storage_group'):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._delete_from_srp, array,
                              device_id, volume_name, extra_specs)
            (self.masking.add_volume_to_default_storage_group.
                assert_called_once_with(
                    array, device_id, volume_name, extra_specs))

    @mock.patch.object(utils.VMAXUtils, 'is_replication_enabled',
                       side_effect=[False, True])
    def test_remove_vol_and_cleanup_replication(self, mock_rep_enabled):
        array = self.data.array
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(
                self.masking, 'remove_and_reset_members') as mock_rm:
            with mock.patch.object(
                    self.common, 'cleanup_lun_replication') as mock_clean:
                self.common._remove_vol_and_cleanup_replication(
                    array, device_id, volume_name, extra_specs, volume)
                mock_rm.assert_called_once_with(
                    array, volume, device_id, volume_name, extra_specs, False)
                mock_clean.assert_not_called()
                self.common._remove_vol_and_cleanup_replication(
                    array, device_id, volume_name, extra_specs, volume)
                mock_clean.assert_called_once_with(
                    volume, volume_name, device_id, extra_specs)

    @mock.patch.object(utils.VMAXUtils, 'is_volume_failed_over',
                       side_effect=[True, False])
    @mock.patch.object(common.VMAXCommon, '_get_replication_extra_specs',
                       return_value=VMAXCommonData.rep_extra_specs)
    def test_get_target_wwns_from_masking_view(self, mock_rep_specs, mock_fo):
        ref_wwns = [self.data.wwnn1]
        for x in range(0, 2):
            target_wwns = self.common._get_target_wwns_from_masking_view(
                self.data.device_id, self.data.connector['host'],
                self.data.extra_specs)
            self.assertEqual(ref_wwns, target_wwns)

    def test_get_target_wwns_from_masking_view_no_mv(self):
        with mock.patch.object(self.common, '_get_masking_views_from_volume',
                               return_value=([], None)):
            target_wwns = self.common._get_target_wwns_from_masking_view(
                self.data.device_id, self.data.connector['host'],
                self.data.extra_specs)
            self.assertEqual([], target_wwns)

    @mock.patch.object(common.VMAXCommon, '_get_replication_extra_specs',
                       return_value=VMAXCommonData.rep_extra_specs)
    @mock.patch.object(common.VMAXCommon, 'get_remote_target_device',
                       return_value=(VMAXCommonData.device_id2,))
    @mock.patch.object(utils.VMAXUtils, 'is_metro_device',
                       side_effect=[False, True])
    def test_get_target_wwns(self, mock_metro, mock_tgt, mock_specs):
        __, metro_wwns = self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, self.data.connector)
        self.assertEqual([], metro_wwns)
        # Is metro volume
        __, metro_wwns = self.common.get_target_wwns_from_masking_view(
            self.data.test_volume, self.data.connector)
        self.assertEqual([self.data.wwnn1], metro_wwns)

    def test_get_port_group_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        with mock.patch.object(self.rest,
                               'get_element_from_masking_view'):
            self.common.get_port_group_from_masking_view(
                array, maskingview_name)
            self.rest.get_element_from_masking_view.assert_called_once_with(
                array, maskingview_name, portgroup=True)

    def test_get_initiator_group_from_masking_view(self):
        array = self.data.array
        maskingview_name = self.data.masking_view_name_f
        with mock.patch.object(self.rest,
                               'get_element_from_masking_view'):
            self.common.get_initiator_group_from_masking_view(
                array, maskingview_name)
            self.rest.get_element_from_masking_view.assert_called_once_with(
                array, maskingview_name, host=True)

    def test_get_common_masking_views(self):
        array = self.data.array
        portgroup_name = self.data.port_group_name_f
        initiator_group_name = self.data.initiatorgroup_name_f
        with mock.patch.object(self.rest, 'get_common_masking_views'):
            self.common.get_common_masking_views(
                array, portgroup_name, initiator_group_name)
            self.rest.get_common_masking_views.assert_called_once_with(
                array, portgroup_name, initiator_group_name)

    def test_get_ip_and_iqn(self):
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip}]
        port = self.data.portgroup[1]['symmetrixPortKey'][0]['portId']
        ip_iqn_list = self.common._get_ip_and_iqn(self.data.array, port)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    def test_find_ip_and_iqns(self):
        ref_ip_iqn = [{'iqn': self.data.initiator,
                       'ip': self.data.ip}]
        ip_iqn_list = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        self.assertEqual(ref_ip_iqn, ip_iqn_list)

    def test_create_replica_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        ref_dict = self.data.provider_location
        clone_dict = self.common._create_replica(
            array, clone_volume, source_device_id,
            self.data.extra_specs, snap_name)
        self.assertEqual(ref_dict, clone_dict)

    def test_create_replica_no_snap_name(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = "temp-" + source_device_id + "-snapshot_for_clone"
        ref_dict = self.data.provider_location
        with mock.patch.object(self.utils, 'get_temp_snap_name',
                               return_value=snap_name):
            clone_dict = self.common._create_replica(
                array, clone_volume, source_device_id,
                self.data.extra_specs)
            self.assertEqual(ref_dict, clone_dict)
            self.utils.get_temp_snap_name.assert_called_once_with(
                source_device_id)

    def test_create_replica_failed_cleanup_target(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        device_id = self.data.device_id
        snap_name = self.data.failed_resource
        clone_name = 'OS-' + clone_volume.id
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.common, '_cleanup_target'):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.common._create_replica, array, clone_volume,
                device_id, self.data.extra_specs, snap_name)
            self.common._cleanup_target.assert_called_once_with(
                array, device_id, device_id, clone_name,
                snap_name, extra_specs)

    def test_create_replica_failed_no_target(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        snap_name = self.data.failed_resource
        with mock.patch.object(self.common, '_create_volume',
                               return_value={'device_id': None}):
            with mock.patch.object(self.common, '_cleanup_target'):
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.common._create_replica, array, clone_volume,
                    source_device_id, self.data.extra_specs, snap_name)
                self.common._cleanup_target.assert_not_called()

    @mock.patch.object(
        masking.VMAXMasking,
        'remove_and_reset_members')
    def test_cleanup_target_sync_present(self, mock_remove):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.failed_resource
        clone_name = clone_volume.name
        extra_specs = self.data.extra_specs
        generation = 0
        with mock.patch.object(self.rest, 'get_sync_session',
                               return_value='session'):
            with mock.patch.object(self.provision,
                                   'break_replication_relationship'):
                self.common._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                (self.provision.break_replication_relationship.
                    assert_called_with(
                        array, target_device_id, source_device_id,
                        snap_name, extra_specs, generation))

    def test_cleanup_target_no_sync(self):
        array = self.data.array
        clone_volume = self.data.test_clone_volume
        source_device_id = self.data.device_id
        target_device_id = self.data.device_id2
        snap_name = self.data.failed_resource
        clone_name = clone_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'get_sync_session',
                               return_value=None):
            with mock.patch.object(self.common,
                                   '_delete_from_srp'):
                self.common._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                self.common._delete_from_srp.assert_called_once_with(
                    array, target_device_id, clone_name,
                    extra_specs)

    @mock.patch.object(
        provision.VMAXProvision,
        'delete_volume_snap')
    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_sync_check_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        snap_name = 'temp-1'
        generation = '0'
        with mock.patch.object(self.rest, 'get_volume_snap',
                               return_value=snap_name):
            self.common._sync_check(array, device_id, volume_name,
                                    extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, generation)
            mock_delete.assert_called_with(array, snap_name,
                                           device_id, restored=False,
                                           generation=generation)
        # Delete legacy temp snap
        mock_delete.reset_mock()
        snap_name2 = 'EMC_SMI_12345'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name2,
                     'target_vol_list': [], 'generation': 0}]
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            with mock.patch.object(self.rest, 'get_volume_snap',
                                   return_value=snap_name2):
                self.common._sync_check(array, device_id, volume_name,
                                        extra_specs)
                mock_delete.assert_called_once_with(
                    array, snap_name2, device_id, restored=False, generation=0)

    @mock.patch.object(
        provision.VMAXProvision,
        'delete_volume_snap')
    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_sync_check_not_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        snap_name = 'OS-1'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._sync_check(array, device_id, volume_name,
                                    extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, 0)
            mock_delete.assert_not_called()

    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_sync_check_no_sessions(self, mock_break):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=None):
            self.common._sync_check(array, device_id, volume_name,
                                    extra_specs)
            mock_break.assert_not_called()

    @mock.patch.object(
        provision.VMAXProvision,
        'delete_volume_snap')
    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_clone_check_cinder_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        snap_name = 'OS-1'
        sessions = [{'source_vol': device_id,
                     'snap_name': snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(True, False, None)):
            with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                                   return_value=sessions):
                self.common._clone_check(array, device_id, extra_specs)
                mock_delete.assert_not_called()
        mock_delete.reset_mock()
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, snap_name, extra_specs, 0)

    @mock.patch.object(
        provision.VMAXProvision,
        'delete_volume_snap')
    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_clone_check_temp_snap(self, mock_break, mock_delete):
        array = self.data.array
        device_id = self.data.device_id
        target = self.data.volume_details[1]['volumeId']
        extra_specs = self.data.extra_specs
        temp_snap_name = 'temp-' + device_id + '-' + 'snapshot_for_clone'
        sessions = [{'source_vol': device_id,
                     'snap_name': temp_snap_name, 'generation': 0,
                     'target_vol_list': [(target, "Copied")]}]
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=sessions):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_called_with(
                array, target, device_id, temp_snap_name, extra_specs, 0)
            mock_delete.asset_not_called()
        sessions1 = [{'source_vol': device_id,
                      'snap_name': temp_snap_name, 'generation': 0,
                      'target_vol_list': [(target, "CopyInProg")]}]
        mock_delete.reset_mock()
        mock_break.reset_mock()
        with mock.patch.object(self.rest, 'is_vol_in_rep_session',
                               return_value=(False, True, None)):
            with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                                   return_value=sessions1):
                self.common._clone_check(array, device_id, extra_specs)
                mock_break.assert_not_called()
                mock_delete.asset_not_called()

    @mock.patch.object(
        provision.VMAXProvision,
        'break_replication_relationship')
    def test_clone_check_no_sessions(self, mock_break):
        array = self.data.array
        device_id = self.data.device_id
        extra_specs = self.data.extra_specs
        with mock.patch.object(self.rest, 'find_snap_vx_sessions',
                               return_value=None):
            self.common._clone_check(array, device_id, extra_specs)
            mock_break.assert_not_called()

    def test_manage_existing_success(self):
        external_ref = {u'source-name': u'00002'}
        provider_location = {'device_id': u'00002', 'array': u'000197800123'}
        ref_update = {'provider_location': six.text_type(provider_location)}
        with mock.patch.object(
                self.common, '_check_lun_valid_for_cinder_management'):
            model_update = self.common.manage_existing(
                self.data.test_volume, external_ref)
            self.assertEqual(ref_update, model_update)

    @mock.patch.object(
        rest.VMAXRest, 'get_masking_views_from_storage_group',
        return_value=None)
    @mock.patch.object(
        rest.VMAXRest, 'is_vol_in_rep_session',
        return_value=(False, False, None))
    def test_check_lun_valid_for_cinder_management(self, mock_rep, mock_mv):
        external_ref = {u'source-name': u'00003'}
        self.common._check_lun_valid_for_cinder_management(
            self.data.array, self.data.device_id3,
            self.data.test_volume.id, external_ref)

    @mock.patch.object(
        rest.VMAXRest, 'get_volume',
        side_effect=[
            None,
            VMAXCommonData.volume_details[2],
            VMAXCommonData.volume_details[2],
            VMAXCommonData.volume_details[1]])
    @mock.patch.object(
        rest.VMAXRest, 'get_masking_views_from_storage_group',
        side_effect=[VMAXCommonData.sg_details[1]['maskingview'],
                     None])
    @mock.patch.object(rest.VMAXRest, 'get_storage_groups_from_volume',
                       return_value=[VMAXCommonData.defaultstoragegroup_name])
    @mock.patch.object(rest.VMAXRest, 'is_vol_in_rep_session',
                       side_effect=[(True, False, []), (False, False, None)])
    def test_check_lun_valid_for_cinder_management_exception(
            self, mock_rep, mock_sg, mock_mvs, mock_get_vol):
        external_ref = {u'source-name': u'00003'}
        for x in range(0, 3):
            self.assertRaises(
                exception.ManageExistingInvalidReference,
                self.common._check_lun_valid_for_cinder_management,
                self.data.array, self.data.device_id3,
                self.data.test_volume.id, external_ref)
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.common._check_lun_valid_for_cinder_management,
                          self.data.array, self.data.device_id3,
                          self.data.test_volume.id, external_ref)

    def test_manage_existing_get_size(self):
        external_ref = {u'source-name': u'00001'}
        size = self.common.manage_existing_get_size(
            self.data.test_volume, external_ref)
        self.assertEqual(2, size)

    def test_manage_existing_get_size_exception(self):
        external_ref = {u'source-name': u'00001'}
        with mock.patch.object(self.rest, 'get_size_of_device_on_array',
                               return_value=3.5):
            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.common.manage_existing_get_size,
                              self.data.test_volume, external_ref)

    @mock.patch.object(common.VMAXCommon,
                       '_remove_vol_and_cleanup_replication')
    def test_unmanage_success(self, mock_rm):
        volume = self.data.test_volume
        with mock.patch.object(self.rest, 'rename_volume'):
            self.common.unmanage(volume)
            self.rest.rename_volume.assert_called_once_with(
                self.data.array, self.data.device_id,
                self.data.test_volume.id)

    def test_unmanage_device_not_found(self):
        volume = self.data.test_volume
        with mock.patch.object(self.common, '_find_device_on_array',
                               return_value=None):
            with mock.patch.object(self.rest, 'rename_volume'):
                self.common.unmanage(volume)
                self.rest.rename_volume.assert_not_called()

    @mock.patch.object(common.VMAXCommon,
                       '_slo_workload_migration')
    def test_retype(self, mock_migrate):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs_intervals_set
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume = self.data.test_volume
        new_type = {'extra_specs': {}}
        host = {'host': self.data.new_host}
        self.common.retype(volume, new_type, host)
        mock_migrate.assert_called_once_with(
            device_id, volume, host, volume_name, new_type, extra_specs)
        mock_migrate.reset_mock()
        with mock.patch.object(
                self.common, '_find_device_on_array', return_value=None):
            self.common.retype(volume, new_type, host)
            mock_migrate.assert_not_called()
        mock_migrate.reset_mock()
        volume2 = self.data.test_attached_volume
        self.common.retype(volume2, new_type, host)
        mock_migrate.assert_not_called()

    def test_slo_workload_migration_valid(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
        volume = self.data.test_volume
        host = {'host': self.data.new_host}
        with mock.patch.object(self.common, '_migrate_volume'):
            self.common._slo_workload_migration(
                device_id, volume, host, volume_name, new_type, extra_specs)
            self.common._migrate_volume.assert_called_once_with(
                extra_specs[utils.ARRAY], volume, device_id,
                extra_specs[utils.SRP], 'Silver',
                'OLTP', volume_name, new_type, extra_specs)

    def test_slo_workload_migration_not_valid(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        new_type = {'extra_specs': {}}
        host = {'host': self.data.new_host}
        with mock.patch.object(self.common,
                               '_is_valid_for_storage_assisted_migration',
                               return_value=(False, 'Silver', 'OLTP')):
            migrate_status = self.common._slo_workload_migration(
                device_id, volume, host, volume_name, new_type, extra_specs)
            self.assertFalse(migrate_status)

    def test_slo_workload_migration_same_hosts(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        host = {'host': self.data.fake_host}
        new_type = {'extra_specs': {}}
        migrate_status = self.common._slo_workload_migration(
            device_id, volume, host, volume_name, new_type, extra_specs)
        self.assertFalse(migrate_status)

    def test_slo_workload_migration_same_host_change_compression(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        volume = self.data.test_volume
        host = {'host': self.data.fake_host}
        new_type = {'extra_specs': {utils.DISABLECOMPRESSION: "true"}}
        with mock.patch.object(
                self.common, '_is_valid_for_storage_assisted_migration',
                return_value=(True, self.data.slo, self.data.workload)):
            with mock.patch.object(self.common, '_migrate_volume'):
                migrate_status = self.common._slo_workload_migration(
                    device_id, volume, host, volume_name, new_type,
                    extra_specs)
                self.assertTrue(bool(migrate_status))
                self.common._migrate_volume.assert_called_once_with(
                    extra_specs[utils.ARRAY], volume, device_id,
                    extra_specs[utils.SRP], self.data.slo,
                    self.data.workload, volume_name, new_type, extra_specs)

    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_migrate_volume_success(self, mock_remove):
        with mock.patch.object(self.rest, 'is_volume_in_storagegroup',
                               return_value=True):
            device_id = self.data.device_id
            volume_name = self.data.test_volume.name
            extra_specs = self.data.extra_specs
            volume = self.data.test_volume
            new_type = {'extra_specs': {}}
            migrate_status = self.common._migrate_volume(
                self.data.array, volume, device_id, self.data.srp,
                self.data.slo, self.data.workload, volume_name,
                new_type, extra_specs)[0]
            self.assertTrue(migrate_status)
            target_extra_specs = {
                'array': self.data.array, 'interval': 3,
                'retries': 120, 'slo': self.data.slo,
                'srp': self.data.srp, 'workload': self.data.workload}
            mock_remove.assert_called_once_with(
                self.data.array, volume, device_id, volume_name,
                target_extra_specs, reset=True)
            mock_remove.reset_mock()
            with mock.patch.object(
                    self.rest, 'get_storage_groups_from_volume',
                    return_value=[]):
                migrate_status = self.common._migrate_volume(
                    self.data.array, volume, device_id, self.data.srp,
                    self.data.slo, self.data.workload, volume_name,
                    new_type, extra_specs)[0]
                self.assertTrue(migrate_status)
                mock_remove.assert_not_called()

    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_migrate_volume_failed_get_new_sg_failed(self, mock_remove):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
        with mock.patch.object(
                self.masking, 'get_or_create_default_storage_group',
                side_effect=exception.VolumeBackendAPIException):
            migrate_status = self.common._migrate_volume(
                self.data.array, self.data.test_volume, device_id,
                self.data.srp, self.data.slo,
                self.data.workload, volume_name, new_type, extra_specs)
            self.assertFalse(migrate_status)

    def test_migrate_volume_failed_vol_not_added(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = self.data.extra_specs
        new_type = {'extra_specs': {}}
        with mock.patch.object(
                self.rest, 'is_volume_in_storagegroup',
                return_value=False):
            migrate_status = self.common._migrate_volume(
                self.data.array, self.data.test_volume, device_id,
                self.data.srp, self.data.slo,
                self.data.workload, volume_name, new_type, extra_specs)[0]
            self.assertFalse(migrate_status)

    def test_is_valid_for_storage_assisted_migration_true(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'OLTP')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # No current sgs found
        with mock.patch.object(self.rest, 'get_storage_groups_from_volume',
                               return_value=None):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array, self.data.srp,
                volume_name, False, False)
            self.assertEqual(ref_return, return_val)
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123'}
        ref_return = (True, 'Silver', 'NONE')
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_false(self):
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        ref_return = (False, None, None)
        # IndexError
        host = {'host': 'HostX@Backend#Silver+SRP_1+000197800123+dummy+data'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Wrong array
        host2 = {'host': 'HostX@Backend#Silver+OLTP+SRP_1+00012345678'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host2, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Wrong srp
        host3 = {'host': 'HostX@Backend#Silver+OLTP+SRP_2+000197800123'}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host3, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)
        # Already in correct sg
        host4 = {'host': self.data.fake_host}
        return_val = self.common._is_valid_for_storage_assisted_migration(
            device_id, host4, self.data.array,
            self.data.srp, volume_name, False, False)
        self.assertEqual(ref_return, return_val)

    def test_is_valid_for_storage_assisted_migration_next_gen(self):
        device_id = self.data.device_id
        host = {'host': self.data.new_host}
        volume_name = self.data.test_volume.name
        ref_return = (True, 'Silver', 'NONE')
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            return_val = self.common._is_valid_for_storage_assisted_migration(
                device_id, host, self.data.array,
                self.data.srp, volume_name, False, False)
            self.assertEqual(ref_return, return_val)

    def test_find_volume_group(self):
        group = self.data.test_group_1
        array = self.data.array
        volume_group = self.common._find_volume_group(array, group)
        ref_group = self.data.sg_details_rep[0]
        self.assertEqual(ref_group, volume_group)

    def test_get_volume_device_ids(self):
        array = self.data.array
        volumes = [self.data.test_volume]
        ref_device_ids = [self.data.device_id]
        device_ids = self.common._get_volume_device_ids(volumes, array)
        self.assertEqual(ref_device_ids, device_ids)

    def test_get_members_of_volume_group(self):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        ref_volumes = [self.data.device_id, self.data.device_id2]
        member_device_ids = self.common._get_members_of_volume_group(
            array, group_name)
        self.assertEqual(ref_volumes, member_device_ids)

    def test_get_members_of_volume_group_empty(self):
        array = self.data.array
        group_name = self.data.storagegroup_name_source
        with mock.patch.object(
                self.rest, 'get_volumes_in_storage_group',
                return_value=None):
            member_device_ids = self.common._get_members_of_volume_group(
                array, group_name
            )
        self.assertIsNone(member_device_ids)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_create_group_replica(self, mock_check):
        source_group = self.data.test_group_1
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                self.common,
                '_create_group_replica') as mock_create_replica:
            self.common._create_group_replica(
                source_group, snap_name)
            mock_create_replica.assert_called_once_with(
                source_group, snap_name)

    def test_create_group_replica_exception(self):
        source_group = self.data.test_group_failed
        snap_name = self.data.group_snapshot_name
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common._create_group_replica,
                              source_group,
                              snap_name)

    def test_create_group_snapshot(self):
        context = None
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            model_update, snapshots_model_update = (
                self.common.create_group_snapshot(
                    context, group_snapshot, snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_create_group_snapshot_exception(self):
        context = None
        group_snapshot = self.data.test_group_snapshot_failed
        snapshots = []
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.create_group_snapshot,
                              context,
                              group_snapshot,
                              snapshots)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_create_group(self, mock_type, mock_cg_type):
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(provision.VMAXProvision, 'create_volume_group',
                       side_effect=exception.CinderException)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_create_group_exception(self, mock_type, mock_create):
        context = None
        group = self.data.test_group_failed
        with mock.patch.object(
                volume_utils, 'is_group_a_cg_snapshot_type',
                return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.create_group,
                              context, group)

    def test_delete_group_snapshot(self):
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        context = None
        ref_model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common.delete_group_snapshot(context,
                                                  group_snapshot, snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_delete_group_snapshot_success(self):
        group_snapshot = self.data.test_group_snapshot_1
        snapshots = []
        ref_model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common._delete_group_snapshot(group_snapshot,
                                                   snapshots))
            self.assertEqual(ref_model_update, model_update)

    def test_delete_group_snapshot_failed(self):
        group_snapshot = self.data.test_group_snapshot_failed
        snapshots = []
        ref_model_update = (
            {'status': fields.GroupSnapshotStatus.ERROR_DELETING})
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, snapshots_model_update = (
                self.common._delete_group_snapshot(group_snapshot,
                                                   snapshots))
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group(self, mock_cg_type, mock_type_check):
        group = self.data.test_group_1
        add_vols = [self.data.test_volume]
        remove_vols = []
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update, __, __ = self.common.update_group(group,
                                                        add_vols,
                                                        remove_vols)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.VMAXCommon, '_find_volume_group',
                       return_value=None)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_not_found(self, mock_check, mock_grp):
        self.assertRaises(exception.GroupNotFound, self.common.update_group,
                          self.data.test_group_1, [], [])

    @mock.patch.object(common.VMAXCommon, '_find_volume_group',
                       side_effect=exception.VolumeBackendAPIException)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_group_exception(self, mock_check, mock_grp):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.update_group,
                          self.data.test_group_1, [], [])

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group(self, mock_check):
        group = self.data.test_group_1
        volumes = [self.data.test_volume]
        context = None
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True),\
                mock.patch.object(self.rest, 'get_volumes_in_storage_group',
                                  return_value=[]):
            model_update, __ = self.common.delete_group(
                context, group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_delete_group_success(self, mock_check):
        group = self.data.test_group_1
        volumes = []
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True),\
                mock.patch.object(self.rest, 'get_volumes_in_storage_group',
                                  return_value=[]):
            model_update, __ = self.common._delete_group(group, volumes)
            self.assertEqual(ref_model_update, model_update)

    def test_delete_group_already_deleted(self):
        group = self.data.test_group_failed
        ref_model_update = {'status': fields.GroupStatus.DELETED}
        volumes = []
        with mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                               return_value=True):
            model_update, __ = self.common._delete_group(group, volumes)
            self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_delete_group_failed(self, mock_check, mock_type_check):
        group = self.data.test_group_1
        volumes = []
        ref_model_update = {'status': fields.GroupStatus.ERROR_DELETING}
        with mock.patch.object(
                self.rest, 'delete_storage_group',
                side_effect=exception.VolumeBackendAPIException):
            model_update, __ = self.common._delete_group(
                group, volumes)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        common.VMAXCommon, '_get_clone_vol_info',
        return_value=(VMAXCommonData.device_id,
                      VMAXCommonData.extra_specs, 1, 'tgt_vol'))
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type',
                       return_value=False)
    def test_create_group_from_src_success(self, mock_type,
                                           mock_cg_type, mock_info):
        ref_model_update = {'status': fields.GroupStatus.AVAILABLE}
        model_update, volumes_model_update = (
            self.common.create_group_from_src(
                None, self.data.test_group_1, [self.data.test_volume],
                self.data.test_group_snapshot_1, [], None, []))
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        common.VMAXCommon, '_remove_vol_and_cleanup_replication')
    @mock.patch.object(
        masking.VMAXMasking, 'remove_volumes_from_storage_group')
    def test_rollback_create_group_from_src(
            self, mock_rm, mock_clean):
        rollback_dict = {
            'target_group_name': self.data.target_group_name,
            'snap_name': 'snap1', 'source_group_name': 'src_grp',
            'volumes': (self.data.device_id, self.data.extra_specs,
                        self.data.test_volume),
            'device_ids': [self.data.device_id],
            'interval_retries_dict': self.data.extra_specs}
        for x in range(0, 2):
            self.common._rollback_create_group_from_src(
                self.data.array, rollback_dict)
        self.assertEqual(2, mock_rm.call_count)

    def test_get_snap_src_dev_list(self):
        src_dev_ids = self.common._get_snap_src_dev_list(
            self.data.array, [self.data.test_snapshot])
        ref_dev_ids = [self.data.device_id]
        self.assertEqual(ref_dev_ids, src_dev_ids)

    def test_get_clone_vol_info(self):
        ref_dev_id = self.data.device_id
        source_vols = [self.data.test_volume,
                       self.data.test_attached_volume]
        src_snapshots = [self.data.test_snapshot]
        src_dev_id1, extra_specs1, vol_size1, tgt_vol_name1 = (
            self.common._get_clone_vol_info(
                self.data.test_clone_volume, source_vols, []))
        src_dev_id2, extra_specs2, vol_size2, tgt_vol_name2 = (
            self.common._get_clone_vol_info(
                self.data.test_clone_volume, [], src_snapshots))
        self.assertEqual(ref_dev_id, src_dev_id1)
        self.assertEqual(ref_dev_id, src_dev_id2)

    def test_get_attributes_from_cinder_config_new_and_old(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1',
             'RestServerPort': 8443,
             'RestUserName': 'smc',
             'RestPassword': 'smc',
             'SSLVerify': False,
             'SerialNumber': self.data.array,
             'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        old_conf = FakeConfiguration(None, 'CommonTests', 1, 1)
        configuration = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)
        self.common.configuration = old_conf
        kwargs = self.common.get_attributes_from_cinder_config()
        self.assertIsNone(kwargs)

    def test_get_attributes_from_cinder_config_with_port_override_old(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1',
             'RestServerPort': 3448,
             'RestUserName': 'smc',
             'RestPassword': 'smc',
             'SSLVerify': False,
             'SerialNumber': self.data.array,
             'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_rest_port=3448, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_attributes_from_cinder_config_with_port_override_new(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1',
             'RestServerPort': 3448,
             'RestUserName': 'smc',
             'RestPassword': 'smc',
             'SSLVerify': False,
             'SerialNumber': self.data.array,
             'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=3448, vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_attributes_from_cinder_config_no_port(self):
        kwargs_expected = (
            {'RestServerIp': '1.1.1.1',
             'RestServerPort': 8443,
             'RestUserName': 'smc',
             'RestPassword': 'smc',
             'SSLVerify': False,
             'SerialNumber': self.data.array,
             'srpName': 'SRP_1',
             'PortGroup': self.data.port_group_name_i})
        configuration = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            vmax_port_groups=[self.data.port_group_name_i])
        self.common.configuration = configuration
        kwargs_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual(kwargs_expected, kwargs_returned)

    def test_get_ssl_attributes_from_cinder_config(self):
        conf = FakeConfiguration(
            None, 'CommonTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            vmax_port_groups=[self.data.port_group_name_i],
            driver_ssl_cert_verify=True,
            driver_ssl_cert_path='/path/to/cert')

        self.common.configuration = conf
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertEqual('/path/to/cert', conf_returned['SSLVerify'])

        conf.driver_ssl_cert_verify = True
        conf.driver_ssl_cert_path = None
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertTrue(conf_returned['SSLVerify'])

        conf.driver_ssl_cert_verify = False
        conf.driver_ssl_cert_path = None
        conf_returned = self.common.get_attributes_from_cinder_config()
        self.assertFalse(conf_returned['SSLVerify'])

    @mock.patch.object(rest.VMAXRest,
                       'get_size_of_device_on_array',
                       return_value=2.0)
    def test_manage_snapshot_get_size_success(self, mock_get_size):
        size = self.common.manage_existing_snapshot_get_size(
            self.data.test_snapshot)
        self.assertEqual(2, size)

    @mock.patch.object(rest.VMAXRest, 'get_volume_snap',
                       return_value={'snap_name': 'snap_name'})
    def test_manage_snapshot_success(self, mock_snap):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        updates_response = self.common.manage_existing_snapshot(
            snapshot, existing_ref)

        prov_loc = {'source_id': self.data.device_id,
                    'snap_name': 'OS-%s' % existing_ref['source-name']}

        updates = {
            'display_name': self.data.test_snapshot_manage.display_name,
            'provider_location': six.text_type(prov_loc)}

        self.assertEqual(updates_response, updates)

    def test_manage_snapshot_fail_already_managed(self):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'OS-test_snap'}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(utils.VMAXUtils,
                       'is_volume_failed_over',
                       return_value=True)
    def test_manage_snapshot_fail_vol_failed_over(self, mock_failed):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(rest.VMAXRest, 'get_volume_snap', return_value=False)
    def test_manage_snapshot_fail_vol_not_snap_src(self, mock_snap):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(utils.VMAXUtils, 'modify_snapshot_prefix',
                       side_effect=exception.VolumeBackendAPIException)
    def test_manage_snapshot_fail_add_prefix(self, mock_mod):
        snapshot = self.data.test_snapshot_manage
        existing_ref = {u'source-name': u'test_snap'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing_snapshot,
                          snapshot, existing_ref)

    @mock.patch.object(common.VMAXCommon, '_sync_check')
    @mock.patch.object(rest.VMAXRest, 'modify_volume_snap')
    def test_unmanage_snapshot_success(self, mock_mod, mock_sync):
        self.common.unmanage_snapshot(self.data.test_snapshot_manage)
        mock_mod.assert_called_once()

    @mock.patch.object(
        utils.VMAXUtils, 'is_volume_failed_over', return_value=True)
    def test_unmanage_snapshot_fail_failover(self, mock_failed):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.unmanage_snapshot,
                          self.data.test_snapshot_manage)

    @mock.patch.object(rest.VMAXRest,
                       'modify_volume_snap',
                       side_effect=exception.VolumeBackendAPIException)
    def test_unmanage_snapshot_fail_rename(self, mock_snap):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.unmanage_snapshot,
                          self.data.test_snapshot_manage)

    @mock.patch.object(provision.VMAXProvision, 'is_restore_complete',
                       return_value=True)
    @mock.patch.object(common.VMAXCommon, '_sync_check')
    @mock.patch.object(provision.VMAXProvision,
                       'revert_volume_snapshot')
    def test_revert_to_snapshot(self, mock_revert, mock_sync, mock_complete):
        volume = self.data.test_volume
        snapshot = self.data.test_snapshot
        array = self.data.array
        device_id = self.data.device_id
        snap_name = self.data.snap_location['snap_name']
        extra_specs = deepcopy(self.data.extra_specs_intervals_set)
        extra_specs['storagetype:portgroupname'] = (
            self.data.port_group_name_f)
        self.common.revert_to_snapshot(volume, snapshot)
        mock_revert.assert_called_once_with(
            array, device_id, snap_name, extra_specs)

    @mock.patch.object(utils.VMAXUtils, 'is_replication_enabled',
                       return_value=True)
    def test_revert_to_snapshot_replicated(self, mock_rep):
        volume = self.data.test_volume
        snapshot = self.data.test_snapshot
        self.assertRaises(exception.VolumeDriverException,
                          self.common.revert_to_snapshot, volume, snapshot)

    def test_get_initiator_check_flag(self):
        self.common.configuration.initiator_check = False
        initiator_check = self.common._get_initiator_check_flag()
        self.assertFalse(initiator_check)

    def test_get_initiator_check_flag_true(self):
        self.common.configuration.initiator_check = True
        initiator_check = self.common._get_initiator_check_flag()
        self.assertTrue(initiator_check)

    def test_get_manageable_volumes_success(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_single):
            vols_lists = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-id': '00001'}, 'safe_to_manage': True,
                 'size': 1.0, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_volumes_filters_set(self):
        marker, limit, offset = '00002', 2, 1
        sort_keys, sort_dirs = 'size', 'desc'
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi):
            vols_lists = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-id': '00003'}, 'safe_to_manage': True,
                 'size': 300, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}},
                {'reference': {'source-id': '00004'}, 'safe_to_manage': True,
                 'size': 400, 'reason_not_safe': None, 'cinder_id': None,
                 'extra_info': {'config': 'TDEV', 'emulation': 'FBA'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_volumes_fail_no_vols(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=[]):
            expected_response = []
            vol_list = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vol_list, expected_response)

    def test_get_manageable_volumes_fail_no_valid_vols(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi_invalid):
            expected_response = []
            vol_list = self.common.get_manageable_volumes(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vol_list, expected_response)

    def test_get_manageable_snapshots_success(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_single):
            snap_list = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [{
                'reference': {'source-name': 'testSnap1'},
                'safe_to_manage': True, 'size': 1,
                'reason_not_safe': None, 'cinder_id': None,
                'extra_info': {
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY},
                'source_reference': {'source-id': '00001'}}]
            self.assertEqual(snap_list, expected_response)

    def test_get_manageable_snapshots_filters_set(self):
        marker, limit, offset = 'testSnap2', 2, 1
        sort_keys, sort_dirs = 'size', 'desc'
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi):
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            expected_response = [
                {'reference': {'source-name': 'testSnap3'},
                 'safe_to_manage': True, 'size': 300, 'reason_not_safe': None,
                 'cinder_id': None, 'extra_info': {
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY},
                 'source_reference': {'source-id': '00003'}},
                {'reference': {'source-name': 'testSnap4'},
                 'safe_to_manage': True, 'size': 400, 'reason_not_safe': None,
                 'cinder_id': None, 'extra_info': {
                    'generation': 0, 'secured': False, 'timeToLive': 'N/A',
                    'timestamp': mock.ANY},
                 'source_reference': {'source-id': '00004'}}]
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_snapshots_fail_no_snaps(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=[]):
            expected_response = []
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vols_lists, expected_response)

    def test_get_manageable_snapshots_fail_no_valid_snaps(self):
        marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(
                self.rest, 'get_private_volume_list',
                return_value=self.data.priv_vol_func_response_multi_invalid):
            expected_response = []
            vols_lists = self.common.get_manageable_snapshots(
                marker, limit, offset, sort_keys, sort_dirs)
            self.assertEqual(vols_lists, expected_response)

    def test_get_slo_workload_combo_from_cinder_conf(self):
        self.common.configuration.vmax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = 'DSS'
        response1 = self.common.get_attributes_from_cinder_config()
        self.assertEqual('Diamond', response1['ServiceLevel'])
        self.assertEqual('DSS', response1['Workload'])

        self.common.configuration.vmax_service_level = 'Diamond'
        self.common.configuration.vmax_workload = None
        response2 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(self.common.configuration.vmax_service_level,
                         response2['ServiceLevel'])
        self.assertIsNone(response2['Workload'])

        expected_response = {
            'RestServerIp': '1.1.1.1',
            'RestServerPort': 8443,
            'RestUserName': 'smc',
            'RestPassword': 'smc',
            'SSLVerify': False,
            'SerialNumber': '000197800123',
            'srpName': 'SRP_1',
            'PortGroup': 'OS-fibre-PG'}

        self.common.configuration.vmax_service_level = None
        self.common.configuration.vmax_workload = 'DSS'
        response3 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(expected_response, response3)

        self.common.configuration.vmax_service_level = None
        self.common.configuration.vmax_workload = None
        response4 = self.common.get_attributes_from_cinder_config()
        self.assertEqual(expected_response, response4)


class VMAXFCTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXFCTest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        self.configuration = FakeConfiguration(
            None, 'FCTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = fc.VMAXFCDriver(configuration=self.configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))

    def test_create_volume(self):
        with mock.patch.object(self.common, 'create_volume'):
            self.driver.create_volume(self.data.test_volume)
            self.common.create_volume.assert_called_once_with(
                self.data.test_volume)

    def test_create_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        snapshot = self.data.test_snapshot
        with mock.patch.object(self.common, 'create_volume_from_snapshot'):
            self.driver.create_volume_from_snapshot(volume, snapshot)
            self.common.create_volume_from_snapshot.assert_called_once_with(
                volume, snapshot)

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        src_volume = self.data.test_volume
        with mock.patch.object(self.common, 'create_cloned_volume'):
            self.driver.create_cloned_volume(volume, src_volume)
            self.common.create_cloned_volume.assert_called_once_with(
                volume, src_volume)

    def test_delete_volume(self):
        with mock.patch.object(self.common, 'delete_volume'):
            self.driver.delete_volume(self.data.test_volume)
            self.common.delete_volume.assert_called_once_with(
                self.data.test_volume)

    def test_create_snapshot(self):
        with mock.patch.object(self.common, 'create_snapshot'):
            self.driver.create_snapshot(self.data.test_snapshot)
            self.common.create_snapshot.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_delete_snapshot(self):
        with mock.patch.object(self.common, 'delete_snapshot'):
            self.driver.delete_snapshot(self.data.test_snapshot)
            self.common.delete_snapshot.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_initialize_connection(self):
        with mock.patch.object(self.common, 'initialize_connection',
                               return_value=self.data.fc_device_info):
            with mock.patch.object(self.driver, 'populate_data'):
                self.driver.initialize_connection(self.data.test_volume,
                                                  self.data.connector)
                self.common.initialize_connection.assert_called_once_with(
                    self.data.test_volume, self.data.connector)
                self.driver.populate_data.assert_called_once_with(
                    self.data.fc_device_info, self.data.test_volume,
                    self.data.connector)

    def test_populate_data(self):
        with mock.patch.object(self.driver, '_build_initiator_target_map',
                               return_value=([], {})):
            ref_data = {
                'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': self.data.fc_device_info['hostlunid'],
                         'target_discovered': True,
                         'target_wwn': [],
                         'initiator_target_map': {}}}
            data = self.driver.populate_data(self.data.fc_device_info,
                                             self.data.test_volume,
                                             self.data.connector)
            self.assertEqual(ref_data, data)
            self.driver._build_initiator_target_map.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_terminate_connection(self):
        with mock.patch.object(self.common, 'terminate_connection'):
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
            self.common.terminate_connection.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_terminate_connection_no_zoning_mappings(self):
        with mock.patch.object(self.driver, '_get_zoning_mappings',
                               return_value=None):
            with mock.patch.object(self.common, 'terminate_connection'):
                self.driver.terminate_connection(self.data.test_volume,
                                                 self.data.connector)
                self.common.terminate_connection.assert_not_called()

    def test_get_zoning_mappings(self):
        ref_mappings = self.data.zoning_mappings
        zoning_mappings = self.driver._get_zoning_mappings(
            self.data.test_volume, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings)
        # Legacy vol
        zoning_mappings2 = self.driver._get_zoning_mappings(
            self.data.test_legacy_vol, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings2)

    def test_get_zoning_mappings_no_mv(self):
        with mock.patch.object(self.common, 'get_masking_views_from_volume',
                               return_value=(None, False)):
            zoning_mappings = self.driver._get_zoning_mappings(
                self.data.test_volume, self.data.connector)
            self.assertEqual({}, zoning_mappings)

    @mock.patch.object(
        common.VMAXCommon, 'get_masking_views_from_volume',
        return_value=([VMAXCommonData.masking_view_name_f], True))
    def test_get_zoning_mappings_metro(self, mock_mv):
        ref_mappings = self.data.zoning_mappings_metro
        zoning_mappings = self.driver._get_zoning_mappings(
            self.data.test_volume, self.data.connector)
        self.assertEqual(ref_mappings, zoning_mappings)

    def test_cleanup_zones_other_vols_mapped(self):
        ref_data = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        data = self.driver._cleanup_zones(self.data.zoning_mappings)
        self.assertEqual(ref_data, data)

    def test_cleanup_zones_no_vols_mapped(self):
        zoning_mappings = self.data.zoning_mappings
        ref_data = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': zoning_mappings['target_wwns'],
                             'initiator_target_map':
                                 zoning_mappings['init_targ_map']}}
        with mock.patch.object(self.common, 'get_common_masking_views',
                               return_value=[]):
            data = self.driver._cleanup_zones(self.data.zoning_mappings)
            self.assertEqual(ref_data, data)

    def test_build_initiator_target_map(self):
        ref_target_map = {'123456789012345': ['543210987654321'],
                          '123456789054321': ['123450987654321']}
        with mock.patch.object(fczm_utils, 'create_lookup_service',
                               return_value=FakeLookupService()):
            driver = fc.VMAXFCDriver(configuration=self.configuration)
            with mock.patch.object(driver.common,
                                   'get_target_wwns_from_masking_view',
                                   return_value=(self.data.target_wwns, [])):
                targets, target_map = driver._build_initiator_target_map(
                    self.data.test_volume, self.data.connector)
                self.assertEqual(ref_target_map, target_map)

    def test_extend_volume(self):
        with mock.patch.object(self.common, 'extend_volume'):
            self.driver.extend_volume(self.data.test_volume, '3')
            self.common.extend_volume.assert_called_once_with(
                self.data.test_volume, '3')

    def test_get_volume_stats(self):
        with mock.patch.object(self.driver, 'update_volume_stats'):
            # no refresh
            self.driver.get_volume_stats()
            self.driver.update_volume_stats.assert_not_called()
            # with refresh
            self.driver.get_volume_stats(True)
            self.driver.update_volume_stats.assert_called_once_with()

    def test_update_volume_stats(self):
        with mock.patch.object(self.common, 'update_volume_stats',
                               return_value={}):
            self.driver.update_volume_stats()
            self.common.update_volume_stats.assert_called_once_with()

    def test_check_for_setup_error(self):
        self.driver.check_for_setup_error()

    def test_ensure_export(self):
        self.driver.ensure_export('context', 'volume')

    def test_create_export(self):
        self.driver.create_export('context', 'volume', 'connector')

    def test_remove_export(self):
        self.driver.remove_export('context', 'volume')

    def test_check_for_export(self):
        self.driver.check_for_export('context', 'volume_id')

    def test_manage_existing(self):
        with mock.patch.object(self.common, 'manage_existing',
                               return_value={}):
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing(self.data.test_volume, external_ref)
            self.common.manage_existing.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_manage_existing_get_size(self):
        with mock.patch.object(self.common, 'manage_existing_get_size',
                               return_value='1'):
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_get_size(
                self.data.test_volume, external_ref)
            self.common.manage_existing_get_size.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_unmanage_volume(self):
        with mock.patch.object(self.common, 'unmanage',
                               return_value={}):
            self.driver.unmanage(self.data.test_volume)
            self.common.unmanage.assert_called_once_with(
                self.data.test_volume)

    def test_retype(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(self.common, 'retype',
                               return_value=True):
            self.driver.retype({}, self.data.test_volume, new_type, '', host)
            self.common.retype.assert_called_once_with(
                self.data.test_volume, new_type, host)

    def test_failover_host(self):
        with mock.patch.object(
                self.common, 'failover_host',
                return_value=(self.data.remote_array, [], [])) as mock_fo:
            self.driver.failover_host(self.data.ctx, [self.data.test_volume])
            mock_fo.assert_called_once_with([self.data.test_volume], None,
                                            None)

    def test_enable_replication(self):
        with mock.patch.object(
                self.common, 'enable_replication') as mock_er:
            self.driver.enable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_er.assert_called_once()

    def test_disable_replication(self):
        with mock.patch.object(
                self.common, 'disable_replication') as mock_dr:
            self.driver.disable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_dr.assert_called_once()

    def test_failover_replication(self):
        with mock.patch.object(
                self.common, 'failover_replication') as mock_fo:
            self.driver.failover_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_fo.assert_called_once()


class VMAXISCSITest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXISCSITest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = FakeConfiguration(
            None, 'ISCSITests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_api_port=8443, vmax_port_groups=[self.data.port_group_name_i])
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = iscsi.VMAXISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))

    def test_create_volume(self):
        with mock.patch.object(self.common, 'create_volume'):
            self.driver.create_volume(self.data.test_volume)
            self.common.create_volume.assert_called_once_with(
                self.data.test_volume)

    def test_create_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        snapshot = self.data.test_snapshot
        with mock.patch.object(self.common, 'create_volume_from_snapshot'):
            self.driver.create_volume_from_snapshot(volume, snapshot)
            self.common.create_volume_from_snapshot.assert_called_once_with(
                volume, snapshot)

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        src_volume = self.data.test_volume
        with mock.patch.object(self.common, 'create_cloned_volume'):
            self.driver.create_cloned_volume(volume, src_volume)
            self.common.create_cloned_volume.assert_called_once_with(
                volume, src_volume)

    def test_delete_volume(self):
        with mock.patch.object(self.common, 'delete_volume'):
            self.driver.delete_volume(self.data.test_volume)
            self.common.delete_volume.assert_called_once_with(
                self.data.test_volume)

    def test_create_snapshot(self):
        with mock.patch.object(self.common, 'create_snapshot'):
            self.driver.create_snapshot(self.data.test_snapshot)
            self.common.create_snapshot.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_delete_snapshot(self):
        with mock.patch.object(self.common, 'delete_snapshot'):
            self.driver.delete_snapshot(self.data.test_snapshot)
            self.common.delete_snapshot.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_initialize_connection(self):
        ref_dict = {'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array,
                    'hostlunid': 3,
                    'device_id': self.data.device_id,
                    'ip_and_iqn': [{'ip': self.data.ip,
                                    'iqn': self.data.initiator}],
                    'is_multipath': False}
        with mock.patch.object(self.driver, 'get_iscsi_dict'):
            with mock.patch.object(
                self.common, 'get_port_group_from_masking_view',
                    return_value=self.data.port_group_name_i):
                self.driver.initialize_connection(self.data.test_volume,
                                                  self.data.connector)
                self.driver.get_iscsi_dict.assert_called_once_with(
                    ref_dict, self.data.test_volume)

    def test_get_iscsi_dict_success(self):
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        volume = self.data.test_volume
        device_info = self.data.iscsi_device_info
        ref_data = {'driver_volume_type': 'iscsi', 'data': {}}
        with mock.patch.object(
                self.driver, 'vmax_get_iscsi_properties', return_value={}):
            data = self.driver.get_iscsi_dict(device_info, volume)
            self.assertEqual(ref_data, data)
            self.driver.vmax_get_iscsi_properties.assert_called_once_with(
                volume, ip_and_iqn, True, host_lun_id, None, None)

    def test_get_iscsi_dict_exception(self):
        device_info = {'ip_and_iqn': ''}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_iscsi_dict,
                          device_info, self.data.test_volume)

    def test_get_iscsi_dict_metro(self):
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info_metro['hostlunid']
        volume = self.data.test_volume
        device_info = self.data.iscsi_device_info_metro
        ref_data = {'driver_volume_type': 'iscsi', 'data': {}}
        with mock.patch.object(
                self.driver, 'vmax_get_iscsi_properties', return_value={}):
            data = self.driver.get_iscsi_dict(device_info, volume)
            self.assertEqual(ref_data, data)
            self.driver.vmax_get_iscsi_properties.assert_called_once_with(
                volume, ip_and_iqn, True, host_lun_id,
                self.data.iscsi_device_info_metro['metro_ip_and_iqn'],
                self.data.iscsi_device_info_metro['metro_hostlunid'])

    def test_vmax_get_iscsi_properties_one_target_no_auth(self):
        vol = deepcopy(self.data.test_volume)
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        ref_properties = {
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(",")[0],
            'target_portal': ip_and_iqn[0]['ip'] + ":3260",
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            vol, ip_and_iqn, True, host_lun_id, [], None)
        self.assertEqual(type(ref_properties), type(iscsi_properties))
        self.assertEqual(ref_properties, iscsi_properties)

    def test_vmax_get_iscsi_properties_multiple_targets(self):
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.initiator},
                      {'ip': self.data.ip, 'iqn': self.data.iqn}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        ref_properties = {
            'target_portals': (
                [t['ip'] + ":3260" for t in ip_and_iqn]),
            'target_iqns': (
                [t['iqn'].split(",")[0] for t in ip_and_iqn]),
            'target_luns': [host_lun_id] * len(ip_and_iqn),
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(",")[0],
            'target_portal': ip_and_iqn[0]['ip'] + ":3260",
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.test_volume, ip_and_iqn, True, host_lun_id, [], None)
        self.assertEqual(ref_properties, iscsi_properties)

    def test_vmax_get_iscsi_properties_auth(self):
        vol = deepcopy(self.data.test_volume)
        backup_conf = self.common.configuration
        configuration = FakeConfiguration(
            None, 'ISCSITests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            vmax_array=self.data.array, vmax_srp='SRP_1', san_password='smc',
            san_rest_port=8443, use_chap_auth=True,
            chap_username='auth_username', chap_password='auth_secret',
            vmax_port_groups=[self.data.port_group_name_i])
        self.driver.configuration = configuration
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.initiator},
                      {'ip': self.data.ip, 'iqn': self.data.iqn}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        ref_properties = {
            'target_portals': (
                [t['ip'] + ":3260" for t in ip_and_iqn]),
            'target_iqns': (
                [t['iqn'].split(",")[0] for t in ip_and_iqn]),
            'target_luns': [host_lun_id] * len(ip_and_iqn),
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(",")[0],
            'target_portal': ip_and_iqn[0]['ip'] + ":3260",
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id,
            'auth_method': 'CHAP',
            'auth_username': 'auth_username',
            'auth_password': 'auth_secret'}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            vol, ip_and_iqn, True, host_lun_id, None, None)
        self.assertEqual(ref_properties, iscsi_properties)
        self.driver.configuration = backup_conf

    def test_vmax_get_iscsi_properties_metro(self):
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.iqn}]
        total_ip_list = [{'ip': self.data.ip, 'iqn': self.data.iqn},
                         {'ip': self.data.ip2, 'iqn': self.data.iqn2}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        host_lun_id2 = self.data.iscsi_device_info_metro['metro_hostlunid']
        ref_properties = {
            'target_portals': (
                [t['ip'] + ":3260" for t in total_ip_list]),
            'target_iqns': (
                [t['iqn'].split(",")[0] for t in total_ip_list]),
            'target_luns': [host_lun_id, host_lun_id2],
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(",")[0],
            'target_portal': ip_and_iqn[0]['ip'] + ":3260",
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.test_volume, ip_and_iqn, True, host_lun_id,
            self.data.iscsi_device_info_metro['metro_ip_and_iqn'],
            self.data.iscsi_device_info_metro['metro_hostlunid'])
        self.assertEqual(ref_properties, iscsi_properties)

    def test_terminate_connection(self):
        with mock.patch.object(self.common, 'terminate_connection'):
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
            self.common.terminate_connection.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_extend_volume(self):
        with mock.patch.object(self.common, 'extend_volume'):
            self.driver.extend_volume(self.data.test_volume, '3')
            self.common.extend_volume.assert_called_once_with(
                self.data.test_volume, '3')

    def test_get_volume_stats(self):
        with mock.patch.object(self.driver, 'update_volume_stats'):
            # no refresh
            self.driver.get_volume_stats()
            self.driver.update_volume_stats.assert_not_called()
            # with refresh
            self.driver.get_volume_stats(True)
            self.driver.update_volume_stats.assert_called_once_with()

    def test_update_volume_stats(self):
        with mock.patch.object(self.common, 'update_volume_stats',
                               return_value={}):
            self.driver.update_volume_stats()
            self.common.update_volume_stats.assert_called_once_with()

    def test_check_for_setup_error(self):
        self.driver.check_for_setup_error()

    def test_ensure_export(self):
        self.driver.ensure_export('context', 'volume')

    def test_create_export(self):
        self.driver.create_export('context', 'volume', 'connector')

    def test_remove_export(self):
        self.driver.remove_export('context', 'volume')

    def test_check_for_export(self):
        self.driver.check_for_export('context', 'volume_id')

    def test_manage_existing(self):
        with mock.patch.object(self.common, 'manage_existing',
                               return_value={}):
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing(self.data.test_volume, external_ref)
            self.common.manage_existing.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_manage_existing_get_size(self):
        with mock.patch.object(self.common, 'manage_existing_get_size',
                               return_value='1'):
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_get_size(
                self.data.test_volume, external_ref)
            self.common.manage_existing_get_size.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_unmanage_volume(self):
        with mock.patch.object(self.common, 'unmanage',
                               return_value={}):
            self.driver.unmanage(self.data.test_volume)
            self.common.unmanage.assert_called_once_with(
                self.data.test_volume)

    def test_retype(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(self.common, 'retype',
                               return_value=True):
            self.driver.retype({}, self.data.test_volume, new_type, '', host)
            self.common.retype.assert_called_once_with(
                self.data.test_volume, new_type, host)

    def test_failover_host(self):
        with mock.patch.object(self.common, 'failover_host',
                               return_value={}) as mock_fo:
            self.driver.failover_host({}, [self.data.test_volume])
            mock_fo.assert_called_once_with([self.data.test_volume], None,
                                            None)

    def test_enable_replication(self):
        with mock.patch.object(
                self.common, 'enable_replication') as mock_er:
            self.driver.enable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_er.assert_called_once()

    def test_disable_replication(self):
        with mock.patch.object(
                self.common, 'disable_replication') as mock_dr:
            self.driver.disable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_dr.assert_called_once()

    def test_failover_replication(self):
        with mock.patch.object(
                self.common, 'failover_replication') as mock_fo:
            self.driver.failover_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_fo.assert_called_once()


class VMAXMaskingTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXMaskingTest, self).setUp()

        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = mock.Mock()
        configuration.safe_get.return_value = 'MaskingTests'
        configuration.config_group = 'MaskingTests'
        self._gather_info = common.VMAXCommon._gather_info
        common.VMAXCommon._gather_info = mock.Mock()
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = common.VMAXCommon(
            'iSCSI', self.data.version, configuration=configuration)
        driver_fc = common.VMAXCommon(
            'FC', self.data.version, configuration=configuration)
        self.driver = driver
        self.driver_fc = driver_fc
        self.mask = self.driver.masking
        self.extra_specs = self.data.extra_specs
        self.extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_i
        self.maskingviewdict = self.driver._populate_masking_dict(
            self.data.test_volume, self.data.connector, self.extra_specs)
        self.maskingviewdict['extra_specs'] = self.extra_specs
        self.maskingviewdict[utils.IS_MULTIATTACH] = False
        self.device_id = self.data.device_id
        self.volume_name = self.data.volume_details[0]['volume_identifier']

    def tearDown(self):
        super(VMAXMaskingTest, self).tearDown()
        common.VMAXCommon._gather_info = self._gather_info

    @mock.patch.object(
        masking.VMAXMasking,
        'get_or_create_masking_view_and_map_lun')
    def test_setup_masking_view(self, mock_get_or_create_mv):
        self.driver.masking.setup_masking_view(
            self.data.array, self.data.test_volume,
            self.maskingviewdict, self.extra_specs)
        mock_get_or_create_mv.assert_called_once()

    @mock.patch.object(
        masking.VMAXMasking,
        '_check_adding_volume_to_storage_group')
    @mock.patch.object(
        masking.VMAXMasking,
        '_move_vol_from_default_sg',
        return_value=None)
    @mock.patch.object(
        masking.VMAXMasking,
        '_get_or_create_masking_view',
        side_effect=[None, "Error in masking view retrieval",
                     exception.VolumeBackendAPIException])
    @mock.patch.object(
        rest.VMAXRest,
        'get_element_from_masking_view',
        side_effect=[VMAXCommonData.port_group_name_i,
                     Exception('Exception')])
    def test_get_or_create_masking_view_and_map_lun(
            self, mock_masking_view_element, mock_masking, mock_move,
            mock_add_volume):
        rollback_dict = (
            self.driver.masking.get_or_create_masking_view_and_map_lun(
                self.data.array, self.data.test_volume,
                self.maskingviewdict['maskingview_name'],
                self.maskingviewdict, self.extra_specs))
        self.assertEqual(self.maskingviewdict, rollback_dict)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.get_or_create_masking_view_and_map_lun,
            self.data.array, self.data.test_volume,
            self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, self.extra_specs)
        self.maskingviewdict['slo'] = None
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.get_or_create_masking_view_and_map_lun,
            self.data.array, self.data.test_volume,
            self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, self.extra_specs)

    @mock.patch.object(
        masking.VMAXMasking,
        '_check_adding_volume_to_storage_group',
        return_value=None)
    @mock.patch.object(
        rest.VMAXRest,
        'move_volume_between_storage_groups',
        side_effect=[None, exception.VolumeBackendAPIException(data='')])
    @mock.patch.object(
        rest.VMAXRest,
        'is_volume_in_storagegroup',
        side_effect=[True, False, True])
    def test_move_vol_from_default_sg(
            self, mock_volume_in_sg, mock_move_volume, mock_add):
        msg = None
        for x in range(0, 2):
            msg = self.driver.masking._move_vol_from_default_sg(
                self.data.array, self.device_id, self.volume_name,
                self.data.defaultstoragegroup_name,
                self.data.storagegroup_name_i, self.extra_specs)
        mock_move_volume.assert_called_once()
        mock_add.assert_called_once()
        self.assertIsNone(msg)
        msg = self.driver.masking._move_vol_from_default_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.defaultstoragegroup_name,
            self.data.storagegroup_name_i, self.extra_specs)
        self.assertIsNotNone(msg)

    @mock.patch.object(rest.VMAXRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(masking.VMAXMasking, 'get_parent_sg_from_child',
                       side_effect=[None, VMAXCommonData.parent_sg_f])
    @mock.patch.object(
        rest.VMAXRest, 'get_num_vols_in_sg', side_effect=[2, 1, 1])
    def test_move_volume_between_storage_groups(
            self, mock_num, mock_parent, mock_rm):
        for x in range(0, 3):
            self.driver.masking.move_volume_between_storage_groups(
                self.data.array, self.data.device_id,
                self.data.storagegroup_name_i, self.data.storagegroup_name_f,
                self.data.extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(
        rest.VMAXRest,
        'get_masking_view',
        side_effect=[VMAXCommonData.maskingview,
                     VMAXCommonData.maskingview, None])
    @mock.patch.object(
        masking.VMAXMasking,
        '_validate_existing_masking_view',
        side_effect=[(VMAXCommonData.maskingview[1]['storageGroupId'],
                      None), (None, "Error Message")])
    @mock.patch.object(
        masking.VMAXMasking,
        '_create_new_masking_view',
        return_value=None)
    def test_get_or_create_masking_view(
            self, mock_create_mv, mock_validate_mv,
            mock_get_mv):
        for x in range(0, 3):
            self.driver.masking._get_or_create_masking_view(
                self.data.array, self.maskingviewdict,
                self.data.defaultstoragegroup_name, self.extra_specs)
        mock_create_mv.assert_called_once()

    @mock.patch.object(
        masking.VMAXMasking,
        '_get_or_create_storage_group',
        side_effect=["Storage group not found", None,
                     "Storage group not found", None, None, None,
                     None, None, None, None, None])
    @mock.patch.object(
        masking.VMAXMasking,
        '_check_port_group',
        side_effect=[(None, "Port group error"), (None, None), (None, None),
                     (None, None)])
    @mock.patch.object(
        masking.VMAXMasking,
        '_get_or_create_initiator_group',
        side_effect=[(None, "Initiator group error"), (None, None),
                     (None, None)])
    @mock.patch.object(
        masking.VMAXMasking,
        '_move_vol_from_default_sg',
        side_effect=["Storage group error", None])
    @mock.patch.object(
        masking.VMAXMasking,
        'create_masking_view',
        return_value=None)
    def test_create_new_masking_view(
            self, mock_create_mv, mock_move, mock_create_IG,
            mock_check_PG, mock_create_SG):
        for x in range(0, 6):
            self.driver.masking._create_new_masking_view(
                self.data.array, self.maskingviewdict,
                self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, self.extra_specs)
        mock_create_mv.assert_called_once()

    @mock.patch.object(
        masking.VMAXMasking,
        '_check_existing_storage_group',
        side_effect=[(VMAXCommonData.storagegroup_name_i, None),
                     (VMAXCommonData.storagegroup_name_i, None),
                     (None, "Error Checking existing storage group")])
    @mock.patch.object(
        rest.VMAXRest,
        'get_element_from_masking_view',
        return_value=VMAXCommonData.port_group_name_i)
    @mock.patch.object(
        masking.VMAXMasking,
        '_check_port_group',
        side_effect=[(None, None), (None, "Error checking pg")])
    @mock.patch.object(
        masking.VMAXMasking,
        '_check_existing_initiator_group',
        return_value=(VMAXCommonData.initiatorgroup_name_i, None))
    def test_validate_existing_masking_view(
            self, mock_check_ig, mock_check_pg, mock_get_mv_element,
            mock_check_sg):
        for x in range(0, 3):
            self.driver.masking._validate_existing_masking_view(
                self.data.array, self.maskingviewdict,
                self.maskingviewdict['maskingview_name'],
                self.data.defaultstoragegroup_name, self.extra_specs)
        self.assertEqual(3, mock_check_sg.call_count)
        mock_get_mv_element.assert_called_with(
            self.data.array, self.maskingviewdict['maskingview_name'],
            portgroup=True)
        mock_check_ig.assert_called_once()

    @mock.patch.object(
        rest.VMAXRest,
        'get_storage_group',
        side_effect=[VMAXCommonData.storagegroup_name_i, None, None])
    @mock.patch.object(
        provision.VMAXProvision,
        'create_storage_group',
        side_effect=[VMAXCommonData.storagegroup_name_i, None])
    def test_get_or_create_storage_group(self, mock_sg, mock_get_sg):
        for x in range(0, 2):
            self.driver.masking._get_or_create_storage_group(
                self.data.array, self.maskingviewdict,
                self.data.storagegroup_name_i, self.extra_specs)
        self.driver.masking._get_or_create_storage_group(
            self.data.array, self.maskingviewdict,
            self.data.storagegroup_name_i, self.extra_specs, True)
        self.assertEqual(3, mock_get_sg.call_count)
        self.assertEqual(2, mock_sg.call_count)

    @mock.patch.object(
        masking.VMAXMasking,
        '_move_vol_from_default_sg',
        return_value=None)
    @mock.patch.object(
        masking.VMAXMasking,
        '_get_or_create_storage_group',
        return_value=None)
    @mock.patch.object(
        rest.VMAXRest,
        'get_element_from_masking_view',
        return_value=VMAXCommonData.parent_sg_i)
    @mock.patch.object(
        rest.VMAXRest,
        'is_child_sg_in_parent_sg',
        side_effect=[True, False])
    @mock.patch.object(
        masking.VMAXMasking,
        '_check_add_child_sg_to_parent_sg',
        return_value=None)
    def test_check_existing_storage_group_success(
            self, mock_add_sg, mock_is_child, mock_get_mv_element,
            mock_create_sg, mock_move):
        masking_view_dict = deepcopy(self.data.masking_view_dict)
        masking_view_dict['extra_specs'] = self.data.extra_specs
        with mock.patch.object(self.driver.rest, 'get_storage_group',
                               side_effect=[
                                   VMAXCommonData.parent_sg_i,
                                   VMAXCommonData.storagegroup_name_i]):
            _, msg = (
                self.driver.masking._check_existing_storage_group(
                    self.data.array, self.maskingviewdict['maskingview_name'],
                    self.data.defaultstoragegroup_name, masking_view_dict))
            self.assertIsNone(msg)
            mock_create_sg.assert_not_called()
        with mock.patch.object(self.driver.rest, 'get_storage_group',
                               side_effect=[
                                   VMAXCommonData.parent_sg_i, None]):
            _, msg = (
                self.driver.masking._check_existing_storage_group(
                    self.data.array, self.maskingviewdict['maskingview_name'],
                    self.data.defaultstoragegroup_name, masking_view_dict))
            self.assertIsNone(msg)
            mock_create_sg.assert_called_once_with(
                self.data.array, masking_view_dict,
                VMAXCommonData.storagegroup_name_f,
                self.data.extra_specs)

    @mock.patch.object(
        masking.VMAXMasking,
        '_move_vol_from_default_sg',
        side_effect=[None, "Error Message"])
    @mock.patch.object(
        rest.VMAXRest,
        'is_child_sg_in_parent_sg',
        side_effect=[True, False, False])
    @mock.patch.object(
        rest.VMAXRest,
        'get_element_from_masking_view',
        return_value=VMAXCommonData.parent_sg_i)
    @mock.patch.object(
        rest.VMAXRest,
        'get_storage_group',
        side_effect=[None, VMAXCommonData.parent_sg_i, None,
                     VMAXCommonData.parent_sg_i, None,
                     VMAXCommonData.parent_sg_i, None])
    def test_check_existing_storage_group_failed(
            self, mock_get_sg, mock_get_mv_element, mock_child, mock_move):
        masking_view_dict = deepcopy(self.data.masking_view_dict)
        masking_view_dict['extra_specs'] = self.data.extra_specs
        for x in range(0, 4):
            _, msg = (
                self.driver.masking._check_existing_storage_group(
                    self.data.array, self.maskingviewdict['maskingview_name'],
                    self.data.defaultstoragegroup_name, masking_view_dict))
            self.assertIsNotNone(msg)
        self.assertEqual(7, mock_get_sg.call_count)
        self.assertEqual(1, mock_move.call_count)

    @mock.patch.object(rest.VMAXRest, 'get_portgroup',
                       side_effect=[VMAXCommonData.port_group_name_i, None])
    def test_check_port_group(
            self, mock_get_pg):
        for x in range(0, 2):
            _, msg = self.driver.masking._check_port_group(
                self.data.array, self.maskingviewdict['maskingview_name'])
        self.assertIsNotNone(msg)
        self.assertEqual(2, mock_get_pg.call_count)

    @mock.patch.object(
        masking.VMAXMasking, '_find_initiator_group',
        side_effect=[VMAXCommonData.initiatorgroup_name_i, None, None])
    @mock.patch.object(masking.VMAXMasking, '_create_initiator_group',
                       side_effect=[VMAXCommonData.initiatorgroup_name_i, None]
                       )
    def test_get_or_create_initiator_group(self, mock_create_ig, mock_find_ig):
        self.driver.masking._get_or_create_initiator_group(
            self.data.array, self.data.initiatorgroup_name_i,
            self.data.connector, self.extra_specs)
        mock_create_ig.assert_not_called()
        found_init_group, msg = (
            self.driver.masking._get_or_create_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector, self.extra_specs))
        self.assertIsNone(msg)
        found_init_group, msg = (
            self.driver.masking._get_or_create_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector, self.extra_specs))
        self.assertIsNotNone(msg)

    def test_check_existing_initiator_group(self):
        with mock.patch.object(
                rest.VMAXRest, 'get_element_from_masking_view',
                return_value=VMAXCommonData.inititiatorgroup):
            ig_from_mv, msg = (
                self.driver.masking._check_existing_initiator_group(
                    self.data.array, self.maskingviewdict['maskingview_name'],
                    self.maskingviewdict, self.data.storagegroup_name_i,
                    self.data.port_group_name_i, self.extra_specs))
            self.assertEqual(self.data.inititiatorgroup, ig_from_mv)

    def test_check_adding_volume_to_storage_group(self):
        with mock.patch.object(
                masking.VMAXMasking, '_create_initiator_group'):
            with mock.patch.object(
                rest.VMAXRest, 'is_volume_in_storagegroup',
                    side_effect=[True, False]):
                msg = (
                    self.driver.masking._check_adding_volume_to_storage_group(
                        self.data.array, self.device_id,
                        self.data.storagegroup_name_i,
                        self.maskingviewdict[utils.VOL_NAME],
                        self.maskingviewdict[utils.EXTRA_SPECS]))
                self.assertIsNone(msg)
                msg = (
                    self.driver.masking._check_adding_volume_to_storage_group(
                        self.data.array, self.device_id,
                        self.data.storagegroup_name_i,
                        self.maskingviewdict[utils.VOL_NAME],
                        self.maskingviewdict[utils.EXTRA_SPECS]))

    @mock.patch.object(rest.VMAXRest, 'add_vol_to_sg')
    def test_add_volume_to_storage_group(self, mock_add_volume):
        self.driver.masking.add_volume_to_storage_group(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs)
        mock_add_volume.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'remove_vol_from_sg')
    def test_remove_vol_from_storage_group(self, mock_remove_volume):
        with mock.patch.object(
                rest.VMAXRest, 'is_volume_in_storagegroup',
                side_effect=[False, True]):
            self.driver.masking.remove_vol_from_storage_group(
                self.data.array, self.device_id, self.data.storagegroup_name_i,
                self.volume_name, self.extra_specs)
            mock_remove_volume.assert_called_once()
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.driver.masking.remove_vol_from_storage_group,
                self.data.array, self.device_id, self.data.storagegroup_name_i,
                self.volume_name, self.extra_specs)

    def test_find_initiator_names(self):
        foundinitiatornames = self.driver.masking.find_initiator_names(
            self.data.connector)
        self.assertEqual(self.data.connector['initiator'],
                         foundinitiatornames[0])
        foundinitiatornames = self.driver_fc.masking.find_initiator_names(
            self.data.connector)
        self.assertEqual(self.data.connector['wwpns'][0],
                         foundinitiatornames[0])
        connector = {'ip': self.data.ip, 'initiator': None, 'host': 'HostX'}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.masking.find_initiator_names, connector)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver_fc.masking.find_initiator_names, connector)

    def test_find_initiator_group_found(self):
        with mock.patch.object(
                rest.VMAXRest, 'get_initiator_list',
                return_value=self.data.initiator_list[2]['initiatorId']):
            with mock.patch.object(
                    rest.VMAXRest, 'get_initiator_group_from_initiator',
                    return_value=self.data.initiator_list):
                found_init_group_nam = (
                    self.driver.masking._find_initiator_group(
                        self.data.array, ['FA-1D:4:123456789012345']))
                self.assertEqual(self.data.initiator_list,
                                 found_init_group_nam)

    def test_find_initiator_group_not_found(self):
        with mock.patch.object(
                rest.VMAXRest, 'get_initiator_list',
                return_value=self.data.initiator_list[2]['initiatorId']):
            with mock.patch.object(
                    rest.VMAXRest, 'get_initiator_group_from_initiator',
                    return_value=None):
                found_init_group_nam = (
                    self.driver.masking._find_initiator_group(
                        self.data.array, ['Error']))
                self.assertIsNone(found_init_group_nam)

    def test_create_masking_view(self):
        with mock.patch.object(rest.VMAXRest, 'create_masking_view',
                               side_effect=[None, Exception]):
            error_message = self.driver.masking.create_masking_view(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.storagegroup_name_i, self.data.port_group_name_i,
                self.data.initiatorgroup_name_i, self.extra_specs)
            self.assertIsNone(error_message)
            error_message = self.driver.masking.create_masking_view(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.data.storagegroup_name_i, self.data.port_group_name_i,
                self.data.initiatorgroup_name_i, self.extra_specs)
            self.assertIsNotNone(error_message)

    @mock.patch.object(masking.VMAXMasking,
                       '_return_volume_to_fast_managed_group')
    @mock.patch.object(masking.VMAXMasking, '_check_ig_rollback')
    def test_check_if_rollback_action_for_masking_required(
            self, mock_check_ig, mock_return):
        with mock.patch.object(rest.VMAXRest,
                               'get_storage_groups_from_volume',
                               side_effect=[
                                   exception.VolumeBackendAPIException,
                                   self.data.storagegroup_list,
                                   self.data.storagegroup_list, None,
                                   None, ]):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.mask.check_if_rollback_action_for_masking_required,
                self.data.array, self.data.test_volume,
                self.device_id, self.maskingviewdict)
            with mock.patch.object(masking.VMAXMasking,
                                   'remove_and_reset_members'):
                self.maskingviewdict[
                    'default_sg_name'] = self.data.defaultstoragegroup_name
                self.mask.check_if_rollback_action_for_masking_required(
                    self.data.array, self.data.test_volume,
                    self.device_id, self.maskingviewdict)
                # Multiattach case
                self.mask.check_if_rollback_action_for_masking_required(
                    self.data.array, self.data.test_volume,
                    self.device_id, self.data.masking_view_dict_multiattach)
                mock_return.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'delete_masking_view')
    @mock.patch.object(rest.VMAXRest, 'delete_initiator_group')
    @mock.patch.object(rest.VMAXRest, 'get_initiator_group')
    @mock.patch.object(masking.VMAXMasking, '_find_initiator_group',
                       return_value=VMAXCommonData.initiatorgroup_name_i)
    def test_verify_initiator_group_from_masking_view(
            self, mock_find_ig, mock_get_ig, mock_delete_ig, mock_delete_mv):
        self.mask._verify_initiator_group_from_masking_view(
            self.data.array, self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, self.data.initiatorgroup_name_i,
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_get_ig.assert_not_called()
        mock_get_ig.return_value = False
        self.mask._verify_initiator_group_from_masking_view(
            self.data.array, self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, 'OS-Wrong-Host-I-IG',
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_get_ig.assert_called()

    @mock.patch.object(rest.VMAXRest, 'delete_masking_view')
    @mock.patch.object(rest.VMAXRest, 'delete_initiator_group')
    @mock.patch.object(rest.VMAXRest, 'get_initiator_group',
                       return_value=True)
    @mock.patch.object(masking.VMAXMasking, '_find_initiator_group',
                       return_value=VMAXCommonData.initiatorgroup_name_i)
    def test_verify_initiator_group_from_masking_view2(
            self, mock_find_ig, mock_get_ig, mock_delete_ig, mock_delete_mv):
        mock_delete_mv.side_effect = [None, Exception]
        self.mask._verify_initiator_group_from_masking_view(
            self.data.array, self.maskingviewdict['maskingview_name'],
            self.maskingviewdict, 'OS-Wrong-Host-I-IG',
            self.data.storagegroup_name_i, self.data.port_group_name_i,
            self.extra_specs)
        mock_delete_mv.assert_called()
        _, found_ig_from_connector = (
            self.mask._verify_initiator_group_from_masking_view(
                self.data.array, self.maskingviewdict['maskingview_name'],
                self.maskingviewdict, 'OS-Wrong-Host-I-IG',
                self.data.storagegroup_name_i, self.data.port_group_name_i,
                self.extra_specs))
        self.assertEqual(self.data.initiatorgroup_name_i,
                         found_ig_from_connector)

    @mock.patch.object(rest.VMAXRest, 'create_initiator_group')
    def test_create_initiator_group(self, mock_create_ig):
        initiator_names = self.mask.find_initiator_names(self.data.connector)
        ret_init_group_name = self.mask._create_initiator_group(
            self.data.array, self.data.initiatorgroup_name_i, initiator_names,
            self.extra_specs)
        self.assertEqual(self.data.initiatorgroup_name_i, ret_init_group_name)

    @mock.patch.object(masking.VMAXMasking,
                       '_last_volume_delete_initiator_group')
    def test_check_ig_rollback(self, mock_last_volume):
        with mock.patch.object(masking.VMAXMasking, '_find_initiator_group',
                               side_effect=[
                                   None, 'FAKE-I-IG',
                                   self.data.initiatorgroup_name_i]):
            for x in range(0, 2):
                self.mask._check_ig_rollback(self.data.array,
                                             self.data.initiatorgroup_name_i,
                                             self.data.connector)
            mock_last_volume.assert_not_called()
            self.mask._check_ig_rollback(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector)
            mock_last_volume.assert_called()

    @mock.patch.object(masking.VMAXMasking, '_cleanup_deletion')
    def test_remove_and_reset_members(self, mock_cleanup):
        self.mask.remove_and_reset_members(
            self.data.array, self.device_id, self.data.test_volume,
            self.volume_name, self.extra_specs, reset=False)
        mock_cleanup.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'get_storage_groups_from_volume',
                       side_effect=[[VMAXCommonData.storagegroup_name_i],
                                    [VMAXCommonData.storagegroup_name_i],
                                    [VMAXCommonData.storagegroup_name_i,
                                     VMAXCommonData.storagegroup_name_f]])
    @mock.patch.object(masking.VMAXMasking, 'remove_volume_from_sg')
    @mock.patch.object(masking.VMAXMasking,
                       'add_volume_to_default_storage_group')
    def test_cleanup_deletion(self, mock_add, mock_remove_vol, mock_get_sg):
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs, None, True, None)
        mock_add.assert_not_called()
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs,
            self.data.connector, True, None)
        mock_add.assert_not_called()
        self.mask._cleanup_deletion(
            self.data.array, self.data.test_volume, self.device_id,
            self.volume_name, self.extra_specs, None, True, None)
        mock_add.assert_called_once_with(
            self.data.array, self.device_id,
            self.volume_name, self.extra_specs, volume=self.data.test_volume)

    @mock.patch.object(masking.VMAXMasking, '_last_vol_in_sg')
    @mock.patch.object(masking.VMAXMasking, '_multiple_vols_in_sg')
    def test_remove_volume_from_sg(self, mock_multiple_vols, mock_last_vol):
        with mock.patch.object(
                rest.VMAXRest, 'get_masking_views_from_storage_group',
                return_value=None):
            with mock.patch.object(
                rest.VMAXRest, 'get_num_vols_in_sg',
                    side_effect=[2, 1]):
                self.mask.remove_volume_from_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.defaultstoragegroup_name, self.extra_specs)
                mock_last_vol.assert_not_called()
                self.mask.remove_volume_from_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.defaultstoragegroup_name, self.extra_specs)
                mock_last_vol.assert_called()

    @mock.patch.object(masking.VMAXMasking, '_last_vol_in_sg')
    @mock.patch.object(masking.VMAXMasking, '_multiple_vols_in_sg')
    def test_remove_volume_from_sg_2(self, mock_multiple_vols, mock_last_vol):
        with mock.patch.object(
                rest.VMAXRest, 'is_volume_in_storagegroup',
                return_value=True):
            with mock.patch.object(
                    rest.VMAXRest, 'get_masking_views_from_storage_group',
                    return_value=[self.data.masking_view_name_i]):
                with mock.patch.object(
                    rest.VMAXRest, 'get_num_vols_in_sg',
                        side_effect=[2, 1]):
                    self.mask.remove_volume_from_sg(
                        self.data.array, self.device_id, self.volume_name,
                        self.data.storagegroup_name_i, self.extra_specs)
                    mock_last_vol.assert_not_called()
                    self.mask.remove_volume_from_sg(
                        self.data.array, self.device_id, self.volume_name,
                        self.data.storagegroup_name_i, self.extra_specs)
                    mock_last_vol.assert_called()

    @mock.patch.object(masking.VMAXMasking, '_last_vol_masking_views',
                       return_value=True)
    @mock.patch.object(masking.VMAXMasking, '_last_vol_no_masking_views',
                       return_value=True)
    def test_last_vol_in_sg(self, mock_no_mv, mock_mv):
        mv_list = [self.data.masking_view_name_i,
                   self.data.masking_view_name_f]
        with mock.patch.object(rest.VMAXRest,
                               'get_masking_views_from_storage_group',
                               side_effect=[mv_list, []]):
            for x in range(0, 2):
                self.mask._last_vol_in_sg(
                    self.data.array, self.device_id, self.volume_name,
                    self.data.storagegroup_name_i, self.extra_specs,
                    self.data.connector)
            self.assertEqual(1, mock_mv.call_count)
            self.assertEqual(1, mock_no_mv.call_count)

    @mock.patch.object(masking.VMAXMasking, '_remove_last_vol_and_delete_sg')
    @mock.patch.object(masking.VMAXMasking, '_delete_cascaded_storage_groups')
    @mock.patch.object(rest.VMAXRest, 'get_num_vols_in_sg',
                       side_effect=[1, 3])
    @mock.patch.object(rest.VMAXRest, 'delete_storage_group')
    @mock.patch.object(masking.VMAXMasking, 'get_parent_sg_from_child',
                       side_effect=[None, 'parent_sg_name', 'parent_sg_name'])
    def test_last_vol_no_masking_views(
            self, mock_get_parent, mock_delete, mock_num_vols,
            mock_delete_casc, mock_remove):
        for x in range(0, 3):
            self.mask._last_vol_no_masking_views(
                self.data.array, self.data.storagegroup_name_i,
                self.device_id, self.volume_name, self.extra_specs,
                False)
        self.assertEqual(1, mock_delete.call_count)
        self.assertEqual(1, mock_delete_casc.call_count)
        self.assertEqual(1, mock_remove.call_count)

    @mock.patch.object(masking.VMAXMasking, '_remove_last_vol_and_delete_sg')
    @mock.patch.object(masking.VMAXMasking, '_delete_mv_ig_and_sg')
    @mock.patch.object(masking.VMAXMasking, '_get_num_vols_from_mv',
                       side_effect=[(1, 'parent_name'), (3, 'parent_name')])
    def test_last_vol_masking_views(
            self, mock_num_vols, mock_delete_all, mock_remove):
        for x in range(0, 2):
            self.mask._last_vol_masking_views(
                self.data.array, self.data.storagegroup_name_i,
                [self.data.masking_view_name_i], self.device_id,
                self.volume_name, self.extra_specs, self.data.connector,
                True)
        self.assertEqual(1, mock_delete_all.call_count)
        self.assertEqual(1, mock_remove.call_count)

    @mock.patch.object(masking.VMAXMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.VMAXRest, 'get_num_vols_in_sg')
    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    def test_multiple_vols_in_sg(self, mock_remove_vol, mock_get_volumes,
                                 mock_add):
        self.mask._multiple_vols_in_sg(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs, False)
        mock_remove_vol.assert_called_once()
        self.mask._multiple_vols_in_sg(
            self.data.array, self.device_id, self.data.storagegroup_name_i,
            self.volume_name, self.extra_specs, True)
        mock_add.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'get_element_from_masking_view')
    @mock.patch.object(masking.VMAXMasking, '_last_volume_delete_masking_view')
    @mock.patch.object(masking.VMAXMasking,
                       '_last_volume_delete_initiator_group')
    @mock.patch.object(masking.VMAXMasking, '_delete_cascaded_storage_groups')
    def test_delete_mv_ig_and_sg(self, mock_delete_sg, mock_delete_ig,
                                 mock_delete_mv, mock_get_element):
        self.mask._delete_mv_ig_and_sg(
            self.data.array, self.data.device_id,
            self.data.masking_view_name_i,
            self.data.storagegroup_name_i, self.data.parent_sg_i,
            self.data.connector, True, self.data.extra_specs)
        mock_delete_sg.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'delete_masking_view')
    def test_last_volume_delete_masking_view(self, mock_delete_mv):
        self.mask._last_volume_delete_masking_view(
            self.data.array, self.data.masking_view_name_i)
        mock_delete_mv.assert_called_once()

    @mock.patch.object(masking.VMAXMasking, 'return_volume_to_volume_group')
    @mock.patch.object(rest.VMAXRest, 'move_volume_between_storage_groups')
    @mock.patch.object(masking.VMAXMasking,
                       'get_or_create_default_storage_group')
    @mock.patch.object(masking.VMAXMasking, 'add_volume_to_storage_group')
    def test_add_volume_to_default_storage_group(
            self, mock_add_sg, mock_get_sg, mock_move, mock_return):
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs)
        mock_add_sg.assert_called_once()
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs, src_sg=self.data.storagegroup_name_i)
        mock_move.assert_called_once()
        vol_grp_member = deepcopy(self.data.test_volume)
        vol_grp_member.group_id = self.data.test_vol_grp_name_id_only
        self.mask.add_volume_to_default_storage_group(
            self.data.array, self.device_id, self.volume_name,
            self.extra_specs, volume=vol_grp_member)
        mock_return.assert_called_once()

    def test_add_volume_to_default_storage_group_next_gen(self):
        with mock.patch.object(rest.VMAXRest, 'is_next_gen_array',
                               return_value=True):
            with mock.patch.object(
                    self.mask, 'get_or_create_default_storage_group'):
                self.mask.add_volume_to_default_storage_group(
                    self.data.array, self.device_id, self.volume_name,
                    self.extra_specs)
                (self.mask.get_or_create_default_storage_group
                    .assert_called_once_with(self.data.array, self.data.srp,
                                             self.extra_specs[utils.SLO],
                                             'NONE', self.extra_specs, False,
                                             False, None))

    @mock.patch.object(provision.VMAXProvision, 'create_storage_group')
    def test_get_or_create_default_storage_group(self, mock_create_sg):
        with mock.patch.object(
                rest.VMAXRest, 'get_vmax_default_storage_group',
                return_value=(None, self.data.storagegroup_name_i)):
            storage_group_name = self.mask.get_or_create_default_storage_group(
                self.data.array, self.data.srp, self.data.slo,
                self.data.workload, self.extra_specs)
            self.assertEqual(self.data.storagegroup_name_i, storage_group_name)
        with mock.patch.object(
                rest.VMAXRest, 'get_vmax_default_storage_group',
                return_value=("test_sg", self.data.storagegroup_name_i)):
            with mock.patch.object(
                rest.VMAXRest, 'get_masking_views_from_storage_group',
                    return_value=self.data.masking_view_name_i):
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.mask.get_or_create_default_storage_group,
                    self.data.array, self.data.srp, self.data.slo,
                    self.data.workload, self.extra_specs)

    @mock.patch.object(masking.VMAXMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.VMAXRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(rest.VMAXRest, 'delete_storage_group')
    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    def test_remove_last_vol_and_delete_sg(self, mock_vol_sg,
                                           mock_delete_sg, mock_rm, mock_add):
        self.mask._remove_last_vol_and_delete_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.storagegroup_name_i, self.extra_specs)
        self.mask._remove_last_vol_and_delete_sg(
            self.data.array, self.device_id, self.volume_name,
            self.data.storagegroup_name_i, self.extra_specs,
            self.data.parent_sg_i, True)
        self.assertEqual(2, mock_delete_sg.call_count)
        self.assertEqual(1, mock_vol_sg.call_count)
        self.assertEqual(1, mock_rm.call_count)
        self.assertEqual(1, mock_add.call_count)

    @mock.patch.object(rest.VMAXRest, 'delete_initiator_group')
    def test_last_volume_delete_initiator_group(self, mock_delete_ig):
        self.mask._last_volume_delete_initiator_group(
            self.data.array, self.data.initiatorgroup_name_f, 'Wrong_Host')
        mock_delete_ig.assert_not_called()
        self.mask._last_volume_delete_initiator_group(
            self.data.array, self.data.initiatorgroup_name_f, None)
        mock_delete_ig.assert_not_called()
        mv_list = [self.data.masking_view_name_i,
                   self.data.masking_view_name_f]
        with mock.patch.object(rest.VMAXRest,
                               'get_masking_views_by_initiator_group',
                               side_effect=[mv_list, []]):
            self.mask._last_volume_delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector['host'])
            mock_delete_ig.assert_not_called()
            self.mask._last_volume_delete_initiator_group(
                self.data.array, self.data.initiatorgroup_name_i,
                self.data.connector['host'])
            mock_delete_ig.assert_called_once()

    def test_populate_masking_dict_init_check_false(self):
        extra_specs = self.data.extra_specs
        connector = self.data.connector
        with mock.patch.object(self.driver, '_get_initiator_check_flag',
                               return_value=False):
            masking_view_dict = self.driver._populate_masking_dict(
                self.data.test_volume, connector, extra_specs)
            self.assertFalse(masking_view_dict['initiator_check'])

    def test_populate_masking_dict_init_check_true(self):
        extra_specs = self.data.extra_specs
        connector = self.data.connector
        with mock.patch.object(self.driver, '_get_initiator_check_flag',
                               return_value=True):
            masking_view_dict = self.driver._populate_masking_dict(
                self.data.test_volume, connector, extra_specs)
            self.assertTrue(masking_view_dict['initiator_check'])

    def test_check_existing_initiator_group_verify_true(self):
        mv_dict = deepcopy(self.data.masking_view_dict)
        mv_dict['initiator_check'] = True
        with mock.patch.object(
                rest.VMAXRest, 'get_element_from_masking_view',
                return_value=VMAXCommonData.initiatorgroup_name_f):
            with mock.patch.object(
                    self.mask, '_verify_initiator_group_from_masking_view',
                    return_value=(True, self.data.initiatorgroup_name_f)):
                self.mask._check_existing_initiator_group(
                    self.data.array, self.data.masking_view_name_f,
                    mv_dict, self.data.storagegroup_name_f,
                    self.data.port_group_name_f, self.data.extra_specs)
                (self.mask._verify_initiator_group_from_masking_view.
                    assert_called_once_with(
                        self.data.array, self.data.masking_view_name_f,
                        mv_dict, self.data.initiatorgroup_name_f,
                        self.data.storagegroup_name_f,
                        self.data.port_group_name_f, self.data.extra_specs))

    @mock.patch.object(masking.VMAXMasking, 'add_child_sg_to_parent_sg',
                       side_effect=[
                           None, exception.VolumeBackendAPIException])
    @mock.patch.object(rest.VMAXRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False, False])
    def test_check_add_child_sg_to_parent_sg(self, mock_is_child, mock_add):
        for x in range(0, 3):
            message = self.mask._check_add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_i,
                self.data.parent_sg_i, self.data.extra_specs)
        self.assertIsNotNone(message)

    @mock.patch.object(rest.VMAXRest, 'add_child_sg_to_parent_sg')
    @mock.patch.object(rest.VMAXRest, 'is_child_sg_in_parent_sg',
                       side_effect=[True, False])
    def test_add_child_sg_to_parent_sg(self, mock_is_child, mock_add):
        for x in range(0, 2):
            self.mask.add_child_sg_to_parent_sg(
                self.data.array, self.data.storagegroup_name_i,
                self.data.parent_sg_i, self.data.extra_specs)
        self.assertEqual(1, mock_add.call_count)

    def test_get_parent_sg_from_child(self):
        with mock.patch.object(self.driver.rest, 'get_storage_group',
                               side_effect=[None, self.data.sg_details[1]]):
            sg_name = self.mask.get_parent_sg_from_child(
                self.data.array, self.data.storagegroup_name_i)
            self.assertIsNone(sg_name)
            sg_name2 = self.mask.get_parent_sg_from_child(
                self.data.array, self.data.storagegroup_name_f)
            self.assertEqual(self.data.parent_sg_f, sg_name2)

    @mock.patch.object(rest.VMAXRest, 'get_element_from_masking_view',
                       return_value='parent_sg')
    @mock.patch.object(rest.VMAXRest, 'get_num_vols_in_sg',
                       return_value=2)
    def test_get_num_vols_from_mv(self, mock_num, mock_element):
        num_vols, sg = self.mask._get_num_vols_from_mv(
            self.data.array, self.data.masking_view_name_f)
        self.assertEqual(2, num_vols)

    @mock.patch.object(masking.VMAXMasking,
                       'add_volume_to_default_storage_group')
    @mock.patch.object(rest.VMAXRest, 'delete_storage_group')
    def test_delete_cascaded(self, mock_delete, mock_add):
        self.mask._delete_cascaded_storage_groups(
            self.data.array, self.data.masking_view_name_f,
            self.data.parent_sg_f, self.data.extra_specs,
            self.data.device_id, False)
        self.assertEqual(2, mock_delete.call_count)
        mock_add.assert_not_called()
        # Delete legacy masking view, parent sg = child sg
        mock_delete.reset_mock()
        self.mask._delete_cascaded_storage_groups(
            self.data.array, self.data.masking_view_name_f,
            self.data.masking_view_name_f, self.data.extra_specs,
            self.data.device_id, True)
        self.assertEqual(1, mock_delete.call_count)
        mock_add.assert_called_once()

    @mock.patch.object(masking.VMAXMasking,
                       'add_volumes_to_storage_group')
    def test_add_remote_vols_to_volume_group(self, mock_add):
        self.mask.add_remote_vols_to_volume_group(
            [self.data.test_volume], self.data.test_rep_group,
            self.data.rep_extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(masking.VMAXMasking, 'add_remote_vols_to_volume_group')
    @mock.patch.object(masking.VMAXMasking,
                       '_check_adding_volume_to_storage_group')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type',
                       side_effect=[False, False, True, True])
    def test_return_volume_to_volume_group(self, mock_type, mock_cg,
                                           mock_check, mock_add):
        vol_grp_member = deepcopy(self.data.test_volume)
        vol_grp_member.group_id = self.data.test_vol_grp_name_id_only
        vol_grp_member.group = self.data.test_group
        for x in range(0, 2):
            self.mask.return_volume_to_volume_group(
                self.data.array, vol_grp_member, self.data.device_id,
                self.data.test_volume.name, self.data.extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(masking.VMAXMasking,
                       '_return_volume_to_fast_managed_group')
    def test_pre_multiattach(self, mock_return):
        mv_dict = self.mask.pre_multiattach(
            self.data.array, self.data.device_id,
            self.data.masking_view_dict_multiattach, self.data.extra_specs)
        mock_return.assert_not_called()
        self.assertEqual(self.data.storagegroup_name_f,
                         mv_dict[utils.FAST_SG])
        with mock.patch.object(
                self.mask, 'move_volume_between_storage_groups',
                side_effect=exception.CinderException):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.mask.pre_multiattach, self.data.array,
                self.data.device_id, self.data.masking_view_dict_multiattach,
                self.data.extra_specs)
            mock_return.assert_called_once()

    def test_pre_multiattach_next_gen(self):
        with mock.patch.object(utils.VMAXUtils, 'truncate_string',
                               return_value='DiamondDSS'):
            self.mask.pre_multiattach(
                self.data.array, self.data.device_id,
                self.data.masking_view_dict_multiattach, self.data.extra_specs)
            utils.VMAXUtils.truncate_string.assert_called_once_with(
                'DiamondDSS', 10)

    @mock.patch.object(rest.VMAXRest, 'get_storage_group_list',
                       side_effect=[{'storageGroupId': [
                           VMAXCommonData.no_slo_sg_name]}, {}])
    @mock.patch.object(masking.VMAXMasking,
                       '_return_volume_to_fast_managed_group')
    def test_check_return_volume_to_fast_managed_group(
            self, mock_return, mock_sg):
        for x in range(0, 2):
            self.mask.return_volume_to_fast_managed_group(
                self.data.array, self.data.device_id, self.data.extra_specs)
        no_slo_specs = deepcopy(self.data.extra_specs)
        no_slo_specs[utils.SLO] = None
        self.mask.return_volume_to_fast_managed_group(
            self.data.array, self.data.device_id, no_slo_specs)
        mock_return.assert_called_once()

    @mock.patch.object(masking.VMAXMasking, '_move_vol_from_default_sg')
    @mock.patch.object(masking.VMAXMasking, '_clean_up_child_storage_group')
    @mock.patch.object(masking.VMAXMasking, 'add_child_sg_to_parent_sg')
    @mock.patch.object(masking.VMAXMasking, '_get_or_create_storage_group')
    @mock.patch.object(rest.VMAXRest, 'get_storage_groups_from_volume',
                       side_effect=[[VMAXCommonData.no_slo_sg_name],
                                    [VMAXCommonData.storagegroup_name_f]])
    def test_return_volume_to_fast_managed_group(
            self, mock_sg, mock_get, mock_add, mock_clean, mock_move):
        for x in range(0, 2):
            self.mask._return_volume_to_fast_managed_group(
                self.data.array, self.data.device_id,
                self.data.parent_sg_f, self.data.storagegroup_name_f,
                self.data.no_slo_sg_name, self.data.extra_specs)
        mock_get.assert_called_once()
        mock_clean.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'delete_storage_group')
    @mock.patch.object(rest.VMAXRest, 'remove_child_sg_from_parent_sg')
    @mock.patch.object(rest.VMAXRest, 'is_child_sg_in_parent_sg',
                       side_effect=[False, True])
    @mock.patch.object(rest.VMAXRest, 'get_num_vols_in_sg',
                       side_effect=[2, 0, 0])
    @mock.patch.object(rest.VMAXRest, 'get_storage_group', side_effect=[
        None, 'child_sg', 'child_sg', 'child_sg'])
    def test_clean_up_child_storage_group(
            self, mock_sg, mock_num, mock_child, mock_rm, mock_del):
        # Storage group not found
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_num.assert_not_called()
        # Storage group not empty
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_child.assert_not_called()
        # Storage group not child
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_rm.assert_not_called()
        # Storage group is child, and empty
        self.mask._clean_up_child_storage_group(
            self.data.array, self.data.storagegroup_name_f,
            self.data.parent_sg_f, self.data.extra_specs)
        mock_rm.assert_called_once()
        self.assertEqual(2, mock_del.call_count)


class VMAXCommonReplicationTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXCommonReplicationTest, self).setUp()
        self.replication_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True'}
        volume_utils.get_max_over_subscription_ratio = mock.Mock()

        configuration = FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.replication_device)
        rest.VMAXRest._establish_rest_session = mock.Mock(
            return_value=FakeRequestsSession())
        driver = fc.VMAXFCDriver(configuration=configuration)
        iscsi_config = FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_i],
            replication_device=self.replication_device)
        iscsi_driver = iscsi.VMAXISCSIDriver(configuration=iscsi_config)
        self.iscsi_common = iscsi_driver.common
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.provision = self.common.provision
        self.rest = self.common.rest
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(
                return_value=self.data.vol_type_extra_specs_rep_enabled))
        self.extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        self.extra_specs['retries'] = 1
        self.extra_specs['interval'] = 1
        self.extra_specs['rep_mode'] = 'Synchronous'
        self.async_rep_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True', 'mode': 'async'}
        async_configuration = FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.async_rep_device)
        self.async_driver = fc.VMAXFCDriver(configuration=async_configuration)
        self.metro_rep_device = {
            'target_device_id': self.data.remote_array,
            'remote_port_group': self.data.port_group_name_f,
            'remote_pool': self.data.srp2,
            'rdf_group_label': self.data.rdf_group_name,
            'allow_extend': 'True', 'mode': 'metro'}
        metro_configuration = FakeConfiguration(
            None, 'CommonReplicationTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.metro_rep_device)
        self.metro_driver = fc.VMAXFCDriver(configuration=metro_configuration)

    def test_get_replication_info(self):
        self.common._get_replication_info()
        self.assertTrue(self.common.replication_enabled)

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=False)
    @mock.patch.object(objects.Group, 'get_by_id',
                       return_value=VMAXCommonData.test_rep_group)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    @mock.patch.object(utils.VMAXUtils, 'check_replication_matched',
                       return_value=True)
    @mock.patch.object(masking.VMAXMasking, 'add_volume_to_storage_group')
    @mock.patch.object(
        common.VMAXCommon, '_replicate_volume',
        return_value=({
            'replication_driver_data':
                VMAXCommonData.test_volume.replication_driver_data}, {}))
    def test_create_replicated_volume(self, mock_rep, mock_add, mock_match,
                                      mock_check, mock_get, mock_cg):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        vol_identifier = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        self.common.create_volume(self.data.test_volume)
        volume_dict = self.data.provider_location
        mock_rep.assert_called_once_with(
            self.data.test_volume, vol_identifier, volume_dict,
            extra_specs)
        # Add volume to replication group
        self.common.create_volume(self.data.test_volume_group_member)
        mock_add.assert_called_once()

    def test_create_cloned_replicated_volume(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.common, '_replicate_volume',
                               return_value=({}, {})) as mock_rep:
            self.common.create_cloned_volume(
                self.data.test_clone_volume, self.data.test_volume)
            volume_dict = self.data.provider_location
            mock_rep.assert_called_once_with(
                self.data.test_clone_volume,
                self.data.test_clone_volume.name, volume_dict, extra_specs)

    def test_create_replicated_volume_from_snap(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        with mock.patch.object(self.common, '_replicate_volume',
                               return_value=({}, {})) as mock_rep:
            self.common.create_volume_from_snapshot(
                self.data.test_clone_volume, self.data.test_snapshot)
            volume_dict = self.data.provider_location
            mock_rep.assert_called_once_with(
                self.data.test_clone_volume,
                "snapshot-%s" % self.data.snapshot_id,
                volume_dict,
                extra_specs)

    def test_replicate_volume(self):
        volume_dict = self.data.provider_location
        rs_enabled = fields.ReplicationStatus.ENABLED
        with mock.patch.object(self.common, 'setup_volume_replication',
                               return_value=(rs_enabled, {}, {}))\
                as mock_setup:
            self.common._replicate_volume(
                self.data.test_volume, "1", volume_dict, self.extra_specs)
            mock_setup.assert_called_once_with(
                self.data.array, self.data.test_volume,
                self.data.device_id, self.extra_specs)

    def test_replicate_volume_exception(self):
        volume_dict = self.data.provider_location
        with mock.patch.object(
                self.common, 'setup_volume_replication',
                side_effect=exception.VolumeBackendAPIException(data='')):
            with mock.patch.object(
                    self.common, '_cleanup_replication_source') as mock_clean:
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.common._replicate_volume,
                                  self.data.test_volume,
                                  "1", volume_dict, self.extra_specs)
                mock_clean.assert_called_once_with(
                    self.data.array, self.data.test_volume, "1",
                    volume_dict, self.extra_specs)

    @mock.patch.object(common.VMAXCommon, '_remove_members')
    @mock.patch.object(common.VMAXCommon,
                       '_get_replication_extra_specs',
                       return_value=VMAXCommonData.rep_extra_specs)
    @mock.patch.object(utils.VMAXUtils, 'is_volume_failed_over',
                       return_value=True)
    def test_unmap_lun_volume_failed_over(self, mock_fo, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(common.VMAXCommon, '_remove_members')
    @mock.patch.object(common.VMAXCommon,
                       '_get_replication_extra_specs',
                       return_value=VMAXCommonData.rep_extra_specs)
    @mock.patch.object(utils.VMAXUtils, 'is_metro_device', return_value=True)
    def test_unmap_lun_metro(self, mock_md, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        self.assertEqual(2, mock_rm.call_count)

    @mock.patch.object(utils.VMAXUtils, 'is_volume_failed_over',
                       return_value=True)
    def test_initialize_connection_vol_failed_over(self, mock_fo):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_extra_specs = deepcopy(VMAXCommonData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        with mock.patch.object(self.common, '_get_replication_extra_specs',
                               return_value=rep_extra_specs) as mock_es:
            self.common.initialize_connection(
                self.data.test_volume, self.data.connector)
            mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(utils.VMAXUtils, 'is_metro_device', return_value=True)
    def test_initialize_connection_vol_metro(self, mock_md):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'metro_hostlunid': 3}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(rest.VMAXRest, 'get_iscsi_ip_address_and_iqn',
                       return_value=([VMAXCommonData.ip],
                                     VMAXCommonData.initiator))
    @mock.patch.object(common.VMAXCommon, '_get_replication_extra_specs',
                       return_value=VMAXCommonData.rep_extra_specs)
    @mock.patch.object(utils.VMAXUtils, 'is_metro_device', return_value=True)
    def test_initialize_connection_vol_metro_iscsi(self, mock_md, mock_es,
                                                   mock_ip):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'ip_and_iqn': [{'ip': self.data.ip,
                                    'iqn': self.data.initiator}],
                    'metro_hostlunid': 3,
                    'is_multipath': True,
                    'metro_ip_and_iqn': [{'ip': self.data.ip,
                                          'iqn': self.data.initiator}]}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(utils.VMAXUtils, 'is_metro_device', return_value=True)
    def test_initialize_connection_no_multipath_iscsi(self, mock_md):
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, self.data.connector)
        self.assertIsNone(info_dict)

    @mock.patch.object(
        masking.VMAXMasking, 'pre_multiattach',
        return_value=VMAXCommonData.masking_view_dict_multiattach)
    def test_attach_metro_volume(self, mock_pre):
        rep_extra_specs = deepcopy(VMAXCommonData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        hostlunid, remote_port_group = self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, False,
            self.data.extra_specs, rep_extra_specs)
        self.assertEqual(self.data.port_group_name_f, remote_port_group)
        # Multiattach case
        self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, True,
            self.data.extra_specs, rep_extra_specs)
        mock_pre.assert_called_once()

    @mock.patch.object(rest.VMAXRest, 'is_vol_in_rep_session',
                       return_value=(False, False, None))
    @mock.patch.object(common.VMAXCommon, 'extend_volume_is_replicated')
    @mock.patch.object(common.VMAXCommon, '_sync_check')
    def test_extend_volume_rep_enabled(self, mock_sync, mock_ex_re,
                                       mock_is_re):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        volume_name = self.data.test_volume.name
        self.common.extend_volume(self.data.test_volume, '5')
        mock_ex_re.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.device_id, volume_name, "5", extra_specs)

    def test_set_config_file_get_extra_specs_rep_enabled(self):
        extra_specs, _ = self.common._set_config_file_and_get_extra_specs(
            self.data.test_volume)
        self.assertTrue(extra_specs['replication_enabled'])

    def test_populate_masking_dict_is_re(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_dict = self.common._populate_masking_dict(
            self.data.test_volume, self.data.connector, extra_specs)
        self.assertTrue(masking_dict['replication_enabled'])
        self.assertEqual('OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG-RE',
                         masking_dict[utils.SG_NAME])

    @mock.patch.object(common.VMAXCommon,
                       '_replicate_volume',
                       return_value=({}, {}))
    def test_manage_existing_is_replicated(self, mock_rep):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        external_ref = {u'source-name': u'00002'}
        volume_name = self.utils.get_volume_element_name(
            self.data.test_volume.id)
        provider_location = {'device_id': u'00002', 'array': self.data.array}
        with mock.patch.object(
                self.common, '_check_lun_valid_for_cinder_management'):
            self.common.manage_existing(
                self.data.test_volume, external_ref)
            mock_rep.assert_called_once_with(
                self.data.test_volume, volume_name, provider_location,
                extra_specs, delete_src=False)

    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_setup_volume_replication(self, mock_rm):
        rep_status, rep_data, __ = self.common.setup_volume_replication(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.extra_specs)
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id}, rep_data)

    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    @mock.patch.object(common.VMAXCommon, '_create_volume')
    def test_setup_volume_replication_target(self, mock_create, mock_rm):
        rep_status, rep_data, __ = self.common.setup_volume_replication(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.extra_specs, self.data.device_id2)
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id2}, rep_data)
        mock_create.assert_not_called()

    @mock.patch.object(common.VMAXCommon, '_cleanup_remote_target')
    def test_cleanup_lun_replication_success(self, mock_clean):
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common.cleanup_lun_replication(
            self.data.test_volume, "1", self.data.device_id,
            self.extra_specs)
        mock_clean.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_no, "1",
            rep_extra_specs)
        # Cleanup legacy replication
        self.common.cleanup_lun_replication(
            self.data.test_legacy_vol, "1", self.data.device_id,
            self.extra_specs)
        mock_clean.assert_called_once_with(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_no, "1",
            rep_extra_specs)

    @mock.patch.object(common.VMAXCommon, '_cleanup_remote_target')
    def test_cleanup_lun_replication_no_target(self, mock_clean):
        with mock.patch.object(self.common, 'get_remote_target_device',
                               return_value=(None, '', '', '', '')):
            self.common.cleanup_lun_replication(
                self.data.test_volume, "1", self.data.device_id,
                self.extra_specs)
            mock_clean.assert_not_called()

    @mock.patch.object(
        common.VMAXCommon, 'get_remote_target_device',
        return_value=(VMAXCommonData.device_id2, '', '', '', ''))
    @mock.patch.object(common.VMAXCommon,
                       '_add_volume_to_async_rdf_managed_grp')
    def test_cleanup_lun_replication_exception(self, mock_add, mock_tgt):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.cleanup_lun_replication,
                          self.data.test_volume, "1", self.data.device_id,
                          self.extra_specs)
        # is metro or async volume
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_METRO
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.cleanup_lun_replication,
                          self.data.test_volume, "1", self.data.device_id,
                          extra_specs)
        mock_add.assert_called_once()

    @mock.patch.object(common.VMAXCommon, '_cleanup_metro_target')
    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    @mock.patch.object(common.VMAXCommon, '_delete_from_srp')
    @mock.patch.object(provision.VMAXProvision, 'break_rdf_relationship')
    def test_cleanup_remote_target(self, mock_break, mock_del,
                                   mock_rm, mock_clean_metro):
        with mock.patch.object(self.rest, 'are_vols_rdf_paired',
                               return_value=(False, '', '')):
            self.common._cleanup_remote_target(
                self.data.array, self.data.test_volume,
                self.data.remote_array, self.data.device_id,
                self.data.device_id2, self.data.rdf_group_name,
                "vol1", self.data.rep_extra_specs)
            mock_break.assert_not_called()
        self.common._cleanup_remote_target(
            self.data.array, self.data.test_volume,
            self.data.remote_array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_name,
            "vol1", self.data.rep_extra_specs)
        mock_break.assert_called_once_with(
            self.data.array, self.data.device_id,
            self.data.device_id2, self.data.rdf_group_name,
            self.data.rep_extra_specs, "Synchronized")
        # is metro volume
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            self.common._cleanup_remote_target(
                self.data.array, self.data.test_volume,
                self.data.remote_array, self.data.device_id,
                self.data.device_id2, self.data.rdf_group_name,
                "vol1", self.data.rep_extra_specs)
            mock_clean_metro.assert_called_once()

    def test_cleanup_remote_target_exception(self):
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs['mode'] = utils.REP_METRO
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.metro_driver.common._cleanup_remote_target,
                          self.data.array, self.data.test_volume,
                          self.data.remote_array,
                          self.data.device_id, self.data.device_id2,
                          self.data.rdf_group_name, "vol1", extra_specs)

    @mock.patch.object(provision.VMAXProvision, 'enable_group_replication')
    @mock.patch.object(rest.VMAXRest, 'get_num_vols_in_sg',
                       side_effect=[2, 0])
    def test_cleanup_metro_target(self, mock_vols, mock_enable):
        # allow delete is True
        specs = {'allow_del_metro': True}
        for x in range(0, 2):
            self.common._cleanup_metro_target(
                self.data.array, self.data.device_id, self.data.device_id2,
                self.data.rdf_group_no, specs)
            mock_enable.assert_called_once()
        # allow delete is False
        specs['allow_del_metro'] = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._cleanup_metro_target,
                          self.data.array, self.data.device_id,
                          self.data.device_id2,
                          self.data.rdf_group_no, specs)

    @mock.patch.object(common.VMAXCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    @mock.patch.object(common.VMAXCommon, '_delete_from_srp')
    def test_cleanup_replication_source(self, mock_del, mock_rm, mock_clean):
        self.common._cleanup_replication_source(
            self.data.array, self.data.test_volume, "vol1",
            {'device_id': self.data.device_id}, self.extra_specs)
        mock_del.assert_called_once_with(
            self.data.array, self.data.device_id, "vol1", self.extra_specs)

    def test_get_rdf_details(self):
        rdf_group_no, remote_array = self.common.get_rdf_details(
            self.data.array)
        self.assertEqual(self.data.rdf_group_no, rdf_group_no)
        self.assertEqual(self.data.remote_array, remote_array)

    def test_get_rdf_details_exception(self):
        with mock.patch.object(self.rest, 'get_rdf_group_number',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.get_rdf_details, self.data.array)

    def test_failover_host(self):
        volumes = [self.data.test_volume, self.data.test_clone_volume]
        with mock.patch.object(self.common, '_failover_replication',
                               return_value=(None, {})) as mock_fo:
            self.common.failover_host(volumes)
            mock_fo.assert_called_once()

    @mock.patch.object(common.VMAXCommon, 'failover_replication',
                       return_value=({}, {}))
    def test_failover_host_groups(self, mock_fg):
        volumes = [self.data.test_volume_group_member]
        group1 = self.data.test_group
        self.common.failover_host(volumes, None, [group1])
        mock_fg.assert_called_once()

    def test_get_remote_target_device(self):
        target_device1, _, _, _, _ = (
            self.common.get_remote_target_device(
                self.data.array, self.data.test_volume, self.data.device_id))
        self.assertEqual(self.data.device_id2, target_device1)
        target_device2, _, _, _, _ = (
            self.common.get_remote_target_device(
                self.data.array, self.data.test_clone_volume,
                self.data.device_id))
        self.assertIsNone(target_device2)
        with mock.patch.object(self.rest, 'are_vols_rdf_paired',
                               return_value=(False, '')):
            target_device3, _, _, _, _ = (
                self.common.get_remote_target_device(
                    self.data.array, self.data.test_volume,
                    self.data.device_id))
            self.assertIsNone(target_device3)
        with mock.patch.object(self.rest, 'get_volume',
                               return_value=None):
            target_device4, _, _, _, _ = (
                self.common.get_remote_target_device(
                    self.data.array, self.data.test_volume,
                    self.data.device_id))
            self.assertIsNone(target_device4)

    @mock.patch.object(common.VMAXCommon, 'setup_volume_replication')
    @mock.patch.object(provision.VMAXProvision, 'extend_volume')
    @mock.patch.object(provision.VMAXProvision, 'break_rdf_relationship')
    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_extend_volume_is_replicated(self, mock_remove,
                                         mock_break, mock_extend, mock_setup):
        self.common.extend_volume_is_replicated(
            self.data.array, self.data.test_volume, self.data.device_id,
            'vol1', '5', self.data.extra_specs_rep_enabled)
        self.assertEqual(2, mock_remove.call_count)
        self.assertEqual(2, mock_extend.call_count)
        mock_remove.reset_mock()
        mock_extend.reset_mock()
        with mock.patch.object(self.rest, 'is_next_gen_array',
                               return_value=True):
            self.common.extend_volume_is_replicated(
                self.data.array, self.data.test_volume, self.data.device_id,
                'vol1', '5', self.data.extra_specs_rep_enabled)
            mock_remove.assert_not_called()
            self.assertEqual(2, mock_extend.call_count)

    def test_extend_volume_is_replicated_exception(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.extend_volume_is_replicated,
                          self.data.failed_resource, self.data.test_volume,
                          self.data.device_id, 'vol1', '1',
                          self.data.extra_specs_rep_enabled)
        with mock.patch.object(self.utils, 'is_metro_device',
                               return_value=True):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.extend_volume_is_replicated,
                              self.data.array, self.data.test_volume,
                              self.data.device_id, 'vol1', '1',
                              self.data.extra_specs_rep_enabled)

    @mock.patch.object(common.VMAXCommon, 'add_volume_to_replication_group')
    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_enable_rdf(self, mock_remove, mock_add):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.common.enable_rdf(
            self.data.array, self.data.test_volume, self.data.device_id,
            self.data.rdf_group_no, rep_config, 'OS-1',
            self.data.remote_array, self.data.device_id2, self.extra_specs)
        self.assertEqual(2, mock_remove.call_count)
        self.assertEqual(2, mock_add.call_count)

    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    @mock.patch.object(common.VMAXCommon, '_cleanup_remote_target')
    def test_enable_rdf_exception(self, mock_cleanup, mock_rm):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        self.assertRaises(
            exception.VolumeBackendAPIException, self.common.enable_rdf,
            self.data.array, self.data.test_volume, self.data.device_id,
            self.data.failed_resource, rep_config, 'OS-1',
            self.data.remote_array, self.data.device_id2, self.extra_specs)
        self.assertEqual(1, mock_cleanup.call_count)

    def test_add_volume_to_replication_group(self):
        sg_name = self.common.add_volume_to_replication_group(
            self.data.array, self.data.device_id, 'vol1',
            self.extra_specs)
        self.assertEqual(self.data.default_sg_re_enabled, sg_name)

    @mock.patch.object(masking.VMAXMasking,
                       'get_or_create_default_storage_group',
                       side_effect=exception.VolumeBackendAPIException)
    def test_add_volume_to_replication_group_exception(self, mock_get):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common.add_volume_to_replication_group,
            self.data.array, self.data.device_id, 'vol1',
            self.extra_specs)

    def test_get_replication_extra_specs(self):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        # Path one - disable compression
        extra_specs1 = deepcopy(self.extra_specs)
        extra_specs1[utils.DISABLECOMPRESSION] = "true"
        ref_specs1 = deepcopy(self.data.rep_extra_specs2)
        rep_extra_specs1 = self.common._get_replication_extra_specs(
            extra_specs1, rep_config)
        self.assertEqual(ref_specs1, rep_extra_specs1)
        # Path two - disable compression, not all flash
        ref_specs2 = deepcopy(self.data.rep_extra_specs2)
        with mock.patch.object(self.rest, 'is_compression_capable',
                               return_value=False):
            rep_extra_specs2 = self.common._get_replication_extra_specs(
                extra_specs1, rep_config)
        self.assertEqual(ref_specs2, rep_extra_specs2)
        # Path three - slo not valid
        extra_specs3 = deepcopy(self.extra_specs)
        ref_specs3 = deepcopy(ref_specs1)
        ref_specs3['slo'] = None
        ref_specs3['workload'] = None
        with mock.patch.object(self.provision, 'verify_slo_workload',
                               return_value=(False, False)):
            rep_extra_specs3 = self.common._get_replication_extra_specs(
                extra_specs3, rep_config)
        self.assertEqual(ref_specs3, rep_extra_specs3)

    def test_get_secondary_stats(self):
        rep_config = self.utils.get_replication_config(
            [self.replication_device])
        array_map = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_map)
        array_info = finalarrayinfolist[0]
        ref_info = deepcopy(array_info)
        ref_info['SerialNumber'] = six.text_type(rep_config['array'])
        ref_info['srpName'] = rep_config['srp']
        secondary_info = self.common.get_secondary_stats_info(
            rep_config, array_info)
        self.assertEqual(ref_info, secondary_info)

    def test_replicate_group(self):
        volume_model_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location}
        vols_model_update = self.common._replicate_group(
            self.data.array, [volume_model_update],
            self.data.test_vol_grp_name, self.extra_specs)
        ref_rep_data = {'array': self.data.remote_array,
                        'device_id': self.data.device_id2}
        ref_vol_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location,
            'replication_driver_data': ref_rep_data,
            'replication_status': fields.ReplicationStatus.ENABLED}

        # Decode string representations of dicts into dicts, because
        # the string representations are randomly ordered and therefore
        # hard to compare.
        vols_model_update[0]['replication_driver_data'] = ast.literal_eval(
            vols_model_update[0]['replication_driver_data'])

        self.assertEqual(ref_vol_update, vols_model_update[0])

    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_create_replicaton_group(self, mock_type, mock_cg_type):
        ref_model_update = {
            'status': fields.GroupStatus.AVAILABLE,
            'replication_status': fields.ReplicationStatus.ENABLED}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)
        # Replication mode is async
        self.assertRaises(exception.InvalidInput,
                          self.async_driver.common.create_group,
                          None, self.data.test_group_1)

    def test_enable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.enable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully enabled
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_disable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.disable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully disabled
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.DISABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_failover_replication(self):
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 1: Empty group
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 2: Successfully failed over
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                             model_update['replication_status'])
            # Case 3: Successfully failed back
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [self.data.test_volume],
                secondary_backend_id='default')
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    @mock.patch.object(provision.VMAXProvision, 'failover_group')
    def test_failover_replication_metro(self, mock_fo):
        volumes = [self.data.test_volume]
        _, vol_model_updates = self.common._failover_replication(
            volumes, group, None, host=True, is_metro=True)
        mock_fo.assert_not_called()

    @mock.patch.object(utils.VMAXUtils, 'get_volume_group_utils',
                       return_value=(VMAXCommonData.array, {}))
    @mock.patch.object(common.VMAXCommon, '_cleanup_group_replication')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_delete_replication_group(self, mock_check,
                                      mock_cleanup, mock_utils):
        self.common._delete_group(self.data.test_rep_group, [])
        mock_cleanup.assert_called_once()

    @mock.patch.object(masking.VMAXMasking,
                       'remove_volumes_from_storage_group')
    @mock.patch.object(utils.VMAXUtils, 'check_rep_status_enabled')
    @mock.patch.object(common.VMAXCommon,
                       '_remove_remote_vols_from_volume_group')
    @mock.patch.object(masking.VMAXMasking, 'add_remote_vols_to_volume_group')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_replicated_group(self, mock_cg_type, mock_type_check,
                                     mock_add, mock_remove, mock_check,
                                     mock_rm):
        add_vols = [self.data.test_volume]
        remove_vols = [self.data.test_clone_volume]
        self.common.update_group(
            self.data.test_group_1, add_vols, remove_vols)
        mock_add.assert_called_once()
        mock_remove.assert_called_once()

    @mock.patch.object(masking.VMAXMasking,
                       'remove_volumes_from_storage_group')
    def test_remove_remote_vols_from_volume_group(self, mock_rm):
        self.common._remove_remote_vols_from_volume_group(
            self.data.remote_array, [self.data.test_volume],
            self.data.test_rep_group, self.data.rep_extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    @mock.patch.object(masking.VMAXMasking,
                       'remove_volumes_from_storage_group')
    def test_cleanup_group_replication(self, mock_rm, mock_rm_reset):
        self.common._cleanup_group_replication(
            self.data.array, self.data.test_vol_grp_name,
            [self.data.device_id], self.extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(masking.VMAXMasking, 'add_volume_to_storage_group')
    def test_add_volume_to_async_group(self, mock_add):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        self.async_driver.common._add_volume_to_async_rdf_managed_grp(
            self.data.array, self.data.device_id, 'name',
            self.data.remote_array, self.data.device_id2, extra_specs)
        self.assertEqual(2, mock_add.call_count)

    def test_add_volume_to_async_group_exception(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.async_driver.common._add_volume_to_async_rdf_managed_grp,
            self.data.failed_resource, self.data.device_id, 'name',
            self.data.remote_array, self.data.device_id2, extra_specs)

    @mock.patch.object(common.VMAXCommon,
                       '_add_volume_to_async_rdf_managed_grp')
    @mock.patch.object(masking.VMAXMasking, 'remove_and_reset_members')
    def test_setup_volume_replication_async(self, mock_rm, mock_add):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        rep_status, rep_data, __ = (
            self.async_driver.common.setup_volume_replication(
                self.data.array, self.data.test_volume,
                self.data.device_id, extra_specs))
        self.assertEqual(fields.ReplicationStatus.ENABLED, rep_status)
        self.assertEqual({'array': self.data.remote_array,
                          'device_id': self.data.device_id}, rep_data)
        mock_add.assert_called_once()

    @mock.patch.object(common.VMAXCommon, '_failover_replication',
                       return_value=({}, {}))
    def test_failover_host_async(self, mock_fg):
        volumes = [self.data.test_volume]
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        with mock.patch.object(common.VMAXCommon, '_initial_setup',
                               return_value=extra_specs):
            self.async_driver.common.failover_host(volumes, None, [])
        mock_fg.assert_called_once()

    @mock.patch.object(common.VMAXCommon, '_retype_volume', return_value=True)
    @mock.patch.object(masking.VMAXMasking, 'remove_vol_from_storage_group')
    @mock.patch.object(common.VMAXCommon, '_retype_remote_volume',
                       return_value=True)
    @mock.patch.object(common.VMAXCommon, 'setup_volume_replication',
                       return_value=(
                           '', VMAXCommonData.provider_location2, ''))
    @mock.patch.object(common.VMAXCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(utils.VMAXUtils, 'is_replication_enabled',
                       side_effect=[False, True, True, False, True, True])
    def test_migrate_volume_replication(self, mock_re, mock_rm_rep,
                                        mock_setup, mock_retype,
                                        mock_rm, mock_rt):
        new_type = {'extra_specs': {}}
        for x in range(0, 3):
            success, model_update = self.common._migrate_volume(
                self.data.array, self.data.test_volume, self.data.device_id,
                self.data.srp, 'OLTP', 'Silver', self.data.test_volume.name,
                new_type, self.data.extra_specs)
            self.assertTrue(success)
        mock_rm_rep.assert_called_once()
        mock_setup.assert_called_once()
        mock_retype.assert_called_once()

    @mock.patch.object(
        common.VMAXCommon, '_get_replication_extra_specs',
        return_value=VMAXCommonData.extra_specs_rep_enabled)
    @mock.patch.object(
        rest.VMAXRest, 'get_storage_groups_from_volume',
        side_effect=[
            VMAXCommonData.storagegroup_list, ['OS-SRP_1-Diamond-DSS-RE-SG']])
    @mock.patch.object(common.VMAXCommon, '_retype_volume', return_value=True)
    def test_retype_volume_replication(self, mock_retype, mock_sg, mock_es):
        for x in range(0, 2):
            self.common._retype_remote_volume(
                self.data.array, self.data.test_volume, self.data.device_id,
                self.data.test_volume.name, utils.REP_SYNC,
                True, self.data.extra_specs)
        mock_retype.assert_called_once()


class VMAXVolumeMetadataNoDebugTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXVolumeMetadataNoDebugTest, self).setUp()
        is_debug = False
        self.volume_metadata = metadata.VMAXVolumeMetadata(
            rest.VMAXRest, '3.1', is_debug)

    @mock.patch.object(metadata.VMAXVolumeMetadata, '_fill_volume_trace_dict',
                       return_value={})
    def test_gather_volume_info(self, mock_fvtd):
        self.volume_metadata.gather_volume_info(
            self.data.volume_id, 'create', False, volume_size=1)
        mock_fvtd.assert_not_called()


class VMAXVolumeMetadataDebugTest(test.TestCase):
    def setUp(self):
        self.data = VMAXCommonData()

        super(VMAXVolumeMetadataDebugTest, self).setUp()
        is_debug = True
        self.volume_metadata = metadata.VMAXVolumeMetadata(
            rest.VMAXRest, '3.1', is_debug)
        self.utils = self.volume_metadata.utils
        self.rest = self.volume_metadata.rest

    @mock.patch.object(metadata.VMAXVolumeMetadata, '_fill_volume_trace_dict',
                       return_value={})
    def test_gather_volume_info(self, mock_fvtd):
        self.volume_metadata.gather_volume_info(
            self.data.volume_id, 'create', False, volume_size=1)
        mock_fvtd.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_attach_info(self, mock_uvim):
        self.volume_metadata.capture_attach_info(
            self.data.test_volume, self.data.extra_specs,
            self.data.masking_view_dict, self.data.fake_host,
            False, False)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_create_volume(self, mock_uvim):
        self.volume_metadata.capture_create_volume(
            self.data.device_id, self.data.test_volume, "test_group",
            "test_group_id", self.data.extra_specs, {}, 'create', None)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_delete_info(self, mock_uvim):
        self.volume_metadata.capture_delete_info(self.data.test_volume)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_manage_existing(self, mock_uvim):
        self.volume_metadata.capture_manage_existing(
            self.data.test_volume, {}, self.data.device_id,
            self.data.extra_specs)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_failover_volume(self, mock_uvim):
        self.volume_metadata.capture_failover_volume(
            self.data.test_volume, self.data.device_id2,
            self.data.remote_array, self.data.rdf_group_name,
            self.data.device_id, self.data.array,
            self.data.extra_specs, True, None,
            fields.ReplicationStatus.FAILED_OVER, utils.REP_SYNC)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_modify_group(self, mock_uvim):
        self.volume_metadata.capture_modify_group(
            "test_group", "test_group_id", [self.data.test_volume],
            [], self.data.array)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_extend_info(self, mock_uvim):
        self.volume_metadata.capture_extend_info(
            self.data.test_volume, 5, self.data.device_id,
            self.data.extra_specs, self.data.array)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_detach_info(self, mock_uvim):
        self.volume_metadata.capture_detach_info(
            self.data.test_volume, self.data.extra_specs, self.data.device_id,
            None, None)
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_snapshot_info(self, mock_uvim):
        self.volume_metadata.capture_snapshot_info(
            self.data.test_volume, self.data.extra_specs, 'createSnapshot',
            'ss-test-vol')
        mock_uvim.assert_called_once()

    @mock.patch.object(metadata.VMAXVolumeMetadata,
                       'update_volume_info_metadata',
                       return_value={})
    def test_capture_retype_info(self, mock_uvim):
        self.volume_metadata.capture_retype_info(
            self.data.test_volume, self.data.device_id, self.data.array,
            self.data.srp, self.data.slo, self.data.workload,
            self.data.storagegroup_name_target, False, None,
            False)
        mock_uvim.assert_called_once()

    def test_update_volume_info_metadata(self):
        volume_metadata = self.volume_metadata.update_volume_info_metadata(
            self.data.data_dict, self.data.version_dict)
        self.assertEqual('2.7.12', volume_metadata['python_version'])
        self.assertEqual('VMAX250F', volume_metadata['vmax_model'])
        self.assertEqual('DSS', volume_metadata['workload'])
        self.assertEqual('OS-fibre-PG', volume_metadata['port_group'])

    def test_fill_volume_trace_dict(self):
        datadict = {}
        volume_trace_dict = {}
        volume_key_value = {}
        result_dict = {'operation': 'create',
                       'volume_id': self.data.test_volume.id}
        volume_metadata = self.volume_metadata._fill_volume_trace_dict(
            self.data.test_volume.id, 'create', False, target_name=None,
            datadict=datadict, volume_key_value=volume_key_value,
            volume_trace_dict=volume_trace_dict)
        self.assertEqual(result_dict, volume_metadata)

    def test_fill_volume_trace_dict_multi_attach(self):
        mv_list = ['mv1', 'mv2', 'mv3']
        sg_list = ['sg1', 'sg2', 'sg3']
        datadict = {}
        volume_trace_dict = {}
        volume_key_value = {}
        result_dict = {'masking_view_1': 'mv1',
                       'masking_view_2': 'mv2',
                       'masking_view_3': 'mv3',
                       'operation': 'attach',
                       'storage_group_1': 'sg1',
                       'storage_group_2': 'sg2',
                       'storage_group_3': 'sg3',
                       'volume_id': self.data.test_volume.id}
        volume_metadata = self.volume_metadata._fill_volume_trace_dict(
            self.data.test_volume.id, 'attach', False, target_name=None,
            datadict=datadict, volume_trace_dict=volume_trace_dict,
            volume_key_value=volume_key_value, mv_list=mv_list,
            sg_list=sg_list)
        self.assertEqual(result_dict, volume_metadata)

    @mock.patch.object(utils.VMAXUtils, 'merge_dicts',
                       return_value={})
    def test_consolidate_volume_trace_list(self, mock_m2d):
        self.volume_metadata.volume_trace_list = [self.data.data_dict]
        volume_trace_dict = {'volume_updated_time': '2018-03-06 16:51:40',
                             'operation': 'delete',
                             'volume_id': self.data.volume_id}
        volume_key_value = {self.data.volume_id: volume_trace_dict}
        self.volume_metadata._consolidate_volume_trace_list(
            self.data.volume_id, volume_trace_dict, volume_key_value)
        mock_m2d.assert_called_once()

    def test_merge_dicts_multiple(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'c': 3, 'd': 4}
        d3 = {'e': 5, 'f': 6}
        res_d = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6}
        result_dict = self.utils.merge_dicts(
            d1, d2, d3)
        self.assertEqual(res_d, result_dict)

    def test_merge_dicts_multiple_2(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'b': 3, 'd': 4}
        d3 = {'d': 5, 'e': 6}
        res_d = {'a': 1, 'b': 2, 'd': 4, 'e': 6}
        result_dict = self.utils.merge_dicts(
            d1, d2, d3)
        self.assertEqual(res_d, result_dict)

    def test_merge_dicts(self):
        self.volume_metadata.volume_trace_list = [self.data.data_dict]
        volume_trace_dict = {'volume_updated_time': '2018-03-06 16:51:40',
                             'operation': 'delete',
                             'volume_id': self.data.volume_id}
        result_dict = self.utils.merge_dicts(
            volume_trace_dict, self.data.volume_info_dict)
        self.assertEqual('delete', result_dict['operation'])
        self.assertEqual(
            '2018-03-06 16:51:40', result_dict['volume_updated_time'])
        self.assertEqual('OS-fibre-PG', result_dict['port_group'])

    @mock.patch.object(platform, 'platform',
                       return_value=VMAXCommonData.platform)
    @mock.patch.object(platform, 'python_version',
                       return_value=VMAXCommonData.python_version)
    @mock.patch.object(openstack_version.version_info, 'version_string',
                       return_value=VMAXCommonData.openstack_version)
    @mock.patch.object(openstack_version.version_info, 'release_string',
                       return_value=VMAXCommonData.openstack_release)
    @mock.patch.object(rest.VMAXRest, 'get_unisphere_version',
                       return_value={
                           'version': VMAXCommonData.unisphere_version})
    @mock.patch.object(rest.VMAXRest, 'get_array_serial',
                       return_value={
                           'ucode': VMAXCommonData.vmax_firmware_version,
                           'model': VMAXCommonData.vmax_model})
    def test_gather_version_info(
            self, mock_vi, mock_ur, mock_or, mock_ov, mock_pv, mock_p):
        self.volume_metadata.gather_version_info(self.data.array)
        self.assertEqual(
            self.data.version_dict, self.volume_metadata.version_dict)
