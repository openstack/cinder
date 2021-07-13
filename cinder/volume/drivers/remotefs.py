# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2014 Red Hat, Inc.
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

import binascii
import collections
import errno
import inspect
import json
import math
import os
import re
import shutil
import string
import tempfile
import time

from castellan import key_manager
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils.secretutils import md5
from oslo_utils import units
import six

from cinder import compute
from cinder import coordination
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


nas_opts = [
    cfg.StrOpt('nas_host',
               default='',
               help='IP address or Hostname of NAS system.'),
    cfg.StrOpt('nas_login',
               default='admin',
               help='User name to connect to NAS system.'),
    cfg.StrOpt('nas_password',
               default='',
               help='Password to connect to NAS system.',
               secret=True),
    cfg.PortOpt('nas_ssh_port',
                default=22,
                help='SSH port to use to connect to NAS system.'),
    cfg.StrOpt('nas_private_key',
               default='',
               help='Filename of private key to use for SSH authentication.'),
    cfg.StrOpt('nas_secure_file_operations',
               default='auto',
               help=('Allow network-attached storage systems to operate in a '
                     'secure environment where root level access is not '
                     'permitted. If set to False, access is as the root user '
                     'and insecure. If set to True, access is not as root. '
                     'If set to auto, a check is done to determine if this is '
                     'a new installation: True is used if so, otherwise '
                     'False. Default is auto.')),
    cfg.StrOpt('nas_secure_file_permissions',
               default='auto',
               help=('Set more secure file permissions on network-attached '
                     'storage volume files to restrict broad other/world '
                     'access. If set to False, volumes are created with open '
                     'permissions. If set to True, volumes are created with '
                     'permissions for the cinder user and group (660). If '
                     'set to auto, a check is done to determine if '
                     'this is a new installation: True is used if so, '
                     'otherwise False. Default is auto.')),
    cfg.StrOpt('nas_share_path',
               default='',
               help=('Path to the share to use for storing Cinder volumes. '
                     'For example:  "/srv/export1" for an NFS server export '
                     'available at 10.0.5.10:/srv/export1 .')),
    cfg.StrOpt('nas_mount_options',
               help=('Options used to mount the storage backend file system '
                     'where Cinder volumes are stored.')),
]

volume_opts = [
    cfg.StrOpt('nas_volume_prov_type',
               default='thin',
               choices=['thin', 'thick'],
               help=('Provisioning type that will be used when '
                     'creating volumes.')),
]

CONF = cfg.CONF
CONF.register_opts(nas_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)


def locked_volume_id_operation(f):
    """Lock decorator for volume operations.

       Takes a named lock prior to executing the operation. The lock is named
       with the id of the volume. This lock can be used by driver methods
       to prevent conflicts with other operations modifying the same volume.

       May be applied to methods that take a 'volume' or 'snapshot' argument.
    """

    def lvo_inner1(inst, *args, **kwargs):
        lock_tag = inst.driver_prefix
        call_args = inspect.getcallargs(f, inst, *args, **kwargs)

        if call_args.get('volume'):
            volume_id = call_args['volume'].id
        elif call_args.get('snapshot'):
            volume_id = call_args['snapshot'].volume.id
        else:
            err_msg = _('The decorated method must accept either a volume or '
                        'a snapshot object')
            raise exception.VolumeBackendAPIException(data=err_msg)

        @utils.synchronized('%s-%s' % (lock_tag, volume_id),
                            external=False)
        def lvo_inner2():
            return f(inst, *args, **kwargs)
        return lvo_inner2()
    return lvo_inner1


class BackingFileTemplate(string.Template):
    """Custom Template for substitutions in backing files regex strings

        Changes the default delimiter from '$' to '#' in order to prevent
        clashing with the regex end of line marker '$'.
    """
    delimiter = '#'
    idpattern = r'[a-z][_a-z0-9]*'


