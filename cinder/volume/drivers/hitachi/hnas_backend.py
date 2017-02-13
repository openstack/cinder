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

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import units
import six

from cinder.i18n import _, _LE
from cinder import exception
from cinder import ssh_utils
from cinder import utils

LOG = logging.getLogger("cinder.volume.driver")
HNAS_SSC_RETRIES = 5


class HNASSSHBackend(object):
    def __init__(self, backend_opts):

        self.mgmt_ip0 = backend_opts.get('mgmt_ip0')
        self.hnas_cmd = backend_opts.get('ssc_cmd', 'ssc')
        self.cluster_admin_ip0 = backend_opts.get('cluster_admin_ip0')
        self.ssh_port = backend_opts.get('ssh_port', '22')
        self.ssh_username = backend_opts.get('username')
        self.ssh_pwd = backend_opts.get('password')
        self.ssh_private_key = backend_opts.get('ssh_private_key')
        self.storage_version = None
        self.sshpool = None
        self.fslist = {}
        self.tgt_list = {}

    @utils.retry(exceptions=exception.HNASConnError, retries=HNAS_SSC_RETRIES,
                 wait_random=True)
    def _run_cmd(self, *args, **kwargs):
        """Runs a command on SMU using SSH.

        :returns: stdout and stderr of the command
        """
        if self.cluster_admin_ip0 is None:
            # Connect to SMU through SSH and run ssc locally
            args = (self.hnas_cmd, 'localhost') + args
        else:
            args = (self.hnas_cmd, '--smuauth', self.cluster_admin_ip0) + args

        utils.check_ssh_injection(args)
        command = ' '.join(args)
        command = command.replace('"', '\\"')

        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(ip=self.mgmt_ip0,
                                             port=int(self.ssh_port),
                                             conn_timeout=None,
                                             login=self.ssh_username,
                                             password=self.ssh_pwd,
                                             privatekey=self.ssh_private_key)

        with self.sshpool.item() as ssh:
            try:
                out, err = putils.ssh_execute(ssh, command,
                                              check_exit_code=True)
                LOG.debug("command %(cmd)s result: out = "
                          "%(out)s - err = %(err)s",
                          {'cmd': self.hnas_cmd, 'out': out, 'err': err})
                return out, err
            except putils.ProcessExecutionError as e:
                if 'Failed to establish SSC connection' in e.stderr:
                    msg = _("Failed to establish SSC connection!")
                    LOG.exception(msg)
                    raise exception.HNASConnError(msg)
                elif 'Connection reset' in e.stderr:
                    msg = _("HNAS connection reset!")
                    LOG.exception(msg)
                    raise exception.HNASConnError(msg)
                else:
                    raise

    def get_version(self):
        """Gets version information from the storage unit.

        :returns: dictionary with HNAS information
        storage_version={
            'mac': HNAS MAC ID,
            'model': HNAS model,
            'version': the software version,
            'hardware': the hardware version,
            'serial': HNAS serial number}
        """
        if not self.storage_version:
            version_info = {}
            out, err = self._run_cmd("cluster-getmac")
            mac = out.split(':')[1].strip()
            version_info['mac'] = mac

            out, err = self._run_cmd("ver")
            split_out = out.split('\n')

            model = split_out[1].split(':')[1].strip()
            version = split_out[3].split()[1]
            hardware = split_out[5].split(':')[1].strip()
            serial = split_out[12].split()[2]

            version_info['model'] = model
            version_info['version'] = version
            version_info['hardware'] = hardware
            version_info['serial'] = serial

            self.storage_version = version_info

        LOG.debug("version_info: %(info)s", {'info': self.storage_version})
        return self.storage_version

    def get_evs_info(self):
        """Gets the IP addresses of all EVSs in HNAS.

        :returns: dictionary with EVS information
        evs_info={
            <IP1>: {evs_number: number identifying the EVS1 on HNAS},
            <IP2>: {evs_number: number identifying the EVS2 on HNAS},
            ...
        }
        """
        evs_info = {}
        out, err = self._run_cmd("evsipaddr", "-l")

        out = out.split('\n')
        for line in out:
            if 'evs' in line and 'admin' not in line:
                ip = line.split()[3].strip()
                evs_info[ip] = {}
                evs_info[ip]['evs_number'] = line.split()[1].strip()

        return evs_info

    def get_fs_info(self, fs_label):
        """Gets the information of a given FS.

        :param fs_label: Label of the filesystem
        :returns: dictionary with FS information
        fs_info={
            'id': a Logical Unit ID,
            'label': a Logical Unit name,
            'evs_id': the ID of the EVS in which the filesystem is created
            (not present if there is a single EVS),
            'total_size': the total size of the FS (in GB),
            'used_size': the size that is already used (in GB),
            'available_size': the free space (in GB)
            }
        """
        def _convert_size(param):
            size = float(param) * units.Mi
            return six.text_type(size)

        fs_info = {}
        single_evs = True
        id, lbl, evs, t_sz, u_sz, a_sz = 0, 1, 2, 3, 5, 12
        t_sz_unit, u_sz_unit, a_sz_unit = 4, 6, 13

        out, err = self._run_cmd("df", "-af", fs_label)

        invalid_outs = ['Not mounted', 'Not determined', 'not found']

        for problem in invalid_outs:
            if problem in out:
                return {}

        if 'EVS' in out:
            single_evs = False

        fs_data = out.split('\n')[3].split()

        # Getting only the desired values from the output. If there is a single
        # EVS, its ID is not shown in the output and we have to decrease the
        # indexes to get the right values.
        fs_info['id'] = fs_data[id]
        fs_info['label'] = fs_data[lbl]

        if not single_evs:
            fs_info['evs_id'] = fs_data[evs]

        fs_info['total_size'] = (
            (fs_data[t_sz]) if not single_evs else fs_data[t_sz - 1])
        fs_info['used_size'] = (
            fs_data[u_sz] if not single_evs else fs_data[u_sz - 1])
        fs_info['available_size'] = (
            fs_data[a_sz] if not single_evs else fs_data[a_sz - 1])

        # Converting the sizes if necessary.
        if not single_evs:
            if fs_data[t_sz_unit] == 'TB':
                fs_info['total_size'] = _convert_size(fs_info['total_size'])
            if fs_data[u_sz_unit] == 'TB':
                fs_info['used_size'] = _convert_size(fs_info['used_size'])
            if fs_data[a_sz_unit] == 'TB':
                fs_info['available_size'] = _convert_size(
                    fs_info['available_size'])
        else:
            if fs_data[t_sz_unit - 1] == 'TB':
                fs_info['total_size'] = _convert_size(fs_info['total_size'])
            if fs_data[u_sz_unit - 1] == 'TB':
                fs_info['used_size'] = _convert_size(fs_info['used_size'])
            if fs_data[a_sz_unit - 1] == 'TB':
                fs_info['available_size'] = _convert_size(
                    fs_info['available_size'])

        # Get the iSCSI LUs in the FS
        evs_id = self.get_evs(fs_label)
        out, err = self._run_cmd('console-context', '--evs', evs_id,
                                 'iscsi-lu', 'list')
        all_lus = [self._parse_lu_info(lu_raw)
                   for lu_raw in out.split('\n\n')[:-1]]

        provisioned_cap = 0
        for lu in all_lus:
            if lu['filesystem'] == fs_label:
                provisioned_cap += lu['size']

        fs_info['provisioned_capacity'] = provisioned_cap

        LOG.debug("File system info of %(fs)s (sizes in GB): %(info)s.",
                  {'fs': fs_label, 'info': fs_info})

        return fs_info

    def get_evs(self, fs_label):
        """Gets the EVS ID for the named filesystem.

        :param fs_label: The filesystem label related to the EVS required
        :returns: EVS ID of the filesystem
        """
        if not self.fslist:
            self._get_fs_list()

        # When the FS is found in the list of known FS, returns the EVS ID
        for key in self.fslist:
            if fs_label == self.fslist[key]['label']:
                LOG.debug("EVS ID for fs %(fs)s: %(id)s.",
                          {'fs': fs_label, 'id': self.fslist[key]['evsid']})
                return self.fslist[key]['evsid']
        LOG.debug("Can't find EVS ID for fs %(fs)s.", {'fs': fs_label})

    def _get_targets(self, evs_id, tgt_alias=None, refresh=False):
        """Gets the target list of an EVS.

        Gets the target list of an EVS. Optionally can return the information
        of a specific target.
        :returns: Target list or Target info (EVS ID) or empty list
        """
        LOG.debug("Getting target list for evs %(evs)s, tgtalias: %(tgt)s.",
                  {'evs': evs_id, 'tgt': tgt_alias})

        if (refresh or
                evs_id not in self.tgt_list.keys() or
                tgt_alias is not None):
            self.tgt_list[evs_id] = []
            out, err = self._run_cmd("console-context", "--evs", evs_id,
                                     'iscsi-target', 'list')

            if 'No targets' in out:
                LOG.debug("No targets found in EVS %(evsid)s.",
                          {'evsid': evs_id})
                return self.tgt_list[evs_id]

            tgt_raw_list = out.split('Alias')[1:]
            for tgt_raw_info in tgt_raw_list:
                tgt = {}
                tgt['alias'] = tgt_raw_info.split('\n')[0].split(' ').pop()
                tgt['iqn'] = tgt_raw_info.split('\n')[1].split(' ').pop()
                tgt['secret'] = tgt_raw_info.split('\n')[3].split(' ').pop()
                tgt['auth'] = tgt_raw_info.split('\n')[4].split(' ').pop()
                lus = []
                tgt_raw_info = tgt_raw_info.split('\n\n')[1]
                tgt_raw_list = tgt_raw_info.split('\n')[2:]

                for lu_raw_line in tgt_raw_list:
                    lu_raw_line = lu_raw_line.strip()
                    lu_raw_line = lu_raw_line.split(' ')
                    lu = {}
                    lu['id'] = lu_raw_line[0]
                    lu['name'] = lu_raw_line.pop()
                    lus.append(lu)

                tgt['lus'] = lus

                if tgt_alias == tgt['alias']:
                    return tgt

                self.tgt_list[evs_id].append(tgt)

        if tgt_alias is not None:
            # We tried to find  'tgtalias' but didn't find. Return a empty
            # list.
            LOG.debug("There's no target %(alias)s in EVS %(evsid)s.",
                      {'alias': tgt_alias, 'evsid': evs_id})
            return []

        LOG.debug("Targets in EVS %(evs)s: %(tgtl)s.",
                  {'evs': evs_id, 'tgtl': self.tgt_list[evs_id]})

        return self.tgt_list[evs_id]

    def _get_unused_luid(self, tgt_info):
        """Gets a free logical unit id number to be used.

        :param tgt_info: dictionary with the target information
        :returns: a free logical unit id number
        """
        if len(tgt_info['lus']) == 0:
            return 0

        free_lu = 0
        for lu in tgt_info['lus']:
            if int(lu['id']) == free_lu:
                free_lu += 1

            if int(lu['id']) > free_lu:
                # Found a free LU number
                break

        LOG.debug("Found the free LU ID: %(lu)s.", {'lu': free_lu})

        return free_lu

    def create_lu(self, fs_label, size, lu_name):
        """Creates a new Logical Unit.

        If the operation can not be performed for some reason, utils.execute()
        throws an error and aborts the operation. Used for iSCSI only

        :param fs_label: data pool the Logical Unit will be created
        :param size: Size (GB) of the new Logical Unit
        :param lu_name: name of the Logical Unit
        """
        evs_id = self.get_evs(fs_label)

        self._run_cmd("console-context", "--evs", evs_id, 'iscsi-lu', 'add',
                      "-e", lu_name, fs_label, '/.cinder/' + lu_name +
                      '.iscsi', size + 'G')

        LOG.debug('Created %(size)s GB LU: %(name)s FS: %(fs)s.',
                  {'size': size, 'name': lu_name, 'fs': fs_label})

    def delete_lu(self, fs_label, lu_name):
        """Deletes a Logical Unit.

        :param fs_label: data pool of the Logical Unit
        :param lu_name: id of the Logical Unit being deleted
        """
        evs_id = self.get_evs(fs_label)
        self._run_cmd("console-context", "--evs", evs_id, 'iscsi-lu', 'del',
                      '-d', '-f', lu_name)

        LOG.debug('LU %(lu)s deleted.', {'lu': lu_name})

    def file_clone(self, fs_label, src, name):
        """Clones NFS files to a new one named 'name'.

        Clone primitive used to support all NFS snapshot/cloning functions.

        :param fs_label:  file system label of the new file
        :param src: source file
        :param name: target path of the new created file
        """
        fs_list = self._get_fs_list()
        fs = fs_list.get(fs_label)
        if not fs:
            LOG.error(_LE("Can't find file %(file)s in FS %(label)s"),
                      {'file': src, 'label': fs_label})
            msg = _('FS label: %(fs_label)s') % {'fs_label': fs_label}
            raise exception.InvalidParameterValue(err=msg)

        self._run_cmd("console-context", "--evs", fs['evsid'],
                      'file-clone-create', '-f', fs_label, src, name)
        LOG.debug('file_clone: fs:%(fs_label)s %(src)s/src: -> %(name)s/dst',
                  {'fs_label': fs_label, 'src': src, 'name': name})

    def extend_lu(self, fs_label, new_size, lu_name):
        """Extends an iSCSI volume.

        :param fs_label: data pool of the Logical Unit
        :param new_size: new size of the Logical Unit
        :param lu_name: name of the Logical Unit
        """
        evs_id = self.get_evs(fs_label)
        size = six.text_type(new_size)
        self._run_cmd("console-context", "--evs", evs_id, 'iscsi-lu', 'expand',
                      lu_name, size + 'G')

        LOG.debug('LU %(lu)s extended.', {'lu': lu_name})

    @utils.retry(putils.ProcessExecutionError, retries=HNAS_SSC_RETRIES,
                 wait_random=True)
    def add_iscsi_conn(self, lu_name, fs_label, port, tgt_alias, initiator):
        """Sets up the Logical Unit on the specified target port.

        :param lu_name: id of the Logical Unit being extended
        :param fs_label: data pool of the Logical Unit
        :param port: iSCSI port
        :param tgt_alias: iSCSI qualified name
        :param initiator: initiator address
        :returns: dictionary (conn_info) with the connection information
        conn_info={
            'lu': Logical Unit ID,
            'iqn': iSCSI qualified name,
            'lu_name': Logical Unit name,
            'initiator': iSCSI initiator,
            'fs_label': File system to connect,
            'port': Port to make the iSCSI connection
             }
        """
        conn_info = {}
        lu_info = self.check_lu(lu_name, fs_label)
        _evs_id = self.get_evs(fs_label)

        if not lu_info['mapped']:
            tgt = self._get_targets(_evs_id, tgt_alias)
            lu_id = self._get_unused_luid(tgt)
            conn_info['lu_id'] = lu_id
            conn_info['iqn'] = tgt['iqn']

            # In busy situations where 2 or more instances of the driver are
            # trying to map an LU, 2 hosts can retrieve the same 'lu_id',
            # and try to map the LU in the same LUN. To handle that we
            # capture the ProcessExecutionError exception, backoff for some
            # seconds and retry it.
            self._run_cmd("console-context", "--evs", _evs_id, 'iscsi-target',
                          'addlu', tgt_alias, lu_name, six.text_type(lu_id))
        else:
            conn_info['lu_id'] = lu_info['id']
            conn_info['iqn'] = lu_info['tgt']['iqn']

        conn_info['lu_name'] = lu_name
        conn_info['initiator'] = initiator
        conn_info['fs'] = fs_label
        conn_info['port'] = port

        LOG.debug('add_iscsi_conn: LU %(lu)s added to %(tgt)s.',
                  {'lu': lu_name, 'tgt': tgt_alias})
        LOG.debug('conn_info: %(conn_info)s', {'conn_info': conn_info})

        return conn_info

    def del_iscsi_conn(self, evs_id, iqn, lu_id):
        """Removes the Logical Unit on the specified target port.

        :param evs_id: EVSID for the file system
        :param iqn: iSCSI qualified name
        :param lu_id: Logical Unit id
        """
        found = False
        out, err = self._run_cmd("console-context", "--evs", evs_id,
                                 'iscsi-target', 'list', iqn)

        # see if LU is already detached
        lines = out.split('\n')
        for line in lines:
            if line.startswith('  '):
                lu_line = line.split()[0]
                if lu_line[0].isdigit() and lu_line == lu_id:
                    found = True
                    break

        # LU wasn't found
        if not found:
            LOG.debug("del_iscsi_conn: LU already deleted from "
                      "target %(iqn)s", {'lu': lu_id, 'iqn': iqn})
            return

        # remove the LU from the target
        self._run_cmd("console-context", "--evs", evs_id, 'iscsi-target',
                      'dellu', '-f', iqn, lu_id)

        LOG.debug("del_iscsi_conn: LU: %(lu)s successfully deleted from "
                  "target %(iqn)s", {'lu': lu_id, 'iqn': iqn})

    def get_target_iqn(self, tgt_alias, fs_label):
        """Obtains the target full iqn

        Returns the target's full iqn rather than its alias.

        :param tgt_alias: alias of the target
        :param fs_label: data pool of the Logical Unit
        :returns: string with full IQN
        """
        _evs_id = self.get_evs(fs_label)
        out, err = self._run_cmd("console-context", "--evs", _evs_id,
                                 'iscsi-target', 'list', tgt_alias)

        lines = out.split('\n')
        # returns the first iqn
        for line in lines:
            if 'Globally unique name' in line:
                full_iqn = line.split()[3]
                LOG.debug('get_target_iqn: %(iqn)s', {'iqn': full_iqn})
                return full_iqn
        LOG.debug("Could not find iqn for alias %(alias)s on fs %(fs_label)s",
                  {'alias': tgt_alias, 'fs_label': fs_label})

    def set_target_secret(self, targetalias, fs_label, secret):
        """Sets the chap secret for the specified target.

        :param targetalias: alias of the target
        :param fs_label: data pool of the Logical Unit
        :param secret: CHAP secret of the target
        """
        _evs_id = self.get_evs(fs_label)
        self._run_cmd("console-context", "--evs", _evs_id, 'iscsi-target',
                      'mod', '-s', secret, '-a', 'enable', targetalias)

        LOG.debug("set_target_secret: Secret set on target %(tgt)s.",
                  {'tgt': targetalias})

    def get_target_secret(self, targetalias, fs_label):
        """Gets the chap secret for the specified target.

        :param targetalias: alias of the target
        :param fs_label: data pool of the Logical Unit
        :returns: CHAP secret of the target
        """
        _evs_id = self.get_evs(fs_label)
        out, err = self._run_cmd("console-context", "--evs", _evs_id,
                                 'iscsi-target', 'list', targetalias)

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

    def check_target(self, fs_label, target_alias):
        """Checks if a given target exists and gets its info.

        :param fs_label: pool name used
        :param target_alias: alias of the target
        :returns: dictionary (tgt_info)
        tgt_info={
            'alias': The alias of the target,
            'found': boolean to inform if the target was found or not,
            'tgt': dictionary with the target information
            }
        """
        tgt_info = {}
        _evs_id = self.get_evs(fs_label)
        _tgt_list = self._get_targets(_evs_id)

        for tgt in _tgt_list:
            if tgt['alias'] == target_alias:
                attached_lus = len(tgt['lus'])
                tgt_info['found'] = True
                tgt_info['tgt'] = tgt
                LOG.debug("Target %(tgt)s has %(lu)s volumes.",
                          {'tgt': target_alias, 'lu': attached_lus})
                return tgt_info

        tgt_info['found'] = False
        tgt_info['tgt'] = None

        LOG.debug("check_target: Target %(tgt)s does not exist.",
                  {'tgt': target_alias})

        return tgt_info

    def check_lu(self, vol_name, fs_label):
        """Checks if a given LU is already mapped

        :param vol_name: name of the LU
        :param fs_label: storage pool of the LU
        :returns: dictionary (lu_info) with LU information
        lu_info={
            'mapped': LU state (mapped or not),
            'id': ID of the LU,
            'tgt': the iSCSI target alias
            }
        """
        lu_info = {}
        evs_id = self.get_evs(fs_label)
        tgt_list = self._get_targets(evs_id, refresh=True)

        for tgt in tgt_list:
            if len(tgt['lus']) == 0:
                continue

            for lu in tgt['lus']:
                lu_id = lu['id']
                lu_name = lu['name']
                if lu_name[:29] == vol_name[:29]:
                    lu_info['mapped'] = True
                    lu_info['id'] = lu_id
                    lu_info['tgt'] = tgt
                    LOG.debug("LU %(lu)s attached on %(luid)s, "
                              "target: %(tgt)s.",
                              {'lu': vol_name, 'luid': lu_id, 'tgt': tgt})
                    return lu_info

        lu_info['mapped'] = False
        lu_info['id'] = 0
        lu_info['tgt'] = None

        LOG.debug("LU %(lu)s not attached. lu_info: %(lu_info)s",
                  {'lu': vol_name, 'lu_info': lu_info})

        return lu_info

    def _parse_lu_info(self, output):
        lu_info = {}
        if 'does not exist.' not in output:
            aux = output.split('\n')
            lu_info['name'] = aux[0].split(':')[1].strip()
            lu_info['comment'] = aux[1].split(':')[1].strip()
            lu_info['path'] = aux[2].split(':')[1].strip()
            lu_info['size'] = aux[3].split(':')[1].strip()
            lu_info['filesystem'] = aux[4].split(':')[1].strip()
            lu_info['fs_mounted'] = aux[5].split(':')[1].strip()
            lu_info['lu_mounted'] = aux[6].split(':')[1].strip()

            if 'TB' in lu_info['size']:
                sz_convert = float(lu_info['size'].split()[0]) * units.Ki
                lu_info['size'] = sz_convert
            elif 'MB' in lu_info['size']:
                sz_convert = float(lu_info['size'].split()[0]) / units.Ki
                lu_info['size'] = sz_convert
            else:
                lu_info['size'] = float(lu_info['size'].split()[0])

        return lu_info

    def get_existing_lu_info(self, lu_name, fs_label=None, evs_id=None):
        """Gets the information for the specified Logical Unit.

        Returns the information of an existing Logical Unit on HNAS, according
        to the name provided.

        :param lu_name: label of the Logical Unit
        :param fs_label: label of the file system
        :param evs_id: ID of the EVS where the LU is located
        :returns: dictionary (lu_info) with LU information
        lu_info={
            'name': A Logical Unit name,
            'comment': A comment about the LU, not used for Cinder,
            'path': Path to LU inside filesystem,
            'size': Logical Unit size returned always in GB (volume size),
            'filesystem': File system where the Logical Unit was created,
            'fs_mounted': Information about the state of file system
            (mounted or not),
            'lu_mounted': Information about the state of Logical Unit
            (mounted or not)
            }
        """

        if evs_id is None:
            evs_id = self.get_evs(fs_label)

        lu_name = "'{}'".format(lu_name)
        out, err = self._run_cmd("console-context", "--evs", evs_id,
                                 'iscsi-lu', 'list', lu_name)
        lu_info = self._parse_lu_info(out)
        LOG.debug('get_existing_lu_info: LU info: %(lu)s', {'lu': lu_info})

        return lu_info

    def rename_existing_lu(self, fs_label, vol_name, new_name):
        """Renames the specified Logical Unit.

         Renames an existing Logical Unit on HNAS according to the new name
         provided.

        :param fs_label: label of the file system
        :param vol_name: current name of the existing volume
        :param new_name: new name to the existing volume
        """

        new_name = "'{}'".format(new_name)
        evs_id = self.get_evs(fs_label)
        self._run_cmd("console-context", "--evs", evs_id, "iscsi-lu", "mod",
                      "-n", new_name, vol_name)

        LOG.debug('rename_existing_lu_info:'
                  'LU %(old)s was renamed to %(new)s',
                  {'old': vol_name, 'new': new_name})

    def _get_fs_list(self):
        """Gets a list of file systems configured on the backend.

        :returns: a list with the Filesystems configured on HNAS
        """
        if not self.fslist:
            fslist_out, err = self._run_cmd('evsfs', 'list')
            list_raw = fslist_out.split('\n')[3:-2]

            for fs_raw in list_raw:
                fs = {}

                fs_raw = fs_raw.split()
                fs['id'] = fs_raw[0]
                fs['label'] = fs_raw[1]
                fs['permid'] = fs_raw[2]
                fs['evsid'] = fs_raw[3]
                fs['evslabel'] = fs_raw[4]
                self.fslist[fs['label']] = fs

        return self.fslist

    def _get_evs_list(self):
        """Gets a list of EVS configured on the backend.

        :returns: a list of the EVS configured on HNAS
        """
        evslist_out, err = self._run_cmd('evs', 'list')

        evslist = {}
        idx = 0
        for evs_raw in evslist_out.split('\n'):
            idx += 1
            if 'Service' in evs_raw and 'Online' in evs_raw:
                evs = {}
                evs_line = evs_raw.split()
                evs['node'] = evs_line[0]
                evs['id'] = evs_line[1]
                evs['label'] = evs_line[3]
                evs['ips'] = []
                evs['ips'].append(evs_line[6])
                # Each EVS can have a list of IPs that are displayed in the
                # next lines of the evslist_out. We need to check if the next
                # lines is a new EVS entry or and IP of this current EVS.
                for evs_ip_raw in evslist_out.split('\n')[idx:]:
                    if 'Service' in evs_ip_raw or not evs_ip_raw.split():
                        break
                    ip = evs_ip_raw.split()[0]
                    evs['ips'].append(ip)

                evslist[evs['label']] = evs

        return evslist

    def get_export_list(self):
        """Gets information on each NFS export.

        :returns: a list of the exports configured on HNAS
        """
        nfs_export_out, _ = self._run_cmd('for-each-evs', '-q', 'nfs-export',
                                          'list')
        fs_list = self._get_fs_list()
        evs_list = self._get_evs_list()

        export_list = []

        for export_raw_data in nfs_export_out.split("Export name:")[1:]:
            export_info = {}
            export_data = export_raw_data.split('\n')

            export_info['name'] = export_data[0].strip()
            export_info['path'] = export_data[1].split(':')[1].strip()
            export_info['fs'] = export_data[2].split(':')[1].strip()

            if "*** not available ***" in export_raw_data:
                export_info['size'] = -1
                export_info['free'] = -1
            else:
                evslbl = fs_list[export_info['fs']]['evslabel']
                export_info['evs'] = evs_list[evslbl]['ips']

                size = export_data[3].split(':')[1].strip().split()[0]
                multiplier = export_data[3].split(':')[1].strip().split()[1]
                if multiplier == 'TB':
                    export_info['size'] = float(size) * units.Ki
                else:
                    export_info['size'] = float(size)

                free = export_data[4].split(':')[1].strip().split()[0]
                fmultiplier = export_data[4].split(':')[1].strip().split()[1]
                if fmultiplier == 'TB':
                    export_info['free'] = float(free) * units.Ki
                else:
                    export_info['free'] = float(free)

            export_list.append(export_info)

        LOG.debug("get_export_list: %(exp_list)s", {'exp_list': export_list})
        return export_list

    def create_cloned_lu(self, src_lu, fs_label, clone_name):
        """Clones a Logical Unit

        Clone primitive used to support all iSCSI snapshot/cloning functions.

        :param src_lu: id of the Logical Unit being deleted
        :param fs_label: data pool of the Logical Unit
        :param clone_name: name of the snapshot
        """
        evs_id = self.get_evs(fs_label)
        self._run_cmd("console-context", "--evs", evs_id, 'iscsi-lu', 'clone',
                      '-e', src_lu, clone_name,
                      '/.cinder/' + clone_name + '.iscsi')

        LOG.debug('LU %(lu)s cloned.', {'lu': clone_name})

    def create_target(self, tgt_alias, fs_label, secret):
        """Creates a new iSCSI target

        :param tgt_alias: the alias with which the target will be created
        :param fs_label: the label of the file system to create the target
        :param secret: the secret for authentication of the target
        """
        _evs_id = self.get_evs(fs_label)
        self._run_cmd("console-context", "--evs", _evs_id,
                      'iscsi-target', 'add', tgt_alias, secret)

        self._get_targets(_evs_id, refresh=True)
        LOG.debug("create_target: alias: %(alias)s  fs_label: %(fs_label)s",
                  {'alias': tgt_alias, 'fs_label': fs_label})

    def _get_file_handler(self, volume_path, _evs_id, fs_label,
                          raise_except):

        try:
            out, err = self._run_cmd("console-context", "--evs", _evs_id,
                                     'file-clone-stat', '-f', fs_label,
                                     volume_path)
        except putils.ProcessExecutionError as e:
            if 'File is not a clone' in e.stderr and raise_except:
                msg = (_("%s is not a clone!") % volume_path)
                raise exception.ManageExistingInvalidReference(
                    existing_ref=volume_path, reason=msg)
            else:
                return

        lines = out.split('\n')
        filehandle_list = []

        for line in lines:
            if "SnapshotFile:" in line and "FileHandle" in line:
                item = line.split(':')
                handler = item[1][:-1].replace(' FileHandle[', "")
                filehandle_list.append(handler)
                LOG.debug("Volume handler found: %(fh)s. Adding to list...",
                          {'fh': handler})

        return filehandle_list

    def get_cloned_file_relatives(self, file_path, fs_label,
                                  raise_except=False):
        """Gets the files related to a clone

        :param file_path: path of the cloned file
        :param fs_label: filesystem of the cloned file
        :param raise_except: If True exception will be raised for files that
        aren't clones. If False, only an error message is logged.
        :returns: list with names of the related files
        """
        relatives = []

        _evs_id = self.get_evs(fs_label)

        file_handler_list = self._get_file_handler(file_path, _evs_id,
                                                   fs_label, raise_except)

        if file_handler_list:
            for file_handler in file_handler_list:
                out, err = self._run_cmd('console-context', '--evs', _evs_id,
                                         'file-clone-stat-snapshot-file', '-f',
                                         fs_label, file_handler)

                results = out.split('\n')

                for value in results:
                    if 'Clone:' in value and file_path not in value:
                        relative = value.split(':')[1]
                        relatives.append(relative)
        else:
            LOG.debug("File %(path)s is not a clone.", {
                'path': file_path})

        return relatives

    def check_snapshot_parent(self, volume_path, snap_name, fs_label):
        """Check if a volume is the snapshot source

        :param volume_path: path of the volume
        :param snap_name: name of the snapshot
        :param fs_label: filesystem label
        :return: True if the volume is the snapshot's source or False otherwise
        """
        lines = self.get_cloned_file_relatives(volume_path, fs_label, True)

        for line in lines:
            if snap_name in line:
                LOG.debug("Snapshot %(snap)s found in children list from "
                          "%(vol)s!", {'snap': snap_name,
                                       'vol': volume_path})
                return True

        LOG.debug("Snapshot %(snap)s was not found in children list from "
                  "%(vol)s, probably it is not the parent!",
                  {'snap': snap_name, 'vol': volume_path})
        return False

    def get_export_path(self, export, fs_label):
        """Gets the path of an export on HNAS

        :param export: the export's name
        :param fs_label: the filesystem name
        :returns: string of the export's path
        """
        evs_id = self.get_evs(fs_label)
        out, err = self._run_cmd("console-context", "--evs", evs_id,
                                 'nfs-export', 'list', export)

        lines = out.split('\n')

        for line in lines:
            if 'Export path:' in line:
                return line.split('Export path:')[1].strip()
