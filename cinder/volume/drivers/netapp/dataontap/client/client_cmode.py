# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
# Copyright (c) 2017 Jose Porrua. All rights reserved.
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

import copy
import math
import re

from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)
DEFAULT_MAX_PAGE_LENGTH = 50
ONTAP_SELECT_MODEL = 'FDvM300'
ONTAP_C190 = 'C190'


@six.add_metaclass(volume_utils.TraceWrapperMetaclass)
class Client(client_base.Client):

    def __init__(self, **kwargs):
        super(Client, self).__init__(**kwargs)
        self.vserver = kwargs.get('vserver', None)
        self.connection.set_vserver(self.vserver)

        # Default values to run first api
        self.connection.set_api_version(1, 15)
        (major, minor) = self.get_ontapi_version(cached=False)
        self.connection.set_api_version(major, minor)
        ontap_version = self.get_ontap_version(cached=False)
        self.connection.set_ontap_version(ontap_version)
        self._init_features()

    def _init_features(self):
        super(Client, self)._init_features()

        ontapi_version = self.get_ontapi_version()   # major, minor

        ontapi_1_20 = ontapi_version >= (1, 20)
        ontapi_1_2x = (1, 20) <= ontapi_version < (1, 30)
        ontapi_1_30 = ontapi_version >= (1, 30)
        ontapi_1_100 = ontapi_version >= (1, 100)
        ontapi_1_1xx = (1, 100) <= ontapi_version < (1, 200)
        ontapi_1_60 = ontapi_version >= (1, 160)
        ontapi_1_40 = ontapi_version >= (1, 140)
        ontapi_1_50 = ontapi_version >= (1, 150)
        ontapi_1_80 = ontapi_version >= (1, 180)
        ontapi_1_90 = ontapi_version >= (1, 190)

        nodes_info = self._get_cluster_nodes_info()
        for node in nodes_info:
            qos_min_block = False
            qos_min_nfs = False
            if node['model'] == ONTAP_SELECT_MODEL:
                qos_min_block = node['is_all_flash_select'] and ontapi_1_60
                qos_min_nfs = qos_min_block
            elif ONTAP_C190 in node['model']:
                qos_min_block = node['is_all_flash'] and ontapi_1_60
                qos_min_nfs = qos_min_block
            else:
                qos_min_block = node['is_all_flash'] and ontapi_1_20
                qos_min_nfs = node['is_all_flash'] and ontapi_1_30

            qos_name = na_utils.qos_min_feature_name(True, node['name'])
            self.features.add_feature(qos_name, supported=qos_min_nfs)
            qos_name = na_utils.qos_min_feature_name(False, node['name'])
            self.features.add_feature(qos_name, supported=qos_min_block)

        self.features.add_feature('SNAPMIRROR_V2', supported=ontapi_1_20)
        self.features.add_feature('USER_CAPABILITY_LIST',
                                  supported=ontapi_1_20)
        self.features.add_feature('SYSTEM_METRICS', supported=ontapi_1_2x)
        self.features.add_feature('CLONE_SPLIT_STATUS', supported=ontapi_1_30)
        self.features.add_feature('FAST_CLONE_DELETE', supported=ontapi_1_30)
        self.features.add_feature('SYSTEM_CONSTITUENT_METRICS',
                                  supported=ontapi_1_30)
        self.features.add_feature('ADVANCED_DISK_PARTITIONING',
                                  supported=ontapi_1_30)
        self.features.add_feature('BACKUP_CLONE_PARAM', supported=ontapi_1_100)
        self.features.add_feature('CLUSTER_PEER_POLICY', supported=ontapi_1_30)
        self.features.add_feature('FLEXVOL_ENCRYPTION', supported=ontapi_1_1xx)
        self.features.add_feature('FLEXGROUP', supported=ontapi_1_80)
        self.features.add_feature('FLEXGROUP_CLONE_FILE',
                                  supported=ontapi_1_90)

        self.features.add_feature('ADAPTIVE_QOS', supported=ontapi_1_40)
        self.features.add_feature('ADAPTIVE_QOS_BLOCK_SIZE',
                                  supported=ontapi_1_50)
        self.features.add_feature('ADAPTIVE_QOS_EXPECTED_IOPS_ALLOCATION',
                                  supported=ontapi_1_50)

        LOG.info('Reported ONTAPI Version: %(major)s.%(minor)s',
                 {'major': ontapi_version[0], 'minor': ontapi_version[1]})

    def _invoke_vserver_api(self, na_element, vserver):
        server = copy.copy(self.connection)
        server.set_vserver(vserver)
        result = server.invoke_successfully(na_element, True)
        return result

    def _has_records(self, api_result_element):
        num_records = api_result_element.get_child_content('num-records')
        return bool(num_records and '0' != num_records)

    def _get_record_count(self, api_result_element):
        try:
            return int(api_result_element.get_child_content('num-records'))
        except TypeError:
            msg = _('Missing record count for NetApp iterator API invocation.')
            raise na_utils.NetAppDriverException(msg)

    def set_vserver(self, vserver):
        self.vserver = vserver
        self.connection.set_vserver(vserver)

    def send_iter_request(self, api_name, api_args=None, enable_tunneling=True,
                          max_page_length=DEFAULT_MAX_PAGE_LENGTH):
        """Invoke an iterator-style getter API."""

        if not api_args:
            api_args = {}

        api_args['max-records'] = max_page_length

        # Get first page
        result = self.connection.send_request(
            api_name, api_args, enable_tunneling=enable_tunneling)

        # Most commonly, we can just return here if there is no more data
        next_tag = result.get_child_content('next-tag')
        if not next_tag:
            return result

        # Ensure pagination data is valid and prepare to store remaining pages
        num_records = self._get_record_count(result)
        attributes_list = result.get_child_by_name('attributes-list')
        if not attributes_list:
            msg = _('Missing attributes list for API %s.') % api_name
            raise na_utils.NetAppDriverException(msg)

        # Get remaining pages, saving data into first page
        while next_tag is not None:
            next_api_args = copy.deepcopy(api_args)
            next_api_args['tag'] = next_tag
            next_result = self.connection.send_request(
                api_name, next_api_args, enable_tunneling=enable_tunneling)

            next_attributes_list = next_result.get_child_by_name(
                'attributes-list') or netapp_api.NaElement('none')

            for record in next_attributes_list.get_children():
                attributes_list.add_child_elem(record)

            num_records += self._get_record_count(next_result)
            next_tag = next_result.get_child_content('next-tag')

        result.get_child_by_name('num-records').set_content(
            six.text_type(num_records))
        result.get_child_by_name('next-tag').set_content('')
        return result

    def _get_cluster_nodes_info(self):
        """Return a list of models of the nodes in the cluster"""
        api_args = {
            'desired-attributes': {
                'node-details-info': {
                    'node': None,
                    'node-model': None,
                    'is-all-flash-select-optimized': None,
                    'is-all-flash-optimized': None,
                }
            }
        }

        nodes = []
        try:
            result = self.send_iter_request('system-node-get-iter', api_args,
                                            enable_tunneling=False)
            system_node_list = result.get_child_by_name(
                'attributes-list') or netapp_api.NaElement('none')
            for system_node in system_node_list.get_children():
                node = {
                    'model': system_node.get_child_content('node-model'),
                    'name': system_node.get_child_content('node'),
                    'is_all_flash': system_node.get_child_content(
                        'is-all-flash-optimized') == 'true',
                    'is_all_flash_select': system_node.get_child_content(
                        'is-all-flash-select-optimized') == 'true',
                }
                nodes.append(node)

        except netapp_api.NaApiError as e:
            if e.code == netapp_api.EAPINOTFOUND:
                LOG.debug('Cluster nodes can only be collected with '
                          'cluster scoped credentials.')
            else:
                LOG.exception('Failed to get the cluster nodes.')

        return nodes

    def list_vservers(self, vserver_type='data'):
        """Get the names of vservers present, optionally filtered by type."""
        query = {
            'vserver-info': {
                'vserver-type': vserver_type,
            }
        } if vserver_type else None

        api_args = {
            'desired-attributes': {
                'vserver-info': {
                    'vserver-name': None,
                },
            },
        }
        if query:
            api_args['query'] = query

        result = self.send_iter_request('vserver-get-iter', api_args,
                                        enable_tunneling=False)
        vserver_info_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')
        return [vserver_info.get_child_content('vserver-name')
                for vserver_info in vserver_info_list.get_children()]

    def _get_ems_log_destination_vserver(self):
        """Returns the best vserver destination for EMS messages."""
        major, minor = self.get_ontapi_version(cached=True)

        if (major > 1) or (major == 1 and minor > 15):
            # Prefer admin Vserver (requires cluster credentials).
            admin_vservers = self.list_vservers(vserver_type='admin')
            if admin_vservers:
                return admin_vservers[0]

            # Fall back to data Vserver.
            data_vservers = self.list_vservers(vserver_type='data')
            if data_vservers:
                return data_vservers[0]

        # If older API version, or no other Vservers found, use node Vserver.
        node_vservers = self.list_vservers(vserver_type='node')
        if node_vservers:
            return node_vservers[0]

        raise exception.NotFound("No Vserver found to receive EMS messages.")

    def send_ems_log_message(self, message_dict):
        """Sends a message to the Data ONTAP EMS log."""

        # NOTE(cknight): Cannot use deepcopy on the connection context
        node_client = copy.copy(self)
        node_client.connection = copy.copy(self.connection)
        node_client.connection.set_timeout(25)

        try:
            node_client.set_vserver(self._get_ems_log_destination_vserver())
            node_client.connection.send_request('ems-autosupport-log',
                                                message_dict)
            LOG.debug('EMS executed successfully.')
        except netapp_api.NaApiError as e:
            LOG.warning('Failed to invoke EMS. %s', e)

    def get_iscsi_target_details(self):
        """Gets the iSCSI target portal details."""
        iscsi_if_iter = netapp_api.NaElement('iscsi-interface-get-iter')
        result = self.connection.invoke_successfully(iscsi_if_iter, True)
        tgt_list = []
        num_records = result.get_child_content('num-records')
        if num_records and int(num_records) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            iscsi_if_list = attr_list.get_children()
            for iscsi_if in iscsi_if_list:
                d = dict()
                d['address'] = iscsi_if.get_child_content('ip-address')
                d['port'] = iscsi_if.get_child_content('ip-port')
                d['tpgroup-tag'] = iscsi_if.get_child_content('tpgroup-tag')
                d['interface-enabled'] = iscsi_if.get_child_content(
                    'is-interface-enabled')
                tgt_list.append(d)
        return tgt_list

    def set_iscsi_chap_authentication(self, iqn, username, password):
        """Provides NetApp host's CHAP credentials to the backend."""
        initiator_exists = self.check_iscsi_initiator_exists(iqn)

        command_template = ('iscsi security %(mode)s -vserver %(vserver)s '
                            '-initiator-name %(iqn)s -auth-type CHAP '
                            '-user-name %(username)s')

        if initiator_exists:
            LOG.debug('Updating CHAP authentication for %(iqn)s.',
                      {'iqn': iqn})
            command = command_template % {
                'mode': 'modify',
                'vserver': self.vserver,
                'iqn': iqn,
                'username': username,
            }
        else:
            LOG.debug('Adding initiator %(iqn)s with CHAP authentication.',
                      {'iqn': iqn})
            command = command_template % {
                'mode': 'create',
                'vserver': self.vserver,
                'iqn': iqn,
                'username': username,
            }

        try:
            with self.ssh_client.ssh_connect_semaphore:
                ssh_pool = self.ssh_client.ssh_pool
                with ssh_pool.item() as ssh:
                    self.ssh_client.execute_command_with_prompt(ssh,
                                                                command,
                                                                'Password:',
                                                                password)
        except Exception as e:
            msg = _('Failed to set CHAP authentication for target IQN %(iqn)s.'
                    ' Details: %(ex)s') % {
                'iqn': iqn,
                'ex': e,
            }
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def check_iscsi_initiator_exists(self, iqn):
        """Returns True if initiator exists."""
        initiator_exists = True
        try:
            auth_list = netapp_api.NaElement('iscsi-initiator-get-auth')
            auth_list.add_new_child('initiator', iqn)
            self.connection.invoke_successfully(auth_list, True)
        except netapp_api.NaApiError:
            initiator_exists = False

        return initiator_exists

    def get_fc_target_wwpns(self):
        """Gets the FC target details."""
        wwpns = []
        port_name_list_api = netapp_api.NaElement('fcp-port-name-get-iter')
        port_name_list_api.add_new_child('max-records', '100')
        result = self.connection.invoke_successfully(port_name_list_api, True)
        num_records = result.get_child_content('num-records')
        if num_records and int(num_records) >= 1:
            for port_name_info in result.get_child_by_name(
                    'attributes-list').get_children():

                if port_name_info.get_child_content('is-used') != 'true':
                    continue

                wwpn = port_name_info.get_child_content('port-name').lower()
                wwpns.append(wwpn)

        return wwpns

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        iscsi_service_iter = netapp_api.NaElement('iscsi-service-get-iter')
        result = self.connection.invoke_successfully(iscsi_service_iter, True)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            iscsi_service = attr_list.get_child_by_name('iscsi-service-info')
            return iscsi_service.get_child_content('node-name')
        LOG.debug('No iSCSI service found for vserver %s', self.vserver)
        return None

    def get_lun_sizes_by_volume(self, volume_name):
        """"Gets the list of LUNs and their sizes from a given volume name"""

        api_args = {
            'query': {
                'lun-info': {
                    'volume': volume_name
                }
            },
            'desired-attributes': {
                'lun-info': {
                    'path': None,
                    'size': None
                }
            }
        }
        result = self.send_iter_request(
            'lun-get-iter', api_args, max_page_length=100)

        if not self._has_records(result):
            return []

        attributes_list = result.get_child_by_name('attributes-list')

        luns = []
        for lun_info in attributes_list.get_children():
            luns.append({
                'path': lun_info.get_child_content('path'),
                'size': float(lun_info.get_child_content('size'))
            })
        return luns

    def get_file_sizes_by_dir(self, dir_path):
        """Gets the list of files and their sizes from a given directory."""

        api_args = {
            'path': '/vol/%s' % dir_path,
            'query': {
                'file-info': {
                    'file-type': 'file'
                }
            },
            'desired-attributes': {
                'file-info': {
                    'name': None,
                    'file-size': None
                }
            }
        }
        result = self.send_iter_request(
            'file-list-directory-iter', api_args, max_page_length=100)

        if not self._has_records(result):
            return []

        attributes_list = result.get_child_by_name('attributes-list')

        files = []
        for file_info in attributes_list.get_children():
            files.append({
                'name': file_info.get_child_content('name'),
                'file-size': float(file_info.get_child_content('file-size'))
            })
        return files

    def get_lun_list(self):
        """Gets the list of LUNs on filer.

        Gets the LUNs from cluster with vserver.
        """

        luns = []
        tag = None
        while True:
            api = netapp_api.NaElement('lun-get-iter')
            api.add_new_child('max-records', '100')
            if tag:
                api.add_new_child('tag', tag, True)
            lun_info = netapp_api.NaElement('lun-info')
            lun_info.add_new_child('vserver', self.vserver)
            query = netapp_api.NaElement('query')
            query.add_child_elem(lun_info)
            api.add_child_elem(query)
            result = self.connection.invoke_successfully(api, True)
            if result.get_child_by_name('num-records') and\
                    int(result.get_child_content('num-records')) >= 1:
                attr_list = result.get_child_by_name('attributes-list')
                luns.extend(attr_list.get_children())
            tag = result.get_child_content('next-tag')
            if tag is None:
                break
        return luns

    def get_lun_map(self, path):
        """Gets the LUN map by LUN path."""
        tag = None
        map_list = []
        while True:
            lun_map_iter = netapp_api.NaElement('lun-map-get-iter')
            lun_map_iter.add_new_child('max-records', '100')
            if tag:
                lun_map_iter.add_new_child('tag', tag, True)
            query = netapp_api.NaElement('query')
            lun_map_iter.add_child_elem(query)
            query.add_node_with_children('lun-map-info', **{'path': path})
            result = self.connection.invoke_successfully(lun_map_iter, True)
            tag = result.get_child_content('next-tag')
            if result.get_child_content('num-records') and \
                    int(result.get_child_content('num-records')) >= 1:
                attr_list = result.get_child_by_name('attributes-list')
                lun_maps = attr_list.get_children()
                for lun_map in lun_maps:
                    lun_m = dict()
                    lun_m['initiator-group'] = lun_map.get_child_content(
                        'initiator-group')
                    lun_m['lun-id'] = lun_map.get_child_content('lun-id')
                    lun_m['vserver'] = lun_map.get_child_content('vserver')
                    map_list.append(lun_m)
            if tag is None:
                break
        return map_list

    def _get_igroup_by_initiator_query(self, initiator, tag):
        igroup_get_iter = netapp_api.NaElement('igroup-get-iter')
        igroup_get_iter.add_new_child('max-records', '100')
        if tag:
            igroup_get_iter.add_new_child('tag', tag, True)

        query = netapp_api.NaElement('query')
        igroup_info = netapp_api.NaElement('initiator-group-info')
        query.add_child_elem(igroup_info)
        igroup_info.add_new_child('vserver', self.vserver)
        initiators = netapp_api.NaElement('initiators')
        igroup_info.add_child_elem(initiators)
        igroup_get_iter.add_child_elem(query)
        initiators.add_node_with_children(
            'initiator-info', **{'initiator-name': initiator})

        # limit results to just the attributes of interest
        desired_attrs = netapp_api.NaElement('desired-attributes')
        desired_igroup_info = netapp_api.NaElement('initiator-group-info')
        desired_igroup_info.add_node_with_children(
            'initiators', **{'initiator-info': None})
        desired_igroup_info.add_new_child('vserver', None)
        desired_igroup_info.add_new_child('initiator-group-name', None)
        desired_igroup_info.add_new_child('initiator-group-type', None)
        desired_igroup_info.add_new_child('initiator-group-os-type', None)
        desired_attrs.add_child_elem(desired_igroup_info)
        igroup_get_iter.add_child_elem(desired_attrs)

        return igroup_get_iter

    def get_igroup_by_initiators(self, initiator_list):
        """Get igroups exactly matching a set of initiators."""
        tag = None
        igroup_list = []
        if not initiator_list:
            return igroup_list

        initiator_set = set(initiator_list)

        while True:
            # C-mode getter APIs can't do an 'and' query, so match the first
            # initiator (which will greatly narrow the search results) and
            # filter the rest in this method.
            query = self._get_igroup_by_initiator_query(initiator_list[0], tag)
            result = self.connection.invoke_successfully(query, True)

            tag = result.get_child_content('next-tag')
            num_records = result.get_child_content('num-records')
            if num_records and int(num_records) >= 1:

                for igroup_info in result.get_child_by_name(
                        'attributes-list').get_children():

                    initiator_set_for_igroup = set()
                    for initiator_info in igroup_info.get_child_by_name(
                            'initiators').get_children():

                        initiator_set_for_igroup.add(
                            initiator_info.get_child_content('initiator-name'))

                    if initiator_set == initiator_set_for_igroup:
                        igroup = {'initiator-group-os-type':
                                  igroup_info.get_child_content(
                                      'initiator-group-os-type'),
                                  'initiator-group-type':
                                  igroup_info.get_child_content(
                                      'initiator-group-type'),
                                  'initiator-group-name':
                                  igroup_info.get_child_content(
                                      'initiator-group-name')}
                        igroup_list.append(igroup)

            if tag is None:
                break

        return igroup_list

    def _validate_qos_policy_group(self, is_adaptive, spec=None,
                                   qos_min_support=False):
        if is_adaptive and not self.features.ADAPTIVE_QOS:
            msg = _("Adaptive QoS feature requires ONTAP 9.4 or later.")
            raise na_utils.NetAppDriverException(msg)

        if not spec:
            return

        qos_spec_support = [
            {'key': 'min_throughput',
             'support': qos_min_support,
             'reason': _('is not supported by this back end.')},
            {'key': 'block_size',
             'support': self.features.ADAPTIVE_QOS_BLOCK_SIZE,
             'reason': _('requires ONTAP >= 9.5.')},
            {'key': 'expected_iops_allocation',
             'support': self.features.ADAPTIVE_QOS_EXPECTED_IOPS_ALLOCATION,
             'reason': _('requires ONTAP >= 9.5.')},
        ]
        for feature in qos_spec_support:
            if feature['key'] in spec and not feature['support']:
                msg = '%(key)s %(reason)s'
                raise na_utils.NetAppDriverException(msg % {
                    'key': feature['key'],
                    'reason': feature['reason']})

    def clone_lun(self, volume, name, new_name, space_reserved='true',
                  qos_policy_group_name=None, src_block=0, dest_block=0,
                  block_count=0, source_snapshot=None, is_snapshot=False,
                  qos_policy_group_is_adaptive=False):
        self._validate_qos_policy_group(qos_policy_group_is_adaptive)

        # ONTAP handles only 128 MB per call as of v9.1
        bc_limit = 2 ** 18  # 2^18 blocks * 512 bytes/block = 128 MB
        z_calls = int(math.ceil(block_count / float(bc_limit)))
        zbc = block_count
        if z_calls == 0:
            z_calls = 1
        for _call in range(0, z_calls):
            if zbc > bc_limit:
                block_count = bc_limit
                zbc -= bc_limit
            else:
                block_count = zbc

            zapi_args = {
                'volume': volume,
                'source-path': name,
                'destination-path': new_name,
                'space-reserve': space_reserved,
            }
            if source_snapshot:
                zapi_args['snapshot-name'] = source_snapshot
            if is_snapshot and self.features.BACKUP_CLONE_PARAM:
                zapi_args['is-backup'] = 'true'
            clone_create = netapp_api.NaElement.create_node_with_children(
                'clone-create', **zapi_args)
            if qos_policy_group_name is not None:
                child_name = 'qos-%spolicy-group-name' % (
                    'adaptive-' if qos_policy_group_is_adaptive else '')
                clone_create.add_new_child(child_name, qos_policy_group_name)
            if block_count > 0:
                block_ranges = netapp_api.NaElement("block-ranges")
                segments = int(math.ceil(block_count / float(bc_limit)))
                bc = block_count
                for _segment in range(0, segments):
                    if bc > bc_limit:
                        block_count = bc_limit
                        bc -= bc_limit
                    else:
                        block_count = bc
                    block_range =\
                        netapp_api.NaElement.create_node_with_children(
                            'block-range',
                            **{'source-block-number':
                               six.text_type(src_block),
                               'destination-block-number':
                               six.text_type(dest_block),
                               'block-count':
                               six.text_type(int(block_count))})
                    block_ranges.add_child_elem(block_range)
                    src_block += int(block_count)
                    dest_block += int(block_count)
                clone_create.add_child_elem(block_ranges)
            self.connection.invoke_successfully(clone_create, True)

    def start_file_copy(self, file_name, dest_ontap_volume,
                        src_ontap_volume=None,
                        dest_file_name=None):
        """Starts a file copy operation between ONTAP volumes."""
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume
        if dest_file_name is None:
            dest_file_name = file_name

        api_args = {
            'source-paths': [{
                'sfod-operation-path': '%s/%s' % (src_ontap_volume,
                                                  file_name)
            }],
            'destination-paths': [{
                'sfod-operation-path': '%s/%s' % (dest_ontap_volume,
                                                  dest_file_name),
            }],
        }
        result = self.connection.send_request('file-copy-start', api_args,
                                              enable_tunneling=False)
        return result.get_child_content('job-uuid')

    def destroy_file_copy(self, job_uuid):
        """Cancel/Destroy a in-progress file copy."""
        api_args = {
            'job-uuid': job_uuid,
            'file-index': 0
        }
        try:
            self.connection.send_request('file-copy-destroy', api_args,
                                         enable_tunneling=False)
        except netapp_api.NaApiError as e:
            msg = (_('Could not cancel lun copy for job uuid %s. %s'))
            raise na_utils.NetAppDriverException(msg % (job_uuid, e))

    def get_file_copy_status(self, job_uuid):
        """Get file copy job status from a given job's UUID."""
        api_args = {
            'query': {
                'file-copy-info': {
                    'job-uuid': job_uuid
                }
            }
        }
        result = self.connection.send_request('file-copy-get-iter', api_args,
                                              enable_tunneling=False)
        lun_copy_info_list = result.get_child_by_name('attributes-list')
        if lun_copy_info_list:
            lun_copy_info = lun_copy_info_list.get_children()[0]
            copy_status = {
                'job-status':
                    lun_copy_info.get_child_content('scanner-status'),
                'last-failure-reason':
                    lun_copy_info.get_child_content('last-failure-reason')
            }
            return copy_status
        return None

    def start_lun_copy(self, lun_name, dest_ontap_volume, dest_vserver,
                       src_ontap_volume=None, src_vserver=None,
                       dest_lun_name=None):
        """Starts a lun copy operation between ONTAP volumes."""
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume
        if src_vserver is None:
            src_vserver = dest_vserver
        if dest_lun_name is None:
            dest_lun_name = lun_name

        api_args = {
            'source-vserver': src_vserver,
            'destination-vserver': dest_vserver,
            'paths': [{
                'lun-path-pair': {
                    'destination-path': '/vol/%s/%s' % (dest_ontap_volume,
                                                        dest_lun_name),
                    'source-path': '/vol/%s/%s' % (src_ontap_volume,
                                                   lun_name)}
            }],
        }
        result = self.connection.send_request('lun-copy-start', api_args,
                                              enable_tunneling=False)
        return result.get_child_content('job-uuid')

    def cancel_lun_copy(self, job_uuid):
        """Cancel an in-progress lun copy."""
        api_args = {
            'job-uuid': job_uuid
        }
        try:
            self.connection.send_request('lun-copy-cancel', api_args,
                                         enable_tunneling=False)
        except netapp_api.NaApiError as e:
            msg = (_('Could not cancel lun copy for job uuid %s. %s'))
            raise na_utils.NetAppDriverException(msg % (job_uuid, e))

    def get_lun_copy_status(self, job_uuid):
        """Get lun copy job status from a given job's UUID."""
        api_args = {
            'query': {
                'lun-copy-info': {
                    'job-uuid': job_uuid
                }
            }
        }
        result = self.connection.send_request('lun-copy-get-iter', api_args,
                                              enable_tunneling=False)
        lun_copy_info_list = result.get_child_by_name('attributes-list')
        if lun_copy_info_list:
            lun_copy_info = lun_copy_info_list.get_children()[0]
            copy_status = {
                'job-status':
                    lun_copy_info.get_child_content('job-status'),
                'last-failure-reason':
                    lun_copy_info.get_child_content('last-failure-reason')
            }
            return copy_status
        return None

    def start_lun_move(self, lun_name, dest_ontap_volume,
                       src_ontap_volume=None, dest_lun_name=None):
        """Starts a lun move operation between ONTAP volumes."""
        if dest_lun_name is None:
            dest_lun_name = lun_name
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume

        api_args = {
            'paths': [{
                'lun-path-pair': {
                    'destination-path': '/vol/%s/%s' % (dest_ontap_volume,
                                                        dest_lun_name),
                    'source-path': '/vol/%s/%s' % (src_ontap_volume,
                                                   lun_name)}
            }]
        }

        result = self.connection.send_request('lun-move-start', api_args)
        return result.get_child_content('job-uuid')

    def get_lun_move_status(self, job_uuid):
        """Get lun move job status from a given job's UUID."""
        api_args = {
            'query': {
                'lun-move-info': {
                    'job-uuid': job_uuid
                }
            }
        }
        result = self.connection.send_request('lun-move-get-iter', api_args)
        lun_move_info_list = result.get_child_by_name('attributes-list')
        if lun_move_info_list:
            lun_move_info = lun_move_info_list.get_children()[0]
            move_status = {
                'job-status':
                    lun_move_info.get_child_content('job-status'),
                'last-failure-reason':
                    lun_move_info.get_child_content('last-failure-reason')
            }
            return move_status
        return None

    def get_lun_by_args(self, **args):
        """Retrieves LUN with specified args."""
        lun_iter = netapp_api.NaElement('lun-get-iter')
        lun_iter.add_new_child('max-records', '100')
        query = netapp_api.NaElement('query')
        lun_iter.add_child_elem(query)
        query.add_node_with_children('lun-info', **args)
        luns = self.connection.invoke_successfully(lun_iter, True)
        attr_list = luns.get_child_by_name('attributes-list')
        if not attr_list:
            return []
        return attr_list.get_children()

    def file_assign_qos(self, flex_vol, qos_policy_group_name,
                        qos_policy_group_is_adaptive, file_path):
        """Assigns the named QoS policy-group to a file."""
        self._validate_qos_policy_group(qos_policy_group_is_adaptive)

        qos_arg_name = "qos-%spolicy-group-name" % (
            "adaptive-" if qos_policy_group_is_adaptive else "")
        api_args = {
            'volume': flex_vol,
            qos_arg_name: qos_policy_group_name,
            'file': file_path,
            'vserver': self.vserver,
        }
        return self.connection.send_request('file-assign-qos', api_args, False)

    def provision_qos_policy_group(self, qos_policy_group_info,
                                   qos_min_support):
        """Create QOS policy group on the backend if appropriate."""
        if qos_policy_group_info is None:
            return

        # Legacy QOS uses externally provisioned QOS policy group,
        # so we don't need to create one on the backend.
        legacy = qos_policy_group_info.get('legacy')
        if legacy:
            return

        spec = qos_policy_group_info.get('spec')

        if not spec:
            return

        is_adaptive = na_utils.is_qos_policy_group_spec_adaptive(
            qos_policy_group_info)
        self._validate_qos_policy_group(is_adaptive, spec=spec,
                                        qos_min_support=qos_min_support)
        if is_adaptive:
            if not self.qos_policy_group_exists(spec['policy_name'],
                                                is_adaptive=True):
                self.qos_adaptive_policy_group_create(spec)
            else:
                self.qos_adaptive_policy_group_modify(spec)
        else:
            if not self.qos_policy_group_exists(spec['policy_name']):
                self.qos_policy_group_create(spec)
            else:
                self.qos_policy_group_modify(spec)

    def qos_policy_group_exists(self, qos_policy_group_name,
                                is_adaptive=False):
        """Checks if a QOS policy group exists."""
        query_name = 'qos-%spolicy-group-info' % (
            'adaptive-' if is_adaptive else '')
        request_name = 'qos-%spolicy-group-get-iter' % (
            'adaptive-' if is_adaptive else '')
        api_args = {
            'query': {
                query_name: {
                    'policy-group': qos_policy_group_name,
                },
            },
            'desired-attributes': {
                query_name: {
                    'policy-group': None,
                },
            },
        }
        result = self.connection.send_request(request_name, api_args, False)
        return self._has_records(result)

    def _qos_spec_to_api_args(self, spec, **kwargs):
        """Convert a QoS spec to ZAPI args."""
        formatted_spec = {k.replace('_', '-'): v for k, v in spec.items() if v}
        formatted_spec['policy-group'] = formatted_spec.pop('policy-name')
        formatted_spec = {**formatted_spec, **kwargs}

        return formatted_spec

    def qos_policy_group_create(self, spec):
        """Creates a QOS policy group."""
        api_args = self._qos_spec_to_api_args(
            spec, vserver=self.vserver)
        return self.connection.send_request(
            'qos-policy-group-create', api_args, False)

    def qos_adaptive_policy_group_create(self, spec):
        """Creates a QOS adaptive policy group."""
        api_args = self._qos_spec_to_api_args(
            spec, vserver=self.vserver)
        return self.connection.send_request(
            'qos-adaptive-policy-group-create', api_args, False)

    def qos_policy_group_modify(self, spec):
        """Modifies a QOS policy group."""
        api_args = self._qos_spec_to_api_args(spec)
        return self.connection.send_request(
            'qos-policy-group-modify', api_args, False)

    def qos_adaptive_policy_group_modify(self, spec):
        """Modifies a QOS adaptive policy group."""
        api_args = self._qos_spec_to_api_args(spec)
        return self.connection.send_request(
            'qos-adaptive-policy-group-modify', api_args, False)

    def qos_policy_group_rename(self, qos_policy_group_name, new_name,
                                is_adaptive=False):
        """Renames a QOS policy group."""
        request_name = 'qos-%spolicy-group-rename' % (
            'adaptive-' if is_adaptive else '')
        api_args = {
            'policy-group-name': qos_policy_group_name,
            'new-name': new_name,
        }
        return self.connection.send_request(request_name, api_args, False)

    def mark_qos_policy_group_for_deletion(self, qos_policy_group_info,
                                           is_adaptive=False):
        """Soft delete a QOS policy group backing a cinder volume."""
        if qos_policy_group_info is None:
            return

        spec = qos_policy_group_info.get('spec')

        # For cDOT we want to delete the QoS policy group that we created for
        # this cinder volume.  Because the QoS policy may still be "in use"
        # after the zapi call to delete the volume itself returns successfully,
        # we instead rename the QoS policy group using a specific pattern and
        # later attempt on a best effort basis to delete any QoS policy groups
        # matching that pattern.
        if spec:
            current_name = spec['policy_name']
            new_name = client_base.DELETED_PREFIX + current_name
            try:
                self.qos_policy_group_rename(current_name, new_name,
                                             is_adaptive)
            except netapp_api.NaApiError as ex:
                LOG.warning('Rename failure in cleanup of cDOT QOS policy '
                            'group %(name)s: %(ex)s',
                            {'name': current_name, 'ex': ex})

        # Attempt to delete any QoS policies named "delete-openstack-*".
        self.remove_unused_qos_policy_groups()

    def _send_qos_policy_group_delete_iter_request(self, is_adaptive=False):
        request_name = 'qos-%spolicy-group-delete-iter' % (
            'adaptive-' if is_adaptive else '')
        query_name = 'qos-%spolicy-group-info' % (
            'adaptive-' if is_adaptive else '')

        api_args = {
            'query': {
                query_name: {
                    'policy-group': '%s*' % client_base.DELETED_PREFIX,
                    'vserver': self.vserver,
                }
            },
            'max-records': 3500,
            'continue-on-failure': 'true',
            'return-success-list': 'false',
            'return-failure-list': 'false',
        }

        try:
            self.connection.send_request(request_name, api_args, False)
        except netapp_api.NaApiError as ex:
            msg = ('Could not delete QOS %(prefix)spolicy groups. '
                   'Details: %(ex)s')
            msg_args = {
                'prefix': 'adaptive ' if is_adaptive else '',
                'ex': ex,
            }
            LOG.debug(msg, msg_args)

    def remove_unused_qos_policy_groups(self):
        """Deletes all QOS policy groups that are marked for deletion."""
        self._send_qos_policy_group_delete_iter_request()
        if self.features.ADAPTIVE_QOS:
            self._send_qos_policy_group_delete_iter_request(is_adaptive=True)

    def set_lun_qos_policy_group(self, path, qos_policy_group,
                                 is_adaptive=False):
        """Sets qos_policy_group on a LUN."""
        self._validate_qos_policy_group(is_adaptive)

        policy_group_key = 'qos-%spolicy-group' % (
            'adaptive-' if is_adaptive else '')
        api_args = {
            'path': path,
            policy_group_key: qos_policy_group,
        }
        return self.connection.send_request(
            'lun-set-qos-policy-group', api_args)

    def get_if_info_by_ip(self, ip):
        """Gets the network interface info by ip."""
        net_if_iter = netapp_api.NaElement('net-interface-get-iter')
        net_if_iter.add_new_child('max-records', '10')
        query = netapp_api.NaElement('query')
        net_if_iter.add_child_elem(query)
        query.add_node_with_children(
            'net-interface-info',
            **{'address': volume_utils.resolve_hostname(ip)})
        result = self.connection.invoke_successfully(net_if_iter, True)
        num_records = result.get_child_content('num-records')
        if num_records and int(num_records) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            return attr_list.get_children()
        raise exception.NotFound(
            _('No interface found on cluster for ip %s') % ip)

    def get_vol_by_junc_vserver(self, vserver, junction):
        """Gets the volume by junction path and vserver."""
        vol_iter = netapp_api.NaElement('volume-get-iter')
        vol_iter.add_new_child('max-records', '10')
        query = netapp_api.NaElement('query')
        vol_iter.add_child_elem(query)
        vol_attrs = netapp_api.NaElement('volume-attributes')
        query.add_child_elem(vol_attrs)
        vol_attrs.add_node_with_children(
            'volume-id-attributes',
            **{'junction-path': junction,
               'owning-vserver-name': vserver})
        des_attrs = netapp_api.NaElement('desired-attributes')
        des_attrs.add_node_with_children('volume-attributes',
                                         **{'volume-id-attributes': None})
        vol_iter.add_child_elem(des_attrs)
        result = self._invoke_vserver_api(vol_iter, vserver)
        num_records = result.get_child_content('num-records')
        if num_records and int(num_records) >= 1:
            volume_attr = self.get_unique_volume(result)
            vol_id = volume_attr.get_child_by_name('volume-id-attributes')
            return vol_id.get_child_content('name')
        msg_fmt = {'vserver': vserver, 'junction': junction}
        raise exception.NotFound(_("No volume on cluster with vserver "
                                   "%(vserver)s and junction path "
                                   "%(junction)s ") % msg_fmt)

    def clone_file(self, flex_vol, src_path, dest_path, vserver,
                   dest_exists=False, source_snapshot=None,
                   is_snapshot=False):
        """Clones file on vserver."""
        LOG.debug("Cloning with params volume %(volume)s, src %(src_path)s, "
                  "dest %(dest_path)s, vserver %(vserver)s,"
                  "source_snapshot %(source_snapshot)s",
                  {'volume': flex_vol, 'src_path': src_path,
                   'dest_path': dest_path, 'vserver': vserver,
                   'source_snapshot': source_snapshot})
        zapi_args = {
            'volume': flex_vol,
            'source-path': src_path,
            'destination-path': dest_path,
        }
        if is_snapshot and self.features.BACKUP_CLONE_PARAM:
            zapi_args['is-backup'] = 'true'
        if source_snapshot:
            zapi_args['snapshot-name'] = source_snapshot
        clone_create = netapp_api.NaElement.create_node_with_children(
            'clone-create', **zapi_args)
        major, minor = self.connection.get_api_version()
        if major == 1 and minor >= 20 and dest_exists:
            clone_create.add_new_child('destination-exists', 'true')
        self._invoke_vserver_api(clone_create, vserver)

    def get_file_usage(self, path, vserver):
        """Gets the file unique bytes."""
        LOG.debug('Getting file usage for %s', path)
        file_use = netapp_api.NaElement.create_node_with_children(
            'file-usage-get', **{'path': path})
        res = self._invoke_vserver_api(file_use, vserver)
        unique_bytes = res.get_child_content('unique-bytes')
        LOG.debug('file-usage for path %(path)s is %(bytes)s',
                  {'path': path, 'bytes': unique_bytes})
        return unique_bytes

    def check_cluster_api(self, object_name, operation_name, api):
        """Checks the availability of a cluster API.

        Returns True if the specified cluster API exists and may be called by
        the current user. The API is *called* on Data ONTAP versions prior to
        8.2, while versions starting with 8.2 utilize an API designed for
        this purpose.
        """

        if not self.features.USER_CAPABILITY_LIST:
            return self._check_cluster_api_legacy(api)
        else:
            return self._check_cluster_api(object_name, operation_name, api)

    def _check_cluster_api(self, object_name, operation_name, api):
        """Checks the availability of a cluster API.

        Returns True if the specified cluster API exists and may be called by
        the current user.  This method assumes Data ONTAP 8.2 or higher.
        """

        api_args = {
            'query': {
                'capability-info': {
                    'object-name': object_name,
                    'operation-list': {
                        'operation-info': {
                            'name': operation_name,
                        },
                    },
                },
            },
            'desired-attributes': {
                'capability-info': {
                    'operation-list': {
                        'operation-info': {
                            'api-name': None,
                        },
                    },
                },
            },
        }
        result = self.connection.send_request(
            'system-user-capability-get-iter', api_args, False)

        if not self._has_records(result):
            return False

        capability_info_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        for capability_info in capability_info_list.get_children():

            operation_list = capability_info.get_child_by_name(
                'operation-list') or netapp_api.NaElement('none')

            for operation_info in operation_list.get_children():
                api_name = operation_info.get_child_content('api-name') or ''
                api_names = api_name.split(',')
                if api in api_names:
                    return True

        return False

    def _check_cluster_api_legacy(self, api):
        """Checks the availability of a cluster API.

        Returns True if the specified cluster API exists and may be called by
        the current user.  This method should only be used for Data ONTAP 8.1,
        and only getter APIs may be tested because the API is actually called
        to perform the check.
        """

        if not re.match(".*-get$|.*-get-iter$|.*-list-info$", api):
            raise ValueError(_('Non-getter API passed to API test method.'))

        try:
            self.connection.send_request(api, enable_tunneling=False)
        except netapp_api.NaApiError as ex:
            if ex.code in (netapp_api.EAPIPRIVILEGE, netapp_api.EAPINOTFOUND):
                return False

        return True

    def get_operational_lif_addresses(self):
        """Gets the IP addresses of operational LIFs on the vserver."""

        net_interface_get_iter_args = {
            'query': {
                'net-interface-info': {
                    'operational-status': 'up'
                }
            },
            'desired-attributes': {
                'net-interface-info': {
                    'address': None,
                }
            }
        }
        result = self.send_iter_request('net-interface-get-iter',
                                        net_interface_get_iter_args)

        lif_info_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        return [lif_info.get_child_content('address') for lif_info in
                lif_info_list.get_children()]

    def get_flexvol_capacity(self, flexvol_path=None, flexvol_name=None):
        """Gets total capacity and free capacity, in bytes, of the flexvol."""

        volume_id_attributes = {}
        if flexvol_path:
            volume_id_attributes['junction-path'] = flexvol_path
        if flexvol_name:
            volume_id_attributes['name'] = flexvol_name

        api_args = {
            'query': {
                'volume-attributes': {
                    'volume-id-attributes': volume_id_attributes,
                }
            },
            'desired-attributes': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'style-extended': None,
                    },
                    'volume-space-attributes': {
                        'size-available': None,
                        'size-total': None,
                    }
                }
            },
        }

        result = self.send_iter_request('volume-get-iter', api_args)
        if self._get_record_count(result) < 1:
            msg = _('Volume %s not found.')
            msg_args = flexvol_path or flexvol_name
            raise na_utils.NetAppDriverException(msg % msg_args)

        volume_attributes = self.get_unique_volume(result)
        volume_space_attributes = volume_attributes.get_child_by_name(
            'volume-space-attributes')

        size_available = float(
            volume_space_attributes.get_child_content('size-available'))
        size_total = float(
            volume_space_attributes.get_child_content('size-total'))

        return {
            'size-total': size_total,
            'size-available': size_available,
        }

    def get_unique_volume(self, get_volume_result):
        """Get the unique FlexVol or FleGroup volume from a get volume list"""
        volume_list = []
        attributes_list = get_volume_result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        for volume_attributes in attributes_list.get_children():
            volume_id_attributes = volume_attributes.get_child_by_name(
                'volume-id-attributes') or netapp_api.NaElement('none')
            style = volume_id_attributes.get_child_content('style-extended')
            if style == 'flexvol' or style == 'flexgroup':
                volume_list.append(volume_attributes)

        if len(volume_list) != 1:
            msg = _('Could not find unique volume. Volumes found: %(vol)s.')
            msg_args = {'vol': volume_list}
            raise exception.VolumeBackendAPIException(data=msg % msg_args)

        return volume_list[0]

    def list_flexvols(self):
        """Returns the names of the flexvols on the controller."""

        api_args = {
            'query': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'type': 'rw',
                        'style': 'flex',
                    },
                    'volume-state-attributes': {
                        'is-vserver-root': 'false',
                        'is-inconsistent': 'false',
                        'is-invalid': 'false',
                        'state': 'online',
                    },
                },
            },
            'desired-attributes': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'name': None,
                    },
                },
            },
        }
        result = self.send_iter_request('volume-get-iter', api_args)
        if not self._has_records(result):
            return []

        volumes = []

        attributes_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        for volume_attributes in attributes_list.get_children():

            volume_id_attributes = volume_attributes.get_child_by_name(
                'volume-id-attributes') or netapp_api.NaElement('none')

            volumes.append(volume_id_attributes.get_child_content('name'))

        return volumes

    def get_volume_state(self, junction_path=None, name=None):
        """Returns volume state for a given name or junction path"""

        volume_id_attributes = {}
        if junction_path:
            volume_id_attributes['junction-path'] = junction_path
        if name:
            volume_id_attributes['name'] = name

        api_args = {
            'query': {
                'volume-attributes': {
                    'volume-id-attributes': volume_id_attributes
                }
            },
            'desired-attributes': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'style-extended': None
                    },
                    'volume-state-attributes': {
                        'state': None
                    }
                }
            }
        }
        result = self.send_iter_request('volume-get-iter', api_args)
        try:
            volume_attributes = self.get_unique_volume(result)
        except exception.VolumeBackendAPIException:
            return None

        volume_state_attributes = volume_attributes.get_child_by_name(
            'volume-state-attributes') or netapp_api.NaElement('none')
        volume_state = volume_state_attributes.get_child_content('state')
        return volume_state

    def get_flexvol(self, flexvol_path=None, flexvol_name=None):
        """Get flexvol attributes needed for the storage service catalog."""

        volume_id_attributes = {'type': 'rw', 'style': 'flex'}
        if flexvol_path:
            volume_id_attributes['junction-path'] = flexvol_path
        if flexvol_name:
            volume_id_attributes['name'] = flexvol_name

        api_args = {
            'query': {
                'volume-attributes': {
                    'volume-id-attributes': volume_id_attributes,
                    'volume-state-attributes': {
                        'is-vserver-root': 'false',
                        'is-inconsistent': 'false',
                        'is-invalid': 'false',
                        'state': 'online',
                    },
                },
            },
            'desired-attributes': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'name': None,
                        'owning-vserver-name': None,
                        'junction-path': None,
                        'aggr-list': {
                            'aggr-name': None,
                        },
                        'containing-aggregate-name': None,
                        'type': None,
                        'style-extended': None,
                    },
                    'volume-mirror-attributes': {
                        'is-data-protection-mirror': None,
                        'is-replica-volume': None,
                    },
                    'volume-space-attributes': {
                        'is-space-guarantee-enabled': None,
                        'space-guarantee': None,
                        'percentage-snapshot-reserve': None,
                        'size': None,
                    },
                    'volume-qos-attributes': {
                        'policy-group-name': None,
                    },
                    'volume-snapshot-attributes': {
                        'snapshot-policy': None,
                    },
                    'volume-language-attributes': {
                        'language-code': None,
                    },
                },
            },
        }
        result = self.send_iter_request('volume-get-iter', api_args)

        volume_attributes = self.get_unique_volume(result)

        volume_id_attributes = volume_attributes.get_child_by_name(
            'volume-id-attributes') or netapp_api.NaElement('none')
        aggr = volume_id_attributes.get_child_content(
            'containing-aggregate-name')
        if not aggr:
            aggr_list_attr = volume_id_attributes.get_child_by_name(
                'aggr-list') or netapp_api.NaElement('none')
            aggr = [aggr_elem.get_content()
                    for aggr_elem in
                    aggr_list_attr.get_children()]

        volume_space_attributes = volume_attributes.get_child_by_name(
            'volume-space-attributes') or netapp_api.NaElement('none')
        volume_qos_attributes = volume_attributes.get_child_by_name(
            'volume-qos-attributes') or netapp_api.NaElement('none')
        volume_snapshot_attributes = volume_attributes.get_child_by_name(
            'volume-snapshot-attributes') or netapp_api.NaElement('none')
        volume_language_attributes = volume_attributes.get_child_by_name(
            'volume-language-attributes') or netapp_api.NaElement('none')

        volume = {
            'name': volume_id_attributes.get_child_content('name'),
            'vserver': volume_id_attributes.get_child_content(
                'owning-vserver-name'),
            'junction-path': volume_id_attributes.get_child_content(
                'junction-path'),
            'aggregate': aggr,
            'type': volume_id_attributes.get_child_content('type'),
            'space-guarantee-enabled': strutils.bool_from_string(
                volume_space_attributes.get_child_content(
                    'is-space-guarantee-enabled')),
            'space-guarantee': volume_space_attributes.get_child_content(
                'space-guarantee'),
            'percentage-snapshot-reserve': (
                volume_space_attributes.get_child_content(
                    'percentage-snapshot-reserve')),
            'size': volume_space_attributes.get_child_content('size'),
            'qos-policy-group': volume_qos_attributes.get_child_content(
                'policy-group-name'),
            'snapshot-policy': volume_snapshot_attributes.get_child_content(
                'snapshot-policy'),
            'language': volume_language_attributes.get_child_content(
                'language-code'),
            'style-extended': volume_id_attributes.get_child_content(
                'style-extended'),

        }

        return volume

    def get_flexvol_dedupe_info(self, flexvol_name):
        """Get dedupe attributes needed for the storage service catalog."""

        api_args = {
            'query': {
                'sis-status-info': {
                    'path': '/vol/%s' % flexvol_name,
                },
            },
            'desired-attributes': {
                'sis-status-info': {
                    'state': None,
                    'is-compression-enabled': None,
                    'logical-data-size': None,
                    'logical-data-limit': None,
                },
            },
        }

        no_dedupe_response = {
            'compression': False,
            'dedupe': False,
            'logical-data-size': 0,
            'logical-data-limit': 1,
        }

        try:
            result = self.send_iter_request('sis-get-iter', api_args)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get dedupe info for volume %s.',
                          flexvol_name)
            return no_dedupe_response

        if self._get_record_count(result) != 1:
            return no_dedupe_response

        attributes_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        sis_status_info = attributes_list.get_child_by_name(
            'sis-status-info') or netapp_api.NaElement('none')

        logical_data_size = sis_status_info.get_child_content(
            'logical-data-size') or 0
        logical_data_limit = sis_status_info.get_child_content(
            'logical-data-limit') or 1

        sis = {
            'compression': strutils.bool_from_string(
                sis_status_info.get_child_content('is-compression-enabled')),
            'dedupe': na_utils.to_bool(
                sis_status_info.get_child_content('state')),
            'logical-data-size': int(logical_data_size),
            'logical-data-limit': int(logical_data_limit),
        }

        return sis

    def get_flexvol_dedupe_used_percent(self, flexvol_name):
        """Determine how close a flexvol is to its shared block limit."""

        # Note(cknight): The value returned by this method is computed from
        # values returned by two different APIs, one of which was new in
        # Data ONTAP 8.3.
        if not self.features.CLONE_SPLIT_STATUS:
            return 0.0

        dedupe_info = self.get_flexvol_dedupe_info(flexvol_name)
        clone_split_info = self.get_clone_split_info(flexvol_name)

        total_dedupe_blocks = (dedupe_info.get('logical-data-size') +
                               clone_split_info.get('unsplit-size'))
        dedupe_used_percent = (100.0 * float(total_dedupe_blocks) /
                               dedupe_info.get('logical-data-limit'))
        return dedupe_used_percent

    def get_clone_split_info(self, flexvol_name):
        """Get the status of unsplit file/LUN clones in a flexvol."""

        try:
            result = self.connection.send_request(
                'clone-split-status', {'volume-name': flexvol_name})
        except netapp_api.NaApiError:
            LOG.exception('Failed to get clone split info for volume %s.',
                          flexvol_name)
            return {'unsplit-size': 0, 'unsplit-clone-count': 0}

        clone_split_info = result.get_child_by_name(
            'clone-split-info') or netapp_api.NaElement('none')

        unsplit_size = clone_split_info.get_child_content('unsplit-size') or 0
        unsplit_clone_count = clone_split_info.get_child_content(
            'unsplit-clone-count') or 0

        return {
            'unsplit-size': int(unsplit_size),
            'unsplit-clone-count': int(unsplit_clone_count),
        }

    def is_flexvol_mirrored(self, flexvol_name, vserver_name):
        """Check if flexvol is a SnapMirror source."""

        api_args = {
            'query': {
                'snapmirror-info': {
                    'source-vserver': vserver_name,
                    'source-volume': flexvol_name,
                    'mirror-state': 'snapmirrored',
                    'relationship-type': 'data_protection',
                },
            },
            'desired-attributes': {
                'snapmirror-info': None,
            },
        }

        try:
            result = self.send_iter_request('snapmirror-get-iter', api_args)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get SnapMirror info for volume %s.',
                          flexvol_name)
            return False

        if not self._has_records(result):
            return False

        return True

    def is_flexvol_encrypted(self, flexvol_name, vserver_name):
        """Check if a flexvol is encrypted."""

        if not self.features.FLEXVOL_ENCRYPTION:
            return False

        api_args = {
            'query': {
                'volume-attributes': {
                    'encrypt': 'true',
                    'volume-id-attributes': {
                        'name': flexvol_name,
                        'owning-vserver-name': vserver_name,
                    },
                },
            },
            'desired-attributes': {
                'volume-attributes': {
                    'encrypt': None,
                },
            },
        }

        try:
            result = self.send_iter_request('volume-get-iter', api_args)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get Encryption info for volume %s.',
                          flexvol_name)
            return False

        if not self._has_records(result):
            return False

        return True

    def is_qos_min_supported(self, is_nfs, node_name):
        """Check if the node supports QoS minimum."""
        qos_min_name = na_utils.qos_min_feature_name(is_nfs, node_name)
        return getattr(self.features, qos_min_name, False).__bool__()

    def create_volume_async(self, name, aggregate_list, size_gb,
                            space_guarantee_type=None, snapshot_policy=None,
                            language=None, snapshot_reserve=None,
                            volume_type='rw'):
        """Creates a FlexGroup volume asynchronously."""

        api_args = {
            'aggr-list': [{'aggr-name': aggr} for aggr in aggregate_list],
            'size': size_gb * units.Gi,
            'volume-name': name,
            'volume-type': volume_type,
        }
        if volume_type == 'dp':
            snapshot_policy = None
        else:
            api_args['junction-path'] = '/%s' % name
        if snapshot_policy is not None:
            api_args['snapshot-policy'] = snapshot_policy
        if space_guarantee_type:
            api_args['space-reserve'] = space_guarantee_type
        if language is not None:
            api_args['language-code'] = language
        if snapshot_reserve is not None:
            api_args['percentage-snapshot-reserve'] = six.text_type(
                snapshot_reserve)

        result = self.connection.send_request('volume-create-async', api_args)
        job_info = {
            'status': result.get_child_content('result-status'),
            'jobid': result.get_child_content('result-jobid'),
            'error-code': result.get_child_content('result-error-code'),
            'error-message': result.get_child_content('result-error-message')
        }
        return job_info

    def create_flexvol(self, flexvol_name, aggregate_name, size_gb,
                       space_guarantee_type=None, snapshot_policy=None,
                       language=None, dedupe_enabled=False,
                       compression_enabled=False, snapshot_reserve=None,
                       volume_type='rw'):

        """Creates a volume."""
        api_args = {
            'containing-aggr-name': aggregate_name,
            'size': six.text_type(size_gb) + 'g',
            'volume': flexvol_name,
            'volume-type': volume_type,
        }
        if volume_type == 'dp':
            snapshot_policy = None
        else:
            api_args['junction-path'] = '/%s' % flexvol_name
        if snapshot_policy is not None:
            api_args['snapshot-policy'] = snapshot_policy
        if space_guarantee_type:
            api_args['space-reserve'] = space_guarantee_type
        if language is not None:
            api_args['language-code'] = language
        if snapshot_reserve is not None:
            api_args['percentage-snapshot-reserve'] = six.text_type(
                snapshot_reserve)
        self.connection.send_request('volume-create', api_args)

        # cDOT compression requires that deduplication be enabled.
        if dedupe_enabled or compression_enabled:
            self.enable_flexvol_dedupe(flexvol_name)
        if compression_enabled:
            self.enable_flexvol_compression(flexvol_name)

    def flexvol_exists(self, volume_name):
        """Checks if a flexvol exists on the storage array."""
        LOG.debug('Checking if volume %s exists', volume_name)

        api_args = {
            'query': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'name': volume_name,
                    },
                },
            },
            'desired-attributes': {
                'volume-attributes': {
                    'volume-id-attributes': {
                        'name': None,
                    },
                },
            },
        }
        result = self.send_iter_request('volume-get-iter', api_args)
        return self._has_records(result)

    def rename_flexvol(self, orig_flexvol_name, new_flexvol_name):
        """Set flexvol name."""
        api_args = {
            'volume': orig_flexvol_name,
            'new-volume-name': new_flexvol_name,
        }
        self.connection.send_request('volume-rename', api_args)

    def rename_file(self, orig_file_name, new_file_name):
        """Rename a volume file."""
        LOG.debug("Renaming the file %(original)s to %(new)s.",
                  {'original': orig_file_name, 'new': new_file_name})

        api_args = {
            'from-path': orig_file_name,
            'to-path': new_file_name,
        }
        self.connection.send_request('file-rename-file', api_args)

    def mount_flexvol(self, flexvol_name, junction_path=None):
        """Mounts a volume on a junction path."""
        api_args = {
            'volume-name': flexvol_name,
            'junction-path': (junction_path if junction_path
                              else '/%s' % flexvol_name)
        }
        self.connection.send_request('volume-mount', api_args)

    def enable_flexvol_dedupe(self, flexvol_name):
        """Enable deduplication on volume."""
        api_args = {'path': '/vol/%s' % flexvol_name}
        self.connection.send_request('sis-enable', api_args)

    def disable_flexvol_dedupe(self, flexvol_name):
        """Disable deduplication on volume."""
        api_args = {'path': '/vol/%s' % flexvol_name}
        self.connection.send_request('sis-disable', api_args)

    def enable_flexvol_compression(self, flexvol_name):
        """Enable compression on volume."""
        api_args = {
            'path': '/vol/%s' % flexvol_name,
            'enable-compression': 'true'
        }
        self.connection.send_request('sis-set-config', api_args)

    def disable_flexvol_compression(self, flexvol_name):
        """Disable compression on volume."""
        api_args = {
            'path': '/vol/%s' % flexvol_name,
            'enable-compression': 'false'
        }
        self.connection.send_request('sis-set-config', api_args)

    def enable_volume_dedupe_async(self, volume_name):
        """Enable deduplication on FlexVol/FlexGroup volume asynchronously."""
        api_args = {'volume-name': volume_name}
        self.connection.send_request('sis-enable-async', api_args)

    def disable_volume_dedupe_async(self, volume_name):
        """Disable deduplication on FlexVol/FlexGroup volume asynchronously."""
        api_args = {'volume-name': volume_name}
        self.connection.send_request('sis-disable-async', api_args)

    def enable_volume_compression_async(self, volume_name):
        """Enable compression on FlexVol/FlexGroup volume asynchronously."""
        api_args = {
            'volume-name': volume_name,
            'enable-compression': 'true'
        }
        self.connection.send_request('sis-set-config-async', api_args)

    def disable_volume_compression_async(self, volume_name):
        """Disable compression on FlexVol/FlexGroup volume asynchronously."""
        api_args = {
            'volume-name': volume_name,
            'enable-compression': 'false'
        }
        self.connection.send_request('sis-set-config-async', api_args)

    @volume_utils.trace_method
    def delete_file(self, path_to_file):
        """Delete file at path."""

        api_args = {
            'path': path_to_file,
        }
        # Use fast clone deletion engine if it is supported.
        if self.features.FAST_CLONE_DELETE:
            api_args['is-clone-file'] = 'true'
        self.connection.send_request('file-delete-file', api_args, True)

    def _get_aggregates(self, aggregate_names=None, desired_attributes=None):

        query = {
            'aggr-attributes': {
                'aggregate-name': '|'.join(aggregate_names),
            }
        } if aggregate_names else None

        api_args = {}
        if query:
            api_args['query'] = query
        if desired_attributes:
            api_args['desired-attributes'] = desired_attributes

        result = self.connection.send_request('aggr-get-iter',
                                              api_args,
                                              enable_tunneling=False)
        if not self._has_records(result):
            return []
        else:
            return result.get_child_by_name('attributes-list').get_children()

    def get_node_for_aggregate(self, aggregate_name):
        """Get home node for the specified aggregate.

        This API could return None, most notably if it was sent
        to a Vserver LIF, so the caller must be able to handle that case.
        """

        if not aggregate_name:
            return None

        desired_attributes = {
            'aggr-attributes': {
                'aggregate-name': None,
                'aggr-ownership-attributes': {
                    'home-name': None,
                },
            },
        }

        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         desired_attributes=desired_attributes)
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.EAPINOTFOUND:
                return None
            else:
                raise

        if len(aggrs) < 1:
            return None

        aggr_ownership_attrs = aggrs[0].get_child_by_name(
            'aggr-ownership-attributes') or netapp_api.NaElement('none')
        return aggr_ownership_attrs.get_child_content('home-name')

    def get_aggregate(self, aggregate_name):
        """Get aggregate attributes needed for the storage service catalog."""

        if not aggregate_name:
            return {}

        desired_attributes = {
            'aggr-attributes': {
                'aggregate-name': None,
                'aggr-raid-attributes': {
                    'raid-type': None,
                    'is-hybrid': None,
                },
                'aggr-ownership-attributes': {
                    'home-name': None,
                },
            },
        }

        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         desired_attributes=desired_attributes)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get info for aggregate %s.',
                          aggregate_name)
            return {}

        if len(aggrs) < 1:
            return {}

        aggr_attributes = aggrs[0]
        aggr_raid_attrs = aggr_attributes.get_child_by_name(
            'aggr-raid-attributes') or netapp_api.NaElement('none')
        aggr_ownership_attrs = aggrs[0].get_child_by_name(
            'aggr-ownership-attributes') or netapp_api.NaElement('none')

        aggregate = {
            'name': aggr_attributes.get_child_content('aggregate-name'),
            'raid-type': aggr_raid_attrs.get_child_content('raid-type'),
            'is-hybrid': strutils.bool_from_string(
                aggr_raid_attrs.get_child_content('is-hybrid')),
            'node-name': aggr_ownership_attrs.get_child_content('home-name'),
        }

        return aggregate

    def get_aggregate_disk_types(self, aggregate_name):
        """Get the disk type(s) of an aggregate."""

        disk_types = set()
        disk_types.update(self._get_aggregate_disk_types(aggregate_name))
        if self.features.ADVANCED_DISK_PARTITIONING:
            disk_types.update(self._get_aggregate_disk_types(aggregate_name,
                                                             shared=True))

        return list(disk_types) if disk_types else None

    def _get_aggregate_disk_types(self, aggregate_name, shared=False):
        """Get the disk type(s) of an aggregate (may be a list)."""

        disk_types = set()

        if shared:
            disk_raid_info = {
                'disk-shared-info': {
                    'aggregate-list': {
                        'shared-aggregate-info': {
                            'aggregate-name': aggregate_name,
                        },
                    },
                },
            }
        else:
            disk_raid_info = {
                'disk-aggregate-info': {
                    'aggregate-name': aggregate_name,
                },
            }

        api_args = {
            'query': {
                'storage-disk-info': {
                    'disk-raid-info': disk_raid_info,
                },
            },
            'desired-attributes': {
                'storage-disk-info': {
                    'disk-raid-info': {
                        'effective-disk-type': None,
                    },
                },
            },
        }

        try:
            result = self.send_iter_request(
                'storage-disk-get-iter', api_args, enable_tunneling=False)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get disk info for aggregate %s.',
                          aggregate_name)
            return disk_types

        attributes_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')

        for storage_disk_info in attributes_list.get_children():

            disk_raid_info = storage_disk_info.get_child_by_name(
                'disk-raid-info') or netapp_api.NaElement('none')
            disk_type = disk_raid_info.get_child_content(
                'effective-disk-type')
            if disk_type:
                disk_types.add(disk_type)

        return disk_types

    def get_aggregate_capacities(self, aggregate_names):
        """Gets capacity info for multiple aggregates."""

        if not isinstance(aggregate_names, list):
            return {}

        aggregates = {}
        for aggregate_name in aggregate_names:
            aggregates[aggregate_name] = self.get_aggregate_capacity(
                aggregate_name)

        return aggregates

    def get_aggregate_capacity(self, aggregate_name):
        """Gets capacity info for an aggregate."""

        desired_attributes = {
            'aggr-attributes': {
                'aggr-space-attributes': {
                    'percent-used-capacity': None,
                    'size-available': None,
                    'size-total': None,
                },
            },
        }

        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         desired_attributes=desired_attributes)
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.EAPINOTFOUND:
                LOG.debug('Aggregate capacity can only be collected with '
                          'cluster scoped credentials.')
            else:
                LOG.exception('Failed to get info for aggregate %s.',
                              aggregate_name)
            return {}

        if len(aggrs) < 1:
            return {}

        aggr_attributes = aggrs[0]
        aggr_space_attributes = aggr_attributes.get_child_by_name(
            'aggr-space-attributes') or netapp_api.NaElement('none')

        percent_used = int(aggr_space_attributes.get_child_content(
            'percent-used-capacity'))
        size_available = float(aggr_space_attributes.get_child_content(
            'size-available'))
        size_total = float(
            aggr_space_attributes.get_child_content('size-total'))

        return {
            'percent-used': percent_used,
            'size-available': size_available,
            'size-total': size_total,
        }

    def get_performance_instance_uuids(self, object_name, node_name):
        """Get UUIDs of performance instances for a cluster node."""

        api_args = {
            'objectname': object_name,
            'query': {
                'instance-info': {
                    'uuid': node_name + ':*',
                }
            }
        }

        result = self.connection.send_request(
            'perf-object-instance-list-info-iter', api_args,
            enable_tunneling=False)

        uuids = []

        instances = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('None')

        for instance_info in instances.get_children():
            uuids.append(instance_info.get_child_content('uuid'))

        return uuids

    def get_performance_counters(self, object_name, instance_uuids,
                                 counter_names):
        """Gets more cDOT performance counters."""

        api_args = {
            'objectname': object_name,
            'instance-uuids': [
                {'instance-uuid': instance_uuid}
                for instance_uuid in instance_uuids
            ],
            'counters': [
                {'counter': counter} for counter in counter_names
            ],
        }

        result = self.connection.send_request(
            'perf-object-get-instances', api_args, enable_tunneling=False)

        counter_data = []

        timestamp = result.get_child_content('timestamp')

        instances = result.get_child_by_name(
            'instances') or netapp_api.NaElement('None')
        for instance in instances.get_children():

            instance_name = instance.get_child_content('name')
            instance_uuid = instance.get_child_content('uuid')
            node_name = instance_uuid.split(':')[0]

            counters = instance.get_child_by_name(
                'counters') or netapp_api.NaElement('None')
            for counter in counters.get_children():

                counter_name = counter.get_child_content('name')
                counter_value = counter.get_child_content('value')

                counter_data.append({
                    'instance-name': instance_name,
                    'instance-uuid': instance_uuid,
                    'node-name': node_name,
                    'timestamp': timestamp,
                    counter_name: counter_value,
                })

        return counter_data

    def get_snapshots_marked_for_deletion(self):
        """Get a list of snapshots marked for deletion."""

        api_args = {
            'query': {
                'snapshot-info': {
                    'name': client_base.DELETED_PREFIX + '*',
                    'vserver': self.vserver,
                    'busy': 'false',
                },
            },
            'desired-attributes': {
                'snapshot-info': {
                    'name': None,
                    'volume': None,
                    'snapshot-instance-uuid': None,
                }
            },
        }

        result = self.connection.send_request('snapshot-get-iter', api_args)

        snapshots = []

        attributes = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')
        snapshot_info_list = attributes.get_children()
        for snapshot_info in snapshot_info_list:
            snapshot_name = snapshot_info.get_child_content('name')
            snapshot_id = snapshot_info.get_child_content(
                'snapshot-instance-uuid')
            snapshot_volume = snapshot_info.get_child_content('volume')

            snapshots.append({
                'name': snapshot_name,
                'instance_id': snapshot_id,
                'volume_name': snapshot_volume,
            })

        return snapshots

    def get_snapshot(self, volume_name, snapshot_name):
        """Gets a single snapshot."""
        api_args = {
            'query': {
                'snapshot-info': {
                    'name': snapshot_name,
                    'volume': volume_name,
                },
            },
            'desired-attributes': {
                'snapshot-info': {
                    'name': None,
                    'volume': None,
                    'busy': None,
                    'snapshot-owners-list': {
                        'snapshot-owner': None,
                    }
                },
            },
        }
        result = self.connection.send_request('snapshot-get-iter', api_args)

        self._handle_get_snapshot_return_failure(result, snapshot_name)

        attributes_list = result.get_child_by_name(
            'attributes-list') or netapp_api.NaElement('none')
        snapshot_info_list = attributes_list.get_children()

        self._handle_snapshot_not_found(result, snapshot_info_list,
                                        snapshot_name, volume_name)

        snapshot_info = snapshot_info_list[0]
        snapshot = {
            'name': snapshot_info.get_child_content('name'),
            'volume': snapshot_info.get_child_content('volume'),
            'busy': strutils.bool_from_string(
                snapshot_info.get_child_content('busy')),
        }

        snapshot_owners_list = snapshot_info.get_child_by_name(
            'snapshot-owners-list') or netapp_api.NaElement('none')
        snapshot_owners = set([
            snapshot_owner.get_child_content('owner')
            for snapshot_owner in snapshot_owners_list.get_children()])
        snapshot['owners'] = snapshot_owners

        return snapshot

    def _handle_get_snapshot_return_failure(self, result, snapshot_name):
        error_record_list = result.get_child_by_name(
            'volume-errors') or netapp_api.NaElement('none')
        errors = error_record_list.get_children()

        if errors:
            error = errors[0]
            error_code = error.get_child_content('errno')
            error_reason = error.get_child_content('reason')
            msg = _('Could not read information for snapshot %(name)s. '
                    'Code: %(code)s. Reason: %(reason)s')
            msg_args = {
                'name': snapshot_name,
                'code': error_code,
                'reason': error_reason,
            }
            if error_code == netapp_api.ESNAPSHOTNOTALLOWED:
                raise exception.SnapshotUnavailable(data=msg % msg_args)
            else:
                raise exception.VolumeBackendAPIException(data=msg % msg_args)

    def _handle_snapshot_not_found(self, result, snapshot_info_list,
                                   snapshot_name, volume_name):
        if not self._has_records(result):
            raise exception.SnapshotNotFound(snapshot_id=snapshot_name)
        elif len(snapshot_info_list) > 1:
            msg = _('Could not find unique snapshot %(snap)s on '
                    'volume %(vol)s.')
            msg_args = {'snap': snapshot_name, 'vol': volume_name}
            raise exception.VolumeBackendAPIException(data=msg % msg_args)

    def get_cluster_name(self):
        """Gets cluster name."""
        api_args = {
            'desired-attributes': {
                'cluster-identity-info': {
                    'cluster-name': None,
                }
            }
        }
        result = self.connection.send_request('cluster-identity-get', api_args,
                                              enable_tunneling=False)
        attributes = result.get_child_by_name('attributes')
        cluster_identity = attributes.get_child_by_name(
            'cluster-identity-info')
        return cluster_identity.get_child_content('cluster-name')

    def create_cluster_peer(self, addresses, username=None, password=None,
                            passphrase=None):
        """Creates a cluster peer relationship."""

        api_args = {
            'peer-addresses': [
                {'remote-inet-address': address} for address in addresses
            ],
        }
        if username:
            api_args['user-name'] = username
        if password:
            api_args['password'] = password
        if passphrase:
            api_args['passphrase'] = passphrase

        self.connection.send_request('cluster-peer-create', api_args)

    def get_cluster_peers(self, remote_cluster_name=None):
        """Gets one or more cluster peer relationships."""

        api_args = {}
        if remote_cluster_name:
            api_args['query'] = {
                'cluster-peer-info': {
                    'remote-cluster-name': remote_cluster_name,
                }
            }

        result = self.send_iter_request('cluster-peer-get-iter', api_args)
        if not self._has_records(result):
            return []

        cluster_peers = []

        for cluster_peer_info in result.get_child_by_name(
                'attributes-list').get_children():

            cluster_peer = {
                'active-addresses': [],
                'peer-addresses': []
            }

            active_addresses = cluster_peer_info.get_child_by_name(
                'active-addresses') or netapp_api.NaElement('none')
            for address in active_addresses.get_children():
                cluster_peer['active-addresses'].append(address.get_content())

            peer_addresses = cluster_peer_info.get_child_by_name(
                'peer-addresses') or netapp_api.NaElement('none')
            for address in peer_addresses.get_children():
                cluster_peer['peer-addresses'].append(address.get_content())

            cluster_peer['availability'] = cluster_peer_info.get_child_content(
                'availability')
            cluster_peer['cluster-name'] = cluster_peer_info.get_child_content(
                'cluster-name')
            cluster_peer['cluster-uuid'] = cluster_peer_info.get_child_content(
                'cluster-uuid')
            cluster_peer['remote-cluster-name'] = (
                cluster_peer_info.get_child_content('remote-cluster-name'))
            cluster_peer['serial-number'] = (
                cluster_peer_info.get_child_content('serial-number'))
            cluster_peer['timeout'] = cluster_peer_info.get_child_content(
                'timeout')

            cluster_peers.append(cluster_peer)

        return cluster_peers

    def delete_cluster_peer(self, cluster_name):
        """Deletes a cluster peer relationship."""

        api_args = {'cluster-name': cluster_name}
        self.connection.send_request('cluster-peer-delete', api_args)

    def get_cluster_peer_policy(self):
        """Gets the cluster peering policy configuration."""

        if not self.features.CLUSTER_PEER_POLICY:
            return {}

        result = self.connection.send_request('cluster-peer-policy-get')

        attributes = result.get_child_by_name(
            'attributes') or netapp_api.NaElement('none')
        cluster_peer_policy = attributes.get_child_by_name(
            'cluster-peer-policy') or netapp_api.NaElement('none')

        policy = {
            'is-unauthenticated-access-permitted':
            cluster_peer_policy.get_child_content(
                'is-unauthenticated-access-permitted'),
            'passphrase-minimum-length':
            cluster_peer_policy.get_child_content(
                'passphrase-minimum-length'),
        }

        if policy['is-unauthenticated-access-permitted'] is not None:
            policy['is-unauthenticated-access-permitted'] = (
                strutils.bool_from_string(
                    policy['is-unauthenticated-access-permitted']))
        if policy['passphrase-minimum-length'] is not None:
            policy['passphrase-minimum-length'] = int(
                policy['passphrase-minimum-length'])

        return policy

    def set_cluster_peer_policy(self, is_unauthenticated_access_permitted=None,
                                passphrase_minimum_length=None):
        """Modifies the cluster peering policy configuration."""

        if not self.features.CLUSTER_PEER_POLICY:
            return

        if (is_unauthenticated_access_permitted is None and
                passphrase_minimum_length is None):
            return

        api_args = {}
        if is_unauthenticated_access_permitted is not None:
            api_args['is-unauthenticated-access-permitted'] = (
                'true' if strutils.bool_from_string(
                    is_unauthenticated_access_permitted) else 'false')
        if passphrase_minimum_length is not None:
            api_args['passphrase-minlength'] = six.text_type(
                passphrase_minimum_length)

        self.connection.send_request('cluster-peer-policy-modify', api_args)

    def create_vserver_peer(self, vserver_name, peer_vserver_name,
                            vserver_peer_application=None):
        """Creates a Vserver peer relationship."""

        # default peering application to `snapmirror` if none is specified.
        if not vserver_peer_application:
            vserver_peer_application = ['snapmirror']

        api_args = {
            'vserver': vserver_name,
            'peer-vserver': peer_vserver_name,
            'applications': [
                {'vserver-peer-application': app}
                for app in vserver_peer_application
            ],
        }
        self.connection.send_request('vserver-peer-create', api_args,
                                     enable_tunneling=False)

    def delete_vserver_peer(self, vserver_name, peer_vserver_name):
        """Deletes a Vserver peer relationship."""

        api_args = {'vserver': vserver_name, 'peer-vserver': peer_vserver_name}
        self.connection.send_request('vserver-peer-delete', api_args)

    def accept_vserver_peer(self, vserver_name, peer_vserver_name):
        """Accepts a pending Vserver peer relationship."""

        api_args = {'vserver': vserver_name, 'peer-vserver': peer_vserver_name}
        self.connection.send_request('vserver-peer-accept', api_args)

    def get_vserver_peers(self, vserver_name=None, peer_vserver_name=None):
        """Gets one or more Vserver peer relationships."""

        api_args = None
        if vserver_name or peer_vserver_name:
            api_args = {'query': {'vserver-peer-info': {}}}
            if vserver_name:
                api_args['query']['vserver-peer-info']['vserver'] = (
                    vserver_name)
            if peer_vserver_name:
                api_args['query']['vserver-peer-info']['peer-vserver'] = (
                    peer_vserver_name)

        result = self.send_iter_request('vserver-peer-get-iter', api_args,
                                        enable_tunneling=False)
        if not self._has_records(result):
            return []

        vserver_peers = []

        for vserver_peer_info in result.get_child_by_name(
                'attributes-list').get_children():

            vserver_peer = {
                'vserver': vserver_peer_info.get_child_content('vserver'),
                'peer-vserver':
                vserver_peer_info.get_child_content('peer-vserver'),
                'peer-state':
                vserver_peer_info.get_child_content('peer-state'),
                'peer-cluster':
                vserver_peer_info.get_child_content('peer-cluster'),
                'applications': [app.get_content() for app in
                                 vserver_peer_info.get_child_by_name(
                                     'applications').get_children()],
            }
            vserver_peers.append(vserver_peer)

        return vserver_peers

    def _ensure_snapmirror_v2(self):
        """Verify support for SnapMirror control plane v2."""
        if not self.features.SNAPMIRROR_V2:
            msg = _('SnapMirror features require Data ONTAP 8.2 or later.')
            raise na_utils.NetAppDriverException(msg)

    def create_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume,
                          schedule=None, policy=None,
                          relationship_type='data_protection'):
        """Creates a SnapMirror relationship (cDOT 8.2 or later only)."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
            'relationship-type': relationship_type,
        }

        if schedule:
            api_args['schedule'] = schedule
        if policy:
            api_args['policy'] = policy

        try:
            self.connection.send_request('snapmirror-create', api_args)
        except netapp_api.NaApiError as e:
            if e.code != netapp_api.ERELATION_EXISTS:
                raise

    def initialize_snapmirror(self, source_vserver, source_volume,
                              destination_vserver, destination_volume,
                              source_snapshot=None, transfer_priority=None):
        """Initializes a SnapMirror relationship (cDOT 8.2 or later only)."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        if source_snapshot:
            api_args['source-snapshot'] = source_snapshot
        if transfer_priority:
            api_args['transfer-priority'] = transfer_priority

        result = self.connection.send_request('snapmirror-initialize',
                                              api_args)

        result_info = {}
        result_info['operation-id'] = result.get_child_content(
            'result-operation-id')
        result_info['status'] = result.get_child_content('result-status')
        result_info['jobid'] = result.get_child_content('result-jobid')
        result_info['error-code'] = result.get_child_content(
            'result-error-code')
        result_info['error-message'] = result.get_child_content(
            'result-error-message')

        return result_info

    def release_snapmirror(self, source_vserver, source_volume,
                           destination_vserver, destination_volume,
                           relationship_info_only=False):
        """Removes a SnapMirror relationship on the source endpoint."""
        self._ensure_snapmirror_v2()

        api_args = {
            'query': {
                'snapmirror-destination-info': {
                    'source-volume': source_volume,
                    'source-vserver': source_vserver,
                    'destination-volume': destination_volume,
                    'destination-vserver': destination_vserver,
                    'relationship-info-only': ('true' if relationship_info_only
                                               else 'false'),
                }
            }
        }
        self.connection.send_request('snapmirror-release-iter', api_args)

    def quiesce_snapmirror(self, source_vserver, source_volume,
                           destination_vserver, destination_volume):
        """Disables future transfers to a SnapMirror destination."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        self.connection.send_request('snapmirror-quiesce', api_args)

    def abort_snapmirror(self, source_vserver, source_volume,
                         destination_vserver, destination_volume,
                         clear_checkpoint=False):
        """Stops ongoing transfers for a SnapMirror relationship."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
            'clear-checkpoint': 'true' if clear_checkpoint else 'false',
        }
        try:
            self.connection.send_request('snapmirror-abort', api_args)
        except netapp_api.NaApiError as e:
            if e.code != netapp_api.ENOTRANSFER_IN_PROGRESS:
                raise

    def break_snapmirror(self, source_vserver, source_volume,
                         destination_vserver, destination_volume):
        """Breaks a data protection SnapMirror relationship."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        self.connection.send_request('snapmirror-break', api_args)

    def modify_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume,
                          schedule=None, policy=None, tries=None,
                          max_transfer_rate=None):
        """Modifies a SnapMirror relationship."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        if schedule:
            api_args['schedule'] = schedule
        if policy:
            api_args['policy'] = policy
        if tries is not None:
            api_args['tries'] = tries
        if max_transfer_rate is not None:
            api_args['max-transfer-rate'] = max_transfer_rate

        self.connection.send_request('snapmirror-modify', api_args)

    def delete_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Destroys an SnapMirror relationship."""
        self._ensure_snapmirror_v2()

        api_args = {
            'query': {
                'snapmirror-info': {
                    'source-volume': source_volume,
                    'source-vserver': source_vserver,
                    'destination-volume': destination_volume,
                    'destination-vserver': destination_vserver,
                }
            }
        }
        self.connection.send_request('snapmirror-destroy-iter', api_args)

    def update_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Schedules a SnapMirror update."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        try:
            self.connection.send_request('snapmirror-update', api_args)
        except netapp_api.NaApiError as e:
            if (e.code != netapp_api.ETRANSFER_IN_PROGRESS and
                    e.code != netapp_api.EANOTHER_OP_ACTIVE):
                raise

    def resume_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Resume a SnapMirror relationship if it is quiesced."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        try:
            self.connection.send_request('snapmirror-resume', api_args)
        except netapp_api.NaApiError as e:
            if e.code != netapp_api.ERELATION_NOT_QUIESCED:
                raise

    def resync_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Resync a SnapMirror relationship."""
        self._ensure_snapmirror_v2()

        api_args = {
            'source-volume': source_volume,
            'source-vserver': source_vserver,
            'destination-volume': destination_volume,
            'destination-vserver': destination_vserver,
        }
        self.connection.send_request('snapmirror-resync', api_args)

    def _get_snapmirrors(self, source_vserver=None, source_volume=None,
                         destination_vserver=None, destination_volume=None,
                         desired_attributes=None):

        query = None
        if (source_vserver or source_volume or destination_vserver or
                destination_volume):
            query = {'snapmirror-info': {}}
            if source_volume:
                query['snapmirror-info']['source-volume'] = source_volume
            if destination_volume:
                query['snapmirror-info']['destination-volume'] = (
                    destination_volume)
            if source_vserver:
                query['snapmirror-info']['source-vserver'] = source_vserver
            if destination_vserver:
                query['snapmirror-info']['destination-vserver'] = (
                    destination_vserver)

        api_args = {}
        if query:
            api_args['query'] = query
        if desired_attributes:
            api_args['desired-attributes'] = desired_attributes

        result = self.send_iter_request('snapmirror-get-iter', api_args)
        if not self._has_records(result):
            return []
        else:
            return result.get_child_by_name('attributes-list').get_children()

    def get_snapmirrors(self, source_vserver, source_volume,
                        destination_vserver, destination_volume,
                        desired_attributes=None):
        """Gets one or more SnapMirror relationships.

        Either the source or destination info may be omitted.
        Desired attributes should be a flat list of attribute names.
        """
        self._ensure_snapmirror_v2()

        if desired_attributes is not None:
            desired_attributes = {
                'snapmirror-info': {attr: None for attr in desired_attributes},
            }

        result = self._get_snapmirrors(
            source_vserver=source_vserver,
            source_volume=source_volume,
            destination_vserver=destination_vserver,
            destination_volume=destination_volume,
            desired_attributes=desired_attributes)

        snapmirrors = []

        for snapmirror_info in result:
            snapmirror = {}
            for child in snapmirror_info.get_children():
                name = self._strip_xml_namespace(child.get_name())
                snapmirror[name] = child.get_content()
            snapmirrors.append(snapmirror)

        return snapmirrors

    def get_provisioning_options_from_flexvol(self, flexvol_name):
        """Get a dict of provisioning options matching existing flexvol."""

        flexvol_info = self.get_flexvol(flexvol_name=flexvol_name)
        dedupe_info = self.get_flexvol_dedupe_info(flexvol_name)

        provisioning_opts = {
            'aggregate': flexvol_info['aggregate'],
            # space-guarantee can be 'none', 'file', 'volume'
            'space_guarantee_type': flexvol_info.get('space-guarantee'),
            'snapshot_policy': flexvol_info['snapshot-policy'],
            'language': flexvol_info['language'],
            'dedupe_enabled': dedupe_info['dedupe'],
            'compression_enabled': dedupe_info['compression'],
            'snapshot_reserve': flexvol_info['percentage-snapshot-reserve'],
            'volume_type': flexvol_info['type'],
            'size': int(math.ceil(float(flexvol_info['size']) / units.Gi)),
            'is_flexgroup': flexvol_info['style-extended'] == 'flexgroup',
        }

        return provisioning_opts
