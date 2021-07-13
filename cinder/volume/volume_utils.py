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

import abc
import ast
import functools
import inspect
import json
import logging as py_logging
import math
import operator
import os
from os import urandom
from random import shuffle
import re
import socket
import tempfile
import time
import types
import typing
from typing import Any, BinaryIO, Callable, Dict, IO  # noqa: H301
from typing import List, Optional, Tuple, Union  # noqa: H301
import uuid

from castellan.common.credentials import keystone_password
from castellan.common import exception as castellan_exception
from castellan import key_manager as castellan_key_manager
import eventlet
from eventlet import tpool
from keystoneauth1 import loading as ks_loading
from os_brick import encryptors
from os_brick.initiator import connector
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
from cinder import rpc
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import group_types
from cinder.volume import throttling
from cinder.volume import volume_types

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

GB: int = units.Gi
# These attributes we will attempt to save for the volume if they exist
# in the source image metadata.
IMAGE_ATTRIBUTES = (
    'checksum',
    'container_format',
    'disk_format',
    'min_disk',
    'min_ram',
    'size',
)
VALID_TRACE_FLAGS = {'method', 'api'}
TRACE_API = False
TRACE_METHOD = False


def null_safe_str(s: Optional[str]) -> str:
    return str(s) if s else ''


def _usage_from_volume(context: context.RequestContext,
                       volume_ref: 'objects.Volume',
                       **kw) -> dict:
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


def _usage_from_backup(backup: 'objects.Backup', **kw) -> dict:
    num_dependent_backups = backup.num_dependent_backups
    usage_info = dict(tenant_id=backup.project_id,
                      user_id=backup.user_id,
                      availability_zone=backup.availability_zone,
                      backup_id=backup.id,
                      host=backup.host,
                      display_name=backup.display_name,
                      created_at=backup.created_at.isoformat(),
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
def notify_about_volume_usage(context: context.RequestContext,
                              volume: 'objects.Volume',
                              event_suffix: str,
                              extra_usage_info: dict = None,
                              host: str = None) -> None:
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(context, volume, **extra_usage_info)

    rpc.get_notifier("volume", host).info(context, 'volume.%s' % event_suffix,
                                          usage_info)


@utils.if_notifications_enabled
def notify_about_backup_usage(context: context.RequestContext,
                              backup: 'objects.Backup',
                              event_suffix: str,
                              extra_usage_info: dict = None,
                              host: str = None) -> None:
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_backup(backup, **extra_usage_info)

    rpc.get_notifier("backup", host).info(context, 'backup.%s' % event_suffix,
                                          usage_info)


def _usage_from_snapshot(snapshot: 'objects.Snapshot',
                         context: context.RequestContext,
                         **extra_usage_info) -> dict:
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
        'created_at': snapshot.created_at.isoformat(),
        'status': snapshot.status,
        'deleted': null_safe_str(snapshot.deleted),
        'metadata': null_safe_str(snapshot.metadata),
    }

    usage_info.update(extra_usage_info)
    return usage_info


@utils.if_notifications_enabled
def notify_about_snapshot_usage(context: context.RequestContext,
                                snapshot: 'objects.Snapshot',
                                event_suffix: str,
                                extra_usage_info: dict = None,
                                host: str = None) -> None:
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_snapshot(snapshot, context, **extra_usage_info)

    rpc.get_notifier('snapshot', host).info(context,
                                            'snapshot.%s' % event_suffix,
                                            usage_info)


def _usage_from_capacity(capacity: Dict[str, Any],
                         **extra_usage_info) -> Dict[str, Any]:

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
def notify_about_capacity_usage(context: context.RequestContext,
                                capacity: dict,
                                suffix: str,
                                extra_usage_info: dict = None,
                                host: str = None) -> None:
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_capacity(capacity, **extra_usage_info)

    rpc.get_notifier('capacity', host).info(context,
                                            'capacity.%s' % suffix,
                                            usage_info)


@utils.if_notifications_enabled
def notify_about_replication_usage(context: context.RequestContext,
                                   volume: 'objects.Volume',
                                   suffix: str,
                                   extra_usage_info: dict = None,
                                   host: str = None) -> None:
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
def notify_about_replication_error(context: context.RequestContext,
                                   volume: 'objects.Volume',
                                   suffix: str,
                                   extra_error_info: dict = None,
                                   host: str = None) -> None:
    if not host:
        host = CONF.host

    if not extra_error_info:
        extra_error_info = {}

    usage_info = _usage_from_volume(context, volume,
                                    **extra_error_info)

    rpc.get_notifier('replication', host).error(context,
                                                'replication.%s' % suffix,
                                                usage_info)


