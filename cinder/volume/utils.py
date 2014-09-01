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


import math

from Crypto.Random import random
from oslo.config import cfg

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import strutils
from cinder.openstack.common import timeutils
from cinder.openstack.common import units
from cinder import rpc
from cinder import utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


def null_safe_str(s):
    return str(s) if s else ''


def _usage_from_volume(context, volume_ref, **kw):
    usage_info = dict(tenant_id=volume_ref['project_id'],
                      host=volume_ref['host'],
                      user_id=volume_ref['user_id'],
                      instance_uuid=volume_ref['instance_uuid'],
                      availability_zone=volume_ref['availability_zone'],
                      volume_id=volume_ref['id'],
                      volume_type=volume_ref['volume_type_id'],
                      display_name=volume_ref['display_name'],
                      launched_at=null_safe_str(volume_ref['launched_at']),
                      created_at=null_safe_str(volume_ref['created_at']),
                      status=volume_ref['status'],
                      snapshot_id=volume_ref['snapshot_id'],
                      size=volume_ref['size'],
                      replication_status=volume_ref['replication_status'],
                      replication_extended_status=
                      volume_ref['replication_extended_status'],
                      replication_driver_data=
                      volume_ref['replication_driver_data'],
                      )

    usage_info.update(kw)
    return usage_info