class RemoteFSDriver(driver.BaseVD):
    """Common base for drivers that work like NFS."""

    driver_volume_type = None
    driver_prefix = 'remotefs'
    volume_backend_name = None
    vendor_name = 'Open Source'
    SHARE_FORMAT_REGEX = r'.+:/.+'

    # We let the drivers inheriting this specify
    # whether thin provisioning is supported or not.
    _thin_provisioning_support = False
    _thick_provisioning_support = False

    def __init__(self, *args, **kwargs):
        super(RemoteFSDriver, self).__init__(*args, **kwargs)
        self.shares = {}
        self._mounted_shares = []
        self._execute_as_root = True
        self._is_voldb_empty_at_startup = kwargs.pop('is_vol_db_empty', None)
        self._supports_encryption = False
        self.format = 'raw'

        if self.configuration:
            self.configuration.append_config_values(nas_opts)
            self.configuration.append_config_values(volume_opts)

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        data = {'export': volume.provider_location,
                'name': volume.name}
        if volume.provider_location in self.shares:
            data['options'] = self.shares[volume.provider_location]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(RemoteFSDriver, self).do_setup(context)

        # Validate the settings for our secure file options.
        self.configuration.nas_secure_file_permissions = \
            self.configuration.nas_secure_file_permissions.lower()
        self.configuration.nas_secure_file_operations = \
            self.configuration.nas_secure_file_operations.lower()
        valid_secure_opts = ['auto', 'true', 'false']
        secure_options = {'nas_secure_file_permissions':
                          self.configuration.nas_secure_file_permissions,
                          'nas_secure_file_operations':
                          self.configuration.nas_secure_file_operations}

        LOG.debug('NAS config: %s', secure_options)
        for opt_name, opt_value in secure_options.items():
            if opt_value not in valid_secure_opts:
                err_parms = {'name': opt_name, 'value': opt_value}
                msg = _("NAS config '%(name)s=%(value)s' invalid. Must be "
                        "'auto', 'true', or 'false'") % err_parms
                LOG.error(msg)
                raise exception.InvalidConfigurationValue(msg)

    def _get_provisioned_capacity(self):
        """Returns the provisioned capacity.

        Get the sum of sizes of volumes, snapshots and any other
        files on the mountpoint.
        """
        provisioned_size = 0.0
        for share in self.shares.keys():
            mount_path = self._get_mount_point_for_share(share)
            out, _ = self._execute('du', '--bytes', '-s', mount_path,
                                   run_as_root=self._execute_as_root)
            provisioned_size += int(out.split()[0])
        return round(provisioned_size / units.Gi, 2)

    def _get_mount_point_base(self):
        """Returns the mount point base for the remote fs.

           This method facilitates returning mount point base
           for the specific remote fs. Override this method
           in the respective driver to return the entry to be
           used while attach/detach using brick in cinder.
           If not overridden then it returns None without
           raising exception to continue working for cases
           when not used with brick.
        """
        LOG.debug("Driver specific implementation needs to return"
                  " mount_point_base.")
        return None

    @staticmethod
    def _validate_state(current_state,
                        acceptable_states,
                        obj_description='volume',
                        invalid_exc=exception.InvalidVolume):
        if current_state not in acceptable_states:
            message = _('Invalid %(obj_description)s state. '
                        'Acceptable states for this operation: '
                        '%(acceptable_states)s. '
                        'Current %(obj_description)s state: '
                        '%(current_state)s.')
            raise invalid_exc(
                message=message %
                dict(obj_description=obj_description,
                     acceptable_states=acceptable_states,
                     current_state=current_state))

    @volume_utils.trace
    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        :returns: provider_location update dict for database
        """

        if volume.encryption_key_id and not self._supports_encryption:
            message = _("Encryption is not yet supported.")
            raise exception.VolumeDriverException(message=message)

        LOG.debug('Creating volume %(vol)s', {'vol': volume.id})
        self._ensure_shares_mounted()

        volume.provider_location = self._find_share(volume)

        LOG.info('casted to %s', volume.provider_location)

        self._do_create_volume(volume)

        return {'provider_location': volume.provider_location}

    def _do_create_volume(self, volume):
        """Create a volume on given remote share.

        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume.size

        encrypted = volume.encryption_key_id is not None

        if encrypted:
            encryption = volume_utils.check_encryption_provider(
                volume,
                volume.obj_context)

            self._create_encrypted_volume_file(volume_path,
                                               volume_size,
                                               encryption,
                                               volume.obj_context)
        elif getattr(self.configuration,
                     self.driver_prefix + '_qcow2_volumes', False):
            # QCOW2 volumes are inherently sparse, so this setting
            # will override the _sparsed_volumes setting.
            self._create_qcow2_file(volume_path, volume_size)
            self.format = 'qcow2'
        elif getattr(self.configuration,
                     self.driver_prefix + '_sparsed_volumes', False):
            self._create_sparsed_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions(volume_path)
        if not volume.consistencygroup_id and not volume.group_id:
            volume.admin_metadata['format'] = self.format
            # This is done here because when creating a volume from image,
            # while encountering other volume.save() method fails for
            # non-admins
            with volume.obj_as_admin():
                volume.save()

    def _ensure_shares_mounted(self):
        """Look for remote shares in the flags and mount them locally."""
        mounted_shares = []

        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))

        for share in self.shares:
            try:
                self._ensure_share_mounted(share)
                mounted_shares.append(share)
            except Exception as exc:
                LOG.error('Exception during mounting %s', exc)

        self._mounted_shares = mounted_shares

        LOG.debug('Available shares %s', self._mounted_shares)

    @volume_utils.trace
    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """

        LOG.debug('Deleting volume %(vol)s, provider_location: %(loc)s',
                  {'vol': volume.id, 'loc': volume.provider_location})
        if not volume.provider_location:
            LOG.warning('Volume %s does not have '
                        'provider_location specified, '
                        'skipping', volume.name)
            return

        self._ensure_share_mounted(volume.provider_location)

        mounted_path = self.local_path(volume)

        self._delete(mounted_path)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""
        self._ensure_share_mounted(volume.provider_location)

    def create_export(self, ctx, volume, connector):
        """Exports the volume.

        Can optionally return a dictionary of changes
        to the volume object to be persisted.
        """
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    def delete_snapshot(self, snapshot):
        """Delete snapshot.

        Do nothing for this driver, but allow manager to handle deletion
        of snapshot in error state.
        """
        pass

    def _delete(self, path):
        # Note(lpetrut): this method is needed in order to provide
        # interoperability with Windows as it will be overridden.
        self._execute('rm', '-f', path, run_as_root=self._execute_as_root)

    def _create_sparsed_file(self, path, size):
        """Creates a sparse file of a given size in GiB."""
        self._execute('truncate', '-s', '%sG' % size,
                      path, run_as_root=self._execute_as_root)

    def _create_regular_file(self, path, size):
        """Creates a regular file of given size in GiB."""

        block_size_mb = 1
        block_count = size * units.Gi // (block_size_mb * units.Mi)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=self._execute_as_root)

    def _create_qcow2_file(self, path, size_gb):
        """Creates a QCOW2 file of a given size in GiB."""

        self._execute('qemu-img', 'create', '-f', 'qcow2',
                      '-o', 'preallocation=metadata',
                      path, str(size_gb * units.Gi),
                      run_as_root=self._execute_as_root)

    def _create_encrypted_volume_file(self,
                                      path,
                                      size_gb,
                                      encryption,
                                      context):
        """Create an encrypted volume.

        This works by creating an encrypted image locally,
        and then uploading it to the volume.
        """

        cipher_spec = image_utils.decode_cipher(encryption['cipher'],
                                                encryption['key_size'])

        # TODO(enriquetaso): share this code w/ the RBD driver
        # Fetch the key associated with the volume and decode the passphrase
        keymgr = key_manager.API(CONF)
        key = keymgr.get(context, encryption['encryption_key_id'])
        passphrase = binascii.hexlify(key.get_encoded()).decode('utf-8')

        # create a file
        tmp_dir = volume_utils.image_conversion_dir()

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_key:
            # TODO(enriquetaso): encrypt w/ aes256 cipher text
            # (qemu-img feature) ?
            with open(tmp_key.name, 'w') as f:
                f.write(passphrase)

            self._execute(
                'qemu-img', 'create', '-f', 'qcow2',
                '-o',
                'encrypt.format=luks,'
                'encrypt.key-secret=sec1,'
                'encrypt.cipher-alg=%(cipher_alg)s,'
                'encrypt.cipher-mode=%(cipher_mode)s,'
                'encrypt.ivgen-alg=%(ivgen_alg)s' % cipher_spec,
                '--object', 'secret,id=sec1,format=raw,file=' + tmp_key.name,
                path, str(size_gb * units.Gi),
                run_as_root=self._execute_as_root)

    def _set_rw_permissions(self, path):
        """Sets access permissions for given NFS path.

        Volume file permissions are set based upon the value of
        secure_file_permissions: 'true' sets secure access permissions and
        'false' sets more open (insecure) access permissions.

        :param path: the volume file path.
        """
        if self.configuration.nas_secure_file_permissions == 'true':
            permissions = '660'
            LOG.debug('File path %(path)s is being set with permissions: '
                      '%(permissions)s',
                      {'path': path, 'permissions': permissions})
        else:
            permissions = 'ugo+rw'
            LOG.warning('%(path)s is being set with open permissions: '
                        '%(perm)s', {'path': path, 'perm': permissions})

        self._execute('chmod', permissions, path,
                      run_as_root=self._execute_as_root)

    def _set_rw_permissions_for_all(self, path):
        """Sets 666 permissions for the path."""
        self._execute('chmod', 'ugo+rw', path,
                      run_as_root=self._execute_as_root)

    def _set_rw_permissions_for_owner(self, path):
        """Sets read-write permissions to the owner for the path."""
        self._execute('chmod', 'u+rw', path,
                      run_as_root=self._execute_as_root)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        remotefs_share = volume.provider_location
        return os.path.join(self._get_mount_point_for_share(remotefs_share),
                            volume.name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""

        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume.size,
                                 run_as_root=self._execute_as_root)

        # NOTE (leseb): Set the virtual size of the image
        # the raw conversion overwrote the destination file
        # (which had the correct size)
        # with the fetched glance image size,
        # thus the initial 'size' parameter is not honored
        # this sets the size to the one asked in the first place by the user
        # and then verify the final virtual size
        image_utils.resize_image(self.local_path(volume), volume.size,
                                 run_as_root=self._execute_as_root)

        data = image_utils.qemu_img_info(self.local_path(volume),
                                         run_as_root=self._execute_as_root)
        virt_size = data.virtual_size // units.Gi
        if virt_size != volume.size:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=(_("Expected volume size was %d") % volume.size)
                + (_(" but size is now %d") % virt_size))

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        volume_utils.upload_volume(context,
                                   image_service,
                                   image_meta,
                                   self.local_path(volume),
                                   volume,
                                   run_as_root=self._execute_as_root)

    def _read_config_file(self, config_file):
        # Returns list of lines in file
        with open(config_file) as f:
            return f.readlines()

    def _load_shares_config(self, share_file=None):
        self.shares = {}

        if all((self.configuration.nas_host,
                self.configuration.nas_share_path)):
            LOG.debug('Using nas_host and nas_share_path configuration.')

            nas_host = self.configuration.nas_host
            nas_share_path = self.configuration.nas_share_path

            share_address = '%s:%s' % (nas_host, nas_share_path)

            if not re.match(self.SHARE_FORMAT_REGEX, share_address):
                msg = (_("Share %s ignored due to invalid format. Must "
                         "be of form address:/export. Please check the "
                         "nas_host and nas_share_path settings."),
                       share_address)
                raise exception.InvalidConfigurationValue(msg)

            self.shares[share_address] = self.configuration.nas_mount_options

        elif share_file is not None:
            LOG.debug('Loading shares from %s.', share_file)

            for share in self._read_config_file(share_file):
                # A configuration line may be either:
                #  host:/vol_name
                # or
                #  host:/vol_name -o options=123,rw --other
                if not share.strip():
                    # Skip blank or whitespace-only lines
                    continue
                if share.startswith('#'):
                    continue

                share_info = share.split(' ', 1)
                # results in share_info =
                #  [ 'address:/vol', '-o options=123,rw --other' ]

                share_address = share_info[0].strip()
                # Replace \040 with a space, to support paths with spaces
                share_address = share_address.replace("\\040", " ")
                share_opts = None
                if len(share_info) > 1:
                    share_opts = share_info[1].strip()

                if not re.match(self.SHARE_FORMAT_REGEX, share_address):
                    LOG.error("Share %s ignored due to invalid format. "
                              "Must be of form address:/export.",
                              share_address)
                    continue

                self.shares[share_address] = share_opts

        LOG.debug("shares loaded: %s", self.shares)

    def _get_mount_point_for_share(self, path):
        raise NotImplementedError()

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.volume_backend_name
        data['vendor_name'] = 'Open Source'
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = self.driver_volume_type

        self._ensure_shares_mounted()

        global_capacity = 0
        global_free = 0
        for share in self._mounted_shares:
            capacity, free, used = self._get_capacity_info(share)
            global_capacity += capacity
            global_free += free

        data['total_capacity_gb'] = global_capacity / float(units.Gi)
        data['free_capacity_gb'] = global_free / float(units.Gi)
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = False
        self._stats = data

    def _get_capacity_info(self, share):
        raise NotImplementedError()

    def _find_share(self, volume):
        raise NotImplementedError()

    def _ensure_share_mounted(self, share):
        raise NotImplementedError()

    def secure_file_operations_enabled(self):
        """Determine if driver is operating in Secure File Operations mode.

        The Cinder Volume driver needs to query if this driver is operating
        in a secure file mode; check our nas_secure_file_operations flag.
        """
        if self.configuration.nas_secure_file_operations == 'true':
            return True
        return False

    def set_nas_security_options(self, is_new_cinder_install):
        """Determine the setting to use for Secure NAS options.

        This method must be overridden by child wishing to use secure
        NAS file operations. This base method will set the NAS security
        options to false.
        """
        doc_html = ("https://docs.openstack.org/cinder/latest/admin"
                    "/blockstorage-nfs-backend.html")
        self.configuration.nas_secure_file_operations = 'false'
        LOG.warning("The NAS file operations will be run as root: "
                    "allowing root level access at the storage backend. "
                    "This is considered an insecure NAS environment. "
                    "Please see %s for information on a secure NAS "
                    "configuration.",
                    doc_html)
        self.configuration.nas_secure_file_permissions = 'false'
        LOG.warning("The NAS file permissions mode will be 666 (allowing "
                    "other/world read & write access). This is considered "
                    "an insecure NAS environment. Please see %s for "
                    "information on a secure NFS configuration.",
                    doc_html)

    def _determine_nas_security_option_setting(self, nas_option, mount_point,
                                               is_new_cinder_install):
        """Determine NAS security option setting when 'auto' is assigned.

        This method determines the final 'true'/'false' setting of an NAS
        security option when the default value of 'auto' has been detected.
        If the nas option isn't 'auto' then its current value is used.

        :param nas_option: The NAS security option value loaded from config.
        :param mount_point: Mount where indicator file is written.
        :param is_new_cinder_install: boolean for new Cinder installation.
        :return string: 'true' or 'false' for new option setting.
        """
        if nas_option == 'auto':
            # For auto detection, we first check to see if we have been
            # through this process before by checking for the existence of
            # the Cinder secure environment indicator file.
            file_name = '.cinderSecureEnvIndicator'
            file_path = os.path.join(mount_point, file_name)
            if os.path.isfile(file_path):
                nas_option = 'true'
                LOG.info('Cinder secure environment '
                         'indicator file exists.')
            else:
                # The indicator file does not exist. If it is a new
                # installation, set to 'true' and create the indicator file.
                if is_new_cinder_install:
                    nas_option = 'true'
                    try:
                        with open(file_path, 'w') as fh:
                            fh.write('Detector file for Cinder secure '
                                     'environment usage.\n')
                            fh.write('Do not delete this file.\n')

                        # Set the permissions on our special marker file to
                        # protect from accidental removal (owner write only).
                        self._execute('chmod', '640', file_path,
                                      run_as_root=self._execute_as_root)
                        LOG.info('New Cinder secure environment indicator'
                                 ' file created at path %s.', file_path)
                    except IOError as err:
                        LOG.error('Failed to created Cinder secure '
                                  'environment indicator file: %s',
                                  err)
                        if err.errno == errno.EACCES:
                            LOG.warning('Reverting to non-secure mode. Adjust '
                                        'permissions at %s to allow the '
                                        'cinder volume service write access '
                                        'to use secure mode.',
                                        mount_point)
                            nas_option = 'false'
                else:
                    # For existing installs, we default to 'false'. The
                    # admin can always set the option at the driver config.
                    nas_option = 'false'

        return nas_option


class RemoteFSSnapDriverBase(RemoteFSDriver):
    """Base class for remotefs drivers implementing qcow2 snapshots.

       Driver must implement:
         _local_volume_dir(self, volume)
    """

    _VALID_IMAGE_EXTENSIONS = []
    # The following flag may be overridden by the concrete drivers in order
    # to avoid using temporary volume snapshots when creating volume clones,
    # when possible.

    _always_use_temp_snap_when_cloning = True

    def __init__(self, *args, **kwargs):
        self._remotefsclient = None
        self.base = None
        self._nova = None
        super(RemoteFSSnapDriverBase, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        super(RemoteFSSnapDriverBase, self).do_setup(context)

        self._nova = compute.API()

    def snapshot_revert_use_temp_snapshot(self):
        # Considering that RemoteFS based drivers use COW images
        # for storing snapshots, having chains of such images,
        # creating a backup snapshot when reverting one is not
        # actutally helpful.
        return False

    def _local_volume_dir(self, volume):
        share = volume.provider_location
        local_dir = self._get_mount_point_for_share(share)
        return local_dir

    def _local_path_volume(self, volume):
        path_to_disk = os.path.join(
            self._local_volume_dir(volume),
            volume.name)

        return path_to_disk

    def _get_new_snap_path(self, snapshot):
        vol_path = self.local_path(snapshot.volume)
        snap_path = '%s.%s' % (vol_path, snapshot.id)
        return snap_path

    def _local_path_volume_info(self, volume):
        return '%s%s' % (self.local_path(volume), '.info')

    def _read_file(self, filename):
        """This method is to make it easier to stub out code for testing.

        Returns a string representing the contents of the file.
        """

        with open(filename, 'r') as f:
            return f.read()

    def _write_info_file(self, info_path, snap_info):
        if 'active' not in snap_info.keys():
            msg = _("'active' must be present when writing snap_info.")
            raise exception.RemoteFSException(msg)

        if not (os.path.exists(info_path) or os.name == 'nt'):
            # We're not managing file permissions on Windows.
            # Plus, 'truncate' is not available.
            self._execute('truncate', "-s0", info_path,
                          run_as_root=self._execute_as_root)
            self._set_rw_permissions(info_path)

        with open(info_path, 'w') as f:
            json.dump(snap_info, f, indent=1, sort_keys=True)

    def _qemu_img_info_base(self, path, volume_name, basedir,
                            ext_bf_template=None,
                            force_share=False,
                            run_as_root=False):
        """Sanitize image_utils' qemu_img_info.

        This code expects to deal only with relative filenames.

        :param path: Path to the image file whose info is fetched
        :param volume_name: Name of the volume
        :param basedir: Path to backing files directory
        :param ext_bf_template: Alt. string.Template for allowed backing files
        :type object: BackingFileTemplate
        :param force_share: Wether to force fetching img info for images in use
        :param run_as_root: Wether to run with privileged permissions or not
        """

        run_as_root = run_as_root or self._execute_as_root

        info = image_utils.qemu_img_info(path,
                                         force_share=force_share,
                                         run_as_root=run_as_root)
        if info.image:
            info.image = os.path.basename(info.image)
        if info.backing_file:
            if self._VALID_IMAGE_EXTENSIONS:
                valid_ext = r'(\.(%s))?' % '|'.join(
                    self._VALID_IMAGE_EXTENSIONS)
            else:
                valid_ext = ''

            if ext_bf_template:
                backing_file_template = ext_bf_template.substitute(
                    basedir=basedir, volname=volume_name, valid_ext=valid_ext
                )
                LOG.debug("Fetching qemu-img info with special "
                          "backing_file_template: %(bft)s", {
                              "bft": backing_file_template
                          })
            else:
                backing_file_template = \
                    "(%(basedir)s/[0-9a-f]+/)?%" \
                    "(volname)s(.(tmp-snap-)?[0-9a-f-]+)?%(valid_ext)s$" % {
                        'basedir': basedir,
                        'volname': volume_name,
                        'valid_ext': valid_ext,
                    }
            if not re.match(backing_file_template, info.backing_file,
                            re.IGNORECASE):
                raise exception.RemoteFSInvalidBackingFile(
                    path=path, backing_file=info.backing_file)

            info.backing_file = os.path.basename(info.backing_file)

        return info

    def _qemu_img_info(self, path, volume_name):
        raise NotImplementedError()

    def _img_commit(self, path, passphrase_file=None, backing_file=None):
        # TODO(eharney): this is not using the correct permissions for
        # NFS snapshots
        #  It needs to run as root for volumes attached to instances, but
        #  does not when in secure mode.
        cmd = ['qemu-img', 'commit']
        if passphrase_file:
            obj = ['--object',
                   'secret,id=s0,format=raw,file=%s' % passphrase_file]
            image_opts = ['--image-opts']

            src_opts = \
                "file.filename=%(filename)s,encrypt.format=luks," \
                "encrypt.key-secret=s0,backing.file.filename=%(backing)s," \
                "backing.encrypt.key-secret=s0" % {
                    'filename': path,
                    'backing': backing_file,
                }

            path_no_to_delete = ['-d', src_opts]
            cmd += obj + image_opts + path_no_to_delete
        else:
            cmd += ['-d', path]

        self._execute(*cmd, run_as_root=self._execute_as_root)
        self._delete(path)

    def _rebase_img(self, image, backing_file, volume_format,
                    passphrase_file=None):
        # qemu-img create must run as root, because it reads from the
        # backing file, which will be owned by qemu:qemu if attached to an
        # instance.
        # TODO(erlon): Sanity check this.
        command = ['qemu-img', 'rebase', '-u']
        # if encrypted
        if passphrase_file:
            objectdef = "secret,id=s0,file=%s" % passphrase_file
            filename = "encrypt.key-secret=s0,"\
                "file.filename=%(filename)s" % {'filename': image}

            command += ['--object', objectdef, '-b', backing_file,
                        '-F', volume_format, '--image-opts', filename]
        # not encrypted
        else:
            command += ['-b', backing_file, image, '-F', volume_format]

        self._execute(*command, run_as_root=self._execute_as_root)

    def _read_info_file(self, info_path, empty_if_missing=False):
        """Return dict of snapshot information.

           :param info_path: path to file
           :param empty_if_missing: True=return empty dict if no file
        """

        if not os.path.exists(info_path):
            if empty_if_missing is True:
                return {}

        return json.loads(self._read_file(info_path))

    def _get_higher_image_path(self, snapshot):
        volume = snapshot.volume
        info_path = self._local_path_volume_info(volume)
        snap_info = self._read_info_file(info_path)

        snapshot_file = snap_info[snapshot.id]
        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        backing_chain = self._get_backing_chain_for_path(
            volume, active_file_path)
        higher_file = next((os.path.basename(f['filename'])
                            for f in backing_chain
                            if utils.paths_normcase_equal(
                                f.get('backing-filename', ''),
                                snapshot_file)),
                           None)
        return higher_file

    def _get_backing_chain_for_path(self, volume, path):
        """Returns list of dicts containing backing-chain information.

        Includes 'filename', and 'backing-filename' for each
        applicable entry.

        Consider converting this to use --backing-chain and --output=json
        when environment supports qemu-img 1.5.0.

        :param volume: volume reference
        :param path: path to image file at top of chain

        """

        output = []

        info = self._qemu_img_info(path, volume.name)
        new_info = {}
        new_info['filename'] = os.path.basename(path)
        new_info['backing-filename'] = info.backing_file

        output.append(new_info)

        while new_info['backing-filename']:
            filename = new_info['backing-filename']
            path = os.path.join(self._local_volume_dir(volume), filename)
            info = self._qemu_img_info(path, volume.name)
            backing_filename = info.backing_file
            new_info = {}
            new_info['filename'] = filename
            new_info['backing-filename'] = backing_filename

            output.append(new_info)

        return output

    def _get_hash_str(self, base_str):
        """Return a string that represents hash of base_str.

        Returns string in a hex format.
        """
        if isinstance(base_str, six.text_type):
            base_str = base_str.encode('utf-8')
        return md5(base_str, usedforsecurity=False).hexdigest()

    def _get_mount_point_for_share(self, share):
        """Return mount point for share.

        :param share: example 172.18.194.100:/var/fs
        """
        return self._remotefsclient.get_mount_point(share)

    def _get_available_capacity(self, share):
        """Calculate available space on the share.

        :param share: example 172.18.194.100:/var/fs
        """
        mount_point = self._get_mount_point_for_share(share)

        out, _ = self._execute('df', '--portability', '--block-size', '1',
                               mount_point,
                               run_as_root=self._execute_as_root)
        out = out.splitlines()[1]

        size = int(out.split()[1])
        available = int(out.split()[3])

        return available, size

    def _get_capacity_info(self, remotefs_share):
        available, size = self._get_available_capacity(remotefs_share)
        return size, available, size - available

    def _get_mount_point_base(self):
        return self.base

    def _copy_volume_to_image(self, context, volume, image_service,
                              image_meta, store_id=None):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        info = self._qemu_img_info(active_file_path, volume.name)
        backing_file = info.backing_file

        root_file_fmt = info.file_format

        tmp_params = {
            'prefix': '%s.temp_image.%s' % (volume.id, image_meta['id']),
            'suffix': '.img'
        }
        with image_utils.temporary_file(**tmp_params) as temp_path:
            if backing_file or (root_file_fmt != 'raw'):
                # Convert due to snapshots
                # or volume data not being stored in raw format
                #  (upload_volume assumes raw format input)
                image_utils.convert_image(active_file_path, temp_path, 'raw',
                                          run_as_root=self._execute_as_root)
                upload_path = temp_path
            else:
                upload_path = active_file_path

            volume_utils.upload_volume(context,
                                       image_service,
                                       image_meta,
                                       upload_path,
                                       volume,
                                       run_as_root=self._execute_as_root)

    def get_active_image_from_info(self, volume):
        """Returns filename of the active image from the info file."""

        info_file = self._local_path_volume_info(volume)

        snap_info = self._read_info_file(info_file, empty_if_missing=True)

        if not snap_info:
            # No info file = no snapshots exist
            vol_path = os.path.basename(self.local_path(volume))
            return vol_path

        return snap_info['active']

    def _local_path_active_image(self, volume):
        active_fname = self.get_active_image_from_info(volume)
        vol_dir = self._local_volume_dir(volume)

        active_fpath = os.path.join(vol_dir, active_fname)
        return active_fpath

    def _get_snapshot_backing_file(self, snapshot):
        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)
        vol_dir = self._local_volume_dir(snapshot.volume)

        forward_file = snap_info[snapshot.id]
        forward_path = os.path.join(vol_dir, forward_file)

        # Find the file which backs this file, which represents the point
        # in which this snapshot was created.
        img_info = self._qemu_img_info(forward_path)
        return img_info.backing_file

    def _snapshots_exist(self, volume):
        if not volume.provider_location:
            return False

        active_fpath = self._local_path_active_image(volume)
        base_vol_path = self.local_path(volume)

        return not utils.paths_normcase_equal(active_fpath, base_vol_path)

    def _is_volume_attached(self, volume):
        return volume.attach_status == fields.VolumeAttachStatus.ATTACHED

    def _create_cloned_volume(self, volume, src_vref, context):
        LOG.info('Cloning volume %(src)s to volume %(dst)s',
                 {'src': src_vref.id,
                  'dst': volume.id})

        acceptable_states = ['available', 'backing-up', 'downloading']
        self._validate_state(src_vref.status,
                             acceptable_states,
                             obj_description='source volume')

        volume_name = CONF.volume_name_template % volume.id

        # Create fake volume and snapshot objects
        vol_attrs = ['provider_location', 'size', 'id', 'name', 'status',
                     'volume_type', 'metadata', 'obj_context']
        Volume = collections.namedtuple('Volume', vol_attrs)
        volume_info = Volume(provider_location=src_vref.provider_location,
                             size=src_vref.size,
                             id=volume.id,
                             name=volume_name,
                             status=src_vref.status,
                             volume_type=src_vref.volume_type,
                             metadata=src_vref.metadata,
                             obj_context=volume.obj_context)

        if (self._always_use_temp_snap_when_cloning or
                self._snapshots_exist(src_vref)):
            kwargs = {
                'volume_id': src_vref.id,
                'user_id': context.user_id,
                'project_id': context.project_id,
                'status': fields.SnapshotStatus.CREATING,
                'progress': '0%',
                'volume_size': src_vref.size,
                'display_name': 'tmp-snap-%s' % volume.id,
                'display_description': None,
                'volume_type_id': src_vref.volume_type_id,
                'encryption_key_id': src_vref.encryption_key_id,
            }
            temp_snapshot = objects.Snapshot(context=context,
                                             **kwargs)
            temp_snapshot.create()

            self._create_snapshot(temp_snapshot)
            try:
                self._copy_volume_from_snapshot(
                    temp_snapshot,
                    volume_info,
                    volume.size,
                    src_encryption_key_id=src_vref.encryption_key_id,
                    new_encryption_key_id=volume.encryption_key_id)

                # remove temp snapshot after the cloning is done
                temp_snapshot.status = fields.SnapshotStatus.DELETING
                temp_snapshot.context = context.elevated()
                temp_snapshot.save()
            finally:
                self._delete_snapshot(temp_snapshot)
                temp_snapshot.destroy()
        else:
            self._copy_volume_image(self.local_path(src_vref),
                                    self.local_path(volume_info))
            self._extend_volume(volume_info, volume.size)

        if src_vref.admin_metadata and 'format' in src_vref.admin_metadata:
            volume.admin_metadata['format'] = (
                src_vref.admin_metadata['format'])
            # This is done here because when cloning from a bootable volume,
            # while encountering other volume.save() method fails
            with volume.obj_as_admin():
                volume.save()
        return {'provider_location': src_vref.provider_location}

    def _copy_volume_image(self, src_path, dest_path):
        shutil.copyfile(src_path, dest_path)
        self._set_rw_permissions(dest_path)

    def _delete_stale_snapshot(self, snapshot):
        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)

        snapshot_file = snap_info[snapshot.id]
        active_file = self.get_active_image_from_info(snapshot.volume)
        snapshot_path = os.path.join(
            self._local_volume_dir(snapshot.volume), snapshot_file)
        if utils.paths_normcase_equal(snapshot_file, active_file):
            return

        LOG.info('Deleting stale snapshot: %s', snapshot.id)
        self._delete(snapshot_path)
        del(snap_info[snapshot.id])
        self._write_info_file(info_path, snap_info)

    def _delete_snapshot(self, snapshot):
        """Delete a snapshot.

        If volume status is 'available', delete snapshot here in Cinder
        using qemu-img.

        If volume status is 'in-use', calculate what qcow2 files need to
        merge, and call to Nova to perform this operation.

        :raises: InvalidVolume if status not acceptable
        :raises: RemoteFSException(msg) if operation fails
        :returns: None

        """
        LOG.debug('Deleting %(type)s snapshot %(snap)s of volume %(vol)s',
                  {'snap': snapshot.id, 'vol': snapshot.volume.id,
                   'type': ('online'
                            if self._is_volume_attached(snapshot.volume)
                            else 'offline')})

        volume_status = snapshot.volume.status
        acceptable_states = ['available', 'in-use', 'backing-up', 'deleting',
                             'downloading']
        self._validate_state(volume_status, acceptable_states)

        vol_path = self._local_volume_dir(snapshot.volume)
        volume_path = os.path.join(vol_path, snapshot.volume.name)

        # Determine the true snapshot file for this snapshot
        # based on the .info file
        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path, empty_if_missing=True)

        if snapshot.id not in snap_info:
            # If snapshot info file is present, but snapshot record does not
            # exist, do not attempt to delete.
            # (This happens, for example, if snapshot_create failed due to lack
            # of permission to write to the share.)
            LOG.info('Snapshot record for %s is not present, allowing '
                     'snapshot_delete to proceed.', snapshot.id)
            return

        snapshot_file = snap_info[snapshot.id]
        LOG.debug('snapshot_file for this snap is: %s', snapshot_file)
        snapshot_path = os.path.join(
            self._local_volume_dir(snapshot.volume),
            snapshot_file)

        snapshot_path_img_info = self._qemu_img_info(
            snapshot_path,
            snapshot.volume.name)

        base_file = snapshot_path_img_info.backing_file
        if base_file is None:
            # There should always be at least the original volume
            # file as base.
            LOG.warning('No backing file found for %s, allowing '
                        'snapshot to be deleted.', snapshot_path)

            # Snapshot may be stale, so just delete it and update the
            # info file instead of blocking
            return self._delete_stale_snapshot(snapshot)

        base_path = os.path.join(vol_path, base_file)
        base_file_img_info = self._qemu_img_info(base_path,
                                                 snapshot.volume.name)

        # Find what file has this as its backing file
        active_file = self.get_active_image_from_info(snapshot.volume)

        if self._is_volume_attached(snapshot.volume):
            # Online delete
            context = snapshot._context

            new_base_file = base_file_img_info.backing_file

            base_id = None
            for key, value in snap_info.items():
                if utils.paths_normcase_equal(value,
                                              base_file) and key != 'active':
                    base_id = key
                    break
            if base_id is None:
                # This means we are deleting the oldest snapshot
                LOG.debug('No %(base_id)s found for %(file)s',
                          {'base_id': 'base_id', 'file': snapshot_file})

            online_delete_info = {
                'active_file': active_file,
                'snapshot_file': snapshot_file,
                'base_file': base_file,
                'base_id': base_id,
                'new_base_file': new_base_file
            }

            return self._delete_snapshot_online(context,
                                                snapshot,
                                                online_delete_info)

        encrypted = snapshot.encryption_key_id is not None

        if encrypted:
            keymgr = key_manager.API(CONF)
            encryption_key = snapshot.encryption_key_id
            new_key = keymgr.get(snapshot.obj_context, encryption_key)
            src_passphrase = \
                binascii.hexlify(new_key.get_encoded()).decode('utf-8')

            tmp_dir = volume_utils.image_conversion_dir()

        if utils.paths_normcase_equal(snapshot_file, active_file):
            # There is no top file
            #      T0       |        T1         |
            #     base      |   snapshot_file   | None
            # (guaranteed to|  (being deleted,  |
            #    exist)     |  committed down)  |
            if encrypted:
                with tempfile.NamedTemporaryFile(prefix='luks_',
                                                 dir=tmp_dir) as src_file:
                    with open(src_file.name, 'w') as f:
                        f.write(src_passphrase)
                    self._img_commit(snapshot_path,
                                     passphrase_file=src_file.name,
                                     backing_file=volume_path)
            else:
                self._img_commit(snapshot_path)
            # Active file has changed
            snap_info['active'] = base_file
        else:
            #      T0        |      T1         |     T2         |      T3
            #     base       |  snapshot_file  |  higher_file   | highest_file
            # (guaranteed to | (being deleted, | (guaranteed to |  (may exist)
            #   exist, not   | committed down) |  exist, needs  |
            #   used here)   |                 |   ptr update)  |

            # This file is guaranteed to exist since we aren't operating on
            # the active file.
            higher_file = self._get_higher_image_path(snapshot)
            if higher_file is None:
                msg = _('No file found with %s as backing file.') %\
                    snapshot_file
                raise exception.RemoteFSException(msg)

            higher_id = next((i for i in snap_info
                              if utils.paths_normcase_equal(snap_info[i],
                                                            higher_file)
                              and i != 'active'),
                             None)
            if higher_id is None:
                msg = _('No snap found with %s as backing file.') %\
                    higher_file
                raise exception.RemoteFSException(msg)

            if encrypted:
                with tempfile.NamedTemporaryFile(prefix='luks_',
                                                 dir=tmp_dir) as src_file:
                    with open(src_file.name, 'w') as f:
                        f.write(src_passphrase)
                    self._img_commit(snapshot_path,
                                     passphrase_file=src_file.name,
                                     backing_file=volume_path)

                    higher_file_path = os.path.join(vol_path, higher_file)
                    base_file_fmt = base_file_img_info.file_format
                    self._rebase_img(higher_file_path, volume_path,
                                     base_file_fmt, src_file.name)
            else:
                self._img_commit(snapshot_path)

                higher_file_path = os.path.join(vol_path, higher_file)
                base_file_fmt = base_file_img_info.file_format
                self._rebase_img(higher_file_path, base_file, base_file_fmt)

        # Remove snapshot_file from info
        del(snap_info[snapshot.id])
        self._write_info_file(info_path, snap_info)

    def _create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        Snapshot must not be the active snapshot. (offline)
        """

        LOG.debug('Creating volume %(vol)s from snapshot %(snap)s',
                  {'vol': volume.id, 'snap': snapshot.id})

        status = snapshot.status
        acceptable_states = ['available', 'backing-up']
        self._validate_state(status, acceptable_states,
                             obj_description='snapshot',
                             invalid_exc=exception.InvalidSnapshot)

        self._ensure_shares_mounted()

        volume.provider_location = self._find_share(volume)

        self._do_create_volume(volume)

        self._copy_volume_from_snapshot(snapshot,
                                        volume,
                                        volume.size,
                                        snapshot.volume.encryption_key_id,
                                        volume.encryption_key_id)

        return {'provider_location': volume.provider_location}

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size,
                                   src_encryption_key_id=None,
                                   new_encryption_key_id=None):
        raise NotImplementedError()

    def _do_create_snapshot(self, snapshot, backing_filename,
                            new_snap_path):
        """Create a QCOW2 file backed by another file.

        :param snapshot: snapshot reference
        :param backing_filename: filename of file that will back the
            new qcow2 file
        :param new_snap_path: filename of new qcow2 file
        """
        backing_path_full_path = os.path.join(
            self._local_volume_dir(snapshot.volume),
            backing_filename)

        volume_path = os.path.join(
            self._local_volume_dir(snapshot.volume),
            snapshot.volume.name)

        info = self._qemu_img_info(backing_path_full_path,
                                   snapshot.volume.name)
        backing_fmt = info.file_format
        obj_context = snapshot.volume.obj_context

        # create new qcow2 file
        if snapshot.volume.encryption_key_id is None:
            command = ['qemu-img', 'create', '-f', 'qcow2', '-o',
                       'backing_file=%s,backing_fmt=%s' %
                       (backing_path_full_path, backing_fmt),
                       new_snap_path,
                       "%dG" % snapshot.volume.size]

            self._execute(*command, run_as_root=self._execute_as_root)

            command = ['qemu-img', 'rebase', '-u',
                       '-b', backing_filename,
                       '-F', backing_fmt,
                       new_snap_path]

            # qemu-img rebase must run as root for the same reasons as above
            self._execute(*command, run_as_root=self._execute_as_root)

        else:
            # encrypted
            keymgr = key_manager.API(CONF)
            # Get key for the source volume using the context of this request.
            key = keymgr.get(obj_context,
                             snapshot.volume.encryption_key_id)
            passphrase = binascii.hexlify(key.get_encoded()).decode('utf-8')

            tmp_dir = volume_utils.image_conversion_dir()
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_key:
                with open(tmp_key.name, 'w') as f:
                    f.write(passphrase)

                file_json_dict = {"driver": "qcow2",
                                  "encrypt.key-secret": "s0",
                                  "backing.encrypt.key-secret": "s0",
                                  "backing.file.filename": volume_path,
                                  "file": {"driver": "file",
                                           "filename": backing_path_full_path,
                                           }}
                file_json = jsonutils.dumps(file_json_dict)

                encryption = volume_utils.check_encryption_provider(
                    volume=snapshot.volume,
                    context=obj_context)

                cipher_spec = image_utils.decode_cipher(encryption['cipher'],
                                                        encryption['key_size'])

                command = ('qemu-img', 'create', '-f' 'qcow2',
                           '-o', 'encrypt.format=luks,encrypt.key-secret=s1,'
                           'encrypt.cipher-alg=%(cipher_alg)s,'
                           'encrypt.cipher-mode=%(cipher_mode)s,'
                           'encrypt.ivgen-alg=%(ivgen_alg)s' % cipher_spec,
                           '-b', 'json:' + file_json,
                           '--object', 'secret,id=s0,file=' + tmp_key.name,
                           '--object', 'secret,id=s1,file=' + tmp_key.name,
                           new_snap_path)
                self._execute(*command, run_as_root=self._execute_as_root)

                command_path = 'encrypt.key-secret=s0,file.filename='
                command = ['qemu-img', 'rebase',
                           '--object', 'secret,id=s0,file=' + tmp_key.name,
                           '--image-opts',
                           command_path + new_snap_path,
                           '-u',
                           '-b', backing_filename,
                           '-F', backing_fmt]

                # qemu-img rebase must run as root for the same reasons as
                # above
                self._execute(*command, run_as_root=self._execute_as_root)

        self._set_rw_permissions(new_snap_path)

        # if in secure mode, chown new file
        if self.secure_file_operations_enabled():
            ref_file = backing_path_full_path
            log_msg = 'Setting permissions: %(file)s -> %(user)s:%(group)s' % {
                'file': ref_file, 'user': os.stat(ref_file).st_uid,
                'group': os.stat(ref_file).st_gid}
            LOG.debug(log_msg)
            command = ['chown',
                       '--reference=%s' % ref_file,
                       new_snap_path]
            self._execute(*command, run_as_root=self._execute_as_root)

    def _create_snapshot(self, snapshot):
        """Create a snapshot.

        If volume is attached, call to Nova to create snapshot, providing a
        qcow2 file. Cinder creates and deletes qcow2 files, but Nova is
        responsible for transitioning the VM between them and handling live
        transfers of data between files as required.

        If volume is detached, create locally with qemu-img. Cinder handles
        manipulation of qcow2 files.

        A file named volume-<uuid>.info is stored with the volume
        data and is a JSON table which contains a mapping between
        Cinder snapshot UUIDs and filenames, as these associations
        will change as snapshots are deleted.


        Basic snapshot operation:

        1. Initial volume file:
            volume-1234

        2. Snapshot created:
            volume-1234  <- volume-1234.aaaa

            volume-1234.aaaa becomes the new "active" disk image.
            If the volume is not attached, this filename will be used to
            attach the volume to a VM at volume-attach time.
            If the volume is attached, the VM will switch to this file as
            part of the snapshot process.

            Note that volume-1234.aaaa represents changes after snapshot
            'aaaa' was created.  So the data for snapshot 'aaaa' is actually
            in the backing file(s) of volume-1234.aaaa.

            This file has a qcow2 header recording the fact that volume-1234 is
            its backing file.  Delta changes since the snapshot was created are
            stored in this file, and the backing file (volume-1234) does not
            change.

            info file: { 'active': 'volume-1234.aaaa',
                         'aaaa':   'volume-1234.aaaa' }

        3. Second snapshot created:
            volume-1234 <- volume-1234.aaaa <- volume-1234.bbbb

            volume-1234.bbbb now becomes the "active" disk image, recording
            changes made to the volume.

            info file: { 'active': 'volume-1234.bbbb',  (* changed!)
                         'aaaa':   'volume-1234.aaaa',
                         'bbbb':   'volume-1234.bbbb' } (* added!)

        4. Snapshot deletion when volume is attached ('in-use' state):

            * When first snapshot is deleted, Cinder calls Nova for online
              snapshot deletion. Nova deletes snapshot with id "aaaa" and
              makes snapshot with id "bbbb" point to the base image.
              Snapshot with id "bbbb" is the active image.

              volume-1234 <- volume-1234.bbbb

              info file: { 'active': 'volume-1234.bbbb',
                           'bbbb':   'volume-1234.bbbb'
                         }

             * When second snapshot is deleted, Cinder calls Nova for online
               snapshot deletion. Nova deletes snapshot with id "bbbb" by
               pulling volume-1234's data into volume-1234.bbbb. This
               (logically) removes snapshot with id "bbbb" and the active
               file remains the same.

               volume-1234.bbbb

               info file: { 'active': 'volume-1234.bbbb' }

           TODO (deepakcs): Change this once Nova supports blockCommit for
                            in-use volumes.

        5. Snapshot deletion when volume is detached ('available' state):

            * When first snapshot is deleted, Cinder does the snapshot
              deletion. volume-1234.aaaa is removed from the snapshot chain.
              The data from it is merged into its parent.

              volume-1234.bbbb is rebased, having volume-1234 as its new
              parent.

              volume-1234 <- volume-1234.bbbb

              info file: { 'active': 'volume-1234.bbbb',
                           'bbbb':   'volume-1234.bbbb'
                         }

            * When second snapshot is deleted, Cinder does the snapshot
              deletion. volume-1234.aaaa is removed from the snapshot chain.
              The base image, volume-1234 becomes the active image for this
              volume again.

              volume-1234

              info file: { 'active': 'volume-1234' }  (* changed!)
        """

        LOG.debug('Creating %(type)s snapshot %(snap)s of volume %(vol)s',
                  {'snap': snapshot.id, 'vol': snapshot.volume.id,
                   'type': ('online'
                            if self._is_volume_attached(snapshot.volume)
                            else 'offline')})

        status = snapshot.volume.status

        acceptable_states = ['available', 'in-use', 'backing-up']
        if (snapshot.display_name and
                snapshot.display_name.startswith('tmp-snap-')):
            # This is an internal volume snapshot. In order to support
            # image caching, we'll allow creating/deleting such snapshots
            # while having volumes in 'downloading' state.
            acceptable_states.append('downloading')

        self._validate_state(status, acceptable_states)

        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path, empty_if_missing=True)
        backing_filename = self.get_active_image_from_info(
            snapshot.volume)
        new_snap_path = self._get_new_snap_path(snapshot)
        active = os.path.basename(new_snap_path)

        if self._is_volume_attached(snapshot.volume):
            self._create_snapshot_online(snapshot,
                                         backing_filename,
                                         new_snap_path)
            # Update reference in the only attachment (no multi-attach support)
            attachment = snapshot.volume.volume_attachment[0]
            attachment.connection_info['name'] = active
            # Let OVO know it has been updated
            attachment.connection_info = attachment.connection_info
            attachment.save()
        else:
            self._do_create_snapshot(snapshot,
                                     backing_filename,
                                     new_snap_path)

        snap_info['active'] = active
        snap_info[snapshot.id] = active
        self._write_info_file(info_path, snap_info)

    def _create_snapshot_online(self, snapshot, backing_filename,
                                new_snap_path):
        # Perform online snapshot via Nova
        self._do_create_snapshot(snapshot,
                                 backing_filename,
                                 new_snap_path)

        connection_info = {
            'type': 'qcow2',
            'new_file': os.path.basename(new_snap_path),
            'snapshot_id': snapshot.id
        }

        try:
            result = self._nova.create_volume_snapshot(
                snapshot.obj_context,
                snapshot.volume_id,
                connection_info)
            LOG.debug('nova call result: %s', result)
        except Exception:
            LOG.exception('Call to Nova to create snapshot failed')
            raise

        # Loop and wait for result
        # Nova will call Cinderclient to update the status in the database
        # An update of progress = '90%' means that Nova is done
        seconds_elapsed = 0
        increment = 1
        timeout = 600
        while True:
            s = db.snapshot_get(snapshot.obj_context, snapshot.id)

            LOG.debug('Status of snapshot %(id)s is now %(status)s',
                      {'id': snapshot['id'],
                       'status': s['status']})

            if s['status'] == fields.SnapshotStatus.CREATING:
                if s['progress'] == '90%':
                    # Nova tasks completed successfully
                    break

                time.sleep(increment)
                seconds_elapsed += increment
            elif s['status'] == fields.SnapshotStatus.ERROR:

                msg = _('Nova returned "error" status '
                        'while creating snapshot.')
                raise exception.RemoteFSException(msg)

            elif (s['status'] == fields.SnapshotStatus.DELETING or
                  s['status'] == fields.SnapshotStatus.ERROR_DELETING):
                msg = _('Snapshot %(id)s has been asked to be deleted while '
                        'waiting for it to become available. Perhaps a '
                        'concurrent request was made.') % {'id':
                                                           snapshot.id}
                raise exception.RemoteFSConcurrentRequest(msg)

            if 10 < seconds_elapsed <= 20:
                increment = 2
            elif 20 < seconds_elapsed <= 60:
                increment = 5
            elif 60 < seconds_elapsed:
                increment = 10

            if seconds_elapsed > timeout:
                msg = _('Timed out while waiting for Nova update '
                        'for creation of snapshot %s.') % snapshot.id
                raise exception.RemoteFSException(msg)

    def _delete_snapshot_online(self, context, snapshot, info):
        # Update info over the course of this method
        # active file never changes
        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)
        update_format = False

        if utils.paths_normcase_equal(info['active_file'],
                                      info['snapshot_file']):
            # blockRebase/Pull base into active
            # info['base'] => snapshot_file

            file_to_delete = info['base_file']
            if info['base_id'] is None:
                # Passing base=none to blockRebase ensures that
                # libvirt blanks out the qcow2 backing file pointer
                new_base = None
            else:
                new_base = info['new_base_file']
                snap_info[info['base_id']] = info['snapshot_file']

            delete_info = {'file_to_merge': new_base,
                           'merge_target_file': None,  # current
                           'type': 'qcow2',
                           'volume_id': snapshot.volume.id}

            del(snap_info[snapshot.id])
            update_format = True
        else:
            # blockCommit snapshot into base
            # info['base'] <= snapshot_file
            # delete record of snapshot
            file_to_delete = info['snapshot_file']

            delete_info = {'file_to_merge': info['snapshot_file'],
                           'merge_target_file': info['base_file'],
                           'type': 'qcow2',
                           'volume_id': snapshot.volume.id}

            del(snap_info[snapshot.id])

        self._nova_assisted_vol_snap_delete(context, snapshot, delete_info)

        if update_format:
            snapshot.volume.admin_metadata['format'] = 'qcow2'
            with snapshot.volume.obj_as_admin():
                snapshot.volume.save()

        # Write info file updated above
        self._write_info_file(info_path, snap_info)

        # Delete stale file
        path_to_delete = os.path.join(
            self._local_volume_dir(snapshot.volume), file_to_delete)
        self._delete(path_to_delete)

    def _nova_assisted_vol_snap_delete(self, context, snapshot, delete_info):
        try:
            self._nova.delete_volume_snapshot(
                context,
                snapshot.id,
                delete_info)
        except Exception:
            LOG.exception('Call to Nova delete snapshot failed')
            raise

        # Loop and wait for result
        # Nova will call Cinderclient to update the status in the database
        # An update of progress = '90%' means that Nova is done
        seconds_elapsed = 0
        increment = 1
        timeout = 7200
        while True:
            s = db.snapshot_get(context, snapshot.id)

            if s['status'] == fields.SnapshotStatus.DELETING:
                if s['progress'] == '90%':
                    # Nova tasks completed successfully
                    break
                else:
                    LOG.debug('status of snapshot %s is still "deleting"... '
                              'waiting', snapshot.id)
                    time.sleep(increment)
                    seconds_elapsed += increment
            else:
                msg = _('Unable to delete snapshot %(id)s, '
                        'status: %(status)s.') % {'id': snapshot.id,
                                                  'status': s['status']}
                raise exception.RemoteFSException(msg)

            if 10 < seconds_elapsed <= 20:
                increment = 2
            elif 20 < seconds_elapsed <= 60:
                increment = 5
            elif 60 < seconds_elapsed:
                increment = 10

            if seconds_elapsed > timeout:
                msg = _('Timed out while waiting for Nova update '
                        'for deletion of snapshot %(id)s.') %\
                    {'id': snapshot.id}
                raise exception.RemoteFSException(msg)

    def _extend_volume(self, volume, size_gb):
        raise NotImplementedError()

    def _revert_to_snapshot(self, context, volume, snapshot):
        raise NotImplementedError()


