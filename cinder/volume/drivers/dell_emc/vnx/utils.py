# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import six
import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import uuidutils

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.san.san import san_opts
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

storops = importutils.try_import('storops')


storops = importutils.try_import('storops')
LOG = logging.getLogger(__name__)


def init_ops(configuration):
    configuration.append_config_values(common.VNX_OPTS)
    configuration.append_config_values(san_opts)


def get_metadata(volume):
    # Since versionedobjects is partially merged, metadata
    # may come from 'volume_metadata' or 'metadata', here
    # we need to take care both of them.
    volume_metadata = {}
    if 'volume_metadata' in volume:
        for metadata in volume['volume_metadata']:
            volume_metadata[metadata['key']] = metadata['value']
        return volume_metadata
    return volume['metadata'] if 'metadata' in volume else {}


def dump_provider_location(location_dict):
    return '|'.join([k + '^' + v for k, v in location_dict.items()])


def build_provider_location(system, lun_type, lun_id, base_lun_name, version):
    """Builds provider_location for volume or snapshot.

    :param system: VNX serial number
    :param lun_id: LUN ID in VNX
    :param lun_type: 'lun' or 'smp'
    :param base_lun_name: primary LUN name,
                          it will be used when creating snap lun
    :param version: driver version
    """
    location_dict = {'system': system,
                     'type': lun_type,
                     'id': six.text_type(lun_id),
                     'base_lun_name': six.text_type(base_lun_name),
                     'version': version}
    return dump_provider_location(location_dict)


def extract_provider_location(provider_location, key):
    """Extracts value of the specified field from provider_location string.

    :param provider_location: provider_location string
    :param key: field name of the value that to be extracted
    :return: value of the specified field if it exists, otherwise,
             None is returned
    """
    if not provider_location:
        return None

    kvps = provider_location.split('|')
    for kvp in kvps:
        fields = kvp.split('^')
        if len(fields) == 2 and fields[0] == key:
            return fields[1]


def update_provider_location(provider_location, items):
    """Updates provider_location with new dict items.

    :param provider_location: volume's provider_location.
    :param items: dict items for updating.
    """
    location_dict = {tp.split('^')[0]: tp.split('^')[1]
                     for tp in provider_location.split('|')}
    for key, value in items.items():
        location_dict[key] = value
    return dump_provider_location(location_dict)


def update_remote_provider_location(volume, client):
    """Update volume provider_location after volume failed-over."""
    provider_location = volume.provider_location
    updated = {}
    updated['system'] = client.get_serial()
    updated['id'] = six.text_type(
        client.get_lun(name=volume.name).lun_id)
    provider_location = update_provider_location(
        provider_location, updated)
    return provider_location


def get_pool_from_host(host):
    return vol_utils.extract_host(host, 'pool')


def wait_until(condition, timeout=None, interval=common.INTERVAL_5_SEC,
               reraise_arbiter=lambda ex: True, *args, **kwargs):
    start_time = time.time()
    if not timeout:
        timeout = common.DEFAULT_TIMEOUT

    def _inner():
        try:
            test_value = condition(*args, **kwargs)
        except Exception as ex:
            test_value = False
            with excutils.save_and_reraise_exception(
                    reraise=reraise_arbiter(ex)):
                LOG.debug('Exception raised when executing %(condition_name)s '
                          'in wait_until. Message: %(msg)s',
                          {'condition_name': condition.__name__,
                           'msg': ex.message})
        if test_value:
            raise loopingcall.LoopingCallDone()

        if int(time.time()) - start_time > timeout:
            msg = (_('Timeout waiting for %(condition_name)s in wait_until.')
                   % {'condition_name': condition.__name__})
            LOG.error(msg)
            raise common.WaitUtilTimeoutException(msg)

    timer = loopingcall.FixedIntervalLoopingCall(_inner)
    timer.start(interval=interval).wait()


def validate_storage_migration(volume, target_host, src_serial, src_protocol):
    if 'location_info' not in target_host['capabilities']:
        LOG.warning("Failed to get pool name and "
                    "serial number. 'location_info' "
                    "from %s.", target_host['host'])
        return False
    info = target_host['capabilities']['location_info']
    LOG.debug("Host for migration is %s.", info)
    try:
        serial_number = info.split('|')[1]
    except AttributeError:
        LOG.warning('Error on getting serial number '
                    'from %s.', target_host['host'])
        return False
    if serial_number != src_serial:
        LOG.debug('Skip storage-assisted migration because '
                  'target and source backend are not managing '
                  'the same array.')
        return False
    if (target_host['capabilities']['storage_protocol'] != src_protocol
            and get_original_status(volume) == 'in-use'):
        LOG.debug('Skip storage-assisted migration because '
                  'in-use volume can not be '
                  'migrate between different protocols.')
        return False
    return True


