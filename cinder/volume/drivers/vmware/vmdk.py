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
Volume driver for VMware vCenter managed datastores.

The volumes created by this driver are backed by VMDK (Virtual Machine
Disk) files stored in datastores. For ease of managing the VMDKs, the
driver creates a virtual machine for each of the volumes. This virtual
machine is never powered on and is often referred as the shadow VM.
"""

import math
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
from oslo_utils import uuidutils
from oslo_utils import versionutils
from oslo_vmware import api
from oslo_vmware import exceptions
from oslo_vmware import image_transfer
from oslo_vmware import pbm
from oslo_vmware import vim_util

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions
from cinder.volume.drivers.vmware import volumeops
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

THIN_VMDK_TYPE = 'thin'
THICK_VMDK_TYPE = 'thick'
EAGER_ZEROED_THICK_VMDK_TYPE = 'eagerZeroedThick'

CREATE_PARAM_ADAPTER_TYPE = 'adapter_type'
CREATE_PARAM_DISK_LESS = 'disk_less'
CREATE_PARAM_BACKING_NAME = 'name'
CREATE_PARAM_DISK_SIZE = 'disk_size'
CREATE_PARAM_TEMP_BACKING = 'temp_backing'

TMP_IMAGES_DATASTORE_FOLDER_PATH = "cinder_temp/"

EXTRA_CONFIG_VOLUME_ID_KEY = "cinder.volume.id"

EXTENSION_KEY = 'org.openstack.storage'
EXTENSION_TYPE = 'volume'

vmdk_opts = [
    cfg.StrOpt('vmware_host_ip',
               help='IP address for connecting to VMware vCenter server.'),
    cfg.PortOpt('vmware_host_port',
                default=443,
                help='Port number for connecting to VMware vCenter server.'),
    cfg.StrOpt('vmware_host_username',
               help='Username for authenticating with VMware vCenter '
                    'server.'),
    cfg.StrOpt('vmware_host_password',
               help='Password for authenticating with VMware vCenter '
                    'server.',
               secret=True),
    cfg.StrOpt('vmware_wsdl_location',
               help='Optional VIM service WSDL Location '
                    'e.g http://<server>/vimService.wsdl. Optional over-ride '
                    'to default location for bug work-arounds.'),
    cfg.IntOpt('vmware_api_retry_count',
               default=10,
               help='Number of times VMware vCenter server API must be '
                    'retried upon connection related issues.'),
    cfg.FloatOpt('vmware_task_poll_interval',
                 default=2.0,
                 help='The interval (in seconds) for polling remote tasks '
                      'invoked on VMware vCenter server.'),
    cfg.StrOpt('vmware_volume_folder',
               default='Volumes',
               help='Name of the vCenter inventory folder that will '
                    'contain Cinder volumes. This folder will be created '
                    'under "OpenStack/<project_folder>", where project_folder '
                    'is of format "Project (<volume_project_id>)".'),
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
               help='Optional string specifying the VMware vCenter server '
                    'version. '
                    'The driver attempts to retrieve the version from VMware '
                    'vCenter server. Set this configuration only if you want '
                    'to override the vCenter server version.'),
    cfg.StrOpt('vmware_tmp_dir',
               default='/tmp',
               help='Directory where virtual disks are stored during volume '
                    'backup and restore.'),
    cfg.StrOpt('vmware_ca_file',
               help='CA bundle file to use in verifying the vCenter server '
                    'certificate.'),
    cfg.BoolOpt('vmware_insecure',
                default=False,
                help='If true, the vCenter server certificate is not '
                     'verified. If false, then the default CA truststore is '
                     'used for verification. This option is ignored if '
                     '"vmware_ca_file" is set.'),
    cfg.MultiStrOpt('vmware_cluster_name',
                    help='Name of a vCenter compute cluster where volumes '
                         'should be created.'),
    cfg.MultiStrOpt('vmware_storage_profile',
                    help='Names of storage profiles to be monitored. Only '
                         'used when vmware_enable_volume_stats is True.'),
    cfg.IntOpt('vmware_connection_pool_size',
               default=10,
               help='Maximum number of connections in http connection pool.'),
    cfg.StrOpt('vmware_adapter_type',
               choices=[volumeops.VirtualDiskAdapterType.LSI_LOGIC,
                        volumeops.VirtualDiskAdapterType.BUS_LOGIC,
                        volumeops.VirtualDiskAdapterType.LSI_LOGIC_SAS,
                        volumeops.VirtualDiskAdapterType.PARA_VIRTUAL,
                        volumeops.VirtualDiskAdapterType.IDE],
               default=volumeops.VirtualDiskAdapterType.LSI_LOGIC,
               help='Default adapter type to be used for attaching volumes.'),
    cfg.StrOpt('vmware_snapshot_format',
               choices=['template', 'COW'],
               default='template',
               help='Volume snapshot format in vCenter server.'),
    cfg.BoolOpt('vmware_lazy_create',
                default=True,
                help='If true, the backend volume in vCenter server is created'
                     ' lazily when the volume is created without any source. '
                     'The backend volume is created when the volume is '
                     'attached, uploaded to image service or during backup.'),
    cfg.StrOpt('vmware_datastore_regex',
               help='Regular expression pattern to match the name of '
                    'datastores where backend volumes are created.'),
    cfg.BoolOpt('vmware_enable_volume_stats',
                default=False,
                help='If true, this enables the fetching of the volume stats '
                     'from the backend.   This has potential performance '
                     'issues at scale.  When False, the driver will not '
                     'collect ANY stats about the backend.')
]

CONF = cfg.CONF
CONF.register_opts(vmdk_opts, group=configuration.SHARED_CONF_GROUP)


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
        LOG.debug("Returning default spec value: %s.", default_value)
        return default_value

    if possible_values is None:
        return spec_value

    if spec_value in possible_values:
        LOG.debug("Returning spec value %s", spec_value)
        return spec_value

    LOG.debug("Invalid spec value: %s specified.", spec_value)


class ImageDiskType(object):
    """Supported disk types in images."""

    PREALLOCATED = "preallocated"
    SPARSE = "sparse"
    STREAM_OPTIMIZED = "streamOptimized"
    THIN = "thin"

    @staticmethod
    def is_valid(extra_spec_disk_type):
        """Check if the given disk type in extra_spec is valid.

        :param extra_spec_disk_type: disk type to check
        :return: True if valid
        """
        return extra_spec_disk_type in [ImageDiskType.PREALLOCATED,
                                        ImageDiskType.SPARSE,
                                        ImageDiskType.STREAM_OPTIMIZED,
                                        ImageDiskType.THIN]

    @staticmethod
    def validate(extra_spec_disk_type):
        """Validate the given disk type in extra_spec.

        This method throws ImageUnacceptable if the disk type is not a
        supported one.

        :param extra_spec_disk_type: disk type
        :raises: ImageUnacceptable
        """
        if not ImageDiskType.is_valid(extra_spec_disk_type):
            raise exception.ImageUnacceptable(_("Invalid disk type: %s.") %
                                              extra_spec_disk_type)


@interface.volumedriver
class VMwareVcVmdkDriver(driver.VolumeDriver):
    """Manage volumes on VMware vCenter server."""

    # 1.0 - initial version of driver
    # 1.1.0 - selection of datastore based on number of host mounts
    # 1.2.0 - storage profile volume types based placement of volumes
    # 1.3.0 - support for volume backup/restore
    # 1.4.0 - support for volume retype
    # 1.5.0 - restrict volume placement to specific vCenter clusters
    # 1.6.0 - support for manage existing
    # 1.7.0 - new config option 'vmware_connection_pool_size'
    # 1.7.1 - enforce vCenter server version 5.5
    # 2.0.0 - performance enhancements
    #       - new config option 'vmware_adapter_type'
    #       - new extra-spec option 'vmware:adapter_type'
    # 3.0.0 - vCenter storage profile ID caching
    #         support for cloning attached volume
    #         optimize volume creation from image for vCenter datastore based
    #         glance backend
    #         add 'managed by OpenStack Cinder' info to volumes in the backend
    #         support for vSphere template as volume snapshot format
    #         support for snapshot of attached volumes
    #         add storage profile ID to connection info
    #         support for revert-to-snapshot
    #         improve scalability of querying volumes in backend (bug 1600754)
    # 3.1.0 - support adapter type change using retype
    # 3.2.0 - config option to disable lazy creation of backend volume
    # 3.3.0 - config option to specify datastore name regex
    # 3.4.0 - added NFS41 as a supported datastore type
    # 3.4.1 - volume capacity stats implemented
    # 3.4.2 - deprecated option vmware_storage_profile
    # 3.4.3 - un-deprecated option vmware_storage_profile and added new
    #         option vmware_enable_volume_stats to optionally enable
    #         real get_volume_stats for proper scheduling of this driver.
    # 3.4.4 - Ensure datastores exist for storage profiles during
    #         get_volume_stats()
    VERSION = '3.4.4'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "VMware_CI"

    # Minimum supported vCenter version.
    MIN_SUPPORTED_VC_VERSION = '5.5'
    NEXT_MIN_SUPPORTED_VC_VERSION = '5.5'

    # PBM is enabled only for vCenter versions 5.5 and above
    PBM_ENABLED_VC_VERSION = '5.5'

    def __init__(self, *args, **kwargs):
        super(VMwareVcVmdkDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(vmdk_opts)
        self._session = None
        self._stats = None
        self._volumeops = None
        self._storage_policy_enabled = False
        self._ds_sel = None
        self._clusters = None
        self._dc_cache = {}
        self._ds_regex = None

    @staticmethod
    def get_driver_options():
        return vmdk_opts

    @property
    def volumeops(self):
        return self._volumeops

    @property
    def ds_sel(self):
        return self._ds_sel

    def _validate_params(self):
        # Throw error if required parameters are not set.
        required_params = ['vmware_host_ip',
                           'vmware_host_username',
                           'vmware_host_password']
        for param in required_params:
            if not getattr(self.configuration, param, None):
                reason = _("%s not set.") % param
                raise exception.InvalidInput(reason=reason)

    def check_for_setup_error(self):
        pass

    def _update_volume_stats(self):
        if self.configuration.safe_get('vmware_enable_volume_stats'):
            self._stats = self._get_volume_stats()
        else:
            self._stats = self._get_fake_stats()

    def _get_fake_stats(self):
        """Provide fake stats to the scheduler.

        :param refresh: Whether to get refreshed information
        """
        if not self._stats:
            backend_name = self.configuration.safe_get('volume_backend_name')
            if not backend_name:
                backend_name = self.__class__.__name__
            data = {'volume_backend_name': backend_name,
                    'vendor_name': 'VMware',
                    'driver_version': self.VERSION,
                    'storage_protocol': 'vmdk',
                    'reserved_percentage': 0,
                    'total_capacity_gb': 'unknown',
                    'free_capacity_gb': 'unknown',
                    'shared_targets': False}
            self._stats = data
        return self._stats

    def _get_volume_stats(self):
        """Fetch the stats about the backend.

        This can be slow at scale, but allows
        properly provisioning scheduling.
        """
        backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        data = {'volume_backend_name': backend_name,
                'vendor_name': 'VMware',
                'driver_version': self.VERSION,
                'storage_protocol': 'vmdk',
                'reserved_percentage': self.configuration.reserved_percentage,
                'shared_targets': False}
        ds_summaries = self._get_datastore_summaries()
        available_hosts = self._get_hosts(self._clusters)
        global_capacity = 0
        global_free = 0
        if ds_summaries:
            while True:
                for ds in ds_summaries.objects:
                    ds_props = self._get_object_properties(ds)
                    summary = ds_props['summary']
                    if self._is_datastore_accessible(summary,
                                                     ds_props['host'],
                                                     available_hosts):
                        global_capacity += summary.capacity
                        global_free += summary.freeSpace
                if getattr(ds_summaries, 'token', None):
                    ds_summaries = self.volumeops.continue_retrieval(
                        ds_summaries)
                else:
                    break
        data['total_capacity_gb'] = round(global_capacity / units.Gi)
        data['free_capacity_gb'] = round(global_free / units.Gi)
        self._stats = data
        return data

    def _get_datastore_summaries(self):
        client_factory = self.session.vim.client.factory
        object_specs = []
        if (self._storage_policy_enabled
                and self.configuration.vmware_storage_profile):
            # Get all available storage profiles on the vCenter and extract the
            # IDs of those that we want to observe
            profiles_ids = []
            for profile in pbm.get_all_profiles(self.session):
                if profile.name in self.configuration.vmware_storage_profile:
                    profiles_ids.append(profile.profileId)
            # Get all matching Datastores for each profile
            datastores = {}
            for profile_id in profiles_ids:
                for pbm_hub in pbm.filter_hubs_by_profile(self.session,
                                                          None,
                                                          profile_id):
                    if pbm_hub.hubType != "Datastore":
                        # We are not interested in Datastore Clusters for now
                        continue
                    if pbm_hub.hubId not in datastores:
                        # Reconstruct a managed object reference to datastore
                        datastores[pbm_hub.hubId] = vim_util.get_moref(
                            pbm_hub.hubId, "Datastore")
            # Build property collector object specs out of them
            for datastore_ref in datastores.values():
                object_specs.append(
                    vim_util.build_object_spec(client_factory,
                                               datastore_ref,
                                               []))

            if not datastores:
                LOG.warning("No Datastores found for storage profile(s) "
                            "''%s'",
                            ', '.join(
                                self.configuration.safe_get(
                                    'vmware_storage_profile')))
        else:
            # Build a catch-all object spec that would reach all datastores
            object_specs.append(
                vim_util.build_object_spec(
                    client_factory,
                    self.session.vim.service_content.rootFolder,
                    [vim_util.build_recursive_traversal_spec(client_factory)]))

        # If there are no datastores, we won't have object_specs and will
        # fail when trying to get stats
        if not object_specs:
            return

        prop_spec = vim_util.build_property_spec(client_factory, 'Datastore',
                                                 ['summary', 'host'])
        filter_spec = vim_util.build_property_filter_spec(client_factory,
                                                          prop_spec,
                                                          object_specs)
        options = client_factory.create('ns0:RetrieveOptions')
        options.maxObjects = self.configuration.vmware_max_objects_retrieval
        result = self.session.vim.RetrievePropertiesEx(
            self.session.vim.service_content.propertyCollector,
            specSet=[filter_spec],
            options=options)
        return result

    def _get_object_properties(self, obj_content):
        props = {}
        if hasattr(obj_content, 'propSet'):
            prop_set = obj_content.propSet
            if prop_set:
                props = {prop.name: prop.val for prop in prop_set}
        return props

    def _is_datastore_accessible(self, ds_summary, ds_host_mounts,
                                 available_hosts):
        # available_hosts empty => vmware_cluster_name not specified => don't
        # filter by hosts
        cluster_access_to_ds = not available_hosts
        for host_mount in ds_host_mounts.DatastoreHostMount:
            for avlbl_host in available_hosts:
                avlbl_host_value = vim_util.get_moref_value(avlbl_host)
                host_mount_key_value = vim_util.get_moref_value(host_mount.key)
                if avlbl_host_value == host_mount_key_value:
                    cluster_access_to_ds = True
        return (ds_summary.accessible
                and not self.volumeops._in_maintenance(ds_summary)
                and cluster_access_to_ds)

    def _verify_volume_creation(self, volume):
        """Verify that the volume can be created.

        Verify the vmdk type and storage profile if the volume is associated
        with a volume type.

        :param volume: Volume object
        """
        # validate disk type
        self._get_disk_type(volume)

        # validate storage profile
        profile_name = self._get_storage_profile(volume)
        if profile_name:
            self.ds_sel.get_profile_id(profile_name)

        # validate adapter type
        self._get_adapter_type(volume)

        LOG.debug("Verified disk type, adapter type and storage profile "
                  "of volume: %s.", volume.name)

    def create_volume(self, volume):
        """Creates a volume.

        We do not create any backing. We do it only the first time
        it is being attached to a virtual machine.

        :param volume: Volume object
        """
        if self.configuration.vmware_lazy_create:
            self._verify_volume_creation(volume)
        else:
            self._create_backing(volume)

    def _delete_volume(self, volume):
        """Delete the volume backing if it is present.

        :param volume: Volume object
        """
        backing = self.volumeops.get_backing(volume['name'], volume['id'])
        if not backing:
            LOG.info("Backing not available, no operation "
                     "to be performed.")
            return
        self.volumeops.delete_backing(backing)

    def delete_volume(self, volume):
        """Deletes volume backing.

        :param volume: Volume object
        """
        self._delete_volume(volume)

    def _get_extra_spec_adapter_type(self, type_id):
        adapter_type = _get_volume_type_extra_spec(
            type_id,
            'adapter_type',
            default_value=self.configuration.vmware_adapter_type)
        volumeops.VirtualDiskAdapterType.validate(adapter_type)
        return adapter_type

    def _get_adapter_type(self, volume):
        return self._get_extra_spec_adapter_type(volume['volume_type_id'])

    def _get_extra_spec_storage_profile(self, type_id):
        """Get storage profile name in the given volume type's extra spec.

        If there is no storage profile in the extra spec, default is None.
        """
        return _get_volume_type_extra_spec(type_id, 'storage_profile')

    def _get_storage_profile(self, volume):
        """Get storage profile associated with the given volume's volume_type.

        :param volume: Volume whose storage profile should be queried
        :return: String value of storage profile if volume type is associated
                 and contains storage_profile extra_spec option; None otherwise
        """
        return self._get_extra_spec_storage_profile(volume['volume_type_id'])

    @staticmethod
    def _get_extra_spec_disk_type(type_id):
        """Get disk type from the given volume type's extra spec.

        If there is no disk type option, default is THIN_VMDK_TYPE.
        """
        disk_type = _get_volume_type_extra_spec(type_id,
                                                'vmdk_type',
                                                default_value=THIN_VMDK_TYPE)
        volumeops.VirtualDiskType.validate(disk_type)
        return disk_type

    @staticmethod
    def _get_disk_type(volume):
        """Get disk type from the given volume's volume type.

        :param volume: Volume object
        :return: Disk type
        """
        return VMwareVcVmdkDriver._get_extra_spec_disk_type(
            volume['volume_type_id'])

    def _get_storage_profile_id(self, volume):
        storage_profile = self._get_storage_profile(volume)
        profile_id = None
        if self._storage_policy_enabled and storage_profile:
            profile = pbm.get_profile_id_by_name(self.session, storage_profile)
            if profile:
                profile_id = profile.uniqueId
        return profile_id

    def _get_extra_config(self, volume):
        return {EXTRA_CONFIG_VOLUME_ID_KEY: volume['id'],
                volumeops.BACKING_UUID_KEY: volume['id']}

    def _create_backing(self, volume, host=None, create_params=None):
        """Create volume backing under the given host.

        If host is unspecified, any suitable host is selected.

        :param volume: Volume object
        :param host: Reference of the host
        :param create_params: Dictionary specifying optional parameters for
                              backing VM creation
        :return: Reference to the created backing
        """
        create_params = create_params or {}
        (host_ref, resource_pool, folder,
         summary) = self._select_ds_for_volume(volume, host)

        # check if a storage profile needs to be associated with the backing VM
        profile_id = self._get_storage_profile_id(volume)

        # Use volume name as the default backing name.
        backing_name = create_params.get(CREATE_PARAM_BACKING_NAME,
                                         volume['name'])

        extra_config = self._get_extra_config(volume)
        # We shoudln't set backing UUID to volume UUID for temporary backing.
        if create_params.get(CREATE_PARAM_TEMP_BACKING):
            del extra_config[volumeops.BACKING_UUID_KEY]

        # default is a backing with single disk
        disk_less = create_params.get(CREATE_PARAM_DISK_LESS, False)
        if disk_less:
            # create a disk-less backing-- disk can be added later; for e.g.,
            # by copying an image
            return self.volumeops.create_backing_disk_less(
                backing_name,
                folder,
                resource_pool,
                host_ref,
                summary.name,
                profileId=profile_id,
                extra_config=extra_config)

        # create a backing with single disk
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)
        size_kb = volume['size'] * units.Mi
        adapter_type = create_params.get(CREATE_PARAM_ADAPTER_TYPE,
                                         self._get_adapter_type(volume))
        backing = self.volumeops.create_backing(backing_name,
                                                size_kb,
                                                disk_type,
                                                folder,
                                                resource_pool,
                                                host_ref,
                                                summary.name,
                                                profileId=profile_id,
                                                adapter_type=adapter_type,
                                                extra_config=extra_config)

        self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        return backing

    def _get_hosts(self, clusters):
        hosts = []
        if clusters:
            for cluster in clusters:
                cluster_hosts = self.volumeops.get_cluster_hosts(cluster)
                hosts.extend(cluster_hosts)
        return hosts

    def _select_datastore(self, req, host=None):
        """Selects datastore satisfying the given requirements.

        :return: (host, resource_pool, summary)
        """
        hosts = None
        if host:
            hosts = [host]
        elif self._clusters:
            hosts = self._get_hosts(self._clusters)
            if not hosts:
                LOG.error("There are no valid hosts available in "
                          "configured cluster(s): %s.", self._clusters)
                raise vmdk_exceptions.NoValidHostException()

        best_candidate = self.ds_sel.select_datastore(req, hosts=hosts)
        if not best_candidate:
            LOG.error("There is no valid datastore satisfying "
                      "requirements: %s.", req)
            raise vmdk_exceptions.NoValidDatastoreException()

        return best_candidate

    def _get_dc(self, resource_pool):
        dc = self._dc_cache.get(vim_util.get_moref_value(resource_pool))
        if not dc:
            dc = self.volumeops.get_dc(resource_pool)
            self._dc_cache[vim_util.get_moref_value(resource_pool)] = dc
        return dc

    def _select_ds_for_volume(self, volume, host=None, create_params=None):
        """Select datastore that can accommodate the given volume's backing.

        Returns the selected datastore summary along with a compute host and
        its resource pool and folder where the volume can be created
        :return: (host, resource_pool, folder, summary)
        """
        # Form requirements for datastore selection.
        create_params = create_params or {}
        size = create_params.get(CREATE_PARAM_DISK_SIZE, volume['size'])

        req = {}
        req[hub.DatastoreSelector.SIZE_BYTES] = size * units.Gi
        req[hub.DatastoreSelector.PROFILE_NAME] = self._get_storage_profile(
            volume)

        (host_ref, resource_pool, summary) = self._select_datastore(req, host)
        dc = self._get_dc(resource_pool)
        folder = self._get_volume_group_folder(dc, volume['project_id'])

        return (host_ref, resource_pool, folder, summary)

    def _get_connection_info(self, volume, backing, connector):
        connection_info = {'driver_volume_type': 'vmdk'}
        connection_info['data'] = {
            'volume': vim_util.get_moref_value(backing),
            'volume_id': volume.id,
            'name': volume.name,
            'profile_id': self._get_storage_profile_id(volume)
        }

        # vmdk connector in os-brick needs additional connection info.
        if 'platform' in connector and 'os_type' in connector:
            connection_info['data']['vmdk_size'] = volume['size'] * units.Gi

            vmdk_path = self.volumeops.get_vmdk_path(backing)
            connection_info['data']['vmdk_path'] = vmdk_path

            datastore = self.volumeops.get_datastore(backing)
            connection_info['data']['datastore'] = \
                vim_util.get_moref_value(datastore)

            datacenter = self.volumeops.get_dc(backing)
            connection_info['data']['datacenter'] = \
                vim_util.get_moref_value(datacenter)

            config = self.configuration
            vmdk_connector_config = {
                'vmware_host_ip': config.vmware_host_ip,
                'vmware_host_port': config.vmware_host_port,
                'vmware_host_username': config.vmware_host_username,
                'vmware_host_password': config.vmware_host_password,
                'vmware_api_retry_count': config.vmware_api_retry_count,
                'vmware_task_poll_interval': config.vmware_task_poll_interval,
                'vmware_ca_file': config.vmware_ca_file,
                'vmware_insecure': config.vmware_insecure,
                'vmware_tmp_dir': config.vmware_tmp_dir,
                'vmware_image_transfer_timeout_secs':
                    config.vmware_image_transfer_timeout_secs,
            }
            connection_info['data']['config'] = vmdk_connector_config

        LOG.debug("Returning connection_info (volume: '%(volume)s', volume_id:"
                  " '%(volume_id)s'), profile_id: '%(profile_id)s' for "
                  "connector: %(connector)s.",
                  {'volume': connection_info['data']['volume'],
                   'volume_id': volume.id,
                   'profile_id': connection_info['data']['profile_id'],
                   'connector': connector})

        return connection_info

    def _initialize_connection(self, volume, connector):
        """Get information of volume's backing.

        If the volume does not have a backing yet. It will be created.

        :param volume: Volume object
        :param connector: Connector information
        :return: Return connection information
        """
        backing = self.volumeops.get_backing(volume.name, volume.id)
        if 'instance' in connector:
            # The instance exists
            instance = vim_util.get_moref(connector['instance'],
                                          'VirtualMachine')
            LOG.debug("The instance: %s for which initialize connection "
                      "is called, exists.", instance)
            # Get host managing the instance
            host = self.volumeops.get_host(instance)
            if not backing:
                # Create a backing in case it does not exist under the
                # host managing the instance.
                LOG.info("There is no backing for the volume: %s. "
                         "Need to create one.", volume.name)
                backing = self._create_backing(volume, host)
            else:
                # Relocate volume is necessary
                self._relocate_backing(volume, backing, host)
        else:
            # The instance does not exist
            LOG.debug("The instance for which initialize connection "
                      "is called, does not exist.")
            if not backing:
                # Create a backing in case it does not exist. It is a bad use
                # case to boot from an empty volume.
                LOG.warning("Trying to boot from an empty volume: %s.",
                            volume.name)
                # Create backing
                backing = self._create_backing(volume)

        return self._get_connection_info(volume, backing, connector)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        The implementation returns the following information:

        .. code-block:: default

            {
                'driver_volume_type': 'vmdk',
                'data': {'volume': $VOLUME_MOREF_VALUE,
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

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def _get_snapshot_group_folder(self, volume, backing):
        dc = self.volumeops.get_dc(backing)
        return self._get_volume_group_folder(
            dc, volume.project_id, snapshot=True)

    def _create_snapshot_template_format(self, snapshot, backing):
        volume = snapshot.volume
        folder = self._get_snapshot_group_folder(volume, backing)
        datastore = self.volumeops.get_datastore(backing)

        if self._in_use(volume):
            tmp_backing = self._create_temp_backing_from_attached_vmdk(
                volume, None, None, folder, datastore, tmp_name=snapshot.name)
        else:
            tmp_backing = self.volumeops.clone_backing(
                snapshot.name, backing, None, volumeops.FULL_CLONE_TYPE,
                datastore, folder=folder)

        try:
            self.volumeops.mark_backing_as_template(tmp_backing)
        except exceptions.VimException:
            with excutils.save_and_reraise_exception():
                LOG.error("Error marking temporary backing as template.")
                self._delete_temp_backing(tmp_backing)

        return {'provider_location':
                self.volumeops.get_inventory_path(tmp_backing)}

    def _create_snapshot(self, snapshot):
        """Creates a snapshot.

        If the volume does not have a backing then simply pass, else create
        a snapshot.
        Snapshot of only available volume is supported.

        :param snapshot: Snapshot object
        """

        volume = snapshot['volume']
        snapshot_format = self.configuration.vmware_snapshot_format
        if self._in_use(volume) and snapshot_format == 'COW':
            msg = _("Snapshot of volume not supported in "
                    "state: %s.") % volume['status']
            LOG.error(msg)
            raise exception.InvalidVolume(msg)

        backing = self.volumeops.get_backing(snapshot['volume_name'],
                                             volume['id'])
        if not backing:
            LOG.info("There is no backing, so will not create "
                     "snapshot: %s.", snapshot['name'])
            return

        model_update = None
        if snapshot_format == 'COW':
            self.volumeops.create_snapshot(backing, snapshot['name'],
                                           snapshot['display_description'])
        else:
            model_update = self._create_snapshot_template_format(
                snapshot, backing)

        LOG.info("Successfully created snapshot: %s.", snapshot['name'])
        return model_update

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Snapshot object
        """
        return self._create_snapshot(snapshot)

    def _get_template_by_inv_path(self, inv_path):
        template = self.volumeops.get_entity_by_inventory_path(inv_path)
        if template is None:
            LOG.error("Template not found at path: %s.", inv_path)
            raise vmdk_exceptions.TemplateNotFoundException(path=inv_path)
        else:
            return template

    def _delete_snapshot_template_format(self, snapshot):
        template = self._get_template_by_inv_path(snapshot.provider_location)
        self.volumeops.delete_backing(template)

    def _delete_snapshot(self, snapshot):
        """Delete snapshot.

        If the volume does not have a backing or the snapshot does not exist
        then simply pass, else delete the snapshot. The volume must not be
        attached for deletion of snapshot in COW format.

        :param snapshot: Snapshot object
        """
        inv_path = snapshot.provider_location
        is_template = inv_path is not None

        backing = self.volumeops.get_backing(snapshot.volume_name,
                                             snapshot.volume.id)
        if not backing:
            LOG.debug("Backing does not exist for volume.",
                      resource=snapshot.volume)
        elif (not is_template and
                not self.volumeops.get_snapshot(backing, snapshot.name)):
            LOG.debug("Snapshot does not exist in backend.", resource=snapshot)
        elif self._in_use(snapshot.volume) and not is_template:
            msg = _("Delete snapshot of volume not supported in "
                    "state: %s.") % snapshot.volume.status
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)
        else:
            if is_template:
                self._delete_snapshot_template_format(snapshot)
            else:
                self.volumeops.delete_snapshot(backing, snapshot.name)

    def delete_snapshot(self, snapshot):
        """Delete snapshot.

        :param snapshot: Snapshot object
        """
        self._delete_snapshot(snapshot)

    def _get_ds_name_folder_path(self, backing):
        """Get datastore name and folder path of the given backing.

        :param backing: Reference to the backing entity
        :return: datastore name and folder path of the backing
        """
        vmdk_ds_file_path = self.volumeops.get_path_name(backing)
        (datastore_name,
         folder_path, _) = volumeops.split_datastore_path(vmdk_ds_file_path)
        return (datastore_name, folder_path)

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

    def _copy_image(self, context, dc_ref, image_service, image_id,
                    image_size_in_bytes, ds_name, upload_file_path):
        """Copy image (flat extent or sparse vmdk) to datastore."""

        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip
        port = self.configuration.vmware_host_port
        ca_file = self.configuration.vmware_ca_file
        insecure = self.configuration.vmware_insecure
        cookies = self.session.vim.client.cookiejar
        dc_name = self.volumeops.get_entity_name(dc_ref)

        LOG.debug("Copying image: %(image_id)s to %(path)s.",
                  {'image_id': image_id,
                   'path': upload_file_path})

        # ca_file is used for verifying vCenter certificate if it is set.
        # If ca_file is unset and insecure is False, the default CA truststore
        # is used for verification. We should pass cacerts=True in this
        # case. If ca_file is unset and insecure is True, there is no
        # certificate verification, and we should pass cacerts=False.
        cacerts = ca_file if ca_file else not insecure

        tmp_images = image_utils.TemporaryImages.for_image_service(
            image_service)
        tmp_image = tmp_images.get(context, image_id)
        if tmp_image:
            LOG.debug("Using temporary image.")
            with open(tmp_image, 'rb') as read_handle:
                image_transfer.download_file(read_handle,
                                             host_ip,
                                             port,
                                             dc_name,
                                             ds_name,
                                             cookies,
                                             upload_file_path,
                                             image_size_in_bytes,
                                             cacerts,
                                             timeout)
        else:
            image_transfer.download_flat_image(context,
                                               timeout,
                                               image_service,
                                               image_id,
                                               image_size=image_size_in_bytes,
                                               host=host_ip,
                                               port=port,
                                               data_center_name=dc_name,
                                               datastore_name=ds_name,
                                               cookies=cookies,
                                               file_path=upload_file_path,
                                               cacerts=cacerts)

        LOG.debug("Image: %(image_id)s copied to %(path)s.",
                  {'image_id': image_id,
                   'path': upload_file_path})

    def _delete_temp_disk(self, descriptor_ds_file_path, dc_ref):
        """Deletes a temporary virtual disk."""

        LOG.debug("Deleting temporary disk: %s.", descriptor_ds_file_path)
        try:
            self.volumeops.delete_vmdk_file(
                descriptor_ds_file_path, dc_ref)
        except exceptions.VimException:
            LOG.warning("Error occurred while deleting temporary disk: %s.",
                        descriptor_ds_file_path, exc_info=True)

    def _copy_temp_virtual_disk(self, src_dc_ref, src_path, dest_dc_ref,
                                dest_path):
        """Clones a temporary virtual disk and deletes it finally."""

        try:
            self.volumeops.copy_vmdk_file(
                src_dc_ref, src_path.get_descriptor_ds_file_path(),
                dest_path.get_descriptor_ds_file_path(), dest_dc_ref)
        except exceptions.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception("Error occurred while copying %(src)s to "
                              "%(dst)s.",
                              {'src': src_path.get_descriptor_ds_file_path(),
                               'dst': dest_path.get_descriptor_ds_file_path()})
        finally:
            # Delete temporary disk.
            self._delete_temp_disk(src_path.get_descriptor_ds_file_path(),
                                   src_dc_ref)

    def _get_temp_image_folder(self, image_size_in_bytes):
        """Get datastore folder for downloading temporary images."""
        # Form requirements for datastore selection.
        req = {}
        req[hub.DatastoreSelector.SIZE_BYTES] = image_size_in_bytes
        # vSAN/VVOL datastores don't support virtual disk with
        # flat extent; skip such datastores.
        req[hub.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = (
            hub.DatastoreType.get_all_types() -
            {hub.DatastoreType.VSAN, hub.DatastoreType.VVOL})

        # Select datastore satisfying the requirements.
        (host_ref, _resource_pool, summary) = self._select_datastore(req)

        ds_name = summary.name
        dc_ref = self.volumeops.get_dc(host_ref)

        # Create temporary datastore folder.
        folder_path = TMP_IMAGES_DATASTORE_FOLDER_PATH
        self.volumeops.create_datastore_folder(ds_name, folder_path, dc_ref)

        return (dc_ref, ds_name, folder_path)

    def _get_vsphere_url(self, context, image_service, image_id):
        (direct_url, _locations) = image_service.get_location(context,
                                                              image_id)
        if direct_url and direct_url.startswith('vsphere://'):
            return direct_url

    def _create_virtual_disk_from_sparse_image(
            self, context, image_service, image_id, image_size_in_bytes,
            dc_ref, ds_name, folder_path, disk_name):
        """Creates a flat extent virtual disk from sparse vmdk image."""

        # Upload the image to a temporary virtual disk.
        src_disk_name = uuidutils.generate_uuid()
        src_path = volumeops.MonolithicSparseVirtualDiskPath(ds_name,
                                                             folder_path,
                                                             src_disk_name)

        LOG.debug("Creating temporary virtual disk: %(path)s from sparse vmdk "
                  "image: %(image_id)s.",
                  {'path': src_path.get_descriptor_ds_file_path(),
                   'image_id': image_id})

        vsphere_url = self._get_vsphere_url(context, image_service,
                                            image_id)
        if vsphere_url:
            self.volumeops.copy_datastore_file(
                vsphere_url, dc_ref, src_path.get_descriptor_ds_file_path())
        else:
            self._copy_image(context, dc_ref, image_service, image_id,
                             image_size_in_bytes, ds_name,
                             src_path.get_descriptor_file_path())

        # Copy sparse disk to create a flat extent virtual disk.
        dest_path = volumeops.FlatExtentVirtualDiskPath(ds_name,
                                                        folder_path,
                                                        disk_name)
        self._copy_temp_virtual_disk(dc_ref, src_path, dc_ref, dest_path)
        LOG.debug("Created virtual disk: %s from sparse vmdk image.",
                  dest_path.get_descriptor_ds_file_path())
        return dest_path

    def _create_virtual_disk_from_preallocated_image(
            self, context, image_service, image_id, image_size_in_bytes,
            dest_dc_ref, dest_ds_name, dest_folder_path, dest_disk_name,
            adapter_type):
        """Creates virtual disk from an image which is a flat extent."""

        # Upload the image and use it as a flat extent to create a virtual
        # disk. First, find the datastore folder to download the image.
        (dc_ref, ds_name,
         folder_path) = self._get_temp_image_folder(image_size_in_bytes)

        # pylint: disable=E1101
        dc_ref_value = vim_util.get_moref_value(dc_ref)
        dest_dc_ref_value = vim_util.get_moref_value(dest_dc_ref)
        if ds_name == dest_ds_name and dc_ref_value == dest_dc_ref_value:
            # Temporary image folder and destination path are on the same
            # datastore. We can directly download the image to the destination
            # folder to save one virtual disk copy.
            path = volumeops.FlatExtentVirtualDiskPath(dest_ds_name,
                                                       dest_folder_path,
                                                       dest_disk_name)
            dest_path = path
        else:
            # Use the image to create a temporary virtual disk which is then
            # copied to the destination folder.
            disk_name = uuidutils.generate_uuid()
            path = volumeops.FlatExtentVirtualDiskPath(ds_name,
                                                       folder_path,
                                                       disk_name)
            dest_path = volumeops.FlatExtentVirtualDiskPath(dest_ds_name,
                                                            dest_folder_path,
                                                            dest_disk_name)

        LOG.debug("Creating virtual disk: %(path)s from (flat extent) image: "
                  "%(image_id)s.",
                  {'path': path.get_descriptor_ds_file_path(),
                   'image_id': image_id})

        # We first create a descriptor with desired settings.
        self.volumeops.create_flat_extent_virtual_disk_descriptor(
            dc_ref, path, image_size_in_bytes // units.Ki, adapter_type,
            EAGER_ZEROED_THICK_VMDK_TYPE)
        # Upload the image and use it as the flat extent.
        try:
            vsphere_url = self._get_vsphere_url(context, image_service,
                                                image_id)
            if vsphere_url:
                self.volumeops.copy_datastore_file(
                    vsphere_url, dc_ref, path.get_flat_extent_ds_file_path())
            else:
                self._copy_image(context, dc_ref, image_service, image_id,
                                 image_size_in_bytes, ds_name,
                                 path.get_flat_extent_file_path())
        except Exception:
            # Delete the descriptor.
            with excutils.save_and_reraise_exception():
                LOG.exception("Error occurred while copying image: "
                              "%(image_id)s to %(path)s.",
                              {'path': path.get_descriptor_ds_file_path(),
                               'image_id': image_id})
                LOG.debug("Deleting descriptor: %s.",
                          path.get_descriptor_ds_file_path())
                try:
                    self.volumeops.delete_file(
                        path.get_descriptor_ds_file_path(), dc_ref)
                except exceptions.VimException:
                    LOG.warning("Error occurred while deleting "
                                "descriptor: %s.",
                                path.get_descriptor_ds_file_path(),
                                exc_info=True)

        if dest_path != path:
            # Copy temporary disk to given destination.
            self._copy_temp_virtual_disk(dc_ref, path, dest_dc_ref, dest_path)

        LOG.debug("Created virtual disk: %s from flat extent image.",
                  dest_path.get_descriptor_ds_file_path())
        return dest_path

    def _check_disk_conversion(self, image_disk_type, extra_spec_disk_type):
        """Check if disk type conversion is needed."""

        if image_disk_type == ImageDiskType.SPARSE:
            # We cannot reliably determine the destination disk type of a
            # virtual disk copied from a sparse image.
            return True
        # Virtual disk created from flat extent is always of type
        # eagerZeroedThick.
        return not (volumeops.VirtualDiskType.get_virtual_disk_type(
                    extra_spec_disk_type) ==
                    volumeops.VirtualDiskType.EAGER_ZEROED_THICK)

    def _delete_temp_backing(self, backing):
        """Deletes temporary backing."""

        LOG.debug("Deleting backing: %s.", backing)
        try:
            self.volumeops.delete_backing(backing)
        except exceptions.VimException:
            LOG.warning("Error occurred while deleting backing: %s.",
                        backing, exc_info=True)

    def _create_volume_from_non_stream_optimized_image(
            self, context, volume, image_service, image_id,
            image_size_in_bytes, adapter_type, image_disk_type):
        """Creates backing VM from non-streamOptimized image.

        First, we create a disk-less backing. Then we create a virtual disk
        using the image which is then attached to the backing VM. Finally, the
        backing VM is cloned if disk type conversion is required.
        """
        # We should use the disk type in volume type for backing's virtual
        # disk.
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)

        # First, create a disk-less backing.
        create_params = {CREATE_PARAM_DISK_LESS: True}

        disk_conversion = self._check_disk_conversion(image_disk_type,
                                                      disk_type)
        if disk_conversion:
            # The initial backing is a temporary one and used as the source
            # for clone operation.
            disk_name = uuidutils.generate_uuid()
            create_params[CREATE_PARAM_BACKING_NAME] = disk_name
            create_params[CREATE_PARAM_TEMP_BACKING] = True
        else:
            disk_name = volume['name']

        LOG.debug("Creating disk-less backing for volume: %(id)s with params: "
                  "%(param)s.",
                  {'id': volume['id'],
                   'param': create_params})
        backing = self._create_backing(volume, create_params=create_params)

        try:
            # Find the backing's datacenter, host, datastore and folder.
            (ds_name, folder_path) = self._get_ds_name_folder_path(backing)
            host = self.volumeops.get_host(backing)
            dc_ref = self.volumeops.get_dc(host)

            vmdk_path = None
            attached = False

            # Create flat extent virtual disk from the image.
            if image_disk_type == ImageDiskType.SPARSE:
                # Monolithic sparse image has embedded descriptor.
                vmdk_path = self._create_virtual_disk_from_sparse_image(
                    context, image_service, image_id, image_size_in_bytes,
                    dc_ref, ds_name, folder_path, disk_name)
            else:
                # The image is just a flat extent.
                vmdk_path = self._create_virtual_disk_from_preallocated_image(
                    context, image_service, image_id, image_size_in_bytes,
                    dc_ref, ds_name, folder_path, disk_name, adapter_type)

            # Attach the virtual disk to the backing.
            LOG.debug("Attaching virtual disk: %(path)s to backing: "
                      "%(backing)s.",
                      {'path': vmdk_path.get_descriptor_ds_file_path(),
                       'backing': backing})

            profile_id = self._get_storage_profile_id(volume)
            self.volumeops.attach_disk_to_backing(
                backing,
                image_size_in_bytes // units.Ki, disk_type,
                adapter_type,
                profile_id,
                vmdk_path.get_descriptor_ds_file_path())
            attached = True

            if disk_conversion:
                # Clone the temporary backing for disk type conversion.
                (host, rp, folder, summary) = self._select_ds_for_volume(
                    volume)
                datastore = summary.datastore
                LOG.debug("Cloning temporary backing: %s for disk type "
                          "conversion.", backing)
                extra_config = self._get_extra_config(volume)
                clone = self.volumeops.clone_backing(volume['name'],
                                                     backing,
                                                     None,
                                                     volumeops.FULL_CLONE_TYPE,
                                                     datastore,
                                                     disk_type=disk_type,
                                                     host=host,
                                                     resource_pool=rp,
                                                     extra_config=extra_config,
                                                     folder=folder)
                self._delete_temp_backing(backing)
                backing = clone

            self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        except Exception:
            # Delete backing and virtual disk created from image.
            with excutils.save_and_reraise_exception():
                LOG.exception("Error occurred while creating "
                              "volume: %(id)s"
                              " from image: %(image_id)s.",
                              {'id': volume['id'],
                               'image_id': image_id})
                self._delete_temp_backing(backing)
                # Delete virtual disk if exists and unattached.
                if vmdk_path is not None and not attached:
                    self._delete_temp_disk(
                        vmdk_path.get_descriptor_ds_file_path(), dc_ref)

    def _fetch_stream_optimized_image(self, context, volume, image_service,
                                      image_id, image_size, adapter_type):
        """Creates volume from image using HttpNfc VM import.

        Uses Nfc API to download the VMDK file from Glance. Nfc creates the
        backing VM that wraps the VMDK in the vCenter inventory.
        This method assumes glance image is VMDK disk format and its
        vmware_disktype is 'streamOptimized'.
        """
        try:
            # find host in which to create the volume
            (_host, rp, folder, summary) = self._select_ds_for_volume(volume)
        except exceptions.VimException as excep:
            err_msg = (_("Exception in _select_ds_for_volume: "
                         "%s."), excep)
            raise exception.VolumeBackendAPIException(data=err_msg)

        size_gb = volume['size']
        LOG.debug("Selected datastore %(ds)s for new volume of size "
                  "%(size)s GB.", {'ds': summary.name, 'size': size_gb})

        # prepare create spec for backing vm
        profile_id = self._get_storage_profile_id(volume)
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)

        # The size of stream optimized glance image is often suspect,
        # so better let vCenter figure out the disk capacity during import.
        dummy_disk_size = 0
        extra_config = self._get_extra_config(volume)
        vm_create_spec = self.volumeops.get_create_spec(
            volume['name'],
            dummy_disk_size,
            disk_type,
            summary.name,
            profile_id=profile_id,
            adapter_type=adapter_type,
            extra_config=extra_config)
        # convert vm_create_spec to vm_import_spec
        cf = self.session.vim.client.factory
        vm_import_spec = cf.create('ns0:VirtualMachineImportSpec')
        vm_import_spec.configSpec = vm_create_spec

        try:
            # fetching image from glance will also create the backing
            timeout = self.configuration.vmware_image_transfer_timeout_secs
            host_ip = self.configuration.vmware_host_ip
            port = self.configuration.vmware_host_port
            LOG.debug("Fetching glance image: %(id)s to server: %(host)s.",
                      {'id': image_id, 'host': host_ip})
            backing = image_transfer.download_stream_optimized_image(
                context,
                timeout,
                image_service,
                image_id,
                session=self.session,
                host=host_ip,
                port=port,
                resource_pool=rp,
                vm_folder=folder,
                vm_import_spec=vm_import_spec,
                image_size=image_size,
                http_method='POST')
            self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        except (exceptions.VimException,
                exceptions.VMwareDriverException):
            with excutils.save_and_reraise_exception():
                LOG.exception("Error occurred while copying image: %(id)s "
                              "to volume: %(vol)s.",
                              {'id': image_id, 'vol': volume['name']})
                backing = self.volumeops.get_backing(volume['name'],
                                                     volume['id'])
                if backing:
                    # delete the backing
                    self.volumeops.delete_backing(backing)

        LOG.info("Done copying image: %(id)s to volume: %(vol)s.",
                 {'id': image_id, 'vol': volume['name']})

    def _extend_backing(self, backing, new_size_in_gb, disk_type):
        """Extend volume backing's virtual disk.

        :param backing: volume backing
        :param new_size_in_gb: new size of virtual disk
        """
        root_vmdk_path = self.volumeops.get_vmdk_path(backing)
        datacenter = self.volumeops.get_dc(backing)
        eager_zero = disk_type == EAGER_ZEROED_THICK_VMDK_TYPE
        self.volumeops.extend_virtual_disk(new_size_in_gb, root_vmdk_path,
                                           datacenter, eager_zero)

    def clone_image(self, context, volume, image_location, image_meta,
                    image_service):
        """Clone image directly to a volume."""
        ret = self.copy_image_to_volume(
            context, volume, image_service, image_meta['id'])
        return (ret, True)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Creates volume from image.

        This method only supports Glance image of VMDK disk format.
        Uses flat vmdk file copy for "sparse" and "preallocated" disk types
        Uses HttpNfc import API for "streamOptimized" disk types. This API
        creates a backing VM that wraps the VMDK in the vCenter inventory.

        :param context: context
        :param volume: Volume object
        :param image_service: Glance image service
        :param image_id: Glance image id
        """
        LOG.debug("Copy glance image: %s to create new volume.", image_id)

        # Verify glance image is vmdk disk format
        metadata = image_service.show(context, image_id)
        VMwareVcVmdkDriver._validate_disk_format(metadata['disk_format'])

        # Validate container format; only 'bare' and 'ova' are supported.
        container_format = metadata.get('container_format')
        if (container_format and container_format not in ['bare', 'ova']):
            msg = _("Container format: %s is unsupported, only 'bare' and "
                    "'ova' are supported.") % container_format
            LOG.error(msg)
            raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

        # Get the disk type, adapter type and size of vmdk image
        image_disk_type = ImageDiskType.PREALLOCATED
        image_adapter_type = self._get_adapter_type(volume)
        image_size_in_bytes = metadata['size']
        properties = metadata['properties']
        if properties:
            if 'vmware_disktype' in properties:
                image_disk_type = properties['vmware_disktype']
            if 'vmware_adaptertype' in properties:
                image_adapter_type = properties['vmware_adaptertype']

        try:
            # validate disk and adapter types in image meta-data
            volumeops.VirtualDiskAdapterType.validate(image_adapter_type)
            ImageDiskType.validate(image_disk_type)

            if image_disk_type == ImageDiskType.STREAM_OPTIMIZED:
                self._fetch_stream_optimized_image(context, volume,
                                                   image_service, image_id,
                                                   image_size_in_bytes,
                                                   image_adapter_type)
            else:
                self._create_volume_from_non_stream_optimized_image(
                    context, volume, image_service, image_id,
                    image_size_in_bytes, image_adapter_type, image_disk_type)
        except (exceptions.VimException,
                exceptions.VMwareDriverException):
            with excutils.save_and_reraise_exception():
                LOG.exception("Error occurred while copying image: %(id)s "
                              "to volume: %(vol)s.",
                              {'id': image_id, 'vol': volume['name']})

        LOG.debug("Volume: %(id)s created from image: %(image_id)s.",
                  {'id': volume['id'],
                   'image_id': image_id})

        # If the user-specified volume size is greater than backing's
        # current disk size, we should extend the disk.
        volume_size = volume['size'] * units.Gi
        backing = self.volumeops.get_backing(volume['name'], volume['id'])
        disk_size = self.volumeops.get_disk_size(backing)
        if volume_size > disk_size:
            LOG.debug("Extending volume: %(name)s since the user specified "
                      "volume size (bytes): %(vol_size)d is greater than "
                      "backing's current disk size (bytes): %(disk_size)d.",
                      {'name': volume['name'],
                       'vol_size': volume_size,
                       'disk_size': disk_size})
            self._extend_backing(backing, volume['size'],
                                 VMwareVcVmdkDriver._get_disk_type(volume))
        # TODO(vbala): handle volume_size < disk_size case.

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Creates glance image from volume.

        Upload of only available volume is supported. The uploaded glance image
        has a vmdk disk type of "streamOptimized" that can only be downloaded
        using the HttpNfc API.
        Steps followed are:
        1. Get the name of the vmdk file which the volume points to right
        now. Can be a chain of snapshots, so we need to know the last in the
        chain.
        2. Use Nfc APIs to upload the contents of the vmdk file to glance.
        """

        # if volume is attached raise exception
        if self._in_use(volume):
            msg = _("Upload to glance of attached volume is not supported.")
            LOG.error(msg)
            raise exception.InvalidVolume(msg)

        # validate disk format is vmdk
        LOG.debug("Copy Volume: %s to new image.", volume['name'])
        VMwareVcVmdkDriver._validate_disk_format(image_meta['disk_format'])

        # get backing vm of volume and its vmdk path
        backing = self.volumeops.get_backing(volume['name'], volume['id'])
        if not backing:
            LOG.info("Backing not found, creating for volume: %s",
                     volume['name'])
            backing = self._create_backing(volume)
        vmdk_file_path = self.volumeops.get_vmdk_path(backing)

        # Upload image from vmdk
        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip
        port = self.configuration.vmware_host_port

        # retrieve store information from extra-specs
        store_id = volume.volume_type.extra_specs.get('image_service:store_id')

        # TODO (whoami-rajat): Remove store_id and base_image_ref
        #  parameters when oslo.vmware calls volume_utils wrapper of
        #  upload_volume instead of image_utils.upload_volume
        image_transfer.upload_image(context,
                                    timeout,
                                    image_service,
                                    image_meta['id'],
                                    volume['project_id'],
                                    session=self.session,
                                    host=host_ip,
                                    port=port,
                                    vm=backing,
                                    vmdk_file_path=vmdk_file_path,
                                    vmdk_size=volume['size'] * units.Gi,
                                    image_name=image_meta['name'],
                                    image_version=1,
                                    store_id=store_id,
                                    base_image_ref=
                                    volume_utils.get_base_image_ref(volume))
        LOG.info("Done copying volume %(vol)s to a new image %(img)s",
                 {'vol': volume['name'], 'img': image_meta['name']})

    def _in_use(self, volume):
        """Check if the given volume is in use."""
        return (volume['volume_attachment'] and
                len(volume['volume_attachment']) > 0)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        The retype is performed only if the volume is not in use. Retype is NOP
        if the backing doesn't exist. If disk type conversion is needed, the
        volume is cloned. If disk type conversion is needed and the volume
        contains snapshots, the backing is relocated instead of cloning. The
        backing is also relocated if the current datastore is not compliant
        with the new storage profile (if any). Finally, the storage profile of
        the backing VM is updated.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to retype
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities (unused)
        :returns: True if the retype occurred; False otherwise.
        """
        # Can't attempt retype if the volume is in use.
        if self._in_use(volume):
            LOG.warning("Volume: %s is in use, can't retype.",
                        volume['name'])
            return False

        # If the backing doesn't exist, retype is NOP.
        backing = self.volumeops.get_backing(volume['name'], volume['id'])
        if backing is None:
            LOG.debug("Backing for volume: %s doesn't exist; retype is NOP.",
                      volume['name'])
            return True

        # Check whether we need disk type conversion.
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)
        new_disk_type = VMwareVcVmdkDriver._get_extra_spec_disk_type(
            new_type['id'])
        need_disk_type_conversion = disk_type != new_disk_type

        # Check whether we need to relocate the backing. If the backing
        # contains snapshots, relocate is the only way to achieve disk type
        # conversion.
        need_relocate = (need_disk_type_conversion and
                         self.volumeops.snapshot_exists(backing))

        datastore = self.volumeops.get_datastore(backing)

        # Check whether we need to change the storage profile.
        need_profile_change = False
        is_compliant = True
        new_profile = None
        if self._storage_policy_enabled:
            profile = self._get_storage_profile(volume)
            new_profile = self._get_extra_spec_storage_profile(new_type['id'])
            need_profile_change = profile != new_profile
            # The current datastore may be compliant with the new profile.
            is_compliant = self.ds_sel.is_datastore_compliant(datastore,
                                                              new_profile)

        # No need to relocate or clone if there is no disk type conversion and
        # the current datastore is compliant with the new profile or storage
        # policy is disabled.
        if not need_disk_type_conversion and is_compliant:
            LOG.debug("Backing: %(backing)s for volume: %(name)s doesn't need "
                      "disk type conversion.",
                      {'backing': backing,
                       'name': volume['name']})
            if self._storage_policy_enabled:
                LOG.debug("Backing: %(backing)s for volume: %(name)s is "
                          "compliant with the new profile: %(new_profile)s.",
                          {'backing': backing,
                           'name': volume['name'],
                           'new_profile': new_profile})
        else:
            # Set requirements for datastore selection.
            req = {}
            req[hub.DatastoreSelector.SIZE_BYTES] = (volume['size'] *
                                                     units.Gi)

            if need_relocate:
                LOG.debug("Backing: %s should be relocated.", backing)
                req[hub.DatastoreSelector.HARD_ANTI_AFFINITY_DS] = (
                    [vim_util.get_moref_value(datastore)])

            if new_profile:
                req[hub.DatastoreSelector.PROFILE_NAME] = new_profile

            # Select datastore satisfying the requirements.
            try:
                best_candidate = self._select_datastore(req)
            except vmdk_exceptions.NoValidDatastoreException:
                # No candidate datastores; can't retype.
                LOG.warning("There are no datastores matching new "
                            "requirements; can't retype volume: %s.",
                            volume['name'])
                return False

            (host, rp, summary) = best_candidate
            dc = self._get_dc(rp)
            folder = self._get_volume_group_folder(dc, volume['project_id'])
            new_datastore = summary.datastore
            datastore_value = vim_util.get_moref_value(datastore)
            new_datastore_value = vim_util.get_moref_value(new_datastore)
            if datastore_value != new_datastore_value:
                # Datastore changed; relocate the backing.
                LOG.debug("Backing: %s needs to be relocated for retype.",
                          backing)
                self.volumeops.relocate_backing(
                    backing, new_datastore, rp, host, new_disk_type)
                self.volumeops.move_backing_to_folder(backing, folder)
            elif need_disk_type_conversion:
                # Same datastore, but clone is needed for disk type conversion.
                LOG.debug("Backing: %s needs to be cloned for retype.",
                          backing)

                new_backing = None
                renamed = False
                tmp_name = uuidutils.generate_uuid()
                try:
                    self.volumeops.rename_backing(backing, tmp_name)
                    renamed = True

                    new_backing = self.volumeops.clone_backing(
                        volume['name'], backing, None,
                        volumeops.FULL_CLONE_TYPE, datastore,
                        disk_type=new_disk_type, host=host,
                        resource_pool=rp, folder=folder)
                    self._delete_temp_backing(backing)
                    backing = new_backing
                    self.volumeops.update_backing_uuid(backing, volume['id'])
                    self.volumeops.update_backing_disk_uuid(backing,
                                                            volume['id'])
                except exceptions.VimException:
                    with excutils.save_and_reraise_exception():
                        LOG.exception("Error occurred while cloning backing: "
                                      "%s during retype.",
                                      backing)
                        if renamed and not new_backing:
                            LOG.debug("Undo rename of backing: %(backing)s; "
                                      "changing name from %(new_name)s to "
                                      "%(old_name)s.",
                                      {'backing': backing,
                                       'new_name': tmp_name,
                                       'old_name': volume['name']})
                            try:
                                self.volumeops.rename_backing(backing,
                                                              volume['name'])
                            except exceptions.VimException:
                                LOG.warning("Changing backing: "
                                            "%(backing)s name from "
                                            "%(new_name)s to %(old_name)s "
                                            "failed.",
                                            {'backing': backing,
                                             'new_name': tmp_name,
                                             'old_name': volume['name']})

        adapter_type = self._get_adapter_type(volume)
        new_adapter_type = self._get_extra_spec_adapter_type(new_type['id'])
        if new_adapter_type != adapter_type:
            LOG.debug("Changing volume: %(name)s adapter type from "
                      "%(adapter_type)s to %(new_adapter_type)s.",
                      {'name': volume['name'],
                       'adapter_type': adapter_type,
                       'new_adapter_type': new_adapter_type})
            disk_device = self.volumeops._get_disk_device(backing)
            self.volumeops.detach_disk_from_backing(backing, disk_device)
            self.volumeops.attach_disk_to_backing(
                backing, disk_device.capacityInKB, new_disk_type,
                new_adapter_type, None, disk_device.backing.fileName)

        # Update the backing's storage profile if needed.
        if need_profile_change:
            LOG.debug("Backing: %(backing)s needs a profile change to:"
                      " %(profile)s.",
                      {'backing': backing,
                       'profile': new_profile})
            profile_id = None
            if new_profile is not None:
                profile_id = self.ds_sel.get_profile_id(new_profile)
            self.volumeops.change_backing_profile(backing, profile_id)

        # Retype is done.
        LOG.debug("Volume: %s retype is done.", volume['name'])
        return True

    def extend_volume(self, volume, new_size):
        """Extend volume to new size.

        Extends the volume backing's virtual disk to new size. First, try to
        extend in place on the same datastore. If that fails due to
        insufficient disk space, then try to relocate the volume to a different
        datastore that can accommodate the backing with new size and retry
        extend.

        :param volume: dictionary describing the existing 'available' volume
        :param new_size: new size in GB to extend this volume to
        """
        vol_name = volume['name']
        backing = self.volumeops.get_backing(vol_name, volume['id'])
        if not backing:
            LOG.info("There is no backing for volume: %s; no need to "
                     "extend the virtual disk.", vol_name)
            return

        # try extending vmdk in place
        try:
            self._extend_backing(backing, new_size,
                                 VMwareVcVmdkDriver._get_disk_type(volume))
            LOG.info("Successfully extended volume: %(vol)s to size: "
                     "%(size)s GB.",
                     {'vol': vol_name, 'size': new_size})
            return
        except exceptions.NoDiskSpaceException:
            LOG.warning("Unable to extend volume: %(vol)s to size: "
                        "%(size)s on current datastore due to insufficient"
                        " space.",
                        {'vol': vol_name, 'size': new_size})

        # Insufficient disk space; relocate the volume to a different datastore
        # and retry extend.
        LOG.info("Relocating volume: %s to a different datastore due to "
                 "insufficient disk space on current datastore.",
                 vol_name)
        try:
            create_params = {CREATE_PARAM_DISK_SIZE: new_size}
            (host, rp, folder, summary) = self._select_ds_for_volume(
                volume, create_params=create_params)
            self.volumeops.relocate_backing(backing, summary.datastore, rp,
                                            host)
            self.volumeops.move_backing_to_folder(backing, folder)
            self._extend_backing(backing, new_size,
                                 VMwareVcVmdkDriver._get_disk_type(volume))
        except exceptions.VMwareDriverException:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to extend volume: %(vol)s to size: "
                          "%(size)s GB.",
                          {'vol': vol_name, 'size': new_size})

        LOG.info("Successfully extended volume: %(vol)s to size: "
                 "%(size)s GB.",
                 {'vol': vol_name, 'size': new_size})

    def _get_disk_device(self, vmdk_path, vm_inv_path):
        # Get the VM that corresponds to the given inventory path.
        vm = self.volumeops.get_entity_by_inventory_path(vm_inv_path)
        if vm:
            # Get the disk device that corresponds to the given vmdk path.
            disk_device = self.volumeops.get_disk_device(vm, vmdk_path)
            if disk_device:
                return (vm, disk_device)

    def _get_existing(self, existing_ref):
        src_name = existing_ref.get('source-name')
        if not src_name:
            raise exception.InvalidInput(
                reason=_("source-name cannot be empty."))

        # source-name format: vmdk_path@vm_inventory_path
        parts = src_name.split('@')
        if len(parts) != 2:
            raise exception.InvalidInput(
                reason=_("source-name format should be: "
                         "'vmdk_path@vm_inventory_path'."))

        (vmdk_path, vm_inv_path) = parts
        existing = self._get_disk_device(vmdk_path, vm_inv_path)
        if not existing:
            reason = _("%s does not exist.") % src_name
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        return existing

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of the volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume: Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        (_vm, disk) = self._get_existing(existing_ref)
        return int(math.ceil(disk.capacityInKB * units.Ki / float(units.Gi)))

    def _manage_existing_int(self, volume, vm, disk):
        LOG.debug("Creating volume from disk: %(disk)s attached to %(vm)s.",
                  {'disk': disk, 'vm': vm})
        # Create a backing for the volume.
        create_params = {CREATE_PARAM_DISK_LESS: True}
        backing = self._create_backing(volume, create_params=create_params)

        # Detach the disk to be managed from the source VM.
        self.volumeops.detach_disk_from_backing(vm, disk)

        # Move the disk to the datastore folder of volume backing.
        src_dc = self.volumeops.get_dc(vm)
        dest_dc = self.volumeops.get_dc(backing)
        (ds_name, folder_path) = self._get_ds_name_folder_path(backing)
        dest_path = volumeops.VirtualDiskPath(
            ds_name, folder_path, volume['name'])
        self.volumeops.move_vmdk_file(src_dc,
                                      disk.backing.fileName,
                                      dest_path.get_descriptor_ds_file_path(),
                                      dest_dc_ref=dest_dc)

        # Attach the disk to be managed to volume backing.
        profile_id = self._get_storage_profile_id(volume)
        self.volumeops.attach_disk_to_backing(
            backing,
            disk.capacityInKB,
            VMwareVcVmdkDriver._get_disk_type(volume),
            self._get_adapter_type(volume),
            profile_id,
            dest_path.get_descriptor_ds_file_path())
        self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        return backing

    def manage_existing(self, volume, existing_ref):
        """Brings an existing virtual disk under Cinder management.

        Detaches the virtual disk identified by existing_ref and attaches
        it to a volume backing.

        :param volume: Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        (vm, disk) = self._get_existing(existing_ref)
        self._manage_existing_int(volume, vm, disk)

    def unmanage(self, volume):
        backing = self.volumeops.get_backing(volume['name'], volume['id'])
        if backing:
            extra_config = self._get_extra_config(volume)
            for key in extra_config:
                extra_config[key] = ''
            self.volumeops.update_backing_extra_config(backing, extra_config)

    @property
    def session(self):
        return self._session

    def _create_session(self):
        ip = self.configuration.vmware_host_ip
        port = self.configuration.vmware_host_port
        username = self.configuration.vmware_host_username
        password = self.configuration.vmware_host_password
        api_retry_count = self.configuration.vmware_api_retry_count
        task_poll_interval = self.configuration.vmware_task_poll_interval
        wsdl_loc = self.configuration.safe_get('vmware_wsdl_location')
        ca_file = self.configuration.vmware_ca_file
        insecure = self.configuration.vmware_insecure
        pool_size = self.configuration.vmware_connection_pool_size
        session = api.VMwareAPISession(ip,
                                       username,
                                       password,
                                       api_retry_count,
                                       task_poll_interval,
                                       wsdl_loc=wsdl_loc,
                                       port=port,
                                       cacert=ca_file,
                                       insecure=insecure,
                                       pool_size=pool_size,
                                       op_id_prefix='c-vol')
        return session

    def _get_vc_version(self):
        """Connect to vCenter server and fetch version.

        Can be over-ridden by setting 'vmware_host_version' config.
        :returns: vCenter version as a LooseVersion object
        """
        version_str = self.configuration.vmware_host_version
        if version_str:
            LOG.info("Using overridden vmware_host_version from config: %s",
                     version_str)
        else:
            version_str = vim_util.get_vc_version(self.session)
            LOG.info("Fetched vCenter server version: %s", version_str)
        return version_str

    def _validate_vcenter_version(self, vc_version):
        if not versionutils.is_compatible(
                self.MIN_SUPPORTED_VC_VERSION, vc_version, same_major=False):
            msg = _('Running Cinder with a VMware vCenter version less than '
                    '%s is not allowed.') % self.MIN_SUPPORTED_VC_VERSION
            LOG.error(msg)
            raise exceptions.VMwareDriverException(message=msg)
        elif not versionutils.is_compatible(self.NEXT_MIN_SUPPORTED_VC_VERSION,
                                            vc_version,
                                            same_major=False):
            LOG.warning('Running Cinder with a VMware vCenter version '
                        'less than %(ver)s is deprecated. The minimum '
                        'required version of vCenter server will be raised'
                        ' to %(ver)s in a future release.',
                        {'ver': self.NEXT_MIN_SUPPORTED_VC_VERSION})

    def _register_extension(self):
        ext = vim_util.find_extension(self.session.vim, EXTENSION_KEY)
        if ext:
            LOG.debug('Extension %s already exists.', EXTENSION_KEY)
        else:
            try:
                vim_util.register_extension(self.session.vim,
                                            EXTENSION_KEY,
                                            EXTENSION_TYPE,
                                            label='OpenStack Cinder')
                LOG.info('Registered extension %s.', EXTENSION_KEY)
            except exceptions.VimFaultException as e:
                if 'InvalidArgument' in e.fault_list:
                    LOG.debug('Extension %s is already registered.',
                              EXTENSION_KEY)
                else:
                    raise

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self._validate_params()

        regex_pattern = self.configuration.vmware_datastore_regex
        if regex_pattern:
            try:
                self._ds_regex = re.compile(regex_pattern)
            except re.error:
                raise exception.InvalidInput(reason=_(
                    "Invalid regular expression: %s.") % regex_pattern)

        self._session = self._create_session()

        # Validate vCenter version.
        self._vc_version = self._get_vc_version()
        self._validate_vcenter_version(self._vc_version)

        # Enable pbm only if vCenter version is 5.5+.
        if (self._vc_version and
                versionutils.is_compatible(self.PBM_ENABLED_VC_VERSION,
                                           self._vc_version,
                                           same_major=False)):
            pbm_wsdl_loc = pbm.get_pbm_wsdl_location(self._vc_version)
            if not pbm_wsdl_loc:
                LOG.error("Not able to configure PBM for vCenter server: %s",
                          self._vc_version)
                raise exceptions.VMwareDriverException()
            self._storage_policy_enabled = True
            self._session.pbm_wsdl_loc_set(pbm_wsdl_loc)

        self._register_extension()

        max_objects = self.configuration.vmware_max_objects_retrieval
        self._volumeops = volumeops.VMwareVolumeOps(
            self.session, max_objects, EXTENSION_KEY, EXTENSION_TYPE)
        self._ds_sel = hub.DatastoreSelector(
            self.volumeops, self.session, max_objects, ds_regex=self._ds_regex)

        # Get clusters to be used for backing VM creation.
        cluster_names = self.configuration.vmware_cluster_name
        if cluster_names:
            self._clusters = self.volumeops.get_cluster_refs(
                cluster_names).values()
            LOG.info("Using compute cluster(s): %s.", cluster_names)

        self.volumeops.build_backing_ref_cache()

        LOG.info("Successfully setup driver: %(driver)s for server: "
                 "%(ip)s.", {'driver': self.__class__.__name__,
                             'ip': self.configuration.vmware_host_ip})

    def _get_volume_group_folder(self, datacenter, project_id, snapshot=False):
        """Get inventory folder for organizing volume backings and snapshots.

        The inventory folder for organizing volume backings has the following
        hierarchy:
               <Datacenter_vmFolder>/OpenStack/Project (<project_id>)/
               <volume_folder>
        where volume_folder is the vmdk driver config option
        "vmware_volume_folder".

        A sub-folder named 'Snapshots' under volume_folder is used for
        organizing snapshots in template format.

        :param datacenter: Reference to the datacenter
        :param project_id: OpenStack project ID
        :param snapshot: Return folder for snapshot if True
        :return: Reference to the inventory folder
        """
        volume_folder_name = self.configuration.vmware_volume_folder
        project_folder_name = "Project (%s)" % project_id
        folder_names = ['OpenStack', project_folder_name, volume_folder_name]
        if snapshot:
            folder_names.append('Snapshots')
        return self.volumeops.create_vm_inventory_folder(datacenter,
                                                         folder_names)

    def _relocate_backing(self, volume, backing, host):
        """Relocate volume backing to a datastore accessible to the given host.

        The backing is not relocated if the current datastore is already
        accessible to the host and compliant with the backing's storage
        profile.

        :param volume: Volume to be relocated
        :param backing: Reference to the backing
        :param host: Reference to the host
        """
        # Check if the current datastore is visible to the host managing
        # the instance and compliant with the storage profile.
        datastore = self.volumeops.get_datastore(backing)
        backing_profile = None
        if self._storage_policy_enabled:
            backing_profile = self._get_storage_profile(volume)
        if (self.volumeops.is_datastore_accessible(datastore, host) and
                self.ds_sel.is_datastore_compliant(datastore,
                                                   backing_profile)):
            LOG.debug("Datastore: %(datastore)s of backing: %(backing)s is "
                      "already accessible to instance's host: %(host)s.",
                      {'backing': backing,
                       'datastore': datastore,
                       'host': host})
            if backing_profile:
                LOG.debug("Backing: %(backing)s is compliant with "
                          "storage profile: %(profile)s.",
                          {'backing': backing,
                           'profile': backing_profile})
            return

        # We need to relocate the backing to an accessible and profile
        # compliant datastore.
        req = {}
        req[hub.DatastoreSelector.SIZE_BYTES] = (volume['size'] *
                                                 units.Gi)
        req[hub.DatastoreSelector.PROFILE_NAME] = backing_profile

        # Select datastore satisfying the requirements.
        (host, resource_pool, summary) = self._select_datastore(req, host)
        dc = self._get_dc(resource_pool)
        folder = self._get_volume_group_folder(dc, volume['project_id'])

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
        clone_type = _get_volume_type_extra_spec(
            volume['volume_type_id'],
            'clone_type',
            default_value=volumeops.FULL_CLONE_TYPE)

        if (clone_type != volumeops.FULL_CLONE_TYPE
                and clone_type != volumeops.LINKED_CLONE_TYPE):
            msg = (_("Clone type '%(clone_type)s' is invalid; valid values"
                     " are: '%(full_clone)s' and '%(linked_clone)s'.") %
                   {'clone_type': clone_type,
                    'full_clone': volumeops.FULL_CLONE_TYPE,
                    'linked_clone': volumeops.LINKED_CLONE_TYPE})
            LOG.error(msg)
            raise exception.Invalid(message=msg)

        return clone_type

    def _clone_backing(self, volume, backing, snapshot, clone_type, src_vsize):
        """Clone the backing.

        :param volume: New Volume object
        :param backing: Reference to the backing entity
        :param snapshot: Reference to the snapshot entity
        :param clone_type: type of the clone
        :param src_vsize: the size of the source volume
        """
        if (clone_type == volumeops.LINKED_CLONE_TYPE and
                volume.size > src_vsize):
            # Volume extend will fail if the volume is a linked clone of
            # another volume. Use full clone if extend is needed after cloning.
            clone_type = volumeops.FULL_CLONE_TYPE
            LOG.debug("Linked cloning not possible for creating volume "
                      "since volume needs to be extended after cloning.",
                      resource=volume)

        datastore = None
        host = None
        rp = None
        folder = None
        if clone_type != volumeops.LINKED_CLONE_TYPE:
            # Pick a datastore where to create the full clone under any host
            (host, rp, folder, summary) = self._select_ds_for_volume(volume)
            datastore = summary.datastore
        extra_config = self._get_extra_config(volume)
        clone = self.volumeops.clone_backing(volume['name'], backing,
                                             snapshot, clone_type, datastore,
                                             host=host, resource_pool=rp,
                                             extra_config=extra_config,
                                             folder=folder)

        # vCenter 6.0+ does not allow changing the UUID of delta disk created
        # during linked cloning; skip setting UUID for vCenter 6.0+.
        if (clone_type == volumeops.LINKED_CLONE_TYPE and
                versionutils.is_compatible(
                    '6.0', self._vc_version, same_major=False)):
            LOG.debug("Not setting vmdk UUID for volume: %s.", volume['id'])
        else:
            self.volumeops.update_backing_disk_uuid(clone, volume['id'])

        # If the volume size specified by the user is greater than
        # the size of the source volume, the newly created volume will
        # allocate the capacity to the size of the source volume in the backend
        # VMDK datastore, though the volume information indicates it has a
        # capacity of the volume size. If the volume size is greater,
        # we need to extend/resize the capacity of the vmdk virtual disk from
        # the size of the source volume to the volume size.
        if volume['size'] > src_vsize:
            self._extend_backing(clone, volume['size'],
                                 VMwareVcVmdkDriver._get_disk_type(volume))
        LOG.info("Successfully created clone: %s.", clone)

    def _create_volume_from_template(self, volume, path):
        LOG.debug("Creating backing for volume: %(volume_id)s from template "
                  "at path: %(path)s.",
                  {'volume_id': volume.id,
                   'path': path})
        template = self._get_template_by_inv_path(path)

        # Create temporary backing by cloning the template.
        tmp_name = uuidutils.generate_uuid()
        (host, rp, folder, summary) = self._select_ds_for_volume(volume)
        datastore = summary.datastore
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)
        tmp_backing = self.volumeops.clone_backing(tmp_name,
                                                   template,
                                                   None,
                                                   volumeops.FULL_CLONE_TYPE,
                                                   datastore,
                                                   disk_type=disk_type,
                                                   host=host,
                                                   resource_pool=rp,
                                                   folder=folder)

        self._create_volume_from_temp_backing(volume, tmp_backing)

    def _create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If the snapshot does not exist or source volume's backing does not
        exist, then pass.

        :param volume: New Volume object
        :param snapshot: Reference to snapshot entity
        """
        backing = self.volumeops.get_backing(snapshot['volume_name'],
                                             snapshot['volume']['id'])
        if not backing:
            LOG.info("There is no backing for the snapshotted volume: "
                     "%(snap)s. Not creating any backing for the "
                     "volume: %(vol)s.",
                     {'snap': snapshot['name'], 'vol': volume['name']})
            return

        inv_path = snapshot.get('provider_location')
        if inv_path:
            self._create_volume_from_template(volume, inv_path)
        else:
            snapshot_moref = self.volumeops.get_snapshot(backing,
                                                         snapshot['name'])
            if not snapshot_moref:
                LOG.info("There is no snapshot point for the snapshotted "
                         "volume: %(snap)s. Not creating any backing for "
                         "the volume: %(vol)s.",
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

    def _get_volume_device_uuid(self, instance, volume_id):
        prop = 'config.extraConfig["volume-%s"]' % volume_id
        opt_val = self.session.invoke_api(vim_util,
                                          'get_object_property',
                                          self.session.vim,
                                          instance,
                                          prop)
        if opt_val is not None:
            return opt_val.value

    def _create_temp_backing_from_attached_vmdk(
            self, src_vref, host, rp, folder, datastore, tmp_name=None):
        instance = self.volumeops.get_backing_by_uuid(
            src_vref['volume_attachment'][0]['instance_uuid'])
        vol_dev_uuid = self._get_volume_device_uuid(instance, src_vref['id'])
        LOG.debug("Cloning volume device: %(dev)s attached to instance: "
                  "%(instance)s.", {'dev': vol_dev_uuid,
                                    'instance': instance})

        tmp_name = tmp_name or uuidutils.generate_uuid()
        return self.volumeops.clone_backing(
            tmp_name, instance, None, volumeops.FULL_CLONE_TYPE, datastore,
            host=host, resource_pool=rp, folder=folder,
            disks_to_clone=[vol_dev_uuid])

    def _extend_if_needed(self, volume, backing):
        volume_size = volume.size * units.Gi
        disk_size = self.volumeops.get_disk_size(backing)
        if volume_size > disk_size:
            self._extend_backing(backing, volume.size,
                                 VMwareVcVmdkDriver._get_disk_type(volume))

    def _create_volume_from_temp_backing(self, volume, tmp_backing):
        try:
            disk_device = self.volumeops._get_disk_device(tmp_backing)
            backing = self._manage_existing_int(
                volume, tmp_backing, disk_device)
            self._extend_if_needed(volume, backing)
        finally:
            self._delete_temp_backing(tmp_backing)

    def _clone_attached_volume(self, src_vref, volume):
        # Clone the vmdk attached to the instance to create a temporary
        # backing.
        (host, rp, folder, summary) = self._select_ds_for_volume(volume)
        datastore = summary.datastore
        tmp_backing = self._create_temp_backing_from_attached_vmdk(
            src_vref, host, rp, folder, datastore)
        self._create_volume_from_temp_backing(volume, tmp_backing)

    def _create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        If source volume's backing does not exist, then pass.
        Linked clone of attached volume is not supported.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        backing = self.volumeops.get_backing(src_vref['name'], src_vref['id'])
        if not backing:
            LOG.info("There is no backing for the source volume: %(src)s. "
                     "Not creating any backing for volume: %(vol)s.",
                     {'src': src_vref['name'], 'vol': volume['name']})
            return

        clone_type = VMwareVcVmdkDriver._get_clone_type(volume)
        snapshot = None
        if clone_type == volumeops.LINKED_CLONE_TYPE:
            if src_vref['status'] != 'available':
                msg = _("Linked clone of source volume not supported "
                        "in state: %s.") % src_vref['status']
                LOG.error(msg)
                raise exception.InvalidVolume(msg)
            # To create a linked clone, we create a temporary snapshot of the
            # source volume, and then create the clone off the temporary
            # snapshot.
            snap_name = 'temp-snapshot-%s' % volume['id']
            snapshot = self.volumeops.create_snapshot(backing, snap_name, None)

        if self._in_use(src_vref):
            self._clone_attached_volume(src_vref, volume)
        else:
            try:
                self._clone_backing(volume, backing, snapshot, clone_type,
                                    src_vref['size'])
            finally:
                if snapshot:
                    # Delete temporary snapshot.
                    try:
                        self.volumeops.delete_snapshot(backing, snap_name)
                    except exceptions.VimException:
                        LOG.debug("Unable to delete temporary snapshot: %s of "
                                  "volume backing.", snap_name,
                                  resource=volume, exc_info=True)

    def create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        self._create_cloned_volume(volume, src_vref)

    def accept_transfer(self, context, volume, new_user, new_project):
        """Accept the transfer of a volume for a new user/project."""
        backing = self.volumeops.get_backing(volume.name, volume.id)
        if backing:
            dc = self.volumeops.get_dc(backing)
            new_folder = self._get_volume_group_folder(dc, new_project)
            self.volumeops.move_backing_to_folder(backing, new_folder)

    def revert_to_snapshot(self, context, volume, snapshot):
        inv_path = snapshot.provider_location
        is_template = inv_path is not None
        if is_template:
            LOG.error("Revert to template based snapshot is not supported.")
            raise exception.InvalidSnapshot("Cannot revert to template "
                                            "based snapshot")

        backing = self.volumeops.get_backing(volume.name, volume.id)
        if not backing:
            LOG.debug("Backing does not exist for volume.", resource=volume)
        else:
            self.volumeops.revert_to_snapshot(backing, snapshot.name)
