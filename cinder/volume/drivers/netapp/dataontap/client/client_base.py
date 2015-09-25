# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
import socket
import sys

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils

import six

from cinder.i18n import _LE, _LW, _LI
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


@six.add_metaclass(utils.TraceWrapperMetaclass)
class Client(object):

    def __init__(self, **kwargs):
        self.connection = netapp_api.NaServer(
            host=kwargs['hostname'],
            transport_type=kwargs['transport_type'],
            port=kwargs['port'],
            username=kwargs['username'],
            password=kwargs['password'])

    def _init_features(self):
        """Set up the repository of available Data ONTAP features."""
        self.features = na_utils.Features()

    def get_ontapi_version(self, cached=True):
        """Gets the supported ontapi version."""

        if cached:
            return self.connection.get_api_version()

        ontapi_version = netapp_api.NaElement('system-get-ontapi-version')
        res = self.connection.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return major, minor

    def get_connection(self):
        return self.connection

    def check_is_naelement(self, elem):
        """Checks if object is instance of NaElement."""
        if not isinstance(elem, netapp_api.NaElement):
            raise ValueError('Expects NaElement')

    def send_request(self, api_name, api_args=None, enable_tunneling=True):
        """Sends request to Ontapi."""
        request = netapp_api.NaElement(api_name)
        if api_args:
            request.translate_struct(api_args)
        return self.connection.invoke_successfully(request, enable_tunneling)

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group_name=None):
        """Issues API request for creating LUN on volume."""

        path = '/vol/%s/%s' % (volume_name, lun_name)
        lun_create = netapp_api.NaElement.create_node_with_children(
            'lun-create-by-size',
            **{'path': path, 'size': six.text_type(size),
               'ostype': metadata['OsType'],
               'space-reservation-enabled': metadata['SpaceReserved']})
        if qos_policy_group_name:
            lun_create.add_new_child('qos-policy-group', qos_policy_group_name)

        try:
            self.connection.invoke_successfully(lun_create, True)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error provisioning volume %(lun_name)s on "
                              "%(volume_name)s. Details: %(ex)s"),
                          {'lun_name': lun_name,
                           'volume_name': volume_name,
                           'ex': ex})

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
            LOG.warning(_LW('Error mapping LUN. Code :%(code)s, Message: '
                            '%(message)s'), {'code': code, 'message': message})
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
            LOG.warning(_LW("Error unmapping LUN. Code :%(code)s, Message: "
                            "%(message)s"), {'code': e.code,
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
        LOG.info(_LI("Resizing LUN %s directly to new size."), seg[-1])
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
            LOG.error(_LE("LUN %(path)s geometry failed. Message - %(msg)s"),
                      {'path': path, 'msg': e.message})
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

    def provide_ems(self, requester, netapp_backend, app_version,
                    server_type="cluster"):
        """Provide ems with volume stats for the requester.

        :param server_type: cluster or 7mode.
        """
        def _create_ems(netapp_backend, app_version, server_type):
            """Create ems API request."""
            ems_log = netapp_api.NaElement('ems-autosupport-log')
            host = socket.getfqdn() or 'Cinder_node'
            if server_type == "cluster":
                dest = "cluster node"
            else:
                dest = "7 mode controller"
            ems_log.add_new_child('computer-name', host)
            ems_log.add_new_child('event-id', '0')
            ems_log.add_new_child('event-source',
                                  'Cinder driver %s' % netapp_backend)
            ems_log.add_new_child('app-version', app_version)
            ems_log.add_new_child('category', 'provisioning')
            ems_log.add_new_child('event-description',
                                  'OpenStack Cinder connected to %s' % dest)
            ems_log.add_new_child('log-level', '6')
            ems_log.add_new_child('auto-support', 'false')
            return ems_log

        def _create_vs_get():
            """Create vs_get API request."""
            vs_get = netapp_api.NaElement('vserver-get-iter')
            vs_get.add_new_child('max-records', '1')
            query = netapp_api.NaElement('query')
            query.add_node_with_children('vserver-info',
                                         **{'vserver-type': 'node'})
            vs_get.add_child_elem(query)
            desired = netapp_api.NaElement('desired-attributes')
            desired.add_node_with_children(
                'vserver-info', **{'vserver-name': '', 'vserver-type': ''})
            vs_get.add_child_elem(desired)
            return vs_get

        def _get_cluster_node(na_server):
            """Get the cluster node for ems."""
            na_server.set_vserver(None)
            vs_get = _create_vs_get()
            res = na_server.invoke_successfully(vs_get)
            if (res.get_child_content('num-records') and
               int(res.get_child_content('num-records')) > 0):
                attr_list = res.get_child_by_name('attributes-list')
                vs_info = attr_list.get_child_by_name('vserver-info')
                vs_name = vs_info.get_child_content('vserver-name')
                return vs_name
            return None

        do_ems = True
        if hasattr(requester, 'last_ems'):
            sec_limit = 3559
            if not (timeutils.is_older_than(requester.last_ems, sec_limit)):
                do_ems = False
        if do_ems:
            na_server = copy.copy(self.connection)
            na_server.set_timeout(25)
            ems = _create_ems(netapp_backend, app_version, server_type)
            try:
                if server_type == "cluster":
                    api_version = na_server.get_api_version()
                    if api_version:
                        major, minor = api_version
                    else:
                        raise netapp_api.NaApiError(
                            code='Not found',
                            message='No API version found')
                    if major == 1 and minor > 15:
                        node = getattr(requester, 'vserver', None)
                    else:
                        node = _get_cluster_node(na_server)
                    if node is None:
                        raise netapp_api.NaApiError(
                            code='Not found',
                            message='No vserver found')
                    na_server.set_vserver(node)
                else:
                    na_server.set_vfiler(None)
                na_server.invoke_successfully(ems, True)
                LOG.debug("ems executed successfully.")
            except netapp_api.NaApiError as e:
                LOG.warning(_LW("Failed to invoke ems. Message : %s"), e)
            finally:
                requester.last_ems = timeutils.utcnow()
