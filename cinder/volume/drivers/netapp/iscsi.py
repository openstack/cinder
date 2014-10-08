# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack Foundation
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
"""
Volume driver for NetApp iSCSI storage systems.

This driver requires NetApp Clustered Data ONTAP or 7-mode
storage systems with installed iSCSI licenses.
"""

import copy
import math
import sys
import time
import uuid

import six

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement
from cinder.volume.drivers.netapp.api import NaServer
from cinder.volume.drivers.netapp.options import netapp_7mode_opts
from cinder.volume.drivers.netapp.options import netapp_basicauth_opts
from cinder.volume.drivers.netapp.options import netapp_cluster_opts
from cinder.volume.drivers.netapp.options import netapp_connection_opts
from cinder.volume.drivers.netapp.options import netapp_provisioning_opts
from cinder.volume.drivers.netapp.options import netapp_transport_opts
from cinder.volume.drivers.netapp import ssc_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers.netapp.utils import get_volume_extra_specs
from cinder.volume.drivers.netapp.utils import round_down
from cinder.volume.drivers.netapp.utils import set_safe_attr
from cinder.volume.drivers.netapp.utils import validate_instantiation
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


class NetAppLun(object):
    """Represents a LUN on NetApp storage."""

    def __init__(self, handle, name, size, metadata_dict):
        self.handle = handle
        self.name = name
        self.size = size
        self.metadata = metadata_dict or {}

    def get_metadata_property(self, prop):
        """Get the metadata property of a LUN."""
        if prop in self.metadata:
            return self.metadata[prop]
        name = self.name
        msg = _("No metadata property %(prop)s defined for the"
                " LUN %(name)s")
        msg_fmt = {'prop': prop, 'name': name}
        LOG.debug(msg % msg_fmt)

    def __str__(self, *args, **kwargs):
        return 'NetApp Lun[handle:%s, name:%s, size:%s, metadata:%s]'\
               % (self.handle, self.name, self.size, self.metadata)


