# Copyright (c) 2013 VMware, Inc.
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
Volume driver for VMware vCenter/ESX managed datastores.

The volumes created by this driver are backed by VMDK (Virtual Machine
Disk) files stored in datastores. For ease of managing the VMDKs, the
driver creates a virtual machine for each of the volumes. This virtual
machine is never powered on and is often referred as the shadow VM.
"""

import distutils.version as dist_version  # pylint: disable=E0611
import os

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import units
from cinder.volume import driver
from cinder.volume.drivers.vmware import api
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim
from cinder.volume.drivers.vmware import vim_util
from cinder.volume.drivers.vmware import vmware_images
from cinder.volume.drivers.vmware import volumeops
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

THIN_VMDK_TYPE = 'thin'
THICK_VMDK_TYPE = 'thick'
EAGER_ZEROED_THICK_VMDK_TYPE = 'eagerZeroedThick'

vmdk_opts = [
    cfg.StrOpt('vmware_host_ip',
               default=None,
               help='IP address for connecting to VMware ESX/VC server.'),
    cfg.StrOpt('vmware_host_username',
               default=None,
               help='Username for authenticating with VMware ESX/VC server.'),
    cfg.StrOpt('vmware_host_password',
               default=None,
               help='Password for authenticating with VMware ESX/VC server.',
               secret=True),
    cfg.StrOpt('vmware_wsdl_location',
               default=None,
               help='Optional VIM service WSDL Location '
                    'e.g http://<server>/vimService.wsdl. Optional over-ride '
                    'to default location for bug work-arounds.'),
    cfg.IntOpt('vmware_api_retry_count',
               default=10,
               help='Number of times VMware ESX/VC server API must be '
                    'retried upon connection related issues.'),
    cfg.IntOpt('vmware_task_poll_interval',
               default=5,
               help='The interval (in seconds) for polling remote tasks '
                    'invoked on VMware ESX/VC server.'),
    cfg.StrOpt('vmware_volume_folder',
               default='cinder-volumes',
               help='Name for the folder in the VC datacenter that will '
                    'contain cinder volumes.'),
    cfg.IntOpt('vmware_image_transfer_timeout_secs',
               default=7200,
               help='Timeout in seconds for VMDK volume transfer between '
                    'Cinder and Glance.'),
    cfg.IntOpt('vmware_max_objects_retrieval',
               default=100,
               help='Max number of objects to be retrieved per batch. '
                    'Query results will be obtained in batches from the '
                    'server and not in one shot. Server may still limit the '
                    'count to something less than the configured value.'),
    cfg.StrOpt('vmware_host_version',
               help='Optional string specifying the VMware VC server version. '
                    'The driver attempts to retrieve the version from VMware '
                    'VC server. Set this configuration only if you want to '
                    'override the VC server version.'),
]

CONF = cfg.CONF
CONF.register_opts(vmdk_opts)


def _get_volume_type_extra_spec(type_id, spec_key, possible_values=None,
                                default_value=None):
    """Get extra spec value.

    If the spec value is not present in the input possible_values, then
    default_value will be returned.
    If the type_id is None, then default_value is returned.

    The caller must not consider scope and the implementation adds/removes
    scope. The scope used here is 'vmware' e.g. key 'vmware:vmdk_type' and
    so the caller must pass vmdk_type as an input ignoring the scope.

    :param type_id: Volume type ID
    :param spec_key: Extra spec key
    :param possible_values: Permitted values for the extra spec if known
    :param default_value: Default value for the extra spec incase of an
                          invalid value or if the entry does not exist
    :return: extra spec value
    """
    if not type_id:
        return default_value

    spec_key = ('vmware:%s') % spec_key
    spec_value = volume_types.get_volume_type_extra_specs(type_id,
                                                          spec_key)
    if not spec_value:
        LOG.debug(_("Returning default spec value: %s.") % default_value)
        return default_value

    if possible_values is None:
        return spec_value

    if spec_value in possible_values:
        LOG.debug(_("Returning spec value %s") % spec_value)
        return spec_value

    LOG.debug(_("Invalid spec value: %s specified.") % spec_value)


class VMwareEsxVmdkDriver(driver.VolumeDriver):
    """Manage volumes on VMware ESX server."""

    # 1.0 - initial version of driver
    # 1.1.0 - selection of datastore based on number of host mounts
    # 1.2.0 - storage profile volume types based placement of volumes
    VERSION = '1.2.0'

    def _do_deprecation_warning(self):
        LOG.warn(_('The VMware ESX VMDK driver is now deprecated and will be '
                   'removed in the Juno release. The VMware vCenter VMDK '
                   'driver will remain and continue to be supported.'))

    def __init__(self, *args, **kwargs):
        super(VMwareEsxVmdkDriver, self).__init__(*args, **kwargs)

        self._do_deprecation_warning()

        self.configuration.append_config_values(vmdk_opts)
        self._session = None
        self._stats = None
        self._volumeops = None
        # No storage policy based placement possible when connecting
        # directly to ESX
        self._storage_policy_enabled = False

    @property
    def session(self):
        if not self._session:
            ip = self.configuration.vmware_host_ip
            username = self.configuration.vmware_host_username
            password = self.configuration.vmware_host_password
            api_retry_count = self.configuration.vmware_api_retry_count
            task_poll_interval = self.configuration.vmware_task_poll_interval
            wsdl_loc = self.configuration.safe_get('vmware_wsdl_location')
            self._session = api.VMwareAPISession(ip, username,
                                                 password, api_retry_count,
                                                 task_poll_interval,
                                                 wsdl_loc=wsdl_loc)
        return self._session

    @property
    def volumeops(self):
        if not self._volumeops:
            max_objects = self.configuration.vmware_max_objects_retrieval
            self._volumeops = volumeops.VMwareVolumeOps(self.session,
                                                        max_objects)
        return self._volumeops

    def do_setup(self, context):
        """Perform validations and establish connection to server.

        :param context: Context information
        """

        # Throw error if required parameters are not set.
        required_params = ['vmware_host_ip',
                           'vmware_host_username',
                           'vmware_host_password']
        for param in required_params:
            if not getattr(self.configuration, param, None):
                raise exception.InvalidInput(_("%s not set.") % param)

        # Create the session object for the first time for ESX driver
        driver = self.__class__.__name__
        if driver == 'VMwareEsxVmdkDriver':
            max_objects = self.configuration.vmware_max_objects_retrieval
            self._volumeops = volumeops.VMwareVolumeOps(self.session,
                                                        max_objects)
            LOG.info(_("Successfully setup driver: %(driver)s for "
                       "server: %(ip)s.") %
                     {'driver': driver,
                      'ip': self.configuration.vmware_host_ip})

    def check_for_setup_error(self):
        pass

    def get_volume_stats(self, refresh=False):
        """Obtain status of the volume service.

        :param refresh: Whether to get refreshed information
        """

        if not self._stats:
            backend_name = self.configuration.safe_get('volume_backend_name')
            if not backend_name:
                backend_name = self.__class__.__name__
            data = {'volume_backend_name': backend_name,
                    'vendor_name': 'VMware',
                    'driver_version': self.VERSION,
                    'storage_protocol': 'LSI Logic SCSI',
                    'reserved_percentage': 0,
                    'total_capacity_gb': 'unknown',
                    'free_capacity_gb': 'unknown'}
            self._stats = data
        return self._stats

    def _verify_volume_creation(self, volume):
        """Verify the volume can be created.

        Verify that there is a datastore that can accommodate this volume.
        If this volume is being associated with a volume_type then verify
        the storage_profile exists and can accommodate this volume. Raise
        an exception otherwise.

        :param volume: Volume object
        """
        try:
            # find if any host can accommodate the volume
            self._select_ds_for_volume(volume)
        except error_util.VimException as excep:
            msg = _("Not able to find a suitable datastore for the volume: "
                    "%s.") % volume['name']
            LOG.exception(msg)
            raise error_util.VimFaultException([excep], msg)
        LOG.debug(_("Verified volume %s can be created."), volume['name'])

    def create_volume(self, volume):
        """Creates a volume.

        We do not create any backing. We do it only the first time
        it is being attached to a virtual machine.

        :param volume: Volume object
        """
        self._verify_volume_creation(volume)

    def _delete_volume(self, volume):
        """Delete the volume backing if it is present.

        :param volume: Volume object
        """
        backing = self.volumeops.get_backing(volume['name'])
        if not backing:
            LOG.info(_("Backing not available, no operation to be performed."))
            return
        self.volumeops.delete_backing(backing)

    def delete_volume(self, volume):
        """Deletes volume backing.

        :param volume: Volume object
        """
        self._delete_volume(volume)

    def _get_volume_group_folder(self, datacenter):
        """Return vmFolder of datacenter as we cannot create folder in ESX.

        :param datacenter: Reference to the datacenter
        :return: vmFolder reference of the datacenter
        """
        return self.volumeops.get_vmfolder(datacenter)

    def _compute_space_utilization(self, datastore_summary):
        """Compute the space utilization of the given datastore.

        :param datastore_summary: Summary of the datastore for which
                                  space utilization is to be computed
        :return: space utilization in the range [0..1]
        """
        return (
            1.0 -
            datastore_summary.freeSpace / float(datastore_summary.capacity)
        )

    def _select_datastore_summary(self, size_bytes, datastores):
        """Get the best datastore summary from the given datastore list.

        The implementation selects a datastore which is connected to maximum
        number of hosts, provided there is enough space to accommodate the
        volume. Ties are broken based on space utilization; datastore with
        low space utilization is preferred.

        :param size_bytes: Size in bytes of the volume
        :param datastores: Datastores from which a choice is to be made
                           for the volume
        :return: Summary of the best datastore selected for volume
        """
        best_summary = None
        max_host_count = 0
        best_space_utilization = 1.0

        for datastore in datastores:
            summary = self.volumeops.get_summary(datastore)
            if summary.freeSpace > size_bytes:
                host_count = len(self.volumeops.get_connected_hosts(datastore))
                if host_count > max_host_count:
                    max_host_count = host_count
                    best_space_utilization = self._compute_space_utilization(
                        summary
                    )
                    best_summary = summary
                elif host_count == max_host_count:
                    # break the tie based on space utilization
                    space_utilization = self._compute_space_utilization(
                        summary
                    )
                    if space_utilization < best_space_utilization:
                        best_space_utilization = space_utilization
                        best_summary = summary

        if not best_summary:
            msg = _("Unable to pick datastore to accommodate %(size)s bytes "
                    "from the datastores: %(dss)s.") % {'size': size_bytes,
                                                        'dss': datastores}
            LOG.error(msg)
            raise error_util.VimException(msg)

        LOG.debug(_("Selected datastore: %(datastore)s with %(host_count)d "
                    "connected host(s) for the volume.") %
                  {'datastore': best_summary, 'host_count': max_host_count})
        return best_summary

    def _get_storage_profile(self, volume):
        """Get storage profile associated with the given volume's volume_type.

        :param volume: Volume whose storage profile should be queried
        :return: String value of storage profile if volume type is associated
                 and contains storage_profile extra_spec option; None otherwise
        """
        type_id = volume['volume_type_id']
        if type_id is None:
            return None
        return _get_volume_type_extra_spec(type_id, 'storage_profile')

    def _filter_ds_by_profile(self, datastores, storage_profile):
        """Filter out datastores that do not match given storage profile.

        :param datastores: list of candidate datastores
        :param storage_profile: storage profile name required to be satisfied
        :return: subset of datastores that match storage_profile, or empty list
                 if none of the datastores match
        """
        LOG.debug(_("Filter datastores matching storage profile %(profile)s: "
                    "%(dss)s."),
                  {'profile': storage_profile, 'dss': datastores})
        profileId = self.volumeops.retrieve_profile_id(storage_profile)
        if not profileId:
            msg = _("No such storage profile '%s; is defined in vCenter.")
            LOG.error(msg, storage_profile)
            raise error_util.VimException(msg % storage_profile)
        pbm_cf = self.session.pbm.client.factory
        hubs = vim_util.convert_datastores_to_hubs(pbm_cf, datastores)
        filtered_hubs = self.volumeops.filter_matching_hubs(hubs, profileId)
        return vim_util.convert_hubs_to_datastores(filtered_hubs, datastores)

    def _get_folder_ds_summary(self, volume, resource_pool, datastores):
        """Get folder and best datastore summary where volume can be placed.

        :param volume: volume to place into one of the datastores
        :param resource_pool: Resource pool reference
        :param datastores: Datastores from which a choice is to be made
                           for the volume
        :return: Folder and best datastore summary where volume can be
                 placed on.
        """
        datacenter = self.volumeops.get_dc(resource_pool)
        folder = self._get_volume_group_folder(datacenter)
        storage_profile = self._get_storage_profile(volume)
        if self._storage_policy_enabled and storage_profile:
            LOG.debug(_("Storage profile required for this volume: %s."),
                      storage_profile)
            datastores = self._filter_ds_by_profile(datastores,
                                                    storage_profile)
            if not datastores:
                msg = _("Aborting since none of the datastores match the "
                        "given storage profile %s.")
                LOG.error(msg, storage_profile)
                raise error_util.VimException(msg % storage_profile)
        elif storage_profile:
            LOG.warn(_("Ignoring storage profile %s requirement for this "
                       "volume since policy based placement is "
                       "disabled."), storage_profile)

        size_bytes = volume['size'] * units.GiB
        datastore_summary = self._select_datastore_summary(size_bytes,
                                                           datastores)
        return (folder, datastore_summary)

    @staticmethod
    def _get_disk_type(volume):
        """Get disk type from volume type.

        :param volume: Volume object
        :return: Disk type
        """
        return _get_volume_type_extra_spec(volume['volume_type_id'],
                                           'vmdk_type',
                                           (THIN_VMDK_TYPE, THICK_VMDK_TYPE,
                                            EAGER_ZEROED_THICK_VMDK_TYPE),
                                           THIN_VMDK_TYPE)

    def _create_backing(self, volume, host):
        """Create volume backing under the given host.

        :param volume: Volume object
        :param host: Reference of the host
        :return: Reference to the created backing
        """
        # Get datastores and resource pool of the host
        (datastores, resource_pool) = self.volumeops.get_dss_rp(host)
        # Pick a folder and datastore to create the volume backing on
        (folder, summary) = self._get_folder_ds_summary(volume,
                                                        resource_pool,
                                                        datastores)
        disk_type = VMwareEsxVmdkDriver._get_disk_type(volume)
        size_kb = volume['size'] * units.MiB
        storage_profile = self._get_storage_profile(volume)
        profileId = None
        if self._storage_policy_enabled and storage_profile:
            profile = self.volumeops.retrieve_profile_id(storage_profile)
            if profile:
                profileId = profile.uniqueId
        return self.volumeops.create_backing(volume['name'],
                                             size_kb,
                                             disk_type, folder,
                                             resource_pool,
                                             host,
                                             summary.name,
                                             profileId)

    def _relocate_backing(self, volume, backing, host):
        pass

    def _select_ds_for_volume(self, volume):
        """Select datastore that can accommodate a volume of given size.

        Returns the selected datastore summary along with a compute host and
        its resource pool and folder where the volume can be created
        :return: (host, rp, folder, summary)
        """
        retrv_result = self.volumeops.get_hosts()
        while retrv_result:
            hosts = retrv_result.objects
            if not hosts:
                break
            (selected_host, rp, folder, summary) = (None, None, None, None)
            for host in hosts:
                host = host.obj
                try:
                    (dss, rp) = self.volumeops.get_dss_rp(host)
                    (folder, summary) = self._get_folder_ds_summary(volume,
                                                                    rp, dss)
                    selected_host = host
                    break
                except error_util.VimException as excep:
                    LOG.warn(_("Unable to find suitable datastore for volume "
                               "of size: %(vol)s GB under host: %(host)s. "
                               "More details: %(excep)s") %
                             {'vol': volume['size'],
                              'host': host, 'excep': excep})
            if selected_host:
                self.volumeops.cancel_retrieval(retrv_result)
                return (selected_host, rp, folder, summary)
            retrv_result = self.volumeops.continue_retrieval(retrv_result)

        msg = _("Unable to find host to accommodate a disk of size: %s "
                "in the inventory.") % volume['size']
        LOG.error(msg)
        raise error_util.VimException(msg)

    def _create_backing_in_inventory(self, volume):
        """Creates backing under any suitable host.

        The method tries to pick datastore that can fit the volume under
        any host in the inventory.

        :param volume: Volume object
        :return: Reference to the created backing
        """

        retrv_result = self.volumeops.get_hosts()
        while retrv_result:
            hosts = retrv_result.objects
            if not hosts:
                break
            backing = None
            for host in hosts:
                try:
                    backing = self._create_backing(volume, host.obj)
                    if backing:
                        break
                except error_util.VimException as excep:
                    LOG.warn(_("Unable to find suitable datastore for "
                               "volume: %(vol)s under host: %(host)s. "
                               "More details: %(excep)s") %
                             {'vol': volume['name'],
                              'host': host.obj, 'excep': excep})
            if backing:
                self.volumeops.cancel_retrieval(retrv_result)
                return backing
            retrv_result = self.volumeops.continue_retrieval(retrv_result)

        msg = _("Unable to create volume: %s in the inventory.")
        LOG.error(msg % volume['name'])
        raise error_util.VimException(msg % volume['name'])

    def _initialize_connection(self, volume, connector):
        """Get information of volume's backing.

        If the volume does not have a backing yet. It will be created.

        :param volume: Volume object
        :param connector: Connector information
        :return: Return connection information
        """
        connection_info = {'driver_volume_type': 'vmdk'}

        backing = self.volumeops.get_backing(volume['name'])
        if 'instance' in connector:
            # The instance exists
            instance = vim.get_moref(connector['instance'], 'VirtualMachine')
            LOG.debug(_("The instance: %s for which initialize connection "
                        "is called, exists.") % instance)
            # Get host managing the instance
            host = self.volumeops.get_host(instance)
            if not backing:
                # Create a backing in case it does not exist under the
                # host managing the instance.
                LOG.info(_("There is no backing for the volume: %s. "
                           "Need to create one.") % volume['name'])
                backing = self._create_backing(volume, host)
            else:
                # Relocate volume is necessary
                self._relocate_backing(volume, backing, host)
        else:
            # The instance does not exist
            LOG.debug(_("The instance for which initialize connection "
                        "is called, does not exist."))
            if not backing:
                # Create a backing in case it does not exist. It is a bad use
                # case to boot from an empty volume.
                LOG.warn(_("Trying to boot from an empty volume: %s.") %
                         volume['name'])
                # Create backing
                backing = self._create_backing_in_inventory(volume)

        # Set volume's moref value and name
        connection_info['data'] = {'volume': backing.value,
                                   'volume_id': volume['id']}

        LOG.info(_("Returning connection_info: %(info)s for volume: "
                   "%(volume)s with connector: %(connector)s.") %
                 {'info': connection_info,
                  'volume': volume['name'],
                  'connector': connector})

        return connection_info

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        The implementation returns the following information:
        {'driver_volume_type': 'vmdk'
         'data': {'volume': $VOLUME_MOREF_VALUE
                  'volume_id': $VOLUME_ID
                 }
        }

        :param volume: Volume object
        :param connector: Connector information
        :return: Return connection information
        """
        return self._initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        pass

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def _create_snapshot(self, snapshot):
        """Creates a snapshot.

        If the volume does not have a backing then simply pass, else create
        a snapshot.
        Snapshot of only available volume is supported.

        :param snapshot: Snapshot object
        """

        volume = snapshot['volume']
        if volume['status'] != 'available':
            msg = _("Snapshot of volume not supported in state: %s.")
            LOG.error(msg % volume['status'])
            raise exception.InvalidVolume(msg % volume['status'])
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_("There is no backing, so will not create "
                       "snapshot: %s.") % snapshot['name'])
            return
        self.volumeops.create_snapshot(backing, snapshot['name'],
                                       snapshot['display_description'])
        LOG.info(_("Successfully created snapshot: %s.") % snapshot['name'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Snapshot object
        """
        self._create_snapshot(snapshot)

    def _delete_snapshot(self, snapshot):
        """Delete snapshot.

        If the volume does not have a backing or the snapshot does not exist
        then simply pass, else delete the snapshot.
        Snapshot deletion of only available volume is supported.

        :param snapshot: Snapshot object
        """

        volume = snapshot['volume']
        if volume['status'] != 'available':
            msg = _("Delete snapshot of volume not supported in state: %s.")
            LOG.error(msg % volume['status'])
            raise exception.InvalidVolume(msg % volume['status'])
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_("There is no backing, and so there is no "
                       "snapshot: %s.") % snapshot['name'])
        else:
            self.volumeops.delete_snapshot(backing, snapshot['name'])
            LOG.info(_("Successfully deleted snapshot: %s.") %
                     snapshot['name'])

    def delete_snapshot(self, snapshot):
        """Delete snapshot.

        :param snapshot: Snapshot object
        """
        self._delete_snapshot(snapshot)

    def _create_backing_by_copying(self, volume, src_vmdk_path,
                                   src_size_in_gb):
        """Create volume backing.

        Creates a backing for the input volume and replaces its VMDK file
        with the input VMDK file copy.

        :param volume: New Volume object
        :param src_vmdk_path: VMDK file path of the source volume backing
        :param src_size_in_gb: The size of the original volume to be cloned
        in GB. The size of the target volume is saved in volume['size'].
        This parameter is used to check if the size specified by the user is
        greater than the original size. If so, the target volume should extend
        its size.
        """

        # Create a backing
        backing = self._create_backing_in_inventory(volume)
        dest_vmdk_path = self.volumeops.get_vmdk_path(backing)
        datacenter = self.volumeops.get_dc(backing)
        # Deleting the current VMDK file
        self.volumeops.delete_vmdk_file(dest_vmdk_path, datacenter)
        # Copying the source VMDK file
        self.volumeops.copy_vmdk_file(datacenter, src_vmdk_path,
                                      dest_vmdk_path)
        # If the target volume has a larger size than the source
        # volume/snapshot, we need to resize/extend the size of the
        # vmdk virtual disk to the value specified by the user.
        if volume['size'] > src_size_in_gb:
            self._extend_volumeops_virtual_disk(volume['size'], dest_vmdk_path,
                                                datacenter)
        LOG.info(_("Successfully cloned new backing: %(back)s from "
                   "source VMDK file: %(vmdk)s.") %
                 {'back': backing, 'vmdk': src_vmdk_path})

    def _create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        If source volume's backing does not exist, then pass.
        Creates a backing and replaces its VMDK file with a copy of the
        source backing's VMDK file.

        :param volume: New Volume object
        :param src_vref: Volume object that must be cloned
        """
        self._verify_volume_creation(volume)
        backing = self.volumeops.get_backing(src_vref['name'])
        if not backing:
            LOG.info(_("There is no backing for the source volume: "
                       "%(svol)s. Not creating any backing for the "
                       "volume: %(vol)s.") %
                     {'svol': src_vref['name'],
                      'vol': volume['name']})
            return
        src_vmdk_path = self.volumeops.get_vmdk_path(backing)
        self._create_backing_by_copying(volume, src_vmdk_path,
                                        src_vref['size'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        :param volume: New Volume object
        :param src_vref: Volume object that must be cloned
        """
        self._create_cloned_volume(volume, src_vref)

    def _create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If the snapshot does not exist or source volume's backing does not
        exist, then pass.
        Else creates clone of source volume backing by copying its VMDK file.

        :param volume: Volume object
        :param snapshot: Snapshot object
        """
        self._verify_volume_creation(volume)
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_("There is no backing for the source snapshot: "
                       "%(snap)s. Not creating any backing for the "
                       "volume: %(vol)s.") %
                     {'snap': snapshot['name'],
                      'vol': volume['name']})
            return
        snapshot_moref = self.volumeops.get_snapshot(backing,
                                                     snapshot['name'])
        if not snapshot_moref:
            LOG.info(_("There is no snapshot point for the snapshotted "
                       "volume: %(snap)s. Not creating any backing for "
                       "the volume: %(vol)s.") %
                     {'snap': snapshot['name'], 'vol': volume['name']})
            return
        src_vmdk_path = self.volumeops.get_vmdk_path(snapshot_moref)
        self._create_backing_by_copying(volume, src_vmdk_path,
                                        snapshot['volume_size'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: Volume object
        :param snapshot: Snapshot object
        """
        self._create_volume_from_snapshot(volume, snapshot)

    def _get_ds_name_flat_vmdk_path(self, backing, vol_name):
        """Get datastore name and folder path of the flat VMDK of the backing.

        :param backing: Reference to the backing entity
        :param vol_name: Name of the volume
        :return: datastore name and folder path of the VMDK of the backing
        """
        file_path_name = self.volumeops.get_path_name(backing)
        (datastore_name,
         folder_path, _) = volumeops.split_datastore_path(file_path_name)
        flat_vmdk_path = '%s%s-flat.vmdk' % (folder_path, vol_name)
        return (datastore_name, flat_vmdk_path)

    @staticmethod
    def _validate_disk_format(disk_format):
        """Verify vmdk as disk format.

        :param disk_format: Disk format of the image
        """
        if disk_format and disk_format.lower() != 'vmdk':
            msg = _("Cannot create image of disk format: %s. Only vmdk "
                    "disk format is accepted.") % disk_format
            LOG.error(msg)
            raise exception.ImageUnacceptable(msg)

    def _fetch_flat_image(self, context, volume, image_service, image_id,
                          image_size):
        """Creates a volume from flat glance image.

        Creates a backing for the volume under the ESX/VC server and
        copies the VMDK flat file from the glance image content.
        The method assumes glance image is VMDK disk format and its
        vmware_disktype is "sparse" or "preallocated", but not
        "streamOptimized"
        """
        # Set volume size in GB from image metadata
        volume['size'] = float(image_size) / units.GiB
        # First create empty backing in the inventory
        backing = self._create_backing_in_inventory(volume)

        try:
            (datastore_name,
             flat_vmdk_path) = self._get_ds_name_flat_vmdk_path(backing,
                                                                volume['name'])
            host = self.volumeops.get_host(backing)
            datacenter = self.volumeops.get_dc(host)
            datacenter_name = self.volumeops.get_entity_name(datacenter)
            flat_vmdk_ds_path = '[%s] %s' % (datastore_name, flat_vmdk_path)
            # Delete the *-flat.vmdk file within the backing
            self.volumeops.delete_file(flat_vmdk_ds_path, datacenter)

            # copy over image from glance into *-flat.vmdk
            timeout = self.configuration.vmware_image_transfer_timeout_secs
            host_ip = self.configuration.vmware_host_ip
            cookies = self.session.vim.client.options.transport.cookiejar
            LOG.debug(_("Fetching glance image: %(id)s to server: %(host)s.") %
                      {'id': image_id, 'host': host_ip})
            vmware_images.fetch_flat_image(context, timeout, image_service,
                                           image_id, image_size=image_size,
                                           host=host_ip,
                                           data_center_name=datacenter_name,
                                           datastore_name=datastore_name,
                                           cookies=cookies,
                                           file_path=flat_vmdk_path)
            LOG.info(_("Done copying image: %(id)s to volume: %(vol)s.") %
                     {'id': image_id, 'vol': volume['name']})
        except Exception as excep:
            err_msg = (_("Exception in copy_image_to_volume: "
                         "%(excep)s. Deleting the backing: "
                         "%(back)s.") % {'excep': excep, 'back': backing})
            # delete the backing
            self.volumeops.delete_backing(backing)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _fetch_stream_optimized_image(self, context, volume, image_service,
                                      image_id, image_size):
        """Creates volume from image using HttpNfc VM import.

        Uses Nfc API to download the VMDK file from Glance. Nfc creates the
        backing VM that wraps the VMDK in the ESX/VC inventory.
        This method assumes glance image is VMDK disk format and its
        vmware_disktype is 'streamOptimized'.
        """
        try:
            # find host in which to create the volume
            (host, rp, folder, summary) = self._select_ds_for_volume(volume)
        except error_util.VimException as excep:
            err_msg = (_("Exception in _select_ds_for_volume: "
                         "%s."), excep)
            raise exception.VolumeBackendAPIException(data=err_msg)

        size_gb = volume['size']
        LOG.debug(_("Selected datastore %(ds)s for new volume of size "
                    "%(size)s GB.") % {'ds': summary.name, 'size': size_gb})

        # prepare create spec for backing vm
        disk_type = VMwareEsxVmdkDriver._get_disk_type(volume)

        # The size of stream optimized glance image is often suspect,
        # so better let VC figure out the disk capacity during import.
        dummy_disk_size = 0
        vm_create_spec = self.volumeops._get_create_spec(volume['name'],
                                                         dummy_disk_size,
                                                         disk_type,
                                                         summary.name)
        # convert vm_create_spec to vm_import_spec
        cf = self.session.vim.client.factory
        vm_import_spec = cf.create('ns0:VirtualMachineImportSpec')
        vm_import_spec.configSpec = vm_create_spec

        try:
            # fetching image from glance will also create the backing
            timeout = self.configuration.vmware_image_transfer_timeout_secs
            host_ip = self.configuration.vmware_host_ip
            LOG.debug(_("Fetching glance image: %(id)s to server: %(host)s.") %
                      {'id': image_id, 'host': host_ip})
            vmware_images.fetch_stream_optimized_image(context, timeout,
                                                       image_service,
                                                       image_id,
                                                       session=self.session,
                                                       host=host_ip,
                                                       resource_pool=rp,
                                                       vm_folder=folder,
                                                       vm_create_spec=
                                                       vm_import_spec,
                                                       image_size=image_size)
        except exception.CinderException as excep:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Exception in copy_image_to_volume: %s."),
                              excep)
                backing = self.volumeops.get_backing(volume['name'])
                if backing:
                    LOG.exception(_("Deleting the backing: %s") % backing)
                    # delete the backing
                    self.volumeops.delete_backing(backing)

        LOG.info(_("Done copying image: %(id)s to volume: %(vol)s.") %
                 {'id': image_id, 'vol': volume['name']})

    def _extend_vmdk_virtual_disk(self, name, new_size_in_gb):
        """Extend the size of the vmdk virtual disk to the new size.

        :param name: the name of the volume
        :param new_size_in_gb: the new size the vmdk virtual disk extends to
        """
        backing = self.volumeops.get_backing(name)
        if not backing:
            LOG.info(_("The backing is not found, so there is no need "
                       "to extend the vmdk virtual disk for the volume "
                       "%s."), name)
        else:
            root_vmdk_path = self.volumeops.get_vmdk_path(backing)
            datacenter = self.volumeops.get_dc(backing)
            self._extend_volumeops_virtual_disk(new_size_in_gb, root_vmdk_path,
                                                datacenter)

    def _extend_volumeops_virtual_disk(self, new_size_in_gb, root_vmdk_path,
                                       datacenter):
        """Call the ExtendVirtualDisk_Task.

        :param new_size_in_gb: the new size the vmdk virtual disk extends to
        :param root_vmdk_path: the path for the vmdk file
        :param datacenter: reference to the datacenter
        """
        try:
            self.volumeops.extend_virtual_disk(new_size_in_gb,
                                               root_vmdk_path, datacenter)
        except error_util.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Unable to extend the size of the "
                                "vmdk virtual disk at the path %s."),
                              root_vmdk_path)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Creates volume from image.

        This method only supports Glance image of VMDK disk format.
        Uses flat vmdk file copy for "sparse" and "preallocated" disk types
        Uses HttpNfc import API for "streamOptimized" disk types. This API
        creates a backing VM that wraps the VMDK in the ESX/VC inventory.

        :param context: context
        :param volume: Volume object
        :param image_service: Glance image service
        :param image_id: Glance image id
        """
        LOG.debug(_("Copy glance image: %s to create new volume.") % image_id)
        # Record the volume size specified by the user, if the size is input
        # from the API.
        volume_size_in_gb = volume['size']
        # Verify glance image is vmdk disk format
        metadata = image_service.show(context, image_id)
        VMwareEsxVmdkDriver._validate_disk_format(metadata['disk_format'])

        # Get disk_type for vmdk disk
        disk_type = None
        image_size_in_bytes = metadata['size']
        properties = metadata['properties']
        if properties and 'vmware_disktype' in properties:
            disk_type = properties['vmware_disktype']

        try:
            if disk_type == 'streamOptimized':
                self._fetch_stream_optimized_image(context, volume,
                                                   image_service, image_id,
                                                   image_size_in_bytes)
            else:
                self._fetch_flat_image(context, volume, image_service,
                                       image_id, image_size_in_bytes)
        except exception.CinderException as excep:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Exception in copying the image to the "
                                "volume: %s."), excep)

        # image_size_in_bytes is the capacity of the image in Bytes and
        # volume_size_in_gb is the size specified by the user, if the
        # size is input from the API.
        #
        # Convert the volume_size_in_gb into bytes and compare with the
        # image size. If the volume_size_in_gb is greater, meaning the
        # user specifies a larger volume, we need to extend/resize the vmdk
        # virtual disk to the capacity specified by the user.
        if volume_size_in_gb * units.GiB > image_size_in_bytes:
            self._extend_vmdk_virtual_disk(volume['name'], volume_size_in_gb)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Creates glance image from volume.

        Upload of only available volume is supported. The uploaded glance image
        has a vmdk disk type of "streamOptimized" that can only be downloaded
        using the HttpNfc API.
        Steps followed are:
        1. Get the name of the vmdk file which the volume points to right now.
           Can be a chain of snapshots, so we need to know the last in the
           chain.
        2. Use Nfc APIs to upload the contents of the vmdk file to glance.
        """

        # if volume is attached raise exception
        if volume['instance_uuid'] or volume['attached_host']:
            msg = _("Upload to glance of attached volume is not supported.")
            LOG.error(msg)
            raise exception.InvalidVolume(msg)

        # validate disk format is vmdk
        LOG.debug(_("Copy Volume: %s to new image.") % volume['name'])
        VMwareEsxVmdkDriver._validate_disk_format(image_meta['disk_format'])

        # get backing vm of volume and its vmdk path
        backing = self.volumeops.get_backing(volume['name'])
        if not backing:
            LOG.info(_("Backing not found, creating for volume: %s") %
                     volume['name'])
            backing = self._create_backing_in_inventory(volume)
        vmdk_file_path = self.volumeops.get_vmdk_path(backing)

        # Upload image from vmdk
        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip

        vmware_images.upload_image(context, timeout, image_service,
                                   image_meta['id'],
                                   volume['project_id'],
                                   session=self.session,
                                   host=host_ip,
                                   vm=backing,
                                   vmdk_file_path=vmdk_file_path,
                                   vmdk_size=volume['size'] * units.GiB,
                                   image_name=image_meta['name'],
                                   image_version=1)
        LOG.info(_("Done copying volume %(vol)s to a new image %(img)s") %
                 {'vol': volume['name'], 'img': image_meta['name']})

    def extend_volume(self, volume, new_size):
        """Extend vmdk to new_size.

        Extends the vmdk backing to new volume size. First try to extend in
        place on the same datastore. If that fails, try to relocate the volume
        to a different datastore that can accommodate the new_size'd volume.

        :param volume: dictionary describing the existing 'available' volume
        :param new_size: new size in GB to extend this volume to
        """
        vol_name = volume['name']
        # try extending vmdk in place
        try:
            self._extend_vmdk_virtual_disk(vol_name, new_size)
            LOG.info(_("Done extending volume %(vol)s to size %(size)s GB.") %
                     {'vol': vol_name, 'size': new_size})
            return
        except error_util.VimFaultException:
            LOG.info(_("Relocating volume %s vmdk to a different "
                       "datastore since trying to extend vmdk file "
                       "in place failed."), vol_name)
        # If in place extend fails, then try to relocate the volume
        try:
            (host, rp, folder, summary) = self._select_ds_for_volume(new_size)
        except error_util.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Not able to find a different datastore to "
                                "place the extended volume %s."), vol_name)

        LOG.info(_("Selected datastore %(ds)s to place extended volume of "
                   "size %(size)s GB.") % {'ds': summary.name,
                                           'size': new_size})

        try:
            backing = self.volumeops.get_backing(vol_name)
            self.volumeops.relocate_backing(backing, summary.datastore, rp,
                                            host)
            self._extend_vmdk_virtual_disk(vol_name, new_size)
            self.volumeops.move_backing_to_folder(backing, folder)
        except error_util.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Not able to relocate volume %s for "
                                "extending."), vol_name)
        LOG.info(_("Done extending volume %(vol)s to size %(size)s GB.") %
                 {'vol': vol_name, 'size': new_size})


class VMwareVcVmdkDriver(VMwareEsxVmdkDriver):
    """Manage volumes on VMware VC server."""

    # PBM is enabled only for VC versions 5.5 and above
    PBM_ENABLED_VC_VERSION = dist_version.LooseVersion('5.5')

    def _do_deprecation_warning(self):
        # no deprecation warning for vCenter vmdk driver
        pass

    def __init__(self, *args, **kwargs):
        super(VMwareVcVmdkDriver, self).__init__(*args, **kwargs)
        self._session = None

    @property
    def session(self):
        if not self._session:
            ip = self.configuration.vmware_host_ip
            username = self.configuration.vmware_host_username
            password = self.configuration.vmware_host_password
            api_retry_count = self.configuration.vmware_api_retry_count
            task_poll_interval = self.configuration.vmware_task_poll_interval
            wsdl_loc = self.configuration.safe_get('vmware_wsdl_location')
            pbm_wsdl = self.pbm_wsdl if hasattr(self, 'pbm_wsdl') else None
            self._session = api.VMwareAPISession(ip, username,
                                                 password, api_retry_count,
                                                 task_poll_interval,
                                                 wsdl_loc=wsdl_loc,
                                                 pbm_wsdl=pbm_wsdl)
        return self._session

    def _get_pbm_wsdl_location(self, vc_version):
        """Return PBM WSDL file location corresponding to VC version."""
        if not vc_version:
            return
        ver = str(vc_version).split('.')
        major_minor = ver[0]
        if len(ver) >= 2:
            major_minor = major_minor + '.' + ver[1]
        curr_dir = os.path.abspath(os.path.dirname(__file__))
        pbm_service_wsdl = os.path.join(curr_dir, 'wsdl', major_minor,
                                        'pbmService.wsdl')
        if not os.path.exists(pbm_service_wsdl):
            LOG.warn(_("PBM WSDL file %s is missing!"), pbm_service_wsdl)
            return
        pbm_wsdl = 'file://' + pbm_service_wsdl
        LOG.info(_("Using PBM WSDL location: %s"), pbm_wsdl)
        return pbm_wsdl

    def _get_vc_version(self):
        """Connect to VC server and fetch version.

        Can be over-ridden by setting 'vmware_host_version' config.
        :returns: VC version as a LooseVersion object
        """
        version_str = self.configuration.vmware_host_version
        if version_str:
            LOG.info(_("Using overridden vmware_host_version from config: "
                       "%s"), version_str)
        else:
            version_str = self.session.vim.service_content.about.version
            LOG.info(_("Fetched VC server version: %s"), version_str)
        # convert version_str to LooseVersion and return
        version = None
        try:
            version = dist_version.LooseVersion(version_str)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Version string '%s' is not parseable"),
                              version_str)
        return version

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(VMwareVcVmdkDriver, self).do_setup(context)
        # VC specific setup is done here

        # Enable pbm only if VC version is greater than 5.5
        vc_version = self._get_vc_version()
        if vc_version and vc_version >= self.PBM_ENABLED_VC_VERSION:
            self.pbm_wsdl = self._get_pbm_wsdl_location(vc_version)
            if not self.pbm_wsdl:
                LOG.error(_("Not able to configure PBM for VC server: %s"),
                          vc_version)
                raise error_util.VMwareDriverException()
            self._storage_policy_enabled = True
            # Destroy current session so that it is recreated with pbm enabled
            self._session = None

        # recreate session and initialize volumeops
        max_objects = self.configuration.vmware_max_objects_retrieval
        self._volumeops = volumeops.VMwareVolumeOps(self.session, max_objects)

        LOG.info(_("Successfully setup driver: %(driver)s for server: "
                   "%(ip)s.") % {'driver': self.__class__.__name__,
                                 'ip': self.configuration.vmware_host_ip})

    def _get_volume_group_folder(self, datacenter):
        """Get volume group folder.

        Creates a folder under the vmFolder of the input datacenter with the
        volume group name if it does not exists.

        :param datacenter: Reference to the datacenter
        :return: Reference to the volume folder
        """
        vm_folder = super(VMwareVcVmdkDriver,
                          self)._get_volume_group_folder(datacenter)
        volume_folder = self.configuration.vmware_volume_folder
        return self.volumeops.create_folder(vm_folder, volume_folder)

    def _relocate_backing(self, volume, backing, host):
        """Relocate volume backing under host and move to volume_group folder.

        If the volume backing is on a datastore that is visible to the host,
        then need not do any operation.

        :param volume: volume to be relocated
        :param backing: Reference to the backing
        :param host: Reference to the host
        """
        # Check if volume's datastore is visible to host managing
        # the instance
        (datastores, resource_pool) = self.volumeops.get_dss_rp(host)
        datastore = self.volumeops.get_datastore(backing)

        visible_to_host = False
        for _datastore in datastores:
            if _datastore.value == datastore.value:
                visible_to_host = True
                break
        if visible_to_host:
            return

        # The volume's backing is on a datastore that is not visible to the
        # host managing the instance. We relocate the volume's backing.

        # Pick a folder and datastore to relocate volume backing to
        (folder, summary) = self._get_folder_ds_summary(volume,
                                                        resource_pool,
                                                        datastores)
        LOG.info(_("Relocating volume: %(backing)s to %(ds)s and %(rp)s.") %
                 {'backing': backing, 'ds': summary, 'rp': resource_pool})
        # Relocate the backing to the datastore and folder
        self.volumeops.relocate_backing(backing, summary.datastore,
                                        resource_pool, host)
        self.volumeops.move_backing_to_folder(backing, folder)

    @staticmethod
    def _get_clone_type(volume):
        """Get clone type from volume type.

        :param volume: Volume object
        :return: Clone type from the extra spec if present, else return
                 default 'full' clone type
        """
        return _get_volume_type_extra_spec(volume['volume_type_id'],
                                           'clone_type',
                                           (volumeops.FULL_CLONE_TYPE,
                                            volumeops.LINKED_CLONE_TYPE),
                                           volumeops.FULL_CLONE_TYPE)

    def _clone_backing(self, volume, backing, snapshot, clone_type, src_vsize):
        """Clone the backing.

        :param volume: New Volume object
        :param backing: Reference to the backing entity
        :param snapshot: Reference to the snapshot entity
        :param clone_type: type of the clone
        :param src_vsize: the size of the source volume
        """
        datastore = None
        if not clone_type == volumeops.LINKED_CLONE_TYPE:
            # Pick a datastore where to create the full clone under any host
            (host, rp, folder, summary) = self._select_ds_for_volume(volume)
            datastore = summary.datastore
        clone = self.volumeops.clone_backing(volume['name'], backing,
                                             snapshot, clone_type, datastore)
        # If the volume size specified by the user is greater than
        # the size of the source volume, the newly created volume will
        # allocate the capacity to the size of the source volume in the backend
        # VMDK datastore, though the volume information indicates it has a
        # capacity of the volume size. If the volume size is greater,
        # we need to extend/resize the capacity of the vmdk virtual disk from
        # the size of the source volume to the volume size.
        if volume['size'] > src_vsize:
            self._extend_vmdk_virtual_disk(volume['name'], volume['size'])
        LOG.info(_("Successfully created clone: %s.") % clone)

    def _create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If the snapshot does not exist or source volume's backing does not
        exist, then pass.

        :param volume: New Volume object
        :param snapshot: Reference to snapshot entity
        """
        self._verify_volume_creation(volume)
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_("There is no backing for the snapshotted volume: "
                       "%(snap)s. Not creating any backing for the "
                       "volume: %(vol)s.") %
                     {'snap': snapshot['name'], 'vol': volume['name']})
            return
        snapshot_moref = self.volumeops.get_snapshot(backing,
                                                     snapshot['name'])
        if not snapshot_moref:
            LOG.info(_("There is no snapshot point for the snapshotted "
                       "volume: %(snap)s. Not creating any backing for "
                       "the volume: %(vol)s.") %
                     {'snap': snapshot['name'], 'vol': volume['name']})
            return
        clone_type = VMwareVcVmdkDriver._get_clone_type(volume)
        self._clone_backing(volume, backing, snapshot_moref, clone_type,
                            snapshot['volume_size'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: New Volume object
        :param snapshot: Reference to snapshot entity
        """
        self._create_volume_from_snapshot(volume, snapshot)

    def _create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        If source volume's backing does not exist, then pass.
        Linked clone of attached volume is not supported.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        self._verify_volume_creation(volume)
        backing = self.volumeops.get_backing(src_vref['name'])
        if not backing:
            LOG.info(_("There is no backing for the source volume: %(src)s. "
                       "Not creating any backing for volume: %(vol)s.") %
                     {'src': src_vref['name'], 'vol': volume['name']})
            return
        clone_type = VMwareVcVmdkDriver._get_clone_type(volume)
        snapshot = None
        if clone_type == volumeops.LINKED_CLONE_TYPE:
            if src_vref['status'] != 'available':
                msg = _("Linked clone of source volume not supported "
                        "in state: %s.")
                LOG.error(msg % src_vref['status'])
                raise exception.InvalidVolume(msg % src_vref['status'])
            # For performing a linked clone, we snapshot the volume and
            # then create the linked clone out of this snapshot point.
            name = 'snapshot-%s' % volume['id']
            snapshot = self.volumeops.create_snapshot(backing, name, None)
        self._clone_backing(volume, backing, snapshot, clone_type,
                            src_vref['size'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        self._create_cloned_volume(volume, src_vref)