def retype_need_migration(volume, old_provision, new_provision, host):
    if volume['host'] != host['host']:
        return True

    lun_type = extract_provider_location(volume['provider_location'], 'type')
    if lun_type == 'smp':
        return True

    if old_provision != new_provision:
        if retype_need_turn_on_compression(old_provision, new_provision):
            return False
        else:
            return True

    return False


def retype_need_turn_on_compression(old_provision, new_provision):
    return (old_provision in [storops.VNXProvisionEnum.THIN,
                              storops.VNXProvisionEnum.THICK]
            and new_provision == storops.VNXProvisionEnum.COMPRESSED)


def retype_need_change_tier(old_tier, new_tier):
    return new_tier is not None and old_tier != new_tier


def get_original_status(volume):
    if not volume['volume_attachment']:
        return 'available'
    else:
        return 'in-use'


def construct_snap_name(volume):
    """Return snapshot name."""
    if is_snapcopy_enabled(volume):
        return 'snap-as-vol-' + six.text_type(volume.name_id)
    else:
        return 'tmp-snap-' + six.text_type(volume.name_id)


def construct_mirror_name(volume):
    """Constructs MirrorView name for volume."""
    return 'mirror_' + six.text_type(volume.id)


def construct_group_name(group):
    """Constructs MirrorGroup name for volumes.

    VNX only allows for 32-character group name, so
    trim the dash(-) from group id.
    """
    return group.id.replace('-', '')


def construct_tmp_cg_snap_name(cg_name):
    """Return CG snapshot name."""
    return 'tmp-snap-' + six.text_type(cg_name)


def construct_tmp_lun_name(lun_name):
    """Constructs a time-based temporary LUN name."""
    return '%(src)s-%(ts)s' % {'src': lun_name,
                               'ts': int(time.time())}


def construct_smp_name(snap_id):
    return 'tmp-smp-' + six.text_type(snap_id)


def is_snapcopy_enabled(volume):
    meta = get_metadata(volume)
    return 'snapcopy' in meta and meta['snapcopy'].lower() == 'true'


def is_async_migrate_enabled(volume):
    extra_specs = common.ExtraSpecs.from_volume(volume)
    if extra_specs.is_replication_enabled:
        # For replication-enabled volume, we should not use the async-cloned
        # volume, or setup replication would fail with
        # VNXMirrorLunNotAvailableError
        return False
    meta = get_metadata(volume)
    if 'async_migrate' not in meta:
        # Asynchronous migration is the default behavior now
        return True
    return 'async_migrate' in meta and meta['async_migrate'].lower() == 'true'


def get_migration_rate(volume):
    metadata = get_metadata(volume)
    rate = metadata.get('migrate_rate', None)
    if rate:
        if rate.lower() in storops.VNXMigrationRate.values():
            return storops.VNXMigrationRate.parse(rate.lower())
        else:
            LOG.warning('Unknown migration rate specified, '
                        'using [high] as migration rate.')

            return storops.VNXMigrationRate.HIGH


def check_type_matched(volume):
    """Check volume type and group type

    This will make sure they do not conflict with each other.

    :param volume: volume to be checked
    :returns: None
    :raises: InvalidInput

    """

    # If volume is not a member of group, skip this check anyway.
    if not volume.group:
        return
    extra_specs = common.ExtraSpecs.from_volume(volume)
    group_specs = common.ExtraSpecs.from_group(volume.group)

    if not (group_specs.is_group_replication_enabled ==
            extra_specs.is_replication_enabled):
        msg = _('Replication should be enabled or disabled for both '
                'volume or group. volume replication status: %(vol_status)s, '
                'group replication status: %(group_status)s') % {
                    'vol_status': extra_specs.is_replication_enabled,
                    'group_status': group_specs.is_group_replication_enabled}
        raise exception.InvalidInput(reason=msg)


def check_rep_status_matched(group):
    """Check replication status for group.

    Group status must be enabled before proceeding.
    """
    group_specs = common.ExtraSpecs.from_group(group)
    if group_specs.is_group_replication_enabled:
        if group.replication_status != fields.ReplicationStatus.ENABLED:
            msg = _('Replication status should be %s for replication-enabled '
                    'group.') % fields.ReplicationStatus.ENABLED
            raise exception.InvalidInput(reason=msg)
    else:
        LOG.info('Replication is not enabled on group %s, skip status check.',
                 group.id)


def update_res_without_poll(res):
    with res.with_no_poll():
        res.update()


def update_res_with_poll(res):
    with res.with_poll():
        res.update()


