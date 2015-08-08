# Copyright 2015 HGST
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
Desc    : Driver to store Cinder volumes using HGST Flash Storage Suite
Require : HGST Flash Storage Suite
Author  : Earle F. Philhower, III <earle.philhower.iii@hgst.com>
"""

import grp
import json
import math
import os
import pwd
import six
import socket
import string

from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.i18n import _LE
from cinder.i18n import _LW
from cinder.image import image_utils
from cinder.volume import driver
from cinder.volume import utils as volutils

LOG = logging.getLogger(__name__)

hgst_opts = [
    cfg.StrOpt('hgst_net',
               default='Net 1 (IPv4)',
               help='Space network name to use for data transfer'),
    cfg.StrOpt('hgst_storage_servers',
               default='os:gbd0',
               help='Comma separated list of Space storage servers:devices. '
                    'ex: os1_stor:gbd0,os2_stor:gbd0'),
    cfg.StrOpt('hgst_redundancy',
               default='0',
               help='Should spaces be redundantly stored (1/0)'),
    cfg.StrOpt('hgst_space_user',
               default='root',
               help='User to own created spaces'),
    cfg.StrOpt('hgst_space_group',
               default='disk',
               help='Group to own created spaces'),
    cfg.StrOpt('hgst_space_mode',
               default='0600',
               help='UNIX mode for created spaces'),
]


CONF = cfg.CONF
CONF.register_opts(hgst_opts)


class HGSTDriver(driver.VolumeDriver):
    """This is the Class to set in cinder.conf (volume_driver).

    Implements a Cinder Volume driver which creates a HGST Space for each
    Cinder Volume or Snapshot requested.  Use the vgc-cluster CLI to do
    all management operations.

    The Cinder host will nominally have all Spaces made visible to it,
    while individual compute nodes will only have Spaces connected to KVM
    instances connected.
    """

    VERSION = '1.0.0'
    VGCCLUSTER = 'vgc-cluster'
    SPACEGB = units.G - 16 * units.M  # Workaround for shrinkage Bug 28320
    BLOCKED = "BLOCKED"  # Exit code when a command is blocked

    def __init__(self, *args, **kwargs):
        """Initialize our protocol descriptor/etc."""
        super(HGSTDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(hgst_opts)
        self._vgc_host = None
        self.check_for_setup_error()
        self._stats = {'driver_version': self.VERSION,
                       'reserved_percentage': 0,
                       'storage_protocol': 'hgst',
                       'total_capacity_gb': 'unknown',
                       'free_capacity_gb': 'unknown',
                       'vendor_name': 'HGST',
                       }
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats['volume_backend_name'] = backend_name or 'hgst'
        self.update_volume_stats()

    def _log_cli_err(self, err):
        """Dumps the full command output to a logfile in error cases."""
        LOG.error(_LE("CLI fail: '%(cmd)s' = %(code)s\nout: %(stdout)s\n"
                      "err: %(stderr)s"),
                  {'cmd': err.cmd, 'code': err.exit_code,
                   'stdout': err.stdout, 'stderr': err.stderr})

    def _find_vgc_host(self):
        """Finds vgc-cluster hostname for this box."""
        params = [self.VGCCLUSTER, "domain-list", "-1"]
        try:
            out, unused = self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Unable to get list of domain members, check that "
                    "the cluster is running.")
            raise exception.VolumeDriverException(message=msg)
        domain = out.splitlines()
        params = ["ip", "addr", "list"]
        try:
            out, unused = self._execute(*params, run_as_root=False)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Unable to get list of IP addresses on this host, "
                    "check permissions and networking.")
            raise exception.VolumeDriverException(message=msg)
        nets = out.splitlines()
        for host in domain:
            try:
                ip = socket.gethostbyname(host)
                for l in nets:
                    x = l.strip()
                    if x.startswith("inet %s/" % ip):
                        return host
            except socket.error:
                pass
        msg = _("Current host isn't part of HGST domain.")
        raise exception.VolumeDriverException(message=msg)

    def _hostname(self):
        """Returns hostname to use for cluster operations on this box."""
        if self._vgc_host is None:
            self._vgc_host = self._find_vgc_host()
        return self._vgc_host

    def _make_server_list(self):
        """Converts a comma list into params for use by HGST CLI."""
        csv = self.configuration.safe_get('hgst_storage_servers')
        servers = csv.split(",")
        params = []
        for server in servers:
            params.append('-S')
            params.append(six.text_type(server))
        return params

    def _make_space_name(self, name):
        """Generates the hashed name for the space from the name.

        This must be called in a locked context as there are race conditions
        where 2 contexts could both pick what they think is an unallocated
        space name, and fail later on due to that conflict.
        """
        # Sanitize the name string
        valid_chars = "-_.%s%s" % (string.ascii_letters, string.digits)
        name = ''.join(c for c in name if c in valid_chars)
        name = name.strip(".")  # Remove any leading .s from evil users
        name = name or "space"  # In case of all illegal chars, safe default
        # Start out with just the name, truncated to 14 characters
        outname = name[0:13]
        # See what names already defined
        params = [self.VGCCLUSTER, "space-list", "--name-only"]
        try:
            out, unused = self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Unable to get list of spaces to make new name.  Please "
                    "verify the cluster is running.")
            raise exception.VolumeDriverException(message=msg)
        names = out.splitlines()
        # And anything in /dev/* is also illegal
        names += os.listdir("/dev")  # Do it the Python way!
        names += ['.', '..']  # Not included above
        # While there's a conflict, add incrementing digits until it passes
        itr = 0
        while outname in names:
            itrstr = six.text_type(itr)
            outname = outname[0:13 - len(itrstr)] + itrstr
            itr += 1
        return outname

    def _get_space_size_redundancy(self, space_name):
        """Parse space output to get allocated size and redundancy."""
        params = [self.VGCCLUSTER, "space-list", "-n", space_name, "--json"]
        try:
            out, unused = self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Unable to get information on space %(space)s, please "
                    "verify that the cluster is running and "
                    "connected.") % {'space': space_name}
            raise exception.VolumeDriverException(message=msg)
        ret = json.loads(out)
        retval = {}
        retval['redundancy'] = int(ret['resources'][0]['redundancy'])
        retval['sizeBytes'] = int(ret['resources'][0]['sizeBytes'])
        return retval

    def _adjust_size_g(self, size_g):
        """Adjust space size to next legal value because of redundancy."""
        # Extending requires expanding to a multiple of the # of
        # storage hosts in the cluster
        count = len(self._make_server_list()) / 2  # Remove -s from count
        if size_g % count:
            size_g = int(size_g + count)
            size_g -= size_g % count
        return int(math.ceil(size_g))

    def do_setup(self, context):
        pass

    def _get_space_name(self, volume):
        """Pull name of /dev/<space> from the provider_id."""
        try:
            return volume.get('provider_id')
        except Exception:
            return ''  # Some error during create, may be able to continue

    def _handle_blocked(self, err, msg):
        """Safely handle a return code of BLOCKED from a cluster command.

        Handle the case where a command is in BLOCKED state by trying to
        cancel it.  If the cancel fails, then the command actually did
        complete.  If the cancel succeeds, then throw the original error
        back up the stack.
        """
        if (err.stdout is not None) and (self.BLOCKED in err.stdout):
            # Command is queued but did not complete in X seconds, so
            # we will cancel it to keep things sane.
            request = err.stdout.split('\n', 1)[0].strip()
            params = [self.VGCCLUSTER, 'request-cancel']
            params += ['-r', six.text_type(request)]
            throw_err = False
            try:
                self._execute(*params, run_as_root=True)
                # Cancel succeeded, the command was aborted
                # Send initial exception up the stack
                LOG.error(_LE("VGC-CLUSTER command blocked and cancelled."))
                # Can't throw it here, the except below would catch it!
                throw_err = True
            except Exception:
                # The cancel failed because the command was just completed.
                # That means there was no failure, so continue with Cinder op
                pass
            if throw_err:
                self._log_cli_err(err)
                msg = _("Command %(cmd)s blocked in the CLI and was "
                        "cancelled") % {'cmd': six.text_type(err.cmd)}
                raise exception.VolumeDriverException(message=msg)
        else:
            # Some other error, just throw it up the chain
            self._log_cli_err(err)
            raise exception.VolumeDriverException(message=msg)

    def _add_cinder_apphost(self, spacename):
        """Add this host to the apphost list of a space."""
        # Connect to source volume
        params = [self.VGCCLUSTER, 'space-set-apphosts']
        params += ['-n', spacename]
        params += ['-A', self._hostname()]
        params += ['--action', 'ADD']  # Non-error to add already existing
        try:
            self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            msg = _("Unable to add Cinder host to apphosts for space "
                    "%(space)s") % {'space': spacename}
            self._handle_blocked(err, msg)

    @lockutils.synchronized('devices', 'cinder-hgst-')
    def create_volume(self, volume):
        """API entry to create a volume on the cluster as a HGST space.

        Creates a volume, adjusting for GiB/GB sizing.  Locked to ensure we
        don't have race conditions on the name we pick to use for the space.
        """
        # For ease of deugging, use friendly name if it exists
        volname = self._make_space_name(volume['display_name']
                                        or volume['name'])
        volnet = self.configuration.safe_get('hgst_net')
        volbytes = volume['size'] * units.Gi  # OS=Base2, but HGST=Base10
        volsize_gb_cinder = int(math.ceil(float(volbytes) /
                                float(self.SPACEGB)))
        volsize_g = self._adjust_size_g(volsize_gb_cinder)
        params = [self.VGCCLUSTER, 'space-create']
        params += ['-n', six.text_type(volname)]
        params += ['-N', six.text_type(volnet)]
        params += ['-s', six.text_type(volsize_g)]
        params += ['--redundancy', six.text_type(
                   self.configuration.safe_get('hgst_redundancy'))]
        params += ['--user', six.text_type(
                   self.configuration.safe_get('hgst_space_user'))]
        params += ['--group', six.text_type(
                   self.configuration.safe_get('hgst_space_group'))]
        params += ['--mode', six.text_type(
                   self.configuration.safe_get('hgst_space_mode'))]
        params += self._make_server_list()
        params += ['-A', self._hostname()]  # Make it visible only here
        try:
            self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            msg = _("Error in space-create for %(space)s of size "
                    "%(size)d GB") % {'space': volname,
                                      'size': int(volsize_g)}
            self._handle_blocked(err, msg)
        # Stash away the hashed name
        provider = {}
        provider['provider_id'] = volname
        return provider

    def update_volume_stats(self):
        """Parse the JSON output of vgc-cluster to find space available."""
        params = [self.VGCCLUSTER, "host-storage", "--json"]
        try:
            out, unused = self._execute(*params, run_as_root=True)
            ret = json.loads(out)
            cap = int(ret["totalCapacityBytes"] / units.Gi)
            used = int(ret["totalUsedBytes"] / units.Gi)
            avail = cap - used
            if int(self.configuration.safe_get('hgst_redundancy')) == 1:
                cap = int(cap / 2)
                avail = int(avail / 2)
            # Reduce both by 1 GB due to BZ 28320
            if cap > 0:
                cap = cap - 1
            if avail > 0:
                avail = avail - 1
        except processutils.ProcessExecutionError as err:
            # Could be cluster still starting up, return unknown for now
            LOG.warning(_LW("Unable to poll cluster free space."))
            self._log_cli_err(err)
            cap = 'unknown'
            avail = 'unknown'
        self._stats['free_capacity_gb'] = avail
        self._stats['total_capacity_gb'] = cap
        self._stats['reserved_percentage'] = 0

    def get_volume_stats(self, refresh=False):
        """Return Volume statistics, potentially cached copy."""
        if refresh:
            self.update_volume_stats()
        return self._stats

    def create_cloned_volume(self, volume, src_vref):
        """Create a cloned volume from an existing one.

        No cloning operation in the current release so simply copy using
        DD to a new space.  This could be a lengthy operation.
        """
        # Connect to source volume
        volname = self._get_space_name(src_vref)
        self._add_cinder_apphost(volname)

        # Make new volume
        provider = self.create_volume(volume)
        self._add_cinder_apphost(provider['provider_id'])

        # And copy original into it...
        info = self._get_space_size_redundancy(volname)
        volutils.copy_volume(
            self.local_path(src_vref),
            "/dev/" + provider['provider_id'],
            info['sizeBytes'] / units.Mi,
            self.configuration.volume_dd_blocksize,
            execute=self._execute)

        # That's all, folks!
        return provider

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def delete_volume(self, volume):
        """Delete a Volume's underlying space."""
        volname = self._get_space_name(volume)
        if volname:
            params = [self.VGCCLUSTER, 'space-delete']
            params += ['-n', six.text_type(volname)]
            # This can fail benignly when we are deleting a snapshot
            try:
                self._execute(*params, run_as_root=True)
            except processutils.ProcessExecutionError as err:
                LOG.warning(_LW("Unable to delete space %(space)s"),
                            {'space': volname})
                self._log_cli_err(err)
        else:
            # This can be benign when we are deleting a snapshot
            LOG.warning(_LW("Attempted to delete a space that's not there."))

    def _check_host_storage(self, server):
        if ":" not in server:
            msg = _("hgst_storage server %(svr)s not of format "
                    "<host>:<dev>") % {'svr': server}
            raise exception.VolumeDriverException(message=msg)
        h, b = server.split(":")
        try:
            params = [self.VGCCLUSTER, 'host-storage', '-h', h]
            self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Storage host %(svr)s not detected, verify "
                    "name") % {'svr': six.text_type(server)}
            raise exception.VolumeDriverException(message=msg)

    def check_for_setup_error(self):
        """Throw an exception if configuration values/setup isn't okay."""
        # Verify vgc-cluster exists and is executable by cinder user
        try:
            params = [self.VGCCLUSTER, '--version']
            self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("Cannot run vgc-cluster command, please ensure software "
                    "is installed and permissions are set properly.")
            raise exception.VolumeDriverException(message=msg)

        # Checks the host is identified with the HGST domain, as well as
        # that vgcnode and vgcclustermgr services are running.
        self._vgc_host = None
        self._hostname()

        # Redundancy better be 0 or 1, otherwise no comprendo
        r = six.text_type(self.configuration.safe_get('hgst_redundancy'))
        if r not in ["0", "1"]:
            msg = _("hgst_redundancy must be set to 0 (non-HA) or 1 (HA) in "
                    "cinder.conf.")
            raise exception.VolumeDriverException(message=msg)

        # Verify user and group exist or we can't connect volumes
        try:
            pwd.getpwnam(self.configuration.safe_get('hgst_space_user'))
            grp.getgrnam(self.configuration.safe_get('hgst_space_group'))
        except KeyError as err:
            msg = _("hgst_group %(grp)s and hgst_user %(usr)s must map to "
                    "valid users/groups in cinder.conf") % {
                'grp': self.configuration.safe_get('hgst_space_group'),
                'usr': self.configuration.safe_get('hgst_space_user')}
            raise exception.VolumeDriverException(message=msg)

        # Verify mode is a nicely formed octal or integer
        try:
            int(self.configuration.safe_get('hgst_space_mode'))
        except Exception as err:
            msg = _("hgst_space_mode must be an octal/int in cinder.conf")
            raise exception.VolumeDriverException(message=msg)

        # Validate network maps to something we know about
        try:
            params = [self.VGCCLUSTER, 'network-list']
            params += ['-N', self.configuration.safe_get('hgst_net')]
            self._execute(*params, run_as_root=True)
        except processutils.ProcessExecutionError as err:
            self._log_cli_err(err)
            msg = _("hgst_net %(net)s specified in cinder.conf not found "
                    "in cluster") % {
                'net': self.configuration.safe_get('hgst_net')}
            raise exception.VolumeDriverException(message=msg)

        # Storage servers require us to split them up and check for
        sl = self.configuration.safe_get('hgst_storage_servers')
        if (sl is None) or (six.text_type(sl) == ""):
            msg = _("hgst_storage_servers must be defined in cinder.conf")
            raise exception.VolumeDriverException(message=msg)
        servers = sl.split(",")
        # Each server must be of the format <host>:<storage> w/host in domain
        for server in servers:
            self._check_host_storage(server)

        # We made it here, we should be good to go!
        return True

    def create_snapshot(self, snapshot):
        """Create a snapshot volume.

        We don't yet support snaps in SW so make a new volume and dd the
        source one into it.  This could be a lengthy operation.
        """
        origvol = {}
        origvol['name'] = snapshot['volume_name']
        origvol['size'] = snapshot['volume_size']
        origvol['id'] = snapshot['volume_id']
        origvol['provider_id'] = snapshot.get('volume').get('provider_id')
        # Add me to the apphosts so I can see the volume
        self._add_cinder_apphost(self._get_space_name(origvol))

        # Make snapshot volume
        snapvol = {}
        snapvol['display_name'] = snapshot['display_name']
        snapvol['name'] = snapshot['name']
        snapvol['size'] = snapshot['volume_size']
        snapvol['id'] = snapshot['id']
        provider = self.create_volume(snapvol)
        # Create_volume attaches the volume to this host, ready to snapshot.
        # Copy it using dd for now, we don't have real snapshots
        # We need to copy the entire allocated volume space, Nova will allow
        # full access, even beyond requested size (when our volume is larger
        # due to our ~1B byte alignment or cluster makeup)
        info = self._get_space_size_redundancy(origvol['provider_id'])
        volutils.copy_volume(
            self.local_path(origvol),
            "/dev/" + provider['provider_id'],
            info['sizeBytes'] / units.Mi,
            self.configuration.volume_dd_blocksize,
            execute=self._execute)
        return provider

    def delete_snapshot(self, snapshot):
        """Delete a snapshot.  For now, snapshots are full volumes."""
        self.delete_volume(snapshot)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from a snapshot, but snaps still full volumes."""
        return self.create_cloned_volume(volume, snapshot)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        We may not actually need to resize the space because it's size is
        always rounded up to a function of the GiB/GB and number of storage
        nodes.
        """
        volname = self._get_space_name(volume)
        info = self._get_space_size_redundancy(volname)
        volnewbytes = new_size * units.Gi
        new_size_g = math.ceil(float(volnewbytes) / float(self.SPACEGB))
        wantedsize_g = self._adjust_size_g(new_size_g)
        havesize_g = (info['sizeBytes'] / self.SPACEGB)
        if havesize_g >= wantedsize_g:
            return  # Already big enough, happens with redundancy
        else:
            # Have to extend it
            delta = int(wantedsize_g - havesize_g)
            params = [self.VGCCLUSTER, 'space-extend']
            params += ['-n', six.text_type(volname)]
            params += ['-s', six.text_type(delta)]
            params += self._make_server_list()
            try:
                self._execute(*params, run_as_root=True)
            except processutils.ProcessExecutionError as err:
                msg = _("Error in space-extend for volume %(space)s with "
                        "%(size)d additional GB") % {'space': volname,
                                                     'size': delta}
                self._handle_blocked(err, msg)

    def initialize_connection(self, volume, connector):
        """Return connection information.

        Need to return noremovehost so that the Nova host
        doesn't accidentally remove us from the apphost list if it is
        running on the same host (like in devstack testing).
        """
        hgst_properties = {'name': volume['provider_id'],
                           'noremovehost': self._hostname()}
        return {'driver_volume_type': 'hgst',
                'data': hgst_properties}

    def local_path(self, volume):
        """Query the provider_id to figure out the proper devnode."""
        return "/dev/" + self._get_space_name(volume)

    def create_export(self, context, volume, connector):
        # Not needed for spaces
        pass

    def remove_export(self, context, volume):
        # Not needed for spaces
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        # Not needed for spaces
        pass

    def ensure_export(self, context, volume):
        # Not needed for spaces
        pass
