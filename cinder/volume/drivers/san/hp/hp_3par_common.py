# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright (c) 2012 Hewlett-Packard, Inc.
#    All Rights Reserved.
#
#    Copyright 2012 OpenStack LLC
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
#
"""
Volume driver common utilities for HP 3PAR Storage array
This driver requires 3.1.2 firmware on the 3PAR array.

The driver uses both the REST service and the SSH
command line to correctly operate.  Since the
ssh credentials and the REST credentials can be different
we need to have settings for both.

This driver requires the use of the san_ip, san_login,
san_password settings for ssh connections into the 3PAR
array.   It also requires the setting of
hp3par_api_url, hp3par_username, hp3par_password
for credentials to talk to the REST service on the 3PAR
array.
"""
import base64
import json
import paramiko
import pprint
from random import randint
import uuid

from eventlet import greenthread
from hp3parclient import exceptions as hpexceptions

from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder import utils


LOG = logging.getLogger(__name__)

hp3par_opts = [
    cfg.StrOpt('hp3par_api_url',
               default='',
               help="3PAR WSAPI Server Url like "
                    "https://<3par ip>:8080/api/v1"),
    cfg.StrOpt('hp3par_username',
               default='',
               help="3PAR Super user username"),
    cfg.StrOpt('hp3par_password',
               default='',
               help="3PAR Super user password"),
    cfg.StrOpt('hp3par_domain',
               default="OpenStack",
               help="The 3par domain name to use"),
    cfg.StrOpt('hp3par_cpg',
               default="OpenStack",
               help="The CPG to use for volume creation"),
    cfg.StrOpt('hp3par_cpg_snap',
               default="",
               help="The CPG to use for Snapshots for volumes. "
                    "If empty hp3par_cpg will be used"),
    cfg.StrOpt('hp3par_snapshot_retention',
               default="",
               help="The time in hours to retain a snapshot.  "
                    "You can't delete it before this expires."),
    cfg.StrOpt('hp3par_snapshot_expiration',
               default="",
               help="The time in hours when a snapshot expires "
                    " and is deleted.  This must be larger than expiration"),
    cfg.BoolOpt('hp3par_debug',
                default=False,
                help="Enable HTTP debugging to 3PAR")
]

FLAGS = flags.FLAGS
FLAGS.register_opts(hp3par_opts)


