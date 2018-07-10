# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Drivers for volumes."""

import abc
import time

from os_brick import exception as brick_exception
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver_utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import throttling

LOG = logging.getLogger(__name__)


volume_opts = [
    cfg.IntOpt('num_shell_tries',
               default=3,
               help='Number of times to attempt to run flakey shell commands'),
    cfg.IntOpt('reserved_percentage',
               default=0,
               min=0, max=100,
               help='The percentage of backend capacity is reserved'),
    cfg.StrOpt('iscsi_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='Prefix for iSCSI volumes'),
    cfg.StrOpt('iscsi_ip_address',
               default='$my_ip',
               help='The IP address that the iSCSI daemon is listening on'),
    cfg.ListOpt('iscsi_secondary_ip_addresses',
                default=[],
                help='The list of secondary IP addresses of the iSCSI daemon'),
    cfg.PortOpt('iscsi_port',
                default=3260,
                help='The port that the iSCSI daemon is listening on'),
    cfg.IntOpt('num_volume_device_scan_tries',
               default=3,
               help='The maximum number of times to rescan targets'
                    ' to find volume'),
    cfg.StrOpt('volume_backend_name',
               help='The backend name for a given driver implementation'),
    cfg.BoolOpt('use_multipath_for_image_xfer',
                default=False,
                help='Do we attach/detach volumes in cinder using multipath '
                     'for volume to image and image to volume transfers?'),
    cfg.BoolOpt('enforce_multipath_for_image_xfer',
                default=False,
                help='If this is set to True, attachment of volumes for '
                     'image transfer will be aborted when multipathd is not '
                     'running. Otherwise, it will fallback to single path.'),
    cfg.StrOpt('volume_clear',
               default='zero',
               choices=['none', 'zero'],
               help='Method used to wipe old volumes'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               max=1024,
               help='Size in MiB to wipe at start of old volumes. 1024 MiB'
                    'at max. 0 => all'),
    cfg.StrOpt('volume_clear_ionice',
               help='The flag to pass to ionice to alter the i/o priority '
                    'of the process used to zero a volume after deletion, '
                    'for example "-c3" for idle only priority.'),
    cfg.StrOpt('iscsi_helper',
               default='tgtadm',
               choices=['tgtadm', 'lioadm', 'scstadmin', 'iscsictl',
                        'ietadm', 'fake'],
               help='iSCSI target user-land tool to use. tgtadm is default, '
                    'use lioadm for LIO iSCSI support, scstadmin for SCST '
                    'target support, ietadm for iSCSI Enterprise Target, '
                    'iscsictl for Chelsio iSCSI '
                    'Target or fake for testing.'),
    cfg.StrOpt('volumes_dir',
               default='$state_path/volumes',
               help='Volume configuration file storage '
               'directory'),
    cfg.StrOpt('iet_conf',
               default='/etc/iet/ietd.conf',
               help='IET configuration file'),
    cfg.StrOpt('chiscsi_conf',
               default='/etc/chelsio-iscsi/chiscsi.conf',
               help='Chiscsi (CXT) global defaults configuration file'),
    cfg.StrOpt('iscsi_iotype',
               default='fileio',
               choices=['blockio', 'fileio', 'auto'],
               help=('Sets the behavior of the iSCSI target '
                     'to either perform blockio or fileio '
                     'optionally, auto can be set and Cinder '
                     'will autodetect type of backing device')),
    cfg.StrOpt('volume_dd_blocksize',
               default='1M',
               help='The default block size used when copying/clearing '
                    'volumes'),
    cfg.StrOpt('volume_copy_blkio_cgroup_name',
               default='cinder-volume-copy',
               help='The blkio cgroup name to be used to limit bandwidth '
                    'of volume copy'),
    cfg.IntOpt('volume_copy_bps_limit',
               default=0,
               help='The upper limit of bandwidth of volume copy. '
                    '0 => unlimited'),
    cfg.StrOpt('iscsi_write_cache',
               default='on',
               choices=['on', 'off'],
               help='Sets the behavior of the iSCSI target to either '
                    'perform write-back(on) or write-through(off). '
                    'This parameter is valid if iscsi_helper is set '
                    'to tgtadm.'),
    cfg.StrOpt('iscsi_target_flags',
               default='',
               help='Sets the target-specific flags for the iSCSI target. '
                    'Only used for tgtadm to specify backing device flags '
                    'using bsoflags option. The specified string is passed '
                    'as is to the underlying tool.'),
    cfg.StrOpt('iscsi_protocol',
               default='iscsi',
               choices=['iscsi', 'iser'],
               help='Determines the iSCSI protocol for new iSCSI volumes, '
                    'created with tgtadm or lioadm target helpers. In '
                    'order to enable RDMA, this parameter should be set '
                    'with the value "iser". The supported iSCSI protocol '
                    'values are "iscsi" and "iser".'),
    cfg.StrOpt('driver_client_cert_key',
               help='The path to the client certificate key for verification, '
                    'if the driver supports it.'),
    cfg.StrOpt('driver_client_cert',
               help='The path to the client certificate for verification, '
                    'if the driver supports it.'),
    cfg.BoolOpt('driver_use_ssl',
                default=False,
                help='Tell driver to use SSL for connection to backend '
                     'storage if the driver supports it.'),
    cfg.FloatOpt('max_over_subscription_ratio',
                 default=20.0,
                 help='Float representation of the over subscription ratio '
                      'when thin provisioning is involved. Default ratio is '
                      '20.0, meaning provisioned capacity can be 20 times of '
                      'the total physical capacity. If the ratio is 10.5, it '
                      'means provisioned capacity can be 10.5 times of the '
                      'total physical capacity. A ratio of 1.0 means '
                      'provisioned capacity cannot exceed the total physical '
                      'capacity. The ratio has to be a minimum of 1.0.'),
    cfg.StrOpt('scst_target_iqn_name',
               help='Certain ISCSI targets have predefined target names, '
                    'SCST target driver uses this name.'),
    cfg.StrOpt('scst_target_driver',
               default='iscsi',
               help='SCST target implementation can choose from multiple '
                    'SCST target drivers.'),
    cfg.BoolOpt('use_chap_auth',
                default=False,
                help='Option to enable/disable CHAP authentication for '
                     'targets.'),
    cfg.StrOpt('chap_username',
               default='',
               help='CHAP user name.'),
    cfg.StrOpt('chap_password',
               default='',
               help='Password for specified CHAP account name.',
               secret=True),
    cfg.StrOpt('driver_data_namespace',
               help='Namespace for driver private data values to be '
                    'saved in.'),
    cfg.StrOpt('filter_function',
               help='String representation for an equation that will be '
                    'used to filter hosts. Only used when the driver '
                    'filter is set to be used by the Cinder scheduler.'),
    cfg.StrOpt('goodness_function',
               help='String representation for an equation that will be '
                    'used to determine the goodness of a host. Only used '
                    'when using the goodness weigher is set to be used by '
                    'the Cinder scheduler.'),
    cfg.BoolOpt('driver_ssl_cert_verify',
                default=False,
                help='If set to True the http client will validate the SSL '
                     'certificate of the backend endpoint.'),
    cfg.StrOpt('driver_ssl_cert_path',
               help='Can be used to specify a non default path to a '
               'CA_BUNDLE file or directory with certificates of '
               'trusted CAs, which will be used to validate the backend'),
    cfg.ListOpt('trace_flags',
                help='List of options that control which trace info '
                     'is written to the DEBUG log level to assist '
                     'developers. Valid values are method and api.'),
    cfg.MultiOpt('replication_device',
                 item_type=types.Dict(),
                 secret=True,
                 help="Multi opt of dictionaries to represent a replication "
                      "target device.  This option may be specified multiple "
                      "times in a single config section to specify multiple "
                      "replication target devices.  Each entry takes the "
                      "standard dict config form: replication_device = "
                      "target_device_id:<required>,"
                      "key1:value1,key2:value2..."),
    cfg.BoolOpt('image_upload_use_cinder_backend',
                default=False,
                help='If set to True, upload-to-image in raw format will '
                     'create a cloned volume and register its location to '
                     'the image service, instead of uploading the volume '
                     'content. The cinder backend and locations support '
                     'must be enabled in the image service, and '
                     'glance_api_version must be set to 2.'),
    cfg.BoolOpt('image_upload_use_internal_tenant',
                default=False,
                help='If set to True, the image volume created by '
                     'upload-to-image will be placed in the internal tenant. '
                     'Otherwise, the image volume is created in the current '
                     'context\'s tenant.'),
    cfg.BoolOpt('image_volume_cache_enabled',
                default=False,
                help='Enable the image volume cache for this backend.'),
    cfg.IntOpt('image_volume_cache_max_size_gb',
               default=0,
               help='Max size of the image volume cache for this backend in '
                    'GB. 0 => unlimited.'),
    cfg.IntOpt('image_volume_cache_max_count',
               default=0,
               help='Max number of entries allowed in the image volume cache. '
                    '0 => unlimited.'),
    cfg.BoolOpt('report_discard_supported',
                default=False,
                help='Report to clients of Cinder that the backend supports '
                     'discard (aka. trim/unmap). This will not actually '
                     'change the behavior of the backend or the client '
                     'directly, it will only notify that it can be used.'),
    cfg.StrOpt('storage_protocol',
               ignore_case=True,
               default='iscsi',
               choices=['iscsi', 'fc'],
               help='Protocol for transferring data between host and '
                    'storage back-end.'),
    cfg.BoolOpt('backup_use_temp_snapshot',
                default=False,
                help='If this is set to True, the backup_use_temp_snapshot '
                     'path will be used during the backup. Otherwise, it '
                     'will use backup_use_temp_volume path.'),
    cfg.BoolOpt('enable_unsupported_driver',
                default=False,
                help="Set this to True when you want to allow an unsupported "
                     "driver to start.  Drivers that haven't maintained a "
                     "working CI system and testing are marked as unsupported "
                     "until CI is working again.  This also marks a driver as "
                     "deprecated and may be removed in the next release."),
    cfg.StrOpt('backend_availability_zone',
               default=None,
               help='Availability zone for this volume backend. If not set, '
                    'the storage_availability_zone option value is used as '
                    'the default for all backends.'),
]

# for backward compatibility
iser_opts = [
    cfg.IntOpt('num_iser_scan_tries',
               default=3,
               help='The maximum number of times to rescan iSER target'
                    'to find volume'),
    cfg.StrOpt('iser_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='Prefix for iSER volumes'),
    cfg.StrOpt('iser_ip_address',
               default='$my_ip',
               help='The IP address that the iSER daemon is listening on'),
    cfg.PortOpt('iser_port',
                default=3260,
                help='The port that the iSER daemon is listening on'),
    cfg.StrOpt('iser_helper',
               default='tgtadm',
               help='The name of the iSER target user-land tool to use'),
]


CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(iser_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(volume_opts)
CONF.register_opts(iser_opts)
CONF.import_opt('backup_use_same_host', 'cinder.backup.api')


@six.add_metaclass(abc.ABCMeta)
class BaseVD(object):
    """Executes commands relating to Volumes.

       Base Driver for Cinder Volume Control Path,
       This includes supported/required implementation
       for API calls.  Also provides *generic* implementation
       of core features like cloning, copy_image_to_volume etc,
       this way drivers that inherit from this base class and
       don't offer their own impl can fall back on a general
       solution here.

       Key thing to keep in mind with this driver is that it's
       intended that these drivers ONLY implement Control Path
       details (create, delete, extend...), while transport or
       data path related implementation should be a *member object*
       that we call a connector.  The point here is that for example
       don't allow the LVM driver to implement iSCSI methods, instead
       call whatever connector it has configured via conf file
       (iSCSI{LIO, TGT, IET}, FC, etc).

       In the base class and for example the LVM driver we do this via a has-a
       relationship and just provide an interface to the specific connector
       methods.  How you do this in your own driver is of course up to you.
    """
    VERSION = "N/A"

    # NOTE(geguileo): By default we assume drivers don't support Active-Active
    # configurations.  If driver supports it then they can set this class
    # attribute on the driver, and if support depends on configuration options
    # then they can set it at the instance level on the driver's __init__
    # method since the manager will do the check after that.
    SUPPORTS_ACTIVE_ACTIVE = False

    # If a driver hasn't maintained their CI system, this will get
    # set to False, which prevents the driver from starting.
    # Add enable_unsupported_driver = True in cinder.conf to get
    # the unsupported driver started.
    SUPPORTED = True

    # Methods checked to detect a driver implements a replication feature
    REPLICATION_FEATURE_CHECKERS = {'v2.1': 'failover_host',
                                    'a/a': 'failover_completed'}

    def __init__(self, execute=utils.execute, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self.db = kwargs.get('db')
        self.host = kwargs.get('host')
        self.cluster_name = kwargs.get('cluster_name')
        self.configuration = kwargs.get('configuration', None)

        if self.configuration:
            self.configuration.append_config_values(volume_opts)
            self.configuration.append_config_values(iser_opts)
            utils.setup_tracing(self.configuration.safe_get('trace_flags'))

            # NOTE(geguileo): Don't allow to start if we are enabling
            # replication on a cluster service with a backend that doesn't
            # support the required mechanism for Active-Active.
            replication_devices = self.configuration.safe_get(
                'replication_device')
            if (self.cluster_name and replication_devices and
                    not self.supports_replication_feature('a/a')):
                raise exception.Invalid(_("Driver doesn't support clustered "
                                          "replication."))

        self.driver_utils = driver_utils.VolumeDriverUtils(
            self._driver_data_namespace(), self.db)

        self._execute = execute
        self._stats = {}
        self._throttle = None

        self.pools = []
        self.capabilities = {}

        # We set these mappings up in the base driver so they
        # can be used by children
        # (intended for LVM and BlockDevice, but others could use as well)
        self.target_mapping = {
            'fake': 'cinder.volume.targets.fake.FakeTarget',
            'ietadm': 'cinder.volume.targets.iet.IetAdm',
            'lioadm': 'cinder.volume.targets.lio.LioAdm',
            'tgtadm': 'cinder.volume.targets.tgt.TgtAdm',
            'scstadmin': 'cinder.volume.targets.scst.SCSTAdm',
            'iscsictl': 'cinder.volume.targets.cxt.CxtAdm'}

        # set True by manager after successful check_for_setup
        self._initialized = False

    def _driver_data_namespace(self):
        namespace = self.__class__.__name__
        if self.configuration:
            namespace = self.configuration.safe_get('driver_data_namespace')
            if not namespace:
                namespace = self.configuration.safe_get('volume_backend_name')
        return namespace

    def _is_non_recoverable(self, err, non_recoverable_list):
        for item in non_recoverable_list:
            if item in err:
                return True

        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.

        non_recoverable = kwargs.pop('no_retry_list', [])

        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except processutils.ProcessExecutionError as ex:
                tries = tries + 1

                if tries >= self.configuration.num_shell_tries or\
                        self._is_non_recoverable(ex.stderr, non_recoverable):
                    raise

                LOG.exception("Recovering from a failed execute. "
                              "Try number %s", tries)
                time.sleep(tries ** 2)

    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False, ignore_errors=False):
        """Disconnect the volume from the host.

        With the force parameter we can indicate if we give more importance to
        cleaning up as much as possible or if data integrity has higher
        priority.  This requires the latests OS-Brick code that adds this
        feature.

        We can also force errors to be ignored using ignore_errors.
        """
        # Use Brick's code to do attach/detach
        exc = brick_exception.ExceptionChainer()
        if attach_info:
            connector = attach_info['connector']
            with exc.context(force, 'Disconnect failed'):
                connector.disconnect_volume(attach_info['conn']['data'],
                                            attach_info['device'], force=force,
                                            ignore_errors=ignore_errors)

        if remote:
            # Call remote manager's terminate_connection which includes
            # driver's terminate_connection and remove export
            rpcapi = volume_rpcapi.VolumeAPI()
            with exc.context(force, 'Remote terminate connection failed'):
                rpcapi.terminate_connection(context, volume, properties,
                                            force=force)
        else:
            # Call local driver's terminate_connection and remove export.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            with exc.context(force,
                             _('Unable to terminate volume connection')):
                try:
                    self.terminate_connection(volume, properties, force=force)
                except Exception as err:
                    err_msg = (
                        _('Unable to terminate volume connection: %(err)s')
                        % {'err': err})
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=err_msg)

            with exc.context(force, _('Unable to remove export')):
                try:
                    LOG.debug("volume %s: removing export", volume['id'])
                    self.remove_export(context, volume)
                except Exception as ex:
                    LOG.exception("Error detaching volume %(volume)s, "
                                  "due to remove export failure.",
                                  {"volume": volume['id']})
                    raise exception.RemoveExportException(volume=volume['id'],
                                                          reason=ex)
        if exc and not ignore_errors:
            raise exc

    def set_initialized(self):
        self._initialized = True

    @property
    def initialized(self):
        return self._initialized

    @property
    def supported(self):
        return self.SUPPORTED

    def set_throttle(self):
        bps_limit = ((self.configuration and
                      self.configuration.safe_get('volume_copy_bps_limit')) or
                     CONF.volume_copy_bps_limit)
        cgroup_name = ((self.configuration and
                        self.configuration.safe_get(
                            'volume_copy_blkio_cgroup_name')) or
                       CONF.volume_copy_blkio_cgroup_name)
        self._throttle = None
        if bps_limit:
            try:
                self._throttle = throttling.BlkioCgroup(int(bps_limit),
                                                        cgroup_name)
            except processutils.ProcessExecutionError as err:
                LOG.warning('Failed to activate volume copy throttling: '
                            '%(err)s', {'err': err})
        throttling.Throttle.set_default(self._throttle)

    def get_version(self):
        """Get the current version of this driver."""
        return self.VERSION

    @abc.abstractmethod
    def check_for_setup_error(self):
        return

    @abc.abstractmethod
    def create_volume(self, volume):
        """Creates a volume.

        Can optionally return a Dictionary of changes to the volume object to
        be persisted.

        If volume_type extra specs includes
        'capabilities:replication <is> True' the driver
        needs to create a volume replica (secondary), and setup replication
        between the newly created volume and the secondary volume.
        Returned dictionary should include:

        .. code-block:: python

            volume['replication_status'] = 'copying'
            volume['replication_extended_status'] = <driver specific value>
            volume['driver_data'] = <driver specific value>

        """
        return

    @abc.abstractmethod
    def delete_volume(self, volume):
        """Deletes a volume.

        If volume_type extra specs includes 'replication: <is> True'
        then the driver needs to delete the volume replica too.
        """
        return

    def secure_file_operations_enabled(self):
        """Determine if driver is running in Secure File Operations mode.

        The Cinder Volume driver needs to query if this driver is running
        in a secure file operations mode. By default, it is False: any driver
        that does support secure file operations should override this method.
        """
        return False

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.

        For replication the following state should be reported:
        replication = True (None or false disables replication)
        """
        return

    def get_prefixed_property(self, property):
        """Return prefixed property name

        :returns: a prefixed property name string or None
        """

        if property and self.capabilities.get('vendor_prefix'):
            return self.capabilities.get('vendor_prefix') + ':' + property

    def _set_property(self, properties, entry, title, description,
                      type, **kwargs):
        prop = dict(title=title, description=description, type=type)
        allowed_keys = ('enum', 'default', 'minimum', 'maximum')
        for key in kwargs:
            if key in allowed_keys:
                prop[key] = kwargs[key]
        properties[entry] = prop

    def _init_standard_capabilities(self):
        """Create a dictionary of Cinder standard capabilities.

        This method creates a dictionary of Cinder standard capabilities
        and returns the created dictionary.
        The keys of this dictionary don't contain prefix and separator(:).
        """

        properties = {}
        self._set_property(
            properties,
            "thin_provisioning",
            "Thin Provisioning",
            _("Sets thin provisioning."),
            "boolean")

        self._set_property(
            properties,
            "compression",
            "Compression",
            _("Enables compression."),
            "boolean")

        self._set_property(
            properties,
            "qos",
            "QoS",
            _("Enables QoS."),
            "boolean")

        self._set_property(
            properties,
            "replication_enabled",
            "Replication",
            _("Enables replication."),
            "boolean")

        return properties

    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

        This method creates a dictionary of vendor unique properties
        and returns both created dictionary and vendor name.
        Returned vendor name is used to check for name of vendor
        unique properties.

        - Vendor name shouldn't include colon(:) because of the separator
          and it is automatically replaced by underscore(_).
          ex. abc:d -> abc_d
        - Vendor prefix is equal to vendor name.
          ex. abcd
        - Vendor unique properties must start with vendor prefix + ':'.
          ex. abcd:maxIOPS

        Each backend driver needs to override this method to expose
        its own properties using _set_property() like this:

        self._set_property(
            properties,
            "vendorPrefix:specific_property",
            "Title of property",
            _("Description of property"),
            "type")

        : return dictionary of vendor unique properties
        : return vendor name

        Example of implementation::

        properties = {}
        self._set_property(
            properties,
            "abcd:compression_type",
            "Compression type",
            _("Specifies compression type."),
            "string",
            enum=["lossy", "lossless", "special"])

        self._set_property(
            properties,
            "abcd:minIOPS",
            "Minimum IOPS QoS",
            _("Sets minimum IOPS if QoS is enabled."),
            "integer",
            minimum=10,
            default=100)

        return properties, 'abcd'
        """

        return {}, None

    def init_capabilities(self):
        """Obtain backend volume stats and capabilities list.

        This stores a dictionary which is consisted of two parts.
        First part includes static backend capabilities which are
        obtained by get_volume_stats(). Second part is properties,
        which includes parameters correspond to extra specs.
        This properties part is consisted of cinder standard
        capabilities and vendor unique properties.

        Using this capabilities list, operator can manage/configure
        backend using key/value from capabilities without specific
        knowledge of backend.
        """

        # Set static backend capabilities from get_volume_stats()
        stats = self.get_volume_stats(True)
        if stats:
            self.capabilities = stats.copy()

        # Set cinder standard capabilities
        self.capabilities['properties'] = self._init_standard_capabilities()

        # Set Vendor unique properties
        vendor_prop, vendor_name = self._init_vendor_properties()
        if vendor_name and vendor_prop:
            updated_vendor_prop = {}
            old_name = None
            # Replace colon in vendor name to underscore.
            if ':' in vendor_name:
                old_name = vendor_name
                vendor_name = vendor_name.replace(':', '_')
                LOG.warning('The colon in vendor name was replaced '
                            'by underscore. Updated vendor name is '
                            '%(name)s".', {'name': vendor_name})

            for key in vendor_prop:
                # If key has colon in vendor name field, we replace it to
                # underscore.
                # ex. abc:d:storagetype:provisioning
                #     -> abc_d:storagetype:provisioning
                if old_name and key.startswith(old_name + ':'):
                    new_key = key.replace(old_name, vendor_name, 1)
                    updated_vendor_prop[new_key] = vendor_prop[key]
                    continue
                if not key.startswith(vendor_name + ':'):
                    LOG.warning('Vendor unique property "%(property)s" '
                                'must start with vendor prefix with colon '
                                '"%(prefix)s". The property was '
                                'not registered on capabilities list.',
                                {'prefix': vendor_name + ':',
                                 'property': key})
                    continue
                updated_vendor_prop[key] = vendor_prop[key]

            # Update vendor unique properties to the dictionary
            self.capabilities['vendor_prefix'] = vendor_name
            self.capabilities['properties'].update(updated_vendor_prop)

        LOG.debug("Initialized capabilities list: %s.", self.capabilities)

    def _update_pools_and_stats(self, data):
        """Updates data for pools and volume stats based on provided data."""
        # provisioned_capacity_gb is set to None by default below, but
        # None won't be used in calculation. It will be overridden by
        # driver's provisioned_capacity_gb if reported, otherwise it
        # defaults to allocated_capacity_gb in host_manager.py.
        if self.pools:
            for pool in self.pools:
                new_pool = {}
                new_pool.update(dict(
                    pool_name=pool,
                    total_capacity_gb=0,
                    free_capacity_gb=0,
                    provisioned_capacity_gb=None,
                    reserved_percentage=100,
                    QoS_support=False,
                    filter_function=self.get_filter_function(),
                    goodness_function=self.get_goodness_function()
                ))
                data["pools"].append(new_pool)
        else:
            # No pool configured, the whole backend will be treated as a pool
            single_pool = {}
            single_pool.update(dict(
                pool_name=data["volume_backend_name"],
                total_capacity_gb=0,
                free_capacity_gb=0,
                provisioned_capacity_gb=None,
                reserved_percentage=100,
                QoS_support=False,
                filter_function=self.get_filter_function(),
                goodness_function=self.get_goodness_function()
            ))
            data["pools"].append(single_pool)
        self._stats = data

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch image from image_service and write to unencrypted volume.

        This does not attach an encryptor layer when connecting to the volume.
        """
        self._copy_image_data_to_volume(
            context, volume, image_service, image_id, encrypted=False)

    def copy_image_to_encrypted_volume(
            self, context, volume, image_service, image_id):
        """Fetch image from image_service and write to encrypted volume.

        This attaches the encryptor layer when connecting to the volume.
        """
        self._copy_image_data_to_volume(
            context, volume, image_service, image_id, encrypted=True)

    def _copy_image_data_to_volume(self, context, volume, image_service,
                                   image_id, encrypted=False):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug('copy_image_to_volume %s.', volume['name'])

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        attach_info, volume = self._attach_volume(context, volume, properties)
        try:
            if encrypted:
                encryption = self.db.volume_encryption_metadata_get(context,
                                                                    volume.id)
                utils.brick_attach_volume_encryptor(context,
                                                    attach_info,
                                                    encryption)
            try:
                image_utils.fetch_to_raw(
                    context,
                    image_service,
                    image_id,
                    attach_info['device']['path'],
                    self.configuration.volume_dd_blocksize,
                    size=volume['size'])
            except exception.ImageTooBig:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Copying image %(image_id)s "
                                  "to volume failed due to "
                                  "insufficient available space.",
                                  {'image_id': image_id})

            finally:
                if encrypted:
                    utils.brick_detach_volume_encryptor(attach_info,
                                                        encryption)
        finally:
            self._detach_volume(context, attach_info, volume, properties,
                                force=True)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        LOG.debug('copy_volume_to_image %s.', volume['name'])

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        attach_info, volume = self._attach_volume(context, volume, properties)

        try:
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      attach_info['device']['path'])
        finally:
            # Since attached volume was not used for writing we can force
            # detach it
            self._detach_volume(context, attach_info, volume, properties,
                                force=True, ignore_errors=True)

    def before_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions before copyvolume data.

        This method will be called before _copy_volume_data during volume
        migration
        """
        pass

    def after_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions after copyvolume data.

        This method will be called after _copy_volume_data during volume
        migration
        """
        pass

    def get_filter_function(self):
        """Get filter_function string.

        Returns either the string from the driver instance or global section
        in cinder.conf. If nothing is specified in cinder.conf, then try to
        find the default filter_function. When None is returned the scheduler
        will always pass the driver instance.

        :returns: a filter_function string or None
        """
        ret_function = self.configuration.filter_function
        if not ret_function:
            ret_function = CONF.filter_function
        if not ret_function:
            ret_function = self.get_default_filter_function()
        return ret_function

    def get_goodness_function(self):
        """Get good_function string.

        Returns either the string from the driver instance or global section
        in cinder.conf. If nothing is specified in cinder.conf, then try to
        find the default goodness_function. When None is returned the scheduler
        will give the lowest score to the driver instance.

        :returns: a goodness_function string or None
        """
        ret_function = self.configuration.goodness_function
        if not ret_function:
            ret_function = CONF.goodness_function
        if not ret_function:
            ret_function = self.get_default_goodness_function()
        return ret_function

    def get_default_filter_function(self):
        """Get the default filter_function string.

        Each driver could overwrite the method to return a well-known
        default string if it is available.

        :returns: None
        """
        return None

    def get_default_goodness_function(self):
        """Get the default goodness_function string.

        Each driver could overwrite the method to return a well-known
        default string if it is available.

        :returns: None
        """
        return None

    def _attach_volume(self, context, volume, properties, remote=False):
        """Attach the volume."""
        if remote:
            # Call remote manager's initialize_connection which includes
            # driver's create_export and initialize_connection
            rpcapi = volume_rpcapi.VolumeAPI()
            try:
                conn = rpcapi.initialize_connection(context, volume,
                                                    properties)
            except Exception:
                with excutils.save_and_reraise_exception():
                    # It is possible that initialize_connection fails due to
                    # timeout. In fact, the volume is already attached after
                    # the timeout error is raised, so the connection worths
                    # a try of terminating.
                    try:
                        rpcapi.terminate_connection(context, volume,
                                                    properties, force=True)
                    except Exception:
                        LOG.warning("Failed terminating the connection "
                                    "of volume %(volume_id)s, but it is "
                                    "acceptable.",
                                    {'volume_id': volume['id']})
        else:
            # Call local driver's create_export and initialize_connection.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            model_update = None
            try:
                LOG.debug("Volume %s: creating export", volume['id'])
                model_update = self.create_export(context, volume, properties)
                if model_update:
                    volume.update(model_update)
                    volume.save()
            except exception.CinderException as ex:
                if model_update:
                    LOG.exception("Failed updating model of volume "
                                  "%(volume_id)s with driver provided "
                                  "model %(model)s",
                                  {'volume_id': volume['id'],
                                   'model': model_update})
                    raise exception.ExportFailure(reason=ex)

            try:
                conn = self.initialize_connection(volume, properties)
            except Exception as err:
                try:
                    err_msg = (_('Unable to fetch connection information from '
                                 'backend: %(err)s') %
                               {'err': six.text_type(err)})
                    LOG.error(err_msg)
                    LOG.debug("Cleaning up failed connect initialization.")
                    self.remove_export(context, volume)
                except Exception as ex:
                    ex_msg = (_('Error encountered during cleanup '
                                'of a failed attach: %(ex)s') %
                              {'ex': six.text_type(ex)})
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=ex_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            # Add encrypted flag to connection_info if not set in the driver.
            if conn['data'].get('encrypted') is None:
                encrypted = bool(volume.encryption_key_id)
                conn['data']['encrypted'] = encrypted

        try:
            attach_info = self._connect_device(conn)
        except Exception as exc:
            # We may have reached a point where we have attached the volume,
            # so we have to detach it (do the cleanup).
            attach_info = getattr(exc, 'kwargs', {}).get('attach_info', None)

            try:
                LOG.debug('Device for volume %s is unavailable but did '
                          'attach, detaching it.', volume['id'])
                self._detach_volume(context, attach_info, volume,
                                    properties, force=True,
                                    remote=remote)
            except Exception:
                LOG.exception('Error detaching volume %s',
                              volume['id'])
            raise

        return (attach_info, volume)

    def _attach_snapshot(self, ctxt, snapshot, properties):
        """Attach the snapshot."""
        model_update = None
        try:
            LOG.debug("Snapshot %s: creating export.", snapshot.id)
            model_update = self.create_export_snapshot(ctxt, snapshot,
                                                       properties)
            if model_update:
                snapshot.provider_location = model_update.get(
                    'provider_location', None)
                snapshot.provider_auth = model_update.get(
                    'provider_auth', None)
                snapshot.save()
        except exception.CinderException as ex:
            if model_update:
                LOG.exception("Failed updating model of snapshot "
                              "%(snapshot_id)s with driver provided "
                              "model %(model)s.",
                              {'snapshot_id': snapshot.id,
                               'model': model_update})
                raise exception.ExportFailure(reason=ex)

        try:
            conn = self.initialize_connection_snapshot(
                snapshot, properties)
        except Exception as err:
            try:
                err_msg = (_('Unable to fetch connection information from '
                             'backend: %(err)s') %
                           {'err': six.text_type(err)})
                LOG.error(err_msg)
                LOG.debug("Cleaning up failed connect initialization.")
                self.remove_export_snapshot(ctxt, snapshot)
            except Exception as ex:
                ex_msg = (_('Error encountered during cleanup '
                            'of a failed attach: %(ex)s') %
                          {'ex': six.text_type(ex)})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=ex_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        return conn

    def _connect_device(self, conn):
        # Use Brick's code to do attach/detach
        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = conn['driver_volume_type']
        connector = utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=device_scan_attempts,
            conn=conn)
        device = connector.connect_volume(conn['data'])
        host_device = device['path']

        attach_info = {'conn': conn, 'device': device, 'connector': connector}

        unavailable = True
        try:
            # Secure network file systems will NOT run as root.
            root_access = not self.secure_file_operations_enabled()
            unavailable = not connector.check_valid_device(host_device,
                                                           root_access)
        except Exception:
            LOG.exception('Could not validate device %s', host_device)

        if unavailable:
            raise exception.DeviceUnavailable(path=host_device,
                                              attach_info=attach_info,
                                              reason=(_("Unable to access "
                                                        "the backend storage "
                                                        "via the path "
                                                        "%(path)s.") %
                                                      {'path': host_device}))
        return attach_info

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        return None, False

    def backup_use_temp_snapshot(self):
        return False

    def snapshot_remote_attachable(self):
        # TODO(lixiaoy1): the method will be deleted later when remote
        # attach snapshot is implemented.
        return False

    def get_backup_device(self, context, backup):
        """Get a backup device from an existing volume.

        The function returns a volume or snapshot to backup service,
        and then backup service attaches the device and does backup.
        """
        backup_device = None
        is_snapshot = False
        if self.backup_use_temp_snapshot():
            (backup_device, is_snapshot) = (
                self._get_backup_volume_temp_snapshot(context, backup))
        else:
            backup_device = self._get_backup_volume_temp_volume(
                context, backup)
            is_snapshot = False
        return (backup_device, is_snapshot)

    def _get_backup_volume_temp_volume(self, context, backup):
        """Return a volume to do backup.

        To backup a snapshot, create a temp volume from the snapshot and
        back it up.

        Otherwise to backup an in-use volume, create a temp volume and
        back it up.
        """
        volume = objects.Volume.get_by_id(context, backup.volume_id)
        snapshot = None
        if backup.snapshot_id:
            snapshot = objects.Snapshot.get_by_id(context, backup.snapshot_id)

        LOG.debug('Creating a new backup for volume %s.', volume['name'])

        temp_vol_ref = None
        device_to_backup = volume

        # NOTE(xyang): If it is to backup from snapshot, create a temp
        # volume from the source snapshot, backup the temp volume, and
        # then clean up the temp volume.
        if snapshot:
            temp_vol_ref = self._create_temp_volume_from_snapshot(
                context, volume, snapshot)
            backup.temp_volume_id = temp_vol_ref.id
            backup.save()
            device_to_backup = temp_vol_ref

        else:
            # NOTE(xyang): Check volume status if it is not to backup from
            # snapshot; if 'in-use', create a temp volume from the source
            # volume, backup the temp volume, and then clean up the temp
            # volume; if 'available', just backup the volume.
            previous_status = volume.get('previous_status')
            if previous_status == "in-use":
                temp_vol_ref = self._create_temp_cloned_volume(
                    context, volume)
                backup.temp_volume_id = temp_vol_ref.id
                backup.save()
                device_to_backup = temp_vol_ref

        return device_to_backup

    def _get_backup_volume_temp_snapshot(self, context, backup):
        """Return a device to backup.

        If it is to backup from snapshot, back it up directly.

        Otherwise for in-use volume, create a temp snapshot and back it up.
        """
        volume = objects.Volume.get_by_id(context, backup.volume_id)
        snapshot = None
        if backup.snapshot_id:
            snapshot = objects.Snapshot.get_by_id(context, backup.snapshot_id)

        LOG.debug('Creating a new backup for volume %s.', volume['name'])

        device_to_backup = volume
        is_snapshot = False
        temp_snapshot = None

        # NOTE(xyang): If it is to backup from snapshot, back it up
        # directly. No need to clean it up.
        if snapshot:
            device_to_backup = snapshot
            is_snapshot = True

        else:
            # NOTE(xyang): If it is not to backup from snapshot, check volume
            # status. If the volume status is 'in-use', create a temp snapshot
            # from the source volume, backup the temp snapshot, and then clean
            # up the temp snapshot; if the volume status is 'available', just
            # backup the volume.
            previous_status = volume.get('previous_status')
            if previous_status == "in-use":
                temp_snapshot = self._create_temp_snapshot(context, volume)
                backup.temp_snapshot_id = temp_snapshot.id
                backup.save()
                device_to_backup = temp_snapshot
                is_snapshot = True

        return (device_to_backup, is_snapshot)

    def _create_temp_snapshot(self, context, volume):
        kwargs = {
            'volume_id': volume['id'],
            'cgsnapshot_id': None,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': fields.SnapshotStatus.CREATING,
            'progress': '0%',
            'volume_size': volume['size'],
            'display_name': 'backup-snap-%s' % volume['id'],
            'display_description': None,
            'volume_type_id': volume['volume_type_id'],
            'encryption_key_id': volume['encryption_key_id'],
            'metadata': {},
        }
        temp_snap_ref = objects.Snapshot(context=context, **kwargs)
        temp_snap_ref.create()
        try:
            model_update = self.create_snapshot(temp_snap_ref)
            if model_update:
                temp_snap_ref.update(model_update)
        except Exception:
            with excutils.save_and_reraise_exception():
                with temp_snap_ref.obj_as_admin():
                    self.db.volume_glance_metadata_delete_by_snapshot(
                        context, temp_snap_ref.id)
                    temp_snap_ref.destroy()

        temp_snap_ref.status = fields.SnapshotStatus.AVAILABLE
        temp_snap_ref.save()
        return temp_snap_ref

    def _create_temp_volume(self, context, volume, volume_options=None):
        kwargs = {
            'size': volume.size,
            'display_name': 'backup-vol-%s' % volume.id,
            'host': volume.host,
            'cluster_name': volume.cluster_name,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'availability_zone': volume.availability_zone,
            'volume_type_id': volume.volume_type_id,
            'admin_metadata': {'temporary': 'True'},
        }
        kwargs.update(volume_options or {})
        temp_vol_ref = objects.Volume(context=context.elevated(), **kwargs)
        temp_vol_ref.create()
        return temp_vol_ref

    def _create_temp_cloned_volume(self, context, volume):
        temp_vol_ref = self._create_temp_volume(context, volume)
        try:
            model_update = self.create_cloned_volume(temp_vol_ref, volume)
            if model_update:
                temp_vol_ref.update(model_update)
        except Exception:
            with excutils.save_and_reraise_exception():
                temp_vol_ref.destroy()

        temp_vol_ref.status = 'available'
        temp_vol_ref.save()
        return temp_vol_ref

    def _create_temp_volume_from_snapshot(self, context, volume, snapshot,
                                          volume_options=None):
        temp_vol_ref = self._create_temp_volume(context, volume,
                                                volume_options=volume_options)
        try:
            model_update = self.create_volume_from_snapshot(temp_vol_ref,
                                                            snapshot)
            if model_update:
                temp_vol_ref.update(model_update)
        except Exception:
            with excutils.save_and_reraise_exception():
                temp_vol_ref.destroy()

        temp_vol_ref.status = 'available'
        temp_vol_ref.save()
        return temp_vol_ref

    def clear_download(self, context, volume):
        """Clean up after an interrupted image copy."""
        pass

    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        """Callback for volume attached to instance or host."""
        pass

    def detach_volume(self, context, volume, attachment=None):
        """Callback for volume detached."""
        pass

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        pass

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by driver."""
        pass

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        Each driver implementing this method needs to be responsible for the
        values of _name_id and provider_location. If None is returned or either
        key is not set, it means the volume table does not need to change the
        value(s) for the key(s).
        The return format is {"_name_id": value, "provider_location": value}.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        msg = _("The method update_migrated_volume is not implemented.")
        raise NotImplementedError(msg)

    @staticmethod
    def validate_connector_has_setting(connector, setting):
        pass

    def retype(self, context, volume, new_type, diff, host):
        return False, None

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        If volume_type extra specs includes 'replication: <is> True' the
        driver needs to create a volume replica (secondary)
        and setup replication between the newly created volume
        and the secondary volume.
        """
        raise NotImplementedError()

    # #######  Interface methods for DataPath (Connector) ########
    @abc.abstractmethod
    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        return

    @abc.abstractmethod
    def create_export(self, context, volume, connector):
        """Exports the volume.

        Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        return

    def create_export_snapshot(self, context, snapshot, connector):
        """Exports the snapshot.

        Can optionally return a Dictionary of changes
        to the snapshot object to be persisted.
        """
        return

    @abc.abstractmethod
    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        return

    def remove_export_snapshot(self, context, snapshot):
        """Removes an export for a snapshot."""
        return

    @abc.abstractmethod
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: The volume to be attached
        :param connector: Dictionary containing information about what is being
                          connected to.
        :returns conn_info: A dictionary of connection information.
        """
        return

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Allow connection to connector and return connection info.

        :param snapshot: The snapshot to be attached
        :param connector: Dictionary containing information about what
                          is being connected to.
        :returns conn_info: A dictionary of connection information. This
                            can optionally include a "initiator_updates"
                            field.

        The "initiator_updates" field must be a dictionary containing a
        "set_values" and/or "remove_values" field. The "set_values" field must
        be a dictionary of key-value pairs to be set/updated in the db. The
        "remove_values" field must be a list of keys, previously set with
        "set_values", that will be deleted from the db.
        """
        return

    @abc.abstractmethod
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        :param volume: The volume to be disconnected.
        :param connector: A dictionary describing the connection with details
                          about the initiator. Can be None.
        """
        return

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Disallow connection from connector."""
        return

    def get_pool(self, volume):
        """Return pool name where volume reside on.

        :param volume: The volume hosted by the driver.
        :returns: name of the pool where given volume is in.
        """
        return None

    def update_provider_info(self, volumes, snapshots):
        """Get provider info updates from driver.

        :param volumes: List of Cinder volumes to check for updates
        :param snapshots: List of Cinder snapshots to check for updates
        :returns: tuple (volume_updates, snapshot_updates)

        where volume updates {'id': uuid, provider_id: <provider-id>}
        and snapshot updates {'id': uuid, provider_id: <provider-id>}
        """
        return None, None

    def migrate_volume(self, context, volume, host):
        """Migrate volume stub.

        This is for drivers that don't implement an enhanced version
        of this operation.
        """
        return (False, None)

    def manage_existing(self, volume, existing_ref):
        """Manage exiting stub.

        This is for drivers that don't implement manage_existing().
        """
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def unmanage(self, volume):
        """Unmanage stub.

        This is for drivers that don't implement unmanage().
        """
        msg = _("Unmanage volume not implemented.")
        raise NotImplementedError(msg)

    def freeze_backend(self, context):
        """Notify the backend that it's frozen.

        We use set to prohibit the creation of any new resources
        on the backend, or any modifications to existing items on
        a backend.  We set/enforce this by not allowing scheduling
        of new volumes to the specified backend, and checking at the
        api for modifications to resources and failing.

        In most cases the driver may not need to do anything, but
        this provides a handle if they need it.

        :param context: security context
        :response: True|False
        """
        return True

    def thaw_backend(self, context):
        """Notify the backend that it's unfrozen/thawed.

        Returns the backend to a normal state after a freeze
        operation.

        In most cases the driver may not need to do anything, but
        this provides a handle if they need it.

        :param context: security context
        :response: True|False
        """
        return True

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover a backend to a secondary replication target.

        Instructs a replication capable/configured backend to failover
        to one of it's secondary replication targets. host=None is
        an acceptable input, and leaves it to the driver to failover
        to the only configured target, or to choose a target on it's
        own. All of the hosts volumes will be passed on to the driver
        in order for it to determine the replicated volumes on the host,
        if needed.

        Response is a tuple, including the new target backend_id
        AND a lit of dictionaries with volume_id and updates.
        Key things to consider (attaching failed-over volumes):
        - provider_location
        - provider_auth
        - provider_id
        - replication_status

        :param context: security context
        :param volumes: list of volume objects, in case the driver needs
                        to take action on them in some way
        :param secondary_id: Specifies rep target backend to fail over to
        :param groups: replication groups
        :returns: ID of the backend that was failed-over to,
                  model update for volumes, and model update for groups
        """

        # Example volume_updates data structure:
        # [{'volume_id': <cinder-uuid>,
        #   'updates': {'provider_id': 8,
        #               'replication_status': 'failed-over',
        #               'replication_extended_status': 'whatever',...}},]
        # Example group_updates data structure:
        # [{'group_id': <cinder-uuid>,
        #   'updates': {'replication_status': 'failed-over',...}},]
        raise NotImplementedError()

    def failover(self, context, volumes, secondary_id=None, groups=None):
        """Like failover but for a host that is clustered.

        Most of the time this will be the exact same behavior as failover_host,
        so if it's not overwritten, it is assumed to be the case.
        """
        return self.failover_host(context, volumes, secondary_id, groups)

    def failover_completed(self, context, active_backend_id=None):
        """This method is called after failover for clustered backends."""
        raise NotImplementedError()

    @classmethod
    def _is_base_method(cls, method_name):
        method = getattr(cls, method_name)
        return method.__module__ == getattr(BaseVD, method_name).__module__

    # Replication Group (Tiramisu)
    def enable_replication(self, context, group, volumes):
        """Enables replication for a group and volumes in the group.

        :param group: group object
        :param volumes: list of volume objects in the group
        :returns: model_update - dict of group updates
        :returns: volume_model_updates - list of dicts of volume updates
        """
        raise NotImplementedError()

    # Replication Group (Tiramisu)
    def disable_replication(self, context, group, volumes):
        """Disables replication for a group and volumes in the group.

        :param group: group object
        :param volumes: list of volume objects in the group
        :returns: model_update - dict of group updates
        :returns: volume_model_updates - list of dicts of volume updates
        """
        raise NotImplementedError()

    # Replication Group (Tiramisu)
    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        """Fails over replication for a group and volumes in the group.

        :param group: group object
        :param volumes: list of volume objects in the group
        :param secondary_backend_id: backend_id of the secondary site
        :returns: model_update - dict of group updates
        :returns: volume_model_updates - list of dicts of volume updates
        """
        raise NotImplementedError()

    def get_replication_error_status(self, context, groups):
        """Returns error info for replicated groups and its volumes.

        :returns: group_model_updates - list of dicts of group updates

        if error happens. For example, a dict of a group can be as follows:

        .. code:: python

          {'group_id': xxxx,
           'replication_status': fields.ReplicationStatus.ERROR}

        :returns: volume_model_updates - list of dicts of volume updates

        if error happens. For example, a dict of a volume can be as follows:

        .. code:: python

          {'volume_id': xxxx,
           'replication_status': fields.ReplicationStatus.ERROR}

        """
        return [], []

    @classmethod
    def supports_replication_feature(cls, feature):
        """Check if driver class supports replication features.

        Feature is a string that must be one of:
            - v2.1
            - a/a
        """
        if feature not in cls.REPLICATION_FEATURE_CHECKERS:
            return False

        # Check if method is being implemented/overwritten by the driver
        method_name = cls.REPLICATION_FEATURE_CHECKERS[feature]
        return not cls._is_base_method(method_name)

    def get_replication_updates(self, context):
        """Old replication update method, deprecate."""
        raise NotImplementedError()

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be created.
        :returns: model_update

        model_update will be in this format: {'status': xxx, ......}.

        If the status in model_update is 'error', the manager will throw
        an exception and it will be caught in the try-except block in the
        manager. If the driver throws an exception, the manager will also
        catch it in the try-except block. The group status in the db will
        be changed to 'error'.

        For a successful operation, the driver can either build the
        model_update and return it or return None. The group status will
        be set to 'available'.
        """
        raise NotImplementedError()

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be deleted.
        :param volumes: a list of Volume objects in the group.
        :returns: model_update, volumes_model_update

        param volumes is a list of objects retrieved from the db. It cannot
        be assigned to volumes_model_update. volumes_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate volumes_model_update and model_update
        and return them.

        The manager will check volumes_model_update and update db accordingly
        for each volume. If the driver successfully deleted some volumes
        but failed to delete others, it should set statuses of the volumes
        accordingly so that the manager can update db correctly.

        If the status in any entry of volumes_model_update is 'error_deleting'
        or 'error', the status in model_update will be set to the same if it
        is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of the group will be
        set to 'error' in the db. If volumes_model_update is not returned by
        the driver, the manager will set the status of every volume in the
        group to 'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager. The statuses of the
        group and all volumes in it will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and volumes_model_update and return them or
        return None, None. The statuses of the group and all volumes
        will be set to 'deleted' after the manager deletes them from db.
        """
        raise NotImplementedError()

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be updated.
        :param add_volumes: a list of Volume objects to be added.
        :param remove_volumes: a list of Volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update

        model_update is a dictionary that the driver wants the manager
        to update upon a successful return. If None is returned, the manager
        will set the status to 'available'.

        add_volumes_update and remove_volumes_update are lists of dictionaries
        that the driver wants the manager to update upon a successful return.
        Note that each entry requires a {'id': xxx} so that the correct
        volume entry can be updated. If None is returned, the volume will
        remain its original status. Also note that you cannot directly
        assign add_volumes to add_volumes_update as add_volumes is a list of
        volume objects and cannot be used for db update directly. Same with
        remove_volumes.

        If the driver throws an exception, the status of the group as well as
        those of the volumes to be added/removed will be set to 'error'.
        """
        raise NotImplementedError()

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of Snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of Volume objects in the source_group.
        :returns: model_update, volumes_model_update

        The source can be group_snapshot or a source_group.

        param volumes is a list of objects retrieved from the db. It cannot
        be assigned to volumes_model_update. volumes_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        To be consistent with other volume operations, the manager will
        assume the operation is successful if no exception is thrown by
        the driver. For a successful operation, the driver can either build
        the model_update and volumes_model_update and return them or
        return None, None.
        """
        raise NotImplementedError()

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is a list of Snapshot objects. It cannot be assigned
        to snapshots_model_update. snapshots_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is 'error', the
        status in model_update will be set to the same if it is not already
        'error'.

        If the status in model_update is 'error', the manager will raise an
        exception and the status of group_snapshot will be set to 'error' in
        the db. If snapshots_model_update is not returned by the driver, the
        manager will set the status of every snapshot to 'error' in the except
        block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        group_snapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of group_snapshot and all snapshots
        will be set to 'available' at the end of the manager function.
        """
        raise NotImplementedError()

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is a list of objects. It cannot be assigned to
        snapshots_model_update. snapshots_model_update is a list of of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is
        'error_deleting' or 'error', the status in model_update will be set to
        the same if it is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of group_snapshot will
        be set to 'error' in the db. If snapshots_model_update is not returned
        by the driver, the manager will set the status of every snapshot to
        'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        group_snapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of group_snapshot and all snapshots
        will be set to 'deleted' after the manager deletes them from db.
        """
        raise NotImplementedError()

    def extend_volume(self, volume, new_size):
        msg = _("Extend volume not implemented")
        raise NotImplementedError(msg)

    def accept_transfer(self, context, volume, new_user, new_project):
        pass


class LocalVD(object):
    """This class has been deprecated and should not be inherited."""
    pass


class SnapshotVD(object):
    """This class has been deprecated and should not be inherited."""
    pass


class ConsistencyGroupVD(object):
    """This class has been deprecated and should not be inherited."""
    pass


@six.add_metaclass(abc.ABCMeta)
class CloneableImageVD(object):
    @abc.abstractmethod
    def clone_image(self, volume, image_location,
                    image_id, image_meta, image_service):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        image_id is a string which represents id of the image.
        It can be used by the driver to introspect internal
        stores or registry to do an efficient image clone.

        image_meta is a dictionary that includes 'disk_format' (e.g.
        raw, qcow2) and other image attributes that allow drivers to
        decide whether they can clone the image without first requiring
        conversion.

        image_service is the reference of the image_service to use.
        Note that this is needed to be passed here for drivers that
        will want to fetch images from the image service directly.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred
        """
        return None, False


@six.add_metaclass(abc.ABCMeta)
class MigrateVD(object):
    @abc.abstractmethod
    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param context: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        return (False, None)


class ExtendVD(object):
    """This class has been deprecated and should not be inherited."""
    pass


class TransferVD(object):
    """This class has been deprecated and should not be inherited."""
    pass


@six.add_metaclass(abc.ABCMeta)
class ManageableVD(object):
    @abc.abstractmethod
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        return

    @abc.abstractmethod
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        :returns size:       Volume size in GiB (integer)
        """
        return

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a volume in the host,
        with the following keys:
        - reference (dictionary): The reference for a volume, which can be
        passed to "manage_existing".
        - size (int): The size of the volume according to the storage
        backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
        manage according to the storage backend. For example, is the volume
        in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        return []

    @abc.abstractmethod
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param volume: Cinder volume to unmanage
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class ManageableSnapshotsVD(object):
    # NOTE: Can't use abstractmethod before all drivers implement it
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        snapshot structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the
           snapshot['name'] which is how drivers traditionally map between a
           cinder snapshot and the associated backend storage object.

        2. Place some metadata on the snapshot, or somewhere in the backend,
           that allows other driver requests (e.g. delete) to locate the
           backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        """
        return

    # NOTE: Can't use abstractmethod before all drivers implement it
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        :returns size:       Volume snapshot size in GiB (integer)
        """
        return

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a snapshot in the host,
        with the following keys:
        - reference (dictionary): The reference for a snapshot, which can be
        passed to "manage_existing_snapshot".
        - size (int): The size of the snapshot according to the storage
        backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this snapshot is safe to
        manage according to the storage backend. For example, is the snapshot
        in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user
        - source_reference (string): Similar to "reference", but for the
        snapshot's source volume.

        :param cinder_snapshots: A list of snapshots in this host that Cinder
                                 currently manages, used to determine if
                                 a snapshot is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')

        """
        return []

    # NOTE: Can't use abstractmethod before all drivers implement it
    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param snapshot: Cinder volume snapshot to unmanage
        """
        pass


class VolumeDriver(ManageableVD, CloneableImageVD, ManageableSnapshotsVD,
                   MigrateVD, BaseVD):
    def check_for_setup_error(self):
        raise NotImplementedError()

    def create_volume(self, volume):
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If volume_type extra specs includes 'replication: <is> True'
        the driver needs to create a volume replica (secondary),
        and setup replication between the newly created volume and
        the secondary volume.
        """

        raise NotImplementedError()

    def create_replica_test_volume(self, volume, src_vref):
        raise NotImplementedError()

    def delete_volume(self, volume):
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        raise NotImplementedError()

    def local_path(self, volume):
        raise NotImplementedError()

    def clear_download(self, context, volume):
        pass

    def extend_volume(self, volume, new_size):
        msg = _("Extend volume not implemented")
        raise NotImplementedError(msg)

    def manage_existing(self, volume, existing_ref):
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot.

        Note: the revert process should not change the volume's
        current size, that means if the driver shrank
        the volume during the process, it should extend the
        volume internally.
        """
        msg = _("Revert volume to snapshot not implemented.")
        raise NotImplementedError(msg)

    def manage_existing_get_size(self, volume, existing_ref):
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        msg = _("Get manageable volumes not implemented.")
        raise NotImplementedError(msg)

    def unmanage(self, volume):
        pass

    def manage_existing_snapshot(self, snapshot, existing_ref):
        msg = _("Manage existing snapshot not implemented.")
        raise NotImplementedError(msg)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        msg = _("Manage existing snapshot not implemented.")
        raise NotImplementedError(msg)

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        msg = _("Get manageable snapshots not implemented.")
        raise NotImplementedError(msg)

    def unmanage_snapshot(self, snapshot):
        """Unmanage the specified snapshot from Cinder management."""

    def retype(self, context, volume, new_type, diff, host):
        return False, None

    # #######  Interface methods for DataPath (Connector) ########
    def ensure_export(self, context, volume):
        raise NotImplementedError()

    def create_export(self, context, volume, connector):
        raise NotImplementedError()

    def create_export_snapshot(self, context, snapshot, connector):
        raise NotImplementedError()

    def remove_export(self, context, volume):
        raise NotImplementedError()

    def remove_export_snapshot(self, context, snapshot):
        raise NotImplementedError()

    def initialize_connection(self, volume, connector, **kwargs):
        raise NotImplementedError()

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Allow connection from connector for a snapshot."""

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector

        :param volume: The volume to be disconnected.
        :param connector: A dictionary describing the connection with details
                          about the initiator. Can be None.
        """

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Disallow connection from connector for a snapshot."""

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :returns: model_update

        model_update will be in this format: {'status': xxx, ......}.

        If the status in model_update is 'error', the manager will throw
        an exception and it will be caught in the try-except block in the
        manager. If the driver throws an exception, the manager will also
        catch it in the try-except block. The group status in the db will
        be changed to 'error'.

        For a successful operation, the driver can either build the
        model_update and return it or return None. The group status will
        be set to 'available'.
        """
        raise NotImplementedError()

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistencygroup from source.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        :returns: model_update, volumes_model_update

        The source can be cgsnapshot or a source cg.

        param volumes is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Volume to be precise. It cannot be
        assigned to volumes_model_update. volumes_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        To be consistent with other volume operations, the manager will
        assume the operation is successful if no exception is thrown by
        the driver. For a successful operation, the driver can either build
        the model_update and volumes_model_update and return them or
        return None, None.
        """
        raise NotImplementedError()

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be deleted.
        :param volumes: a list of volume dictionaries in the group.
        :returns: model_update, volumes_model_update

        param volumes is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Volume to be precise. It cannot be
        assigned to volumes_model_update. volumes_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate volumes_model_update and model_update
        and return them.

        The manager will check volumes_model_update and update db accordingly
        for each volume. If the driver successfully deleted some volumes
        but failed to delete others, it should set statuses of the volumes
        accordingly so that the manager can update db correctly.

        If the status in any entry of volumes_model_update is 'error_deleting'
        or 'error', the status in model_update will be set to the same if it
        is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of the group will be
        set to 'error' in the db. If volumes_model_update is not returned by
        the driver, the manager will set the status of every volume in the
        group to 'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager. The statuses of the
        group and all volumes in it will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and volumes_model_update and return them or
        return None, None. The statuses of the group and all volumes
        will be set to 'deleted' after the manager deletes them from db.
        """
        raise NotImplementedError()

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update

        model_update is a dictionary that the driver wants the manager
        to update upon a successful return. If None is returned, the manager
        will set the status to 'available'.

        add_volumes_update and remove_volumes_update are lists of dictionaries
        that the driver wants the manager to update upon a successful return.
        Note that each entry requires a {'id': xxx} so that the correct
        volume entry can be updated. If None is returned, the volume will
        remain its original status. Also note that you cannot directly
        assign add_volumes to add_volumes_update as add_volumes is a list of
        cinder.db.sqlalchemy.models.Volume objects and cannot be used for
        db update directly. Same with remove_volumes.

        If the driver throws an exception, the status of the group as well as
        those of the volumes to be added/removed will be set to 'error'.
        """
        raise NotImplementedError()

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be created.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Snapshot to be precise. It cannot be
        assigned to snapshots_model_update. snapshots_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is 'error', the
        status in model_update will be set to the same if it is not already
        'error'.

        If the status in model_update is 'error', the manager will raise an
        exception and the status of cgsnapshot will be set to 'error' in the
        db. If snapshots_model_update is not returned by the driver, the
        manager will set the status of every snapshot to 'error' in the except
        block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        cgsnapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of cgsnapshot and all snapshots
        will be set to 'available' at the end of the manager function.
        """
        raise NotImplementedError()

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be deleted.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Snapshot to be precise. It cannot be
        assigned to snapshots_model_update. snapshots_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is
        'error_deleting' or 'error', the status in model_update will be set to
        the same if it is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of cgsnapshot will be
        set to 'error' in the db. If snapshots_model_update is not returned by
        the driver, the manager will set the status of every snapshot to
        'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        cgsnapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of cgsnapshot and all snapshots
        will be set to 'deleted' after the manager deletes them from db.
        """
        raise NotImplementedError()

    def clone_image(self, volume, image_location, image_id, image_meta,
                    image_service):
        return None, False

    def get_pool(self, volume):
        """Return pool name where volume reside on.

        :param volume: The volume hosted by the driver.
        :returns: name of the pool where given volume is in.
        """
        return None

    def migrate_volume(self, context, volume, host):
        return (False, None)

    def accept_transfer(self, context, volume, new_user, new_project):
        pass


class ProxyVD(object):
    """Proxy Volume Driver to mark proxy drivers

        If a driver uses a proxy class (e.g. by using __setattr__ and
        __getattr__) without directly inheriting from base volume driver this
        class can help marking them and retrieve the actual used driver object.
    """
    def _get_driver(self):
        """Returns the actual driver object.

        Can be overloaded by the proxy.
        """
        return getattr(self, "driver", None)


class ISCSIDriver(VolumeDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSCSI target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """

    def __init__(self, *args, **kwargs):
        super(ISCSIDriver, self).__init__(*args, **kwargs)

    def _do_iscsi_discovery(self, volume):
        # TODO(justinsb): Deprecate discovery and use stored info
        # NOTE(justinsb): Discovery won't work with CHAP-secured targets (?)
        LOG.warning("ISCSI provider_location not stored, using discovery")

        volume_name = volume['name']

        try:
            # NOTE(griff) We're doing the split straight away which should be
            # safe since using '@' in hostname is considered invalid

            (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                        '-t', 'sendtargets', '-p',
                                        volume['host'].split('@')[0],
                                        run_as_root=True)
        except processutils.ProcessExecutionError as ex:
            LOG.error("ISCSI discovery attempt failed for:%s",
                      volume['host'].split('@')[0])
            LOG.debug("Error from iscsiadm -m discovery: %s", ex.stderr)
            return None

        for target in out.splitlines():
            if (self.configuration.iscsi_ip_address in target
                    and volume_name in target):
                return target
        return None

    def _get_iscsi_properties(self, volume, multipath=False):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the id of the volume (currently used by xen)

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.

        :discard:    boolean indicating if discard is supported

        In some of drivers that support multiple connections (for multipath
        and for single path with failover on connection failure), it returns
        :target_iqns, :target_portals, :target_luns, which contain lists of
        multiple values. The main portal information is also returned in
        :target_iqn, :target_portal, :target_lun for backward compatibility.

        Note that some of drivers don't return :target_portals even if they
        support multipath. Then the connector should use sendtargets discovery
        to find the other portals if it supports multipath.
        """

        properties = {}

        location = volume['provider_location']

        if location:
            # provider_location is the same format as iSCSI discovery output
            properties['target_discovered'] = False
        else:
            location = self._do_iscsi_discovery(volume)

            if not location:
                msg = (_("Could not find iSCSI export for volume %s") %
                        (volume['name']))
                raise exception.InvalidVolume(reason=msg)

            LOG.debug("ISCSI Discovery: Found %s", location)
            properties['target_discovered'] = True

        results = location.split(" ")
        portals = results[0].split(",")[0].split(";")
        iqn = results[1]
        nr_portals = len(portals)

        try:
            lun = int(results[2])
        except (IndexError, ValueError):
            if (self.configuration.volume_driver ==
                    'cinder.volume.drivers.lvm.ThinLVMVolumeDriver' and
                    self.configuration.iscsi_helper == 'tgtadm'):
                lun = 1
            else:
                lun = 0

        if nr_portals > 1:
            properties['target_portals'] = portals
            properties['target_iqns'] = [iqn] * nr_portals
            properties['target_luns'] = [lun] * nr_portals
        properties['target_portal'] = portals[0]
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        geometry = volume.get('provider_geometry', None)
        if geometry:
            (physical_block_size, logical_block_size) = geometry.split()
            properties['physical_block_size'] = physical_block_size
            properties['logical_block_size'] = logical_block_size

        encryption_key_id = volume.get('encryption_key_id', None)
        properties['encrypted'] = encryption_key_id is not None

        return properties

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s",
                  {'command': iscsi_command, 'out': out, 'err': err})
        return (out, err)

    def _run_iscsiadm_bare(self, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm',
                                   *iscsi_command,
                                   run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s",
                  {'command': iscsi_command, 'out': out, 'err': err})
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value,
                         **kwargs):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command, **kwargs)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                    'discard': False,
                }
            }

        If the backend driver supports multiple connections for multipath and
        for single path with failover, "target_portals", "target_iqns",
        "target_luns" are also populated::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': False,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume1',
                    'target_iqns': ['iqn.2010-10.org.openstack:volume1',
                                    'iqn.2010-10.org.openstack:volume1-2'],
                    'target_portal': '10.0.0.1:3260',
                    'target_portals': ['10.0.0.1:3260', '10.0.1.1:3260']
                    'target_lun': 1,
                    'target_luns': [1, 1],
                    'volume_id': 1,
                    'discard': False,
                }
            }
        """
        # NOTE(jdg): Yes, this is duplicated in the volume/target
        # drivers, for now leaving it as there are 3'rd party
        # drivers that don't use target drivers, but inherit from
        # this base class and use this init data
        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type':
                self.configuration.safe_get('iscsi_protocol'),
            'data': iscsi_properties
        }

    def validate_connector(self, connector):
        # iSCSI drivers require the initiator information
        required = 'initiator'
        if required not in connector:
            LOG.error('The volume driver requires %(data)s '
                      'in the connector.', {'data': required})
            raise exception.InvalidConnectorException(missing=required)

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats...")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'Generic_iSCSI'
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'iSCSI'
        data["pools"] = []
        data["replication_enabled"] = False

        self._update_pools_and_stats(data)


class ISERDriver(ISCSIDriver):
    """Executes commands relating to ISER volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSER target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """
    def __init__(self, *args, **kwargs):
        super(ISERDriver, self).__init__(*args, **kwargs)
        # for backward compatibility
        self.configuration.num_volume_device_scan_tries = \
            self.configuration.num_iser_scan_tries
        self.configuration.iscsi_target_prefix = \
            self.configuration.iser_target_prefix
        self.configuration.iscsi_ip_address = \
            self.configuration.iser_ip_address
        self.configuration.iscsi_port = self.configuration.iser_port

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iser driver returns a driver_volume_type of 'iser'.
        The format of the driver data is defined in _get_iser_properties.
        Example return value:

        .. code-block:: default

            {
                'driver_volume_type': 'iser',
                'data': {
                    'target_discovered': True,
                    'target_iqn':
                    'iqn.2010-10.org.iser.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1
                }
            }

        """
        iser_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iser',
            'data': iser_properties
        }

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats...")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'Generic_iSER'
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'iSER'
        data["pools"] = []

        self._update_pools_and_stats(data)