def notify_about_volume_usage(context, volume, event_suffix,
                              extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(context, volume, **extra_usage_info)

    rpc.get_notifier("volume", host).info(context, 'volume.%s' % event_suffix,
                                          usage_info)


def _usage_from_snapshot(context, snapshot_ref, **extra_usage_info):
    usage_info = {
        'tenant_id': snapshot_ref['project_id'],
        'user_id': snapshot_ref['user_id'],
        'availability_zone': snapshot_ref.volume['availability_zone'],
        'volume_id': snapshot_ref['volume_id'],
        'volume_size': snapshot_ref['volume_size'],
        'snapshot_id': snapshot_ref['id'],
        'display_name': snapshot_ref['display_name'],
        'created_at': str(snapshot_ref['created_at']),
        'status': snapshot_ref['status'],
        'deleted': null_safe_str(snapshot_ref['deleted'])
    }

    usage_info.update(extra_usage_info)
    return usage_info


def notify_about_snapshot_usage(context, snapshot, event_suffix,
                                extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_snapshot(context, snapshot, **extra_usage_info)

    rpc.get_notifier('snapshot', host).info(context,
                                            'snapshot.%s' % event_suffix,
                                            usage_info)


def notify_about_replication_usage(context, volume, suffix,
                                   extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(context,
                                    volume,
                                    **extra_usage_info)

    rpc.get_notifier('replication', host).info(context,
                                               'replication.%s' % suffix,
                                               usage_info)


def notify_about_replication_error(context, volume, suffix,
                                   extra_error_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_error_info:
        extra_error_info = {}

    usage_info = _usage_from_volume(context,
                                    volume,
                                    **extra_error_info)

    rpc.get_notifier('replication', host).error(context,
                                                'replication.%s' % suffix,
                                                usage_info)


def _usage_from_consistencygroup(context, group_ref, **kw):
    usage_info = dict(tenant_id=group_ref['project_id'],
                      user_id=group_ref['user_id'],
                      availability_zone=group_ref['availability_zone'],
                      consistencygroup_id=group_ref['id'],
                      name=group_ref['name'],
                      created_at=null_safe_str(group_ref['created_at']),
                      status=group_ref['status'])

    usage_info.update(kw)
    return usage_info


def notify_about_consistencygroup_usage(context, group, event_suffix,
                                        extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_consistencygroup(context,
                                              group,
                                              **extra_usage_info)

    rpc.get_notifier("consistencygroup", host).info(
        context,
        'consistencygroup.%s' % event_suffix,
        usage_info)


def _usage_from_cgsnapshot(context, cgsnapshot_ref, **kw):
    usage_info = dict(
        tenant_id=cgsnapshot_ref['project_id'],
        user_id=cgsnapshot_ref['user_id'],
        cgsnapshot_id=cgsnapshot_ref['id'],
        name=cgsnapshot_ref['name'],
        consistencygroup_id=cgsnapshot_ref['consistencygroup_id'],
        created_at=null_safe_str(cgsnapshot_ref['created_at']),
        status=cgsnapshot_ref['status'])

    usage_info.update(kw)
    return usage_info


def notify_about_cgsnapshot_usage(context, cgsnapshot, event_suffix,
                                  extra_usage_info=None, host=None):
    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_cgsnapshot(context,
                                        cgsnapshot,
                                        **extra_usage_info)

    rpc.get_notifier("cgsnapshot", host).info(
        context,
        'cgsnapshot.%s' % event_suffix,
        usage_info)


def setup_blkio_cgroup(srcpath, dstpath, bps_limit, execute=utils.execute):
    if not bps_limit:
        LOG.debug('Not using bps rate limiting on volume copy')
        return None

    try:
        srcdev = utils.get_blkdev_major_minor(srcpath)
    except exception.Error as e:
        msg = (_('Failed to get device number for read throttling: %(error)s')
               % {'error': e})
        LOG.error(msg)
        srcdev = None

    try:
        dstdev = utils.get_blkdev_major_minor(dstpath)
    except exception.Error as e:
        msg = (_('Failed to get device number for write throttling: %(error)s')
               % {'error': e})
        LOG.error(msg)
        dstdev = None

    if not srcdev and not dstdev:
        return None

    group_name = CONF.volume_copy_blkio_cgroup_name
    LOG.debug('Setting rate limit to %s bps for blkio '
              'group: %s' % (bps_limit, group_name))
    try:
        execute('cgcreate', '-g', 'blkio:%s' % group_name, run_as_root=True)
    except processutils.ProcessExecutionError:
        LOG.warn(_('Failed to create blkio cgroup'))
        return None

    try:
        if srcdev:
            execute('cgset', '-r', 'blkio.throttle.read_bps_device=%s %d'
                    % (srcdev, bps_limit), group_name, run_as_root=True)
        if dstdev:
            execute('cgset', '-r', 'blkio.throttle.write_bps_device=%s %d'
                    % (dstdev, bps_limit), group_name, run_as_root=True)
    except processutils.ProcessExecutionError:
        msg = (_('Failed to setup blkio cgroup to throttle the devices: '
                 '\'%(src)s\',\'%(dst)s\'')
               % {'src': srcdev, 'dst': dstdev})
        LOG.warn(msg)
        return None

    return ['cgexec', '-g', 'blkio:%s' % group_name]


def _calculate_count(size_in_m, blocksize):

    # Check if volume_dd_blocksize is valid
    try:
        # Rule out zero-sized/negative/float dd blocksize which
        # cannot be caught by strutils
        if blocksize.startswith(('-', '0')) or '.' in blocksize:
            raise ValueError
        bs = strutils.string_to_bytes('%sB' % blocksize)
    except ValueError:
        msg = (_("Incorrect value error: %(blocksize)s, "
                 "it may indicate that \'volume_dd_blocksize\' "
                 "was configured incorrectly. Fall back to default.")
               % {'blocksize': blocksize})
        LOG.warn(msg)
        # Fall back to default blocksize
        CONF.clear_override('volume_dd_blocksize')
        blocksize = CONF.volume_dd_blocksize
        bs = strutils.string_to_bytes('%sB' % blocksize)

    count = math.ceil(size_in_m * units.Mi / bs)

    return blocksize, int(count)


def copy_volume(srcstr, deststr, size_in_m, blocksize, sync=False,
                execute=utils.execute, ionice=None):
    # Use O_DIRECT to avoid thrashing the system buffer cache
    extra_flags = []
    # Check whether O_DIRECT is supported to iflag and oflag separately
    for flag in ['iflag=direct', 'oflag=direct']:
        try:
            execute('dd', 'count=0', 'if=%s' % srcstr, 'of=%s' % deststr,
                    flag, run_as_root=True)
            extra_flags.append(flag)
        except processutils.ProcessExecutionError:
            pass

    # If the volume is being unprovisioned then
    # request the data is persisted before returning,
    # so that it's not discarded from the cache.
    if sync and not extra_flags:
        extra_flags.append('conv=fdatasync')

    blocksize, count = _calculate_count(size_in_m, blocksize)

    cmd = ['dd', 'if=%s' % srcstr, 'of=%s' % deststr,
           'count=%d' % count, 'bs=%s' % blocksize]
    cmd.extend(extra_flags)

    if ionice is not None:
        cmd = ['ionice', ionice] + cmd

    cgcmd = setup_blkio_cgroup(srcstr, deststr, CONF.volume_copy_bps_limit)
    if cgcmd:
        cmd = cgcmd + cmd

    # Perform the copy
    start_time = timeutils.utcnow()
    execute(*cmd, run_as_root=True)
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    mbps = (size_in_m / duration)
    mesg = ("Volume copy details: src %(src)s, dest %(dest)s, "
            "size %(sz).2f MB, duration %(duration).2f sec")
    LOG.debug(mesg % {"src": srcstr,
                      "dest": deststr,
                      "sz": size_in_m,
                      "duration": duration})
    mesg = _("Volume copy %(size_in_m).2f MB at %(mbps).2f MB/s")
    LOG.info(mesg % {'size_in_m': size_in_m, 'mbps': mbps})


def clear_volume(volume_size, volume_path, volume_clear=None,
                 volume_clear_size=None, volume_clear_ionice=None):
    """Unprovision old volumes to prevent data leaking between users."""
    if volume_clear is None:
        volume_clear = CONF.volume_clear

    if volume_clear_size is None:
        volume_clear_size = CONF.volume_clear_size

    if volume_clear_size == 0:
        volume_clear_size = volume_size

    if volume_clear_ionice is None:
        volume_clear_ionice = CONF.volume_clear_ionice

    LOG.info(_("Performing secure delete on volume: %s") % volume_path)

    if volume_clear == 'zero':
        return copy_volume('/dev/zero', volume_path, volume_clear_size,
                           CONF.volume_dd_blocksize,
                           sync=True, execute=utils.execute,
                           ionice=volume_clear_ionice)
    elif volume_clear == 'shred':
        clear_cmd = ['shred', '-n3']
        if volume_clear_size:
            clear_cmd.append('-s%dMiB' % volume_clear_size)
    else:
        raise exception.InvalidConfigurationValue(
            option='volume_clear',
            value=volume_clear)

    clear_cmd.append(volume_path)
    start_time = timeutils.utcnow()
    utils.execute(*clear_cmd, run_as_root=True)
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    LOG.info(_('Elapsed time for clear volume: %.2f sec') % duration)


def supports_thin_provisioning():
    return brick_lvm.LVM.supports_thin_provisioning(
        utils.get_root_helper())


def get_all_volumes(vg_name=None):
    return brick_lvm.LVM.get_all_volumes(
        utils.get_root_helper(),
        vg_name)


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


def generate_password(length=20, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbol groups.

    At least one symbol from each group will be included. Unpredictable
    results if length is less than the number of symbol groups.

    Believed to be reasonably secure (with a reasonable password length!)

    """
    # NOTE(jerdfelt): Some password policies require at least one character
    # from each group of symbols, so start off with one random character
    # from each symbol group
    password = [random.choice(s) for s in symbolgroups]
    # If length < len(symbolgroups), the leading characters will only
    # be from the first length groups. Try our best to not be predictable
    # by shuffling and then truncating.
    random.shuffle(password)
    password = password[:length]
    length -= len(password)

    # then fill with random characters from all symbol groups
    symbols = ''.join(symbolgroups)
    password.extend([random.choice(symbols) for _i in xrange(length)])

    # finally shuffle to ensure first x characters aren't from a
    # predictable group
    random.shuffle(password)

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
    :return: expected level of information

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
