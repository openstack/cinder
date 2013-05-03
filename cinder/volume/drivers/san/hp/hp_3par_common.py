# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    (c) Copyright 2012-2013 Hewlett-Packard Development Company, L.P.
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
The 3PAR drivers requires 3.1.2 firmware on the 3PAR array.

You will need to install the python hp3parclient.
sudo pip install hp3parclient

The drivers uses both the REST service and the SSH
command line to correctly operate.  Since the
ssh credentials and the REST credentials can be different
we need to have settings for both.

The drivers requires the use of the san_ip, san_login,
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
import time
import uuid

from eventlet import greenthread
from hp3parclient import exceptions as hpexceptions
from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import volume_types

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
               help="3PAR Super user password",
               secret=True),
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


class HP3PARCommon():

    stats = {}

    # Valid values for volume type extra specs
    # The first value in the list is the default value
    valid_prov_values = ['thin', 'full']
    valid_persona_values = ['1 - Generic',
                            '2 - Generic-ALUA',
                            '6 - Generic-legacy',
                            '7 - HPUX-legacy',
                            '8 - AIX-legacy',
                            '9 - EGENERA',
                            '10 - ONTAP-legacy',
                            '11 - VMware']

    def __init__(self, config):
        self.sshpool = None
        self.config = config

    def check_flags(self, options, required_flags):
        for flag in required_flags:
            if not getattr(options, flag, None):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)

    def _get_3par_vol_name(self, volume_id):
        """
        Converts the openstack volume id from
        ecffc30f-98cb-4cf5-85ee-d7309cc17cd2
        to
        osv-7P.DD5jLTPWF7tcwnMF80g

        We convert the 128 bits of the uuid into a 24character long
        base64 encoded string to ensure we don't exceed the maximum
        allowed 31 character name limit on 3Par

        We strip the padding '=' and replace + with .
        and / with -
        """
        volume_name = self._encode_name(volume_id)
        return "osv-%s" % volume_name

    def _get_3par_snap_name(self, snapshot_id):
        snapshot_name = self._encode_name(snapshot_id)
        return "oss-%s" % snapshot_name

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.b64encode(vol_uuid.bytes)

        # 3par doesn't allow +, nor /
        vol_encoded = vol_encoded.replace('+', '.')
        vol_encoded = vol_encoded.replace('/', '-')
        # strip off the == as 3par doesn't like those.
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
        """ Runs a CLI command over SSH, without doing any result parsing. """
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
        command.
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

        # stdin.write('process_input would go here')
        # stdin.flush()

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
            self.sshpool = utils.SSHPool(self.config.san_ip,
                                         self.config.san_ssh_port,
                                         self.config.ssh_conn_timeout,
                                         self.config.san_login,
                                         password=self.config.san_password,
                                         privatekey=
                                         self.config.san_private_key,
                                         min_size=
                                         self.config.ssh_min_pool_conn,
                                         max_size=
                                         self.config.ssh_max_pool_conn)
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
        for 3PAR host names.
        """
        try:
            index = hostname.index('.')
        except ValueError:
            # couldn't find it
            index = len(hostname)

        # we'll just chop this off for now.
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

    def get_ports(self):
        # First get the active FC ports
        out = self._cli_run('showport', None)

        # strip out header
        # N:S:P,Mode,State,----Node_WWN----,-Port_WWN/HW_Addr-,Type,
        # Protocol,Label,Partner,FailoverState
        out = out[1:len(out) - 2]

        ports = {'FC': [], 'iSCSI': []}
        for line in out:
            tmp = line.split(',')

            if tmp:
                if tmp[1] == 'target' and tmp[2] == 'ready':
                    if tmp[6] == 'FC':
                        ports['FC'].append(tmp[4])

        # now get the active iSCSI ports
        out = self._cli_run('showport -iscsi', None)

        # strip out header
        # N:S:P,State,IPAddr,Netmask,Gateway,
        # TPGT,MTU,Rate,DHCP,iSNS_Addr,iSNS_Port
        out = out[1:len(out) - 2]
        for line in out:
            tmp = line.split(',')

            if tmp:
                if tmp[1] == 'ready':
                    ports['iSCSI'].append(tmp[2])

        LOG.debug("PORTS = %s" % pprint.pformat(ports))
        return ports

    def get_volume_stats(self, refresh, client):
        # const to convert MiB to GB
        const = 0.0009765625

        if refresh:
            self._update_volume_stats(client)

        return self.stats

    def _update_volume_stats(self, client):

        # storage_protocol and volume_backend_name are
        # set in the child classes
        stats = {'driver_version': '1.0',
                 'free_capacity_gb': 'unknown',
                 'reserved_percentage': 0,
                 'storage_protocol': None,
                 'total_capacity_gb': 'unknown',
                 'vendor_name': 'Hewlett-Packard',
                 'volume_backend_name': None}

        try:
            cpg = client.getCPG(self.config.hp3par_cpg)
            if 'limitMiB' not in cpg['SDGrowth']:
                total_capacity = 'infinite'
                free_capacity = 'infinite'
            else:
                total_capacity = int(cpg['SDGrowth']['limitMiB'] * const)
                free_capacity = int((cpg['SDGrowth']['limitMiB'] -
                                    cpg['UsrUsage']['usedMiB']) * const)

            stats['total_capacity_gb'] = total_capacity
            stats['free_capacity_gb'] = free_capacity
        except hpexceptions.HTTPNotFound:
            err = (_("CPG (%s) doesn't exist on array")
                   % self.config.hp3par_cpg)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        self.stats = stats

    def create_vlun(self, volume, host, client):
        """
        In order to export a volume on a 3PAR box, we have to
        create a VLUN.
        """
        volume_name = self._get_3par_vol_name(volume['id'])
        self._create_3par_vlun(volume_name, host['name'])
        return client.getVLUN(volume_name)

    def delete_vlun(self, volume, connector, client):
        hostname = self._safe_hostname(connector['host'])

        volume_name = self._get_3par_vol_name(volume['id'])
        vlun = client.getVLUN(volume_name)
        client.deleteVLUN(volume_name, vlun['lun'], hostname)
        self._delete_3par_host(hostname)

    def _get_volume_type(self, type_id):
        ctxt = context.get_admin_context()
        return volume_types.get_volume_type(ctxt, type_id)

    def _get_volume_type_value(self, volume_type, key, default=None):
        if volume_type is not None:
            specs = volume_type.get('extra_specs')
            if key in specs:
                return specs[key]
            else:
                return default
        else:
            return default

    def get_persona_type(self, volume):
        default_persona = self.valid_persona_values[0]
        type_id = volume.get('volume_type_id', None)
        volume_type = None
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
        persona_value = self._get_volume_type_value(volume_type, 'persona',
                                                    default_persona)
        if persona_value not in self.valid_persona_values:
            err = _("Must specify a valid persona %(valid)s, "
                    "value '%(persona)s' is invalid.") % \
                   ({'valid': self.valid_persona_values,
                     'persona': persona_value})
            raise exception.InvalidInput(reason=err)
        # persona is set by the id so remove the text and return the id
        # i.e for persona '1 - Generic' returns 1
        persona_id = persona_value.split(' ')
        return persona_id[0]

    @lockutils.synchronized('3par', 'cinder-', True)
    def create_volume(self, volume, client):
        LOG.debug("CREATE VOLUME (%s : %s %s)" %
                  (volume['display_name'], volume['name'],
                   self._get_3par_vol_name(volume['id'])))
        try:
            comments = {'volume_id': volume['id'],
                        'name': volume['name'],
                        'type': 'OpenStack'}

            name = volume.get('display_name', None)
            if name:
                comments['display_name'] = name

            # get the options supported by volume types
            volume_type = None
            type_id = volume.get('volume_type_id', None)
            if type_id is not None:
                volume_type = self._get_volume_type(type_id)

            cpg = self._get_volume_type_value(volume_type, 'cpg',
                                              self.config.hp3par_cpg)

            # if provisioning is not set use thin
            default_prov = self.valid_prov_values[0]
            prov_value = self._get_volume_type_value(volume_type,
                                                     'provisioning',
                                                     default_prov)
            # check for valid provisioning type
            if prov_value not in self.valid_prov_values:
                err = _("Must specify a valid provisioning type %(valid)s, "
                        "value '%(prov)s' is invalid.") % \
                       ({'valid': self.valid_prov_values,
                         'prov': prov_value})
                raise exception.InvalidInput(reason=err)

            ttpv = True
            if prov_value == "full":
                ttpv = False

            # default to hp3par_cpg if hp3par_cpg_snap is not set.
            if self.config.hp3par_cpg_snap == "":
                snap_default = self.config.hp3par_cpg
            else:
                snap_default = self.config.hp3par_cpg_snap
            snap_cpg = self._get_volume_type_value(volume_type,
                                                   'snap_cpg',
                                                   snap_default)

            # check for valid persona even if we don't use it until
            # attach time, this will given end user notice that the
            # persona type is invalid at volume creation time
            self.get_persona_type(volume)

            if type_id is not None:
                comments['volume_type_name'] = volume_type.get('name')
                comments['volume_type_id'] = type_id

            extras = {'comment': json.dumps(comments),
                      'snapCPG': snap_cpg,
                      'tpvv': ttpv}

            capacity = self._capacity_from_size(volume['size'])
            volume_name = self._get_3par_vol_name(volume['id'])
            client.createVolume(volume_name, cpg, capacity, extras)

        except hpexceptions.HTTPConflict:
            raise exception.Duplicate(_("Volume (%s) already exists on array")
                                      % volume_name)
        except hpexceptions.HTTPBadRequest as ex:
            LOG.error(str(ex))
            raise exception.Invalid(ex.get_description())
        except exception.InvalidInput as ex:
            LOG.error(str(ex))
            raise ex
        except Exception as ex:
            LOG.error(str(ex))
            raise exception.CinderException(ex.get_description())

        metadata = {'3ParName': volume_name, 'CPG': self.config.hp3par_cpg,
                    'snapCPG': extras['snapCPG']}
        return metadata

    @lockutils.synchronized('3parcopy', 'cinder-', True)
    def _copy_volume(self, src_name, dest_name):
        self._cli_run('createvvcopy -p %s %s' % (src_name, dest_name), None)

    @lockutils.synchronized('3parstate', 'cinder-', True)
    def _get_volume_state(self, vol_name):
        out = self._cli_run('showvv -state %s' % vol_name, None)
        status = None
        if out:
            # out[0] is the header
            info = out[1].split(',')
            status = info[5]

        return status

    @lockutils.synchronized('3parclone', 'cinder-', True)
    def create_cloned_volume(self, volume, src_vref, client):

        try:
            orig_name = self._get_3par_vol_name(volume['source_volid'])
            vol_name = self._get_3par_vol_name(volume['id'])
            # We need to create a new volume first.  Otherwise you
            # can't delete the original
            new_vol = self.create_volume(volume, client)

            # make the 3PAR copy the contents.
            # can't delete the original until the copy is done.
            self._copy_volume(orig_name, vol_name)

            # this can take a long time to complete
            done = False
            while not done:
                status = self._get_volume_state(vol_name)
                if status == 'normal':
                    done = True
                elif status == 'copy_target':
                    LOG.debug("3Par still copying %s => %s"
                              % (orig_name, vol_name))
                else:
                    msg = _("Unexpected state while cloning %s") % status
                    LOG.warn(msg)
                    raise exception.CinderException(msg)

                if not done:
                    # wait 5 seconds between tests
                    time.sleep(5)

            return new_vol
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()
        except Exception as ex:
            LOG.error(str(ex))
            raise exception.CinderException(ex)

        return None

    @lockutils.synchronized('3par', 'cinder-', True)
    def delete_volume(self, volume, client):
        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            client.deleteVolume(volume_name)
        except hpexceptions.HTTPNotFound as ex:
            # We'll let this act as if it worked
            # it helps clean up the cinder entries.
            LOG.error(str(ex))
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
                   pprint.pformat(snapshot['display_name'])))

        if snapshot['volume_size'] != volume['size']:
            err = "You cannot change size of the volume.  It must "
            "be the same as the snapshot."
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            vol_name = self._get_3par_vol_name(volume['id'])

            extra = {'volume_id': volume['id'],
                     'snapshot_id': snapshot['id']}
            name = snapshot.get('display_name', None)
            if name:
                extra['name'] = name

            description = snapshot.get('display_description', None)
            if description:
                extra['description'] = description

            optional = {'comment': json.dumps(extra),
                        'readOnly': False}

            client.createSnapshot(vol_name, snap_name, optional)
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()

    @lockutils.synchronized('3par', 'cinder-', True)
    def create_snapshot(self, snapshot, client):
        LOG.debug("Create Snapshot\n%s" % pprint.pformat(snapshot))

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            vol_name = self._get_3par_vol_name(snapshot['volume_id'])

            extra = {'volume_name': snapshot['volume_name']}
            vol_id = snapshot.get('volume_id', None)
            if vol_id:
                extra['volume_id'] = vol_id

            try:
                extra['name'] = snapshot['display_name']
            except AttribteError:
                pass

            try:
                extra['description'] = snapshot['display_description']
            except AttribteError:
                pass

            optional = {'comment': json.dumps(extra),
                        'readOnly': True}
            if self.config.hp3par_snapshot_expiration:
                optional['expirationHours'] = (
                    self.config.hp3par_snapshot_expiration)

            if self.config.hp3par_snapshot_retention:
                optional['retentionHours'] = (
                    self.config.hp3par_snapshot_retention)

            client.createSnapshot(snap_name, vol_name, optional)
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()

    @lockutils.synchronized('3par', 'cinder-', True)
    def delete_snapshot(self, snapshot, client):
        LOG.debug("Delete Snapshot\n%s" % pprint.pformat(snapshot))

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            client.deleteVolume(snap_name)
        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound as ex:
            LOG.error(str(ex))
