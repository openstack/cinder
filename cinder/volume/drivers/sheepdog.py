#    Copyright 2012 OpenStack Foundation
#    Copyright (c) 2013 Zelin.io
#    Copyright (C) 2015 Nippon Telegraph and Telephone Corporation.
#    All Rights Reserved.
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
SheepDog Volume Driver.

"""
import errno
import eventlet
import io
import re

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume import driver


LOG = logging.getLogger(__name__)

sheepdog_opts = [
    cfg.StrOpt('sheepdog_store_address',
               default='127.0.0.1',
               help=('IP address of sheep daemon.')),
    cfg.IntOpt('sheepdog_store_port',
               min=1, max=65535,
               default=7000,
               help=('Port of sheep daemon.'))
]

CONF = cfg.CONF
CONF.import_opt("image_conversion_dir", "cinder.image.image_utils")
CONF.register_opts(sheepdog_opts)


class SheepdogClient(object):
    """Sheepdog command executor."""
    DOG_RESP_CONNECTION_ERROR = 'failed to connect to'
    DOG_RESP_CLUSTER_RUNNING = 'Cluster status: running'
    DOG_RESP_CLUSTER_NOT_FORMATTED = ('Cluster status: '
                                      'Waiting for cluster to be formatted')
    DOG_RESP_CLUSTER_WAITING = ('Cluster status: '
                                'Waiting for other nodes to join cluster')
    DOG_RESP_VDI_ALREADY_EXISTS = ': VDI exists already'
    DOG_RESP_VDI_NOT_FOUND = ': No VDI found'

    def __init__(self, addr, port):
        self.addr = addr
        self.port = port

    def _run_dog(self, command, subcommand, *params):
        cmd = ('env', 'LC_ALL=C', 'LANG=C', 'dog', command, subcommand,
               '-a', self.addr, '-p', str(self.port)) + params
        try:
            return utils.execute(*cmd)
        except OSError as e:
            with excutils.save_and_reraise_exception():
                if e.errno == errno.ENOENT:
                    msg = _LE('Sheepdog is not installed. '
                              'OSError: command is %s.')
                else:
                    msg = _LE('OSError: command is %s.')
                LOG.error(msg, cmd)
        except processutils.ProcessExecutionError as e:
            raise exception.SheepdogCmdError(
                cmd=e.cmd,
                exit_code=e.exit_code,
                stdout=e.stdout.replace('\n', '\\n'),
                stderr=e.stderr.replace('\n', '\\n'))

    def check_cluster_status(self):
        try:
            (_stdout, _stderr) = self._run_dog('cluster', 'info')
        except exception.SheepdogCmdError as e:
            cmd = e.kwargs['cmd']
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                    msg = _LE('Failed to connect to sheep daemon. '
                              'addr: %(addr)s, port: %(port)s')
                    LOG.error(msg, {'addr': self.addr, 'port': self.port})
                else:
                    LOG.error(_LE('Failed to check cluster status.'
                                  '(command: %s)'), cmd)

        if _stdout.startswith(self.DOG_RESP_CLUSTER_RUNNING):
            LOG.debug('Sheepdog cluster is running.')
            return

        reason = _('Invalid sheepdog cluster status.')
        if _stdout.startswith(self.DOG_RESP_CLUSTER_NOT_FORMATTED):
            reason = _('Cluster is not formatted. '
                       'You should probably perform "dog cluster format".')
        elif _stdout.startswith(self.DOG_RESP_CLUSTER_WAITING):
            reason = _('Waiting for all nodes to join cluster. '
                       'Ensure all sheep daemons are running.')
        raise exception.SheepdogError(reason=reason)

    def create(self, vdiname, size):
        try:
            self._run_dog('vdi', 'create', vdiname, '%sG' % size)
        except exception.SheepdogCmdError as e:
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                    LOG.error(_LE("Failed to connect to sheep daemon. "
                              "addr: %(addr)s, port: %(port)s"),
                              {'addr': self.addr, 'port': self.port})
                elif _stderr.rstrip('\\n').endswith(
                        self.DOG_RESP_VDI_ALREADY_EXISTS):
                    LOG.error(_LE('Volume already exists. %s'), vdiname)
                else:
                    LOG.error(_LE('Failed to create volume. %s'), vdiname)

    def delete(self, vdiname):
        try:
            (_stdout, _stderr) = self._run_dog('vdi', 'delete', vdiname)
            if _stderr.rstrip().endswith(self.DOG_RESP_VDI_NOT_FOUND):
                LOG.warning(_LW('Volume not found. %s'), vdiname)
            elif _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                # NOTE(tishizaki)
                # Dog command does not return error_code although
                # dog command cannot connect to sheep process.
                # That is a Sheepdog's bug.
                # To avoid a Sheepdog's bug, now we need to check stderr.
                # If Sheepdog has been fixed, this check logic is needed
                # by old Sheepdog users.
                reason = (_('Failed to connect to sheep daemon. '
                          'addr: %(addr)s, port: %(port)s'),
                          {'addr': self.addr, 'port': self.port})
                raise exception.SheepdogError(reason=reason)
        except exception.SheepdogCmdError as e:
            _stderr = e.kwargs['stderr']
            with excutils.save_and_reraise_exception():
                if _stderr.startswith(self.DOG_RESP_CONNECTION_ERROR):
                    LOG.error(_LE('Failed to connect to sheep daemon. '
                              'addr: %(addr)s, port: %(port)s'),
                              {'addr': self.addr, 'port': self.port})
                else:
                    LOG.error(_LE('Failed to delete volume. %s'), vdiname)


class SheepdogIOWrapper(io.RawIOBase):
    """File-like object with Sheepdog backend."""

    def __init__(self, volume, snapshot_name=None):
        self._vdiname = volume['name']
        self._snapshot_name = snapshot_name
        self._offset = 0
        # SheepdogIOWrapper instance becomes invalid if a write error occurs.
        self._valid = True

    def _execute(self, cmd, data=None):
        try:
            # NOTE(yamada-h): processutils.execute causes busy waiting
            # under eventlet.
            # To avoid wasting CPU resources, it should not be used for
            # the command which takes long time to execute.
            # For workaround, we replace a subprocess module with
            # the original one while only executing a read/write command.
            _processutils_subprocess = processutils.subprocess
            processutils.subprocess = eventlet.patcher.original('subprocess')
            return processutils.execute(*cmd, process_input=data)[0]
        except (processutils.ProcessExecutionError, OSError):
            self._valid = False
            msg = _('Sheepdog I/O Error, command was: "%s".') % ' '.join(cmd)
            raise exception.VolumeDriverException(message=msg)
        finally:
            processutils.subprocess = _processutils_subprocess

    def read(self, length=None):
        if not self._valid:
            msg = _('An error occurred while reading volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        cmd = ['dog', 'vdi', 'read']
        if self._snapshot_name:
            cmd.extend(('-s', self._snapshot_name))
        cmd.extend((self._vdiname, self._offset))
        if length:
            cmd.append(length)
        data = self._execute(cmd)
        self._offset += len(data)
        return data

    def write(self, data):
        if not self._valid:
            msg = _('An error occurred while writing to volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        length = len(data)
        cmd = ('dog', 'vdi', 'write', self._vdiname, self._offset, length)
        self._execute(cmd, data)
        self._offset += length
        return length

    def seek(self, offset, whence=0):
        if not self._valid:
            msg = _('An error occured while seeking for volume "%s".'
                    ) % self._vdiname
            raise exception.VolumeDriverException(message=msg)

        if whence == 0:
            # SEEK_SET or 0 - start of the stream (the default);
            # offset should be zero or positive
            new_offset = offset
        elif whence == 1:
            # SEEK_CUR or 1 - current stream position; offset may be negative
            new_offset = self._offset + offset
        else:
            # SEEK_END or 2 - end of the stream; offset is usually negative
            # TODO(yamada-h): Support SEEK_END
            raise IOError(_("Invalid argument - whence=%s not supported.") %
                          whence)

        if new_offset < 0:
            raise IOError(_("Invalid argument - negative seek offset."))

        self._offset = new_offset

    def tell(self):
        return self._offset

    def flush(self):
        pass

    def fileno(self):
        """Sheepdog does not have support for fileno so we raise IOError.

        Raising IOError is recommended way to notify caller that interface is
        not supported - see http://docs.python.org/2/library/io.html#io.IOBase
        """
        raise IOError(_("fileno is not supported by SheepdogIOWrapper"))


class SheepdogDriver(driver.VolumeDriver):
    """Executes commands relating to Sheepdog Volumes."""

    VERSION = "1.0.0"

    def __init__(self, *args, **kwargs):
        super(SheepdogDriver, self).__init__(*args, **kwargs)
        self.client = SheepdogClient(CONF.sheepdog_store_address,
                                     CONF.sheepdog_store_port)
        self.stats_pattern = re.compile(r'[\w\s%]*Total\s(\d+)\s(\d+)*')
        self._stats = {}

    def check_for_setup_error(self):
        self.client.check_cluster_status()

    def _is_cloneable(self, image_location, image_meta):
        """Check the image can be clone or not."""

        if image_location is None:
            return False

        if not image_location.startswith("sheepdog:"):
            LOG.debug("Image is not stored in sheepdog.")
            return False

        if image_meta['disk_format'] != 'raw':
            LOG.debug("Image clone requires image format to be "
                      "'raw' but image %s(%s) is '%s'.",
                      image_location,
                      image_meta['id'],
                      image_meta['disk_format'])
            return False

        cloneable = False
        # check whether volume is stored in sheepdog
        try:
            # The image location would be like
            # "sheepdog:192.168.10.2:7000:Alice"
            (label, ip, port, name) = image_location.split(":", 3)

            self._try_execute('collie', 'vdi', 'list', '--address', ip,
                              '--port', port, name)
            cloneable = True
        except processutils.ProcessExecutionError as e:
            LOG.debug("Can not find vdi %(image)s: %(err)s",
                      {'image': name, 'err': e})

        return cloneable

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume efficiently from an existing image."""
        image_location = image_location[0] if image_location else None
        if not self._is_cloneable(image_location, image_meta):
            return {}, False

        # The image location would be like
        # "sheepdog:192.168.10.2:7000:Alice"
        (label, ip, port, name) = image_location.split(":", 3)
        volume_ref = {'name': name, 'size': image_meta['size']}
        self.create_cloned_volume(volume, volume_ref)
        self._resize(volume)

        vol_path = self.local_path(volume)
        return {'provider_location': vol_path}, True

    def create_cloned_volume(self, volume, src_vref):
        """Clone a sheepdog volume from another volume."""

        snapshot_name = src_vref['name'] + '-temp-snapshot'
        snapshot = {
            'name': snapshot_name,
            'volume_name': src_vref['name'],
            'volume_size': src_vref['size'],
        }

        self.create_snapshot(snapshot)

        try:
            # Create volume
            self.create_volume_from_snapshot(volume, snapshot)
        except processutils.ProcessExecutionError:
            msg = _('Failed to create cloned volume %s.') % volume['id']
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)
        finally:
            # Delete temp Snapshot
            self.delete_snapshot(snapshot)

    def create_volume(self, volume):
        """Create a sheepdog volume."""
        self.client.create(volume.name, volume.size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a sheepdog volume from a snapshot."""
        self._try_execute('qemu-img', 'create', '-b',
                          "sheepdog:%s:%s" % (snapshot['volume_name'],
                                              snapshot['name']),
                          "sheepdog:%s" % volume['name'],
                          '%sG' % volume['size'])

    def delete_volume(self, volume):
        """Delete a logical volume."""
        self.client.delete(volume.name)

    def _resize(self, volume, size=None):
        if not size:
            size = int(volume['size']) * units.Gi

        self._try_execute('collie', 'vdi', 'resize',
                          volume['name'], size)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        with image_utils.temporary_file() as tmp:
            # (wenhao): we don't need to convert to raw for sheepdog.
            image_utils.fetch_verify_image(context, image_service,
                                           image_id, tmp)

            # remove the image created by import before this function.
            # see volume/drivers/manager.py:_create_volume
            self.client.delete(volume.name)
            # convert and store into sheepdog
            image_utils.convert_image(tmp, 'sheepdog:%s' % volume['name'],
                                      'raw')
            self._resize(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_id = image_meta['id']
        with image_utils.temporary_file() as tmp:
            # image_utils.convert_image doesn't support "sheepdog:" source,
            # so we use the qemu-img directly.
            # Sheepdog volume is always raw-formatted.
            cmd = ('qemu-img',
                   'convert',
                   '-f', 'raw',
                   '-t', 'none',
                   '-O', 'raw',
                   'sheepdog:%s' % volume['name'],
                   tmp)
            self._try_execute(*cmd)

            with open(tmp, 'rb') as image_file:
                image_service.update(context, image_id, {}, image_file)

    def create_snapshot(self, snapshot):
        """Create a sheepdog snapshot."""
        self._try_execute('qemu-img', 'snapshot', '-c', snapshot['name'],
                          "sheepdog:%s" % snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Delete a sheepdog snapshot."""
        self._try_execute('collie', 'vdi', 'delete', snapshot['volume_name'],
                          '-s', snapshot['name'])

    def local_path(self, volume):
        return "sheepdog:%s" % volume['name']

    def ensure_export(self, context, volume):
        """Safely and synchronously recreate an export for a logical volume."""
        pass

    def create_export(self, context, volume, connector):
        """Export a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name']
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _update_volume_stats(self):
        stats = {}

        backend_name = "sheepdog"
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        stats["volume_backend_name"] = backend_name or 'sheepdog'
        stats['vendor_name'] = 'Open Source'
        stats['driver_version'] = self.VERSION
        stats['storage_protocol'] = 'sheepdog'
        stats['total_capacity_gb'] = 'unknown'
        stats['free_capacity_gb'] = 'unknown'
        stats['reserved_percentage'] = 0
        stats['QoS_support'] = False

        try:
            stdout, _err = self._execute('collie', 'node', 'info', '-r')
            m = self.stats_pattern.match(stdout)
            total = float(m.group(1))
            used = float(m.group(2))
            stats['total_capacity_gb'] = total / units.Gi
            stats['free_capacity_gb'] = (total - used) / units.Gi
        except processutils.ProcessExecutionError:
            LOG.exception(_LE('error refreshing volume stats'))

        self._stats = stats

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        old_size = volume['size']

        try:
            size = int(new_size) * units.Gi
            self._resize(volume, size=size)
        except Exception:
            msg = _('Failed to Extend Volume '
                    '%(volname)s') % {'volname': volume['name']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Extend volume from %(old_size)s GB to %(new_size)s GB.",
                  {'old_size': old_size, 'new_size': new_size})

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])
        temp_snapshot = {'volume_name': volume['name'],
                         'name': 'tmp-snap-%s' % volume['name']}

        # NOTE(tishizaki): If previous backup_volume operation has failed,
        # a temporary snapshot for previous operation may exist.
        # So, the old snapshot must be deleted before backup_volume.
        # Sheepdog 0.9 or later 'delete_snapshot' operation
        # is done successfully, although target snapshot does not exist.
        # However, sheepdog 0.8 or before 'delete_snapshot' operation
        # is failed, and raise ProcessExecutionError when target snapshot
        # does not exist.
        try:
            self.delete_snapshot(temp_snapshot)
        except (processutils.ProcessExecutionError):
            pass

        try:
            self.create_snapshot(temp_snapshot)
        except (processutils.ProcessExecutionError, OSError):
            msg = (_('Failed to create a temporary snapshot for volume %s.')
                   % volume['id'])
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            sheepdog_fd = SheepdogIOWrapper(volume, temp_snapshot['name'])
            backup_service.backup(backup, sheepdog_fd)
        finally:
            self.delete_snapshot(temp_snapshot)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        sheepdog_fd = SheepdogIOWrapper(volume)
        backup_service.restore(backup, volume['id'], sheepdog_fd)