class RemoteFSSnapDriver(RemoteFSSnapDriverBase):
    @locked_volume_id_operation
    def create_snapshot(self, snapshot):
        """Apply locking to the create snapshot operation."""

        return self._create_snapshot(snapshot)

    @locked_volume_id_operation
    def delete_snapshot(self, snapshot):
        """Apply locking to the delete snapshot operation."""

        return self._delete_snapshot(snapshot)

    @locked_volume_id_operation
    def create_volume_from_snapshot(self, volume, snapshot):
        return self._create_volume_from_snapshot(volume, snapshot)

    # TODO: should be locking on src_vref id -- bug #1852449
    @locked_volume_id_operation
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        return self._create_cloned_volume(volume, src_vref,
                                          src_vref.obj_context)

    @locked_volume_id_operation
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        return self._copy_volume_to_image(context, volume, image_service,
                                          image_meta)

    @locked_volume_id_operation
    def extend_volume(self, volume, size_gb):
        return self._extend_volume(volume, size_gb)

    @locked_volume_id_operation
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert to specified snapshot."""

        return self._revert_to_snapshot(context, volume, snapshot)


class RemoteFSSnapDriverDistributed(RemoteFSSnapDriverBase):
    @coordination.synchronized('{self.driver_prefix}-{snapshot.volume.id}')
    def create_snapshot(self, snapshot):
        """Apply locking to the create snapshot operation."""

        return self._create_snapshot(snapshot)

    @coordination.synchronized('{self.driver_prefix}-{snapshot.volume.id}')
    def delete_snapshot(self, snapshot):
        """Apply locking to the delete snapshot operation."""

        return self._delete_snapshot(snapshot)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def create_volume_from_snapshot(self, volume, snapshot):
        return self._create_volume_from_snapshot(volume, snapshot)

    # lock the source volume id first
    @coordination.synchronized('{self.driver_prefix}-{src_vref.id}')
    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        return self._create_cloned_volume(volume, src_vref,
                                          src_vref.obj_context)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        return self._copy_volume_to_image(context, volume, image_service,
                                          image_meta)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def extend_volume(self, volume, size_gb):
        return self._extend_volume(volume, size_gb)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert to specified snapshot."""

        return self._revert_to_snapshot(context, volume, snapshot)