def _usage_from_consistencygroup(group_ref: 'objects.Group', **kw) -> dict:
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
def notify_about_consistencygroup_usage(context: context.RequestContext,
                                        group: 'objects.Group',
                                        event_suffix: str,
                                        extra_usage_info: dict = None,
                                        host: str = None) -> None:
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


def _usage_from_group(group_ref: 'objects.Group', **kw) -> dict:
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
def notify_about_group_usage(context: context.RequestContext,
                             group: 'objects.Group',
                             event_suffix: str,
                             extra_usage_info: dict = None,
                             host: str = None) -> None:
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


def _usage_from_cgsnapshot(cgsnapshot: 'objects.CGSnapshot', **kw) -> dict:
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


def _usage_from_group_snapshot(group_snapshot: 'objects.GroupSnapshot',
                               **kw) -> dict:
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
def notify_about_cgsnapshot_usage(context: context.RequestContext,
                                  cgsnapshot: 'objects.CGSnapshot',
                                  event_suffix: str,
                                  extra_usage_info: dict = None,
                                  host: str = None) -> None:
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
def notify_about_group_snapshot_usage(context: context.RequestContext,
                                      group_snapshot: 'objects.GroupSnapshot',
                                      event_suffix: str,
                                      extra_usage_info=None,
                                      host: str = None) -> None:
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


def _check_blocksize(blocksize: Union[str, int]) -> Union[str, int]:

    # Check if volume_dd_blocksize is valid
    try:
        # Rule out zero-sized/negative/float dd blocksize which
        # cannot be caught by strutils
        if (blocksize.startswith(('-', '0')) or  # type: ignore
                '.' in blocksize):  # type: ignore
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


def check_for_odirect_support(src: str, dest: str,
                              flag: str = 'oflag=direct') -> bool:

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


def _copy_volume_with_path(prefix, srcstr: str, deststr: str,
                           size_in_m: int, blocksize: Union[str, int],
                           sync: bool = False,
                           execute: Callable = utils.execute,
                           ionice=None,
                           sparse: bool = False) -> None:
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


def _open_volume_with_path(path: str, mode: str) -> IO[Any]:
    try:
        with utils.temporary_chown(path):
            handle = open(path, mode)
            return handle
    except Exception:
        LOG.error("Failed to open volume from %(path)s.", {'path': path})
        raise


def _transfer_data(src: IO, dest: IO,
                   length: int, chunk_size: int) -> None:
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


def _copy_volume_with_file(src: Union[str, IO],
                           dest: Union[str, IO],
                           size_in_m: int) -> None:
    src_handle = src
    if isinstance(src, str):
        src_handle = _open_volume_with_path(src, 'rb')

    src_handle = typing.cast(IO, src_handle)

    dest_handle = dest
    if isinstance(dest, str):
        dest_handle = _open_volume_with_path(dest, 'wb')

    dest_handle = typing.cast(IO, dest_handle)

    if not src_handle:
        raise exception.DeviceUnavailable(
            _("Failed to copy volume, source device unavailable."))

    if not dest_handle:
        raise exception.DeviceUnavailable(
            _("Failed to copy volume, destination device unavailable."))

    start_time = timeutils.utcnow()

    _transfer_data(src_handle, dest_handle, size_in_m * units.Mi, units.Mi * 4)

    duration = max(1, timeutils.delta_seconds(start_time, timeutils.utcnow()))

    if isinstance(src, str):
        src_handle.close()
    if isinstance(dest, str):
        dest_handle.close()

    mbps = (size_in_m / duration)
    LOG.info("Volume copy completed (%(size_in_m).2f MB at "
             "%(mbps).2f MB/s).",
             {'size_in_m': size_in_m, 'mbps': mbps})


def copy_volume(src: Union[str, BinaryIO],
                dest: Union[str, BinaryIO],
                size_in_m: int,
                blocksize: Union[str, int], sync=False,
                execute=utils.execute, ionice=None, throttle=None,
                sparse=False) -> None:
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

    if (isinstance(src, str) and
            isinstance(dest, str)):
        if not throttle:
            throttle = throttling.Throttle.get_default()
        with throttle.subcommand(src, dest) as throttle_cmd:
            _copy_volume_with_path(throttle_cmd['prefix'], src, dest,
                                   size_in_m, blocksize, sync=sync,
                                   execute=execute, ionice=ionice,
                                   sparse=sparse)
    else:
        _copy_volume_with_file(src, dest, size_in_m)