class NetAppDirectISCSIDriver(driver.ISCSIDriver):
    """NetApp Direct iSCSI volume driver."""

    VERSION = "1.0.0"

    IGROUP_PREFIX = 'openstack-'
    required_flags = ['netapp_transport_type', 'netapp_login',
                      'netapp_password', 'netapp_server_hostname',
                      'netapp_server_port']

    def __init__(self, *args, **kwargs):
        super(NetAppDirectISCSIDriver, self).__init__(*args, **kwargs)
        validate_instantiation(**kwargs)
        self.configuration.append_config_values(netapp_connection_opts)
        self.configuration.append_config_values(netapp_basicauth_opts)
        self.configuration.append_config_values(netapp_transport_opts)
        self.configuration.append_config_values(netapp_provisioning_opts)
        self.lun_table = {}

    def _create_client(self, **kwargs):
        """Instantiate a client for NetApp server.

        This method creates NetApp server client for api communication.
        """

        host_filer = kwargs['hostname']
        LOG.debug('Using NetApp filer: %s' % host_filer)
        self.client = NaServer(host=host_filer,
                               server_type=NaServer.SERVER_TYPE_FILER,
                               transport_type=kwargs['transport_type'],
                               style=NaServer.STYLE_LOGIN_PASSWORD,
                               username=kwargs['login'],
                               password=kwargs['password'])

    def _do_custom_setup(self):
        """Does custom setup depending on the type of filer."""
        raise NotImplementedError()

    def _check_flags(self):
        """Ensure that the flags we care about are set."""
        required_flags = self.required_flags
        for flag in required_flags:
            if not getattr(self.configuration, flag, None):
                msg = _('%s is not set') % flag
                raise exception.InvalidInput(reason=msg)

    def do_setup(self, context):
        """Setup the NetApp Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about and setup NetApp
        client.
        """

        self._check_flags()
        self._create_client(
            transport_type=self.configuration.netapp_transport_type,
            login=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port)
        self._do_custom_setup()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.

        Discovers the LUNs on the NetApp server.
        """

        self.lun_table = {}
        self._get_lun_list()
        LOG.debug("Success getting LUN list from server")

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata') or dict()
        return metadata.get('Volume', None)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume (aka ONTAP LUN)."""

        LOG.debug('create_volume on %s' % volume['host'])

        # get ONTAP volume name as pool name
        ontap_volume_name = volume_utils.extract_host(volume['host'],
                                                      level='pool')

        if ontap_volume_name is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        lun_name = volume['name']

        # start with default size, get requested size
        default_size = units.Mi * 100  # 100 MB
        size = default_size if not int(volume['size'])\
            else int(volume['size']) * units.Gi

        metadata = {'OsType': 'linux', 'SpaceReserved': 'true'}

        extra_specs = get_volume_extra_specs(volume)
        qos_policy_group = extra_specs.pop('netapp:qos_policy_group', None) \
            if extra_specs else None

        # warn on obsolete extra specs
        na_utils.log_extra_spec_warnings(extra_specs)

        self.create_lun(ontap_volume_name, lun_name, size,
                        metadata, qos_policy_group)
        LOG.debug('Created LUN with name %s' % lun_name)

        metadata['Path'] = '/vol/%s/%s' % (ontap_volume_name, lun_name)
        metadata['Volume'] = ontap_volume_name
        metadata['Qtree'] = None

        handle = self._create_lun_handle(metadata)
        self._add_lun_to_table(NetAppLun(handle, lun_name, size, metadata))

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        if not metadata:
            msg = _("No entry in LUN table for volume/snapshot %(name)s.")
            msg_fmt = {'name': name}
            LOG.warn(msg % msg_fmt)
            return
        self._destroy_lun(metadata['Path'])
        self.lun_table.pop(name)

    def _destroy_lun(self, path, force=True):
        """Destroys the lun at the path."""
        lun_destroy = NaElement.create_node_with_children(
            'lun-destroy',
            **{'path': path})
        if force:
            lun_destroy.add_new_child('force', 'true')
        self.client.invoke_successfully(lun_destroy, True)
        seg = path.split("/")
        LOG.debug("Destroyed LUN %s" % seg[-1])

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        handle = self._get_lun_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        handle = self._get_lun_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """

        pass

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance.

        Do the LUN masking on the storage system so the initiator can access
        the LUN on the target. Also return the iSCSI properties so the
        initiator can find the LUN. This implementation does not call
        _get_iscsi_properties() to get the properties because cannot store the
        LUN number in the database. We only find out what the LUN number will
        be during this method call so we construct the properties dictionary
        ourselves.
        """

        initiator_name = connector['initiator']
        name = volume['name']
        lun_id = self._map_lun(name, initiator_name, 'iscsi', None)
        msg = _("Mapped LUN %(name)s to the initiator %(initiator_name)s")
        msg_fmt = {'name': name, 'initiator_name': initiator_name}
        LOG.debug(msg % msg_fmt)
        iqn = self._get_iscsi_service_details()
        target_details_list = self._get_target_details()
        msg = _("Successfully fetched target details for LUN %(name)s and "
                "initiator %(initiator_name)s")
        msg_fmt = {'name': name, 'initiator_name': initiator_name}
        LOG.debug(msg % msg_fmt)

        if not target_details_list:
            msg = _('No iscsi target details were found for LUN %s')
            raise exception.VolumeBackendAPIException(data=msg % name)
        target_details = None
        for tgt_detail in target_details_list:
            if tgt_detail.get('interface-enabled', 'true') == 'true':
                target_details = tgt_detail
                break
        if not target_details:
            target_details = target_details_list[0]

        if not target_details['address'] and target_details['port']:
            msg = _('Failed to get target portal for the LUN %s')
            raise exception.VolumeBackendAPIException(data=msg % name)
        if not iqn:
            msg = _('Failed to get target IQN for the LUN %s')
            raise exception.VolumeBackendAPIException(data=msg % name)

        properties = {}
        properties['target_discovered'] = False
        (address, port) = (target_details['address'], target_details['port'])
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun_id
        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.

        This driver implements snapshots by using efficient single-file
        (LUN) cloning.
        """

        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        lun = self._get_lun_from_table(vol_name)
        self._clone_lun(lun.name, snapshot_name, 'false')

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        self.delete_volume(snapshot)
        LOG.debug("Snapshot %s deletion successful" % snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for creating a new volume from a snapshot.

        Many would call this "cloning" and in fact we use cloning to implement
        this feature.
        """

        vol_size = volume['size']
        snap_size = snapshot['volume_size']
        snapshot_name = snapshot['name']
        new_name = volume['name']
        self._clone_lun(snapshot_name, new_name, 'true')
        if vol_size != snap_size:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(
                        _("Resizing %s failed. Cleaning volume."), new_name)
                    self.delete_volume(volume)

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given initiator can no
        longer access it.
        """

        initiator_name = connector['initiator']
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        self._unmap_lun(path, initiator_name)
        msg = _("Unmapped LUN %(name)s from the initiator "
                "%(initiator_name)s")
        msg_fmt = {'name': name, 'initiator_name': initiator_name}
        LOG.debug(msg % msg_fmt)

    def _get_ontapi_version(self):
        """Gets the supported ontapi version."""
        ontapi_version = NaElement('system-get-ontapi-version')
        res = self.client.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return (major, minor)

    def create_lun(self, volume_name, lun_name, size,
                   metadata, qos_policy_group=None):
        """Issues API request for creating LUN on volume."""

        path = '/vol/%s/%s' % (volume_name, lun_name)
        lun_create = NaElement.create_node_with_children(
            'lun-create-by-size',
            **{'path': path, 'size': six.text_type(size),
                'ostype': metadata['OsType'],
                'space-reservation-enabled': metadata['SpaceReserved']})
        if qos_policy_group:
            lun_create.add_new_child('qos-policy-group', qos_policy_group)

        try:
            self.client.invoke_successfully(lun_create, True)
        except NaApiError as ex:
            with excutils.save_and_reraise_exception():
                msg = _("Error provisioning volume %(lun_name)s on "
                        "%(volume_name)s. Details: %(ex)s")
                msg_args = {'lun_name': lun_name,
                            'volume_name': volume_name,
                            'ex': six.text_type(ex)}
                LOG.error(msg % msg_args)

    def _get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        raise NotImplementedError()

    def _get_target_details(self):
        """Gets the target portal details."""
        raise NotImplementedError()

    def _create_lun_handle(self, metadata):
        """Returns lun handle based on filer type."""
        raise NotImplementedError()

    def _get_lun_list(self):
        """Gets the list of luns on filer."""
        raise NotImplementedError()

    def _extract_and_populate_luns(self, api_luns):
        """Extracts the luns from api.

        Populates in the lun table.
        """

        for lun in api_luns:
            meta_dict = self._create_lun_meta(lun)
            path = lun.get_child_content('path')
            (rest, splitter, name) = path.rpartition('/')
            handle = self._create_lun_handle(meta_dict)
            size = lun.get_child_content('size')
            discovered_lun = NetAppLun(handle, name,
                                       size, meta_dict)
            self._add_lun_to_table(discovered_lun)

    def _is_naelement(self, elem):
        """Checks if element is NetApp element."""
        if not isinstance(elem, NaElement):
            raise ValueError('Expects NaElement')

    def _map_lun(self, name, initiator, initiator_type='iscsi', lun_id=None):
        """Maps lun to the initiator and returns lun id assigned."""
        metadata = self._get_lun_attr(name, 'metadata')
        os = metadata['OsType']
        path = metadata['Path']
        if self._check_allowed_os(os):
            os = os
        else:
            os = 'default'
        igroup_name = self._get_or_create_igroup(initiator,
                                                 initiator_type, os)
        lun_map = NaElement.create_node_with_children(
            'lun-map', **{'path': path,
                          'initiator-group': igroup_name})
        if lun_id:
            lun_map.add_new_child('lun-id', lun_id)
        try:
            result = self.client.invoke_successfully(lun_map, True)
            return result.get_child_content('lun-id-assigned')
        except NaApiError as e:
            code = e.code
            message = e.message
            msg = _('Error mapping lun. Code :%(code)s, Message:%(message)s')
            msg_fmt = {'code': code, 'message': message}
            exc_info = sys.exc_info()
            LOG.warn(msg % msg_fmt)
            (igroup, lun_id) = self._find_mapped_lun_igroup(path, initiator)
            if lun_id is not None:
                return lun_id
            else:
                raise exc_info[0], exc_info[1], exc_info[2]

    def _unmap_lun(self, path, initiator):
        """Unmaps a lun from given initiator."""
        (igroup_name, lun_id) = self._find_mapped_lun_igroup(path, initiator)
        lun_unmap = NaElement.create_node_with_children(
            'lun-unmap',
            **{'path': path, 'initiator-group': igroup_name})
        try:
            self.client.invoke_successfully(lun_unmap, True)
        except NaApiError as e:
            msg = _("Error unmapping lun. Code :%(code)s,"
                    " Message:%(message)s")
            msg_fmt = {'code': e.code, 'message': e.message}
            exc_info = sys.exc_info()
            LOG.warn(msg % msg_fmt)
            # if the lun is already unmapped
            if e.code == '13115' or e.code == '9016':
                pass
            else:
                raise exc_info[0], exc_info[1], exc_info[2]

    def _find_mapped_lun_igroup(self, path, initiator, os=None):
        """Find the igroup for mapped lun with initiator."""
        raise NotImplementedError()

    def _get_or_create_igroup(self, initiator, initiator_type='iscsi',
                              os='default'):
        """Checks for an igroup for an initiator.

        Creates igroup if not found.
        """

        igroups = self._get_igroup_by_initiator(initiator=initiator)
        igroup_name = None
        for igroup in igroups:
            if igroup['initiator-group-os-type'] == os:
                if igroup['initiator-group-type'] == initiator_type or \
                        igroup['initiator-group-type'] == 'mixed':
                    if igroup['initiator-group-name'].startswith(
                            self.IGROUP_PREFIX):
                        igroup_name = igroup['initiator-group-name']
                        break
        if not igroup_name:
            igroup_name = self.IGROUP_PREFIX + str(uuid.uuid4())
            self._create_igroup(igroup_name, initiator_type, os)
            self._add_igroup_initiator(igroup_name, initiator)
        return igroup_name

    def _get_igroup_by_initiator(self, initiator):
        """Get igroups by initiator."""
        raise NotImplementedError()

    def _check_allowed_os(self, os):
        """Checks if the os type supplied is NetApp supported."""
        if os in ['linux', 'aix', 'hpux', 'windows', 'solaris',
                  'netware', 'vmware', 'openvms', 'xen', 'hyper_v']:
            return True
        else:
            return False

    def _create_igroup(self, igroup, igroup_type='iscsi', os_type='default'):
        """Creates igroup with specified args."""
        igroup_create = NaElement.create_node_with_children(
            'igroup-create',
            **{'initiator-group-name': igroup,
               'initiator-group-type': igroup_type,
               'os-type': os_type})
        self.client.invoke_successfully(igroup_create, True)

    def _add_igroup_initiator(self, igroup, initiator):
        """Adds initiators to the specified igroup."""
        igroup_add = NaElement.create_node_with_children(
            'igroup-add',
            **{'initiator-group-name': igroup,
               'initiator': initiator})
        self.client.invoke_successfully(igroup_add, True)

    def _add_lun_to_table(self, lun):
        """Adds LUN to cache table."""
        if not isinstance(lun, NetAppLun):
            msg = _("Object is not a NetApp LUN.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.lun_table[lun.name] = lun

    def _get_lun_from_table(self, name):
        """Gets LUN from cache table.

        Refreshes cache if lun not found in cache.
        """
        lun = self.lun_table.get(name)
        if lun is None:
            self._get_lun_list()
            lun = self.lun_table.get(name)
            if lun is None:
                raise exception.VolumeNotFound(volume_id=name)
        return lun

    def _clone_lun(self, name, new_name, space_reserved='true',
                   src_block=0, dest_block=0, block_count=0):
        """Clone LUN with the given name to the new name."""
        raise NotImplementedError()

    def _get_lun_by_args(self, **args):
        """Retrieves luns with specified args."""
        raise NotImplementedError()

    def _get_lun_attr(self, name, attr):
        """Get the lun attribute if found else None."""
        try:
            attr = getattr(self._get_lun_from_table(name), attr)
            return attr
        except exception.VolumeNotFound as e:
            LOG.error(_("Message: %s"), e.msg)
        except Exception as e:
            LOG.error(_("Error getting lun attribute. Exception: %s"),
                      e.__str__())
        return None

    def _create_lun_meta(self, lun):
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_size = volume['size']
        src_vol = self._get_lun_from_table(src_vref['name'])
        src_vol_size = src_vref['size']
        new_name = volume['name']
        self._clone_lun(src_vol.name, new_name, 'true')
        if vol_size != src_vol_size:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(
                        _("Resizing %s failed. Cleaning volume."), new_name)
                    self.delete_volume(volume)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        raise NotImplementedError()

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        name = volume['name']
        lun = self._get_lun_from_table(name)
        path = lun.metadata['Path']
        curr_size_bytes = str(lun.size)
        new_size_bytes = str(int(new_size) * units.Gi)
        # Reused by clone scenarios.
        # Hence comparing the stored size.
        if curr_size_bytes != new_size_bytes:
            lun_geometry = self._get_lun_geometry(path)
            if (lun_geometry and lun_geometry.get("max_resize")
                    and int(lun_geometry.get("max_resize")) >=
                    int(new_size_bytes)):
                self._do_direct_resize(path, new_size_bytes)
            else:
                self._do_sub_clone_resize(path, new_size_bytes)
            self.lun_table[name].size = new_size_bytes
        else:
            LOG.info(_("No need to extend volume %s"
                       " as it is already the requested new size."), name)

    def _do_direct_resize(self, path, new_size_bytes, force=True):
        """Uses the resize api to resize the lun."""
        seg = path.split("/")
        LOG.info(_("Resizing lun %s directly to new size."), seg[-1])
        lun_resize = NaElement("lun-resize")
        lun_resize.add_new_child('path', path)
        lun_resize.add_new_child('size', new_size_bytes)
        if force:
            lun_resize.add_new_child('force', 'true')
        self.client.invoke_successfully(lun_resize, True)

    def _get_lun_geometry(self, path):
        """Gets the lun geometry."""
        geometry = {}
        lun_geo = NaElement("lun-get-geometry")
        lun_geo.add_new_child('path', path)
        try:
            result = self.client.invoke_successfully(lun_geo, True)
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
            LOG.error(_("Lun %(path)s geometry failed. Message - %(msg)s")
                      % {'path': path, 'msg': e.message})
        return geometry

    def _get_volume_options(self, volume_name):
        """Get the value for the volume option."""
        opts = []
        vol_option_list = NaElement("volume-options-list-info")
        vol_option_list.add_new_child('volume', volume_name)
        result = self.client.invoke_successfully(vol_option_list, True)
        options = result.get_child_by_name("options")
        if options:
            opts = options.get_children()
        return opts

    def _get_vol_option(self, volume_name, option_name):
        """Get the value for the volume option."""
        value = None
        options = self._get_volume_options(volume_name)
        for opt in options:
            if opt.get_child_content('name') == option_name:
                value = opt.get_child_content('value')
                break
        return value

    def _move_lun(self, path, new_path):
        """Moves the lun at path to new path."""
        seg = path.split("/")
        new_seg = new_path.split("/")
        LOG.debug("Moving lun %(name)s to %(new_name)s."
                  % {'name': seg[-1], 'new_name': new_seg[-1]})
        lun_move = NaElement("lun-move")
        lun_move.add_new_child("path", path)
        lun_move.add_new_child("new-path", new_path)
        self.client.invoke_successfully(lun_move, True)

    def _do_sub_clone_resize(self, path, new_size_bytes):
        """Does sub lun clone after verification.

            Clones the block ranges and swaps
            the luns also deletes older lun
            after a successful clone.
        """
        seg = path.split("/")
        LOG.info(_("Resizing lun %s using sub clone to new size."), seg[-1])
        name = seg[-1]
        vol_name = seg[2]
        lun = self._get_lun_from_table(name)
        metadata = lun.metadata
        compression = self._get_vol_option(vol_name, 'compression')
        if compression == "on":
            msg = _('%s cannot be sub clone resized'
                    ' as it is hosted on compressed volume')
            raise exception.VolumeBackendAPIException(data=msg % name)
        else:
            block_count = self._get_lun_block_count(path)
            if block_count == 0:
                msg = _('%s cannot be sub clone resized'
                        ' as it contains no blocks.')
                raise exception.VolumeBackendAPIException(data=msg % name)
            new_lun = 'new-%s' % (name)
            self.create_lun(vol_name, new_lun, new_size_bytes, metadata)
            try:
                self._clone_lun(name, new_lun, block_count=block_count)
                self._post_sub_clone_resize(path)
            except Exception:
                with excutils.save_and_reraise_exception():
                    new_path = '/vol/%s/%s' % (vol_name, new_lun)
                    self._destroy_lun(new_path)

    def _post_sub_clone_resize(self, path):
        """Try post sub clone resize in a transactional manner."""
        st_tm_mv, st_nw_mv, st_del_old = None, None, None
        seg = path.split("/")
        LOG.info(_("Post clone resize lun %s"), seg[-1])
        new_lun = 'new-%s' % (seg[-1])
        tmp_lun = 'tmp-%s' % (seg[-1])
        tmp_path = "/vol/%s/%s" % (seg[2], tmp_lun)
        new_path = "/vol/%s/%s" % (seg[2], new_lun)
        try:
            st_tm_mv = self._move_lun(path, tmp_path)
            st_nw_mv = self._move_lun(new_path, path)
            st_del_old = self._destroy_lun(tmp_path)
        except Exception as e:
            if st_tm_mv is None:
                msg = _("Failure staging lun %s to tmp.")
                raise exception.VolumeBackendAPIException(data=msg % (seg[-1]))
            else:
                if st_nw_mv is None:
                    self._move_lun(tmp_path, path)
                    msg = _("Failure moving new cloned lun to %s.")
                    raise exception.VolumeBackendAPIException(
                        data=msg % (seg[-1]))
                elif st_del_old is None:
                    LOG.error(_("Failure deleting staged tmp lun %s."),
                              tmp_lun)
                else:
                    LOG.error(_("Unknown exception in"
                                " post clone resize lun %s."), seg[-1])
                    LOG.error(_("Exception details: %s") % (e.__str__()))

    def _get_lun_block_count(self, path):
        """Gets block counts for the lun."""
        LOG.debug("Getting lun block count.")
        block_count = 0
        lun_infos = self._get_lun_by_args(path=path)
        if not lun_infos:
            seg = path.split('/')
            msg = _('Failure getting lun info for %s.')
            raise exception.VolumeBackendAPIException(data=msg % seg[-1])
        lun_info = lun_infos[-1]
        bs = int(lun_info.get_child_content('block-size'))
        ls = int(lun_info.get_child_content('size'))
        block_count = ls / bs
        return block_count


class NetAppDirectCmodeISCSIDriver(NetAppDirectISCSIDriver):
    """NetApp C-mode iSCSI volume driver."""

    DEFAULT_VS = 'openstack'

    def __init__(self, *args, **kwargs):
        super(NetAppDirectCmodeISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_cluster_opts)

    def _do_custom_setup(self):
        """Does custom setup for ontap cluster."""
        self.vserver = self.configuration.netapp_vserver
        self.vserver = self.vserver if self.vserver else self.DEFAULT_VS
        # We set vserver in client permanently.
        # To use tunneling enable_tunneling while invoking api
        self.client.set_vserver(self.vserver)
        # Default values to run first api
        self.client.set_api_version(1, 15)
        (major, minor) = self._get_ontapi_version()
        self.client.set_api_version(major, minor)
        self.ssc_vols = None
        self.stale_vols = set()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        ssc_utils.check_ssc_api_permissions(self.client)
        super(NetAppDirectCmodeISCSIDriver, self).check_for_setup_error()

    def create_lun(self, volume_name, lun_name, size,
                   metadata, qos_policy_group=None):
        """Creates a LUN, handling ONTAP differences as needed."""

        super(NetAppDirectCmodeISCSIDriver, self).create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group)

        self._update_stale_vols(
            volume=ssc_utils.NetAppVolume(volume_name, self.vserver))

    def _get_target_details(self):
        """Gets the target portal details."""
        iscsi_if_iter = NaElement('iscsi-interface-get-iter')
        result = self.client.invoke_successfully(iscsi_if_iter, True)
        tgt_list = []
        if result.get_child_content('num-records')\
                and int(result.get_child_content('num-records')) >= 1:
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

    def _get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        iscsi_service_iter = NaElement('iscsi-service-get-iter')
        result = self.client.invoke_successfully(iscsi_service_iter, True)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            iscsi_service = attr_list.get_child_by_name('iscsi-service-info')
            return iscsi_service.get_child_content('node-name')
        LOG.debug('No iscsi service found for vserver %s' % (self.vserver))
        return None

    def _create_lun_handle(self, metadata):
        """Returns lun handle based on filer type."""
        return '%s:%s' % (self.vserver, metadata['Path'])

    def _get_lun_list(self):
        """Gets the list of luns on filer.

        Gets the luns from cluster with vserver.
        """

        tag = None
        while True:
            api = NaElement('lun-get-iter')
            api.add_new_child('max-records', '100')
            if tag:
                api.add_new_child('tag', tag, True)
            lun_info = NaElement('lun-info')
            lun_info.add_new_child('vserver', self.vserver)
            query = NaElement('query')
            query.add_child_elem(lun_info)
            api.add_child_elem(query)
            result = self.client.invoke_successfully(api)
            if result.get_child_by_name('num-records') and\
                    int(result.get_child_content('num-records')) >= 1:
                attr_list = result.get_child_by_name('attributes-list')
                self._extract_and_populate_luns(attr_list.get_children())
            tag = result.get_child_content('next-tag')
            if tag is None:
                break

    def _find_mapped_lun_igroup(self, path, initiator, os=None):
        """Find the igroup for mapped lun with initiator."""
        initiator_igroups = self._get_igroup_by_initiator(initiator=initiator)
        lun_maps = self._get_lun_map(path)
        if initiator_igroups and lun_maps:
            for igroup in initiator_igroups:
                igroup_name = igroup['initiator-group-name']
                if igroup_name.startswith(self.IGROUP_PREFIX):
                    for lun_map in lun_maps:
                        if lun_map['initiator-group'] == igroup_name:
                            return (igroup_name, lun_map['lun-id'])
        return (None, None)

    def _get_lun_map(self, path):
        """Gets the lun map by lun path."""
        tag = None
        map_list = []
        while True:
            lun_map_iter = NaElement('lun-map-get-iter')
            lun_map_iter.add_new_child('max-records', '100')
            if tag:
                lun_map_iter.add_new_child('tag', tag, True)
            query = NaElement('query')
            lun_map_iter.add_child_elem(query)
            query.add_node_with_children('lun-map-info', **{'path': path})
            result = self.client.invoke_successfully(lun_map_iter, True)
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

    def _get_igroup_by_initiator(self, initiator):
        """Get igroups by initiator."""
        tag = None
        igroup_list = []
        while True:
            igroup_iter = NaElement('igroup-get-iter')
            igroup_iter.add_new_child('max-records', '100')
            if tag:
                igroup_iter.add_new_child('tag', tag, True)
            query = NaElement('query')
            igroup_iter.add_child_elem(query)
            igroup_info = NaElement('initiator-group-info')
            query.add_child_elem(igroup_info)
            igroup_info.add_new_child('vserver', self.vserver)
            initiators = NaElement('initiators')
            igroup_info.add_child_elem(initiators)
            initiators.add_node_with_children('initiator-info',
                                              **{'initiator-name': initiator})
            des_attrs = NaElement('desired-attributes')
            des_ig_info = NaElement('initiator-group-info')
            des_attrs.add_child_elem(des_ig_info)
            des_ig_info.add_node_with_children('initiators',
                                               **{'initiator-info': None})
            des_ig_info.add_new_child('vserver', None)
            des_ig_info.add_new_child('initiator-group-name', None)
            des_ig_info.add_new_child('initiator-group-type', None)
            des_ig_info.add_new_child('initiator-group-os-type', None)
            igroup_iter.add_child_elem(des_attrs)
            result = self.client.invoke_successfully(igroup_iter, False)
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

    def _clone_lun(self, name, new_name, space_reserved='true',
                   src_block=0, dest_block=0, block_count=0):
        """Clone LUN with the given handle to the new name."""
        metadata = self._get_lun_attr(name, 'metadata')
        volume = metadata['Volume']
        # zAPI can only handle 2^24 blocks per range
        bc_limit = 2 ** 24  # 8GB
        # zAPI can only handle 32 block ranges per call
        br_limit = 32
        z_limit = br_limit * bc_limit  # 256 GB
        z_calls = int(math.ceil(block_count / float(z_limit)))
        zbc = block_count
        if z_calls == 0:
            z_calls = 1
        for call in range(0, z_calls):
            if zbc > z_limit:
                block_count = z_limit
                zbc -= z_limit
            else:
                block_count = zbc
            clone_create = NaElement.create_node_with_children(
                'clone-create',
                **{'volume': volume, 'source-path': name,
                   'destination-path': new_name,
                   'space-reserve': space_reserved})
            if block_count > 0:
                block_ranges = NaElement("block-ranges")
                segments = int(math.ceil(block_count / float(bc_limit)))
                bc = block_count
                for segment in range(0, segments):
                    if bc > bc_limit:
                        block_count = bc_limit
                        bc -= bc_limit
                    else:
                        block_count = bc
                    block_range = NaElement.create_node_with_children(
                        'block-range',
                        **{'source-block-number': str(src_block),
                           'destination-block-number': str(dest_block),
                           'block-count': str(block_count)})
                    block_ranges.add_child_elem(block_range)
                    src_block += int(block_count)
                    dest_block += int(block_count)
                clone_create.add_child_elem(block_ranges)
            self.client.invoke_successfully(clone_create, True)
        LOG.debug("Cloned LUN with new name %s" % new_name)
        lun = self._get_lun_by_args(vserver=self.vserver, path='/vol/%s/%s'
                                    % (volume, new_name))
        if len(lun) == 0:
            msg = _("No cloned lun named %s found on the filer")
            raise exception.VolumeBackendAPIException(data=msg % (new_name))
        clone_meta = self._create_lun_meta(lun[0])
        self._add_lun_to_table(NetAppLun('%s:%s' % (clone_meta['Vserver'],
                                                    clone_meta['Path']),
                                         new_name,
                                         lun[0].get_child_content('size'),
                                         clone_meta))
        self._update_stale_vols(
            volume=ssc_utils.NetAppVolume(volume, self.vserver))

    def _get_lun_by_args(self, **args):
        """Retrieves lun with specified args."""
        lun_iter = NaElement('lun-get-iter')
        lun_iter.add_new_child('max-records', '100')
        query = NaElement('query')
        lun_iter.add_child_elem(query)
        query.add_node_with_children('lun-info', **args)
        luns = self.client.invoke_successfully(lun_iter)
        attr_list = luns.get_child_by_name('attributes-list')
        return attr_list.get_children()

    def _create_lun_meta(self, lun):
        """Creates lun metadata dictionary."""
        self._is_naelement(lun)
        meta_dict = {}
        meta_dict['Vserver'] = lun.get_child_content('vserver')
        meta_dict['Volume'] = lun.get_child_content('volume')
        meta_dict['Qtree'] = lun.get_child_content('qtree')
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = \
            lun.get_child_content('is-space-reservation-enabled')
        return meta_dict

    def _configure_tunneling(self, do_tunneling=False):
        """Configures tunneling for ontap cluster."""
        if do_tunneling:
            self.client.set_vserver(self.vserver)
        else:
            self.client.set_vserver(None)

    def _update_volume_stats(self):
        """Retrieve stats info from vserver."""

        sync = True if self.ssc_vols is None else False
        ssc_utils.refresh_cluster_ssc(self, self.client,
                                      self.vserver, synchronous=sync)

        LOG.debug('Updating volume stats')
        data = {}
        netapp_backend = 'NetApp_iSCSI_Cluster_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or netapp_backend
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'iSCSI'
        data['pools'] = self._get_pool_stats()

        na_utils.provide_ems(self, self.client, data, netapp_backend)
        self._stats = data

    def _get_pool_stats(self):
        """Retrieve pool (i.e. ONTAP volume) stats info from SSC volumes."""

        pools = []
        if not self.ssc_vols:
            return pools

        for vol in self.ssc_vols['all']:
            pool = dict()
            pool['pool_name'] = vol.id['name']
            pool['QoS_support'] = False
            pool['reserved_percentage'] = 0

            # convert sizes to GB and de-rate by NetApp multiplier
            total = float(vol.space['size_total_bytes'])
            total /= self.configuration.netapp_size_multiplier
            total /= units.Gi
            pool['total_capacity_gb'] = round_down(total, '0.01')

            free = float(vol.space['size_avl_bytes'])
            free /= self.configuration.netapp_size_multiplier
            free /= units.Gi
            pool['free_capacity_gb'] = round_down(free, '0.01')

            pool['netapp_raid_type'] = vol.aggr['raid_type']
            pool['netapp_disk_type'] = vol.aggr['disk_type']

            mirrored = vol in self.ssc_vols['mirrored']
            pool['netapp_mirrored'] = six.text_type(mirrored).lower()
            pool['netapp_unmirrored'] = six.text_type(not mirrored).lower()

            dedup = vol in self.ssc_vols['dedup']
            pool['netapp_dedup'] = six.text_type(dedup).lower()
            pool['netapp_nodedup'] = six.text_type(not dedup).lower()

            compression = vol in self.ssc_vols['compression']
            pool['netapp_compression'] = six.text_type(compression).lower()
            pool['netapp_nocompression'] = six.text_type(
                not compression).lower()

            thin = vol in self.ssc_vols['thin']
            pool['netapp_thin_provisioned'] = six.text_type(thin).lower()
            pool['netapp_thick_provisioned'] = six.text_type(not thin).lower()

            pools.append(pool)

        return pools

    @utils.synchronized('update_stale')
    def _update_stale_vols(self, volume=None, reset=False):
        """Populates stale vols with vol and returns set copy if reset."""
        if volume:
            self.stale_vols.add(volume)
        if reset:
            set_copy = copy.deepcopy(self.stale_vols)
            self.stale_vols.clear()
            return set_copy

    @utils.synchronized("refresh_ssc_vols")
    def refresh_ssc_vols(self, vols):
        """Refreshes ssc_vols with latest entries."""
        self.ssc_vols = vols

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        try:
            lun = self._get_lun_from_table(volume['name'])
        except exception.VolumeNotFound:
            lun = None
        netapp_vol = None
        if lun:
            netapp_vol = lun.get_metadata_property('Volume')
        super(NetAppDirectCmodeISCSIDriver, self).delete_volume(volume)
        if netapp_vol:
            self._update_stale_vols(
                volume=ssc_utils.NetAppVolume(netapp_vol, self.vserver))


class NetAppDirect7modeISCSIDriver(NetAppDirectISCSIDriver):
    """NetApp 7-mode iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirect7modeISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_7mode_opts)

    def _do_custom_setup(self):
        """Does custom setup depending on the type of filer."""
        self.vfiler = self.configuration.netapp_vfiler
        self.volume_list = self.configuration.netapp_volume_list
        if self.volume_list:
            self.volume_list = self.volume_list.split(',')
            self.volume_list = [el.strip() for el in self.volume_list]
        (major, minor) = self._get_ontapi_version()
        self.client.set_api_version(major, minor)
        if self.vfiler:
            self.client.set_vfiler(self.vfiler)
        self.vol_refresh_time = None
        self.vol_refresh_interval = 1800
        self.vol_refresh_running = False
        self.vol_refresh_voluntary = False
        self.root_volume_name = self._get_root_volume_name()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        api_version = self.client.get_api_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 9:
                msg = _("Unsupported ONTAP version."
                        " ONTAP version 7.3.1 and above is supported.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("Api version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)
        super(NetAppDirect7modeISCSIDriver, self).check_for_setup_error()

    def create_lun(self, volume_name, lun_name, size,
                   metadata, qos_policy_group=None):
        """Creates a LUN, handling ONTAP differences as needed."""

        super(NetAppDirect7modeISCSIDriver, self).create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group)

        self.vol_refresh_voluntary = True

    def _get_filer_volumes(self, volume=None):
        """Returns list of filer volumes in api format."""
        vol_request = NaElement('volume-list-info')
        if volume:
            vol_request.add_new_child('volume', volume)
        res = self.client.invoke_successfully(vol_request, True)
        volumes = res.get_child_by_name('volumes')
        if volumes:
            return volumes.get_children()
        return []

    def _get_root_volume_name(self):
        # switch to volume-get-root-name API when possible
        vols = self._get_filer_volumes()
        for vol in vols:
            volume_name = vol.get_child_content('name')
            if self._get_vol_option(volume_name, 'root') == 'true':
                return volume_name
        LOG.warn(_('Could not determine root volume name '
                   'on %s.') % self._get_owner())
        return None

    def _get_igroup_by_initiator(self, initiator):
        """Get igroups by initiator."""
        igroup_list = NaElement('igroup-list-info')
        result = self.client.invoke_successfully(igroup_list, True)
        igroups = []
        igs = result.get_child_by_name('initiator-groups')
        if igs:
            ig_infos = igs.get_children()
            if ig_infos:
                for info in ig_infos:
                    initiators = info.get_child_by_name('initiators')
                    init_infos = initiators.get_children()
                    if init_infos:
                        for init in init_infos:
                            if init.get_child_content('initiator-name')\
                                    == initiator:
                                d = dict()
                                d['initiator-group-os-type'] = \
                                    info.get_child_content(
                                        'initiator-group-os-type')
                                d['initiator-group-type'] = \
                                    info.get_child_content(
                                        'initiator-group-type')
                                d['initiator-group-name'] = \
                                    info.get_child_content(
                                        'initiator-group-name')
                                igroups.append(d)
        return igroups

    def _get_target_details(self):
        """Gets the target portal details."""
        iscsi_if_iter = NaElement('iscsi-portal-list-info')
        result = self.client.invoke_successfully(iscsi_if_iter, True)
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

    def _get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        iscsi_service_iter = NaElement('iscsi-node-get-name')
        result = self.client.invoke_successfully(iscsi_service_iter, True)
        return result.get_child_content('node-name')

    def _get_owner(self):
        if self.vfiler:
            owner = '%s:%s' % (self.configuration.netapp_server_hostname,
                               self.vfiler)
        else:
            owner = self.configuration.netapp_server_hostname
        return owner

    def _create_lun_handle(self, metadata):
        """Returns lun handle based on filer type."""
        owner = self._get_owner()
        return '%s:%s' % (owner, metadata['Path'])

    def _get_lun_list(self):
        """Gets the list of luns on filer."""
        lun_list = []
        if self.volume_list:
            for vol in self.volume_list:
                try:
                    luns = self._get_vol_luns(vol)
                    if luns:
                        lun_list.extend(luns)
                except NaApiError:
                    LOG.warn(_("Error finding luns for volume %s."
                               " Verify volume exists.") % (vol))
        else:
            luns = self._get_vol_luns(None)
            lun_list.extend(luns)
        self._extract_and_populate_luns(lun_list)

    def _get_vol_luns(self, vol_name):
        """Gets the luns for a volume."""
        api = NaElement('lun-list-info')
        if vol_name:
            api.add_new_child('volume-name', vol_name)
        result = self.client.invoke_successfully(api, True)
        luns = result.get_child_by_name('luns')
        return luns.get_children()

    def _find_mapped_lun_igroup(self, path, initiator, os=None):
        """Find the igroup for mapped lun with initiator."""
        lun_map_list = NaElement.create_node_with_children(
            'lun-map-list-info',
            **{'path': path})
        result = self.client.invoke_successfully(lun_map_list, True)
        igroups = result.get_child_by_name('initiator-groups')
        if igroups:
            igroup = None
            lun_id = None
            found = False
            igroup_infs = igroups.get_children()
            for ig in igroup_infs:
                initiators = ig.get_child_by_name('initiators')
                init_infs = initiators.get_children()
                for info in init_infs:
                    if info.get_child_content('initiator-name') == initiator:
                        found = True
                        igroup = ig.get_child_content('initiator-group-name')
                        lun_id = ig.get_child_content('lun-id')
                        break
                if found:
                    break
        return (igroup, lun_id)

    def _clone_lun(self, name, new_name, space_reserved='true',
                   src_block=0, dest_block=0, block_count=0):
        """Clone LUN with the given handle to the new name."""
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        (parent, splitter, name) = path.rpartition('/')
        clone_path = '%s/%s' % (parent, new_name)
        # zAPI can only handle 2^24 blocks per range
        bc_limit = 2 ** 24  # 8GB
        # zAPI can only handle 32 block ranges per call
        br_limit = 32
        z_limit = br_limit * bc_limit  # 256 GB
        z_calls = int(math.ceil(block_count / float(z_limit)))
        zbc = block_count
        if z_calls == 0:
            z_calls = 1
        for call in range(0, z_calls):
            if zbc > z_limit:
                block_count = z_limit
                zbc -= z_limit
            else:
                block_count = zbc
            clone_start = NaElement.create_node_with_children(
                'clone-start', **{'source-path': path,
                                  'destination-path': clone_path,
                                  'no-snap': 'true'})
            if block_count > 0:
                block_ranges = NaElement("block-ranges")
                # zAPI can only handle 2^24 block ranges
                bc_limit = 2 ** 24  # 8GB
                segments = int(math.ceil(block_count / float(bc_limit)))
                bc = block_count
                for segment in range(0, segments):
                    if bc > bc_limit:
                        block_count = bc_limit
                        bc -= bc_limit
                    else:
                        block_count = bc
                    block_range = NaElement.create_node_with_children(
                        'block-range',
                        **{'source-block-number': str(src_block),
                            'destination-block-number': str(dest_block),
                            'block-count': str(block_count)})
                    block_ranges.add_child_elem(block_range)
                    src_block += int(block_count)
                    dest_block += int(block_count)
                clone_start.add_child_elem(block_ranges)
            result = self.client.invoke_successfully(clone_start, True)
            clone_id_el = result.get_child_by_name('clone-id')
            cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
            vol_uuid = cl_id_info.get_child_content('volume-uuid')
            clone_id = cl_id_info.get_child_content('clone-op-id')
            if vol_uuid:
                self._check_clone_status(clone_id, vol_uuid, name, new_name)
        self.vol_refresh_voluntary = True
        luns = self._get_lun_by_args(path=clone_path)
        if luns:
            cloned_lun = luns[0]
            self._set_space_reserve(clone_path, space_reserved)
            clone_meta = self._create_lun_meta(cloned_lun)
            handle = self._create_lun_handle(clone_meta)
            self._add_lun_to_table(
                NetAppLun(handle, new_name,
                          cloned_lun.get_child_content('size'),
                          clone_meta))
        else:
            raise NaApiError('ENOLUNENTRY', 'No Lun entry found on the filer')

    def _set_space_reserve(self, path, enable):
        """Sets the space reserve info."""
        space_res = NaElement.create_node_with_children(
            'lun-set-space-reservation-info',
            **{'path': path, 'enable': enable})
        self.client.invoke_successfully(space_res, True)

    def _check_clone_status(self, clone_id, vol_uuid, name, new_name):
        """Checks for the job till completed."""
        clone_status = NaElement('clone-list-status')
        cl_id = NaElement('clone-id')
        clone_status.add_child_elem(cl_id)
        cl_id.add_node_with_children(
            'clone-id-info',
            **{'clone-op-id': clone_id, 'volume-uuid': vol_uuid})
        running = True
        clone_ops_info = None
        while running:
            result = self.client.invoke_successfully(clone_status, True)
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
                    raise NaApiError(
                        clone_ops_info.get_child_content('error'),
                        clone_ops_info.get_child_content('reason'))

    def _get_lun_by_args(self, **args):
        """Retrieves luns with specified args."""
        lun_info = NaElement.create_node_with_children('lun-list-info', **args)
        result = self.client.invoke_successfully(lun_info, True)
        luns = result.get_child_by_name('luns')
        return luns.get_children()

    def _create_lun_meta(self, lun):
        """Creates lun metadata dictionary."""
        self._is_naelement(lun)
        meta_dict = {}
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['Volume'] = lun.get_child_content('path').split('/')[2]
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = lun.get_child_content(
            'is-space-reservation-enabled')
        return meta_dict

    def _update_volume_stats(self):
        """Retrieve stats info from filer."""

        # ensure we get current data
        self.vol_refresh_voluntary = True
        self._refresh_volume_info()

        LOG.debug('Updating volume stats')
        data = {}
        netapp_backend = 'NetApp_iSCSI_7mode_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or netapp_backend
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'iSCSI'
        data['pools'] = self._get_pool_stats()

        na_utils.provide_ems(self, self.client, data, netapp_backend,
                             server_type='7mode')
        self._stats = data

    def _get_pool_stats(self):
        """Retrieve pool (i.e. ONTAP volume) stats info from volumes."""

        pools = []
        if not self.vols:
            return pools

        for vol in self.vols:

            # omit volumes not specified in the config
            volume_name = vol.get_child_content('name')
            if self.volume_list and volume_name not in self.volume_list:
                continue

            # omit root volume
            if volume_name == self.root_volume_name:
                continue

            # ensure good volume state
            state = vol.get_child_content('state')
            inconsistent = vol.get_child_content('is-inconsistent')
            invalid = vol.get_child_content('is-invalid')
            if (state != 'online' or
                    inconsistent != 'false' or
                    invalid != 'false'):
                continue

            pool = dict()
            pool['pool_name'] = volume_name
            pool['QoS_support'] = False
            pool['reserved_percentage'] = 0

            # convert sizes to GB and de-rate by NetApp multiplier
            total = float(vol.get_child_content('size-total') or 0)
            total /= self.configuration.netapp_size_multiplier
            total /= units.Gi
            pool['total_capacity_gb'] = round_down(total, '0.01')

            free = float(vol.get_child_content('size-available') or 0)
            free /= self.configuration.netapp_size_multiplier
            free /= units.Gi
            pool['free_capacity_gb'] = round_down(free, '0.01')

            pools.append(pool)

        return pools

    def _get_lun_block_count(self, path):
        """Gets block counts for the lun."""
        bs = super(
            NetAppDirect7modeISCSIDriver, self)._get_lun_block_count(path)
        api_version = self.client.get_api_version()
        if api_version:
            major = api_version[0]
            minor = api_version[1]
            if major == 1 and minor < 15:
                bs = bs - 1
        return bs

    def _refresh_volume_info(self):
        """Saves the volume information for the filer."""

        if (self.vol_refresh_time is None or self.vol_refresh_voluntary or
                timeutils.is_newer_than(self.vol_refresh_time,
                                        self.vol_refresh_interval)):
            try:
                job_set = set_safe_attr(self, 'vol_refresh_running', True)
                if not job_set:
                    LOG.warn(
                        _("Volume refresh job already running. Returning..."))
                    return
                self.vol_refresh_voluntary = False
                self.vols = self._get_filer_volumes()
                self.vol_refresh_time = timeutils.utcnow()
            except Exception as e:
                LOG.warn(_("Error refreshing volume info. Message: %s"),
                         six.text_type(e))
            finally:
                set_safe_attr(self, 'vol_refresh_running', False)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        super(NetAppDirect7modeISCSIDriver, self).delete_volume(volume)
        self.vol_refresh_voluntary = True
