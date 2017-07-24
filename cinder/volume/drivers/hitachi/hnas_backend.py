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

from cinder import exception
from cinder.i18n import _
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

        .. code:: python

          storage_version={
              'mac': HNAS MAC ID,
              'model': HNAS model,
              'version': the software version,
              'hardware': the hardware version,
              'serial': HNAS serial number
          }

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

        .. code:: python

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

        .. code:: python

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

        fs_info['provisioned_capacity'] = 0

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
            LOG.error("Can't find file %(file)s in FS %(label)s",
                      {'file': src, 'label': fs_label})
            msg = _('FS label: %(fs_label)s') % {'fs_label': fs_label}
            raise exception.InvalidParameterValue(err=msg)

        self._run_cmd("console-context", "--evs", fs['evsid'],
                      'file-clone-create', '-f', fs_label, src, name)
        LOG.debug('file_clone: fs:%(fs_label)s %(src)s/src: -> %(name)s/dst',
                  {'fs_label': fs_label, 'src': src, 'name': name})

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
                             aren't clones. If False, only an error message
                             is logged.
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