def clear_volume(volume_size: int,
                 volume_path: str,
                 volume_clear: str = None,
                 volume_clear_size: int = None,
                 volume_clear_ionice: str = None,
                 throttle=None) -> None:
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


def supports_thin_provisioning() -> bool:
    return brick_lvm.LVM.supports_thin_provisioning(
        utils.get_root_helper())


def get_all_physical_volumes(vg_name=None) -> list:
    return brick_lvm.LVM.get_all_physical_volumes(
        utils.get_root_helper(),
        vg_name)


def get_all_volume_groups(vg_name=None) -> list:
    return brick_lvm.LVM.get_all_volume_groups(
        utils.get_root_helper(),
        vg_name)


def extract_availability_zones_from_volume_type(
        volume_type: Union['objects.VolumeType', dict]) \
        -> Optional[List[str]]:
    if not volume_type:
        return None
    extra_specs = volume_type.get('extra_specs', {})
    if 'RESKEY:availability_zones' not in extra_specs:
        return None
    azs = extra_specs.get('RESKEY:availability_zones', '').split(',')
    return [az.strip() for az in azs if az != '']


# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0,1
                            'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                            'abcdefghijkmnopqrstuvwxyz')  # Removed: l


def generate_password(
        length: int = 16,
        symbolgroups: Tuple[str, ...] = DEFAULT_PASSWORD_SYMBOLS) -> str:
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


def generate_username(
        length: int = 20,
        symbolgroups: Tuple[str, ...] = DEFAULT_PASSWORD_SYMBOLS) -> str:
    # Use the same implementation as the password generation.
    return generate_password(length, symbolgroups)


DEFAULT_POOL_NAME = '_pool0'


def extract_host(host: Optional[str],
                 level: str = 'backend',
                 default_pool_name: bool = False) -> Optional[str]:
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

    return None  # not hit


def append_host(host: Optional[str],
                pool: Optional[str]) -> Optional[str]:
    """Encode pool into host info."""
    if not host or not pool:
        return host

    new_host = "#".join([host, pool])
    return new_host


def matching_backend_name(src_volume_type, volume_type) -> bool:
    if src_volume_type.get('volume_backend_name') and \
            volume_type.get('volume_backend_name'):
        return src_volume_type.get('volume_backend_name') == \
            volume_type.get('volume_backend_name')
    else:
        return False


def hosts_are_equivalent(host_1: str, host_2: str) -> bool:
    # In case host_1 or host_2 are None
    if not (host_1 and host_2):
        return host_1 == host_2
    return extract_host(host_1) == extract_host(host_2)


def read_proc_mounts() -> List[str]:
    """Read the /proc/mounts file.

    It's a dummy function but it eases the writing of unit tests as mocking
    __builtin__open() for a specific file only is not trivial.
    """
    with open('/proc/mounts') as mounts:
        return mounts.readlines()


def extract_id_from_volume_name(vol_name: str) -> Optional[str]:
    regex: typing.Pattern = re.compile(
        CONF.volume_name_template.replace('%s', r'(?P<uuid>.+)'))
    match = regex.match(vol_name)
    return match.group('uuid') if match else None


def check_already_managed_volume(vol_id: Optional[str]):
    """Check cinder db for already managed volume.

    :param vol_id: volume id parameter
    :returns: bool -- return True, if db entry with specified
                      volume id exists, otherwise return False
    :raises: ValueError if vol_id is not a valid uuid string
    """
    try:
        return (vol_id and isinstance(vol_id, str) and
                uuid.UUID(vol_id, version=4) and
                objects.Volume.exists(context.get_admin_context(), vol_id))
    except ValueError:
        return False


def extract_id_from_snapshot_name(snap_name: str) -> Optional[str]:
    """Return a snapshot's ID from its name on the backend."""
    regex = re.compile(
        CONF.snapshot_name_template.replace('%s', r'(?P<uuid>.+)'))
    match = regex.match(snap_name)
    return match.group('uuid') if match else None


def paginate_entries_list(entries: List[Dict],
                          marker: Optional[Union[dict, str]],
                          limit: int,
                          offset: Optional[int],
                          sort_keys: List[str],
                          sort_dirs: List[str]) -> list:
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

    def comparer(left, right) -> int:
        fn: Callable
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


def convert_config_string_to_dict(config_string: str) -> dict:
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


