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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE, _LW
from cinder.image import image_utils
from cinder import objects
from cinder import utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import throttling
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)


deprecated_use_chap_auth_opts = [cfg.DeprecatedOpt('eqlx_use_chap')]
deprecated_chap_username_opts = [cfg.DeprecatedOpt('eqlx_chap_login')]
deprecated_chap_password_opts = [cfg.DeprecatedOpt('eqlx_chap_password')]

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
    cfg.IntOpt('iscsi_port',
               default=3260,
               min=1, max=65535,
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
               choices=['none', 'zero', 'shred'],
               help='Method used to wipe old volumes'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               help='Size in MiB to wipe at start of old volumes. 0 => all'),
    cfg.StrOpt('volume_clear_ionice',
               help='The flag to pass to ionice to alter the i/o priority '
                    'of the process used to zero a volume after deletion, '
                    'for example "-c3" for idle only priority.'),
    cfg.StrOpt('iscsi_helper',
               default='tgtadm',
               choices=['tgtadm', 'lioadm', 'scstadmin', 'iseradm', 'iscsictl',
                        'ietadm', 'fake'],
               help='iSCSI target user-land tool to use. tgtadm is default, '
                    'use lioadm for LIO iSCSI support, scstadmin for SCST '
                    'target support, iseradm for the ISER protocol, ietadm '
                    'for iSCSI Enterprise Target, iscsictl for Chelsio iSCSI '
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
                    'to tgtadm or iseradm.'),
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
                      'capacity. A ratio lower than 1.0 will be ignored and '
                      'the default value will be used instead.'),
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
                     'targets.',
                deprecated_opts=deprecated_use_chap_auth_opts),
    cfg.StrOpt('chap_username',
               default='',
               help='CHAP user name.',
               deprecated_opts=deprecated_chap_username_opts),
    cfg.StrOpt('chap_password',
               default='',
               help='Password for specified CHAP account name.',
               deprecated_opts=deprecated_chap_password_opts,
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
    cfg.ListOpt('trace_flags',
                help='List of options that control which trace info '
                     'is written to the DEBUG log level to assist '
                     'developers. Valid values are method and api.'),
    cfg.MultiOpt('replication_device',
                 item_type=types.Dict(),
                 help="Multi opt of dictionaries to represent a replication "
                      "target device.  This option may be specified multiple "
                      "times in a single config section to specify multiple "
                      "replication target devices.  Each entry takes the "
                      "standard dict config form: replication_device = "
                      "device_target_id:<required>,"
                      "managed_backend_name:<host@backend_name>,"
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
    cfg.IntOpt('iser_port',
               default=3260,
               min=1, max=65535,
               help='The port that the iSER daemon is listening on'),
    cfg.StrOpt('iser_helper',
               default='tgtadm',
               help='The name of the iSER target user-land tool to use'),
]


CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.register_opts(iser_opts)


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

    def __init__(self, execute=utils.execute, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self.db = kwargs.get('db')
        self.host = kwargs.get('host')
        self.configuration = kwargs.get('configuration', None)

        if self.configuration:
            self.configuration.append_config_values(volume_opts)
            self.configuration.append_config_values(iser_opts)
            utils.setup_tracing(self.configuration.safe_get('trace_flags'))

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
            'iseradm': 'cinder.volume.targets.iser.ISERTgtAdm',
            'lioadm': 'cinder.volume.targets.lio.LioAdm',
            'tgtadm': 'cinder.volume.targets.tgt.TgtAdm',
            'scstadmin': 'cinder.volume.targets.scst.SCSTAdm',
            'iscsictl': 'cinder.volume.targets.cxt.CxtAdm'}

        # set True by manager after successful check_for_setup
        self._initialized = False

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

                LOG.exception(_LE("Recovering from a failed execute.  "
                                  "Try number %s"), tries)
                time.sleep(tries ** 2)

    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False):
        """Disconnect the volume from the host."""
        # Use Brick's code to do attach/detach
        connector = attach_info['connector']
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'])

        if remote:
            # Call remote manager's terminate_connection which includes
            # driver's terminate_connection and remove export
            rpcapi = volume_rpcapi.VolumeAPI()
            rpcapi.terminate_connection(context, volume, properties,
                                        force=force)
        else:
            # Call local driver's terminate_connection and remove export.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            try:
                self.terminate_connection(volume, properties, force=force)
            except Exception as err:
                err_msg = (_('Unable to terminate volume connection: %(err)s')
                           % {'err': six.text_type(err)})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            try:
                LOG.debug("volume %s: removing export", volume['id'])
                self.remove_export(context, volume)
            except Exception as ex:
                LOG.exception(_LE("Error detaching volume %(volume)s, "
                                  "due to remove export failure."),
                              {"volume": volume['id']})
                raise exception.RemoveExportException(volume=volume['id'],
                                                      reason=ex)

    def _detach_snapshot(self, context, attach_info, snapshot, properties,
                         force=False, remote=False):
        """Disconnect the snapshot from the host."""
        # Use Brick's code to do attach/detach
        connector = attach_info['connector']
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'])

        # NOTE(xyang): This method is introduced for non-disruptive backup.
        # Currently backup service has to be on the same node as the volume
        # driver. Therefore it is not possible to call a volume driver on a
        # remote node. In the future, if backup can be done from a remote
        # node, this function can be modified to allow RPC calls. The remote
        # flag in the interface is for anticipation that it will be enabled
        # in the future.
        if remote:
            LOG.error(_LE("Detaching snapshot from a remote node "
                          "is not supported."))
            raise exception.NotSupportedOperation(
                operation=_("detach snapshot from remote node"))
        else:
            # Call local driver's terminate_connection and remove export.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            try:
                self.terminate_connection_snapshot(snapshot, properties,
                                                   force=force)
            except Exception as err:
                err_msg = (_('Unable to terminate volume connection: %(err)s')
                           % {'err': six.text_type(err)})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            try:
                LOG.debug("Snapshot %s: removing export.", snapshot.id)
                self.remove_export_snapshot(context, snapshot)
            except Exception as ex:
                LOG.exception(_LE("Error detaching snapshot %(snapshot)s, "
                                  "due to remove export failure."),
                              {"snapshot": snapshot.id})
                raise exception.RemoveExportException(volume=snapshot.id,
                                                      reason=ex)

    def set_initialized(self):
        self._initialized = True

    @property
    def initialized(self):
        return self._initialized

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
                LOG.warning(_LW('Failed to activate volume copy throttling: '
                                '%(err)s'), {'err': err})
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
            volume['replication_status'] = 'copying'
            volume['replication_extended_status'] = driver specific value
            volume['driver_data'] = driver specific value
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

        :return a prefixed property name string or None
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
            "replication",
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
                LOG.warning(_LW('The colon in vendor name was replaced '
                                'by underscore. Updated vendor name is '
                                '%(name)s".'), {'name': vendor_name})

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
                    LOG.warning(_LW('Vendor unique property "%(property)s" '
                                    'must start with vendor prefix with colon '
                                    '"%(prefix)s". The property was '
                                    'not registered on capabilities list.'),
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

    def copy_volume_data(self, context, src_vol, dest_vol, remote=None):
        """Copy data from src_vol to dest_vol."""
        LOG.debug('copy_data_between_volumes %(src)s -> %(dest)s.', {
            'src': src_vol['name'], 'dest': dest_vol['name']})

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        dest_remote = True if remote in ['dest', 'both'] else False
        dest_orig_status = dest_vol['status']
        try:
            dest_attach_info, dest_vol = self._attach_volume(
                context,
                dest_vol,
                properties,
                remote=dest_remote)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to attach volume %(vol)s"),
                          {'vol': dest_vol['id']})
                self.db.volume_update(context, dest_vol['id'],
                                      {'status': dest_orig_status})

        src_remote = True if remote in ['src', 'both'] else False
        src_orig_status = src_vol['status']
        try:
            src_attach_info, src_vol = self._attach_volume(context,
                                                           src_vol,
                                                           properties,
                                                           remote=src_remote)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to attach volume %(vol)s"),
                          {'vol': src_vol['id']})
                self.db.volume_update(context, src_vol['id'],
                                      {'status': src_orig_status})
                self._detach_volume(context, dest_attach_info, dest_vol,
                                    properties, force=True, remote=dest_remote)

        # Check the backend capabilities of migration destination host.
        rpcapi = volume_rpcapi.VolumeAPI()
        capabilities = rpcapi.get_capabilities(context, dest_vol['host'],
                                               False)
        sparse_copy_volume = bool(capabilities and
                                  capabilities.get('sparse_copy_volume',
                                                   False))

        copy_error = True
        try:
            size_in_mb = int(src_vol['size']) * 1024    # vol size is in GB
            volume_utils.copy_volume(
                src_attach_info['device']['path'],
                dest_attach_info['device']['path'],
                size_in_mb,
                self.configuration.volume_dd_blocksize,
                throttle=self._throttle,
                sparse=sparse_copy_volume)
            copy_error = False
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to copy volume %(src)s to %(dest)s."),
                          {'src': src_vol['id'], 'dest': dest_vol['id']})
        finally:
            self._detach_volume(context, dest_attach_info, dest_vol,
                                properties, force=copy_error,
                                remote=dest_remote)
            self._detach_volume(context, src_attach_info, src_vol,
                                properties, force=copy_error,
                                remote=src_remote)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug('copy_image_to_volume %s.', volume['name'])

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        attach_info, volume = self._attach_volume(context, volume, properties)

        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     attach_info['device']['path'],
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])
        finally:
            self._detach_volume(context, attach_info, volume, properties)

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
            self._detach_volume(context, attach_info, volume, properties)

    def get_filter_function(self):
        """Get filter_function string.

        Returns either the string from the driver instance or global section
        in cinder.conf. If nothing is specified in cinder.conf, then try to
        find the default filter_function. When None is returned the scheduler
        will always pass the driver instance.

        :return a filter_function string or None
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

        :return a goodness_function string or None
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

        :return: None
        """
        return None

    def get_default_goodness_function(self):
        """Get the default goodness_function string.

        Each driver could overwrite the method to return a well-known
        default string if it is available.

        :return: None
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
                        LOG.warning(_LW("Failed terminating the connection "
                                        "of volume %(volume_id)s, but it is "
                                        "acceptable."),
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
                    volume = self.db.volume_update(context, volume['id'],
                                                   model_update)
            except exception.CinderException as ex:
                if model_update:
                    LOG.exception(_LE("Failed updating model of volume "
                                      "%(volume_id)s with driver provided "
                                      "model %(model)s"),
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

        try:
            attach_info = self._connect_device(conn)
        except exception.DeviceUnavailable as exc:
            # We may have reached a point where we have attached the volume,
            # so we have to detach it (do the cleanup).
            attach_info = exc.kwargs.get('attach_info', None)
            if attach_info:
                try:
                    LOG.debug('Device for volume %s is unavailable but did '
                              'attach, detaching it.', volume['id'])
                    self._detach_volume(context, attach_info, volume,
                                        properties, force=True,
                                        remote=remote)
                except Exception:
                    LOG.exception(_LE('Error detaching volume %s'),
                                  volume['id'])
            raise

        return (attach_info, volume)

    def _attach_snapshot(self, context, snapshot, properties, remote=False):
        """Attach the snapshot."""
        # NOTE(xyang): This method is introduced for non-disruptive backup.
        # Currently backup service has to be on the same node as the volume
        # driver. Therefore it is not possible to call a volume driver on a
        # remote node. In the future, if backup can be done from a remote
        # node, this function can be modified to allow RPC calls. The remote
        # flag in the interface is for anticipation that it will be enabled
        # in the future.
        if remote:
            LOG.error(_LE("Attaching snapshot from a remote node "
                          "is not supported."))
            raise exception.NotSupportedOperation(
                operation=_("attach snapshot from remote node"))
        else:
            # Call local driver's create_export and initialize_connection.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            model_update = None
            try:
                LOG.debug("Snapshot %s: creating export.", snapshot.id)
                model_update = self.create_export_snapshot(context, snapshot,
                                                           properties)
                if model_update:
                    snapshot.provider_location = model_update.get(
                        'provider_location', None)
                    snapshot.provider_auth = model_update.get(
                        'provider_auth', None)
                    snapshot.save()
            except exception.CinderException as ex:
                if model_update:
                    LOG.exception(_LE("Failed updating model of snapshot "
                                      "%(snapshot_id)s with driver provided "
                                      "model %(model)s."),
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
                    self.remove_export_snapshot(context, snapshot)
                except Exception as ex:
                    ex_msg = (_('Error encountered during cleanup '
                                'of a failed attach: %(ex)s') %
                              {'ex': six.text_type(ex)})
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=ex_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)
        return (self._connect_device(conn), snapshot)

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
            LOG.exception(_LE('Could not validate device %s'), host_device)

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

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        if self.backup_use_temp_snapshot():
            self._backup_volume_temp_snapshot(context, backup,
                                              backup_service)
        else:
            self._backup_volume_temp_volume(context, backup,
                                            backup_service)

    def _backup_volume_temp_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume.

        For in-use volume, create a temp volume and back it up.
        """
        volume = self.db.volume_get(context, backup.volume_id)

        LOG.debug('Creating a new backup for volume %s.', volume['name'])

        # NOTE(xyang): Check volume status; if 'in-use', create a temp
        # volume from the source volume, backup the temp volume, and
        # then clean up the temp volume; if 'available', just backup the
        # volume.
        previous_status = volume.get('previous_status', None)
        device_to_backup = volume
        temp_vol_ref = None
        if previous_status == "in-use":
            temp_vol_ref = self._create_temp_cloned_volume(
                context, volume)
            backup.temp_volume_id = temp_vol_ref['id']
            backup.save()
            device_to_backup = temp_vol_ref

        self._backup_device(context, backup, backup_service, device_to_backup)

        if temp_vol_ref:
            self._delete_temp_volume(context, temp_vol_ref)
            backup.temp_volume_id = None
            backup.save()

    def _backup_volume_temp_snapshot(self, context, backup, backup_service):
        """Create a new backup from an existing volume.

        For in-use volume, create a temp snapshot and back it up.
        """
        volume = self.db.volume_get(context, backup.volume_id)

        LOG.debug('Creating a new backup for volume %s.', volume['name'])

        # NOTE(xyang): Check volume status; if 'in-use', create a temp
        # snapshot from the source volume, backup the temp snapshot, and
        # then clean up the temp snapshot; if 'available', just backup the
        # volume.
        previous_status = volume.get('previous_status', None)
        device_to_backup = volume
        is_snapshot = False
        temp_snapshot = None
        if previous_status == "in-use":
            temp_snapshot = self._create_temp_snapshot(context, volume)
            backup.temp_snapshot_id = temp_snapshot.id
            backup.save()
            device_to_backup = temp_snapshot
            is_snapshot = True

        self._backup_device(context, backup, backup_service, device_to_backup,
                            is_snapshot)

        if temp_snapshot:
            self._delete_temp_snapshot(context, temp_snapshot)
            backup.temp_snapshot_id = None
            backup.save()

    def _backup_device(self, context, backup, backup_service, device,
                       is_snapshot=False):
        """Create a new backup from a volume or snapshot."""

        LOG.debug('Creating a new backup for %s.', device['name'])
        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        if is_snapshot:
            attach_info, device = self._attach_snapshot(context, device,
                                                        properties)
        else:
            attach_info, device = self._attach_volume(context, device,
                                                      properties)
        try:
            device_path = attach_info['device']['path']

            # Secure network file systems will not chown files.
            if self.secure_file_operations_enabled():
                with open(device_path) as device_file:
                    backup_service.backup(backup, device_file)
            else:
                with utils.temporary_chown(device_path):
                    with open(device_path) as device_file:
                        backup_service.backup(backup, device_file)

        finally:
            if is_snapshot:
                self._detach_snapshot(context, attach_info, device, properties)
            else:
                self._detach_volume(context, attach_info, device, properties)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        LOG.debug(('Restoring backup %(backup)s to '
                   'volume %(volume)s.'),
                  {'backup': backup['id'],
                   'volume': volume['name']})

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        properties = utils.brick_get_connector_properties(use_multipath,
                                                          enforce_multipath)
        attach_info, volume = self._attach_volume(context, volume, properties)

        try:
            volume_path = attach_info['device']['path']

            # Secure network file systems will not chown files.
            if self.secure_file_operations_enabled():
                with open(volume_path, 'wb') as volume_file:
                    backup_service.restore(backup, volume['id'], volume_file)
            else:
                with utils.temporary_chown(volume_path):
                    with open(volume_path, 'wb') as volume_file:
                        backup_service.restore(backup, volume['id'],
                                               volume_file)

        finally:
            self._detach_volume(context, attach_info, volume, properties)

    def _create_temp_snapshot(self, context, volume):
        kwargs = {
            'volume_id': volume['id'],
            'cgsnapshot_id': None,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
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
            self.create_snapshot(temp_snap_ref)
        except Exception:
            with excutils.save_and_reraise_exception():
                with temp_snap_ref.obj_as_admin():
                    self.db.volume_glance_metadata_delete_by_snapshot(
                        context, temp_snap_ref.id)
                    temp_snap_ref.destroy()

        temp_snap_ref.status = 'available'
        temp_snap_ref.save()
        return temp_snap_ref

    def _create_temp_cloned_volume(self, context, volume):
        temp_volume = {
            'size': volume['size'],
            'display_name': 'backup-vol-%s' % volume['id'],
            'host': volume['host'],
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
        }
        temp_vol_ref = self.db.volume_create(context, temp_volume)
        try:
            self.create_cloned_volume(temp_vol_ref, volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_destroy(context.elevated(),
                                       temp_vol_ref['id'])

        self.db.volume_update(context, temp_vol_ref['id'],
                              {'status': 'available'})
        return temp_vol_ref

    def _delete_temp_snapshot(self, context, snapshot):
        self.delete_snapshot(snapshot)
        with snapshot.obj_as_admin():
            self.db.volume_glance_metadata_delete_by_snapshot(
                context, snapshot.id)
            snapshot.destroy()

    def _delete_temp_volume(self, context, volume):
        self.delete_volume(volume)
        context = context.elevated()
        self.db.volume_destroy(context, volume['id'])

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
        :return model_update to update DB with any needed changes
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
    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info.

        :param volume: The volume to be attached
        :param connector: Dictionary containing information about what is being
        connected to.
        :param initiator_data (optional): A dictionary of driver_initiator_data
        objects with key-value pairs that have been saved for this initiator by
        a driver in previous initialize_connection calls.
        :returns conn_info: A dictionary of connection information. This can
        optionally include a "initiator_updates" field.

        The "initiator_updates" field must be a dictionary containing a
        "set_values" and/or "remove_values" field. The "set_values" field must
        be a dictionary of key-value pairs to be set/updated in the db. The
        "remove_values" field must be a list of keys, previously set with
        "set_values", that will be deleted from the db.
        """
        return

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Allow connection to connector and return connection info.

        :param snapshot: The snapshot to be attached
        :param connector: Dictionary containing information about what is being
        connected to.
        :returns conn_info: A dictionary of connection information. This can
        optionally include a "initiator_updates" field.

        The "initiator_updates" field must be a dictionary containing a
        "set_values" and/or "remove_values" field. The "set_values" field must
        be a dictionary of key-value pairs to be set/updated in the db. The
        "remove_values" field must be a list of keys, previously set with
        "set_values", that will be deleted from the db.
        """
        return

    @abc.abstractmethod
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        return

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Disallow connection from connector."""
        return

    def get_pool(self, volume):
        """Return pool name where volume reside on.

        :param volume: The volume hosted by the the driver.
        :return: name of the pool where given volume is in.
        """
        return None

    def update_provider_info(self, volumes, snapshots):
        """Get provider info updates from driver.

        :param volumes: List of Cinder volumes to check for updates
        :param snapshots: List of Cinder snapshots to check for updates
        :return: tuple (volume_updates, snapshot_updates)

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


@six.add_metaclass(abc.ABCMeta)
class LocalVD(object):
    @abc.abstractmethod
    def local_path(self, volume):
        return


@six.add_metaclass(abc.ABCMeta)
class SnapshotVD(object):
    @abc.abstractmethod
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        return

    @abc.abstractmethod
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        return

    @abc.abstractmethod
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If volume_type extra specs includes 'replication: <is> True'
        the driver needs to create a volume replica (secondary),
        and setup replication between the newly created volume and
        the secondary volume.
        """
        return


@six.add_metaclass(abc.ABCMeta)
class ConsistencyGroupVD(object):
    @abc.abstractmethod
    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        return

    @abc.abstractmethod
    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        return

    @abc.abstractmethod
    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        return

    @abc.abstractmethod
    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        return


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

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        return (False, None)


@six.add_metaclass(abc.ABCMeta)
class ExtendVD(object):
    @abc.abstractmethod
    def extend_volume(self, volume, new_size):
        return


@six.add_metaclass(abc.ABCMeta)
class TransferVD(object):
    def accept_transfer(self, context, volume, new_user, new_project):
        """Accept the transfer of a volume for a new user/project."""
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
        """
        return

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
class ReplicaV2VD(object):
    """Cinder replication functionality.

    The Cinder replication functionality is set up primarily through
    the use of volume-types in conjunction with the filter scheduler.
    This requires:
    1. The driver reports "replication = True" in it's capabilities
    2. The cinder.conf file includes the valid_replication_devices section

    The driver configuration is expected to take one of the following two
    forms, see devref replication docs for details.

    Note we provide cinder.volume.utils.convert_config_string_to_dict
    to parse this out into a usable proper dictionary.

    """

    @abc.abstractmethod
    def replication_enable(self, context, volume):
        """Enable replication on a replication capable volume.

        If the volume was created on a replication_enabled host this method
        is used to re-enable replication for the volume.

        Primarily we only want this for testing/admin purposes.  The idea
        being that the bulk of the replication details are handled by the
        type definition and the driver; however disable/enable(re-enable) is
        provided for admins to test or do maintenance which is a
        requirement by some cloud-providers.

        NOTE: This is intended as an ADMIN only call and is not
        intended to be used by end-user to enable replication.  We're
        leaving that to volume-type info, this is for things like
        maintenance or testing.


        :param context: security context
        :param volume: volume object returned by DB
        :response: {replication_driver_data: vendor-data} DB update

        The replication_driver_data response is vendor unique,
        data returned/used by the driver.  It is expected that
        the reponse from the driver is in the appropriate db update
        format, in the form of a dict, where the vendor data is
        stored under the key 'replication_driver_data'

        """

        # TODO(jdg): Put a check in at API layer to verify the host is
        # replication capable before even issuing this call (can just
        # check against the volume-type for said volume as well)

        raise NotImplementedError()

    @abc.abstractmethod
    def replication_disable(self, context, volume):
        """Disable replication on the specified volume.

        If the specified volume is currently replication enabled,
        this method can be used to disable the replciation process
        on the backend.

        Note that we still send this call to a driver whos volume
        may report replication-disabled already.  We do this as a
        safety mechanism to allow a driver to cleanup any mismatch
        in state between Cinder and itself.

        This is intended as an ADMIN only call to allow for
        maintenance and testing.  If a driver receives this call
        and the process fails for some reason the driver should
        return a status update to "replication_status=disable_failed"

        :param context: security context
        :param volume: volume object returned by DB
        :response: {replication_driver_data: vendor-data} DB update

        The replication_driver_data response is vendor unique,
        data returned/used by the driver.  It is expected that
        the reponse from the driver is in the appropriate db update
        format, in the form of a dict, where the vendor data is
        stored under the key 'replication_driver_data'

        """

        raise NotImplementedError()

    @abc.abstractmethod
    def replication_failover(self, context, volume, secondary):
        """Force failover to a secondary replication target.

        Forces the failover action of a replicated volume to one of its
        secondary/target devices.  By default the choice of target devices
        is left up to the driver.  In particular we expect one way
        replication here, but are providing a mechanism for 'n' way
        if supported/configured.

        Currently we leave it up to the driver to figure out how/what
        to do here.  Rather than doing things like ID swaps, we instead
        just let the driver figure out how/where to route things.

        In cases where we might want to drop a volume-service node and
        the replication target is a configured cinder backend, we'll
        just update the host column for the volume.

        Very important point here is that in the case of a succesful
        failover, we want to update the replication_status of the
        volume to "failed-over".  This way there's an indication that
        things worked as expected, and that it's evident that the volume
        may no longer be replicating to another backend (primary burst
        in to flames).  This status will be set by the manager.

        :param context: security context
        :param volume: volume object returned by DB
        :param secondary: Specifies rep target to fail over to
        :response: dict of udpates

        So the response would take the form:
            {host: <properly formatted host string for db update>,
             model_update: {standard_model_update_KVs},
             replication_driver_data: xxxxxxx}

        It is expected that the format of these responses are in a consumable
        format to be used in a db.update call directly.

        Additionally we utilize exception catching to report back to the
        manager when things went wrong and to inform the caller on how
        to proceed.

        """

        raise NotImplementedError()

    @abc.abstractmethod
    def list_replication_targets(self, context, vref):
        """Provide a means to obtain replication targets for a volume.

        This method is used to query a backend to get the current
        replication config info for the specified volume.

        In the case of a volume that isn't being replicated,
        the driver should return an empty list.


        Example response for replicating to a managed backend:
        {'volume_id': volume['id'],
         'targets':[{'type': 'managed',
                     'backend_name': 'backend_name'}...]

        Example response for replicating to an unmanaged backend:
        {'volume_id': volume['id'],
         'targets':[{'type': 'managed',
                     'vendor-key-1': 'value-1'}...]

        NOTE: It's the responsibility of the driver to mask out any
        passwords or sensitive information.  Also the format of the
        response allows mixed (managed/unmanaged) targets, even though
        the first iteration does not support configuring the driver in
        such a manner.

        """

        raise NotImplementedError()

    @abc.abstractmethod
    def get_replication_updates(self, context):
        """Provide a means to obtain status updates from backend.

        Provides a concise update for backends to report any errors
        or problems with replicating volumes.  The intent is we only
        return something here if there's an error or a problem, and to
        notify where the backend thinks the volume is.

        param: context: context of caller (probably don't need)
        returns: [{volid: n, status: ok|error,...}]
        """
        # NOTE(jdg): flush this out with implementations so we all
        # have something usable here
        raise NotImplementedError()


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
        """
        return

    # NOTE: Can't use abstractmethod before all drivers implement it
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        return

    # NOTE: Can't use abstractmethod before all drivers implement it
    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class ReplicaVD(object):
    @abc.abstractmethod
    def reenable_replication(self, context, volume):
        """Re-enable replication between the replica and primary volume.

        This is used to re-enable/fix the replication between primary
        and secondary. One use is as part of the fail-back process, when
        you re-synchorize your old primary with the promoted volume
        (the old replica).
        Returns model_update for the volume to reflect the actions of the
        driver.
        The driver is expected to update the following entries:
            'replication_status'
            'replication_extended_status'
            'replication_driver_data'
        Possible 'replication_status' values (in model_update) are:
        'error' - replication in error state
        'copying' - replication copying data to secondary (inconsistent)
        'active' - replication copying data to secondary (consistent)
        'active-stopped' - replication data copy on hold (consistent)
        'inactive' - replication data copy on hold (inconsistent)
        Values in 'replication_extended_status' and 'replication_driver_data'
        are managed by the driver.

        :param context: Context
        :param volume: A dictionary describing the volume
        """
        return

    def get_replication_status(self, context, volume):
        """Query the actual volume replication status from the driver.

        Returns model_update for the volume.
        The driver is expected to update the following entries:
            'replication_status'
            'replication_extended_status'
            'replication_driver_data'
        Possible 'replication_status' values (in model_update) are:
        'error' - replication in error state
        'copying' - replication copying data to secondary (inconsistent)
        'active' - replication copying data to secondary (consistent)
        'active-stopped' - replication data copy on hold (consistent)
        'inactive' - replication data copy on hold (inconsistent)
        Values in 'replication_extended_status' and 'replication_driver_data'
        are managed by the driver.

        :param context: Context
        :param volume: A dictionary describing the volume
        """
        return None

    @abc.abstractmethod
    def promote_replica(self, context, volume):
        """Promote the replica to be the primary volume.

        Following this command, replication between the volumes at
        the storage level should be stopped, the replica should be
        available to be attached, and the replication status should
        be in status 'inactive'.

        Returns model_update for the volume.
        The driver is expected to update the following entries:
            'replication_status'
            'replication_extended_status'
            'replication_driver_data'
        Possible 'replication_status' values (in model_update) are:
        'error' - replication in error state
        'inactive' - replication data copy on hold (inconsistent)
        Values in 'replication_extended_status' and 'replication_driver_data'
        are managed by the driver.

        :param context: Context
        :param volume: A dictionary describing the volume
        """
        return

    @abc.abstractmethod
    def create_replica_test_volume(self, volume, src_vref):
        """Creates a test replica clone of the specified replicated volume.

        Create a clone of the replicated (secondary) volume.
        """
        return


class VolumeDriver(ConsistencyGroupVD, TransferVD, ManageableVD, ExtendVD,
                   CloneableImageVD, ManageableSnapshotsVD,
                   SnapshotVD, ReplicaVD, LocalVD, MigrateVD, BaseVD):
    """This class will be deprecated soon.

    Please use the abstract classes above for new drivers.
    """
    def check_for_setup_error(self):
        raise NotImplementedError()

    def create_volume(self, volume):
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        raise NotImplementedError()

    def create_replica_test_volume(self, volume, src_vref):
        raise NotImplementedError()

    def delete_volume(self, volume):
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
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

    def manage_existing_get_size(self, volume, existing_ref):
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def unmanage(self, volume):
        pass

    def manage_existing_snapshot(self, snapshot, existing_ref):
        msg = _("Manage existing snapshot not implemented.")
        raise NotImplementedError(msg)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        msg = _("Manage existing snapshot not implemented.")
        raise NotImplementedError(msg)

    def unmanage_snapshot(self, snapshot):
        """Unmanage the specified snapshot from Cinder management."""

    def retype(self, context, volume, new_type, diff, host):
        return False, None

    def reenable_replication(self, context, volume):
        msg = _("sync_replica not implemented.")
        raise NotImplementedError(msg)

    def promote_replica(self, context, volume):
        msg = _("promote_replica not implemented.")
        raise NotImplementedError(msg)

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
        """Disallow connection from connector"""

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Disallow connection from connector for a snapshot."""

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
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
        :return model_update, volumes_model_update

        The source can be cgsnapshot or a source cg.

        param volumes is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Volume to be precise. It cannot be
        assigned to volumes_model_update. volumes_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: ['id': xxx, 'status': xxx, ......]. model_update
        will be in this format: ['status': xxx, ......].

        To be consistent with other volume operations, the manager will
        assume the operation is successful if no exception is thrown by
        the driver. For a successful operation, the driver can either build
        the model_update and volumes_model_update and return them or
        return None, None.
        """
        raise NotImplementedError()

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        raise NotImplementedError()

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :return model_update, add_volumes_update, remove_volumes_update

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

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        raise NotImplementedError()

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        raise NotImplementedError()

    def clone_image(self, volume, image_location, image_id, image_meta,
                    image_service):
        return None, False

    def get_pool(self, volume):
        """Return pool name where volume reside on.

        :param volume: The volume hosted by the the driver.
        :return: name of the pool where given volume is in.
        """
        return None

    def migrate_volume(self, context, volume, host):
        return (False, None)


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
        LOG.warning(_LW("ISCSI provider_location not "
                        "stored, using discovery"))

        volume_name = volume['name']

        try:
            # NOTE(griff) We're doing the split straight away which should be
            # safe since using '@' in hostname is considered invalid

            (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                        '-t', 'sendtargets', '-p',
                                        volume['host'].split('@')[0],
                                        run_as_root=True)
        except processutils.ProcessExecutionError as ex:
            LOG.error(_LE("ISCSI discovery attempt failed for:%s"),
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

        :access_mode:    the volume access mode allow client used
                         ('rw' or 'ro' currently supported)

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
            if (self.configuration.volume_driver in
                    ['cinder.volume.drivers.lvm.LVMISCSIDriver',
                     'cinder.volume.drivers.lvm.LVMISERDriver',
                     'cinder.volume.drivers.lvm.ThinLVMVolumeDriver'] and
                    self.configuration.iscsi_helper in ('tgtadm', 'iseradm')):
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
                    'access_mode': 'rw',
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
                    'access_mode': 'rw',
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
            LOG.error(_LE('The volume driver requires %(data)s '
                          'in the connector.'), {'data': required})
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


class FakeISCSIDriver(ISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISCSIDriver, self).__init__(execute=self.fake_execute,
                                              *args, **kwargs)

    def _update_pools_and_stats(self, data):
        fake_pool = {}
        fake_pool.update(dict(
            pool_name=data["volume_backend_name"],
            total_capacity_gb=0,
            free_capacity_gb=0,
            provisioned_capacity_gb=0,
            reserved_percentage=100,
            QoS_support=False,
            filter_function=self.get_filter_function(),
            goodness_function=self.get_goodness_function()
        ))
        data["pools"].append(fake_pool)
        self._stats = data

    def create_volume(self, volume):
        pass

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iscsi',
            'data': {'access_mode': 'rw'},
            'discard': False,
        }

    def initialize_connection_snapshot(self, snapshot, connector):
        return {
            'driver_volume_type': 'iscsi',
            'data': {'access_mode': 'rw'}
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        pass

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        LOG.debug("FAKE ISCSI: %s", cmd)
        return (None, None)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        pass

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        pass

    def delete_volume(self, volume):
        """Deletes a volume."""
        pass

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        pass

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        pass

    def local_path(self, volume):
        return '/tmp/volume-%s' % volume.id

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume.

        Can optionally return a Dictionary of changes to the volume object to
        be persisted.
        """
        pass

    def create_export_snapshot(self, context, snapshot, connector):
        """Exports the snapshot.

        Can optionally return a Dictionary of changes to the snapshot object to
        be persisted.
        """
        pass

    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        pass

    def remove_export_snapshot(self, context, snapshot):
        """Removes an export for a snapshot."""
        pass


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
        Example return value::

            {
                'driver_volume_type': 'iser'
                'data': {
                    'target_discovered': True,
                    'target_iqn':
                    'iqn.2010-10.org.iser.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
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


class FakeISERDriver(FakeISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISERDriver, self).__init__(execute=self.fake_execute,
                                             *args, **kwargs)

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iser',
            'data': {}
        }

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        LOG.debug("FAKE ISER: %s", cmd)
        return (None, None)


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

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                    'access_mode': 'rw',
                    'discard': False,
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                    'access_mode': 'rw',
                    'discard': False,
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
            LOG.error(_LE(
                "FibreChannelDriver validate_connector failed. "
                "No '%(setting)s'. Make sure HBA state is Online."),
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