def get_base_lun_name(volume):
    """Returns base LUN name for LUN/snapcopy LUN."""
    base_name = extract_provider_location(
        volume.provider_location, 'base_lun_name')
    if base_name is None or base_name == 'None':
        return volume.name
    return base_name


def sift_port_white_list(port_white_list, registered_io_ports):
    """Filters out the unregistered ports.

    Goes through the `port_white_list`, and filters out the ones not
    registered (that is not in `registered_io_ports`).
    """
    valid_port_list = []
    LOG.debug('Filter ports in [%(white)s}] but not in [%(reg_ports)s].',
              {'white': ','.join(
                  [port.display_name for port in port_white_list]),
               'reg_ports': ','.join(
                   [port.display_name for port in registered_io_ports])})
    for io_port in port_white_list:
        if io_port not in registered_io_ports:
            LOG.debug('Skipped SP port %(port)s due to it is not registered. '
                      'The registered IO ports: %(reg_ports)s.',
                      {'port': io_port, 'reg_ports': registered_io_ports})
        else:
            valid_port_list.append(io_port)

    return valid_port_list


def convert_to_tgt_list_and_itor_tgt_map(zone_mapping):
    """Function to process data from lookup service.

    :param zone_mapping: mapping is the data from the zone lookup service
                         with below format

        .. code:: python

          {
               <San name>: {
                   'initiator_port_wwn_list':
                   ('200000051e55a100', '200000051e55a121'..)
                   'target_port_wwn_list':
                   ('100000051e55a100', '100000051e55a121'..)
               }
          }

    """
    target_wwns = []
    itor_tgt_map = {}
    for san_name in zone_mapping:
        one_map = zone_mapping[san_name]
        for target in one_map['target_port_wwn_list']:
            if target not in target_wwns:
                target_wwns.append(target)
        for initiator in one_map['initiator_port_wwn_list']:
            itor_tgt_map[initiator] = one_map['target_port_wwn_list']
    LOG.debug("target_wwns: %(tgt_wwns)s\n init_targ_map: %(itor_tgt_map)s",
              {'tgt_wwns': target_wwns,
               'itor_tgt_map': itor_tgt_map})
    return target_wwns, itor_tgt_map


def truncate_fc_port_wwn(wwn):
    return wwn.replace(':', '')[16:]


def is_volume_smp(volume):
    return 'smp' == extract_provider_location(volume.provider_location, 'type')


def require_consistent_group_snapshot_enabled(func):
    @six.wraps(func)
    def inner(self, *args, **kwargs):
        if not vol_utils.is_group_a_cg_snapshot_type(args[1]):
            raise NotImplementedError
        return func(self, *args, **kwargs)
    return inner


def get_remote_pool(config, volume):
    """Select remote pool name for replication.

    Prefer configured remote pool name, or same pool name
    as the source volume.
    """
    pool_name = get_pool_from_host(volume.host)
    rep_list = common.ReplicationDeviceList(config)
    remote_pool_name = rep_list[0].pool_name
    return remote_pool_name if remote_pool_name else pool_name


def is_image_cache_volume(volume):
    display_name = volume.display_name
    if (display_name.startswith('image-')
            and uuidutils.is_uuid_like(display_name[6:])):
        LOG.debug('Volume: %s is for image cache. Use sync migration and '
                  'thin provisioning.', volume.name)
        return True
    return False


def calc_migrate_and_provision(volume):
    """Returns a tuple of async migrate and provision type.

    The first element is the flag whether to enable async migrate,
    the second is the provision type (thin or thick).
    """
    if is_image_cache_volume(volume):
        return False, storops.VNXProvisionEnum.THIN
    else:
        specs = common.ExtraSpecs.from_volume(volume)
        return is_async_migrate_enabled(volume), specs.provision


def get_backend_qos_specs(volume):
    type_id = volume.volume_type_id
    if type_id is None:
        return None

    # Use the provided interface to avoid permission issue
    qos_specs = volume_types.get_volume_type_qos_specs(type_id)
    if qos_specs is None:
        return None

    qos_specs = qos_specs['qos_specs']
    if qos_specs is None:
        return None

    consumer = qos_specs['consumer']
    # Front end QoS specs are handled by nova. We ignore them here.
    if consumer not in common.BACKEND_QOS_CONSUMERS:
        return None

    max_iops = qos_specs['specs'].get(common.QOS_MAX_IOPS)
    max_bws = qos_specs['specs'].get(common.QOS_MAX_BWS)
    if max_iops is None and max_bws is None:
        return None

    return {
        'id': qos_specs['id'],
        common.QOS_MAX_IOPS: max_iops,
        common.QOS_MAX_BWS: max_bws,
    }
