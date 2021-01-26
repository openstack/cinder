#
# Copyright (c) 2016 NEC Corporation.
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

import re
import traceback

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.nec import cli
from cinder.volume.drivers.nec import volume_common
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


class MStorageDriver(volume_common.MStorageVolumeCommon):
    """M-Series Storage helper class."""

    def _convert_id2name(self, volume):
        ldname = (self.get_ldname(volume.id,
                                  self._properties['ld_name_format']))
        return ldname

    def _convert_id2snapname(self, volume):
        ldname = (self.get_ldname(volume.id,
                                  self._properties['ld_backupname_format']))
        return ldname

    def _convert_id2migratename(self, volume):
        ldname = self._convert_id2name(volume)
        ldname = ldname + '_m'
        return ldname

    def _convert_deleteldname(self, ldname):
        return ldname + '_d'

    def _select_ldnumber(self, used_ldns, max_ld_count):
        """Pick up unused LDN."""
        for ldn in range(0, max_ld_count + 1):
            if ldn not in used_ldns:
                break
        if ldn > max_ld_count - 1:
            msg = _('All Logical Disk Numbers are used. '
                    'No more volumes can be created.')
            raise exception.VolumeBackendAPIException(data=msg)
        return ldn

    def _return_poolnumber(self, nominated_pools):
        """Select pool form nominated pools."""
        selected_pool = -1
        min_ldn = 0
        for pool in nominated_pools:
            nld = len(pool['ld_list'])
            if selected_pool == -1 or min_ldn > nld:
                selected_pool = pool['pool_num']
                min_ldn = nld
        if selected_pool < 0:
            msg = _('No available pools found.')
            raise exception.VolumeBackendAPIException(data=msg)
        return selected_pool

    def _select_leastused_poolnumber(self, volume, pools,
                                     xml, option=None):
        """Pick up least used pool."""
        size = volume.size * units.Gi
        pools = [pool for (pn, pool) in pools.items()
                 if pool['free'] >= size and
                 (len(self._properties['pool_pools']) == 0 or
                  pn in self._properties['pool_pools'])]
        return self._return_poolnumber(pools)

    def _select_migrate_poolnumber(self, volume, pools, xml, host):
        """Pick up migration target pool."""
        tmpPools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))
        ldname = self.get_ldname(volume.id,
                                 self._properties['ld_name_format'])
        ld = lds[ldname]

        capabilities = host['capabilities']
        pools_string = capabilities.get('location_info').split(':')[1]
        destination_pools = list(map(int, pools_string.split(',')))

        size = volume.size * units.Gi
        pools = [pool for (pn, pool) in pools.items()
                 if pool['free'] >= size and
                 (len(destination_pools) == 0 or pn in destination_pools)]

        selected_pool = self._return_poolnumber(pools)
        if selected_pool == ld['pool_num']:
            # it is not necessary to create new volume.
            selected_pool = -1
        return selected_pool

    def _select_dsv_poolnumber(self, volume, pools, option=None):
        """Pick up backup pool for DSV."""
        pools = [pool for (pn, pool) in pools.items()
                 if pn in self._properties['pool_backup_pools']]
        return self._return_poolnumber(pools)

    def _select_ddr_poolnumber(self, volume, pools, xml, option):
        """Pick up backup pool for DDR."""
        size = option * units.Gi
        pools = [pool for (pn, pool) in pools.items()
                 if pool['free'] >= size and
                 pn in self._properties['pool_backup_pools']]
        return self._return_poolnumber(pools)

    def _select_volddr_poolnumber(self, volume, pools, xml, option):
        """Pick up backup pool for DDR."""
        size = option * units.Gi
        pools = [pool for (pn, pool) in pools.items()
                 if pool['free'] >= size and
                 pn in self._properties['pool_pools']]
        return self._return_poolnumber(pools)

    def _bind_ld(self, volume, capacity, validator,
                 nameselector, poolselector, option=None):
        return self._sync_bind_ld(volume, capacity, validator,
                                  nameselector, poolselector,
                                  self._properties['diskarray_name'],
                                  option)

    @coordination.synchronized('mstorage_bind_execute_{diskarray_name}')
    def _sync_bind_ld(self, volume, capacity, validator, nameselector,
                      poolselector, diskarray_name, option=None):
        """Get storage state and bind ld.

        volume: ld information
        capacity: capacity in GB
        validator: validate method(volume, xml)
        nameselector: select ld name method(volume)
        poolselector: select ld location method(volume, pools)
        diskarray_name: target diskarray name
        option: optional info
        """
        LOG.debug('_bind_ld Start.')
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # execute validator function.
        if validator is not None:
            result = validator(volume, xml)
            if result is False:
                msg = _('Invalid bind Logical Disk info.')
                raise exception.VolumeBackendAPIException(data=msg)

        # generate new ld name.
        ldname = nameselector(volume)
        # pick up least used pool and unused LDN.
        selected_pool = poolselector(volume, pools, xml, option)
        selected_ldn = self._select_ldnumber(used_ldns, max_ld_count)
        if selected_pool < 0 or selected_ldn < 0:
            LOG.debug('NOT necessary LD bind. '
                      'Name=%(name)s '
                      'Size=%(size)dGB '
                      'LDN=%(ldn)04xh '
                      'Pool=%(pool)04xh.',
                      {'name': ldname,
                       'size': capacity,
                       'ldn': selected_ldn,
                       'pool': selected_pool})
            return ldname, selected_ldn, selected_pool

        # bind LD.
        retnum, errnum = (self._cli.ldbind(ldname,
                                           selected_pool,
                                           selected_ldn,
                                           capacity))
        if retnum is False:
            if 'iSM31077' in errnum:
                msg = _('Logical Disk number is duplicated (%s).') % errnum
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Failed to bind Logical Disk (%s).') % errnum
                raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('LD bound. Name=%(name)s Size=%(size)dGB '
                  'LDN=%(ldn)04xh Pool=%(pool)04xh.',
                  {'name': ldname, 'size': capacity,
                   'ldn': selected_ldn, 'pool': selected_pool})
        return ldname, selected_ldn, selected_pool

    def _validate_ld_exist(self, lds, vol_id, name_format):
        ldname = self.get_ldname(vol_id, name_format)
        if ldname not in lds:
            msg = _('Logical Disk `%s` could not be found.') % ldname
            LOG.error(msg)
            raise exception.NotFound(msg)
        return ldname

    def _validate_iscsildset_exist(self, ldsets, connector):
        ldset = self.get_ldset(ldsets)
        if ldset is None:
            for tldset in ldsets.values():
                if 'initiator_list' not in tldset:
                    continue
                n = tldset['initiator_list'].count(connector['initiator'])
                if n > 0:
                    ldset = tldset
                    break
            if ldset is None:
                if self._properties['auto_accesscontrol']:
                    authname = connector['initiator'].strip()
                    authname = authname.replace((":"), "")
                    authname = authname.replace(("."), "")
                    new_ldsetname = authname[-16:]
                    ret = self._cli.addldset_iscsi(new_ldsetname, connector)
                    if ret is False:
                        msg = _('Appropriate Logical Disk Set'
                                ' could not be found.')
                        raise exception.NotFound(msg)
                    xml = self._cli.view_all(self._properties['ismview_path'])
                    pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
                        self.configs(xml))
                    ldset = self._validate_iscsildset_exist(ldsets, connector)
                else:
                    msg = _('Appropriate Logical Disk Set could not be found.')
                    raise exception.NotFound(msg)

        if len(ldset['portal_list']) < 1:
            msg = (_('Logical Disk Set `%s` has no portal.') %
                   ldset['ldsetname'])
            raise exception.NotFound(msg)
        return ldset

    def _validate_fcldset_exist(self, ldsets, connector):
        ldset = self.get_ldset(ldsets)
        if ldset is None:
            for conect in connector['wwpns']:
                length = len(conect)
                findwwpn = '-'.join([conect[i:i + 4]
                                     for i in range(0, length, 4)])
                findwwpn = findwwpn.upper()
                for tldset in ldsets.values():
                    if 'wwpn' in tldset and findwwpn in tldset['wwpn']:
                        ldset = tldset
                        break
                if ldset is not None:
                    break
            if ldset is None:
                if self._properties['auto_accesscontrol']:
                    new_ldsetname = connector['wwpns'][0][:16]
                    ret = self._cli.addldset_fc(new_ldsetname, connector)
                    if ret is False:
                        msg = _('Appropriate Logical Disk Set'
                                ' could not be found.')
                        raise exception.NotFound(msg)
                    xml = self._cli.view_all(self._properties['ismview_path'])
                    pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
                        self.configs(xml))
                    ldset = self._validate_fcldset_exist(ldsets, connector)
                else:
                    msg = _('Appropriate Logical Disk Set could not be found.')
                    raise exception.NotFound(msg)

        return ldset

    def _enumerate_iscsi_portals(self, hostports, ldset, prefered_director=0):
        portals = []
        for director in [prefered_director, 1 - prefered_director]:
            if director not in hostports:
                continue
            dirportals = []
            for port in hostports[director]:
                if not port['protocol'].lower() == 'iscsi':
                    continue
                for portal in ldset['portal_list']:
                    if portal.startswith(port['ip'] + ':'):
                        dirportals.append(portal)
                        break
            if (self._properties['portal_number'] > 0 and
                    len(dirportals) > self._properties['portal_number']):
                portals.extend(
                    dirportals[0:self._properties['portal_number']])
            else:
                portals.extend(dirportals)

        if len(portals) == 0:
            raise exception.NotFound(
                _('No portal matches to any host ports.'))

        return portals

    def create_volume(self, volume):
        msgparm = ('Volume ID = %(id)s, Size = %(size)dGB'
                   % {'id': volume.id, 'size': volume.size})
        try:
            self._create_volume(volume)
            LOG.info('Created Volume (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Create Volume (%(msgparm)s) '
                            '(%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _create_volume(self, volume):
        LOG.debug('_create_volume Start.')

        # select ld number and LD bind.
        ldname, ldn, selected_pool = self._bind_ld(
            volume,
            volume.size,
            None,
            self._convert_id2name,
            self._select_leastused_poolnumber)

        self._set_qos_spec(ldname, volume.volume_type_id)

        LOG.debug('LD bound. '
                  'Name=%(name)s '
                  'Size=%(size)dGB '
                  'LDN=%(ldn)04xh '
                  'Pool=%(pool)04xh.',
                  {'name': ldname,
                   'size': volume.size,
                   'ldn': ldn,
                   'pool': selected_pool})

    def _can_extend_capacity(self, new_size, pools, lds, ld):
        rvs = {}
        ld_count_in_pool = {}
        if ld['RPL Attribute'] == 'MV':
            pair_lds = self._cli.get_pair_lds(ld['ldname'], lds)
            for (ldn, pair_ld) in pair_lds.items():
                rv_name = pair_ld['ldname']
                pool_number = pair_ld['pool_num']
                ldn = pair_ld['ldn']
                rvs[ldn] = pair_ld
                # check rv status.
                query_status = self._cli.query_MV_RV_status(rv_name[3:], 'RV')
                if query_status != 'separated':
                    msg = (_('Specified Logical Disk %s has been copied.') %
                           rv_name)
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                # get pool number.
                if pool_number in ld_count_in_pool:
                    ld_count_in_pool[pool_number].append(ldn)
                else:
                    ld_count_in_pool[pool_number] = [ldn]

        # check pool capacity.
        for (pool_number, tmp_ldn_list) in ld_count_in_pool.items():
            ld_capacity = (
                ld['ld_capacity'] * units.Gi)
            new_size_byte = new_size * units.Gi
            size_increase = new_size_byte - ld_capacity
            pool = pools[pool_number]
            ld_count = len(tmp_ldn_list)
            if pool['free'] < size_increase * ld_count:
                msg = (_('Not enough pool capacity. '
                         'pool_number=%(pool)d, size_increase=%(sizeinc)d') %
                       {'pool': pool_number,
                        'sizeinc': size_increase * ld_count})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return rvs

    def extend_volume(self, volume, new_size):
        msgparm = ('Volume ID = %(id)s, New Size = %(newsize)dGB, '
                   'Old Size = %(oldsize)dGB'
                   % {'id': volume.id, 'newsize': new_size,
                      'oldsize': volume.size})
        try:
            self._extend_volume(volume, new_size)
            LOG.info('Extended Volume (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Extend Volume (%(msgparm)s) '
                            '(%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _extend_volume(self, volume, new_size):
        LOG.debug('_extend_volume(Volume ID = %(id)s, '
                  'new_size = %(size)s) Start.',
                  {'id': volume.id, 'size': new_size})

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get volume.
        ldname = self._validate_ld_exist(
            lds, volume.id, self._properties['ld_name_format'])
        ld = lds[ldname]
        ldn = ld['ldn']

        # check pools capacity.
        rvs = self._can_extend_capacity(new_size, pools, lds, ld)

        # volume expand.
        self._cli.expand(ldn, new_size)

        # rv expand.
        if ld['RPL Attribute'] == 'MV':
            # ld expand.
            for (ldn, rv) in rvs.items():
                self._cli.expand(ldn, new_size)
        elif ld['RPL Attribute'] != 'IV':
            msg = (_('RPL Attribute Error. RPL Attribute = %s.')
                   % ld['RPL Attribute'])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('_extend_volume(Volume ID = %(id)s, '
                  'new_size = %(newsize)s) End.',
                  {'id': volume.id, 'newsize': new_size})

    def create_cloned_volume(self, volume, src_vref):
        msgparm = ('Volume ID = %(id)s, '
                   'Source Volume ID = %(src_id)s'
                   % {'id': volume.id,
                      'src_id': src_vref.id})
        try:
            self._create_cloned_volume(volume, src_vref)
            LOG.info('Created Cloned Volume (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Create Cloned Volume '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug('_create_cloned_volume'
                  '(Volume ID = %(id)s, Source ID = %(src_id)s ) Start.',
                  {'id': volume.id, 'src_id': src_vref.id})

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # check MV existence and get MV info.
        source_name = (
            self.get_ldname(src_vref.id,
                            self._properties['ld_name_format']))
        if source_name not in lds:
            msg = (_('Logical Disk `%(name)s` has unbound already. '
                     'volume_id = %(id)s.') %
                   {'name': source_name, 'id': src_vref.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        source_ld = lds[source_name]

        # check temporarily released pairs existence.
        if source_ld['RPL Attribute'] == 'MV':
            # get pair lds.
            pair_lds = self._cli.get_pair_lds(source_name, lds)
            if len(pair_lds) == 3:
                msg = (_('Cannot create clone volume. '
                         'number of pairs reached 3. '
                         'ldname=%s') % source_name)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # Creating Cloned Volume.
        volume_name, ldn, selected_pool = self._bind_ld(
            volume,
            src_vref.size,
            None,
            self._convert_id2name,
            self._select_leastused_poolnumber)

        self._set_qos_spec(volume_name, volume.volume_type_id)

        LOG.debug('LD bound. Name=%(name)s '
                  'Size=%(size)dGB '
                  'LDN=%(ldn)04xh '
                  'Pool=%(pool)04xh.',
                  {'name': volume_name,
                   'size': volume.size,
                   'ldn': ldn,
                   'pool': selected_pool})
        LOG.debug('source_name=%(src_name)s, volume_name=%(name)s.',
                  {'src_name': source_name, 'name': volume_name})

        # compare volume size and copy data to RV.
        mv_capacity = src_vref.size
        rv_capacity = volume.size
        if rv_capacity <= mv_capacity:
            rv_capacity = None

        volume_properties = {
            'mvname': source_name,
            'rvname': volume_name,
            'capacity': mv_capacity,
            'mvid': src_vref.id,
            'rvid': volume.id,
            'rvldn': ldn,
            'rvcapacity': rv_capacity,
            'flag': 'clone',
            'context': self._context
        }
        self._cli.backup_restore(volume_properties, cli.UnpairWaitForClone)
        LOG.debug('_create_cloned_volume(Volume ID = %(id)s, '
                  'Source ID = %(src_id)s ) End.',
                  {'id': volume.id, 'src_id': src_vref.id})

    def _set_qos_spec(self, ldname, volume_type_id, reset=False):
        # check io limit.
        specs = self.get_volume_type_qos_specs(volume_type_id)
        qos_params = self.get_qos_parameters(specs, reset)

        # set io limit.
        self._cli.set_io_limit(ldname, qos_params)
        LOG.debug('_set_qos_spec(Specs = %s) End.', qos_params)

        return

    def _validate_migrate_volume(self, volume, xml):
        """Validate source volume information."""
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get ld object
        ldname = self._validate_ld_exist(
            lds, volume.id, self._properties['ld_name_format'])

        # check rpl attribute.
        ld = lds[ldname]
        if ld['Purpose'] != '---':
            msg = (_('Specified Logical Disk %(ld)s '
                     'has an invalid attribute (%(purpose)s).')
                   % {'ld': ldname, 'purpose': ld['Purpose']})
            raise exception.VolumeBackendAPIException(data=msg)
        return True

    def migrate_volume(self, context, volume, host):
        msgparm = ('Volume ID = %(id)s, '
                   'Destination Host = %(dsthost)s'
                   % {'id': volume.id,
                      'dsthost': host})
        try:
            ret = self._migrate_volume(context, volume, host)
            if ret != (False, None):
                LOG.info('Migrated Volume (%s)', msgparm)
            else:
                LOG.debug('Failed to Migrate Volume (%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Migrate Volume '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.
        """
        LOG.debug('_migrate_volume('
                  'Volume ID = %(id)s, '
                  'Volume Name = %(name)s, '
                  'host = %(host)s) Start.',
                  {'id': volume.id,
                   'name': volume.name,
                   'host': host})

        false_ret = (False, None)

        # check volume status.
        if volume.status != 'available':
            LOG.debug('Specified volume %s is not available.', volume.id)
            return false_ret

        if 'capabilities' not in host:
            LOG.debug('Host not in capabilities. Host = %s ', host)
            return false_ret

        capabilities = host['capabilities']
        if capabilities.get('vendor_name') != self._properties['vendor_name']:
            LOG.debug('Vendor is not %(vendor)s. '
                      'capabilities = %(capabilities)s ',
                      {'vendor': self._properties['vendor_name'],
                       'capabilities': capabilities})
            return false_ret

        # another storage configuration is not supported.
        destination_fip = capabilities.get('location_info').split(':')[0]
        if destination_fip != self._properties['cli_fip']:
            LOG.debug('FIP is mismatch. FIP = %(destination)s != %(fip)s',
                      {'destination': destination_fip,
                       'fip': self._properties['cli_fip']})
            return false_ret

        self._migrate(volume, host, volume.volume_type_id,
                      self._validate_migrate_volume,
                      self._select_migrate_poolnumber)

        LOG.debug('_migrate_volume(Volume ID = %(id)s, '
                  'Host = %(host)s) End.',
                  {'id': volume.id, 'host': host})

        return (True, [])

    def _validate_retype_volume(self, volume, xml):
        """Validate source volume information."""
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get ld object
        ldname = self._validate_ld_exist(
            lds, volume.id, self._properties['ld_name_format'])

        # check rpl attribute.
        ld = lds[ldname]
        if ld['Purpose'] != '---':
            msg = (_('Specified Logical Disk %(ld)s '
                     'has an invalid attribute (%(purpose)s).')
                   % {'ld': ldname, 'purpose': ld['Purpose']})
            raise exception.VolumeBackendAPIException(data=msg)
        return True

    def _spec_is_changed(self, specdiff, resname):
        res = specdiff.get(resname)
        if (res is not None and res[0] != res[1]):
            return True
        return False

    def _check_same_backend(self, diff):
        if self._spec_is_changed(diff['extra_specs'], 'volume_backend_name'):
            return False

        if len(diff['extra_specs']) > 1:
            return False

        return True

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to the specified volume type.

        :param context: The context used to run the method retype
        :param volume: The original volume that was retype to this backend
        :param new_type: The new volume type
        :param diff: The difference between the two types
        :param host: The target information
        :returns: a boolean indicating whether the migration occurred, and
                  model_update
        """
        msgparm = ('Volume ID = %(id)s, '
                   'New Type = %(type)s, '
                   'Diff = %(diff)s, '
                   'Destination Host = %(dsthost)s'
                   % {'id': volume.id,
                      'type': new_type,
                      'diff': diff,
                      'dsthost': host})
        try:
            ret = self._retype(context, volume, new_type, diff, host)
            if ret is not False:
                LOG.info('Retyped Volume (%s)', msgparm)
            else:
                LOG.debug('Failed to Retype Volume (%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Retype Volume '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _retype(self, context, volume, new_type, diff, host):
        """Retype the volume to the specified volume type.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.
        """
        LOG.debug('_retype('
                  'Volume ID = %(id)s, '
                  'Volume Name = %(name)s, '
                  'New Type = %(type)s, '
                  'Diff = %(diff)s, '
                  'host = %(host)s) Start.',
                  {'id': volume.id,
                   'name': volume.name,
                   'type': new_type,
                   'diff': diff,
                   'host': host})

        # check volume attach status.
        if volume.attach_status == 'attached':
            LOG.debug('Specified volume %s is attached.', volume.id)
            return False

        if self._check_same_backend(diff):
            ldname = self._convert_id2name(volume)
            reset = (diff['qos_specs'].get('consumer')[0] == 'back-end')
            self._set_qos_spec(ldname, new_type['id'], reset)
            LOG.debug('_retype(QoS setting only)(Volume ID = %(id)s, '
                      'Host = %(host)s) End.',
                      {'id': volume.id, 'host': host})
            return True

        self._migrate(volume,
                      host,
                      new_type['id'],
                      self._validate_retype_volume,
                      self._select_leastused_poolnumber)

        LOG.debug('_retype(Volume ID = %(id)s, '
                  'Host = %(host)s) End.',
                  {'id': volume.id, 'host': host})

        return True

    def _migrate(self, volume, host, volume_type_id, validator, pool_selecter):

        # bind LD.
        rvname, __, selected_pool = self._bind_ld(
            volume,
            volume.size,
            validator,
            self._convert_id2migratename,
            pool_selecter,
            host)

        if selected_pool >= 0:
            self._set_qos_spec(rvname, volume_type_id)

            volume_properties = {
                'mvname':
                    self.get_ldname(
                        volume.id, self._properties['ld_name_format']),
                'rvname': rvname,
                'capacity':
                    volume.size * units.Gi,
                'mvid': volume.id,
                'rvid': None,
                'flag': 'migrate',
                'context': self._context
            }
            # replicate LD.
            self._cli.backup_restore(volume_properties,
                                     cli.UnpairWaitForMigrate)
        return

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Updates metadata after host-assisted migration.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        LOG.debug('update_migrated_volume'
                  '(Volume ID = %(id)s, New Volume ID = %(new_id)s, '
                  'Status = %(status)s) Start.',
                  {'id': volume.id, 'new_id': new_volume.id,
                   'status': original_volume_status})

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        name_id = None
        provider_location = None
        if original_volume_status in ['available', 'in-use']:
            original_name = self._convert_id2name(volume)
            new_name = self._convert_id2name(new_volume)
            try:
                if original_name in lds:
                    delete_ldname = self._convert_deleteldname(original_name)
                    self._cli.changeldname(None, delete_ldname, original_name)
                self._cli.changeldname(None, original_name, new_name)
            except exception.CinderException as e:
                LOG.warning('Unable to rename the logical volume '
                            '(Volume ID = %(id)s), (%(exception)s)',
                            {'id': volume.id, 'exception': e})
                # If the rename fails, _name_id should be set to the new
                # volume id and provider_location should be set to the
                # one from the new volume as well.
                name_id = new_volume._name_id or new_volume.id
                provider_location = new_volume.provider_location
        else:
            # The back-end will not be renamed.
            name_id = new_volume._name_id or new_volume.id
            provider_location = new_volume.provider_location

        LOG.debug('update_migrated_volume(name_id = %(name_id)s, '
                  'provider_location = %(location)s) End.',
                  {'name_id': name_id, 'location': provider_location})

        return {'_name_id': name_id, 'provider_location': provider_location}

    def check_for_export(self, context, volume_id):
        pass

    def backup_use_temp_snapshot(self):
        return True

    def _get_free_lun(self, ldset):
        # Lun can't be specified when multi target mode.
        if ldset['protocol'] == 'iSCSI' and ldset['mode'] == 'Multi-Target':
            return None
        # get free lun.
        luns = []
        ldsetlds = ldset['lds']
        for ld in ldsetlds.values():
            luns.append(ld['lun'])
        target_lun = 0
        for lun in sorted(luns):
            if target_lun < lun:
                break
            target_lun += 1
        return target_lun

    def create_export(self, context, volume, connector):
        pass

    def create_export_snapshot(self, context, snapshot, connector):
        pass

    @coordination.synchronized('mstorage_bind_execute_{diskarray_name}')
    def _create_snapshot_and_link(self, snapshot, connector, diskarray_name,
                                  validate_ldset_exist):
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        LOG.debug('validate data.')
        svname = self._validate_ld_exist(
            lds, snapshot.id, self._properties['ld_name_format'])
        bvname = self._validate_ld_exist(
            lds, snapshot.volume_id, self._properties['ld_name_format'])
        lvname = svname + '_l'
        ldset = validate_ldset_exist(ldsets, connector)
        svstatus = self._cli.query_BV_SV_status(bvname[3:], svname[3:])
        if svstatus != 'snap/active':
            msg = _('Logical Disk (%s) is invalid snapshot.') % svname
            raise exception.VolumeBackendAPIException(data=msg)
        lvldn = self._select_ldnumber(used_ldns, max_ld_count)

        LOG.debug('configure backend.')
        lun0 = [ld for (ldn, ld) in ldset['lds'].items() if ld['lun'] == 0]
        # NEC Storage cannot create an LV with LUN 0.
        # Create a CV with LUN 0 to use the other LUN for an LV.
        if not lun0:
            LOG.debug('create and attach control volume.')
            used_ldns.append(lvldn)
            cvldn = self._select_ldnumber(used_ldns, max_ld_count)
            self._cli.cvbind(lds[bvname]['pool_num'], cvldn)
            self._cli.changeldname(cvldn,
                                   self._properties['cv_name_format'] % cvldn)
            self._cli.addldsetld(ldset['ldsetname'],
                                 self._properties['cv_name_format'] % cvldn,
                                 self._get_free_lun(ldset))
            xml = self._cli.view_all(self._properties['ismview_path'])
            pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
                self.configs(xml))
            ldset = validate_ldset_exist(ldsets, connector)

        self._cli.lvbind(bvname, lvname[3:], lvldn)
        self._cli.lvlink(svname[3:], lvname[3:])
        self._cli.addldsetld(ldset['ldsetname'], lvname,
                             self._get_free_lun(ldset))
        LOG.debug('Add LD `%(ld)s` to LD Set `%(ldset)s`.',
                  {'ld': lvname, 'ldset': ldset['ldsetname']})
        return lvname

    def remove_export(self, context, volume):
        pass

    def _detach_from_all(self, ldname, xml):
        LOG.debug('_detach_from_all Start.')
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get target LD Set.
        ldset = self.get_ldset(ldsets)

        ld = lds[ldname]
        ldsetlist = []

        if ldset is None:
            for tldset in ldsets.values():
                if ld['ldn'] in tldset['lds']:
                    ldsetlist.append(tldset)
                    LOG.debug('ldset=%s.', tldset)
            if len(ldsetlist) == 0:
                return False
        else:
            if ld['ldn'] not in ldset['lds']:
                LOG.debug('LD `%(ld)s` already deleted '
                          'from LD Set `%(ldset)s`?',
                          {'ld': ldname, 'ldset': ldset['ldsetname']})
                return False
            ldsetlist.append(ldset)

        # delete LD from LD set.
        for tagetldset in ldsetlist:
            retnum, errnum = (self._cli.delldsetld(
                tagetldset['ldsetname'], ldname))

            if retnum is not True:
                if 'iSM31065' in errnum:
                    LOG.debug(
                        'LD `%(ld)s` already deleted '
                        'from LD Set `%(ldset)s`?',
                        {'ld': ldname, 'ldset': tagetldset['ldsetname']})
                else:
                    msg = (_('Failed to unregister Logical Disk from '
                             'Logical Disk Set (%s)') % errnum)
                    raise exception.VolumeBackendAPIException(data=msg)
            LOG.debug('LD `%(ld)s` deleted from LD Set `%(ldset)s`.',
                      {'ld': ldname, 'ldset': tagetldset['ldsetname']})

        LOG.debug('_detach_from_all(LD Name = %s) End.', ldname)
        return True

    def remove_export_snapshot(self, context, snapshot):
        """Removes an export for a snapshot."""
        msgparm = 'Snapshot ID = %s' % snapshot.id
        try:
            self._remove_export_snapshot(context, snapshot)
            LOG.info('Removed Export Snapshot(%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Remove Export Snapshot'
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _remove_export_snapshot(self, context, snapshot):
        LOG.debug('_remove_export_snapshot(Snapshot ID = %s) Start.',
                  snapshot.id)
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        LOG.debug('validate data.')
        svname = self._validate_ld_exist(
            lds, snapshot.id, self._properties['ld_name_format'])
        lvname = svname + '_l'
        if lvname not in lds:
            LOG.debug('Logical Disk `%s` is already unexported.', lvname)
            return

        ld = lds[lvname]
        ldsetlist = []
        if ld is None:
            msg = _('Exported snapshot could not be found.')
            raise exception.VolumeBackendAPIException(data=msg)
        for tldset in ldsets.values():
            if ld['ldn'] in tldset['lds']:
                ldsetlist.append(tldset)
        if len(ldsetlist) == 0:
            LOG.debug('Specified Logical Disk is already removed.')
            return

        LOG.debug('configure backend.')
        for tagetldset in ldsetlist:
            retnum, errnum = self._cli.delldsetld(tagetldset['ldsetname'],
                                                  lvname)
            if retnum is not True:
                msg = (_('Failed to remove export Logical Disk from '
                         'Logical Disk Set (%s)') % errnum)
                raise exception.VolumeBackendAPIException(data=msg)
            LOG.debug('LD `%(ld)s` deleted from LD Set `%(ldset)s`.',
                      {'ld': lvname, 'ldset': tagetldset['ldsetname']})

        try:
            self._cli.lvunlink(lvname[3:])
        except Exception:
            LOG.debug('LV unlink error.')

        try:
            self._cli.lvunbind(lvname)
        except Exception:
            LOG.debug('LV unbind error.')

        LOG.debug('_remove_export_snapshot(Snapshot ID = %s) End.',
                  snapshot.id)

    @coordination.synchronized('mstorage_bind_execute_{diskarray_name}')
    def _export_volume(self, volume, connector, diskarray_name,
                       validate_exist):
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))
        ldset = validate_exist(ldsets, connector)
        ldname = self.get_ldname(
            volume.id, self._properties['ld_name_format'])
        if ldname not in lds:
            msg = _('Logical Disk `%s` could not be found.') % ldname
            raise exception.NotFound(msg)
        ld = lds[ldname]
        if ld['ldn'] not in ldset['lds']:
            self._cli.addldsetld(ldset['ldsetname'], ldname,
                                 self._get_free_lun(ldset))
            # update local info.
            LOG.debug('Add LD `%(ld)s` to LD Set `%(ldset)s`.',
                      {'ld': ldname, 'ldset': ldset['ldsetname']})

        return ldname

    def iscsi_initialize_connection(self, volume, connector):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': volume.id, 'connector': connector})

        try:
            ret = self._iscsi_initialize_connection(volume, connector)
            LOG.info('Initialized iSCSI Connection (%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Initialize iSCSI Connection '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _iscsi_initialize_connection(self, volume, connector,
                                     is_snapshot=False):
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
                    'access_mode': 'rw'
                }
            }

        """
        LOG.debug('_iscsi_initialize_connection'
                  '(Volume ID = %(id)s, connector = %(connector)s, '
                  'snapshot = %(snapshot)s) Start.',
                  {'id': volume.id, 'connector': connector,
                   'snapshot': is_snapshot})

        # configure access control
        if is_snapshot:
            ldname = self._create_snapshot_and_link(
                volume, connector,
                self._properties['diskarray_name'],
                self._validate_iscsildset_exist)
        else:
            ldname = self._export_volume(volume, connector,
                                         self._properties['diskarray_name'],
                                         self._validate_iscsildset_exist)

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # enumerate portals for iscsi multipath.
        ld = lds[ldname]
        ldset = self._validate_iscsildset_exist(ldsets, connector)
        prefered_director = ld['pool_num'] % 2
        portals = self._enumerate_iscsi_portals(hostports, ldset,
                                                prefered_director)

        info = {'driver_volume_type': 'iscsi',
                'data': {'target_portal':
                         portals[int(volume.id[:1], 16) % len(portals)],
                         'target_iqn': ldset['lds'][ld['ldn']]['iqn'],
                         'target_lun': ldset['lds'][ld['ldn']]['lun'],
                         'target_discovered': False,
                         'volume_id': volume.id}
                }
        if connector.get('multipath'):
            portals_len = len(portals)
            info['data'].update({'target_portals': portals,
                                 'target_iqns': [ldset['lds'][ld['ldn']]
                                                 ['iqn']] * portals_len,
                                 'target_luns': [ldset['lds'][ld['ldn']]
                                                 ['lun']] * portals_len})
        LOG.debug('_iscsi_initialize_connection'
                  '(Volume ID = %(id)s, connector = %(connector)s, '
                  'info = %(info)s) End.',
                  {'id': volume.id,
                   'connector': connector,
                   'info': info})
        return info

    def iscsi_initialize_connection_snapshot(self, snapshot, connector,
                                             **kwargs):
        """Allow connection to connector and return connection info.

        :param snapshot: The snapshot to be attached
        :param connector: Dictionary containing information about what
                          is being connected to.
        :returns conn_info: A dictionary of connection information. This
                            can optionally include a "initiator_updates"
                            field.
        """
        msgparm = ('Snapshot ID = %(id)s, Connector = %(connector)s'
                   % {'id': snapshot.id, 'connector': connector})

        try:
            ret = self._iscsi_initialize_connection(snapshot, connector,
                                                    is_snapshot=True)
            LOG.info('Initialized iSCSI Connection snapshot(%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Initialize iSCSI Connection snapshot'
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})
        return ret

    @coordination.synchronized('mstorage_iscsi_terminate_{volume.id}')
    def iscsi_terminate_connection(self, volume, connector):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': volume.id, 'connector': connector})

        try:
            self._iscsi_terminate_connection(volume, connector)
            LOG.info('Terminated iSCSI Connection (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Terminate iSCSI Connection '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _iscsi_terminate_connection(self, volume, connector):
        if self._properties['ldset_name'] != '':
            LOG.debug('Ldset is specified. Access control setting '
                      'is not deleted automatically.')
            return

        if connector is None:
            LOG.debug('Connector is not specified. Nothing to do.')
            return

        if self._is_multi_attachment(volume, connector):
            return

        # delete unused access control setting.
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        ldname = self.get_ldname(
            volume.id, self._properties['ld_name_format'])
        if ldname not in lds:
            LOG.debug('Logical Disk `%s` has unbound already.', ldname)
            return

        ldset = self._validate_iscsildset_exist(ldsets, connector)
        retnum, errnum = self._cli.delldsetld(ldset['ldsetname'], ldname)
        if retnum is not True:
            if 'iSM31065' in errnum:
                LOG.debug('LD `%(ld)s` already deleted '
                          'from LD Set `%(ldset)s`?',
                          {'ld': ldname, 'ldset': ldset['ldsetname']})
            else:
                msg = (_('Failed to unregister Logical Disk from '
                         'Logical Disk Set (%s)') % errnum)
                raise exception.VolumeBackendAPIException(data=msg)
        LOG.debug('LD `%(ld)s` deleted from LD Set `%(ldset)s`.',
                  {'ld': ldname, 'ldset': ldset['ldsetname']})

    def iscsi_terminate_connection_snapshot(self, snapshot, connector,
                                            **kwargs):
        """Disallow connection from connector."""
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': snapshot.id, 'connector': connector})
        self.remove_export_snapshot(None, snapshot)
        LOG.info('Terminated iSCSI Connection snapshot(%s)', msgparm)

    def fc_initialize_connection(self, volume, connector):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': volume.id, 'connector': connector})

        try:
            ret = self._fc_initialize_connection(volume, connector)
            LOG.info('Initialized FC Connection (%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Initialize FC Connection '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _fc_initialize_connection(self, volume, connector, is_snapshot=False):
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
                    'access_mode': 'rw'
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                    'access_mode': 'rw'
                }
            }
        """

        LOG.debug('_fc_initialize_connection'
                  '(Volume ID = %(id)s, connector = %(connector)s, '
                  'snapshot = %(snapshot)s) Start.',
                  {'id': volume.id, 'connector': connector,
                   'snapshot': is_snapshot})

        if is_snapshot:
            ldname = self._create_snapshot_and_link(
                volume, connector,
                self._properties['diskarray_name'],
                self._validate_fcldset_exist)
        else:
            ldname = self._export_volume(volume, connector,
                                         self._properties['diskarray_name'],
                                         self._validate_fcldset_exist)

        # update local info.
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get target wwpns and initiator/target map.
        fc_ports = []
        for director, hostport in hostports.items():
            for port in hostport:
                if port['protocol'].lower() == 'fc':
                    fc_ports.append(port)
        target_wwns, init_targ_map = (
            self._build_initiator_target_map(connector, fc_ports))

        # get link volume number
        ldname = self.get_ldname(
            volume.id, self._properties['ld_name_format'])
        lvname = ldname + '_l'
        if lvname in lds:
            ldn = lds[lvname]['ldn']
        else:
            ldn = lds[ldname]['ldn']

        ldset = self._validate_fcldset_exist(ldsets, connector)

        info = {
            'driver_volume_type': 'fibre_channel',
            'data': {'target_lun': ldset['lds'][ldn]['lun'],
                     'target_wwn': target_wwns,
                     'initiator_target_map': init_targ_map}}

        LOG.debug('_fc_initialize_connection'
                  '(Volume ID = %(id)s, connector = %(connector)s, '
                  'info = %(info)s) End.',
                  {'id': volume.id,
                   'connector': connector,
                   'info': info})
        return info

    def fc_initialize_connection_snapshot(self, snapshot, connector):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': snapshot.id, 'connector': connector})

        try:
            ret = self._fc_initialize_connection(snapshot, connector,
                                                 is_snapshot=True)
            LOG.info('Initialized FC Connection snapshot(%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Initialize FC Connection snapshot'
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    @coordination.synchronized('mstorage_fc_terminate_{volume.id}')
    def fc_terminate_connection(self, volume, connector):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': volume.id, 'connector': connector})

        try:
            ret = self._fc_terminate_connection(volume, connector)
            LOG.info('Terminated FC Connection (%s)', msgparm)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Terminate FC Connection '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    @volume_utils.trace
    def _fc_terminate_connection(self, vol_or_snap, connector,
                                 is_snapshot=False):
        """Disallow connection from connector."""
        if not is_snapshot and connector is not None and (
           self._is_multi_attachment(vol_or_snap, connector)):
            return

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get target wwpns and initiator/target map.
        fc_ports = []
        for director, hostport in hostports.items():
            for port in hostport:
                if port['protocol'].lower() == 'fc':
                    fc_ports.append(port)

        info = {'driver_volume_type': 'fibre_channel',
                'data': {}}
        if connector is not None:
            target_wwns, init_targ_map = (
                self._build_initiator_target_map(connector, fc_ports))
            info['data'] = {'target_wwn': target_wwns,
                            'initiator_target_map': init_targ_map}

        if is_snapshot:
            # Detaching the snapshot is performed in the
            # remove_export_snapshot.
            return info

        if connector is not None and self._properties['ldset_name'] == '':
            # delete LD from LD set.
            ldname = self.get_ldname(
                vol_or_snap.id, self._properties['ld_name_format'])
            if ldname not in lds:
                LOG.debug('Logical Disk `%s` has unbound already.', ldname)
                return info

            ldset = self._validate_fcldset_exist(ldsets, connector)
            retnum, errnum = self._cli.delldsetld(ldset['ldsetname'], ldname)
            if retnum is not True:
                if 'iSM31065' in errnum:
                    LOG.debug('LD `%(ld)s` already deleted '
                              'from LD Set `%(ldset)s`?',
                              {'ld': ldname, 'ldset': ldset['ldsetname']})
                else:
                    msg = (_('Failed to unregister Logical Disk from '
                             'Logical Disk Set (%s)') % errnum)
                    raise exception.VolumeBackendAPIException(data=msg)

        return info

    def fc_terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        msgparm = ('Volume ID = %(id)s, Connector = %(connector)s'
                   % {'id': snapshot.id, 'connector': connector})
        try:
            ret = self._fc_terminate_connection(snapshot, connector,
                                                is_snapshot=True)
            LOG.info('Terminated FC Connection snapshot(%s)', msgparm)
            self.remove_export_snapshot(None, snapshot)
            return ret
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Terminate FC Connection snapshot'
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _is_multi_attachment(self, volume, connector):
        """Check the number of attached instances.

        Returns true if the volume is attached to multiple instances.
        Returns false if the volume is attached to a single instance.
        """
        host = connector['host']
        attach_list = volume.volume_attachment

        if attach_list is None:
            return False

        host_list = [att.connector['host'] for att in attach_list if
                     att is not None and att.connector is not None]
        if host_list.count(host) > 1:
            LOG.info("Volume is attached to multiple instances on "
                     "this host.")
            return True
        return False

    def _build_initiator_target_map(self, connector, fc_ports):
        target_wwns = []
        for port in fc_ports:
            target_wwns.append(port['wwpn'])

        initiator_wwns = []
        if connector is not None:
            initiator_wwns = connector['wwpns']

        init_targ_map = {}
        for initiator in initiator_wwns:
            init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        data = {}

        data['volume_backend_name'] = (self._properties['backend_name'] or
                                       self._driver_name)
        data['vendor_name'] = self._properties['vendor_name']
        data['driver_version'] = self.VERSION
        data['reserved_percentage'] = self._properties['reserved_percentage']
        data['QoS_support'] = True
        data['multiattach'] = True
        data['location_info'] = (self._properties['cli_fip'] + ":"
                                 + (','.join(map(str,
                                                 self._properties['pool_pools']
                                                 ))))

        # Get xml data from file and parse.
        try:
            pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
                self.parse_xml())

            # Get capacities from pools.
            pool_capacity = self.get_pool_capacity(pools, ldsets)

            data['total_capacity_gb'] = pool_capacity['total_capacity_gb']
            data['free_capacity_gb'] = pool_capacity['free_capacity_gb']
        except Exception:
            LOG.debug('_update_volume_status Unexpected error. '
                      'exception=%s',
                      traceback.format_exc())
            data['total_capacity_gb'] = 0
            data['free_capacity_gb'] = 0
        return data

    def iscsi_get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._stats = self._update_volume_status()
            self._stats['storage_protocol'] = 'iSCSI'
        LOG.debug('data=%(data)s, config_group=%(group)s',
                  {'data': self._stats, 'group': self._config_group})

        return self._stats

    def fc_get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._stats = self._update_volume_status()
            self._stats['storage_protocol'] = 'FC'
        LOG.debug('data=%(data)s, config_group=%(group)s',
                  {'data': self._stats, 'group': self._config_group})

        return self._stats

    def get_pool(self, volume):
        LOG.debug('backend_name=%s', self._properties['backend_name'])
        return self._properties['backend_name']

    def delete_volume(self, volume):
        msgparm = 'Volume ID = %s' % volume.id
        try:
            self._delete_volume(volume)
            LOG.info('Deleted Volume (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Delete Volume '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _delete_volume(self, volume):
        LOG.debug('_delete_volume id=%(id)s, _name_id=%(name_id)s Start.',
                  {'id': volume.id, 'name_id': volume._name_id})

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        ldname = self.get_ldname(volume.name_id,
                                 self._properties['ld_name_format'])

        # The volume to be deleted has '_d' at the end of the name
        # when migrating with the same backend.
        delete_ldname = self._convert_deleteldname(ldname)
        if delete_ldname in lds:
            ldname = delete_ldname

        if ldname not in lds:
            LOG.debug('LD `%s` already unbound?', ldname)
            return

        # If not migrating, detach from all hosts.
        if ldname != delete_ldname:
            detached = self._detach_from_all(ldname, xml)
            xml = self._cli.view_all(self._properties['ismview_path'],
                                     detached)
            pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
                self.configs(xml))

        ld = lds[ldname]

        if ld['RPL Attribute'] == 'IV':
            pass

        elif ld['RPL Attribute'] == 'MV':
            query_status = self._cli.query_MV_RV_status(ldname[3:], 'MV')
            if query_status == 'separated':
                # unpair.
                rvname = self._cli.query_MV_RV_name(ldname[3:], 'MV')
                self._cli.unpair(ldname[3:], rvname, 'force')
            else:
                msg = _('Specified Logical Disk %s has been copied.') % ldname
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        elif ld['RPL Attribute'] == 'RV':
            query_status = self._cli.query_MV_RV_status(ldname[3:], 'RV')
            if query_status == 'separated':
                # unpair.
                mvname = self._cli.query_MV_RV_name(ldname[3:], 'RV')
                self._cli.unpair(mvname, ldname[3:], 'force')
            else:
                msg = _('Specified Logical Disk %s has been copied.') % ldname
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        else:
            msg = (_('RPL Attribute Error. RPL Attribute = %s.')
                   % ld['RPL Attribute'])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # unbind LD.
        self._cli.unbind(ldname)
        LOG.debug('LD unbound. Name=%s.', ldname)

    def _is_manageable_volume(self, ld):
        if ld['RPL Attribute'] == '---':
            return False
        if ld['Purpose'] != '---' and 'BV' not in ld['RPL Attribute']:
            return False
        if ld['pool_num'] not in self._properties['pool_pools']:
            return False
        return True

    def _is_manageable_snapshot(self, ld):
        if ld['RPL Attribute'] == '---':
            return False
        if 'SV' not in ld['RPL Attribute']:
            return False
        if ld['pool_num'] not in self._properties['pool_backup_pools']:
            return False
        return True

    def _reference_to_ldname(self, resource_type, volume, existing_ref):
        if resource_type == 'volume':
            ldname_format = self._properties['ld_name_format']
        else:
            ldname_format = self._properties['ld_backupname_format']

        id_name = self.get_ldname(volume.id, ldname_format)
        ref_name = existing_ref['source-name']
        volid = re.search(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            ref_name)
        if volid:
            ref_name = self.get_ldname(volid.group(0), ldname_format)

        return id_name, ref_name

    def _get_manageable_resources(self, resource_type, cinder_volumes, marker,
                                  limit, offset, sort_keys, sort_dirs):
        entries = []
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))
        cinder_ids = [resource['id'] for resource in cinder_volumes]

        for ld in lds.values():
            if ((resource_type == 'volume' and
                 not self._is_manageable_volume(ld)) or
                (resource_type == 'snapshot' and
                 not self._is_manageable_snapshot(ld))):
                continue

            ld_info = {'reference': {'source-name': ld['ldname']},
                       'size': ld['ld_capacity'],
                       'cinder_id': None,
                       'extra_info': None}

            potential_id = volume_common.convert_to_id(ld['ldname'][3:])
            if potential_id in cinder_ids:
                ld_info['safe_to_manage'] = False
                ld_info['reason_not_safe'] = 'already managed'
                ld_info['cinder_id'] = potential_id
            elif self.check_accesscontrol(ldsets, ld):
                ld_info['safe_to_manage'] = False
                ld_info['reason_not_safe'] = '%s in use' % resource_type
            else:
                ld_info['safe_to_manage'] = True
                ld_info['reason_not_safe'] = None

            if resource_type == 'snapshot':
                bvname = self._cli.get_bvname(ld['ldname'])
                bv_id = volume_common.convert_to_id(bvname)
                ld_info['source_reference'] = {'source-name': bv_id}

            entries.append(ld_info)

        return volume_utils.paginate_entries_list(entries, marker, limit,
                                                  offset, sort_keys, sort_dirs)

    def _manage_existing_get_size(self, resource_type, volume, existing_ref):
        if 'source-name' not in existing_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        id_name, ref_name = self._reference_to_ldname(resource_type,
                                                      volume,
                                                      existing_ref)
        if ref_name not in lds:
            reason = _('Specified resource does not exist.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        ld = lds[ref_name]
        return ld['ld_capacity']

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder."""
        LOG.debug('get_manageable_volumes Start.')
        return self._get_manageable_resources('volume',
                                              cinder_volumes, marker, limit,
                                              offset, sort_keys, sort_dirs)

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.
        """
        LOG.debug('manage_existing Start.')

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        newname, oldname = self._reference_to_ldname('volume',
                                                     volume,
                                                     existing_ref)
        if self.check_accesscontrol(ldsets, lds[oldname]):
            reason = _('Specified resource is already in-use.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        if lds[oldname]['pool_num'] not in self._properties['pool_pools']:
            reason = _('Volume type is unmatched.')
            raise exception.ManageExistingVolumeTypeMismatch(
                existing_ref=existing_ref, reason=reason)

        try:
            self._cli.changeldname(None, newname, oldname)
        except exception.CinderException as e:
            LOG.warning('Unable to manage existing volume '
                        '(reference = %(ref)s), (%(exception)s)',
                        {'ref': existing_ref['source-name'], 'exception': e})
        return

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""
        LOG.debug('manage_existing_get_size Start.')
        return self._manage_existing_get_size('volume', volume, existing_ref)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        pass

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder."""
        LOG.debug('get_manageable_snapshots Start.')
        return self._get_manageable_resources('snapshot',
                                              cinder_snapshots, marker, limit,
                                              offset, sort_keys, sort_dirs)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        Rename the backend storage object so that it matches the
        snapshot['name'] which is how drivers traditionally map between a
        cinder snapshot and the associated backend storage object.
        """
        LOG.debug('manage_existing_snapshots Start.')

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        newname, oldname = self._reference_to_ldname('snapshot',
                                                     snapshot,
                                                     existing_ref)
        param_source = self.get_ldname(snapshot.volume_id,
                                       self._properties['ld_name_format'])
        ref_source = self._cli.get_bvname(oldname)
        if param_source[3:] != ref_source:
            reason = _('Snapshot source is unmatched.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        if (lds[oldname]['pool_num']
                not in self._properties['pool_backup_pools']):
            reason = _('Volume type is unmatched.')
            raise exception.ManageExistingVolumeTypeMismatch(
                existing_ref=existing_ref, reason=reason)

        try:
            self._cli.changeldname(None, newname, oldname)
        except exception.CinderException as e:
            LOG.warning('Unable to manage existing snapshot '
                        '(reference = %(ref)s), (%(exception)s)',
                        {'ref': existing_ref['source-name'], 'exception': e})

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing."""
        LOG.debug('manage_existing_snapshot_get_size Start.')
        return self._manage_existing_get_size('snapshot',
                                              snapshot, existing_ref)

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management."""
        pass


class MStorageDSVDriver(MStorageDriver):
    """M-Series Storage Snapshot helper class."""

    def create_snapshot(self, snapshot):
        msgparm = ('Snapshot ID = %(snap_id)s, '
                   'Snapshot Volume ID = %(snapvol_id)s'
                   % {'snap_id': snapshot.id,
                      'snapvol_id': snapshot.volume_id})
        try:
            self._create_snapshot(snapshot,
                                  self._properties['diskarray_name'])
            LOG.info('Created Snapshot (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Create Snapshot '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    @coordination.synchronized('mstorage_bind_execute_{diskarray_name}')
    def _create_snapshot(self, snapshot, diskarray_name):
        LOG.debug('_create_snapshot(Volume ID = %(snapvol_id)s, '
                  'Snapshot ID = %(snap_id)s ) Start.',
                  {'snapvol_id': snapshot.volume_id,
                   'snap_id': snapshot.id})

        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        if len(self._properties['pool_backup_pools']) == 0:
            LOG.error('backup_pools is not set.')
            raise exception.ParameterNotFound(param='backup_pools')

        # get BV name.
        ldname = self._validate_ld_exist(
            lds, snapshot.volume_id, self._properties['ld_name_format'])

        selected_pool = self._select_dsv_poolnumber(snapshot, pools, None)
        snapshotname = self._convert_id2snapname(snapshot)
        self._cli.snapshot_create(ldname, snapshotname[3:], selected_pool)

        LOG.debug('_create_snapshot(Volume ID = %(snapvol_id)s, '
                  'Snapshot ID = %(snap_id)s) End.',
                  {'snapvol_id': snapshot.volume_id,
                   'snap_id': snapshot.id})

    def delete_snapshot(self, snapshot):
        msgparm = ('Snapshot ID = %(snap_id)s, '
                   'Snapshot Volume ID = %(snapvol_id)s'
                   % {'snap_id': snapshot.id,
                      'snapvol_id': snapshot.volume_id})
        try:
            self._delete_snapshot(snapshot)
            LOG.info('Deleted Snapshot (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Delete Snapshot '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _delete_snapshot(self, snapshot):
        LOG.debug('_delete_snapshot(Snapshot ID = %s) Start.',
                  snapshot.id)
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get BV name.
        ldname = self.get_ldname(snapshot.volume_id,
                                 self._properties['ld_name_format'])
        if ldname not in lds:
            LOG.debug('LD(BV) `%s` already unbound?', ldname)
            return

        # get SV name.
        snapshotname = (
            self.get_ldname(snapshot.id,
                            self._properties['ld_backupname_format']))
        if snapshotname not in lds:
            LOG.debug('LD(SV) `%s` already unbound?', snapshotname)
            return

        self._cli.snapshot_delete(ldname, snapshotname[3:])

        LOG.debug('_delete_snapshot(Snapshot ID = %s) End.', snapshot.id)

    def create_volume_from_snapshot(self, volume, snapshot):
        msgparm = ('Volume ID = %(vol_id)s, '
                   'Snapshot ID = %(snap_id)s, '
                   'Snapshot Volume ID = %(snapvol_id)s'
                   % {'vol_id': volume.id,
                      'snap_id': snapshot.id,
                      'snapvol_id': snapshot.volume_id})
        try:
            self._create_volume_from_snapshot(volume, snapshot)
            LOG.info('Created Volume from Snapshot (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to Create Volume from Snapshot '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _create_volume_from_snapshot(self, volume, snapshot):
        LOG.debug('_create_volume_from_snapshot'
                  '(Volume ID = %(vol_id)s, Snapshot ID(SV) = %(snap_id)s, '
                  'Snapshot ID(BV) = %(snapvol_id)s) Start.',
                  {'vol_id': volume.id,
                   'snap_id': snapshot.id,
                   'snapvol_id': snapshot.volume_id})
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))

        # get BV name.
        mvname = (
            self.get_ldname(snapshot.volume_id,
                            self._properties['ld_name_format']))

        # get SV name.
        rvname = (
            self.get_ldname(snapshot.id,
                            self._properties['ld_backupname_format']))

        if rvname not in lds:
            msg = _('Logical Disk `%s` has unbound already.') % rvname
            LOG.error(msg)
            raise exception.NotFound(msg)
        rv = lds[rvname]

        # check snapshot status.
        query_status = self._cli.query_BV_SV_status(mvname[3:], rvname[3:])
        if query_status != 'snap/active':
            msg = (_('Cannot create volume from snapshot, '
                     'because the snapshot data does not exist. '
                     'bvname=%(bvname)s, svname=%(svname)s') %
                   {'bvname': mvname, 'svname': rvname})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        mv_capacity = rv['ld_capacity']
        rv_capacity = volume.size

        new_rvname, rvnumber, selected_pool = self._bind_ld(
            volume,
            mv_capacity,
            None,
            self._convert_id2name,
            self._select_volddr_poolnumber,
            mv_capacity)

        self._set_qos_spec(new_rvname, volume.volume_type_id)

        if rv_capacity <= mv_capacity:
            rvnumber = None
            rv_capacity = None

        # Restore Start.
        volume_properties = {
            'mvname': rvname,
            'rvname': new_rvname,
            'prev_mvname': None,
            'capacity': mv_capacity,
            'mvid': snapshot.id,
            'rvid': volume.id,
            'rvldn': rvnumber,
            'rvcapacity': rv_capacity,
            'flag': 'esv_restore',
            'context': self._context
        }
        self._cli.backup_restore(volume_properties,
                                 cli.UnpairWaitForDDRRestore)

        LOG.debug('_create_volume_from_snapshot(Volume ID = %(vol_id)s, '
                  'Snapshot ID(SV) = %(snap_id)s, '
                  'Snapshot ID(BV) = %(snapvol_id)s) End.',
                  {'vol_id': volume.id,
                   'snap_id': snapshot.id,
                   'snapvol_id': snapshot.volume_id})

    def revert_to_snapshot(self, context, volume, snapshot):
        """called to perform revert volume from snapshot.

        :param context: Our working context.
        :param volume: the volume to be reverted.
        :param snapshot: the snapshot data revert to volume.
        :return None
        """
        msgparm = ('Volume ID = %(vol_id)s, '
                   'Snapshot ID = %(snap_id)s, '
                   'Snapshot Volume ID = %(snapvol_id)s'
                   % {'vol_id': volume.id,
                      'snap_id': snapshot.id,
                      'snapvol_id': snapshot.volume_id})
        try:
            self._revert_to_snapshot(context, volume, snapshot)
            LOG.info('Reverted to Snapshot (%s)', msgparm)
        except exception.CinderException as e:
            with excutils.save_and_reraise_exception():
                LOG.warning('Failed to revert to Snapshot '
                            '(%(msgparm)s) (%(exception)s)',
                            {'msgparm': msgparm, 'exception': e})

    def _revert_to_snapshot(self, context, volume, snapshot):
        LOG.debug('_revert_to_snapshot (Volume ID = %(vol_id)s, '
                  'Snapshot ID = %(snap_id)s) Start.',
                  {'vol_id': volume.id, 'snap_id': snapshot.id})
        xml = self._cli.view_all(self._properties['ismview_path'])
        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml))
        # get BV name.
        bvname = (
            self.get_ldname(volume.id,
                            self._properties['ld_name_format']))
        if bvname not in lds:
            msg = _('Logical Disk `%s` has unbound already.') % bvname
            LOG.error(msg)
            raise exception.NotFound(msg)

        # get SV name.
        svname = (
            self.get_ldname(snapshot.id,
                            self._properties['ld_backupname_format']))
        if svname not in lds:
            msg = _('Logical Disk `%s` has unbound already.') % svname
            LOG.error(msg)
            raise exception.NotFound(msg)

        self._cli.snapshot_restore(bvname, svname)

        LOG.debug('_revert_to_snapshot(Volume ID = %s) End.', volume.id)
