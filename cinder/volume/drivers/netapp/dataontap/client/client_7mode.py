# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base

from oslo_utils import strutils

LOG = logging.getLogger(__name__)


@six.add_metaclass(utils.TraceWrapperMetaclass)
class Client(client_base.Client):

    def __init__(self, volume_list=None, **kwargs):
        super(Client, self).__init__(**kwargs)
        vfiler = kwargs.get('vfiler', None)
        self.connection.set_vfiler(vfiler)

        (major, minor) = self.get_ontapi_version(cached=False)
        self.connection.set_api_version(major, minor)

        self.volume_list = volume_list
        self._init_features()

    def _init_features(self):
        super(Client, self)._init_features()

        ontapi_version = self.get_ontapi_version()   # major, minor

        ontapi_1_20 = ontapi_version >= (1, 20)
        self.features.add_feature('SYSTEM_METRICS', supported=ontapi_1_20)

    def send_ems_log_message(self, message_dict):
        """Sends a message to the Data ONTAP EMS log."""

        # NOTE(cknight): Cannot use deepcopy on the connection context
        node_client = copy.copy(self)
        node_client.connection = copy.copy(self.connection)
        node_client.connection.set_timeout(25)

        try:
            node_client.connection.set_vfiler(None)
            node_client.send_request('ems-autosupport-log', message_dict)
            LOG.debug('EMS executed successfully.')
        except netapp_api.NaApiError as e:
            LOG.warning('Failed to invoke EMS. %s', e)

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

    def check_iscsi_initiator_exists(self, iqn):
        """Returns True if initiator exists."""
        initiator_exists = True
        try:
            auth_list = netapp_api.NaElement('iscsi-initiator-auth-list-info')
            auth_list.add_new_child('initiator', iqn)
            self.connection.invoke_successfully(auth_list, True)
        except netapp_api.NaApiError:
            initiator_exists = False

        return initiator_exists

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

    def set_iscsi_chap_authentication(self, iqn, username, password):
        """Provides NetApp host's CHAP credentials to the backend."""

        command = ("iscsi security add -i %(iqn)s -s CHAP "
                   "-p %(password)s -n %(username)s") % {
            'iqn': iqn,
            'password': password,
            'username': username,
        }

        LOG.debug('Updating CHAP authentication for %(iqn)s.', {'iqn': iqn})

        try:
            ssh_pool = self.ssh_client.ssh_pool
            with ssh_pool.item() as ssh:
                self.ssh_client.execute_command(ssh, command)
        except Exception as e:
            msg = _('Failed to set CHAP authentication for target IQN '
                    '%(iqn)s. Details: %(ex)s') % {
                'iqn': iqn,
                'ex': e,
            }
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

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
                    LOG.warning("Error finding LUNs for volume %s."
                                " Verify volume exists.", vol)
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
                  dest_block=0, block_count=0, source_snapshot=None):
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

            zapi_args = {
                'source-path': path,
                'destination-path': clone_path,
                'no-snap': 'true',
            }
            if source_snapshot:
                zapi_args['snapshot-name'] = source_snapshot
            clone_start = netapp_api.NaElement.create_node_with_children(
                'clone-start', **zapi_args)
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
                              " and dest %(new_name)s completed", fmt)
                else:
                    LOG.debug("Clone operation with src %(name)s"
                              " and dest %(new_name)s failed", fmt)
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

    def clone_file(self, src_path, dest_path, source_snapshot=None):
        LOG.debug("Cloning with src %(src_path)s, dest %(dest_path)s",
                  {'src_path': src_path, 'dest_path': dest_path})
        zapi_args = {
            'source-path': src_path,
            'destination-path': dest_path,
            'no-snap': 'true',
        }
        if source_snapshot:
            zapi_args['snapshot-name'] = source_snapshot

        clone_start = netapp_api.NaElement.create_node_with_children(
            'clone-start', **zapi_args)
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
                raise

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
        LOG.debug('file-usage for path %(path)s is %(bytes)s',
                  {'path': path, 'bytes': bytes})
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

        size_total = float(flexvol_info.get_child_content('size-total'))
        size_available = float(
            flexvol_info.get_child_content('size-available'))

        return {
            'size-total': size_total,
            'size-available': size_available,
        }

    def get_performance_instance_names(self, object_name):
        """Get names of performance instances for a node."""

        api_args = {'objectname': object_name}

        result = self.send_request('perf-object-instance-list-info',
                                   api_args,
                                   enable_tunneling=False)

        instance_names = []

        instances = result.get_child_by_name(
            'instances') or netapp_api.NaElement('None')

        for instance_info in instances.get_children():
            instance_names.append(instance_info.get_child_content('name'))

        return instance_names

    def get_performance_counters(self, object_name, instance_names,
                                 counter_names):
        """Gets or or more 7-mode Data ONTAP performance counters."""

        api_args = {
            'objectname': object_name,
            'instances': [
                {'instance': instance} for instance in instance_names
            ],
            'counters': [
                {'counter': counter} for counter in counter_names
            ],
        }

        result = self.send_request('perf-object-get-instances',
                                   api_args,
                                   enable_tunneling=False)

        counter_data = []

        timestamp = result.get_child_content('timestamp')

        instances = result.get_child_by_name(
            'instances') or netapp_api.NaElement('None')
        for instance in instances.get_children():

            instance_name = instance.get_child_content('name')

            counters = instance.get_child_by_name(
                'counters') or netapp_api.NaElement('None')
            for counter in counters.get_children():

                counter_name = counter.get_child_content('name')
                counter_value = counter.get_child_content('value')

                counter_data.append({
                    'instance-name': instance_name,
                    'timestamp': timestamp,
                    counter_name: counter_value,
                })

        return counter_data

    def get_system_name(self):
        """Get the name of the 7-mode Data ONTAP controller."""

        result = self.send_request('system-get-info',
                                   {},
                                   enable_tunneling=False)

        system_info = result.get_child_by_name('system-info')
        system_name = system_info.get_child_content('system-name')
        return system_name

    def get_snapshot(self, volume_name, snapshot_name):
        """Gets a single snapshot."""
        snapshot_list_info = netapp_api.NaElement('snapshot-list-info')
        snapshot_list_info.add_new_child('volume', volume_name)
        result = self.connection.invoke_successfully(snapshot_list_info,
                                                     enable_tunneling=True)

        snapshots = result.get_child_by_name('snapshots')
        if not snapshots:
            msg = _('No snapshots could be found on volume %s.')
            raise exception.VolumeBackendAPIException(data=msg % volume_name)
        snapshot_list = snapshots.get_children()
        snapshot = None
        for s in snapshot_list:
            if (snapshot_name == s.get_child_content('name')) and (snapshot
                                                                   is None):
                snapshot = {
                    'name': s.get_child_content('name'),
                    'volume': s.get_child_content('volume'),
                    'busy': strutils.bool_from_string(
                        s.get_child_content('busy')),
                }
                snapshot_owners_list = s.get_child_by_name(
                    'snapshot-owners-list') or netapp_api.NaElement('none')
                snapshot_owners = set([snapshot_owner.get_child_content(
                    'owner') for snapshot_owner in
                    snapshot_owners_list.get_children()])
                snapshot['owners'] = snapshot_owners
            elif (snapshot_name == s.get_child_content('name')) and (
                    snapshot is not None):
                msg = _('Could not find unique snapshot %(snap)s on '
                        'volume %(vol)s.')
                msg_args = {'snap': snapshot_name, 'vol': volume_name}
                raise exception.VolumeBackendAPIException(data=msg % msg_args)
        if not snapshot:
            raise exception.SnapshotNotFound(snapshot_id=snapshot_name)

        return snapshot

    def get_snapshots_marked_for_deletion(self, volume_list=None):
        """Get a list of snapshots marked for deletion."""
        snapshots = []

        for volume_name in volume_list:
            api_args = {
                'target-name': volume_name,
                'target-type': 'volume',
                'terse': 'true',
            }
            result = self.send_request('snapshot-list-info', api_args)
            snapshots.extend(
                self._parse_snapshot_list_info_result(result, volume_name))

        return snapshots

    def _parse_snapshot_list_info_result(self, result, volume_name):
        snapshots = []
        snapshots_elem = result.get_child_by_name(
            'snapshots') or netapp_api.NaElement('none')
        snapshot_info_list = snapshots_elem.get_children()
        for snapshot_info in snapshot_info_list:
            snapshot_name = snapshot_info.get_child_content('name')
            snapshot_busy = strutils.bool_from_string(
                snapshot_info.get_child_content('busy'))
            snapshot_id = snapshot_info.get_child_content(
                'snapshot-instance-uuid')
            if (not snapshot_busy and
                    snapshot_name.startswith(client_base.DELETED_PREFIX)):
                snapshots.append({
                    'name': snapshot_name,
                    'instance_id': snapshot_id,
                    'volume_name': volume_name,
                })

        return snapshots
