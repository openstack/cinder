# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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
VNX CLI on iSCSI.
"""

import os
import time

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import processutils
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
VERSION = '02.00.00'

loc_opts = [
    cfg.StrOpt('naviseccli_path',
               default='',
               help='Naviseccli Path'),
    cfg.StrOpt('storage_vnx_pool_name',
               default=None,
               help='ISCSI pool name'),
    cfg.IntOpt('default_timeout',
               default=20,
               help='Default Time Out For CLI operations in minutes'),
    cfg.IntOpt('max_luns_per_storage_group',
               default=256,
               help='Default max number of LUNs in a storage group'), ]

CONF.register_opts(loc_opts)


class EMCVnxCli(object):
    """This class defines the functions to use the native CLI functionality."""

    stats = {'driver_version': VERSION,
             'free_capacity_gb': 'unknown',
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 'unknown',
             'vendor_name': 'EMC',
             'volume_backend_name': None}

    def __init__(self, prtcl, configuration=None):

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(loc_opts)
        self.configuration.append_config_values(san.san_opts)
        self.storage_ip = self.configuration.san_ip
        self.storage_username = self.configuration.san_login
        self.storage_password = self.configuration.san_password

        self.pool_name = self.configuration.storage_vnx_pool_name
        if not self.pool_name:
            msg = (_('Pool name is not specified.'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        self.timeout = self.configuration.default_timeout
        self.max_luns = self.configuration.max_luns_per_storage_group
        self.hlu_set = set(xrange(1, self.max_luns + 1))
        self.navisecclipath = self.configuration.naviseccli_path
        self.cli_prefix = (self.navisecclipath, '-address', self.storage_ip)
        self.cli_credentials = ()
        self.wait_interval = 3

        # if there is a username/password provided, use those in the cmd line
        if self.storage_username is not None and \
                self.storage_password is not None:
            self.cli_credentials += ('-user', self.storage_username,
                                     '-password', self.storage_password,
                                     '-scope', '0')

        # Checking for existence of naviseccli tool
        if not os.path.exists(self.navisecclipath):
            msg = (_('Could not find NAVISECCLI tool.'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Testing the naviseccli setup
        query_list = ("storagepool", "-list",
                      "-name", self.pool_name, "-state")
        out, rc = self._cli_execute(*query_list)
        if rc != 0:
            LOG.error(_("Failed to find pool %s"), self.pool_name)
            raise exception.VolumeBackendAPIException(data=out)

    def _cli_execute(self, *cmd, **kwargv):
        if "check_exit_code" not in kwargv:
            kwargv["check_exit_code"] = True
        rc = 0
        try:
            out, _err = utils.execute(*(self.cli_prefix +
                                      self.cli_credentials + cmd), **kwargv)
        except processutils.ProcessExecutionError as pe:
            rc = pe.exit_code
            out = pe.stdout + pe.stderr
        return out, rc

    def create_volume(self, volume):
        """Creates a EMC volume."""

        LOG.debug(_('Entering create_volume.'))
        volumesize = volume['size']
        volumename = volume['name']

        LOG.info(_('Create Volume: %(volume)s  Size: %(size)s')
                 % {'volume': volumename,
                    'size': volumesize})

        # defining CLI command
        thinness = self._get_provisioning_by_volume(volume)

        # executing CLI command to create volume
        LOG.debug(_('Create Volume: %(volumename)s')
                  % {'volumename': volumename})

        lun_create = ('lun', '-create',
                      '-type', thinness,
                      '-capacity', volumesize,
                      '-sq', 'gb',
                      '-poolName', self.pool_name,
                      '-name', volumename)
        out, rc = self._cli_execute(*lun_create)
        LOG.debug(_('Create Volume: %(volumename)s  Return code: %(rc)s')
                  % {'volumename': volumename,
                     'rc': rc})
        if rc == 4:
            LOG.warn(_('Volume %s already exists'), volumename)
        elif rc != 0:
            msg = (_('Failed to create %(volumename)s: %(out)s') %
                   {'volumename': volumename, 'out': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # wait for up to a minute to verify that the LUN has progressed
        # to Ready state
        def _wait_for_lun_ready(volumename, start_time):
            # executing cli command to check volume
            command_to_verify = ('lun', '-list', '-name', volumename)
            out, rc = self._cli_execute(*command_to_verify)
            if rc == 0 and out.find("Ready") > -1:
                raise loopingcall.LoopingCallDone()
            if int(time.time()) - start_time > self.timeout * 60:
                msg = (_('LUN %s failed to become Ready'), volumename)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_lun_ready, volumename, int(time.time()))
        timer.start(interval=self.wait_interval).wait()

    def delete_volume(self, volume):
        """Deletes an EMC volume."""

        LOG.debug(_('Entering delete_volume.'))
        volumename = volume['name']
        # defining CLI command
        lun_destroy = ('lun', '-destroy',
                       '-name', volumename,
                       '-forceDetach', '-o')

        # executing CLI command to delete volume
        out, rc = self._cli_execute(*lun_destroy)
        LOG.debug(_('Delete Volume: %(volumename)s  Output: %(out)s')
                  % {'volumename': volumename, 'out': out})
        if rc not in (0, 9):
            msg = (_('Failed to destroy %s'), volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def extend_volume(self, volume, new_size):
        """Extends an EMC volume."""

        LOG.debug(_('Entering extend_volume.'))
        volumename = volume['name']

        # defining CLI command
        lun_expand = ('lun', '-expand',
                      '-name', volumename,
                      '-capacity', new_size,
                      '-sq', 'gb',
                      '-o', '-ignoreThresholds')

        # executing CLI command to extend volume
        out, rc = self._cli_execute(*lun_expand)

        LOG.debug(_('Extend Volume: %(volumename)s  Output: %(out)s')
                  % {'volumename': volumename,
                     'out': out})
        if rc == 97:
            msg = (_('The LUN cannot be expanded or shrunk because '
                   'it has snapshots. Command to extend the specified '
                   'volume failed.'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if rc != 0:
            msg = (_('Failed to expand %s'), volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def update_volume_status(self):
        """Retrieve status info."""
        LOG.debug(_("Updating volume status"))

        poolname = self.pool_name
        pool_list = ('storagepool', '-list',
                     '-name', poolname,
                     '-userCap', '-availableCap')
        out, rc = self._cli_execute(*pool_list)
        if rc == 0:
            pool_details = out.split('\n')
            self.stats['total_capacity_gb'] = float(
                pool_details[3].split(':')[1].strip())
            self.stats['free_capacity_gb'] = float(
                pool_details[5].split(':')[1].strip())
        else:
            msg = (_('Failed to list %s'), poolname)
            LOG.error(msg)

        return self.stats

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        volumename = volume['name']

        device_id = self._find_lun_id(volumename)

        LOG.debug(_('create_export: Volume: %(volume)s  Device ID: '
                  '%(device_id)s')
                  % {'volume': volumename,
                     'device_id': device_id})

        return {'provider_location': device_id}

    def _find_lun_id(self, volumename):
        """Returns the LUN of a volume."""

        lun_list = ('lun', '-list', '-name', volumename)

        out, rc = self._cli_execute(*lun_list)
        if rc == 0:
            vol_details = out.split('\n')
            lun = vol_details[0].split(' ')[3]
        else:
            msg = (_('Failed to list %s'), volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return lun

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug(_('Entering create_snapshot.'))
        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        LOG.info(_('Create snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        volume_lun = self._find_lun_id(volumename)

        # defining CLI command
        snap_create = ('snap', '-create',
                       '-res', volume_lun,
                       '-name', snapshotname,
                       '-allowReadWrite', 'yes')
        # executing CLI command to create snapshot
        out, rc = self._cli_execute(*snap_create)

        LOG.debug(_('Create Snapshot: %(snapshotname)s  Unity: %(out)s')
                  % {'snapshotname': snapshotname,
                     'out': out})
        if rc != 0:
            msg = (_('Failed to create snap %s'), snapshotname)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug(_('Entering delete_snapshot.'))

        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        LOG.info(_('Delete Snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        def _wait_for_snap_delete(snapshot, start_time):
            # defining CLI command
            snapshotname = snapshot['name']
            volumename = snapshot['volume_name']
            snap_destroy = ('snap', '-destroy', '-id', snapshotname, '-o')
            # executing CLI command
            out, rc = self._cli_execute(*snap_destroy)

            LOG.debug(_('Delete Snapshot: Volume: %(volumename)s  Snapshot: '
                      '%(snapshotname)s  Output: %(out)s')
                      % {'volumename': volumename,
                         'snapshotname': snapshotname,
                         'out': out})

            if rc not in [0, 9, 5]:
                if rc == 13:
                    if int(time.time()) - start_time < \
                            self.timeout * 60:
                        LOG.info(_('Snapshot %s is in use'), snapshotname)
                    else:
                        msg = (_('Failed to destroy %s '
                               ' because snapshot is in use.'), snapshotname)
                        LOG.error(msg)
                        raise exception.SnapshotIsBusy(data=msg)
                else:
                    msg = (_('Failed to destroy %s'), snapshotname)
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_snap_delete, snapshot, int(time.time()))
        timer.start(interval=self.wait_interval).wait()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug(_('Entering create_volume_from_snapshot.'))

        snapshotname = snapshot['name']
        source_volume_name = snapshot['volume_name']
        volumename = volume['name']
        volumesize = snapshot['volume_size']

        destvolumename = volumename + 'dest'

        # Create a mount point, migrate data from source (snapshot) to
        # destination volume.  The destination volume is the only new volume
        # to be created here.
        LOG.info(_('Creating Destination Volume : %s ') % (destvolumename))

        poolname = self.pool_name
        thinness = self._get_provisioning_by_volume(volume)
        # defining CLI command
        lun_create = ('lun', '-create', '-type', thinness,
                      '-capacity', volumesize, '-sq', 'gb',
                      '-poolName', poolname,
                      '-name', destvolumename)
        # executing CLI command
        out, rc = self._cli_execute(*lun_create)

        LOG.debug(_('Create temporary Volume: %(volumename)s  '
                  'Output : %(out)s')
                  % {'volumename': destvolumename, 'out': out})

        if rc != 0:
            msg = (_('Command to create the destination volume failed'))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # defining CLI command
        smp_create = ('lun', '-create', '-type', 'Snap',
                      '-primaryLunName', source_volume_name,
                      '-name', volumename)

        # executing CLI command
        out, rc = self._cli_execute(*smp_create)
        LOG.debug(_('Create mount point : Volume: %(volumename)s  '
                  'Source Volume: %(sourcevolumename)s  Output: %(out)s')
                  % {'volumename': volumename,
                     'sourcevolumename': source_volume_name,
                     'out': out})

        if rc != 0:
            msg = (_('Failed to create SMP %s'), volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # defining CLI command
        lun_attach = ('lun', '-attach',
                      '-name', volumename,
                      '-snapName', snapshotname)

        # executing CLI command
        out, rc = self._cli_execute(*lun_attach)
        LOG.debug(_('Attaching mount point Volume: %(volumename)s  '
                  'with  Snapshot: %(snapshotname)s  Output: %(out)s')
                  % {'volumename': volumename,
                     'snapshotname': snapshotname,
                     'out': out})

        if rc != 0:
            msg = (_('Failed to attach snapshotname %s'), snapshotname)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        source_vol_lun = self._find_lun_id(volumename)
        dest_vol_lun = self._find_lun_id(destvolumename)

        LOG.info(_('Migrating Mount Point Volume: %s ') % (volumename))

        # defining CLI command
        migrate_start = ('migrate', '-start',
                         '-source', source_vol_lun,
                         '-dest', dest_vol_lun,
                         '-rate', 'ASAP', '-o')

        # executing CLI command
        out, rc = self._cli_execute(*migrate_start)

        LOG.debug(_('Migrate Mount Point  Volume: %(volumename)s  '
                  'Output : %(out)s')
                  % {'volumename': volumename,
                     'out': out})

        if rc != 0:
            msg = (_('Failed to start migrating SMP %s'), volumename)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        def _wait_for_sync_status(volumename, start_time):
            lun_list = ('lun', '-list', '-name', volumename,
                        '-attachedSnapshot')
            out, rc = self._cli_execute(*lun_list)
            if rc == 0:
                vol_details = out.split('\n')
                snapshotname = vol_details[2].split(':')[1].strip()
            if (snapshotname == 'N/A'):
                raise loopingcall.LoopingCallDone()
            else:
                LOG.info(_('Waiting for the update on Sync status of %s'),
                         volumename)
                if int(time.time()) - start_time >= self.timeout * 60:
                    msg = (_('Failed to really migrate %s'), volumename)
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_sync_status, volumename, int(time.time()))
        timer.start(interval=self.wait_interval).wait()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        source_volume_name = src_vref['name']
        volumesize = src_vref['size']
        snapshotname = source_volume_name + '-temp-snapshot'

        snapshot = {
            'name': snapshotname,
            'volume_name': source_volume_name,
            'volume_size': volumesize,
        }

        # Create temp Snapshot
        self.create_snapshot(snapshot)

        try:
            # Create volume
            self.create_volume_from_snapshot(volume, snapshot)
        except Exception:
            msg = (_('Failed to create cloned volume %s'), volume['name'])
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        finally:
            # Delete temp Snapshot
            self.delete_snapshot(snapshot)

    def get_storage_group(self, hostname):
        """Returns the storage group for the host node."""

        storage_groupname = hostname

        sg_list = ('storagegroup', '-list', '-gname', storage_groupname)

        out, rc = self._cli_execute(*sg_list)

        if rc != 0:
            LOG.debug(_('creating new storage group %s'), storage_groupname)

            sg_create = ('storagegroup', '-create',
                         '-gname', storage_groupname)
            out, rc = self._cli_execute(*sg_create)
            LOG.debug(_('Create new storage group : %(storage_groupname)s, '
                      'Output: %(out)s')
                      % {'storage_groupname': storage_groupname,
                         'out': out})

            if rc != 0:
                msg = (_('Failed to create SG %s'), storage_groupname)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # connecting the new storagegroup to the host
            connect_host = ('storagegroup', '-connecthost',
                            '-host', hostname,
                            '-gname', storage_groupname,
                            '-o')

            out, rc = self._cli_execute(*connect_host)
            LOG.debug(_('Connect storage group : %(storage_groupname)s ,'
                        'To Host : %(hostname)s, Output : %(out)s')
                      % {'storage_groupname': storage_groupname,
                         'hostname': hostname,
                         'out': out})

            if rc != 0:
                msg = (_('Failed to connect %s'), hostname)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return hostname

    def find_device_details(self, volume, storage_group):
        """Returns the Host Device number for the volume."""

        allocated_lun_id = self._find_lun_id(volume["name"])
        host_lun_id = -1
        owner_sp = ""
        lun_map = {}

        sg_list = ('storagegroup', '-list', '-gname', storage_group)
        out, rc = self._cli_execute(*sg_list)
        if out.find('HLU/ALU Pairs') == -1:
            LOG.info(_('NO LUNs in the storagegroup : %s ')
                     % (storage_group))
        else:
            sg_details = out.split('HLU/ALU Pairs:')[1]
            sg_lun_details = sg_details.split('Shareable')[0]
            lun_details = sg_lun_details.split('\n')

            for data in lun_details:
                if data not in ['', '  HLU Number     ALU Number',
                                '  ----------     ----------']:
                    data = data.strip()
                    items = data.split(' ')
                    lun_map[int(items[len(items) - 1])] = int(items[0])
            for lun in lun_map.iterkeys():
                if lun == int(allocated_lun_id):
                    host_lun_id = lun_map[lun]
                    LOG.debug(_('Host Lun Id : %s') % (host_lun_id))
                    break

        # finding the owner SP for the LUN
        lun_list = ('lun', '-list', '-l', allocated_lun_id, '-owner')
        out, rc = self._cli_execute(*lun_list)
        if rc == 0:
            output = out.split('\n')
            owner_sp = output[2].split('Current Owner:  SP ')[1]
            LOG.debug(_('Owner SP : %s') % (owner_sp))

        device = {
            'hostlunid': host_lun_id,
            'ownersp': owner_sp,
            'lunmap': lun_map,
        }
        return device

    def _get_host_lun_id(self, host_lun_id_list):
        # Returns the host lun id for the LUN to be added
        # in the storage group.

        used_hlu_set = set(host_lun_id_list)
        for hlu in self.hlu_set - used_hlu_set:
            return hlu
        return None

    def _add_lun_to_storagegroup(self, volume, storage_group):

        storage_groupname = storage_group
        volumename = volume['name']
        allocated_lun_id = self._find_lun_id(volumename)
        count = 0
        while(count < 5):
            device_info = self.find_device_details(volume, storage_group)
            device_number = device_info['hostlunid']
            if device_number < 0:
                lun_map = device_info['lunmap']
                if lun_map:
                    host_lun_id_list = lun_map.values()

                    if len(host_lun_id_list) >= self.max_luns:
                        msg = (_('The storage group has reached the '
                               'maximum capacity of LUNs. '
                               'Command to add LUN for volume - %s '
                               'in storagegroup failed') % (volumename))
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)

                    host_lun_id = self._get_host_lun_id(host_lun_id_list)

                    if host_lun_id is None:
                        msg = (_('Unable to get new host lun id. Please '
                               'check if the storage group can accommodate '
                               'new LUN. '
                               'Command to add LUN for volume - %s '
                               'in storagegroup failed') % (volumename))
                        LOG.error(msg)
                        raise exception.VolumeBackendAPIException(data=msg)
                else:
                    host_lun_id = 1

                addhlu = ('storagegroup', '-addhlu', '-o',
                          '-gname', storage_groupname,
                          '-hlu', host_lun_id,
                          '-alu', allocated_lun_id)
                out, rc = self._cli_execute(*addhlu)
                LOG.debug(_('Add ALU %(alu)s to SG %(sg)s as %(hlu)s. '
                          'Output: %(out)s')
                          % {'alu': allocated_lun_id,
                             'sg': storage_groupname,
                             'hlu': host_lun_id,
                             'out': out})
                if rc == 0:
                    return host_lun_id
                if rc == 66:
                    LOG.warn(_('Requested Host LUN Number already in use'))
                count += 1
            else:
                LOG.warn(_('LUN was already added in the storage group'))
                return device_number

        if count == 5:
            msg = (_('Failed to add %s into SG') % (volumename))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _remove_lun_from_storagegroup(self, device_number, storage_group):

        storage_groupname = storage_group
        removehlu = ('storagegroup', '-removehlu',
                     '-gname', storage_groupname,
                     '-hlu', device_number,
                     '-o')

        out, rc = self._cli_execute(*removehlu)

        LOG.debug(_('Remove %(hlu)s from SG %(sg)s. Output: %(out)s')
                  % {'hlu': device_number,
                     'sg': storage_groupname,
                     'out': out})
        if rc != 0:
            msg = (_('Failed to remove %(hlu)s from %(sg)s')
                   % {'hlu': device_number, 'sg': storage_groupname})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""

        hostname = connector['host']
        storage_group = self.get_storage_group(hostname)

        device_number = self._add_lun_to_storagegroup(volume, storage_group)
        return device_number

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector."""
        hostname = connector['host']
        storage_group = self.get_storage_group(hostname)
        device_info = self.find_device_details(volume, storage_group)
        device_number = device_info['hostlunid']
        if device_number < 0:
            LOG.error(_('Could not locate the attached volume.'))
        else:
            self._remove_lun_from_storagegroup(device_number, storage_group)

    def _find_iscsi_protocol_endpoints(self, device_sp):
        """Returns the iSCSI initiators for a SP."""

        initiator_address = []

        connection_getport = ('connection', '-getport', '-sp', device_sp)
        out, _rc = self._cli_execute(*connection_getport)
        output = out.split('SP:  ')

        for port in output:
            port_info = port.split('\n')
            if port_info[0] == device_sp:
                port_wwn = port_info[2].split('Port WWN:')[1].strip()
                initiator_address.append(port_wwn)

        LOG.debug(_('WWNs found for SP %(devicesp)s '
                  'are: %(initiator_address)s')
                  % {'devicesp': device_sp,
                     'initiator_address': initiator_address})

        return initiator_address

    def _get_volumetype_extraspecs(self, volume):
        specs = {}

        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)

        return specs

    def _get_provisioning_by_volume(self, volume):
        # By default, the user can not create thin LUN without thin
        # provisioning enabler.
        thinness = 'NonThin'
        spec_id = 'storagetype:provisioning'

        specs = self._get_volumetype_extraspecs(volume)
        if specs and spec_id in specs:
            provisioning = specs[spec_id].lower()
            if 'thin' == provisioning:
                thinness = 'Thin'
            elif 'thick' != provisioning:
                LOG.warning(_('Invalid value of extra spec '
                            '\'storagetype:provisioning\': %(provisioning)s')
                            % {'provisioning': specs[spec_id]})
        else:
            LOG.info(_('No extra spec \'storagetype:provisioning\' exist'))

        return thinness
