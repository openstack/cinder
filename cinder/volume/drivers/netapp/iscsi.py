# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack LLC.
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

import sys
import time
import uuid

from cinder import exception
from cinder.openstack.common import log as logging
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
from cinder.volume.drivers.netapp.utils import provide_ems
from cinder.volume.drivers.netapp.utils import validate_instantiation
from cinder.volume import volume_types
from oslo.config import cfg


LOG = logging.getLogger(__name__)


CONF = cfg.CONF
CONF.register_opts(netapp_connection_opts)
CONF.register_opts(netapp_transport_opts)
CONF.register_opts(netapp_basicauth_opts)
CONF.register_opts(netapp_cluster_opts)
CONF.register_opts(netapp_7mode_opts)
CONF.register_opts(netapp_provisioning_opts)


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
        LOG.debug(_('Using NetApp filer: %s') % host_filer)
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
                raise exception.InvalidInput(data=msg)

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
        LOG.debug(_("Success getting LUN list from server"))

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        default_size = '104857600'  # 100 MB
        gigabytes = 1073741824L  # 2^30
        name = volume['name']
        if int(volume['size']) == 0:
            size = default_size
        else:
            size = str(int(volume['size']) * gigabytes)
        metadata = {}
        metadata['OsType'] = 'linux'
        metadata['SpaceReserved'] = 'true'
        self._create_lun_on_eligible_vol(name, size, metadata)
        LOG.debug(_("Created LUN with name %s") % name)
        handle = self._create_lun_handle(metadata)
        self._add_lun_to_table(NetAppLun(handle, name, size, metadata))

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        if not metadata:
            msg = _("No entry in LUN table for volume/snapshot %(name)s.")
            msg_fmt = {'name': name}
            LOG.warn(msg % msg_fmt)
            return
        lun_destroy = NaElement.create_node_with_children(
            'lun-destroy',
            **{'path': metadata['Path'],
            'force': 'true'})
        self.client.invoke_successfully(lun_destroy, True)
        LOG.debug(_("Destroyed LUN %s") % name)
        self.lun_table.pop(name)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        handle = self._get_lun_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        handle = self._get_lun_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume.

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
        msg = _("Succesfully fetched target details for LUN %(name)s and "
                "initiator %(initiator_name)s")
        msg_fmt = {'name': name, 'initiator_name': initiator_name}
        LOG.debug(msg % msg_fmt)

        if not target_details_list:
            msg = _('Failed to get LUN target details for the LUN %s')
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
        lun = self.lun_table[vol_name]
        self._clone_lun(lun.name, snapshot_name, 'false')

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        self.delete_volume(snapshot)
        LOG.debug(_("Snapshot %s deletion successful") % snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for creating a new volume from a snapshot.

        Many would call this "cloning" and in fact we use cloning to implement
        this feature.
        """
        vol_size = volume['size']
        snap_size = snapshot['volume_size']
        if vol_size != snap_size:
            msg = _('Cannot create volume of size %(vol_size)s from '
                    'snapshot of size %(snap_size)s')
            msg_fmt = {'vol_size': vol_size, 'snap_size': snap_size}
            raise exception.VolumeBackendAPIException(data=msg % msg_fmt)
        snapshot_name = snapshot['name']
        new_name = volume['name']
        self._clone_lun(snapshot_name, new_name, 'true')

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given intiator can no
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

    def _create_lun_on_eligible_vol(self, name, size, metadata):
        """Creates an actual lun on filer."""
        req_size = float(size) *\
            float(self.configuration.netapp_size_multiplier)
        volume = self._get_avl_volume_by_size(req_size)
        if not volume:
            msg = _('Failed to get vol with required size for volume: %s')
            raise exception.VolumeBackendAPIException(data=msg % name)
        path = '/vol/%s/%s' % (volume['name'], name)
        lun_create = NaElement.create_node_with_children(
            'lun-create-by-size',
            **{'path': path, 'size': size,
            'ostype': metadata['OsType'],
            'space-reservation-enabled':
            metadata['SpaceReserved']})
        self.client.invoke_successfully(lun_create, True)
        metadata['Path'] = '/vol/%s/%s' % (volume['name'], name)
        metadata['Volume'] = volume['name']
        metadata['Qtree'] = None

    def _get_avl_volume_by_size(self, size):
        """Get the available volume by size."""
        raise NotImplementedError()

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
            **{'path': path,
            'initiator-group': igroup_name})
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
        """Creates igoup with specified args."""
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

    def _get_qos_type(self, volume):
        """Get the storage service type for a volume."""
        type_id = volume['volume_type_id']
        if not type_id:
            return None
        volume_type = volume_types.get_volume_type(None, type_id)
        if not volume_type:
            return None
        return volume_type['name']

    def _add_lun_to_table(self, lun):
        """Adds LUN to cache table."""
        if not isinstance(lun, NetAppLun):
            msg = _("Object is not a NetApp LUN.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.lun_table[lun.name] = lun

    def _clone_lun(self, name, new_name, space_reserved):
        """Clone LUN with the given name to the new name."""
        raise NotImplementedError()

    def _get_lun_by_args(self, **args):
        """Retrives lun with specified args."""
        raise NotImplementedError()

    def _get_lun_attr(self, name, attr):
        """Get the attributes for a LUN from our cache table."""
        if not name in self.lun_table or not hasattr(
                self.lun_table[name], attr):
            LOG.warn(_("Could not find attribute for LUN named %s") % name)
            return None
        return getattr(self.lun_table[name], attr)

    def _create_lun_meta(self, lun):
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_size = volume['size']
        src_vol = self.lun_table[src_vref['name']]
        src_vol_size = src_vref['size']
        if vol_size != src_vol_size:
            msg = _('Cannot clone volume of size %(vol_size)s from '
                    'src volume of size %(src_vol_size)s')
            msg_fmt = {'vol_size': vol_size, 'src_vol_size': src_vol_size}
            raise exception.VolumeBackendAPIException(data=msg % msg_fmt)
        new_name = volume['name']
        self._clone_lun(src_vol.name, new_name, 'true')

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        raise NotImplementedError()


class NetAppDirectCmodeISCSIDriver(NetAppDirectISCSIDriver):
    """NetApp C-mode iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirectCmodeISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_cluster_opts)

    def _do_custom_setup(self):
        """Does custom setup for ontap cluster."""
        self.vserver = self.configuration.netapp_vserver
        # We set vserver in client permanently.
        # To use tunneling enable_tunneling while invoking api
        self.client.set_vserver(self.vserver)
        # Default values to run first api
        self.client.set_api_version(1, 15)
        (major, minor) = self._get_ontapi_version()
        self.client.set_api_version(major, minor)

    def _get_avl_volume_by_size(self, size):
        """Get the available volume by size."""
        tag = None
        while True:
            vol_request = self._create_avl_vol_request(self.vserver, tag)
            res = self.client.invoke_successfully(vol_request)
            tag = res.get_child_content('next-tag')
            attr_list = res.get_child_by_name('attributes-list')
            vols = attr_list.get_children()
            for vol in vols:
                vol_space = vol.get_child_by_name('volume-space-attributes')
                avl_size = vol_space.get_child_content('size-available')
                if float(avl_size) >= float(size):
                    avl_vol = dict()
                    vol_id = vol.get_child_by_name('volume-id-attributes')
                    avl_vol['name'] = vol_id.get_child_content('name')
                    avl_vol['vserver'] = vol_id.get_child_content(
                        'owning-vserver-name')
                    avl_vol['size-available'] = avl_size
                    return avl_vol
            if tag is None:
                break
        return None

    def _create_avl_vol_request(self, vserver, tag=None):
        vol_get_iter = NaElement('volume-get-iter')
        vol_get_iter.add_new_child('max-records', '100')
        if tag:
            vol_get_iter.add_new_child('tag', tag, True)
        query = NaElement('query')
        vol_get_iter.add_child_elem(query)
        vol_attrs = NaElement('volume-attributes')
        query.add_child_elem(vol_attrs)
        if vserver:
            vol_attrs.add_node_with_children(
                'volume-id-attributes',
                **{"owning-vserver-name": vserver})
        vol_attrs.add_node_with_children(
            'volume-state-attributes',
            **{"is-vserver-root": "false", "state": "online"})
        desired_attrs = NaElement('desired-attributes')
        vol_get_iter.add_child_elem(desired_attrs)
        des_vol_attrs = NaElement('volume-attributes')
        desired_attrs.add_child_elem(des_vol_attrs)
        des_vol_attrs.add_node_with_children(
            'volume-id-attributes',
            **{"name": None, "owning-vserver-name": None})
        des_vol_attrs.add_node_with_children(
            'volume-space-attributes',
            **{"size-available": None})
        des_vol_attrs.add_node_with_children('volume-state-attributes',
                                             **{"is-cluster-volume": None,
                                             "is-vserver-root": None,
                                             "state": None})
        return vol_get_iter

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
        LOG.debug(_('No iscsi service found for vserver %s') % (self.vserver))
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

    def _clone_lun(self, name, new_name, space_reserved):
        """Clone LUN with the given handle to the new name."""
        metadata = self._get_lun_attr(name, 'metadata')
        volume = metadata['Volume']
        clone_create = NaElement.create_node_with_children(
            'clone-create',
            **{'volume': volume, 'source-path': name,
            'destination-path': new_name,
            'space-reserve': space_reserved})
        self.client.invoke_successfully(clone_create, True)
        LOG.debug(_("Cloned LUN with new name %s") % new_name)
        lun = self._get_lun_by_args(vserver=self.vserver, path='/vol/%s/%s'
                                    % (volume, new_name))
        if len(lun) == 0:
            msg = _("No clonned lun named %s found on the filer")
            raise exception.VolumeBackendAPIException(data=msg % (new_name))
        clone_meta = self._create_lun_meta(lun[0])
        self._add_lun_to_table(NetAppLun('%s:%s' % (clone_meta['Vserver'],
                                                    clone_meta['Path']),
                                         new_name,
                                         lun[0].get_child_content('size'),
                                         clone_meta))

    def _get_lun_by_args(self, **args):
        """Retrives lun with specified args."""
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
        self._is_naelement(lun)
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

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug(_("Updating volume status"))
        data = {}
        netapp_backend = 'NetApp_iSCSI_Cluster_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = (
            backend_name or netapp_backend)
        data["vendor_name"] = 'NetApp'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'iSCSI'

        data['total_capacity_gb'] = 'infinite'
        data['free_capacity_gb'] = 'infinite'
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        provide_ems(self, self.client, data, netapp_backend)
        self._stats = data


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
        if self.vfiler:
            (major, minor) = self._get_ontapi_version()
            self.client.set_api_version(major, minor)
            self.client.set_vfiler(self.vfiler)

    def _get_avl_volume_by_size(self, size):
        """Get the available volume by size."""
        vol_request = NaElement('volume-list-info')
        res = self.client.invoke_successfully(vol_request, True)
        volumes = res.get_child_by_name('volumes')
        vols = volumes.get_children()
        for vol in vols:
            avl_size = vol.get_child_content('size-available')
            state = vol.get_child_content('state')
            if float(avl_size) >= float(size) and state == 'online':
                avl_vol = dict()
                avl_vol['name'] = vol.get_child_content('name')
                avl_vol['block-type'] = vol.get_child_content('block-type')
                avl_vol['type'] = vol.get_child_content('type')
                avl_vol['size-available'] = avl_size
                if self.volume_list:
                    if avl_vol['name'] in self.volume_list:
                        return avl_vol
                else:
                    if self._check_vol_not_root(avl_vol):
                        return avl_vol
        return None

    def _check_vol_not_root(self, vol):
        """Checks if a volume is not root."""
        vol_options = NaElement.create_node_with_children(
            'volume-options-list-info', **{'volume': vol['name']})
        result = self.client.invoke_successfully(vol_options, True)
        options = result.get_child_by_name('options')
        ops = options.get_children()
        for op in ops:
            if op.get_child_content('name') == 'root' and\
                    op.get_child_content('value') == 'true':
                return False
        return True

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

    def _create_lun_handle(self, metadata):
        """Returns lun handle based on filer type."""
        if self.vfiler:
            owner = '%s:%s' % (self.configuration.netapp_server_hostname,
                               self.vfiler)
        else:
            owner = self.configuration.netapp_server_hostname
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

    def _clone_lun(self, name, new_name, space_reserved):
        """Clone LUN with the given handle to the new name."""
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        (parent, splitter, name) = path.rpartition('/')
        clone_path = '%s/%s' % (parent, new_name)
        clone_start = NaElement.create_node_with_children(
            'clone-start',
            **{'source-path': path, 'destination-path': clone_path,
            'no-snap': 'true'})
        result = self.client.invoke_successfully(clone_start, True)
        clone_id_el = result.get_child_by_name('clone-id')
        cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
        vol_uuid = cl_id_info.get_child_content('volume-uuid')
        clone_id = cl_id_info.get_child_content('clone-op-id')
        if vol_uuid:
            self._check_clone_status(clone_id, vol_uuid, name, new_name)
        cloned_lun = self._get_lun_by_args(path=clone_path)
        if cloned_lun:
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
                    LOG.debug(_("Clone operation with src %(name)s"
                                " and dest %(new_name)s completed") % fmt)
                else:
                    LOG.debug(_("Clone operation with src %(name)s"
                                " and dest %(new_name)s failed") % fmt)
                    raise NaApiError(
                        clone_ops_info.get_child_content('error'),
                        clone_ops_info.get_child_content('reason'))

    def _get_lun_by_args(self, **args):
        """Retrives lun with specified args."""
        lun_info = NaElement.create_node_with_children('lun-list-info', **args)
        result = self.client.invoke_successfully(lun_info, True)
        luns = result.get_child_by_name('luns')
        if luns:
            infos = luns.get_children()
            if infos:
                return infos[0]
        return None

    def _create_lun_meta(self, lun):
        """Creates lun metadata dictionary."""
        self._is_naelement(lun)
        meta_dict = {}
        self._is_naelement(lun)
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = lun.get_child_content(
            'is-space-reservation-enabled')
        return meta_dict

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug(_("Updating volume status"))
        data = {}
        netapp_backend = 'NetApp_iSCSI_7mode_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = (
            backend_name or 'NetApp_iSCSI_7mode_direct')
        data["vendor_name"] = 'NetApp'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'iSCSI'

        data['total_capacity_gb'] = 'infinite'
        data['free_capacity_gb'] = 'infinite'
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        provide_ems(self, self.client, data, netapp_backend,
                    server_type="7mode")
        self._stats = data