def create_encryption_key(context: context.RequestContext,
                          key_manager,
                          volume_type_id: str) -> Optional[str]:
    encryption_key_id = None
    if volume_types.is_encrypted(context, volume_type_id):
        volume_type_encryption: db.sqlalchemy.models.Encryption = (
            volume_types.get_volume_type_encryption(context,
                                                    volume_type_id))
        if volume_type_encryption is None:
            raise exception.Invalid(message="Volume type error")
        cipher = volume_type_encryption.cipher
        length = volume_type_encryption.key_size
        algorithm = cipher.split('-')[0] if cipher else None
        if algorithm is None:
            raise exception.InvalidVolumeType(
                message="Invalid encryption spec")
        try:
            encryption_key_id = key_manager.create_key(
                context,
                algorithm=algorithm,
                length=length)
        except castellan_exception.KeyManagerError:
            # The messaging back to the client here is
            # purposefully terse, so we don't leak any sensitive
            # details.
            LOG.exception("Key manager error")
            raise exception.Invalid(message="Key manager error")

    typing.cast(str, encryption_key_id)

    return encryption_key_id


def delete_encryption_key(context: context.RequestContext,
                          key_manager,
                          encryption_key_id: str) -> None:
    try:
        key_manager.delete(context, encryption_key_id)
    except castellan_exception.ManagedObjectNotFoundError:
        pass
    except castellan_exception.KeyManagerError:
        LOG.info("First attempt to delete key id %s failed, retrying with "
                 "cinder's service context.", encryption_key_id)
        conf = CONF
        ks_loading.register_auth_conf_options(conf, 'keystone_authtoken')
        service_context = keystone_password.KeystonePassword(
            password=conf.keystone_authtoken.password,
            auth_url=conf.keystone_authtoken.auth_url,
            username=conf.keystone_authtoken.username,
            user_domain_name=conf.keystone_authtoken.user_domain_name,
            project_name=conf.keystone_authtoken.project_name,
            project_domain_name=conf.keystone_authtoken.project_domain_name)
        try:
            castellan_key_manager.API(conf).delete(service_context,
                                                   encryption_key_id)
        except castellan_exception.ManagedObjectNotFoundError:
            pass


def clone_encryption_key(context: context.RequestContext,
                         key_manager,
                         encryption_key_id: str) -> str:
    clone_key_id = None
    if encryption_key_id is not None:
        clone_key_id = key_manager.store(
            context,
            key_manager.get(context, encryption_key_id))
    return clone_key_id


def is_boolean_str(str: Optional[str]) -> bool:
    spec = (str or '').split()
    return (len(spec) == 2 and
            spec[0] == '<is>' and strutils.bool_from_string(spec[1]))


def is_replicated_spec(extra_specs: dict) -> bool:
    return (bool(extra_specs) and
            is_boolean_str(extra_specs.get('replication_enabled')))


def is_multiattach_spec(extra_specs: dict) -> bool:
    return (bool(extra_specs) and
            is_boolean_str(extra_specs.get('multiattach')))


def group_get_by_id(group_id):
    ctxt = context.get_admin_context()
    group = db.group_get(ctxt, group_id)
    return group


def is_group_a_cg_snapshot_type(group_or_snap) -> bool:
    LOG.debug("Checking if %s is a consistent snapshot group",
              group_or_snap)
    if group_or_snap["group_type_id"] is not None:
        spec = group_types.get_group_type_specs(
            group_or_snap["group_type_id"],
            key="consistent_group_snapshot_enabled"
        )
        return spec == "<is> True"
    return False


def is_group_a_type(group: 'objects.Group', key: str) -> bool:
    if group.group_type_id is not None:
        spec = group_types.get_group_type_specs(
            group.group_type_id, key=key
        )
        return spec == "<is> True"
    return False


def get_max_over_subscription_ratio(
        str_value: Union[str, float],
        supports_auto: bool = False) -> Union[str, float]:
    """Get the max_over_subscription_ratio from a string

    As some drivers need to do some calculations with the value and we are now
    receiving a string value in the conf, this converts the value to float
    when appropriate.

    :param str_value: Configuration object
    :param supports_auto: Tell if the calling driver supports auto MOSR.
    :response: value of mosr
    """

    if not supports_auto and str_value == "auto":
        msg = _("This driver does not support automatic "
                "max_over_subscription_ratio calculation. Please use a "
                "valid float value.")
        LOG.error(msg)
        raise exception.VolumeDriverException(message=msg)

    if str_value == 'auto':
        str_value = typing.cast(str, str_value)
        return str_value

    mosr = float(str_value)
    if mosr < 1:
        msg = _("The value of max_over_subscription_ratio must be "
                "greater than 1.")
        LOG.error(msg)
        raise exception.InvalidParameterValue(message=msg)
    return mosr


