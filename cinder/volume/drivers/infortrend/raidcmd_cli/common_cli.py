# Copyright (c) 2015 Infortrend Technology, Inc.
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
Infortrend Common CLI.
"""
import math
import time

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration as conf
from cinder.volume.drivers.infortrend.raidcmd_cli import cli_factory as cli
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

infortrend_esds_opts = [
    cfg.StrOpt('infortrend_pools_name',
               default='',
               help='Infortrend raid pool name list. '
               'It is separated with comma.'),
    cfg.StrOpt('infortrend_cli_path',
               default='/opt/bin/Infortrend/raidcmd_ESDS10.jar',
               help='The Infortrend CLI absolute path. '
               'By default, it is at '
               '/opt/bin/Infortrend/raidcmd_ESDS10.jar'),
    cfg.IntOpt('infortrend_cli_max_retries',
               default=5,
               help='Maximum retry time for cli. Default is 5.'),
    cfg.IntOpt('infortrend_cli_timeout',
               default=30,
               help='Default timeout for CLI copy operations in minutes. '
               'Support: migrate volume, create cloned volume and '
               'create volume from snapshot. '
               'By Default, it is 30 minutes.'),
    cfg.StrOpt('infortrend_slots_a_channels_id',
               default='0,1,2,3,4,5,6,7',
               help='Infortrend raid channel ID list on Slot A '
               'for OpenStack usage. It is separated with comma. '
               'By default, it is the channel 0~7.'),
    cfg.StrOpt('infortrend_slots_b_channels_id',
               default='0,1,2,3,4,5,6,7',
               help='Infortrend raid channel ID list on Slot B '
               'for OpenStack usage. It is separated with comma. '
               'By default, it is the channel 0~7.'),
]

infortrend_esds_extra_opts = [
    cfg.StrOpt('infortrend_provisioning',
               default='full',
               help='Let the volume use specific provisioning. '
               'By default, it is the full provisioning. '
               'The supported options are full or thin.'),
    cfg.StrOpt('infortrend_tiering',
               default='0',
               help='Let the volume use specific tiering level. '
               'By default, it is the level 0. '
               'The supported levels are 0,2,3,4.'),
]

CONF = cfg.CONF
CONF.register_opts(infortrend_esds_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(infortrend_esds_extra_opts, group=conf.SHARED_CONF_GROUP)

CLI_RC_FILTER = {
    'CreatePartition': {'error': _('Failed to create partition.')},
    'DeletePartition': {'error': _('Failed to delete partition.')},
    'SetPartition': {'error': _('Failed to set partition.')},
    'CreateMap': {
        'warning': {20: 'The MCS Channel is grouped.'},
        'error': _('Failed to create map.'),
    },
    'DeleteMap': {
        'warning': {11: 'No mapping.'},
        'error': _('Failed to delete map.'),
    },
    'CreateSnapshot': {'error': _('Failed to create snapshot.')},
    'DeleteSnapshot': {'error': _('Failed to delete snapshot.')},
    'CreateReplica': {'error': _('Failed to create replica.')},
    'DeleteReplica': {'error': _('Failed to delete replica.')},
    'CreateIQN': {
        'warning': {20: 'IQN already existed.'},
        'error': _('Failed to create iqn.'),
    },
    'DeleteIQN': {
        'warning': {
            20: 'IQN has been used to create map.',
            11: 'No such host alias name.',
        },
        'error': _('Failed to delete iqn.'),
    },
    'ShowLV': {'error': _('Failed to get lv info.')},
    'ShowPartition': {'error': _('Failed to get partition info.')},
    'ShowSnapshot': {'error': _('Failed to get snapshot info.')},
    'ShowDevice': {'error': _('Failed to get device info.')},
    'ShowChannel': {'error': _('Failed to get channel info.')},
    'ShowMap': {'error': _('Failed to get map info.')},
    'ShowNet': {'error': _('Failed to get network info.')},
    'ShowLicense': {'error': _('Failed to get license info.')},
    'ShowReplica': {'error': _('Failed to get replica info.')},
    'ShowWWN': {'error': _('Failed to get wwn info.')},
    'ShowIQN': {'error': _('Failed to get iqn info.')},
    'ExecuteCommand': {'error': _('Failed to execute common command.')},
}


def log_func(func):
    def inner(self, *args, **kwargs):
        LOG.debug('Entering: %(method)s', {'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug(
            'Leaving: %(method)s, '
            'Spent: %(time)s sec, '
            'Return: %(ret)s.', {
                'method': func.__name__,
                'time': timeutils.delta_seconds(start, end),
                'ret': ret})
        return ret
    return inner


def mi_to_gi(mi_size):
    return mi_size * units.Mi / units.Gi


def gi_to_mi(gi_size):
    return gi_size * units.Gi / units.Mi


class InfortrendCommon(object):

    """The Infortrend's Common Command using CLI.

    Version history:
        1.0.0 - Initial driver
        1.0.1 - Support DS4000
        1.0.2 - Support GS Series
    """

    VERSION = '1.0.2'

    constants = {
        'ISCSI_PORT': 3260,
        'MAX_LUN_MAP_PER_CHL': 128
    }

    provisioning_values = ['thin', 'full']

    tiering_values = ['0', '2', '3', '4']

    def __init__(self, protocol, configuration=None):

        self.protocol = protocol
        self.configuration = configuration
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(infortrend_esds_opts)
        self.configuration.append_config_values(infortrend_esds_extra_opts)

        self.iscsi_multipath = self.configuration.use_multipath_for_image_xfer
        self.path = self.configuration.infortrend_cli_path
        self.password = self.configuration.san_password
        self.ip = self.configuration.san_ip
        self.cli_retry_time = self.configuration.infortrend_cli_max_retries
        self.cli_timeout = self.configuration.infortrend_cli_timeout * 60
        self.iqn = 'iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s'
        self.unmanaged_prefix = 'cinder-unmanaged-%s'

        if self.ip == '':
            msg = _('san_ip is not set.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self.fc_lookup_service = fczm_utils.create_lookup_service()

        self._volume_stats = None
        self._model_type = 'R'
        self._replica_timeout = self.cli_timeout

        self.map_dict = {
            'slot_a': {},
            'slot_b': {},
        }
        self.map_dict_init = False

        self.target_dict = {
            'slot_a': {},
            'slot_b': {},
        }

        if self.protocol == 'iSCSI':
            self.mcs_dict = {
                'slot_a': {},
                'slot_b': {},
            }

        self._init_pool_list()
        self._init_channel_list()

        self.cli_conf = {
            'path': self.path,
            'password': self.password,
            'ip': self.ip,
            'cli_retry_time': int(self.cli_retry_time),
        }

    def _init_pool_list(self):
        pools_name = self.configuration.infortrend_pools_name
        if pools_name == '':
            msg = _('Pools name is not set.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        tmp_pool_list = pools_name.split(',')
        self.pool_list = [pool.strip() for pool in tmp_pool_list]

    def _init_channel_list(self):
        self.channel_list = {
            'slot_a': [],
            'slot_b': [],
        }
        tmp_channel_list = (
            self.configuration.infortrend_slots_a_channels_id.split(',')
        )
        self.channel_list['slot_a'] = (
            [channel.strip() for channel in tmp_channel_list]
        )
        tmp_channel_list = (
            self.configuration.infortrend_slots_b_channels_id.split(',')
        )
        self.channel_list['slot_b'] = (
            [channel.strip() for channel in tmp_channel_list]
        )

    def _execute_command(self, cli_type, *args, **kwargs):
        command = getattr(cli, cli_type)
        return command(self.cli_conf).execute(*args, **kwargs)

    def _execute(self, cli_type, *args, **kwargs):
        LOG.debug('Executing command type: %(type)s.', {'type': cli_type})

        rc, out = self._execute_command(cli_type, *args, **kwargs)

        if rc != 0:
            if ('warning' in CLI_RC_FILTER[cli_type] and
                    rc in CLI_RC_FILTER[cli_type]['warning']):
                LOG.warning(CLI_RC_FILTER[cli_type]['warning'][rc])
            else:
                msg = CLI_RC_FILTER[cli_type]['error']
                LOG.error(msg)
                raise exception.InfortrendCliException(
                    err=msg, param=args, rc=rc, out=out)
        return rc, out

    @log_func
    def _init_map_info(self, multipath=False):
        if not self.map_dict_init:

            rc, channel_info = self._execute('ShowChannel')

            if 'BID' in channel_info[0]:
                self._model_type = 'R'
            else:
                self._model_type = 'G'

            self._set_channel_id(channel_info, 'slot_a', multipath)

            if multipath and self._model_type == 'R':
                self._set_channel_id(channel_info, 'slot_b', multipath)

            self.map_dict_init = True

    @log_func
    def _update_map_info(self, multipath=False):
        """Record the driver mapping information.

        map_dict = {
            'slot_a': {
                '0': [1, 2, 3, 4]  # Slot A Channel 0 map lun 1, 2, 3, 4
            },
            'slot_b' : {
                '1': [0, 1, 3]     # Slot B Channel 1 map lun 0, 1, 3
            }
        }
        """
        rc, map_info = self._execute('ShowMap')

        self._update_map_info_by_slot(map_info, 'slot_a')

        if multipath and self._model_type == 'R':
            self._update_map_info_by_slot(map_info, 'slot_b')
        return map_info

    @log_func
    def _update_map_info_by_slot(self, map_info, slot_key):
        for key, value in self.map_dict[slot_key].items():
            self.map_dict[slot_key][key] = list(
                range(self.constants['MAX_LUN_MAP_PER_CHL']))

        if len(map_info) > 0 and isinstance(map_info, list):
            for entry in map_info:
                ch = entry['Ch']
                lun = entry['LUN']
                if ch not in self.map_dict[slot_key].keys():
                    continue

                target_id = self.target_dict[slot_key][ch]
                if (entry['Target'] == target_id and
                        int(lun) in self.map_dict[slot_key][ch]):
                    self.map_dict[slot_key][ch].remove(int(lun))

    def _check_initiator_has_lun_map(self, initiator_info, map_info):
        if not isinstance(initiator_info, list):
            initiator_info = (initiator_info,)
        for initiator_name in initiator_info:
            for entry in map_info:
                if initiator_name.lower() == entry['Host-ID'].lower():
                    return True
        return False

    @log_func
    def _set_channel_id(
            self, channel_info, controller='slot_a', multipath=False):

        if self.protocol == 'iSCSI':
            check_channel_type = ('NETWORK', 'LAN')
        else:
            check_channel_type = ('FIBRE', 'Fibre')

        for entry in channel_info:
            if entry['Type'] in check_channel_type:
                if entry['Ch'] in self.channel_list[controller]:
                    self.map_dict[controller][entry['Ch']] = []

                    if self.protocol == 'iSCSI':
                        self._update_mcs_dict(
                            entry['Ch'], entry['MCS'], controller)

                    self._update_target_dict(entry, controller)

    @log_func
    def _update_target_dict(self, channel, controller):
        """Record the target id for mapping.

        # R model
        target_dict = {
            'slot_a': {
                '0': '0',
                '1': '0',
            },
            'slot_b': {
                '0': '1',
                '1': '1',
            },
        }

        # G model
        target_dict = {
            'slot_a': {
                '2': '32',
                '3': '112',
            }
        }
        """
        if self._model_type == 'G':
            self.target_dict[controller][channel['Ch']] = channel['ID']
        else:
            if controller == 'slot_a':
                self.target_dict[controller][channel['Ch']] = channel['AID']
            else:
                self.target_dict[controller][channel['Ch']] = channel['BID']

    def _update_mcs_dict(self, channel_id, mcs_id, controller):
        """Record the iSCSI MCS topology.

        # R model with mcs, but it not working with iSCSI multipath
        mcs_dict = {
            'slot_a': {
                '0': ['0', '1'],
                '1': ['2']
            },
            'slot_b': {
                '0': ['0', '1'],
                '1': ['2']
            }
        }

        # G model with mcs
        mcs_dict = {
            'slot_a': {
                '0': ['0', '1'],
                '1': ['2']
            },
            'slot_b': {}
        }
        """
        if mcs_id not in self.mcs_dict[controller]:
            self.mcs_dict[controller][mcs_id] = []
        self.mcs_dict[controller][mcs_id].append(channel_id)

    def _check_tiers_setup(self):
        tiering = self.configuration.infortrend_tiering
        if tiering != '0':
            self._check_extraspec_value(
                tiering, self.tiering_values)
            tier_levels_list = list(range(int(tiering)))
            tier_levels_list = list(map(str, tier_levels_list))

            rc, lv_info = self._execute('ShowLV', 'tier')

            for pool in self.pool_list:
                support_tier_levels = tier_levels_list[:]
                for entry in lv_info:
                    if (entry['LV-Name'] == pool and
                            entry['Tier'] in support_tier_levels):
                        support_tier_levels.remove(entry['Tier'])
                    if len(support_tier_levels) == 0:
                        break
                if len(support_tier_levels) != 0:
                    msg = _('Please create %(tier_levels)s '
                            'tier in pool %(pool)s in advance!') % {
                                'tier_levels': support_tier_levels,
                                'pool': pool}
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)

    def _check_pools_setup(self):
        pool_list = self.pool_list[:]

        rc, lv_info = self._execute('ShowLV')

        for lv in lv_info:
            if lv['Name'] in pool_list:
                pool_list.remove(lv['Name'])
            if len(pool_list) == 0:
                break

        if len(pool_list) != 0:
            msg = _('Please create %(pool_list)s pool in advance!') % {
                'pool_list': pool_list}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def check_for_setup_error(self):
        self._check_pools_setup()
        self._check_tiers_setup()

    def create_volume(self, volume):
        """Create a Infortrend partition."""
        volume_id = volume['id'].replace('-', '')

        self._create_partition_by_default(volume)
        part_id = self._get_part_id(volume_id)

        system_id = self._get_system_id(self.ip)

        model_dict = {
            'system_id': system_id,
            'partition_id': part_id,
        }

        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }
        LOG.info('Create Volume %(volume_id)s completed.', {
            'volume_id': volume_id})
        return model_update

    def _create_partition_by_default(self, volume):
        pool_id = self._get_target_pool_id(volume)
        self._create_partition_with_pool(volume, pool_id)

    def _create_partition_with_pool(
            self, volume, pool_id, extraspecs=None):

        volume_id = volume['id'].replace('-', '')
        volume_size = gi_to_mi(volume['size'])

        if extraspecs is None:
            extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])

        provisioning = self._get_extraspecs_value(extraspecs, 'provisioning')
        tiering = self._get_extraspecs_value(extraspecs, 'tiering')

        extraspecs_dict = {}
        cmd = ''
        if provisioning == 'thin':
            provisioning = int(volume_size * 0.2)
            extraspecs_dict['provisioning'] = provisioning
            extraspecs_dict['init'] = 'disable'
        else:
            self._check_extraspec_value(
                provisioning, self.provisioning_values)

        if tiering != '0':
            self._check_extraspec_value(
                tiering, self.tiering_values)
            tier_levels_list = list(range(int(tiering)))
            tier_levels_list = list(map(str, tier_levels_list))
            self._check_tiering_existing(tier_levels_list, pool_id)
            extraspecs_dict['provisioning'] = 0
            extraspecs_dict['init'] = 'disable'

        if extraspecs_dict:
            cmd = self._create_part_parameters_str(extraspecs_dict)

        commands = (pool_id, volume_id, 'size=%s' % int(volume_size), cmd)
        self._execute('CreatePartition', *commands)

    def _create_part_parameters_str(self, extraspecs_dict):
        parameters_list = []
        parameters = {
            'provisioning': 'min=%sMB',
            'tiering': 'tier=%s',
            'init': 'init=%s',
        }
        for extraspec in sorted(extraspecs_dict.keys()):
            value = parameters[extraspec] % (extraspecs_dict[extraspec])
            parameters_list.append(value)

        cmd = ' '.join(parameters_list)
        return cmd

    def _check_tiering_existing(self, tier_levels, pool_id):
        rc, lv_info = self._execute('ShowLV', 'tier')

        for entry in lv_info:
            if entry['LV-ID'] == pool_id and entry['Tier'] in tier_levels:
                tier_levels.remove(entry['Tier'])
                if len(tier_levels) == 0:
                    break
        if len(tier_levels) != 0:
            msg = _('Have not created %(tier_levels)s tier(s).') % {
                'tier_levels': tier_levels}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    @log_func
    def _create_map_with_lun_filter(
            self, part_id, channel_id, lun_id, host, controller='slot_a'):

        host_filter = self._create_target_id_and_host_filter(
            controller, host)
        target_id = self.target_dict[controller][channel_id]

        commands = (
            'part', part_id, channel_id, target_id, lun_id, host_filter
        )
        self._execute('CreateMap', *commands)

    @log_func
    def _create_map_with_mcs(
            self, part_id, channel_list, lun_id, host, controller='slot_a'):

        map_channel_id = None
        for channel_id in channel_list:

            host_filter = self._create_target_id_and_host_filter(
                controller, host)
            target_id = self.target_dict[controller][channel_id]

            commands = (
                'part', part_id, channel_id, target_id, lun_id,
                host_filter
            )
            rc, out = self._execute('CreateMap', *commands)
            if rc == 0:
                map_channel_id = channel_id
                break

        if map_channel_id is None:
            msg = _('Failed to create map on mcs, no channel can map.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return map_channel_id

    def _create_target_id_and_host_filter(self, controller, host):
        if self.protocol == 'iSCSI':
            host_filter = 'iqn=%s' % host
        else:
            host_filter = 'wwn=%s' % host

        return host_filter

    def _get_extraspecs_dict(self, volume_type_id):
        extraspecs = {}
        if volume_type_id:
            extraspecs = volume_types.get_volume_type_extra_specs(
                volume_type_id)

        return extraspecs

    def _get_extraspecs_value(self, extraspecs, key):
        value = None
        if key == 'provisioning':
            if (extraspecs and
                    'infortrend_provisioning' in extraspecs.keys()):
                value = extraspecs['infortrend_provisioning'].lower()
            else:
                value = self.configuration.infortrend_provisioning.lower()
        elif key == 'tiering':
            value = self.configuration.infortrend_tiering
        return value

    def _select_most_free_capacity_pool_id(self, lv_info):
        largest_free_capacity_gb = 0.0
        dest_pool_id = None

        for lv in lv_info:
            if lv['Name'] in self.pool_list:
                available_space = float(lv['Available'].split(' ', 1)[0])
                free_capacity_gb = round(mi_to_gi(available_space))
                if free_capacity_gb > largest_free_capacity_gb:
                    largest_free_capacity_gb = free_capacity_gb
                    dest_pool_id = lv['ID']
        return dest_pool_id

    def _get_target_pool_id(self, volume):
        extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])
        pool_id = None
        rc, lv_info = self._execute('ShowLV')

        if 'pool_name' in extraspecs.keys():
            poolname = extraspecs['pool_name']

            for entry in lv_info:
                if entry['Name'] == poolname:
                    pool_id = entry['ID']
        else:
            pool_id = self._select_most_free_capacity_pool_id(lv_info)

        if pool_id is None:
            msg = _('Failed to get pool id with volume %(volume_id)s.') % {
                'volume_id': volume['id']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return pool_id

    def _get_system_id(self, system_ip):
        rc, device_info = self._execute('ShowDevice')

        for entry in device_info:
            if system_ip == entry['Connected-IP']:
                return str(int(entry['ID'], 16))
        return

    @log_func
    def _get_lun_id(self, ch_id, controller='slot_a'):
        lun_id = -1

        if len(self.map_dict[controller][ch_id]) > 0:
            lun_id = self.map_dict[controller][ch_id][0]
            self.map_dict[controller][ch_id].remove(lun_id)

        if lun_id == -1:
            msg = _('LUN number is out of bound '
                    'on channel id: %(ch_id)s.') % {'ch_id': ch_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            return lun_id

    @log_func
    def _get_mapping_info(self, multipath):
        if self.iscsi_multipath or multipath:
            return self._get_mapping_info_with_mcs()
        else:
            return self._get_mapping_info_with_normal()

    def _get_mapping_info_with_mcs(self):
        """Get the minimun mapping channel id and multi lun id mapping info.

        # R model with mcs
        map_chl = {
            'slot_a': ['0', '1']
        }
        map_lun = ['0']

        # G model with mcs
        map_chl = {
            'slot_a': ['1', '2']
        }
        map_lun = ['0']

        :returns: minimun mapping channel id per slot and multi lun id
        """
        map_chl = {
            'slot_a': []
        }

        min_lun_num = 0
        map_mcs_group = None
        for mcs in self.mcs_dict['slot_a']:
            if len(self.mcs_dict['slot_a'][mcs]) > 1:
                if min_lun_num < self._get_mcs_channel_lun_map_num(mcs):
                    min_lun_num = self._get_mcs_channel_lun_map_num(mcs)
                    map_mcs_group = mcs

        if map_mcs_group is None:
            msg = _('Raid did not have MCS Channel.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        map_chl['slot_a'] = self.mcs_dict['slot_a'][map_mcs_group]
        map_lun = self._get_mcs_channel_lun_map(map_chl['slot_a'])
        return map_chl, map_lun, map_mcs_group

    def _get_mcs_channel_lun_map_num(self, mcs_id):
        lun_num = 0
        for channel in self.mcs_dict['slot_a'][mcs_id]:
            lun_num += len(self.map_dict['slot_a'][channel])
        return lun_num

    def _get_mcs_channel_lun_map(self, channel_list):
        """Find the common lun id in mcs channel."""

        map_lun = []
        for lun_id in range(self.constants['MAX_LUN_MAP_PER_CHL']):
            check_map = True
            for channel_id in channel_list:
                if lun_id not in self.map_dict['slot_a'][channel_id]:
                    check_map = False
            if check_map:
                map_lun.append(str(lun_id))
                break
        return map_lun

    @log_func
    def _get_mapping_info_with_normal(self):
        """Get the minimun mapping channel id and lun id mapping info.

        # G model and R model
        map_chl = {
            'slot_a': ['1']
        }
        map_lun = ['0']

        :returns: minimun mapping channel id per slot and lun id
        """
        map_chl = {
            'slot_a': []
        }
        map_lun = []

        ret_chl = self._get_minimun_mapping_channel_id('slot_a')
        lun_id = self._get_lun_id(ret_chl, 'slot_a')
        mcs_id = self._get_mcs_id_by_channel_id(ret_chl)

        map_chl['slot_a'].append(ret_chl)
        map_lun.append(str(lun_id))

        return map_chl, map_lun, mcs_id

    @log_func
    def _get_minimun_mapping_channel_id(self, controller):
        empty_lun_num = 0
        min_map_chl = -1

        # Sort items to get a reliable behaviour. Dictionary items
        # are iterated in a random order because of hash randomization.
        for key, value in sorted(self.map_dict[controller].items()):
            if empty_lun_num < len(value):
                min_map_chl = key
                empty_lun_num = len(value)

        if int(min_map_chl) < 0:
            msg = _('LUN map overflow on every channel.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            return min_map_chl

    def _get_common_lun_map_id(self, wwpn_channel_info):
        map_lun = None

        for lun_id in range(self.constants['MAX_LUN_MAP_PER_CHL']):
            lun_id_exist = False
            for slot_name in ['slot_a', 'slot_b']:
                for wwpn in wwpn_channel_info:
                    channel_id = wwpn_channel_info[wwpn]['channel']
                    if channel_id not in self.map_dict[slot_name]:
                        continue
                    elif lun_id not in self.map_dict[slot_name][channel_id]:
                        lun_id_exist = True
            if not lun_id_exist:
                map_lun = str(lun_id)
                break
        return map_lun

    def _get_mcs_id_by_channel_id(self, channel_id):
        mcs_id = None

        for mcs in self.mcs_dict['slot_a']:
            if channel_id in self.mcs_dict['slot_a'][mcs]:
                mcs_id = mcs
                break

        if mcs_id is None:
            msg = _('Cannot get mcs_id by channel id: %(channel_id)s.') % {
                'channel_id': channel_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return mcs_id

    def _concat_provider_location(self, model_dict):
        keys = sorted(model_dict.keys())
        return '@'.join([i + '^' + str(model_dict[i]) for i in keys])

    def delete_volume(self, volume):
        """Delete the specific volume."""

        volume_id = volume['id'].replace('-', '')
        has_pair = False
        have_map = False

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        (check_exist, have_map, part_id) = (
            self._check_volume_exist(volume_id, part_id)
        )

        if not check_exist:
            LOG.warning('Volume %(volume_id)s already deleted.', {
                'volume_id': volume_id})
            return

        rc, replica_list = self._execute('ShowReplica', '-l')

        for entry in replica_list:
            if (volume_id == entry['Source-Name'] and
                    part_id == entry['Source']):
                if not self._check_replica_completed(entry):
                    has_pair = True
                    LOG.warning('Volume still %(status)s '
                                'Cannot delete volume.',
                                {'status': entry['Status']})
                else:
                    have_map = entry['Source-Mapped'] == 'Yes'
                    self._execute('DeleteReplica', entry['Pair-ID'], '-y')

            elif (volume_id == entry['Target-Name'] and
                    part_id == entry['Target']):
                have_map = entry['Target-Mapped'] == 'Yes'
                self._execute('DeleteReplica', entry['Pair-ID'], '-y')

        if not has_pair:

            rc, snapshot_list = self._execute(
                'ShowSnapshot', 'part=%s' % part_id)

            for snapshot in snapshot_list:
                si_has_pair = self._delete_pair_with_snapshot(
                    snapshot['SI-ID'], replica_list)

                if si_has_pair:
                    msg = _('Failed to delete SI '
                            'for volume_id: %(volume_id)s '
                            'because it has pair.') % {
                                'volume_id': volume_id}
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)

                self._execute('DeleteSnapshot', snapshot['SI-ID'], '-y')

            rc, map_info = self._execute('ShowMap', 'part=%s' % part_id)

            if have_map or len(map_info) > 0:
                self._execute('DeleteMap', 'part', part_id, '-y')

            self._execute('DeletePartition', part_id, '-y')

            LOG.info('Delete Volume %(volume_id)s completed.', {
                'volume_id': volume_id})
        else:
            msg = _('Failed to delete volume '
                    'for volume_id: %(volume_id)s '
                    'because it has pair.') % {
                        'volume_id': volume_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _check_replica_completed(self, replica):
        if ((replica['Type'] == 'Copy' and replica['Status'] == 'Completed') or
                (replica['Type'] == 'Mirror' and
                    replica['Status'] == 'Mirror')):
            return True

        return False

    def _check_volume_exist(self, volume_id, part_id):
        check_exist = False
        have_map = False
        result_part_id = part_id

        rc, part_list = self._execute('ShowPartition', '-l')

        for entry in part_list:
            if entry['Name'] == volume_id:
                check_exist = True

                if part_id is None:
                    result_part_id = entry['ID']
                if entry['Mapped'] == 'true':
                    have_map = True

        if check_exist:
            return (check_exist, have_map, result_part_id)
        else:
            return (False, False, None)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume by volume copy."""

        volume_id = volume['id'].replace('-', '')
        #  Step1 create a snapshot of the volume
        src_part_id = self._extract_specific_provider_location(
            src_vref['provider_location'], 'partition_id')

        if src_part_id is None:
            src_part_id = self._get_part_id(volume_id)

        model_update = self._create_volume_from_volume(volume, src_part_id)

        LOG.info('Create Cloned Volume %(volume_id)s completed.', {
            'volume_id': volume['id']})
        return model_update

    def _create_volume_from_volume(self, dst_volume, src_part_id):
        # create the target volume for volume copy
        dst_volume_id = dst_volume['id'].replace('-', '')

        self._create_partition_by_default(dst_volume)

        dst_part_id = self._get_part_id(dst_volume_id)
        # prepare return value
        system_id = self._get_system_id(self.ip)
        model_dict = {
            'system_id': system_id,
            'partition_id': dst_part_id,
        }

        model_info = self._concat_provider_location(model_dict)
        model_update = {"provider_location": model_info}

        # clone the volume from the origin partition
        commands = (
            'Cinder-Cloned', 'part', src_part_id, 'part', dst_part_id
        )
        self._execute('CreateReplica', *commands)
        self._wait_replica_complete(dst_part_id)

        return model_update

    def _extract_specific_provider_location(self, provider_location, key):
        provider_location_dict = self._extract_all_provider_location(
            provider_location)

        result = provider_location_dict.get(key, None)
        return result

    @log_func
    def _extract_all_provider_location(self, provider_location):
        provider_location_dict = {}
        dict_entry = provider_location.split("@")
        for entry in dict_entry:
            key, value = entry.split('^', 1)
            if value == 'None':
                value = None
            provider_location_dict[key] = value

        return provider_location_dict

    def create_export(self, context, volume):
        model_update = volume['provider_location']

        LOG.info('Create export done from Volume %(volume_id)s.', {
            'volume_id': volume['id']})

        return {'provider_location': model_update}

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If refresh is True, update the status first.
        """
        if self._volume_stats is None or refresh:
            self._update_volume_stats()

        LOG.info(
            'Successfully update volume stats. '
            'backend: %(volume_backend_name)s, '
            'vendor: %(vendor_name)s, '
            'driver version: %(driver_version)s, '
            'storage protocol: %(storage_protocol)s.', self._volume_stats)

        return self._volume_stats

    def _update_volume_stats(self):

        backend_name = self.configuration.safe_get('volume_backend_name')

        data = {
            'volume_backend_name': backend_name,
            'vendor_name': 'Infortrend',
            'driver_version': self.VERSION,
            'storage_protocol': self.protocol,
            'pools': self._update_pools_stats(),
        }
        self._volume_stats = data

    def _update_pools_stats(self):
        enable_specs_dict = self._get_enable_specs_on_array()

        if 'Thin Provisioning' in enable_specs_dict.keys():
            provisioning = 'thin'
            provisioning_support = True
        else:
            provisioning = 'full'
            provisioning_support = False

        rc, part_list = self._execute('ShowPartition', '-l')
        rc, pools_info = self._execute('ShowLV')
        pools = []

        for pool in pools_info:
            if pool['Name'] in self.pool_list:
                total_space = float(pool['Size'].split(' ', 1)[0])
                available_space = float(pool['Available'].split(' ', 1)[0])

                total_capacity_gb = round(mi_to_gi(total_space), 2)
                free_capacity_gb = round(mi_to_gi(available_space), 2)
                provisioning_factor = self.configuration.safe_get(
                    'max_over_subscription_ratio')
                provisioned_space = self._get_provisioned_space(
                    pool['ID'], part_list)
                provisioned_capacity_gb = round(mi_to_gi(provisioned_space), 2)

                new_pool = {
                    'pool_name': pool['Name'],
                    'pool_id': pool['ID'],
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'reserved_percentage': 0,
                    'QoS_support': False,
                    'provisioned_capacity_gb': provisioned_capacity_gb,
                    'max_over_subscription_ratio': provisioning_factor,
                    'thin_provisioning_support': provisioning_support,
                    'thick_provisioning_support': True,
                    'infortrend_provisioning': provisioning,
                }
                pools.append(new_pool)
        return pools

    def _get_provisioned_space(self, pool_id, part_list):
        provisioning_space = 0
        for entry in part_list:
            if entry['LV-ID'] == pool_id:
                provisioning_space += int(entry['Size'])
        return provisioning_space

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Create Snapshot %(snapshot)s volume %(volume)s.',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        model_update = {}
        part_id = self._get_part_id(volume_id)

        if part_id is None:
            msg = _('Failed to get Partition ID for volume %(volume_id)s.') % {
                'volume_id': volume_id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        @lockutils.synchronized(
            'snapshot-' + part_id, 'infortrend-', True)
        def do_create_snapshot():
            self._execute('CreateSnapshot', 'part', part_id)
            rc, tmp_snapshot_list = self._execute(
                'ShowSnapshot', 'part=%s' % part_id)
            return tmp_snapshot_list

        snapshot_list = do_create_snapshot()

        LOG.info(
            'Create success. '
            'Snapshot: %(snapshot)s, '
            'Snapshot ID in raid: %(raid_snapshot_id)s, '
            'volume: %(volume)s.', {
                'snapshot': snapshot_id,
                'raid_snapshot_id': snapshot_list[-1]['SI-ID'],
                'volume': volume_id})
        model_update['provider_location'] = snapshot_list[-1]['SI-ID']
        return model_update

    def delete_snapshot(self, snapshot):
        """Delete the snapshot."""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Delete Snapshot %(snapshot)s volume %(volume)s.',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id:

            rc, replica_list = self._execute('ShowReplica', '-l')

            has_pair = self._delete_pair_with_snapshot(
                raid_snapshot_id, replica_list)

            if not has_pair:
                self._execute('DeleteSnapshot', raid_snapshot_id, '-y')

                LOG.info('Delete Snapshot %(snapshot_id)s completed.', {
                    'snapshot_id': snapshot_id})
            else:
                msg = _('Failed to delete snapshot '
                        'for snapshot_id: %s '
                        'because it has pair.') % snapshot_id
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            msg = _(
                'Failed to get Raid Snapshot ID '
                'from Snapshot %(snapshot_id)s.') % {
                    'snapshot_id': snapshot_id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_raid_snapshot_id(self, snapshot):
        if 'provider_location' not in snapshot:
            LOG.warning(
                'Failed to get Raid Snapshot ID and '
                'did not store in snapshot.')
            return
        return snapshot['provider_location']

    def _delete_pair_with_snapshot(self, snapshot_id, replica_list):
        has_pair = False
        for entry in replica_list:
            if entry['Source'] == snapshot_id:

                if not self._check_replica_completed(entry):
                    has_pair = True
                    LOG.warning(
                        'Snapshot still %(status)s Cannot delete snapshot.',
                        {'status': entry['Status']})
                else:
                    self._execute('DeleteReplica', entry['Pair-ID'], '-y')
        return has_pair

    def _get_part_id(self, volume_id, pool_id=None, part_list=None):
        if part_list is None:
            rc, part_list = self._execute('ShowPartition')
        for entry in part_list:
            if pool_id is None:
                if entry['Name'] == volume_id:
                    return entry['ID']
            else:
                if entry['Name'] == volume_id and entry['LV-ID'] == pool_id:
                    return entry['ID']
        return

    def create_volume_from_snapshot(self, volume, snapshot):
        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id is None:
            msg = _('Failed to get Raid Snapshot ID '
                    'from snapshot: %(snapshot_id)s.') % {
                        'snapshot_id': snapshot['id']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        src_part_id = self._check_snapshot_filled_block(raid_snapshot_id)

        model_update = self._create_volume_from_snapshot_id(
            volume, raid_snapshot_id, src_part_id)

        LOG.info(
            'Create Volume %(volume_id)s from '
            'snapshot %(snapshot_id)s completed.', {
                'volume_id': volume['id'],
                'snapshot_id': snapshot['id']})

        return model_update

    def _check_snapshot_filled_block(self, raid_snapshot_id):
        rc, snapshot_list = self._execute(
            'ShowSnapshot', 'si=%s' % raid_snapshot_id, '-l')

        if snapshot_list and snapshot_list[0]['Total-filled-block'] == '0':
            return snapshot_list[0]['Partition-ID']
        return

    def _create_volume_from_snapshot_id(
            self, dst_volume, raid_snapshot_id, src_part_id):
        # create the target volume for volume copy
        dst_volume_id = dst_volume['id'].replace('-', '')

        self._create_partition_by_default(dst_volume)

        dst_part_id = self._get_part_id(dst_volume_id)
        # prepare return value
        system_id = self._get_system_id(self.ip)
        model_dict = {
            'system_id': system_id,
            'partition_id': dst_part_id,
        }

        model_info = self._concat_provider_location(model_dict)
        model_update = {"provider_location": model_info}

        if src_part_id:
            # clone the volume from the origin partition
            commands = (
                'Cinder-Snapshot', 'part', src_part_id, 'part', dst_part_id
            )
            self._execute('CreateReplica', *commands)
            self._wait_replica_complete(dst_part_id)

        # clone the volume from the snapshot
        commands = (
            'Cinder-Snapshot', 'si', raid_snapshot_id, 'part', dst_part_id
        )
        self._execute('CreateReplica', *commands)
        self._wait_replica_complete(dst_part_id)

        return model_update

    @lockutils.synchronized('connection', 'infortrend-', True)
    def initialize_connection(self, volume, connector):
        if self.protocol == 'iSCSI':
            multipath = connector.get('multipath', False)
            return self._initialize_connection_iscsi(
                volume, connector, multipath)
        elif self.protocol == 'FC':
            return self._initialize_connection_fc(
                volume, connector)
        else:
            msg = _('Unknown protocol: %(protocol)s.') % {
                'protocol': self.protocol}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _initialize_connection_fc(self, volume, connector):
        self._init_map_info(True)
        self._update_map_info(True)

        map_lun, target_wwpns, initiator_target_map = (
            self._do_fc_connection(volume, connector)
        )

        properties = self._generate_fc_connection_properties(
            map_lun, target_wwpns, initiator_target_map)

        LOG.info('Successfully initialized connection. '
                 'target_wwn: %(target_wwn)s, '
                 'initiator_target_map: %(initiator_target_map)s, '
                 'lun: %(target_lun)s.', properties['data'])
        return properties

    def _do_fc_connection(self, volume, connector):
        volume_id = volume['id'].replace('-', '')
        target_wwpns = []

        partition_data = self._extract_all_provider_location(
            volume['provider_location'])
        part_id = partition_data['partition_id']

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        wwpn_list, wwpn_channel_info = self._get_wwpn_list()

        initiator_target_map, target_wwpns = self._build_initiator_target_map(
            connector, wwpn_list)

        map_lun = self._get_common_lun_map_id(wwpn_channel_info)

        # Sort items to get a reliable behaviour. Dictionary items
        # are iterated in a random order because of hash randomization.
        for initiator_wwpn in sorted(initiator_target_map):
            for target_wwpn in initiator_target_map[initiator_wwpn]:
                channel_id = wwpn_channel_info[target_wwpn.upper()]['channel']
                controller = wwpn_channel_info[target_wwpn.upper()]['slot']
                self._create_map_with_lun_filter(
                    part_id, channel_id, map_lun, initiator_wwpn,
                    controller=controller)

        return map_lun, target_wwpns, initiator_target_map

    def _build_initiator_target_map(self, connector, all_target_wwpns):
        initiator_target_map = {}
        target_wwpns = []

        if self.fc_lookup_service:
            lookup_map = (
                self.fc_lookup_service.get_device_mapping_from_network(
                    connector['wwpns'], all_target_wwpns)
            )
            for fabric_name in lookup_map:
                fabric = lookup_map[fabric_name]
                target_wwpns.extend(fabric['target_port_wwn_list'])
                for initiator in fabric['initiator_port_wwn_list']:
                    initiator_target_map[initiator] = (
                        fabric['target_port_wwn_list']
                    )
        else:
            initiator_wwns = connector['wwpns']
            target_wwpns = all_target_wwpns
            for initiator in initiator_wwns:
                initiator_target_map[initiator] = all_target_wwpns

        return initiator_target_map, target_wwpns

    def _generate_fc_connection_properties(
            self, lun_id, target_wwpns, initiator_target_map):

        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': int(lun_id),
                'target_wwn': target_wwpns,
                'initiator_target_map': initiator_target_map,
            },
        }

    @log_func
    def _initialize_connection_iscsi(self, volume, connector, multipath):
        self._init_map_info(multipath)
        self._update_map_info(multipath)

        volume_id = volume['id'].replace('-', '')

        partition_data = self._extract_all_provider_location(
            volume['provider_location'])  # system_id, part_id

        part_id = partition_data['partition_id']

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        self._set_host_iqn(connector['initiator'])

        map_chl, map_lun, mcs_id = self._get_mapping_info(multipath)

        lun_id = map_lun[0]

        if self.iscsi_multipath or multipath:
            channel_id = self._create_map_with_mcs(
                part_id, map_chl['slot_a'], lun_id, connector['initiator'])
        else:
            channel_id = map_chl['slot_a'][0]

            self._create_map_with_lun_filter(
                part_id, channel_id, lun_id, connector['initiator'])

        rc, net_list = self._execute('ShowNet')
        ip = self._get_ip_by_channel(channel_id, net_list)

        if ip is None:
            msg = _(
                'Failed to get ip on Channel %(channel_id)s '
                'with volume: %(volume_id)s.') % {
                    'channel_id': channel_id, 'volume_id': volume_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        partition_data = self._combine_channel_lun_target_id(
            partition_data, mcs_id, lun_id, channel_id)

        property_value = [{
            'lun_id': partition_data['lun_id'],
            'iqn': self._generate_iqn(partition_data),
            'ip': ip,
            'port': self.constants['ISCSI_PORT'],
        }]

        properties = self._generate_iscsi_connection_properties(
            property_value, volume)
        LOG.info('Successfully initialized connection '
                 'with volume: %(volume_id)s.', properties['data'])
        return properties

    @log_func
    def _combine_channel_lun_target_id(
            self, partition_data, mcs_id, lun_id, channel_id):

        target_id = self.target_dict['slot_a'][channel_id]

        partition_data['mcs_id'] = mcs_id
        partition_data['lun_id'] = lun_id
        partition_data['target_id'] = target_id
        partition_data['slot_id'] = 1

        return partition_data

    def _set_host_iqn(self, host_iqn):

        rc, iqn_list = self._execute('ShowIQN')

        check_iqn_exist = False
        for entry in iqn_list:
            if entry['IQN'] == host_iqn:
                check_iqn_exist = True

        if not check_iqn_exist:
            self._execute(
                'CreateIQN', host_iqn, self._truncate_host_name(host_iqn))

    def _truncate_host_name(self, iqn):
        if len(iqn) > 16:
            return iqn[-16:]
        else:
            return iqn

    @log_func
    def _generate_iqn(self, partition_data):
        return self.iqn % (
            partition_data['system_id'],
            partition_data['mcs_id'],
            partition_data['target_id'],
            partition_data['slot_id'])

    @log_func
    def _get_ip_by_channel(
            self, channel_id, net_list, controller='slot_a'):

        slot_name = 'slotA' if controller == 'slot_a' else 'slotB'

        for entry in net_list:
            if entry['ID'] == channel_id and entry['Slot'] == slot_name:
                return entry['IPv4']
        return

    def _get_wwpn_list(self):
        rc, wwn_list = self._execute('ShowWWN')

        wwpn_list = []
        wwpn_channel_info = {}

        for entry in wwn_list:
            channel_id = entry['CH']
            if 'BID' in entry['ID']:
                slot_name = 'slot_b'
            else:
                slot_name = 'slot_a'

            if channel_id in self.map_dict[slot_name]:
                wwpn_list.append(entry['WWPN'])

                wwpn_channel_info[entry['WWPN']] = {
                    'channel': channel_id,
                    'slot': slot_name,
                }

        return wwpn_list, wwpn_channel_info

    @log_func
    def _generate_iscsi_connection_properties(
            self, property_value, volume):

        properties = {}
        discovery_exist = False

        specific_property = property_value[0]

        discovery_ip = '%s:%s' % (
            specific_property['ip'], specific_property['port'])
        discovery_iqn = specific_property['iqn']

        if self._do_iscsi_discovery(discovery_iqn, discovery_ip):
            properties['target_portal'] = discovery_ip
            properties['target_iqn'] = discovery_iqn
            properties['target_lun'] = int(specific_property['lun_id'])
            discovery_exist = True

        if not discovery_exist:
            msg = _(
                'Could not find iSCSI target '
                'for volume: %(volume_id)s.') % {
                    'volume_id': volume['id']}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        properties['target_discovered'] = discovery_exist
        properties['volume_id'] = volume['id']

        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            if auth:
                (auth_method, auth_username, auth_secret) = auth.split()
                properties['auth_method'] = auth_method
                properties['auth_username'] = auth_username
                properties['auth_password'] = auth_secret

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    @log_func
    def _do_iscsi_discovery(self, target_iqn, target_ip):
        rc, out = self._execute(
            'ExecuteCommand',
            'iscsiadm', '-m', 'discovery',
            '-t', 'sendtargets', '-p',
            target_ip,
            run_as_root=True)

        if rc != 0:
            LOG.error(
                'Can not discovery in %(target_ip)s with %(target_iqn)s.',
                {'target_ip': target_ip, 'target_iqn': target_iqn})
            return False
        else:
            for target in out.splitlines():
                if target_iqn in target and target_ip in target:
                    return True
        return False

    def extend_volume(self, volume, new_size):
        volume_id = volume['id'].replace('-', '')

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        expand_size = new_size - volume['size']

        if '.' in ('%s' % expand_size):
            expand_size = round(gi_to_mi(float(expand_size)))
            expand_command = 'size=%sMB' % expand_size
        else:
            expand_command = 'size=%sGB' % expand_size

        self._execute('SetPartition', 'expand', part_id, expand_command)

        LOG.info(
            'Successfully extended volume %(volume_id)s to size %(size)s.', {
                'volume_id': volume['id'], 'size': new_size})

    @lockutils.synchronized('connection', 'infortrend-', True)
    def terminate_connection(self, volume, connector):
        volume_id = volume['id'].replace('-', '')
        multipath = connector.get('multipath', False)
        conn_info = None

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        self._execute('DeleteMap', 'part', part_id, '-y')
        map_info = self._update_map_info(multipath)

        if self.protocol == 'iSCSI':
            initiator_iqn = self._truncate_host_name(connector['initiator'])
            lun_map_exist = self._check_initiator_has_lun_map(
                initiator_iqn, map_info)

            if not lun_map_exist:
                self._execute('DeleteIQN', initiator_iqn)

        elif self.protocol == 'FC':
            conn_info = {'driver_volume_type': 'fibre_channel',
                         'data': {}}
            lun_map_exist = self._check_initiator_has_lun_map(
                connector['wwpns'], map_info)

            if not lun_map_exist:

                wwpn_list, wwpn_channel_info = self._get_wwpn_list()
                init_target_map, target_wwpns = (
                    self._build_initiator_target_map(connector, wwpn_list)
                )
                conn_info['data']['initiator_target_map'] = init_target_map

        LOG.info(
            'Successfully terminated connection for volume: %(volume_id)s.',
            {'volume_id': volume['id']})

        return conn_info

    def migrate_volume(self, volume, host, new_extraspecs=None):
        is_valid, dst_pool_id = (
            self._is_valid_for_storage_assisted_migration(host)
        )
        if not is_valid:
            return (False, None)

        model_dict = self._migrate_volume_with_pool(
            volume, dst_pool_id, new_extraspecs)

        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }

        LOG.info('Migrate Volume %(volume_id)s completed.', {
            'volume_id': volume['id']})

        return (True, model_update)

    def _is_valid_for_storage_assisted_migration(self, host):
        if 'pool_id' not in host['capabilities']:
            LOG.warning('Failed to get target pool id.')
            return (False, None)

        dst_pool_id = host['capabilities']['pool_id']
        if dst_pool_id is None:
            return (False, None)

        return (True, dst_pool_id)

    def _migrate_volume_with_pool(self, volume, dst_pool_id, extraspecs=None):
        volume_id = volume['id'].replace('-', '')

        # Get old partition data for delete map
        partition_data = self._extract_all_provider_location(
            volume['provider_location'])

        src_part_id = partition_data['partition_id']

        if src_part_id is None:
            src_part_id = self._get_part_id(volume_id)

        # Create New Partition
        self._create_partition_with_pool(volume, dst_pool_id, extraspecs)

        dst_part_id = self._get_part_id(
            volume_id, pool_id=dst_pool_id)

        if dst_part_id is None:
            msg = _('Failed to get new part id in new pool: %(pool_id)s.') % {
                'pool_id': dst_pool_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Volume Mirror from old partition into new partition
        commands = (
            'Cinder-Migrate', 'part', src_part_id, 'part', dst_part_id,
            'type=mirror'
        )
        self._execute('CreateReplica', *commands)

        self._wait_replica_complete(dst_part_id)

        self._execute('DeleteMap', 'part', src_part_id, '-y')
        self._execute('DeletePartition', src_part_id, '-y')

        model_dict = {
            'system_id': partition_data['system_id'],
            'partition_id': dst_part_id,
        }

        return model_dict

    def _wait_replica_complete(self, part_id):
        start_time = int(time.time())
        timeout = self._replica_timeout

        def _inner():
            check_done = False
            try:
                rc, replica_list = self._execute('ShowReplica', '-l')
                for entry in replica_list:
                    if (entry['Target'] == part_id and
                            self._check_replica_completed(entry)):
                        check_done = True
                        self._execute('DeleteReplica', entry['Pair-ID'], '-y')
            except Exception:
                check_done = False
                LOG.exception('Cannot detect replica status.')

            if check_done:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = _('Wait replica complete timeout.')
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=10).wait()

    def _check_extraspec_value(self, extraspec, validvalues):
        if not extraspec:
            LOG.debug("The given extraspec is None.")
        elif extraspec not in validvalues:
            msg = _("The extraspec: %(extraspec)s is not valid.") % {
                'extraspec': extraspec}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _get_enable_specs_on_array(self):
        enable_specs = {}
        rc, license_list = self._execute('ShowLicense')

        for key, value in license_list.items():
            if value['Support']:
                enable_specs[key] = value

        return enable_specs

    def manage_existing_get_size(self, volume, ref):
        """Return size of volume to be managed by manage_existing."""

        volume_name = self._get_existing_volume_ref_name(ref)
        part_entry = self._get_latter_volume_dict(volume_name)

        if part_entry is None:
            msg = _('Specified logical volume does not exist.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        rc, map_info = self._execute('ShowMap', 'part=%s' % part_entry['ID'])

        if len(map_info) != 0:
            msg = _('The specified volume is mapped to a host.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return int(math.ceil(mi_to_gi(float(part_entry['Size']))))

    def manage_existing(self, volume, ref):
        volume_name = self._get_existing_volume_ref_name(ref)
        volume_id = volume['id'].replace('-', '')

        part_entry = self._get_latter_volume_dict(volume_name)

        if part_entry is None:
            msg = _('Specified logical volume does not exist.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        self._execute('SetPartition', part_entry['ID'], 'name=%s' % volume_id)

        model_dict = {
            'system_id': self._get_system_id(self.ip),
            'partition_id': part_entry['ID'],
        }
        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }

        LOG.info('Rename Volume %(volume_id)s completed.', {
            'volume_id': volume['id']})

        return model_update

    def _get_existing_volume_ref_name(self, ref):
        volume_name = None
        if 'source-name' in ref:
            volume_name = ref['source-name']
        elif 'source-id' in ref:
            volume_name = self._get_unmanaged_volume_name(
                ref['source-id'].replace('-', ''))
        else:
            msg = _('Reference must contain source-id or source-name.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        return volume_name

    def unmanage(self, volume):
        volume_id = volume['id'].replace('-', '')
        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        new_vol_name = self._get_unmanaged_volume_name(volume_id)
        self._execute('SetPartition', part_id, 'name=%s' % new_vol_name)

        LOG.info('Unmanage volume %(volume_id)s completed.', {
            'volume_id': volume_id})

    def _get_unmanaged_volume_name(self, volume_id):
        return self.unmanaged_prefix % volume_id[:-17]

    def _get_specific_volume_dict(self, volume_id):
        ref_dict = {}
        rc, part_list = self._execute('ShowPartition')

        for entry in part_list:
            if entry['Name'] == volume_id:
                ref_dict = entry
                break

        return ref_dict

    def _get_latter_volume_dict(self, volume_name):
        rc, part_list = self._execute('ShowPartition', '-l')

        latest_timestamps = 0
        ref_dict = None

        for entry in part_list:
            if entry['Name'] == volume_name:

                timestamps = self._get_part_timestamps(
                    entry['Creation-time'])

                if timestamps > latest_timestamps:
                    ref_dict = entry
                    latest_timestamps = timestamps

        return ref_dict

    def _get_part_timestamps(self, time_string):
        """Transform 'Sat, Jan 11 22:18:40 2020' into timestamps with sec."""

        first, value = time_string.split(',')
        timestamps = time.mktime(
            time.strptime(value, " %b %d %H:%M:%S %Y"))

        return timestamps

    def _check_volume_attachment(self, volume):
        if not volume['volume_attachment']:
            return False
        return True

    def _check_volume_has_snapshot(self, volume):
        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        rc, snapshot_list = self._execute('ShowSnapshot', 'part=%s' % part_id)

        if len(snapshot_list) > 0:
            return True
        return False

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""

        if volume['host'] != host['host']:
            if self._check_volume_attachment(volume):
                LOG.warning(
                    'Volume %(volume_id)s cannot be retyped '
                    'during attachment.', {
                        'volume_id': volume['id']})
                return False

            if self._check_volume_has_snapshot(volume):
                LOG.warning(
                    'Volume %(volume_id)s cannot be retyped '
                    'because it has snapshot.', {
                        'volume_id': volume['id']})
                return False

            new_extraspecs = new_type['extra_specs']
            rc, model_update = self.migrate_volume(
                volume, host, new_extraspecs)

            if rc:
                LOG.info(
                    'Retype Volume %(volume_id)s is done '
                    'and migrated to pool %(pool_id)s.', {
                        'volume_id': volume['id'],
                        'pool_id': host['capabilities']['pool_id']})

            return (rc, model_update)
        else:
            if ('infortrend_provisioning' in diff['extra_specs'] and
                    (diff['extra_specs']['infortrend_provisioning'][0] !=
                        diff['extra_specs']['infortrend_provisioning'][1])):

                LOG.warning(
                    'The provisioning: %(provisioning)s is not valid.',
                    {'provisioning':
                     diff['extra_specs']['infortrend_provisioning'][1]})
                return False

            LOG.info('Retype Volume %(volume_id)s is completed.', {
                'volume_id': volume['id']})
            return True

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume."""

        src_volume_id = volume['id'].replace('-', '')
        dst_volume_id = new_volume['id'].replace('-', '')
        part_id = self._extract_specific_provider_location(
            new_volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(dst_volume_id)

        LOG.debug(
            'Rename partition %(part_id)s '
            'into new volume %(new_volume)s.', {
                'part_id': part_id, 'new_volume': dst_volume_id})
        try:
            self._execute('SetPartition', part_id, 'name=%s' % src_volume_id)
        except exception.InfortrendCliException:
            LOG.exception('Failed to rename %(new_volume)s into '
                          '%(volume)s.', {'new_volume': new_volume['id'],
                                          'volume': volume['id']})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}

        LOG.info('Update migrated volume %(new_volume)s completed.', {
            'new_volume': new_volume['id']})

        model_update = {
            '_name_id': None,
            'provider_location': new_volume['provider_location'],
        }
        return model_update
