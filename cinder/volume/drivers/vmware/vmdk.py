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

import contextlib
import distutils.version as dist_version  # pylint: disable=E0611
import os
import tempfile

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import units
from oslo_utils import uuidutils
from oslo_vmware import api
from oslo_vmware import exceptions
from oslo_vmware import image_transfer
from oslo_vmware import pbm
from oslo_vmware import vim_util
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions
from cinder.volume.drivers.vmware import volumeops
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

THIN_VMDK_TYPE = 'thin'
THICK_VMDK_TYPE = 'thick'
EAGER_ZEROED_THICK_VMDK_TYPE = 'eagerZeroedThick'

CREATE_PARAM_ADAPTER_TYPE = 'adapter_type'
CREATE_PARAM_DISK_LESS = 'disk_less'
CREATE_PARAM_BACKING_NAME = 'name'
CREATE_PARAM_DISK_SIZE = 'disk_size'

TMP_IMAGES_DATASTORE_FOLDER_PATH = "cinder_temp/"

EXTRA_CONFIG_VOLUME_ID_KEY = "cinder.volume.id"

vmdk_opts = [
    cfg.StrOpt('vmware_host_ip',
               help='IP address for connecting to VMware vCenter server.'),
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
                 default=0.5,
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


class VMwareVcVmdkDriver(driver.VolumeDriver):
    """Manage volumes on VMware vCenter server."""

    # 1.0 - initial version of driver
    # 1.1.0 - selection of datastore based on number of host mounts
    # 1.2.0 - storage profile volume types based placement of volumes
    # 1.3.0 - support for volume backup/restore
    # 1.4.0 - support for volume retype
    # 1.5.0 - restrict volume placement to specific vCenter clusters
    VERSION = '1.5.0'

    # Minimum supported vCenter version.
    MIN_SUPPORTED_VC_VERSION = dist_version.LooseVersion('5.1')

    # PBM is enabled only for vCenter versions 5.5 and above
    PBM_ENABLED_VC_VERSION = dist_version.LooseVersion('5.5')

    def __init__(self, *args, **kwargs):
        super(VMwareVcVmdkDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(vmdk_opts)
        self._session = None
        self._stats = None
        self._volumeops = None
        self._storage_policy_enabled = False
        self._ds_sel = None
        self._clusters = None

    @property
    def volumeops(self):
        if not self._volumeops:
            max_objects = self.configuration.vmware_max_objects_retrieval
            self._volumeops = volumeops.VMwareVolumeOps(self.session,
                                                        max_objects)
        return self._volumeops

    @property
    def ds_sel(self):
        if not self._ds_sel:
            self._ds_sel = hub.DatastoreSelector(self.volumeops,
                                                 self.session)
        return self._ds_sel

    def _validate_params(self):
        # Throw error if required parameters are not set.
        required_params = ['vmware_host_ip',
                           'vmware_host_username',
                           'vmware_host_password']
        for param in required_params:
            if not getattr(self.configuration, param, None):
                raise exception.InvalidInput(_("%s not set.") % param)

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
                    'storage_protocol': 'vmdk',
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
        except exceptions.VimException as excep:
            msg = _("Not able to find a suitable datastore for the volume: "
                    "%s.") % volume['name']
            LOG.exception(msg)
            raise exceptions.VimFaultException([excep], msg)
        LOG.debug("Verified volume %s can be created.", volume['name'])

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
            LOG.info(_LI("Backing not available, no operation "
                         "to be performed."))
            return
        self.volumeops.delete_backing(backing)

    def delete_volume(self, volume):
        """Deletes volume backing.

        :param volume: Volume object
        """
        self._delete_volume(volume)

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
        return {EXTRA_CONFIG_VOLUME_ID_KEY: volume['id']}

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
                                         'lsiLogic')
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
                for host in cluster_hosts:
                    if self.volumeops.is_host_usable(host):
                        hosts.append(host)
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
                LOG.error(_LE("There are no valid hosts available in "
                              "configured cluster(s): %s."), self._clusters)
                raise vmdk_exceptions.NoValidHostException()

        best_candidate = self.ds_sel.select_datastore(req, hosts=hosts)
        if not best_candidate:
            LOG.error(_LE("There is no valid datastore satisfying "
                          "requirements: %s."), req)
            raise vmdk_exceptions.NoValidDatastoreException()

        return best_candidate

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
        dc = self.volumeops.get_dc(resource_pool)
        folder = self._get_volume_group_folder(dc, volume['project_id'])

        return (host_ref, resource_pool, folder, summary)

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
            instance = vim_util.get_moref(connector['instance'],
                                          'VirtualMachine')
            LOG.debug("The instance: %s for which initialize connection "
                      "is called, exists.", instance)
            # Get host managing the instance
            host = self.volumeops.get_host(instance)
            if not backing:
                # Create a backing in case it does not exist under the
                # host managing the instance.
                LOG.info(_LI("There is no backing for the volume: %s. "
                             "Need to create one."), volume['name'])
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
                LOG.warning(_LW("Trying to boot from an empty volume: %s."),
                            volume['name'])
                # Create backing
                backing = self._create_backing(volume)

        # Set volume's moref value and name
        connection_info['data'] = {'volume': backing.value,
                                   'volume_id': volume['id']}

        LOG.info(_LI("Returning connection_info: %(info)s for volume: "
                     "%(volume)s with connector: %(connector)s."),
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

    def create_export(self, context, volume, connector):
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
            msg = _("Snapshot of volume not supported in "
                    "state: %s.") % volume['status']
            LOG.error(msg)
            raise exception.InvalidVolume(msg)
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_LI("There is no backing, so will not create "
                         "snapshot: %s."), snapshot['name'])
            return
        self.volumeops.create_snapshot(backing, snapshot['name'],
                                       snapshot['display_description'])
        LOG.info(_LI("Successfully created snapshot: %s."), snapshot['name'])

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
            msg = _("Delete snapshot of volume not supported in "
                    "state: %s.") % volume['status']
            LOG.error(msg)
            raise exception.InvalidVolume(msg)
        backing = self.volumeops.get_backing(snapshot['volume_name'])
        if not backing:
            LOG.info(_LI("There is no backing, and so there is no "
                         "snapshot: %s."), snapshot['name'])
        else:
            self.volumeops.delete_snapshot(backing, snapshot['name'])
            LOG.info(_LI("Successfully deleted snapshot: %s."),
                     snapshot['name'])

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
        ca_file = self.configuration.vmware_ca_file
        insecure = self.configuration.vmware_insecure
        cookies = self.session.vim.client.options.transport.cookiejar
        dc_name = self.volumeops.get_entity_name(dc_ref)

        LOG.debug("Copying image: %(image_id)s to %(path)s.",
                  {'image_id': image_id,
                   'path': upload_file_path})
        # TODO(vbala): add config option to override non-default port

        # ca_file is used for verifying vCenter certificate if it is set.
        # If ca_file is unset and insecure is False, the default CA truststore
        # is used for verification. We should pass cacerts=True in this
        # case. If ca_file is unset and insecure is True, there is no
        # certificate verification, and we should pass cacerts=False.
        cacerts = ca_file if ca_file else not insecure
        image_transfer.download_flat_image(context,
                                           timeout,
                                           image_service,
                                           image_id,
                                           image_size=image_size_in_bytes,
                                           host=host_ip,
                                           port=443,
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
            LOG.warning(_LW("Error occurred while deleting temporary "
                            "disk: %s."),
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
                LOG.exception(_LE("Error occurred while copying %(src)s to "
                                  "%(dst)s."),
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
        # vSAN datastores don't support virtual disk with
        # flat extent; skip such datastores.
        req[hub.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = (
            hub.DatastoreType.get_all_types() - {hub.DatastoreType.VSAN})

        # Select datastore satisfying the requirements.
        (host_ref, _resource_pool, summary) = self._select_datastore(req)

        ds_name = summary.name
        dc_ref = self.volumeops.get_dc(host_ref)

        # Create temporary datastore folder.
        folder_path = TMP_IMAGES_DATASTORE_FOLDER_PATH
        self.volumeops.create_datastore_folder(ds_name, folder_path, dc_ref)

        return (dc_ref, ds_name, folder_path)

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
        if ds_name == dest_ds_name and dc_ref.value == dest_dc_ref.value:
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
            dc_ref, path, image_size_in_bytes / units.Ki, adapter_type,
            EAGER_ZEROED_THICK_VMDK_TYPE)
        # Upload the image and use it as the flat extent.
        try:
            self._copy_image(context, dc_ref, image_service, image_id,
                             image_size_in_bytes, ds_name,
                             path.get_flat_extent_file_path())
        except Exception:
            # Delete the descriptor.
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while copying image: "
                                  "%(image_id)s to %(path)s."),
                              {'path': path.get_descriptor_ds_file_path(),
                               'image_id': image_id})
                LOG.debug("Deleting descriptor: %s.",
                          path.get_descriptor_ds_file_path())
                try:
                    self.volumeops.delete_file(
                        path.get_descriptor_ds_file_path(), dc_ref)
                except exceptions.VimException:
                    LOG.warning(_LW("Error occurred while deleting "
                                    "descriptor: %s."),
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
            LOG.warning(_LW("Error occurred while deleting backing: %s."),
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

            self.volumeops.attach_disk_to_backing(
                backing, image_size_in_bytes / units.Ki, disk_type,
                adapter_type, vmdk_path.get_descriptor_ds_file_path())
            attached = True

            if disk_conversion:
                # Clone the temporary backing for disk type conversion.
                (host, rp, _folder, summary) = self._select_ds_for_volume(
                    volume)
                datastore = summary.datastore
                LOG.debug("Cloning temporary backing: %s for disk type "
                          "conversion.", backing)
                clone = self.volumeops.clone_backing(volume['name'],
                                                     backing,
                                                     None,
                                                     volumeops.FULL_CLONE_TYPE,
                                                     datastore,
                                                     disk_type,
                                                     host,
                                                     rp)
                self._delete_temp_backing(backing)
                backing = clone
            self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        except Exception:
            # Delete backing and virtual disk created from image.
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while creating "
                                  "volume: %(id)s"
                                  " from image: %(image_id)s."),
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
            profileId=profile_id,
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
            LOG.debug("Fetching glance image: %(id)s to server: %(host)s.",
                      {'id': image_id, 'host': host_ip})
            backing = image_transfer.download_stream_optimized_image(
                context,
                timeout,
                image_service,
                image_id,
                session=self.session,
                host=host_ip,
                port=443,
                resource_pool=rp,
                vm_folder=folder,
                vm_import_spec=vm_import_spec,
                image_size=image_size)
            self.volumeops.update_backing_disk_uuid(backing, volume['id'])
        except (exceptions.VimException,
                exceptions.VMwareDriverException):
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while copying image: %(id)s "
                                  "to volume: %(vol)s."),
                              {'id': image_id, 'vol': volume['name']})
                backing = self.volumeops.get_backing(volume['name'])
                if backing:
                    # delete the backing
                    self.volumeops.delete_backing(backing)

        LOG.info(_LI("Done copying image: %(id)s to volume: %(vol)s."),
                 {'id': image_id, 'vol': volume['name']})

    def _extend_backing(self, backing, new_size_in_gb):
        """Extend volume backing's virtual disk.

        :param backing: volume backing
        :param new_size_in_gb: new size of virtual disk
        """
        root_vmdk_path = self.volumeops.get_vmdk_path(backing)
        datacenter = self.volumeops.get_dc(backing)
        self.volumeops.extend_virtual_disk(new_size_in_gb, root_vmdk_path,
                                           datacenter)

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

        # Validate container format; only 'bare' is supported currently.
        container_format = metadata.get('container_format')
        if (container_format and container_format != 'bare'):
            msg = _("Container format: %s is unsupported by the VMDK driver, "
                    "only 'bare' is supported.") % container_format
            LOG.error(msg)
            raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

        # Get the disk type, adapter type and size of vmdk image
        image_disk_type = ImageDiskType.PREALLOCATED
        image_adapter_type = volumeops.VirtualDiskAdapterType.LSI_LOGIC
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
                LOG.exception(_LE("Error occurred while copying image: %(id)s "
                                  "to volume: %(vol)s."),
                              {'id': image_id, 'vol': volume['name']})

        LOG.debug("Volume: %(id)s created from image: %(image_id)s.",
                  {'id': volume['id'],
                   'image_id': image_id})

        # If the user-specified volume size is greater than backing's
        # current disk size, we should extend the disk.
        volume_size = volume['size'] * units.Gi
        backing = self.volumeops.get_backing(volume['name'])
        disk_size = self.volumeops.get_disk_size(backing)
        if volume_size > disk_size:
            LOG.debug("Extending volume: %(name)s since the user specified "
                      "volume size (bytes): %(vol_size)d is greater than "
                      "backing's current disk size (bytes): %(disk_size)d.",
                      {'name': volume['name'],
                       'vol_size': volume_size,
                       'disk_size': disk_size})
            self._extend_backing(backing, volume['size'])
        # TODO(vbala): handle volume_size < disk_size case.

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
        if (volume['volume_attachment'] and
                len(volume['volume_attachment']) > 0):
            msg = _("Upload to glance of attached volume is not supported.")
            LOG.error(msg)
            raise exception.InvalidVolume(msg)

        # validate disk format is vmdk
        LOG.debug("Copy Volume: %s to new image.", volume['name'])
        VMwareVcVmdkDriver._validate_disk_format(image_meta['disk_format'])

        # get backing vm of volume and its vmdk path
        backing = self.volumeops.get_backing(volume['name'])
        if not backing:
            LOG.info(_LI("Backing not found, creating for volume: %s"),
                     volume['name'])
            backing = self._create_backing(volume)
        vmdk_file_path = self.volumeops.get_vmdk_path(backing)

        # Upload image from vmdk
        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip

        image_transfer.upload_image(context,
                                    timeout,
                                    image_service,
                                    image_meta['id'],
                                    volume['project_id'],
                                    session=self.session,
                                    host=host_ip,
                                    port=443,
                                    vm=backing,
                                    vmdk_file_path=vmdk_file_path,
                                    vmdk_size=volume['size'] * units.Gi,
                                    image_name=image_meta['name'],
                                    image_version=1,
                                    is_public=image_meta['is_public'])
        LOG.info(_LI("Done copying volume %(vol)s to a new image %(img)s"),
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
            LOG.warning(_LW("Volume: %s is in use, can't retype."),
                        volume['name'])
            return False

        # If the backing doesn't exist, retype is NOP.
        backing = self.volumeops.get_backing(volume['name'])
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
                    [datastore.value])

            if new_profile:
                req[hub.DatastoreSelector.PROFILE_NAME] = new_profile

            # Select datastore satisfying the requirements.
            best_candidate = self.ds_sel.select_datastore(req)
            if not best_candidate:
                # No candidate datastores; can't retype.
                LOG.warning(_LW("There are no datastores matching new "
                                "requirements; can't retype volume: %s."),
                            volume['name'])
                return False

            (host, rp, summary) = best_candidate
            new_datastore = summary.datastore
            if datastore.value != new_datastore.value:
                # Datastore changed; relocate the backing.
                LOG.debug("Backing: %s needs to be relocated for retype.",
                          backing)
                self.volumeops.relocate_backing(
                    backing, new_datastore, rp, host, new_disk_type)

                dc = self.volumeops.get_dc(rp)
                folder = self._get_volume_group_folder(dc,
                                                       volume['project_id'])
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
                        volumeops.FULL_CLONE_TYPE, datastore, new_disk_type,
                        host, rp)
                    self.volumeops.update_backing_disk_uuid(new_backing,
                                                            volume['id'])
                    self._delete_temp_backing(backing)
                    backing = new_backing
                except exceptions.VimException:
                    with excutils.save_and_reraise_exception():
                        LOG.exception(_LE("Error occurred while cloning "
                                          "backing:"
                                          " %s during retype."),
                                      backing)
                        if renamed:
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
                                LOG.warning(_LW("Changing backing: "
                                                "%(backing)s name from "
                                                "%(new_name)s to %(old_name)s "
                                                "failed."),
                                            {'backing': backing,
                                             'new_name': tmp_name,
                                             'old_name': volume['name']})

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
        backing = self.volumeops.get_backing(vol_name)
        if not backing:
            LOG.info(_LI("There is no backing for volume: %s; no need to "
                         "extend the virtual disk."), vol_name)
            return

        # try extending vmdk in place
        try:
            self._extend_backing(backing, new_size)
            LOG.info(_LI("Successfully extended volume: %(vol)s to size: "
                         "%(size)s GB."),
                     {'vol': vol_name, 'size': new_size})
            return
        except exceptions.NoDiskSpaceException:
            LOG.warning(_LW("Unable to extend volume: %(vol)s to size: "
                            "%(size)s on current datastore due to insufficient"
                            " space."),
                        {'vol': vol_name, 'size': new_size})

        # Insufficient disk space; relocate the volume to a different datastore
        # and retry extend.
        LOG.info(_LI("Relocating volume: %s to a different datastore due to "
                     "insufficient disk space on current datastore."),
                 vol_name)
        try:
            create_params = {CREATE_PARAM_DISK_SIZE: new_size}
            (host, rp, folder, summary) = self._select_ds_for_volume(
                volume, create_params=create_params)
            self.volumeops.relocate_backing(backing, summary.datastore, rp,
                                            host)
            self.volumeops.move_backing_to_folder(backing, folder)
            self._extend_backing(backing, new_size)
        except exceptions.VMwareDriverException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to extend volume: %(vol)s to size: "
                              "%(size)s GB."),
                          {'vol': vol_name, 'size': new_size})

        LOG.info(_LI("Successfully extended volume: %(vol)s to size: "
                     "%(size)s GB."),
                 {'vol': vol_name, 'size': new_size})

    @contextlib.contextmanager
    def _temporary_file(self, *args, **kwargs):
        """Create a temporary file and return its path."""
        tmp_dir = self.configuration.vmware_tmp_dir
        fileutils.ensure_tree(tmp_dir)
        fd, tmp = tempfile.mkstemp(
            dir=self.configuration.vmware_tmp_dir, *args, **kwargs)
        try:
            os.close(fd)
            yield tmp
        finally:
            fileutils.delete_if_exists(tmp)

    def _download_vmdk(self, context, volume, backing, tmp_file_path):
        """Download virtual disk in streamOptimized format."""
        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip
        vmdk_ds_file_path = self.volumeops.get_vmdk_path(backing)

        with open(tmp_file_path, "wb") as tmp_file:
            image_transfer.copy_stream_optimized_disk(
                context,
                timeout,
                tmp_file,
                session=self.session,
                host=host_ip,
                port=443,
                vm=backing,
                vmdk_file_path=vmdk_ds_file_path,
                vmdk_size=volume['size'] * units.Gi)

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])

        LOG.debug("Creating backup: %(backup_id)s for volume: %(name)s.",
                  {'backup_id': backup['id'],
                   'name': volume['name']})

        backing = self.volumeops.get_backing(volume['name'])
        if backing is None:
            LOG.debug("Creating backing for volume: %s.", volume['name'])
            backing = self._create_backing(volume)

        tmp_vmdk_name = uuidutils.generate_uuid()
        with self._temporary_file(suffix=".vmdk",
                                  prefix=tmp_vmdk_name) as tmp_file_path:
            # TODO(vbala) Clean up vmware_tmp_dir during driver init.
            LOG.debug("Using temporary file: %(tmp_path)s for creating backup:"
                      " %(backup_id)s.",
                      {'tmp_path': tmp_file_path,
                       'backup_id': backup['id']})
            self._download_vmdk(context, volume, backing, tmp_file_path)
            with open(tmp_file_path, "rb") as tmp_file:
                LOG.debug("Calling backup service to backup file: %s.",
                          tmp_file_path)
                backup_service.backup(backup, tmp_file)
                LOG.debug("Created backup: %(backup_id)s for volume: "
                          "%(name)s.",
                          {'backup_id': backup['id'],
                           'name': volume['name']})

    def _create_backing_from_stream_optimized_file(
            self, context, name, volume, tmp_file_path, file_size_bytes):
        """Create backing from streamOptimized virtual disk file."""
        LOG.debug("Creating backing: %(name)s from virtual disk: %(path)s.",
                  {'name': name,
                   'path': tmp_file_path})

        (_host, rp, folder, summary) = self._select_ds_for_volume(volume)
        LOG.debug("Selected datastore: %(ds)s for backing: %(name)s.",
                  {'ds': summary.name,
                   'name': name})

        # Prepare import spec for backing.
        cf = self.session.vim.client.factory
        vm_import_spec = cf.create('ns0:VirtualMachineImportSpec')

        profile_id = self._get_storage_profile_id(volume)
        disk_type = VMwareVcVmdkDriver._get_disk_type(volume)
        extra_config = self._get_extra_config(volume)
        # We cannot determine the size of a virtual disk created from
        # streamOptimized disk image. Set size to 0 and let vCenter
        # figure out the size after virtual disk creation.
        vm_create_spec = self.volumeops.get_create_spec(
            name, 0, disk_type, summary.name, profileId=profile_id,
            extra_config=extra_config)
        vm_import_spec.configSpec = vm_create_spec

        timeout = self.configuration.vmware_image_transfer_timeout_secs
        host_ip = self.configuration.vmware_host_ip
        try:
            with open(tmp_file_path, "rb") as tmp_file:
                vm_ref = image_transfer.download_stream_optimized_data(
                    context,
                    timeout,
                    tmp_file,
                    session=self.session,
                    host=host_ip,
                    port=443,
                    resource_pool=rp,
                    vm_folder=folder,
                    vm_import_spec=vm_import_spec,
                    image_size=file_size_bytes)
                LOG.debug("Created backing: %(name)s from virtual disk: "
                          "%(path)s.",
                          {'name': name,
                           'path': tmp_file_path})
                return vm_ref
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while creating temporary "
                                  "backing."))
                backing = self.volumeops.get_backing(name)
                if backing is not None:
                    self._delete_temp_backing(backing)

    def _restore_backing(
            self, context, volume, backing, tmp_file_path, backup_size):
        """Restore backing from backup."""
        # Create temporary backing from streamOptimized file.
        src_name = uuidutils.generate_uuid()
        src = self._create_backing_from_stream_optimized_file(
            context, src_name, volume, tmp_file_path, backup_size)

        # Copy temporary backing for desired disk type conversion.
        new_backing = (backing is None)
        if new_backing:
            # No backing exists; clone can be used as the volume backing.
            dest_name = volume['name']
        else:
            # Backing exists; clone can be used as the volume backing only
            # after deleting the current backing.
            dest_name = uuidutils.generate_uuid()

        dest = None
        tmp_backing_name = None
        renamed = False
        try:
            # Find datastore for clone.
            (host, rp, _folder, summary) = self._select_ds_for_volume(volume)
            datastore = summary.datastore

            disk_type = VMwareVcVmdkDriver._get_disk_type(volume)
            dest = self.volumeops.clone_backing(dest_name, src, None,
                                                volumeops.FULL_CLONE_TYPE,
                                                datastore, disk_type, host, rp)
            self.volumeops.update_backing_disk_uuid(dest, volume['id'])
            if new_backing:
                LOG.debug("Created new backing: %s for restoring backup.",
                          dest_name)
                return

            # Rename current backing.
            tmp_backing_name = uuidutils.generate_uuid()
            self.volumeops.rename_backing(backing, tmp_backing_name)
            renamed = True

            # Rename clone in order to treat it as the volume backing.
            self.volumeops.rename_backing(dest, volume['name'])

            # Now we can delete the old backing.
            self._delete_temp_backing(backing)

            LOG.debug("Deleted old backing and renamed clone for restoring "
                      "backup.")
        except (exceptions.VimException, exceptions.VMwareDriverException):
            with excutils.save_and_reraise_exception():
                if dest is not None:
                    # Copy happened; we need to delete the clone.
                    self._delete_temp_backing(dest)
                    if renamed:
                        # Old backing was renamed; we need to undo that.
                        try:
                            self.volumeops.rename_backing(backing,
                                                          volume['name'])
                        except exceptions.VimException:
                            LOG.warning(_LW("Cannot undo volume rename; old "
                                            "name was %(old_name)s and new "
                                            "name is %(new_name)s."),
                                        {'old_name': volume['name'],
                                         'new_name': tmp_backing_name},
                                        exc_info=True)
        finally:
            # Delete the temporary backing.
            self._delete_temp_backing(src)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume.

        This method raises InvalidVolume if the existing volume contains
        snapshots since it is not possible to restore the virtual disk of
        a backing with snapshots.
        """
        LOG.debug("Restoring backup: %(backup_id)s to volume: %(name)s.",
                  {'backup_id': backup['id'],
                   'name': volume['name']})

        backing = self.volumeops.get_backing(volume['name'])
        if backing is not None and self.volumeops.snapshot_exists(backing):
            msg = _("Volume cannot be restored since it contains snapshots.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        tmp_vmdk_name = uuidutils.generate_uuid()
        with self._temporary_file(suffix=".vmdk",
                                  prefix=tmp_vmdk_name) as tmp_file_path:
            LOG.debug("Using temporary file: %(tmp_path)s for restoring "
                      "backup: %(backup_id)s.",
                      {'tmp_path': tmp_file_path,
                       'backup_id': backup['id']})
            with open(tmp_file_path, "wb") as tmp_file:
                LOG.debug("Calling backup service to restore backup: "
                          "%(backup_id)s to file: %(tmp_path)s.",
                          {'backup_id': backup['id'],
                           'tmp_path': tmp_file_path})
                backup_service.restore(backup, volume['id'], tmp_file)
                LOG.debug("Backup: %(backup_id)s restored to file: "
                          "%(tmp_path)s.",
                          {'backup_id': backup['id'],
                           'tmp_path': tmp_file_path})
            self._restore_backing(context, volume, backing, tmp_file_path,
                                  backup['size'] * units.Gi)

            if backup['size'] < volume['size']:
                # Current backing size is backup size.
                LOG.debug("Backup size: %(backup_size)d is less than "
                          "volume size: %(vol_size)d; extending volume.",
                          {'backup_size': backup['size'],
                           'vol_size': volume['size']})
                self.extend_volume(volume, volume['size'])

            LOG.debug("Backup: %(backup_id)s restored to volume: "
                      "%(name)s.",
                      {'backup_id': backup['id'],
                       'name': volume['name']})

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
            ca_file = self.configuration.vmware_ca_file
            insecure = self.configuration.vmware_insecure
            self._session = api.VMwareAPISession(ip, username,
                                                 password, api_retry_count,
                                                 task_poll_interval,
                                                 wsdl_loc=wsdl_loc,
                                                 pbm_wsdl_loc=pbm_wsdl,
                                                 cacert=ca_file,
                                                 insecure=insecure)
        return self._session

    def _get_vc_version(self):
        """Connect to vCenter server and fetch version.

        Can be over-ridden by setting 'vmware_host_version' config.
        :returns: vCenter version as a LooseVersion object
        """
        version_str = self.configuration.vmware_host_version
        if version_str:
            LOG.info(_LI("Using overridden vmware_host_version from config: "
                         "%s"), version_str)
        else:
            version_str = vim_util.get_vc_version(self.session)
            LOG.info(_LI("Fetched vCenter server version: %s"), version_str)
        # Convert version_str to LooseVersion and return.
        version = None
        try:
            version = dist_version.LooseVersion(version_str)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Version string '%s' is not parseable"),
                              version_str)
        return version

    def _validate_vcenter_version(self, vc_version):
        if vc_version < self.MIN_SUPPORTED_VC_VERSION:
            msg = _('Running Cinder with a VMware vCenter version less than '
                    '%s is not allowed.') % self.MIN_SUPPORTED_VC_VERSION
            LOG.error(msg)
            raise exceptions.VMwareDriverException(message=msg)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self._validate_params()

        # Validate vCenter version.
        vc_version = self._get_vc_version()
        self._validate_vcenter_version(vc_version)

        # Enable pbm only if vCenter version is 5.5+.
        if vc_version and vc_version >= self.PBM_ENABLED_VC_VERSION:
            self.pbm_wsdl = pbm.get_pbm_wsdl_location(
                six.text_type(vc_version))
            if not self.pbm_wsdl:
                LOG.error(_LE("Not able to configure PBM for vCenter server: "
                              "%s"), vc_version)
                raise exceptions.VMwareDriverException()
            self._storage_policy_enabled = True
            # Destroy current session so that it is recreated with pbm enabled
            self._session = None

        # recreate session and initialize volumeops and ds_sel
        # TODO(vbala) remove properties: session, volumeops and ds_sel
        max_objects = self.configuration.vmware_max_objects_retrieval
        self._volumeops = volumeops.VMwareVolumeOps(self.session, max_objects)
        self._ds_sel = hub.DatastoreSelector(self.volumeops, self.session)

        # Get clusters to be used for backing VM creation.
        cluster_names = self.configuration.vmware_cluster_name
        if cluster_names:
            self._clusters = self.volumeops.get_cluster_refs(
                cluster_names).values()
            LOG.info(_LI("Using compute cluster(s): %s."), cluster_names)

        LOG.info(_LI("Successfully setup driver: %(driver)s for server: "
                     "%(ip)s."), {'driver': self.__class__.__name__,
                                  'ip': self.configuration.vmware_host_ip})

    def _get_volume_group_folder(self, datacenter, project_id):
        """Get inventory folder for organizing volume backings.

        The inventory folder for organizing volume backings has the following
        hierarchy:
               <Datacenter_vmFolder>/OpenStack/Project (<project_id>)/
               <volume_folder>
        where volume_folder is the vmdk driver config option
        "vmware_volume_folder".

        :param datacenter: Reference to the datacenter
        :param project_id: OpenStack project ID
        :return: Reference to the inventory folder
        """
        volume_folder_name = self.configuration.vmware_volume_folder
        project_folder_name = "Project (%s)" % project_id
        folder_names = ['OpenStack', project_folder_name, volume_folder_name]
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
            backing_profile = self.volumeops.get_profile(backing)
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
        dc = self.volumeops.get_dc(resource_pool)
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
        host = None
        rp = None
        if not clone_type == volumeops.LINKED_CLONE_TYPE:
            # Pick a datastore where to create the full clone under any host
            (host, rp, _folder, summary) = self._select_ds_for_volume(volume)
            datastore = summary.datastore
        extra_config = self._get_extra_config(volume)
        clone = self.volumeops.clone_backing(volume['name'], backing,
                                             snapshot, clone_type, datastore,
                                             host=host, resource_pool=rp,
                                             extra_config=extra_config)
        self.volumeops.update_backing_disk_uuid(clone, volume['id'])
        # If the volume size specified by the user is greater than
        # the size of the source volume, the newly created volume will
        # allocate the capacity to the size of the source volume in the backend
        # VMDK datastore, though the volume information indicates it has a
        # capacity of the volume size. If the volume size is greater,
        # we need to extend/resize the capacity of the vmdk virtual disk from
        # the size of the source volume to the volume size.
        if volume['size'] > src_vsize:
            self._extend_backing(clone, volume['size'])
        LOG.info(_LI("Successfully created clone: %s."), clone)

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
            LOG.info(_LI("There is no backing for the snapshotted volume: "
                         "%(snap)s. Not creating any backing for the "
                         "volume: %(vol)s."),
                     {'snap': snapshot['name'], 'vol': volume['name']})
            return
        snapshot_moref = self.volumeops.get_snapshot(backing,
                                                     snapshot['name'])
        if not snapshot_moref:
            LOG.info(_LI("There is no snapshot point for the snapshotted "
                         "volume: %(snap)s. Not creating any backing for "
                         "the volume: %(vol)s."),
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
            LOG.info(_LI("There is no backing for the source volume: %(src)s. "
                         "Not creating any backing for volume: %(vol)s."),
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