class HP3PARCommon():

    def __init__(self):
        self.sshpool = None

    def check_flags(self, FLAGS, required_flags):
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)

    def _get_3par_vol_name(self, name):
        """
        Converts the openstack volume name from
        volume-ecffc30f-98cb-4cf5-85ee-d7309cc17cd2
        to
        osv-7P.DD5jLTPWF7tcwnMF80g

        We convert the 128 bits of the uuid into a 24character long
        base64 encoded string to ensure we don't exceed the maximum
        allowed 31 character name limit on 3Par

        We strip the padding '=' and replace + with .
        and / with -
        """
        name = name.replace("volume-", "")
        volume_name = self._encode_name(name)
        return "osv-%s" % volume_name

    def _get_3par_snap_name(self, name):
        name = name.replace("snapshot-", "")
        snapshot_name = self._encode_name(name)
        return "oss-%s" % snapshot_name

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.b64encode(vol_uuid.bytes)

        # 3par doesn't allow +, nor /
        vol_encoded = vol_encoded.replace('+', '.')
        vol_encoded = vol_encoded.replace('/', '-')
        #strip off the == as 3par doesn't like those.
        vol_encoded = vol_encoded.replace('=', '')
        return vol_encoded

    def _capacity_from_size(self, vol_size):

        # because 3PAR volume sizes are in
        # Mebibytes, Gigibytes, not Megabytes.
        MB = 1000L
        MiB = 1.048576

        if int(vol_size) == 0:
            capacity = MB  # default: 1GB
        else:
            capacity = vol_size * MB

        capacity = int(round(capacity / MiB))
        return capacity

    def _cli_run(self, verb, cli_args):
        """Runs a CLI command over SSH, without doing any result parsing"""
        cli_arg_strings = []
        if cli_args:
            for k, v in cli_args.items():
                if k == '':
                    cli_arg_strings.append(" %s" % k)
                else:
                    cli_arg_strings.append(" %s=%s" % (k, v))

        cmd = verb + ''.join(cli_arg_strings)
        LOG.debug("SSH CMD = %s " % cmd)

        (stdout, stderr) = self._run_ssh(cmd, False)

        # we have to strip out the input and exit lines
        tmp = stdout.split("\r\n")
        out = tmp[5:len(tmp) - 2]
        return out

    def _ssh_execute(self, ssh, cmd,
                     check_exit_code=True):
        """
        We have to do this in order to get CSV output
        from the CLI command.   We first have to issue
        a command to tell the CLI that we want the output
        to be formatted in CSV, then we issue the real
        command
        """
        LOG.debug(_('Running cmd (SSH): %s'), cmd)

        channel = ssh.invoke_shell()
        stdin_stream = channel.makefile('wb')
        stdout_stream = channel.makefile('rb')
        stderr_stream = channel.makefile('rb')

        stdin_stream.write('''setclienv csvtable 1
%s
exit
''' % cmd)

        #stdin.write('process_input would go here')
        #stdin.flush()

        # NOTE(justinsb): This seems suspicious...
        # ...other SSH clients have buffering issues with this approach
        stdout = stdout_stream.read()
        stderr = stderr_stream.read()
        stdin_stream.close()
        stdout_stream.close()
        stderr_stream.close()

        exit_status = channel.recv_exit_status()

        # exit_status == -1 if no exit code was returned
        if exit_status != -1:
            LOG.debug(_('Result was %s') % exit_status)
            if check_exit_code and exit_status != 0:
                raise exception.ProcessExecutionError(exit_code=exit_status,
                                                      stdout=stdout,
                                                      stderr=stderr,
                                                      cmd=cmd)
        channel.close()
        return (stdout, stderr)

    def _run_ssh(self, command, check_exit=True, attempts=1):
        if not self.sshpool:
            self.sshpool = utils.SSHPool(FLAGS.san_ip,
                                         FLAGS.san_ssh_port,
                                         FLAGS.ssh_conn_timeout,
                                         FLAGS.san_login,
                                         password=FLAGS.san_password,
                                         privatekey=FLAGS.san_private_key,
                                         min_size=FLAGS.ssh_min_pool_conn,
                                         max_size=FLAGS.ssh_max_pool_conn)
        try:
            total_attempts = attempts
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return self._ssh_execute(ssh, command,
                                                 check_exit_code=check_exit)
                    except Exception as e:
                        LOG.error(e)
                        greenthread.sleep(randint(20, 500) / 100.0)
                raise paramiko.SSHException(_("SSH Command failed after "
                                              "'%(total_attempts)r' attempts"
                                              ": '%(command)s'"), locals())
        except Exception as e:
            LOG.error(_("Error running ssh command: %s") % command)
            raise e

    def _delete_3par_host(self, hostname):
        self._cli_run('removehost %s' % hostname, None)

    def _create_3par_vlun(self, volume, hostname):
        self._cli_run('createvlun %s auto %s' % (volume, hostname), None)

    def _safe_hostname(self, hostname):
        """
        We have to use a safe hostname length
        for 3PAR host names
        """
        try:
            index = hostname.index('.')
        except ValueError:
            # couldn't find it
            index = len(hostname)

        #we'll just chop this off for now.
        if index > 23:
            index = 23

        return hostname[:index]

    def _get_3par_host(self, hostname):
        out = self._cli_run('showhost -verbose %s' % (hostname), None)
        LOG.debug("OUTPUT = \n%s" % (pprint.pformat(out)))
        host = {'id': None, 'name': None,
                'domain': None,
                'descriptors': {},
                'iSCSIPaths': [],
                'FCPaths': []}

        if out:
            err = out[0]
            if err == 'no hosts listed':
                msg = {'code': 'NON_EXISTENT_HOST',
                       'desc': "HOST '%s' was not found" % hostname}
                raise hpexceptions.HTTPNotFound(msg)

            # start parsing the lines after the header line
            for line in out[1:]:
                if line == '':
                    break
                tmp = line.split(',')
                paths = {}

                LOG.debug("line = %s" % (pprint.pformat(tmp)))
                host['id'] = tmp[0]
                host['name'] = tmp[1]

                portPos = tmp[4]
                LOG.debug("portPos = %s" % (pprint.pformat(portPos)))
                if portPos == '---':
                    portPos = None
                else:
                    port = portPos.split(':')
                    portPos = {'node': int(port[0]), 'slot': int(port[1]),
                               'cardPort': int(port[2])}

                paths['portPos'] = portPos

                # If FC entry
                if tmp[5] == 'n/a':
                    paths['wwn'] = tmp[3]
                    host['FCPaths'].append(paths)
                # else iSCSI entry
                else:
                    paths['name'] = tmp[3]
                    paths['ipAddr'] = tmp[5]
                    host['iSCSIPaths'].append(paths)

            # find the offset to the description stuff
            offset = 0
            for line in out:
                if line[:15] == '---------- Host':
                    break
                else:
                    offset += 1

            info = out[offset + 2]
            tmp = info.split(':')
            host['domain'] = tmp[1]

            info = out[offset + 4]
            tmp = info.split(':')
            host['descriptors']['location'] = tmp[1]

            info = out[offset + 5]
            tmp = info.split(':')
            host['descriptors']['ipAddr'] = tmp[1]

            info = out[offset + 6]
            tmp = info.split(':')
            host['descriptors']['os'] = tmp[1]

            info = out[offset + 7]
            tmp = info.split(':')
            host['descriptors']['model'] = tmp[1]

            info = out[offset + 8]
            tmp = info.split(':')
            host['descriptors']['contact'] = tmp[1]

            info = out[offset + 9]
            tmp = info.split(':')
            host['descriptors']['comment'] = tmp[1]

        return host

    def create_vlun(self, volume, host, client):
        """
        In order to export a volume on a 3PAR box, we have to
        create a VLUN.
        """
        volume_name = self._get_3par_vol_name(volume['name'])
        self._create_3par_vlun(volume_name, host['name'])
        return client.getVLUN(volume_name)

    def delete_vlun(self, volume, connector, client):
        hostname = self._safe_hostname(connector['host'])

        volume_name = self._get_3par_vol_name(volume['name'])
        vlun = client.getVLUN(volume_name)
        client.deleteVLUN(volume_name, vlun['lun'], hostname)
        self._delete_3par_host(hostname)

    @lockutils.synchronized('3par', 'cinder-', True)
    def create_volume(self, volume, client, FLAGS):
        """ Create a new volume """
        LOG.debug("CREATE VOLUME (%s : %s %s)" %
                  (volume['display_name'], volume['name'],
                   self._get_3par_vol_name(volume['name'])))
        try:
            comments = {'name': volume['name'],
                        'display_name': volume['display_name'],
                        'type': 'OpenStack'}
            extras = {'comment': json.dumps(comments),
                      'snapCPG': FLAGS.hp3par_cpg_snap}

            if not FLAGS.hp3par_cpg_snap:
                extras['snapCPG'] = FLAGS.hp3par_cpg

            capacity = self._capacity_from_size(volume['size'])
            volume_name = self._get_3par_vol_name(volume['name'])
            client.createVolume(volume_name, FLAGS.hp3par_cpg,
                                capacity, extras)

        except hpexceptions.HTTPConflict:
            raise exception.Duplicate(_("Volume (%s) already exists on array")
                                      % volume_name)
        except hpexceptions.HTTPBadRequest as ex:
            LOG.error(str(ex))
            raise exception.Invalid(ex.get_description())
        except Exception as ex:
            LOG.error(str(ex))
            raise exception.CinderException(ex.get_description())

    @lockutils.synchronized('3par', 'cinder-', True)
    def delete_volume(self, volume, client):
        """ Delete a volume """
        try:
            volume_name = self._get_3par_vol_name(volume['name'])
            client.deleteVolume(volume_name)
        except hpexceptions.HTTPNotFound as ex:
            LOG.error(str(ex))
            raise exception.NotFound(ex.get_description())
        except hpexceptions.HTTPForbidden as ex:
            LOG.error(str(ex))
            raise exception.NotAuthorized(ex.get_description())
        except Exception as ex:
            LOG.error(str(ex))
            raise exception.CinderException(ex.get_description())

    @lockutils.synchronized('3par', 'cinder-', True)
    def create_volume_from_snapshot(self, volume, snapshot, client):
        """
        Creates a volume from a snapshot.

        TODO: support using the size from the user.
        """
        LOG.debug("Create Volume from Snapshot\n%s\n%s" %
                  (pprint.pformat(volume['display_name']),
                   pprint.pformat(snapshot.display_name)))
        try:
            snap_name = self._get_3par_snap_name(snapshot.name)
            vol_name = self._get_3par_vol_name(volume['name'])

            extra = {'name': snapshot.display_name,
                     'description': snapshot.display_description}

            optional = {'comment': json.dumps(extra),
                        'readOnly': False}

            client.createSnapshot(vol_name, snap_name, optional)
        except hpexceptions.HTTPForbidden as ex:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound as ex:
            raise exception.NotFound()

    @lockutils.synchronized('3par', 'cinder-', True)
    def create_snapshot(self, snapshot, client, FLAGS):
        """Creates a snapshot."""
        LOG.debug("Create Snapshot\n%s" % pprint.pformat(snapshot))

        try:
            snap_name = self._get_3par_snap_name(snapshot.name)
            vol_name = self._get_3par_vol_name(snapshot.volume_name)

            extra = {'name': snapshot.display_name,
                     'vol_name': snapshot.volume_name,
                     'description': snapshot.display_description}

            optional = {'comment': json.dumps(extra),
                        'readOnly': True}
            if FLAGS.hp3par_snapshot_expiration:
                optional['expirationHours'] = FLAGS.hp3par_snapshot_expiration

            if FLAGS.hp3par_snapshot_retention:
                optional['retentionHours'] = FLAGS.hp3par_snapshot_retention

            client.createSnapshot(snap_name, vol_name, optional)
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()

    @lockutils.synchronized('3par', 'cinder-', True)
    def delete_snapshot(self, snapshot, client):
        """Driver entry point for deleting a snapshot."""
        LOG.debug("Delete Snapshot\n%s" % pprint.pformat(snapshot))

        try:
            snap_name = self._get_3par_snap_name(snapshot.name)
            client.deleteVolume(snap_name)
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()
