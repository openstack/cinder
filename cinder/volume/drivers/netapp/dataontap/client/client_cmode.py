# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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

import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


class Client(client_base.Client):

    def __init__(self, **kwargs):
        super(Client, self).__init__(**kwargs)
        self.vserver = kwargs.get('vserver', None)
        self.connection.set_vserver(self.vserver)

        # Default values to run first api
        self.connection.set_api_version(1, 15)
        (major, minor) = self.get_ontapi_version(cached=False)
        self.connection.set_api_version(major, minor)

    def _invoke_vserver_api(self, na_element, vserver):
        server = copy.copy(self.connection)
        server.set_vserver(vserver)
        result = server.invoke_successfully(na_element, True)
        return result

    def set_vserver(self, vserver):
        self.connection.set_vserver(vserver)

    def get_target_details(self):
        """Gets the target portal details."""
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

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        iscsi_service_iter = netapp_api.NaElement('iscsi-service-get-iter')
        result = self.connection.invoke_successfully(iscsi_service_iter, True)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            iscsi_service = attr_list.get_child_by_name('iscsi-service-info')
            return iscsi_service.get_child_content('node-name')
        LOG.debug('No iSCSI service found for vserver %s' % (self.vserver))
        return None

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
            result = self.connection.invoke_successfully(api)
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

    def get_igroup_by_initiator(self, initiator):
        """Get igroups by initiator."""
        tag = None
        igroup_list = []
        while True:
            igroup_iter = netapp_api.NaElement('igroup-get-iter')
            igroup_iter.add_new_child('max-records', '100')
            if tag:
                igroup_iter.add_new_child('tag', tag, True)
            query = netapp_api.NaElement('query')
            igroup_iter.add_child_elem(query)
            igroup_info = netapp_api.NaElement('initiator-group-info')
            query.add_child_elem(igroup_info)
            igroup_info.add_new_child('vserver', self.vserver)
            initiators = netapp_api.NaElement('initiators')
            igroup_info.add_child_elem(initiators)
            initiators.add_node_with_children('initiator-info',
                                              **{'initiator-name': initiator})
            des_attrs = netapp_api.NaElement('desired-attributes')
            des_ig_info = netapp_api.NaElement('initiator-group-info')
            des_attrs.add_child_elem(des_ig_info)
            des_ig_info.add_node_with_children('initiators',
                                               **{'initiator-info': None})
            des_ig_info.add_new_child('vserver', None)
            des_ig_info.add_new_child('initiator-group-name', None)
            des_ig_info.add_new_child('initiator-group-type', None)
            des_ig_info.add_new_child('initiator-group-os-type', None)
            igroup_iter.add_child_elem(des_attrs)
            result = self.connection.invoke_successfully(igroup_iter, False)
            tag = result.get_child_content('next-tag')
            if result.get_child_content('num-records') and\
                    int(result.get_child_content('num-records')) > 0:
                attr_list = result.get_child_by_name('attributes-list')
                igroups = attr_list.get_children()
                for igroup in igroups:
                    ig = dict()
                    ig['initiator-group-os-type'] = igroup.get_child_content(
                        'initiator-group-os-type')
                    ig['initiator-group-type'] = igroup.get_child_content(
                        'initiator-group-type')
                    ig['initiator-group-name'] = igroup.get_child_content(
                        'initiator-group-name')
                    igroup_list.append(ig)
            if tag is None:
                break
        return igroup_list

    def clone_lun(self, volume, name, new_name, space_reserved='true',
                  src_block=0, dest_block=0, block_count=0):
        # zAPI can only handle 2^24 blocks per range
        bc_limit = 2 ** 24  # 8GB
        # zAPI can only handle 32 block ranges per call
        br_limit = 32
        z_limit = br_limit * bc_limit  # 256 GB
        z_calls = int(math.ceil(block_count / float(z_limit)))
        zbc = block_count
        if z_calls == 0:
            z_calls = 1
        for _call in range(0, z_calls):
            if zbc > z_limit:
                block_count = z_limit
                zbc -= z_limit
            else:
                block_count = zbc
            clone_create = netapp_api.NaElement.create_node_with_children(
                'clone-create',
                **{'volume': volume, 'source-path': name,
                   'destination-path': new_name,
                   'space-reserve': space_reserved})
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
                               six.text_type(block_count)})
                    block_ranges.add_child_elem(block_range)
                    src_block += int(block_count)
                    dest_block += int(block_count)
                clone_create.add_child_elem(block_ranges)
            self.connection.invoke_successfully(clone_create, True)

    def get_lun_by_args(self, **args):
        """Retrieves LUN with specified args."""
        lun_iter = netapp_api.NaElement('lun-get-iter')
        lun_iter.add_new_child('max-records', '100')
        query = netapp_api.NaElement('query')
        lun_iter.add_child_elem(query)
        query.add_node_with_children('lun-info', **args)
        luns = self.connection.invoke_successfully(lun_iter)
        attr_list = luns.get_child_by_name('attributes-list')
        return attr_list.get_children()

    def file_assign_qos(self, flex_vol, qos_policy_group, file_path):
        """Retrieves LUN with specified args."""
        file_assign_qos = netapp_api.NaElement.create_node_with_children(
            'file-assign-qos',
            **{'volume': flex_vol,
               'qos-policy-group-name': qos_policy_group,
               'file': file_path,
               'vserver': self.vserver})
        self.connection.invoke_successfully(file_assign_qos, True)

    def get_if_info_by_ip(self, ip):
        """Gets the network interface info by ip."""
        net_if_iter = netapp_api.NaElement('net-interface-get-iter')
        net_if_iter.add_new_child('max-records', '10')
        query = netapp_api.NaElement('query')
        net_if_iter.add_child_elem(query)
        query.add_node_with_children(
            'net-interface-info',
            **{'address': na_utils.resolve_hostname(ip)})
        result = self.connection.invoke_successfully(net_if_iter, True)
        num_records = result.get_child_content('num-records')
        if num_records and int(num_records) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            return attr_list.get_children()
        raise exception.NotFound(
            _('No interface found on cluster for ip %s') % (ip))

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
            attr_list = result.get_child_by_name('attributes-list')
            vols = attr_list.get_children()
            vol_id = vols[0].get_child_by_name('volume-id-attributes')
            return vol_id.get_child_content('name')
        msg_fmt = {'vserver': vserver, 'junction': junction}
        raise exception.NotFound(_("No volume on cluster with vserver "
                                   "%(vserver)s and junction path "
                                   "%(junction)s ") % msg_fmt)

    def clone_file(self, flex_vol, src_path, dest_path, vserver,
                   dest_exists=False):
        """Clones file on vserver."""
        msg = ("Cloning with params volume %(volume)s, src %(src_path)s,"
               "dest %(dest_path)s, vserver %(vserver)s")
        msg_fmt = {'volume': flex_vol, 'src_path': src_path,
                   'dest_path': dest_path, 'vserver': vserver}
        LOG.debug(msg % msg_fmt)
        clone_create = netapp_api.NaElement.create_node_with_children(
            'clone-create',
            **{'volume': flex_vol, 'source-path': src_path,
               'destination-path': dest_path})
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
        LOG.debug('file-usage for path %(path)s is %(bytes)s'
                  % {'path': path, 'bytes': unique_bytes})
        return unique_bytes

    def get_vserver_ips(self, vserver):
        """Get ips for the vserver."""
        result = netapp_api.invoke_api(
            self.connection, api_name='net-interface-get-iter',
            is_iter=True, tunnel=vserver)
        if_list = []
        for res in result:
            records = res.get_child_content('num-records')
            if records > 0:
                attr_list = res['attributes-list']
                ifs = attr_list.get_children()
                if_list.extend(ifs)
        return if_list

    def check_apis_on_cluster(self, api_list=None):
        """Checks API availability and permissions on cluster.

        Checks API availability and permissions for executing user.
        Returns a list of failed apis.
        """
        api_list = api_list or []
        failed_apis = []
        if api_list:
            api_version = self.connection.get_api_version()
            if api_version:
                major, minor = api_version
                if major == 1 and minor < 20:
                    for api_name in api_list:
                        na_el = netapp_api.NaElement(api_name)
                        try:
                            self.connection.invoke_successfully(na_el)
                        except Exception as e:
                            if isinstance(e, netapp_api.NaApiError):
                                if (e.code == netapp_api.NaErrors
                                        ['API_NOT_FOUND'].code or
                                    e.code == netapp_api.NaErrors
                                        ['INSUFFICIENT_PRIVS'].code):
                                    failed_apis.append(api_name)
                elif major == 1 and minor >= 20:
                    failed_apis = copy.copy(api_list)
                    result = netapp_api.invoke_api(
                        self.connection,
                        api_name='system-user-capability-get-iter',
                        api_family='cm',
                        additional_elems=None,
                        is_iter=True)
                    for res in result:
                        attr_list = res.get_child_by_name('attributes-list')
                        if attr_list:
                            capabilities = attr_list.get_children()
                            for capability in capabilities:
                                op_list = capability.get_child_by_name(
                                    'operation-list')
                                if op_list:
                                    ops = op_list.get_children()
                                    for op in ops:
                                        apis = op.get_child_content(
                                            'api-name')
                                        if apis:
                                            api_list = apis.split(',')
                                            for api_name in api_list:
                                                if (api_name and
                                                        api_name.strip()
                                                        in failed_apis):
                                                    failed_apis.remove(
                                                        api_name)
                                        else:
                                            continue
                else:
                    msg = _("Unsupported Clustered Data ONTAP version.")
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _("Data ONTAP API version could not be determined.")
                raise exception.VolumeBackendAPIException(data=msg)
        return failed_apis