def check_image_metadata(image_meta: Dict[str, Union[str, int]],
                         vol_size: int) -> None:
    """Validates the image metadata."""
    # Check whether image is active
    if image_meta['status'] != 'active':
        msg = _('Image %(image_id)s is not active.'
                ) % {'image_id': image_meta['id']}
        raise exception.InvalidInput(reason=msg)

    # Check image size is not larger than volume size.
    image_size = utils.as_int(image_meta['size'], quiet=False)
    image_size_in_gb = (image_size + GB - 1) // GB
    if image_size_in_gb > vol_size:
        msg = _('Size of specified image %(image_size)sGB'
                ' is larger than volume size %(volume_size)sGB.')
        msg = msg % {'image_size': image_size_in_gb, 'volume_size': vol_size}
        raise exception.InvalidInput(reason=msg)

    # Check image min_disk requirement is met for the particular volume
    min_disk = image_meta.get('min_disk', 0)
    min_disk = typing.cast(int, min_disk)
    if vol_size < min_disk:
        msg = _('Volume size %(volume_size)sGB cannot be smaller'
                ' than the image minDisk size %(min_disk)sGB.')
        msg = msg % {'volume_size': vol_size, 'min_disk': min_disk}
        raise exception.InvalidInput(reason=msg)


def enable_bootable_flag(volume: 'objects.Volume') -> None:
    try:
        LOG.debug('Marking volume %s as bootable.', volume.id)
        volume.bootable = True
        volume.save()
    except exception.CinderException as ex:
        LOG.exception("Failed updating volume %(volume_id)s bootable "
                      "flag to true", {'volume_id': volume.id})
        raise exception.MetadataUpdateFailure(reason=ex)


def get_volume_image_metadata(image_id: str,
                              image_meta: Dict[str, Any]) -> dict:

    # Save some base attributes into the volume metadata
    base_metadata = {
        'image_id': image_id,
    }
    name = image_meta.get('name', None)
    if name:
        base_metadata['image_name'] = name

    # Save some more attributes into the volume metadata from the image
    # metadata
    for key in IMAGE_ATTRIBUTES:
        if key not in image_meta:
            continue
        value = image_meta.get(key, None)
        if value is not None:
            base_metadata[key] = value

    # Save all the image metadata properties into the volume metadata
    property_metadata = {}
    image_properties = image_meta.get('properties', {})
    image_properties = typing.cast(dict, image_properties)
    for (key, value) in image_properties.items():
        if value is not None:
            property_metadata[key] = value

    volume_metadata = dict(property_metadata)
    volume_metadata.update(base_metadata)
    return volume_metadata


def copy_image_to_volume(driver,
                         context: context.RequestContext,
                         volume: 'objects.Volume',
                         image_meta: dict,
                         image_location: str,
                         image_service) -> None:
    """Downloads Glance image to the specified volume."""
    image_id = image_meta['id']
    LOG.debug("Attempting download of %(image_id)s (%(image_location)s)"
              " to volume %(volume_id)s.",
              {'image_id': image_id, 'volume_id': volume.id,
               'image_location': image_location})
    try:
        image_encryption_key = image_meta.get('cinder_encryption_key_id')

        if volume.encryption_key_id and image_encryption_key:
            # If the image provided an encryption key, we have
            # already cloned it to the volume's key in
            # _get_encryption_key_id, so we can do a direct copy.
            driver.copy_image_to_volume(
                context, volume, image_service, image_id)
        elif volume.encryption_key_id:
            # Creating an encrypted volume from a normal, unencrypted,
            # image.
            driver.copy_image_to_encrypted_volume(
                context, volume, image_service, image_id)
        else:
            driver.copy_image_to_volume(
                context, volume, image_service, image_id)
    except processutils.ProcessExecutionError as ex:
        LOG.exception("Failed to copy image %(image_id)s to volume: "
                      "%(volume_id)s",
                      {'volume_id': volume.id, 'image_id': image_id})
        raise exception.ImageCopyFailure(reason=ex.stderr)
    except (exception.ImageUnacceptable, exception.ImageTooBig):
        with excutils.save_and_reraise_exception():
            LOG.exception("Failed to copy image %(image_id)s to volume: "
                          "%(volume_id)s",
                          {'volume_id': volume.id, 'image_id': image_id})
    except Exception as ex:
        LOG.exception("Failed to copy image %(image_id)s to "
                      "volume: %(volume_id)s",
                      {'volume_id': volume.id, 'image_id': image_id})
        if not isinstance(ex, exception.ImageCopyFailure):
            raise exception.ImageCopyFailure(reason=ex)
        else:
            raise

    LOG.debug("Downloaded image %(image_id)s (%(image_location)s)"
              " to volume %(volume_id)s successfully.",
              {'image_id': image_id, 'volume_id': volume.id,
               'image_location': image_location})


