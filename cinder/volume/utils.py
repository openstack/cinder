# Copyright (c) 2012 OpenStack Foundation
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

"""Volume-related Utilities and helpers."""


import ast
import functools
import json
import math
import operator
from os import urandom
import re
import time
import uuid

import eventlet
from eventlet import tpool
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
from random import shuffle
import six
from six.moves import range

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import rpc
from cinder import utils
from cinder.volume import group_types
from cinder.volume import throttling
from cinder.volume import volume_types


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


def null_safe_str(s):
    return str(s) if s else ''


def _usage_from_volume(context, volume_ref, **kw):
    now = timeutils.utcnow()
    launched_at = volume_ref['launched_at'] or now
    created_at = volume_ref['created_at'] or now
    volume_status = volume_ref['status']
    if volume_status == 'error_managing_deleting':
        volume_status = 'deleting'
    usage_info = dict(
        tenant_id=volume_ref['project_id'],
        host=volume_ref['host'],
        user_id=volume_ref['user_id'],
        availability_zone=volume_ref['availability_zone'],
        volume_id=volume_ref['id'],
        volume_type=volume_ref['volume_type_id'],
        display_name=volume_ref['display_name'],
        launched_at=launched_at.isoformat(),
        created_at=created_at.isoformat(),
        status=volume_status,
        snapshot_id=volume_ref['snapshot_id'],
        size=volume_ref['size'],
        replication_status=volume_ref['replication_status'],
        replication_extended_status=volume_ref['replication_extended_status'],
        replication_driver_data=volume_ref['replication_driver_data'],
        metadata=volume_ref.get('volume_metadata'),)

    usage_info.update(kw)
    try:
        attachments = db.volume_attachment_get_all_by_volume_id(
            context, volume_ref['id'])
        usage_info['volume_attachment'] = attachments

        glance_meta = db.volume_glance_metadata_get(context, volume_ref['id'])
        if glance_meta:
            usage_info['glance_metadata'] = glance_meta
    except exception.GlanceMetadataNotFound:
        pass
    except exception.VolumeNotFound:
        LOG.debug("Can not find volume %s at notify usage", volume_ref['id'])

    return usage_info


def _usage_from_backup(backup, **kw):
    num_dependent_backups = backup.num_dependent_backups
    usage_info = dict(tenant_id=backup.project_id,
                      user_id=backup.user_id,
                      availability_zone=backup.availability_zone,
                      backup_id=backup.id,
                      host=backup.host,
                      display_name=backup.display_name,
                      created_at=str(backup.created_at),
                      status=backup.status,
                      volume_id=backup.volume_id,
                      size=backup.size,
                      service_metadata=backup.service_metadata,
                      service=backup.service,
                      fail_reason=backup.fail_reason,
                      parent_id=backup.parent_id,
                      num_dependent_backups=num_dependent_backups,
                      snapshot_id=backup.snapshot_id,
                      )

    usage_info.update(kw)
    return usage_info


