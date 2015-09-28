# Copyright (c) 2014 Hitachi Data Systems, Inc.
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
#

"""
Hitachi Unified Storage (HUS-HNAS) platform. Backend operations.
"""

import re

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import units
import six

from cinder.i18n import _, _LW, _LI, _LE
from cinder import exception
from cinder import ssh_utils
from cinder import utils

LOG = logging.getLogger("cinder.volume.driver")
HNAS_SSC_RETRIES = 5


class HnasBackend(object):
    """Back end. Talks to HUS-HNAS."""
    def __init__(self, drv_configs):
        self.drv_configs = drv_configs
        self.sshpool = None

    @utils.retry(exceptions=exception.HNASConnError, retries=HNAS_SSC_RETRIES,
                 wait_random=True)
    def run_cmd(self, cmd, ip0, user, pw, *args, **kwargs):
        """Run a command on SMU or using SSH

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :return: formated string with version information
        """
        LOG.debug('Enable ssh: %s',
                  six.text_type(self.drv_configs['ssh_enabled']))

        if self.drv_configs['ssh_enabled'] != 'True':
            # Direct connection via ssc
            args = (cmd, '--user', user, '--password', pw, ip0) + args

            try:
                out, err = utils.execute(*args, **kwargs)
                LOG.debug("command %(cmd)s result: out = %(out)s - err = "
                          "%(err)s", {'cmd': cmd, 'out': out, 'err': err})
                return out, err
            except putils.ProcessExecutionError as e:
                if 'Failed to establish SSC connection' in e.stderr:
                    LOG.debug("SSC connection error!")
                    msg = _("Failed to establish SSC connection.")
                    raise exception.HNASConnError(msg)
                else:
                    raise putils.ProcessExecutionError

        else:
            if self.drv_configs['cluster_admin_ip0'] is None:
                # Connect to SMU through SSH and run ssc locally
                args = (cmd, 'localhost') + args
            else:
                args = (cmd, '--smuauth',
                        self.drv_configs['cluster_admin_ip0']) + args

            utils.check_ssh_injection(args)
            command = ' '.join(args)
            command = command.replace('"', '\\"')

            if not self.sshpool:
                server = self.drv_configs['mgmt_ip0']
                port = int(self.drv_configs['ssh_port'])
                username = self.drv_configs['username']
                # We only accept private/public key auth
                password = ""
                privatekey = self.drv_configs['ssh_private_key']
                self.sshpool = ssh_utils.SSHPool(server,
                                                 port,
                                                 None,
                                                 username,
                                                 password=password,
                                                 privatekey=privatekey)

            with self.sshpool.item() as ssh:

                try:
                    out, err = putils.ssh_execute(ssh, command,
                                                  check_exit_code=True)
                    LOG.debug("command %(cmd)s result: out = "
                              "%(out)s - err = %(err)s",
                              {'cmd': cmd, 'out': out, 'err': err})
                    return out, err
                except putils.ProcessExecutionError as e:
                    if 'Failed to establish SSC connection' in e.stderr:
                        LOG.debug("SSC connection error!")
                        msg = _("Failed to establish SSC connection.")
                        raise exception.HNASConnError(msg)
                    else:
                        raise putils.ProcessExecutionError

    def get_version(self, cmd, ver, ip0, user, pw):
        """Gets version information from the storage unit

       :param cmd: ssc command name
       :param ver: string driver version
       :param ip0: string IP address of controller
       :param user: string user authentication for array
       :param pw: string password authentication for array
       :return: formated string with version information
       """
        if (self.drv_configs['ssh_enabled'] == 'True' and
                self.drv_configs['cluster_admin_ip0'] is not None):
            util = 'SMU ' + cmd
        else:
            out, err = utils.execute(cmd,
                                     "-version",
                                     check_exit_code=True)
            util = out.split()[1]

        out, err = self.run_cmd(cmd, ip0, user, pw, "cluster-getmac",
                                check_exit_code=True)
        hardware = out.split()[2]
        out, err = self.run_cmd(cmd, ip0, user, pw, "ver",
                                check_exit_code=True)
        lines = out.split('\n')

        model = ""
        for line in lines:
            if 'Model:' in line:
                model = line.split()[1]
            if 'Software:' in line:
                ver = line.split()[1]

        out = "Array_ID: %s (%s) version: %s LU: 256 RG: 0 RG_LU: 0 \
               Utility_version: %s" % (hardware, model, ver, util)

        LOG.debug('get_version: %(out)s -- %(err)s', {'out': out, 'err': err})
        return out

    def get_iscsi_info(self, cmd, ip0, user, pw):
        """Gets IP addresses for EVSs, use EVSID as controller.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :return: formated string with iSCSI information
        """

        out, err = self.run_cmd(cmd, ip0, user, pw,
                                'evsipaddr', '-l',
                                check_exit_code=True)
        lines = out.split('\n')

        newout = ""
        for line in lines:
            if 'evs' in line and 'admin' not in line:
                inf = line.split()
                (evsnum, ip) = (inf[1], inf[3])
                newout += "CTL: %s Port: 0 IP: %s Port: 3260 Link: Up\n" \
                          % (evsnum, ip)

        LOG.debug('get_iscsi_info: %(out)s -- %(err)s',
                  {'out': out, 'err': err})
        return newout

    def get_hdp_info(self, cmd, ip0, user, pw, fslabel=None):
        """Gets the list of filesystems and fsids.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param fslabel: filesystem label we want to get info
        :return: formated string with filesystems and fsids
        """

        if fslabel is None:
            out, err = self.run_cmd(cmd, ip0, user, pw, 'df', '-a',
                                    check_exit_code=True)
        else:
            out, err = self.run_cmd(cmd, ip0, user, pw, 'df', '-f', fslabel,
                                    check_exit_code=True)

        lines = out.split('\n')
        single_evs = True

        LOG.debug("Parsing output: %s", lines)

        newout = ""
        for line in lines:
            if 'Not mounted' in line or 'Not determined' in line:
                continue
            if 'not' not in line and 'EVS' in line:
                single_evs = False
            if 'GB' in line or 'TB' in line:
                LOG.debug("Parsing output: %s", line)
                inf = line.split()

                if not single_evs:
                    (fsid, fslabel, capacity) = (inf[0], inf[1], inf[3])
                    (used, perstr) = (inf[5], inf[7])
                    (availunit, usedunit) = (inf[4], inf[6])
                else:
                    (fsid, fslabel, capacity) = (inf[0], inf[1], inf[2])
                    (used, perstr) = (inf[4], inf[6])
                    (availunit, usedunit) = (inf[3], inf[5])

                if usedunit == 'GB':
                    usedmultiplier = units.Ki
                else:
                    usedmultiplier = units.Mi
                if availunit == 'GB':
                    availmultiplier = units.Ki
                else:
                    availmultiplier = units.Mi
                m = re.match("\((\d+)\%\)", perstr)
                if m:
                    percent = m.group(1)
                else:
                    percent = 0
                newout += "HDP: %s %d MB %d MB %d %% LUs: 256 Normal %s\n" \
                          % (fsid, int(float(capacity) * availmultiplier),
                             int(float(used) * usedmultiplier),
                             int(percent), fslabel)

        LOG.debug('get_hdp_info: %(out)s -- %(err)s',
                  {'out': newout, 'err': err})
        return newout

    def get_evs(self, cmd, ip0, user, pw, fsid):
        """Gets the EVSID for the named filesystem.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :return: EVS id of the file system
        """

        out, err = self.run_cmd(cmd, ip0, user, pw, "evsfs", "list",
                                check_exit_code=True)
        LOG.debug('get_evs: out %s.', out)

        lines = out.split('\n')
        for line in lines:
            inf = line.split()
            if fsid in line and (fsid == inf[0] or fsid == inf[1]):
                return inf[3]

        LOG.warning(_LW('get_evs: %(out)s -- No find for %(fsid)s'),
                    {'out': out, 'fsid': fsid})
        return 0

    def _get_evsips(self, cmd, ip0, user, pw, evsid):
        """Gets the EVS IPs for the named filesystem."""

        out, err = self.run_cmd(cmd, ip0, user, pw,
                                'evsipaddr', '-e', evsid,
                                check_exit_code=True)

        iplist = ""
        lines = out.split('\n')
        for line in lines:
            inf = line.split()
            if 'evs' in line:
                iplist += inf[3] + ' '

        LOG.debug('get_evsips: %s', iplist)
        return iplist

    def _get_fsid(self, cmd, ip0, user, pw, fslabel):
        """Gets the FSID for the named filesystem."""

        out, err = self.run_cmd(cmd, ip0, user, pw, 'evsfs', 'list',
                                check_exit_code=True)
        LOG.debug('get_fsid: out %s', out)

        lines = out.split('\n')
        for line in lines:
            inf = line.split()
            if fslabel in line and fslabel == inf[1]:
                LOG.debug('get_fsid: %s', line)
                return inf[0]

        LOG.warning(_LW('get_fsid: %(out)s -- No info for %(fslabel)s'),
                    {'out': out, 'fslabel': fslabel})
        return 0

    def _get_targets(self, cmd, ip0, user, pw, evsid, tgtalias=None):
        """Get the target list of an EVS.

        Get the target list of an EVS. Optionally can return the target
        list of a specific target.
        """

        LOG.debug("Getting target list for evs %s, tgtalias: %s.",
                  evsid, tgtalias)

        try:
            out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                    "--evs", evsid, 'iscsi-target', 'list',
                                    check_exit_code=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE('Error getting iSCSI target info '
                          'from EVS %(evs)s.'), {'evs': evsid})
            LOG.debug("_get_targets out: %(out)s, err: %(err)s.",
                      {'out': e.stdout, 'err': e.stderr})
            return []

        tgt_list = []
        if 'No targets' in out:
            LOG.debug("No targets found in EVS %(evsid)s.", {'evsid': evsid})
            return tgt_list

        tgt_raw_list = out.split('Alias')[1:]
        for tgt_raw_info in tgt_raw_list:
            tgt = {}
            tgt['alias'] = tgt_raw_info.split('\n')[0].split(' ').pop()
            tgt['iqn'] = tgt_raw_info.split('\n')[1].split(' ').pop()
            tgt['secret'] = tgt_raw_info.split('\n')[3].split(' ').pop()
            tgt['auth'] = tgt_raw_info.split('\n')[4].split(' ').pop()
            luns = []
            tgt_raw_info = tgt_raw_info.split('\n\n')[1]
            tgt_raw_list = tgt_raw_info.split('\n')[2:]

            for lun_raw_line in tgt_raw_list:
                lun_raw_line = lun_raw_line.strip()
                lun_raw_line = lun_raw_line.split(' ')
                lun = {}
                lun['id'] = lun_raw_line[0]
                lun['name'] = lun_raw_line.pop()
                luns.append(lun)

            tgt['luns'] = luns

            if tgtalias == tgt['alias']:
                return [tgt]

            tgt_list.append(tgt)

        if tgtalias is not None:
            # We tried to find  'tgtalias' but didn't find. Return a empty
            # list.
            LOG.debug("There's no target %(alias)s in EVS %(evsid)s.",
                      {'alias': tgtalias, 'evsid': evsid})
            return []

        LOG.debug("Targets in EVS %(evs)s: %(tgtl)s.",
                  {'evs': evsid, 'tgtl': tgt_list})
        return tgt_list

    def _get_unused_lunid(self, cmd, ip0, user, pw, tgt_info):

        if len(tgt_info['luns']) == 0:
            return 0

        free_lun = 0
        for lun in tgt_info['luns']:
            if int(lun['id']) == free_lun:
                free_lun += 1

            if int(lun['id']) > free_lun:
                # Found a free LUN number
                break

        return free_lun

    def get_nfs_info(self, cmd, ip0, user, pw):
        """Gets information on each NFS export.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :returns: formated string
        """

        out, err = self.run_cmd(cmd, ip0, user, pw,
                                'for-each-evs', '-q',
                                'nfs-export', 'list',
                                check_exit_code=True)

        lines = out.split('\n')
        newout = ""
        export = ""
        path = ""
        for line in lines:
            inf = line.split()
            if 'Export name' in line:
                export = inf[2]
            if 'Export path' in line:
                path = inf[2]
            if 'File system info' in line:
                fs = ""
            if 'File system label' in line:
                fs = inf[3]
            if 'Transfer setting' in line and fs != "":
                fsid = self._get_fsid(cmd, ip0, user, pw, fs)
                evsid = self.get_evs(cmd, ip0, user, pw, fsid)
                ips = self._get_evsips(cmd, ip0, user, pw, evsid)
                newout += "Export: %s Path: %s HDP: %s FSID: %s \
                           EVS: %s IPS: %s\n" \
                           % (export, path, fs, fsid, evsid, ips)
                fs = ""

        LOG.debug('get_nfs_info: %(out)s -- %(err)s',
                  {'out': newout, 'err': err})
        return newout

    def create_lu(self, cmd, ip0, user, pw, hdp, size, name):
        """Creates a new Logical Unit.

        If the operation can not be performed for some reason, utils.execute()
        throws an error and aborts the operation. Used for iSCSI only

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param hdp: data Pool the logical unit will be created
        :param size: Size (Mb) of the new logical unit
        :param name: name of the logical unit
        :returns: formated string with 'LUN %d HDP: %d size: %s MB, is
                  successfully created'
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-lu', 'add', "-e",
                                name, hdp,
                                '/.cinder/' + name + '.iscsi',
                                size + 'M',
                                check_exit_code=True)

        out = "LUN %s HDP: %s size: %s MB, is successfully created" \
              % (name, hdp, size)

        LOG.debug('create_lu: %s.', out)
        return out

    def delete_lu(self, cmd, ip0, user, pw, hdp, lun):
        """Delete an logical unit. Used for iSCSI only

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param hdp: data Pool of the logical unit
        :param lun: id of the logical unit being deleted
        :returns: formated string 'Logical unit deleted successfully.'
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-lu', 'del', '-d',
                                '-f', lun,
                                check_exit_code=True)

        LOG.debug('delete_lu: %(out)s -- %(err)s.', {'out': out, 'err': err})
        return out

    def create_dup(self, cmd, ip0, user, pw, src_lun, hdp, size, name):
        """Clones a volume

        Clone primitive used to support all iSCSI snapshot/cloning functions.
        Used for iSCSI only.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param hdp: data Pool of the logical unit
        :param src_lun: id of the logical unit being deleted
        :param size: size of the LU being cloned. Only for logging purposes
        :returns: formated string
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-lu', 'clone', '-e',
                                src_lun, name,
                                '/.cinder/' + name + '.iscsi',
                                check_exit_code=True)

        out = "LUN %s HDP: %s size: %s MB, is successfully created" \
              % (name, hdp, size)

        LOG.debug('create_dup: %(out)s -- %(err)s.', {'out': out, 'err': err})
        return out

    def file_clone(self, cmd, ip0, user, pw, fslabel, src, name):
        """Clones NFS files to a new one named 'name'

        Clone primitive used to support all NFS snapshot/cloning functions.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param fslabel:  file system label of the new file
        :param src: source file
        :param name: target path of the new created file
        :returns: formated string
        """

        _fsid = self._get_fsid(cmd, ip0, user, pw, fslabel)
        _evsid = self.get_evs(cmd, ip0, user, pw, _fsid)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'file-clone-create', '-f', fslabel,
                                src, name,
                                check_exit_code=True)

        out = "LUN %s HDP: %s Clone: %s -> %s" % (name, _fsid, src, name)

        LOG.debug('file_clone: %(out)s -- %(err)s.', {'out': out, 'err': err})
        return out

    def extend_vol(self, cmd, ip0, user, pw, hdp, lun, new_size, name):
        """Extend a iSCSI volume.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param hdp: data Pool of the logical unit
        :param lun: id of the logical unit being extended
        :param new_size: new size of the LU
        :param name: formated string
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-lu', 'expand',
                                name, new_size + 'M',
                                check_exit_code=True)

        out = ("LUN: %s successfully extended to %s MB" % (name, new_size))

        LOG.debug('extend_vol: %s.', out)
        return out

    @utils.retry(putils.ProcessExecutionError, retries=HNAS_SSC_RETRIES,
                 wait_random=True)
    def add_iscsi_conn(self, cmd, ip0, user, pw, lun_name, hdp,
                       port, tgtalias, initiator):
        """Setup the lun on on the specified target port

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param lun_name: id of the logical unit being extended
        :param hdp: data pool of the logical unit
        :param port: iSCSI port
        :param tgtalias: iSCSI qualified name
        :param initiator: initiator address
        """

        LOG.debug('Adding %(lun)s to %(tgt)s returns %(tgt)s.',
                  {'lun': lun_name, 'tgt': tgtalias})
        found, lunid, tgt = self.check_lu(cmd, ip0, user, pw, lun_name, hdp)
        evsid = self.get_evs(cmd, ip0, user, pw, hdp)

        if found:
            conn = (int(lunid), lun_name, initiator, int(lunid), tgt['iqn'],
                    int(lunid), hdp, port)
            out = ("H-LUN: %d mapped LUN: %s, iSCSI Initiator: %s "
                   "@ index: %d, and Target: %s @ index %d is "
                   "successfully paired  @ CTL: %s, Port: %s.") % conn
        else:
            tgt = self._get_targets(cmd, ip0, user, pw, evsid, tgtalias)
            lunid = self._get_unused_lunid(cmd, ip0, user, pw, tgt[0])

            out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                    "--evs", evsid,
                                    'iscsi-target', 'addlu',
                                    tgtalias, lun_name, six.text_type(lunid),
                                    check_exit_code=True)

            conn = (int(lunid), lun_name, initiator, int(lunid), tgt[0]['iqn'],
                    int(lunid), hdp, port)
            out = ("H-LUN: %d mapped LUN: %s, iSCSI Initiator: %s "
                   "@ index: %d, and Target: %s @ index %d is "
                   "successfully paired  @ CTL: %s, Port: %s.") % conn

        LOG.debug('add_iscsi_conn: returns %s.', out)
        return out

    def del_iscsi_conn(self, cmd, ip0, user, pw, evsid, iqn, hlun):
        """Remove the lun on on the specified target port

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param evsid: EVSID for the file system
        :param iqn: iSCSI qualified name
        :param hlun: logical unit id
        :return: formated string
        """

        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", evsid,
                                'iscsi-target', 'list', iqn,
                                check_exit_code=True)

        lines = out.split('\n')
        out = ("H-LUN: %d already deleted from target %s" % (int(hlun), iqn))
        # see if lun is already detached
        for line in lines:
            if line.startswith('  '):
                lunline = line.split()[0]
                if lunline[0].isdigit() and lunline == hlun:
                    out = ""
                    break

        if out != "":
            # hlun wasn't found
            LOG.info(_LI('del_iscsi_conn: hlun not found %s.'), out)
            return out

        # remove the LU from the target
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", evsid,
                                'iscsi-target', 'dellu',
                                '-f', iqn, hlun,
                                check_exit_code=True)

        out = "H-LUN: %d successfully deleted from target %s" \
              % (int(hlun), iqn)

        LOG.debug('del_iscsi_conn: %s.', out)
        return out

    def get_targetiqn(self, cmd, ip0, user, pw, targetalias, hdp, secret):
        """Obtain the targets full iqn

        Returns the target's full iqn rather than its alias.
        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param targetalias: alias of the target
        :param hdp: data pool of the logical unit
        :param secret: CHAP secret of the target
        :return: string with full IQN
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-target', 'list', targetalias,
                                check_exit_code=True)

        if "does not exist" in out:
            if secret == "":
                secret = '""'
                out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                        "--evs", _evsid,
                                        'iscsi-target', 'add',
                                        targetalias, secret,
                                        check_exit_code=True)
            else:
                out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                        "--evs", _evsid,
                                        'iscsi-target', 'add',
                                        targetalias, secret,
                                        check_exit_code=True)
            if "success" in out:
                return targetalias

        lines = out.split('\n')
        # returns the first iqn
        for line in lines:
            if 'Alias' in line:
                fulliqn = line.split()[2]
                return fulliqn

    def set_targetsecret(self, cmd, ip0, user, pw, targetalias, hdp, secret):
        """Sets the chap secret for the specified target.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param targetalias: alias of the target
        :param hdp: data pool of the logical unit
        :param secret: CHAP secret of the target
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-target', 'list',
                                targetalias,
                                check_exit_code=False)

        if "does not exist" in out:
            out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                    "--evs", _evsid,
                                    'iscsi-target', 'add',
                                    targetalias, secret,
                                    check_exit_code=True)
        else:
            LOG.info(_LI('targetlist: %s'), targetalias)
            out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                    "--evs", _evsid,
                                    'iscsi-target', 'mod',
                                    '-s', secret, '-a', 'enable',
                                    targetalias,
                                    check_exit_code=True)

    def get_targetsecret(self, cmd, ip0, user, pw, targetalias, hdp):
        """Returns the chap secret for the specified target.

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param targetalias: alias of the target
        :param hdp: data pool of the logical unit
        :return secret: CHAP secret of the target
        """

        _evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context",
                                "--evs", _evsid,
                                'iscsi-target', 'list', targetalias,
                                check_exit_code=True)

        enabled = ""
        secret = ""
        lines = out.split('\n')
        for line in lines:
            if 'Secret' in line:
                if len(line.split()) > 2:
                    secret = line.split()[2]
            if 'Authentication' in line:
                enabled = line.split()[2]

        if enabled == 'Enabled':
            return secret
        else:
            return ""

    def check_target(self, cmd, ip0, user, pw, hdp, target_alias):
        """Checks if a given target exists and gets its info

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param hdp: pool name used
        :param target_alias: alias of the target
        :return True if target exists
        :return list with the target info
        """

        LOG.debug("Checking if target %(tgt)s exists.", {'tgt': target_alias})
        evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        tgt_list = self._get_targets(cmd, ip0, user, pw, evsid)

        for tgt in tgt_list:
            if tgt['alias'] == target_alias:
                attached_luns = len(tgt['luns'])
                LOG.debug("Target %(tgt)s has %(lun)s volumes.",
                          {'tgt': target_alias, 'lun': attached_luns})
                return True, tgt

        LOG.debug("Target %(tgt)s does not exist.", {'tgt': target_alias})
        return False, None

    def check_lu(self, cmd, ip0, user, pw, volume_name, hdp):
        """Checks if a given LUN is already mapped

        :param cmd: ssc command name
        :param ip0: string IP address of controller
        :param user: string user authentication for array
        :param pw: string password authentication for array
        :param volume_name: number of the LUN
        :param hdp: storage pool of the LUN
        :return True if the lun is attached
        :return the LUN id
        :return Info related to the target
        """

        LOG.debug("Checking if vol %s (hdp: %s) is attached.",
                  volume_name, hdp)
        evsid = self.get_evs(cmd, ip0, user, pw, hdp)
        tgt_list = self._get_targets(cmd, ip0, user, pw, evsid)

        for tgt in tgt_list:
            if len(tgt['luns']) == 0:
                continue

            for lun in tgt['luns']:
                lunid = lun['id']
                lunname = lun['name']
                if lunname[:29] == volume_name[:29]:
                    LOG.debug("LUN %(lun)s attached on %(lunid)s, "
                              "target: %(tgt)s.",
                              {'lun': volume_name, 'lunid': lunid, 'tgt': tgt})
                    return True, lunid, tgt

        LOG.debug("LUN %(lun)s not attached.", {'lun': volume_name})
        return False, 0, None

    def get_existing_lu_info(self, cmd, ip0, user, pw, fslabel, lun):
        """Returns the information for the specified Logical Unit.

        Returns the information of an existing Logical Unit on HNAS, according
        to the name provided.

        :param cmd:     the command that will be run on SMU
        :param ip0:     string IP address of controller
        :param user:    string user authentication for array
        :param pw:      string password authentication for array
        :param fslabel: label of the file system
        :param lun:     label of the logical unit
        """

        evs = self.get_evs(cmd, ip0, user, pw, fslabel)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context", "--evs",
                                evs, 'iscsi-lu', 'list', lun)

        return out

    def rename_existing_lu(self, cmd, ip0, user, pw, fslabel,
                           new_name, vol_name):
        """Renames the specified Logical Unit.

         Renames an existing Logical Unit on HNAS according to the new name
         provided.

        :param cmd:      command that will be run on SMU
        :param ip0:      string IP address of controller
        :param user:     string user authentication for array
        :param pw:       string password authentication for array
        :param fslabel:  label of the file system
        :param new_name: new name to the existing volume
        :param vol_name: current name of the existing volume
        """
        evs = self.get_evs(cmd, ip0, user, pw, fslabel)
        out, err = self.run_cmd(cmd, ip0, user, pw, "console-context", "--evs",
                                evs, "iscsi-lu", "mod", "-n", new_name,
                                vol_name)

        return out