def image_conversion_dir() -> str:
    tmpdir = (CONF.image_conversion_dir or
              tempfile.gettempdir())

    # ensure temporary directory exists
    if not os.path.exists(tmpdir):
        os.makedirs(tmpdir)

    return tmpdir


def check_encryption_provider(
    volume: 'objects.Volume',
    context: context.RequestContext,
) -> dict:
    """Check that this is a LUKS encryption provider.

    :returns: encryption dict
    """

    encryption = db.volume_encryption_metadata_get(context, volume.id)

    if 'provider' not in encryption:
        message = _("Invalid encryption spec.")
        raise exception.VolumeDriverException(message=message)

    provider = encryption['provider']
    if provider in encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP:
        provider = encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP[provider]
        encryption['provider'] = provider
    if provider != encryptors.LUKS:
        message = _("Provider %s not supported.") % provider
        raise exception.VolumeDriverException(message=message)

    if 'cipher' not in encryption or 'key_size' not in encryption:
        msg = _('encryption spec must contain "cipher" and '
                '"key_size"')
        raise exception.VolumeDriverException(message=msg)

    return encryption


def sanitize_host(host: str) -> str:
    """Ensure IPv6 addresses are enclosed in [] for iSCSI portals."""
    if netutils.is_valid_ipv6(host):
        return '[%s]' % host
    return host


def sanitize_hostname(hostname) -> str:
    """Return a hostname which conforms to RFC-952 and RFC-1123 specs."""
    hostname = hostname.encode('latin-1', 'ignore')
    hostname = hostname.decode('latin-1')

    hostname = re.sub(r'[ _]', '-', hostname)
    hostname = re.sub(r'[^\w.-]+', '', hostname)
    hostname = hostname.lower()
    hostname = hostname.strip('.-')

    return hostname


def resolve_hostname(hostname: str) -> str:
    """Resolves host name to IP address.

    Resolves a host name (my.data.point.com) to an IP address (10.12.143.11).
    This routine also works if the data passed in hostname is already an IP.
    In this case, the same IP address will be returned.

    :param hostname:  Host name to resolve.
    :returns:         IP Address for Host name.
    """
    ip = socket.getaddrinfo(hostname, None)[0][4][0]
    LOG.debug('Asked to resolve hostname %(host)s and got IP %(ip)s.',
              {'host': hostname, 'ip': ip})
    return ip


def update_backup_error(backup,
                        err: str,
                        status=fields.BackupStatus.ERROR) -> None:
    backup.status = status
    backup.fail_reason = err
    backup.save()


# TODO (whoami-rajat): Remove this method when oslo.vmware calls volume_utils
#  wrapper of upload_volume instead of image_utils.upload_volume
def get_base_image_ref(volume: 'objects.Volume'):
    # This method fetches the image_id from volume glance metadata and pass
    # it to the driver calling it during upload volume to image operation
    base_image_ref = None
    if volume.glance_metadata:
        base_image_ref = volume.glance_metadata.get('image_id')
    return base_image_ref


def upload_volume(context: context.RequestContext,
                  image_service, image_meta, volume_path,
                  volume: 'objects.Volume',
                  volume_format: str = 'raw',
                  run_as_root: bool = True,
                  compress: bool = True) -> None:
    # retrieve store information from extra-specs
    store_id = volume.volume_type.extra_specs.get('image_service:store_id')

    # This fetches the image_id from volume glance metadata and pass
    # it to the driver calling it during upload volume to image operation
    base_image_ref = None
    if volume.glance_metadata:
        base_image_ref = volume.glance_metadata.get('image_id')
    image_utils.upload_volume(context, image_service, image_meta, volume_path,
                              volume_format=volume_format,
                              run_as_root=run_as_root,
                              compress=compress, store_id=store_id,
                              base_image_ref=base_image_ref)