class RemoteFSPoolMixin(object):
    """Drivers inheriting this will report each share as a pool."""

    def _find_share(self, volume):
        # We let the scheduler choose a pool for us.
        pool_name = self._get_pool_name_from_volume(volume)
        share = self._get_share_from_pool_name(pool_name)
        return share

    def _get_pool_name_from_volume(self, volume):
        pool_name = volume_utils.extract_host(volume['host'],
                                              level='pool')
        return pool_name

    def _get_pool_name_from_share(self, share):
        raise NotImplementedError()

    def _get_share_from_pool_name(self, pool_name):
        # To be implemented by drivers using pools.
        raise NotImplementedError()

    def _update_volume_stats(self):
        data = {}
        pools = []
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.volume_backend_name
        data['vendor_name'] = self.vendor_name
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = self.driver_volume_type

        self._ensure_shares_mounted()

        for share in self._mounted_shares:
            (share_capacity,
             share_free,
             total_allocated) = self._get_capacity_info(share)

            pool = {'pool_name': self._get_pool_name_from_share(share),
                    'total_capacity_gb': share_capacity / float(units.Gi),
                    'free_capacity_gb': share_free / float(units.Gi),
                    'provisioned_capacity_gb': (
                        total_allocated / float(units.Gi)),
                    'reserved_percentage': (
                        self.configuration.reserved_percentage),
                    'max_over_subscription_ratio': (
                        self.configuration.max_over_subscription_ratio),
                    'thin_provisioning_support': (
                        self._thin_provisioning_support),
                    'thick_provisioning_support': (
                        self._thick_provisioning_support),
                    'QoS_support': False,
                    }

            pools.append(pool)

        data['total_capacity_gb'] = 0
        data['free_capacity_gb'] = 0
        data['pools'] = pools

        self._stats = data


