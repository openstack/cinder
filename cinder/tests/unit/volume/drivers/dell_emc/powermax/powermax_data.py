# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
import random

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
    array_model = 'PowerMax_8000'
    srp = 'SRP_1'
    slo = 'Diamond'
    slo_diamond = 'Diamond'
    slo_silver = 'Silver'
    workload = 'DSS'
    port_group_name_f = 'OS-fibre-PG'
    port_group_name_i = 'OS-iscsi-PG'
    masking_view_name_f = 'OS-HostX-F-OS-fibre-PG-MV'
    masking_view_name_Y_f = 'OS-HostY-F-OS-fibre-PG-MV'
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
    default_sg_no_slo_re_enabled = 'OS-SRP_1-Diamond-NONE-RE-SG'
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
    rdf_group_name_1 = '23_24_007'
    rdf_group_name_2 = '23_24_008'
    rdf_group_name_3 = '23_24_009'
    rdf_group_name_4 = '23_24_010'
    rdf_group_no_1 = '70'
    rdf_group_no_2 = '71'
    rdf_group_no_3 = '72'
    rdf_group_no_4 = '73'
    u4v_version = '92'
    storagegroup_name_source = 'Grp_source_sg'
    storagegroup_name_target = 'Grp_target_sg'
    group_snapshot_name = 'Grp_snapshot'
    target_group_name = 'Grp_target'
    storagegroup_name_with_id = 'GrpId_group_name'
    rdf_managed_async_grp = 'OS-%s-Asynchronous-rdf-sg' % rdf_group_name_1
    default_sg_re_managed_list = [default_sg_re_enabled, rdf_managed_async_grp]
    volume_id = '2b06255d-f5f0-4520-a953-b029196add6a'
    no_slo_sg_name = 'OS-HostX-No_SLO-OS-fibre-PG'
    temp_snapvx = 'temp-00001-snapshot_for_clone'
    next_gen_ucode = 5978
    gvg_group_id = 'test-gvg'
    sg_tags = 'production,test'
    snap_id = 118749976833
    snap_id_2 = 118749976834

    # connector info
    wwpn1 = '123456789012345'
    wwpn2 = '123456789054321'
    wwnn1 = '223456789012345'
    wwnn2 = '223456789012346'
    initiator = 'iqn.1993-08.org.debian:01:222'
    iscsi_dir = 'SE-4E'
    iscsi_port = '1'
    ip, ip2 = '123.456.7.8', '123.456.7.9'
    iqn = 'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000001'
    iqn2 = 'iqn.1992-04.com.emc:600009700bca30c01e3e012e00000002'
    connector = {'ip': ip,
                 'initiator': initiator,
                 'wwpns': [wwpn1, wwpn2],
                 'wwnns': [wwnn1],
                 'host': 'HostX'}

    fabric_name_prefix = 'fakeFabric'
    end_point_map = {connector['wwpns'][0]: [wwnn1],
                     connector['wwpns'][1]: [wwnn1]}
    target_wwns = [wwnn1]
    target_wwns_multi = [wwnn1, wwnn2]
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

    iscsi_dir_port = '%(dir)s:%(port)s' % {'dir': iscsi_dir,
                                           'port': iscsi_port}
    iscsi_dir_virtual_port = '%(dir)s:%(port)s' % {'dir': iscsi_dir,
                                                   'port': '000'}
    iscsi_device_info = {'maskingview': masking_view_name_i,
                         'ip_and_iqn': [{'ip': ip,
                                         'iqn': initiator,
                                         'physical_port': iscsi_dir_port}],
                         'is_multipath': True,
                         'array': array,
                         'controller': {'host': '10.00.00.00'},
                         'hostlunid': 3,
                         'device_id': device_id}
    iscsi_device_info_metro = deepcopy(iscsi_device_info)
    iscsi_device_info_metro['metro_ip_and_iqn'] = [{
        'ip': ip2, 'iqn': iqn2, 'physical_port': iscsi_dir_port}]
    iscsi_device_info_metro['metro_hostlunid'] = 2

    fc_device_info = {'maskingview': masking_view_name_f,
                      'array': array,
                      'controller': {'host': '10.00.00.00'},
                      'hostlunid': 3}

    director_port_keys_empty = {'symmetrixPortKey': []}
    director_port_keys_multiple = {'symmetrixPortKey': [
        {'directorId': 'SE-1E', 'portId': '1'},
        {'directorId': 'SE-1E', 'portId': '2'}]}

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

    replication_update = (
        {'replication_status': 'enabled',
         'replication_driver_data': six.text_type(
             {'array': remote_array, 'device_id': device_id2})})

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

    test_rep_volume = fake_volume.fake_volume_obj(
        context=ctx, name='vol1', size=2, provider_auth=None,
        provider_location=six.text_type(provider_location),
        volume_type=test_volume_type, host=fake_host,
        replication_driver_data=six.text_type(provider_location3),
        replication_status=fields.ReplicationStatus.ENABLED)

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
        connector=connector, attached_host='HostX')

    location_info = {'location_info': '000197800123#SRP_1#Diamond#DSS',
                     'storage_protocol': 'FC'}
    test_host = {'capabilities': location_info,
                 'host': fake_host}

    # replication
    rep_backend_id_sync = 'rep_backend_id_sync'
    rep_backend_id_async = 'rep_backend_id_async'
    rep_backend_id_metro = 'rep_backend_id_metro'
    rep_backend_id_sync_2 = 'rep_backend_id_sync_2'

    rep_dev_1 = {
        utils.BACKEND_ID: rep_backend_id_sync,
        'target_device_id': remote_array,
        'remote_port_group': port_group_name_f,
        'remote_pool': srp,
        'rdf_group_label': rdf_group_name_1,
        'mode': utils.REP_SYNC,
        'allow_extend': True}
    rep_dev_2 = {
        utils.BACKEND_ID: rep_backend_id_async,
        'target_device_id': remote_array,
        'remote_port_group': port_group_name_f,
        'remote_pool': srp,
        'rdf_group_label': rdf_group_name_2,
        'mode': utils.REP_ASYNC,
        'allow_extend': True}
    rep_dev_3 = {
        utils.BACKEND_ID: rep_backend_id_metro,
        'target_device_id': remote_array,
        'remote_port_group': port_group_name_f,
        'remote_pool': srp,
        'rdf_group_label': rdf_group_name_3,
        'mode': utils.REP_METRO,
        'allow_extend': True}
    sync_rep_device = [rep_dev_1]
    async_rep_device = [rep_dev_2]
    metro_rep_device = [rep_dev_3]
    multi_rep_device = [rep_dev_1, rep_dev_2, rep_dev_3]

    rep_config_sync = {
        utils.BACKEND_ID: rep_backend_id_sync,
        'array': remote_array,
        'portgroup': port_group_name_f,
        'srp': srp,
        'rdf_group_label': rdf_group_name_1,
        'mode': utils.REP_SYNC,
        'allow_extend': True,
        'sync_interval': 3,
        'sync_retries': 200}
    rep_config_async = {
        utils.BACKEND_ID: rep_backend_id_async,
        'array': remote_array,
        'portgroup': port_group_name_f,
        'srp': srp,
        'rdf_group_label': rdf_group_name_2,
        'mode': utils.REP_ASYNC,
        'allow_extend': True,
        'sync_interval': 3,
        'sync_retries': 200}
    rep_config_metro = {
        utils.BACKEND_ID: rep_backend_id_metro,
        'array': remote_array,
        'portgroup': port_group_name_f,
        'srp': srp,
        'rdf_group_label': rdf_group_name_3,
        'mode': utils.REP_METRO,
        'allow_extend': True,
        'sync_interval': 3,
        'sync_retries': 200}
    rep_config_sync_2 = {
        utils.BACKEND_ID: rep_backend_id_sync_2,
        'array': remote_array,
        'portgroup': port_group_name_f,
        'srp': srp,
        'rdf_group_label': rdf_group_name_1,
        'mode': utils.REP_SYNC,
        'allow_extend': True,
        'sync_interval': 3,
        'sync_retries': 200}
    sync_rep_config_list = [rep_config_sync]
    async_rep_config_list = [rep_config_async]
    metro_rep_config_list = [rep_config_metro]
    multi_rep_config_list = [rep_config_sync, rep_config_async,
                             rep_config_metro, rep_config_sync_2]

    # extra-specs
    vol_type_extra_specs = {'pool_name': u'Diamond+DSS+SRP_1+000197800123'}
    vol_type_extra_specs_none_pool = {
        'pool_name': u'None+NONE+SRP_1+000197800123'}
    vol_type_extra_specs_optimised_pool = {
        'pool_name': u'Optimized+NONE+SRP_1+000197800123'}
    vol_type_extra_specs_next_gen_pool = {
        'pool_name': u'Optimized+SRP_1+000197800123'}
    vol_type_extra_specs_compr_disabled = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'storagetype:disablecompression': 'true'}
    vol_type_extra_specs_rep_enabled = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'replication_enabled': '<is> True'}
    vol_type_extra_specs_rep_enabled_backend_id_sync = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'replication_enabled': '<is> True',
        utils.REPLICATION_DEVICE_BACKEND_ID: rep_backend_id_sync}
    vol_type_extra_specs_rep_enabled_backend_id_sync_2 = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'replication_enabled': '<is> True',
        utils.REPLICATION_DEVICE_BACKEND_ID: rep_backend_id_sync_2}
    vol_type_extra_specs_rep_enabled_backend_id_async = {
        'pool_name': u'Diamond+DSS+SRP_1+000197800123',
        'replication_enabled': '<is> True',
        utils.REPLICATION_DEVICE_BACKEND_ID: rep_backend_id_async}
    extra_specs = {'pool_name': u'Diamond+DSS+SRP_1+000197800123',
                   'slo': slo,
                   'workload': workload,
                   'srp': srp,
                   'array': array,
                   'interval': 3,
                   'retries': 120}
    extra_specs_optimized = {
        'pool_name': u'Optimized+None+SRP_1+000197800123',
        'slo': 'Optimized', 'workload': 'None',
        'srp': srp, 'array': array, 'interval': 3, 'retries': 120}

    vol_type_extra_specs_tags = {
        'storagetype:storagegrouptags': u'good, comma,  separated,list'}
    vol_type_extra_specs_tags_bad = {
        'storagetype:storagegrouptags': u'B&d, [list]'}
    extra_specs_port_group_template = deepcopy(extra_specs)
    extra_specs_port_group_template['port_group_template'] = 'portGroupName'
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
    rep_extra_specs['srp'] = srp
    rep_extra_specs['rep_mode'] = 'Synchronous'
    rep_extra_specs['sync_interval'] = 3
    rep_extra_specs['sync_retries'] = 200
    rep_extra_specs['rdf_group_label'] = rdf_group_name_1
    rep_extra_specs['rdf_group_no'] = rdf_group_no_1
    rep_extra_specs2 = deepcopy(rep_extra_specs)
    rep_extra_specs2[utils.PORTGROUPNAME] = port_group_name_f
    rep_extra_specs3 = deepcopy(rep_extra_specs)
    rep_extra_specs3['slo'] = slo
    rep_extra_specs3['workload'] = workload
    rep_extra_specs4 = deepcopy(rep_extra_specs3)
    rep_extra_specs4['rdf_group_label'] = rdf_group_name_1
    rep_extra_specs5 = deepcopy(rep_extra_specs2)
    rep_extra_specs5['target_array_model'] = 'VMAX250F'
    rep_extra_specs5['sync_interval'] = 3
    rep_extra_specs5['sync_retries'] = 200
    rep_extra_specs6 = deepcopy(rep_extra_specs3)
    rep_extra_specs6['target_array_model'] = 'PMAX2000'

    rep_extra_specs_ode = deepcopy(rep_extra_specs2)
    rep_extra_specs_ode['array'] = array
    rep_extra_specs_ode.pop('rep_mode')
    rep_extra_specs_ode['mode'] = 'Metro'

    rep_extra_specs_legacy = deepcopy(rep_extra_specs_ode)
    rep_extra_specs_legacy['mode'] = 'Synchronous'

    rep_extra_specs_rep_config = deepcopy(rep_extra_specs6)
    rep_extra_specs_rep_config[utils.REP_CONFIG] = rep_config_sync

    rep_extra_specs_rep_config_metro = deepcopy(rep_extra_specs6)
    rep_extra_specs_rep_config_metro[utils.REP_CONFIG] = rep_config_metro
    rep_extra_specs_rep_config_metro[utils.REP_MODE] = utils.REP_METRO

    extra_specs_tags = deepcopy(extra_specs)
    extra_specs_tags.update({utils.STORAGE_GROUP_TAGS: sg_tags})

    rep_extra_specs_mgmt = deepcopy(rep_extra_specs)
    rep_extra_specs_mgmt['srp'] = srp
    rep_extra_specs_mgmt['mgmt_sg_name'] = rdf_managed_async_grp
    rep_extra_specs_mgmt['sg_name'] = default_sg_no_slo_re_enabled
    rep_extra_specs_mgmt['rdf_group_no'] = rdf_group_no_1
    rep_extra_specs_mgmt['rdf_group_label'] = rdf_group_name_1
    rep_extra_specs_mgmt['target_array_model'] = array_model
    rep_extra_specs_mgmt['slo'] = 'Diamond'
    rep_extra_specs_mgmt['workload'] = 'NONE'
    rep_extra_specs_mgmt['sync_interval'] = 2
    rep_extra_specs_mgmt['sync_retries'] = 200

    rep_extra_specs_metro = deepcopy(rep_extra_specs)
    rep_extra_specs_metro[utils.REP_MODE] = utils.REP_METRO
    rep_extra_specs_metro[utils.METROBIAS] = True
    rep_extra_specs_metro['replication_enabled'] = '<is> True'

    rep_config = {
        'array': remote_array, 'srp': srp, 'portgroup': port_group_name_i,
        'rdf_group_no': rdf_group_no_1, 'sync_retries': 200,
        'sync_interval': 1, 'rdf_group_label': rdf_group_name_1,
        'allow_extend': True, 'mode': utils.REP_METRO}

    ex_specs_rep_config = deepcopy(rep_extra_specs_metro)
    ex_specs_rep_config['array'] = array
    ex_specs_rep_config['rep_config'] = rep_config

    ex_specs_rep_config_no_extend = deepcopy(ex_specs_rep_config)
    ex_specs_rep_config_no_extend['rep_config']['allow_extend'] = False

    test_volume_type_1 = volume_type.VolumeType(
        id='2b06255d-f5f0-4520-a953-b029196add6a', name='abc',
        extra_specs=extra_specs)

    ex_specs_rep_config_sync = deepcopy(ex_specs_rep_config)
    ex_specs_rep_config_sync[utils.REP_MODE] = utils.REP_SYNC
    ex_specs_rep_config_sync[utils.REP_CONFIG]['mode'] = utils.REP_SYNC

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

    test_rep_group2 = fake_group.fake_group_obj(
        context=ctx,
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
        'replication_enabled': False,
        'used_host_name': 'HostX',
        'port_group_label': port_group_name_f}

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

    masking_view_dict_tags = deepcopy(masking_view_dict)
    masking_view_dict_tags.update(
        {'tag_list': sg_tags})

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
                       'portId': '4'}],
                  'maskingview': [masking_view_name_f]},
                 {'portGroupId': port_group_name_i,
                  'symmetrixPortKey': [
                      {'directorId': 'SE-4E',
                       'portId': '0'}],
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
                       'rdfGroupNumber': rdf_group_no_1,
                       'states': ['Synchronized']},
                      {'storageGroupName': test_fo_vol_group,
                       'symmetrixId': array,
                       'modes': ['Synchronous'],
                       'rdfGroupNumber': rdf_group_no_1,
                       'states': ['Failed Over']}]

    sg_rdf_group_details = {
        "storageGroupName": test_vol_grp_name,
        "symmetrixId": array,
        "volumeRdfTypes": ["R1"],
        "modes": ["Asynchronous"],
        "totalTracks": 8205,
        "largerRdfSides": ["Equal"],
        "rdfGroupNumber": 1,
        "states": ["suspended"]}

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
                       'cap_cyl': 1092,
                       'num_of_storage_groups': 1,
                       'volumeId': device_id,
                       'volume_identifier': 'OS-%s' % test_volume.id,
                       'wwn': volume_wwn,
                       'snapvx_target': 'false',
                       'snapvx_source': 'false',
                       'storageGroupId': [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {'cap_gb': 1,
                       'cap_cyl': 546,
                       'num_of_storage_groups': 1,
                       'volumeId': device_id2,
                       'volume_identifier': 'OS-%s' % test_volume.id,
                       'wwn': '600012345',
                       'storageGroupId': [defaultstoragegroup_name,
                                          storagegroup_name_f]},
                      {'cap_gb': 1,
                       'cap_cyl': 546,
                       'num_of_storage_groups': 0,
                       'volumeId': device_id3,
                       'volume_identifier': '123',
                       'wwn': '600012345'},
                      {'cap_gb': 1,
                       'cap_cyl': 546,
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

    volume_details_attached_async = (
        {'cap_gb': 2,
         'num_of_storage_groups': 1,
         'volumeId': device_id,
         'volume_identifier': 'OS-%s' % test_volume.id,
         'wwn': volume_wwn,
         'snapvx_target': 'false',
         'snapvx_source': 'false',
         'storageGroupId': [
             rdf_managed_async_grp, storagegroup_name_f + '-RA']})

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
                                'snapid': snap_id},
                                'lnkSnapshotGenInfo': [
                                    {'targetDevice': device_id2,
                                     'state': 'Copied'}]}]},
                        {'tgtSrcSnapshotGenInfo': {
                            'snapshotName': 'temp-1',
                            'targetDevice': device_id2,
                            'sourceDevice': device_id,
                            'snapid': snap_id_2,
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
                      'snapshotSrcs': [
                          {'snap_id': snap_id,
                           'linkedDevices': [
                               {'targetDevice': device_id2,
                                'percentageCopied': 100,
                                'state': 'Copied',
                                'copy': True,
                                'defined': True,
                                'linked': True,
                                'snap_id': snap_id}],
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

    rdf_group_list = {'rdfGroupID': [{'rdfgNumber': rdf_group_no_1,
                                      'label': rdf_group_name_1},
                                     {'rdfgNumber': rdf_group_no_2,
                                      'label': rdf_group_name_2},
                                     {'rdfgNumber': rdf_group_no_3,
                                      'label': rdf_group_name_3},
                                     {'rdfgNumber': rdf_group_no_4,
                                      'label': rdf_group_name_4}]}
    rdf_group_details = {'modes': ['Synchronous'],
                         'remoteSymmetrix': remote_array,
                         'label': rdf_group_name_1,
                         'type': 'Dynamic',
                         'numDevices': 1,
                         'remoteRdfgNumber': rdf_group_no_1,
                         'rdfgNumber': rdf_group_no_1}
    rdf_group_vol_details = {'remoteRdfGroupNumber': rdf_group_no_1,
                             'localSymmetrixId': array,
                             'volumeConfig': 'RDF1+TDEV',
                             'localRdfGroupNumber': rdf_group_no_1,
                             'localVolumeName': device_id,
                             'rdfpairState': 'Synchronized',
                             'remoteVolumeName': device_id2,
                             'localVolumeState': 'Ready',
                             'rdfMode': 'Synchronous',
                             'remoteVolumeState': 'Write Disabled',
                             'remoteSymmetrixId': remote_array}

    rdf_group_vol_details_not_synced = {
        'remoteRdfGroupNumber': rdf_group_no_1, 'localSymmetrixId': array,
        'volumeConfig': 'RDF1+TDEV', 'localRdfGroupNumber': rdf_group_no_1,
        'localVolumeName': device_id, 'rdfpairState': 'syncinprog',
        'remoteVolumeName': device_id2, 'localVolumeState': 'Ready',
        'rdfMode': 'Synchronous', 'remoteVolumeState': 'Write Disabled',
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
    version_details = {'version': 'V9.2.0.0'}

    headroom = {'headroom': [{'headroomCapacity': 20348.29}]}

    ucode_5978_foxtail = {'ucode': '5978.435.435'}

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
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
                            'device': '00001', 'snapid': snap_id,
                            'timeToLive': 0, 'generation': 0
                        }}]}]}}]

    priv_vol_func_response_multi = [
        {'volumeHeader': {
            'private': False, 'capGB': 100.0, 'capMB': 102400.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
                            'device': '00001', 'snapid': snap_id,
                            'timeToLive': 0, 'generation': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 200.0, 'capMB': 204800.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00002', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00002',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
                            'device': '00002', 'snapid': snap_id,
                            'timeToLive': 0, 'generation': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 300.0, 'capMB': 307200.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00003', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00003',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
                            'device': '00003', 'snapid': snap_id,
                            'timeToLive': 0, 'generation': 0
                        }}]}]}},
        {'volumeHeader': {
            'private': False, 'capGB': 400.0, 'capMB': 409600.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00004', 'status': 'Ready', 'numStorageGroups': 0,
            'reservationInfo': {'reserved': False}, 'mapped': False,
            'encapsulated': False, 'formattedName': '00004',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
                            'device': '00004', 'snapid': snap_id,
                            'timeToLive': 0, 'generation': 0
                        }}]}]}}]

    priv_vol_func_response_multi_invalid = [
        {'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 10.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
            'nameModifier': "", "userDefinedIdentifier": "N/A",
            'configuration': 'TDEV'},
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
            'nameModifier': 'OS-vol', "userDefinedIdentifier": "OS-vol",
            'configuration': 'TDEV'},
            'maskingInfo': {'masked': False},
            'rdfInfo': {
                'dynamicRDF': False, 'RDF': False,
                'concurrentRDF': False,
                'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False},
            'timeFinderInfo': {'snapVXTgt': False, 'snapVXSrc': False}}]

    volume_create_info_dict = {utils.ARRAY: array, utils.DEVICE_ID: device_id}

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

    add_volume_sg_info_dict = {
        "storageGroupId": defaultstoragegroup_name,
        "slo": "Optimized",
        "service_level": "Optimized",
        "base_slo_name": "Optimized",
        "srp": "SRP_1",
        "slo_compliance": "NONE",
        "num_of_vols": 39,
        "num_of_child_sgs": 0,
        "num_of_parent_sgs": 0,
        "num_of_masking_views": 0,
        "num_of_snapshots": 0,
        "cap_gb": 109.06,
        "device_emulation": "FBA",
        "type": "Standalone",
        "unprotected": "true",
        "compression": "true",
        "compressionRatio": "1.0:1",
        "compression_ratio_to_one": 1,
        "vp_saved_percent": 99.9
    }

    storage_group_with_tags = deepcopy(add_volume_sg_info_dict)
    storage_group_with_tags.update({"tags": sg_tags})

    data_dict = {volume_id: volume_info_dict}
    platform = 'Linux-4.4.0-104-generic-x86_64-with-Ubuntu-16.04-xenial'
    unisphere_version = u'V9.2.0.0'
    unisphere_version_90 = "V9.0.0.1"
    openstack_release = '12.0.0.0b3.dev401'
    openstack_version = '12.0.0'
    python_version = '2.7.12'
    vmax_driver_version = '4.1'
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
        'SSLVerify': '/path/to/cert',
        'SerialNumber': array},
        {'RestServerIp': '10.10.10.12',
         'RestServerPort': '8443',
         'RestUserName': 'test',
         'RestPassword': 'test',
         'SSLVerify': 'True',
         'SerialNumber': array}]

    snapshot_src_details = {'snapshotSrcs': [{
        'snapshotName': 'temp-000AA-snapshot_for_clone',
        'snap_id': snap_id, 'state': 'Established', 'expired': False,
        'linkedDevices': [{'targetDevice': device_id2, 'state': 'Copied',
                           'copy': True}]},
        {'snapshotName': 'temp-000AA-snapshot_for_clone', 'snap_id': snap_id_2,
         'state': 'Established', 'expired': False,
         'linkedDevices': [{'targetDevice': device_id3, 'state': 'Copied',
                            'copy': True}]}],
        'snapshotLnks': []}

    snapshot_tgt_details = {"snapshotLnks": [{
        "linkSourceName": device_id2, "state": "Linked", "copy": False}]}

    snap_tgt_vol_details = {"timeFinderInfo": {"snapVXSession": [{
        "tgtSrcSnapshotGenInfo": {
            "snapid": snap_id, "expired": True,
            "snapshotName": "temp-000AA-snapshot_for_clone"}}]}}

    snap_tgt_session = {
        'snapid': snap_id, 'expired': False, 'copy_mode': False,
        'snap_name': 'temp-000AA-snapshot_for_clone', 'state': 'Copied',
        'source_vol_id': device_id, 'target_vol_id': device_id2}

    snap_tgt_session_cm_enabled = {
        'snapid': snap_id, 'expired': False, 'copy_mode': True,
        'snap_name': 'temp-000AA-snapshot_for_clone', 'state': 'Copied',
        'source_vol_id': device_id, 'target_vol_id': device_id2}

    snap_src_sessions = [
        {'snapid': snap_id, 'expired': False, 'copy_mode': False,
         'snap_name': 'temp-000AA-snapshot_for_clone', 'state': 'Copied',
         'source_vol_id': device_id, 'target_vol_id': device_id3},
        {'snapid': snap_id_2, 'expired': False, 'copy_mode': False,
         'snap_name': 'temp-000AA-snapshot_for_clone', 'state': 'Copied',
         'source_vol_id': device_id, 'target_vol_id': device_id4}]

    device_label = 'OS-00001'
    priv_vol_response_rep = {
        'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV',
            'userDefinedIdentifier': 'OS-00001'},
        'maskingInfo': {'masked': False},
        'rdfInfo': {
            'dynamicRDF': False, 'RDF': True,
            'concurrentRDF': False,
            'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False,
            'RDFSession': [
                {'SRDFStatus': 'Ready',
                 'SRDFReplicationMode': 'Synchronized',
                 'remoteDeviceID': device_id2,
                 'remoteSymmetrixID': remote_array,
                 'SRDFGroupNumber': 1,
                 'SRDFRemoteGroupNumber': 1}]}}

    priv_vol_response_metro_active_rep = {
        'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV',
            'userDefinedIdentifier': 'OS-00001'},
        'maskingInfo': {'masked': False},
        'rdfInfo': {
            'dynamicRDF': False, 'RDF': True,
            'concurrentRDF': False,
            'getDynamicRDFCapability': 'RDF1_Capable', 'RDFA': False,
            'RDFSession': [
                {'SRDFStatus': 'Ready',
                 'SRDFReplicationMode': 'Active',
                 'remoteDeviceID': device_id2,
                 'remoteSymmetrixID': remote_array,
                 'SRDFGroupNumber': 1,
                 'SRDFRemoteGroupNumber': 1}]}}

    priv_vol_response_no_rep = {
        'volumeHeader': {
            'private': False, 'capGB': 1.0, 'capMB': 1026.0,
            'serviceState': 'Normal', 'emulationType': 'FBA',
            'volumeId': '00001', 'status': 'Ready', 'mapped': False,
            'numStorageGroups': 0, 'reservationInfo': {'reserved': False},
            'encapsulated': False, 'formattedName': '00001',
            'system_resource': False, 'numSymDevMaskingViews': 0,
            'nameModifier': "", 'configuration': 'TDEV',
            'userDefinedIdentifier': 'OS-00001'},
        'maskingInfo': {'masked': False},
        'rdfInfo': {'RDF': False}}

    snap_device_label = ('%(dev)s:%(label)s' % {'dev': device_id,
                                                'label': managed_snap_id})

    priv_snap_response = {
        'deviceName': snap_device_label, 'snapshotLnks': [],
        'snapshotSrcs': [
            {'snap_id': snap_id,
             'linkedDevices': [
                 {'targetDevice': device_id2, 'percentageCopied': 100,
                  'state': 'Copied', 'copy': True, 'defined': True,
                  'linked': True}],
             'snapshotName': test_snapshot_snap_name,
             'state': 'Established'}]}

    priv_snap_response_no_label = deepcopy(priv_snap_response)
    priv_snap_response_no_label.update({'deviceName': device_id})

    volume_metadata = {
        'DeviceID': device_id, 'ArrayID': array, 'ArrayModel': array_model}

    # retype metadata dict
    retype_metadata_dict = {
        'device_id': device_id,
        'rdf_group_no': '10',
        'remote_array': remote_array,
        'target_device_id': device_id,
        'rep_mode': 'Asynchronous',
        'replication_status': 'enabled',
        'target_array_model': array_model}

    retype_metadata_dict2 = {
        'default_sg_name': 'default-sg',
        'service_level': 'Diamond'
    }

    rep_info_dict = {
        'device_id': device_id,
        'local_array': array, 'remote_array': remote_array,
        'target_device_id': device_id2, 'target_name': 'test_vol',
        'rdf_group_no': rdf_group_no_1, 'rep_mode': 'Metro',
        'replication_status': 'Enabled', 'rdf_group_label': rdf_group_name_1,
        'target_array_model': array_model,
        'rdf_mgmt_grp': rdf_managed_async_grp}

    create_vol_with_replication_payload = {
        'executionOption': 'ASYNCHRONOUS',
        'editStorageGroupActionParam': {
            'expandStorageGroupParam': {
                'addVolumeParam': {
                    'emulation': 'FBA',
                    'create_new_volumes': 'True',
                    'volumeAttributes': [
                        {'num_of_vols': 1,
                         'volumeIdentifier': {
                             'identifier_name': (
                                 volume_details[0]['volume_identifier']),
                             'volumeIdentifierChoice': 'identifier_name'},
                         'volume_size': test_volume.size,
                         'capacityUnit': 'GB'}],
                    'remoteSymmSGInfoParam': {
                        'force': 'true',
                        'remote_symmetrix_1_id': remote_array,
                        'remote_symmetrix_1_sgs': [
                            defaultstoragegroup_name]}}}}}

    r1_sg_list = [default_sg_no_slo_re_enabled,
                  rdf_managed_async_grp]

    r2_sg_list = deepcopy(r1_sg_list)
    replication_model = (
        {'provider_location': six.text_type(provider_location),
         'metadata': {'DeviceID': device_id,
                      'DeviceLabel': 'OS-%s' % volume_id,
                      'ArrayID': array,
                      'ArrayModel': array_model,
                      'ServiceLevel': 'Silver',
                      'Workload': 'NONE',
                      'Emulation': 'FBA',
                      'Configuration': 'TDEV',
                      'CompressionDisabled': False,
                      'R2-DeviceID': device_id2,
                      'R2-ArrayID': remote_array,
                      'R2-ArrayModel': array_model,
                      'ReplicationMode': 'Synchronous',
                      'RDFG-Label': rdf_group_name_1,
                      'R1-RDFG': rdf_group_no_1,
                      'R2-RDFG': rdf_group_no_1}})

    non_replication_model = (
        {'provider_location': six.text_type(provider_location),
         'metadata': {'DeviceID': device_id,
                      'DeviceLabel': 'OS-%s' % volume_id,
                      'ArrayID': array,
                      'ArrayModel': array_model,
                      'ServiceLevel': 'Silver',
                      'Workload': 'NONE',
                      'Emulation': 'FBA',
                      'Configuration': 'TDEV',
                      'CompressionDisabled': False}})

    vol_create_desc1 = 'Populating Storage Group(s) with volumes : [00001]'
    vol_create_desc2 = ('Refresh [Storage Group [OS-SG] '
                        'on Symmetrix [000197800123]] ')
    vol_create_task = [{'execution_order': 1,
                        'description': vol_create_desc1},
                       {'execution_order': 2,
                        'description': vol_create_desc2}]

    # performance
    f_date_a = 1593432600000
    f_date_b = 1594136400000
    l_date = 1594730100000
    perf_pb_metric = 'PercentBusy'
    perf_df_avg = 'Average'
    perf_port_groups = ['port_group_a', 'port_group_b', 'port_group_c']
    perf_ports = ['SE-1E:1', 'SE-1E:2', 'SE-1E:3']

    performance_config = {
        'load_balance': True, 'load_balance_rt': True,
        'perf_registered': True, 'rt_registered': True,
        'collection_interval': 5, 'data_format': 'Average',
        'look_back': 60, 'look_back_rt': 10,
        'port_group_metric': 'PercentBusy', 'port_metric': 'PercentBusy'}

    array_registration = {"registrationDetailsInfo": [
        {"symmetrixId": array, "realtime": True, "message": "Success",
         "collectionintervalmins": 5, "diagnostic": True}]}

    array_keys = {"arrayInfo": [
        {"symmetrixId": array,
         "firstAvailableDate": f_date_a,
         "lastAvailableDate": l_date},
        {"symmetrixId": array_herc,
         "firstAvailableDate": f_date_a,
         "lastAvailableDate": l_date},
        {"symmetrixId": remote_array,
         "firstAvailableDate": f_date_b,
         "lastAvailableDate": l_date}]}

    dummy_performance_data = {
        "expirationTime": 1594731525645,
        "count": 10,
        "maxPageSize": 1000,
        "id": "3b757302-6e4a-4dbe-887d-e42aed7f5944_0",
        "resultList": {
            "result": [
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593432600000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593432900000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593433200000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593433500000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593433800000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593434100000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593434400000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593434700000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593435000000},
                {"PercentBusy": random.uniform(0.0, 100.0),
                 "timestamp": 1593435300000}],
            "from": 1,
            "to": 10
        }
    }
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
    snapshot_metadata = {'SnapshotLabel': test_snapshot_snap_name,
                         'SourceDeviceID': device_id,
                         'SourceDeviceLabel': device_label,
                         'SnapIdList': [snap_id]}

    port_info = {
        "symmetrixPort": {
            "director_status": "Online",
            "maskingview": [
                "Test_MV",
            ],
            "port_status": "ON",
            "symmetrixPortKey": {
                "directorId": "FA-1D",
                "portId": "4"
            },
            "portgroup": [
                "Test_PG"
            ]
        }
    }

    port_info_off = deepcopy(port_info)
    port_info_off.update({"symmetrixPort": {
        "director_status": "Offline",
        "port_status": "OFF"}})

    port_info_no_status = deepcopy(port_info)
    port_info_no_status.update({"symmetrixPort": {
        "symmetrixPortKey": {
            "directorId": "FA-1D",
            "portId": "4"
        }
    }})

    port_info_no_details = deepcopy(port_info)
    port_info_no_details.pop("symmetrixPort")