def get_backend_configuration(backend_name, backend_opts=None):
    """Get a configuration object for a specific backend."""

    config_stanzas = CONF.list_all_sections()
    if backend_name not in config_stanzas:
        msg = _("Could not find backend stanza %(backend_name)s in "
                "configuration. Available stanzas are %(stanzas)s")
        params = {
            "stanzas": config_stanzas,
            "backend_name": backend_name,
        }
        raise exception.ConfigNotFound(message=msg % params)

    config = configuration.Configuration(driver.volume_opts,
                                         config_group=backend_name)

    if backend_opts:
        config.append_config_values(backend_opts)

    return config


def brick_get_connector_properties(multipath: bool = False,
                                   enforce_multipath: bool = False):
    """Wrapper to automatically set root_helper in brick calls.

    :param multipath: A boolean indicating whether the connector can
                      support multipath.
    :param enforce_multipath: If True, it raises exception when multipath=True
                              is specified but multipathd is not running.
                              If False, it falls back to multipath=False
                              when multipathd is not running.
    """

    root_helper = utils.get_root_helper()
    return connector.get_connector_properties(root_helper,
                                              CONF.my_ip,
                                              multipath,
                                              enforce_multipath)


def brick_get_connector(protocol: str,
                        driver=None,
                        use_multipath: bool = False,
                        device_scan_attempts: int = 3,
                        *args, **kwargs):
    """Wrapper to get a brick connector object.

    This automatically populates the required protocol as well
    as the root_helper needed to execute commands.
    """

    root_helper = utils.get_root_helper()
    return connector.InitiatorConnector.factory(protocol, root_helper,
                                                driver=driver,
                                                use_multipath=use_multipath,
                                                device_scan_attempts=
                                                device_scan_attempts,
                                                *args, **kwargs)


def brick_get_encryptor(connection_info: dict, *args, **kwargs):
    """Wrapper to get a brick encryptor object."""

    root_helper = utils.get_root_helper()
    km = castellan_key_manager.API(CONF)
    return encryptors.get_volume_encryptor(root_helper=root_helper,
                                           connection_info=connection_info,
                                           keymgr=km,
                                           *args, **kwargs)


def brick_attach_volume_encryptor(context: context.RequestContext,
                                  attach_info: dict,
                                  encryption: dict) -> None:
    """Attach encryption layer."""
    connection_info = attach_info['conn']
    connection_info['data']['device_path'] = attach_info['device']['path']
    encryptor = brick_get_encryptor(connection_info,
                                    **encryption)
    encryptor.attach_volume(context, **encryption)


def brick_detach_volume_encryptor(attach_info: dict, encryption: dict) -> None:
    """Detach encryption layer."""
    connection_info = attach_info['conn']
    connection_info['data']['device_path'] = attach_info['device']['path']

    encryptor = brick_get_encryptor(connection_info,
                                    **encryption)
    encryptor.detach_volume(**encryption)


# NOTE: the trace methods are included in volume_utils because
# they are currently only called by code in the volume area
# of Cinder.  These can be moved to a different file if they
# are needed elsewhere.
def trace(*dec_args, **dec_kwargs):
    """Trace calls to the decorated function.

    This decorator should always be defined as the outermost decorator so it
    is defined last. This is important so it does not interfere
    with other decorators.

    Using this decorator on a function will cause its execution to be logged at
    `DEBUG` level with arguments, return values, and exceptions.

    :returns: a function decorator
    """

    def _decorator(f):

        func_name = f.__name__

        @functools.wraps(f)
        def trace_logging_wrapper(*args, **kwargs):
            filter_function = dec_kwargs.get('filter_function')

            if len(args) > 0:
                maybe_self = args[0]
            else:
                maybe_self = kwargs.get('self', None)

            if maybe_self and hasattr(maybe_self, '__module__'):
                logger = logging.getLogger(maybe_self.__module__)
            else:
                logger = LOG

            # NOTE(ameade): Don't bother going any further if DEBUG log level
            # is not enabled for the logger.
            if not logger.isEnabledFor(py_logging.DEBUG):
                return f(*args, **kwargs)

            all_args = inspect.getcallargs(f, *args, **kwargs)

            pass_filter = filter_function is None or filter_function(all_args)

            if pass_filter:
                logger.debug('==> %(func)s: call %(all_args)r',
                             {'func': func_name,
                              'all_args': strutils.mask_password(
                                  str(all_args))})

            start_time = time.time() * 1000
            try:
                result = f(*args, **kwargs)
            except Exception as exc:
                total_time = int(round(time.time() * 1000)) - start_time
                logger.debug('<== %(func)s: exception (%(time)dms) %(exc)r',
                             {'func': func_name,
                              'time': total_time,
                              'exc': exc})
                raise
            total_time = int(round(time.time() * 1000)) - start_time

            if isinstance(result, dict):
                mask_result = strutils.mask_dict_password(result)
            elif isinstance(result, str):
                mask_result = strutils.mask_password(result)
            else:
                mask_result = result

            if pass_filter:
                logger.debug('<== %(func)s: return (%(time)dms) %(result)r',
                             {'func': func_name,
                              'time': total_time,
                              'result': mask_result})
            return result
        return trace_logging_wrapper

    if len(dec_args) == 0:
        # filter_function is passed and args does not contain f
        return _decorator
    else:
        # filter_function is not passed
        return _decorator(dec_args[0])


