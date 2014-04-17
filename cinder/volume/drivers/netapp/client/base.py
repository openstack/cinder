# Copyright (c) - 2014, Alex Meade.  All rights reserved.
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

import sys

from oslo.utils import excutils
import six

from cinder.i18n import _LE, _LW, _LI
from cinder.openstack.common import log as logging
from cinder.volume.drivers.netapp import api as netapp_api


LOG = logging.getLogger(__name__)


class Client(object):

    def __init__(self, connection):
        self.connection = connection

    def get_ontapi_version(self):
        """Gets the supported ontapi version."""
        ontapi_version = netapp_api.NaElement('system-get-ontapi-version')
        res = self.connection.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return (major, minor)

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group=None):
        """Issues API request for creating LUN on volume."""

        path = '/vol/%s/%s' % (volume_name, lun_name)
        lun_create = netapp_api.NaElement.create_node_with_children(
            'lun-create-by-size',
            **{'path': path, 'size': six.text_type(size),
               'ostype': metadata['OsType'],
               'space-reservation-enabled': metadata['SpaceReserved']})
        if qos_policy_group:
            lun_create.add_new_child('qos-policy-group', qos_policy_group)

        try:
            self.connection.invoke_successfully(lun_create, True)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                msg = _LE("Error provisioning volume %(lun_name)s on "
                          "%(volume_name)s. Details: %(ex)s")
                msg_args = {'lun_name': lun_name,
                            'volume_name': volume_name,
                            'ex': six.text_type(ex)}
                LOG.error(msg % msg_args)

    def destroy_lun(self, path, force=True):
        """Destroys the lun at the path."""
        lun_destroy = netapp_api.NaElement.create_node_with_children(
            'lun-destroy',
            **{'path': path})
        if force:
            lun_destroy.add_new_child('force', 'true')
        self.connection.invoke_successfully(lun_destroy, True)
        seg = path.split("/")
        LOG.debug("Destroyed LUN %s" % seg[-1])

    def map_lun(self, path, igroup_name, lun_id=None):
        """Maps lun to the initiator and returns lun id assigned."""
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
            msg = _LW('Error mapping lun. Code :%(code)s, Message:%(message)s')
            msg_fmt = {'code': code, 'message': message}
            LOG.warning(msg % msg_fmt)
            raise

    def unmap_lun(self, path, igroup_name):
        """Unmaps a lun from given initiator."""
        lun_unmap = netapp_api.NaElement.create_node_with_children(
            'lun-unmap',
            **{'path': path, 'initiator-group': igroup_name})
        try:
            self.connection.invoke_successfully(lun_unmap, True)
        except netapp_api.NaApiError as e:
            msg = _LW("Error unmapping lun. Code :%(code)s,"
                      " Message:%(message)s")
            msg_fmt = {'code': e.code, 'message': e.message}
            exc_info = sys.exc_info()
            LOG.warning(msg % msg_fmt)
            # if the lun is already unmapped
            if e.code == '13115' or e.code == '9016':
                pass
            else:
                raise exc_info[0], exc_info[1], exc_info[2]

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
        """Resize the lun."""
        seg = path.split("/")
        LOG.info(_LI("Resizing lun %s directly to new size."), seg[-1])
        lun_resize = netapp_api.NaElement.create_node_with_children(
            'lun-resize',
            **{'path': path,
               'size': new_size_bytes})
        if force:
            lun_resize.add_new_child('force', 'true')
        self.connection.invoke_successfully(lun_resize, True)

    def get_lun_geometry(self, path):
        """Gets the lun geometry."""
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
            LOG.error(_LE("Lun %(path)s geometry failed. Message - %(msg)s")
                      % {'path': path, 'msg': e.message})
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
        """Moves the lun at path to new path."""
        seg = path.split("/")
        new_seg = new_path.split("/")
        LOG.debug("Moving lun %(name)s to %(new_name)s."
                  % {'name': seg[-1], 'new_name': new_seg[-1]})
        lun_move = netapp_api.NaElement("lun-move")
        lun_move.add_new_child("path", path)
        lun_move.add_new_child("new-path", new_path)
        self.connection.invoke_successfully(lun_move, True)

    def get_target_details(self):
        """Gets the target portal details."""
        raise NotImplementedError()

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        raise NotImplementedError()

    def get_lun_list(self):
        """Gets the list of luns on filer."""
        raise NotImplementedError()

    def get_igroup_by_initiator(self, initiator):
        """Get igroups by initiator."""
        raise NotImplementedError()

    def get_lun_by_args(self, **args):
        """Retrieves luns with specified args."""
        raise NotImplementedError()