class FibreChannelDriver(VolumeDriver):
    """Executes commands relating to Fibre Channel volumes."""
    def __init__(self, *args, **kwargs):
        super(FibreChannelDriver, self).__init__(*args, **kwargs)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:

        .. code-block:: default

            {
                'driver_volume_type': 'fibre_channel',
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                    'discard': False
                }
            }

        or

        .. code-block:: default

             {
                'driver_volume_type': 'fibre_channel',
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                    'discard': False
                }
            }

        """
        msg = _("Driver must implement initialize_connection")
        raise NotImplementedError(msg)

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by driver.

        Do a check on the connector and ensure that it has wwnns, wwpns.
        """
        self.validate_connector_has_setting(connector, 'wwpns')
        self.validate_connector_has_setting(connector, 'wwnns')

    @staticmethod
    def validate_connector_has_setting(connector, setting):
        """Test for non-empty setting in connector."""
        if setting not in connector or not connector[setting]:
            LOG.error(
                "FibreChannelDriver validate_connector failed. "
                "No '%(setting)s'. Make sure HBA state is Online.",
                {'setting': setting})
            raise exception.InvalidConnectorException(missing=setting)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats...")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'Generic_FC'
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'FC'
        data["pools"] = []

        self._update_pools_and_stats(data)