def trace_api(*dec_args, **dec_kwargs):
    """Decorates a function if TRACE_API is true."""

    def _decorator(f):
        @functools.wraps(f)
        def trace_api_logging_wrapper(*args, **kwargs):
            if TRACE_API:
                return trace(f, *dec_args, **dec_kwargs)(*args, **kwargs)
            return f(*args, **kwargs)
        return trace_api_logging_wrapper

    if len(dec_args) == 0:
        # filter_function is passed and args does not contain f
        return _decorator
    else:
        # filter_function is not passed
        return _decorator(dec_args[0])


def trace_method(f):
    """Decorates a function if TRACE_METHOD is true."""
    @functools.wraps(f)
    def trace_method_logging_wrapper(*args, **kwargs):
        if TRACE_METHOD:
            return trace(f)(*args, **kwargs)
        return f(*args, **kwargs)
    return trace_method_logging_wrapper


class TraceWrapperMetaclass(type):
    """Metaclass that wraps all methods of a class with trace_method.

    This metaclass will cause every function inside of the class to be
    decorated with the trace_method decorator.

    To use the metaclass you define a class like so:
    class MyClass(object, metaclass=utils.TraceWrapperMetaclass):
    """
    def __new__(meta, classname, bases, classDict):
        newClassDict = {}
        for attributeName, attribute in classDict.items():
            if isinstance(attribute, types.FunctionType):
                # replace it with a wrapped version
                attribute = functools.update_wrapper(trace_method(attribute),
                                                     attribute)
            newClassDict[attributeName] = attribute

        return type.__new__(meta, classname, bases, newClassDict)


class TraceWrapperWithABCMetaclass(abc.ABCMeta, TraceWrapperMetaclass):
    """Metaclass that wraps all methods of a class with trace."""
    pass


def setup_tracing(trace_flags):
    """Set global variables for each trace flag.

    Sets variables TRACE_METHOD and TRACE_API, which represent
    whether to log methods or api traces.

    :param trace_flags: a list of strings
    """
    global TRACE_METHOD
    global TRACE_API
    try:
        trace_flags = [flag.strip() for flag in trace_flags]
    except TypeError:  # Handle when trace_flags is None or a test mock
        trace_flags = []
    for invalid_flag in (set(trace_flags) - VALID_TRACE_FLAGS):
        LOG.warning('Invalid trace flag: %s', invalid_flag)
    TRACE_METHOD = 'method' in trace_flags
    TRACE_API = 'api' in trace_flags


def require_driver_initialized(driver):
    """Verifies if `driver` is initialized

    If the driver is not initialized, an exception will be raised.

    :params driver: The driver instance.
    :raises: `exception.DriverNotInitialized`
    """
    # we can't do anything if the driver didn't init
    if not driver.initialized:
        driver_name = driver.__class__.__name__
        LOG.error("Volume driver %s not initialized", driver_name)
        raise exception.DriverNotInitialized()
    else:
        log_unsupported_driver_warning(driver)


def log_unsupported_driver_warning(driver):
    """Annoy the log about unsupported drivers."""
    if not driver.supported:
        # Check to see if the driver is flagged as supported.
        LOG.warning("Volume driver (%(driver_name)s %(version)s) is "
                    "currently unsupported and may be removed in the "
                    "next release of OpenStack.  Use at your own risk.",
                    {'driver_name': driver.__class__.__name__,
                     'version': driver.get_version()},
                    resource={'type': 'driver',
                              'id': driver.__class__.__name__})
