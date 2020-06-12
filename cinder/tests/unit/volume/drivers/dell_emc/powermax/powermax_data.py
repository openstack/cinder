# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
import six

from cinder import context
from cinder.objects import fields
from cinder.objects import group
from cinder.objects import group_snapshot
from cinder.objects import volume_attachment
from cinder.objects import volume_type
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.dell_emc.powermax import utils

CINDER_EMC_CONFIG_DIR = '/etc/cinder/'


class PowerMaxData(object):
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
    device_id4 = '00004'
    rdf_group_name = '23_24_007'
    rdf_group_no = '70'
    u4v_version = '90'
    storagegroup_name_source = 'Grp_source_sg'
    storagegroup_name_target = 'Grp_target_sg'
    group_snapshot_name = 'Grp_snapshot'
    target_group_name = 'Grp_target'
    storagegroup_name_with_id = 'GrpId_group_name'
    rdf_managed_async_grp = 'OS-%s-Asynchronous-rdf-sg' % rdf_group_name
    volume_id = '2b06255d-f5f0-4520-a953-b029196add6a'
    no_slo_sg_name = 'OS-HostX-No_SLO-OS-fibre-PG'
    temp_snapvx = 'temp-00001-snapshot_for_clone'

    # connector info
    wwpn1 = '123456789012345'
    wwpn2 = '123456789054321'
    wwnn1 = '223456789012345'
    initiator = 'iqn.1993-08.org.debian: 01: 222'
    ip, ip2 = u'123.456.7.8', u'123.456.7.9'
    iqn = u'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000001,t,0x0001'
    iqn2 = u'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000002,t,0x0001'
    connector = {'ip': ip,
                 'initiator': initiator,
                 'wwpns': [wwpn1, wwpn2],
                 'wwnns': [wwnn1],
                 'host': 'HostX'}

    fabric_name_prefix = 'fakeFabric'
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

    # snapshot info
    snapshot_id = '390eeb4d-0f56-4a02-ba14-167167967014'
    snapshot_display_id = 'my_snap'
    managed_snap_id = 'OS-390eeb4d-0f56-4a02-ba14-167167967014'
    test_snapshot_snap_name = 'OS-' + snapshot_id[:6] + snapshot_id[-9:]

    snap_location = {'snap_name': test_snapshot_snap_name,
                     'source_id': device_id}

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
    provider_location_clone = {'array': array,
                               'device_id': device_id,
                               'snap_name': temp_snapvx,
                               'source_device_id': device_id}
    provider_location_snapshot = {'array': array,
                                  'device_id': device_id,
                                  'snap_name': test_snapshot_snap_name,
                                  'source_device_id': device_id}

    provider_location5 = {'array': remote_array,
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
        id='4732de9b-98a4-4b6d-ae4b-3cafb3d34220', context=ctx, name='vol1',
        size=0, provider_auth=None, attach_status='attached',
        provider_location=six.text_type(provider_location), host=fake_host,
        volume_type=test_volume_type,
        replication_driver_data=six.text_type(provider_location3))

    test_legacy_vol = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(legacy_provider_location),
        replication_driver_data=six.text_type(legacy_provider_location2),
        host=fake_host, volume_type=test_volume_type)

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
        'storagetype:disablecompression': 'true'}
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

    extra_specs_migrate = deepcopy(extra_specs)
    extra_specs_migrate[utils.PORTGROUPNAME] = port_group_name_f

    extra_specs_disable_compression = deepcopy(extra_specs)
    extra_specs_disable_compression[utils.DISABLECOMPRESSION] = 'true'
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
    rep_extra_specs3 = deepcopy(rep_extra_specs)
    rep_extra_specs3['slo'] = slo
    rep_extra_specs3['workload'] = workload
    rep_extra_specs4 = deepcopy(rep_extra_specs3)
    rep_extra_specs4['rdf_group_label'] = rdf_group_name
    rep_extra_specs5 = deepcopy(rep_extra_specs2)
    rep_extra_specs5['target_array_model'] = 'VMAX250F'

    test_volume_type_1 = volume_type.VolumeType(
        id='2b06255d-f5f0-4520-a953-b029196add6a', name='abc',
        extra_specs=extra_specs)

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
    compression_info = {'symmetrixId': ['000197800128']}
    inititiatorgroup = [{'initiator': [wwpn1],
                         'hostId': initiatorgroup_name_f,
                         'maskingview': [masking_view_name_f]},
                        {'initiator': [initiator],
                         'hostId': initiatorgroup_name_i,
                         'maskingview': [masking_view_name_i]}]

    initiator_list = [{'host': initiatorgroup_name_f,
                       'initiatorId': wwpn1,
                       'maskingview': [masking_view_name_f]},
                      {'host': initiatorgroup_name_i,
                       'initiatorId': initiator,
                       'maskingview': [masking_view_name_i]},
                      {'initiatorId': [
                          'FA-1D:4:' + wwpn1,
                          'SE-4E:0:' + initiator]}]

    maskingview = [{'maskingViewId': masking_view_name_f,
                    'portGroupId': port_group_name_f,
                    'storageGroupId': storagegroup_name_f,
                    'hostId': initiatorgroup_name_f,
                    'maskingViewConnection': [
                        {'host_lun_address': '0003'}]},
                   {'maskingViewId': masking_view_name_i,
                    'portGroupId': port_group_name_i,
                    'storageGroupId': storagegroup_name_i,
                    'hostId': initiatorgroup_name_i,
                    'maskingViewConnection': [
                        {'host_lun_address': '0003'}]},
                   {}]

    portgroup = [{'portGroupId': port_group_name_f,
                  'symmetrixPortKey': [
                      {'directorId': 'FA-1D',
                       'portId': 'FA-1D:4'}],
                  'maskingview': [masking_view_name_f]},
                 {'portGroupId': port_group_name_i,
                  'symmetrixPortKey': [
                      {'directorId': 'SE-4E',
                       'portId': 'SE-4E:0'}],
                  'maskingview': [masking_view_name_i]}]

    port_list = [
        {'symmetrixPort': {'num_of_masking_views': 1,
                           'maskingview': [masking_view_name_f],
                           'identifier': wwnn1,
                           'symmetrixPortKey': {
                               'directorId': 'FA-1D',
                               'portId': '4'},
                           'portgroup': [port_group_name_f]}},
        {'symmetrixPort': {'identifier': initiator,
                           'symmetrixPortKey': {
                               'directorId': 'SE-4E',
                               'portId': '0'},
                           'ip_addresses': [ip],
                           'num_of_masking_views': 1,
                           'maskingview': [masking_view_name_i],
                           'portgroup': [port_group_name_i]}}]

    sg_details = [{'srp': srp,
                   'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': defaultstoragegroup_name,
                   'slo': slo,
                   'workload': workload},
                  {'srp': srp,
                   'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': storagegroup_name_f,
                   'slo': slo,
                   'workload': workload,
                   'maskingview': [masking_view_name_f],
                   'parent_storage_group': [parent_sg_f]},
                  {'srp': srp,
                   'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': storagegroup_name_i,
                   'slo': slo,
                   'workload': workload,
                   'maskingview': [masking_view_name_i],
                   'parent_storage_group': [parent_sg_i]},
                  {'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': parent_sg_f,
                   'num_of_child_sgs': 1,
                   'child_storage_group': [storagegroup_name_f],
                   'maskingview': [masking_view_name_f]},
                  {'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': parent_sg_i,
                   'num_of_child_sgs': 1,
                   'child_storage_group': [storagegroup_name_i],
                   'maskingview': [masking_view_name_i], },
                  {'srp': srp,
                   'num_of_vols': 2,
                   'cap_gb': 2,
                   'storageGroupId': no_slo_sg_name,
                   'slo': None,
                   'workload': None,
                   'maskingview': [masking_view_name_i],
                   'parent_storage_group': [parent_sg_i]}
                  ]

    sg_details_rep = [{'childNames': [],
                       'numDevicesNonGk': 2,
                       'isLinkTarget': False,
                       'rdf': True,
                       'capacityGB': 2.0,
                       'name': storagegroup_name_source,
                       'snapVXSnapshots': ['6560405d-752f5a139'],
                       'symmetrixId': array,
                       'numSnapVXSnapshots': 1}]

    sg_rdf_details = [{'storageGroupName': test_vol_grp_name,
                       'symmetrixId': array,
                       'modes': ['Synchronous'],
                       'rdfGroupNumber': rdf_group_no,
                       'states': ['Synchronized']},
                      {'storageGroupName': test_fo_vol_group,
                       'symmetrixId': array,
                       'modes': ['Synchronous'],
                       'rdfGroupNumber': rdf_group_no,
                       'states': ['Failed Over']}]

    sg_list = {'storageGroupId': [storagegroup_name_f,
                                  defaultstoragegroup_name]}

    sg_list_rep = [storagegroup_name_with_id]

    srp_details = {'srp_capacity': {u'subscribed_total_tb': 93.52,
                                    u'usable_used_tb': 8.62,
                                    u'usable_total_tb': 24.45,
                                    u'snapshot_modified_tb': 0.0,
                                    u'subscribed_allocated_tb': 18.77,
                                    u'snapshot_total_tb': 1.58},
                   'srpId': srp,
                   'reserved_cap_percent': 10}

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

    volume_details = [{'cap_gb': 2,
                       'num_of_storage_groups': 1,
                       'volumeId': device_id,
                       'volume_identifier': 'OS-%s' % test_volume.id,
                       'wwn': volume_wwn,
                       'snapvx_target': 'false',
                       'snapvx_source': 'false',
                       'storageGroupId': [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {'cap_gb': 1,
                       'num_of_storage_groups': 1,
                       'volumeId': device_id2,
                       'volume_identifier': 'OS-%s' % test_volume.id,
                       'wwn': '600012345',
                       'storageGroupId': [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {'cap_gb': 1,
                       'num_of_storage_groups': 0,
                       'volumeId': device_id3,
                       'volume_identifier': '123',
                       'wwn': '600012345'},
                      {'cap_gb': 1,
                       'num_of_storage_groups': 1,
                       'volumeId': device_id4,
                       'volume_identifier': 'random_name',
                       'wwn': '600012345',
                       'storageGroupId': ['random_sg_1',
                                          'random_sg_2']},
                      ]

    volume_details_attached = {'cap_gb': 2,
                               'num_of_storage_groups': 1,
                               'volumeId': device_id,
                               'volume_identifier': 'OS-%s' % test_volume.id,
                               'wwn': volume_wwn,
                               'snapvx_target': 'false',
                               'snapvx_source': 'false',
                               'storageGroupId': [storagegroup_name_f]}

    volume_details_no_sg = {'cap_gb': 2,
                            'num_of_storage_groups': 1,
                            'volumeId': device_id,
                            'volume_identifier': 'OS-%s' % test_volume.id,
                            'wwn': volume_wwn,
                            'snapvx_target': 'false',
                            'snapvx_source': 'false',
                            'storageGroupId': []}

    volume_details_legacy = {'cap_gb': 2,
                             'num_of_storage_groups': 1,
                             'volumeId': device_id,
                             'volume_identifier': test_volume.id,
                             'wwn': volume_wwn,
                             'snapvx_target': 'false',
                             'snapvx_source': 'false',
                             'storageGroupId': []}

    volume_list = [
        {'id': '6b70de13-98c5-46b2-8f24-e4e96a8988fa',
         'count': 2,
         'maxPageSize': 1,
         'resultList': {'result': [{'volumeId': device_id}],
                        'from': 0, 'to': 1}},
        {'resultList': {'result': [{'volumeId': device_id2}]}},
        {'id': '6b70de13-98c5-46b2-8f24-e4e96a8988fa',
         'count': 2,
         'maxPageSize': 1,
         'resultList': {'result': [{'volumeId': device_id},
                                   {'volumeId': device_id2}],
                        'from': 0, 'to': 1}}]

    private_vol_details = {
        'id': '6b70de13-98c5-46b2-8f24-e4e96a8988fa',
        'count': 2,
        'maxPageSize': 1,
        'resultList': {
            'result': [{
                'timeFinderInfo': {
                    'snapVXSession': [
                        {'srcSnapshotGenInfo': [
                            {'snapshotHeader': {
                                'snapshotName': 'temp-1',
                                'device': device_id,
                                'generation': '0'},
                                'lnkSnapshotGenInfo': [
                                    {'targetDevice': device_id2,
                                     'state': 'Copied'}]}]},
                        {'tgtSrcSnapshotGenInfo': {
                            'snapshotName': 'temp-1',
                            'targetDevice': device_id2,
                            'sourceDevice': device_id,
                            'generation': '0',
                            'state': 'Copied'}}],
                    'snapVXSrc': 'true',
                    'snapVXTgt': 'true'},
                'rdfInfo': {'RDFSession': [
                    {'SRDFStatus': 'Ready',
                     'pairState': 'Synchronized',
                     'remoteDeviceID': device_id2,
                     'remoteSymmetrixID': remote_array}]}}],
            'from': 0, 'to': 1}}

    # Service Levels / Workloads
    workloadtype = {'workloadId': ['OLTP', 'OLTP_REP', 'DSS', 'DSS_REP']}
    srp_slo_details = {'serviceLevelDemand': [
        {'serviceLevelId': 'None'}, {'serviceLevelId': 'Diamond'},
        {'serviceLevelId': 'Gold'}, {'serviceLevelId': 'Optimized'}]}
    slo_details = ['None', 'Diamond', 'Gold', 'Optimized']
    powermax_slo_details = {'sloId': ['Bronze', 'Diamond', 'Gold',
                                      'Optimized', 'Platinum', 'Silver']}
    powermax_model_details = {'symmetrixId': array,
                              'model': 'PowerMax_2000',
                              'ucode': '5978.1091.1092'}
    vmax_slo_details = {'sloId': ['Diamond', 'Optimized']}
    vmax_model_details = {'model': 'VMAX450F'}

    # replication
    volume_snap_vx = {'snapshotLnks': [],
                      'snapshotSrc': [
                          {'generation': 0,
                           'linkedDevices': [
                               {'targetDevice': device_id2,
                                'percentageCopied': 100,
                                'state': 'Copied',
                                'copy': True,
                                'defined': True,
                                'linked': True}],
                           'snapshotName': test_snapshot_snap_name,
                           'state': 'Established'}]}
    capabilities = {'symmetrixCapability': [{'rdfCapable': True,
                                             'snapVxCapable': True,
                                             'symmetrixId': '0001111111'},
                                            {'symmetrixId': array,
                                             'snapVxCapable': True,
                                             'rdfCapable': True}]}
    group_snap_vx = {'generation': 0,
                     'isLinked': False,
                     'numUniqueTracks': 0,
                     'isRestored': False,
                     'name': group_snapshot_name,
                     'numStorageGroupVolumes': 1,
                     'state': ['Established'],
                     'timeToLiveExpiryDate': 'N/A',
                     'isExpired': False,
                     'numSharedTracks': 0,
                     'timestamp': '00:30:50 Fri, 02 Jun 2017 IST +0100',
                     'numSourceVolumes': 1
                     }
    group_snap_vx_1 = {'generation': 0,
                       'isLinked': False,
                       'numUniqueTracks': 0,
                       'isRestored': False,
                       'name': group_snapshot_name,
                       'numStorageGroupVolumes': 1,
                       'state': ['Copied'],
                       'timeToLiveExpiryDate': 'N/A',
                       'isExpired': False,
                       'numSharedTracks': 0,
                       'timestamp': '00:30:50 Fri, 02 Jun 2017 IST +0100',
                       'numSourceVolumes': 1,
                       'linkedStorageGroup':
                           {'name': target_group_name,
                            'percentageCopied': 100},
                       }
    grp_snapvx_links = [{'name': target_group_name,
                         'percentageCopied': 100},
                        {'name': 'another-target',
                         'percentageCopied': 90}]

    rdf_group_list = {'rdfGroupID': [{'rdfgNumber': rdf_group_no,
                                      'label': rdf_group_name}]}
    rdf_group_details = {'modes': ['Synchronous'],
                         'remoteSymmetrix': remote_array,
                         'label': rdf_group_name,
                         'type': 'Dynamic',
                         'numDevices': 1,
                         'remoteRdfgNumber': rdf_group_no,
                         'rdfgNumber': rdf_group_no}
    rdf_group_vol_details = {'remoteRdfGroupNumber': rdf_group_no,
                             'localSymmetrixId': array,
                             'volumeConfig': 'RDF1+TDEV',
                             'localRdfGroupNumber': rdf_group_no,
                             'localVolumeName': device_id,
                             'rdfpairState': 'Synchronized',
                             'remoteVolumeName': device_id2,
                             'localVolumeState': 'Ready',
                             'rdfMode': 'Synchronous',
                             'remoteVolumeState': 'Write Disabled',
                             'remoteSymmetrixId': remote_array}

    # system
    job_list = [{'status': 'SUCCEEDED',
                 'jobId': '12345',
                 'result': 'created',
                 'resourceLink': 'storagegroup/%s' % storagegroup_name_f},
                {'status': 'RUNNING', 'jobId': '55555'},
                {'status': 'FAILED', 'jobId': '09999'}]
    symmetrix = [{'symmetrixId': array,
                  'model': 'VMAX250F',
                  'ucode': '5977.1091.1092'},
                 {'symmetrixId': array_herc,
                  'model': 'PowerMax 2000',
                  'ucode': '5978.1091.1092'}]
    version_details = {'version': 'V9.0.0.1'}

    headroom = {'headroom': [{'headroomCapacity': 20348.29}]}

    p_vol_rest_response_single = {
        'id': 'f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0', 'count': 1,
        'expirationTime': 1521650650793, 'maxPageSize': 1000,
        'resultList': {'to': 1, 'from': 1, 'result': [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00001',
                'status': 'Ready', 'configuration': 'TDEV'}}]}}
    p_vol_rest_response_none = {
        'id': 'f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0', 'count': 0,
        'expirationTime': 1521650650793, 'maxPageSize': 1000,
        'resultList': {'to': 0, 'from': 0, 'result': []}}
    p_vol_rest_response_iterator_1 = {
        'id': 'f3aab01c-a5a8-4fb4-af2b-16ae1c46dc9e_0', 'count': 1500,
        'expirationTime': 1521650650793, 'maxPageSize': 1000,
        'resultList': {'to': 1, 'from': 1, 'result': [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00002',
                'status': 'Ready', 'configuration': 'TDEV'}}]}}
    p_vol_rest_response_iterator_2 = {
        'to': 2000, 'from': 1001, 'result': [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00001',
                'status': 'Ready', 'configuration': 'TDEV'}}]}
    rest_iterator_resonse_one = {
        'to': 1000, 'from': 1, 'result': [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00001',
                'status': 'Ready', 'configuration': 'TDEV'}}]}
    rest_iterator_resonse_two = {
        'to': 1500, 'from': 1001, 'result': [
            {'volumeHeader': {
                'capGB': 1.0, 'capMB': 1026.0, 'volumeId': '00002',
                'status': 'Ready', 'configuration': 'TDEV'}}]}

    # COMMON.PY
    priv_vol_func_response_single = [
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {
                'mirror': False, 'snapVXTgt': False,
                'cloneTarget': False, 'cloneSrc': False,
                'snapVXSrc': True, 'snapVXSession': [
                    {'srcSnapshotGenInfo': [
                        {'snapshotHeader': {
                            'timestamp': 1512763278000, 'expired': False,
                            'secured': False, 'snapshotName': 'testSnap1',
                            'device': '00001', 'generation': 0, 'timeToLive': 0
                        }}]}]}}]

    priv_vol_func_response_multi = [
        {'volumeHeader': {
            'private': False, 'capGB': 100.0, 'capMB': 102400.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'maskingInfo': {'masked': False},
            'timeFinderInfo': {
                'mirror': False, 'snapVXTgt': False,
                'cloneTarget': False, 'cloneSrc': False,
                'snapVXSrc': True, 'snapVXSession': [
                    {'srcSnapshotGenInfo': [
                        {'snapshotHeader': {
                            'timestamp': 1512763278000, 'expired': False,
                            'secured': False, 'snapshotName': 'testSnap1',
                            'device': '00001', 'generation': 0, 'timeToLive': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 200.0, 'capMB': 204800.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00002', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00002',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'maskingInfo': {'masked': False},
            'timeFinderInfo': {
                'mirror': False, 'snapVXTgt': False,
                'cloneTarget': False, 'cloneSrc': False,
                'snapVXSrc': True, 'snapVXSession': [
                    {'srcSnapshotGenInfo': [
                        {'snapshotHeader': {
                            'timestamp': 1512763278000, 'expired': False,
                            'secured': False, 'snapshotName': 'testSnap2',
                            'device': '00002', 'generation': 0, 'timeToLive': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 300.0, 'capMB': 307200.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00003', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00003',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'maskingInfo': {'masked': False},
            'timeFinderInfo': {
                'mirror': False, 'snapVXTgt': False,
                'cloneTarget': False, 'cloneSrc': False,
                'snapVXSrc': True, 'snapVXSession': [
                    {'srcSnapshotGenInfo': [
                        {'snapshotHeader': {
                            'timestamp': 1512763278000, 'expired': False,
                            'secured': False, 'snapshotName': 'testSnap3',
                            'device': '00003', 'generation': 0, 'timeToLive': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 400.0, 'capMB': 409600.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00004', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00004',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'maskingInfo': {'masked': False},
            'timeFinderInfo': {
                'mirror': False, 'snapVXTgt': False,
                'cloneTarget': False, 'cloneSrc': False,
                'snapVXSrc': True, 'snapVXSession': [
                    {'srcSnapshotGenInfo': [
                        {'snapshotHeader': {
                            'timestamp': 1512763278000, 'expired': False,
                            'secured': False, 'snapshotName': 'testSnap4',
                            'device': '00004', 'generation': 0, 'timeToLive': 0
                        }}]}]}}]

    priv_vol_func_response_multi_invalid = [
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 10.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': False, 'snapVXSrc': False}},
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00002', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00002',
            'system_resource': False, 'numSymDevMaskingViews': 1,
            'nameModifier': "", 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': False, 'snapVXSrc': False}},
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'CKD',
            'volumeId': '00003', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00003',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': False, 'snapVXSrc': False}},
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00004', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00004',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': True, 'snapVXSrc': False}},
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00005', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00005',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': 'OS-vol', 'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': False, 'snapVXSrc': False}}]

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
        'unisphere_for_powermax_version': unisphere_version,
        'openstack_release': openstack_release,
        'openstack_version': openstack_version,
        'python_version': python_version,
        'powermax_cinder_driver_version': vmax_driver_version,
        'openstack_platform': platform,
        'storage_firmware_version': vmax_firmware_version,
        'serial_number': array,
        'storage_model': vmax_model}

    u4p_failover_config = {
        'u4p_failover_backoff_factor': '2',
        'u4p_failover_retries': '3',
        'u4p_failover_timeout': '10',
        'u4p_primary': '10.10.10.10',
        'u4p_failover_autofailback': 'True',
        'u4p_failover_targets': [
            {'san_ip': '10.10.10.11',
             'san_api_port': '8443',
             'san_login': 'test',
             'san_password': 'test',
             'driver_ssl_cert_verify': '/path/to/cert',
             'driver_ssl_cert_path': 'True'},
            {'san_ip': '10.10.10.12',
             'san_api_port': '8443',
             'san_login': 'test',
             'san_password': 'test',
             'driver_ssl_cert_verify': 'True'},
            {'san_ip': '10.10.10.11',
             'san_api_port': '8443',
             'san_login': 'test',
             'san_password': 'test',
             'driver_ssl_cert_verify': '/path/to/cert',
             'driver_ssl_cert_path': 'False'}]}

    u4p_failover_target = [{
        'RestServerIp': '10.10.10.11',
        'RestServerPort': '8443',
        'RestUserName': 'test',
        'RestPassword': 'test',
        'SSLVerify': '/path/to/cert'},
        {'RestServerIp': '10.10.10.12',
         'RestServerPort': '8443',
         'RestUserName': 'test',
         'RestPassword': 'test',
         'SSLVerify': 'True'}]

    staging_sg = 'STG-myhostB-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-SG'
    staging_mv1 = 'STG-myhostA-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-MV'
    staging_mv2 = 'STG-myhostB-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-MV'
    staging_mvs = [staging_mv1, staging_mv2]
    legacy_mv1 = 'OS-myhostA-No_SLO-e14f48b8-MV'
    legacy_mv2 = 'OS-myhostB-No_SLO-e14f48b8-MV'
    legacy_shared_sg = 'OS-myhostA-No_SLO-SG'
    legacy_mvs = [legacy_mv1, legacy_mv2]
    legacy_not_shared_mv = 'OS-myhostA-SRP_1-Diamond-NONE-MV'
    legacy_not_shared_sg = 'OS-myhostA-SRP_1-Diamond-NONE-SG'