@utils.if_notifications_enabled
def notify_about_volume_usage(context, volume, event_suffix,
                              extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(context, volume, **extra_usage_info)

    rpc.get_notifier("volume", host).info(context, 'volume.%s' % event_suffix,
                                          usage_info)


@utils.if_notifications_enabled
def notify_about_backup_usage(context, backup, event_suffix,
                              extra_usage_info=None,
                              host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_backup(backup, **extra_usage_info)

    rpc.get_notifier("backup", host).info(context, 'backup.%s' % event_suffix,
                                          usage_info)


def _usage_from_snapshot(snapshot, context, **extra_usage_info):
    # (niedbalski) a snapshot might be related to a deleted
    # volume, if that's the case, the volume information is still
    # required for filling the usage_info, so we enforce to read
    # the volume data even if the volume has been deleted.
    context.read_deleted = "yes"
    volume = db.volume_get(context, snapshot.volume_id)
    usage_info = {
        'tenant_id': snapshot.project_id,
        'user_id': snapshot.user_id,
        'availability_zone': volume['availability_zone'],
        'volume_id': snapshot.volume_id,
        'volume_size': snapshot.volume_size,
        'snapshot_id': snapshot.id,
        'display_name': snapshot.display_name,
        'created_at': str(snapshot.created_at),
        'status': snapshot.status,
        'deleted': null_safe_str(snapshot.deleted),
        'metadata': null_safe_str(snapshot.metadata),
    }

    usage_info.update(extra_usage_info)
    return usage_info


@utils.if_notifications_enabled
def notify_about_snapshot_usage(context, snapshot, event_suffix,
                                extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_snapshot(snapshot, context, **extra_usage_info)

    rpc.get_notifier('snapshot', host).info(context,
                                            'snapshot.%s' % event_suffix,
                                            usage_info)


def _usage_from_capacity(capacity, **extra_usage_info):

    capacity_info = {
        'name_to_id': capacity['name_to_id'],
        'total': capacity['total'],
        'free': capacity['free'],
        'allocated': capacity['allocated'],
        'provisioned': capacity['provisioned'],
        'virtual_free': capacity['virtual_free'],
        'reported_at': capacity['reported_at']
    }

    capacity_info.update(extra_usage_info)
    return capacity_info


@utils.if_notifications_enabled
def notify_about_capacity_usage(context, capacity, suffix,
                                extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_capacity(capacity, **extra_usage_info)

    rpc.get_notifier('capacity', host).info(context,
                                            'capacity.%s' % suffix,
                                            usage_info)


@utils.if_notifications_enabled
def notify_about_replication_usage(context, volume, suffix,
                                   extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(context, volume,
                                    **extra_usage_info)

    rpc.get_notifier('replication', host).info(context,
                                               'replication.%s' % suffix,
                                               usage_info)


@utils.if_notifications_enabled
def notify_about_replication_error(context, volume, suffix,
                                   extra_error_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_error_info:
        extra_error_info = {}

    usage_info = _usage_from_volume(context, volume,
                                    **extra_error_info)

    rpc.get_notifier('replication', host).error(context,
                                                'replication.%s' % suffix,
                                                usage_info)


def _usage_from_consistencygroup(group_ref, **kw):
    usage_info = dict(tenant_id=group_ref.project_id,
                      user_id=group_ref.user_id,
                      availability_zone=group_ref.availability_zone,
                      consistencygroup_id=group_ref.id,
                      name=group_ref.name,
                      created_at=group_ref.created_at.isoformat(),
                      status=group_ref.status)

    usage_info.update(kw)
    return usage_info


@utils.if_notifications_enabled
def notify_about_consistencygroup_usage(context, group, event_suffix,
                                        extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_consistencygroup(group,
                                              **extra_usage_info)

    rpc.get_notifier("consistencygroup", host).info(
        context,
        'consistencygroup.%s' % event_suffix,
        usage_info)


def _usage_from_group(group_ref, **kw):
    usage_info = dict(tenant_id=group_ref.project_id,
                      user_id=group_ref.user_id,
                      availability_zone=group_ref.availability_zone,
                      group_id=group_ref.id,
                      group_type=group_ref.group_type_id,
                      name=group_ref.name,
                      created_at=group_ref.created_at.isoformat(),
                      status=group_ref.status)

    usage_info.update(kw)
    return usage_info


@utils.if_notifications_enabled
def notify_about_group_usage(context, group, event_suffix,
                             extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_group(group,
                                   **extra_usage_info)

    rpc.get_notifier("group", host).info(
        context,
        'group.%s' % event_suffix,
        usage_info)


def _usage_from_cgsnapshot(cgsnapshot, **kw):
    usage_info = dict(
        tenant_id=cgsnapshot.project_id,
        user_id=cgsnapshot.user_id,
        cgsnapshot_id=cgsnapshot.id,
        name=cgsnapshot.name,
        consistencygroup_id=cgsnapshot.consistencygroup_id,
        created_at=cgsnapshot.created_at.isoformat(),
        status=cgsnapshot.status)

    usage_info.update(kw)
    return usage_info


def _usage_from_group_snapshot(group_snapshot, **kw):
    usage_info = dict(
        tenant_id=group_snapshot.project_id,
        user_id=group_snapshot.user_id,
        group_snapshot_id=group_snapshot.id,
        name=group_snapshot.name,
        group_id=group_snapshot.group_id,
        group_type=group_snapshot.group_type_id,
        created_at=group_snapshot.created_at.isoformat(),
        status=group_snapshot.status)

    usage_info.update(kw)
    return usage_info


@utils.if_notifications_enabled
def notify_about_cgsnapshot_usage(context, cgsnapshot, event_suffix,
                                  extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_cgsnapshot(cgsnapshot,
                                        **extra_usage_info)

    rpc.get_notifier("cgsnapshot", host).info(
        context,
        'cgsnapshot.%s' % event_suffix,
        usage_info)


@utils.if_notifications_enabled
def notify_about_group_snapshot_usage(context, group_snapshot, event_suffix,
                                      extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_group_snapshot(group_snapshot,
                                            **extra_usage_info)

    rpc.get_notifier("group_snapshot", host).info(
        context,
        'group_snapshot.%s' % event_suffix,
        usage_info)


def _check_blocksize(blocksize):

    # Check if volume_dd_blocksize is valid
    try:
        # Rule out zero-sized/negative/float dd blocksize which
        # cannot be caught by strutils
        if blocksize.startswith(('-', '0')) or '.' in blocksize:
            raise ValueError
        strutils.string_to_bytes('%sB' % blocksize)
    except ValueError:
        LOG.warning("Incorrect value error: %(blocksize)s, "
                    "it may indicate that \'volume_dd_blocksize\' "
                    "was configured incorrectly. Fall back to default.",
                    {'blocksize': blocksize})
        # Fall back to default blocksize
        CONF.clear_override('volume_dd_blocksize')
        blocksize = CONF.volume_dd_blocksize

    return blocksize


def check_for_odirect_support(src, dest, flag='oflag=direct'):

    # Check whether O_DIRECT is supported
    try:
        # iflag=direct and if=/dev/zero combination does not work
        # error: dd: failed to open '/dev/zero': Invalid argument
        if (src == '/dev/zero' and flag == 'iflag=direct'):
            return False
        else:
            utils.execute('dd', 'count=0', 'if=%s' % src,
                          'of=%s' % dest,
                          flag, run_as_root=True)
            return True
    except processutils.ProcessExecutionError:
        return False


def _copy_volume_with_path(prefix, srcstr, deststr, size_in_m, blocksize,
                           sync=False, execute=utils.execute, ionice=None,
                           sparse=False):
    cmd = prefix[:]

    if ionice:
        cmd.extend(('ionice', ionice))

    blocksize = _check_blocksize(blocksize)
    size_in_bytes = size_in_m * units.Mi

    cmd.extend(('dd', 'if=%s' % srcstr, 'of=%s' % deststr,
                'count=%d' % size_in_bytes, 'bs=%s' % blocksize))

    # Use O_DIRECT to avoid thrashing the system buffer cache
    odirect = check_for_odirect_support(srcstr, deststr, 'iflag=direct')

    cmd.append('iflag=count_bytes,direct' if odirect else 'iflag=count_bytes')

    if check_for_odirect_support(srcstr, deststr, 'oflag=direct'):
        cmd.append('oflag=direct')
        odirect = True

    # If the volume is being unprovisioned then
    # request the data is persisted before returning,
    # so that it's not discarded from the cache.
    conv = []
    if sync and not odirect:
        conv.append('fdatasync')
    if sparse:
        conv.append('sparse')
    if conv:
        conv_options = 'conv=' + ",".join(conv)
        cmd.append(conv_options)

    # Perform the copy
    start_time = timeutils.utcnow()
    execute(*cmd, run_as_root=True)
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    mbps = (size_in_m / duration)
    LOG.debug("Volume copy details: src %(src)s, dest %(dest)s, "
              "size %(sz).2f MB, duration %(duration).2f sec",
              {"src": srcstr,
               "dest": deststr,
               "sz": size_in_m,
               "duration": duration})
    LOG.info("Volume copy %(size_in_m).2f MB at %(mbps).2f MB/s",
             {'size_in_m': size_in_m, 'mbps': mbps})


def _open_volume_with_path(path, mode):
    try:
        with utils.temporary_chown(path):
            handle = open(path, mode)
            return handle
    except Exception:
        LOG.error("Failed to open volume from %(path)s.", {'path': path})


def _transfer_data(src, dest, length, chunk_size):
    """Transfer data between files (Python IO objects)."""

    chunks = int(math.ceil(length / chunk_size))
    remaining_length = length

    LOG.debug("%(chunks)s chunks of %(bytes)s bytes to be transferred.",
              {'chunks': chunks, 'bytes': chunk_size})

    for chunk in range(0, chunks):
        before = time.time()
        data = tpool.execute(src.read, min(chunk_size, remaining_length))

        # If we have reached end of source, discard any extraneous bytes from
        # destination volume if trim is enabled and stop writing.
        if data == b'':
            break

        tpool.execute(dest.write, data)
        remaining_length -= len(data)
        delta = (time.time() - before)
        rate = (chunk_size / delta) / units.Ki
        LOG.debug("Transferred chunk %(chunk)s of %(chunks)s (%(rate)dK/s).",
                  {'chunk': chunk + 1, 'chunks': chunks, 'rate': rate})

        # yield to any other pending operations
        eventlet.sleep(0)

    tpool.execute(dest.flush)


def _copy_volume_with_file(src, dest, size_in_m):
    src_handle = src
    if isinstance(src, six.string_types):
        src_handle = _open_volume_with_path(src, 'rb')

    dest_handle = dest
    if isinstance(dest, six.string_types):
        dest_handle = _open_volume_with_path(dest, 'wb')

    if not src_handle:
        raise exception.DeviceUnavailable(
            _("Failed to copy volume, source device unavailable."))

    if not dest_handle:
        raise exception.DeviceUnavailable(
            _("Failed to copy volume, destination device unavailable."))

    start_time = timeutils.utcnow()

    _transfer_data(src_handle, dest_handle, size_in_m * units.Mi, units.Mi * 4)

    duration = max(1, timeutils.delta_seconds(start_time, timeutils.utcnow()))

    if isinstance(src, six.string_types):
        src_handle.close()
    if isinstance(dest, six.string_types):
        dest_handle.close()

    mbps = (size_in_m / duration)
    LOG.info("Volume copy completed (%(size_in_m).2f MB at "
             "%(mbps).2f MB/s).",
             {'size_in_m': size_in_m, 'mbps': mbps})


def copy_volume(src, dest, size_in_m, blocksize, sync=False,
                execute=utils.execute, ionice=None, throttle=None,
                sparse=False):
    """Copy data from the source volume to the destination volume.

    The parameters 'src' and 'dest' are both typically of type str, which
    represents the path to each volume on the filesystem.  Connectors can
    optionally return a volume handle of type RawIOBase for volumes that are
    not available on the local filesystem for open/close operations.

    If either 'src' or 'dest' are not of type str, then they are assumed to be
    of type RawIOBase or any derivative that supports file operations such as
    read and write.  In this case, the handles are treated as file handles
    instead of file paths and, at present moment, throttling is unavailable.
    """

    if (isinstance(src, six.string_types) and
            isinstance(dest, six.string_types)):
        if not throttle:
            throttle = throttling.Throttle.get_default()
        with throttle.subcommand(src, dest) as throttle_cmd:
            _copy_volume_with_path(throttle_cmd['prefix'], src, dest,
                                   size_in_m, blocksize, sync=sync,
                                   execute=execute, ionice=ionice,
                                   sparse=sparse)
    else:
        _copy_volume_with_file(src, dest, size_in_m)


def clear_volume(volume_size, volume_path, volume_clear=None,
                 volume_clear_size=None, volume_clear_ionice=None,
                 throttle=None):
    """Unprovision old volumes to prevent data leaking between users."""
    if volume_clear is None:
        volume_clear = CONF.volume_clear

    if volume_clear_size is None:
        volume_clear_size = CONF.volume_clear_size

    if volume_clear_size == 0:
        volume_clear_size = volume_size

    if volume_clear_ionice is None:
        volume_clear_ionice = CONF.volume_clear_ionice

    LOG.info("Performing secure delete on volume: %s", volume_path)

    # We pass sparse=False explicitly here so that zero blocks are not
    # skipped in order to clear the volume.
    if volume_clear == 'zero':
        return copy_volume('/dev/zero', volume_path, volume_clear_size,
                           CONF.volume_dd_blocksize,
                           sync=True, execute=utils.execute,
                           ionice=volume_clear_ionice,
                           throttle=throttle, sparse=False)
    else:
        raise exception.InvalidConfigurationValue(
            option='volume_clear',
            value=volume_clear)


def supports_thin_provisioning():
    return brick_lvm.LVM.supports_thin_provisioning(
        utils.get_root_helper())


def get_all_physical_volumes(vg_name=None):
    return brick_lvm.LVM.get_all_physical_volumes(
        utils.get_root_helper(),
        vg_name)


def get_all_volume_groups(vg_name=None):
    return brick_lvm.LVM.get_all_volume_groups(
        utils.get_root_helper(),
        vg_name)

# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0,1
                            'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                            'abcdefghijkmnopqrstuvwxyz')  # Removed: l


def generate_password(length=16, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbol groups.

    At least one symbol from each group will be included. Unpredictable
    results if length is less than the number of symbol groups.

    Believed to be reasonably secure (with a reasonable password length!)

    """
    # NOTE(jerdfelt): Some password policies require at least one character
    # from each group of symbols, so start off with one random character
    # from each symbol group

    bytes = 1  # Number of random bytes to generate for each choice

    password = [s[ord(urandom(bytes)) % len(s)]
                for s in symbolgroups]
    # If length < len(symbolgroups), the leading characters will only
    # be from the first length groups. Try our best to not be predictable
    # by shuffling and then truncating.
    shuffle(password)
    password = password[:length]
    length -= len(password)

    # then fill with random characters from all symbol groups
    symbols = ''.join(symbolgroups)
    password.extend(
        [symbols[ord(urandom(bytes)) % len(symbols)]
            for _i in range(length)])

    # finally shuffle to ensure first x characters aren't from a
    # predictable group
    shuffle(password)

    return ''.join(password)


def generate_username(length=20, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    # Use the same implementation as the password generation.
    return generate_password(length, symbolgroups)


DEFAULT_POOL_NAME = '_pool0'


def extract_host(host, level='backend', default_pool_name=False):
    """Extract Host, Backend or Pool information from host string.

    :param host: String for host, which could include host@backend#pool info
    :param level: Indicate which level of information should be extracted
                  from host string. Level can be 'host', 'backend' or 'pool',
                  default value is 'backend'
    :param default_pool_name: this flag specify what to do if level == 'pool'
                              and there is no 'pool' info encoded in host
                              string.  default_pool_name=True will return
                              DEFAULT_POOL_NAME, otherwise we return None.
                              Default value of this parameter is False.
    :return: expected information, string or None
    :raises: exception.InvalidVolume

    For example:
        host = 'HostA@BackendB#PoolC'
        ret = extract_host(host, 'host')
        # ret is 'HostA'
        ret = extract_host(host, 'backend')
        # ret is 'HostA@BackendB'
        ret = extract_host(host, 'pool')
        # ret is 'PoolC'

        host = 'HostX@BackendY'
        ret = extract_host(host, 'pool')
        # ret is None
        ret = extract_host(host, 'pool', True)
        # ret is '_pool0'
    """

    if host is None:
        msg = _("volume is not assigned to a host")
        raise exception.InvalidVolume(reason=msg)

    if level == 'host':
        # make sure pool is not included
        hst = host.split('#')[0]
        return hst.split('@')[0]
    elif level == 'backend':
        return host.split('#')[0]
    elif level == 'pool':
        lst = host.split('#')
        if len(lst) == 2:
            return lst[1]
        elif default_pool_name is True:
            return DEFAULT_POOL_NAME
        else:
            return None


def append_host(host, pool):
    """Encode pool into host info."""
    if not host or not pool:
        return host

    new_host = "#".join([host, pool])
    return new_host


def matching_backend_name(src_volume_type, volume_type):
    if src_volume_type.get('volume_backend_name') and \
            volume_type.get('volume_backend_name'):
        return src_volume_type.get('volume_backend_name') == \
            volume_type.get('volume_backend_name')
    else:
        return False


def hosts_are_equivalent(host_1, host_2):
    # In case host_1 or host_2 are None
    if not (host_1 and host_2):
        return host_1 == host_2
    return extract_host(host_1) == extract_host(host_2)


def read_proc_mounts():
    """Read the /proc/mounts file.

    It's a dummy function but it eases the writing of unit tests as mocking
    __builtin__open() for a specific file only is not trivial.
    """
    with open('/proc/mounts') as mounts:
        return mounts.readlines()


def extract_id_from_volume_name(vol_name):
    regex = re.compile(
        CONF.volume_name_template.replace('%s', '(?P<uuid>.+)'))
    match = regex.match(vol_name)
    return match.group('uuid') if match else None


def check_already_managed_volume(vol_id):
    """Check cinder db for already managed volume.

    :param vol_id: volume id parameter
    :returns: bool -- return True, if db entry with specified
                      volume id exists, otherwise return False
    """
    try:
        return (vol_id and isinstance(vol_id, six.string_types) and
                uuid.UUID(vol_id, version=4) and
                objects.Volume.exists(context.get_admin_context(), vol_id))
    except ValueError:
        return False


def extract_id_from_snapshot_name(snap_name):
    """Return a snapshot's ID from its name on the backend."""
    regex = re.compile(
        CONF.snapshot_name_template.replace('%s', '(?P<uuid>.+)'))
    match = regex.match(snap_name)
    return match.group('uuid') if match else None


def paginate_entries_list(entries, marker, limit, offset, sort_keys,
                          sort_dirs):
    """Paginate a list of entries.

    :param entries: list of dictionaries
    :marker: The last element previously returned
    :limit: The maximum number of items to return
    :offset: The number of items to skip from the marker or from the first
             element.
    :sort_keys: A list of keys in the dictionaries to sort by
    :sort_dirs: A list of sort directions, where each is either 'asc' or 'dec'
    """
    comparers = [(operator.itemgetter(key.strip()), multiplier)
                 for (key, multiplier) in zip(sort_keys, sort_dirs)]

    def comparer(left, right):
        for fn, d in comparers:
            left_val = fn(left)
            right_val = fn(right)
            if isinstance(left_val, dict):
                left_val = sorted(left_val.values())[0]
            if isinstance(right_val, dict):
                right_val = sorted(right_val.values())[0]
            if left_val == right_val:
                continue
            if d == 'asc':
                return -1 if left_val < right_val else 1
            else:
                return -1 if left_val > right_val else 1
        else:
            return 0
    sorted_entries = sorted(entries, key=functools.cmp_to_key(comparer))

    start_index = 0
    if offset is None:
        offset = 0
    if marker:
        if not isinstance(marker, dict):
            try:
                marker = json.loads(marker)
            except ValueError:
                msg = _('marker %s can not be analysed, please use json like '
                        'format') % marker
                raise exception.InvalidInput(reason=msg)
        start_index = -1
        for i, entry in enumerate(sorted_entries):
            if entry['reference'] == marker:
                start_index = i + 1
                break
        if start_index < 0:
            msg = _('marker not found: %s') % marker
            raise exception.InvalidInput(reason=msg)
    range_end = start_index + limit
    return sorted_entries[start_index + offset:range_end + offset]


def convert_config_string_to_dict(config_string):
    """Convert config file replication string to a dict.

    The only supported form is as follows:
    "{'key-1'='val-1' 'key-2'='val-2'...}"

    :param config_string: Properly formatted string to convert to dict.
    :response: dict of string values
    """

    resultant_dict = {}

    try:
        st = config_string.replace("=", ":")
        st = st.replace(" ", ", ")
        resultant_dict = ast.literal_eval(st)
    except Exception:
        LOG.warning("Error encountered translating config_string: "
                    "%(config_string)s to dict",
                    {'config_string': config_string})

    return resultant_dict


def create_encryption_key(context, key_manager, volume_type_id):
    encryption_key_id = None
    if volume_types.is_encrypted(context, volume_type_id):
        volume_type_encryption = (
            volume_types.get_volume_type_encryption(context,
                                                    volume_type_id))
        cipher = volume_type_encryption.cipher
        length = volume_type_encryption.key_size
        algorithm = cipher.split('-')[0] if cipher else None
        encryption_key_id = key_manager.create_key(
            context,
            algorithm=algorithm,
            length=length)
    return encryption_key_id


def is_replicated_str(str):
    spec = (str or '').split()
    return (len(spec) == 2 and
            spec[0] == '<is>' and strutils.bool_from_string(spec[1]))


def is_replicated_spec(extra_specs):
    return (extra_specs and
            is_replicated_str(extra_specs.get('replication_enabled')))


def group_get_by_id(group_id):
    ctxt = context.get_admin_context()
    group = db.group_get(ctxt, group_id)
    return group


def is_group_a_cg_snapshot_type(group_or_snap):
    LOG.debug("Checking if %s is a consistent snapshot group",
              group_or_snap)
    if group_or_snap["group_type_id"] is not None:
        spec = group_types.get_group_type_specs(
            group_or_snap["group_type_id"],
            key="consistent_group_snapshot_enabled"
        )
        return spec == "<is> True"
    return False


def is_group_a_type(group, key):
    if group.group_type_id is not None:
        spec = group_types.get_group_type_specs(
            group.group_type_id, key=key
        )
        return spec == "<is> True"
    return False
