# Copyright (c) 2014, Oracle and/or its affiliates. All rights reserved.
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
ZFS Storage Appliance Cinder Volume Driver
"""
import ast
import base64

from oslo_config import cfg
from oslo_log import log
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.zfssa import zfssarest
from cinder.volume import volume_types

CONF = cfg.CONF
LOG = log.getLogger(__name__)

ZFSSA_OPTS = [
    cfg.StrOpt('zfssa_pool',
               help='Storage pool name.'),
    cfg.StrOpt('zfssa_project',
               help='Project name.'),
    cfg.StrOpt('zfssa_lun_volblocksize', default='8k',
               choices=['512', '1k', '2k', '4k', '8k', '16k', '32k', '64k',
                        '128k'],
               help='Block size.'),
    cfg.BoolOpt('zfssa_lun_sparse', default=False,
                help='Flag to enable sparse (thin-provisioned): True, False.'),
    cfg.StrOpt('zfssa_lun_compression', default='off',
               choices=['off', 'lzjb', 'gzip-2', 'gzip', 'gzip-9'],
               help='Data compression.'),
    cfg.StrOpt('zfssa_lun_logbias', default='latency',
               choices=['latency', 'throughput'],
               help='Synchronous write bias.'),
    cfg.StrOpt('zfssa_initiator_group', default='',
               help='iSCSI initiator group.'),
    cfg.StrOpt('zfssa_initiator', default='',
               help='iSCSI initiator IQNs. (comma separated)'),
    cfg.StrOpt('zfssa_initiator_user', default='',
               help='iSCSI initiator CHAP user (name).'),
    cfg.StrOpt('zfssa_initiator_password', default='',
               help='Secret of the iSCSI initiator CHAP user.', secret=True),
    cfg.StrOpt('zfssa_initiator_config', default='',
               help='iSCSI initiators configuration.'),
    cfg.StrOpt('zfssa_target_group', default='tgt-grp',
               help='iSCSI target group name.'),
    cfg.StrOpt('zfssa_target_user', default='',
               help='iSCSI target CHAP user (name).'),
    cfg.StrOpt('zfssa_target_password', default='', secret=True,
               help='Secret of the iSCSI target CHAP user.'),
    cfg.StrOpt('zfssa_target_portal',
               help='iSCSI target portal (Data-IP:Port, w.x.y.z:3260).'),
    cfg.StrOpt('zfssa_target_interfaces',
               help='Network interfaces of iSCSI targets. (comma separated)'),
    cfg.IntOpt('zfssa_rest_timeout',
               help='REST connection timeout. (seconds)')

]

CONF.register_opts(ZFSSA_OPTS)

ZFSSA_LUN_SPECS = {
    'zfssa:volblocksize',
    'zfssa:sparse',
    'zfssa:compression',
    'zfssa:logbias',
}


def factory_zfssa():
    return zfssarest.ZFSSAApi()


class ZFSSAISCSIDriver(driver.ISCSIDriver):
    """ZFSSA Cinder iSCSI volume driver."""

    VERSION = '1.0.0'
    protocol = 'iSCSI'

    def __init__(self, *args, **kwargs):
        super(ZFSSAISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(ZFSSA_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.zfssa = None
        self._stats = None
        self.tgtiqn = None

    def _get_target_alias(self):
        """return target alias."""
        return self.configuration.zfssa_target_group

    def do_setup(self, context):
        """Setup - create multiple elements.

        Project, initiators, initiatorgroup, target and targetgroup.
        """
        lcfg = self.configuration
        LOG.info(_LI('Connecting to host: %s.'), lcfg.san_ip)
        self.zfssa = factory_zfssa()
        self.zfssa.set_host(lcfg.san_ip, timeout=lcfg.zfssa_rest_timeout)
        auth_str = base64.encodestring('%s:%s' %
                                       (lcfg.san_login,
                                        lcfg.san_password))[:-1]
        self.zfssa.login(auth_str)
        self.zfssa.create_project(lcfg.zfssa_pool, lcfg.zfssa_project,
                                  compression=lcfg.zfssa_lun_compression,
                                  logbias=lcfg.zfssa_lun_logbias)

        if (lcfg.zfssa_initiator_config != ''):
            initiator_config = ast.literal_eval(lcfg.zfssa_initiator_config)
            for initiator_group in initiator_config:
                zfssa_initiator_group = initiator_group
                for zfssa_initiator in initiator_config[zfssa_initiator_group]:
                    self.zfssa.create_initiator(zfssa_initiator['iqn'],
                                                zfssa_initiator_group + '-' +
                                                zfssa_initiator['iqn'],
                                                chapuser=
                                                zfssa_initiator['user'],
                                                chapsecret=
                                                zfssa_initiator['password'])
                    if (zfssa_initiator_group != 'default'):
                        self.zfssa.add_to_initiatorgroup(
                            zfssa_initiator['iqn'],
                            zfssa_initiator_group)
        else:
            LOG.warning(_LW('zfssa_initiator_config not found. '
                            'Using deprecated configuration options.'))
            if (lcfg.zfssa_initiator != '' and
                (lcfg.zfssa_initiator_group == '' or
                 lcfg.zfssa_initiator_group == 'default')):
                LOG.warning(_LW('zfssa_initiator: %(ini)s'
                                ' wont be used on '
                                'zfssa_initiator_group= %(inigrp)s.'),
                            {'ini': lcfg.zfssa_initiator,
                             'inigrp': lcfg.zfssa_initiator_group})

            # Setup initiator and initiator group
            if (lcfg.zfssa_initiator != '' and
               lcfg.zfssa_initiator_group != '' and
               lcfg.zfssa_initiator_group != 'default'):
                for initiator in lcfg.zfssa_initiator.split(','):
                    self.zfssa.create_initiator(
                        initiator, lcfg.zfssa_initiator_group + '-' +
                        initiator, chapuser=lcfg.zfssa_initiator_user,
                        chapsecret=lcfg.zfssa_initiator_password)
                    self.zfssa.add_to_initiatorgroup(
                        initiator, lcfg.zfssa_initiator_group)

        # Parse interfaces
        interfaces = []
        for interface in lcfg.zfssa_target_interfaces.split(','):
            if interface == '':
                continue
            interfaces.append(interface)

        # Setup target and target group
        iqn = self.zfssa.create_target(
            self._get_target_alias(),
            interfaces,
            tchapuser=lcfg.zfssa_target_user,
            tchapsecret=lcfg.zfssa_target_password)

        self.zfssa.add_to_targetgroup(iqn, lcfg.zfssa_target_group)

    def check_for_setup_error(self):
        """Check that driver can login.

        Check also pool, project, initiators, initiatorgroup, target and
        targetgroup.
        """
        lcfg = self.configuration

        self.zfssa.verify_pool(lcfg.zfssa_pool)
        self.zfssa.verify_project(lcfg.zfssa_pool, lcfg.zfssa_project)

        if (lcfg.zfssa_initiator_config != ''):
            initiator_config = ast.literal_eval(lcfg.zfssa_initiator_config)
            for initiator_group in initiator_config:
                zfssa_initiator_group = initiator_group
                for zfssa_initiator in initiator_config[zfssa_initiator_group]:
                    self.zfssa.verify_initiator(zfssa_initiator['iqn'])
        else:
            if (lcfg.zfssa_initiator != '' and
               lcfg.zfssa_initiator_group != '' and
               lcfg.zfssa_initiator_group != 'default'):
                for initiator in lcfg.zfssa_initiator.split(','):
                    self.zfssa.verify_initiator(initiator)

            self.zfssa.verify_target(self._get_target_alias())

    def _get_provider_info(self, volume, lun=None):
        """Return provider information."""
        lcfg = self.configuration
        if lun is None:
            lun = self.zfssa.get_lun(lcfg.zfssa_pool,
                                     lcfg.zfssa_project,
                                     volume['name'])

        if isinstance(lun['number'], list):
            lun['number'] = lun['number'][0]

        if self.tgtiqn is None:
            self.tgtiqn = self.zfssa.get_target(self._get_target_alias())

        loc = "%s %s %s" % (lcfg.zfssa_target_portal, self.tgtiqn,
                            lun['number'])
        LOG.debug('_get_provider_info: provider_location: %s', loc)
        provider = {'provider_location': loc}
        if lcfg.zfssa_target_user != '' and lcfg.zfssa_target_password != '':
            provider['provider_auth'] = ('CHAP %s %s' %
                                         (lcfg.zfssa_target_user,
                                          lcfg.zfssa_target_password))

        return provider

    def create_volume(self, volume):
        """Create a volume on ZFSSA."""
        LOG.debug('zfssa.create_volume: volume=' + volume['name'])
        lcfg = self.configuration
        volsize = str(volume['size']) + 'g'
        specs = self._get_voltype_specs(volume)
        self.zfssa.create_lun(lcfg.zfssa_pool,
                              lcfg.zfssa_project,
                              volume['name'],
                              volsize,
                              lcfg.zfssa_target_group,
                              specs)

    def delete_volume(self, volume):
        """Deletes a volume with the given volume['name']."""
        LOG.debug('zfssa.delete_volume: name=%s', volume['name'])
        lcfg = self.configuration

        try:
            lun2del = self.zfssa.get_lun(lcfg.zfssa_pool,
                                         lcfg.zfssa_project,
                                         volume['name'])
        except exception.VolumeBackendAPIException as ex:
            # NOTE(jdg): This will log an error and continue
            # if for some reason the volume no longer exists
            # on the backend
            if 'Error Getting Volume' in ex.message:
                LOG.error(_LE("Volume ID %s was not found on "
                              "the zfssa device while attempting "
                              "delete_volume operation."), volume['id'])
                return

        # Delete clone temp snapshot. see create_cloned_volume()
        if 'origin' in lun2del and 'id' in volume:
            if lun2del['nodestroy']:
                self.zfssa.set_lun_props(lcfg.zfssa_pool,
                                         lcfg.zfssa_project,
                                         volume['name'],
                                         nodestroy=False)

            tmpsnap = 'tmp-snapshot-%s' % volume['id']
            if lun2del['origin']['snapshot'] == tmpsnap:
                self.zfssa.delete_snapshot(lcfg.zfssa_pool,
                                           lcfg.zfssa_project,
                                           lun2del['origin']['share'],
                                           lun2del['origin']['snapshot'])
                return

        self.zfssa.delete_lun(pool=lcfg.zfssa_pool,
                              project=lcfg.zfssa_project,
                              lun=volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot of a volume.

        Snapshot name: snapshot['name']
        Volume name: snapshot['volume_name']
        """
        LOG.debug('zfssa.create_snapshot: snapshot=%s', snapshot['name'])
        lcfg = self.configuration
        self.zfssa.create_snapshot(lcfg.zfssa_pool,
                                   lcfg.zfssa_project,
                                   snapshot['volume_name'],
                                   snapshot['name'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug('zfssa.delete_snapshot: snapshot=%s', snapshot['name'])
        lcfg = self.configuration
        has_clones = self.zfssa.has_clones(lcfg.zfssa_pool,
                                           lcfg.zfssa_project,
                                           snapshot['volume_name'],
                                           snapshot['name'])
        if has_clones:
            LOG.error(_LE('Snapshot %s: has clones'), snapshot['name'])
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])

        self.zfssa.delete_snapshot(lcfg.zfssa_pool,
                                   lcfg.zfssa_project,
                                   snapshot['volume_name'],
                                   snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot - clone a snapshot."""
        LOG.debug('zfssa.create_volume_from_snapshot: volume=%s',
                  volume['name'])
        LOG.debug('zfssa.create_volume_from_snapshot: snapshot=%s',
                  snapshot['name'])
        if not self._verify_clone_size(snapshot, volume['size'] * units.Gi):
            exception_msg = (_('Error verifying clone size on '
                               'Volume clone: %(clone)s '
                               'Size: %(size)d on'
                               'Snapshot: %(snapshot)s')
                             % {'clone': volume['name'],
                                'size': volume['size'],
                                'snapshot': snapshot['name']})
            LOG.error(exception_msg)
            raise exception.InvalidInput(reason=exception_msg)

        lcfg = self.configuration
        self.zfssa.clone_snapshot(lcfg.zfssa_pool,
                                  lcfg.zfssa_project,
                                  snapshot['volume_name'],
                                  snapshot['name'],
                                  volume['name'])

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        LOG.debug("Updating volume status")
        self._stats = None
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Oracle'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = self.protocol

        lcfg = self.configuration
        (avail, total) = self.zfssa.get_pool_stats(lcfg.zfssa_pool)
        if avail is None or total is None:
            return

        data['total_capacity_gb'] = int(total) / units.Gi
        data['free_capacity_gb'] = int(avail) / units.Gi
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_status()
        return self._stats

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def extend_volume(self, volume, new_size):
        """Driver entry point to extent volume size."""
        LOG.debug('extend_volume: volume name: %s', volume['name'])
        lcfg = self.configuration
        self.zfssa.set_lun_props(lcfg.zfssa_pool,
                                 lcfg.zfssa_project,
                                 volume['name'],
                                 volsize=new_size * units.Gi)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        zfssa_snapshot = {'volume_name': src_vref['name'],
                          'name': 'tmp-snapshot-%s' % volume['id']}
        self.create_snapshot(zfssa_snapshot)
        try:
            self.create_volume_from_snapshot(volume, zfssa_snapshot)
        except exception.VolumeBackendAPIException:
            LOG.error(_LE('Clone Volume:'
                          '%(volume)s failed from source volume:'
                          '%(src_vref)s'),
                      {'volume': volume['name'],
                       'src_vref': src_vref['name']})
            # Cleanup snapshot
            self.delete_snapshot(zfssa_snapshot)

    def local_path(self, volume):
        """Not implemented."""
        pass

    def backup_volume(self, context, backup, backup_service):
        """Not implemented."""
        pass

    def restore_backup(self, context, backup, volume, backup_service):
        """Not implemented."""
        pass

    def _verify_clone_size(self, snapshot, size):
        """Check whether the clone size is the same as the parent volume."""
        lcfg = self.configuration
        lun = self.zfssa.get_lun(lcfg.zfssa_pool,
                                 lcfg.zfssa_project,
                                 snapshot['volume_name'])
        return lun['size'] == size

    def initialize_connection(self, volume, connector):
        lcfg = self.configuration
        init_groups = self.zfssa.get_initiator_initiatorgroup(
            connector['initiator'])
        for initiator_group in init_groups:
            self.zfssa.set_lun_initiatorgroup(lcfg.zfssa_pool,
                                              lcfg.zfssa_project,
                                              volume['name'],
                                              initiator_group)
        iscsi_properties = {}
        provider = self._get_provider_info(volume)

        (target_portal, iqn, lun) = provider['provider_location'].split()
        iscsi_properties['target_discovered'] = False
        iscsi_properties['target_portal'] = target_portal
        iscsi_properties['target_iqn'] = iqn
        iscsi_properties['target_lun'] = lun
        iscsi_properties['volume_id'] = volume['id']

        if 'provider_auth' in provider:
            (auth_method, auth_username, auth_password) = provider[
                'provider_auth'].split()
            iscsi_properties['auth_method'] = auth_method
            iscsi_properties['auth_username'] = auth_username
            iscsi_properties['auth_password'] = auth_password

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to terminate a connection for a volume."""
        LOG.debug('terminate_connection: volume name: %s.', volume['name'])
        lcfg = self.configuration
        self.zfssa.set_lun_initiatorgroup(lcfg.zfssa_pool,
                                          lcfg.zfssa_project,
                                          volume['name'],
                                          '')

    def _get_voltype_specs(self, volume):
        """Get specs suitable for volume creation."""
        vtype = volume.get('volume_type_id', None)
        extra_specs = None
        if vtype:
            extra_specs = volume_types.get_volume_type_extra_specs(vtype)

        return self._get_specs(extra_specs)

    def _get_specs(self, xspecs):
        """Return a dict with extra specs and/or config values."""
        result = {}
        for spc in ZFSSA_LUN_SPECS:
            val = None
            prop = spc.split(':')[1]
            cfg = 'zfssa_lun_' + prop
            if xspecs:
                val = xspecs.pop(spc, None)

            if val is None:
                val = self.configuration.safe_get(cfg)

            if val is not None and val != '':
                result.update({prop: val})

        return result
