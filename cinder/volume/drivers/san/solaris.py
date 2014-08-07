#    Copyright 2012 OpenStack Foundation
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

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san.san import SanISCSIDriver

LOG = logging.getLogger(__name__)

solaris_opts = [
    cfg.StrOpt('san_zfs_volume_base',
               default='rpool/',
               help='The ZFS path under which to create zvols for volumes.'), ]

CONF = cfg.CONF
CONF.register_opts(solaris_opts)


class SolarisISCSIDriver(SanISCSIDriver):
    """Executes commands relating to Solaris-hosted ISCSI volumes.

    Basic setup for a Solaris iSCSI server:

    pkg install storage-server SUNWiscsit

    svcadm enable stmf

    svcadm enable -r svc:/network/iscsi/target:default

    pfexec itadm create-tpg e1000g0 ${MYIP}

    pfexec itadm create-target -t e1000g0


    Then grant the user that will be logging on lots of permissions.
    I'm not sure exactly which though:

    zfs allow justinsb create,mount,destroy rpool

    usermod -P'File System Management' justinsb

    usermod -P'Primary Administrator' justinsb

    Also make sure you can login using san_login & san_password/san_private_key
    """
    def __init__(self, *cmd, **kwargs):
        super(SolarisISCSIDriver, self).__init__(execute=self.solaris_execute,
                                                 *cmd, **kwargs)
        self.configuration.append_config_values(solaris_opts)

    def solaris_execute(self, *cmd, **kwargs):
        new_cmd = ['pfexec']
        new_cmd.extend(cmd)
        return super(SolarisISCSIDriver, self).san_execute(*new_cmd, **kwargs)

    def _view_exists(self, luid):
        (out, _err) = self._execute('/usr/sbin/stmfadm',
                                    'list-view', '-l', luid,
                                    check_exit_code=False)
        if "no views found" in out:
            return False

        if "View Entry:" in out:
            return True
        msg = _("Cannot parse list-view output: %s") % out
        raise exception.VolumeBackendAPIException(data=msg)

    def _get_target_groups(self):
        """Gets list of target groups from host."""
        (out, _err) = self._execute('/usr/sbin/stmfadm', 'list-tg')
        matches = self._get_prefixed_values(out, 'Target group: ')
        LOG.debug("target_groups=%s" % matches)
        return matches

    def _target_group_exists(self, target_group_name):
        return target_group_name not in self._get_target_groups()

    def _get_target_group_members(self, target_group_name):
        (out, _err) = self._execute('/usr/sbin/stmfadm',
                                    'list-tg', '-v', target_group_name)
        matches = self._get_prefixed_values(out, 'Member: ')
        LOG.debug("members of %s=%s" % (target_group_name, matches))
        return matches

    def _is_target_group_member(self, target_group_name, iscsi_target_name):
        return iscsi_target_name in (
            self._get_target_group_members(target_group_name))

    def _get_iscsi_targets(self):
        (out, _err) = self._execute('/usr/sbin/itadm', 'list-target')
        matches = self._collect_lines(out)

        # Skip header
        if len(matches) != 0:
            assert 'TARGET NAME' in matches[0]
            matches = matches[1:]

        targets = []
        for line in matches:
            items = line.split()
            assert len(items) == 3
            targets.append(items[0])

        LOG.debug("_get_iscsi_targets=%s" % (targets))
        return targets

    def _iscsi_target_exists(self, iscsi_target_name):
        return iscsi_target_name in self._get_iscsi_targets()

    def _build_zfs_poolname(self, volume):
        zfs_poolname = '%s%s' % (self.configuration.san_zfs_volume_base,
                                 volume['name'])
        return zfs_poolname

    def create_volume(self, volume):
        """Creates a volume."""
        if int(volume['size']) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % volume['size']

        zfs_poolname = self._build_zfs_poolname(volume)

        # Create a zfs volume
        cmd = ['/usr/sbin/zfs', 'create']
        if self.configuration.san_thin_provision:
            cmd.append('-s')
        cmd.extend(['-V', sizestr])
        cmd.append(zfs_poolname)
        self._execute(*cmd)

    def _get_luid(self, volume):
        zfs_poolname = self._build_zfs_poolname(volume)
        zvol_name = '/dev/zvol/rdsk/%s' % zfs_poolname

        (out, _err) = self._execute('/usr/sbin/sbdadm', 'list-lu')

        lines = self._collect_lines(out)

        # Strip headers
        if len(lines) >= 1:
            if lines[0] == '':
                lines = lines[1:]

        if len(lines) >= 4:
            assert 'Found' in lines[0]
            assert '' == lines[1]
            assert 'GUID' in lines[2]
            assert '------------------' in lines[3]

            lines = lines[4:]

        for line in lines:
            items = line.split()
            assert len(items) == 3
            if items[2] == zvol_name:
                luid = items[0].strip()
                return luid

        msg = _('LUID not found for %(zfs_poolname)s. '
                'Output=%(out)s') % {'zfs_poolname': zfs_poolname, 'out': out}
        raise exception.VolumeBackendAPIException(data=msg)

    def _is_lu_created(self, volume):
        luid = self._get_luid(volume)
        return luid

    def delete_volume(self, volume):
        """Deletes a volume."""
        zfs_poolname = self._build_zfs_poolname(volume)
        self._execute('/usr/sbin/zfs', 'destroy', zfs_poolname)

    def local_path(self, volume):
        # TODO(justinsb): Is this needed here?
        escaped_group = self.configuration.volume_group.replace('-', '--')
        escaped_name = volume['name'].replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        #TODO(justinsb): On bootup, this is called for every volume.
        # It then runs ~5 SSH commands for each volume,
        # most of which fetch the same info each time
        # This makes initial start stupid-slow
        return self._do_export(volume, force_create=False)

    def create_export(self, context, volume):
        return self._do_export(volume, force_create=True)

    def _do_export(self, volume, force_create):
        # Create a Logical Unit (LU) backed by the zfs volume
        zfs_poolname = self._build_zfs_poolname(volume)

        if force_create or not self._is_lu_created(volume):
            zvol_name = '/dev/zvol/rdsk/%s' % zfs_poolname
            self._execute('/usr/sbin/sbdadm', 'create-lu', zvol_name)

        luid = self._get_luid(volume)
        iscsi_name = self._build_iscsi_target_name(volume)
        target_group_name = 'tg-%s' % volume['name']

        # Create a iSCSI target, mapped to just this volume
        if force_create or not self._target_group_exists(target_group_name):
            self._execute('/usr/sbin/stmfadm', 'create-tg', target_group_name)

        # Yes, we add the initiatior before we create it!
        # Otherwise, it complains that the target is already active
        if force_create or not self._is_target_group_member(target_group_name,
                                                            iscsi_name):
            self._execute('/usr/sbin/stmfadm',
                          'add-tg-member', '-g', target_group_name, iscsi_name)

        if force_create or not self._iscsi_target_exists(iscsi_name):
            self._execute('/usr/sbin/itadm', 'create-target', '-n', iscsi_name)

        if force_create or not self._view_exists(luid):
            self._execute('/usr/sbin/stmfadm',
                          'add-view', '-t', target_group_name, luid)

        #TODO(justinsb): Is this always 1? Does it matter?
        iscsi_portal_interface = '1'
        iscsi_portal = \
            self.configuration.san_ip + ":3260," + iscsi_portal_interface

        db_update = {}
        db_update['provider_location'] = ("%s %s" %
                                          (iscsi_portal,
                                           iscsi_name))

        return db_update

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""

        # This is the reverse of _do_export
        luid = self._get_luid(volume)
        iscsi_name = self._build_iscsi_target_name(volume)
        target_group_name = 'tg-%s' % volume['name']

        if self._view_exists(luid):
            self._execute('/usr/sbin/stmfadm', 'remove-view', '-l', luid, '-a')

        if self._iscsi_target_exists(iscsi_name):
            self._execute('/usr/sbin/stmfadm', 'offline-target', iscsi_name)
            self._execute('/usr/sbin/itadm', 'delete-target', iscsi_name)

        # We don't delete the tg-member; we delete the whole tg!

        if self._target_group_exists(target_group_name):
            self._execute('/usr/sbin/stmfadm', 'delete-tg', target_group_name)

        if self._is_lu_created(volume):
            self._execute('/usr/sbin/sbdadm', 'delete-lu', luid)

    def _collect_lines(self, data):
        """Split lines from data into an array, trimming them."""
        matches = []
        for line in data.splitlines():
            match = line.strip()
            matches.append(match)
        return matches

    def _get_prefixed_values(self, data, prefix):
        """Collect lines which start with prefix; with trimming."""
        matches = []
        for line in data.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                match = line[len(prefix):]
                match = match.strip()
                matches.append(match)
        return matches
