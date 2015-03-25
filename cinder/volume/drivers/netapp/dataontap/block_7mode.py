# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2014 Jeff Applewhite.  All rights reserved.
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
Volume driver library for NetApp 7-mode block storage systems.
"""

from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LW
from cinder.volume import configuration
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


class NetAppBlockStorage7modeLibrary(block_base.
                                     NetAppBlockStorageLibrary):
    """NetApp block storage library for Data ONTAP (7-mode)."""

    def __init__(self, driver_name, driver_protocol, **kwargs):
        super(NetAppBlockStorage7modeLibrary, self).__init__(driver_name,
                                                             driver_protocol,
                                                             **kwargs)
        self.configuration.append_config_values(na_opts.netapp_7mode_opts)
        self.driver_mode = '7mode'

    def do_setup(self, context):
        super(NetAppBlockStorage7modeLibrary, self).do_setup(context)

        self.volume_list = self.configuration.netapp_volume_list
        if self.volume_list:
            self.volume_list = self.volume_list.split(',')
            self.volume_list = [el.strip() for el in self.volume_list]

        self.vfiler = self.configuration.netapp_vfiler

        self.zapi_client = client_7mode.Client(
            self.volume_list,
            transport_type=self.configuration.netapp_transport_type,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            vfiler=self.vfiler)

        self._do_partner_setup()

        self.vol_refresh_time = None
        self.vol_refresh_interval = 1800
        self.vol_refresh_running = False
        self.vol_refresh_voluntary = False
        self.root_volume_name = self._get_root_volume_name()

    def _do_partner_setup(self):
        partner_backend = self.configuration.netapp_partner_backend_name
        if partner_backend:
            config = configuration.Configuration(na_opts.netapp_7mode_opts,
                                                 partner_backend)
            config.append_config_values(na_opts.netapp_connection_opts)
            config.append_config_values(na_opts.netapp_basicauth_opts)
            config.append_config_values(na_opts.netapp_transport_opts)

            self.partner_zapi_client = client_7mode.Client(
                None,
                transport_type=config.netapp_transport_type,
                username=config.netapp_login,
                password=config.netapp_password,
                hostname=config.netapp_server_hostname,
                port=config.netapp_server_port,
                vfiler=None)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        api_version = self.zapi_client.get_ontapi_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 9:
                msg = _("Unsupported Data ONTAP version."
                        " Data ONTAP version 7.3.1 and above is supported.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("API version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)
        super(NetAppBlockStorage7modeLibrary, self).check_for_setup_error()

    def _create_lun(self, volume_name, lun_name, size,
                    metadata, qos_policy_group=None):
        """Creates a LUN, handling Data ONTAP differences as needed."""

        self.zapi_client.create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group)

        self.vol_refresh_voluntary = True

    def _get_root_volume_name(self):
        # switch to volume-get-root-name API when possible
        vols = self.zapi_client.get_filer_volumes()
        for vol in vols:
            volume_name = vol.get_child_content('name')
            if self._get_vol_option(volume_name, 'root') == 'true':
                return volume_name
        LOG.warning(_LW('Could not determine root volume name '
                        'on %s.') % self._get_owner())
        return None

    def _get_owner(self):
        if self.vfiler:
            owner = '%s:%s' % (self.configuration.netapp_server_hostname,
                               self.vfiler)
        else:
            owner = self.configuration.netapp_server_hostname
        return owner

    def _create_lun_handle(self, metadata):
        """Returns LUN handle based on filer type."""
        owner = self._get_owner()
        return '%s:%s' % (owner, metadata['Path'])

    def _find_mapped_lun_igroup(self, path, initiator_list):
        """Find an igroup for a LUN mapped to the given initiator(s)."""
        initiator_set = set(initiator_list)

        result = self.zapi_client.get_lun_map(path)
        initiator_groups = result.get_child_by_name('initiator-groups')
        if initiator_groups:
            for initiator_group_info in initiator_groups.get_children():

                initiator_set_for_igroup = set()
                for initiator_info in initiator_group_info.get_child_by_name(
                        'initiators').get_children():
                    initiator_set_for_igroup.add(
                        initiator_info.get_child_content('initiator-name'))

                if initiator_set == initiator_set_for_igroup:
                        igroup = initiator_group_info.get_child_content(
                            'initiator-group-name')
                        lun_id = initiator_group_info.get_child_content(
                            'lun-id')
                        return igroup, lun_id

        return None, None

    def _has_luns_mapped_to_initiators(self, initiator_list,
                                       include_partner=True):
        """Checks whether any LUNs are mapped to the given initiator(s)."""
        if self.zapi_client.has_luns_mapped_to_initiators(initiator_list):
            return True
        if include_partner and self.partner_zapi_client and \
                self.partner_zapi_client.has_luns_mapped_to_initiators(
                    initiator_list):
            return True
        return False

    def _clone_lun(self, name, new_name, space_reserved='true',
                   src_block=0, dest_block=0, block_count=0):
        """Clone LUN with the given handle to the new name."""
        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        (parent, _splitter, name) = path.rpartition('/')
        clone_path = '%s/%s' % (parent, new_name)

        self.zapi_client.clone_lun(path, clone_path, name, new_name,
                                   space_reserved, src_block=0,
                                   dest_block=0, block_count=0)

        self.vol_refresh_voluntary = True
        luns = self.zapi_client.get_lun_by_args(path=clone_path)
        cloned_lun = luns[0]
        self.zapi_client.set_space_reserve(clone_path, space_reserved)
        clone_meta = self._create_lun_meta(cloned_lun)
        handle = self._create_lun_handle(clone_meta)
        self._add_lun_to_table(
            block_base.NetAppLun(handle, new_name,
                                 cloned_lun.get_child_content('size'),
                                 clone_meta))

    def _create_lun_meta(self, lun):
        """Creates LUN metadata dictionary."""
        self.zapi_client.check_is_naelement(lun)
        meta_dict = {}
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['Volume'] = lun.get_child_content('path').split('/')[2]
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = lun.get_child_content(
            'is-space-reservation-enabled')
        meta_dict['UUID'] = lun.get_child_content('uuid')
        return meta_dict

    def _get_fc_target_wwpns(self, include_partner=True):
        wwpns = self.zapi_client.get_fc_target_wwpns()
        if include_partner and self.partner_zapi_client:
            wwpns.extend(self.partner_zapi_client.get_fc_target_wwpns())
        return wwpns

    def _update_volume_stats(self):
        """Retrieve stats info from filer."""

        # ensure we get current data
        self.vol_refresh_voluntary = True
        self._refresh_volume_info()

        LOG.debug('Updating volume stats')
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.driver_name
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.driver_protocol
        data['pools'] = self._get_pool_stats()

        self.zapi_client.provide_ems(self, self.driver_name, self.app_version,
                                     server_type=self.driver_mode)
        self._stats = data

    def _get_pool_stats(self):
        """Retrieve pool (i.e. Data ONTAP volume) stats info from volumes."""

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
            pool['total_capacity_gb'] = na_utils.round_down(total, '0.01')

            free = float(vol.get_child_content('size-available') or 0)
            free /= self.configuration.netapp_size_multiplier
            free /= units.Gi
            pool['free_capacity_gb'] = na_utils.round_down(free, '0.01')

            pools.append(pool)

        return pools

    def _get_lun_block_count(self, path):
        """Gets block counts for the LUN."""
        bs = super(NetAppBlockStorage7modeLibrary,
                   self)._get_lun_block_count(path)
        api_version = self.zapi_client.get_ontapi_version()
        if api_version:
            major = api_version[0]
            minor = api_version[1]
            if major == 1 and minor < 15:
                bs -= 1
        return bs

    def _refresh_volume_info(self):
        """Saves the volume information for the filer."""

        if (self.vol_refresh_time is None or self.vol_refresh_voluntary or
                timeutils.is_newer_than(self.vol_refresh_time,
                                        self.vol_refresh_interval)):
            try:
                job_set = na_utils.set_safe_attr(self, 'vol_refresh_running',
                                                 True)
                if not job_set:
                    LOG.warning(_LW("Volume refresh job already running. "
                                    "Returning..."))
                    return
                self.vol_refresh_voluntary = False
                self.vols = self.zapi_client.get_filer_volumes()
                self.vol_refresh_time = timeutils.utcnow()
            except Exception as e:
                LOG.warning(_LW("Error refreshing volume info. Message: %s"),
                            six.text_type(e))
            finally:
                na_utils.set_safe_attr(self, 'vol_refresh_running', False)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        super(NetAppBlockStorage7modeLibrary, self).delete_volume(volume)
        self.vol_refresh_voluntary = True

    def _is_lun_valid_on_storage(self, lun):
        """Validate LUN specific to storage system."""
        if self.volume_list:
            lun_vol = lun.get_metadata_property('Volume')
            if lun_vol not in self.volume_list:
                return False
        return True

    def _check_volume_type_for_lun(self, volume, lun, existing_ref):
        """Check if lun satisfies volume type."""
        extra_specs = na_utils.get_volume_extra_specs(volume)
        if extra_specs and extra_specs.pop('netapp:qos_policy_group', None):
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=_("Setting LUN QoS policy group is not supported"
                         " on this storage family and ONTAP version."))

    def _get_preferred_target_from_list(self, target_details_list):
        # 7-mode iSCSI LIFs migrate from controller to controller
        # in failover and flap operational state in transit, so
        # we  don't filter these on operational state.

        return (super(NetAppBlockStorage7modeLibrary, self)
                ._get_preferred_target_from_list(target_details_list,
                                                 filter=None))
