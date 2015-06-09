# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2014 Jeff Applewhite.  All rights reserved.
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
"""
Volume driver library for NetApp 7/C-mode block storage systems.
"""

import math
import sys
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume.drivers.netapp.dataontap.client import api as na_api
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils


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
        LOG.debug("No metadata property %(prop)s defined for the LUN %(name)s",
                  {'prop': prop, 'name': name})

    def __str__(self, *args, **kwargs):
        return 'NetApp LUN [handle:%s, name:%s, size:%s, metadata:%s]' % (
               self.handle, self.name, self.size, self.metadata)


class NetAppBlockStorageLibrary(object):
    """NetApp block storage library for Data ONTAP."""

    # do not increment this as it may be used in volume type definitions
    VERSION = "1.0.0"
    REQUIRED_FLAGS = ['netapp_login', 'netapp_password',
                      'netapp_server_hostname']
    ALLOWED_LUN_OS_TYPES = ['linux', 'aix', 'hpux', 'image', 'windows',
                            'windows_2008', 'windows_gpt', 'solaris',
                            'solaris_efi', 'netware', 'openvms', 'hyper_v']
    ALLOWED_IGROUP_HOST_TYPES = ['linux', 'aix', 'hpux', 'windows', 'solaris',
                                 'netware', 'default', 'vmware', 'openvms',
                                 'xen', 'hyper_v']
    DEFAULT_LUN_OS = 'linux'
    DEFAULT_HOST_TYPE = 'linux'

    def __init__(self, driver_name, driver_protocol, **kwargs):

        na_utils.validate_instantiation(**kwargs)

        self.driver_name = driver_name
        self.driver_protocol = driver_protocol
        self.zapi_client = None
        self._stats = {}
        self.lun_table = {}
        self.lun_ostype = None
        self.host_type = None
        self.lookup_service = fczm_utils.create_lookup_service()
        self.app_version = kwargs.get("app_version", "unknown")

        self.configuration = kwargs['configuration']
        self.configuration.append_config_values(na_opts.netapp_connection_opts)
        self.configuration.append_config_values(na_opts.netapp_basicauth_opts)
        self.configuration.append_config_values(na_opts.netapp_transport_opts)
        self.configuration.append_config_values(
            na_opts.netapp_provisioning_opts)
        self.configuration.append_config_values(na_opts.netapp_san_opts)

    def do_setup(self, context):
        na_utils.check_flags(self.REQUIRED_FLAGS, self.configuration)
        self.lun_ostype = (self.configuration.netapp_lun_ostype
                           or self.DEFAULT_LUN_OS)
        self.host_type = (self.configuration.netapp_host_type
                          or self.DEFAULT_HOST_TYPE)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.

        Discovers the LUNs on the NetApp server.
        """
        if self.lun_ostype not in self.ALLOWED_LUN_OS_TYPES:
            msg = _("Invalid value for NetApp configuration"
                    " option netapp_lun_ostype.")
            LOG.error(msg)
            raise exception.NetAppDriverException(msg)
        if self.host_type not in self.ALLOWED_IGROUP_HOST_TYPES:
            msg = _("Invalid value for NetApp configuration"
                    " option netapp_host_type.")
            LOG.error(msg)
            raise exception.NetAppDriverException(msg)
        lun_list = self.zapi_client.get_lun_list()
        self._extract_and_populate_luns(lun_list)
        LOG.debug("Success getting list of LUNs from server.")

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata') or dict()
        return metadata.get('Volume', None)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume (Data ONTAP LUN)."""

        LOG.debug('create_volume on %s', volume['host'])

        # get Data ONTAP volume name as pool name
        pool_name = volume_utils.extract_host(volume['host'], level='pool')

        if pool_name is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        extra_specs = na_utils.get_volume_extra_specs(volume)

        lun_name = volume['name']

        size = int(volume['size']) * units.Gi

        metadata = {'OsType': self.lun_ostype,
                    'SpaceReserved': 'true',
                    'Path': '/vol/%s/%s' % (pool_name, lun_name)}

        qos_policy_group_info = self._setup_qos_for_volume(volume, extra_specs)
        qos_policy_group_name = (
            na_utils.get_qos_policy_group_name_from_info(
                qos_policy_group_info))

        try:
            self._create_lun(pool_name, lun_name, size, metadata,
                             qos_policy_group_name)
        except Exception:
            LOG.exception(_LE("Exception creating LUN %(name)s in pool "
                              "%(pool)s."),
                          {'name': lun_name, 'pool': pool_name})
            self._mark_qos_policy_group_for_deletion(qos_policy_group_info)
            msg = _("Volume %s could not be created.")
            raise exception.VolumeBackendAPIException(data=msg % (
                volume['name']))
        LOG.debug('Created LUN with name %(name)s and QoS info %(qos)s',
                  {'name': lun_name, 'qos': qos_policy_group_info})

        metadata['Path'] = '/vol/%s/%s' % (pool_name, lun_name)
        metadata['Volume'] = pool_name
        metadata['Qtree'] = None

        handle = self._create_lun_handle(metadata)
        self._add_lun_to_table(NetAppLun(handle, lun_name, size, metadata))

    def _setup_qos_for_volume(self, volume, extra_specs):
        return None

    def _mark_qos_policy_group_for_deletion(self, qos_policy_group_info):
        return

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        if not metadata:
            LOG.warning(_LW("No entry in LUN table for volume/snapshot"
                            " %(name)s."), {'name': name})
            return
        self.zapi_client.destroy_lun(metadata['Path'])
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
        """Driver entry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """

        pass

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.

        This driver implements snapshots by using efficient single-file
        (LUN) cloning.
        """

        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        lun = self._get_lun_from_table(vol_name)
        self._clone_lun(lun.name, snapshot_name, space_reserved='false')

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        self.delete_volume(snapshot)
        LOG.debug("Snapshot %s deletion successful", snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        source = {'name': snapshot['name'], 'size': snapshot['volume_size']}
        return self._clone_source_to_destination(source, volume)

    def create_cloned_volume(self, volume, src_vref):
        src_lun = self._get_lun_from_table(src_vref['name'])
        source = {'name': src_lun.name, 'size': src_vref['size']}
        return self._clone_source_to_destination(source, volume)

    def _clone_source_to_destination(self, source, destination_volume):
        source_size = source['size']
        destination_size = destination_volume['size']

        source_name = source['name']
        destination_name = destination_volume['name']

        extra_specs = na_utils.get_volume_extra_specs(destination_volume)

        qos_policy_group_info = self._setup_qos_for_volume(
            destination_volume, extra_specs)
        qos_policy_group_name = (
            na_utils.get_qos_policy_group_name_from_info(
                qos_policy_group_info))

        try:
            self._clone_lun(source_name, destination_name,
                            space_reserved='true',
                            qos_policy_group_name=qos_policy_group_name)

            if destination_size != source_size:

                try:
                    self.extend_volume(
                        destination_volume, destination_size,
                        qos_policy_group_name=qos_policy_group_name)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error(
                            _LE("Resizing %s failed. Cleaning volume."),
                            destination_volume['id'])
                        self.delete_volume(destination_volume)

        except Exception:
            LOG.exception(_LE("Exception cloning volume %(name)s from source "
                          "volume %(source)s."),
                          {'name': destination_name, 'source': source_name})

            self._mark_qos_policy_group_for_deletion(qos_policy_group_info)

            msg = _("Volume %s could not be created from source volume.")
            raise exception.VolumeBackendAPIException(
                data=msg % destination_name)

    def _create_lun(self, volume_name, lun_name, size,
                    metadata, qos_policy_group_name=None):
        """Creates a LUN, handling Data ONTAP differences as needed."""
        raise NotImplementedError()

    def _create_lun_handle(self, metadata):
        """Returns LUN handle based on filer type."""
        raise NotImplementedError()

    def _extract_lun_info(self, lun):
        """Extracts the LUNs from API and populates the LUN table."""

        meta_dict = self._create_lun_meta(lun)
        path = lun.get_child_content('path')
        (_rest, _splitter, name) = path.rpartition('/')
        handle = self._create_lun_handle(meta_dict)
        size = lun.get_child_content('size')
        return NetAppLun(handle, name, size, meta_dict)

    def _extract_and_populate_luns(self, api_luns):
        """Extracts the LUNs from API and populates the LUN table."""

        for lun in api_luns:
            discovered_lun = self._extract_lun_info(lun)
            self._add_lun_to_table(discovered_lun)

    def _map_lun(self, name, initiator_list, initiator_type, lun_id=None):
        """Maps LUN to the initiator(s) and returns LUN ID assigned."""
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        igroup_name, ig_host_os, ig_type = self._get_or_create_igroup(
            initiator_list, initiator_type, self.host_type)
        if ig_host_os != self.host_type:
            LOG.warning(_LW("LUN misalignment may occur for current"
                            " initiator group %(ig_nm)s) with host OS type"
                            " %(ig_os)s. Please configure initiator group"
                            " manually according to the type of the"
                            " host OS."),
                        {'ig_nm': igroup_name, 'ig_os': ig_host_os})
        try:
            return self.zapi_client.map_lun(path, igroup_name, lun_id=lun_id)
        except na_api.NaApiError:
            exc_info = sys.exc_info()
            (_igroup, lun_id) = self._find_mapped_lun_igroup(path,
                                                             initiator_list)
            if lun_id is not None:
                return lun_id
            else:
                raise exc_info[0], exc_info[1], exc_info[2]

    def _unmap_lun(self, path, initiator_list):
        """Unmaps a LUN from given initiator."""
        (igroup_name, _lun_id) = self._find_mapped_lun_igroup(path,
                                                              initiator_list)
        self.zapi_client.unmap_lun(path, igroup_name)

    def _find_mapped_lun_igroup(self, path, initiator_list):
        """Find an igroup for a LUN mapped to the given initiator(s)."""
        raise NotImplementedError()

    def _has_luns_mapped_to_initiators(self, initiator_list):
        """Checks whether any LUNs are mapped to the given initiator(s)."""
        return self.zapi_client.has_luns_mapped_to_initiators(initiator_list)

    def _get_or_create_igroup(self, initiator_list, initiator_group_type,
                              host_os_type):
        """Checks for an igroup for a set of one or more initiators.

        Creates igroup if not already present with given host os type,
        igroup type and adds initiators.
        """
        igroups = self.zapi_client.get_igroup_by_initiators(initiator_list)
        igroup_name = None

        if igroups:
            igroup = igroups[0]
            igroup_name = igroup['initiator-group-name']
            host_os_type = igroup['initiator-group-os-type']
            initiator_group_type = igroup['initiator-group-type']

        if not igroup_name:
            igroup_name = self._create_igroup_add_initiators(
                initiator_group_type, host_os_type, initiator_list)
        return igroup_name, host_os_type, initiator_group_type

    def _create_igroup_add_initiators(self, initiator_group_type,
                                      host_os_type, initiator_list):
        """Creates igroup and adds initiators."""
        igroup_name = na_utils.OPENSTACK_PREFIX + six.text_type(uuid.uuid4())
        self.zapi_client.create_igroup(igroup_name, initiator_group_type,
                                       host_os_type)
        for initiator in initiator_list:
            self.zapi_client.add_igroup_initiator(igroup_name, initiator)
        return igroup_name

    def _add_lun_to_table(self, lun):
        """Adds LUN to cache table."""
        if not isinstance(lun, NetAppLun):
            msg = _("Object is not a NetApp LUN.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.lun_table[lun.name] = lun

    def _get_lun_from_table(self, name):
        """Gets LUN from cache table.

        Refreshes cache if LUN not found in cache.
        """
        lun = self.lun_table.get(name)
        if lun is None:
            lun_list = self.zapi_client.get_lun_list()
            self._extract_and_populate_luns(lun_list)
            lun = self.lun_table.get(name)
            if lun is None:
                raise exception.VolumeNotFound(volume_id=name)
        return lun

    def _clone_lun(self, name, new_name, space_reserved='true',
                   qos_policy_group_name=None, src_block=0, dest_block=0,
                   block_count=0):
        """Clone LUN with the given name to the new name."""
        raise NotImplementedError()

    def _get_lun_attr(self, name, attr):
        """Get the LUN attribute if found else None."""
        try:
            attr = getattr(self._get_lun_from_table(name), attr)
            return attr
        except exception.VolumeNotFound as e:
            LOG.error(_LE("Message: %s"), e.msg)
        except Exception as e:
            LOG.error(_LE("Error getting LUN attribute. Exception: %s"), e)
        return None

    def _create_lun_meta(self, lun):
        raise NotImplementedError()

    def _get_fc_target_wwpns(self, include_partner=True):
        raise NotImplementedError()

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        raise NotImplementedError()

    def extend_volume(self, volume, new_size, qos_policy_group_name=None):
        """Extend an existing volume to the new size."""
        name = volume['name']
        lun = self._get_lun_from_table(name)
        path = lun.metadata['Path']
        curr_size_bytes = six.text_type(lun.size)
        new_size_bytes = six.text_type(int(new_size) * units.Gi)
        # Reused by clone scenarios.
        # Hence comparing the stored size.
        if curr_size_bytes != new_size_bytes:
            lun_geometry = self.zapi_client.get_lun_geometry(path)
            if (lun_geometry and lun_geometry.get("max_resize")
                    and int(lun_geometry.get("max_resize")) >=
                    int(new_size_bytes)):
                self.zapi_client.do_direct_resize(path, new_size_bytes)
            else:
                self._do_sub_clone_resize(
                    path, new_size_bytes,
                    qos_policy_group_name=qos_policy_group_name)
            self.lun_table[name].size = new_size_bytes
        else:
            LOG.info(_LI("No need to extend volume %s"
                         " as it is already the requested new size."), name)

    def _get_vol_option(self, volume_name, option_name):
        """Get the value for the volume option."""
        value = None
        options = self.zapi_client.get_volume_options(volume_name)
        for opt in options:
            if opt.get_child_content('name') == option_name:
                value = opt.get_child_content('value')
                break
        return value

    def _do_sub_clone_resize(self, path, new_size_bytes,
                             qos_policy_group_name=None):
        """Does sub LUN clone after verification.

            Clones the block ranges and swaps
            the LUNs also deletes older LUN
            after a successful clone.
        """
        seg = path.split("/")
        LOG.info(_LI("Resizing LUN %s to new size using clone operation."),
                 seg[-1])
        name = seg[-1]
        vol_name = seg[2]
        lun = self._get_lun_from_table(name)
        metadata = lun.metadata
        compression = self._get_vol_option(vol_name, 'compression')
        if compression == "on":
            msg = _('%s cannot be resized using clone operation'
                    ' as it is hosted on compressed volume')
            raise exception.VolumeBackendAPIException(data=msg % name)
        else:
            block_count = self._get_lun_block_count(path)
            if block_count == 0:
                msg = _('%s cannot be resized using clone operation'
                        ' as it contains no blocks.')
                raise exception.VolumeBackendAPIException(data=msg % name)
            new_lun = 'new-%s' % name
            self.zapi_client.create_lun(
                vol_name, new_lun, new_size_bytes, metadata,
                qos_policy_group_name=qos_policy_group_name)
            try:
                self._clone_lun(name, new_lun, block_count=block_count,
                                qos_policy_group_name=qos_policy_group_name)

                self._post_sub_clone_resize(path)
            except Exception:
                with excutils.save_and_reraise_exception():
                    new_path = '/vol/%s/%s' % (vol_name, new_lun)
                    self.zapi_client.destroy_lun(new_path)

    def _post_sub_clone_resize(self, path):
        """Try post sub clone resize in a transactional manner."""
        st_tm_mv, st_nw_mv, st_del_old = None, None, None
        seg = path.split("/")
        LOG.info(_LI("Post clone resize LUN %s"), seg[-1])
        new_lun = 'new-%s' % (seg[-1])
        tmp_lun = 'tmp-%s' % (seg[-1])
        tmp_path = "/vol/%s/%s" % (seg[2], tmp_lun)
        new_path = "/vol/%s/%s" % (seg[2], new_lun)
        try:
            st_tm_mv = self.zapi_client.move_lun(path, tmp_path)
            st_nw_mv = self.zapi_client.move_lun(new_path, path)
            st_del_old = self.zapi_client.destroy_lun(tmp_path)
        except Exception as e:
            if st_tm_mv is None:
                msg = _("Failure staging LUN %s to tmp.")
                raise exception.VolumeBackendAPIException(data=msg % (seg[-1]))
            else:
                if st_nw_mv is None:
                    self.zapi_client.move_lun(tmp_path, path)
                    msg = _("Failure moving new cloned LUN to %s.")
                    raise exception.VolumeBackendAPIException(
                        data=msg % (seg[-1]))
                elif st_del_old is None:
                    LOG.error(_LE("Failure deleting staged tmp LUN %s."),
                              tmp_lun)
                else:
                    LOG.error(_LE("Unknown exception in"
                                  " post clone resize LUN %s."), seg[-1])
                    LOG.error(_LE("Exception details: %s"), e)

    def _get_lun_block_count(self, path):
        """Gets block counts for the LUN."""
        LOG.debug("Getting LUN block count.")
        lun_infos = self.zapi_client.get_lun_by_args(path=path)
        if not lun_infos:
            seg = path.split('/')
            msg = _('Failure getting LUN info for %s.')
            raise exception.VolumeBackendAPIException(data=msg % seg[-1])
        lun_info = lun_infos[-1]
        bs = int(lun_info.get_child_content('block-size'))
        ls = int(lun_info.get_child_content('size'))
        block_count = ls / bs
        return block_count

    def _check_volume_type_for_lun(self, volume, lun, existing_ref,
                                   extra_specs):
        """Checks if lun satifies the volume type."""
        raise NotImplementedError()

    def manage_existing(self, volume, existing_ref):
        """Brings an existing storage object under Cinder management.

        existing_ref can contain source-id or source-name or both.
        source-id: lun uuid.
        source-name: complete lun path eg. /vol/vol0/lun.
        """
        lun = self._get_existing_vol_with_manage_ref(existing_ref)

        extra_specs = na_utils.get_volume_extra_specs(volume)

        self._check_volume_type_for_lun(volume, lun, existing_ref, extra_specs)

        qos_policy_group_info = self._setup_qos_for_volume(volume, extra_specs)
        qos_policy_group_name = (
            na_utils.get_qos_policy_group_name_from_info(
                qos_policy_group_info))

        path = lun.get_metadata_property('Path')
        if lun.name == volume['name']:
            new_path = path
            LOG.info(_LI("LUN with given ref %s need not be renamed "
                         "during manage operation."), existing_ref)
        else:
            (rest, splitter, name) = path.rpartition('/')
            new_path = '%s/%s' % (rest, volume['name'])
            self.zapi_client.move_lun(path, new_path)
            lun = self._get_existing_vol_with_manage_ref(
                {'source-name': new_path})
        if qos_policy_group_name is not None:
            self.zapi_client.set_lun_qos_policy_group(new_path,
                                                      qos_policy_group_name)
        self._add_lun_to_table(lun)
        LOG.info(_LI("Manage operation completed for LUN with new path"
                     " %(path)s and uuid %(uuid)s."),
                 {'path': lun.get_metadata_property('Path'),
                  'uuid': lun.get_metadata_property('UUID')})

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        lun = self._get_existing_vol_with_manage_ref(existing_ref)
        return int(math.ceil(float(lun.size) / units.Gi))

    def _get_existing_vol_with_manage_ref(self, existing_ref):
        """Get the corresponding LUN from the storage server."""
        uuid = existing_ref.get('source-id')
        path = existing_ref.get('source-name')
        if not (uuid or path):
            reason = _('Reference must contain either source-id'
                       ' or source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        lun_info = {}
        lun_info.setdefault('path', path if path else None)
        if hasattr(self, 'vserver') and uuid:
            lun_info['uuid'] = uuid
        luns = self.zapi_client.get_lun_by_args(**lun_info)
        if luns:
            for lun in luns:
                netapp_lun = self._extract_lun_info(lun)
                storage_valid = self._is_lun_valid_on_storage(netapp_lun)
                uuid_valid = True
                if uuid:
                    if netapp_lun.get_metadata_property('UUID') == uuid:
                        uuid_valid = True
                    else:
                        uuid_valid = False
                if storage_valid and uuid_valid:
                    return netapp_lun
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref,
            reason=(_('LUN not found with given ref %s.') % existing_ref))

    def _is_lun_valid_on_storage(self, lun):
        """Validate lun specific to storage system."""
        return True

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object.
        """
        managed_lun = self._get_lun_from_table(volume['name'])
        LOG.info(_LI("Unmanaged LUN with current path %(path)s and uuid "
                     "%(uuid)s."),
                 {'path': managed_lun.get_metadata_property('Path'),
                  'uuid': managed_lun.get_metadata_property('UUID')
                  or 'unknown'})

    def initialize_connection_iscsi(self, volume, connector):
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
        lun_id = self._map_lun(name, [initiator_name], 'iscsi', None)

        LOG.debug("Mapped LUN %(name)s to the initiator %(initiator_name)s",
                  {'name': name, 'initiator_name': initiator_name})

        target_list = self.zapi_client.get_iscsi_target_details()
        if not target_list:
            raise exception.VolumeBackendAPIException(
                data=_('Failed to get LUN target list for the LUN %s') % name)

        LOG.debug("Successfully fetched target list for LUN %(name)s and "
                  "initiator %(initiator_name)s",
                  {'name': name, 'initiator_name': initiator_name})

        preferred_target = self._get_preferred_target_from_list(
            target_list)
        if preferred_target is None:
            msg = _('Failed to get target portal for the LUN %s')
            raise exception.VolumeBackendAPIException(data=msg % name)
        (address, port) = (preferred_target['address'],
                           preferred_target['port'])

        iqn = self.zapi_client.get_iscsi_service_details()
        if not iqn:
            msg = _('Failed to get target IQN for the LUN %s')
            raise exception.VolumeBackendAPIException(data=msg % name)

        properties = na_utils.get_iscsi_connection_properties(lun_id, volume,
                                                              iqn, address,
                                                              port)
        return properties

    def _get_preferred_target_from_list(self, target_details_list,
                                        filter=None):
        preferred_target = None
        for target in target_details_list:
            if filter and target['address'] not in filter:
                continue
            if target.get('interface-enabled', 'true') == 'true':
                preferred_target = target
                break
        if preferred_target is None and len(target_details_list) > 0:
            preferred_target = target_details_list[0]
        return preferred_target

    def terminate_connection_iscsi(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given initiator can no
        longer access it.
        """

        initiator_name = connector['initiator']
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        self._unmap_lun(path, [initiator_name])
        LOG.debug("Unmapped LUN %(name)s from the initiator "
                  "%(initiator_name)s",
                  {'name': name, 'initiator_name': initiator_name})

    def initialize_connection_fc(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:
            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '500a098280feeba5',
                    'access_mode': 'rw',
                    'initiator_target_map': {
                        '21000024ff406cc3': ['500a098280feeba5'],
                        '21000024ff406cc2': ['500a098280feeba5']
                    }
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['500a098280feeba5', '500a098290feeba5',
                                   '500a098190feeba5', '500a098180feeba5'],
                    'access_mode': 'rw',
                    'initiator_target_map': {
                        '21000024ff406cc3': ['500a098280feeba5',
                                             '500a098290feeba5'],
                        '21000024ff406cc2': ['500a098190feeba5',
                                             '500a098180feeba5']
                    }
                }
            }
        """

        initiators = [fczm_utils.get_formatted_wwn(wwpn)
                      for wwpn in connector['wwpns']]
        volume_name = volume['name']

        lun_id = self._map_lun(volume_name, initiators, 'fcp', None)

        LOG.debug("Mapped LUN %(name)s to the initiator(s) %(initiators)s",
                  {'name': volume_name, 'initiators': initiators})

        target_wwpns, initiator_target_map, num_paths = (
            self._build_initiator_target_map(connector))

        if target_wwpns:
            LOG.debug("Successfully fetched target details for LUN %(name)s "
                      "and initiator(s) %(initiators)s",
                      {'name': volume_name, 'initiators': initiators})
        else:
            raise exception.VolumeBackendAPIException(
                data=_('Failed to get LUN target details for '
                       'the LUN %s') % volume_name)

        target_info = {'driver_volume_type': 'fibre_channel',
                       'data': {'target_discovered': True,
                                'target_lun': int(lun_id),
                                'target_wwn': target_wwpns,
                                'access_mode': 'rw',
                                'initiator_target_map': initiator_target_map}}

        return target_info

    def terminate_connection_fc(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        Return empty data if other volumes are in the same zone.
        The FibreChannel ZoneManager doesn't remove zones
        if there isn't an initiator_target_map in the
        return of terminate_connection.

        :returns: data - the target_wwns and initiator_target_map if the
                         zone is to be removed, otherwise the same map with
                         an empty dict for the 'data' key
        """

        initiators = [fczm_utils.get_formatted_wwn(wwpn)
                      for wwpn in connector['wwpns']]
        name = volume['name']
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']

        self._unmap_lun(path, initiators)

        LOG.debug("Unmapped LUN %(name)s from the initiator %(initiators)s",
                  {'name': name, 'initiators': initiators})

        info = {'driver_volume_type': 'fibre_channel',
                'data': {}}

        if not self._has_luns_mapped_to_initiators(initiators):
            # No more exports for this host, so tear down zone.
            LOG.info(_LI("Need to remove FC Zone, building initiator "
                         "target map"))

            target_wwpns, initiator_target_map, num_paths = (
                self._build_initiator_target_map(connector))

            info['data'] = {'target_wwn': target_wwpns,
                            'initiator_target_map': initiator_target_map}

        return info

    def _build_initiator_target_map(self, connector):
        """Build the target_wwns and the initiator target map."""

        # get WWPNs from controller and strip colons
        all_target_wwpns = self._get_fc_target_wwpns()
        all_target_wwpns = [six.text_type(wwpn).replace(':', '')
                            for wwpn in all_target_wwpns]

        target_wwpns = []
        init_targ_map = {}
        num_paths = 0

        if self.lookup_service is not None:
            # Use FC SAN lookup to determine which ports are visible.
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                all_target_wwpns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwpns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
                    for target in init_targ_map[initiator]:
                        num_paths += 1
            target_wwpns = list(set(target_wwpns))
        else:
            initiator_wwns = connector['wwpns']
            target_wwpns = all_target_wwpns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwpns

        return target_wwpns, init_targ_map, num_paths