class RevertToSnapshotMixin(object):

    def _revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to specified snapshot

        The volume must not be attached. Only the latest snapshot
        can be used.
        """
        status = snapshot.volume.status
        acceptable_states = ['available', 'reverting']

        self._validate_state(status, acceptable_states)

        LOG.debug('Reverting volume %(vol)s to snapshot %(snap)s',
                  {'vol': snapshot.volume.id, 'snap': snapshot.id})

        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)

        snapshot_file = snap_info[snapshot.id]
        active_file = snap_info['active']

        if not utils.paths_normcase_equal(snapshot_file, active_file):
            msg = _("Could not revert volume '%(volume_id)s' to snapshot "
                    "'%(snapshot_id)s' as it does not "
                    "appear to be the latest snapshot. Current active "
                    "image: %(active_file)s.")
            raise exception.InvalidSnapshot(
                msg % dict(snapshot_id=snapshot.id,
                           active_file=active_file,
                           volume_id=volume.id))

        snapshot_path = os.path.join(
            self._local_volume_dir(snapshot.volume), snapshot_file)
        backing_filename = self._qemu_img_info(
            snapshot_path, volume.name).backing_file

        # We revert the volume to the latest snapshot by recreating the top
        # image from the chain.
        # This workflow should work with most (if not all) drivers inheriting
        # this class.
        self._delete(snapshot_path)
        self._do_create_snapshot(snapshot, backing_filename, snapshot_path)


class RemoteFSManageableVolumesMixin(object):
    _SUPPORTED_IMAGE_FORMATS = ['raw', 'qcow2']
    _MANAGEABLE_IMAGE_RE = None

    def _get_manageable_vol_location(self, existing_ref):
        if 'source-name' not in existing_ref:
            reason = _('The existing volume reference '
                       'must contain "source-name".')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        vol_remote_path = os.path.normcase(
            os.path.normpath(existing_ref['source-name']))

        for mounted_share in self._mounted_shares:
            # We don't currently attempt to resolve hostnames. This could
            # be troublesome for some distributed shares, which may have
            # hostnames resolving to multiple addresses.
            norm_share = os.path.normcase(os.path.normpath(mounted_share))
            head, match, share_rel_path = vol_remote_path.partition(norm_share)
            if not (match and share_rel_path.startswith(os.path.sep)):
                continue

            mountpoint = self._get_mount_point_for_share(mounted_share)
            vol_local_path = os.path.join(mountpoint,
                                          share_rel_path.lstrip(os.path.sep))

            LOG.debug("Found mounted share referenced by %s.",
                      vol_remote_path)

            if os.path.isfile(vol_local_path):
                LOG.debug("Found volume %(path)s on share %(share)s.",
                          dict(path=vol_local_path, share=mounted_share))
                return dict(share=mounted_share,
                            mountpoint=mountpoint,
                            vol_local_path=vol_local_path,
                            vol_remote_path=vol_remote_path)
            else:
                LOG.error("Could not find volume %s on the "
                          "specified share.", vol_remote_path)
                break

        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=_('Volume not found.'))

    def _get_managed_vol_expected_path(self, volume, volume_location):
        # This may be overridden by the drivers.
        return os.path.join(volume_location['mountpoint'],
                            volume.name)

    def _is_volume_manageable(self, volume_path, already_managed=False):
        unmanageable_reason = None

        if already_managed:
            return False, _('Volume already managed.')

        try:
            img_info = self._qemu_img_info(volume_path, volume_name=None)
        except exception.RemoteFSInvalidBackingFile:
            return False, _("Backing file present.")
        except Exception:
            return False, _("Failed to open image.")

        # We're double checking as some drivers do not validate backing
        # files through '_qemu_img_info'.
        if img_info.backing_file:
            return False, _("Backing file present.")

        if img_info.file_format not in self._SUPPORTED_IMAGE_FORMATS:
            unmanageable_reason = _(
                "Unsupported image format: '%s'.") % img_info.file_format
            return False, unmanageable_reason

        return True, None

    def manage_existing(self, volume, existing_ref):
        LOG.info('Managing volume %(volume_id)s with ref %(ref)s',
                 {'volume_id': volume.id, 'ref': existing_ref})

        vol_location = self._get_manageable_vol_location(existing_ref)
        vol_local_path = vol_location['vol_local_path']

        manageable, unmanageable_reason = self._is_volume_manageable(
            vol_local_path)

        if not manageable:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=unmanageable_reason)

        expected_vol_path = self._get_managed_vol_expected_path(
            volume, vol_location)

        self._set_rw_permissions(vol_local_path)

        # This should be the last thing we do.
        if expected_vol_path != vol_local_path:
            LOG.info("Renaming imported volume image %(src)s to %(dest)s",
                     dict(src=vol_location['vol_local_path'],
                          dest=expected_vol_path))
            os.rename(vol_location['vol_local_path'],
                      expected_vol_path)

        return {'provider_location': vol_location['share']}

    def _get_rounded_manageable_image_size(self, image_path):
        image_size = image_utils.qemu_img_info(
            image_path, run_as_root=self._execute_as_root).virtual_size
        return int(math.ceil(float(image_size) / units.Gi))

    def manage_existing_get_size(self, volume, existing_ref):
        vol_location = self._get_manageable_vol_location(existing_ref)
        volume_path = vol_location['vol_local_path']
        return self._get_rounded_manageable_image_size(volume_path)

    def unmanage(self, volume):
        pass

    def _get_manageable_volume(self, share, volume_path, managed_volume=None):
        manageable, unmanageable_reason = self._is_volume_manageable(
            volume_path, already_managed=managed_volume is not None)
        size_gb = None
        if managed_volume:
            # We may not be able to query in-use images.
            size_gb = managed_volume.size
        else:
            try:
                size_gb = self._get_rounded_manageable_image_size(volume_path)
            except Exception:
                manageable = False
                unmanageable_reason = (unmanageable_reason or
                                       _("Failed to get size."))

        mountpoint = self._get_mount_point_for_share(share)
        norm_mountpoint = os.path.normcase(os.path.normpath(mountpoint))
        norm_vol_path = os.path.normcase(os.path.normpath(volume_path))

        ref = norm_vol_path.replace(norm_mountpoint, share).replace('\\', '/')
        manageable_volume = {
            'reference': {'source-name': ref},
            'size': size_gb,
            'safe_to_manage': manageable,
            'reason_not_safe': unmanageable_reason,
            'cinder_id': managed_volume.id if managed_volume else None,
            'extra_info': None,
        }
        return manageable_volume

    def _get_share_manageable_volumes(self, share, managed_volumes):
        manageable_volumes = []
        mount_path = self._get_mount_point_for_share(share)

        for dir_path, dir_names, file_names in os.walk(mount_path):
            for file_name in file_names:
                file_name = os.path.normcase(file_name)
                img_path = os.path.join(dir_path, file_name)
                # In the future, we may have the regex filtering images
                # as a config option.
                if (not self._MANAGEABLE_IMAGE_RE or
                        self._MANAGEABLE_IMAGE_RE.match(file_name)):
                    managed_volume = managed_volumes.get(
                        os.path.splitext(file_name)[0])
                    try:
                        manageable_volume = self._get_manageable_volume(
                            share, img_path, managed_volume)
                        manageable_volumes.append(manageable_volume)
                    except Exception as exc:
                        LOG.error(
                            "Failed to get manageable volume info: "
                            "'%(image_path)s'. Exception: %(exc)s.",
                            dict(image_path=img_path, exc=exc))
        return manageable_volumes

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        manageable_volumes = []
        managed_volumes = {vol.name: vol for vol in cinder_volumes}

        for share in self._mounted_shares:
            try:
                manageable_volumes += self._get_share_manageable_volumes(
                    share, managed_volumes)
            except Exception as exc:
                LOG.error("Failed to get manageable volumes for "
                          "share %(share)s. Exception: %(exc)s.",
                          dict(share=share, exc=exc))

        return volume_utils.paginate_entries_list(
            manageable_volumes, marker, limit, offset, sort_keys, sort_dirs)
