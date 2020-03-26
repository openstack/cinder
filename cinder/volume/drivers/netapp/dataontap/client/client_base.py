# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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

import sys

from oslo_log import log as logging
from oslo_utils import excutils

import six

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)

DELETED_PREFIX = 'deleted_cinder_'
MAX_SIZE_FOR_A_LUN = '17555678822400'


@six.add_metaclass(utils.TraceWrapperMetaclass)
class Client(object):

    def __init__(self, **kwargs):
        host = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']
        api_trace_pattern = kwargs['api_trace_pattern']
        self.connection = netapp_api.NaServer(
            host=host,
            transport_type=kwargs['transport_type'],
            port=kwargs['port'],
            username=username,
            password=password,
            api_trace_pattern=api_trace_pattern)

        self.ssh_client = self._init_ssh_client(host, username, password)

    def _init_ssh_client(self, host, username, password):
        return netapp_api.SSHUtil(
            host=host,
            username=username,
            password=password)

    def _init_features(self):
        """Set up the repository of available Data ONTAP features."""
        self.features = na_utils.Features()

    def get_ontap_version(self, cached=True):
        """Gets the ONTAP version."""

        if cached:
            return self.connection.get_ontap_version()

        ontap_version = netapp_api.NaElement("system-get-version")
        result = self.connection.invoke_successfully(ontap_version, True)

        version_tuple = result.get_child_by_name(
            'version-tuple') or netapp_api.NaElement('none')
        system_version_tuple = version_tuple.get_child_by_name(
            'system-version-tuple') or netapp_api.NaElement('none')

        generation = system_version_tuple.get_child_content("generation")
        major = system_version_tuple.get_child_content("major")

        return '%(generation)s.%(major)s' % {
            'generation': generation,
            'major': major}

    def get_ontapi_version(self, cached=True):
        """Gets the supported ontapi version."""

        if cached:
            return self.connection.get_api_version()

        ontapi_version = netapp_api.NaElement('system-get-ontapi-version')
        res = self.connection.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return major, minor

    def _strip_xml_namespace(self, string):
        if string.startswith('{') and '}' in string:
            return string.split('}', 1)[1]
        return string

    def check_is_naelement(self, elem):
        """Checks if object is instance of NaElement."""
        if not isinstance(elem, netapp_api.NaElement):
            raise ValueError('Expects NaElement')

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group_name=None):
        """Issues API request for creating LUN on volume."""

        path = '/vol/%s/%s' % (volume_name, lun_name)
        space_reservation = metadata['SpaceReserved']
        initial_size = size
        ontap_version = self.get_ontap_version()

        # On older ONTAP versions the extend size is limited to its
        # geometry on max_resize_size. In order to remove this
        # limitation we create the LUN with its maximum possible size
        # and then shrink to the requested size.
        if ontap_version < '9.5':
            initial_size = MAX_SIZE_FOR_A_LUN
            # In order to create a LUN with its maximum size (16TB),
            # the space_reservation needs to be disabled
            space_reservation = 'false'

        params = {'path': path, 'size': str(initial_size),
                  'ostype': metadata['OsType'],
                  'space-reservation-enabled': space_reservation}
        version = self.get_ontapi_version()
        if version >= (1, 110):
            params['use-exact-size'] = 'true'
        lun_create = netapp_api.NaElement.create_node_with_children(
            'lun-create-by-size',
            **params)
        if qos_policy_group_name:
            lun_create.add_new_child('qos-policy-group', qos_policy_group_name)

        try:
            self.connection.invoke_successfully(lun_create, True)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error("Error provisioning volume %(lun_name)s on "
                          "%(volume_name)s. Details: %(ex)s",
                          {'lun_name': lun_name,
                           'volume_name': volume_name,
                           'ex': ex})

        if ontap_version < '9.5':
            self.do_direct_resize(path, six.text_type(size))
            if metadata['SpaceReserved'] == 'true':
                self.set_lun_space_reservation(path, True)

    def set_lun_space_reservation(self, path, flag):
        """Sets the LUN space reservation on ONTAP."""

        lun_modify_space_reservation = (
            netapp_api.NaElement.create_node_with_children(
                'lun-set-space-reservation-info', **{
                    'path': path,
                    'enable': str(flag)}))
        self.connection.invoke_successfully(lun_modify_space_reservation, True)

    def destroy_lun(self, path, force=True):
        """Destroys the LUN at the path."""
        lun_destroy = netapp_api.NaElement.create_node_with_children(
            'lun-destroy',
            **{'path': path})
        if force:
            lun_destroy.add_new_child('force', 'true')
        self.connection.invoke_successfully(lun_destroy, True)
        seg = path.split("/")
        LOG.debug("Destroyed LUN %s", seg[-1])

    def map_lun(self, path, igroup_name, lun_id=None):
        """Maps LUN to the initiator and returns LUN id assigned."""
        lun_map = netapp_api.NaElement.create_node_with_children(
            'lun-map', **{'path': path,
                          'initiator-group': igroup_name})
        if lun_id:
            lun_map.add_new_child('lun-id', lun_id)
        try:
            result = self.connection.invoke_successfully(lun_map, True)
            return result.get_child_content('lun-id-assigned')
        except netapp_api.NaApiError as e:
            code = e.code
            message = e.message
            LOG.warning('Error mapping LUN. Code :%(code)s, Message: '
                        '%(message)s', {'code': code, 'message': message})
            raise

    def unmap_lun(self, path, igroup_name):
        """Unmaps a LUN from given initiator."""
        lun_unmap = netapp_api.NaElement.create_node_with_children(
            'lun-unmap',
            **{'path': path, 'initiator-group': igroup_name})
        try:
            self.connection.invoke_successfully(lun_unmap, True)
        except netapp_api.NaApiError as e:
            exc_info = sys.exc_info()
            LOG.warning("Error unmapping LUN. Code :%(code)s, Message: "
                        "%(message)s", {'code': e.code,
                                        'message': e.message})
            # if the LUN is already unmapped
            if e.code == '13115' or e.code == '9016':
                pass
            else:
                six.reraise(*exc_info)

    def create_igroup(self, igroup, igroup_type='iscsi', os_type='default'):
        """Creates igroup with specified args."""
        igroup_create = netapp_api.NaElement.create_node_with_children(
            'igroup-create',
            **{'initiator-group-name': igroup,
               'initiator-group-type': igroup_type,
               'os-type': os_type})
        self.connection.invoke_successfully(igroup_create, True)

    def add_igroup_initiator(self, igroup, initiator):
        """Adds initiators to the specified igroup."""
        igroup_add = netapp_api.NaElement.create_node_with_children(
            'igroup-add',
            **{'initiator-group-name': igroup,
               'initiator': initiator})
        self.connection.invoke_successfully(igroup_add, True)

    def do_direct_resize(self, path, new_size_bytes, force=True):
        """Resize the LUN."""
        seg = path.split("/")
        LOG.info("Resizing LUN %s directly to new size.", seg[-1])
        lun_resize = netapp_api.NaElement.create_node_with_children(
            'lun-resize',
            **{'path': path,
               'size': new_size_bytes})
        if force:
            lun_resize.add_new_child('force', 'true')
        self.connection.invoke_successfully(lun_resize, True)

    def get_lun_geometry(self, path):
        """Gets the LUN geometry."""
        geometry = {}
        lun_geo = netapp_api.NaElement("lun-get-geometry")
        lun_geo.add_new_child('path', path)
        try:
            result = self.connection.invoke_successfully(lun_geo, True)
            geometry['size'] = result.get_child_content("size")
            geometry['bytes_per_sector'] =\
                result.get_child_content("bytes-per-sector")
            geometry['sectors_per_track'] =\
                result.get_child_content("sectors-per-track")
            geometry['tracks_per_cylinder'] =\
                result.get_child_content("tracks-per-cylinder")
            geometry['cylinders'] =\
                result.get_child_content("cylinders")
            geometry['max_resize'] =\
                result.get_child_content("max-resize-size")
        except Exception as e:
            LOG.error("LUN %(path)s geometry failed. Message - %(msg)s",
                      {'path': path, 'msg': six.text_type(e)})
        return geometry

    def get_volume_options(self, volume_name):
        """Get the value for the volume option."""
        opts = []
        vol_option_list = netapp_api.NaElement("volume-options-list-info")
        vol_option_list.add_new_child('volume', volume_name)
        result = self.connection.invoke_successfully(vol_option_list, True)
        options = result.get_child_by_name("options")
        if options:
            opts = options.get_children()
        return opts

    def move_lun(self, path, new_path):
        """Moves the LUN at path to new path."""
        seg = path.split("/")
        new_seg = new_path.split("/")
        LOG.debug("Moving LUN %(name)s to %(new_name)s.",
                  {'name': seg[-1], 'new_name': new_seg[-1]})
        lun_move = netapp_api.NaElement("lun-move")
        lun_move.add_new_child("path", path)
        lun_move.add_new_child("new-path", new_path)
        self.connection.invoke_successfully(lun_move, True)

    def get_iscsi_target_details(self):
        """Gets the iSCSI target portal details."""
        raise NotImplementedError()

    def get_fc_target_wwpns(self):
        """Gets the FC target details."""
        raise NotImplementedError()

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        raise NotImplementedError()

    def check_iscsi_initiator_exists(self, iqn):
        """Returns True if initiator exists."""
        raise NotImplementedError()

    def set_iscsi_chap_authentication(self, iqn, username, password):
        """Provides NetApp host's CHAP credentials to the backend."""
        raise NotImplementedError()

    def get_lun_list(self):
        """Gets the list of LUNs on filer."""
        raise NotImplementedError()

    def get_igroup_by_initiators(self, initiator_list):
        """Get igroups exactly matching a set of initiators."""
        raise NotImplementedError()

    def _has_luns_mapped_to_initiator(self, initiator):
        """Checks whether any LUNs are mapped to the given initiator."""
        lun_list_api = netapp_api.NaElement('lun-initiator-list-map-info')
        lun_list_api.add_new_child('initiator', initiator)
        result = self.connection.invoke_successfully(lun_list_api, True)
        lun_maps_container = result.get_child_by_name(
            'lun-maps') or netapp_api.NaElement('none')
        return len(lun_maps_container.get_children()) > 0

    def has_luns_mapped_to_initiators(self, initiator_list):
        """Checks whether any LUNs are mapped to the given initiator(s)."""
        for initiator in initiator_list:
            if self._has_luns_mapped_to_initiator(initiator):
                return True
        return False

    def get_lun_by_args(self, **args):
        """Retrieves LUNs with specified args."""
        raise NotImplementedError()

    def get_performance_counter_info(self, object_name, counter_name):
        """Gets info about one or more Data ONTAP performance counters."""

        api_args = {'objectname': object_name}
        result = self.connection.send_request('perf-object-counter-list-info',
                                              api_args,
                                              enable_tunneling=False)

        counters = result.get_child_by_name(
            'counters') or netapp_api.NaElement('None')

        for counter in counters.get_children():

            if counter.get_child_content('name') == counter_name:

                labels = []
                label_list = counter.get_child_by_name(
                    'labels') or netapp_api.NaElement('None')
                for label in label_list.get_children():
                    labels.extend(label.get_content().split(','))
                base_counter = counter.get_child_content('base-counter')

                return {
                    'name': counter_name,
                    'labels': labels,
                    'base-counter': base_counter,
                }
        else:
            raise exception.NotFound(_('Counter %s not found') % counter_name)

    def delete_snapshot(self, volume_name, snapshot_name):
        """Deletes a volume snapshot."""
        api_args = {'volume': volume_name, 'snapshot': snapshot_name}
        self.connection.send_request('snapshot-delete', api_args)

    def create_cg_snapshot(self, volume_names, snapshot_name):
        """Creates a consistency group snapshot out of one or more flexvols.

        ONTAP requires an invocation of cg-start to first fence off the
        flexvols to be included in the snapshot. If cg-start returns
        success, a cg-commit must be executed to finalized the snapshot and
        unfence the flexvols.
        """
        cg_id = self._start_cg_snapshot(volume_names, snapshot_name)
        if not cg_id:
            msg = _('Could not start consistency group snapshot %s.')
            raise exception.VolumeBackendAPIException(data=msg % snapshot_name)
        self._commit_cg_snapshot(cg_id)

    def _start_cg_snapshot(self, volume_names, snapshot_name):
        snapshot_init = {
            'snapshot': snapshot_name,
            'timeout': 'relaxed',
            'volumes': [
                {'volume-name': volume_name} for volume_name in volume_names
            ],
        }
        result = self.connection.send_request('cg-start', snapshot_init)
        return result.get_child_content('cg-id')

    def _commit_cg_snapshot(self, cg_id):
        snapshot_commit = {'cg-id': cg_id}
        self.connection.send_request('cg-commit', snapshot_commit)

    def get_snapshot(self, volume_name, snapshot_name):
        """Gets a single snapshot."""
        raise NotImplementedError()

    @utils.retry(exception.SnapshotIsBusy)
    def wait_for_busy_snapshot(self, flexvol, snapshot_name):
        """Checks for and handles a busy snapshot.

        If a snapshot is busy, for reasons other than cloning, an exception is
        raised immediately. Otherwise, wait for a period of time for the clone
        dependency to finish before giving up. If the snapshot is not busy then
        no action is taken and the method exits.
        """
        snapshot = self.get_snapshot(flexvol, snapshot_name)
        if not snapshot['busy']:
            LOG.debug("Backing consistency group snapshot %s available for "
                      "deletion.", snapshot_name)
            return
        else:
            LOG.debug("Snapshot %(snap)s for vol %(vol)s is busy, waiting "
                      "for volume clone dependency to clear.",
                      {"snap": snapshot_name, "vol": flexvol})
            raise exception.SnapshotIsBusy(snapshot_name=snapshot_name)

    def mark_snapshot_for_deletion(self, volume, snapshot_name):
        """Mark snapshot for deletion by renaming snapshot."""
        return self.rename_snapshot(
            volume, snapshot_name, DELETED_PREFIX + snapshot_name)

    def rename_snapshot(self, volume, current_name, new_name):
        """Renames a snapshot."""
        api_args = {
            'volume': volume,
            'current-name': current_name,
            'new-name': new_name,
        }
        return self.connection.send_request('snapshot-rename', api_args)
