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
import time

from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _, _LW
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base


LOG = logging.getLogger(__name__)


class Client(client_base.Client):

    def __init__(self, volume_list=None, **kwargs):
        super(Client, self).__init__(**kwargs)
        vfiler = kwargs.get('vfiler', None)
        self.connection.set_vfiler(vfiler)

        (major, minor) = self.get_ontapi_version(cached=False)
        self.connection.set_api_version(major, minor)

        self.volume_list = volume_list

    def _invoke_vfiler_api(self, na_element, vfiler):
        server = copy.copy(self.connection)
        server.set_vfiler(vfiler)
        result = server.invoke_successfully(na_element, True)
        return result

    def _invoke_7mode_iterator_getter(self, start_api_name, next_api_name,
                                      end_api_name, record_container_tag_name,
                                      maximum=100):
        """Invoke a 7-mode iterator-style getter API."""
        data = []

        start_api = netapp_api.NaElement(start_api_name)
        start_result = self.connection.invoke_successfully(start_api)
        tag = start_result.get_child_content('tag')
        if not tag:
            return data

        try:
            while True:
                next_api = netapp_api.NaElement(next_api_name)
                next_api.add_new_child('tag', tag)
                next_api.add_new_child('maximum', six.text_type(maximum))
                next_result = self.connection.invoke_successfully(next_api)
                records = next_result.get_child_content('records') or 0
                if int(records) == 0:
                    break

                record_container = next_result.get_child_by_name(
                    record_container_tag_name) or netapp_api.NaElement('none')

                data.extend(record_container.get_children())
        finally:
            end_api = netapp_api.NaElement(end_api_name)
            end_api.add_new_child('tag', tag)
            self.connection.invoke_successfully(end_api)

        return data

    def get_iscsi_target_details(self):
        """Gets the iSCSI target portal details."""
        iscsi_if_iter = netapp_api.NaElement('iscsi-portal-list-info')
        result = self.connection.invoke_successfully(iscsi_if_iter, True)
        tgt_list = []
        portal_list_entries = result.get_child_by_name(
            'iscsi-portal-list-entries')
        if portal_list_entries:
            portal_list = portal_list_entries.get_children()
            for iscsi_if in portal_list:
                d = dict()
                d['address'] = iscsi_if.get_child_content('ip-address')
                d['port'] = iscsi_if.get_child_content('ip-port')
                d['tpgroup-tag'] = iscsi_if.get_child_content('tpgroup-tag')
                tgt_list.append(d)
        return tgt_list

    def get_fc_target_wwpns(self):
        """Gets the FC target details."""
        wwpns = []
        port_name_list_api = netapp_api.NaElement('fcp-port-name-list-info')
        result = self.connection.invoke_successfully(port_name_list_api)
        port_names = result.get_child_by_name('fcp-port-names')
        if port_names:
            for port_name_info in port_names.get_children():
                wwpn = port_name_info.get_child_content('port-name').lower()
                wwpns.append(wwpn)
        return wwpns

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        iscsi_service_iter = netapp_api.NaElement('iscsi-node-get-name')
        result = self.connection.invoke_successfully(iscsi_service_iter, True)
        return result.get_child_content('node-name')

    def get_lun_list(self):
        """Gets the list of LUNs on filer."""
        lun_list = []
        if self.volume_list:
            for vol in self.volume_list:
                try:
                    luns = self._get_vol_luns(vol)
                    if luns:
                        lun_list.extend(luns)
                except netapp_api.NaApiError:
                    LOG.warning(_LW("Error finding LUNs for volume %s."
                                    " Verify volume exists.") % vol)
        else:
            luns = self._get_vol_luns(None)
            lun_list.extend(luns)
        return lun_list

    def _get_vol_luns(self, vol_name):
        """Gets the LUNs for a volume."""
        api = netapp_api.NaElement('lun-list-info')
        if vol_name:
            api.add_new_child('volume-name', vol_name)
        result = self.connection.invoke_successfully(api, True)
        luns = result.get_child_by_name('luns')
        return luns.get_children()

    def get_igroup_by_initiators(self, initiator_list):
        """Get igroups exactly matching a set of initiators."""
        igroup_list = []
        if not initiator_list:
            return igroup_list

        initiator_set = set(initiator_list)

        igroup_list_info = netapp_api.NaElement('igroup-list-info')
        result = self.connection.invoke_successfully(igroup_list_info, True)

        initiator_groups = result.get_child_by_name(
            'initiator-groups') or netapp_api.NaElement('none')
        for initiator_group_info in initiator_groups.get_children():

            initiator_set_for_igroup = set()
            initiators = initiator_group_info.get_child_by_name(
                'initiators') or netapp_api.NaElement('none')
            for initiator_info in initiators.get_children():
                initiator_set_for_igroup.add(
                    initiator_info.get_child_content('initiator-name'))

            if initiator_set == initiator_set_for_igroup:
                igroup = {'initiator-group-os-type':
                          initiator_group_info.get_child_content(
                              'initiator-group-os-type'),
                          'initiator-group-type':
                          initiator_group_info.get_child_content(
                              'initiator-group-type'),
                          'initiator-group-name':
                          initiator_group_info.get_child_content(
                              'initiator-group-name')}
                igroup_list.append(igroup)

        return igroup_list

    def clone_lun(self, path, clone_path, name, new_name,
                  space_reserved='true', src_block=0,
                  dest_block=0, block_count=0):
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
            clone_start = netapp_api.NaElement.create_node_with_children(
                'clone-start', **{'source-path': path,
                                  'destination-path': clone_path,
                                  'no-snap': 'true'})
            if block_count > 0:
                block_ranges = netapp_api.NaElement("block-ranges")
                # zAPI can only handle 2^24 block ranges
                bc_limit = 2 ** 24  # 8GB
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
                clone_start.add_child_elem(block_ranges)
            result = self.connection.invoke_successfully(clone_start, True)
            clone_id_el = result.get_child_by_name('clone-id')
            cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
            vol_uuid = cl_id_info.get_child_content('volume-uuid')
            clone_id = cl_id_info.get_child_content('clone-op-id')
            if vol_uuid:
                self._check_clone_status(clone_id, vol_uuid, name, new_name)

    def _check_clone_status(self, clone_id, vol_uuid, name, new_name):
        """Checks for the job till completed."""
        clone_status = netapp_api.NaElement('clone-list-status')
        cl_id = netapp_api.NaElement('clone-id')
        clone_status.add_child_elem(cl_id)
        cl_id.add_node_with_children('clone-id-info',
                                     **{'clone-op-id': clone_id,
                                        'volume-uuid': vol_uuid})
        running = True
        clone_ops_info = None
        while running:
            result = self.connection.invoke_successfully(clone_status, True)
            status = result.get_child_by_name('status')
            ops_info = status.get_children()
            if ops_info:
                for info in ops_info:
                    if info.get_child_content('clone-state') == 'running':
                        time.sleep(1)
                        break
                    else:
                        running = False
                        clone_ops_info = info
                        break
        else:
            if clone_ops_info:
                fmt = {'name': name, 'new_name': new_name}
                if clone_ops_info.get_child_content('clone-state')\
                        == 'completed':
                    LOG.debug("Clone operation with src %(name)s"
                              " and dest %(new_name)s completed" % fmt)
                else:
                    LOG.debug("Clone operation with src %(name)s"
                              " and dest %(new_name)s failed" % fmt)
                    raise netapp_api.NaApiError(
                        clone_ops_info.get_child_content('error'),
                        clone_ops_info.get_child_content('reason'))

    def get_lun_by_args(self, **args):
        """Retrieves LUNs with specified args."""
        lun_info = netapp_api.NaElement.create_node_with_children(
            'lun-list-info', **args)
        result = self.connection.invoke_successfully(lun_info, True)
        luns = result.get_child_by_name('luns')
        return luns.get_children()

    def get_filer_volumes(self, volume=None):
        """Returns list of filer volumes in API format."""
        vol_request = netapp_api.NaElement('volume-list-info')
        res = self.connection.invoke_successfully(vol_request, True)
        volumes = res.get_child_by_name('volumes')
        if volumes:
            return volumes.get_children()
        return []

    def get_lun_map(self, path):
        lun_map_list = netapp_api.NaElement.create_node_with_children(
            'lun-map-list-info',
            **{'path': path})
        return self.connection.invoke_successfully(lun_map_list, True)

    def set_space_reserve(self, path, enable):
        """Sets the space reserve info."""
        space_res = netapp_api.NaElement.create_node_with_children(
            'lun-set-space-reservation-info',
            **{'path': path, 'enable': enable})
        self.connection.invoke_successfully(space_res, True)

    def get_actual_path_for_export(self, export_path):
        """Gets the actual path on the filer for export path."""
        storage_path = netapp_api.NaElement.create_node_with_children(
            'nfs-exportfs-storage-path', **{'pathname': export_path})
        result = self.connection.invoke_successfully(storage_path,
                                                     enable_tunneling=True)
        if result.get_child_content('actual-pathname'):
            return result.get_child_content('actual-pathname')
        raise exception.NotFound(_('No storage path found for export path %s')
                                 % (export_path))

    def clone_file(self, src_path, dest_path):
        msg_fmt = {'src_path': src_path, 'dest_path': dest_path}
        LOG.debug("""Cloning with src %(src_path)s, dest %(dest_path)s"""
                  % msg_fmt)
        clone_start = netapp_api.NaElement.create_node_with_children(
            'clone-start',
            **{'source-path': src_path,
               'destination-path': dest_path,
               'no-snap': 'true'})
        result = self.connection.invoke_successfully(clone_start,
                                                     enable_tunneling=True)
        clone_id_el = result.get_child_by_name('clone-id')
        cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
        vol_uuid = cl_id_info.get_child_content('volume-uuid')
        clone_id = cl_id_info.get_child_content('clone-op-id')

        if vol_uuid:
            try:
                self._wait_for_clone_finish(clone_id, vol_uuid)
            except netapp_api.NaApiError as e:
                if e.code != 'UnknownCloneId':
                    self._clear_clone(clone_id)
                raise e

    def _wait_for_clone_finish(self, clone_op_id, vol_uuid):
        """Waits till a clone operation is complete or errored out."""
        clone_ls_st = netapp_api.NaElement('clone-list-status')
        clone_id = netapp_api.NaElement('clone-id')
        clone_ls_st.add_child_elem(clone_id)
        clone_id.add_node_with_children('clone-id-info',
                                        **{'clone-op-id': clone_op_id,
                                           'volume-uuid': vol_uuid})
        task_running = True
        while task_running:
            result = self.connection.invoke_successfully(clone_ls_st,
                                                         enable_tunneling=True)
            status = result.get_child_by_name('status')
            ops_info = status.get_children()
            if ops_info:
                state = ops_info[0].get_child_content('clone-state')
                if state == 'completed':
                    task_running = False
                elif state == 'failed':
                    code = ops_info[0].get_child_content('error')
                    reason = ops_info[0].get_child_content('reason')
                    raise netapp_api.NaApiError(code, reason)
                else:
                    time.sleep(1)
            else:
                raise netapp_api.NaApiError(
                    'UnknownCloneId',
                    'No clone operation for clone id %s found on the filer'
                    % (clone_id))

    def _clear_clone(self, clone_id):
        """Clear the clone information.

        Invoke this in case of failed clone.
        """

        clone_clear = netapp_api.NaElement.create_node_with_children(
            'clone-clear',
            **{'clone-id': clone_id})
        retry = 3
        while retry:
            try:
                self.connection.invoke_successfully(clone_clear,
                                                    enable_tunneling=True)
                break
            except netapp_api.NaApiError:
                # Filer might be rebooting
                time.sleep(5)
            retry = retry - 1

    def get_file_usage(self, path):
        """Gets the file unique bytes."""
        LOG.debug('Getting file usage for %s', path)
        file_use = netapp_api.NaElement.create_node_with_children(
            'file-usage-get', **{'path': path})
        res = self.connection.invoke_successfully(file_use)
        bytes = res.get_child_content('unique-bytes')
        LOG.debug('file-usage for path %(path)s is %(bytes)s'
                  % {'path': path, 'bytes': bytes})
        return bytes

    def get_ifconfig(self):
        ifconfig = netapp_api.NaElement('net-ifconfig-get')
        return self.connection.invoke_successfully(ifconfig)

    def get_flexvol_capacity(self, flexvol_path):
        """Gets total capacity and free capacity, in bytes, of the flexvol."""

        api_args = {'volume': flexvol_path, 'verbose': 'false'}

        result = self.send_request('volume-list-info', api_args)

        flexvol_info_list = result.get_child_by_name('volumes')
        flexvol_info = flexvol_info_list.get_children()[0]

        total_bytes = float(
            flexvol_info.get_child_content('size-total'))
        available_bytes = float(
            flexvol_info.get_child_content('size-available'))

        return total_bytes, available_bytes
